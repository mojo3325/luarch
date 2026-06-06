from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass
import statistics

import bpy

from .. import metadata, naming, presets
from ..services import build_scheduler, cleanup, collections as collection_service
from ..utils.random import rng_from_seed
from .building import (
    create_build_finalize_sequence,
    create_build_preview_sequence,
    exact_spec_key_for_spec,
)
from .building_layout import estimate_footprint_extents
from .specs import building_spec_from_mapping, normalized_payload_from_mapping


VariationSignature = tuple[str, str, str, str, str, str, str, str]

_VARIANT_PROBE_COUNT = 6
_RECENT_PRESET_WINDOW = 6
_RECENT_SIGNATURE_WINDOW = 8
_CONTENT_POOL_CEILING = {
    "ANY": 6,
    "RESIDENTIAL": 5,
    "COMMERCIAL": 1,
    "INDUSTRIAL": 0,
}


@dataclass(frozen=True)
class DistrictIdentity:
    block_id: str
    seed: int
    rows: int
    columns: int
    lot_type: str
    origin: tuple[float, float, float]


@dataclass(frozen=True)
class DistrictSlotPlan:
    slot_id: str
    row: int
    column: int
    payload: dict
    spec: object
    exact_spec_key: str
    origin: tuple[float, float, float]
    yaw: float


@dataclass(frozen=True)
class DistrictPlan:
    identity: DistrictIdentity
    resolved_eligible_preset_pool: tuple[str, ...]
    slots: tuple[DistrictSlotPlan, ...]
    preview_order: tuple[str, ...]
    finalize_order: tuple[str, ...]
    planned_preset_frequency: tuple[tuple[str, int], ...]
    planned_repeated_neighbor_signatures: int
    planned_family_spread_count: int
    planned_office_midrise_share: float


_DISTRICT_RUNTIME_METRICS: dict[str, object] = {}


def reset_district_runtime_metrics() -> None:
    _DISTRICT_RUNTIME_METRICS.clear()


def district_runtime_snapshot() -> dict[str, object]:
    return dict(_DISTRICT_RUNTIME_METRICS)


def _variation_signature(payload: dict) -> VariationSignature:
    return (
        payload.get("preset_id", ""),
        payload.get("facade_family", ""),
        payload.get("facade_mode", ""),
        payload.get("roof_mode", ""),
        payload.get("massing_profile", ""),
        payload.get("balcony_mode", ""),
        payload.get("ground_floor_tactical_profile", ""),
        payload.get("door_profile", ""),
    )


def _blocked_signatures(
    placed_signatures: dict[tuple[int, int], VariationSignature],
    row: int,
    col: int,
) -> set[tuple[str, str, str, str, str, str, str, str]]:
    blocked: set[VariationSignature] = set()
    for row_delta in range(-2, 3):
        for col_delta in range(-2, 3):
            distance = abs(row_delta) + abs(col_delta)
            if distance == 0 or distance > 2:
                continue
            candidate_row = row + row_delta
            candidate_col = col + col_delta
            if candidate_row < 0 or candidate_col < 0:
                continue
            if candidate_row > row or (candidate_row == row and candidate_col >= col):
                continue
            signature = placed_signatures.get((candidate_row, candidate_col))
            if signature is not None:
                blocked.add(signature)
    return blocked


def _previous_neighbors(row: int, col: int, *, max_distance: int = 2) -> list[tuple[int, int, int]]:
    neighbors: list[tuple[int, int, int]] = []
    for row_delta in range(-max_distance, max_distance + 1):
        for col_delta in range(-max_distance, max_distance + 1):
            distance = abs(row_delta) + abs(col_delta)
            if distance == 0 or distance > max_distance:
                continue
            candidate_row = row + row_delta
            candidate_col = col + col_delta
            if candidate_row < 0 or candidate_col < 0:
                continue
            if candidate_row > row or (candidate_row == row and candidate_col >= col):
                continue
            neighbors.append((candidate_row, candidate_col, distance))
    neighbors.sort(key=lambda item: (item[2], item[0], item[1]))
    return neighbors


def _stable_text_hash(value: str) -> int:
    total = 0
    for index, char in enumerate(str(value or "")):
        total += (index + 1) * ord(char)
    return total


def _slot_seed(seed: int, row: int, col: int) -> int:
    return int(seed + row * 100 + col)


def _slot_tiebreak(seed: int, row: int, col: int, token: str) -> float:
    tie_rng = rng_from_seed(seed + row * 409 + col * 1301 + _stable_text_hash(token) * 17)
    return float(tie_rng.random())


def _signature_overlap(left: VariationSignature, right: VariationSignature) -> int:
    return sum(1 for left_value, right_value in zip(left, right) if left_value and left_value == right_value)


def _spec_height(spec) -> float:
    return (
        float(getattr(spec, "floor_count", 0)) * float(getattr(spec, "floor_height", 0.0))
        + float(getattr(spec, "parapet_height", 0.0))
    )


