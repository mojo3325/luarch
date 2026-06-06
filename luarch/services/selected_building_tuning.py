from __future__ import annotations

import json

import bpy

from .. import constants, metadata, presets, properties
from ..generator.block_layout import compute_grid_axis_extents, solve_axis_centers
from ..generator.building import (
    create_build_finalize_sequence,
    create_build_preview_sequence,
    plan_building,
)
from ..generator.building_layout import estimate_footprint_extents
from ..generator.layout_facade_planning import entry_stoop_edit_applicability
from ..generator.specs import (
    FACADE_MODE_SPLIT,
    FACADE_MODE_UNIFORM_BRICK,
    FACADE_MODE_UNIFORM_FLAT,
    ROOF_MODE_FLAT,
    ROOF_MODE_TERRACE,
    SUPPORTED_FLAT_FACADE_FAMILIES,
    building_spec_from_mapping,
    building_spec_from_settings,
    normalized_facade_mode,
    normalized_payload_from_mapping,
)
from . import build_scheduler

_COALESCE_SECONDS = 0.12
_MSG_OWNER = object()
_MONITOR_CALLBACK_ID = "selected_building_tuning.monitor"
_SELECTED_PREVIEW_DEDUPE_PREFIX = "selected-preview:"
_PENDING_SCENE_APPLIES: dict[str, tuple[str, str]] = {}
_REBUILDING_SCENES: set[str] = set()
_LAST_ACTIVE_BY_SCENE: dict[str, tuple[str, str]] = {}
_PENDING_SELECTION_SIGNATURES: dict[str, tuple[tuple[str, str], tuple[tuple[str, str], ...]]] = {}
_ERROR_STATUS_PREFIXES = ("Edit blocked:", "Edit rebuild failed:", "Finalize failed:", "Generate failed:")

_FOOTPRINT_OVERLAP_TOLERANCE = 0.02
_BLOCK_AXIS_CLUSTER_TOLERANCE = 0.05
_VISIBLE_MASSING_PROFILES = frozenset(("BOX", "BASE_HEAVY", "TOP_SETBACK", "BALCONY_FACE", "PILOTIS"))
_PAYLOAD_IDENTITY_IGNORE_KEYS = frozenset(("origin", "building_id"))
_FULL_PREVIEW_KEYS = frozenset(
    (
        "width",
        "depth",
        "floor_count",
        "floor_height",
        "wall_thickness",
        "slab_thickness",
        "massing_profile",
        "stair_core_enabled",
        "core_width",
        "core_depth",
        "stair_width",
        "step_count",
        "roof_mode",
    )
)
_FACADE_LOCAL_KEYS = frozenset(
    (
        "facade_family",
        "facade_mode",
        "open_window_ratio",
        "combat_open_window_min",
        "window_policy_manual_override",
        "wide_window_ratio",
        "tactical_facade_profile",
        "ground_floor_tactical_profile",
        "facade_ac_ratio",
    )
)
_ROOF_LOCAL_KEYS = frozenset(
    (
        "parapet_height",
    )
)
_LANE_BLAST_RADIUS = {
    "roof_prop_profile": {"roof"},
    "stair_placement": {"core"},
    "stair_core_variant": {"core"},
    "railing_enabled": {"core"},
    "stair_window_mode": {"core"},
    "door_hinge": {"doors"},
    "door_width": {"doors"},
    "door_height": {"doors"},
    "door_thickness": {"doors"},
    "door_offset_x": {"doors"},
    "door_profile": {"doors"},
    "front_stoop_variant": {"structure", "doors"},
    "rear_stoop_variant": {"structure", "doors"},
}
_STOOP_SIDE_BY_KEY = {
    "front_stoop_variant": "front",
    "rear_stoop_variant": "rear",
}
def _scene_key(scene) -> str:
    return str(getattr(scene, "name_full", "") or getattr(scene, "name", ""))


def _active_object(context=None):
    ctx = context or bpy.context
    view_layer = getattr(ctx, "view_layer", None)
    if view_layer is not None and getattr(view_layer.objects, "active", None) is not None:
        return view_layer.objects.active
    return getattr(ctx, "active_object", None)


def _root_identity(root) -> tuple[str, str]:
    if root is None:
        return "", ""
    return root.name, str(root.get("tbg_building_id", ""))


def _active_identity(context=None) -> tuple[str, str]:
    active = _active_object(context)
    if active is None:
        return "", ""
    root = metadata.resolve_root_from_object(active)
    if root is not None:
        return _root_identity(root)
    return str(getattr(active, "name", "") or ""), ""


def _selection_signature(context=None) -> tuple[tuple[str, str], tuple[tuple[str, str], ...]]:
    ctx = context or bpy.context
    selected_root_identities: set[tuple[str, str]] = set()
    for obj in tuple(getattr(ctx, "selected_objects", ()) or ()):
        root = metadata.resolve_root_from_object(obj)
        if root is None:
            continue
        selected_root_identities.add(_root_identity(root))
    return _active_identity(ctx), tuple(sorted(selected_root_identities))


def _selected_root_from_context(context=None):
    ctx = context or bpy.context
    active_root = metadata.resolve_root_from_object(_active_object(ctx))
    if active_root is not None:
        return active_root
    selected_root = None
    for obj in tuple(getattr(ctx, "selected_objects", ()) or ()):
        candidate = metadata.resolve_root_from_object(obj)
        if candidate is None:
            continue
        if selected_root is None:
            selected_root = candidate
            continue
        if candidate is not selected_root:
            return None
    return selected_root


def _is_root_edit_mode_dirty(root) -> bool:
    return bool(root is not None and root.get("tbg_edit_mode_dirty"))


def _parse_spec_json(payload: str) -> dict:
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _payload_values_equal(left, right) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        try:
            return abs(float(left) - float(right)) <= 1e-6
        except (TypeError, ValueError):
            return left == right
    return left == right


def _changed_payload_keys(current_payload: dict, next_payload: dict) -> set[str]:
    changed = set()
    for key in set(current_payload.keys()) | set(next_payload.keys()):
        if not _payload_values_equal(current_payload.get(key), next_payload.get(key)):
            changed.add(key)
    return changed


def _stoop_side_for_payload_key(key: str) -> str | None:
    return _STOOP_SIDE_BY_KEY.get(str(key).strip())


def _stoop_applicability_from_payload(payload: dict) -> dict[str, dict[str, str | bool]]:
    normalized_payload = normalized_payload_from_mapping(payload)
    spec = building_spec_from_mapping(
        normalized_payload,
        building_id=None,
        origin=(0.0, 0.0, 0.0),
    )
    return entry_stoop_edit_applicability(spec)


def _default_stoop_applicability(reason: str) -> dict[str, dict[str, str | bool]]:
    fallback_reason = str(reason or "stoop applicability is unavailable")
    return {
        "front": {"applicable": False, "reason": fallback_reason},
        "rear": {"applicable": False, "reason": fallback_reason},
    }


def entry_stoop_edit_applicability_from_payload(payload: dict) -> dict[str, dict[str, str | bool]]:
    if not payload:
        return _default_stoop_applicability("resolved payload is missing")
    try:
        return _stoop_applicability_from_payload(payload)
    except Exception as exc:
        return _default_stoop_applicability(f"failed to resolve stoop capability: {exc}")


