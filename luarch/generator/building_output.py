from __future__ import annotations

import json
import math
from dataclasses import dataclass

import bmesh
import bpy
from mathutils import Matrix, Vector

from .. import constants, export_contract
from .building_layout import (
    ENTRY_LIGHT_HEIGHT_OFFSET,
    ROOM_LIGHT_HEIGHT_OFFSET,
    RUNTIME_MARKER_THICKNESS,
    STAIR_LIGHT_HEIGHT_FACTOR,
    _dogleg_metrics,
    _front_entry_envelope,
    _interior_bounds,
    _interior_bounds_for_rect,
    _roof_surface_z,
    _stable_unit_float,
    _wide_partition_positions,
)
from .building_occupancy import OccupancyCanonicalization
from .layout_facade_planning import _is_hangar_frontage
from .building_support import (
    _assign_material,
    _assign_material_slot_only,
    build_authored_voxel_walls,
    _create_box,
    _create_composite_box_object,
    derive_voxel_wall_frame,
    _mesh_from_pydata,
    composite_part_root_local_bounds,
    _mark_generated,
    _name,
    merge_coplanar_voxel_wall_source_entries,
    object_local_bounds,
    planned_voxel_wall_marker_payload,
    _parent_to,
    resolve_authored_voxel_wall_material_metadata,
    resolve_voxel_wall_display_color_rgb,
    VoxelWallOccupancyContractError,
    write_voxel_wall_marker_payload,
    root_local_matrix,
)
from .material_uv import _apply_material_uv, _brick_section_requires_retile, _retile_brick_section
from .materials import (
    BRICK_FAMILIES,
    FLAT_FACADE_FAMILIES,
    INDUSTRIAL_CLADDING_MATERIAL_NAME,
    ensure_v3_wall_texture_preview_material,
    material_uv_settings,
)
from .runtime_markers import _create_runtime_marker_box


@dataclass(frozen=True)
class _ConsolidationClassification:
    obj: bpy.types.Object
    bucket: str
    merge_allowed: bool
    hide_with_walls: bool
    material: bpy.types.Material | None
    material_name: str


@dataclass(frozen=True)
class ConsolidationBucketPlan:
    bucket: str
    material_name: str
    items: tuple[_ConsolidationClassification, ...]
    material: bpy.types.Material | None
    hide_with_walls: bool


@dataclass(frozen=True)
class ConsolidationReductionStep:
    source_names: tuple[str, ...]
    output_name: str
    is_final: bool


@dataclass(frozen=True)
class ConsolidationReductionPlan:
    bucket_plan: ConsolidationBucketPlan
    steps: tuple[ConsolidationReductionStep, ...]
    roof_exit_shell_bounds: tuple[float, ...] | None
    top_room_floor_bounds: tuple[float, ...] | None
    entry_canopy_present: bool


@dataclass
class _FinalSectionBucketState:
    bucket: str
    material_name: str
    material: bpy.types.Material | None
    hide_with_walls: bool
    collections: tuple[bpy.types.Collection, ...]
    bm: bmesh.types.BMesh
    roof_exit_shell_bounds: list[float] | None = None
    top_room_floor_bounds: list[float] | None = None
    entry_canopy_present: bool = False


_HIDE_WITH_WALLS_BUCKETS = frozenset({
    "Section_Walls_Exterior",
    "Section_Walls_ExteriorSurfaceTile",
    "Section_Walls_ExteriorShell",
    "Section_Stairs_RoomShell",
    "Section_Walls_Roof",
    "Section_Walls_Canopy",
    "Section_Walls_Trim",
})
_MAX_REDUCTION_SOURCES = 8
_EXTERIOR_BRICK_BUCKET = "Section_Walls_Exterior"
_EXTERIOR_SURFACE_TILE_BUCKET = "Section_Walls_ExteriorSurfaceTile"
_EXTERIOR_SHELL_BUCKET = "Section_Walls_ExteriorShell"
_GRID_EPSILON = 1e-6
_FRAGMENT_PROFILE_BRICK_GRID = "BRICK_GRID"
_FRAGMENT_PROFILE_SURFACE_TILE = "SURFACE_TILE"
_FRAGMENT_PROFILE_PRESERVE = "PRESERVE"
_FRAGMENT_PROFILE_KEY = "tbg_fragment_profile"
_FRAGMENT_TILE_U_KEY = "tbg_fragment_tile_u"
_FRAGMENT_TILE_V_KEY = "tbg_fragment_tile_v"
_FRAGMENT_RUN_AXIS_KEY = "tbg_fragment_run_axis"
_SURFACE_TILE_UV_SPACE_KEY = "tbg_surface_tile_uv_space"
_SURFACE_TILE_UV_BOUNDS_KEY = "tbg_surface_tile_uv_bounds"
_SURFACE_TILE_UV_RUN_AXIS_KEY = "tbg_surface_tile_uv_run_axis"
_VOXEL_WALL_MARKER_NAME_PREFIX = "Meta_VoxelWall"
_VOXEL_PREVIEW_TAG = "tbg_voxel_preview"
_STRUCTURAL_WALL_BUCKETS = frozenset(str(bucket) for bucket in export_contract.VOXEL_WALL_SOURCE_BUCKETS)
_SURFACE_TILE_UV_SPACE_ROOT_SOURCE = "ROOT_SOURCE_SURFACE"
_V3_WALL_UV_SOURCE_ROBLOX_TEXTURE = "payload_roblox_part_texture_v1"
_V3_WALL_UV_SOURCE_MATERIAL_STYLE = "payload_material_variant_style_v1"


@dataclass(frozen=True)
class ExteriorFragmentStamp:
    profile: str
    tile_u: float | None = None
    tile_v: float | None = None
    run_axis: str | None = None


@dataclass(frozen=True)
class ExteriorBrickSource:
    source_name: str
    bounds: tuple[float, float, float, float, float, float]
    material_name: str
    material: bpy.types.Material | None
    hide_with_walls: bool
    preserved_shell: bool
    roof_exit_shell: bool
    top_room_floor: bool
    entry_canopy_present: bool
    entrance_part: str
    facade_side: str
    fragment_profile: str
    fragment_tile_u: float | None
    fragment_tile_v: float | None
    fragment_run_axis: str | None


class FinalSectionSink:
    """Geometry-only final section emitter for the canonical normal path."""

    def __init__(self, prefix: str, root_obj, *, world_scale: float | None = None):
        self._prefix = str(prefix)
        self._root_obj = root_obj
        self._world_scale = float(world_scale) if world_scale is not None else None
        self._bucket_states: dict[tuple[str, str], _FinalSectionBucketState] = {}
        self._standalone_section_count = 0
        self._pending_section_ptrs: set[int] = set()
        self._pending_section_objects: list[bpy.types.Object] = []
        self._closed = False

    def ingest_root_meshes(self, *, consume_sections: bool = True) -> None:
        # Legacy migration/debug helper.
        if self._closed or self._root_obj is None:
            return
        meshes = [child for child in self._root_obj.children_recursive if child.type == "MESH"]
        self.ingest_objects(meshes, consume_sections=consume_sections)

    def queue_section_object(self, obj) -> None:
        if self._closed or obj is None or obj.type != "MESH":
            return
        ptr = int(obj.as_pointer())
        if ptr in self._pending_section_ptrs:
            return
        self._pending_section_ptrs.add(ptr)
        self._pending_section_objects.append(obj)

    def flush_pending_objects(self) -> int:
        if self._closed:
            return 0
        pending = tuple(self._pending_section_objects)
        self._pending_section_objects.clear()
        self._pending_section_ptrs.clear()
        if not pending:
            return 0
        self.ingest_objects(pending, consume_sections=True)
        return len(pending)

    def ingest_objects(
        self,
        objects: list[bpy.types.Object] | tuple[bpy.types.Object, ...],
        *,
        consume_sections: bool = True,
    ) -> None:
        if self._closed or self._root_obj is None:
            return
        for obj in objects:
            if obj is None or obj.type != "MESH":
                continue
            if obj.name not in bpy.data.objects:
                continue
            if consume_sections:
                self._ingest_section_object(obj)

    def closeout(self) -> tuple[int, int]:
        if self._closed:
            merged = len(self._bucket_states)
            return merged, int(self._standalone_section_count)
        self.flush_pending_objects()
        self._closed = True
        merged_section_count = 0
        for bucket_state in self._bucket_states.values():
            if not bucket_state.bm.faces:
                bucket_state.bm.free()
                continue
            bmesh.ops.recalc_face_normals(bucket_state.bm, faces=list(bucket_state.bm.faces))
            _stabilize_bottom_face_normals(bucket_state.bm)
            mesh = bpy.data.meshes.new(_section_mesh_name(self._prefix, bucket_state))
            bucket_state.bm.to_mesh(mesh)
            bucket_state.bm.free()
            mesh.update()
            merged = bpy.data.objects.new(_section_object_name(self._prefix, bucket_state), mesh)
            collections = bucket_state.collections or tuple(self._root_obj.users_collection)
            if not collections:
                collections = tuple(self._root_obj.users_collection)
            for collection in collections:
                collection.objects.link(merged)
            _parent_to(merged, self._root_obj)
            # Bucket geometry is already baked into root-local space during ingestion.
            # Keep the emitted section at identity local transform under the root.
            merged.matrix_basis = Matrix.Identity(4)
            _apply_final_bucket_contract(
                merged,
                ConsolidationBucketPlan(
                    bucket=bucket_state.bucket,
                    material_name=bucket_state.material_name,
                    items=(),
                    material=bucket_state.material,
                    hide_with_walls=bucket_state.hide_with_walls,
                ),
                roof_exit_shell_bounds=_freeze_bounds(bucket_state.roof_exit_shell_bounds),
                top_room_floor_bounds=_freeze_bounds(bucket_state.top_room_floor_bounds),
                entry_canopy_present=bool(bucket_state.entry_canopy_present),
            )
            merged_section_count += 1
        return merged_section_count, int(self._standalone_section_count)

    def _ingest_section_object(self, obj) -> None:
        classified = _classify_consolidation_object(obj)
        if classified is None:
            return
        if classified.bucket in _STRUCTURAL_WALL_BUCKETS:
            bpy.data.objects.remove(obj, do_unlink=True)
            return
        if not classified.merge_allowed:
            self._standalone_section_count += 1
            return
        key = (classified.bucket, classified.material_name)
        state = self._bucket_states.get(key)
        if state is None:
            state = _FinalSectionBucketState(
                bucket=classified.bucket,
                material_name=classified.material_name,
                material=classified.material,
                hide_with_walls=classified.hide_with_walls,
                collections=tuple(obj.users_collection),
                bm=bmesh.new(),
            )
            self._bucket_states[key] = state
        self._accumulate_bucket_bounds(state, obj)
        _append_object_mesh_to_bucket_bmesh(state.bm, obj, self._root_obj)
        bpy.data.objects.remove(obj, do_unlink=True)

    def _accumulate_bucket_bounds(self, state: _FinalSectionBucketState, obj) -> None:
        bounds = [round(value, 4) for value in object_local_bounds(self._root_obj, obj)]
        if obj.get("tbg_roof_exit_shell"):
            state.roof_exit_shell_bounds = _accumulate_bounds(state.roof_exit_shell_bounds, bounds)
        if obj.get("tbg_top_room_floor"):
            state.top_room_floor_bounds = _accumulate_bounds(state.top_room_floor_bounds, bounds)
        if obj.get("tbg_entry_canopy"):
            state.entry_canopy_present = True