def _clamp_invalid_risk_payload(payload: dict) -> dict:
    compacted = normalized_payload_from_mapping(presets.clamp_invalid_risk_payload(dict(payload)))
    compacted["preset_id"] = str(payload.get("preset_id", compacted.get("preset_id", "")))
    compacted["seed"] = int(payload.get("seed", compacted.get("seed", 0)))
    return compacted


def _profile_payload_for_family(preset_id: str, *, seed: int) -> dict:
    profile_seed = int(seed + _stable_text_hash(preset_id) * 29 + 811)
    return _clamp_invalid_risk_payload(presets.build_block_payload(preset_id, profile_seed))


def _family_profile(payload: dict) -> dict[str, object]:
    spec = building_spec_from_mapping(payload, building_id=None, origin=(0.0, 0.0, 0.0))
    return {
        "height": _spec_height(spec),
        "massing_profile": str(getattr(spec, "massing_profile", "")),
    }


def _score_family_candidate(
    *,
    preset_id: str,
    row: int,
    col: int,
    assigned_families: dict[tuple[int, int], str],
    assigned_profiles: dict[tuple[int, int], dict[str, object]],
    recent_presets: list[str],
    family_profile: dict[str, object],
    family_usage: dict[str, int],
    target_per_family: float,
) -> float:
    score = 0.0
    usage = int(family_usage.get(preset_id, 0))

    if usage == 0:
        score += 4.5
    score -= float(usage) * 3.25
    score += max(0.0, target_per_family - float(usage)) * 0.8

    for index, recent in enumerate(reversed(recent_presets[-_RECENT_PRESET_WINDOW:]), start=1):
        if recent != preset_id:
            continue
        score -= float(_RECENT_PRESET_WINDOW - index + 1) * 1.75

    candidate_height = float(family_profile.get("height", 0.0))
    candidate_massing = str(family_profile.get("massing_profile", ""))
    nearby_heights: list[float] = []
    nearby_massing_matches = 0

    for neighbor_row, neighbor_col, distance in _previous_neighbors(row, col, max_distance=2):
        neighbor_family = assigned_families.get((neighbor_row, neighbor_col), "")
        if neighbor_family == preset_id:
            score -= 4.0 / float(distance)
        neighbor_profile = assigned_profiles.get((neighbor_row, neighbor_col))
        if neighbor_profile is None:
            continue
        nearby_height = float(neighbor_profile.get("height", 0.0))
        nearby_heights.append(nearby_height)
        if str(neighbor_profile.get("massing_profile", "")) == candidate_massing:
            nearby_massing_matches += 1

    if nearby_heights:
        average_height = sum(nearby_heights) / float(len(nearby_heights))
        height_delta = abs(candidate_height - average_height)
        score += min(3.5, height_delta * 0.45)
        if height_delta < 1.2:
            score -= 1.0
    score -= float(nearby_massing_matches) * 0.9
    return score


def _allocate_preset_families(
    *,
    rows: int,
    columns: int,
    resolved_pool: tuple[str, ...],
    block_seed: int,
) -> list[list[str]]:
    if not resolved_pool:
        raise ValueError("Cannot allocate district families with an empty eligible pool.")

    family_profiles = {
        preset_id: _family_profile(_profile_payload_for_family(preset_id, seed=block_seed))
        for preset_id in resolved_pool
    }
    family_usage = {preset_id: 0 for preset_id in resolved_pool}
    assigned_families: dict[tuple[int, int], str] = {}
    assigned_profiles: dict[tuple[int, int], dict[str, object]] = {}
    recent_presets: list[str] = []
    target_per_family = (float(rows) * float(columns)) / float(len(resolved_pool))

    allocation: list[list[str]] = []
    for row in range(rows):
        allocation_row: list[str] = []
        for col in range(columns):
            best_preset = resolved_pool[0]
            best_score = float("-inf")
            best_tie = float("-inf")
            for preset_id in resolved_pool:
                score = _score_family_candidate(
                    preset_id=preset_id,
                    row=row,
                    col=col,
                    assigned_families=assigned_families,
                    assigned_profiles=assigned_profiles,
                    recent_presets=recent_presets,
                    family_profile=family_profiles[preset_id],
                    family_usage=family_usage,
                    target_per_family=target_per_family,
                )
                tie_break = _slot_tiebreak(block_seed, row, col, f"family:{preset_id}")
                if score > best_score + 1e-9 or (abs(score - best_score) <= 1e-9 and tie_break > best_tie):
                    best_preset = preset_id
                    best_score = score
                    best_tie = tie_break
            assigned_families[(row, col)] = best_preset
            assigned_profiles[(row, col)] = family_profiles[best_preset]
            family_usage[best_preset] += 1
            recent_presets.append(best_preset)
            allocation_row.append(best_preset)
        allocation.append(allocation_row)
    return allocation


