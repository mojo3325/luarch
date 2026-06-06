from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from .. import constants
from .layout_constants import _STAGE1_IDENTITY_RESET_PRESETS
from .layout_constants import *
from .specs import (
    ROOF_MODE_FLAT,
    ROOF_MODE_TERRACE,
    compact_residential_envelope as _compact_residential_envelope_contract,
    normalized_balcony_mode as _normalized_balcony_mode,
    normalized_roof_mode as _normalized_roof_mode,
    roomy_multi_floor_envelope as _roomy_multi_floor_envelope_contract,
)


@dataclass(frozen=True)
class SpatialFloor:
    floor_index: int
    footprint: tuple[float, float, float, float]
    base_z: float
    ceiling_z: float
    is_traversable: bool
    has_front_door: bool
    has_rear_door: bool


@dataclass(frozen=True)
class RoofRoomVolume:
    terminal_profile: str
    footprint: tuple[float, float, float, float]
    opening_rect: tuple[float, float, float, float] | None
    base_z: float
    height: float
    shell_bucket: str
    door_wall: str
    door_width: float
    door_height: float


@dataclass(frozen=True)
class SpatialPlan:
    floors: tuple[SpatialFloor, ...]
    rear_access: bool
    rear_access_profile: str
    top_terminal_mode: str
    roof_access_enabled: bool
    stair_run_count: int
    transition_floor_index: int | None
    upper_shell_rect: tuple[float, float, float, float] | None
    terrace_open_sides: tuple[str, ...]
    top_arrival_rects: tuple[tuple[float, float, float, float], ...]
    roof_room: RoofRoomVolume | None
    roof_keepout: tuple[float, float, float, float] | None
    service_anchor: ServiceAnchor


TOP_TERMINAL_TOP_FLOOR_ONLY = "TOP_FLOOR_ONLY"
TOP_TERMINAL_PLAYABLE_TOP_ROOM = "PLAYABLE_TOP_ROOM"
TERMINAL_PROFILE_ATTIC_OPEN = "ATTIC_OPEN"
TERMINAL_PROFILE_FULL_ROOM = "FULL_ROOM"
TERMINAL_PROFILE_STAIR_HEAD = "STAIR_HEAD"
REAR_ACCESS_PROFILE_NONE = "NONE"
REAR_ACCESS_PROFILE_SERVICE_DOOR = "SERVICE_DOOR"
REAR_ACCESS_PROFILE_OPEN_BAY = "OPEN_BAY"
REAR_ACCESS_PROFILE_SHELL_ONLY = "SHELL_ONLY"
REAR_ENTRY_STAIR_CLEARANCE_MIN = 0.6
FRONT_ENTRY_STAIR_CLEARANCE_MIN = 0.72


def _resolved_top_terminal_policy(
    spec,
    *,
    transition_floor_index: int | None,
) -> tuple[str, bool, str | None]:
    from .layout_facade_planning import (
        _top_terminal_family_policy_mode,
        _top_terminal_family_terminal_profile,
    )

    preset_id = str(getattr(spec, "preset_id", "")).lower()
    roof_mode = _normalized_roof_mode(getattr(spec, "roof_mode", ROOF_MODE_FLAT))
    top_terminal_mode_requested = _top_terminal_family_policy_mode(spec, roof_mode=roof_mode)
    terminal_profile_requested = _top_terminal_family_terminal_profile(spec, roof_mode=roof_mode)
    roof_access_enabled = (
        top_terminal_mode_requested == TOP_TERMINAL_PLAYABLE_TOP_ROOM
        and bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled)
        and preset_id != "under_construction"
        and transition_floor_index is None
    )
    top_terminal_mode = (
        TOP_TERMINAL_PLAYABLE_TOP_ROOM if roof_access_enabled else TOP_TERMINAL_TOP_FLOOR_ONLY
    )
    terminal_profile = terminal_profile_requested if roof_access_enabled else None
    return top_terminal_mode, roof_access_enabled, terminal_profile


def _rects_almost_equal(
    rect_a: tuple[float, float, float, float],
    rect_b: tuple[float, float, float, float],
    *,
    tolerance: float = 1e-4,
) -> bool:
    return all(abs(float(value_a) - float(value_b)) <= tolerance for value_a, value_b in zip(rect_a, rect_b))