def _inapplicable_stoop_edit_keys(
    *,
    changed_keys: set[str],
    candidate_payload: dict,
) -> dict[str, str]:
    stoop_changed_keys = [key for key in sorted(changed_keys) if _stoop_side_for_payload_key(key) is not None]
    if not stoop_changed_keys:
        return {}
    applicability = entry_stoop_edit_applicability_from_payload(candidate_payload)
    blocked: dict[str, str] = {}
    for key in stoop_changed_keys:
        side = _stoop_side_for_payload_key(key)
        if side is None:
            continue
        side_info = applicability.get(side, {})
        if bool(side_info.get("applicable", False)):
            continue
        blocked[key] = str(side_info.get("reason", "resolved capability marks this stoop as inapplicable")).strip()
    return blocked


def _normalized_roof_mode_value(value: object) -> str:
    roof_mode = str(value or ROOF_MODE_FLAT).strip().upper()
    return roof_mode or ROOF_MODE_FLAT


def _blocked_roof_mode_reason(
    *,
    settings,
    baseline_payload: dict,
    candidate_payload: dict,
) -> str | None:
    return None


def _spec_dict_from_settings(settings, root) -> dict:
    current_spec_dict = _root_proxy_spec_dict(root)
    selected_facade_family = str(getattr(settings, "facade_family", "LIGHT_BRICK") or "LIGHT_BRICK").upper()
    selected_ratio = float(getattr(settings, "open_window_ratio", current_spec_dict.get("open_window_ratio", 0.62)))
    selected_min = int(getattr(settings, "combat_open_window_min", current_spec_dict.get("combat_open_window_min", 1)))
    current_facade_mode = normalized_facade_mode(
        current_spec_dict.get("facade_mode", getattr(settings, "facade_mode", FACADE_MODE_SPLIT))
    )
    if selected_facade_family in SUPPORTED_FLAT_FACADE_FAMILIES:
        derived_facade_mode = FACADE_MODE_UNIFORM_FLAT
    elif current_facade_mode in {FACADE_MODE_SPLIT, FACADE_MODE_UNIFORM_BRICK}:
        derived_facade_mode = current_facade_mode
    else:
        derived_facade_mode = FACADE_MODE_SPLIT

    planned = plan_building(
        building_spec_from_settings(
            settings,
            building_id=str(root.get("tbg_building_id", "")) or None,
            origin=tuple(root.location),
        )
    )
    spec = planned.spec
    spec_dict = spec.to_dict()
    spec_dict["facade_family"] = selected_facade_family
    spec_dict["facade_mode"] = derived_facade_mode
    spec_dict = plan_building(
        building_spec_from_mapping(
            spec_dict,
            building_id=str(root.get("tbg_building_id", "")) or None,
            origin=tuple(root.location),
        )
    ).spec.to_dict()
    current_payload = _normalized_payload_for_spec_dict(current_spec_dict)
    candidate_payload = _normalized_payload_for_spec_dict(spec_dict)
    manual_window_policy = bool(current_spec_dict.get("window_policy_manual_override", False))
    if current_payload:
        if not _payload_values_equal(current_payload.get("open_window_ratio"), selected_ratio) or not _payload_values_equal(
            current_payload.get("combat_open_window_min"), selected_min
        ):
            manual_window_policy = True
    if current_payload and candidate_payload:
        if not _payload_values_equal(
            current_payload.get("open_window_ratio"),
            candidate_payload.get("open_window_ratio"),
        ) or not _payload_values_equal(
            current_payload.get("combat_open_window_min"),
            candidate_payload.get("combat_open_window_min"),
        ):
            manual_window_policy = True
    if candidate_payload:
        candidate_ratio = float(candidate_payload.get("open_window_ratio", 0.62))
        candidate_min = int(candidate_payload.get("combat_open_window_min", 1))
        if candidate_min == 0 or abs(candidate_ratio) <= 1e-6 or abs(candidate_ratio - 1.0) <= 1e-6:
            manual_window_policy = True
    if manual_window_policy:
        spec_dict["open_window_ratio"] = selected_ratio
        spec_dict["combat_open_window_min"] = selected_min
        spec_dict["window_policy_manual_override"] = True
        spec_dict = plan_building(
            building_spec_from_mapping(
                spec_dict,
                building_id=str(root.get("tbg_building_id", "")) or None,
                origin=tuple(root.location),
            )
        ).spec.to_dict()
    return spec_dict


def _preview_dispatch_for_changed_keys(
    changed_keys: set[str],
) -> tuple[set[str] | None, set[str] | None, set[str] | None]:
    if not changed_keys:
        return set(), set(), None
    local_scopes: set[str] = set()
    affected_lanes: set[str] = set()
    for key in changed_keys:
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        if normalized_key in _FULL_PREVIEW_KEYS:
            return None, None, None
        if normalized_key in _FACADE_LOCAL_KEYS:
            local_scopes.add("facade")
            continue
        if normalized_key in _ROOF_LOCAL_KEYS:
            local_scopes.add("roof")
            continue
        lane_set = _LANE_BLAST_RADIUS.get(normalized_key)
        if lane_set is None:
            return None, None, None
        affected_lanes.update(lane_set)
    if local_scopes and affected_lanes:
        return None, None, None
    if len(local_scopes) > 1:
        return None, None, None
    if "facade" in local_scopes:
        facade_lanes = {"structure"}
        return facade_lanes, facade_lanes, {"facade"}
    if "roof" in local_scopes:
        roof_lanes = {"roof"}
        return roof_lanes, roof_lanes, {"roof"}
    return (affected_lanes or None), (affected_lanes or None), None


def _normalized_payload_for_spec_dict(spec_dict: dict) -> dict:
    if not spec_dict:
        return {}
    payload = normalized_payload_from_mapping(spec_dict)
    for key in _PAYLOAD_IDENTITY_IGNORE_KEYS:
        payload.pop(key, None)
    roof_mode = str(payload.get("roof_mode", ROOF_MODE_FLAT)).upper()
    if roof_mode == ROOF_MODE_TERRACE:
        payload["roof_mode"] = ROOF_MODE_FLAT
    massing_profile = str(payload.get("massing_profile", "BOX")).upper()
    if massing_profile not in _VISIBLE_MASSING_PROFILES:
        payload["massing_profile"] = "BOX"
    return payload


def _binding_matches_root_payload(scene, root) -> bool:
    if scene is None or root is None:
        return False
    proxy = getattr(scene, "tbg_selected_building", None)
    if proxy is None:
        return False
    root_spec_dict = _root_proxy_spec_dict(root)
    if not root_spec_dict:
        return False
    try:
        proxy_spec_dict = _spec_dict_from_settings(proxy, root)
    except Exception:
        return False
    return _normalized_payload_for_spec_dict(root_spec_dict) == _normalized_payload_for_spec_dict(proxy_spec_dict)


def _root_edit_spec_dict(root) -> dict:
    return _parse_spec_json(str(root.get("tbg_edit_spec_json", "") or ""))


def _root_proxy_spec_dict(root) -> dict:
    return metadata.read_effective_spec_dict(root, allow_legacy_dirty=True)


def _footprint_extents(root, spec_dict: dict) -> tuple[float, float, float, float] | None:
    if root is None or not spec_dict:
        return None
    try:
        spec = building_spec_from_mapping(
            spec_dict,
            building_id=str(root.get("tbg_building_id", "")) or None,
            origin=tuple(root.location),
        )
        return estimate_footprint_extents(spec, include_world_scale=True)
    except Exception:
        return None