def _score_variant_candidate(
    *,
    row: int,
    col: int,
    signature: VariationSignature,
    spec,
    placed_signatures: dict[tuple[int, int], VariationSignature],
    placed_specs: dict[tuple[int, int], object],
    recent_signatures: list[VariationSignature],
) -> float:
    score = 0.0
    nearby_heights: list[float] = []
    nearby_massing_matches = 0
    candidate_height = _spec_height(spec)
    candidate_massing = str(getattr(spec, "massing_profile", ""))

    blocked = _blocked_signatures(placed_signatures, row, col)
    if signature in blocked:
        score -= 10.0

    for neighbor_row, neighbor_col, distance in _previous_neighbors(row, col, max_distance=2):
        neighbor_signature = placed_signatures.get((neighbor_row, neighbor_col))
        if neighbor_signature is not None:
            overlap = _signature_overlap(signature, neighbor_signature)
            if overlap > 0:
                proximity_weight = 1.0 + (2 - distance) * 0.65
                score -= float(overlap) * proximity_weight
                if signature == neighbor_signature:
                    score -= 3.5 / float(distance)
        neighbor_spec = placed_specs.get((neighbor_row, neighbor_col))
        if neighbor_spec is None:
            continue
        nearby_height = _spec_height(neighbor_spec)
        nearby_heights.append(nearby_height)
        if str(getattr(neighbor_spec, "massing_profile", "")) == candidate_massing:
            nearby_massing_matches += 1

    for index, recent_signature in enumerate(reversed(recent_signatures[-_RECENT_SIGNATURE_WINDOW:]), start=1):
        if recent_signature != signature:
            continue
        score -= float(_RECENT_SIGNATURE_WINDOW - index + 1) * 0.9

    if nearby_heights:
        average_height = sum(nearby_heights) / float(len(nearby_heights))
        height_delta = abs(candidate_height - average_height)
        score += min(3.5, height_delta * 0.5)
        if height_delta < 0.9:
            score -= 1.1
    score -= float(nearby_massing_matches) * 1.0
    return score


def _pick_payload_for_family(
    preset_id: str,
    *,
    seed_base: int,
    row: int,
    col: int,
    placed_signatures: dict[tuple[int, int], VariationSignature],
    placed_specs: dict[tuple[int, int], object],
    recent_signatures: list[VariationSignature],
) -> tuple[dict, object, VariationSignature]:
    family_seed_offset = _stable_text_hash(preset_id) * 113
    best_payload: dict | None = None
    best_spec = None
    best_signature: VariationSignature | None = None
    best_score = float("-inf")
    best_tie = float("-inf")

    for variant_index in range(_VARIANT_PROBE_COUNT):
        candidate_seed = int(seed_base + family_seed_offset + variant_index * 10000)
        payload = _clamp_invalid_risk_payload(presets.build_block_payload(preset_id, candidate_seed))
        spec = building_spec_from_mapping(payload, building_id=None, origin=(0.0, 0.0, 0.0))
        signature = _variation_signature(payload)
        score = _score_variant_candidate(
            row=row,
            col=col,
            signature=signature,
            spec=spec,
            placed_signatures=placed_signatures,
            placed_specs=placed_specs,
            recent_signatures=recent_signatures,
        )
        tie_break = _slot_tiebreak(seed_base, row, col, f"variant:{preset_id}:{variant_index}")
        if score > best_score + 1e-9 or (abs(score - best_score) <= 1e-9 and tie_break > best_tie):
            best_payload = dict(payload)
            best_spec = spec
            best_signature = signature
            best_score = score
            best_tie = tie_break

    if best_payload is None or best_spec is None or best_signature is None:
        raise RuntimeError(f"Failed to probe district variants for preset family '{preset_id}'.")
    return best_payload, best_spec, best_signature


def _district_yaw(seed: int, row: int, col: int) -> float:
    yaw_rng = rng_from_seed(seed + row * 101 + col * 1009)
    return yaw_rng.choice((0.0, math.pi / 2, math.pi, math.pi * 1.5))


def _jittered_gap(base_gap: float, seed: int, axis_key: str, index: int) -> float:
    gap_rng = rng_from_seed(seed + (20011 if axis_key == "x" else 40009) + index * 131)
    jitter = gap_rng.uniform(-base_gap * 0.18, base_gap * 0.18)
    return max(1.0, round(base_gap + jitter, 3))


def _rotated_footprint_extents(
    spec,
    *,
    yaw: float,
    include_world_scale: bool = False,
) -> tuple[float, float, float, float]:
    left_extent, right_extent, front_extent, back_extent = estimate_footprint_extents(
        spec,
        include_world_scale=include_world_scale,
    )
    cos_yaw = math.cos(float(yaw))
    sin_yaw = math.sin(float(yaw))
    corners = (
        (-float(left_extent), -float(front_extent)),
        (float(right_extent), -float(front_extent)),
        (float(right_extent), float(back_extent)),
        (-float(left_extent), float(back_extent)),
    )
    rotated = [
        (
            local_x * cos_yaw - local_y * sin_yaw,
            local_x * sin_yaw + local_y * cos_yaw,
        )
        for local_x, local_y in corners
    ]
    xs = [point[0] for point in rotated]
    ys = [point[1] for point in rotated]
    return (
        abs(min(xs)),
        abs(max(xs)),
        abs(min(ys)),
        abs(max(ys)),
    )