def create_final_section_sink(prefix: str, root_obj, *, world_scale: float | None = None) -> FinalSectionSink:
    return FinalSectionSink(prefix, root_obj, world_scale=world_scale)


def _room_light_spans(
    spec,
    *,
    footprint: tuple[float, float, float, float] | None = None,
) -> list[tuple[float, float, float, float]]:
    inner_x0, inner_x1, inner_y0, inner_y1 = (
        _interior_bounds(spec)
        if footprint is None
        else _interior_bounds_for_rect(footprint, spec.wall_thickness)
    )
    if spec.stair_core.enabled:
        metrics = _dogleg_metrics(spec)
        base_spans = [(inner_x0, metrics.x0), (metrics.x1, inner_x1)]
    else:
        base_spans = [(inner_x0, inner_x1)]
    cuts = _wide_partition_positions(spec, interior_bounds=(inner_x0, inner_x1, inner_y0, inner_y1))
    spans: list[tuple[float, float, float, float]] = []
    for span_start, span_end in base_spans:
        if span_end - span_start < 1.6:
            continue
        local_cuts = [value for value in cuts if span_start + 0.25 < value < span_end - 0.25]
        edges = [span_start] + local_cuts + [span_end]
        for left, right in zip(edges, edges[1:]):
            if right - left < 2.05:
                continue
            spans.append((left, right, inner_y0, inner_y1))
    if not spans and inner_x1 - inner_x0 > 1.6:
        spans.append((inner_x0, inner_x1, inner_y0, inner_y1))
    return spans


def _build_runtime_light_markers(prefix, spec, spatial_plan, collection, parent, material):
    inner_x0, inner_x1, inner_y0, inner_y1 = _interior_bounds(spec)
    inner_depth = inner_y1 - inner_y0
    for floor_plan in spatial_plan.floors:
        if not floor_plan.is_traversable:
            continue
        floor = floor_plan.floor_index
        base_z = floor_plan.base_z
        light_z = base_z + max(1.8, spec.floor_height - ROOM_LIGHT_HEIGHT_OFFSET)
        room_spans = [] if _is_hangar_frontage(spec) else _room_light_spans(spec, footprint=floor_plan.footprint)
        for index, (x0, x1, y0, y1) in enumerate(room_spans, start=1):
            marker_width = max(1.2, x1 - x0 - 0.55)
            marker_depth = max(1.4, y1 - y0 - 0.7)
            _create_runtime_marker_box(
                _name(prefix, f"Meta_Light_Room_F{floor:02d}_{index:02d}"),
                (marker_width, marker_depth, RUNTIME_MARKER_THICKNESS),
                ((x0 + x1) / 2, (y0 + y1) / 2, light_z),
                collection,
                parent,
                material,
                kind="LIGHT",
                role="ROOM",
                source_name=f"Floor_{floor:02d}",
            )
        if floor == 0:
            envelope = _front_entry_envelope(spec)
            _create_runtime_marker_box(
                _name(prefix, "Meta_Light_Entry_F00"),
                (max(2.0, envelope.landing_width), max(1.8, min(inner_depth, 2.4)), RUNTIME_MARKER_THICKNESS),
                (envelope.door_offset_x, inner_y0 + min(1.25, inner_depth / 2), base_z + ENTRY_LIGHT_HEIGHT_OFFSET),
                collection,
                parent,
                material,
                kind="LIGHT",
                role="ENTRY",
                source_name="MainDoor",
            )
        if spec.stair_core.enabled and floor < spatial_plan.stair_run_count:
            metrics = _dogleg_metrics(spec)
            _create_runtime_marker_box(
                _name(prefix, f"Meta_Light_Stair_F{floor:02d}"),
                (max(1.4, metrics.clear_width - 0.18), max(1.4, metrics.landing_depth + 0.9), RUNTIME_MARKER_THICKNESS),
                (metrics.cx, metrics.mid_landing_y, base_z + spec.floor_height * STAIR_LIGHT_HEIGHT_FACTOR),
                collection,
                parent,
                material,
                kind="LIGHT",
                role="STAIR",
                source_name=f"Stair_F{floor:02d}",
            )
    if spatial_plan.roof_room is not None:
        roof_exit_rect = spatial_plan.roof_room.footprint
        _create_runtime_marker_box(
            _name(prefix, "Meta_Light_RoofExit"),
            (
                max(1.8, roof_exit_rect[1] - roof_exit_rect[0] - 0.18),
                max(1.8, roof_exit_rect[3] - roof_exit_rect[2] - 0.18),
                RUNTIME_MARKER_THICKNESS,
            ),
            (
                (roof_exit_rect[0] + roof_exit_rect[1]) / 2,
                (roof_exit_rect[2] + roof_exit_rect[3]) / 2,
                spatial_plan.roof_room.base_z + spatial_plan.roof_room.height * 0.68,
            ),
            collection,
            parent,
            material,
            kind="LIGHT",
            role="ROOF_EXIT",
            source_name="RoofExit",
        )


def _build_export_contract_marker(prefix, collection, parent, material):
    marker = _create_box(
        export_contract.export_contract_marker_name(prefix),
        (0.08, 0.08, 0.08),
        (0.0, 0.0, 0.04),
        collection,
        parent,
        material,
    )
    marker = _mark_generated(
        marker,
        tbg_contract_marker=True,
        tbg_export_contract_version=export_contract.EXPORT_CONTRACT_VERSION,
    )
    if marker is not None:
        marker.display_type = "WIRE"
        marker.hide_render = True
        if hasattr(marker, "show_in_front"):
            marker.show_in_front = True
    return marker


def _build_runtime_markers(prefix, spec, spatial_plan, collection, parent, materials_map):
    _build_export_contract_marker(prefix, collection, parent, materials_map["helper"])
    _build_runtime_light_markers(prefix, spec, spatial_plan, collection, parent, materials_map["helper"])


def _stabilize_bottom_face_normals(bm: bmesh.types.BMesh, *, tolerance: float = 0.02) -> None:
    if bm is None or not bm.faces or not bm.verts:
        return
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    min_z = min(float(vertex.co.z) for vertex in bm.verts)
    threshold = min_z + float(tolerance)
    upward_bottom_faces = [
        face
        for face in bm.faces
        if float(face.calc_center_median().z) <= threshold and float(face.normal.z) > 0.35
    ]
    if not upward_bottom_faces:
        return
    bmesh.ops.reverse_faces(bm, faces=upward_bottom_faces)
    bm.normal_update()


