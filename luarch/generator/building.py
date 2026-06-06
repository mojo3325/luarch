from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from collections import OrderedDict
from copy import deepcopy
from typing import Callable

import bpy
from mathutils import Euler, Vector

from .. import constants, export_contract, metadata, naming
from ..generation_summary import (
    SummaryChildSnapshot,
    build_generation_summary as _build_generation_summary,
    snapshot_summary_child,
)
from ..services import cleanup, collections as collection_service
from . import materials
from .building_core import (
    _build_core_partitions,
    _build_floor_pieces,
    _build_stair_step,
    _build_stairs,
    _build_under_construction_frame,
    _build_wide_room_partitions,
)
from .building_facade import (
    _derive_facade_facts,
    _build_facade_bands,
    _build_foundation_podium,
    _build_main_door,
    _build_outer_shell,
    _build_outer_shell_floor_side,
    _build_wall_service_pipes,
)
from .building_layout import (
    _spatial_plan,
    resolve_terrace_feasible_spec,
)
from .layout_facade_planning import (
    _effective_entrance_profile,
    _is_industrial_frontage,
    _uses_wood_floor_material,
)
from .specs import normalized_facade_family as _normalized_facade_family
from .building_occupancy import (
    OccupancyAuthoringSession,
    serialize_authored_wall_cell_payload,
)
from .building_output import (
    _FRAGMENT_PROFILE_KEY,
    _FRAGMENT_RUN_AXIS_KEY,
    _FRAGMENT_TILE_U_KEY,
    _FRAGMENT_TILE_V_KEY,
    _build_runtime_markers,
    create_final_section_sink,
    final_section_object_name,
    iter_final_section_objects,
    iter_runtime_marker_objects,
    emit_visible_authored_wall_sections_from_canonicalization,
    authored_visible_wall_section_registry_entries,
    _preserved_exterior_shell_hint_for_object,
    clone_final_sections_for_exact_spec_reuse,
    _retile_dirty_brick_sections,
    _set_generated_wall_visibility,
    FinalSectionSink,
    iter_dirty_brick_sections,
    retile_dirty_brick_section,
)
from .building_roof import (
    _build_roof,
    _build_roof_exit,
    _build_roof_props,
)
from .building_support import (
    _apply_uniform_world_scale,
    composite_part_root_local_bounds,
    object_local_bounds,
    output_ledger_scope,
    resolve_authored_voxel_wall_material_metadata,
    section_sink_scope,
)
from .runtime_markers import RuntimeMarkerEmitter

_AUTHORING_LANES = frozenset(("structure", "core", "roof", "doors"))
_LANE_COLLECTION_KEYS = frozenset(("structure", "core", "roof", "doors", "helpers"))
_PREVIEW_SCOPE_TAGS = frozenset(("structure_base", "facade", "core", "roof", "roof_exit", "roof_props", "doors"))
_EXACT_SPEC_REUSE_CACHE_MAX_ENTRIES = 64
_EXACT_SPEC_REUSE_CACHE: "OrderedDict[str, _ExactSpecReuseEntry]" = OrderedDict()
_EXACT_SPEC_REUSE_STATS = {
    "lookups": 0,
    "hits": 0,
    "misses": 0,
    "stores": 0,
    "evictions": 0,
    "invalidations": 0,
}
_PLAN_MEMO_CACHE_MAX_ENTRIES = 128
_PLAN_MEMO_CACHE: "OrderedDict[str, _PlanMemoEntry]" = OrderedDict()
_PLAN_MEMO_STATS = {
    "lookups": 0,
    "hits": 0,
    "misses": 0,
    "stores": 0,
    "evictions": 0,
}
_STRUCTURAL_EXACT_SPEC_REUSE_DISABLED = True
_TRAVERSAL_RUNTIME_ROLES = frozenset(
    {
        export_contract.ROLE_ATTIC_OPENING,
        export_contract.ROLE_BALCONY_ACCESS_OPENING,
        export_contract.ROLE_ENTRY_LANDING,
        export_contract.ROLE_ENTRY_WEDGE,
        export_contract.ROLE_FLOOR_BLOCKER,
        export_contract.ROLE_OPEN_WINDOW_OPENING,
        export_contract.ROLE_PODIUM_BLOCKER,
        export_contract.ROLE_ROOF_EXIT_PLATFORM,
        export_contract.ROLE_STAIR_LANDING,
        export_contract.ROLE_STAIR_RAMP,
        export_contract.ROLE_STAIR_STEP,
    }
)


@dataclass(frozen=True)
class BuildingPlan:
    spec: object
    spatial_plan: object
    facade_facts: dict
    exact_spec_key: str


@dataclass(frozen=True)
class _ExactSpecReuseEntry:
    key: str
    source_root_name: str
    source_prefix: str
    finalized_source: bool
    generation_summary: dict
    summary_children: tuple[SummaryChildSnapshot, ...]
    section_registry: dict


@dataclass(frozen=True)
class _PlanMemoEntry:
    key: str
    spatial_plan: object
    facade_facts: dict


@dataclass
class BuildLaneState:
    plan: BuildingPlan
    spec: object
    spatial_plan: object
    building_id: str
    hierarchy: dict
    root_collection: object
    root_obj: object
    materials_map: dict
    prefix: str
    interior_wall_material: object
    runtime_emitter: object | None
    facade_facts: dict
    output_ledger: "BuildOutputLedger | None"
    section_sink: FinalSectionSink | None
    occupancy_author: OccupancyAuthoringSession
    exact_spec_key: str
    exact_reuse_applied: bool
    exact_reuse_source_root_name: str
    exact_reuse_runtime_markers_cloned: bool
    cached_generation_summary: dict | None
    cached_summary_children: tuple[SummaryChildSnapshot, ...] | None
    cached_section_registry: dict | None
    enable_preview_exact_spec_reuse: bool
    final_occupancy_canonicalization: object | None = None
    final_visible_wall_cell_count: int | None = None


class _TraversalRuntimeEmitter:
    def __init__(self, emitter: RuntimeMarkerEmitter):
        self._emitter = emitter

    def emit_box(self, *, role: str, **kwargs):
        if str(role) not in _TRAVERSAL_RUNTIME_ROLES:
            return None
        return self._emitter.emit_box(role=role, **kwargs)

    def emit_wedge(self, *, role: str, **kwargs):
        if str(role) not in _TRAVERSAL_RUNTIME_ROLES:
            return None
        return self._emitter.emit_wedge(role=role, **kwargs)

    def emit_composite_boxes(self, *, role: str | None = None, roles=None, **kwargs):
        if roles is not None:
            if any(str(part_role) not in _TRAVERSAL_RUNTIME_ROLES for part_role in roles):
                return []
            return self._emitter.emit_composite_boxes(roles=roles, **kwargs)
        if role is None or str(role) not in _TRAVERSAL_RUNTIME_ROLES:
            return []
        return self._emitter.emit_composite_boxes(role=role, **kwargs)


@dataclass(frozen=True)
class _SectionRegistration:
    object_name: str
    bucket: str
    merge_allowed: bool
    hide_with_walls: bool


@dataclass(frozen=True)
class _FrozenSectionRegistration:
    object_name: str
    bucket: str
    merge_allowed: bool
    hide_with_walls: bool
    material_name: str
    material_family: str | None
    visual_style: str | None
    display_color_rgb: dict[str, int] | None
    material_is_brick: bool
    fragment_profile: str
    fragment_tile_u: float | None
    fragment_tile_v: float | None
    fragment_run_axis: str | None
    bounds: tuple[float, float, float, float, float, float]
    part_bounds: tuple[tuple[float, float, float, float, float, float], ...]
    preserved_shell: bool
    roof_exit_shell: bool
    top_room_floor: bool
    stair_flight: bool
    stair_direction: float | None
    entrance_part: str
    facade_side: str