def _rect_from_center_extents(
    center_x: float,
    center_y: float,
    extents: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    left_extent, right_extent, front_extent, back_extent = extents
    return (
        float(center_x) - float(left_extent),
        float(center_x) + float(right_extent),
        float(center_y) - float(back_extent),
        float(center_y) + float(front_extent),
    )


def _world_footprint_rect(root, spec_dict: dict) -> tuple[float, float, float, float] | None:
    extents = _footprint_extents(root, spec_dict)
    if extents is None:
        return None
    return _rect_from_center_extents(float(root.location.x), float(root.location.y), extents)


def _rects_overlap_2d(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    tol = _FOOTPRINT_OVERLAP_TOLERANCE
    return (
        left[0] < right[1] - tol
        and left[1] > right[0] + tol
        and left[2] < right[3] - tol
        and left[3] > right[2] + tol
    )


def _footprint_overlap_names(scene, root, spec_dict: dict) -> set[str]:
    scene_objects = getattr(scene, "objects", None)
    if scene_objects is None:
        return set()
    root_rect = _world_footprint_rect(root, spec_dict)
    if root_rect is None:
        return set()
    overlaps: set[str] = set()
    for candidate in scene_objects:
        if candidate is root or not metadata.is_root_object(candidate):
            continue
        candidate_spec_dict = _root_proxy_spec_dict(candidate)
        candidate_rect = _world_footprint_rect(candidate, candidate_spec_dict)
        if candidate_rect is None:
            continue
        if _rects_overlap_2d(root_rect, candidate_rect):
            overlaps.add(candidate.name)
    return overlaps


def _collection_contains_descendant(collection, descendant) -> bool:
    if collection is None or descendant is None:
        return False
    if collection is descendant:
        return True
    queue = list(getattr(collection, "children", ()))
    seen: set[str] = set()
    while queue:
        child = queue.pop()
        child_name = str(getattr(child, "name", "") or "")
        if not child_name or child_name in seen:
            continue
        seen.add(child_name)
        if child is descendant:
            return True
        queue.extend(tuple(getattr(child, "children", ())))
    return False


def _root_collection(root):
    if root is None:
        return None
    collection_name = str(root.get(constants.COLLECTION_NAME_KEY, "")).strip()
    if collection_name:
        collection = bpy.data.collections.get(collection_name)
        if collection is not None:
            return collection
    users_collection = tuple(getattr(root, "users_collection", ()) or ())
    if not users_collection:
        return None
    root_prefix = f"{constants.ROOT_COLLECTION_PREFIX}_"
    for collection in users_collection:
        if str(getattr(collection, "name", "")).startswith(root_prefix):
            return collection
    return users_collection[0]


def _block_collection_for_root(root):
    root_collection = _root_collection(root)
    if root_collection is None:
        return None
    block_prefix = f"{constants.BLOCK_COLLECTION_PREFIX}_"
    for collection in sorted(bpy.data.collections, key=lambda item: item.name):
        if not str(getattr(collection, "name", "")).startswith(block_prefix):
            continue
        if _collection_contains_descendant(collection, root_collection):
            return collection
    return None


def _root_in_block_collection(root, block_collection) -> bool:
    root_collection = _root_collection(root)
    if root_collection is None:
        return False
    return _collection_contains_descendant(block_collection, root_collection)


def _is_scene_top_level_root(scene, root) -> bool:
    if scene is None or root is None:
        return False
    root_collection = _root_collection(root)
    if root_collection is None:
        return False
    scene_collection = getattr(scene, "collection", None)
    if scene_collection is None:
        return False
    return scene_collection.children.get(root_collection.name) is not None


def _cluster_axis_values(values_by_building_id: list[tuple[str, float]]):
    if not values_by_building_id:
        return None
    ordered = sorted(values_by_building_id, key=lambda item: (item[1], item[0]))
    groups: list[list[tuple[str, float]]] = []
    for building_id, value in ordered:
        if not groups or abs(value - groups[-1][-1][1]) > _BLOCK_AXIS_CLUSTER_TOLERANCE:
            groups.append([(building_id, float(value))])
            continue
        groups[-1].append((building_id, float(value)))
    centers: list[float] = []
    index_by_building_id: dict[str, int] = {}
    for group_index, group in enumerate(groups):
        centers.append(sum(entry[1] for entry in group) / float(len(group)))
        for building_id, _value in group:
            index_by_building_id[building_id] = group_index
    return centers, index_by_building_id


def _scene_roots_by_building_id(scene) -> dict[str, object]:
    roots: dict[str, object] = {}
    scene_objects = getattr(scene, "objects", None)
    if scene_objects is None:
        return roots
    for obj in scene_objects:
        if not metadata.is_root_object(obj):
            continue
        building_id = str(obj.get("tbg_building_id", "")).strip()
        if not building_id:
            continue
        roots.setdefault(building_id, obj)
    return roots


def _connected_top_level_cohort_roots(scene, edited_root):
    scene_objects = getattr(scene, "objects", None)
    if scene_objects is None:
        return None
    top_level_roots = [
        candidate
        for candidate in scene_objects
        if metadata.is_root_object(candidate)
        and _block_collection_for_root(candidate) is None
        and _is_scene_top_level_root(scene, candidate)
    ]
    if len(top_level_roots) <= 1 or edited_root not in top_level_roots:
        return None

    roots_by_building_id: dict[str, object] = {}
    for candidate in top_level_roots:
        building_id = str(candidate.get("tbg_building_id", "")).strip()
        if not building_id or building_id in roots_by_building_id:
            return None
        roots_by_building_id[building_id] = candidate

    edited_building_id = str(edited_root.get("tbg_building_id", "")).strip()
    if not edited_building_id:
        return None

    x_cluster = _cluster_axis_values(
        [(building_id, float(root.location.x)) for building_id, root in roots_by_building_id.items()]
    )
    y_cluster = _cluster_axis_values(
        [(building_id, float(root.location.y)) for building_id, root in roots_by_building_id.items()]
    )
    if x_cluster is None or y_cluster is None:
        return None

    _x_centers, x_index_by_building_id = x_cluster
    _y_centers, y_index_by_building_id = y_cluster
    x_members: dict[int, set[str]] = {}
    y_members: dict[int, set[str]] = {}
    for building_id in roots_by_building_id:
        x_index = x_index_by_building_id.get(building_id)
        y_index = y_index_by_building_id.get(building_id)
        if x_index is None or y_index is None:
            return None
        x_members.setdefault(x_index, set()).add(building_id)
        y_members.setdefault(y_index, set()).add(building_id)

    cohort_ids: set[str] = set()
    pending = [edited_building_id]
    while pending:
        building_id = pending.pop()
        if building_id in cohort_ids:
            continue
        cohort_ids.add(building_id)
        pending.extend(x_members.get(x_index_by_building_id[building_id], ()))
        pending.extend(y_members.get(y_index_by_building_id[building_id], ()))

    if len(cohort_ids) <= 1:
        return None
    return [roots_by_building_id[building_id] for building_id in sorted(cohort_ids)]


def _live_reflow_cohort_roots(scene, edited_root):
    block_collection = _block_collection_for_root(edited_root)
    scene_objects = getattr(scene, "objects", None)
    if scene_objects is None:
        return None
    if block_collection is not None:
        cohort_roots = [
            candidate
            for candidate in scene_objects
            if metadata.is_root_object(candidate) and _root_in_block_collection(candidate, block_collection)
        ]
        return cohort_roots if len(cohort_roots) > 1 else None
    return _connected_top_level_cohort_roots(scene, edited_root)


def _planned_live_cohort_reflow_positions(
    scene,
    edited_root,
    baseline_spec_dict: dict,
    candidate_spec_dict: dict,
    changed_keys: set[str],
) -> dict[str, tuple[float, float]] | None:
    width_changed = "width" in changed_keys
    depth_changed = "depth" in changed_keys
    if not width_changed and not depth_changed:
        return None

    cohort_roots = _live_reflow_cohort_roots(scene, edited_root)
    if cohort_roots is None or len(cohort_roots) <= 1:
        return None

    edited_building_id = str(edited_root.get("tbg_building_id", "")).strip()
    if not edited_building_id:
        return None

    entries: dict[str, dict] = {}
    for candidate in cohort_roots:
        building_id = str(candidate.get("tbg_building_id", "")).strip()
        if not building_id or building_id in entries:
            return None
        if candidate is edited_root:
            baseline_spec = baseline_spec_dict
            candidate_spec = candidate_spec_dict
        else:
            baseline_spec = _root_proxy_spec_dict(candidate)
            candidate_spec = baseline_spec
        baseline_extents = _footprint_extents(candidate, baseline_spec)
        candidate_extents = _footprint_extents(candidate, candidate_spec)
        if baseline_extents is None or candidate_extents is None:
            return None
        entries[building_id] = {
            "root": candidate,
            "x": float(candidate.location.x),
            "y": float(candidate.location.y),
            "baseline_extents": baseline_extents,
            "candidate_extents": candidate_extents,
        }
    if edited_building_id not in entries:
        return None

    col_cluster = _cluster_axis_values([(building_id, entry["x"]) for building_id, entry in entries.items()])
    row_cluster = _cluster_axis_values([(building_id, entry["y"]) for building_id, entry in entries.items()])
    if col_cluster is None or row_cluster is None:
        return None
    col_centers, col_index_by_building_id = col_cluster
    row_centers, row_index_by_building_id = row_cluster

    row_count = len(row_centers)
    col_count = len(col_centers)
    if row_count <= 0 or col_count <= 0:
        return None

    grid_slots: list[list[str | None]] = [[None for _ in range(col_count)] for _ in range(row_count)]
    for building_id in entries:
        row_index = row_index_by_building_id.get(building_id)
        col_index = col_index_by_building_id.get(building_id)
        if row_index is None or col_index is None:
            return None
        if grid_slots[row_index][col_index] is not None:
            return None
        grid_slots[row_index][col_index] = building_id

    baseline_extent_grid: list[list[tuple[float, float, float, float]]] = []
    candidate_extent_grid: list[list[tuple[float, float, float, float]]] = []
    for row_slots in grid_slots:
        baseline_row: list[tuple[float, float, float, float]] = []
        candidate_row: list[tuple[float, float, float, float]] = []
        for building_id in row_slots:
            if building_id is None:
                baseline_row.append((0.0, 0.0, 0.0, 0.0))
                candidate_row.append((0.0, 0.0, 0.0, 0.0))
                continue
            baseline_row.append(entries[building_id]["baseline_extents"])
            candidate_row.append(entries[building_id]["candidate_extents"])
        baseline_extent_grid.append(baseline_row)
        candidate_extent_grid.append(candidate_row)

    baseline_col_left, baseline_col_right, baseline_row_front, baseline_row_back = compute_grid_axis_extents(
        baseline_extent_grid
    )
    candidate_col_left, candidate_col_right, candidate_row_front, candidate_row_back = compute_grid_axis_extents(
        candidate_extent_grid
    )

    col_gaps = [
        max(
            0.0,
            float(col_centers[col + 1])
            - float(col_centers[col])
            - float(baseline_col_right[col])
            - float(baseline_col_left[col + 1]),
        )
        for col in range(max(0, col_count - 1))
    ]
    row_gaps = [
        max(
            0.0,
            float(row_centers[row + 1])
            - float(row_centers[row])
            - float(baseline_row_back[row])
            - float(baseline_row_front[row + 1]),
        )
        for row in range(max(0, row_count - 1))
    ]

    edited_col_index = col_index_by_building_id[edited_building_id]
    edited_row_index = row_index_by_building_id[edited_building_id]
    next_col_centers = (
        solve_axis_centers(
            negative_extents=candidate_col_left,
            positive_extents=candidate_col_right,
            gaps=col_gaps,
            anchor_index=edited_col_index,
            anchor_center=float(col_centers[edited_col_index]),
        )
        if width_changed
        else list(col_centers)
    )
    next_row_centers = (
        solve_axis_centers(
            negative_extents=candidate_row_back,
            positive_extents=candidate_row_front,
            gaps=row_gaps,
            anchor_index=edited_row_index,
            anchor_center=float(row_centers[edited_row_index]),
        )
        if depth_changed
        else list(row_centers)
    )

    return {
        building_id: (
            float(next_col_centers[col_index_by_building_id[building_id]]),
            float(next_row_centers[row_index_by_building_id[building_id]]),
        )
        for building_id in entries
    }


def _apply_block_reflow_positions(scene, positions_by_building_id: dict[str, tuple[float, float]]) -> int:
    if not positions_by_building_id:
        return 0
    scene_roots = _scene_roots_by_building_id(scene)
    moved = 0
    for building_id, (next_x, next_y) in positions_by_building_id.items():
        root = scene_roots.get(building_id)
        if root is None:
            continue
        if (
            abs(float(root.location.x) - float(next_x)) <= 1e-6
            and abs(float(root.location.y) - float(next_y)) <= 1e-6
        ):
            continue
        root.location.x = float(next_x)
        root.location.y = float(next_y)
        moved += 1
    return moved


def _mark_pending_selection_signature(context=None):
    ctx = context or bpy.context
    scene = getattr(ctx, "scene", None)
    if scene is None:
        return
    _PENDING_SELECTION_SIGNATURES[_scene_key(scene)] = _selection_signature(ctx)


def _selection_changed_since(context, expected_signature) -> bool:
    if expected_signature is None:
        return False
    current_signature = _selection_signature(context)
    if current_signature == expected_signature:
        return False
    # During root rebuild Blender can momentarily drop selection/active object.
    # Treat that transient empty signature as unchanged so restore/reflow can finish.
    if current_signature == (("", ""), ()) and expected_signature[0] != ("", ""):
        return False
    return True


def _clear_binding(scene, *, status: str):
    scene.tbg_selected_root_bound = False
    scene.tbg_selected_root_name = ""
    scene.tbg_selected_root_building_id = ""
    _set_root_status(scene, status, force_redraw=True)
    scene_key = _scene_key(scene)
    _PENDING_SCENE_APPLIES.pop(scene_key, None)
    _PENDING_SELECTION_SIGNATURES.pop(scene_key, None)


def _tag_ui_redraw():
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return
    for window in tuple(getattr(window_manager, "windows", ())):
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in tuple(getattr(screen, "areas", ())):
            if getattr(area, "type", "") in {"VIEW_3D", "PROPERTIES"}:
                area.tag_redraw()


def _set_root_status(scene, status: str, *, force_redraw: bool = False):
    status_text = str(status or "")
    changed = str(getattr(scene, "tbg_selected_root_status", "") or "") != status_text
    scene.tbg_selected_root_status = status_text
    if changed or force_redraw:
        _tag_ui_redraw()


def _resolve_bound_root(scene):
    root_name = str(getattr(scene, "tbg_selected_root_name", "") or "")
    building_id = str(getattr(scene, "tbg_selected_root_building_id", "") or "")
    root = bpy.data.objects.get(root_name) if root_name else None
    if root is not None:
        if metadata.resolve_root_from_object(root) is not root:
            root = None
        elif building_id and str(root.get("tbg_building_id", "")) != building_id:
            root = None
    if root is None and building_id:
        for candidate in bpy.data.objects:
            if metadata.is_root_object(candidate) and str(candidate.get("tbg_building_id", "")) == building_id:
                root = candidate
                break
    return root


def _resolve_root_by_identity(root_identity: tuple[str, str] | None):
    if not root_identity:
        return None
    root_name, building_id = root_identity
    root = bpy.data.objects.get(root_name) if root_name else None
    if root is not None:
        if metadata.resolve_root_from_object(root) is not root:
            root = None
        elif building_id and str(root.get("tbg_building_id", "")) != building_id:
            root = None
    if root is None and building_id:
        for candidate in bpy.data.objects:
            if metadata.is_root_object(candidate) and str(candidate.get("tbg_building_id", "")) == building_id:
                root = candidate
                break
    return root


def _pop_pending_scene_apply(scene_key: str, *, expected_root_identity: tuple[str, str] | None = None) -> None:
    pending_identity = _PENDING_SCENE_APPLIES.get(scene_key)
    if pending_identity is None:
        return
    if expected_root_identity is None or pending_identity == expected_root_identity:
        _PENDING_SCENE_APPLIES.pop(scene_key, None)


def has_bound_root(scene, context=None) -> bool:
    return _resolve_bound_root(scene) is not None


def bound_root_name(scene, context=None) -> str:
    root = _resolve_bound_root(scene)
    return "" if root is None else str(getattr(root, "name", "") or "")


def is_rebuild_pending(scene) -> bool:
    scene_key = _scene_key(scene)
    return scene_key in _PENDING_SCENE_APPLIES or build_scheduler.has_pending_jobs(
        dedupe_key=f"{_SELECTED_PREVIEW_DEDUPE_PREFIX}{scene_key}"
    )


def is_bound_root_dirty(scene, context=None) -> bool:
    return _is_root_edit_mode_dirty(_resolve_bound_root(scene))


def bound_root_state_label(scene, context=None) -> str:
    root = _resolve_bound_root(scene)
    if root is None:
        return "Unbound"
    if is_rebuild_pending(scene):
        return "Pending rebuild"
    if _is_root_edit_mode_dirty(root):
        return "Preview dirty (not committed)"
    return "Finalized"


def binding_status(scene, context=None) -> str:
    root = _resolve_bound_root(scene)
    stored_status = str(getattr(scene, "tbg_selected_root_status", "") or "").strip()
    if root is None:
        return stored_status or "No TBG building selected."
    if stored_status.startswith(_ERROR_STATUS_PREFIXES):
        return stored_status
    state_label = bound_root_state_label(scene).lower()
    return f"Bound to {root.name} ({state_label})."


def selected_preset_label(scene, context=None) -> str:
    if _resolve_bound_root(scene) is None:
        return ""
    proxy = getattr(scene, "tbg_selected_building", None)
    if proxy is None:
        return ""
    return str(getattr(proxy, "preset_id", "") or "")


def bound_stoop_edit_applicability(scene, context=None) -> dict[str, dict[str, str | bool]]:
    root = _resolve_bound_root(scene)
    if root is None:
        return _default_stoop_applicability("no TBG root is currently bound")
    spec_dict = _root_proxy_spec_dict(root)
    if not spec_dict:
        return _default_stoop_applicability("bound root has no stored spec payload")
    payload = _normalized_payload_for_spec_dict(spec_dict)
    if not payload:
        return _default_stoop_applicability("bound root payload could not be normalized")
    return entry_stoop_edit_applicability_from_payload(payload)


def _hydrate_proxy_from_root(scene, root):
    spec_dict = _root_proxy_spec_dict(root)
    if not spec_dict:
        _clear_binding(scene, status="Selected building has no stored spec.")
        return
    scene_key = _scene_key(scene)
    _PENDING_SCENE_APPLIES.pop(scene_key, None)
    _PENDING_SELECTION_SIGNATURES.pop(scene_key, None)
    payload = _normalized_payload_for_spec_dict(spec_dict)
    settings = scene.tbg_selected_building
    pointer = properties.suppress_selected_callback(settings)
    try:
        settings.facade_mode = str(payload.get("facade_mode", getattr(settings, "facade_mode", "SPLIT")))
        presets.apply_payload(settings, payload, include_preset_id=True)
    finally:
        properties.resume_selected_callback(pointer)
    scene.tbg_selected_root_bound = True
    scene.tbg_selected_root_name = root.name
    scene.tbg_selected_root_building_id = str(root.get("tbg_building_id", ""))
    mode_label = " (preview dirty)" if _is_root_edit_mode_dirty(root) else ""
    _set_root_status(scene, f"Bound to {root.name}{mode_label}", force_redraw=True)


def refresh_selected_building_binding(context=None) -> bool:
    ctx = context or bpy.context
    scene = getattr(ctx, "scene", None)
    if scene is None:
        return False
    if _scene_key(scene) in _REBUILDING_SCENES:
        return False
    root = _selected_root_from_context(ctx)
    if root is None:
        _clear_binding(scene, status="No TBG building selected.")
        return True
    current_name, current_id = str(scene.tbg_selected_root_name), str(scene.tbg_selected_root_building_id)
    next_name, next_id = _root_identity(root)
    if (
        bool(scene.tbg_selected_root_bound)
        and current_name == next_name
        and current_id == next_id
        and _binding_matches_root_payload(scene, root)
    ):
        return True
    _hydrate_proxy_from_root(scene, root)
    return True


def select_and_bind_root(context, root):
    if context is None or root is None:
        return
    for obj in list(getattr(context, "selected_objects", ())):
        obj.select_set(False)
    root.select_set(True)
    view_layer = getattr(context, "view_layer", None)
    if view_layer is not None:
        view_layer.objects.active = root
        view_layer.update()
    scene = getattr(context, "scene", None)
    if scene is not None:
        _hydrate_proxy_from_root(scene, root)
        scene_key = _scene_key(scene)
        _LAST_ACTIVE_BY_SCENE[scene_key] = _active_identity(context)
        _PENDING_SELECTION_SIGNATURES.pop(scene_key, None)


def _selection_state_for_root(context, root) -> tuple[set[str], str | None, bool]:
    selected_names = {obj.name for obj in context.selected_objects}
    active_object = _active_object(context)
    active_name = active_object.name if active_object is not None else None
    root_related = False
    for obj in context.selected_objects:
        if metadata.resolve_root_from_object(obj) is root:
            root_related = True
            break
    if not root_related and active_object is not None and metadata.resolve_root_from_object(active_object) is root:
        root_related = True
    return selected_names, active_name, root_related


def _restore_selection_state(
    context,
    root,
    selected_names: set[str],
    active_name: str | None,
    root_related: bool,
    *,
    expected_signature=None,
) -> bool:
    if _selection_changed_since(context, expected_signature):
        return False
    view_layer = context.view_layer
    for obj in list(context.selected_objects):
        obj.select_set(False)
    for name in selected_names:
        obj = bpy.data.objects.get(name)
        if obj is not None and metadata.resolve_root_from_object(obj) is not root:
            obj.select_set(True)
    if root_related and root is not None:
        root.select_set(True)
    active_obj = bpy.data.objects.get(active_name) if active_name else None
    if active_obj is not None and metadata.resolve_root_from_object(active_obj) is not root:
        view_layer.objects.active = active_obj
    elif root_related and root is not None:
        view_layer.objects.active = root
    return True


def _is_bound_to_identity(scene, root_identity: tuple[str, str]) -> bool:
    if scene is None:
        return False
    if not (root_identity[0] or root_identity[1]):
        return False
    return _root_identity(_resolve_bound_root(scene)) == root_identity


def _run_selected_preview_job(scene_name: str, queued_root_identity: tuple[str, str]):
    scene = bpy.data.scenes.get(scene_name)
    if scene is None:
        _pop_pending_scene_apply(scene_name, expected_root_identity=queued_root_identity)
        return True, "Dropped queued selected preview because the scene is gone."
    bound_root = _resolve_bound_root(scene)
    if bound_root is None:
        _pop_pending_scene_apply(scene_name, expected_root_identity=queued_root_identity)
        return True, "Dropped queued selected preview because no root is currently bound."
    if _root_identity(bound_root) != queued_root_identity:
        _pop_pending_scene_apply(scene_name, expected_root_identity=queued_root_identity)
        queued_name = queued_root_identity[0] or "previous root"
        return True, f"Dropped stale queued edit for {queued_name}."
    return _apply_selected_building(scene, queued_root_identity=queued_root_identity)


def _continued_job(*, label: str, dedupe_key: str, execute, delay_seconds: float = 0.0, message: str = ""):
    return build_scheduler.JobContinuation(
        label=label,
        execute=execute,
        delay_seconds=delay_seconds,
        dedupe_key=dedupe_key,
        message=message,
    )


def _apply_selected_building(scene, *, context=None, queued_root_identity: tuple[str, str] | None = None):
    root = _resolve_bound_root(scene)
    if root is None:
        _clear_binding(scene, status="Selected building is no longer available.")
        return False, "Selected building is no longer available."
    bound_identity = _root_identity(root)
    if queued_root_identity is not None and queued_root_identity != bound_identity:
        _pop_pending_scene_apply(_scene_key(scene), expected_root_identity=queued_root_identity)
        queued_name = queued_root_identity[0] or "previous root"
        return True, f"Dropped stale queued edit for {queued_name}."
    ctx = context or bpy.context
    scene_key = _scene_key(scene)
    target_identity = bound_identity
    target_name = target_identity[0] or root.name
    selected_names, active_name, root_related = _selection_state_for_root(ctx, root)
    selection_signature = _selection_signature(ctx)
    _REBUILDING_SCENES.add(scene_key)
    dedupe_key = f"{_SELECTED_PREVIEW_DEDUPE_PREFIX}{scene_key}"

    def _finish_request():
        _REBUILDING_SCENES.discard(scene_key)
        _pop_pending_scene_apply(scene_key, expected_root_identity=queued_root_identity)

    try:
        candidate_spec_dict = _spec_dict_from_settings(scene.tbg_selected_building, root)
        candidate_payload = _normalized_payload_for_spec_dict(candidate_spec_dict)
        if not candidate_payload:
            raise RuntimeError("Failed to build a valid candidate selected-building spec payload.")

        canonical_spec_dict = metadata.read_spec_dict(root)
        if not canonical_spec_dict:
            raise RuntimeError(f"Selected building has no stored spec metadata on {root.name}.")
        baseline_spec_dict = _root_proxy_spec_dict(root)
        if not baseline_spec_dict:
            baseline_spec_dict = canonical_spec_dict
        baseline_payload = _normalized_payload_for_spec_dict(baseline_spec_dict)
        if not baseline_payload:
            raise RuntimeError("Selected building has no valid effective payload for deferred preview diffing.")
        canonical_payload = _normalized_payload_for_spec_dict(canonical_spec_dict)
        if not canonical_payload:
            raise RuntimeError("Selected building has no valid canonical payload for deferred preview diffing.")
        blocked_roof_mode_reason = _blocked_roof_mode_reason(
            settings=scene.tbg_selected_building,
            baseline_payload=baseline_payload,
            candidate_payload=candidate_payload,
        )
        if blocked_roof_mode_reason:
            if _is_bound_to_identity(scene, target_identity):
                if _selection_changed_since(ctx, selection_signature):
                    _mark_pending_selection_signature(ctx)
                    _finish_request()
                    return True, f"Dropped stale queued edit for {target_name}."
                _hydrate_proxy_from_root(scene, root)
                _set_root_status(
                    scene,
                    f"Edit blocked: {blocked_roof_mode_reason}; reverted to current root",
                    force_redraw=True,
                )
                _restore_selection_state(
                    ctx,
                    root,
                    selected_names,
                    active_name,
                    root_related,
                    expected_signature=selection_signature,
                )
                _finish_request()
                return True, f"Blocked unsupported roof-mode edit on {root.name}: {blocked_roof_mode_reason}"
            _finish_request()
            return True, f"Dropped stale queued edit for {target_name}."
        changed_keys = _changed_payload_keys(baseline_payload, candidate_payload)
        candidate_matches_canonical = canonical_payload == candidate_payload
        if not changed_keys:
            if _is_root_edit_mode_dirty(root):
                rebuilt_root = root
                if _is_bound_to_identity(scene, target_identity):
                    if _selection_changed_since(ctx, selection_signature):
                        _mark_pending_selection_signature(ctx)
                        _finish_request()
                        return True, f"Dropped stale queued edit for {target_name}."
                    _restore_selection_state(
                        ctx,
                        rebuilt_root,
                        selected_names,
                        active_name,
                        root_related,
                        expected_signature=selection_signature,
                    )
                    _hydrate_proxy_from_root(scene, rebuilt_root)
                    _set_root_status(scene, f"Preview already up to date for {rebuilt_root.name}.", force_redraw=True)
                    _finish_request()
                    return True, f"Preview already up to date for {rebuilt_root.name}."
                _finish_request()
                return True, f"Dropped stale queued edit for {target_name}."
            if _is_bound_to_identity(scene, target_identity):
                if _selection_changed_since(ctx, selection_signature):
                    _mark_pending_selection_signature(ctx)
                    _finish_request()
                    return True, f"Dropped stale queued edit for {target_name}."
                _restore_selection_state(
                    ctx,
                    root,
                    selected_names,
                    active_name,
                    root_related,
                    expected_signature=selection_signature,
                )
                _set_root_status(scene, f"{root.name} already up to date.", force_redraw=True)
                _finish_request()
                return True, f"No effective selected-tuning changes for {root.name}."
            _finish_request()
            return True, f"Dropped stale queued edit for {target_name}."

        blocked_stoop_keys = _inapplicable_stoop_edit_keys(
            changed_keys=changed_keys,
            candidate_payload=candidate_payload,
        )
        if blocked_stoop_keys:
            blocked_fragments: list[str] = []
            for key in sorted(blocked_stoop_keys):
                side = _stoop_side_for_payload_key(key) or "entry"
                reason = blocked_stoop_keys[key] or "resolved capability marks this stoop as inapplicable"
                blocked_fragments.append(f"{side} stoop ({reason})")
            blocked_summary = "; ".join(blocked_fragments)
            if _is_bound_to_identity(scene, target_identity):
                if _selection_changed_since(ctx, selection_signature):
                    _mark_pending_selection_signature(ctx)
                    return True, f"Dropped stale queued edit for {target_name}."
                _hydrate_proxy_from_root(scene, root)
                _set_root_status(scene, f"Edit blocked: {blocked_summary}; reverted to current root", force_redraw=True)
                _restore_selection_state(
                    ctx,
                    root,
                    selected_names,
                    active_name,
                    root_related,
                    expected_signature=selection_signature,
                )
                return True, (
                    f"Inapplicable selected stoop edit reverted on {root.name}: {blocked_summary}"
                )
            return True, f"Dropped stale queued edit for {target_name}."

        if candidate_matches_canonical and _is_root_edit_mode_dirty(root):
            finalize_spec = building_spec_from_mapping(
                canonical_spec_dict,
                building_id=str(root.get("tbg_building_id", "")) or None,
                origin=tuple(root.location),
            )
            sequence = create_build_finalize_sequence(
                ctx,
                finalize_spec,
                existing_root=root,
                suppress_viewport_emit=True,
            )
            label = f"selected-preview:{target_name}"

            def _finalize_step():
                active_scene = bpy.data.scenes.get(scene_key)
                if active_scene is None:
                    _finish_request()
                    return True, "Dropped queued selected preview because the scene is gone."
                if not _is_bound_to_identity(active_scene, target_identity):
                    _finish_request()
                    return True, f"Dropped stale queued edit for {target_name}."
                try:
                    completed = sequence.step()
                except Exception as exc:
                    if _is_bound_to_identity(active_scene, target_identity):
                        _set_root_status(active_scene, f"Edit rebuild failed: {exc}", force_redraw=True)
                        _finish_request()
                        return False, f"Selected-building edit rebuild failed: {exc}"
                    _finish_request()
                    return True, f"Dropped stale queued edit for {target_name}."
                if not completed:
                    return _continued_job(
                        label=label,
                        dedupe_key=dedupe_key,
                        execute=_finalize_step,
                        message=f"Continuing selected finalize for {target_name}.",
                    )
                rebuilt_root = metadata.resolve_root_from_object(sequence.root_obj) or sequence.root_obj
                if not _is_bound_to_identity(active_scene, target_identity):
                    _finish_request()
                    return True, f"Dropped stale queued edit for {target_name}."
                if _selection_changed_since(ctx, selection_signature):
                    _mark_pending_selection_signature(ctx)
                    _finish_request()
                    return True, f"Dropped stale queued edit for {target_name}."
                _restore_selection_state(
                    ctx,
                    rebuilt_root,
                    selected_names,
                    active_name,
                    root_related,
                    expected_signature=selection_signature,
                )
                _hydrate_proxy_from_root(active_scene, rebuilt_root)
                _set_root_status(active_scene, f"Reverted preview to finalized {rebuilt_root.name}.", force_redraw=True)
                _finish_request()
                return True, f"Reverted preview to finalized {rebuilt_root.name}."

            return _finalize_step()

        reflow_positions = _planned_live_cohort_reflow_positions(
            scene,
            root,
            baseline_spec_dict=baseline_spec_dict,
            candidate_spec_dict=candidate_spec_dict,
            changed_keys=changed_keys,
        )
        if reflow_positions is None:
            baseline_overlaps = _footprint_overlap_names(scene, root, baseline_spec_dict)
            candidate_overlaps = _footprint_overlap_names(scene, root, candidate_spec_dict)
            introduced_overlaps = sorted(candidate_overlaps - baseline_overlaps)
            if introduced_overlaps:
                overlap_label = ", ".join(introduced_overlaps[:3])
                if len(introduced_overlaps) > 3:
                    overlap_label += ", ..."
                if _is_bound_to_identity(scene, target_identity):
                    if _selection_changed_since(ctx, selection_signature):
                        _mark_pending_selection_signature(ctx)
                        return True, f"Dropped stale queued edit for {target_name}."
                    _hydrate_proxy_from_root(scene, root)
                    _set_root_status(
                        scene,
                        f"Edit blocked: footprint overlaps {overlap_label}; reverted to current root",
                        force_redraw=True,
                    )
                    _restore_selection_state(
                        ctx,
                        root,
                        selected_names,
                        active_name,
                        root_related,
                        expected_signature=selection_signature,
                    )
                    return False, f"Selected-building edit blocked by sibling overlap: {overlap_label}"
                return True, f"Dropped stale queued edit for {target_name}."

        clear_lanes, emit_lanes, scoped_preview_tags = _preview_dispatch_for_changed_keys(changed_keys)
        preview_spec = building_spec_from_mapping(
            candidate_spec_dict,
            building_id=str(root.get("tbg_building_id", "")) or None,
            origin=tuple(root.location),
        )
        sequence = create_build_preview_sequence(
            ctx,
            preview_spec,
            existing_root=root,
            clear_lanes=clear_lanes,
            emit_lanes=emit_lanes,
            clear_scopes=scoped_preview_tags,
            emit_scopes=scoped_preview_tags,
            suppress_viewport_emit=True,
        )
        label = f"selected-preview:{target_name}"

        def _preview_step():
            active_scene = bpy.data.scenes.get(scene_key)
            if active_scene is None:
                _finish_request()
                return True, "Dropped queued selected preview because the scene is gone."
            if not _is_bound_to_identity(active_scene, target_identity):
                _finish_request()
                return True, f"Dropped stale queued edit for {target_name}."
            try:
                completed = sequence.step()
            except Exception as exc:
                if _is_bound_to_identity(active_scene, target_identity):
                    _set_root_status(active_scene, f"Edit rebuild failed: {exc}", force_redraw=True)
                    _finish_request()
                    return False, f"Selected-building edit rebuild failed: {exc}"
                _finish_request()
                return True, f"Dropped stale queued edit for {target_name}."
            if not completed:
                return _continued_job(
                    label=label,
                    dedupe_key=dedupe_key,
                    execute=_preview_step,
                    message=f"Continuing selected preview for {target_name}.",
                )
            rebuilt_root = _resolve_bound_root(active_scene) or metadata.resolve_root_from_object(sequence.root_obj) or sequence.root_obj
            if not _is_bound_to_identity(active_scene, target_identity):
                _finish_request()
                return True, f"Dropped stale queued edit for {target_name}."
            if _selection_changed_since(ctx, selection_signature):
                _mark_pending_selection_signature(ctx)
                _finish_request()
                return True, f"Dropped stale queued edit for {target_name}."
            reflow_moved = 0
            if reflow_positions is not None:
                reflow_moved = _apply_block_reflow_positions(active_scene, reflow_positions)
            _restore_selection_state(
                ctx,
                rebuilt_root,
                selected_names,
                active_name,
                root_related,
                expected_signature=selection_signature,
            )
            _hydrate_proxy_from_root(active_scene, rebuilt_root)
            reflow_label = f", reflow {reflow_moved} roots" if reflow_moved > 0 else ""
            _set_root_status(active_scene, f"Preview updated for {rebuilt_root.name}{reflow_label}", force_redraw=True)
            _finish_request()
            return True, f"Preview updated for {rebuilt_root.name}{reflow_label}."

        return _preview_step()
    except Exception as exc:
        if _is_bound_to_identity(scene, target_identity):
            _set_root_status(scene, f"Edit rebuild failed: {exc}", force_redraw=True)
            _finish_request()
            return False, f"Selected-building edit rebuild failed: {exc}"
        _finish_request()
        return True, f"Dropped stale queued edit for {target_name}."


def ensure_root_finalized(context, root, *, require_authoritative_payload: bool = False):
    if root is None:
        raise ValueError("Finalize requires a valid building root.")

    scene = getattr(context, "scene", None)
    if scene is not None and _resolve_bound_root(scene) is root and is_rebuild_pending(scene):
        success, message = build_scheduler.flush(
            force_ready=True,
        )
        if not success:
            raise RuntimeError(message)
        root = _resolve_bound_root(scene) or _resolve_root_by_identity(_root_identity(root)) or root

    if not _is_root_edit_mode_dirty(root):
        if require_authoritative_payload:
            try:
                metadata.read_voxel_wall_occupancy_payload(root, strict=True)
            except metadata.MetadataContractError as exc:
                raise RuntimeError(f"{root.name} has no fresh authored wall payload: {exc}") from exc
        return root, False

    root_identity = _root_identity(root)
    scene_key = _scene_key(scene) if scene is not None else ""
    finalize_spec_dict = _root_edit_spec_dict(root)
    if not finalize_spec_dict:
        raise RuntimeError(f"Dirty edit-mode snapshot is missing on {root.name}.")
    finalize_spec = building_spec_from_mapping(
        finalize_spec_dict,
        building_id=str(root.get("tbg_building_id", "")) or None,
        origin=tuple(root.location),
    )
    sequence = create_build_finalize_sequence(
        context,
        finalize_spec,
        existing_root=root,
        suppress_viewport_emit=True,
    )

    def _finalize_job():
        target_root = _resolve_root_by_identity(root_identity)
        if target_root is None:
            missing_name = root_identity[0] or "root"
            return False, f"Finalize failed: {missing_name} is no longer available."
        try:
            completed = sequence.step()
        except Exception as exc:
            return False, f"Finalize failed: {exc}"
        if not completed:
            return _continued_job(
                label=f"finalize:{root_identity[0] or 'selected-root'}",
                dedupe_key=f"finalize:{root_identity[1] or root_identity[0]}",
                execute=_finalize_job,
                message=f"Continuing finalize for {target_root.name}.",
            )
        rebuilt_root = metadata.resolve_root_from_object(sequence.root_obj) or sequence.root_obj

        target_scene = bpy.data.scenes.get(scene_key) if scene_key else None
        if target_scene is not None and _is_bound_to_identity(target_scene, root_identity):
            _hydrate_proxy_from_root(target_scene, rebuilt_root)
            _set_root_status(target_scene, f"Finalized {rebuilt_root.name}", force_redraw=True)
        return True, f"Finalized {rebuilt_root.name}"

    build_scheduler.enqueue_job(
        label=f"finalize:{root_identity[0] or 'selected-root'}",
        execute=_finalize_job,
        dedupe_key=f"finalize:{root_identity[1] or root_identity[0]}",
        replace_dedupe=True,
    )
    success, message = build_scheduler.flush(force_ready=True)
    if not success:
        raise RuntimeError(message)
    finalized_root = _resolve_root_by_identity(root_identity)
    if finalized_root is None:
        raise RuntimeError("Finalize completed but target root can no longer be resolved.")
    if _is_root_edit_mode_dirty(finalized_root):
        raise RuntimeError(f"Finalize did not clear edit-mode dirty state on {finalized_root.name}.")
    if require_authoritative_payload:
        try:
            metadata.read_voxel_wall_occupancy_payload(finalized_root, strict=True)
        except metadata.MetadataContractError as exc:
            raise RuntimeError(f"{finalized_root.name} has no fresh authored wall payload after finalize: {exc}") from exc
    return finalized_root, True


def apply_selected_building(scene, *, context=None):
    ctx = context or bpy.context
    root = _resolve_bound_root(scene)
    if root is None:
        _clear_binding(scene, status="Selected building is no longer available.")
        return False, "Selected building is no longer available."

    if is_rebuild_pending(scene):
        success, message = build_scheduler.flush(force_ready=True)
        if not success:
            return False, message
        root = _resolve_bound_root(scene) or root

    try:
        finalized_root, finalized = ensure_root_finalized(ctx, root)
    except Exception as exc:
        _set_root_status(scene, f"Finalize failed: {exc}", force_redraw=True)
        return False, f"Finalize failed: {exc}"
    if finalized:
        return True, f"Finalized {finalized_root.name}"
    _set_root_status(scene, f"{finalized_root.name} already finalized.", force_redraw=True)
    return True, f"{finalized_root.name} is already finalized."


def _scheduler_monitor_tick():
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return
    scene_key = _scene_key(scene)
    active_signature = _selection_signature()
    pending_signature = _PENDING_SELECTION_SIGNATURES.get(scene_key)
    if pending_signature is not None and pending_signature != active_signature:
        _PENDING_SELECTION_SIGNATURES[scene_key] = active_signature
    if pending_signature is not None:
        if refresh_selected_building_binding():
            _PENDING_SELECTION_SIGNATURES.pop(scene_key, None)
            _LAST_ACTIVE_BY_SCENE[scene_key] = active_signature[0]
        return
    active_identity = active_signature[0]
    if _LAST_ACTIVE_BY_SCENE.get(scene_key) != active_identity and refresh_selected_building_binding():
        _LAST_ACTIVE_BY_SCENE[scene_key] = active_identity


def on_selected_proxy_changed(scene):
    if scene is None or not bool(getattr(scene, "tbg_selected_root_bound", False)):
        return
    if _scene_key(scene) in _REBUILDING_SCENES:
        return
    root = _resolve_bound_root(scene)
    if root is None:
        _clear_binding(scene, status="Selected building is no longer available.")
        return
    baseline_spec_dict = _root_proxy_spec_dict(root)
    if baseline_spec_dict:
        baseline_payload = _normalized_payload_for_spec_dict(baseline_spec_dict)
        if baseline_payload:
            candidate_spec_dict = _spec_dict_from_settings(scene.tbg_selected_building, root)
            candidate_payload = _normalized_payload_for_spec_dict(candidate_spec_dict)
            blocked_roof_mode_reason = _blocked_roof_mode_reason(
                settings=scene.tbg_selected_building,
                baseline_payload=baseline_payload,
                candidate_payload=candidate_payload,
            )
            if blocked_roof_mode_reason:
                _hydrate_proxy_from_root(scene, root)
                _set_root_status(
                    scene,
                    f"Edit blocked: {blocked_roof_mode_reason}; reverted to current root",
                    force_redraw=True,
                )
                _PENDING_SCENE_APPLIES.pop(_scene_key(scene), None)
                return
    scene_key = _scene_key(scene)
    queued_root_identity = _root_identity(root)
    _PENDING_SCENE_APPLIES[scene_key] = queued_root_identity
    build_scheduler.enqueue_job(
        label=f"selected-preview:{queued_root_identity[0] or scene_key}",
        execute=lambda scene_name=scene_key, root_identity=queued_root_identity: _run_selected_preview_job(
            scene_name,
            root_identity,
        ),
        delay_seconds=_COALESCE_SECONDS,
        dedupe_key=f"{_SELECTED_PREVIEW_DEDUPE_PREFIX}{scene_key}",
        replace_dedupe=True,
    )


def _selection_msgbus_notify():
    _mark_pending_selection_signature()


def register():
    build_scheduler.register()
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.LayerObjects, "active"),
        owner=_MSG_OWNER,
        args=(),
        notify=_selection_msgbus_notify,
        options={"PERSISTENT"},
    )
    build_scheduler.register_maintenance_callback(_MONITOR_CALLBACK_ID, _scheduler_monitor_tick)
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        scene_key = _scene_key(scene)
        _LAST_ACTIVE_BY_SCENE[scene_key] = _active_identity()
        _PENDING_SELECTION_SIGNATURES[scene_key] = _selection_signature()


def unregister():
    bpy.msgbus.clear_by_owner(_MSG_OWNER)
    build_scheduler.unregister_maintenance_callback(_MONITOR_CALLBACK_ID)
    _PENDING_SCENE_APPLIES.clear()
    _PENDING_SELECTION_SIGNATURES.clear()
    _REBUILDING_SCENES.clear()
    _LAST_ACTIVE_BY_SCENE.clear()