def _join_mesh_objects(name: str, objects: list[bpy.types.Object], *, origin_to_geometry: bool = True):
    mesh_objects = [obj for obj in objects if obj is not None and obj.type == "MESH" and obj.name in bpy.data.objects]
    if not mesh_objects:
        return None
    if len(mesh_objects) == 1:
        mesh_objects[0].name = name
        if origin_to_geometry:
            _set_origin_to_geometry(mesh_objects[0])
        return mesh_objects[0]

    base = mesh_objects[0]
    base_matrix = base.matrix_world.copy()
    base_matrix_inv = base_matrix.inverted()
    collections = list(base.users_collection)
    parent = base.parent
    merged_mesh = bpy.data.meshes.new(name + "_Mesh")
    bm = bmesh.new()
    scratch_bm = bmesh.new()
    scratch_mesh = bpy.data.meshes.new(name + "_Scratch")
    for obj in mesh_objects:
        scratch_bm.clear()
        scratch_bm.from_mesh(obj.data)
        scratch_bm.verts.ensure_lookup_table()
        bmesh.ops.transform(
            scratch_bm,
            verts=scratch_bm.verts[:],
            matrix=base_matrix_inv @ obj.matrix_world,
        )
        scratch_mesh.clear_geometry()
        scratch_bm.to_mesh(scratch_mesh)
        bm.from_mesh(scratch_mesh)
    scratch_bm.free()
    bpy.data.meshes.remove(scratch_mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    _stabilize_bottom_face_normals(bm)
    bm.to_mesh(merged_mesh)
    bm.free()
    merged_mesh.update()
    merged = bpy.data.objects.new(name, merged_mesh)
    for collection in collections:
        collection.objects.link(merged)
    if parent is not None:
        _parent_to(merged, parent)
    merged.matrix_world = base_matrix
    for obj in mesh_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    if origin_to_geometry:
        _set_origin_to_geometry(merged)
    return merged


def _set_origin_to_geometry(obj):
    mesh = getattr(obj, "data", None)
    if obj is None or obj.type != "MESH" or mesh is None or not mesh.vertices:
        return
    local_center = Vector()
    for vertex in mesh.vertices:
        local_center += vertex.co
    local_center /= len(mesh.vertices)
    if local_center.length <= 1e-8:
        return
    transform = Matrix.Translation(-local_center)
    mesh.transform(transform)
    mesh.update()
    obj.matrix_world.translation = obj.matrix_world @ local_center


def _primary_material_for_object(obj) -> tuple[bpy.types.Material | None, str]:
    material = obj.material_slots[0].material if obj.material_slots else None
    return material, material.name if material is not None else ""


def _bucket_name_for_object(obj, material_name: str | None = None) -> str | None:
    authored_bucket = str(obj.get("tbg_section_bucket", ""))
    if authored_bucket:
        return authored_bucket
    return None

def _compact_section_bucket_name(bucket: str) -> str:
    side_map = {"front": "f", "back": "b", "left": "l", "right": "r"}
    if bucket.startswith("Section_Openings_Balcony_"):
        rest = bucket.removeprefix("Section_Openings_Balcony_")
        for side_key, side_short in side_map.items():
            rest = rest.replace(side_key, side_short)
        return "OBA_" + rest
    alias_map = {
        "Section_Openings_Frame": "OFR",
        "Section_Openings_WindowFill": "OWF",
        "Section_Openings_Trim_Wall": "OTW",
        "Section_Openings_Trim_Panel": "OTP",
        "Section_Walls_Exterior": "WEX",
        "Section_Walls_ExteriorSurfaceTile": "SFT",
        "Section_Walls_ExteriorShell": "WXS",
        "Section_Walls_Interior": "WIN",
        "Section_Stairs_RoomShell": "SRS",
        "Section_Walls_Roof": "WRF",
        "Section_Walls_Canopy": "WCN",
        "Section_Walls_Trim": "WTR",
        "Section_Floors": "FLR",
        "Section_Stairs_Flights": "STF",
        "Section_Stairs_Landings": "STL",
        "Section_Services_Prop": "SVP",
        "Section_Services_Helper": "SVH",
        "Section_Doors_Trim": "DTR",
        "Section_Doors_Prop": "DPR",
        "Section_Doors_Leaf": "DLF",
    }
    return alias_map.get(bucket, bucket.replace("Section_", "S_"))


def _section_merge_allowed(obj) -> bool:
    return bool(obj.get("tbg_section_merge_allowed", True))


def _section_hides_with_walls(obj, bucket: str) -> bool:
    if "tbg_hide_with_walls" in obj.keys():
        return bool(obj.get("tbg_hide_with_walls"))
    return bucket in _HIDE_WITH_WALLS_BUCKETS


def _classify_consolidation_object(obj) -> _ConsolidationClassification | None:
    material, material_name = _primary_material_for_object(obj)
    bucket = _bucket_name_for_object(obj, material_name)
    if bucket is None:
        return None
    return _ConsolidationClassification(
        obj=obj,
        bucket=bucket,
        merge_allowed=_section_merge_allowed(obj),
        hide_with_walls=_section_hides_with_walls(obj, bucket),
        material=material,
        material_name=material_name or "NoMaterial",
    )


def _is_brick_material(material: bpy.types.Material | None, material_name: str) -> bool:
    if material is not None:
        return bool(material.get("tbg_is_brick"))
    return "brick" in str(material_name).strip().lower()


def _preserved_exterior_shell_hint_for_object(obj) -> bool:
    if obj is None:
        return False
    return any(
        bool(obj.get(key))
        for key in (
            "tbg_preserved_exterior_shell",
            "tbg_hangar_portal",
            "tbg_roof_eave_fill",
            "tbg_timber_trim_band",
        )
    )


def resolve_exterior_fragment_stamp(
    root_obj,
    *,
    material: bpy.types.Material | None,
    material_name: str,
    bounds: tuple[float, float, float, float, float, float],
    facade_side: str,
    preserved_shell: bool,
    roof_exit_shell: bool,
    top_room_floor: bool,
    entry_canopy_present: bool,
) -> ExteriorFragmentStamp:
    if preserved_shell or roof_exit_shell or top_room_floor or entry_canopy_present:
        return ExteriorFragmentStamp(profile=_FRAGMENT_PROFILE_PRESERVE)
    if _is_brick_material(material, material_name):
        return ExteriorFragmentStamp(profile=_FRAGMENT_PROFILE_BRICK_GRID)
    return ExteriorFragmentStamp(profile=_FRAGMENT_PROFILE_PRESERVE)


def exterior_output_bucket_for_fragment_profile(profile: str) -> str:
    normalized = str(profile)
    if normalized == _FRAGMENT_PROFILE_BRICK_GRID:
        return _EXTERIOR_BRICK_BUCKET
    if normalized == _FRAGMENT_PROFILE_SURFACE_TILE:
        return _EXTERIOR_SURFACE_TILE_BUCKET
    return _EXTERIOR_SHELL_BUCKET


def _resolved_exterior_output_bucket(
    root_obj,
    *,
    material: bpy.types.Material | None,
    material_name: str,
    bounds: tuple[float, float, float, float, float, float],
    facade_side: str,
    preserved_shell: bool,
    roof_exit_shell: bool,
    top_room_floor: bool,
    entry_canopy_present: bool,
) -> str:
    stamp = resolve_exterior_fragment_stamp(
        root_obj,
        material=material,
        material_name=material_name,
        bounds=bounds,
        facade_side=facade_side,
        preserved_shell=preserved_shell,
        roof_exit_shell=roof_exit_shell,
        top_room_floor=top_room_floor,
        entry_canopy_present=entry_canopy_present,
    )
    return exterior_output_bucket_for_fragment_profile(stamp.profile)


def _apply_exterior_fragment_stamp_metadata(obj, stamp: ExteriorFragmentStamp) -> None:
    if obj is None:
        return
    obj[_FRAGMENT_PROFILE_KEY] = str(stamp.profile)
    if stamp.profile == _FRAGMENT_PROFILE_SURFACE_TILE:
        obj[_FRAGMENT_TILE_U_KEY] = float(stamp.tile_u or 0.0)
        obj[_FRAGMENT_TILE_V_KEY] = float(stamp.tile_v or 0.0)
        obj[_FRAGMENT_RUN_AXIS_KEY] = str(stamp.run_axis or "")
        return
    for key in (_FRAGMENT_TILE_U_KEY, _FRAGMENT_TILE_V_KEY, _FRAGMENT_RUN_AXIS_KEY):
        if key in obj.keys():
            del obj[key]


def ensure_exterior_fragment_stamp(
    root_obj,
    obj,
    *,
    bucket: str,
    material: bpy.types.Material | None = None,
    material_name: str | None = None,
) -> ExteriorFragmentStamp | None:
    if obj is None or str(bucket) != _EXTERIOR_BRICK_BUCKET:
        return None
    resolved_material = material
    resolved_material_name = str(material_name or "")
    if resolved_material is None and getattr(obj, "material_slots", None):
        resolved_material = obj.material_slots[0].material if obj.material_slots else None
    if not resolved_material_name:
        _material, resolved_material_name = _primary_material_for_object(obj)
        if resolved_material is None:
            resolved_material = _material
    stamp = resolve_exterior_fragment_stamp(
        root_obj,
        material=resolved_material,
        material_name=resolved_material_name,
        bounds=tuple(round(float(value), 4) for value in object_local_bounds(root_obj, obj)),
        facade_side=str(obj.get("tbg_facade_side", "") or ""),
        preserved_shell=_preserved_exterior_shell_hint_for_object(obj),
        roof_exit_shell=bool(obj.get("tbg_roof_exit_shell")),
        top_room_floor=bool(obj.get("tbg_top_room_floor")),
        entry_canopy_present=bool(obj.get("tbg_entry_canopy")),
    )
    _apply_exterior_fragment_stamp_metadata(obj, stamp)
    return stamp


def _apply_preserved_exterior_shell_metadata(obj, *, hide_with_walls: bool) -> None:
    if obj is None:
        return
    obj["tbg_section_bucket"] = _EXTERIOR_SHELL_BUCKET
    obj["tbg_hide_with_walls"] = bool(hide_with_walls)
    obj["tbg_preserved_exterior_shell"] = True
    if "tbg_exterior_brick" in obj.keys():
        del obj["tbg_exterior_brick"]


def _combined_source_bounds(root_obj, objects) -> list[float] | None:
    bounds_items = []
    for obj in objects:
        try:
            bounds_items.append(object_local_bounds(root_obj, obj))
        except ReferenceError:
            continue
    if not bounds_items:
        return None
    return [
        round(min(item[index] for item in bounds_items), 4) if index % 2 == 0 else round(max(item[index] for item in bounds_items), 4)
        for index in range(6)
    ]


def _freeze_bounds(bounds: list[float] | None) -> tuple[float, ...] | None:
    if bounds is None:
        return None
    return tuple(float(value) for value in bounds)


def _accumulate_bounds(existing: list[float] | None, incoming: list[float]) -> list[float]:
    if existing is None:
        return [float(value) for value in incoming]
    merged = list(existing)
    for index, value in enumerate(incoming):
        merged[index] = min(merged[index], value) if index % 2 == 0 else max(merged[index], value)
    return [round(value, 4) for value in merged]


def _exterior_brick_source_bounds(
    obj,
    root_obj,
) -> tuple[tuple[float, float, float, float, float, float], ...]:
    part_bounds = composite_part_root_local_bounds(root_obj, obj)
    if part_bounds:
        return tuple(tuple(float(value) for value in bounds) for bounds in part_bounds)
    return (tuple(round(float(value), 4) for value in object_local_bounds(root_obj, obj)),)


def _exterior_brick_sources_from_object(
    obj,
    classified: _ConsolidationClassification,
    root_obj,
) -> tuple[ExteriorBrickSource, ...]:
    stamp = ensure_exterior_fragment_stamp(
        root_obj,
        obj,
        bucket=classified.bucket,
        material=classified.material,
        material_name=classified.material_name,
    )
    preserved_shell = _preserved_exterior_shell_hint_for_object(obj)
    return tuple(
        ExteriorBrickSource(
            source_name=str(obj.name),
            bounds=tuple(float(value) for value in bounds),
            material_name=str(classified.material_name),
            material=classified.material,
            hide_with_walls=bool(classified.hide_with_walls),
            preserved_shell=bool(preserved_shell),
            roof_exit_shell=bool(obj.get("tbg_roof_exit_shell")),
            top_room_floor=bool(obj.get("tbg_top_room_floor")),
            entry_canopy_present=bool(obj.get("tbg_entry_canopy")),
            entrance_part=str(obj.get("tbg_entrance_part", "") or ""),
            facade_side=str(obj.get("tbg_facade_side", "") or ""),
            fragment_profile=str(stamp.profile if stamp is not None else _FRAGMENT_PROFILE_BRICK_GRID),
            fragment_tile_u=(float(stamp.tile_u) if stamp is not None and stamp.tile_u is not None else None),
            fragment_tile_v=(float(stamp.tile_v) if stamp is not None and stamp.tile_v is not None else None),
            fragment_run_axis=(str(stamp.run_axis) if stamp is not None and stamp.run_axis is not None else None),
        )
        for bounds in _exterior_brick_source_bounds(obj, root_obj)
    )


def _section_name(prefix: str, bucket_plan: ConsolidationBucketPlan) -> str:
    compact_bucket = _compact_section_bucket_name(bucket_plan.bucket)
    material_alias = bucket_plan.material_name.replace("TBG_", "")
    return _name(prefix, f"{compact_bucket}_{material_alias}")


def _partial_section_name(prefix: str, bucket_plan: ConsolidationBucketPlan, *, depth: int, index: int) -> str:
    compact_bucket = _compact_section_bucket_name(bucket_plan.bucket)
    material_alias = bucket_plan.material_name.replace("TBG_", "")
    return _name(prefix, f"{compact_bucket}_{material_alias}_P{depth:02d}_{index:03d}")


def _section_object_name(prefix: str, bucket_state: _FinalSectionBucketState) -> str:
    return final_section_object_name(prefix, bucket_state.bucket, bucket_state.material_name)


def final_section_object_name(prefix: str, bucket: str, material_name: str) -> str:
    compact_bucket = _compact_section_bucket_name(str(bucket))
    material_alias = str(material_name).replace("TBG_", "")
    return _name(prefix, f"{compact_bucket}_{material_alias}")


def _remap_section_object_name_for_prefix(name: str, *, source_prefix: str, target_prefix: str) -> str:
    source_prefix_token = f"{str(source_prefix)}_"
    if str(name).startswith(source_prefix_token):
        suffix = str(name)[len(source_prefix_token):]
        return _name(str(target_prefix), suffix)
    return str(name)


def iter_final_section_objects(root_obj) -> tuple[bpy.types.Object, ...]:
    if root_obj is None:
        return ()
    return tuple(
        child
        for child in root_obj.children_recursive
        if child is not None
        and child.type == "MESH"
        and bool(child.get("tbg_section_bucket"))
        and child.name in bpy.data.objects
    )


def iter_runtime_marker_objects(root_obj) -> tuple[bpy.types.Object, ...]:
    if root_obj is None:
        return ()
    return tuple(
        child
        for child in root_obj.children_recursive
        if child is not None
        and child.type == "MESH"
        and child.name in bpy.data.objects
        and (
            bool(child.get("tbg_contract_marker"))
            or (
                bool(child.get("tbg_runtime_marker"))
                and str(child.get("tbg_runtime_kind", "")) == export_contract.RUNTIME_KIND_LIGHT
            )
        )
    )


def iter_voxel_wall_marker_objects(root_obj) -> tuple[bpy.types.Object, ...]:
    if root_obj is None:
        return ()
    return tuple(
        child
        for child in root_obj.children_recursive
        if child is not None
        and child.type == "MESH"
        and child.name in bpy.data.objects
        and bool(child.get("tbg_voxel_wall_marker"))
    )


def iter_voxel_preview_cache_objects(root_obj) -> tuple[bpy.types.Object, ...]:
    if root_obj is None:
        return ()
    return tuple(
        child
        for child in root_obj.children_recursive
        if child is not None
        and child.type == "MESH"
        and child.name in bpy.data.objects
        and bool(child.get(_VOXEL_PREVIEW_TAG))
    )


def clear_voxel_preview_cache(root_obj) -> int:
    cleared = 0
    stale_meshes: list[bpy.types.Mesh] = []
    for helper_obj in iter_voxel_preview_cache_objects(root_obj):
        if helper_obj is None or helper_obj.name not in bpy.data.objects:
            continue
        mesh_data = helper_obj.data if helper_obj.type == "MESH" else None
        bpy.data.objects.remove(helper_obj, do_unlink=True)
        if isinstance(mesh_data, bpy.types.Mesh):
            stale_meshes.append(mesh_data)
        cleared += 1
    for mesh_data in stale_meshes:
        if mesh_data.name in bpy.data.meshes and mesh_data.users == 0:
            bpy.data.meshes.remove(mesh_data)
    return int(cleared)


def _candidate_visible_material_names_for_authored_wall(
    *,
    material_family: str,
    visual_style: str | None,
) -> tuple[str, ...]:
    family = str(material_family or "").strip().upper()
    style = str(visual_style or "").strip().upper() or None
    if family == "BRICK":
        return tuple(
            name
            for name in (
                "TBG_Wall",
                *(str(config.get("name", "")).strip() for config in BRICK_FAMILIES.values()),
            )
            if name
        )
    if family == "WOOD" and style == "TIMBER_PAINTED":
        return (_flat_panel_material_name("PAINTED_WOOD"),)
    if family == "WOOD":
        return (
            _flat_panel_material_name("TIMBER_WARM"),
            _flat_panel_material_name("TIMBER_WEATHERED"),
        )
    if family == "CONCRETE":
        return (_flat_panel_material_name("CONCRETE_FLAT"),)
    if family == "METAL":
        return (str(INDUSTRIAL_CLADDING_MATERIAL_NAME),)
    return (
        _flat_panel_material_name("PLASTER_WARM"),
        _flat_panel_material_name("PLASTER_COOL"),
        _flat_panel_material_name("SANDSTONE_FLAT"),
        *(
            _brick_panel_material_name(family_key)
            for family_key in sorted(BRICK_FAMILIES)
        ),
    )


def _flat_panel_material_name(family_key: str) -> str:
    wall_name = str(FLAT_FACADE_FAMILIES[str(family_key)]["name"])
    return wall_name.replace("TBG_Wall_", "TBG_Panel_", 1)


def _brick_panel_material_name(family_key: str) -> str:
    wall_name = str(BRICK_FAMILIES[str(family_key)]["name"])
    return wall_name.replace("TBG_Wall_", "TBG_Panel_", 1)


def _visible_material_color_distance_sq(
    *,
    display_color_rgb: tuple[int, int, int] | None,
    material_name: str,
) -> float:
    if display_color_rgb is None:
        return 0.0
    candidate_color = resolve_voxel_wall_display_color_rgb(material_name)
    if candidate_color is None:
        return float("inf")
    return (
        float(candidate_color["r"] - int(display_color_rgb[0])) ** 2
        + float(candidate_color["g"] - int(display_color_rgb[1])) ** 2
        + float(candidate_color["b"] - int(display_color_rgb[2])) ** 2
    )


def _resolve_visible_material_for_authored_wall(
    *,
    material_family: str,
    visual_style: str | None,
    display_color_rgb: tuple[int, int, int] | None,
    texture_key: str = "",
    texture_projection: str = "",
) -> tuple[bpy.types.Material | None, str]:
    projection = str(texture_projection or "").strip().upper()
    if projection in {
        export_contract.TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1,
        export_contract.TEXTURE_PROJECTION_SOLID_COLOR_V1,
    }:
        preview = ensure_v3_wall_texture_preview_material(
            texture_key=texture_key or f"wall_{str(material_family or 'unknown').lower()}_{str(visual_style or 'solid').lower()}",
            material_family=material_family,
            visual_style=visual_style,
            display_color_rgb=display_color_rgb,
        )
        return preview, str(preview.name)
    candidate_names = _candidate_visible_material_names_for_authored_wall(
        material_family=material_family,
        visual_style=visual_style,
    )
    resolved_materials: list[tuple[str, bpy.types.Material]] = []
    for material_name in candidate_names:
        material = bpy.data.materials.get(str(material_name))
        if material is not None:
            resolved_materials.append((str(material_name), material))
    if not resolved_materials:
        fallback_name = candidate_names[0] if candidate_names else "NoMaterial"
        return None, str(fallback_name)
    if len(resolved_materials) == 1 or display_color_rgb is None:
        material_name, material = resolved_materials[0]
        return material, material_name
    material_name, material = min(
        resolved_materials,
        key=lambda item: (
            _visible_material_color_distance_sq(
                display_color_rgb=display_color_rgb,
                material_name=item[0],
            ),
            item[0],
        ),
    )
    return material, material_name


@dataclass(frozen=True)
class _AuthoredVisibleWallTextureEntry:
    cell_id: str
    group_id: str
    bounds: tuple[float, float, float, float, float, float]
    normal_axis: str
    texture_key: str
    texture_projection: str
    texture_image_period_contract: str
    texture_face_axis_table_version: str
    studs_per_tile_u: float
    studs_per_tile_v: float
    surface_u_origin_studs: float
    surface_v_origin_studs: float
    material_family: str
    visual_style: str | None
    display_color_rgb: tuple[int, int, int] | None
    color_modulation_policy: str


@dataclass(frozen=True)
class _AuthoredVisibleWallSection:
    object_name: str
    bucket_plan: ConsolidationBucketPlan
    parts: tuple[tuple[tuple[float, float, float], tuple[float, float, float]], ...]
    group_ids: tuple[str, ...]
    cell_ids: tuple[str, ...]
    cell_count: int
    bounds: tuple[float, float, float, float, float, float]
    source_fragments: tuple[dict[str, object], ...]
    texture_entries: tuple[_AuthoredVisibleWallTextureEntry, ...]


@dataclass(frozen=True)
class AuthoredVisibleWallEmissionSummary:
    object_count: int
    scalar_cell_count: int
    composite_cell_count: int
    object_names: tuple[str, ...]


def _display_color_dict(color: tuple[int, int, int] | None) -> dict[str, int] | None:
    if color is None:
        return None
    return {"r": int(color[0]), "g": int(color[1]), "b": int(color[2])}


def _merge_bounds(
    current: tuple[float, float, float, float, float, float] | None,
    bounds: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    if current is None:
        return tuple(float(value) for value in bounds)
    return (
        min(float(current[0]), float(bounds[0])),
        max(float(current[1]), float(bounds[1])),
        min(float(current[2]), float(bounds[2])),
        max(float(current[3]), float(bounds[3])),
        min(float(current[4]), float(bounds[4])),
        max(float(current[5]), float(bounds[5])),
    )


def _canonical_cell_bounds_for_section(cell) -> tuple[float, float, float, float, float, float]:
    bounds = cell.bounds
    return (
        float(bounds.x_min),
        float(bounds.x_max),
        float(bounds.y_min),
        float(bounds.y_max),
        float(bounds.z_min),
        float(bounds.z_max),
    )


def _authored_visible_wall_section_object_name(
    prefix: str,
    *,
    bucket: str,
    material_name: str,
) -> str:
    return final_section_object_name(prefix, bucket, material_name)


def _authored_visible_wall_sections(
    prefix: str,
    canonicalization: OccupancyCanonicalization,
) -> tuple[_AuthoredVisibleWallSection, ...]:
    grouped_parts: dict[tuple[str, str], list[tuple[tuple[float, float, float], tuple[float, float, float]]]] = {}
    grouped_group_ids: dict[tuple[str, str], set[str]] = {}
    grouped_cell_counts: dict[tuple[str, str], int] = {}
    grouped_bounds: dict[tuple[str, str], tuple[float, float, float, float, float, float]] = {}
    grouped_source_fragments: dict[tuple[str, str], list[dict[str, object]]] = {}
    grouped_cell_ids: dict[tuple[str, str], list[str]] = {}
    grouped_texture_entries: dict[tuple[str, str], list[_AuthoredVisibleWallTextureEntry]] = {}
    bucket_plans: dict[tuple[str, str], ConsolidationBucketPlan] = {}
    for group in tuple(getattr(canonicalization, "groups", ())):
        material, material_name = _resolve_visible_material_for_authored_wall(
            material_family=str(group.material_family),
            visual_style=str(group.visual_style) if group.visual_style else None,
            display_color_rgb=tuple(group.display_color_rgb) if group.display_color_rgb is not None else None,
            texture_key=str(group.texture_key or ""),
            texture_projection=str(group.texture_projection or ""),
        )
        for cell in group.cells:
            key = (str(group.source_bucket), str(material_name))
            grouped_group_ids.setdefault(key, set()).add(str(group.group_id))
            grouped_cell_counts[key] = int(grouped_cell_counts.get(key, 0)) + 1
            grouped_cell_ids.setdefault(key, []).append(str(cell.cell_id))
            bounds = _canonical_cell_bounds_for_section(cell)
            grouped_bounds[key] = _merge_bounds(grouped_bounds.get(key), bounds)
            grouped_parts.setdefault(key, []).append(
                (
                    cell.bounds.size_studs(),
                    (
                        float(cell.bounds.x_min + (cell.bounds.x_max - cell.bounds.x_min) * 0.5),
                        float(cell.bounds.y_min + (cell.bounds.y_max - cell.bounds.y_min) * 0.5),
                        float(cell.bounds.z_min + (cell.bounds.z_max - cell.bounds.z_min) * 0.5),
                    ),
                )
            )
            grouped_texture_entries.setdefault(key, []).append(
                _AuthoredVisibleWallTextureEntry(
                    cell_id=str(cell.cell_id),
                    group_id=str(cell.group_id),
                    bounds=tuple(float(value) for value in bounds),
                    normal_axis=str(cell.normal_axis),
                    texture_key=str(cell.texture_key or group.texture_key or ""),
                    texture_projection=str(cell.texture_projection or group.texture_projection or ""),
                    texture_image_period_contract=str(
                        cell.texture_image_period_contract or group.texture_image_period_contract or ""
                    ),
                    texture_face_axis_table_version=str(
                        cell.texture_face_axis_table_version or group.texture_face_axis_table_version or ""
                    ),
                    studs_per_tile_u=float(cell.studs_per_tile_u or group.studs_per_tile_u or 1.0),
                    studs_per_tile_v=float(cell.studs_per_tile_v or group.studs_per_tile_v or 1.0),
                    surface_u_origin_studs=float(cell.surface_u_origin_studs if cell.surface_u_origin_studs is not None else 0.0),
                    surface_v_origin_studs=float(cell.surface_v_origin_studs if cell.surface_v_origin_studs is not None else 0.0),
                    material_family=str(cell.material_family),
                    visual_style=str(cell.visual_style) if cell.visual_style else None,
                    display_color_rgb=tuple(cell.display_color_rgb) if cell.display_color_rgb is not None else None,
                    color_modulation_policy=str(cell.color_modulation_policy or group.color_modulation_policy or ""),
                )
            )
            grouped_source_fragments.setdefault(key, []).append(
                {
                    "source_name": str(cell.cell_id),
                    "bounds": [float(value) for value in bounds],
                    "part_bounds": [[float(value) for value in bounds]],
                    "preserved_shell": False,
                    "material_family": str(cell.material_family),
                    "visual_style": str(cell.visual_style) if cell.visual_style else None,
                    "display_color_rgb": _display_color_dict(cell.display_color_rgb),
                    "texture_key": str(cell.texture_key or group.texture_key or ""),
                    "texture_projection": str(cell.texture_projection or group.texture_projection or ""),
                    "texture_image_period_contract": str(cell.texture_image_period_contract or group.texture_image_period_contract or ""),
                    "texture_face_axis_table_version": str(cell.texture_face_axis_table_version or group.texture_face_axis_table_version or ""),
                    "studs_per_tile_u": float(cell.studs_per_tile_u or group.studs_per_tile_u or 1.0),
                    "studs_per_tile_v": float(cell.studs_per_tile_v or group.studs_per_tile_v or 1.0),
                    "color_modulation_policy": str(cell.color_modulation_policy or group.color_modulation_policy or ""),
                    "fragment_profile": "",
                    "fragment_tile_u": None,
                    "fragment_tile_v": None,
                    "fragment_run_axis": None,
                    "roof_exit_shell": False,
                    "top_room_floor": False,
                    "stair_flight": False,
                    "stair_direction": None,
                    "entrance_part": "",
                    "facade_side": "",
                    "cell_id": str(cell.cell_id),
                    "group_id": str(cell.group_id),
                    "source_fragment_ids": list(cell.source_fragment_ids),
                    "staged_object_names": list(cell.staged_object_names),
                }
            )
            bucket_plans[key] = ConsolidationBucketPlan(
                bucket=str(group.source_bucket),
                material_name=str(material_name),
                items=(),
                material=material,
                hide_with_walls=str(group.source_bucket) in _HIDE_WITH_WALLS_BUCKETS,
            )
    sections: list[_AuthoredVisibleWallSection] = []
    for key in sorted(grouped_parts):
        parts = tuple(grouped_parts.get(key, ()))
        bounds = grouped_bounds.get(key)
        if not parts or bounds is None:
            continue
        sections.append(
            _AuthoredVisibleWallSection(
                object_name=_authored_visible_wall_section_object_name(
                    prefix,
                    bucket=bucket_plans[key].bucket,
                    material_name=bucket_plans[key].material_name,
                ),
                bucket_plan=bucket_plans[key],
                parts=parts,
                group_ids=tuple(sorted(group_id for group_id in grouped_group_ids.get(key, set()) if group_id)),
                cell_ids=tuple(sorted(grouped_cell_ids.get(key, ()))),
                cell_count=int(grouped_cell_counts.get(key, 0)),
                bounds=tuple(round(float(value), 4) for value in bounds),
                source_fragments=tuple(grouped_source_fragments.get(key, ())),
                texture_entries=tuple(grouped_texture_entries.get(key, ())),
            )
        )
    return tuple(sections)


def authored_visible_wall_section_registry_entries(
    prefix: str,
    canonicalization: OccupancyCanonicalization,
) -> tuple[dict[str, object], ...]:
    entries: list[dict[str, object]] = []
    for section in _authored_visible_wall_sections(prefix, canonicalization):
        bucket_plan = section.bucket_plan
        material_metadata = resolve_authored_voxel_wall_material_metadata(bucket_plan.material_name)
        entries.append(
            {
                "name": section.object_name,
                "bucket": bucket_plan.bucket,
                "material_name": bucket_plan.material_name,
                "material_family": str(material_metadata.material_family) if material_metadata is not None else None,
                "visual_style": (
                    str(material_metadata.visual_style)
                    if material_metadata is not None and material_metadata.visual_style
                    else None
                ),
                "display_color_rgb": (
                    dict(material_metadata.display_color_rgb)
                    if material_metadata is not None and material_metadata.display_color_rgb is not None
                    else None
                ),
                "merge_allowed": True,
                "hide_with_walls": bool(bucket_plan.hide_with_walls),
                "preserved_shell": False,
                "roof_exit_shell": False,
                "top_room_floor": False,
                "bounds": [float(value) for value in section.bounds],
                "source_fragments": list(section.source_fragments),
                "cell_count": int(section.cell_count),
                "cell_ids": list(section.cell_ids),
                "source_count": int(section.cell_count),
                "tbg_wall_emit_owner": "occupancy_v3",
                "tbg_wall_group_ids": list(section.group_ids),
                "texture_keys": sorted({entry.texture_key for entry in section.texture_entries if entry.texture_key}),
                "texture_projection": _section_uniform_texture_value(section, "texture_projection"),
                "texture_image_period_contract": _section_uniform_texture_value(section, "texture_image_period_contract"),
                "texture_face_axis_table_version": _section_uniform_texture_value(section, "texture_face_axis_table_version"),
            }
        )
    return tuple(entries)


def _visible_wall_surface_run_axis(bounds: tuple[float, float, float, float, float, float]) -> str:
    x_span = abs(float(bounds[1]) - float(bounds[0]))
    y_span = abs(float(bounds[3]) - float(bounds[2]))
    return "X" if x_span >= y_span else "Y"


def _section_uniform_texture_value(section: _AuthoredVisibleWallSection, field_name: str) -> str:
    values = sorted({str(getattr(entry, field_name, "") or "") for entry in section.texture_entries})
    values = [value for value in values if value]
    if len(values) == 1:
        return values[0]
    return "MIXED" if values else ""


def _section_texture_uv_source(section: _AuthoredVisibleWallSection) -> str:
    projections = {entry.texture_projection for entry in section.texture_entries}
    if export_contract.TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1 in projections:
        return _V3_WALL_UV_SOURCE_ROBLOX_TEXTURE
    return _V3_WALL_UV_SOURCE_MATERIAL_STYLE


def _axis_coord(co, axis: str) -> float:
    if axis == "x":
        return float(co.x)
    if axis == "y":
        return float(co.y)
    if axis == "z":
        return float(co.z)
    raise ValueError(f"Unsupported texture coordinate axis: {axis!r}.")


def _axis_bounds(bounds: tuple[float, float, float, float, float, float], axis: str) -> tuple[float, float]:
    if axis == "x":
        return float(bounds[0]), float(bounds[1])
    if axis == "y":
        return float(bounds[2]), float(bounds[3])
    if axis == "z":
        return float(bounds[4]), float(bounds[5])
    raise ValueError(f"Unsupported texture bounds axis: {axis!r}.")


def _roblox_material_variant_axis_phase(
    *,
    coord: float,
    bounds: tuple[float, float, float, float, float, float],
    axis: str,
    sign: float,
) -> float:
    axis_min, axis_max = _axis_bounds(bounds, axis)
    if sign < 0.0:
        return axis_max - float(coord)
    return float(coord) - axis_min


def _ensure_material_slot(obj, material) -> int:
    if material is None:
        return 0
    for index, slot in enumerate(obj.material_slots):
        if slot.material is material:
            return index
    if len(obj.data.materials) == 1:
        obj.data.materials[0] = material
        return 0
    obj.data.materials.append(material)
    return len(obj.data.materials) - 1


def _entry_preview_material(entry: _AuthoredVisibleWallTextureEntry, fallback_material):
    if entry.texture_projection != export_contract.TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1:
        return fallback_material
    return ensure_v3_wall_texture_preview_material(
        texture_key=entry.texture_key,
        material_family=entry.material_family,
        visual_style=entry.visual_style,
        display_color_rgb=entry.display_color_rgb,
    )


def _apply_v3_visible_wall_material_style_uv(obj, section: _AuthoredVisibleWallSection) -> None:
    mesh = getattr(obj, "data", None)
    if mesh is None or not hasattr(mesh, "uv_layers"):
        return
    faces_per_part = len(export_contract.COMPOSITE_BOX_FACE_ORDER_V1)
    if len(mesh.polygons) < len(section.texture_entries) * faces_per_part:
        raise VoxelWallOccupancyContractError(
            f"Visible V3 wall section '{section.object_name}' has too few composite faces for material-style UV preview."
        )
    uv_layer = mesh.uv_layers.get("TBG_UV")
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="TBG_UV")
    mesh.uv_layers.active = uv_layer
    for part_index, entry in enumerate(section.texture_entries):
        for normal_sign in ("+", "-"):
            table = export_contract.TEXTURE_FACE_AXIS_TABLE_V1.get((entry.normal_axis, normal_sign))
            if table is None:
                raise VoxelWallOccupancyContractError(
                    f"Visible V3 wall section '{section.object_name}' has unsupported normal axis {entry.normal_axis!r}."
                )
            poly = mesh.polygons[part_index * faces_per_part + int(table["composite_face_index"])]
            u_axis = str(table["u_axis"])
            v_axis = str(table["v_axis"])
            u_sign = float(table["u_sign"])
            v_sign = float(table["v_sign"])
            period_u = max(1e-6, float(entry.studs_per_tile_u))
            period_v = max(1e-6, float(entry.studs_per_tile_v))
            for loop_index in poly.loop_indices:
                co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
                # Roblox MaterialVariant has no per-Part phase/offset. Preview each
                # authored cell as a fresh BasePart-local tile so Blender exposes the
                # same reset seams as Studio instead of a false root-local UV phase.
                phase_u = _roblox_material_variant_axis_phase(
                    coord=_axis_coord(co, u_axis),
                    bounds=entry.bounds,
                    axis=u_axis,
                    sign=u_sign,
                )
                phase_v = _roblox_material_variant_axis_phase(
                    coord=_axis_coord(co, v_axis),
                    bounds=entry.bounds,
                    axis=v_axis,
                    sign=v_sign,
                )
                uv_layer.data[loop_index].uv = (phase_u / period_u, phase_v / period_v)


def _apply_v3_visible_wall_roblox_part_texture_uv(obj, section: _AuthoredVisibleWallSection) -> bool:
    if obj is None or obj.type != "MESH" or not section.texture_entries:
        return False
    mesh = getattr(obj, "data", None)
    if mesh is None or not hasattr(mesh, "uv_layers"):
        return False
    if len(section.texture_entries) != len(section.parts):
        raise VoxelWallOccupancyContractError(
            f"Visible V3 wall section '{section.object_name}' texture-entry count does not match composite parts "
            f"({len(section.texture_entries)} != {len(section.parts)})."
        )
    needs_part_texture_uv = any(
        entry.texture_projection == export_contract.TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1
        for entry in section.texture_entries
    )
    faces_per_part = len(export_contract.COMPOSITE_BOX_FACE_ORDER_V1)
    if len(mesh.polygons) < len(section.texture_entries) * faces_per_part:
        raise VoxelWallOccupancyContractError(
            f"Visible V3 wall section '{section.object_name}' has too few composite faces for texture contract."
        )
    if not needs_part_texture_uv:
        material = section.bucket_plan.material
        if (
            material is not None
            and str(material.get("tbg_roblox_basepart_sim_pattern", "")) == "BRICK_MASONRY"
            and bool(material_uv_settings(material)["requires_uv"])
        ):
            _apply_v3_visible_wall_material_style_uv(obj, section)
        obj["tbg_texture_projection"] = _section_uniform_texture_value(section, "texture_projection")
        obj["tbg_texture_image_period_contract"] = _section_uniform_texture_value(section, "texture_image_period_contract")
        obj["tbg_texture_uv_source"] = _section_texture_uv_source(section)
        obj["tbg_texture_contract_cell_count"] = int(len(section.texture_entries))
        obj["tbg_texture_key_set_json"] = json.dumps(
            sorted({entry.texture_key for entry in section.texture_entries if entry.texture_key}),
            separators=(",", ":"),
        )
        obj["tbg_texture_face_axis_table_version"] = _section_uniform_texture_value(section, "texture_face_axis_table_version")
        if "tbg_brick_uv_space" in obj.keys():
            del obj["tbg_brick_uv_space"]
        return True

    uv_layer = mesh.uv_layers.get("TBG_UV")
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="TBG_UV")
    mesh.uv_layers.active = uv_layer
    material_slots: dict[str, int] = {}
    for part_index, entry in enumerate(section.texture_entries):
        if entry.texture_projection != export_contract.TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1:
            continue
        if entry.texture_image_period_contract != export_contract.TEXTURE_IMAGE_PERIOD_REPEAT_FULL_IMAGE_EQUALS_STUDS_PER_TILE:
            raise VoxelWallOccupancyContractError(
                f"Visible V3 wall section '{section.object_name}' uses unsupported texture period contract "
                f"{entry.texture_image_period_contract!r}."
            )
        if entry.texture_face_axis_table_version != export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1:
            raise VoxelWallOccupancyContractError(
                f"Visible V3 wall section '{section.object_name}' uses unsupported face-axis table "
                f"{entry.texture_face_axis_table_version!r}."
            )
        for normal_sign in ("+", "-"):
            table = export_contract.TEXTURE_FACE_AXIS_TABLE_V1.get((entry.normal_axis, normal_sign))
            if table is None:
                raise VoxelWallOccupancyContractError(
                    f"Visible V3 wall section '{section.object_name}' has unsupported normal axis {entry.normal_axis!r}."
                )
            poly_index = part_index * faces_per_part + int(table["composite_face_index"])
            poly = mesh.polygons[poly_index]
            material_key = entry.texture_key
            if material_key not in material_slots:
                material_slots[material_key] = _ensure_material_slot(
                    obj,
                    _entry_preview_material(entry, section.bucket_plan.material),
                )
            poly.material_index = material_slots[material_key]
            u_axis = str(table["u_axis"])
            v_axis = str(table["v_axis"])
            u_sign = float(table["u_sign"])
            v_sign = float(table["v_sign"])
            period_u = max(1e-6, float(entry.studs_per_tile_u))
            period_v = max(1e-6, float(entry.studs_per_tile_v))
            for loop_index in poly.loop_indices:
                co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
                phase_u = u_sign * (_axis_coord(co, u_axis) - float(entry.surface_u_origin_studs))
                phase_v = v_sign * (_axis_coord(co, v_axis) - float(entry.surface_v_origin_studs))
                uv_layer.data[loop_index].uv = (phase_u / period_u, phase_v / period_v)
    obj["tbg_texture_projection"] = _section_uniform_texture_value(section, "texture_projection")
    obj["tbg_texture_image_period_contract"] = _section_uniform_texture_value(section, "texture_image_period_contract")
    obj["tbg_texture_uv_source"] = _section_texture_uv_source(section)
    obj["tbg_texture_contract_cell_count"] = int(len(section.texture_entries))
    obj["tbg_texture_key_set_json"] = json.dumps(
        sorted({entry.texture_key for entry in section.texture_entries if entry.texture_key}),
        separators=(",", ":"),
    )
    obj["tbg_texture_face_axis_table_version"] = _section_uniform_texture_value(section, "texture_face_axis_table_version")
    if "tbg_brick_uv_space" in obj.keys():
        del obj["tbg_brick_uv_space"]
    return True