def compute_grid_axis_extents(
    extent_grid: list[list[tuple[float, float, float, float]]],
) -> tuple[list[float], list[float], list[float], list[float]]:
    rows = len(extent_grid)
    cols = len(extent_grid[0]) if rows else 0
    if rows <= 0 or cols <= 0:
        return [], [], [], []
    col_left = [max(extent_grid[row][col][0] for row in range(rows)) for col in range(cols)]
    col_right = [max(extent_grid[row][col][1] for row in range(rows)) for col in range(cols)]
    row_front = [max(extent_grid[row][col][2] for col in range(cols)) for row in range(rows)]
    row_back = [max(extent_grid[row][col][3] for col in range(cols)) for row in range(rows)]
    return col_left, col_right, row_front, row_back


def solve_axis_centers(
    *,
    negative_extents: list[float],
    positive_extents: list[float],
    gaps: list[float],
    anchor_index: int,
    anchor_center: float,
) -> list[float]:
    count = len(negative_extents)
    if count != len(positive_extents):
        raise ValueError("Axis extent vectors must have identical lengths.")
    if count == 0:
        return []
    if len(gaps) != max(0, count - 1):
        raise ValueError("Gap count must be exactly one less than axis slot count.")
    if anchor_index < 0 or anchor_index >= count:
        raise ValueError("Anchor index is outside the solved axis range.")

    centers = [0.0] * count
    centers[anchor_index] = float(anchor_center)

    for index in range(anchor_index + 1, count):
        centers[index] = (
            centers[index - 1]
            + float(positive_extents[index - 1])
            + float(gaps[index - 1])
            + float(negative_extents[index])
        )
    for index in range(anchor_index - 1, -1, -1):
        centers[index] = (
            centers[index + 1]
            - float(positive_extents[index])
            - float(gaps[index])
            - float(negative_extents[index + 1])
        )
    return centers


def solve_grid_centers(
    extent_grid: list[list[tuple[float, float, float, float]]],
    *,
    col_gaps: list[float],
    row_gaps: list[float],
    origin_xy: tuple[float, float],
    anchor_col: int = 0,
    anchor_row: int = 0,
) -> tuple[list[float], list[float]]:
    col_left, col_right, row_front, row_back = compute_grid_axis_extents(extent_grid)
    col_centers = solve_axis_centers(
        negative_extents=col_left,
        positive_extents=col_right,
        gaps=col_gaps,
        anchor_index=anchor_col,
        anchor_center=float(origin_xy[0]),
    )
    row_centers = solve_axis_centers(
        negative_extents=row_back,
        positive_extents=row_front,
        gaps=row_gaps,
        anchor_index=anchor_row,
        anchor_center=float(origin_xy[1]),
    )
    return col_centers, row_centers


def _continue_job(
    *,
    label: str,
    execute,
    dedupe_key: str,
    message: str,
):
    return build_scheduler.JobContinuation(
        label=label,
        execute=execute,
        dedupe_key=dedupe_key,
        replace_dedupe=True,
        message=message,
    )


def _count_repeated_neighbor_signatures(signature_grid: list[list[VariationSignature]]) -> int:
    if not signature_grid:
        return 0
    rows = len(signature_grid)
    columns = len(signature_grid[0])
    repeats = 0
    for row in range(rows):
        for col in range(columns):
            current = signature_grid[row][col]
            if row > 0 and signature_grid[row - 1][col] == current:
                repeats += 1
            if col > 0 and signature_grid[row][col - 1] == current:
                repeats += 1
    return repeats