def _roof_room_envelope_footprint(
    spec,
    *,
    terminal_profile: str,
    top_floor_footprint: tuple[float, float, float, float],
    opening_footprint: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    wall_thickness = float(getattr(spec, "wall_thickness", 0.0))
    interior_footprint = _interior_bounds_for_rect(
        top_floor_footprint,
        wall_thickness,
    )
    if (
        interior_footprint[1] - interior_footprint[0] <= 1e-4
        or interior_footprint[3] - interior_footprint[2] <= 1e-4
    ):
        interior_footprint = top_floor_footprint

    if terminal_profile == TERMINAL_PROFILE_FULL_ROOM:
        metrics = _dogleg_metrics(spec)
        opening_x0, opening_x1, opening_y0, opening_y1 = (float(value) for value in opening_footprint)
        opening_width = max(1e-4, opening_x1 - opening_x0)
        opening_depth = max(1e-4, opening_y1 - opening_y0)
        side_pad = max(0.16, min(0.34, wall_thickness * 1.85))
        depth_pad = max(0.24, min(0.56, float(metrics.landing_depth) * 0.38))
        desired_width = opening_width + side_pad * 2
        desired_depth = opening_depth + depth_pad * 2

        room_cx = (opening_x0 + opening_x1) / 2
        room_cy = (opening_y0 + opening_y1) / 2
        room_rect = (
            float(room_cx - desired_width / 2),
            float(room_cx + desired_width / 2),
            float(room_cy - desired_depth / 2),
            float(room_cy + desired_depth / 2),
        )
        clamped_room_rect = _clamp_rect_to_bounds(room_rect, interior_footprint)
        merged = _union_rects((clamped_room_rect, opening_footprint))
        return merged or opening_footprint

    if terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN:
        return interior_footprint

    if terminal_profile == TERMINAL_PROFILE_STAIR_HEAD:
        pad_x = max(0.12, min(0.32, wall_thickness * 1.6))
        pad_y = max(0.16, min(0.4, wall_thickness * 2.0))
        stair_head_rect = (
            float(opening_footprint[0] - pad_x),
            float(opening_footprint[1] + pad_x),
            float(opening_footprint[2] - pad_y),
            float(opening_footprint[3] + pad_y),
        )
        x0 = max(float(stair_head_rect[0]), float(interior_footprint[0]))
        x1 = min(float(stair_head_rect[1]), float(interior_footprint[1]))
        y0 = max(float(stair_head_rect[2]), float(interior_footprint[2]))
        y1 = min(float(stair_head_rect[3]), float(interior_footprint[3]))
        if x1 - x0 > 1e-4 and y1 - y0 > 1e-4:
            return (x0, x1, y0, y1)
        merged = _union_rects((opening_footprint, interior_footprint))
        return merged or opening_footprint

    return opening_footprint


def _roof_exit_arrival_platform_rect(spec, spatial_plan) -> tuple[float, float, float, float] | None:
    if (
        spatial_plan.top_terminal_mode != TOP_TERMINAL_PLAYABLE_TOP_ROOM
        or not getattr(spec, "stair_core", None)
        or not spec.stair_core.enabled
    ):
        return None
    if not spatial_plan.top_arrival_rects:
        return None
    return _union_rects(spatial_plan.top_arrival_rects)


def _stair_head_opening_footprint(
    spec,
    *,
    top_floor_footprint: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    metrics = _dogleg_metrics(spec)
    opening_width = max(1.02, _core_arrival_opening_width(spec, metrics))
    opening_depth = max(
        1.18,
        min(
            2.08,
            float(metrics.landing_depth) + max(0.18, float(spec.wall_thickness) * 1.2),
        ),
    )
    opening_center_x = _core_arrival_opening_center_x(spec, metrics)
    opening_center_y = float(metrics.arrival_landing_y)
    return _clamp_rect_to_bounds(
        (
            float(opening_center_x - opening_width / 2),
            float(opening_center_x + opening_width / 2),
            float(opening_center_y - opening_depth / 2),
            float(opening_center_y + opening_depth / 2),
        ),
        top_floor_footprint,
    )


def _rects_touch_or_overlap(
    rect_a: tuple[float, float, float, float],
    rect_b: tuple[float, float, float, float],
    *,
    epsilon: float = 1e-4,
) -> bool:
    return not (
        float(rect_a[1]) < float(rect_b[0]) - epsilon
        or float(rect_b[1]) < float(rect_a[0]) - epsilon
        or float(rect_a[3]) < float(rect_b[2]) - epsilon
        or float(rect_b[3]) < float(rect_a[2]) - epsilon
    )


def _union_rects(rects: tuple[tuple[float, float, float, float], ...]) -> tuple[float, float, float, float] | None:
    if not rects:
        return None
    x0 = min(float(rect[0]) for rect in rects)
    x1 = max(float(rect[1]) for rect in rects)
    y0 = min(float(rect[2]) for rect in rects)
    y1 = max(float(rect[3]) for rect in rects)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, x1, y0, y1)


def _split_rect_around_opening(
    rect: tuple[float, float, float, float],
    opening_rect: tuple[float, float, float, float] | None,
) -> tuple[tuple[float, float, float, float], ...]:
    if opening_rect is None:
        return (rect,)
    x0, x1, y0, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    open_x0 = max(x0, float(opening_rect[0]))
    open_x1 = min(x1, float(opening_rect[1]))
    open_y0 = max(y0, float(opening_rect[2]))
    open_y1 = min(y1, float(opening_rect[3]))
    if open_x1 - open_x0 <= 1e-4 or open_y1 - open_y0 <= 1e-4:
        return (rect,)
    slabs = (
        (x0, open_x0, y0, y1),
        (open_x1, x1, y0, y1),
        (open_x0, open_x1, y0, open_y0),
        (open_x0, open_x1, open_y1, y1),
    )
    return tuple(
        slab
        for slab in slabs
        if float(slab[1]) - float(slab[0]) > 1e-4 and float(slab[3]) - float(slab[2]) > 1e-4
    )


def _clamp_rect_to_bounds(
    rect: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    rx0, rx1, ry0, ry1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    bx0, bx1, by0, by1 = (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
    rect_w = max(1e-4, rx1 - rx0)
    rect_d = max(1e-4, ry1 - ry0)
    bounds_w = max(1e-4, bx1 - bx0)
    bounds_d = max(1e-4, by1 - by0)
    resolved_w = min(rect_w, bounds_w)
    resolved_d = min(rect_d, bounds_d)
    center_x = min(max((rx0 + rx1) / 2, bx0 + resolved_w / 2), bx1 - resolved_w / 2)
    center_y = min(max((ry0 + ry1) / 2, by0 + resolved_d / 2), by1 - resolved_d / 2)
    return (
        float(center_x - resolved_w / 2),
        float(center_x + resolved_w / 2),
        float(center_y - resolved_d / 2),
        float(center_y + resolved_d / 2),
    )


def _attic_open_support_depth_target(
    *,
    metrics,
    interior_depth: float,
    wall_thickness: float,
) -> float:
    minimum_depth = max(
        float(metrics.landing_depth) * 1.1,
        float(metrics.flight_width) * 1.42,
        wall_thickness * 6.2,
    )
    target_depth = max(minimum_depth, float(interior_depth) * 0.24)
    maximum_depth = max(
        minimum_depth,
        min(float(interior_depth) * 0.44, float(metrics.landing_depth) * 1.95),
    )
    return min(max(1e-4, float(interior_depth)), min(target_depth, maximum_depth))


def _attic_open_support_width_target(
    *,
    metrics,
    interior_width: float,
    breach_width: float,
    wall_thickness: float,
) -> float:
    side_pad = max(0.24, min(0.66, float(metrics.flight_width) * 0.22 + wall_thickness * 1.4))
    minimum_width = max(
        float(breach_width) + side_pad * 2,
        float(metrics.flight_width) * 1.74,
        float(metrics.clear_width) + 0.36,
    )
    target_width = max(minimum_width, float(interior_width) * 0.34)
    maximum_width = max(
        minimum_width,
        min(float(interior_width) * 0.6, float(metrics.clear_width) + 1.18),
    )
    return min(max(1e-4, float(interior_width)), min(target_width, maximum_width))


def _attic_open_breach_footprint(
    spec,
    *,
    top_floor_footprint: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    metrics = _dogleg_metrics(spec)
    wall_thickness = float(getattr(spec, "wall_thickness", 0.0))
    interior_footprint = _interior_bounds_for_rect(top_floor_footprint, wall_thickness)
    if (
        interior_footprint[1] - interior_footprint[0] <= 1e-4
        or interior_footprint[3] - interior_footprint[2] <= 1e-4
    ):
        interior_footprint = top_floor_footprint
    breach_width = min(
        float(metrics.clear_width),
        max(
            float(metrics.flight_width) + wall_thickness * 1.6,
            float(metrics.flight_width) * 1.18,
        ),
    )
    breach_depth = min(
        float(metrics.landing_depth),
        max(
            wall_thickness * 3.2,
            float(metrics.landing_depth) * 0.58,
            float(metrics.flight_width) * 0.82,
        ),
    )
    ix0, ix1, iy0, iy1 = (float(value) for value in interior_footprint)
    along_inset = max(0.0, min(0.08, wall_thickness * 0.35))
    pocket_gap = max(0.14, min(0.34, wall_thickness * 0.62 + float(metrics.landing_depth) * 0.1))
    support_depth = _attic_open_support_depth_target(
        metrics=metrics,
        interior_depth=max(1e-4, iy1 - iy0),
        wall_thickness=wall_thickness,
    )
    if str(metrics.arrival_side).upper() == "BACK":
        support_y0 = iy0 + along_inset
        support_y1 = min(iy1 - along_inset, support_y0 + support_depth)
        breach_y0 = min(iy1 - breach_depth, support_y1 + pocket_gap)
        breach_y1 = breach_y0 + breach_depth
    else:
        support_y1 = iy1 - along_inset
        support_y0 = max(iy0 + along_inset, support_y1 - support_depth)
        breach_y1 = max(iy0 + breach_depth, support_y0 - pocket_gap)
        breach_y0 = breach_y1 - breach_depth
    breach_rect = (
        float(metrics.cx - breach_width / 2),
        float(metrics.cx + breach_width / 2),
        float(breach_y0),
        float(breach_y1),
    )
    return _clamp_rect_to_bounds(breach_rect, interior_footprint)


def _attic_open_support_footprint(
    spec,
    *,
    top_floor_footprint: tuple[float, float, float, float],
    breach_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    metrics = _dogleg_metrics(spec)
    wall_thickness = float(getattr(spec, "wall_thickness", 0.0))
    interior_footprint = _interior_bounds_for_rect(top_floor_footprint, wall_thickness)
    if (
        interior_footprint[1] - interior_footprint[0] <= 1e-4
        or interior_footprint[3] - interior_footprint[2] <= 1e-4
    ):
        interior_footprint = top_floor_footprint

    ix0, ix1, iy0, iy1 = (float(value) for value in interior_footprint)
    bx0, bx1, by0, by1 = (float(value) for value in breach_rect)
    along_inset = max(0.0, min(0.08, wall_thickness * 0.35))
    support_depth_target = _attic_open_support_depth_target(
        metrics=metrics,
        interior_depth=max(1e-4, iy1 - iy0),
        wall_thickness=wall_thickness,
    )
    support_width_target = _attic_open_support_width_target(
        metrics=metrics,
        interior_width=max(1e-4, ix1 - ix0),
        breach_width=max(1e-4, bx1 - bx0),
        wall_thickness=wall_thickness,
    )
    support_cx = (bx0 + bx1) / 2
    support_x0 = max(ix0, min(support_cx - support_width_target / 2, ix1 - support_width_target))
    support_x1 = min(ix1, support_x0 + support_width_target)
    breach_overlap = max(0.08, min(0.22, wall_thickness * 0.42 + float(metrics.landing_depth) * 0.05))
    if str(metrics.arrival_side).upper() == "BACK":
        support_y1 = min(iy1 - along_inset, by1 - along_inset + breach_overlap)
        support_y0 = max(iy0 + along_inset, support_y1 - support_depth_target)
    else:
        support_y0 = max(iy0 + along_inset, by0 + along_inset - breach_overlap)
        support_y1 = min(iy1 - along_inset, support_y0 + support_depth_target)

    support_rect = (
        float(support_x0),
        float(support_x1),
        float(support_y0),
        float(support_y1),
    )
    support_depth = max(0.0, float(support_rect[3] - support_rect[2]))
    support_width = max(0.0, float(support_rect[1] - support_rect[0]))
    if support_depth <= 1e-4 or support_width <= 1e-4:
        fallback_depth = min(max(0.84, float(metrics.landing_depth) * 1.08), max(0.84, iy1 - iy0))
        if str(metrics.arrival_side).upper() == "BACK":
            support_y1 = min(iy1 - along_inset, by1 - along_inset + breach_overlap)
            support_y0 = max(iy0 + along_inset, support_y1 - fallback_depth)
        else:
            support_y0 = max(iy0 + along_inset, by0 + along_inset - breach_overlap)
            support_y1 = min(iy1 - along_inset, support_y0 + fallback_depth)
        support_rect = (
            float(support_x0),
            float(support_x1),
            float(support_y0),
            float(support_y1),
        )
    return _clamp_rect_to_bounds(support_rect, interior_footprint)


def _planned_top_arrival_connector_rect(
    *,
    landing_rect: tuple[float, float, float, float],
    destination_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    if _rects_touch_or_overlap(landing_rect, destination_rect):
        return None
    lx0, lx1, ly0, ly1 = landing_rect
    dx0, dx1, dy0, dy1 = destination_rect
    landing_width = max(1e-4, float(lx1 - lx0))
    landing_depth = max(1e-4, float(ly1 - ly0))

    x_overlap0 = max(float(lx0), float(dx0))
    x_overlap1 = min(float(lx1), float(dx1))
    if x_overlap1 - x_overlap0 > 1e-4:
        if dy0 >= ly1:
            y0, y1 = float(ly1), float(dy0)
        elif ly0 >= dy1:
            y0, y1 = float(dy1), float(ly0)
        else:
            return None
        if y1 - y0 <= 1e-4:
            return None
        overlap_width = float(x_overlap1 - x_overlap0)
        width = max(1e-4, min(landing_width, overlap_width))
        x_center = (x_overlap0 + x_overlap1) / 2
        avail_x0 = min(float(lx0), float(dx0))
        avail_x1 = max(float(lx1), float(dx1))
        if avail_x1 - avail_x0 < width:
            width = max(1e-4, avail_x1 - avail_x0)
        x0 = max(avail_x0, min(x_center - width / 2, avail_x1 - width))
        x1 = x0 + width
        return (x0, x1, y0, y1)

    y_overlap0 = max(float(ly0), float(dy0))
    y_overlap1 = min(float(ly1), float(dy1))
    if y_overlap1 - y_overlap0 > 1e-4:
        if dx0 >= lx1:
            x0, x1 = float(lx1), float(dx0)
        elif lx0 >= dx1:
            x0, x1 = float(dx1), float(lx0)
        else:
            return None
        if x1 - x0 <= 1e-4:
            return None
        overlap_depth = float(y_overlap1 - y_overlap0)
        depth = max(1e-4, min(landing_depth, overlap_depth))
        y_center = (y_overlap0 + y_overlap1) / 2
        avail_y0 = min(float(ly0), float(dy0))
        avail_y1 = max(float(ly1), float(dy1))
        if avail_y1 - avail_y0 < depth:
            depth = max(1e-4, avail_y1 - avail_y0)
        y0 = max(avail_y0, min(y_center - depth / 2, avail_y1 - depth))
        y1 = y0 + depth
        return (x0, x1, y0, y1)

    return None


def _plan_top_arrival_rects(
    spec,
    *,
    top_terminal_mode: str,
    roof_room: RoofRoomVolume | None,
) -> tuple[tuple[float, float, float, float], ...]:
    if not bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled):
        return tuple()
    metrics = _dogleg_metrics(spec)
    landing_width = max(1e-4, float(metrics.clear_width))
    landing_depth = max(1e-4, float(metrics.landing_depth))
    landing_rect = (
        float(metrics.cx - landing_width / 2),
        float(metrics.cx + landing_width / 2),
        float(metrics.arrival_landing_y - landing_depth / 2),
        float(metrics.arrival_landing_y + landing_depth / 2),
    )
    rects = [landing_rect]

    def _append_unique_rect(rect: tuple[float, float, float, float] | None):
        if rect is None:
            return
        if any(_rects_almost_equal(rect, existing_rect) for existing_rect in rects):
            return
        rects.append(rect)

    if top_terminal_mode == TOP_TERMINAL_PLAYABLE_TOP_ROOM and roof_room is not None:
        terminal_profile = str(getattr(roof_room, "terminal_profile", "")).upper()
        destination_rect = tuple(float(value) for value in roof_room.footprint)
        opening_rect = _clamp_rect_to_bounds(
            (
                float(metrics.clear_x0),
                float(metrics.clear_x1),
                float(metrics.clear_y0),
                float(metrics.clear_y1),
            ),
            destination_rect,
        )
        if terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN:
            # ATTIC_OPEN floor ownership must stay full-attic-owned while the stair shaft
            # remains genuinely open. The planner breach rect is shell-facing doctrine, not
            # the top-floor cutout shape, so split the attic floor around the actual stair
            # clear opening instead of the compact shell breach.
            attic_floor_rects = _split_rect_around_opening(destination_rect, opening_rect)
            for attic_rect in attic_floor_rects:
                _append_unique_rect(attic_rect)
        else:
            connector_rect = _planned_top_arrival_connector_rect(
                landing_rect=landing_rect,
                destination_rect=destination_rect,
            )
            if connector_rect is not None:
                _append_unique_rect(connector_rect)
            if terminal_profile in {TERMINAL_PROFILE_FULL_ROOM, TERMINAL_PROFILE_STAIR_HEAD}:
                # FULL_ROOM / STAIR_HEAD support ownership matches ATTIC_OPEN at the shaft:
                # landing stays rects[0], while later support pieces wrap around the clear
                # stair opening instead of authoring one solid slab across the throat.
                support_rects = _split_rect_around_opening(destination_rect, opening_rect)
                for support_rect in support_rects:
                    _append_unique_rect(support_rect)
            elif not _rects_touch_or_overlap(landing_rect, destination_rect):
                _append_unique_rect(destination_rect)
    return tuple(rects)


def _rear_entry_stair_clearance(spec) -> float:
    door_width = float(getattr(getattr(spec, "door", None), "width", 1.2))
    return max(REAR_ENTRY_STAIR_CLEARANCE_MIN, min(1.0, door_width * 0.55))


def _front_entry_stair_clearance(spec) -> float:
    door_width = float(getattr(getattr(spec, "door", None), "width", 1.2))
    return max(FRONT_ENTRY_STAIR_CLEARANCE_MIN, min(1.24, door_width * 0.58))


def _front_entry_approach_band_min(spec) -> float:
    door_width = float(getattr(getattr(spec, "door", None), "width", 1.2))
    compact = _compact_residential_envelope(spec)
    min_band = 0.26 if compact["active"] else 0.3
    max_band = 0.44 if compact["active"] else 0.48
    return max(min_band, min(max_band, door_width * 0.3 + float(spec.wall_thickness) * 0.6))


def _adjacent_exterior_sides_for_bounds(
    spec,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> set[str]:
    inner_x0, inner_x1, inner_y0, inner_y1 = _interior_bounds(spec)
    threshold = constants.INNER_MARGIN + 0.1
    sides = set()
    if abs(float(x0) - inner_x0) <= threshold:
        sides.add("LEFT")
    if abs(inner_x1 - float(x1)) <= threshold:
        sides.add("RIGHT")
    if abs(float(y0) - inner_y0) <= threshold:
        sides.add("FRONT")
    if abs(inner_y1 - float(y1)) <= threshold:
        sides.add("BACK")
    return sides


def _front_entry_stair_conflict_span_for_bounds(
    spec,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> tuple[float, float] | None:
    if not bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled):
        return None
    adjacent = _adjacent_exterior_sides_for_bounds(
        spec,
        x0=x0,
        x1=x1,
        y0=y0,
        y1=y1,
    )
    if "FRONT" not in adjacent:
        return None
    clearance = _front_entry_stair_clearance(spec)
    compact = _compact_residential_envelope(spec)
    left_clearance = clearance
    right_clearance = clearance
    if compact["active"]:
        edge_relief = float(compact["front_conflict_edge_relief"])
        if "LEFT" in adjacent:
            left_clearance = max(0.0, clearance - edge_relief)
        if "RIGHT" in adjacent:
            right_clearance = max(0.0, clearance - edge_relief)
    return (float(x0) - left_clearance, float(x1) + right_clearance)


def _front_entry_stair_conflict_span(spec) -> tuple[float, float] | None:
    x0, x1, _y0, _y1, _cx, _cy = _core_bounds(spec)
    return _front_entry_stair_conflict_span_for_bounds(
        spec,
        x0=x0,
        x1=x1,
        y0=_y0,
        y1=_y1,
    )


def _compact_residential_envelope(spec) -> dict[str, float | bool]:
    contract = _compact_residential_envelope_contract(
        str(getattr(spec, "preset_id", "")),
        int(getattr(spec, "floor_count", 0)),
    )
    return {
        "active": bool(float(contract["outer_width_min"]) > 0.0),
        "outer_width_min": float(contract["outer_width_min"]),
        "outer_depth_min": float(contract["outer_depth_min"]),
        "core_width_reserve": float(contract["core_width_reserve"]),
        "core_depth_reserve": float(contract["core_depth_reserve"]),
        "front_conflict_edge_relief": float(contract["front_conflict_edge_relief"]),
    }


def _roomy_multi_floor_envelope(spec) -> dict[str, float | bool]:
    contract = _roomy_multi_floor_envelope_contract(
        str(getattr(spec, "preset_id", "")),
        int(getattr(spec, "floor_count", 0)),
    )
    return {
        "active": bool(float(contract["outer_width_min"]) > 0.0),
        "outer_width_min": float(contract["outer_width_min"]),
        "outer_depth_min": float(contract["outer_depth_min"]),
        "core_width_reserve": float(contract["core_width_reserve"]),
        "core_depth_reserve": float(contract["core_depth_reserve"]),
    }


def _front_entry_approach_gap(
    spec,
    *,
    door_left: float,
    door_right: float,
) -> float | None:
    return _front_entry_approach_gap_from_span(
        door_left=door_left,
        door_right=door_right,
        conflict_span=_front_entry_stair_conflict_span(spec),
    )


def _front_entry_approach_gap_from_span(
    *,
    door_left: float,
    door_right: float,
    conflict_span: tuple[float, float] | None,
) -> float | None:
    epsilon = 1e-9
    if conflict_span is None:
        return None
    if float(door_right) <= float(conflict_span[0]):
        gap = float(conflict_span[0] - door_right)
        return 0.0 if abs(gap) <= epsilon else gap
    if float(door_left) >= float(conflict_span[1]):
        gap = float(door_left - conflict_span[1])
        return 0.0 if abs(gap) <= epsilon else gap
    gap = -float(min(door_right - conflict_span[0], conflict_span[1] - door_left))
    return 0.0 if abs(gap) <= epsilon else gap


def _front_entry_preferred_side(spec) -> str | None:
    if not bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled):
        return None
    placement = str(getattr(spec.stair_core, "placement", "")).upper()
    if placement in {
        constants.STAIR_PLACEMENT_FRONT_RIGHT,
        constants.STAIR_PLACEMENT_BACK_RIGHT,
    }:
        return "left"
    if placement == constants.STAIR_PLACEMENT_BACK_LEFT:
        return "right"
    return None


def _resolve_front_entry_center_against_stair(
    spec,
    *,
    door_width: float,
    preferred_center_x: float,
    conflict_span: tuple[float, float] | None = None,
) -> tuple[float, float | None]:
    approach_band = _front_entry_approach_band_min(spec)
    half_width = max(0.0, float(door_width)) / 2
    min_center = -spec.width / 2 + DOOR_JAMB_MIN + half_width
    max_center = spec.width / 2 - DOOR_JAMB_MIN - half_width
    if min_center > max_center:
        center = (min_center + max_center) / 2
        min_center = center
        max_center = center
    requested_center = min(max(float(preferred_center_x), min_center), max_center)
    if str(getattr(spec, "preset_id", "")).lower() == "market_hall":
        return requested_center, None
    if conflict_span is None:
        conflict_span = _front_entry_stair_conflict_span(spec)
    if conflict_span is None:
        return requested_center, None

    preferred_side = _front_entry_preferred_side(spec)

    def _side_penalty(center_x: float) -> int:
        if preferred_side == "left":
            return 0 if center_x <= 1e-6 else 1
        if preferred_side == "right":
            return 0 if center_x >= -1e-6 else 1
        return 0

    def _score_center(center_x: float) -> tuple[int, float, int, float]:
        gap = _front_entry_approach_gap_from_span(
            door_left=center_x - half_width,
            door_right=center_x + half_width,
            conflict_span=conflict_span,
        )
        if gap is None:
            return (0, 0.0, _side_penalty(center_x), abs(center_x - requested_center))
        gap = float(gap)
        overlap_penalty = 1 if gap < 0.0 else 0
        band_deficit = max(0.0, approach_band - max(gap, 0.0))
        return (overlap_penalty, band_deficit, _side_penalty(center_x), abs(center_x - requested_center))

    left_relaxed_max = float(conflict_span[0]) - half_width - approach_band
    right_relaxed_min = float(conflict_span[1]) + half_width + approach_band
    left_clear_max = float(conflict_span[0]) - half_width
    right_clear_min = float(conflict_span[1]) + half_width
    candidates = [requested_center]
    if left_relaxed_max >= min_center:
        candidates.append(min(max(requested_center, min_center), left_relaxed_max))
    if right_relaxed_min <= max_center:
        candidates.append(min(max(requested_center, right_relaxed_min), max_center))
    if left_clear_max >= min_center:
        candidates.append(min(max(requested_center, min_center), left_clear_max))
    if right_clear_min <= max_center:
        candidates.append(min(max(requested_center, right_clear_min), max_center))
    unique_candidates = sorted({float(center_x) for center_x in candidates})
    scored = sorted(
        ((_score_center(float(center_x)), float(center_x)) for center_x in unique_candidates),
        key=lambda item: item[0],
    )
    resolved_center = scored[0][1]
    resolved_gap = _front_entry_approach_gap_from_span(
        door_left=resolved_center - half_width,
        door_right=resolved_center + half_width,
        conflict_span=conflict_span,
    )
    return resolved_center, (None if resolved_gap is None else float(resolved_gap))


def _fallback_arrival_side_for_placement(spec) -> str:
    placement = str(getattr(getattr(spec, "stair_core", None), "placement", "")).upper()
    if placement in {
        constants.STAIR_PLACEMENT_FRONT_RIGHT,
        constants.STAIR_PLACEMENT_BACK_RIGHT,
        constants.STAIR_PLACEMENT_BACK_LEFT,
    }:
        return "FRONT"
    return "BACK"


def _resolved_front_entry_arrival_side(spec) -> str:
    fallback_side = _fallback_arrival_side_for_placement(spec)
    if not bool(getattr(getattr(spec, "door", None), "enabled", True)):
        return fallback_side
    if str(getattr(spec, "preset_id", "")).lower() == "market_hall":
        return fallback_side
    if _front_entry_stair_conflict_span(spec) is None:
        return "FRONT"
    door_width, preferred_center_x = _effective_door(spec)
    _resolved_center_x, gap = _resolve_front_entry_center_against_stair(
        spec,
        door_width=float(door_width),
        preferred_center_x=float(preferred_center_x),
    )
    if gap is not None and gap >= 0.0:
        return "FRONT"
    return fallback_side


def _rear_entry_stair_conflict_span(spec) -> tuple[float, float] | None:
    if not bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled):
        return None
    if "BACK" not in _adjacent_exterior_sides(spec):
        return None
    x0, x1, _y0, _y1, _cx, _cy = _core_bounds(spec)
    clearance = _rear_entry_stair_clearance(spec)
    return (float(x0 - clearance), float(x1 + clearance))


def _roof_room_shell_bucket(spec, footprint: tuple[float, float, float, float]) -> str:
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    footprint_area = max(0.0, footprint[1] - footprint[0]) * max(0.0, footprint[3] - footprint[2])
    prominent = preset_id in {"clinic", "market_hall", "office_block"} or footprint_area > 4.0
    return "Section_Walls_Exterior" if prominent else "Section_Walls_Interior"


def _roof_requires_pipe_run(
    spec=None,
    *,
    width: float | None = None,
    depth: float | None = None,
    floor_count: int | None = None,
) -> bool:
    if spec is not None:
        if width is None:
            width = float(spec.width)
        if depth is None:
            depth = float(spec.depth)
        if floor_count is None:
            floor_count = int(spec.floor_count)
    if width is None or depth is None or floor_count is None:
        raise ValueError("Roof pipe-run checks require width, depth, and floor_count.")
    return (
        int(floor_count) > 2
        and max(width, depth) >= ROOF_PIPE_RUN_REQUIRED_LONG_DIM_MIN
        and min(width, depth) >= ROOF_PIPE_RUN_REQUIRED_SHORT_DIM_MIN
    )


def _roof_pipe_run_safe_strip_issue(
    spec,
    *,
    side: str,
    edge_inset: float,
    bounds: tuple[float, float, float, float],
    width: float | None = None,
    depth: float | None = None,
) -> str | None:
    if side not in {"front", "back", "left", "right"} or edge_inset <= 0.0:
        return "missing_metadata"

    width = float(spec.width if width is None else width)
    depth = float(spec.depth if depth is None else depth)
    if side == "front":
        target_center = -depth / 2 + edge_inset
    elif side == "back":
        target_center = depth / 2 - edge_inset
    elif side == "left":
        target_center = -width / 2 + edge_inset
    else:
        target_center = width / 2 - edge_inset
    if side in {"front", "back"}:
        if (
            bounds[0] < -width / 2 + edge_inset - ROOF_PIPE_RUN_STRIP_BOUNDS_TOLERANCE
            or bounds[1] > width / 2 - edge_inset + ROOF_PIPE_RUN_STRIP_BOUNDS_TOLERANCE
        ):
            return "outside_strip"
        if abs(((bounds[2] + bounds[3]) / 2) - target_center) > ROOF_PIPE_RUN_STRIP_CENTER_TOLERANCE:
            return "drifted_strip"
        return None

    if (
        bounds[2] < -depth / 2 + edge_inset - ROOF_PIPE_RUN_STRIP_BOUNDS_TOLERANCE
        or bounds[3] > depth / 2 - edge_inset + ROOF_PIPE_RUN_STRIP_BOUNDS_TOLERANCE
    ):
        return "outside_strip"
    if abs(((bounds[0] + bounds[1]) / 2) - target_center) > ROOF_PIPE_RUN_STRIP_CENTER_TOLERANCE:
        return "drifted_strip"
    return None


def _roof_service_bounds(spec) -> tuple[float, float, float, float]:
    parapet_keepout = max(
        ROOF_SERVICE_PARAPET_KEEPOUT_MIN,
        spec.parapet_height + PARAPET_CAP_DEPTH + ROOF_SERVICE_PARAPET_KEEPOUT_EXTRA,
    )
    margin_x = max(
        parapet_keepout,
        min(ROOF_PROP_EDGE_MARGIN, max(ROOF_SERVICE_MARGIN_MIN, spec.width * ROOF_SERVICE_MARGIN_X_RATIO)),
    )
    margin_y = max(
        parapet_keepout,
        min(ROOF_PROP_EDGE_MARGIN, max(ROOF_SERVICE_MARGIN_MIN, spec.depth * ROOF_SERVICE_MARGIN_Y_RATIO)),
    )
    return (
        -spec.width / 2 + margin_x,
        spec.width / 2 - margin_x,
        -spec.depth / 2 + margin_y,
        spec.depth / 2 - margin_y,
    )


def _clamp_service_anchor_origin_point(spec, x: float, y: float) -> tuple[float, float]:
    min_x, max_x, min_y, max_y = _roof_service_bounds(spec)
    if min_x > max_x:
        center_x = (min_x + max_x) / 2
        min_x = center_x
        max_x = center_x
    if min_y > max_y:
        center_y = (min_y + max_y) / 2
        min_y = center_y
        max_y = center_y
    return min(max(x, min_x), max_x), min(max(y, min_y), max_y)


def _service_anchor(spec, *, roof_room: RoofRoomVolume | None = None) -> ServiceAnchor:
    source_rect: tuple[float, float, float, float] | None = None
    kind = "WALL"
    door_offset_x = _effective_door(spec)[1]
    wall_side = "right" if door_offset_x <= 0.0 else "left"

    if spec.stair_core.enabled:
        x0, x1, y0, y1, cx, cy = _core_bounds(spec)
        source_rect = (x0, x1, y0, y1)
        kind = "CORE"
        exposed = _adjacent_exterior_sides(spec)
        roof_exit_side = roof_room.door_wall.upper() if roof_room is not None else _dogleg_metrics(spec).arrival_side
        opposite_side = {
            "FRONT": "BACK",
            "BACK": "FRONT",
            "LEFT": "RIGHT",
            "RIGHT": "LEFT",
        }.get(roof_exit_side, "")
        for candidate in (opposite_side, "RIGHT", "LEFT", "BACK", "FRONT"):
            if not candidate or candidate == roof_exit_side:
                continue
            if candidate in exposed:
                wall_side = candidate.lower()
                break
        else:
            if roof_exit_side in exposed:
                wall_side = roof_exit_side.lower()
            else:
                wall_side = "right" if cx >= 0.0 else "left"
    else:
        side_roll = _stable_unit_float(spec.seed, "service_wall_side")
        if side_roll > 0.78:
            wall_side = "back"
        elif side_roll > 0.39:
            wall_side = "right" if door_offset_x <= 0.0 else "left"
        else:
            wall_side = "left" if door_offset_x <= 0.0 else "right"

    if source_rect is not None:
        x0, x1, y0, y1 = source_rect
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        if wall_side == "right":
            roof_origin_x, roof_origin_y = x1 - 0.56, cy
        elif wall_side == "left":
            roof_origin_x, roof_origin_y = x0 + 0.56, cy
        elif wall_side == "back":
            roof_origin_x, roof_origin_y = cx, y1 - 0.56
        else:
            roof_origin_x, roof_origin_y = cx, y0 + 0.56
    else:
        roof_origin_x = 0.0
        roof_origin_y = 0.0
        if wall_side == "right":
            roof_origin_x = spec.width * 0.22
        elif wall_side == "left":
            roof_origin_x = -spec.width * 0.22
        elif wall_side == "back":
            roof_origin_y = spec.depth * 0.22
        else:
            roof_origin_y = -spec.depth * 0.22

    roof_origin_x, roof_origin_y = _clamp_service_anchor_origin_point(spec, roof_origin_x, roof_origin_y)
    return ServiceAnchor(
        anchor_id=f"{kind.lower()}_{wall_side}",
        kind=kind,
        wall_side=wall_side,
        roof_origin_x=roof_origin_x,
        roof_origin_y=roof_origin_y,
        source_rect=source_rect,
    )


def _wall_service_pipe_band(spec, *, entrance_profile: str | None = None) -> dict[str, float | bool]:
    roof_surface_z = _roof_surface_z(spec)
    base_elev = _base_elevation(spec)
    floor_height = float(spec.floor_height)
    floor_count = int(spec.floor_count)

    if floor_count <= 1:
        top_margin = max(0.34, min(0.58, floor_height * 0.24))
        bottom_margin = max(0.42, floor_height * 0.24)
        desired_span = max(0.82, min(floor_height * 0.52, 1.58))
        validation_min_bottom = 0.18
        validation_max_bottom = 0.28
        validation_min_span = max(0.75, floor_height * 0.28)
        validation_max_span = max(1.75, floor_height * 0.66)
        validation_top_margin = max(0.68, floor_height * 0.26)
    elif floor_count == 2:
        top_margin = max(0.3, min(0.54, floor_height * 0.18))
        bottom_margin = max(0.72, floor_height * 0.32)
        desired_span = max(1.36, min(floor_height * 0.96, 2.34))
        validation_min_bottom = 0.34
        validation_max_bottom = 0.48
        validation_min_span = max(1.25, floor_height * 0.52)
        validation_max_span = floor_height * 1.08
        validation_top_margin = max(0.66, floor_height * 0.22)
    else:
        cluster_floor_span = 1.04 if floor_count <= 4 else 1.22
        top_margin = max(0.28, min(0.52, floor_height * 0.16))
        bottom_margin = max(floor_height * 0.92, 1.08)
        desired_span = floor_height * cluster_floor_span
        validation_min_bottom = None
        validation_max_bottom = floor_height * 0.72
        validation_min_span = floor_height * 0.72
        validation_max_span = floor_height * 1.78
        validation_top_margin = max(0.62, floor_height * 0.22)

    pipe_top = roof_surface_z - top_margin
    pipe_bottom = max(base_elev + bottom_margin, pipe_top - desired_span)
    if pipe_bottom >= pipe_top - 0.62:
        pipe_bottom = max(base_elev + max(0.32, bottom_margin * 0.65), pipe_top - 0.92)

    validation_base_elevation = 0.0
    if entrance_profile is None:
        from .layout_facade_planning import _effective_entrance_profile

        entrance_profile = _effective_entrance_profile(spec)
    entrance_profile = str(entrance_profile)
    if entrance_profile == ENTRANCE_STOOP_LOW:
        validation_base_elevation = 0.24
    elif entrance_profile == ENTRANCE_PODIUM_HIGH:
        validation_base_elevation = 0.72
    validation_roof_surface_z = validation_base_elevation + floor_count * floor_height

    if floor_count <= 2:
        validation_min_bottom_value = validation_base_elevation + float(validation_min_bottom)
        validation_max_bottom_value = validation_roof_surface_z - float(validation_max_bottom)
    else:
        validation_min_bottom_value = max(
            validation_base_elevation + floor_height * 0.9,
            validation_roof_surface_z - floor_height * 2.05,
        )
        validation_max_bottom_value = validation_roof_surface_z - float(validation_max_bottom)

    return {
        "pipe_top": pipe_top,
        "pipe_bottom": pipe_bottom,
        "pipe_height": pipe_top - pipe_bottom,
        "spawnable": pipe_bottom < pipe_top - 0.46,
        "validation_min_bottom": validation_min_bottom_value,
        "validation_max_bottom": validation_max_bottom_value,
        "validation_min_span": validation_min_span,
        "validation_max_span": validation_max_span,
        "validation_expected_top": validation_roof_surface_z - validation_top_margin,
    }


def _spatial_plan(spec) -> SpatialPlan:
    from .layout_facade_planning import _rear_access_family_policy_profile

    preset_id = str(getattr(spec, "preset_id", "")).lower()
    rear_access_profile = _rear_access_family_policy_profile(spec)
    door_enabled = bool(getattr(getattr(spec, "door", None), "enabled", False))
    if rear_access_profile == REAR_ACCESS_PROFILE_NONE:
        rear_access = False
    elif rear_access_profile in {REAR_ACCESS_PROFILE_OPEN_BAY, REAR_ACCESS_PROFILE_SHELL_ONLY}:
        rear_access = True
    else:
        rear_access = door_enabled
    transition_floor_index, upper_shell_rect, terrace_open_sides = _terrace_transition_contract(spec)
    top_terminal_mode, roof_access_enabled, terminal_profile = _resolved_top_terminal_policy(
        spec,
        transition_floor_index=transition_floor_index,
    )
    floors: list[SpatialFloor] = []
    full_rect = _full_shell_rect(spec)
    for floor_index in range(int(getattr(spec, "floor_count", 0))):
        footprint = full_rect
        if (
            upper_shell_rect is not None
            and transition_floor_index is not None
            and int(floor_index) == int(transition_floor_index)
        ):
            footprint = upper_shell_rect
        base_z = _level_base_z(spec, floor_index)
        floors.append(
            SpatialFloor(
                floor_index=floor_index,
                footprint=footprint,
                base_z=base_z,
                ceiling_z=base_z + float(spec.floor_height),
                is_traversable=(floor_index == 0 or bool(getattr(getattr(spec, "stair_core", None), "enabled", False))),
                has_front_door=(floor_index == 0 and bool(getattr(getattr(spec, "door", None), "enabled", False)) and preset_id != "under_construction"),
                has_rear_door=(
                    floor_index == 0
                    and rear_access
                    and rear_access_profile == REAR_ACCESS_PROFILE_SERVICE_DOOR
                ),
            )
        )
    stair_run_count = max(0, sum(1 for floor in floors[1:] if floor.is_traversable) + int(roof_access_enabled))

    roof_room = None
    roof_keepout = None
    if roof_access_enabled:
        resolved_terminal_profile = terminal_profile or TERMINAL_PROFILE_FULL_ROOM
        metrics = _dogleg_metrics(spec)
        door_width = min(1.2, max(1.0, metrics.clear_width * 0.3))
        top_floor_footprint = tuple(float(value) for value in floors[-1].footprint) if floors else _full_shell_rect(spec)
        if resolved_terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN:
            breach_footprint = _attic_open_breach_footprint(
                spec,
                top_floor_footprint=top_floor_footprint,
            )
            opening_footprint = breach_footprint
        else:
            if resolved_terminal_profile == TERMINAL_PROFILE_STAIR_HEAD:
                opening_footprint = _stair_head_opening_footprint(
                    spec,
                    top_floor_footprint=top_floor_footprint,
                )
            else:
                opening_footprint = (
                    float(metrics.clear_x0),
                    float(metrics.clear_x1),
                    float(metrics.clear_y0),
                    float(metrics.clear_y1),
                )
        footprint = _roof_room_envelope_footprint(
            spec,
            terminal_profile=resolved_terminal_profile,
            top_floor_footprint=top_floor_footprint,
            opening_footprint=opening_footprint,
        )
        opening_rect = None if _rects_almost_equal(footprint, opening_footprint) else opening_footprint
        roof_room = RoofRoomVolume(
            terminal_profile=resolved_terminal_profile,
            footprint=footprint,
            opening_rect=opening_rect,
            base_z=_roof_surface_z(spec),
            height=ROOF_EXIT_HEIGHT,
            shell_bucket=_roof_room_shell_bucket(spec, footprint),
            door_wall=metrics.arrival_side.lower(),
            door_width=door_width,
            door_height=2.2,
        )

    top_arrival_rects = _plan_top_arrival_rects(
        spec,
        top_terminal_mode=top_terminal_mode,
        roof_room=roof_room,
    )
    if roof_room is not None:
        clearance = max(ROOF_EXIT_SERVICE_CLEARANCE, _dogleg_metrics(spec).landing_depth + 1.05)
        roof_keepout = (
            roof_room.footprint[0] - clearance,
            roof_room.footprint[1] + clearance,
            roof_room.footprint[2] - clearance,
            roof_room.footprint[3] + clearance,
        )
    service_anchor = _service_anchor(spec, roof_room=roof_room)

    return SpatialPlan(
        floors=tuple(floors),
        rear_access=rear_access,
        rear_access_profile=rear_access_profile,
        top_terminal_mode=top_terminal_mode,
        roof_access_enabled=roof_access_enabled,
        stair_run_count=stair_run_count,
        transition_floor_index=transition_floor_index,
        upper_shell_rect=upper_shell_rect,
        terrace_open_sides=terrace_open_sides,
        top_arrival_rects=top_arrival_rects,
        roof_room=roof_room,
        roof_keepout=roof_keepout,
        service_anchor=service_anchor,
    )


def _spatial_plan_roof_room_bounds(spatial_plan: SpatialPlan) -> tuple[float, float, float, float, float, float] | None:
    if spatial_plan.roof_room is None:
        return None
    x0, x1, y0, y1 = spatial_plan.roof_room.footprint
    return (
        float(x0),
        float(x1),
        float(y0),
        float(y1),
        float(spatial_plan.roof_room.base_z),
        float(spatial_plan.roof_room.base_z + spatial_plan.roof_room.height),
    )


def _spatial_plan_roof_opening_bounds(spatial_plan: SpatialPlan) -> tuple[float, float, float, float, float, float] | None:
    if spatial_plan.roof_room is None:
        return None
    opening_rect = spatial_plan.roof_room.opening_rect or spatial_plan.roof_room.footprint
    x0, x1, y0, y1 = opening_rect
    return (
        float(x0),
        float(x1),
        float(y0),
        float(y1),
        float(spatial_plan.roof_room.base_z),
        float(spatial_plan.roof_room.base_z + spatial_plan.roof_room.height),
    )

def _is_stage1_identity_reset_family(spec) -> bool:
    return str(getattr(spec, "preset_id", "")).lower() in _STAGE1_IDENTITY_RESET_PRESETS


def _interior_bounds(spec):
    return (
        -spec.width / 2 + spec.wall_thickness,
        spec.width / 2 - spec.wall_thickness,
        -spec.depth / 2 + spec.wall_thickness,
        spec.depth / 2 - spec.wall_thickness,
    )


def _interior_bounds_for_rect(rect: tuple[float, float, float, float], wall_thickness: float):
    x0, x1, y0, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    inset = float(wall_thickness)
    return (
        x0 + inset,
        x1 - inset,
        y0 + inset,
        y1 - inset,
    )


def _target_tread_depth(floor_height: float, step_count: int) -> float:
    step_rise = floor_height / max(step_count, 1)
    target = step_rise / math.tan(math.radians(TARGET_STAIR_ANGLE_DEGREES))
    return min(MAX_TREAD_DEPTH, max(MIN_TREAD_DEPTH, target))


def _clear_landing_depth(flight_width: float, *, railing_enabled: bool) -> float:
    clear_depth = max(MIN_LANDING_DEPTH, float(flight_width))
    if railing_enabled:
        clear_depth += max(0.18, RAIL_THICKNESS * 3.0)
    return clear_depth


def _effective_core_geometry(spec):
    inner_x0, inner_x1, inner_y0, inner_y1 = _interior_bounds(spec)
    inner_width = inner_x1 - inner_x0
    inner_depth = inner_y1 - inner_y0

    lower_steps = max(1, spec.stair_core.step_count // 2)
    upper_steps = max(1, spec.stair_core.step_count - lower_steps)
    target_tread = _target_tread_depth(spec.floor_height, spec.stair_core.step_count)

    desired_flight_width = min(spec.stair_core.stair_width, max(0.95, inner_width - 1.2))
    width_padding = spec.wall_thickness * 2 + FLIGHT_GAP + FLIGHT_SIDE_MARGIN * 2
    core_width = max(spec.stair_core.core_width, desired_flight_width * 2 + width_padding)
    roomy = _roomy_multi_floor_envelope(spec)
    if roomy["active"]:
        width_reserve = float(roomy["core_width_reserve"])
    else:
        width_reserve = 1.8 if spec.stair_core.placement == constants.STAIR_PLACEMENT_CENTER else 1.1
    core_width = min(core_width, inner_width - 0.1, max(2.6, inner_width - width_reserve))
    clear_width = max(2.0, core_width - spec.wall_thickness * 2)
    max_flight_width = max(0.95, (clear_width - FLIGHT_GAP - FLIGHT_SIDE_MARGIN * 2) / 2)
    flight_width = min(desired_flight_width, max_flight_width)
    core_width = min(
        inner_width - 0.1,
        max(core_width, flight_width * 2 + FLIGHT_GAP + FLIGHT_SIDE_MARGIN * 2 + spec.wall_thickness * 2),
    )

    railing_enabled = bool(getattr(spec.stair_core, "railing_enabled", False))
    landing_depth = _clear_landing_depth(flight_width, railing_enabled=railing_enabled)
    run_required = max(lower_steps, upper_steps) * target_tread
    core_depth = max(spec.stair_core.core_depth, spec.wall_thickness * 2 + landing_depth * 2 + run_required)
    if roomy["active"]:
        depth_reserve = float(roomy["core_depth_reserve"])
    else:
        depth_reserve = 0.95 if spec.stair_core.placement == constants.STAIR_PLACEMENT_CENTER else 0.7
    core_depth = min(core_depth, inner_depth - 0.1, max(3.9, inner_depth - depth_reserve))
    clear_depth = max(2.2, core_depth - spec.wall_thickness * 2)
    run_span = clear_depth - landing_depth * 2
    min_run_span = max(lower_steps, upper_steps) * MIN_TREAD_DEPTH
    if run_span < min_run_span:
        required_clear_depth = min_run_span + landing_depth * 2
        required_core_depth = spec.wall_thickness * 2 + required_clear_depth
        core_depth = min(inner_depth - 0.1, max(core_depth, required_core_depth))
        clear_depth = max(2.2, core_depth - spec.wall_thickness * 2)
        run_span = clear_depth - landing_depth * 2
    if run_span < min_run_span:
        landing_depth = max(MIN_LANDING_DEPTH, (clear_depth - min_run_span) / 2)
        run_span = clear_depth - landing_depth * 2
    core_depth = max(core_depth, spec.wall_thickness * 2 + landing_depth * 2 + run_span)
    return core_width, core_depth, flight_width, landing_depth


def _placement_core_center(
    spec,
    *,
    core_width: float,
    core_depth: float,
) -> tuple[float, float]:
    margin_x = spec.wall_thickness + core_width / 2 + constants.INNER_MARGIN
    margin_y = spec.wall_thickness + core_depth / 2 + constants.INNER_MARGIN
    half_w = spec.width / 2
    half_d = spec.depth / 2
    mapping = {
        constants.STAIR_PLACEMENT_CENTER: (0.0, 0.0),
        constants.STAIR_PLACEMENT_FRONT_RIGHT: (half_w - margin_x, -half_d + margin_y),
        constants.STAIR_PLACEMENT_BACK_RIGHT: (half_w - margin_x, half_d - margin_y),
        constants.STAIR_PLACEMENT_BACK_LEFT: (-half_w + margin_x, half_d - margin_y),
    }
    return mapping.get(spec.stair_core.placement, (0.0, 0.0))


def _core_center_x_bounds(
    spec,
    *,
    core_width: float,
) -> tuple[float, float]:
    margin_x = spec.wall_thickness + core_width / 2 + constants.INNER_MARGIN
    half_w = spec.width / 2
    return (-half_w + margin_x, half_w - margin_x)


def _coupled_front_entry_core_center_x(
    spec,
    *,
    core_width: float,
    core_depth: float,
    placement_cx: float,
    placement_cy: float,
) -> float:
    if not bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled):
        return float(placement_cx)
    if not bool(getattr(getattr(spec, "door", None), "enabled", True)):
        return float(placement_cx)

    min_cx, max_cx = _core_center_x_bounds(spec, core_width=core_width)
    placement_cx = min(max(float(placement_cx), min_cx), max_cx)
    door_width, preferred_center_x = _effective_door(spec)
    visible_opening_width = _front_entry_visible_opening_width(door_width)
    opening_w = min(max(0.0, float(core_width) - 0.4), max(1.2, float(visible_opening_width)))
    opening_host_half_span = max(
        0.0,
        float(core_width) / 2 - float(spec.wall_thickness) - opening_w / 2,
    )
    y0 = float(placement_cy) - float(core_depth) / 2
    y1 = float(placement_cy) + float(core_depth) / 2
    cx = placement_cx

    for _ in range(4):
        x0 = cx - float(core_width) / 2
        x1 = cx + float(core_width) / 2
        conflict_span = _front_entry_stair_conflict_span_for_bounds(
            spec,
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
        )
        if conflict_span is None:
            resolved_center_x = float(preferred_center_x)
        else:
            resolved_center_x, _gap = _resolve_front_entry_center_against_stair(
                spec,
                door_width=float(door_width),
                preferred_center_x=float(preferred_center_x),
                conflict_span=conflict_span,
            )
        if opening_host_half_span <= 1e-6:
            next_cx = min(max(float(resolved_center_x), min_cx), max_cx)
        else:
            host_min = max(min_cx, float(resolved_center_x) - opening_host_half_span)
            host_max = min(max_cx, float(resolved_center_x) + opening_host_half_span)
            if host_min > host_max:
                next_cx = min(max(float(resolved_center_x), min_cx), max_cx)
            else:
                next_cx = min(max(placement_cx, host_min), host_max)
        if abs(next_cx - cx) <= 1e-6:
            return float(next_cx)
        cx = float(next_cx)
    return float(cx)


def _core_center(spec):
    core_width, core_depth, _flight_width, _landing_depth = _effective_core_geometry(spec)
    placement_cx, placement_cy = _placement_core_center(
        spec,
        core_width=core_width,
        core_depth=core_depth,
    )
    solved_cx = _coupled_front_entry_core_center_x(
        spec,
        core_width=core_width,
        core_depth=core_depth,
        placement_cx=placement_cx,
        placement_cy=placement_cy,
    )
    return solved_cx, float(placement_cy)


def _core_bounds(spec):
    core_width, core_depth, _flight_width, _landing_depth = _effective_core_geometry(spec)
    cx, cy = _core_center(spec)
    return (
        cx - core_width / 2,
        cx + core_width / 2,
        cy - core_depth / 2,
        cy + core_depth / 2,
        cx,
        cy,
    )


def slab_planar_sections(
    spec,
    *,
    split_for_core: bool,
    opening_bounds: tuple[float, float, float, float] | None = None,
) -> list[tuple[str, tuple[float, float], tuple[float, float]]]:
    inner_x0, inner_x1, inner_y0, inner_y1 = _interior_bounds(spec)
    inner_w = inner_x1 - inner_x0
    inner_d = inner_y1 - inner_y0
    if not split_for_core:
        return [("Main", (inner_w, inner_d), (0.0, 0.0))]

    if opening_bounds is None:
        open_x0, open_x1, open_y0, open_y1, cx, _cy = _core_bounds(spec)
    else:
        open_x0, open_x1, open_y0, open_y1 = opening_bounds
        cx = (open_x0 + open_x1) / 2
    return [
        ("Left", (open_x0 - inner_x0, inner_d), ((inner_x0 + open_x0) / 2, 0.0)),
        ("Right", (inner_x1 - open_x1, inner_d), ((open_x1 + inner_x1) / 2, 0.0)),
        ("Front", (open_x1 - open_x0, open_y0 - inner_y0), (cx, (inner_y0 + open_y0) / 2)),
        ("Back", (open_x1 - open_x0, inner_y1 - open_y1), (cx, (open_y1 + inner_y1) / 2)),
    ]


def _adjacent_exterior_sides(spec):
    if not spec.stair_core.enabled:
        return set()

    x0, x1, y0, y1, _cx, _cy = _core_bounds(spec)
    return _adjacent_exterior_sides_for_bounds(
        spec,
        x0=x0,
        x1=x1,
        y0=y0,
        y1=y1,
    )


def _core_arrival_opening_width(spec, metrics: DoglegMetrics) -> float:
    max_opening = max(0.6, float(metrics.core_width) - 0.4)
    hostable_opening = max(
        0.6,
        float(metrics.clear_width) - max(0.14, float(spec.wall_thickness) * 0.6),
    )
    requested_opening = max(1.2, float(metrics.flight_width) * 1.45)
    return min(max_opening, hostable_opening, requested_opening)


def _core_arrival_opening_center_x(spec, metrics: DoglegMetrics) -> float:
    opening_w = _core_arrival_opening_width(spec, metrics)
    min_center = float(metrics.x0 + float(spec.wall_thickness) + opening_w / 2)
    max_center = float(metrics.x1 - float(spec.wall_thickness) - opening_w / 2)
    if min_center > max_center:
        center = (min_center + max_center) / 2
        min_center = center
        max_center = center
    requested_center = float(metrics.cx)
    return min(max(requested_center, min_center), max_center)


def _stair_flow(spec):
    arrival_side = _resolved_front_entry_arrival_side(spec)
    if arrival_side == "FRONT":
        return 1.0, "FRONT", "BACK"
    return -1.0, "BACK", "FRONT"


def _dogleg_metrics(spec) -> DoglegMetrics:
    x0, x1, y0, y1, cx, cy = _core_bounds(spec)
    _core_width, _core_depth, flight_width, landing_depth = _effective_core_geometry(spec)
    clear_x0 = x0 + spec.wall_thickness
    clear_x1 = x1 - spec.wall_thickness
    clear_y0 = y0 + spec.wall_thickness
    clear_y1 = y1 - spec.wall_thickness
    clear_width = clear_x1 - clear_x0
    lower_steps = max(1, spec.stair_core.step_count // 2)
    upper_steps = max(1, spec.stair_core.step_count - lower_steps)
    step_rise = spec.floor_height / max(spec.stair_core.step_count, 1)

    side_margin = max(0.02, (clear_width - flight_width * 2 - FLIGHT_GAP) / 2)
    lower_x = clear_x0 + side_margin + flight_width / 2
    upper_x = clear_x1 - side_margin - flight_width / 2

    run_span = max(1.4, clear_y1 - clear_y0 - landing_depth * 2)
    lower_tread = run_span / lower_steps
    upper_tread = run_span / upper_steps
    _direction_sign, arrival_side, opposite_side = _stair_flow(spec)

    if arrival_side == "BACK":
        arrival_wall_y = y1 - spec.wall_thickness / 2
        opposite_wall_y = y0 + spec.wall_thickness / 2
        arrival_landing_y = clear_y1 - landing_depth / 2
        mid_landing_y = clear_y0 + landing_depth / 2
        lower_start_y = clear_y1 - landing_depth - lower_tread / 2
        upper_start_y = clear_y0 + landing_depth + upper_tread / 2
        lower_direction = -1.0
        upper_direction = 1.0
    else:
        arrival_wall_y = y0 + spec.wall_thickness / 2
        opposite_wall_y = y1 - spec.wall_thickness / 2
        arrival_landing_y = clear_y0 + landing_depth / 2
        mid_landing_y = clear_y1 - landing_depth / 2
        lower_start_y = clear_y0 + landing_depth + lower_tread / 2
        upper_start_y = clear_y1 - landing_depth - upper_tread / 2
        lower_direction = 1.0
        upper_direction = -1.0

    return DoglegMetrics(
        x0=x0,
        x1=x1,
        y0=y0,
        y1=y1,
        cx=cx,
        cy=cy,
        clear_x0=clear_x0,
        clear_x1=clear_x1,
        clear_y0=clear_y0,
        clear_y1=clear_y1,
        core_width=x1 - x0,
        core_depth=y1 - y0,
        clear_width=clear_width,
        flight_width=flight_width,
        landing_depth=landing_depth,
        lower_steps=lower_steps,
        upper_steps=upper_steps,
        step_rise=step_rise,
        lower_tread=lower_tread,
        upper_tread=upper_tread,
        lower_x=lower_x,
        upper_x=upper_x,
        arrival_side=arrival_side,
        opposite_side=opposite_side,
        arrival_wall_y=arrival_wall_y,
        opposite_wall_y=opposite_wall_y,
        arrival_landing_y=arrival_landing_y,
        mid_landing_y=mid_landing_y,
        lower_start_y=lower_start_y,
        upper_start_y=upper_start_y,
        lower_direction=lower_direction,
        upper_direction=upper_direction,
    )


def _effective_door(spec):
    from .layout_facade_planning import _effective_door as _impl

    return _impl(spec)


def _door_threshold_z(spec) -> float:
    from .layout_facade_planning import _door_threshold_z as _impl

    return _impl(spec)


def _front_entry_envelope(spec) -> FrontEntryEnvelope:
    from .layout_facade_planning import _front_entry_envelope as _impl

    return _impl(spec)


def _front_entry_package_center_span(spec) -> tuple[float, float]:
    from .layout_facade_planning import _front_entry_package_center_span as _impl

    return _impl(spec)


def _front_entry_visible_opening_width(opening_width: float) -> float:
    from .layout_facade_planning import _front_entry_visible_opening_width as _impl

    return _impl(opening_width)


def _stable_unit_float(seed: int, *parts) -> float:
    payload = "|".join([str(int(seed))] + [str(part) for part in parts]).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value / float((1 << 64) - 1)


def _brick_story_count(spec) -> int:
    from .layout_facade_planning import _brick_story_count as _impl

    return _impl(spec)


def _completed_facade_floor_count(spec) -> int:
    from .layout_facade_planning import _completed_facade_floor_count as _impl

    return _impl(spec)


def _pilotis_open_side(spec, side_key: str, floor_index: int) -> bool:
    return (
        int(floor_index) == 0
        and getattr(spec, "massing_profile", "") == MASSING_PROFILE_PILOTIS
        and side_key in {"back", "left", "right"}
    )


def _is_panel_floor(spec, floor_index: int) -> bool:
    from .layout_facade_planning import _is_panel_floor as _impl

    return _impl(spec, floor_index)


def _is_office_window_profile(window_profile: str) -> bool:
    from .layout_facade_planning import _is_office_window_profile as _impl

    return _impl(window_profile)


def _is_small_square_window_profile(window_profile: str) -> bool:
    from .layout_facade_planning import _is_small_square_window_profile as _impl

    return _impl(window_profile)


def _is_panoramic_window_profile(window_profile: str) -> bool:
    from .layout_facade_planning import _is_panoramic_window_profile as _impl

    return _impl(window_profile)


def _is_tall_narrow_window_profile(window_profile: str) -> bool:
    from .layout_facade_planning import _is_tall_narrow_window_profile as _impl

    return _impl(window_profile)


def _is_multi_pane_window_profile(window_profile: str) -> bool:
    from .layout_facade_planning import _is_multi_pane_window_profile as _impl

    return _impl(window_profile)


def _is_residential_wide(window_profile: str) -> bool:
    from .layout_facade_planning import _is_residential_wide as _impl

    return _impl(window_profile)


def _has_podium_base(spec) -> bool:
    return _effective_entrance_profile(spec) == ENTRANCE_PODIUM_HIGH


def _base_elevation(spec) -> float:
    return _door_threshold_z(spec)


def _level_base_z(spec, floor_index: int) -> float:
    return _base_elevation(spec) + floor_index * spec.floor_height


def _roof_surface_z(spec) -> float:
    return _base_elevation(spec) + spec.floor_count * spec.floor_height


def _effective_entrance_profile(spec) -> str:
    from .layout_facade_planning import _effective_entrance_profile as _impl

    return _impl(spec)


def subtract_blocked_spans(
    intervals: list[tuple[float, float]],
    block_start: float,
    block_end: float,
    *,
    padding: float = 0.0,
    minimum_span: float = 0.0,
) -> list[tuple[float, float]]:
    padded_start = block_start - padding
    padded_end = block_end + padding
    result: list[tuple[float, float]] = []
    for start, end in intervals:
        if padded_end <= start or padded_start >= end:
            result.append((start, end))
            continue
        if padded_start > start:
            result.append((start, padded_start))
        if padded_end < end:
            result.append((padded_end, end))
    return [item for item in result if item[1] - item[0] >= minimum_span]


def _window_verticals(floor_height: float, window_profile: str):
    from .layout_facade_planning import _window_verticals as _impl

    return _impl(floor_height, window_profile)


def _side_sign(side_key: str) -> float:
    return -1.0 if side_key in {"front", "left"} else 1.0


def _orientation_rotation(orientation: str, extra_rotation_z: float = 0.0):
    return (0.0, 0.0, extra_rotation_z if orientation == "X" else math.pi / 2 + extra_rotation_z)


def _opening_location(orientation: str, along_coord: float, normal_coord: float, z_center: float):
    return (along_coord, normal_coord, z_center) if orientation == "X" else (normal_coord, along_coord, z_center)


def _surface_coord(side_key: str, wall_pos: float, wall_t: float, depth: float, *, exterior: bool = True, offset: float = 0.0):
    sign = _side_sign(side_key)
    wall_face = wall_pos + sign * (wall_t / 2 if exterior else -wall_t / 2)
    travel = sign if exterior else -sign
    return wall_face + travel * (depth / 2 - 0.004 + offset)


def _opening_inset_coord(
    side_key: str,
    wall_pos: float,
    wall_t: float,
    depth: float,
    *,
    inset: float,
    interior: bool = False,
) -> float:
    sign = _side_sign(side_key)
    face = wall_pos - sign * (wall_t / 2) if interior else wall_pos + sign * (wall_t / 2)
    travel = sign if interior else -sign
    clamped_inset = max(0.0, min(wall_t - depth, inset))
    return face + travel * (clamped_inset + depth / 2 - 0.004)


def _centered_opening_shell_parts(
    *,
    wall_width: float,
    wall_depth: float,
    wall_height: float,
    opening_width: float,
    opening_height: float,
    wall_center_along: float,
    wall_center_normal: float,
    base_z: float,
    orientation: str = "Y",
) -> dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]]:
    opening_box_size = (
        lambda along_span, normal_depth, height: (along_span, normal_depth, height)
        if orientation == "X"
        else (normal_depth, along_span, height)
    )
    minimum_axis = max(1e-6, wall_depth / 2)
    side_width = max(0.0, (wall_width - opening_width) / 2)
    lintel_height = max(0.0, wall_height - opening_height)
    wall_center_z = base_z + wall_height / 2
    opening_top_z = base_z + opening_height
    parts: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {}
    if side_width > minimum_axis:
        left_size = opening_box_size(side_width, wall_depth, wall_height)
        if min(left_size) > minimum_axis:
            parts["left"] = (
                left_size,
                _opening_location(
                    orientation,
                    wall_center_along - opening_width / 2 - side_width / 2,
                    wall_center_normal,
                    wall_center_z,
                ),
            )
        right_size = opening_box_size(side_width, wall_depth, wall_height)
        if min(right_size) > minimum_axis:
            parts["right"] = (
                right_size,
                _opening_location(
                    orientation,
                    wall_center_along + opening_width / 2 + side_width / 2,
                    wall_center_normal,
                    wall_center_z,
                ),
            )
    if lintel_height > minimum_axis:
        lintel_size = opening_box_size(opening_width, wall_depth, lintel_height)
        if min(lintel_size) > minimum_axis:
            parts["lintel"] = (
                lintel_size,
                _opening_location(
                    orientation,
                    wall_center_along,
                    wall_center_normal,
                    opening_top_z + lintel_height / 2,
                ),
            )
    return parts


def _wide_partition_positions(
    spec,
    *,
    interior_bounds: tuple[float, float, float, float] | None = None,
) -> list[float]:
    if not spec.stair_core.enabled and int(getattr(spec, "floor_count", 0)) != 1:
        return []

    inner_x0, inner_x1, inner_y0, inner_y1 = (
        _interior_bounds(spec) if interior_bounds is None else interior_bounds
    )
    inner_width = inner_x1 - inner_x0
    inner_depth = inner_y1 - inner_y0
    if (
        inner_width < WIDE_PARTITION_MIN_WIDTH
        or inner_depth < WIDE_PARTITION_DEPTH_MIN
        or inner_width < inner_depth + 1.8
    ):
        return []

    metrics = _dogleg_metrics(spec)
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    positions: list[float] = []
    raw_side_spans = [(inner_x0, metrics.x0), (metrics.x1, inner_x1)]
    if not bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled):
        raw_side_spans = [(inner_x0, inner_x1)]

    def _side_usable_spans() -> list[tuple[float, float]]:
        usable: list[tuple[float, float]] = []
        for span_start, span_end in raw_side_spans:
            usable_start = span_start + 0.95
            usable_end = span_end - 0.95
            if usable_end - usable_start >= WIDE_PARTITION_MIN_ROOM_WIDTH:
                usable.append((usable_start, usable_end))
        return usable

    side_spans = raw_side_spans
    if not side_spans:
        return []

    filtered_side_spans = list(side_spans)
    from .layout_facade_planning import _rear_entry_partition_keepout_span

    rear_corridor_span = _rear_entry_partition_keepout_span(
        spec,
        _spatial_plan(spec),
        face_length=float(spec.width),
    )
    if rear_corridor_span is not None:
        filtered_side_spans = subtract_blocked_spans(
            filtered_side_spans,
            float(rear_corridor_span[0]),
            float(rear_corridor_span[1]),
            minimum_span=max(0.0, WIDE_PARTITION_MIN_ROOM_WIDTH * 0.45),
        )
        if not filtered_side_spans:
            return []

    def _extend_positions(span_start: float, span_end: float, *, already_usable: bool = False):
        usable_start = span_start if already_usable else span_start + 0.95
        usable_end = span_end if already_usable else span_end - 0.95
        span = usable_end - usable_start
        if span < WIDE_PARTITION_MIN_ROOM_WIDTH:
            return
        count = 1
        if span >= WIDE_PARTITION_MIN_ROOM_WIDTH * 2.2:
            count = 2
        step = span / (count + 1)
        for idx in range(count):
            positions.append(usable_start + step * (idx + 1))

    if preset_id == "office_block":
        from .layout_facade_planning import _office_partition_keepout_contract

        spatial_plan = _spatial_plan(spec)
        keepout_contract = _office_partition_keepout_contract(
            spec,
            spatial_plan,
            face_length=float(spec.width),
        )
        blocked_spans = list(keepout_contract["blocked_spans"] or ())
        office_filtered_side_spans: list[tuple[float, float]] = []
        for span_start, span_end in filtered_side_spans:
            current = [(span_start, span_end)]
            for block_start, block_end in blocked_spans:
                current = subtract_blocked_spans(
                    current,
                    block_start,
                    block_end,
                    minimum_span=max(0.0, WIDE_PARTITION_MIN_ROOM_WIDTH * 0.45),
                )
                if not current:
                    break
            office_filtered_side_spans.extend(current)

        side_groups: list[list[tuple[float, float]]] = [[], []]
        for span_start, span_end in office_filtered_side_spans:
            if span_end <= metrics.cx:
                side_groups[0].append((span_start, span_end))
            elif span_start >= metrics.cx:
                side_groups[1].append((span_start, span_end))
            else:
                side_groups[0].append((span_start, metrics.cx))
                side_groups[1].append((metrics.cx, span_end))

        side_positions: list[float] = []
        min_spacing = max(2.4, WIDE_PARTITION_MIN_ROOM_WIDTH * 0.75)
        for spans in side_groups:
            valid_spans = [span for span in spans if span[1] - span[0] >= WIDE_PARTITION_MIN_ROOM_WIDTH * 0.56]
            if not valid_spans:
                continue
            lengths = [span[1] - span[0] for span in valid_spans]
            total_length = sum(lengths)
            longest = max(lengths)
            desired = 0
            if longest >= max(2.2, WIDE_PARTITION_MIN_ROOM_WIDTH * 0.7):
                desired = 1
            if (
                longest >= WIDE_PARTITION_MIN_ROOM_WIDTH * 1.22
                and total_length >= WIDE_PARTITION_MIN_ROOM_WIDTH * 3.45
                and len(valid_spans) >= 2
            ):
                desired = 2
            selected: list[float] = []
            for span_start, span_end in sorted(valid_spans, key=lambda item: item[1] - item[0], reverse=True):
                center = (span_start + span_end) / 2
                if any(abs(center - existing) < min_spacing for existing in selected):
                    continue
                selected.append(center)
                if len(selected) >= desired:
                    break
            side_positions.extend(selected)
        positions = sorted(set(round(value, 4) for value in side_positions))
    else:
        for span_start, span_end in filtered_side_spans:
            _extend_positions(span_start, span_end)
        positions = sorted(set(round(value, 4) for value in positions))
        if positions:
            from .layout_facade_planning import _balcony_plans_for_side, _facade_window_layouts, _slot_intervals

            front_layout, back_layout, _side_layout, masks = _facade_window_layouts(spec, _spatial_plan(spec))
            blocked_spans: list[tuple[float, float]] = []
            for side_key, layout in (("front", front_layout), ("back", back_layout)):
                balcony_plans = _balcony_plans_for_side(spec, side_key, layout, masks[side_key])
                if not balcony_plans:
                    continue
                slot_intervals = _slot_intervals(spec.width, layout[0], layout[1], layout[2])
                interval_by_idx = {int(slot_index): (float(slot_min), float(slot_max)) for slot_index, slot_min, slot_max in slot_intervals}
                for plan in balcony_plans:
                    member_intervals = [interval_by_idx[idx] for idx in plan.member_indices if idx in interval_by_idx]
                    if not member_intervals:
                        continue
                    blocked_spans.append(
                        (
                            min(item[0] for item in member_intervals) - max(0.18, spec.wall_thickness * 0.6),
                            max(item[1] for item in member_intervals) + max(0.18, spec.wall_thickness * 0.6),
                        )
                    )
            if blocked_spans:
                positions = [
                    value
                    for value in positions
                    if not any(span_start <= value <= span_end for span_start, span_end in blocked_spans)
                ]
    if rear_corridor_span is not None:
        positions = [
            value
            for value in positions
            if not (float(rear_corridor_span[0]) <= float(value) <= float(rear_corridor_span[1]))
        ]
    if len(positions) <= 3:
        return positions
    middle = positions[len(positions) // 2]
    return [positions[0], middle, positions[-1]]


def _slab_center_z(level_z: float, thickness: float):
    return level_z - thickness / 2


def _full_shell_rect(spec) -> tuple[float, float, float, float]:
    return (-float(spec.width) / 2, float(spec.width) / 2, -float(spec.depth) / 2, float(spec.depth) / 2)


def _terrace_open_sides(
    *,
    full_rect: tuple[float, float, float, float],
    upper_shell_rect: tuple[float, float, float, float],
) -> tuple[str, ...]:
    full_x0, full_x1, full_y0, full_y1 = full_rect
    shell_x0, shell_x1, shell_y0, shell_y1 = upper_shell_rect
    epsilon = 1e-4
    open_sides: list[str] = []
    if shell_y0 - full_y0 > epsilon:
        open_sides.append("front")
    if full_y1 - shell_y1 > epsilon:
        open_sides.append("back")
    if shell_x0 - full_x0 > epsilon:
        open_sides.append("left")
    if full_x1 - shell_x1 > epsilon:
        open_sides.append("right")
    return tuple(open_sides)


def _terrace_transition_enabled(spec) -> bool:
    massing_profile = str(getattr(spec, "massing_profile", "")).upper()
    roof_mode = _normalized_roof_mode(getattr(spec, "roof_mode", ROOF_MODE_FLAT))
    return massing_profile == MASSING_PROFILE_TOP_SETBACK or roof_mode == ROOF_MODE_TERRACE


def _terrace_transition_contract(
    spec,
) -> tuple[int | None, tuple[float, float, float, float] | None, tuple[str, ...]]:
    if not _terrace_transition_enabled(spec):
        return None, None, tuple()
    floor_count = int(getattr(spec, "floor_count", 0))
    if floor_count < 2:
        return None, None, tuple()
    upper_shell_rect = _roof_setback_rect(spec)
    if upper_shell_rect is None:
        return None, None, tuple()
    transition_floor_index = floor_count - 1
    open_sides = _terrace_open_sides(full_rect=_full_shell_rect(spec), upper_shell_rect=upper_shell_rect)
    if not open_sides:
        return None, None, tuple()
    return transition_floor_index, upper_shell_rect, open_sides


def _floor_shell_rect(spec, floor_index: int) -> tuple[float, float, float, float]:
    transition_floor_index, upper_shell_rect, _open_sides = _terrace_transition_contract(spec)
    if (
        transition_floor_index is not None
        and upper_shell_rect is not None
        and int(floor_index) == int(transition_floor_index)
    ):
        return upper_shell_rect
    return _full_shell_rect(spec)


def _compress_axis_with_bands(
    *,
    span: float,
    min_shell_span: float,
    lead_band: float,
    trail_band: float,
) -> tuple[float, float]:
    lead = max(0.0, float(lead_band))
    trail = max(0.0, float(trail_band))
    required_shell = min(max(0.0, float(min_shell_span)), max(0.0, float(span)))
    max_band_total = max(0.0, float(span) - required_shell)
    band_total = lead + trail
    if band_total > max_band_total and band_total > 1e-6:
        scale = max_band_total / band_total
        lead *= scale
        trail *= scale
    return lead, trail


def _shift_rect_inside(
    rect: tuple[float, float, float, float],
    full_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x0, x1, y0, y1 = rect
    full_x0, full_x1, full_y0, full_y1 = full_rect
    width = max(0.0, x1 - x0)
    depth = max(0.0, y1 - y0)
    if width >= full_x1 - full_x0:
        x0, x1 = full_x0, full_x1
    else:
        if x0 < full_x0:
            shift = full_x0 - x0
            x0 += shift
            x1 += shift
        if x1 > full_x1:
            shift = x1 - full_x1
            x0 -= shift
            x1 -= shift
    if depth >= full_y1 - full_y0:
        y0, y1 = full_y0, full_y1
    else:
        if y0 < full_y0:
            shift = full_y0 - y0
            y0 += shift
            y1 += shift
        if y1 > full_y1:
            shift = y1 - full_y1
            y0 -= shift
            y1 -= shift
    return (x0, x1, y0, y1)


def _expand_rect_to_cover(
    rect: tuple[float, float, float, float],
    *,
    cover_bounds: tuple[float, float, float, float],
    margin: float,
    full_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x0, x1, y0, y1 = rect
    cover_x0, cover_x1, cover_y0, cover_y1 = cover_bounds
    expanded = (
        min(x0, cover_x0 - margin),
        max(x1, cover_x1 + margin),
        min(y0, cover_y0 - margin),
        max(y1, cover_y1 + margin),
    )
    return _shift_rect_inside(expanded, full_rect)


TERRACE_ENCLOSED_RATIO = 0.7
TERRACE_AREA_RATIO_TOLERANCE = 0.02
TERRACE_CORE_MARGIN_MIN = 0.12
TERRACE_CORE_MARGIN_MAX = 0.22


def _terrace_min_usable_band(spec, *, full_w: float, full_d: float) -> float:
    return max(0.85, min(1.55, min(full_w, full_d) * 0.08, max(0.85, float(spec.wall_thickness) * 7.0)))


def _terrace_core_margin(spec) -> float:
    return max(TERRACE_CORE_MARGIN_MIN, min(TERRACE_CORE_MARGIN_MAX, float(spec.wall_thickness) * 0.9))


def _contains_bounds(
    rect: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
    *,
    margin: float,
) -> bool:
    x0, x1, y0, y1 = rect
    bx0, bx1, by0, by1 = bounds
    return (
        x0 <= bx0 - margin + 1e-4
        and x1 >= bx1 + margin - 1e-4
        and y0 <= by0 - margin + 1e-4
        and y1 >= by1 + margin - 1e-4
    )


def _aligned_axis_start(
    span_start: float,
    span_end: float,
    size: float,
    *,
    placement: str,
    positive_side: str,
    negative_side: str,
) -> float:
    available = max(0.0, float(span_end) - float(span_start))
    clamped_size = min(max(0.0, float(size)), available)
    if clamped_size >= available - 1e-6:
        return float(span_start)
    if placement == positive_side:
        return float(span_end) - clamped_size
    if placement == negative_side:
        return float(span_start)
    return float(span_start) + (available - clamped_size) / 2.0


def _solve_terrace_enclosed_rect(spec, full_rect: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    full_x0, full_x1, full_y0, full_y1 = full_rect
    full_w = max(0.01, full_x1 - full_x0)
    full_d = max(0.01, full_y1 - full_y0)
    full_area = full_w * full_d
    if full_area <= 1e-4:
        return None

    target_area = full_area * TERRACE_ENCLOSED_RATIO
    stair_enabled = bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled)
    core_margin = _terrace_core_margin(spec)
    core_bounds: tuple[float, float, float, float] | None = None
    required_w = 0.0
    required_d = 0.0

    if stair_enabled:
        core_x0, core_x1, core_y0, core_y1, _core_cx, _core_cy = _core_bounds(spec)
        core_bounds = (core_x0, core_x1, core_y0, core_y1)
        required_w = (core_x1 - core_x0) + core_margin * 2.0
        required_d = (core_y1 - core_y0) + core_margin * 2.0

    min_band = _terrace_min_usable_band(spec, full_w=full_w, full_d=full_d)
    placement = str(getattr(getattr(spec, "stair_core", None), "placement", "") or "")

    def _candidate_rect(open_side: str) -> tuple[float, float, float, float] | None:
        if open_side in {"front", "back"}:
            shell_depth = max(required_d, target_area / full_w)
            if shell_depth > full_d + 1e-6:
                return None
            shell_depth = min(shell_depth, full_d)
            shell_width = target_area / shell_depth
            if shell_width > full_w + 1e-6 or shell_width < required_w - 1e-6:
                return None
            shell_width = min(shell_width, full_w)
            x0 = _aligned_axis_start(
                full_x0,
                full_x1,
                shell_width,
                placement=placement,
                positive_side=constants.STAIR_PLACEMENT_BACK_RIGHT,
                negative_side=constants.STAIR_PLACEMENT_BACK_LEFT,
            )
            x1 = x0 + shell_width
            if open_side == "front":
                y1 = full_y1
                y0 = y1 - shell_depth
            else:
                y0 = full_y0
                y1 = y0 + shell_depth
            return (x0, x1, y0, y1)

        shell_width = max(required_w, target_area / full_d)
        if shell_width > full_w + 1e-6:
            return None
        shell_width = min(shell_width, full_w)
        shell_depth = target_area / shell_width
        if shell_depth > full_d + 1e-6 or shell_depth < required_d - 1e-6:
            return None
        shell_depth = min(shell_depth, full_d)
        y0 = _aligned_axis_start(
            full_y0,
            full_y1,
            shell_depth,
            placement=placement,
            positive_side=constants.STAIR_PLACEMENT_BACK_RIGHT,
            negative_side=constants.STAIR_PLACEMENT_FRONT_RIGHT,
        )
        y1 = y0 + shell_depth
        if open_side == "right":
            x0 = full_x0
            x1 = x0 + shell_width
        else:
            x1 = full_x1
            x0 = x1 - shell_width
        return (x0, x1, y0, y1)

    preferred_order = ("front", "back", "left", "right")
    for open_side in preferred_order:
        shell_rect = _candidate_rect(open_side)
        if shell_rect is None:
            continue
        shell_x0, shell_x1, shell_y0, shell_y1 = shell_rect
        band_widths = (
            shell_y0 - full_y0,
            full_y1 - shell_y1,
            shell_x0 - full_x0,
            full_x1 - shell_x1,
        )
        if any(width > 1e-4 and width < min_band for width in band_widths):
            continue
        if abs(((shell_x1 - shell_x0) * (shell_y1 - shell_y0)) / full_area - TERRACE_ENCLOSED_RATIO) > TERRACE_AREA_RATIO_TOLERANCE:
            continue
        if core_bounds is not None and not _contains_bounds(shell_rect, core_bounds, margin=core_margin):
            continue
        open_sides = _terrace_open_sides(full_rect=full_rect, upper_shell_rect=shell_rect)
        if not open_sides or open_side not in open_sides:
            continue
        return shell_rect
    return None


def _roof_setback_rect(spec) -> tuple[float, float, float, float] | None:
    terrace_enabled = _terrace_transition_enabled(spec)
    minimum_floors = 2
    if not terrace_enabled:
        return None
    if spec.floor_count < minimum_floors:
        return None
    full_rect = _full_shell_rect(spec)
    return _solve_terrace_enclosed_rect(spec, full_rect)


def resolve_terrace_feasible_spec(spec):
    if not _terrace_transition_enabled(spec):
        return spec
    if _terrace_transition_contract(spec)[0] is not None:
        return spec

    from .specs import building_spec_from_mapping

    base = spec.to_dict()
    base_width = float(base["width"])
    base_depth = float(base["depth"])
    best = None
    best_score: tuple[float, float, float] | None = None
    step = 0.25
    max_extra = 12.0
    max_steps = int(round(max_extra / step))

    for depth_steps in range(0, max_steps + 1):
        for width_steps in range(0, max_steps + 1):
            if width_steps == 0 and depth_steps == 0:
                continue
            candidate_payload = dict(base)
            candidate_payload["width"] = round(base_width + width_steps * step, 3)
            candidate_payload["depth"] = round(base_depth + depth_steps * step, 3)
            candidate = building_spec_from_mapping(
                candidate_payload,
                building_id=getattr(spec, "building_id", None),
                origin=tuple(getattr(spec, "origin", (0.0, 0.0, 0.0))),
            )
            if _terrace_transition_contract(candidate)[0] is None:
                continue
            area_growth = float(candidate.width * candidate.depth - base_width * base_depth)
            score = (area_growth, candidate.depth - base_depth, candidate.width - base_width)
            if best_score is None or score < best_score:
                best_score = score
                best = candidate
        if best is not None:
            break
    return best or spec


def estimate_footprint_extents(spec, *, include_world_scale: bool = False) -> tuple[float, float, float, float]:
    from .layout_facade_planning import _selected_balcony_sides

    if spec is None:
        raise ValueError("Footprint estimation requires a BuildingSpec.")
    if float(spec.width) <= 0.0 or float(spec.depth) <= 0.0:
        raise ValueError("Footprint estimation requires positive building width and depth.")
    if int(spec.floor_count) <= 0:
        raise ValueError("Footprint estimation requires floor_count >= 1.")
    envelope = _front_entry_envelope(spec)
    balcony_mode = _normalized_balcony_mode(spec.balcony_mode)

    left_extent = max(spec.width / 2, envelope.footprint_left_extent)
    right_extent = max(spec.width / 2, envelope.footprint_right_extent)
    front_extent = max(spec.depth / 2 + GROUND_PLINTH_DEPTH, envelope.front_footprint_extent)
    back_extent = spec.depth / 2 + GROUND_PLINTH_DEPTH

    balcony_depth = 0.0
    if balcony_mode == BALCONY_MODE_SHORT:
        balcony_depth = BALCONY_DEPTH
    elif balcony_mode == BALCONY_MODE_STRIP:
        balcony_depth = BALCONY_STRIP_DEPTH
    if balcony_depth > 0.0 and spec.floor_count > 1:
        balcony_sides = _selected_balcony_sides(spec)
        if "front" in balcony_sides:
            front_extent = max(front_extent, spec.depth / 2 + balcony_depth + 0.08)
        if "back" in balcony_sides:
            back_extent = max(back_extent, spec.depth / 2 + balcony_depth + 0.08)

    if include_world_scale:
        scale = float(getattr(spec, "world_scale", 1.0) or 1.0)
        left_extent *= scale
        right_extent *= scale
        front_extent *= scale
        back_extent *= scale

    return left_extent, right_extent, front_extent, back_extent