def _apply_visible_panel_face_fit_uv(obj, material) -> bool:
    if obj is None or obj.type != "MESH" or material is None:
        return False
    if not str(getattr(material, "name", "")).startswith("TBG_Panel_"):
        return False
    mesh = getattr(obj, "data", None)
    if mesh is None or not hasattr(mesh, "uv_layers"):
        return False
    uv_settings = material_uv_settings(material)
    if not bool(uv_settings["requires_uv"]) or bool(uv_settings["is_brick"]):
        return False
    uv_layer = mesh.uv_layers.get("TBG_UV")
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="TBG_UV")
    mesh.uv_layers.active = uv_layer
    u0, v0, u1, v1 = uv_settings["uv_rect"]
    span_u = max(1e-6, float(u1) - float(u0))
    span_v = max(1e-6, float(v1) - float(v0))
    inset = max(0.0, min(0.45, float(uv_settings["island_inset"])))
    usable_span = max(0.0, 1.0 - inset * 2.0)
    for poly in mesh.polygons:
        normal = poly.normal
        ax, ay, az = abs(normal.x), abs(normal.y), abs(normal.z)
        raw_coords: list[tuple[int, float, float]] = []
        for loop_index in poly.loop_indices:
            co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            if az >= ax and az >= ay:
                raw_coords.append((loop_index, float(co.x), float(co.y)))
            elif ax >= ay:
                raw_coords.append((loop_index, float(co.y), float(co.z)))
            else:
                raw_coords.append((loop_index, float(co.x), float(co.z)))
        if not raw_coords:
            continue
        min_raw_u = min(item[1] for item in raw_coords)
        max_raw_u = max(item[1] for item in raw_coords)
        min_raw_v = min(item[2] for item in raw_coords)
        max_raw_v = max(item[2] for item in raw_coords)
        raw_span_u = max(1e-6, max_raw_u - min_raw_u)
        raw_span_v = max(1e-6, max_raw_v - min_raw_v)
        for loop_index, raw_u, raw_v in raw_coords:
            normalized_u = inset + max(0.0, min(1.0, (raw_u - min_raw_u) / raw_span_u)) * usable_span
            normalized_v = inset + max(0.0, min(1.0, (raw_v - min_raw_v) / raw_span_v)) * usable_span
            uv_layer.data[loop_index].uv = (
                float(u0) + normalized_u * span_u,
                float(v0) + normalized_v * span_v,
            )
    return True