class BuildOutputLedger:
    """Canonical authoring-time semantic ledger for final output closeout."""

    _TOKEN_KEY = "_tbg_output_ledger_token"

    def __init__(self, prefix: str, root_obj, *, world_scale: float | None = None):
        self._prefix = str(prefix)
        self._root_obj = root_obj
        self._world_scale = float(world_scale) if world_scale is not None else None
        self._pending_object_tokens: set[int] = set()
        self._pending_objects: list[bpy.types.Object] = []
        self._section_registrations: dict[int, _SectionRegistration] = {}
        self._summary_order: list[int] = []
        self._summary_snapshots: dict[int, SummaryChildSnapshot] = {}
        self._frozen_sections: dict[int, _FrozenSectionRegistration] = {}
        self._next_token = 1

    def _token_for_object(self, obj) -> int:
        token = obj.get(self._TOKEN_KEY)
        if token is None:
            token = int(self._next_token)
            self._next_token += 1
            obj[self._TOKEN_KEY] = int(token)
        return int(token)

    def queue_authored_object(self, obj) -> None:
        if obj is None or obj.type != "MESH":
            return
        token = self._token_for_object(obj)
        if token in self._pending_object_tokens:
            return
        self._pending_object_tokens.add(token)
        self._pending_objects.append(obj)

    def register_section_object(self, obj, *, bucket: str, merge_allowed: bool, hide_with_walls: bool) -> None:
        if obj is None or obj.type != "MESH":
            return
        token = self._token_for_object(obj)
        self._section_registrations[token] = _SectionRegistration(
            object_name=str(obj.name),
            bucket=str(bucket),
            merge_allowed=bool(merge_allowed),
            hide_with_walls=bool(hide_with_walls),
        )
        self.queue_authored_object(obj)

    def flush_pending_objects(self) -> int:
        pending = tuple(self._pending_objects)
        self._pending_objects.clear()
        self._pending_object_tokens.clear()
        for obj in pending:
            if obj is None or obj.type != "MESH":
                continue
            if obj.name not in bpy.data.objects:
                continue
            token = self._token_for_object(obj)
            if token not in self._summary_snapshots:
                self._summary_order.append(token)
            self._summary_snapshots[token] = snapshot_summary_child(self._root_obj, obj)
            section_registration = self._section_registrations.get(token)
            if section_registration is None:
                continue
            material = obj.material_slots[0].material if obj.material_slots else None
            material_name = _material_name_for_object(obj)
            voxel_wall_material_metadata = None
            if section_registration.bucket in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
                voxel_wall_material_metadata = resolve_authored_voxel_wall_material_metadata(material_name)
                if voxel_wall_material_metadata is None:
                    raise RuntimeError(
                        f"Voxel wall source '{obj.name}' is missing canonical material metadata for material '{material_name}'."
                    )
            self._frozen_sections[token] = _FrozenSectionRegistration(
                object_name=str(obj.name),
                bucket=section_registration.bucket,
                merge_allowed=section_registration.merge_allowed,
                hide_with_walls=section_registration.hide_with_walls,
                material_name=material_name,
                material_family=(
                    str(voxel_wall_material_metadata.material_family)
                    if voxel_wall_material_metadata is not None
                    else None
                ),
                visual_style=(
                    str(voxel_wall_material_metadata.visual_style)
                    if voxel_wall_material_metadata is not None and voxel_wall_material_metadata.visual_style
                    else None
                ),
                display_color_rgb=(
                    dict(voxel_wall_material_metadata.display_color_rgb)
                    if voxel_wall_material_metadata is not None and voxel_wall_material_metadata.display_color_rgb is not None
                    else None
                ),
                material_is_brick=bool(material.get("tbg_is_brick")) if material is not None else False,
                fragment_profile=str(obj.get(_FRAGMENT_PROFILE_KEY, "")),
                fragment_tile_u=(
                    float(obj.get(_FRAGMENT_TILE_U_KEY))
                    if obj.get(_FRAGMENT_TILE_U_KEY) is not None
                    else None
                ),
                fragment_tile_v=(
                    float(obj.get(_FRAGMENT_TILE_V_KEY))
                    if obj.get(_FRAGMENT_TILE_V_KEY) is not None
                    else None
                ),
                fragment_run_axis=(
                    str(obj.get(_FRAGMENT_RUN_AXIS_KEY))
                    if obj.get(_FRAGMENT_RUN_AXIS_KEY) not in {None, ""}
                    else None
                ),
                bounds=tuple(round(value, 4) for value in object_local_bounds(self._root_obj, obj)),
                part_bounds=tuple(
                    tuple(round(float(value), 4) for value in bounds)
                    for bounds in composite_part_root_local_bounds(self._root_obj, obj)
                ),
                preserved_shell=bool(_preserved_exterior_shell_hint_for_object(obj)),
                roof_exit_shell=bool(obj.get("tbg_roof_exit_shell")),
                top_room_floor=bool(obj.get("tbg_top_room_floor")),
                stair_flight=bool(obj.get("tbg_stair_flight")),
                stair_direction=(
                    float(obj.get("tbg_stair_direction"))
                    if obj.get("tbg_stair_direction") is not None
                    else None
                ),
                entrance_part=str(obj.get("tbg_entrance_part", "") or ""),
                facade_side=str(obj.get("tbg_facade_side", "") or ""),
            )
        return len(pending)

    def summary_children(self) -> tuple[SummaryChildSnapshot, ...]:
        return tuple(
            self._summary_snapshots[token]
            for token in self._summary_order
            if token in self._summary_snapshots
        )

    def section_registry(self) -> dict:
        merged_entries: dict[tuple[str, str], dict] = {}
        standalone_entries: list[dict] = []
        for section in self._frozen_sections.values():
            section_bucket = str(section.bucket)
            if section_bucket in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
                continue
            fragment_entry = {
                "source_name": str(section.object_name),
                "bounds": [float(value) for value in section.bounds],
                "part_bounds": [
                    [float(value) for value in bounds]
                    for bounds in section.part_bounds
                ],
                "preserved_shell": bool(section.preserved_shell),
                "material_family": str(section.material_family) if section.material_family is not None else None,
                "visual_style": str(section.visual_style) if section.visual_style is not None else None,
                "display_color_rgb": dict(section.display_color_rgb) if section.display_color_rgb is not None else None,
                "fragment_profile": str(section.fragment_profile or ""),
                "fragment_tile_u": float(section.fragment_tile_u) if section.fragment_tile_u is not None else None,
                "fragment_tile_v": float(section.fragment_tile_v) if section.fragment_tile_v is not None else None,
                "fragment_run_axis": str(section.fragment_run_axis) if section.fragment_run_axis is not None else None,
                "roof_exit_shell": bool(section.roof_exit_shell),
                "top_room_floor": bool(section.top_room_floor),
                "stair_flight": bool(section.stair_flight),
                "stair_direction": float(section.stair_direction) if section.stair_direction is not None else None,
                "entrance_part": str(section.entrance_part),
                "facade_side": str(section.facade_side),
            }
            base_entry = {
                "bucket": section_bucket,
                "material_name": section.material_name,
                "material_family": str(section.material_family) if section.material_family is not None else None,
                "visual_style": str(section.visual_style) if section.visual_style is not None else None,
                "display_color_rgb": dict(section.display_color_rgb) if section.display_color_rgb is not None else None,
                "merge_allowed": bool(section.merge_allowed),
                "hide_with_walls": bool(section.hide_with_walls),
                "preserved_shell": bool(section.preserved_shell),
                "roof_exit_shell": bool(section.roof_exit_shell),
                "top_room_floor": bool(section.top_room_floor),
                "bounds": [float(value) for value in section.bounds],
                "source_fragments": [fragment_entry] if not section.merge_allowed else [],
            }
            if section.merge_allowed:
                key = (section_bucket, section.material_name)
                merged = merged_entries.get(key)
                if merged is None:
                    merged = {
                        **base_entry,
                        "name": final_section_object_name(self._prefix, section_bucket, section.material_name),
                        "source_count": 0,
                    }
                    merged_entries[key] = merged
                merged["source_count"] += 1
                merged["preserved_shell"] = bool(merged["preserved_shell"] or section.preserved_shell)
                merged["roof_exit_shell"] = bool(merged["roof_exit_shell"] or section.roof_exit_shell)
                merged["top_room_floor"] = bool(merged["top_room_floor"] or section.top_room_floor)
                merged["bounds"] = _merge_registry_bounds(merged["bounds"], section.bounds)
                merged["source_fragments"].append(fragment_entry)
                continue
            standalone_entries.append(
                {
                    **base_entry,
                    "name": section.object_name,
                    "source_count": 1,
                }
            )
        sections = sorted(
            [*merged_entries.values(), *standalone_entries],
            key=lambda item: (str(item["bucket"]), str(item["material_name"]), str(item["name"])),
        )
        return {
            "schema_version": 2,
            "section_count": len(sections),
            "sections": sections,
        }