def plan_block(context) -> DistrictPlan:
    scene = context.scene
    block_settings = scene.tbg_block
    base_origin = tuple(float(v) for v in scene.cursor.location)
    rows = int(block_settings.rows)
    columns = int(block_settings.columns)

    if rows <= 0 or columns <= 0:
        raise ValueError("District rows/columns must be positive.")

    requested = [item.strip() for item in block_settings.allowed_presets.split(",") if item.strip()]
    eligible_pool = presets.block_eligible_ids(block_settings.lot_type)
    explicit_allowed = [preset_id for preset_id in requested if preset_id in eligible_pool]
    resolved_pool = tuple(explicit_allowed or eligible_pool)
    if not resolved_pool:
        raise ValueError(f"No block-eligible presets are available for lot type '{block_settings.lot_type}'.")

    family_grid = _allocate_preset_families(
        rows=rows,
        columns=columns,
        resolved_pool=resolved_pool,
        block_seed=int(block_settings.seed),
    )
    placed_signatures: dict[tuple[int, int], VariationSignature] = {}
    placed_specs: dict[tuple[int, int], object] = {}
    recent_signatures: list[VariationSignature] = []
    payload_grid: list[list[dict]] = []
    spec_grid: list[list[object]] = []
    yaw_grid: list[list[float]] = []
    signature_grid: list[list[VariationSignature]] = []
    for row in range(rows):
        payload_row: list[dict] = []
        spec_row: list[object] = []
        yaw_row: list[float] = []
        signature_row: list[VariationSignature] = []
        for col in range(columns):
            seed = _slot_seed(int(block_settings.seed), row, col)
            chosen_family = family_grid[row][col]
            payload, spec, signature = _pick_payload_for_family(
                chosen_family,
                seed_base=seed,
                row=row,
                col=col,
                placed_signatures=placed_signatures,
                placed_specs=placed_specs,
                recent_signatures=recent_signatures,
            )
            placed_signatures[(row, col)] = signature
            placed_specs[(row, col)] = spec
            recent_signatures.append(signature)
            payload_row.append(payload)
            spec_row.append(spec)
            yaw_row.append(_district_yaw(int(block_settings.seed), row, col))
            signature_row.append(signature)
        payload_grid.append(payload_row)
        spec_grid.append(spec_row)
        yaw_grid.append(yaw_row)
        signature_grid.append(signature_row)
    extent_grid = [
        [
            _rotated_footprint_extents(spec_grid[row][col], yaw=yaw_grid[row][col], include_world_scale=True)
            for col in range(columns)
        ]
        for row in range(rows)
    ]

    col_gaps = [
        _jittered_gap(float(block_settings.spacing_x), int(block_settings.seed), "x", col)
        for col in range(1, columns)
    ]
    row_gaps = [
        _jittered_gap(float(block_settings.spacing_y), int(block_settings.seed), "y", row)
        for row in range(1, rows)
    ]

    col_centers, row_centers = solve_grid_centers(
        extent_grid,
        col_gaps=col_gaps,
        row_gaps=row_gaps,
        origin_xy=(base_origin[0], base_origin[1]),
        anchor_col=0,
        anchor_row=0,
    )

    slots: list[DistrictSlotPlan] = []
    for row in range(rows):
        for col in range(columns):
            origin = (col_centers[col], row_centers[row], base_origin[2])
            payload = dict(payload_grid[row][col])
            slot_spec = building_spec_from_mapping(payload, building_id=None, origin=origin)
            slots.append(
                DistrictSlotPlan(
                    slot_id=f"r{row:02d}c{col:02d}",
                    row=row,
                    column=col,
                    payload=payload,
                    spec=slot_spec,
                    exact_spec_key=exact_spec_key_for_spec(slot_spec),
                    origin=origin,
                    yaw=yaw_grid[row][col],
                )
            )
    planned_preset_frequency = Counter(str(slot.payload.get("preset_id", "")) for slot in slots)
    planned_family_order = tuple(family for row in family_grid for family in row)
    planned_office_midrise_count = sum(1 for family in planned_family_order if family in {"office_block", "apartment_midrise"})
    preview_order = tuple(slot.slot_id for slot in slots)
    return DistrictPlan(
        identity=DistrictIdentity(
            block_id=naming.next_block_id(scene),
            seed=int(block_settings.seed),
            rows=rows,
            columns=columns,
            lot_type=str(block_settings.lot_type),
            origin=base_origin,
        ),
        resolved_eligible_preset_pool=resolved_pool,
        slots=tuple(slots),
        preview_order=preview_order,
        finalize_order=tuple(preview_order),
        planned_preset_frequency=tuple(sorted(planned_preset_frequency.items(), key=lambda item: item[0])),
        planned_repeated_neighbor_signatures=_count_repeated_neighbor_signatures(signature_grid),
        planned_family_spread_count=sum(1 for count in planned_preset_frequency.values() if int(count) > 0),
        planned_office_midrise_share=(
            float(planned_office_midrise_count) / float(len(planned_family_order))
            if planned_family_order
            else 0.0
        ),
    )