def _apply_visible_wall_surface_uv(obj, section: _AuthoredVisibleWallSection) -> None:
    if obj is None or obj.type != "MESH":
        return
    if _apply_v3_visible_wall_roblox_part_texture_uv(obj, section):
        return
    if _apply_visible_panel_face_fit_uv(obj, section.bucket_plan.material):
        return
    obj[_SURFACE_TILE_UV_SPACE_KEY] = _SURFACE_TILE_UV_SPACE_ROOT_SOURCE
    obj[_SURFACE_TILE_UV_BOUNDS_KEY] = [float(value) for value in section.bounds]
    obj[_SURFACE_TILE_UV_RUN_AXIS_KEY] = _visible_wall_surface_run_axis(section.bounds)
    _apply_material_uv(obj, section.bucket_plan.material)


def _create_authored_visible_wall_object(
    section: _AuthoredVisibleWallSection,
    collection,
    root_obj,
):
    return _create_composite_box_object(
        section.object_name,
        list(section.parts),
        (0.0, 0.0, 0.0),
        collection,
        root_obj,
        section.bucket_plan.material,
    )


def emit_visible_authored_wall_sections_from_canonicalization(
    prefix: str,
    root_obj,
    collection,
    canonicalization: OccupancyCanonicalization,
) -> AuthoredVisibleWallEmissionSummary:
    expected_cell_count = len(tuple(getattr(canonicalization, "cells", ())))
    if expected_cell_count <= 0:
        return AuthoredVisibleWallEmissionSummary(
            object_count=0,
            scalar_cell_count=0,
            composite_cell_count=0,
            object_names=(),
        )
    if root_obj is None or collection is None:
        raise VoxelWallOccupancyContractError(
            "Authored wall cells exist, but visible wall emission has no root/structure collection."
        )

    sections = _authored_visible_wall_sections(prefix, canonicalization)
    if not sections:
        raise VoxelWallOccupancyContractError(
            f"Authored wall cells exist ({expected_cell_count}), but no visible V3 wall sections were planned."
        )

    object_names: list[str] = []
    scalar_cell_count = 0
    composite_cell_count = 0
    for section in sections:
        bucket_plan = section.bucket_plan
        merged = _create_authored_visible_wall_object(section, collection, root_obj)
        if merged is None:
            raise VoxelWallOccupancyContractError(
                f"Visible V3 wall section '{section.object_name}' was not created."
            )
        merged.matrix_basis = Matrix.Identity(4)
        _apply_final_bucket_contract(
            merged,
            bucket_plan,
            roof_exit_shell_bounds=None,
            top_room_floor_bounds=None,
            entry_canopy_present=False,
            v3_visible_wall=True,
        )
        _apply_visible_wall_surface_uv(merged, section)
        if section.group_ids:
            merged["tbg_wall_group_id"] = section.group_ids[0]
            merged["tbg_wall_group_ids_json"] = json.dumps(list(section.group_ids), separators=(",", ":"))
        merged["tbg_wall_group_count"] = int(len(section.group_ids))
        merged["tbg_wall_emit_owner"] = "occupancy_v3"
        merged["tbg_wall_payload_kind"] = export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND
        merged["tbg_wall_payload_version"] = export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION
        merged["tbg_wall_export_contract_version"] = export_contract.EXPORT_CONTRACT_VERSION
        merged["tbg_wall_source_bucket"] = bucket_plan.bucket
        merged["tbg_wall_hidden_with_walls"] = bool(bucket_plan.hide_with_walls)
        merged["tbg_wall_cell_count"] = int(section.cell_count)

        composite_bounds = composite_part_root_local_bounds(root_obj, merged)
        composite_count = int(len(composite_bounds))
        if composite_count != int(section.cell_count):
            bpy.data.objects.remove(merged, do_unlink=True)
            raise VoxelWallOccupancyContractError(
                f"Visible V3 wall section '{section.object_name}' composite part count drifted "
                f"from its cell stamp ({composite_count} != {int(section.cell_count)})."
            )
        object_names.append(str(merged.name))
        scalar_cell_count += int(section.cell_count)
        composite_cell_count += composite_count

    if not object_names:
        raise VoxelWallOccupancyContractError(
            f"Authored wall cells exist ({expected_cell_count}), but no visible V3 wall objects were emitted."
        )
    if scalar_cell_count != expected_cell_count or composite_cell_count != expected_cell_count:
        raise VoxelWallOccupancyContractError(
            "Visible V3 wall cell count drifted from authored payload: "
            f"payload={expected_cell_count}, scalar={scalar_cell_count}, composite={composite_cell_count}."
        )

    return AuthoredVisibleWallEmissionSummary(
        object_count=len(object_names),
        scalar_cell_count=int(scalar_cell_count),
        composite_cell_count=int(composite_cell_count),
        object_names=tuple(object_names),
    )