@dataclass
class BuildRuntimeSequence:
    context: object
    plan: BuildingPlan
    existing_root: object = None
    parent_collection: object = None
    clear_lanes: set[str] | None = None
    clear_scopes: set[str] | None = None
    emit_lanes: set[str] | None = None
    emit_scopes: set[str] | None = None
    suppress_viewport_emit: bool = True
    emit_runtime_markers: bool = False
    reuse_existing_preview: bool = False
    enable_preview_exact_spec_reuse: bool = False
    used_exact_spec_reuse: bool = False
    _state: BuildLaneState | None = None
    _ops: list[Callable[[], None]] | None = None

    @property
    def root_obj(self):
        if self._state is not None:
            return self._state.root_obj
        return self.existing_root

    def _prepare(self) -> None:
        self.used_exact_spec_reuse = False
        if self.reuse_existing_preview and self.existing_root is not None:
            self._state = _prepare_existing_preview_finalize(
                self.context,
                self.plan,
                existing_root=self.existing_root,
                parent_collection=self.parent_collection,
            )
        else:
            self._state = _prepare_building(
                self.context,
                self.plan,
                existing_root=self.existing_root,
                parent_collection=self.parent_collection,
                clear_lanes=self.clear_lanes,
                clear_scopes=self.clear_scopes,
                emit_runtime_markers=self.emit_runtime_markers,
                enable_preview_exact_spec_reuse=self.enable_preview_exact_spec_reuse,
            )
        if (
            not _STRUCTURAL_EXACT_SPEC_REUSE_DISABLED
            and self._state is not None
            and not bool(self.reuse_existing_preview)
            and (bool(self.emit_runtime_markers) or bool(self.enable_preview_exact_spec_reuse))
        ):
            self.used_exact_spec_reuse = _try_apply_exact_spec_reuse(
                self._state,
                clone_runtime_markers=bool(self.emit_runtime_markers),
                require_finalized_source=bool(self.emit_runtime_markers),
            )
        self._ops = _build_runtime_ops(
            self._state,
            emit_lanes=set() if (self.reuse_existing_preview or self.used_exact_spec_reuse) else self.emit_lanes,
            emit_scopes=set() if (self.reuse_existing_preview or self.used_exact_spec_reuse) else self.emit_scopes,
            suppress_viewport_emit=bool(self.suppress_viewport_emit),
            emit_runtime_markers=bool(self.emit_runtime_markers),
            context=self.context,
        )

    def step(self) -> bool:
        if self._state is None:
            self._prepare()
            return not bool(self._ops)
        if not self._ops:
            return True
        op = self._ops.pop(0)
        try:
            result = op()
        except Exception:
            if self._state is not None:
                cleanup.clear_transient_wall_helpers(self._state.root_obj)
            raise
        if isinstance(result, tuple) and all(callable(item) for item in result):
            self._ops = list(result) + self._ops
        return not self._ops

    def run_to_completion(self):
        while not self.step():
            continue
        return self.root_obj