def plan_block_exact_duplicates(
    context,
    *,
    preset_id: str,
    duplicate_seed: int | None = None,
) -> DistrictPlan:
    scene = context.scene
    block_settings = scene.tbg_block
    rows = int(block_settings.rows)
    columns = int(block_settings.columns)
    if rows <= 0 or columns <= 0:
        raise ValueError("District rows/columns must be positive.")

    base_origin = tuple(float(v) for v in scene.cursor.location)
    resolved_pool = tuple(presets.block_eligible_ids(block_settings.lot_type))
    if str(preset_id) not in resolved_pool:
        raise ValueError(
            f"Preset '{preset_id}' is not eligible for lot type '{block_settings.lot_type}'."
        )

    seed_value = int(duplicate_seed) if duplicate_seed is not None else int(block_settings.seed)
    duplicate_payload = _clamp_invalid_risk_payload(
        presets.build_block_payload(str(preset_id), seed_value)
    )
    duplicate_payload["preset_id"] = str(preset_id)
    duplicate_payload["seed"] = int(seed_value)
    signature = _variation_signature(duplicate_payload)

    prototype_spec = building_spec_from_mapping(duplicate_payload, building_id=None, origin=(0.0, 0.0, 0.0))
    yaw_grid = [
        [_district_yaw(int(block_settings.seed), row, col) for col in range(columns)]
        for row in range(rows)
    ]
    extent_grid = [
        [
            _rotated_footprint_extents(prototype_spec, yaw=yaw_grid[row][col], include_world_scale=True)
            for col in range(columns)
        ]
        for row in range(rows)
    ]

    col_gaps = [
        _jittered_gap(float(block_settings.spacing_x), int(block_settings.seed), "x", col)
        for col in range(1, columns)
    ]
    row_gaps = [
        _jittered_gap(float(block_settings.spacing_y), int(block_settings.seed), "y", row)
        for row in range(1, rows)
    ]
    col_centers, row_centers = solve_grid_centers(
        extent_grid,
        col_gaps=col_gaps,
        row_gaps=row_gaps,
        origin_xy=(base_origin[0], base_origin[1]),
        anchor_col=0,
        anchor_row=0,
    )

    slots: list[DistrictSlotPlan] = []
    for row in range(rows):
        for col in range(columns):
            origin = (col_centers[col], row_centers[row], base_origin[2])
            payload = dict(duplicate_payload)
            slot_spec = building_spec_from_mapping(payload, building_id=None, origin=origin)
            slots.append(
                DistrictSlotPlan(
                    slot_id=f"r{row:02d}c{col:02d}",
                    row=row,
                    column=col,
                    payload=payload,
                    spec=slot_spec,
                    exact_spec_key=exact_spec_key_for_spec(slot_spec),
                    origin=origin,
                    yaw=yaw_grid[row][col],
                )
            )

    preview_order = tuple(slot.slot_id for slot in slots)
    signature_grid = [[signature for _ in range(columns)] for _ in range(rows)]
    return DistrictPlan(
        identity=DistrictIdentity(
            block_id=naming.next_block_id(scene),
            seed=int(block_settings.seed),
            rows=rows,
            columns=columns,
            lot_type=str(block_settings.lot_type),
            origin=base_origin,
        ),
        resolved_eligible_preset_pool=(str(preset_id),),
        slots=tuple(slots),
        preview_order=preview_order,
        finalize_order=tuple(preview_order),
        planned_preset_frequency=((str(preset_id), len(slots)),),
        planned_repeated_neighbor_signatures=_count_repeated_neighbor_signatures(signature_grid),
        planned_family_spread_count=1 if slots else 0,
        planned_office_midrise_share=(
            1.0
            if str(preset_id) in {"office_block", "apartment_midrise"} and slots
            else 0.0
        ),
    )