def _material_family_for_voxel_wall(material_name: str) -> str:
    canonical_metadata = resolve_authored_voxel_wall_material_metadata(material_name)
    if canonical_metadata is not None:
        return str(canonical_metadata.material_family)
    return "PLASTER"


def _visual_style_for_voxel_wall(material_name: str) -> str | None:
    canonical_metadata = resolve_authored_voxel_wall_material_metadata(material_name)
    if canonical_metadata is None:
        return None
    return str(canonical_metadata.visual_style) if canonical_metadata.visual_style else None


def _summary_child_bounds(child) -> tuple[float, float, float, float, float, float] | None:
    bounds = getattr(child, "bounds", None)
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 6:
        return None
    try:
        return tuple(float(value) for value in bounds)
    except (TypeError, ValueError):
        return None


def _window_opening_candidate_from_summary(child) -> dict[str, object] | None:
    if not bool(child.get("tbg_window_marker")):
        return None
    bounds = _summary_child_bounds(child)
    if bounds is None:
        return None
    opening_width = float(child.get("tbg_window_opening_width", 0.0) or 0.0)
    opening_height = float(child.get("tbg_window_opening_height", 0.0) or 0.0)
    if opening_width <= 1e-5 or opening_height <= 1e-5:
        return None
    side_key = str(child.get("tbg_window_side", "") or "").lower()
    center_x = (bounds[0] + bounds[1]) * 0.5
    center_y = (bounds[2] + bounds[3]) * 0.5
    center_z = (bounds[4] + bounds[5]) * 0.5
    if side_key in {"front", "back"}:
        raw_bounds = (
            center_x - opening_width / 2,
            center_x + opening_width / 2,
            bounds[2],
            bounds[3],
            center_z - opening_height / 2,
            center_z + opening_height / 2,
        )
    elif side_key in {"left", "right"}:
        raw_bounds = (
            bounds[0],
            bounds[1],
            center_y - opening_width / 2,
            center_y + opening_width / 2,
            center_z - opening_height / 2,
            center_z + opening_height / 2,
        )
    else:
        return None
    if bool(child.get("tbg_balcony_access")):
        kind = "BALCONY_ACCESS"
    elif bool(child.get("tbg_window_open")):
        kind = "WINDOW_OPEN"
    else:
        kind = "WINDOW_CLOSED"
    return {
        "kind": kind,
        "source_name": str(getattr(child, "name", "") or "WindowOpening"),
        "bounds": raw_bounds,
    }