def _ensure_root_empty(root_collection, building_id: str, origin: tuple[float, float, float], *, existing_root=None):
    root_name = naming.root_object_name(building_id)
    root = existing_root or bpy.data.objects.get(root_name)
    if root is None:
        root = bpy.data.objects.new(root_name, None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = constants.ROOT_EMPTY_SIZE
    if root_collection.objects.get(root.name) is None:
        root_collection.objects.link(root)
    root.location = Vector(origin)
    root.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    return root


def _stable_json_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _exact_spec_payload(spec) -> dict:
    payload = dict(spec.to_dict())
    payload.pop("building_id", None)
    payload.pop("origin", None)
    return payload


def exact_spec_key_for_spec(spec) -> str:
    return _stable_json_payload(_exact_spec_payload(spec))


def exact_spec_key_for_plan(plan: BuildingPlan) -> str:
    return str(plan.exact_spec_key)


def reset_exact_spec_reuse_runtime_state() -> None:
    _EXACT_SPEC_REUSE_CACHE.clear()
    for key in tuple(_EXACT_SPEC_REUSE_STATS):
        _EXACT_SPEC_REUSE_STATS[key] = 0


def invalidate_exact_spec_reuse_entries() -> int:
    invalidated = len(_EXACT_SPEC_REUSE_CACHE)
    if invalidated:
        _EXACT_SPEC_REUSE_CACHE.clear()
        _EXACT_SPEC_REUSE_STATS["invalidations"] += int(invalidated)
    return int(invalidated)


def exact_spec_reuse_runtime_snapshot() -> dict[str, int]:
    snapshot = {key: int(value) for key, value in _EXACT_SPEC_REUSE_STATS.items()}
    snapshot["cache_entry_count"] = len(_EXACT_SPEC_REUSE_CACHE)
    return snapshot


def reset_plan_memo_runtime_state() -> None:
    _PLAN_MEMO_CACHE.clear()
    for key in tuple(_PLAN_MEMO_STATS):
        _PLAN_MEMO_STATS[key] = 0


def plan_memo_runtime_snapshot() -> dict[str, int]:
    snapshot = {key: int(value) for key, value in _PLAN_MEMO_STATS.items()}
    snapshot["cache_entry_count"] = len(_PLAN_MEMO_CACHE)
    return snapshot


def _plan_memo_entry_for_key(key: str) -> _PlanMemoEntry | None:
    _PLAN_MEMO_STATS["lookups"] += 1
    entry = _PLAN_MEMO_CACHE.get(str(key))
    if entry is None:
        _PLAN_MEMO_STATS["misses"] += 1
        return None
    _PLAN_MEMO_CACHE.move_to_end(str(key))
    _PLAN_MEMO_STATS["hits"] += 1
    return entry


def _cache_plan_memo_entry(
    *,
    key: str,
    spatial_plan,
    facade_facts: dict,
) -> None:
    entry = _PlanMemoEntry(
        key=str(key),
        spatial_plan=spatial_plan,
        facade_facts=deepcopy(facade_facts),
    )
    if str(key) in _PLAN_MEMO_CACHE:
        _PLAN_MEMO_CACHE.pop(str(key), None)
    _PLAN_MEMO_CACHE[str(key)] = entry
    while len(_PLAN_MEMO_CACHE) > _PLAN_MEMO_CACHE_MAX_ENTRIES:
        _PLAN_MEMO_CACHE.popitem(last=False)
        _PLAN_MEMO_STATS["evictions"] += 1
    _PLAN_MEMO_STATS["stores"] += 1


def _canonicalize_generation_spec(spec):
    spec = resolve_terrace_feasible_spec(spec)
    spec.facade_family = _normalized_facade_family(
        spec.facade_family,
        facade_mode=getattr(spec, "facade_mode", None),
    )
    spec.entrance_profile = _effective_entrance_profile(spec)
    return spec


def plan_building(spec) -> BuildingPlan:
    planned_spec = _canonicalize_generation_spec(spec)
    exact_key = exact_spec_key_for_spec(planned_spec)
    memo_entry = _plan_memo_entry_for_key(exact_key)
    if memo_entry is not None:
        return BuildingPlan(
            spec=planned_spec,
            spatial_plan=memo_entry.spatial_plan,
            facade_facts=deepcopy(memo_entry.facade_facts),
            exact_spec_key=exact_key,
        )
    spatial_plan = _spatial_plan(planned_spec)
    facade_facts = _derive_facade_facts(planned_spec, spatial_plan)
    _cache_plan_memo_entry(
        key=exact_key,
        spatial_plan=spatial_plan,
        facade_facts=facade_facts,
    )
    return BuildingPlan(
        spec=planned_spec,
        spatial_plan=spatial_plan,
        facade_facts=facade_facts,
        exact_spec_key=exact_key,
    )


def _normalize_lane_names(lane_names, *, lane_type: str) -> set[str]:
    if lane_names is None:
        return set()
    normalized = {str(name).strip().lower() for name in lane_names if str(name).strip()}
    if not normalized:
        return set()
    unknown = normalized - _LANE_COLLECTION_KEYS
    if unknown:
        labels = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown {lane_type} lane(s): {labels}")
    return normalized


def _normalize_emit_lanes(lane_names) -> set[str]:
    if lane_names is None:
        return set(_AUTHORING_LANES)
    normalized = {str(name).strip().lower() for name in lane_names if str(name).strip()}
    if not normalized:
        return set(_AUTHORING_LANES)
    unknown = normalized - _AUTHORING_LANES
    if unknown:
        labels = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown emit lane(s): {labels}")
    return normalized


def _normalize_preview_scopes(scope_names) -> set[str]:
    if scope_names is None:
        return set()
    normalized = {str(name).strip().lower() for name in scope_names if str(name).strip()}
    if not normalized:
        return set()
    unknown = normalized - _PREVIEW_SCOPE_TAGS
    if unknown:
        labels = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown preview scope tag(s): {labels}")
    return normalized


def _find_layer_collection(layer_collection, target_collection):
    if layer_collection.collection == target_collection:
        return layer_collection
    for child in layer_collection.children:
        found = _find_layer_collection(child, target_collection)
        if found is not None:
            return found
    return None


@contextmanager
def _suppressed_viewport_emit(context, root_collection, *, enabled: bool):
    if not enabled:
        yield
        return
    view_layer = getattr(context, "view_layer", None)
    layer_root = getattr(view_layer, "layer_collection", None)
    if layer_root is None:
        yield
        return
    layer_collection = _find_layer_collection(layer_root, root_collection)
    if layer_collection is None:
        yield
        return
    was_excluded = bool(layer_collection.exclude)
    if not was_excluded:
        layer_collection.exclude = True
    try:
        yield
    finally:
        if not was_excluded:
            layer_collection.exclude = False


def _prepare_building(
    context,
    plan: BuildingPlan,
    *,
    existing_root=None,
    parent_collection=None,
    clear_lanes: set[str] | None = None,
    clear_scopes: set[str] | None = None,
    emit_runtime_markers: bool = True,
    enable_preview_exact_spec_reuse: bool = False,
):
    spec = plan.spec
    existing_building_id = (
        str(existing_root.get(constants.BUILDING_ID_KEY, "") or "").strip()
        if existing_root is not None
        else ""
    )
    building_id = existing_building_id or spec.building_id or naming.next_building_id(context.scene)
    hierarchy = collection_service.create_building_hierarchy(
        context.scene,
        building_id,
        spec.export_profile,
        parent_collection=parent_collection,
        existing_root=existing_root,
    )
    root_collection = hierarchy["root"]
    root_obj = _ensure_root_empty(root_collection, building_id, spec.origin, existing_root=existing_root)
    root_obj.scale = Vector((1.0, 1.0, 1.0))
    if existing_root is not None:
        cleanup.clear_transient_wall_helpers(root_obj)

    normalized_clear_lanes = _normalize_lane_names(clear_lanes, lane_type="cleanup")
    normalized_clear_scopes = _normalize_preview_scopes(clear_scopes)
    if normalized_clear_lanes:
        cleanup.clear_generated_building_lanes(
            hierarchy,
            normalized_clear_lanes,
            scope_names=normalized_clear_scopes or None,
            clear_export_collection=not emit_runtime_markers,
        )
    else:
        cleanup.clear_generated_building(hierarchy, root_obj)
    materials_map = materials.ensure_blockout_materials()
    if _uses_wood_floor_material(spec):
        materials_map["floor"] = materials_map["wood_floor"]
        materials_map["stair"] = materials_map["wood_floor"]
    prefix = f"TBG_B{building_id}"
    interior_wall_material = materials_map["interior_wall"]
    runtime_emitter = (
        _TraversalRuntimeEmitter(
            RuntimeMarkerEmitter(
                prefix,
                hierarchy["helpers"],
                root_obj,
                materials_map["helper"],
            )
        )
        if emit_runtime_markers
        else None
    )
    world_scale = float(getattr(spec, "world_scale", 1.0))
    output_ledger = BuildOutputLedger(prefix, root_obj, world_scale=world_scale)
    section_sink = create_final_section_sink(prefix, root_obj, world_scale=world_scale) if (emit_runtime_markers or enable_preview_exact_spec_reuse) else None
    return BuildLaneState(
        plan=plan,
        spec=spec,
        spatial_plan=plan.spatial_plan,
        building_id=building_id,
        hierarchy=hierarchy,
        root_collection=root_collection,
        root_obj=root_obj,
        materials_map=materials_map,
        prefix=prefix,
        interior_wall_material=interior_wall_material,
        runtime_emitter=runtime_emitter,
        facade_facts=plan.facade_facts,
        output_ledger=output_ledger,
        section_sink=section_sink,
        occupancy_author=OccupancyAuthoringSession(
            building_id=building_id,
            root_object_name=root_obj.name,
        ),
        exact_spec_key=exact_spec_key_for_plan(plan),
        exact_reuse_applied=False,
        exact_reuse_source_root_name="",
        exact_reuse_runtime_markers_cloned=False,
        cached_generation_summary=None,
        cached_summary_children=None,
        cached_section_registry=None,
        enable_preview_exact_spec_reuse=bool(enable_preview_exact_spec_reuse),
    )


def _prepare_existing_preview_finalize(
    context,
    plan: BuildingPlan,
    *,
    existing_root,
    parent_collection=None,
):
    spec = plan.spec
    building_id = (
        str(existing_root.get(constants.BUILDING_ID_KEY, "") or "").strip()
        or spec.building_id
        or naming.next_building_id(context.scene)
    )
    hierarchy = collection_service.create_building_hierarchy(
        context.scene,
        building_id,
        spec.export_profile,
        parent_collection=parent_collection,
        existing_root=existing_root,
    )
    root_collection = hierarchy["root"]
    materials_map = materials.ensure_blockout_materials()
    if _uses_wood_floor_material(spec):
        materials_map["floor"] = materials_map["wood_floor"]
        materials_map["stair"] = materials_map["wood_floor"]
    interior_wall_material = materials_map["interior_wall"]
    root_obj = existing_root
    prefix = f"TBG_B{building_id}"
    return BuildLaneState(
        plan=plan,
        spec=spec,
        spatial_plan=plan.spatial_plan,
        building_id=building_id,
        hierarchy=hierarchy,
        root_collection=root_collection,
        root_obj=root_obj,
        materials_map=materials_map,
        prefix=prefix,
        interior_wall_material=interior_wall_material,
        runtime_emitter=None,
        facade_facts=plan.facade_facts,
        output_ledger=BuildOutputLedger(prefix, root_obj, world_scale=float(getattr(spec, "world_scale", 1.0))),
        section_sink=create_final_section_sink(prefix, root_obj, world_scale=float(getattr(spec, "world_scale", 1.0))),
        occupancy_author=OccupancyAuthoringSession(
            building_id=building_id,
            root_object_name=root_obj.name,
        ),
        exact_spec_key=exact_spec_key_for_plan(plan),
        exact_reuse_applied=False,
        exact_reuse_source_root_name="",
        exact_reuse_runtime_markers_cloned=False,
        cached_generation_summary=None,
        cached_summary_children=None,
        cached_section_registry=None,
        enable_preview_exact_spec_reuse=False,
    )


def _emit_structure_stage(state: BuildLaneState):
    _build_foundation_podium(
        state.prefix,
        state.spec,
        state.hierarchy["structure"],
        state.root_obj,
        state.materials_map["floor"],
        state.materials_map,
        runtime_emitter=state.runtime_emitter,
    )
    _build_floor_pieces(
        state.prefix,
        state.spec,
        state.hierarchy["structure"],
        state.root_obj,
        state.materials_map["floor"],
        runtime_emitter=state.runtime_emitter,
    )
    _build_under_construction_frame(
        state.prefix,
        state.spec,
        state.hierarchy["structure"],
        state.root_obj,
        state.materials_map["frame"],
        runtime_emitter=state.runtime_emitter,
    )
    _build_outer_shell(
        state.prefix,
        state.spec,
        state.spatial_plan,
        state.hierarchy["structure"],
        state.root_obj,
        state.materials_map,
        occupancy_author=state.occupancy_author,
        runtime_emitter=state.runtime_emitter,
        facade_facts=state.facade_facts,
    )
    _build_facade_bands(
        state.prefix,
        state.spec,
        state.hierarchy["structure"],
        state.root_obj,
        state.materials_map,
    )
    _build_wall_service_pipes(
        state.prefix,
        state.spec,
        state.hierarchy["structure"],
        state.root_obj,
        state.materials_map,
        runtime_emitter=state.runtime_emitter,
        facade_facts=state.facade_facts,
        spatial_plan=state.spatial_plan,
    )


def _emit_core_stage(state: BuildLaneState):
    _build_core_partitions(
        state.prefix,
        state.spec,
        state.hierarchy["core"],
        state.root_obj,
        state.interior_wall_material,
        runtime_emitter=state.runtime_emitter,
        occupancy_author=state.occupancy_author,
    )
    _build_wide_room_partitions(
        state.prefix,
        state.spec,
        state.spatial_plan,
        state.hierarchy["core"],
        state.root_obj,
        state.materials_map,
        runtime_emitter=state.runtime_emitter,
        occupancy_author=state.occupancy_author,
    )
    _build_stairs(
        state.prefix,
        state.spec,
        state.spatial_plan,
        state.hierarchy["core"],
        state.root_obj,
        state.materials_map["stair"],
        runtime_emitter=state.runtime_emitter,
    )


def _emit_roof_stage(state: BuildLaneState):
    _build_roof(
        state.prefix,
        state.spec,
        state.hierarchy["roof"],
        state.root_obj,
        state.materials_map,
        runtime_emitter=state.runtime_emitter,
        occupancy_author=state.occupancy_author,
    )
    _build_roof_exit(
        state.prefix,
        state.spec,
        state.spatial_plan,
        state.hierarchy["roof"],
        state.root_obj,
        state.materials_map,
        runtime_emitter=state.runtime_emitter,
        occupancy_author=state.occupancy_author,
    )
    _build_roof_props(
        state.prefix,
        state.spec,
        state.spatial_plan,
        state.hierarchy["roof"],
        state.root_obj,
        state.materials_map,
        runtime_emitter=state.runtime_emitter,
    )


def _emit_door_stage(state: BuildLaneState):
    if (
        str(getattr(state.spec, "preset_id", "")).lower() == "under_construction"
        or _is_industrial_frontage(state.spec)
    ):
        return
    _build_main_door(
        state.prefix,
        state.spec,
        state.spatial_plan,
        state.hierarchy["doors"],
        state.root_obj,
        state.materials_map["door"],
        state.materials_map,
        facade_facts=state.facade_facts,
        runtime_emitter=state.runtime_emitter,
    )


def _tag_new_collection_objects_with_scope(collection, *, previous_ptrs: set[int], scope_tag: str) -> None:
    if collection is None or not scope_tag:
        return
    normalized_scope = str(scope_tag).strip().lower()
    if not normalized_scope:
        return
    for obj in tuple(getattr(collection, "objects", ())):
        if obj is None or obj.type != "MESH":
            continue
        if int(obj.as_pointer()) in previous_ptrs:
            continue
        obj["tbg_preview_scope"] = normalized_scope


def _run_emit_op(
    context,
    state: BuildLaneState,
    emit_fn: Callable[[BuildLaneState], None],
    *,
    suppress_viewport_emit: bool,
    emit_collection=None,
    emit_scope_tag: str | None = None,
):
    previous_ptrs: set[int] = set()
    if emit_collection is not None and emit_scope_tag:
        previous_ptrs = {int(obj.as_pointer()) for obj in tuple(getattr(emit_collection, "objects", ())) if obj is not None}
    with output_ledger_scope(state.output_ledger):
        with section_sink_scope(state.section_sink):
            with _suppressed_viewport_emit(context, state.root_collection, enabled=bool(suppress_viewport_emit)):
                emit_fn(state)
    if state.output_ledger is not None:
        state.output_ledger.flush_pending_objects()
    if state.section_sink is not None:
        state.section_sink.flush_pending_objects()
    if emit_collection is not None and emit_scope_tag:
        _tag_new_collection_objects_with_scope(
            emit_collection,
            previous_ptrs=previous_ptrs,
            scope_tag=emit_scope_tag,
        )


def _structure_emit_ops(state: BuildLaneState) -> tuple[tuple[str, Callable[[BuildLaneState], None]], ...]:
    ops: list[tuple[str, Callable[[BuildLaneState], None]]] = [
        ("structure_base", lambda state: _build_foundation_podium(
            state.prefix,
            state.spec,
            state.hierarchy["structure"],
            state.root_obj,
            state.materials_map["floor"],
            state.materials_map,
            runtime_emitter=state.runtime_emitter,
        )),
        ("structure_base", lambda state: _build_floor_pieces(
            state.prefix,
            state.spec,
            state.hierarchy["structure"],
            state.root_obj,
            state.materials_map["floor"],
            runtime_emitter=state.runtime_emitter,
        )),
        ("structure_base", lambda state: _build_under_construction_frame(
            state.prefix,
            state.spec,
            state.hierarchy["structure"],
            state.root_obj,
            state.materials_map["frame"],
            runtime_emitter=state.runtime_emitter,
        )),
        ("facade", lambda state: _build_facade_bands(
            state.prefix,
            state.spec,
            state.hierarchy["structure"],
            state.root_obj,
            state.materials_map,
        )),
        ("structure_base", lambda state: _build_wall_service_pipes(
            state.prefix,
            state.spec,
            state.hierarchy["structure"],
            state.root_obj,
            state.materials_map,
            runtime_emitter=state.runtime_emitter,
            facade_facts=state.facade_facts,
            spatial_plan=state.spatial_plan,
        )),
    ]
    outer_shell_index = 3
    for floor in range(state.spec.floor_count):
        for side_key in ("back", "left", "right", "front"):
            ops.insert(
                outer_shell_index,
                (
                    "facade",
                    lambda state, floor=floor, side_key=side_key: _build_outer_shell_floor_side(
                        state.prefix,
                        state.spec,
                        state.spatial_plan,
                        state.hierarchy["structure"],
                        state.root_obj,
                        state.materials_map,
                        side_key,
                        floor,
                        occupancy_author=state.occupancy_author,
                        runtime_emitter=state.runtime_emitter,
                        facade_facts=state.facade_facts,
                    ),
                ),
            )
            outer_shell_index += 1
    return tuple(ops)


def _core_emit_ops(state: BuildLaneState) -> tuple[tuple[str, Callable[[BuildLaneState], None]], ...]:
    ops: list[tuple[str, Callable[[BuildLaneState], None]]] = [
        ("core", lambda state: _build_core_partitions(
            state.prefix,
            state.spec,
            state.hierarchy["core"],
            state.root_obj,
            state.interior_wall_material,
            runtime_emitter=state.runtime_emitter,
            occupancy_author=state.occupancy_author,
        )),
        ("core", lambda state: _build_wide_room_partitions(
            state.prefix,
            state.spec,
            state.spatial_plan,
            state.hierarchy["core"],
            state.root_obj,
            state.materials_map,
            runtime_emitter=state.runtime_emitter,
            occupancy_author=state.occupancy_author,
        )),
    ]
    for floor in range(max(int(state.spatial_plan.stair_run_count), 0)):
        for part in (
            "lower_steps",
            "upper_steps",
            "lower_support",
            "upper_support",
            "mid_landing",
            "top_landing",
        ):
            ops.append(
                (
                    "core",
                    lambda state, floor=floor, part=part: _build_stair_step(
                        state.prefix,
                        state.spec,
                        state.spatial_plan,
                        state.hierarchy["core"],
                        state.root_obj,
                        state.materials_map["stair"],
                        floor,
                        part,
                        runtime_emitter=state.runtime_emitter,
                    ),
                )
            )
    return tuple(ops)


def _roof_emit_ops() -> tuple[tuple[str, Callable[[BuildLaneState], None]], ...]:
    return (
        (
            "roof",
            lambda state: _build_roof(
                state.prefix,
                state.spec,
                state.hierarchy["roof"],
                state.root_obj,
                state.materials_map,
                runtime_emitter=state.runtime_emitter,
                occupancy_author=state.occupancy_author,
            ),
        ),
        (
            "roof_exit",
            lambda state: _build_roof_exit(
                state.prefix,
                state.spec,
                state.spatial_plan,
                state.hierarchy["roof"],
                state.root_obj,
                state.materials_map,
                runtime_emitter=state.runtime_emitter,
                occupancy_author=state.occupancy_author,
            ),
        ),
        (
            "roof_props",
            lambda state: _build_roof_props(
                state.prefix,
                state.spec,
                state.spatial_plan,
                state.hierarchy["roof"],
                state.root_obj,
                state.materials_map,
                runtime_emitter=state.runtime_emitter,
            ),
        ),
    )


def _door_emit_ops() -> tuple[tuple[str, Callable[[BuildLaneState], None]], ...]:
    return (
        ("doors", lambda state: _emit_door_stage(state)),
    )


def _build_canonical_generation_summary(state: BuildLaneState) -> dict:
    _require_no_cached_structural_reuse(state)
    # Summary source-of-truth: canonical spec/spatial plan + authoring-time snapshots from the explicit output ledger.
    summary_children = _require_live_output_ledger(state).summary_children()
    return _build_generation_summary(
        state.root_obj,
        state.spec,
        state.spatial_plan,
        summary_children=summary_children,
    )


def _material_name_for_object(obj) -> str:
    if obj is None:
        return ""
    for slot in getattr(obj, "material_slots", ()):
        material = getattr(slot, "material", None)
        if material is not None:
            return str(material.name)
    return ""


def _merge_registry_bounds(
    left: list[float] | tuple[float, ...],
    right: tuple[float, float, float, float, float, float],
) -> list[float]:
    merged = list(left)
    for index, value in enumerate(right):
        merged[index] = min(merged[index], float(value)) if index % 2 == 0 else max(merged[index], float(value))
    return [round(float(value), 4) for value in merged]


def _remap_name_for_prefix(name: str, *, source_prefix: str, target_prefix: str) -> str:
    source_token = f"{str(source_prefix)}_"
    if str(name).startswith(source_token):
        suffix = str(name)[len(source_token):]
        return f"{target_prefix}_{suffix}"
    return str(name)


def _remap_summary_children_for_prefix(
    summary_children: tuple[SummaryChildSnapshot, ...],
    *,
    source_prefix: str,
    target_prefix: str,
) -> tuple[SummaryChildSnapshot, ...]:
    return tuple(
        SummaryChildSnapshot(
            name=_remap_name_for_prefix(child.name, source_prefix=source_prefix, target_prefix=target_prefix),
            props=dict(child.props),
            bounds=tuple(float(value) for value in child.bounds),
            hide_viewport=bool(child.hide_viewport),
            hide_render=bool(child.hide_render),
        )
        for child in summary_children
    )


def _remap_generation_summary_for_prefix(summary: dict, *, source_prefix: str, target_prefix: str) -> dict:
    remapped = deepcopy(summary)
    overlap_names = remapped.get("perimeter_corner_overlap_names")
    if isinstance(overlap_names, list):
        remapped["perimeter_corner_overlap_names"] = [
            _remap_name_for_prefix(str(name), source_prefix=source_prefix, target_prefix=target_prefix)
            for name in overlap_names
        ]
    return remapped


def _remap_section_registry_for_prefix(registry: dict, *, source_prefix: str, target_prefix: str) -> dict:
    remapped = deepcopy(registry)
    for section in remapped.get("sections", ()):
        section_name = str(section.get("name", ""))
        section["name"] = _remap_name_for_prefix(
            section_name,
            source_prefix=source_prefix,
            target_prefix=target_prefix,
        )
        source_fragments = section.get("source_fragments")
        if not isinstance(source_fragments, list):
            continue
        for fragment in source_fragments:
            if not isinstance(fragment, dict):
                continue
            source_name = str(fragment.get("source_name", ""))
            if not source_name:
                continue
            fragment["source_name"] = _remap_name_for_prefix(
                source_name,
                source_prefix=source_prefix,
                target_prefix=target_prefix,
            )
    return remapped


def _cache_exact_spec_reuse_entry(
    state: BuildLaneState,
    *,
    registry: dict,
    finalized_source: bool,
) -> None:
    # V3 rewrite lock: structural exact-spec replay is disabled until the
    # cell-authoritative lifecycle is green. Do not store summary/registry data.
    invalidate_exact_spec_reuse_entries()


def _exact_spec_reuse_entry_for_state(
    state: BuildLaneState,
    *,
    require_finalized_source: bool,
) -> tuple[_ExactSpecReuseEntry | None, object | None]:
    key = str(state.exact_spec_key or "")
    _EXACT_SPEC_REUSE_STATS["lookups"] += 1
    if not key:
        _EXACT_SPEC_REUSE_STATS["misses"] += 1
        return None, None
    invalidate_exact_spec_reuse_entries()
    _EXACT_SPEC_REUSE_STATS["misses"] += 1
    return None, None


def _try_apply_exact_spec_reuse(
    state: BuildLaneState,
    *,
    clone_runtime_markers: bool,
    require_finalized_source: bool,
) -> bool:
    _ = (state, clone_runtime_markers, require_finalized_source)
    invalidate_exact_spec_reuse_entries()
    _EXACT_SPEC_REUSE_STATS["misses"] += 1
    return False


def _require_live_output_ledger(state: BuildLaneState) -> BuildOutputLedger:
    if state.output_ledger is None:
        raise RuntimeError("Structural summary/registry replay is disabled; live output ledger is required.")
    return state.output_ledger


def _require_no_cached_structural_reuse(state: BuildLaneState) -> None:
    if state.cached_generation_summary is not None or state.cached_summary_children is not None or state.cached_section_registry is not None:
        raise RuntimeError("Structural exact-spec replay is disabled for this rewrite wave.")


def _write_final_output_ledger(state: BuildLaneState, *, canonicalization=None) -> dict:
    _require_no_cached_structural_reuse(state)
    registry = _require_live_output_ledger(state).section_registry()
    resolved_canonicalization = (
        canonicalization
        if canonicalization is not None
        else state.occupancy_author.canonicalize()
    )
    sections = [
        *registry.get("sections", ()),
        *authored_visible_wall_section_registry_entries(
            state.prefix,
            resolved_canonicalization,
        ),
    ]
    registry = {
        **registry,
        "section_count": len(sections),
        "sections": sorted(
            sections,
            key=lambda item: (str(item["bucket"]), str(item["material_name"]), str(item["name"])),
        ),
    }
    metadata.write_generation_summary(
        state.root_obj,
        _build_canonical_generation_summary(state),
    )
    metadata.write_final_section_registry(state.root_obj, registry)
    state.root_obj["tbg_section_count"] = int(registry.get("section_count", 0))
    return registry


def _closeout_final_output(state: BuildLaneState) -> dict:
    if state.output_ledger is not None:
        state.output_ledger.flush_pending_objects()
    canonicalization = state.occupancy_author.canonicalize()
    state.final_occupancy_canonicalization = canonicalization
    state.final_visible_wall_cell_count = None
    authored_cell_count = len(tuple(getattr(canonicalization, "cells", ())))
    registry = _write_final_output_ledger(state, canonicalization=canonicalization)
    if state.section_sink is None:
        if authored_cell_count > 0:
            raise RuntimeError(
                f"Authored wall cells exist ({authored_cell_count}), but final section sink is unavailable "
                "so visible V3 wall meshes cannot be emitted."
            )
        return registry
    merged_count, standalone_count = state.section_sink.closeout()
    authored_wall_emission = emit_visible_authored_wall_sections_from_canonicalization(
        state.prefix,
        state.root_obj,
        state.hierarchy["structure"],
        canonicalization,
    )
    state.final_visible_wall_cell_count = int(authored_wall_emission.composite_cell_count)
    if authored_cell_count > 0 and int(authored_wall_emission.object_count) <= 0:
        raise RuntimeError(
            f"Authored wall cells exist ({authored_cell_count}), but no visible V3 wall mesh was emitted."
        )
    if authored_cell_count != int(authored_wall_emission.composite_cell_count):
        raise RuntimeError(
            "Visible V3 wall composite cell count drifted from canonical payload cells: "
            f"payload={authored_cell_count}, visible={int(authored_wall_emission.composite_cell_count)}."
        )
    expected_count = int(registry.get("section_count", 0))
    actual_count = int(merged_count) + int(standalone_count) + int(authored_wall_emission.object_count)
    if actual_count != expected_count:
        raise RuntimeError(
            "Final section registry drifted from emitted geometry: "
            f"ledger={expected_count}, emitted={actual_count}."
        )
    _cache_exact_spec_reuse_entry(
        state,
        registry=registry,
        finalized_source=True,
    )
    return registry


def _closeout_preview_exact_spec_reuse_source(state: BuildLaneState) -> None:
    if not bool(state.enable_preview_exact_spec_reuse) or state.output_ledger is None or state.section_sink is None:
        return
    invalidate_exact_spec_reuse_entries()


def _clear_voxel_wall_authority_state(root_obj) -> None:
    if root_obj is None:
        return
    cleanup.clear_transient_wall_helpers(root_obj)


def _summary_children_for_voxel_wall_authoring(state: BuildLaneState) -> tuple[SummaryChildSnapshot, ...]:
    _require_no_cached_structural_reuse(state)
    return _require_live_output_ledger(state).summary_children()


def _section_registry_for_voxel_wall_authoring(state: BuildLaneState) -> dict:
    _require_no_cached_structural_reuse(state)
    return _require_live_output_ledger(state).section_registry()


def _build_and_write_voxel_wall_occupancy_payload(state: BuildLaneState) -> dict:
    canonicalization = state.final_occupancy_canonicalization
    if canonicalization is None:
        canonicalization = state.occupancy_author.canonicalize()
    payload = serialize_authored_wall_cell_payload(canonicalization)
    payload_cell_count = int(payload.get("authored_cell_count", 0))
    visible_cell_count = state.final_visible_wall_cell_count
    if payload_cell_count > 0 and visible_cell_count is None:
        raise RuntimeError(
            f"Authored wall payload has cells ({payload_cell_count}), but visible V3 wall emission was not verified."
        )
    if visible_cell_count is not None and int(visible_cell_count) != payload_cell_count:
        raise RuntimeError(
            "Authored wall payload drifted from visible V3 wall composite cells during finalize: "
            f"payload={payload_cell_count}, visible={int(visible_cell_count)}."
        )
    metadata.write_voxel_wall_occupancy_payload(state.root_obj, payload)
    return payload


def _rebuild_runtime_helper_markers(state: BuildLaneState) -> None:
    for helper_obj in iter_runtime_marker_objects(state.root_obj):
        if helper_obj is None or helper_obj.name not in bpy.data.objects:
            continue
        bpy.data.objects.remove(helper_obj, do_unlink=True)
    _build_runtime_markers(
        state.prefix,
        state.spec,
        state.spatial_plan,
        state.hierarchy["helpers"],
        state.root_obj,
        state.materials_map,
    )


def _finalize_building_full_ops(context, state: BuildLaneState) -> tuple[Callable[[], None], ...]:
    requires_view_layer_sync = not bool(state.root_obj is not None and state.root_obj.get("tbg_edit_mode_dirty"))

    def _write_root_metadata_step():
        metadata.write_root_metadata(state.root_obj, state.root_collection, state.spec.to_dict(), state.building_id)
        state.root_obj[constants.EXPORT_COLLECTION_NAME_KEY] = (
            state.hierarchy["export"].name if state.hierarchy["export"] else ""
        )

    def _closeout_output_step():
        _closeout_final_output(state)

    runtime_marker_step: Callable[[], None]
    runtime_marker_step = lambda: _rebuild_runtime_helper_markers(state)

    ops: list[Callable[[], None]] = [
        lambda: _clear_voxel_wall_authority_state(state.root_obj),
        *( [lambda: context.view_layer.update()] if requires_view_layer_sync else [] ),
        _closeout_output_step,
        lambda: _build_and_write_voxel_wall_occupancy_payload(state),
        runtime_marker_step,
    ]
    ops.extend(
        (
            lambda: _apply_uniform_world_scale(state.root_obj, float(getattr(state.spec, "world_scale", 1.0))),
            lambda: _set_generated_wall_visibility(state.root_obj, hidden=False),
            _write_root_metadata_step,
            lambda: _clear_edit_mode_state(state.root_obj),
        )
    )
    return tuple(ops)


def _finalize_building_edit_ops(state: BuildLaneState) -> tuple[Callable[[], None], ...]:
    def _expand_retile_ops():
        return tuple(
            lambda child=child, material=material: retile_dirty_brick_section(child, material)
            for child, material in iter_dirty_brick_sections(state.root_obj)
        )

    ops: list[Callable[[], None]] = []
    if bool(state.enable_preview_exact_spec_reuse):
        ops.append(lambda: _closeout_preview_exact_spec_reuse_source(state))
    ops.extend(
        (
            lambda: _write_preview_identity(state),
            _expand_retile_ops,
        )
    )
    ops.extend(
        (
            lambda: _apply_uniform_world_scale(state.root_obj, float(getattr(state.spec, "world_scale", 1.0))),
            lambda: _set_generated_wall_visibility(
                state.root_obj,
                hidden=bool(state.root_obj.get("tbg_walls_hidden", False)),
            ),
            lambda: _set_edit_mode_state(state.root_obj, state.spec),
        )
    )
    return tuple(ops)


def _build_runtime_ops(
    state: BuildLaneState,
    *,
    emit_lanes: set[str] | None,
    emit_scopes: set[str] | None,
    suppress_viewport_emit: bool,
    emit_runtime_markers: bool,
    context,
) -> list[Callable[[], None]]:
    ops: list[Callable[[], None]] = []
    lanes = _normalize_emit_lanes(None) if emit_lanes is None else set(emit_lanes)
    scoped_emit = _normalize_preview_scopes(emit_scopes)
    if "structure" in lanes:
        for scope_tag, emit_fn in _structure_emit_ops(state):
            if scoped_emit and scope_tag not in scoped_emit:
                continue
            ops.append(
                lambda emit_fn=emit_fn, scope_tag=scope_tag: _run_emit_op(
                    context,
                    state,
                    emit_fn,
                    suppress_viewport_emit=suppress_viewport_emit,
                    emit_collection=state.hierarchy["structure"],
                    emit_scope_tag=scope_tag,
                )
            )
    if "core" in lanes:
        for scope_tag, emit_fn in _core_emit_ops(state):
            if scoped_emit and scope_tag not in scoped_emit:
                continue
            ops.append(
                lambda emit_fn=emit_fn, scope_tag=scope_tag: _run_emit_op(
                    context,
                    state,
                    emit_fn,
                    suppress_viewport_emit=suppress_viewport_emit,
                    emit_collection=state.hierarchy["core"],
                    emit_scope_tag=scope_tag,
                )
            )
    if "roof" in lanes:
        for scope_tag, emit_fn in _roof_emit_ops():
            if scoped_emit and scope_tag not in scoped_emit:
                continue
            ops.append(
                lambda emit_fn=emit_fn, scope_tag=scope_tag: _run_emit_op(
                    context,
                    state,
                    emit_fn,
                    suppress_viewport_emit=suppress_viewport_emit,
                    emit_collection=state.hierarchy["roof"],
                    emit_scope_tag=scope_tag,
                )
            )
    if "doors" in lanes:
        for scope_tag, emit_fn in _door_emit_ops():
            if scoped_emit and scope_tag not in scoped_emit:
                continue
            ops.append(
                lambda emit_fn=emit_fn, scope_tag=scope_tag: _run_emit_op(
                    context,
                    state,
                    emit_fn,
                    suppress_viewport_emit=suppress_viewport_emit,
                    emit_collection=state.hierarchy["doors"],
                    emit_scope_tag=scope_tag,
                )
            )
    if emit_runtime_markers:
        ops.extend(_finalize_building_full_ops(context, state))
    else:
        ops.extend(_finalize_building_edit_ops(state))
    return ops


def _emit_building(state: BuildLaneState, *, emit_lanes: set[str] | None = None):
    lanes = _normalize_emit_lanes(emit_lanes)
    if "structure" in lanes:
        _emit_structure_stage(state)
    if "core" in lanes:
        _emit_core_stage(state)
    if "roof" in lanes:
        _emit_roof_stage(state)
    if "doors" in lanes:
        _emit_door_stage(state)


def _set_edit_mode_state(root_obj, spec):
    _clear_voxel_wall_authority_state(root_obj)
    root_obj["tbg_edit_mode_dirty"] = True
    root_obj["tbg_edit_spec_json"] = json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"))


def _clear_edit_mode_state(root_obj):
    if "tbg_edit_mode_dirty" in root_obj:
        del root_obj["tbg_edit_mode_dirty"]
    if "tbg_edit_spec_json" in root_obj:
        del root_obj["tbg_edit_spec_json"]


def _write_preview_identity(state: BuildLaneState):
    state.root_obj[constants.ROOT_OBJECT_KEY] = True
    state.root_obj[constants.BUILDING_ID_KEY] = state.building_id
    state.root_obj[constants.COLLECTION_NAME_KEY] = state.root_collection.name
    state.root_obj[constants.PRESET_KEY] = state.spec.preset_id
    state.root_obj[constants.SEED_KEY] = int(getattr(state.spec, "seed", 0))
    state.root_obj[constants.UNIT_MODE_KEY] = getattr(state.spec, "unit_mode", constants.UNIT_MODE_METERS)
    state.root_obj[constants.EXPORT_PROFILE_KEY] = getattr(state.spec, "export_profile", constants.EDITABLE_ONLY)


def _finalize_building_full(context, state: BuildLaneState):
    _clear_voxel_wall_authority_state(state.root_obj)
    context.view_layer.update()
    _closeout_final_output(state)
    _build_and_write_voxel_wall_occupancy_payload(state)
    _rebuild_runtime_helper_markers(state)
    _apply_uniform_world_scale(state.root_obj, float(getattr(state.spec, "world_scale", 1.0)))
    _set_generated_wall_visibility(state.root_obj, hidden=False)
    metadata.write_root_metadata(state.root_obj, state.root_collection, state.spec.to_dict(), state.building_id)
    state.root_obj[constants.EXPORT_COLLECTION_NAME_KEY] = (
        state.hierarchy["export"].name if state.hierarchy["export"] else ""
    )
    _clear_edit_mode_state(state.root_obj)


def _finalize_building_edit(state: BuildLaneState):
    _write_preview_identity(state)
    _retile_dirty_brick_sections(state.root_obj)
    _apply_uniform_world_scale(state.root_obj, float(getattr(state.spec, "world_scale", 1.0)))
    _set_generated_wall_visibility(state.root_obj, hidden=bool(state.root_obj.get("tbg_walls_hidden", False)))
    _set_edit_mode_state(state.root_obj, state.spec)


def create_build_preview_sequence(
    context,
    spec,
    *,
    existing_root=None,
    parent_collection=None,
    clear_lanes: set[str] | None = None,
    clear_scopes: set[str] | None = None,
    emit_lanes: set[str] | None = None,
    emit_scopes: set[str] | None = None,
    suppress_viewport_emit: bool = True,
    enable_exact_spec_reuse: bool = False,
) -> BuildRuntimeSequence:
    normalized_emit_lanes = _normalize_emit_lanes(emit_lanes) if emit_lanes is not None else None
    normalized_emit_scopes = _normalize_preview_scopes(emit_scopes) if emit_scopes is not None else None
    normalized_clear_lanes = None
    normalized_clear_scopes = None
    if clear_lanes is not None:
        normalized_clear_lanes = _normalize_lane_names(clear_lanes, lane_type="cleanup")
    elif normalized_emit_lanes is not None:
        normalized_clear_lanes = set(normalized_emit_lanes)
    if clear_scopes is not None:
        normalized_clear_scopes = _normalize_preview_scopes(clear_scopes)
    elif normalized_emit_scopes is not None:
        normalized_clear_scopes = set(normalized_emit_scopes)
    if normalized_clear_lanes is not None:
        normalized_clear_lanes.add("helpers")
    return BuildRuntimeSequence(
        context=context,
        plan=plan_building(spec),
        existing_root=existing_root,
        parent_collection=parent_collection,
        clear_lanes=normalized_clear_lanes,
        clear_scopes=normalized_clear_scopes,
        emit_lanes=normalized_emit_lanes,
        emit_scopes=normalized_emit_scopes,
        suppress_viewport_emit=bool(suppress_viewport_emit),
        emit_runtime_markers=False,
        enable_preview_exact_spec_reuse=False,
    )


def create_build_finalize_sequence(
    context,
    spec,
    *,
    existing_root=None,
    parent_collection=None,
    suppress_viewport_emit: bool = False,
) -> BuildRuntimeSequence:
    return BuildRuntimeSequence(
        context=context,
        plan=plan_building(spec),
        existing_root=existing_root,
        parent_collection=parent_collection,
        clear_lanes=None,
        emit_lanes=None,
        suppress_viewport_emit=bool(suppress_viewport_emit),
        emit_runtime_markers=True,
        reuse_existing_preview=False,
    )


def build_building_preview(
    context,
    spec,
    *,
    existing_root=None,
    parent_collection=None,
    clear_lanes: set[str] | None = None,
    emit_lanes: set[str] | None = None,
    suppress_viewport_emit: bool = True,
):
    sequence = create_build_preview_sequence(
        context,
        spec,
        existing_root=existing_root,
        parent_collection=parent_collection,
        clear_lanes=clear_lanes,
        emit_lanes=emit_lanes,
        suppress_viewport_emit=suppress_viewport_emit,
    )
    return sequence.run_to_completion()


def build_building_finalize(
    context,
    spec,
    *,
    existing_root=None,
    parent_collection=None,
    suppress_viewport_emit: bool = False,
):
    sequence = create_build_finalize_sequence(
        context,
        spec,
        existing_root=existing_root,
        parent_collection=parent_collection,
        suppress_viewport_emit=suppress_viewport_emit,
    )
    return sequence.run_to_completion()


def build_building(
    context,
    spec,
    *,
    existing_root=None,
    parent_collection=None,
    edit_mode: bool = False,
    clear_lanes: set[str] | None = None,
    emit_lanes: set[str] | None = None,
    suppress_viewport_emit: bool | None = None,
):
    if not edit_mode and (clear_lanes is not None or emit_lanes is not None):
        raise ValueError("Lane-scoped rebuild options are only supported in edit_mode.")
    if suppress_viewport_emit is None:
        suppress_viewport_emit = bool(edit_mode)
    if edit_mode:
        return build_building_preview(
            context,
            spec,
            existing_root=existing_root,
            parent_collection=parent_collection,
            clear_lanes=clear_lanes,
            emit_lanes=emit_lanes,
            suppress_viewport_emit=bool(suppress_viewport_emit),
        )
    return build_building_finalize(
        context,
        spec,
        existing_root=existing_root,
        parent_collection=parent_collection,
        suppress_viewport_emit=bool(suppress_viewport_emit),
    )