class _DistrictRuntimeJob:
    def __init__(self, plan: DistrictPlan, *, scene_name: str, block_collection_name: str):
        self._plan = plan
        self._scene_name = str(scene_name or "")
        self._block_collection_name = str(block_collection_name or "")
        self._slots_by_id = {slot.slot_id: slot for slot in plan.slots}
        self._slot_order = tuple(plan.preview_order)
        self._slot_root_names: dict[str, str] = {}
        self._slot_index = 0
        self._preview_completed_slots = 0
        self._finalize_completed_slots = 0
        self._active_slot_id = ""
        self._active_stage = ""
        self._active_sequence = None
        self._active_finalize_started_at: float | None = None
        self._phase = "rolling"
        self._started_at = time.perf_counter()
        self._label = f"generate-block:{plan.identity.block_id}"
        self._dedupe_key = f"generate-block:{plan.identity.block_id}"
        self._exact_spec_finalize_samples: dict[str, list[float]] = {}
        self._exact_spec_reuse_hits = 0
        self._exact_spec_reuse_misses = 0
        exact_spec_counts = Counter(slot.exact_spec_key for slot in plan.slots if str(slot.exact_spec_key))
        duplicate_slot_count = sum(max(0, int(count) - 1) for count in exact_spec_counts.values())
        _DISTRICT_RUNTIME_METRICS.clear()
        _DISTRICT_RUNTIME_METRICS.update(
            {
                "block_id": plan.identity.block_id,
                "rows": int(plan.identity.rows),
                "columns": int(plan.identity.columns),
                "status": "queued",
                "runtime_shape": "rolling_preview_finalize",
                "planned_slot_count": len(plan.slots),
                "preview_completed_slots": 0,
                "finalize_completed_slots": 0,
                "first_visible_root_ms": None,
                "first_finalized_root_ms": None,
                "half_finalized_slots_ms": None,
                "district_complete_ms": None,
                "preview_wave_complete_ms": None,
                "finalize_wave_complete_ms": None,
                "preview_order": tuple(plan.preview_order),
                "finalize_order": tuple(plan.finalize_order),
                "resolved_eligible_preset_pool": tuple(plan.resolved_eligible_preset_pool),
                "planned_preset_frequency": tuple(plan.planned_preset_frequency),
                "planned_family_spread_count": int(plan.planned_family_spread_count),
                "planned_repeated_neighbor_signatures": int(plan.planned_repeated_neighbor_signatures),
                "planned_office_midrise_share": float(plan.planned_office_midrise_share),
                "planned_exact_spec_unique_count": int(len(exact_spec_counts)),
                "planned_exact_spec_duplicate_slot_count": int(duplicate_slot_count),
                "content_pool_ceiling": dict(_CONTENT_POOL_CEILING),
                "exact_spec_reuse_hits": 0,
                "exact_spec_reuse_misses": 0,
                "exact_spec_first_slot_ms": None,
                "exact_spec_repeat_slot_ms": None,
                "exact_spec_repeat_to_first_ratio": None,
                "error": "",
            }
        )

    def _elapsed_ms(self) -> float:
        return (time.perf_counter() - self._started_at) * 1000.0

    def _update_metrics(self, **updates) -> None:
        _DISTRICT_RUNTIME_METRICS.update(updates)

    def _mark_failed(self, message: str):
        self._phase = "failed"
        self._update_metrics(status="failed", error=str(message))
        cleanup.prune_empty_generated_collections()
        return False, str(message)

    def _ensure_block_collection(self):
        collection = bpy.data.collections.get(self._block_collection_name)
        if collection is not None:
            return collection
        scene = bpy.data.scenes.get(self._scene_name)
        if scene is None:
            scene = getattr(bpy.context, "scene", None)
        if scene is None:
            raise RuntimeError("District generation scene is no longer available.")
        collection = collection_service.create_block_collection(scene, self._plan.identity.block_id)
        self._block_collection_name = collection.name
        return collection

    def _queue_next(self, message: str):
        return _continue_job(
            label=self._label,
            execute=self.execute,
            dedupe_key=self._dedupe_key,
            message=message,
        )

    def _record_first_visible(self) -> None:
        if _DISTRICT_RUNTIME_METRICS.get("first_visible_root_ms") is not None:
            return
        self._update_metrics(first_visible_root_ms=self._elapsed_ms())

    def _record_finalize_progress(self) -> None:
        if self._finalize_completed_slots <= 0:
            return
        if _DISTRICT_RUNTIME_METRICS.get("first_finalized_root_ms") is None:
            self._update_metrics(first_finalized_root_ms=self._elapsed_ms())
        half_target = int((len(self._slot_order) + 1) // 2)
        if (
            half_target > 0
            and self._finalize_completed_slots >= half_target
            and _DISTRICT_RUNTIME_METRICS.get("half_finalized_slots_ms") is None
        ):
            self._update_metrics(half_finalized_slots_ms=self._elapsed_ms())

    def _refresh_exact_spec_metrics(self) -> None:
        first_samples = [float(samples[0]) for samples in self._exact_spec_finalize_samples.values() if samples]
        repeat_samples = [
            float(sample)
            for samples in self._exact_spec_finalize_samples.values()
            for sample in samples[1:]
        ]
        first_median = statistics.median(first_samples) if first_samples else None
        repeat_median = statistics.median(repeat_samples) if repeat_samples else None
        ratio = None
        if first_median is not None and first_median > 1e-9 and repeat_median is not None:
            ratio = float(repeat_median) / float(first_median)
        self._update_metrics(
            exact_spec_reuse_hits=int(self._exact_spec_reuse_hits),
            exact_spec_reuse_misses=int(self._exact_spec_reuse_misses),
            exact_spec_first_slot_ms=float(first_median) if first_median is not None else None,
            exact_spec_repeat_slot_ms=float(repeat_median) if repeat_median is not None else None,
            exact_spec_repeat_to_first_ratio=float(ratio) if ratio is not None else None,
        )

    def _record_finalize_slot_metrics(self, *, slot: DistrictSlotPlan, sequence, elapsed_ms: float) -> None:
        key = str(getattr(slot, "exact_spec_key", "") or "")
        if key:
            self._exact_spec_finalize_samples.setdefault(key, []).append(float(elapsed_ms))
        if bool(getattr(sequence, "used_exact_spec_reuse", False)):
            self._exact_spec_reuse_hits += 1
        else:
            self._exact_spec_reuse_misses += 1
        self._refresh_exact_spec_metrics()

    def _start_preview_slot(self, slot_id: str) -> None:
        slot = self._slots_by_id[slot_id]
        self._active_slot_id = slot_id
        self._active_stage = "preview"
        self._active_finalize_started_at = None
        self._active_sequence = create_build_preview_sequence(
            bpy.context,
            slot.spec,
            parent_collection=self._ensure_block_collection(),
            suppress_viewport_emit=True,
            enable_exact_spec_reuse=True,
        )
        self._update_metrics(
            status="preview",
            preview_completed_slots=self._preview_completed_slots,
            finalize_completed_slots=self._finalize_completed_slots,
        )

    def _start_finalize_slot(self, slot_id: str) -> DistrictSlotPlan:
        slot = self._slots_by_id[slot_id]
        self._active_finalize_started_at = time.perf_counter()
        root_name = self._slot_root_names.get(slot_id, "")
        root_obj = bpy.data.objects.get(root_name) if root_name else None
        if root_obj is None:
            raise RuntimeError(f"District rolling finalize cannot find preview root for slot {slot.slot_id}.")
        effective_spec_dict = metadata.read_effective_spec_dict(root_obj, allow_legacy_dirty=True)
        effective_spec = building_spec_from_mapping(
            effective_spec_dict or slot.spec.to_dict(),
            building_id=str(root_obj.get("tbg_building_id", "")) or None,
            origin=tuple(root_obj.location),
        )
        self._active_slot_id = slot_id
        self._active_stage = "finalize"
        self._active_sequence = create_build_finalize_sequence(
            bpy.context,
            effective_spec,
            existing_root=root_obj,
            parent_collection=self._ensure_block_collection(),
            suppress_viewport_emit=True,
        )
        self._update_metrics(
            status="finalize",
            preview_completed_slots=self._preview_completed_slots,
            finalize_completed_slots=self._finalize_completed_slots,
        )
        return slot

    def _active_progress_message(self) -> str:
        total = len(self._slot_order)
        ordinal = min(total, self._slot_index + 1)
        if self._active_stage == "finalize":
            return f"Continuing district rolling finalize ({ordinal}/{total})."
        return f"Continuing district rolling preview ({ordinal}/{total})."

    def _complete(self):
        self._phase = "completed"
        self._update_metrics(
            status="completed",
            district_complete_ms=self._elapsed_ms(),
            preview_completed_slots=self._preview_completed_slots,
            finalize_completed_slots=self._finalize_completed_slots,
        )
        cleanup.prune_empty_generated_collections()
        return True, f"Generated block layout {self._plan.identity.block_id}"

    def _advance_rolling(self):
        if self._active_sequence is None and self._slot_index >= len(self._slot_order):
            return self._complete()
        if self._active_sequence is None:
            self._start_preview_slot(self._slot_order[self._slot_index])
        slot = self._slots_by_id[self._active_slot_id]
        try:
            completed = self._active_sequence.step()
        except Exception as exc:
            return self._mark_failed(f"District {self._active_stage or 'runtime'} failed at slot {slot.slot_id}: {exc}")
        if self._active_stage == "preview":
            preview_root = metadata.resolve_root_from_object(self._active_sequence.root_obj) or self._active_sequence.root_obj
            if preview_root is not None:
                self._record_first_visible()

        if not completed:
            return self._queue_next(self._active_progress_message())

        if self._active_stage == "preview":
            active_sequence = self._active_sequence
            preview_root = metadata.resolve_root_from_object(active_sequence.root_obj) or active_sequence.root_obj
            if preview_root is None:
                return self._mark_failed(f"District rolling preview completed without root for slot {slot.slot_id}.")
            self._record_first_visible()
            preview_root.rotation_euler.z = slot.yaw
            self._slot_root_names[slot.slot_id] = preview_root.name
            self._preview_completed_slots += 1
            self._update_metrics(preview_completed_slots=self._preview_completed_slots, status="preview")
            try:
                self._start_finalize_slot(slot.slot_id)
            except Exception as exc:
                return self._mark_failed(str(exc))
            return self._queue_next(self._active_progress_message())

        active_sequence = self._active_sequence
        finalized_root = metadata.resolve_root_from_object(active_sequence.root_obj) or active_sequence.root_obj
        if finalized_root is not None:
            finalized_root.rotation_euler.z = slot.yaw
        if self._active_finalize_started_at is not None:
            slot_elapsed_ms = (time.perf_counter() - self._active_finalize_started_at) * 1000.0
            self._record_finalize_slot_metrics(
                slot=slot,
                sequence=active_sequence,
                elapsed_ms=slot_elapsed_ms,
            )
        self._active_sequence = None
        self._active_slot_id = ""
        self._active_stage = ""
        self._active_finalize_started_at = None
        self._slot_index += 1
        self._finalize_completed_slots += 1
        self._record_finalize_progress()
        self._update_metrics(finalize_completed_slots=self._finalize_completed_slots, status="rolling")
        if self._slot_index >= len(self._slot_order):
            return self._complete()
        return self._queue_next(self._active_progress_message())

    def execute(self):
        if self._phase == "failed":
            return False, str(_DISTRICT_RUNTIME_METRICS.get("error", "District generation failed."))
        if self._phase == "completed":
            return True, f"Generated block layout {self._plan.identity.block_id}"
        return self._advance_rolling()


def enqueue_block_generation(context) -> DistrictPlan:
    cleanup.prune_empty_generated_collections()
    plan = plan_block(context)
    scene = context.scene
    block_collection = collection_service.create_block_collection(scene, plan.identity.block_id)
    runtime = _DistrictRuntimeJob(
        plan,
        scene_name=str(getattr(scene, "name_full", "") or getattr(scene, "name", "")),
        block_collection_name=block_collection.name,
    )
    build_scheduler.enqueue_job(
        label=f"generate-block:{plan.identity.block_id}",
        execute=runtime.execute,
        dedupe_key=f"generate-block:{plan.identity.block_id}",
        replace_dedupe=True,
    )
    return plan


def generate_block(context):
    return enqueue_block_generation(context).identity.block_id