def _door_opening_candidate_from_summary(child) -> dict[str, object] | None:
    if not bool(child.get("tbg_is_door_leaf")):
        return None
    if bool(child.get("tbg_roof_exit_door")) or "Door_RoofExit" in str(getattr(child, "name", "")):
        return None
    bounds = _summary_child_bounds(child)
    if bounds is None:
        return None
    return {
        "kind": "DOOR",
        "source_name": str(getattr(child, "name", "") or "DoorOpening"),
        "bounds": bounds,
    }


def _attic_opening_candidate_from_summary(child) -> dict[str, object] | None:
    if not bool(child.get("tbg_runtime_marker")):
        return None
    if str(child.get("tbg_runtime_role", "") or "") != export_contract.ROLE_ATTIC_OPENING:
        return None
    bounds = _summary_child_bounds(child)
    if bounds is None:
        return None
    return {
        "kind": "ATTIC_OPENING",
        "source_name": str(child.get("tbg_runtime_source_name", "") or getattr(child, "name", "") or "AtticOpening"),
        "bounds": bounds,
    }


def _roof_access_opening_candidate(spatial_plan, *, wall_thickness: float) -> dict[str, object] | None:
    roof_room = getattr(spatial_plan, "roof_room", None)
    if roof_room is None or not bool(getattr(spatial_plan, "roof_access_enabled", False)):
        return None
    terminal_profile = str(getattr(roof_room, "terminal_profile", "") or "").upper()
    if terminal_profile == "ATTIC_OPEN":
        return None
    shell_x0, shell_x1, shell_y0, shell_y1 = (float(value) for value in roof_room.footprint)
    shell_cx = (shell_x0 + shell_x1) * 0.5
    shell_cy = (shell_y0 + shell_y1) * 0.5
    door_width = float(getattr(roof_room, "door_width", 0.0) or 0.0)
    door_height = float(getattr(roof_room, "door_height", 0.0) or 0.0)
    thickness = max(0.01, float(wall_thickness))
    if door_width <= 1e-5 or door_height <= 1e-5:
        return None
    wall_side = str(getattr(roof_room, "door_wall", "") or "").lower()
    if wall_side == "back":
        bounds = (
            shell_cx - door_width / 2,
            shell_cx + door_width / 2,
            shell_y1 - thickness,
            shell_y1,
            float(roof_room.base_z),
            float(roof_room.base_z + door_height),
        )
    elif wall_side == "front":
        bounds = (
            shell_cx - door_width / 2,
            shell_cx + door_width / 2,
            shell_y0,
            shell_y0 + thickness,
            float(roof_room.base_z),
            float(roof_room.base_z + door_height),
        )
    elif wall_side == "left":
        bounds = (
            shell_x0,
            shell_x0 + thickness,
            shell_cy - door_width / 2,
            shell_cy + door_width / 2,
            float(roof_room.base_z),
            float(roof_room.base_z + door_height),
        )
    elif wall_side == "right":
        bounds = (
            shell_x1 - thickness,
            shell_x1,
            shell_cy - door_width / 2,
            shell_cy + door_width / 2,
            float(roof_room.base_z),
            float(roof_room.base_z + door_height),
        )
    else:
        return None
    return {
        "kind": "ROOF_ACCESS",
        "source_name": "RoofAccess",
        "bounds": bounds,
        "target_roof_exit_shell": True,
    }


def _collect_voxel_wall_opening_candidates(
    summary_children: tuple[object, ...] | list[object],
    *,
    spatial_plan,
    wall_thickness: float,
) -> tuple[dict[str, object], ...]:
    candidates: list[dict[str, object]] = []
    for child in tuple(summary_children):
        for builder in (
            _window_opening_candidate_from_summary,
            _door_opening_candidate_from_summary,
            _attic_opening_candidate_from_summary,
        ):
            candidate = builder(child)
            if candidate is not None:
                candidates.append(candidate)
                break
    roof_access_candidate = _roof_access_opening_candidate(spatial_plan, wall_thickness=wall_thickness)
    if roof_access_candidate is not None:
        candidates.append(roof_access_candidate)
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                str(item.get("kind", "")),
                str(item.get("source_name", "")),
                tuple(float(value) for value in item.get("bounds", ())),
            ),
        )
    )


def _opening_candidate_targets_voxel_wall_entry(
    opening_candidate: dict[str, object],
    source_entry: dict[str, object],
) -> bool:
    if str(opening_candidate.get("kind", "") or "") != "ROOF_ACCESS":
        return True
    return bool(source_entry.get("roof_exit_shell"))


def _iter_voxel_wall_source_entries(section_registry: dict) -> tuple[dict[str, object], ...]:
    sections = tuple(section_registry.get("sections") or ()) if isinstance(section_registry, dict) else ()
    entries: list[dict[str, object]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        bucket = str(section.get("bucket", "") or "")
        if bucket not in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
            continue
        if bool(section.get("roof_exit_shell")):
            continue
        material_name = str(section.get("material_name", "") or "")
        source_fragments = section.get("source_fragments")
        if isinstance(source_fragments, list) and source_fragments:
            for fragment in source_fragments:
                if not isinstance(fragment, dict):
                    continue
                if bool(fragment.get("roof_exit_shell")):
                    continue
                bounds = fragment.get("bounds")
                if not isinstance(bounds, (list, tuple)) or len(bounds) != 6:
                    continue
                entries.append(
                    {
                        "bucket": bucket,
                        "material_name": material_name,
                        "visual_style": _visual_style_for_voxel_wall(material_name),
                        "source_name": str(fragment.get("source_name", "") or section.get("name", "") or bucket),
                        "bounds": tuple(float(value) for value in bounds),
                        "display_color_rgb": resolve_voxel_wall_display_color_rgb(material_name),
                        "roof_exit_shell": bool(fragment.get("roof_exit_shell") or section.get("roof_exit_shell")),
                    }
                )
            continue
        bounds = section.get("bounds")
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 6:
            continue
        entries.append(
            {
                "bucket": bucket,
                "material_name": material_name,
                "visual_style": _visual_style_for_voxel_wall(material_name),
                "source_name": str(section.get("name", "") or bucket),
                "bounds": tuple(float(value) for value in bounds),
                "display_color_rgb": resolve_voxel_wall_display_color_rgb(material_name),
                "roof_exit_shell": bool(section.get("roof_exit_shell")),
            }
        )
    return merge_coplanar_voxel_wall_source_entries(
        tuple(
            sorted(
                entries,
                key=lambda item: (
                    str(item["bucket"]),
                    str(item["material_name"]),
                    str(item["source_name"]),
                    tuple(float(value) for value in item["bounds"]),
                ),
            )
        )
    )


def rebuild_voxel_wall_helper_markers(
    prefix: str,
    root_obj,
    collection,
    material,
    *,
    section_registry: dict,
    summary_children: tuple[object, ...] | list[object],
    spatial_plan,
    wall_thickness: float,
) -> tuple[int, int]:
    if root_obj is None or collection is None:
        return 0, 0
    marker_count = 0
    estimated_part_count = 0
    authored_walls = build_authored_voxel_walls(
        building_id=str(root_obj.get(constants.BUILDING_ID_KEY, "") or prefix),
        section_registry=section_registry,
        summary_children=summary_children,
        spatial_plan=spatial_plan,
        wall_thickness=wall_thickness,
    )
    for authored_wall in authored_walls:
        marker_name = _name(str(prefix), f"{_VOXEL_WALL_MARKER_NAME_PREFIX}_{marker_count + 1:04d}")
        payload, planned_part_count = planned_voxel_wall_marker_payload(
            name=marker_name,
            source_bucket=authored_wall.source_bucket,
            material_family=authored_wall.material_family,
            display_color_rgb=authored_wall.display_color_rgb,
            visual_style=authored_wall.visual_style,
            surface_u_origin_studs=authored_wall.surface_u_origin_studs,
            surface_v_origin_studs=authored_wall.surface_v_origin_studs,
            frame=authored_wall.frame,
            openings=authored_wall.openings,
        )
        if planned_part_count <= 0:
            continue
        rotation = (
            (0.0, 0.0, 0.0)
            if authored_wall.frame.width_axis == "X"
            else (0.0, 0.0, math.pi / 2)
        )
        marker = _create_box(
            marker_name,
            (
                authored_wall.frame.width_studs,
                authored_wall.frame.thickness_studs,
                authored_wall.frame.height_studs,
            ),
            authored_wall.frame.local_center,
            collection,
            root_obj,
            material,
            rotation=rotation,
        )
        marker = _mark_generated(
            marker,
            tbg_voxel_wall_marker=True,
            tbg_voxel_wall_source_bucket=authored_wall.source_bucket,
            tbg_voxel_wall_material_family=authored_wall.material_family,
            tbg_voxel_wall_source_name=authored_wall.source_name,
        )
        estimated_part_count += write_voxel_wall_marker_payload(
            marker,
            payload,
            estimated_part_count=planned_part_count,
        )
        marker_count += 1
        marker.display_type = "WIRE"
        marker.hide_viewport = True
        marker.hide_render = True
        if hasattr(marker, "show_in_front"):
            marker.show_in_front = True
    return int(marker_count), int(estimated_part_count)


def _clone_object_for_exact_spec_reuse(
    *,
    source_obj,
    source_root,
    target_root,
    cloned_name: str,
    target_collections: tuple[bpy.types.Collection, ...],
    source_root_inverse_matrix: Matrix | None = None,
) -> bpy.types.Object | None:
    if getattr(source_obj, "data", None) is None:
        return None
    cloned = source_obj.copy()
    cloned.data = source_obj.data
    cloned.name = str(cloned_name)
    for collection in target_collections:
        collection.objects.link(cloned)
    _parent_to(cloned, target_root)
    if source_obj.parent == source_root:
        cloned.matrix_basis = source_obj.matrix_basis.copy()
    elif source_root_inverse_matrix is not None:
        cloned.matrix_basis = source_root_inverse_matrix @ source_obj.matrix_world
    else:
        cloned.matrix_basis = root_local_matrix(source_obj, root_obj=source_root)
    return cloned


def clone_final_sections_for_exact_spec_reuse(
    *,
    source_root,
    target_root,
    source_prefix: str,
    target_prefix: str,
) -> int:
    # V3 rewrite lock: structural exact-spec replay is fail-closed until the
    # cell-authoritative path is green. Callers must rebuild fresh geometry instead
    # of cloning any cached final-section output back into the live root.
    return 0


def clone_runtime_markers_for_exact_spec_reuse(
    *,
    source_root,
    target_root,
    source_prefix: str,
    target_prefix: str,
    target_collection=None,
) -> int:
    # Stage 2 rewrite lock: runtime/helper marker replay is also disabled so no
    # wall helper truth can leak back through exact-spec convenience paths.
    return 0


def _section_mesh_name(prefix: str, bucket_state: _FinalSectionBucketState) -> str:
    return f"{_section_object_name(prefix, bucket_state)}_Mesh"


def _append_object_mesh_to_bucket_bmesh(target_bm: bmesh.types.BMesh, obj, root_obj) -> None:
    source_bm = bmesh.new()
    scratch_mesh = bpy.data.meshes.new(f"{obj.name}_SinkScratch")
    try:
        source_bm.from_mesh(obj.data)
        source_bm.verts.ensure_lookup_table()
        bmesh.ops.transform(
            source_bm,
            verts=source_bm.verts[:],
            matrix=root_local_matrix(obj, root_obj=root_obj),
        )
        source_bm.to_mesh(scratch_mesh)
        target_bm.from_mesh(scratch_mesh)
    finally:
        source_bm.free()
        bpy.data.meshes.remove(scratch_mesh)


def _resolve_root_mesh_sources(root_obj, source_names: tuple[str, ...]) -> list[bpy.types.Object]:
    root_name = str(getattr(root_obj, "name", ""))
    resolved: list[bpy.types.Object] = []
    for source_name in source_names:
        obj = bpy.data.objects.get(source_name)
        if obj is None or obj.type != "MESH":
            continue
        if obj.name not in bpy.data.objects:
            continue
        parent = obj.parent
        while parent is not None and parent.name != root_name:
            parent = parent.parent
        if parent is None:
            continue
        resolved.append(obj)
    return resolved


def _apply_final_bucket_contract(
    merged,
    bucket_plan: ConsolidationBucketPlan,
    *,
    roof_exit_shell_bounds: tuple[float, ...] | None,
    top_room_floor_bounds: tuple[float, ...] | None,
    entry_canopy_present: bool = False,
    v3_visible_wall: bool = False,
) -> None:
    if bucket_plan.material is not None:
        if v3_visible_wall:
            _assign_material_slot_only(merged, bucket_plan.material)
        elif bool(bucket_plan.material.get("tbg_is_brick")):
            _retile_brick_section(merged, bucket_plan.material)
        elif bool(bucket_plan.material.get("tbg_preserve_join_uv")):
            _assign_material_slot_only(merged, bucket_plan.material)
        else:
            _assign_material(merged, bucket_plan.material)
    _mark_generated(
        merged,
        tbg_section_bucket=bucket_plan.bucket,
        tbg_hide_with_walls=bucket_plan.hide_with_walls,
    )
    if bucket_plan.bucket != _EXTERIOR_BRICK_BUCKET and "tbg_exterior_brick" in merged.keys():
        del merged["tbg_exterior_brick"]
    if bucket_plan.bucket != _EXTERIOR_SURFACE_TILE_BUCKET and "tbg_exterior_surface_tile" in merged.keys():
        del merged["tbg_exterior_surface_tile"]
    if bucket_plan.bucket == _EXTERIOR_SHELL_BUCKET:
        merged["tbg_preserved_exterior_shell"] = True
    if roof_exit_shell_bounds is not None:
        merged["tbg_roof_exit_shell"] = True
        merged["tbg_roof_exit_shell_bounds"] = list(roof_exit_shell_bounds)
    if top_room_floor_bounds is not None:
        merged["tbg_top_room_floor"] = True
        merged["tbg_top_room_floor_bounds"] = list(top_room_floor_bounds)
    if entry_canopy_present:
        merged["tbg_entry_canopy"] = True


def plan_bucket_reduction(
    prefix: str,
    root_obj,
    bucket_plan: ConsolidationBucketPlan,
) -> ConsolidationReductionPlan:
    section_name = _section_name(prefix, bucket_plan)
    roof_exit_shell_sources = [item.obj for item in bucket_plan.items if item.obj.get("tbg_roof_exit_shell")]
    top_room_floor_sources = [item.obj for item in bucket_plan.items if item.obj.get("tbg_top_room_floor")]
    entry_canopy_present = any(item.obj.get("tbg_entry_canopy") for item in bucket_plan.items if item.obj is not None)
    roof_exit_shell_bounds = _freeze_bounds(_combined_source_bounds(root_obj, roof_exit_shell_sources))
    top_room_floor_bounds = _freeze_bounds(_combined_source_bounds(root_obj, top_room_floor_sources))
    source_names = [item.obj.name for item in bucket_plan.items if item.obj is not None]
    if not source_names:
        return ConsolidationReductionPlan(
            bucket_plan=bucket_plan,
            steps=(),
            roof_exit_shell_bounds=roof_exit_shell_bounds,
            top_room_floor_bounds=top_room_floor_bounds,
            entry_canopy_present=entry_canopy_present,
        )

    steps: list[ConsolidationReductionStep] = []
    if len(source_names) == 1:
        steps.append(
            ConsolidationReductionStep(
                source_names=(source_names[0],),
                output_name=section_name,
                is_final=True,
            )
        )
    else:
        reduction_sources = list(source_names)
        depth = 0
        while len(reduction_sources) > 1:
            next_sources: list[str] = []
            chunks = [
                reduction_sources[offset:offset + _MAX_REDUCTION_SOURCES]
                for offset in range(0, len(reduction_sources), _MAX_REDUCTION_SOURCES)
            ]
            for index, chunk in enumerate(chunks):
                if len(chunk) == 1:
                    next_sources.append(chunk[0])
                    continue
                is_final = len(chunks) == 1
                output_name = section_name if is_final else _partial_section_name(
                    prefix,
                    bucket_plan,
                    depth=depth,
                    index=index,
                )
                steps.append(
                    ConsolidationReductionStep(
                        source_names=tuple(chunk),
                        output_name=output_name,
                        is_final=is_final,
                    )
                )
                next_sources.append(output_name)
            reduction_sources = next_sources
            depth += 1

        if not steps or not steps[-1].is_final:
            steps.append(
                ConsolidationReductionStep(
                    source_names=(reduction_sources[0],),
                    output_name=section_name,
                    is_final=True,
                )
            )

    return ConsolidationReductionPlan(
        bucket_plan=bucket_plan,
        steps=tuple(steps),
        roof_exit_shell_bounds=roof_exit_shell_bounds,
        top_room_floor_bounds=top_room_floor_bounds,
        entry_canopy_present=entry_canopy_present,
    )


def _consolidate_generated_meshes(prefix: str, root_obj):
    # Legacy migration/debug path only.
    # Canonical runtime now uses FinalSectionSink via building._finalize_building_full_ops.
    bucket_plans, standalone_section_count = plan_consolidation(root_obj)
    merged_section_count = 0
    for bucket_plan in bucket_plans:
        reduction_plan = plan_bucket_reduction(prefix, root_obj, bucket_plan)
        for reduction_step in reduction_plan.steps:
            if consolidate_bucket(
                prefix,
                root_obj,
                bucket_plan,
                reduction_plan=reduction_plan,
                reduction_step=reduction_step,
            ):
                merged_section_count += 1
    finalize_consolidation(
        root_obj,
        merged_section_count=merged_section_count,
        standalone_section_count=standalone_section_count,
    )


def _set_generated_wall_visibility(root_obj, *, hidden: bool):
    hide_value = bool(hidden)
    for child in root_obj.children_recursive:
        if child.type != "MESH" or not child.get("tbg_hide_with_walls"):
            continue
        child.hide_viewport = hide_value
        child.hide_render = hide_value
    root_obj["tbg_walls_hidden"] = hide_value


def _retile_dirty_brick_sections(root_obj) -> int:
    if root_obj is None:
        return 0
    retiled = 0
    for child, material in iter_dirty_brick_sections(root_obj):
        _retile_brick_section(child, material)
        retiled += 1
    return retiled


def iter_dirty_brick_sections(root_obj) -> tuple[tuple[bpy.types.Object, bpy.types.Material], ...]:
    if root_obj is None:
        return ()
    targets: list[tuple[bpy.types.Object, bpy.types.Material]] = []
    for child in root_obj.children_recursive:
        if child.type != "MESH" or not child.get("tbg_section_bucket"):
            continue
        material = child.material_slots[0].material if child.material_slots else None
        if material is None or not bool(material.get("tbg_is_brick")):
            continue
        if not _brick_section_requires_retile(child, material):
            continue
        targets.append((child, material))
    return tuple(targets)


def retile_dirty_brick_section(child, material) -> None:
    _retile_brick_section(child, material)


def plan_consolidation(root_obj) -> tuple[tuple[ConsolidationBucketPlan, ...], int]:
    # Legacy migration/debug helper retained for tooling compatibility.
    mesh_children = [child for child in root_obj.children_recursive if child.type == "MESH"]
    buckets: dict[tuple[str, str], list[_ConsolidationClassification]] = {}
    standalone_section_count = 0
    for child in mesh_children:
        classified = _classify_consolidation_object(child)
        if classified is None:
            continue
        if not classified.merge_allowed:
            standalone_section_count += 1
            continue
        buckets.setdefault((classified.bucket, classified.material_name), []).append(classified)

    plans: list[ConsolidationBucketPlan] = []
    for (bucket, material_name), classified_objects in buckets.items():
        first = classified_objects[0]
        plans.append(
            ConsolidationBucketPlan(
                bucket=bucket,
                material_name=material_name,
                items=tuple(classified_objects),
                material=first.material,
                hide_with_walls=first.hide_with_walls,
            )
        )
    return tuple(plans), standalone_section_count


def consolidate_bucket(
    prefix: str,
    root_obj,
    bucket_plan: ConsolidationBucketPlan,
    *,
    reduction_plan: ConsolidationReductionPlan | None = None,
    reduction_step: ConsolidationReductionStep | None = None,
) -> bool:
    # Legacy migration/debug helper retained for tooling compatibility.
    if reduction_step is None:
        active_plan = reduction_plan or plan_bucket_reduction(prefix, root_obj, bucket_plan)
        merged_final = False
        for step in active_plan.steps:
            merged_final = consolidate_bucket(
                prefix,
                root_obj,
                bucket_plan,
                reduction_plan=active_plan,
                reduction_step=step,
            ) or merged_final
        return merged_final

    active_plan = reduction_plan or plan_bucket_reduction(prefix, root_obj, bucket_plan)
    sources = _resolve_root_mesh_sources(root_obj, reduction_step.source_names)
    if not sources:
        return False
    merged = _join_mesh_objects(reduction_step.output_name, sources, origin_to_geometry=False)
    if merged is None:
        return False
    if not reduction_step.is_final:
        return False
    _apply_final_bucket_contract(
        merged,
        bucket_plan,
        roof_exit_shell_bounds=active_plan.roof_exit_shell_bounds,
        top_room_floor_bounds=active_plan.top_room_floor_bounds,
        entry_canopy_present=bool(active_plan.entry_canopy_present),
    )
    return True


def finalize_consolidation(root_obj, *, merged_section_count: int, standalone_section_count: int) -> None:
    # Shared section-count closeout is reused by both the new sink and legacy consolidation helpers.
    root_obj["tbg_section_count"] = int(merged_section_count) + int(standalone_section_count)
