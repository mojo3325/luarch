from __future__ import annotations

import json
import math
from dataclasses import dataclass

import bpy
from mathutils import Matrix, Vector

from .. import constants, export_contract, metadata
from ..export_rbxmx import runtime_render_meshes
from ..generation_summary import (
    GenerationSummaryContractError,
    GenerationSummaryFacts,
    parse_generation_summary,
)
from ..generator.building_layout import (
    MASSING_PROFILE_PILOTIS,
    REAR_ACCESS_PROFILE_NONE,
    REAR_ACCESS_PROFILE_SERVICE_DOOR,
    WINDOW_STATE_STAIR,
    _brick_story_count,
    _completed_facade_floor_count,
    _dogleg_metrics,
    _front_entry_approach_band_min,
    _front_entry_approach_gap,
    _front_entry_envelope,
    _front_entry_stair_conflict_span,
    _rear_entry_stair_clearance,
    _rear_entry_stair_conflict_span,
    _spatial_plan,
    _spatial_plan_roof_opening_bounds,
    _spatial_plan_roof_room_bounds,
    _window_verticals,
    estimate_footprint_extents,
)
from ..generator.building_occupancy import MIN_NON_THICKNESS_CELL_SPAN_STUDS
from ..generator.building_facade_opening_slots import slot_opening_profile as _slot_opening_profile
from ..generator.layout_facade_planning import (
    _office_partition_keepout_contract,
    _rear_entry_opening_contract,
)
from ..generator.building_core import _core_arrival_sightline_keepout_bounds
from ..generator.building_output import iter_voxel_preview_cache_objects
from ..generator.materials import WINDOW_FILL_EXPECTED_COLOR, WINDOW_FILL_MATERIAL_NAME, material_uv_settings
from ..generator.building_support import composite_part_root_local_bounds, object_local_bounds
from ..generator.specs import (
    SpecContractError,
    normalized_door_profile,
    normalized_entrance_profile,
    normalized_facade_mode,
    normalized_facade_family,
    normalized_roof_mode,
    stored_building_spec_from_mapping,
)


WOOD_PRESET_IDS = frozenset({"wood_house", "wood_rowhouse"})
WINDOW_OPTIONAL_PRESET_IDS = frozenset({"hangar"})
SERVICE_HEAVY_WALL_PIPE_PRESET_IDS = frozenset({"depot", "warehouse"})
EXPOSED_STAIR_WINDOW_OPTIONAL_PRESET_IDS = frozenset({"market_hall"})
MIN_WALL_PLANE_AREA_COVERAGE_RATIO = 0.95
_OPENING_BOUNDARY_COORD_EPSILON = 1e-4
TRIM_BACK_AIR_GAP_MAX_STUDS = 0.001
TRIM_BACK_OVERLAP_MIN_STUDS = 0.004
FRAME_SILHOUETTE_MIN_STUDS = 0.10
FRAME_RING_WIDTH_MIN_STUDS = 0.06
FRAME_INNER_RETURN_MIN_STUDS = 0.06
CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS = 0.001
OPENING_VISUAL_SEAL_GAP_MAX_STUDS = 0.01
ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN = 0.99
RESIDENTIAL_BORDER_MIN_STUDS = 0.55
_TRIM_ATTACHMENT_BUCKETS = frozenset({"Section_Walls_Trim"})
_OPENING_FRAME_BUCKETS = frozenset({"Section_Openings_Frame", "Section_Doors_Trim"})
_DIAGNOSTIC_OWNER_UNKNOWN = "unknown"
TERRACE_TOP_OWNER_TRANSOM_FRAME = "TERRACE_TRANSOM_FRAME"
TERRACE_TOP_OWNER_WALL_CLOSURE = "TERRACE_WALL_CLOSURE"
VALID_TERRACE_TOP_OWNER_CLASSES = frozenset(
    {TERRACE_TOP_OWNER_TRANSOM_FRAME, TERRACE_TOP_OWNER_WALL_CLOSURE}
)
WINDOW_FILL_BLUE_TOLERANCE = 0.05


@dataclass(frozen=True)
class RuntimeMarkerFacts:
    collision_markers: tuple[bpy.types.Object, ...]
    light_markers: tuple[bpy.types.Object, ...]
    role_counts: dict[str, int]
    role_shapes: dict[str, frozenset[str]]
    slot_roles: dict[tuple[str, int, int], frozenset[str]]
    span_roles: dict[str, dict[str, int]]
    floor_roles: dict[tuple[str, int], int]
    wedge_markers: tuple[bpy.types.Object, ...]
    stair_directions: frozenset[float]


@dataclass(frozen=True)
class VoxelWallOverlapFacts:
    cell_ids: tuple[str, ...]
    cell_pair_count: int


@dataclass(frozen=True)
class VoxelWallDuplicateBoundsFacts:
    bounds_signature: tuple[float, float, float, float, float, float]
    cell_ids: tuple[str, ...]


@dataclass(frozen=True)
class VoxelWallRectCutFacts:
    label: str
    kind: str
    run_min: float | None
    run_max: float | None
    z_min: float | None
    z_max: float | None


@dataclass(frozen=True)
class VoxelWallGroupFacts:
    label: str
    group_id: str
    payload: dict[str, object] | None
    source_bucket: str
    material_family: str
    authoring_mode: str
    normal_axis: str
    run_axis: str
    plane_run_min_studs: float | None
    plane_run_max_studs: float | None
    plane_z_min_studs: float | None
    plane_z_max_studs: float | None
    plane_thickness_min_studs: float | None
    plane_thickness_max_studs: float | None
    visual_style: str | None
    display_color_rgb: tuple[int, int, int] | None
    surface_u_origin_studs: float | None
    surface_v_origin_studs: float | None
    texture_key: str
    texture_projection: str
    texture_image_period_contract: str
    texture_face_axis_table_version: str
    studs_per_tile_u: float | None
    studs_per_tile_v: float | None
    color_modulation_policy: str
    cell_count: int | None
    cell_ids: tuple[str, ...]
    source_fragment_ids: tuple[str, ...]
    rect_cuts: tuple[VoxelWallRectCutFacts, ...]
    top_profile: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class VoxelWallGroupAreaCoverageFacts:
    group_id: str
    expected_solid_area_studs2: float
    actual_cell_area_studs2: float
    coverage_ratio: float


@dataclass(frozen=True)
class VoxelWallCutIntrusionFacts:
    group_id: str
    cut_label: str
    cell_ids: tuple[str, ...]


@dataclass(frozen=True)
class VoxelWallTopProfileProtrusionFacts:
    group_id: str
    cell_ids: tuple[str, ...]


@dataclass(frozen=True)
class VoxelWallSubMinResidualFacts:
    group_id: str
    cut_label: str
    side: str
    residual_studs: float
    threshold_studs: float


@dataclass(frozen=True)
class VoxelOpeningBoundaryEdgeFacts:
    side: str
    required: bool
    nearest_edge_studs: float | None
    nearest_gap_studs: float | None
    has_adjacent_boundary: bool


@dataclass(frozen=True)
class VoxelWallCellFacts:
    label: str
    cell_id: str
    group_id: str
    payload: dict[str, object] | None
    source_bucket: str
    material_family: str
    normal_axis: str
    run_axis: str
    visual_style: str | None
    display_color_rgb: tuple[int, int, int] | None
    surface_u_origin_studs: float | None
    surface_v_origin_studs: float | None
    texture_key: str
    texture_projection: str
    texture_image_period_contract: str
    texture_face_axis_table_version: str
    studs_per_tile_u: float | None
    studs_per_tile_v: float | None
    color_modulation_policy: str
    min_studs: tuple[float, float, float] | None
    size_studs: tuple[float, float, float] | None
    max_studs: tuple[float, float, float] | None


@dataclass(frozen=True)
class VoxelVisibleWallObjectFacts:
    object_name: str
    source_bucket: str
    emit_owner: str
    payload_kind: str
    payload_version: str
    export_contract_version: str
    expected_emit_owner: str
    expected_payload_kind: str
    expected_payload_version: str
    group_id: str
    group_ids: tuple[str, ...]
    scalar_cell_count: int | None
    composite_cell_count: int
    texture_projection: str
    texture_image_period_contract: str
    texture_uv_source: str
    texture_contract_cell_count: int | None
    texture_key_set: tuple[str, ...]
    texture_face_axis_table_version: str
    material_name: str
    material_is_roblox_basepart_sim_preview: bool
    material_roblox_basepart_sim_pattern: str
    has_composite_part_bounds: bool
    is_runtime_render_mesh: bool


@dataclass(frozen=True)
class VoxelOpeningStampIssueFacts:
    object_name: str
    reason: str


@dataclass(frozen=True)
class VoxelOpeningVisualFacts:
    object_name: str
    kind: str
    side: str
    floor: int
    slot: int
    root_local_bounds: tuple[float, float, float, float, float, float]
    cut_run_min: float
    cut_run_max: float
    cut_z_min: float
    cut_z_max: float
    actual_run_min: float
    actual_run_max: float
    actual_z_min: float
    actual_z_max: float
    plane_normal_axis: str
    plane_run_axis: str
    plane_pos: float
    matching_group_id: str | None
    matching_cut_label: str | None
    same_plane_overlap_cell_ids: tuple[str, ...]
    max_gap_studs: float | None
    gap_side: str | None
    actual_max_gap_studs: float | None
    actual_gap_side: str | None
    actual_missing_boundary_sides: tuple[str, ...]
    nearest_final_cell_edges_by_side: tuple[VoxelOpeningBoundaryEdgeFacts, ...]
    sub_min_residuals: tuple[VoxelWallSubMinResidualFacts, ...]
    owner_class: str
    is_seating_source: bool
    cut_intrusion_cell_ids: tuple[str, ...]
    cross_plane_leakage_cell_ids: tuple[str, ...]
    is_window_frame: bool
    is_door_frame: bool
    is_terrace_exit: bool
    is_roof_exit: bool
    cut_envelope_match_delta_studs: float | None
    diagnostic_owner_class: str


@dataclass(frozen=True)
class WindowFillVisualTruthFacts:
    object_name: str
    material_name: str
    diffuse_rgba: tuple[float, float, float, float] | None
    shader_rgb: tuple[float, float, float] | None
    shader_uses_image: bool
    uv_required: bool
    uv_missing: bool
    same_plane_overlap_cell_ids: tuple[str, ...]
    cut_intrusion_cell_ids: tuple[str, ...]


@dataclass(frozen=True)
class VoxelTrimAttachmentFacts:
    object_name: str
    source_bucket: str
    side: str | None
    root_local_bounds: tuple[float, float, float, float, float, float]
    nearest_wall_face_studs: float | None
    trim_back_face_studs: float | None
    air_gap_studs: float
    overlap_studs: float
    owner_class: str


@dataclass(frozen=True)
class VoxelOpeningFrameMassFacts:
    object_name: str
    source_bucket: str
    kind: str | None
    side: str | None
    root_local_bounds: tuple[float, float, float, float, float, float]
    has_opening_stamp: bool
    silhouette_thickness_studs: float | None
    ring_width_studs: float | None
    inner_return_depth_studs: float | None
    open_boundary_edge_count: int
    outer_perimeter_face_count: int
    sill_or_head_mass_missing: bool
    gasket_back_overlap_studs: float | None
    gasket_air_gap_studs: float | None
    cut_envelope_match_delta_studs: float | None
    owner_class: str


@dataclass(frozen=True)
class VoxelRearDoorReservationFacts:
    object_name: str
    reserved_span: tuple[float, float]
    candidate_object_name: str
    candidate_slot: int
    candidate_span: tuple[float, float]
    overlap_studs: float
    owner_class: str


@dataclass(frozen=True)
class VoxelRoofExitTopClosureFacts:
    door_object_name: str
    required_band: tuple[float, float, float, float]
    closure_object_names: tuple[str, ...]
    rejected_object_names: tuple[str, ...]
    coverage_ratio: float
    owner_class: str


@dataclass(frozen=True)
class VoxelTerraceExitTopFacts:
    object_name: str
    side: str
    floor: int
    slot: int
    owner_class: str
    owner_valid: bool
    coverage_ratio: float
    allowed_frame_inflation: bool
    floor_penetration_studs: float
    threshold_obstruction_height_studs: float
    clear_passage_height_studs: float | None
    clear_passage_width_studs: float | None
    authored_opening_width_studs: float | None


@dataclass(frozen=True)
class VoxelWallFacts:
    payload: dict[str, object]
    groups: tuple[VoxelWallGroupFacts, ...]
    cells: tuple[VoxelWallCellFacts, ...]
    visible_wall_objects: tuple[VoxelVisibleWallObjectFacts, ...]
    malformed_entries: tuple[str, ...]
    duplicate_group_ids: tuple[str, ...]
    duplicate_cell_ids: tuple[str, ...]
    duplicate_cell_bounds: tuple[VoxelWallDuplicateBoundsFacts, ...]
    overlapping_cells: tuple[VoxelWallOverlapFacts, ...]
    horizontal_cell_ids: tuple[str, ...]
    micro_span_cell_ids: tuple[str, ...]
    adapter_group_ids: tuple[str, ...]
    plane_area_coverages: tuple[VoxelWallGroupAreaCoverageFacts, ...]
    opening_cut_intrusions: tuple[VoxelWallCutIntrusionFacts, ...]
    top_profile_protrusions: tuple[VoxelWallTopProfileProtrusionFacts, ...]
    sub_min_residuals: tuple[VoxelWallSubMinResidualFacts, ...]
    opening_visuals: tuple[VoxelOpeningVisualFacts, ...]
    trim_attachment_facts: tuple[VoxelTrimAttachmentFacts, ...]
    opening_frame_mass_facts: tuple[VoxelOpeningFrameMassFacts, ...]
    rear_door_reservation_facts: tuple[VoxelRearDoorReservationFacts, ...]
    roof_exit_top_closure_facts: tuple[VoxelRoofExitTopClosureFacts, ...]
    terrace_exit_top_facts: tuple[VoxelTerraceExitTopFacts, ...]
    opening_stamp_issues: tuple[VoxelOpeningStampIssueFacts, ...]
    deferred_unstamped_openings: tuple[VoxelOpeningStampIssueFacts, ...]
    preview_cache_cell_count: int | None
    preview_cache_object_names: tuple[str, ...]
    real_visible_cell_count: int
    visible_scalar_cell_count: int
    runtime_render_wall_object_names: tuple[str, ...]
    opening_visual_count: int
    opening_seating_source_count: int
    cut_edge_boundary_max_delta_studs: float | None
    max_actual_visual_gap_studs: float | None
    actual_missing_boundary_sides_total: int
    sub_min_residual_count: int
    trim_back_air_gap_max_studs: float | None
    trim_back_overlap_min_studs: float | None
    floating_trim_object_count: int
    frame_silhouette_thickness_min_studs: float | None
    frame_ring_width_min_studs: float | None
    frame_inner_return_depth_min_studs: float | None
    frame_open_boundary_edge_count: int
    frame_outer_perimeter_face_count: int
    frame_sill_or_head_mass_missing_count: int
    frame_gasket_back_overlap_min_studs: float | None
    frame_gasket_air_gap_max_studs: float | None
    unstamped_opening_trim_object_count: int
    window_cut_envelope_match_max_delta_studs: float | None
    door_frame_cut_envelope_match_max_delta_studs: float | None
    ordinary_door_panel_height_delta_studs: float | None
    roof_exit_door_panel_height_delta_studs: float | None
    roof_exit_lintel_closure_present_count: int
    roof_exit_lintel_required_count: int
    roof_exit_lintel_closure_distinct_from_frame_count: int
    roof_exit_lintel_closure_section_bucket_invalid_count: int
    roof_exit_lintel_closure_from_door_trim_count: int
    roof_exit_lintel_closure_survives_finalsectionsink_count: int
    roof_exit_top_band_coverage_ratio: float | None
    roof_exit_frame_inner_height_delta_studs: float | None
    roof_exit_frame_outer_height_delta_studs: float | None
    roof_exit_frame_height_delta_studs: float | None
    roof_exit_frame_cut_height_ratio_max: float | None
    roof_exit_frame_counts_as_lintel_count: int
    roof_exit_top_wall_lintel_coverage_ratio: float | None
    rear_door_window_clearance_overlap_count: int
    rear_door_reserved_span_window_candidate_overlap_count: int
    rear_door_reserved_span_window_overlap_max_studs: float
    terrace_exit_unclassified_top_coverage_count: int
    terrace_exit_top_band_coverage_ratio: float | None
    terrace_exit_owner_class_invalid_count: int
    terrace_exit_allowed_frame_inflation: bool
    terrace_exit_frame_floor_penetration_count: int
    terrace_exit_frame_floor_penetration_max_studs: float | None
    terrace_exit_threshold_obstruction_height_max_studs: float | None
    terrace_exit_traversal_blocker_count: int
    terrace_exit_clear_passage_height_min_studs: float | None
    terrace_exit_clear_passage_width_min_studs: float | None
    terrace_exit_top_transom_coverage_ratio: float | None
    ordinary_door_unseated_count: int
    roof_exit_uncovered_cut_top_gap_count: int
    opening_visual_seal_gap_max_studs: float | None
    roof_exit_side_seal_gap_max_studs: float | None
    roof_exit_top_closure_gap_count: int
    roof_exit_cut_covered_area_ratio: float | None
    trim_segment_back_air_gap_max_studs: float | None
    trim_segment_back_overlap_min_studs: float | None
    parapet_cap_segment_back_air_gap_max_studs: float | None
    townhouse_like_parapet_height_min_studs: float | None
    missing_cut_or_stamp_count: int
    sealed_backfilled_opening_count: int
    same_plane_opening_cell_overlap_count: int
    total_authored_cell_count: int
    stale_authored_evidence: tuple[str, ...]
    legacy_helper_evidence: tuple[str, ...]
    texture_contract_key_present_count: int
    texture_projection_valid_count: int
    texture_image_period_contract_valid_count: int
    texture_face_axis_table_valid_count: int
    texture_studs_per_tile_valid_count: int
    cells_with_surface_uv_origin_count: int
    cell_surface_uv_phase_consistency_max_delta_studs: float
    texture_tile_scale_max_delta_studs: float
    visible_texture_contract_cell_count: int
    v3_visible_root_local_uv_object_count: int
    texture_preview_payload_parity: bool
    color_modulation_policy_invalid_count: int
    projection_classification_drift_count: int
    non_axis_aligned_plane_count: int
    composite_box_face_order_probe_match: bool
    texture_face_uv_implementation_invalid_count: int
    v3_material_style_preview_mismatch_count: int
    opening_bounds_off_grid_count: int
    brick_opening_adjacent_non_grid_cell_count: int
    window_fill_visual_truths: tuple[WindowFillVisualTruthFacts, ...]
    window_fill_wrong_material_count: int
    window_fill_non_blue_count: int
    window_fill_shader_non_blue_count: int
    window_fill_missing_uv_count: int
    window_fill_shader_rgb_min: tuple[float, float, float] | None
    window_fill_shader_rgb_max: tuple[float, float, float] | None
    window_fill_same_plane_v3_overlap_count: int


@dataclass(frozen=True)
class LoadedValidationState:
    root_obj: bpy.types.Object
    effective_spec: object
    summary: GenerationSummaryFacts
    final_section_registry: dict
    voxel_wall_payload: dict
    children: tuple[bpy.types.Object, ...]
    mesh_children: tuple[bpy.types.Object, ...]
    render_mesh_children: tuple[bpy.types.Object, ...]
    marker_facts: RuntimeMarkerFacts


@dataclass(frozen=True)
class ValidationFacts:
    root_obj: bpy.types.Object
    effective_spec: object
    summary: GenerationSummaryFacts
    mesh_children: tuple[bpy.types.Object, ...]
    render_mesh_children: tuple[bpy.types.Object, ...]
    marker_facts: RuntimeMarkerFacts
    voxel_wall_facts: VoxelWallFacts
    door_leaves: tuple[bpy.types.Object, ...]
    brick_mesh_children: tuple[bpy.types.Object, ...]
    drifting_children: tuple[str, ...]
    multi_material_children: tuple[str, ...]
    hidden_wall_sections: tuple[str, ...]
    render_section_buckets: frozenset[str]
    registry_fragment_profiles: frozenset[str]
    registry_fragment_run_axes: frozenset[str]
    brick_projection_modes: tuple[str, ...]
    brick_uv_scales: tuple[float, ...]
    balcony_material_names: tuple[str, ...]
    atlas_images: tuple[str, ...]
    wide_partition_eligible: bool
    room_partition_corridor_width: float
    preset_id: str
    floor_count: int
    massing_profile: str
    facade_mode: str
    door_profile: str
    roof_mode: str
    front_entry_stair_conflict_span: tuple[float, float] | None
    front_entry_approach_band_min: float
    front_entry_approach_gap: float | None
    front_door_bounds: tuple[float, float, float, float, float, float] | None
    stair_arrival_side: str
    rear_through_access: bool
    rear_access_profile: str
    rear_entry_stair_clearance_min: float
    rear_entry_stair_conflict_span: tuple[float, float] | None
    rear_entry_planned_center_x: float | None
    rear_entry_planned_opening_width: float | None
    rear_entry_planned_span: tuple[float, float] | None
    rear_entry_authored_span: tuple[float, float] | None
    rear_door_bounds: tuple[float, float, float, float, float, float] | None
    rear_shell_marker_bounds: tuple[tuple[float, float, float, float, float, float], ...]
    stair_core_sight_keepout_bounds: tuple[float, float, float, float, float, float] | None
    core_shell_partition_mesh_bounds: tuple[tuple[float, float, float, float, float, float], ...]
    core_shell_partition_marker_bounds: tuple[tuple[float, float, float, float, float, float], ...]
    partition_marker_bounds: tuple[tuple[float, float, float, float, float, float], ...]
    office_partition_positions_x: tuple[float, ...]
    office_window_approach_keepout_spans: tuple[tuple[float, float], ...]
    office_balcony_access_keepout_spans: tuple[tuple[float, float], ...]
    office_rear_corridor_keepout_span: tuple[float, float] | None
    authored_window_slot_count_by_side_floor: dict[tuple[str, int], int]
    shell_slot_count_by_side_floor: dict[tuple[str, int], int]
    top_terminal_mode: str
    terminal_profile: str
    roof_access_enabled: bool
    contract_roof_exit_bounds: tuple[float, float, float, float, float, float] | None
    contract_roof_opening_bounds: tuple[float, float, float, float, float, float] | None
    authored_roof_exit_bounds: tuple[float, float, float, float, float, float] | None
    top_room_floor_bounds: tuple[float, float, float, float, float, float] | None
    roof_blocker_bounds: tuple[tuple[float, float, float, float, float, float], ...]
    roof_exit_platform_marker_bounds: tuple[tuple[float, float, float, float, float, float], ...]
    service_anchor_id: str
    completed_facade_floors: int
    effective_facade_family: str
    brick_floor_count: int
    panel_floor_count: int
    entrance_profile: str
    standard_sill_height: float
    standard_opening_height: float
    expected_open_window_verticals_by_slot: dict[tuple[str, int, int], tuple[float, float]]
    has_stairs: bool
    has_mid_landing: bool
    has_stair_window: bool
    width: float
    depth: float
    wall_thickness: float
    entrance_left_limit: float | None
    entrance_right_limit: float | None
    entrance_front_limit: float | None
    left_extent: float
    right_extent: float
    front_extent: float
    tri_count: int
    non_voxel_render_tri_count: int
    v3_wall_source_tri_count_in_render_meshes: int
    total_scene_render_tri_count: int
    tri_count_by_bucket: dict[str, int]
    tri_count_by_category: dict[str, int]
    tri_count_top_offenders: tuple[dict[str, object], ...]
    exported_render_object_count: int
    object_count_by_bucket: dict[str, int]
    unique_material_count: int
    material_slot_count_total: int
    frame_tri_count_total: int
    trim_tri_count_total: int
    stair_tri_count_total: int


def _version_label(value) -> str:
    return str(value) if value not in {None, ""} else "<missing>"


def _finite_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _expected_texture_projection(material_family: str, visual_style: str | None) -> str:
    family = str(material_family or "").strip().upper()
    if family in export_contract.TEXTURED_VOXEL_WALL_MATERIAL_FAMILIES and str(visual_style or "").strip():
        return export_contract.TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1
    return export_contract.TEXTURE_PROJECTION_SOLID_COLOR_V1


def _expected_texture_period(material_family: str, visual_style: str | None) -> float:
    family = str(material_family or "").strip().upper()
    if family == "BRICK":
        return float(export_contract.BRICK_TEXTURE_STUDS_PER_TILE)
    return float(export_contract.DEFAULT_TEXTURE_STUDS_PER_TILE)


def _texture_key_set_from_object(child: bpy.types.Object) -> tuple[str, ...]:
    raw = child.get("tbg_texture_key_set_json")
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        decoded = ()
    if not isinstance(decoded, (list, tuple)):
        return ()
    return tuple(sorted(str(item or "").strip() for item in decoded if str(item or "").strip()))


def _object_material_slot0(child: bpy.types.Object) -> bpy.types.Material | None:
    if child is None or not getattr(child, "material_slots", None) or not child.material_slots:
        return None
    return child.material_slots[0].material


def _material_diffuse_rgba(material: bpy.types.Material | None) -> tuple[float, float, float, float] | None:
    if material is None or getattr(material, "diffuse_color", None) is None:
        return None
    return tuple(float(channel) for channel in material.diffuse_color[:4])


def _is_window_fill_blue(diffuse_rgba: tuple[float, float, float, float] | None) -> bool:
    if diffuse_rgba is None:
        return False
    return all(
        abs(float(diffuse_rgba[index]) - float(WINDOW_FILL_EXPECTED_COLOR[index])) <= WINDOW_FILL_BLUE_TOLERANCE
        for index in range(3)
    )


def _principled_base_color_node(material: bpy.types.Material | None):
    node_tree = getattr(material, "node_tree", None) if material is not None else None
    if node_tree is None:
        return None, None
    for node in node_tree.nodes:
        if getattr(node, "type", "") != "BSDF_PRINCIPLED":
            continue
        base_input = node.inputs.get("Base Color")
        return node, base_input
    return None, None


def _linked_image_node(base_input):
    if base_input is None or not getattr(base_input, "is_linked", False):
        return None
    for link in getattr(base_input, "links", ()):
        source = getattr(link, "from_node", None)
        if getattr(source, "type", "") == "TEX_IMAGE":
            return source
    return None


def _image_rgb_at_uv(image, u: float, v: float) -> tuple[float, float, float] | None:
    if image is None or not getattr(image, "size", None):
        return None
    width, height = int(image.size[0]), int(image.size[1])
    if width <= 0 or height <= 0:
        return None
    try:
        pixels = image.pixels
        u_wrapped = float(u) % 1.0
        v_wrapped = float(v) % 1.0
        x = min(width - 1, max(0, int(round(u_wrapped * (width - 1)))))
        y = min(height - 1, max(0, int(round(v_wrapped * (height - 1)))))
        offset = (y * width + x) * 4
        return (float(pixels[offset]), float(pixels[offset + 1]), float(pixels[offset + 2]))
    except (TypeError, ValueError, IndexError, RuntimeError):
        return None


def _mesh_uv_sample_points(obj: bpy.types.Object) -> tuple[tuple[float, float], ...]:
    mesh = getattr(obj, "data", None)
    if mesh is None or not hasattr(mesh, "uv_layers"):
        return ()
    uv_layer = mesh.uv_layers.get("TBG_UV") or mesh.uv_layers.active
    if uv_layer is None:
        return ()
    samples: list[tuple[float, float]] = []
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            try:
                uv = uv_layer.data[loop_index].uv
            except (IndexError, AttributeError):
                continue
            samples.append((float(uv.x), float(uv.y)))
            if len(samples) >= 12:
                return tuple(samples)
    return tuple(samples)


def _window_fill_shader_rgb(obj: bpy.types.Object, material: bpy.types.Material | None) -> tuple[float, float, float] | None:
    _node, base_input = _principled_base_color_node(material)
    image_node = _linked_image_node(base_input)
    if image_node is None:
        if base_input is None:
            return None
        try:
            value = base_input.default_value
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, IndexError, AttributeError):
            return None
    samples = _mesh_uv_sample_points(obj)
    if not samples:
        return None
    colors = [
        color
        for u, v in samples
        for color in (_image_rgb_at_uv(getattr(image_node, "image", None), u, v),)
        if color is not None
    ]
    if not colors:
        return None
    return tuple(sum(color[index] for color in colors) / len(colors) for index in range(3))


def _shader_uses_image(material: bpy.types.Material | None) -> bool:
    _node, base_input = _principled_base_color_node(material)
    return _linked_image_node(base_input) is not None


def _nonnegative_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _payload_vector3(payload: dict[str, object] | None, key: str) -> tuple[float, float, float] | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get(key)
    if not isinstance(raw, dict):
        return None
    x = _finite_float(raw.get("x"))
    y = _finite_float(raw.get("y"))
    z = _finite_float(raw.get("z"))
    if x is None or y is None or z is None:
        return None
    return (x, y, z)


def _payload_color3(payload: dict[str, object] | None, key: str) -> tuple[int, int, int] | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get(key)
    if not isinstance(raw, dict):
        return None
    channels: list[int] = []
    for channel in ("r", "g", "b"):
        value = raw.get(channel)
        if not isinstance(value, int):
            return None
        channels.append(max(0, min(255, int(value))))
    return tuple(channels)


def _payload_required_vector3(payload: dict[str, object] | None, key: str) -> tuple[float, float, float] | None:
    vector = _payload_vector3(payload, key)
    if vector is None:
        return None
    return (
        round(float(vector[0]), 6),
        round(float(vector[1]), 6),
        round(float(vector[2]), 6),
    )


def _cell_max_studs(
    min_studs: tuple[float, float, float] | None,
    size_studs: tuple[float, float, float] | None,
) -> tuple[float, float, float] | None:
    if min_studs is None or size_studs is None:
        return None
    return (
        round(float(min_studs[0]) + float(size_studs[0]), 6),
        round(float(min_studs[1]) + float(size_studs[1]), 6),
        round(float(min_studs[2]) + float(size_studs[2]), 6),
    )


def _cells_overlap_positive_volume(
    left: VoxelWallCellFacts,
    right: VoxelWallCellFacts,
    *,
    epsilon: float = 1e-6,
) -> bool:
    if left.min_studs is None or left.max_studs is None or right.min_studs is None or right.max_studs is None:
        return False
    return (
        min(float(left.max_studs[0]), float(right.max_studs[0])) - max(float(left.min_studs[0]), float(right.min_studs[0])) > epsilon
        and min(float(left.max_studs[1]), float(right.max_studs[1])) - max(float(left.min_studs[1]), float(right.min_studs[1])) > epsilon
        and min(float(left.max_studs[2]), float(right.max_studs[2])) - max(float(left.min_studs[2]), float(right.min_studs[2])) > epsilon
    )


def _bounds_overlap_positive_volume(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
    *,
    epsilon: float = 1e-6,
) -> bool:
    return (
        min(float(left[1]), float(right[1])) - max(float(left[0]), float(right[0])) > epsilon
        and min(float(left[3]), float(right[3])) - max(float(left[2]), float(right[2])) > epsilon
        and min(float(left[5]), float(right[5])) - max(float(left[4]), float(right[4])) > epsilon
    )


def _cell_bounds_tuple(cell: VoxelWallCellFacts) -> tuple[float, float, float, float, float, float] | None:
    if cell.min_studs is None or cell.max_studs is None:
        return None
    return (
        float(cell.min_studs[0]),
        float(cell.max_studs[0]),
        float(cell.min_studs[1]),
        float(cell.max_studs[1]),
        float(cell.min_studs[2]),
        float(cell.max_studs[2]),
    )


def _payload_float(payload: dict[str, object] | None, key: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    return _finite_float(payload.get(key))


def _payload_float_from_keys(payload: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        value = _payload_float(payload, key)
        if value is not None:
            return value
    return None


def _payload_rect_cuts(group_payload: dict[str, object], group_label: str, malformed_entries: list[str]) -> tuple[VoxelWallRectCutFacts, ...]:
    raw_cuts = group_payload.get("rect_cuts", ())
    if raw_cuts in (None, ""):
        return ()
    if not isinstance(raw_cuts, (list, tuple)):
        malformed_entries.append(f"{group_label}.rect_cuts")
        return ()
    cuts: list[VoxelWallRectCutFacts] = []
    for cut_index, cut_payload in enumerate(raw_cuts, start=1):
        cut_label = f"{group_label}.rect_cuts[{cut_index}]"
        if isinstance(cut_payload, dict):
            kind = str(cut_payload.get("kind", "") or "")
            run_min = _payload_float_from_keys(cut_payload, "run_min", "run_min_studs")
            run_max = _payload_float_from_keys(cut_payload, "run_max", "run_max_studs")
            z_min = _payload_float_from_keys(cut_payload, "z_min", "z_min_studs")
            z_max = _payload_float_from_keys(cut_payload, "z_max", "z_max_studs")
        elif isinstance(cut_payload, (list, tuple)) and len(cut_payload) >= 5:
            kind = str(cut_payload[0] or "")
            run_min = _finite_float(cut_payload[1])
            run_max = _finite_float(cut_payload[2])
            z_min = _finite_float(cut_payload[3])
            z_max = _finite_float(cut_payload[4])
        else:
            malformed_entries.append(cut_label)
            continue
        if run_min is None or run_max is None or z_min is None or z_max is None:
            malformed_entries.append(cut_label)
            continue
        cuts.append(
            VoxelWallRectCutFacts(
                label=cut_label,
                kind=kind,
                run_min=run_min,
                run_max=run_max,
                z_min=z_min,
                z_max=z_max,
            )
        )
    return tuple(cuts)


def _payload_top_profile(
    group_payload: dict[str, object],
    group_label: str,
    malformed_entries: list[str],
) -> tuple[tuple[float, float], ...]:
    raw_profile = group_payload.get("top_profile", ())
    if raw_profile in (None, ""):
        return ()
    if not isinstance(raw_profile, (list, tuple)):
        malformed_entries.append(f"{group_label}.top_profile")
        return ()
    points: list[tuple[float, float]] = []
    for point_index, point_payload in enumerate(raw_profile, start=1):
        point_label = f"{group_label}.top_profile[{point_index}]"
        if isinstance(point_payload, dict):
            run = _payload_float_from_keys(point_payload, "run", "run_studs")
            z = _payload_float_from_keys(point_payload, "z", "z_studs")
        elif isinstance(point_payload, (list, tuple)) and len(point_payload) >= 2:
            run = _finite_float(point_payload[0])
            z = _finite_float(point_payload[1])
        else:
            malformed_entries.append(point_label)
            continue
        if run is None or z is None:
            malformed_entries.append(point_label)
            continue
        points.append((round(float(run), 6), round(float(z), 6)))
    points.sort(key=lambda item: item[0])
    return tuple(points)


def _cell_run_bounds(cell: VoxelWallCellFacts) -> tuple[float, float] | None:
    if cell.min_studs is None or cell.max_studs is None:
        return None
    if cell.run_axis == "x":
        return (float(cell.min_studs[0]), float(cell.max_studs[0]))
    if cell.run_axis == "y":
        return (float(cell.min_studs[1]), float(cell.max_studs[1]))
    return None


def _cell_z_bounds(cell: VoxelWallCellFacts) -> tuple[float, float] | None:
    if cell.min_studs is None or cell.max_studs is None:
        return None
    return (float(cell.min_studs[2]), float(cell.max_studs[2]))


def _interval_overlap_positive(
    left_min: float,
    left_max: float,
    right_min: float,
    right_max: float,
    *,
    epsilon: float = 1e-6,
) -> bool:
    return min(float(left_max), float(right_max)) - max(float(left_min), float(right_min)) > epsilon


def _top_profile_z_at(profile: tuple[tuple[float, float], ...], run_value: float) -> float | None:
    if not profile:
        return None
    run_value = round(float(run_value), 4)
    if run_value < profile[0][0] - 1e-6 or run_value > profile[-1][0] + 1e-6:
        return None
    for left, right in zip(profile, profile[1:]):
        if run_value > right[0] + 1e-6:
            continue
        width = right[0] - left[0]
        if width <= 1e-6:
            return min(left[1], right[1])
        t = min(1.0, max(0.0, (run_value - left[0]) / width))
        return round(left[1] + (right[1] - left[1]) * t, 4)
    return profile[-1][1]


def _cell_above_top_profile(
    profile: tuple[tuple[float, float], ...],
    *,
    run_min: float,
    run_max: float,
    z_max: float,
    tolerance: float = 0.02,
) -> bool:
    if not profile:
        return False
    samples = (run_min, round((run_min + run_max) / 2.0, 4), run_max)
    tops: list[float] = []
    for sample in samples:
        top = _top_profile_z_at(profile, sample)
        if top is None:
            return True
        tops.append(top)
    return float(z_max) - min(tops) > tolerance


def _cell_overlaps_cut(cell: VoxelWallCellFacts, cut: VoxelWallRectCutFacts) -> bool:
    if cut.run_min is None or cut.run_max is None or cut.z_min is None or cut.z_max is None:
        return False
    run_bounds = _cell_run_bounds(cell)
    z_bounds = _cell_z_bounds(cell)
    if run_bounds is None or z_bounds is None:
        return False
    return _interval_overlap_positive(run_bounds[0], run_bounds[1], cut.run_min, cut.run_max) and _interval_overlap_positive(
        z_bounds[0],
        z_bounds[1],
        cut.z_min,
        cut.z_max,
    )


def _value_on_grid(value: float, origin: float, cell_size: float, *, tolerance: float = 0.001) -> bool:
    if cell_size <= 1e-6:
        return False
    units = (float(value) - float(origin)) / float(cell_size)
    return abs(units - round(units)) <= tolerance


def _span_is_grid_multiple(span: float, cell_size: float, *, tolerance: float = 0.001) -> bool:
    if cell_size <= 1e-6:
        return False
    units = float(span) / float(cell_size)
    return abs(units - round(units)) <= tolerance


def _cut_bounds_off_grid(group: VoxelWallGroupFacts, cut: VoxelWallRectCutFacts, *, cell_size: float) -> bool:
    if (
        group.plane_run_min_studs is None
        or group.plane_z_min_studs is None
        or cut.run_min is None
        or cut.run_max is None
        or cut.z_min is None
        or cut.z_max is None
    ):
        return False
    run_origin = float(group.plane_run_min_studs)
    z_origin = float(group.plane_z_min_studs)
    return not all(
        (
            _value_on_grid(float(cut.run_min), run_origin, cell_size),
            _value_on_grid(float(cut.run_max), run_origin, cell_size),
            _value_on_grid(float(cut.z_min), z_origin, cell_size),
            _value_on_grid(float(cut.z_max), z_origin, cell_size),
        )
    )


def _cut_is_interior_window_like(group: VoxelWallGroupFacts, cut: VoxelWallRectCutFacts, *, tolerance: float = 0.001) -> bool:
    if (
        group.plane_z_min_studs is None
        or group.plane_z_max_studs is None
        or cut.z_min is None
        or cut.z_max is None
    ):
        return False
    return (
        float(cut.z_min) > float(group.plane_z_min_studs) + tolerance
        and float(cut.z_max) < float(group.plane_z_max_studs) - tolerance
    )


def _cell_touches_cut_boundary(cell: VoxelWallCellFacts, cut: VoxelWallRectCutFacts, *, tolerance: float = 0.001) -> bool:
    if cut.run_min is None or cut.run_max is None or cut.z_min is None or cut.z_max is None:
        return False
    run_bounds = _cell_run_bounds(cell)
    z_bounds = _cell_z_bounds(cell)
    if run_bounds is None or z_bounds is None:
        return False
    run_min, run_max = (float(value) for value in run_bounds)
    z_min, z_max = (float(value) for value in z_bounds)
    cut_run_min, cut_run_max, cut_z_min, cut_z_max = (
        float(cut.run_min),
        float(cut.run_max),
        float(cut.z_min),
        float(cut.z_max),
    )
    touches_vertical_edge = (
        abs(run_max - cut_run_min) <= tolerance
        or abs(run_min - cut_run_max) <= tolerance
    ) and _interval_overlap_positive(z_min, z_max, cut_z_min, cut_z_max)
    touches_horizontal_edge = (
        abs(z_max - cut_z_min) <= tolerance
        or abs(z_min - cut_z_max) <= tolerance
    ) and _interval_overlap_positive(run_min, run_max, cut_run_min, cut_run_max)
    return bool(touches_vertical_edge or touches_horizontal_edge)


def _cell_has_non_grid_surface_span(
    cell: VoxelWallCellFacts,
    group: VoxelWallGroupFacts,
    *,
    cell_size: float,
) -> bool:
    run_bounds = _cell_run_bounds(cell)
    z_bounds = _cell_z_bounds(cell)
    if run_bounds is None or z_bounds is None:
        return False
    run_span = float(run_bounds[1]) - float(run_bounds[0])
    z_span = float(z_bounds[1]) - float(z_bounds[0])
    run_non_grid = not _span_is_grid_multiple(run_span, cell_size)
    z_non_grid = not _span_is_grid_multiple(z_span, cell_size)
    if run_non_grid and group.plane_run_min_studs is not None and group.plane_run_max_studs is not None:
        touches_perimeter_run = (
            abs(float(run_bounds[0]) - float(group.plane_run_min_studs)) <= 0.001
            or abs(float(run_bounds[1]) - float(group.plane_run_max_studs)) <= 0.001
        )
        run_non_grid = not touches_perimeter_run
    if z_non_grid and group.plane_z_min_studs is not None and group.plane_z_max_studs is not None:
        touches_perimeter_z = (
            abs(float(z_bounds[0]) - float(group.plane_z_min_studs)) <= 0.001
            or abs(float(z_bounds[1]) - float(group.plane_z_max_studs)) <= 0.001
        )
        z_non_grid = not touches_perimeter_z
    return bool(run_non_grid or z_non_grid)


def _group_critical_run_knots(group: VoxelWallGroupFacts) -> tuple[float, ...]:
    if group.plane_run_min_studs is None or group.plane_run_max_studs is None:
        return ()
    run_min = round(float(group.plane_run_min_studs), 4)
    run_max = round(float(group.plane_run_max_studs), 4)
    if run_max - run_min <= 1e-6:
        return ()
    knots: set[float] = {run_min, run_max}
    for cut in group.rect_cuts:
        if cut.run_min is None or cut.run_max is None:
            continue
        if not _interval_overlap_positive(run_min, run_max, cut.run_min, cut.run_max):
            continue
        knots.add(round(max(run_min, cut.run_min), 4))
        knots.add(round(min(run_max, cut.run_max), 4))
    for run, _z in group.top_profile:
        if run_min + 1e-6 < run < run_max - 1e-6:
            knots.add(round(float(run), 4))
    return tuple(sorted(knots))


def _pack_area_lattice_intervals(min_value: float, max_value: float, *, cell_size: float) -> tuple[tuple[float, float], ...]:
    min_value = round(float(min_value), 4)
    max_value = round(float(max_value), 4)
    if max_value - min_value < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        return ()
    intervals: list[tuple[float, float]] = []
    left = min_value
    while max_value - left > 1e-6:
        right = min(max_value, round(left + float(cell_size), 4))
        if max_value - right <= 1e-6:
            right = max_value
        if right - left > 1e-6:
            intervals.append((round(left, 4), round(right, 4)))
        left = right
    if len(intervals) >= 2 and round(intervals[-1][1] - intervals[-1][0], 4) < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        previous_min, _previous_max = intervals[-2]
        _last_min, last_max = intervals[-1]
        intervals[-2] = (previous_min, last_max)
        intervals.pop()
    return tuple(
        (left, right)
        for left, right in intervals
        if round(right - left, 4) >= MIN_NON_THICKNESS_CELL_SPAN_STUDS
    )


def _is_group_cut_edge_residue_run_span(group: VoxelWallGroupFacts, run_min: float, run_max: float) -> bool:
    if group.plane_run_min_studs is None or group.plane_run_max_studs is None:
        return False
    run_min = round(float(run_min), 4)
    run_max = round(float(run_max), 4)
    if round(run_max - run_min, 4) >= MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        return False
    plane_run_min = round(float(group.plane_run_min_studs), 4)
    plane_run_max = round(float(group.plane_run_max_studs), 4)
    touches_left_edge = abs(run_min - plane_run_min) <= 1e-6
    touches_right_edge = abs(run_max - plane_run_max) <= 1e-6
    if touches_left_edge == touches_right_edge:
        return False
    if group.plane_z_min_studs is None or group.plane_z_max_studs is None:
        return False
    for cut in group.rect_cuts:
        if cut.run_min is None or cut.run_max is None or cut.z_min is None or cut.z_max is None:
            continue
        if not _interval_overlap_positive(group.plane_z_min_studs, group.plane_z_max_studs, cut.z_min, cut.z_max):
            continue
        if touches_left_edge and abs(run_max - float(cut.run_min)) <= 1e-6:
            return True
        if touches_right_edge and abs(run_min - float(cut.run_max)) <= 1e-6:
            return True
    return False


def _group_top_profile_cap(group: VoxelWallGroupFacts, run_min: float, run_max: float) -> float | None:
    if group.plane_z_max_studs is None:
        return None
    if not group.top_profile:
        return float(group.plane_z_max_studs)
    samples = (run_min, round((run_min + run_max) / 2.0, 4), run_max)
    caps: list[float] = []
    for sample in samples:
        cap = _top_profile_z_at(group.top_profile, sample)
        if cap is None:
            return None
        caps.append(min(float(group.plane_z_max_studs), cap))
    return round(min(caps), 4)


def _subtract_area_z_interval(
    intervals: tuple[tuple[float, float], ...],
    cut_min: float,
    cut_max: float,
) -> tuple[tuple[float, float], ...]:
    remaining: list[tuple[float, float]] = []
    for interval_min, interval_max in intervals:
        if not _interval_overlap_positive(interval_min, interval_max, cut_min, cut_max):
            remaining.append((interval_min, interval_max))
            continue
        if cut_min - interval_min > 1e-6:
            remaining.append((interval_min, min(interval_max, cut_min)))
        if interval_max - cut_max > 1e-6:
            remaining.append((max(interval_min, cut_max), interval_max))
    return tuple(
        (round(left, 6), round(right, 6))
        for left, right in remaining
        if right - left >= MIN_NON_THICKNESS_CELL_SPAN_STUDS
    )


def _group_solid_z_intervals_for_run_span(
    group: VoxelWallGroupFacts,
    run_min: float,
    run_max: float,
) -> tuple[tuple[float, float], ...]:
    if group.plane_z_min_studs is None:
        return ()
    z_min = float(group.plane_z_min_studs)
    top_z = _group_top_profile_cap(group, run_min, run_max)
    if top_z is None or top_z - z_min < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        return ()
    solid_intervals: tuple[tuple[float, float], ...] = ((z_min, top_z),)
    for cut in group.rect_cuts:
        if cut.run_min is None or cut.run_max is None or cut.z_min is None or cut.z_max is None:
            continue
        if not _interval_overlap_positive(run_min, run_max, cut.run_min, cut.run_max):
            continue
        solid_intervals = _subtract_area_z_interval(solid_intervals, cut.z_min, cut.z_max)
        if not solid_intervals:
            break
    return solid_intervals


def _expected_group_solid_area(group: VoxelWallGroupFacts, *, cell_size: float) -> float | None:
    if group.plane_z_min_studs is None or group.plane_z_max_studs is None:
        return None
    run_knots = _group_critical_run_knots(group)
    if len(run_knots) < 2:
        return None
    expected_area = 0.0
    for critical_run_min, critical_run_max in zip(run_knots, run_knots[1:]):
        if critical_run_max - critical_run_min <= 1e-6:
            continue
        solid_intervals = _group_solid_z_intervals_for_run_span(group, critical_run_min, critical_run_max)
        if not solid_intervals:
            continue
        if round(critical_run_max - critical_run_min, 4) < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
            if _is_group_cut_edge_residue_run_span(group, critical_run_min, critical_run_max):
                continue
            run_intervals = ((critical_run_min, critical_run_max),)
        else:
            run_intervals = _pack_area_lattice_intervals(critical_run_min, critical_run_max, cell_size=cell_size)
        for run_min, run_max in run_intervals:
            for solid_min, solid_max in _group_solid_z_intervals_for_run_span(group, run_min, run_max):
                expected_area += (run_max - run_min) * (solid_max - solid_min)
    return round(expected_area, 6)


def _actual_group_cell_area(cells: tuple[VoxelWallCellFacts, ...]) -> float:
    actual_area = 0.0
    for cell in cells:
        run_bounds = _cell_run_bounds(cell)
        z_bounds = _cell_z_bounds(cell)
        if run_bounds is None or z_bounds is None:
            continue
        run_span = max(0.0, float(run_bounds[1]) - float(run_bounds[0]))
        z_span = max(0.0, float(z_bounds[1]) - float(z_bounds[0]))
        actual_area += run_span * z_span
    return round(actual_area, 6)


def _group_sub_min_residuals(group: VoxelWallGroupFacts) -> tuple[VoxelWallSubMinResidualFacts, ...]:
    if (
        group.plane_run_min_studs is None
        or group.plane_run_max_studs is None
        or group.plane_z_min_studs is None
        or group.plane_z_max_studs is None
    ):
        return ()
    threshold = float(MIN_NON_THICKNESS_CELL_SPAN_STUDS)
    group_id = group.group_id or group.label
    residuals: list[VoxelWallSubMinResidualFacts] = []

    def _append_if_sub_min(cut: VoxelWallRectCutFacts, side: str, residual: float) -> None:
        residual = round(float(residual), 6)
        if 0.0 < residual < threshold:
            residuals.append(
                VoxelWallSubMinResidualFacts(
                    group_id=group_id,
                    cut_label=cut.label,
                    side=side,
                    residual_studs=residual,
                    threshold_studs=threshold,
                )
            )

    for cut in group.rect_cuts:
        if cut.run_min is None or cut.run_max is None or cut.z_min is None or cut.z_max is None:
            continue
        _append_if_sub_min(cut, "left", float(cut.run_min) - float(group.plane_run_min_studs))
        _append_if_sub_min(cut, "right", float(group.plane_run_max_studs) - float(cut.run_max))
        _append_if_sub_min(cut, "bottom", float(cut.z_min) - float(group.plane_z_min_studs))
        _append_if_sub_min(cut, "top", float(group.plane_z_max_studs) - float(cut.z_max))
    return tuple(residuals)


def _visible_wall_group_ids(child: bpy.types.Object) -> tuple[str, ...]:
    group_ids: set[str] = set()
    raw_group_id = str(child.get("tbg_wall_group_id", "") or "").strip()
    if raw_group_id:
        group_ids.add(raw_group_id)
    raw_group_ids_json = child.get("tbg_wall_group_ids_json")
    if raw_group_ids_json:
        try:
            decoded = json.loads(str(raw_group_ids_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = ()
        if isinstance(decoded, list):
            group_ids.update(str(group_id or "").strip() for group_id in decoded if str(group_id or "").strip())
    return tuple(sorted(group_ids))


def _is_window_visual_opening_object(child: bpy.types.Object) -> bool:
    return any(
        bool(child.get(key))
        for key in (
            "tbg_window_frame_outer",
            "tbg_window_fill",
            "tbg_window_mullion",
            "tbg_window_marker",
            "tbg_hangar_window",
        )
    )


def _is_stage2a_deferred_window(child: bpy.types.Object) -> bool:
    _ = child
    return False


def _is_stage2a_door_visual_object(child: bpy.types.Object, ordinary_door_sides: frozenset[str]) -> bool:
    if bool(child.get("tbg_roller_door")):
        return False
    if bool(child.get("tbg_roof_exit_door")):
        return False
    if bool(child.get("tbg_door_frame")):
        return child.get("tbg_door_frame_left") is not None and child.get("tbg_door_frame_right") is not None
    if not bool(child.get("tbg_is_door_leaf")):
        return False
    if not (child.name.endswith("Door_Main") or child.name.endswith("Door_Rear")):
        return False
    side = str(child.get("tbg_facade_side", "") or "")
    return side in ordinary_door_sides


def _is_opening_visual_seating_source(child: bpy.types.Object) -> bool:
    if bool(child.get("tbg_terrace_exit")):
        return False
    if bool(child.get("tbg_hangar_window")):
        return True
    if bool(child.get("tbg_window_frame_outer")) or bool(child.get("tbg_door_frame")):
        return True
    if bool(child.get("tbg_roof_exit_door")):
        return False
    if bool(child.get("tbg_window_fill")) or bool(child.get("tbg_window_mullion")) or bool(child.get("tbg_window_marker")):
        return False
    if bool(child.get("tbg_is_door_leaf")):
        return False
    return False


def _opening_stamp_missing_keys(child: bpy.types.Object) -> tuple[str, ...]:
    required_keys = (
        "tbg_wall_opening_kind",
        "tbg_wall_opening_side",
        "tbg_wall_opening_floor",
        "tbg_wall_opening_slot",
        "tbg_wall_cut_run_min",
        "tbg_wall_cut_run_max",
        "tbg_wall_cut_z_min",
        "tbg_wall_cut_z_max",
        "tbg_wall_plane_normal_axis",
        "tbg_wall_plane_run_axis",
        "tbg_wall_plane_pos",
    )
    return tuple(key for key in required_keys if child.get(key) is None)


def _opening_stamp_numbers(child: bpy.types.Object) -> tuple[float, float, float, float, float] | None:
    values = (
        _finite_float(child.get("tbg_wall_cut_run_min")),
        _finite_float(child.get("tbg_wall_cut_run_max")),
        _finite_float(child.get("tbg_wall_cut_z_min")),
        _finite_float(child.get("tbg_wall_cut_z_max")),
        _finite_float(child.get("tbg_wall_plane_pos")),
    )
    if any(value is None for value in values):
        return None
    run_min, run_max, z_min, z_max, plane_pos = (float(value) for value in values if value is not None)
    if run_max <= run_min or z_max <= z_min:
        return None
    return (run_min, run_max, z_min, z_max, plane_pos)


def _cut_matches_stamp(
    cut: VoxelWallRectCutFacts,
    *,
    run_min: float,
    run_max: float,
    z_min: float,
    z_max: float,
    tolerance: float = 0.001,
) -> bool:
    if cut.run_min is None or cut.run_max is None or cut.z_min is None or cut.z_max is None:
        return False
    return (
        abs(float(cut.run_min) - float(run_min)) <= tolerance
        and abs(float(cut.run_max) - float(run_max)) <= tolerance
        and abs(float(cut.z_min) - float(z_min)) <= tolerance
        and abs(float(cut.z_max) - float(z_max)) <= tolerance
    )


def _find_matching_opening_group_cut(
    groups: tuple[VoxelWallGroupFacts, ...],
    *,
    normal_axis: str,
    run_axis: str,
    plane_pos: float,
    run_min: float,
    run_max: float,
    z_min: float,
    z_max: float,
) -> tuple[VoxelWallGroupFacts, VoxelWallRectCutFacts] | None:
    for group in groups:
        if group.normal_axis != normal_axis or group.run_axis != run_axis:
            continue
        if group.plane_thickness_min_studs is None or group.plane_thickness_max_studs is None:
            continue
        if not (float(group.plane_thickness_min_studs) - 0.001 <= plane_pos <= float(group.plane_thickness_max_studs) + 0.001):
            continue
        for cut in group.rect_cuts:
            if _cut_matches_stamp(cut, run_min=run_min, run_max=run_max, z_min=z_min, z_max=z_max):
                return (group, cut)
    return None


def _opening_prism_bounds(
    *,
    group: VoxelWallGroupFacts,
    run_min: float,
    run_max: float,
    z_min: float,
    z_max: float,
) -> tuple[float, float, float, float, float, float] | None:
    if group.plane_thickness_min_studs is None or group.plane_thickness_max_studs is None:
        return None
    thickness_min = float(group.plane_thickness_min_studs)
    thickness_max = float(group.plane_thickness_max_studs)
    if group.normal_axis == "y" and group.run_axis == "x":
        return (run_min, run_max, thickness_min, thickness_max, z_min, z_max)
    if group.normal_axis == "x" and group.run_axis == "y":
        return (thickness_min, thickness_max, run_min, run_max, z_min, z_max)
    return None


def _opening_visual_run_z_bounds(
    root_bounds: tuple[float, float, float, float, float, float],
    *,
    run_axis: str,
) -> tuple[float, float, float, float] | None:
    if run_axis == "x":
        run_min, run_max = float(root_bounds[0]), float(root_bounds[1])
    elif run_axis == "y":
        run_min, run_max = float(root_bounds[2]), float(root_bounds[3])
    else:
        return None
    z_min, z_max = float(root_bounds[4]), float(root_bounds[5])
    if run_max - run_min <= 1e-6 or z_max - z_min <= 1e-6:
        return None
    return (
        round(run_min, 6),
        round(run_max, 6),
        round(z_min, 6),
        round(z_max, 6),
    )


def _opening_boundary_edges(
    group: VoxelWallGroupFacts,
    group_cells: tuple[VoxelWallCellFacts, ...],
    *,
    run_min: float,
    run_max: float,
    z_min: float,
    z_max: float,
    tolerance: float = 0.05,
) -> tuple[VoxelOpeningBoundaryEdgeFacts, ...]:
    if (
        group.plane_run_min_studs is None
        or group.plane_run_max_studs is None
        or group.plane_z_min_studs is None
        or group.plane_z_max_studs is None
    ):
        return ()
    plane_run_min = float(group.plane_run_min_studs)
    plane_run_max = float(group.plane_run_max_studs)
    plane_z_min = float(group.plane_z_min_studs)
    plane_z_max = float(group.plane_z_max_studs)
    required_margin = max(float(tolerance), float(MIN_NON_THICKNESS_CELL_SPAN_STUDS))
    _ = tolerance
    adjacency_window = max(0.001, min(0.05, float(MIN_NON_THICKNESS_CELL_SPAN_STUDS) / 7.0))

    def _edge_fact(side: str, required: bool, edges: list[float], target: float) -> VoxelOpeningBoundaryEdgeFacts:
        nearest_edge = None
        nearest_gap = None
        if edges:
            if side in {"left", "bottom"}:
                nearest_edge = max(edges)
                nearest_gap = target - nearest_edge
            else:
                nearest_edge = min(edges)
                nearest_gap = nearest_edge - target
            nearest_edge = round(float(nearest_edge), 6)
            nearest_gap = round(max(0.0, float(nearest_gap)), 6)
        return VoxelOpeningBoundaryEdgeFacts(
            side=side,
            required=bool(required),
            nearest_edge_studs=nearest_edge,
            nearest_gap_studs=nearest_gap,
            has_adjacent_boundary=bool(
                required
                and nearest_gap is not None
                and float(nearest_gap) <= adjacency_window + 1e-6
            ),
        )

    left_required = run_min > plane_run_min + required_margin
    left_edges = [
        float(bounds[1])
        for cell in group_cells
        if left_required
        and (bounds := _cell_run_bounds(cell)) is not None
        and (zbounds := _cell_z_bounds(cell)) is not None
        and bounds[1] <= run_min + _OPENING_BOUNDARY_COORD_EPSILON
        and _interval_overlap_positive(zbounds[0], zbounds[1], z_min, z_max)
    ]
    right_required = run_max < plane_run_max - required_margin
    right_edges = [
        float(bounds[0])
        for cell in group_cells
        if right_required
        and (bounds := _cell_run_bounds(cell)) is not None
        and (zbounds := _cell_z_bounds(cell)) is not None
        and bounds[0] >= run_max - _OPENING_BOUNDARY_COORD_EPSILON
        and _interval_overlap_positive(zbounds[0], zbounds[1], z_min, z_max)
    ]
    bottom_required = z_min > plane_z_min + required_margin
    bottom_edges = [
        float(zbounds[1])
        for cell in group_cells
        if bottom_required
        and (bounds := _cell_run_bounds(cell)) is not None
        and (zbounds := _cell_z_bounds(cell)) is not None
        and zbounds[1] <= z_min + _OPENING_BOUNDARY_COORD_EPSILON
        and _interval_overlap_positive(bounds[0], bounds[1], run_min, run_max)
    ]
    top_required = z_max < plane_z_max - required_margin
    top_edges = [
        float(zbounds[0])
        for cell in group_cells
        if top_required
        and (bounds := _cell_run_bounds(cell)) is not None
        and (zbounds := _cell_z_bounds(cell)) is not None
        and zbounds[0] >= z_max - _OPENING_BOUNDARY_COORD_EPSILON
        and _interval_overlap_positive(bounds[0], bounds[1], run_min, run_max)
    ]
    return (
        _edge_fact("left", left_required, left_edges, run_min),
        _edge_fact("right", right_required, right_edges, run_max),
        _edge_fact("bottom", bottom_required, bottom_edges, z_min),
        _edge_fact("top", top_required, top_edges, z_max),
    )


def _opening_gap_fact(
    group: VoxelWallGroupFacts,
    group_cells: tuple[VoxelWallCellFacts, ...],
    *,
    run_min: float,
    run_max: float,
    z_min: float,
    z_max: float,
    tolerance: float = 0.05,
) -> tuple[float | None, str | None]:
    edge_facts = _opening_boundary_edges(
        group,
        group_cells,
        run_min=run_min,
        run_max=run_max,
        z_min=z_min,
        z_max=z_max,
        tolerance=tolerance,
    )
    if not edge_facts:
        return (None, None)
    missing_boundary_sides = tuple(
        edge.side for edge in edge_facts if edge.required and not edge.has_adjacent_boundary
    )
    if missing_boundary_sides:
        return (float("inf"), missing_boundary_sides[0])
    gaps = [
        (float(edge.nearest_gap_studs), edge.side)
        for edge in edge_facts
        if edge.required and edge.nearest_gap_studs is not None
    ]
    if not gaps:
        return (0.0, None)
    max_gap, side = max(gaps, key=lambda item: item[0])
    return (round(float(max_gap), 6) if math.isfinite(max_gap) else max_gap, side)


def _opening_owner_class(
    *,
    matching_group_id: str | None,
    matching_cut_label: str | None,
    same_plane_overlap_cell_ids: tuple[str, ...],
    max_gap_studs: float | None,
    actual_max_gap_studs: float | None,
    cut_intrusion_cell_ids: tuple[str, ...],
    cross_plane_leakage_cell_ids: tuple[str, ...],
    sub_min_residuals: tuple[VoxelWallSubMinResidualFacts, ...],
    is_seating_source: bool,
) -> str:
    if sub_min_residuals:
        return "sub_min_residual"
    if not matching_group_id or not matching_cut_label:
        return "bad_payload_cut"
    if same_plane_overlap_cell_ids or cut_intrusion_cell_ids or cross_plane_leakage_cell_ids:
        return "bad_cell_boundary"
    if max_gap_studs is not None and (not math.isfinite(float(max_gap_studs)) or float(max_gap_studs) > 0.05):
        return "bad_cell_boundary"
    if is_seating_source and actual_max_gap_studs is not None and (
        not math.isfinite(float(actual_max_gap_studs)) or float(actual_max_gap_studs) > 0.05
    ):
        return "bad_visual_placement"
    return "none"


def _side_sign_for_attachment(side_key: str) -> float | None:
    if side_key in {"front", "left"}:
        return -1.0
    if side_key in {"back", "right", "roof_exit"}:
        return 1.0
    return None


def _normal_axis_for_side(side_key: str) -> str | None:
    if side_key in {"front", "back", "roof_exit"}:
        return "y"
    if side_key in {"left", "right"}:
        return "x"
    return None


def _side_from_object(child: bpy.types.Object) -> str | None:
    side = str(child.get("tbg_facade_side", "") or child.get("tbg_wall_opening_side", "") or "").strip().lower()
    if side in {"front", "back", "left", "right", "roof_exit"}:
        return side
    name = str(getattr(child, "name", "") or "").lower()
    for candidate in ("front", "back", "left", "right"):
        if f"_{candidate}_" in name or name.endswith(f"_{candidate}") or f"_{candidate}." in name:
            return candidate
    if "_rear_" in name or name.endswith("_rear"):
        return "back"
    return None


def _trim_back_face(bounds: tuple[float, float, float, float, float, float], side: str) -> float | None:
    if side == "front":
        return float(bounds[3])
    if side == "back" or side == "roof_exit":
        return float(bounds[2])
    if side == "left":
        return float(bounds[1])
    if side == "right":
        return float(bounds[0])
    return None


def _wall_outer_face(bounds: tuple[float, float, float, float, float, float], side: str) -> float | None:
    if side == "front":
        return float(bounds[2])
    if side == "back" or side == "roof_exit":
        return float(bounds[3])
    if side == "left":
        return float(bounds[0])
    if side == "right":
        return float(bounds[1])
    return None


def _bounds_projected_overlap_for_side(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
    side: str,
) -> bool:
    if side in {"front", "back", "roof_exit"}:
        return _interval_overlap_positive(left[0], left[1], right[0], right[1]) and _interval_overlap_positive(
            left[4],
            left[5],
            right[4],
            right[5],
        )
    if side in {"left", "right"}:
        return _interval_overlap_positive(left[2], left[3], right[2], right[3]) and _interval_overlap_positive(
            left[4],
            left[5],
            right[4],
            right[5],
        )
    return False


def _overlap_length(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
    return max(0.0, min(float(a_max), float(b_max)) - max(float(a_min), float(b_min)))


def _run_z_coverage_ratio(
    required_band: tuple[float, float, float, float],
    candidate_bands: tuple[tuple[float, float, float, float], ...],
) -> float:
    run_min, run_max, z_min, z_max = (float(value) for value in required_band)
    required_area = max(0.0, run_max - run_min) * max(0.0, z_max - z_min)
    if required_area <= 1e-9:
        return 1.0
    covered = 0.0
    # The current producers emit one simple top-band owner per opening.  Summing
    # clamped overlaps is sufficient and keeps validation consumer-only.
    for cand_run_min, cand_run_max, cand_z_min, cand_z_max in candidate_bands:
        covered += _overlap_length(run_min, run_max, cand_run_min, cand_run_max) * _overlap_length(
            z_min,
            z_max,
            cand_z_min,
            cand_z_max,
        )
    return round(min(1.0, covered / required_area), 6)


def _opening_run_z_bounds_for_child(
    root_obj: bpy.types.Object,
    child: bpy.types.Object,
) -> tuple[float, float, float, float] | None:
    run_axis = str(child.get("tbg_wall_plane_run_axis", "") or "").strip().lower()
    if run_axis not in {"x", "y"}:
        side = _side_from_object(child) or ""
        normal_axis = _normal_axis_for_side(side)
        run_axis = "x" if normal_axis == "y" else "y" if normal_axis == "x" else ""
    if run_axis not in {"x", "y"}:
        return None
    return _opening_visual_run_z_bounds(object_local_bounds(root_obj, child), run_axis=run_axis)


def _frame_mesh_inner_outer_height(child: bpy.types.Object) -> tuple[float | None, float | None]:
    mesh = getattr(child, "data", None)
    vertices = tuple(getattr(mesh, "vertices", ()) or ())
    if not vertices:
        return (None, None)
    z_values = sorted({round(float(vertex.co.z), 6) for vertex in vertices})
    if len(z_values) < 2:
        return (None, None)
    outer_height = round(float(z_values[-1] - z_values[0]), 6)
    if len(z_values) >= 4:
        inner_height = round(float(z_values[-2] - z_values[1]), 6)
    else:
        inner_height = None
    return (inner_height, outer_height)


def _is_valid_roof_exit_lintel_closure(child: bpy.types.Object) -> bool:
    if not bool(child.get("tbg_roof_exit_lintel_closure")):
        return False
    if bool(child.get("tbg_door_frame")) or bool(child.get("tbg_roof_exit_frame")):
        return False
    if bool(child.get("tbg_is_door_leaf")) or bool(child.get("tbg_door_panel")):
        return False
    return str(child.get("tbg_section_bucket", "") or "") == "Section_Walls_Roof"


def _mesh_triangle_count(child: bpy.types.Object) -> int:
    return sum(
        max(1, len(poly.vertices) - 2)
        for poly in getattr(getattr(child, "data", None), "polygons", [])
    )


def _mesh_material_names(child: bpy.types.Object) -> tuple[str, ...]:
    mesh = getattr(child, "data", None)
    materials = tuple(getattr(mesh, "materials", ()) or ())
    return tuple(str(getattr(material, "name", "") or "") for material in materials if material is not None)


def _polybudget_bucket(child: bpy.types.Object) -> str:
    return str(child.get("tbg_section_bucket", "") or child.get("tbg_render_bucket", "") or "<unbucketed>")


def _polybudget_category(child: bpy.types.Object) -> str:
    bucket = _polybudget_bucket(child)
    name = str(getattr(child, "name", "") or "")
    if "Opening" in bucket or bool(child.get("tbg_window_marker")) or bool(child.get("tbg_door_frame")):
        return "openings"
    if "Trim" in bucket or bool(child.get("tbg_wall_trim")) or bool(child.get("tbg_facade_band")):
        return "trim"
    if "Stairs" in bucket or "Stair" in name:
        return "stairs"
    if "Roof" in bucket or "Roof" in name:
        return "roof"
    if "Wall" in bucket:
        return "walls"
    return "other"


def _is_v3_wall_source_render_mesh(child: bpy.types.Object) -> bool:
    bucket = _polybudget_bucket(child)
    return (
        bool(child.get("tbg_voxel_wall_source"))
        or bool(child.get("tbg_wall_cell_object"))
        or bool(child.get("tbg_wall_cell_count"))
        or bucket in getattr(export_contract, "VOXEL_WALL_SOURCE_BUCKETS", frozenset())
    )


def _nearest_wall_face_for_trim(
    bounds: tuple[float, float, float, float, float, float],
    cells: tuple[VoxelWallCellFacts, ...],
    *,
    side: str | None,
) -> tuple[str | None, float | None, float | None]:
    sides = (side,) if side in {"front", "back", "left", "right"} else ("front", "back", "left", "right")
    best: tuple[float, str, float, float] | None = None
    for candidate_side in sides:
        back_face = _trim_back_face(bounds, candidate_side)
        if back_face is None:
            continue
        for cell in cells:
            cell_bounds = _cell_bounds_tuple(cell)
            if cell_bounds is None or not _bounds_projected_overlap_for_side(bounds, cell_bounds, candidate_side):
                continue
            wall_face = _wall_outer_face(cell_bounds, candidate_side)
            if wall_face is None:
                continue
            distance = abs(float(back_face) - float(wall_face))
            if best is None or distance < best[0]:
                best = (distance, candidate_side, float(wall_face), float(back_face))
    if best is None:
        return (side, None, None)
    return (best[1], best[2], best[3])


def _is_trim_attachment_object(child: bpy.types.Object) -> bool:
    if bool(child.get("tbg_freestanding")):
        return False
    if bool(child.get("tbg_terrace_rail")):
        return False
    bucket = str(child.get("tbg_section_bucket", "") or "")
    if bucket in _TRIM_ATTACHMENT_BUCKETS:
        return True
    if bool(child.get("tbg_hide_with_walls")) and bucket not in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
        label = f"{bucket} {getattr(child, 'name', '')}".lower()
        return "trim" in label or "band" in label or "cornice" in label or "cap" in label
    return False


def _collect_trim_attachment_facts(
    root_obj: bpy.types.Object,
    mesh_children: tuple[bpy.types.Object, ...],
    cells: tuple[VoxelWallCellFacts, ...],
) -> tuple[VoxelTrimAttachmentFacts, ...]:
    facts: list[VoxelTrimAttachmentFacts] = []
    for child in mesh_children:
        if not _is_trim_attachment_object(child):
            continue
        bounds = tuple(round(float(value), 6) for value in object_local_bounds(root_obj, child))
        side_hint = _side_from_object(child)
        side, nearest_wall_face, trim_back_face = _nearest_wall_face_for_trim(bounds, cells, side=side_hint)
        sign = _side_sign_for_attachment(side or "")
        if nearest_wall_face is None or trim_back_face is None or sign is None:
            air_gap = 1_000_000.0
            overlap = 0.0
        else:
            signed_outside = float(sign) * (float(trim_back_face) - float(nearest_wall_face))
            air_gap = round(max(0.0, signed_outside), 6)
            overlap = round(max(0.0, -signed_outside), 6)
        owner_class = (
            "floating_trim_band"
            if air_gap > TRIM_BACK_AIR_GAP_MAX_STUDS + 1e-9 or overlap + 1e-9 < TRIM_BACK_OVERLAP_MIN_STUDS
            else _DIAGNOSTIC_OWNER_UNKNOWN
        )
        facts.append(
            VoxelTrimAttachmentFacts(
                object_name=str(child.name),
                source_bucket=str(child.get("tbg_section_bucket", "") or ""),
                side=side,
                root_local_bounds=bounds,
                nearest_wall_face_studs=(round(float(nearest_wall_face), 6) if nearest_wall_face is not None else None),
                trim_back_face_studs=(round(float(trim_back_face), 6) if trim_back_face is not None else None),
                air_gap_studs=air_gap,
                overlap_studs=overlap,
                owner_class=owner_class,
            )
        )
    return tuple(facts)


def _is_opening_frame_candidate(child: bpy.types.Object) -> bool:
    if bool(child.get("tbg_terrace_exit")):
        return False
    if bool(child.get("tbg_window_frame_outer")) or bool(child.get("tbg_door_frame")):
        return True
    bucket = str(child.get("tbg_section_bucket", "") or "")
    return bucket in _OPENING_FRAME_BUCKETS and child.get("tbg_wall_opening_kind") is not None


def _frame_mesh_ring_metrics(child: bpy.types.Object) -> tuple[float | None, float | None]:
    mesh = getattr(child, "data", None)
    vertices = tuple(getattr(mesh, "vertices", ()) or ())
    if len(vertices) < 8:
        return (None, None)
    xs = sorted({round(float(vertex.co.x), 6) for vertex in vertices})
    ys = sorted({round(float(vertex.co.y), 6) for vertex in vertices})
    zs = sorted({round(float(vertex.co.z), 6) for vertex in vertices})
    if len(xs) < 4 or len(ys) < 2 or len(zs) < 4:
        return (None, None)
    outer_x_min, outer_x_max = xs[0], xs[-1]
    inner_x_min, inner_x_max = xs[1], xs[-2]
    outer_z_min, outer_z_max = zs[0], zs[-1]
    inner_z_min, inner_z_max = zs[1], zs[-2]
    ring_width = min(
        inner_x_min - outer_x_min,
        outer_x_max - inner_x_max,
        inner_z_min - outer_z_min,
        outer_z_max - inner_z_max,
    )
    depth = ys[-1] - ys[0]
    inner_return_faces = 0
    for polygon in tuple(getattr(mesh, "polygons", ()) or ()):
        poly_vertices = [vertices[index].co for index in polygon.vertices]
        poly_xs = [round(float(vertex.x), 6) for vertex in poly_vertices]
        poly_ys = [round(float(vertex.y), 6) for vertex in poly_vertices]
        poly_zs = [round(float(vertex.z), 6) for vertex in poly_vertices]
        spans_depth = max(poly_ys) - min(poly_ys) >= depth - 1e-5
        on_inner_x = max(poly_xs) - min(poly_xs) <= 1e-5 and (
            abs(poly_xs[0] - inner_x_min) <= 1e-5 or abs(poly_xs[0] - inner_x_max) <= 1e-5
        )
        on_inner_z = max(poly_zs) - min(poly_zs) <= 1e-5 and (
            abs(poly_zs[0] - inner_z_min) <= 1e-5 or abs(poly_zs[0] - inner_z_max) <= 1e-5
        )
        if spans_depth and (on_inner_x or on_inner_z):
            inner_return_faces += 1
    return_depth = depth if inner_return_faces >= 2 else 0.0
    return (round(max(0.0, float(ring_width)), 6), round(max(0.0, float(return_depth)), 6))


def _frame_mesh_topology_metrics(child: bpy.types.Object) -> tuple[int, int, bool]:
    mesh = getattr(child, "data", None)
    vertices = tuple(getattr(mesh, "vertices", ()) or ())
    polygons = tuple(getattr(mesh, "polygons", ()) or ())
    if len(vertices) < 8 or not polygons:
        return (1_000_000, 0, True)

    edge_use_counts: dict[tuple[int, int], int] = {}
    for polygon in polygons:
        indices = tuple(int(index) for index in polygon.vertices)
        for idx, start in enumerate(indices):
            end = indices[(idx + 1) % len(indices)]
            edge = (min(start, end), max(start, end))
            edge_use_counts[edge] = edge_use_counts.get(edge, 0) + 1
    boundary_edge_count = sum(1 for count in edge_use_counts.values() if count == 1)

    xs = sorted({round(float(vertex.co.x), 6) for vertex in vertices})
    ys = sorted({round(float(vertex.co.y), 6) for vertex in vertices})
    zs = sorted({round(float(vertex.co.z), 6) for vertex in vertices})
    if len(xs) < 4 or len(ys) < 2 or len(zs) < 4:
        return (boundary_edge_count, 0, True)
    outer_x_min, outer_x_max = xs[0], xs[-1]
    inner_x_min, inner_x_max = xs[1], xs[-2]
    outer_z_min, outer_z_max = zs[0], zs[-1]
    inner_z_min, inner_z_max = zs[1], zs[-2]
    depth = ys[-1] - ys[0]

    outer_perimeter_faces = 0
    for polygon in polygons:
        poly_vertices = [vertices[index].co for index in polygon.vertices]
        poly_xs = [round(float(vertex.x), 6) for vertex in poly_vertices]
        poly_ys = [round(float(vertex.y), 6) for vertex in poly_vertices]
        poly_zs = [round(float(vertex.z), 6) for vertex in poly_vertices]
        spans_depth = max(poly_ys) - min(poly_ys) >= depth - 1e-5
        on_outer_x = max(poly_xs) - min(poly_xs) <= 1e-5 and (
            abs(poly_xs[0] - outer_x_min) <= 1e-5 or abs(poly_xs[0] - outer_x_max) <= 1e-5
        )
        on_outer_z = max(poly_zs) - min(poly_zs) <= 1e-5 and (
            abs(poly_zs[0] - outer_z_min) <= 1e-5 or abs(poly_zs[0] - outer_z_max) <= 1e-5
        )
        if spans_depth and (on_outer_x or on_outer_z):
            outer_perimeter_faces += 1

    top_mass = max(0.0, outer_z_max - inner_z_max)
    bottom_mass = max(0.0, inner_z_min - outer_z_min)
    kind = str(child.get("tbg_wall_opening_kind", "") or "")
    bottom_required = kind != "door"
    missing_head_or_sill = top_mass + 1e-9 < FRAME_RING_WIDTH_MIN_STUDS or (
        bottom_required and bottom_mass + 1e-9 < FRAME_RING_WIDTH_MIN_STUDS
    )
    return (int(boundary_edge_count), int(outer_perimeter_faces), bool(missing_head_or_sill))


def _cut_envelope_match_delta(
    *,
    actual_run_min: float,
    actual_run_max: float,
    actual_z_min: float,
    actual_z_max: float,
    cut_run_min: float,
    cut_run_max: float,
    cut_z_min: float,
    cut_z_max: float,
) -> float:
    return round(
        max(
            abs(float(actual_run_min) - float(cut_run_min)),
            abs(float(actual_run_max) - float(cut_run_max)),
            abs(float(actual_z_min) - float(cut_z_min)),
            abs(float(actual_z_max) - float(cut_z_max)),
        ),
        6,
    )


def _opening_diagnostic_owner_class(
    *,
    opening: VoxelOpeningVisualFacts | None = None,
    legacy_owner_class: str = "none",
    cut_envelope_delta: float | None = None,
    ordinary_door_unseated: bool = False,
    roof_exit_top_gap: bool = False,
    visual_seal_gap: float | None = None,
) -> str:
    if ordinary_door_unseated:
        return "ordinary_door_unseated"
    if roof_exit_top_gap:
        return "roof_exit_lintel_unpacked"
    if cut_envelope_delta is not None and cut_envelope_delta > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:
        return "cut_envelope_mismatch"
    if visual_seal_gap is not None and (
        not math.isfinite(float(visual_seal_gap)) or float(visual_seal_gap) > OPENING_VISUAL_SEAL_GAP_MAX_STUDS
    ):
        return "visual_seal_gap"
    if legacy_owner_class in {"bad_payload_cut", "bad_cell_boundary", "bad_visual_placement"}:
        return "visual_seal_gap"
    if legacy_owner_class == "sub_min_residual":
        return "roof_exit_lintel_unpacked" if opening is not None and opening.is_roof_exit else "visual_seal_gap"
    return _DIAGNOSTIC_OWNER_UNKNOWN


def _collect_opening_frame_mass_facts(
    root_obj: bpy.types.Object,
    mesh_children: tuple[bpy.types.Object, ...],
    opening_by_object_name: dict[str, VoxelOpeningVisualFacts],
    cells: tuple[VoxelWallCellFacts, ...],
) -> tuple[VoxelOpeningFrameMassFacts, ...]:
    facts: list[VoxelOpeningFrameMassFacts] = []
    for child in mesh_children:
        if not _is_opening_frame_candidate(child):
            continue
        bounds = tuple(round(float(value), 6) for value in object_local_bounds(root_obj, child))
        opening = opening_by_object_name.get(str(child.name))
        side = _side_from_object(child)
        normal_axis = str(child.get("tbg_wall_plane_normal_axis", "") or "").strip().lower()
        if normal_axis not in {"x", "y"}:
            normal_axis = _normal_axis_for_side(side or "") or ""
        if normal_axis == "x":
            silhouette = round(float(bounds[1]) - float(bounds[0]), 6)
        elif normal_axis == "y":
            silhouette = round(float(bounds[3]) - float(bounds[2]), 6)
        else:
            silhouette = round(min(float(bounds[1]) - float(bounds[0]), float(bounds[3]) - float(bounds[2])), 6)
        ring_width, return_depth = _frame_mesh_ring_metrics(child)
        open_boundary_edge_count, outer_perimeter_face_count, sill_or_head_missing = _frame_mesh_topology_metrics(child)
        plane_pos = _finite_float(child.get("tbg_wall_plane_pos"))
        if plane_pos is not None and normal_axis in {"x", "y"}:
            interval = (float(bounds[0]), float(bounds[1])) if normal_axis == "x" else (float(bounds[2]), float(bounds[3]))
            if float(plane_pos) < interval[0]:
                gasket_air_gap = round(interval[0] - float(plane_pos), 6)
                gasket_overlap = 0.0
            elif float(plane_pos) > interval[1]:
                gasket_air_gap = round(float(plane_pos) - interval[1], 6)
                gasket_overlap = 0.0
            else:
                gasket_air_gap = 0.0
                gasket_overlap = round(min(float(plane_pos) - interval[0], interval[1] - float(plane_pos)), 6)
        else:
            _, nearest_wall_face, frame_back_face = _nearest_wall_face_for_trim(bounds, cells, side=side)
            sign = _side_sign_for_attachment(side or "")
            if nearest_wall_face is None or frame_back_face is None or sign is None:
                gasket_air_gap = None
                gasket_overlap = None
            else:
                signed_outside = float(sign) * (float(frame_back_face) - float(nearest_wall_face))
                gasket_air_gap = round(max(0.0, signed_outside), 6)
                gasket_overlap = round(max(0.0, -signed_outside), 6)
        cut_delta = opening.cut_envelope_match_delta_studs if opening is not None else None
        has_stamp = child.get("tbg_wall_opening_kind") is not None
        owner_class = _DIAGNOSTIC_OWNER_UNKNOWN
        if not has_stamp:
            owner_class = "unstamped_opening_trim"
        elif (
            silhouette < FRAME_SILHOUETTE_MIN_STUDS
            or ring_width is None
            or ring_width < FRAME_RING_WIDTH_MIN_STUDS
            or return_depth is None
            or return_depth < FRAME_INNER_RETURN_MIN_STUDS
            or open_boundary_edge_count != 0
            or outer_perimeter_face_count < 4
            or sill_or_head_missing
            or gasket_air_gap is None
            or gasket_air_gap > TRIM_BACK_AIR_GAP_MAX_STUDS
            or gasket_overlap is None
            or gasket_overlap < TRIM_BACK_OVERLAP_MIN_STUDS
        ):
            owner_class = "frame_mass_thin"
        elif cut_delta is not None and cut_delta > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:
            owner_class = "cut_envelope_mismatch"
        facts.append(
            VoxelOpeningFrameMassFacts(
                object_name=str(child.name),
                source_bucket=str(child.get("tbg_section_bucket", "") or ""),
                kind=(str(child.get("tbg_wall_opening_kind", "") or "") or None),
                side=side,
                root_local_bounds=bounds,
                has_opening_stamp=bool(has_stamp),
                silhouette_thickness_studs=silhouette,
                ring_width_studs=ring_width,
                inner_return_depth_studs=return_depth,
                open_boundary_edge_count=int(open_boundary_edge_count),
                outer_perimeter_face_count=int(outer_perimeter_face_count),
                sill_or_head_mass_missing=bool(sill_or_head_missing),
                gasket_back_overlap_studs=gasket_overlap,
                gasket_air_gap_studs=gasket_air_gap,
                cut_envelope_match_delta_studs=cut_delta,
                owner_class=owner_class,
            )
        )
    return tuple(facts)


def _collect_voxel_wall_facts(
    root_obj: bpy.types.Object,
    mesh_children: tuple[bpy.types.Object, ...],
    occupancy_payload: dict,
    effective_spec: object,
) -> VoxelWallFacts:
    stale_authored_evidence: set[str] = set()
    legacy_helper_evidence: set[str] = set()
    malformed_entries: list[str] = []
    group_facts: list[VoxelWallGroupFacts] = []
    cell_facts: list[VoxelWallCellFacts] = []
    visible_wall_object_facts: list[VoxelVisibleWallObjectFacts] = []
    runtime_render_mesh_names = frozenset(str(child.name) for child in runtime_render_meshes(root_obj))

    for child in mesh_children:
        child_name = str(child.name)
        section_bucket = str(child.get("tbg_section_bucket", "") or "")
        if section_bucket in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
            group_ids = _visible_wall_group_ids(child)
            composite_bounds = composite_part_root_local_bounds(root_obj, child)
            scalar_cell_count = _nonnegative_int(child.get("tbg_wall_cell_count"))
            material = _object_material_slot0(child)
            visible_wall_object_facts.append(
                VoxelVisibleWallObjectFacts(
                    object_name=child_name,
                    source_bucket=section_bucket,
                    emit_owner=str(child.get("tbg_wall_emit_owner", "") or ""),
                    payload_kind=str(child.get("tbg_wall_payload_kind", "") or ""),
                    payload_version=str(child.get("tbg_wall_payload_version", "") or ""),
                    export_contract_version=str(child.get("tbg_wall_export_contract_version", "") or ""),
                    expected_emit_owner="occupancy_v3",
                    expected_payload_kind=export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND,
                    expected_payload_version=export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION,
                    group_id=str(child.get("tbg_wall_group_id", "") or ""),
                    group_ids=group_ids,
                    scalar_cell_count=scalar_cell_count,
                    composite_cell_count=len(composite_bounds),
                    texture_projection=str(child.get("tbg_texture_projection", "") or ""),
                    texture_image_period_contract=str(child.get("tbg_texture_image_period_contract", "") or ""),
                    texture_uv_source=str(child.get("tbg_texture_uv_source", "") or ""),
                    texture_contract_cell_count=_nonnegative_int(child.get("tbg_texture_contract_cell_count")),
                    texture_key_set=_texture_key_set_from_object(child),
                    texture_face_axis_table_version=str(child.get("tbg_texture_face_axis_table_version", "") or ""),
                    material_name=str(material.name) if material is not None else "",
                    material_is_roblox_basepart_sim_preview=bool(
                        material.get("tbg_roblox_basepart_sim_preview") if material is not None else False
                    ),
                    material_roblox_basepart_sim_pattern=str(
                        material.get("tbg_roblox_basepart_sim_pattern", "") if material is not None else ""
                    ),
                    has_composite_part_bounds=bool(composite_bounds),
                    is_runtime_render_mesh=child_name in runtime_render_mesh_names,
                )
            )
        if (
            "_WEX_BRK_" in child_name
            or "_WEX_SFT_" in child_name
            or bool(child.get("tbg_exterior_brick"))
            or bool(child.get("tbg_exterior_surface_tile"))
            or section_bucket in {"Section_Openings_Trim_Wall", "Section_Openings_Trim_Panel"}
        ):
            stale_authored_evidence.add(child_name)
        if bool(child.get("tbg_voxel_wall_marker")):
            legacy_helper_evidence.add(child_name)

    cells_payload = occupancy_payload.get("cells")
    if not isinstance(cells_payload, list):
        malformed_entries.append("payload.cells")
        cells_payload = []
    groups_payload = occupancy_payload.get("wall_groups")
    if not isinstance(groups_payload, list):
        malformed_entries.append("payload.wall_groups")
        groups_payload = []

    for group_index, group_payload in enumerate(groups_payload, start=1):
        group_label = f"wall_groups[{group_index}]"
        if not isinstance(group_payload, dict):
            malformed_entries.append(group_label)
            continue
        group_facts.append(
            VoxelWallGroupFacts(
                label=group_label,
                group_id=str(group_payload.get("group_id", "") or ""),
                payload=group_payload,
                source_bucket=str(group_payload.get("source_bucket", "") or ""),
                material_family=str(group_payload.get("material_family", "") or ""),
                authoring_mode=str(group_payload.get("authoring_mode", "") or "").strip(),
                normal_axis=str(group_payload.get("normal_axis", "") or "").strip().lower(),
                run_axis=str(group_payload.get("run_axis", "") or "").strip().lower(),
                plane_run_min_studs=_payload_float(group_payload, "plane_run_min_studs"),
                plane_run_max_studs=_payload_float(group_payload, "plane_run_max_studs"),
                plane_z_min_studs=_payload_float(group_payload, "plane_z_min_studs"),
                plane_z_max_studs=_payload_float(group_payload, "plane_z_max_studs"),
                plane_thickness_min_studs=_payload_float(group_payload, "plane_thickness_min_studs"),
                plane_thickness_max_studs=_payload_float(group_payload, "plane_thickness_max_studs"),
                visual_style=(str(group_payload.get("visual_style", "") or "").strip() or None),
                display_color_rgb=_payload_color3(group_payload, "display_color_rgb"),
                surface_u_origin_studs=_finite_float(group_payload.get("surface_u_origin_studs")),
                surface_v_origin_studs=_finite_float(group_payload.get("surface_v_origin_studs")),
                texture_key=str(group_payload.get("texture_key", "") or "").strip(),
                texture_projection=str(group_payload.get("texture_projection", "") or "").strip().upper(),
                texture_image_period_contract=str(group_payload.get("texture_image_period_contract", "") or "").strip().upper(),
                texture_face_axis_table_version=str(group_payload.get("texture_face_axis_table_version", "") or "").strip().upper(),
                studs_per_tile_u=_finite_float(group_payload.get("studs_per_tile_u")),
                studs_per_tile_v=_finite_float(group_payload.get("studs_per_tile_v")),
                color_modulation_policy=str(group_payload.get("color_modulation_policy", "") or "").strip().upper(),
                cell_count=(
                    int(group_payload.get("cell_count"))
                    if isinstance(group_payload.get("cell_count"), int)
                    else None
                ),
                cell_ids=(),
                source_fragment_ids=tuple(
                    sorted(
                        str(item or "").strip()
                        for item in group_payload.get("source_fragment_ids", ())
                        if str(item or "").strip()
                    )
                )
                if isinstance(group_payload.get("source_fragment_ids", ()), list)
                else (),
                rect_cuts=_payload_rect_cuts(group_payload, group_label, malformed_entries),
                top_profile=_payload_top_profile(group_payload, group_label, malformed_entries),
            )
        )

    group_lookup = {group.group_id: group for group in group_facts if group.group_id}
    for cell_index, cell_payload in enumerate(cells_payload, start=1):
        cell_label = f"cells[{cell_index}]"
        if not isinstance(cell_payload, dict):
            malformed_entries.append(cell_label)
            continue
        cell_id = str(cell_payload.get("cell_id", "") or "")
        group_id = str(cell_payload.get("group_id", "") or "")
        group = group_lookup.get(group_id)
        source_bucket = group.source_bucket if group is not None else ""
        material_family = group.material_family if group is not None else ""
        normal_axis = str(cell_payload.get("normal_axis", "") or "").strip().lower()
        run_axis = str(cell_payload.get("run_axis", "") or "").strip().lower()
        visual_style = group.visual_style if group is not None else None
        display_color_rgb = group.display_color_rgb if group is not None else None
        surface_u_origin_studs = group.surface_u_origin_studs if group is not None else None
        surface_v_origin_studs = group.surface_v_origin_studs if group is not None else None
        texture_key = group.texture_key if group is not None else ""
        texture_projection = group.texture_projection if group is not None else ""
        texture_image_period_contract = group.texture_image_period_contract if group is not None else ""
        texture_face_axis_table_version = group.texture_face_axis_table_version if group is not None else ""
        studs_per_tile_u = group.studs_per_tile_u if group is not None else None
        studs_per_tile_v = group.studs_per_tile_v if group is not None else None
        color_modulation_policy = group.color_modulation_policy if group is not None else ""
        min_studs = _payload_required_vector3(cell_payload, "min_studs")
        size_studs = _payload_required_vector3(cell_payload, "size_studs")
        max_studs = _cell_max_studs(min_studs, size_studs)

        cell_facts.append(
            VoxelWallCellFacts(
                label=cell_label,
                cell_id=cell_id,
                group_id=group_id,
                payload=cell_payload,
                source_bucket=source_bucket,
                material_family=material_family,
                normal_axis=normal_axis,
                run_axis=run_axis,
                visual_style=visual_style,
                display_color_rgb=display_color_rgb,
                surface_u_origin_studs=surface_u_origin_studs,
                surface_v_origin_studs=surface_v_origin_studs,
                texture_key=texture_key,
                texture_projection=texture_projection,
                texture_image_period_contract=texture_image_period_contract,
                texture_face_axis_table_version=texture_face_axis_table_version,
                studs_per_tile_u=studs_per_tile_u,
                studs_per_tile_v=studs_per_tile_v,
                color_modulation_policy=color_modulation_policy,
                min_studs=min_studs,
                size_studs=size_studs,
                max_studs=max_studs,
            )
        )

    group_ids = [group.group_id for group in group_facts if group.group_id]
    duplicate_group_ids = tuple(sorted({group_id for group_id in group_ids if group_ids.count(group_id) > 1}))
    cell_ids = [cell.cell_id for cell in cell_facts if cell.cell_id]
    duplicate_cell_ids = tuple(sorted({cell_id for cell_id in cell_ids if cell_ids.count(cell_id) > 1}))

    bounds_buckets: dict[tuple[float, float, float, float, float, float], list[str]] = {}
    horizontal_cell_ids: list[str] = []
    micro_span_cell_ids: list[str] = []
    for cell in cell_facts:
        fact_id = cell.cell_id or cell.label
        if cell.min_studs is not None and cell.size_studs is not None:
            bounds_signature = (
                float(cell.min_studs[0]),
                float(cell.min_studs[1]),
                float(cell.min_studs[2]),
                float(cell.size_studs[0]),
                float(cell.size_studs[1]),
                float(cell.size_studs[2]),
            )
            bounds_buckets.setdefault(bounds_signature, []).append(fact_id)
        if cell.normal_axis == "z":
            horizontal_cell_ids.append(fact_id)
        if cell.size_studs is not None:
            run_axis_index = 0 if cell.run_axis == "x" else 1 if cell.run_axis == "y" else None
            if run_axis_index is not None:
                if float(cell.size_studs[run_axis_index]) + 1e-6 < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
                    micro_span_cell_ids.append(fact_id)
            if float(cell.size_studs[2]) + 1e-6 < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
                micro_span_cell_ids.append(fact_id)
    duplicate_cell_bounds = tuple(
        VoxelWallDuplicateBoundsFacts(
            bounds_signature=bounds_signature,
            cell_ids=tuple(sorted(bounds_cell_ids)),
        )
        for bounds_signature, bounds_cell_ids in sorted(bounds_buckets.items())
        if len(bounds_cell_ids) > 1
    )

    overlapping_cells: list[VoxelWallOverlapFacts] = []
    for left_index, left in enumerate(cell_facts):
        for right in cell_facts[left_index + 1 :]:
            if not _cells_overlap_positive_volume(left, right):
                continue
            overlapping_cells.append(
                VoxelWallOverlapFacts(
                    cell_ids=tuple(sorted((left.cell_id or left.label, right.cell_id or right.label))),
                    cell_pair_count=1,
                )
            )

    payload_cell_size = _finite_float(occupancy_payload.get("cell_size_studs"))
    cell_size = float(payload_cell_size) if payload_cell_size is not None and payload_cell_size > 0.0 else 0.75
    cells_by_group: dict[str, list[VoxelWallCellFacts]] = {}
    for cell in cell_facts:
        if cell.group_id:
            cells_by_group.setdefault(cell.group_id, []).append(cell)

    plane_area_coverages: list[VoxelWallGroupAreaCoverageFacts] = []
    opening_cut_intrusions: list[VoxelWallCutIntrusionFacts] = []
    top_profile_protrusions: list[VoxelWallTopProfileProtrusionFacts] = []
    sub_min_residuals: list[VoxelWallSubMinResidualFacts] = []
    opening_bounds_off_grid_count = 0
    brick_opening_adjacent_non_grid_cell_ids: set[str] = set()
    adapter_group_ids = tuple(
        sorted(
            (group.group_id or group.label)
            for group in group_facts
            if group.authoring_mode == "fragment_adapter" or bool(group.source_fragment_ids)
        )
    )
    for group in group_facts:
        group_cells = tuple(cells_by_group.get(group.group_id, ()))
        sub_min_residuals.extend(_group_sub_min_residuals(group))
        is_brick_masonry_group = group.material_family == "BRICK" and group.visual_style == "BRICK_MASONRY"
        for cut in group.rect_cuts:
            if not (is_brick_masonry_group and _cut_is_interior_window_like(group, cut)):
                continue
            if _cut_bounds_off_grid(group, cut, cell_size=cell_size):
                opening_bounds_off_grid_count += 1
            for cell in group_cells:
                if _cell_touches_cut_boundary(cell, cut) and _cell_has_non_grid_surface_span(cell, group, cell_size=cell_size):
                    brick_opening_adjacent_non_grid_cell_ids.add(cell.cell_id or cell.label)
        expected_area = _expected_group_solid_area(group, cell_size=cell_size)
        if expected_area is not None and expected_area > 1e-6:
            actual_area = _actual_group_cell_area(group_cells)
            plane_area_coverages.append(
                VoxelWallGroupAreaCoverageFacts(
                    group_id=group.group_id or group.label,
                    expected_solid_area_studs2=expected_area,
                    actual_cell_area_studs2=actual_area,
                    coverage_ratio=round(actual_area / expected_area, 6),
                )
            )
        for cut in group.rect_cuts:
            intruding_cell_ids = tuple(
                sorted(
                    (cell.cell_id or cell.label)
                    for cell in group_cells
                    if _cell_overlaps_cut(cell, cut)
                )
            )
            if intruding_cell_ids:
                opening_cut_intrusions.append(
                    VoxelWallCutIntrusionFacts(
                        group_id=group.group_id or group.label,
                        cut_label=cut.label,
                        cell_ids=intruding_cell_ids,
                    )
                )
        if group.top_profile:
            protruding_cell_ids: list[str] = []
            for cell in group_cells:
                run_bounds = _cell_run_bounds(cell)
                z_bounds = _cell_z_bounds(cell)
                if run_bounds is None or z_bounds is None:
                    continue
                if _cell_above_top_profile(
                    group.top_profile,
                    run_min=run_bounds[0],
                    run_max=run_bounds[1],
                    z_max=z_bounds[1],
                ):
                    protruding_cell_ids.append(cell.cell_id or cell.label)
            if protruding_cell_ids:
                top_profile_protrusions.append(
                    VoxelWallTopProfileProtrusionFacts(
                        group_id=group.group_id or group.label,
                        cell_ids=tuple(sorted(protruding_cell_ids)),
                    )
                )

    cut_intrusion_lookup: dict[tuple[str, str], tuple[str, ...]] = {
        (intrusion.group_id, intrusion.cut_label): intrusion.cell_ids
        for intrusion in opening_cut_intrusions
    }
    sub_min_residual_lookup: dict[tuple[str, str], tuple[VoxelWallSubMinResidualFacts, ...]] = {}
    for residual in sub_min_residuals:
        sub_min_residual_lookup.setdefault((residual.group_id, residual.cut_label), ())
        sub_min_residual_lookup[(residual.group_id, residual.cut_label)] = (
            *sub_min_residual_lookup[(residual.group_id, residual.cut_label)],
            residual,
        )
    ordinary_door_sides = frozenset(
        str(child.get("tbg_facade_side", "") or "")
        for child in mesh_children
        if bool(child.get("tbg_door_frame"))
        and child.get("tbg_door_frame_left") is not None
        and child.get("tbg_door_frame_right") is not None
    )
    opening_visuals: list[VoxelOpeningVisualFacts] = []
    opening_stamp_issues: list[VoxelOpeningStampIssueFacts] = []
    deferred_unstamped_openings: list[VoxelOpeningStampIssueFacts] = []

    for child in mesh_children:
        expects_window_stamp = _is_window_visual_opening_object(child)
        expects_deferred_window = not child.get("tbg_wall_opening_kind") and _is_stage2a_deferred_window(child)
        expects_door_stamp = _is_stage2a_door_visual_object(child, ordinary_door_sides)
        if expects_deferred_window:
            deferred_unstamped_openings.append(
                VoxelOpeningStampIssueFacts(
                    object_name=str(child.name),
                    reason="rear ground-floor service-door override window has no authored Stage 2A cut stamp",
                )
            )
            continue
        if not (expects_window_stamp or expects_door_stamp or child.get("tbg_wall_opening_kind")):
            continue

        missing_keys = _opening_stamp_missing_keys(child)
        if missing_keys:
            opening_stamp_issues.append(
                VoxelOpeningStampIssueFacts(
                    object_name=str(child.name),
                    reason="missing " + ", ".join(missing_keys),
                )
            )
            continue
        numeric_stamp = _opening_stamp_numbers(child)
        if numeric_stamp is None:
            opening_stamp_issues.append(
                VoxelOpeningStampIssueFacts(
                    object_name=str(child.name),
                    reason="non-finite or non-positive cut/plane scalar metadata",
                )
            )
            continue

        run_min, run_max, z_min, z_max, plane_pos = numeric_stamp
        kind = str(child.get("tbg_wall_opening_kind", "") or "")
        side = str(child.get("tbg_wall_opening_side", "") or "")
        normal_axis = str(child.get("tbg_wall_plane_normal_axis", "") or "").strip().lower()
        run_axis = str(child.get("tbg_wall_plane_run_axis", "") or "").strip().lower()
        if kind not in {"window", "door"} or normal_axis not in {"x", "y"} or run_axis not in {"x", "y"}:
            opening_stamp_issues.append(
                VoxelOpeningStampIssueFacts(
                    object_name=str(child.name),
                    reason=f"invalid kind/axis metadata kind={kind!r} normal_axis={normal_axis!r} run_axis={run_axis!r}",
                )
            )
            continue
        floor = int(child.get("tbg_wall_opening_floor", -1) or -1)
        slot = int(child.get("tbg_wall_opening_slot", -1) or -1)
        root_bounds = object_local_bounds(root_obj, child)
        visual_run_z_bounds = _opening_visual_run_z_bounds(root_bounds, run_axis=run_axis)
        if visual_run_z_bounds is None:
            opening_stamp_issues.append(
                VoxelOpeningStampIssueFacts(
                    object_name=str(child.name),
                    reason="non-positive actual projected visual opening bounds",
                )
            )
            continue
        actual_run_min, actual_run_max, actual_z_min, actual_z_max = visual_run_z_bounds
        is_seating_source = _is_opening_visual_seating_source(child)
        is_window_frame = bool(child.get("tbg_window_frame_outer"))
        is_door_frame = bool(child.get("tbg_door_frame"))
        is_terrace_exit = bool(child.get("tbg_terrace_exit"))
        is_roof_exit = bool(child.get("tbg_roof_exit_door")) or side == "roof_exit"
        if is_seating_source:
            cut_envelope_delta = _cut_envelope_match_delta(
                actual_run_min=actual_run_min,
                actual_run_max=actual_run_max,
                actual_z_min=actual_z_min,
                actual_z_max=actual_z_max,
                cut_run_min=run_min,
                cut_run_max=run_max,
                cut_z_min=z_min,
                cut_z_max=z_max,
            )
        else:
            cut_envelope_delta = None
        match = _find_matching_opening_group_cut(
            tuple(group_facts),
            normal_axis=normal_axis,
            run_axis=run_axis,
            plane_pos=plane_pos,
            run_min=run_min,
            run_max=run_max,
            z_min=z_min,
            z_max=z_max,
        )
        matching_group_id: str | None = None
        matching_cut_label: str | None = None
        same_plane_overlap_cell_ids: tuple[str, ...] = ()
        cut_intrusion_cell_ids: tuple[str, ...] = ()
        cross_plane_leakage_cell_ids: tuple[str, ...] = ()
        max_gap_studs: float | None = None
        gap_side: str | None = None
        actual_max_gap_studs: float | None = None
        actual_gap_side: str | None = None
        actual_missing_boundary_sides: tuple[str, ...] = ()
        nearest_final_cell_edges_by_side: tuple[VoxelOpeningBoundaryEdgeFacts, ...] = ()
        opening_sub_min_residuals: tuple[VoxelWallSubMinResidualFacts, ...] = ()
        if match is not None:
            group, cut = match
            matching_group_id = group.group_id or group.label
            matching_cut_label = cut.label
            group_cells = tuple(cells_by_group.get(group.group_id, ()))
            same_plane_overlap_cell_ids = tuple(
                sorted(
                    cell.cell_id or cell.label
                    for cell in group_cells
                    if (cell_bounds := _cell_bounds_tuple(cell)) is not None
                    and _bounds_overlap_positive_volume(root_bounds, cell_bounds, epsilon=0.01)
                )
            )
            cut_intrusion_cell_ids = cut_intrusion_lookup.get((matching_group_id, matching_cut_label), ())
            opening_sub_min_residuals = sub_min_residual_lookup.get((matching_group_id, matching_cut_label), ())
            max_gap_studs, gap_side = _opening_gap_fact(
                group,
                group_cells,
                run_min=run_min,
                run_max=run_max,
                z_min=z_min,
                z_max=z_max,
            )
            if not is_seating_source:
                max_gap_studs = None
                gap_side = None
            if is_seating_source:
                actual_max_gap_studs, actual_gap_side = _opening_gap_fact(
                    group,
                    group_cells,
                    run_min=actual_run_min,
                    run_max=actual_run_max,
                    z_min=actual_z_min,
                    z_max=actual_z_max,
                )
                nearest_final_cell_edges_by_side = _opening_boundary_edges(
                    group,
                    group_cells,
                    run_min=actual_run_min,
                    run_max=actual_run_max,
                    z_min=actual_z_min,
                    z_max=actual_z_max,
                )
                actual_missing_boundary_sides = tuple(
                    edge.side
                    for edge in nearest_final_cell_edges_by_side
                    if edge.required and not edge.has_adjacent_boundary
                )
            opening_prism = _opening_prism_bounds(
                group=group,
                run_min=run_min,
                run_max=run_max,
                z_min=z_min,
                z_max=z_max,
            )
            if opening_prism is not None:
                leakage_ids: list[str] = []
                for candidate in cell_facts:
                    if candidate.group_id == group.group_id:
                        continue
                    if candidate.source_bucket not in {"Section_Walls_Interior", "Section_Stairs_RoomShell"}:
                        continue
                    candidate_bounds = _cell_bounds_tuple(candidate)
                    if candidate_bounds is None:
                        continue
                    if _bounds_overlap_positive_volume(opening_prism, candidate_bounds, epsilon=0.01):
                        leakage_ids.append(candidate.cell_id or candidate.label)
                cross_plane_leakage_cell_ids = tuple(sorted(leakage_ids))
        legacy_owner_class = _opening_owner_class(
            matching_group_id=matching_group_id,
            matching_cut_label=matching_cut_label,
            same_plane_overlap_cell_ids=same_plane_overlap_cell_ids,
            max_gap_studs=max_gap_studs,
            actual_max_gap_studs=actual_max_gap_studs,
            cut_intrusion_cell_ids=cut_intrusion_cell_ids,
            cross_plane_leakage_cell_ids=cross_plane_leakage_cell_ids,
            sub_min_residuals=opening_sub_min_residuals,
            is_seating_source=is_seating_source,
        )
        roof_exit_top_gap = bool(
            is_roof_exit
            and is_seating_source
            and actual_z_max is not None
            and float(z_max) - float(actual_z_max) > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
        )
        diagnostic_owner_class = _opening_diagnostic_owner_class(
            legacy_owner_class=legacy_owner_class,
            cut_envelope_delta=cut_envelope_delta,
            roof_exit_top_gap=roof_exit_top_gap,
            visual_seal_gap=actual_max_gap_studs if is_seating_source else None,
        )
        opening_visuals.append(
            VoxelOpeningVisualFacts(
                object_name=str(child.name),
                kind=kind,
                side=side,
                floor=floor,
                slot=slot,
                root_local_bounds=tuple(round(float(value), 6) for value in root_bounds),
                cut_run_min=run_min,
                cut_run_max=run_max,
                cut_z_min=z_min,
                cut_z_max=z_max,
                actual_run_min=actual_run_min,
                actual_run_max=actual_run_max,
                actual_z_min=actual_z_min,
                actual_z_max=actual_z_max,
                plane_normal_axis=normal_axis,
                plane_run_axis=run_axis,
                plane_pos=plane_pos,
                matching_group_id=matching_group_id,
                matching_cut_label=matching_cut_label,
                same_plane_overlap_cell_ids=same_plane_overlap_cell_ids,
                max_gap_studs=max_gap_studs,
                gap_side=gap_side,
                actual_max_gap_studs=actual_max_gap_studs,
                actual_gap_side=actual_gap_side,
                actual_missing_boundary_sides=actual_missing_boundary_sides,
                nearest_final_cell_edges_by_side=nearest_final_cell_edges_by_side,
                sub_min_residuals=opening_sub_min_residuals,
                owner_class=legacy_owner_class,
                is_seating_source=is_seating_source,
                cut_intrusion_cell_ids=cut_intrusion_cell_ids,
                cross_plane_leakage_cell_ids=cross_plane_leakage_cell_ids,
                is_window_frame=is_window_frame,
                is_door_frame=is_door_frame,
                is_terrace_exit=is_terrace_exit,
                is_roof_exit=is_roof_exit,
                cut_envelope_match_delta_studs=cut_envelope_delta,
                diagnostic_owner_class=diagnostic_owner_class,
            )
        )

    preview_objects = iter_voxel_preview_cache_objects(root_obj)
    preview_cache_object_names = tuple(sorted(str(obj.name) for obj in preview_objects))
    preview_cache_cell_count = (
        sum(_nonnegative_int(obj.get("tbg_voxel_preview_cell_count")) or 0 for obj in preview_objects)
        if preview_objects
        else None
    )
    real_visible_cell_count = sum(fact.composite_cell_count for fact in visible_wall_object_facts)
    visible_scalar_cell_count = sum(fact.scalar_cell_count or 0 for fact in visible_wall_object_facts)
    runtime_render_wall_object_names = tuple(
        sorted(fact.object_name for fact in visible_wall_object_facts if fact.is_runtime_render_mesh)
    )
    opening_by_object_name = {opening.object_name: opening for opening in opening_visuals}
    window_fill_visual_truths: list[WindowFillVisualTruthFacts] = []
    for child in mesh_children:
        if not bool(child.get("tbg_window_fill")):
            continue
        material = _object_material_slot0(child)
        uv_required = bool(material_uv_settings(material)["requires_uv"]) if material is not None else False
        uv_missing = bool(uv_required and not _mesh_uv_sample_points(child))
        opening = opening_by_object_name.get(str(child.name))
        window_fill_visual_truths.append(
            WindowFillVisualTruthFacts(
                object_name=str(child.name),
                material_name=str(material.name) if material is not None else "",
                diffuse_rgba=_material_diffuse_rgba(material),
                shader_rgb=_window_fill_shader_rgb(child, material),
                shader_uses_image=_shader_uses_image(material),
                uv_required=uv_required,
                uv_missing=uv_missing,
                same_plane_overlap_cell_ids=(
                    tuple(
                        sorted(
                            set(opening.same_plane_overlap_cell_ids)
                            | set(opening.cut_intrusion_cell_ids)
                        )
                    )
                    if opening is not None
                    else ()
                ),
                cut_intrusion_cell_ids=opening.cut_intrusion_cell_ids if opening is not None else (),
            )
        )
    window_fill_wrong_material_count = sum(
        1 for fact in window_fill_visual_truths if fact.material_name != WINDOW_FILL_MATERIAL_NAME
    )
    window_fill_non_blue_count = sum(
        1 for fact in window_fill_visual_truths if not _is_window_fill_blue(fact.diffuse_rgba)
    )
    window_fill_shader_non_blue_count = sum(
        1
        for fact in window_fill_visual_truths
        if fact.shader_rgb is None
        or not all(
            abs(float(fact.shader_rgb[index]) - float(WINDOW_FILL_EXPECTED_COLOR[index])) <= WINDOW_FILL_BLUE_TOLERANCE
            for index in range(3)
        )
    )
    window_fill_missing_uv_count = sum(1 for fact in window_fill_visual_truths if fact.uv_missing)
    shader_rgbs = [fact.shader_rgb for fact in window_fill_visual_truths if fact.shader_rgb is not None]
    window_fill_shader_rgb_min = (
        tuple(min(float(color[index]) for color in shader_rgbs) for index in range(3))
        if shader_rgbs
        else None
    )
    window_fill_shader_rgb_max = (
        tuple(max(float(color[index]) for color in shader_rgbs) for index in range(3))
        if shader_rgbs
        else None
    )
    window_fill_same_plane_v3_overlap_count = sum(
        len(fact.same_plane_overlap_cell_ids) for fact in window_fill_visual_truths
    )
    trim_attachment_facts = _collect_trim_attachment_facts(root_obj, mesh_children, tuple(cell_facts))
    opening_frame_mass_facts = _collect_opening_frame_mass_facts(
        root_obj,
        mesh_children,
        opening_by_object_name,
        tuple(cell_facts),
    )
    opening_visual_count = len(opening_visuals)
    opening_seating_source_count = sum(1 for fact in opening_visuals if fact.is_seating_source)
    cut_gap_values = [
        float(fact.max_gap_studs)
        for fact in opening_visuals
        if fact.max_gap_studs is not None
    ]
    cut_edge_boundary_max_delta_studs = max(cut_gap_values) if cut_gap_values else None
    actual_gap_values = [
        float(fact.actual_max_gap_studs)
        for fact in opening_visuals
        if fact.is_seating_source and fact.actual_max_gap_studs is not None
    ]
    max_actual_visual_gap_studs = max(actual_gap_values) if actual_gap_values else None
    actual_missing_boundary_sides_total = sum(
        len(fact.actual_missing_boundary_sides)
        for fact in opening_visuals
        if fact.is_seating_source
    )
    sub_min_residual_count = len(sub_min_residuals)
    trim_back_air_gap_max_studs = (
        max(float(fact.air_gap_studs) for fact in trim_attachment_facts) if trim_attachment_facts else None
    )
    trim_back_overlap_min_studs = (
        min(float(fact.overlap_studs) for fact in trim_attachment_facts) if trim_attachment_facts else None
    )
    floating_trim_object_count = sum(
        1
        for fact in trim_attachment_facts
        if fact.air_gap_studs > TRIM_BACK_AIR_GAP_MAX_STUDS + 1e-9
        or fact.overlap_studs + 1e-9 < TRIM_BACK_OVERLAP_MIN_STUDS
    )
    frame_silhouette_values = [
        float(fact.silhouette_thickness_studs if fact.silhouette_thickness_studs is not None else 0.0)
        for fact in opening_frame_mass_facts
    ]
    frame_ring_values = [
        float(fact.ring_width_studs if fact.ring_width_studs is not None else 0.0)
        for fact in opening_frame_mass_facts
    ]
    frame_return_values = [
        float(fact.inner_return_depth_studs if fact.inner_return_depth_studs is not None else 0.0)
        for fact in opening_frame_mass_facts
    ]
    frame_silhouette_thickness_min_studs = min(frame_silhouette_values) if frame_silhouette_values else None
    frame_ring_width_min_studs = min(frame_ring_values) if frame_ring_values else None
    frame_inner_return_depth_min_studs = min(frame_return_values) if frame_return_values else None
    frame_open_boundary_edge_count = sum(int(fact.open_boundary_edge_count) for fact in opening_frame_mass_facts)
    frame_outer_perimeter_face_count = (
        min(int(fact.outer_perimeter_face_count) for fact in opening_frame_mass_facts)
        if opening_frame_mass_facts
        else 0
    )
    frame_sill_or_head_mass_missing_count = sum(
        1 for fact in opening_frame_mass_facts if fact.sill_or_head_mass_missing
    )
    frame_gasket_air_gap_values = [
        float(fact.gasket_air_gap_studs)
        for fact in opening_frame_mass_facts
        if fact.gasket_air_gap_studs is not None
    ]
    frame_gasket_overlap_values = [
        float(fact.gasket_back_overlap_studs)
        for fact in opening_frame_mass_facts
        if fact.gasket_back_overlap_studs is not None
    ]
    frame_gasket_air_gap_max_studs = max(frame_gasket_air_gap_values) if frame_gasket_air_gap_values else None
    frame_gasket_back_overlap_min_studs = min(frame_gasket_overlap_values) if frame_gasket_overlap_values else None
    unstamped_opening_trim_object_count = sum(1 for fact in opening_frame_mass_facts if not fact.has_opening_stamp)
    window_cut_delta_values = [
        float(opening.cut_envelope_match_delta_studs)
        for opening in opening_visuals
        if opening.is_window_frame and opening.cut_envelope_match_delta_studs is not None
    ]
    door_frame_cut_delta_values = [
        float(opening.cut_envelope_match_delta_studs)
        for opening in opening_visuals
        if opening.is_door_frame and not opening.is_roof_exit and opening.cut_envelope_match_delta_studs is not None
    ]
    window_cut_envelope_match_max_delta_studs = max(window_cut_delta_values) if window_cut_delta_values else None
    door_frame_cut_envelope_match_max_delta_studs = max(door_frame_cut_delta_values) if door_frame_cut_delta_values else None
    authored_door_height = float(getattr(getattr(effective_spec, "door", None), "height", 0.0) or 0.0)
    ordinary_door_height_deltas: list[float] = []
    roof_exit_door_height_deltas: list[float] = []
    for child in mesh_children:
        if not bool(child.get("tbg_door_panel")) and not bool(child.get("tbg_is_door_leaf")):
            continue
        bounds = object_local_bounds(root_obj, child)
        panel_height = max(0.0, float(bounds[5]) - float(bounds[4]))
        if bool(child.get("tbg_roof_exit_door")):
            roof_room = getattr(_spatial_plan(effective_spec), "roof_room", None)
            expected_height = float(getattr(roof_room, "door_height", authored_door_height) or authored_door_height)
            if expected_height > 0.0:
                roof_exit_door_height_deltas.append(abs(panel_height - expected_height))
        elif child.name.endswith("Door_Main") or child.name.endswith("Door_Rear"):
            if authored_door_height > 0.0:
                ordinary_door_height_deltas.append(abs(panel_height - authored_door_height))
    ordinary_door_panel_height_delta_studs = (
        round(max(ordinary_door_height_deltas), 6) if ordinary_door_height_deltas else None
    )
    roof_exit_door_panel_height_delta_studs = (
        round(max(roof_exit_door_height_deltas), 6) if roof_exit_door_height_deltas else None
    )
    ordinary_door_frames_by_key = {
        (opening.side, opening.floor, opening.slot): opening
        for opening in opening_visuals
        if opening.kind == "door" and opening.is_door_frame and not opening.is_roof_exit
    }
    ordinary_door_unseated_count = 0
    for opening in opening_visuals:
        if opening.kind != "door" or opening.is_roof_exit or opening.is_door_frame:
            continue
        if not bool(opening.object_name.endswith("Door_Main") or opening.object_name.endswith("Door_Rear")):
            continue
        frame = ordinary_door_frames_by_key.get((opening.side, opening.floor, opening.slot))
        if frame is None or frame.cut_envelope_match_delta_studs is None:
            ordinary_door_unseated_count += 1
        elif frame.cut_envelope_match_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:
            ordinary_door_unseated_count += 1

    rear_reserved_spans = tuple(
        (float(opening.cut_run_min), float(opening.cut_run_max), opening.object_name)
        for opening in opening_visuals
        if opening.kind == "door"
        and opening.side == "back"
        and int(opening.floor) == 0
        and (opening.is_door_frame or opening.object_name.endswith("Door_Rear"))
    )
    rear_window_candidates = tuple(
        opening
        for opening in opening_visuals
        if opening.kind == "window"
        and opening.side == "back"
        and int(opening.floor) == 0
        and opening.is_window_frame
    )
    rear_door_reservation_facts: list[VoxelRearDoorReservationFacts] = []
    for span_left, span_right, door_name in rear_reserved_spans:
        for candidate in rear_window_candidates:
            overlap = round(
                _overlap_length(span_left, span_right, candidate.cut_run_min, candidate.cut_run_max),
                6,
            )
            if overlap <= CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:
                continue
            rear_door_reservation_facts.append(
                VoxelRearDoorReservationFacts(
                    object_name=door_name,
                    reserved_span=(round(span_left, 6), round(span_right, 6)),
                    candidate_object_name=candidate.object_name,
                    candidate_slot=int(candidate.slot),
                    candidate_span=(round(float(candidate.cut_run_min), 6), round(float(candidate.cut_run_max), 6)),
                    overlap_studs=overlap,
                    owner_class="rear_window_candidate_collision",
                )
            )
    rear_door_reserved_span_window_candidate_overlap_count = len(rear_door_reservation_facts)
    rear_door_window_clearance_overlap_count = rear_door_reserved_span_window_candidate_overlap_count
    rear_door_reserved_span_window_overlap_max_studs = (
        max(fact.overlap_studs for fact in rear_door_reservation_facts)
        if rear_door_reservation_facts
        else 0.0
    )

    roof_exit_doors = tuple(child for child in mesh_children if bool(child.get("tbg_roof_exit_door")))
    roof_exit_top_closure_facts: list[VoxelRoofExitTopClosureFacts] = []
    tagged_roof_exit_closures = tuple(
        child for child in mesh_children if bool(child.get("tbg_roof_exit_lintel_closure"))
    )
    valid_roof_exit_closures = tuple(
        child for child in tagged_roof_exit_closures if _is_valid_roof_exit_lintel_closure(child)
    )
    invalid_roof_exit_closures = tuple(
        child for child in tagged_roof_exit_closures if not _is_valid_roof_exit_lintel_closure(child)
    )
    roof_exit_lintel_closure_section_bucket_invalid_count = sum(
        1
        for child in tagged_roof_exit_closures
        if str(child.get("tbg_section_bucket", "") or "") != "Section_Walls_Roof"
    )
    roof_exit_lintel_closure_from_door_trim_count = sum(
        1
        for child in tagged_roof_exit_closures
        if bool(child.get("tbg_door_frame"))
        or bool(child.get("tbg_roof_exit_frame"))
        or bool(child.get("tbg_is_door_leaf"))
        or bool(child.get("tbg_door_panel"))
        or str(child.get("tbg_section_bucket", "") or "") == "Section_Doors_Trim"
    )
    for door in roof_exit_doors:
        run_z = _opening_run_z_bounds_for_child(root_obj, door)
        if run_z is None:
            continue
        actual_run_min, actual_run_max, actual_z_min, actual_z_max = run_z
        cut_run_min = _finite_float(door.get("tbg_wall_cut_run_min"))
        cut_run_max = _finite_float(door.get("tbg_wall_cut_run_max"))
        cut_z_min = _finite_float(door.get("tbg_wall_cut_z_min"))
        cut_z_max = _finite_float(door.get("tbg_wall_cut_z_max"))
        if cut_run_min is None or cut_run_max is None or cut_z_min is None or cut_z_max is None:
            continue
        if float(cut_z_max) - float(actual_z_max) <= CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:
            continue
        required_band = (
            float(cut_run_min),
            float(cut_run_max),
            float(actual_z_max),
            float(cut_z_max),
        )
        closure_bands: list[tuple[float, float, float, float]] = []
        closure_names: list[str] = []
        rejected_names: list[str] = [str(child.name) for child in invalid_roof_exit_closures]
        for closure in valid_roof_exit_closures:
            closure_run_z = _opening_run_z_bounds_for_child(root_obj, closure)
            if closure_run_z is None:
                bounds = object_local_bounds(root_obj, closure)
                closure_run_z = (float(bounds[0]), float(bounds[1]), float(bounds[4]), float(bounds[5]))
            coverage = _run_z_coverage_ratio(required_band, (closure_run_z,))
            if coverage <= 0.0:
                continue
            closure_bands.append(closure_run_z)
            closure_names.append(str(closure.name))
        coverage_ratio = _run_z_coverage_ratio(required_band, tuple(closure_bands))
        roof_exit_top_closure_facts.append(
            VoxelRoofExitTopClosureFacts(
                door_object_name=str(door.name),
                required_band=tuple(round(float(value), 6) for value in required_band),
                closure_object_names=tuple(sorted(closure_names)),
                rejected_object_names=tuple(sorted(set(rejected_names))),
                coverage_ratio=coverage_ratio,
                owner_class=(
                    "none"
                    if coverage_ratio >= ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
                    else "roof_exit_lintel_real_closure"
                ),
            )
        )
    roof_exit_lintel_required_count = len(roof_exit_top_closure_facts)
    roof_exit_lintel_closure_present_count = sum(
        1
        for fact in roof_exit_top_closure_facts
        if fact.coverage_ratio >= ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
    )
    roof_exit_lintel_closure_distinct_from_frame_count = roof_exit_lintel_closure_present_count
    roof_exit_lintel_closure_survives_finalsectionsink_count = len(valid_roof_exit_closures)
    roof_exit_top_band_coverage_ratio = (
        min(fact.coverage_ratio for fact in roof_exit_top_closure_facts)
        if roof_exit_top_closure_facts
        else None
    )
    roof_exit_uncovered_cut_top_gap_count = max(
        0,
        roof_exit_lintel_required_count - roof_exit_lintel_closure_present_count,
    )
    roof_exit_openings = tuple(opening for opening in opening_visuals if opening.is_roof_exit and opening.is_seating_source)
    roof_exit_side_gap_values = [
        float(edge.nearest_gap_studs)
        for opening in roof_exit_openings
        for edge in opening.nearest_final_cell_edges_by_side
        if edge.side in {"left", "right"} and edge.nearest_gap_studs is not None
    ]
    roof_exit_side_seal_gap_max_studs = max(roof_exit_side_gap_values) if roof_exit_side_gap_values else (None if not roof_exit_openings else 1_000_000.0)
    roof_exit_top_closure_gap_count = roof_exit_uncovered_cut_top_gap_count
    roof_exit_coverage_ratios: list[float] = []
    roof_exit_frame_objects = tuple(child for child in mesh_children if bool(child.get("tbg_roof_exit_frame")))
    roof_exit_frame_inner_deltas: list[float] = []
    roof_exit_frame_outer_deltas: list[float] = []
    roof_exit_frame_cut_height_ratios: list[float] = []
    roof_exit_frame_counts_as_lintel_count = sum(
        1
        for child in roof_exit_frame_objects
        if bool(child.get("tbg_roof_exit_lintel_closure"))
        or str(child.get("tbg_roof_exit_lintel_closure_kind", "") or "")
    )
    for frame in roof_exit_frame_objects:
        actual_inner_height, actual_outer_height = _frame_mesh_inner_outer_height(frame)
        expected_inner_height = _finite_float(frame.get("tbg_roof_exit_frame_expected_inner_height"))
        if expected_inner_height is None:
            expected_inner_height = _finite_float(frame.get("tbg_roof_exit_frame_authored_door_height"))
        expected_outer_height = _finite_float(frame.get("tbg_roof_exit_frame_expected_outer_height"))
        if expected_outer_height is None and expected_inner_height is not None:
            expected_outer_height = float(expected_inner_height) + FRAME_RING_WIDTH_MIN_STUDS * 2.0
        if actual_inner_height is not None and expected_inner_height is not None:
            roof_exit_frame_inner_deltas.append(abs(float(actual_inner_height) - float(expected_inner_height)))
        if actual_outer_height is not None and expected_outer_height is not None:
            roof_exit_frame_outer_deltas.append(abs(float(actual_outer_height) - float(expected_outer_height)))
            if expected_outer_height > 1e-6:
                roof_exit_frame_cut_height_ratios.append(float(actual_outer_height) / float(expected_outer_height))
    roof_exit_frame_inner_height_delta_studs = (
        round(max(roof_exit_frame_inner_deltas), 6) if roof_exit_frame_inner_deltas else None
    )
    roof_exit_frame_outer_height_delta_studs = (
        round(max(roof_exit_frame_outer_deltas), 6) if roof_exit_frame_outer_deltas else None
    )
    roof_exit_frame_height_delta_studs = roof_exit_frame_outer_height_delta_studs
    roof_exit_frame_cut_height_ratio_max = (
        round(max(roof_exit_frame_cut_height_ratios), 6) if roof_exit_frame_cut_height_ratios else None
    )
    for door in roof_exit_doors:
        run_z = _opening_run_z_bounds_for_child(root_obj, door)
        if run_z is None:
            continue
        actual_run_min, actual_run_max, actual_z_min, actual_z_max = run_z
        cut_run_min = _finite_float(door.get("tbg_wall_cut_run_min"))
        cut_run_max = _finite_float(door.get("tbg_wall_cut_run_max"))
        cut_z_min = _finite_float(door.get("tbg_wall_cut_z_min"))
        cut_z_max = _finite_float(door.get("tbg_wall_cut_z_max"))
        if cut_run_min is None or cut_run_max is None or cut_z_min is None or cut_z_max is None:
            continue
        full_cut = (float(cut_run_min), float(cut_run_max), float(cut_z_min), float(cut_z_max))
        door_band = (float(actual_run_min), float(actual_run_max), float(actual_z_min), float(actual_z_max))
        closure_bands = []
        for closure in (*valid_roof_exit_closures, *roof_exit_frame_objects):
            closure_run_z = _opening_run_z_bounds_for_child(root_obj, closure)
            if closure_run_z is None:
                bounds = object_local_bounds(root_obj, closure)
                closure_run_z = (float(bounds[0]), float(bounds[1]), float(bounds[4]), float(bounds[5]))
            closure_bands.append(closure_run_z)
        roof_exit_coverage_ratios.append(_run_z_coverage_ratio(full_cut, (door_band, *tuple(closure_bands))))
    roof_exit_cut_covered_area_ratio = min(roof_exit_coverage_ratios) if roof_exit_coverage_ratios else None
    roof_exit_top_wall_lintel_coverage_ratio = roof_exit_top_band_coverage_ratio

    terrace_exit_top_facts: list[VoxelTerraceExitTopFacts] = []
    terrace_owner_objects = tuple(
        child
        for child in mesh_children
        if bool(child.get("tbg_terrace_exit")) and not bool(child.get("tbg_runtime_marker"))
    )
    terrace_keys = sorted(
        {
            (
                str(child.get("tbg_wall_opening_side", "") or child.get("tbg_facade_side", "") or ""),
                int(child.get("tbg_wall_opening_floor", child.get("tbg_facade_floor", -1)) or -1),
                int(child.get("tbg_wall_opening_slot", child.get("tbg_facade_slot", -1)) or -1),
            )
            for child in terrace_owner_objects
        }
    )
    for side, floor, slot in terrace_keys:
        owners = tuple(
            child
            for child in terrace_owner_objects
            if str(child.get("tbg_wall_opening_side", "") or child.get("tbg_facade_side", "") or "") == side
            and int(child.get("tbg_wall_opening_floor", child.get("tbg_facade_floor", -1)) or -1) == floor
            and int(child.get("tbg_wall_opening_slot", child.get("tbg_facade_slot", -1)) or -1) == slot
        )
        owner_classes = tuple(
            sorted({str(child.get("tbg_terrace_top_owner_class", "") or "") for child in owners})
        )
        valid_owner_classes = tuple(owner_class for owner_class in owner_classes if owner_class in VALID_TERRACE_TOP_OWNER_CLASSES)
        primary_owner = valid_owner_classes[0] if valid_owner_classes else (owner_classes[0] if owner_classes else "")
        cut_bounds = None
        top_band_bounds = None
        floor_z: float | None = None
        clear_passage_heights: list[float] = []
        clear_passage_widths: list[float] = []
        authored_opening_widths: list[float] = []
        threshold_obstructions: list[float] = []
        floor_penetrations: list[float] = []
        for child in owners:
            cut_run_min = _finite_float(child.get("tbg_wall_cut_run_min"))
            cut_run_max = _finite_float(child.get("tbg_wall_cut_run_max"))
            cut_z_min = _finite_float(child.get("tbg_wall_cut_z_min"))
            cut_z_max = _finite_float(child.get("tbg_wall_cut_z_max"))
            if cut_run_min is not None and cut_run_max is not None and cut_z_min is not None and cut_z_max is not None:
                cut_bounds = (float(cut_run_min), float(cut_run_max), float(cut_z_min), float(cut_z_max))
            top_run_min = _finite_float(child.get("tbg_terrace_top_band_run_min"))
            top_run_max = _finite_float(child.get("tbg_terrace_top_band_run_max"))
            top_z_min = _finite_float(child.get("tbg_terrace_top_band_z_min"))
            top_z_max = _finite_float(child.get("tbg_terrace_top_band_z_max"))
            if top_run_min is not None and top_run_max is not None and top_z_min is not None and top_z_max is not None:
                top_band_bounds = (float(top_run_min), float(top_run_max), float(top_z_min), float(top_z_max))
            child_floor_z = _finite_float(child.get("tbg_terrace_floor_z"))
            if child_floor_z is not None:
                floor_z = float(child_floor_z)
            clear_height = _finite_float(child.get("tbg_terrace_clear_passage_height"))
            clear_width = _finite_float(child.get("tbg_terrace_clear_passage_width"))
            if clear_height is not None:
                clear_passage_heights.append(float(clear_height))
            if clear_width is not None:
                clear_passage_widths.append(float(clear_width))
            opening_width = _finite_float(child.get("tbg_window_opening_width"))
            if opening_width is not None:
                authored_opening_widths.append(float(opening_width))
            threshold_height = _finite_float(child.get("tbg_terrace_threshold_obstruction_height"))
            if threshold_height is not None:
                threshold_obstructions.append(max(0.0, float(threshold_height)))
        if floor_z is None and cut_bounds is not None:
            floor_z = float(cut_bounds[2])
        owner_bands: list[tuple[float, float, float, float]] = []
        for child in owners:
            run_z = _opening_run_z_bounds_for_child(root_obj, child)
            if run_z is None:
                continue
            owner_bands.append(run_z)
            if floor_z is not None:
                floor_penetrations.append(max(0.0, float(floor_z) - float(run_z[2])))
        coverage_band = top_band_bounds if top_band_bounds is not None else cut_bounds
        coverage_ratio = _run_z_coverage_ratio(coverage_band, tuple(owner_bands)) if coverage_band else 0.0
        floor_penetration = round(max(floor_penetrations), 6) if floor_penetrations else 0.0
        threshold_obstruction = round(max(threshold_obstructions), 6) if threshold_obstructions else 0.0
        clear_passage_height = round(min(clear_passage_heights), 6) if clear_passage_heights else None
        clear_passage_width = round(min(clear_passage_widths), 6) if clear_passage_widths else None
        authored_opening_width = round(min(authored_opening_widths), 6) if authored_opening_widths else None
        terrace_exit_top_facts.append(
            VoxelTerraceExitTopFacts(
                object_name=",".join(sorted(str(child.name) for child in owners)),
                side=side,
                floor=int(floor),
                slot=int(slot),
                owner_class=primary_owner,
                owner_valid=bool(valid_owner_classes),
                coverage_ratio=coverage_ratio,
                allowed_frame_inflation=bool(primary_owner == TERRACE_TOP_OWNER_TRANSOM_FRAME),
                floor_penetration_studs=floor_penetration,
                threshold_obstruction_height_studs=threshold_obstruction,
                clear_passage_height_studs=clear_passage_height,
                clear_passage_width_studs=clear_passage_width,
                authored_opening_width_studs=authored_opening_width,
            )
        )
    terrace_exit_unclassified_top_coverage_count = sum(1 for fact in terrace_exit_top_facts if not fact.owner_valid)
    terrace_exit_owner_class_invalid_count = terrace_exit_unclassified_top_coverage_count
    terrace_exit_top_band_coverage_ratio = (
        min(fact.coverage_ratio for fact in terrace_exit_top_facts) if terrace_exit_top_facts else None
    )
    terrace_exit_top_transom_coverage_ratio = terrace_exit_top_band_coverage_ratio
    terrace_exit_frame_floor_penetration_max_studs = (
        max(fact.floor_penetration_studs for fact in terrace_exit_top_facts)
        if terrace_exit_top_facts
        else None
    )
    terrace_exit_frame_floor_penetration_count = sum(
        1 for fact in terrace_exit_top_facts if fact.floor_penetration_studs > TRIM_BACK_AIR_GAP_MAX_STUDS
    )
    terrace_exit_threshold_obstruction_height_max_studs = (
        max(fact.threshold_obstruction_height_studs for fact in terrace_exit_top_facts)
        if terrace_exit_top_facts
        else None
    )
    terrace_exit_clear_passage_height_min_studs = (
        min(
            fact.clear_passage_height_studs
            for fact in terrace_exit_top_facts
            if fact.clear_passage_height_studs is not None
        )
        if any(fact.clear_passage_height_studs is not None for fact in terrace_exit_top_facts)
        else None
    )
    terrace_exit_clear_passage_width_min_studs = (
        min(
            fact.clear_passage_width_studs
            for fact in terrace_exit_top_facts
            if fact.clear_passage_width_studs is not None
        )
        if any(fact.clear_passage_width_studs is not None for fact in terrace_exit_top_facts)
        else None
    )
    terrace_exit_traversal_blocker_count = 0
    for fact in terrace_exit_top_facts:
        min_expected_width = (
            float(fact.authored_opening_width_studs) - 0.02
            if fact.authored_opening_width_studs is not None
            else None
        )
        if fact.floor_penetration_studs > TRIM_BACK_AIR_GAP_MAX_STUDS:
            terrace_exit_traversal_blocker_count += 1
        elif fact.threshold_obstruction_height_studs > 0.02:
            terrace_exit_traversal_blocker_count += 1
        elif fact.clear_passage_height_studs is not None and fact.clear_passage_height_studs < 1.90:
            terrace_exit_traversal_blocker_count += 1
        elif (
            fact.clear_passage_width_studs is not None
            and min_expected_width is not None
            and fact.clear_passage_width_studs + 1e-9 < min_expected_width
        ):
            terrace_exit_traversal_blocker_count += 1
    terrace_exit_allowed_frame_inflation = all(
        fact.owner_class != TERRACE_TOP_OWNER_TRANSOM_FRAME or fact.allowed_frame_inflation
        for fact in terrace_exit_top_facts
    )
    opening_visual_seal_gap_max_studs = max_actual_visual_gap_studs
    trim_segment_back_air_gap_max_studs = trim_back_air_gap_max_studs
    trim_segment_back_overlap_min_studs = trim_back_overlap_min_studs
    parapet_cap_gap_values = [
        float(fact.air_gap_studs)
        for fact in trim_attachment_facts
        if any(child.name == fact.object_name and bool(child.get("tbg_parapet_cap")) for child in mesh_children)
    ]
    parapet_cap_segment_back_air_gap_max_studs = max(parapet_cap_gap_values) if parapet_cap_gap_values else None
    preset_id = str(getattr(effective_spec, "preset_id", "") or "").lower()
    roof_mode = normalized_roof_mode(str(getattr(effective_spec, "roof_mode", "") or ""))
    townhouse_like_parapet_height_min_studs = (
        round(float(getattr(effective_spec, "parapet_height", 0.0) or 0.0), 6)
        if preset_id in {"townhouse", "apartment_lowrise", "apartment_midrise"} and roof_mode in {"FLAT", "TERRACE"}
        else None
    )
    missing_cut_or_stamp_count = (
        len(opening_stamp_issues)
        + len(deferred_unstamped_openings)
        + sum(
            1
            for fact in opening_visuals
            if not fact.is_terrace_exit and (not fact.matching_group_id or not fact.matching_cut_label)
        )
    )
    sealed_backfilled_opening_count = sum(
        1
        for fact in opening_visuals
        if fact.cut_intrusion_cell_ids or fact.cross_plane_leakage_cell_ids
    )
    same_plane_opening_cell_overlap_count = sum(
        len(fact.same_plane_overlap_cell_ids) for fact in opening_visuals
    )

    texture_contract_key_present_count = sum(1 for cell in cell_facts if bool(cell.texture_key))
    texture_projection_valid_count = sum(1 for cell in cell_facts if cell.texture_projection in export_contract.TEXTURE_PROJECTIONS)
    texture_image_period_contract_valid_count = sum(
        1 for cell in cell_facts if cell.texture_image_period_contract in export_contract.TEXTURE_IMAGE_PERIOD_CONTRACTS
    )
    texture_face_axis_table_valid_count = sum(
        1 for cell in cell_facts if cell.texture_face_axis_table_version == export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1
    )
    texture_studs_per_tile_valid_count = sum(
        1
        for cell in cell_facts
        if cell.studs_per_tile_u is not None
        and cell.studs_per_tile_v is not None
        and float(cell.studs_per_tile_u) > 0.0
        and float(cell.studs_per_tile_v) > 0.0
    )
    cells_with_surface_uv_origin_count = sum(
        1 for cell in cell_facts if cell.surface_u_origin_studs is not None and cell.surface_v_origin_studs is not None
    )
    texture_tile_scale_deltas = [
        max(
            abs(float(cell.studs_per_tile_u or 0.0) - _expected_texture_period(cell.material_family, cell.visual_style)),
            abs(float(cell.studs_per_tile_v or 0.0) - _expected_texture_period(cell.material_family, cell.visual_style)),
        )
        for cell in cell_facts
        if cell.studs_per_tile_u is not None and cell.studs_per_tile_v is not None
    ]
    texture_tile_scale_max_delta_studs = max(texture_tile_scale_deltas) if texture_tile_scale_deltas else 0.0
    cell_surface_uv_phase_consistency_max_delta_studs = 0.0 if cells_with_surface_uv_origin_count == len(cell_facts) else 1_000_000.0
    visible_texture_contract_cell_count = sum(
        fact.texture_contract_cell_count or 0 for fact in visible_wall_object_facts
    )
    v3_visible_root_local_uv_object_count = sum(
        1
        for fact in visible_wall_object_facts
        for child in mesh_children
        if child.name == fact.object_name and str(child.get("tbg_brick_uv_space", "")) == "ROOT_LOCAL"
    )
    payload_texture_keys = tuple(sorted({cell.texture_key for cell in cell_facts if cell.texture_key}))
    visible_texture_keys = tuple(sorted({key for fact in visible_wall_object_facts for key in fact.texture_key_set}))
    texture_preview_payload_parity = (
        visible_texture_contract_cell_count == len(cell_facts)
        and sum(fact.composite_cell_count for fact in visible_wall_object_facts) == len(cell_facts)
        and visible_texture_keys == payload_texture_keys
    )
    color_modulation_policy_invalid_count = sum(
        1 for cell in cell_facts if cell.color_modulation_policy != export_contract.COLOR_MODULATION_POLICY_NONE
    )
    projection_classification_drift_count = sum(
        1
        for cell in cell_facts
        if cell.texture_projection != _expected_texture_projection(cell.material_family, cell.visual_style)
    )
    non_axis_aligned_plane_count = sum(
        1
        for group in group_facts
        if group.normal_axis not in {"x", "y"}
        or group.run_axis not in {"x", "y"}
        or group.run_axis == group.normal_axis
    )
    composite_box_face_order_probe_match = export_contract.COMPOSITE_BOX_FACE_ORDER_V1 == ("-z", "+z", "-y", "+x", "+y", "-x")
    texture_face_uv_implementation_invalid_count = 0
    for fact in visible_wall_object_facts:
        if not fact.texture_contract_cell_count:
            continue
        expected_uv_source = (
            "payload_roblox_part_texture_v1"
            if fact.texture_projection == export_contract.TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1
            else "payload_material_variant_style_v1"
        )
        if (
            fact.texture_uv_source != expected_uv_source
            or fact.texture_image_period_contract not in export_contract.TEXTURE_IMAGE_PERIOD_CONTRACTS
            or fact.texture_face_axis_table_version != export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1
        ):
            texture_face_uv_implementation_invalid_count += 1
    v3_material_style_preview_mismatch_count = sum(
        1
        for fact in visible_wall_object_facts
        if fact.texture_projection
        in {
            export_contract.TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1,
            export_contract.TEXTURE_PROJECTION_SOLID_COLOR_V1,
        }
        and (
            not fact.material_is_roblox_basepart_sim_preview
            or (
                any("brick" in key.lower() for key in fact.texture_key_set)
                and fact.material_roblox_basepart_sim_pattern != "BRICK_MASONRY"
            )
        )
    )

    return VoxelWallFacts(
        payload=dict(occupancy_payload),
        groups=tuple(group_facts),
        cells=tuple(cell_facts),
        visible_wall_objects=tuple(visible_wall_object_facts),
        malformed_entries=tuple(sorted(malformed_entries)),
        duplicate_group_ids=duplicate_group_ids,
        duplicate_cell_ids=duplicate_cell_ids,
        duplicate_cell_bounds=duplicate_cell_bounds,
        overlapping_cells=tuple(overlapping_cells),
        horizontal_cell_ids=tuple(sorted(horizontal_cell_ids)),
        micro_span_cell_ids=tuple(sorted(set(micro_span_cell_ids))),
        adapter_group_ids=adapter_group_ids,
        plane_area_coverages=tuple(plane_area_coverages),
        opening_cut_intrusions=tuple(opening_cut_intrusions),
        top_profile_protrusions=tuple(top_profile_protrusions),
        sub_min_residuals=tuple(sub_min_residuals),
        opening_visuals=tuple(opening_visuals),
        trim_attachment_facts=tuple(trim_attachment_facts),
        opening_frame_mass_facts=tuple(opening_frame_mass_facts),
        rear_door_reservation_facts=tuple(rear_door_reservation_facts),
        roof_exit_top_closure_facts=tuple(roof_exit_top_closure_facts),
        terrace_exit_top_facts=tuple(terrace_exit_top_facts),
        opening_stamp_issues=tuple(opening_stamp_issues),
        deferred_unstamped_openings=tuple(deferred_unstamped_openings),
        preview_cache_cell_count=preview_cache_cell_count,
        preview_cache_object_names=preview_cache_object_names,
        real_visible_cell_count=real_visible_cell_count,
        visible_scalar_cell_count=visible_scalar_cell_count,
        runtime_render_wall_object_names=runtime_render_wall_object_names,
        opening_visual_count=opening_visual_count,
        opening_seating_source_count=opening_seating_source_count,
        cut_edge_boundary_max_delta_studs=cut_edge_boundary_max_delta_studs,
        max_actual_visual_gap_studs=max_actual_visual_gap_studs,
        actual_missing_boundary_sides_total=actual_missing_boundary_sides_total,
        sub_min_residual_count=sub_min_residual_count,
        trim_back_air_gap_max_studs=trim_back_air_gap_max_studs,
        trim_back_overlap_min_studs=trim_back_overlap_min_studs,
        floating_trim_object_count=floating_trim_object_count,
        frame_silhouette_thickness_min_studs=frame_silhouette_thickness_min_studs,
        frame_ring_width_min_studs=frame_ring_width_min_studs,
        frame_inner_return_depth_min_studs=frame_inner_return_depth_min_studs,
        frame_open_boundary_edge_count=frame_open_boundary_edge_count,
        frame_outer_perimeter_face_count=frame_outer_perimeter_face_count,
        frame_sill_or_head_mass_missing_count=frame_sill_or_head_mass_missing_count,
        frame_gasket_back_overlap_min_studs=frame_gasket_back_overlap_min_studs,
        frame_gasket_air_gap_max_studs=frame_gasket_air_gap_max_studs,
        unstamped_opening_trim_object_count=unstamped_opening_trim_object_count,
        window_cut_envelope_match_max_delta_studs=window_cut_envelope_match_max_delta_studs,
        door_frame_cut_envelope_match_max_delta_studs=door_frame_cut_envelope_match_max_delta_studs,
        ordinary_door_panel_height_delta_studs=ordinary_door_panel_height_delta_studs,
        roof_exit_door_panel_height_delta_studs=roof_exit_door_panel_height_delta_studs,
        roof_exit_lintel_closure_present_count=roof_exit_lintel_closure_present_count,
        roof_exit_lintel_required_count=roof_exit_lintel_required_count,
        roof_exit_lintel_closure_distinct_from_frame_count=roof_exit_lintel_closure_distinct_from_frame_count,
        roof_exit_lintel_closure_section_bucket_invalid_count=roof_exit_lintel_closure_section_bucket_invalid_count,
        roof_exit_lintel_closure_from_door_trim_count=roof_exit_lintel_closure_from_door_trim_count,
        roof_exit_lintel_closure_survives_finalsectionsink_count=roof_exit_lintel_closure_survives_finalsectionsink_count,
        roof_exit_top_band_coverage_ratio=roof_exit_top_band_coverage_ratio,
        roof_exit_frame_inner_height_delta_studs=roof_exit_frame_inner_height_delta_studs,
        roof_exit_frame_outer_height_delta_studs=roof_exit_frame_outer_height_delta_studs,
        roof_exit_frame_height_delta_studs=roof_exit_frame_height_delta_studs,
        roof_exit_frame_cut_height_ratio_max=roof_exit_frame_cut_height_ratio_max,
        roof_exit_frame_counts_as_lintel_count=roof_exit_frame_counts_as_lintel_count,
        roof_exit_top_wall_lintel_coverage_ratio=roof_exit_top_wall_lintel_coverage_ratio,
        rear_door_window_clearance_overlap_count=rear_door_window_clearance_overlap_count,
        rear_door_reserved_span_window_candidate_overlap_count=rear_door_reserved_span_window_candidate_overlap_count,
        rear_door_reserved_span_window_overlap_max_studs=rear_door_reserved_span_window_overlap_max_studs,
        terrace_exit_unclassified_top_coverage_count=terrace_exit_unclassified_top_coverage_count,
        terrace_exit_top_band_coverage_ratio=terrace_exit_top_band_coverage_ratio,
        terrace_exit_owner_class_invalid_count=terrace_exit_owner_class_invalid_count,
        terrace_exit_allowed_frame_inflation=terrace_exit_allowed_frame_inflation,
        terrace_exit_frame_floor_penetration_count=terrace_exit_frame_floor_penetration_count,
        terrace_exit_frame_floor_penetration_max_studs=terrace_exit_frame_floor_penetration_max_studs,
        terrace_exit_threshold_obstruction_height_max_studs=terrace_exit_threshold_obstruction_height_max_studs,
        terrace_exit_traversal_blocker_count=terrace_exit_traversal_blocker_count,
        terrace_exit_clear_passage_height_min_studs=terrace_exit_clear_passage_height_min_studs,
        terrace_exit_clear_passage_width_min_studs=terrace_exit_clear_passage_width_min_studs,
        terrace_exit_top_transom_coverage_ratio=terrace_exit_top_transom_coverage_ratio,
        ordinary_door_unseated_count=ordinary_door_unseated_count,
        roof_exit_uncovered_cut_top_gap_count=roof_exit_uncovered_cut_top_gap_count,
        opening_visual_seal_gap_max_studs=opening_visual_seal_gap_max_studs,
        roof_exit_side_seal_gap_max_studs=roof_exit_side_seal_gap_max_studs,
        roof_exit_top_closure_gap_count=roof_exit_top_closure_gap_count,
        roof_exit_cut_covered_area_ratio=roof_exit_cut_covered_area_ratio,
        trim_segment_back_air_gap_max_studs=trim_segment_back_air_gap_max_studs,
        trim_segment_back_overlap_min_studs=trim_segment_back_overlap_min_studs,
        parapet_cap_segment_back_air_gap_max_studs=parapet_cap_segment_back_air_gap_max_studs,
        townhouse_like_parapet_height_min_studs=townhouse_like_parapet_height_min_studs,
        missing_cut_or_stamp_count=missing_cut_or_stamp_count,
        sealed_backfilled_opening_count=sealed_backfilled_opening_count,
        same_plane_opening_cell_overlap_count=same_plane_opening_cell_overlap_count,
        total_authored_cell_count=len(cell_facts),
        stale_authored_evidence=tuple(sorted(stale_authored_evidence)),
        legacy_helper_evidence=tuple(sorted(legacy_helper_evidence)),
        texture_contract_key_present_count=texture_contract_key_present_count,
        texture_projection_valid_count=texture_projection_valid_count,
        texture_image_period_contract_valid_count=texture_image_period_contract_valid_count,
        texture_face_axis_table_valid_count=texture_face_axis_table_valid_count,
        texture_studs_per_tile_valid_count=texture_studs_per_tile_valid_count,
        cells_with_surface_uv_origin_count=cells_with_surface_uv_origin_count,
        cell_surface_uv_phase_consistency_max_delta_studs=cell_surface_uv_phase_consistency_max_delta_studs,
        texture_tile_scale_max_delta_studs=texture_tile_scale_max_delta_studs,
        visible_texture_contract_cell_count=visible_texture_contract_cell_count,
        v3_visible_root_local_uv_object_count=v3_visible_root_local_uv_object_count,
        texture_preview_payload_parity=texture_preview_payload_parity,
        color_modulation_policy_invalid_count=color_modulation_policy_invalid_count,
        projection_classification_drift_count=projection_classification_drift_count,
        non_axis_aligned_plane_count=non_axis_aligned_plane_count,
        composite_box_face_order_probe_match=composite_box_face_order_probe_match,
        texture_face_uv_implementation_invalid_count=texture_face_uv_implementation_invalid_count,
        v3_material_style_preview_mismatch_count=v3_material_style_preview_mismatch_count,
        opening_bounds_off_grid_count=opening_bounds_off_grid_count,
        brick_opening_adjacent_non_grid_cell_count=len(brick_opening_adjacent_non_grid_cell_ids),
        window_fill_visual_truths=tuple(window_fill_visual_truths),
        window_fill_wrong_material_count=window_fill_wrong_material_count,
        window_fill_non_blue_count=window_fill_non_blue_count,
        window_fill_shader_non_blue_count=window_fill_shader_non_blue_count,
        window_fill_missing_uv_count=window_fill_missing_uv_count,
        window_fill_shader_rgb_min=window_fill_shader_rgb_min,
        window_fill_shader_rgb_max=window_fill_shader_rgb_max,
        window_fill_same_plane_v3_overlap_count=window_fill_same_plane_v3_overlap_count,
    )


def _combined_bounds(root_obj, children) -> tuple[float, float, float, float, float, float] | None:
    items = []
    for child in children:
        stored_bounds = child.get("tbg_roof_exit_shell_bounds")
        if stored_bounds is None:
            stored_bounds = child.get("tbg_top_room_floor_bounds")
        bounds_tuple = None
        if stored_bounds is not None:
            try:
                if len(stored_bounds) == 6:
                    bounds_tuple = tuple(float(stored_bounds[index]) for index in range(6))
            except (TypeError, ValueError, IndexError, KeyError):
                bounds_tuple = None
        if bounds_tuple is not None:
            items.append(bounds_tuple)
            continue
        items.append(object_local_bounds(root_obj, child))
    if not items:
        return None
    return (
        min(item[0] for item in items),
        max(item[1] for item in items),
        min(item[2] for item in items),
        max(item[3] for item in items),
        min(item[4] for item in items),
        max(item[5] for item in items),
    )


def _rear_entry_authored_span(
    root_obj,
    mesh_children: tuple[bpy.types.Object, ...],
) -> tuple[float, float] | None:
    spans: list[tuple[float, float]] = []
    for child in mesh_children:
        if not child.get("tbg_door_frame"):
            continue
        if not (child.get("tbg_rear_through_access") or str(child.get("tbg_facade_side", "")) == "back"):
            continue
        left_raw = child.get("tbg_door_frame_left")
        right_raw = child.get("tbg_door_frame_right")
        if left_raw is not None and right_raw is not None:
            try:
                span_left = float(left_raw)
                span_right = float(right_raw)
            except (TypeError, ValueError):
                span_left = float(object_local_bounds(root_obj, child)[0])
                span_right = float(object_local_bounds(root_obj, child)[1])
        else:
            span_left = float(object_local_bounds(root_obj, child)[0])
            span_right = float(object_local_bounds(root_obj, child)[1])
        if span_right - span_left > 1e-4:
            spans.append((span_left, span_right))
    if not spans:
        return None
    return (
        min(span_left for span_left, _span_right in spans),
        max(span_right for _span_left, span_right in spans),
    )


def _office_authored_partition_centers_x(
    root_obj,
    collision_markers: tuple[bpy.types.Object, ...],
) -> tuple[float, ...]:
    centers: set[float] = set()
    for marker in collision_markers:
        if str(marker.get("tbg_runtime_role", "")) != export_contract.ROLE_PARTITION:
            continue
        source_name = str(marker.get("tbg_runtime_source_name", ""))
        if "RoomPartition_" not in source_name:
            continue
        bounds = object_local_bounds(root_obj, marker)
        centers.add(round((float(bounds[0]) + float(bounds[1])) / 2, 4))
    return tuple(sorted(centers))


def _expected_open_window_vertical_profile(
    spec,
    slot_summary,
) -> tuple[float, float]:
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    slot_side = str(slot_summary.side)
    slot_floor = int(slot_summary.floor)
    if preset_id in {"warehouse", "depot"} and slot_side == "back" and slot_floor == 0:
        floor_height = float(spec.floor_height)
        if preset_id == "depot":
            sill_h = max(0.14, min(0.3, floor_height * 0.09))
            opening_h = min(
                max(0.9, floor_height - sill_h - 0.1),
                max(1.24, floor_height * 0.46),
            )
        else:
            sill_h = max(0.12, min(0.24, floor_height * 0.08))
            opening_h = min(
                max(0.9, floor_height - sill_h - 0.1),
                max(1.38, floor_height * 0.5),
            )
        return (float(sill_h), float(opening_h))
    _opening_width, sill_h, opening_h, _top_h = _slot_opening_profile(
        spec,
        str(slot_summary.state),
        max(0.1, float(slot_summary.opening_width)),
        float(spec.floor_height),
        side_key=str(slot_summary.side),
        floor_index=int(slot_summary.floor),
        slot_index=int(slot_summary.slot),
    )
    return (float(sill_h), float(opening_h))


def _contract_marker_issues(contract_markers) -> list[str]:
    if not contract_markers:
        return [
            "Sidecar contract failure: missing author-time version handshake marker for export contract "
            f"{export_contract.EXPORT_CONTRACT_VERSION}. Regenerate before writing the FBX + RBXMX handoff."
        ]

    versions = {
        export_contract.parse_export_contract_marker_name(marker.name)
        for marker in contract_markers
    }
    versions.discard(None)
    if len(versions) != 1:
        return [
            "Sidecar contract failure: version handshake markers disagree on export contract version: "
            + ", ".join(sorted(versions) or ["<missing>"])
            + "."
        ]
    version = next(iter(versions))
    if version != export_contract.EXPORT_CONTRACT_VERSION:
        return [
            "Sidecar contract failure: authored marker contract version is "
            f"{version}, expected {export_contract.EXPORT_CONTRACT_VERSION}. "
            "Regenerate before writing the FBX + RBXMX handoff."
        ]
    return []


def _summary_contract_issues(root_obj, summary: GenerationSummaryFacts) -> list[str]:
    issues: list[str] = []

    if summary.summary_schema_version != constants.SUMMARY_SCHEMA_VERSION:
        issues.append(
            "Stored generation summary schema mismatch: found "
            f"{_version_label(summary.summary_schema_version)}, expected {constants.SUMMARY_SCHEMA_VERSION}. "
            "Regenerate with the current addon."
        )

    if summary.export_contract_version != export_contract.EXPORT_CONTRACT_VERSION:
        issues.append(
            "Sidecar contract failure: stored generation summary targets export contract "
            f"{_version_label(summary.export_contract_version)}, expected {export_contract.EXPORT_CONTRACT_VERSION}. "
            "Regenerate before writing the FBX + RBXMX handoff."
        )

    root_summary_schema_version = metadata.read_summary_schema_version(root_obj)
    if root_summary_schema_version != constants.SUMMARY_SCHEMA_VERSION:
        issues.append(
            "Root metadata summary schema mismatch: found "
            f"{_version_label(root_summary_schema_version)}, expected {constants.SUMMARY_SCHEMA_VERSION}. "
            "Regenerate with the current addon."
        )

    root_contract_version = metadata.read_export_contract_version(root_obj)
    if root_contract_version != export_contract.EXPORT_CONTRACT_VERSION:
        issues.append(
            "Sidecar contract failure: root metadata targets export contract "
            f"{_version_label(root_contract_version)}, expected {export_contract.EXPORT_CONTRACT_VERSION}. "
            "Regenerate before writing the FBX + RBXMX handoff."
        )

    return issues


def _runtime_collision_maps(runtime_markers):
    collision_markers = [
        child
        for child in runtime_markers
        if str(child.get("tbg_runtime_kind", "")) == export_contract.RUNTIME_KIND_COLLISION
    ]
    light_markers = [
        child
        for child in runtime_markers
        if str(child.get("tbg_runtime_kind", "")) == export_contract.RUNTIME_KIND_LIGHT
    ]
    role_counts: dict[str, int] = {}
    role_shapes: dict[str, set[str]] = {}
    slot_roles: dict[tuple[str, int, int], set[str]] = {}
    span_roles: dict[str, dict[str, int]] = {}
    floor_roles: dict[tuple[str, int], int] = {}
    wedge_markers: list[bpy.types.Object] = []
    stair_directions: set[float] = set()

    for marker in collision_markers:
        role = str(marker.get("tbg_runtime_role", ""))
        shape = str(marker.get("tbg_runtime_shape", ""))
        role_counts[role] = role_counts.get(role, 0) + 1
        role_shapes.setdefault(role, set()).add(shape)

        side = str(marker.get("tbg_runtime_side", ""))
        floor = int(marker.get("tbg_runtime_floor", -1))
        slot = int(marker.get("tbg_runtime_slot", -1))
        if side and floor >= 0 and slot >= 0:
            slot_roles.setdefault((side, floor, slot), set()).add(role)
        if floor >= 0:
            floor_roles[(role, floor)] = floor_roles.get((role, floor), 0) + 1

        span_key = str(marker.get("tbg_runtime_span_key", ""))
        if span_key:
            role_map = span_roles.setdefault(span_key, {})
            role_map[role] = role_map.get(role, 0) + 1

        if role in {export_contract.ROLE_STAIR_STEP, export_contract.ROLE_STAIR_WEDGE}:
            stair_directions.add(float(marker.get("tbg_runtime_direction", 0.0)))
        if shape == export_contract.RUNTIME_SHAPE_WEDGE:
            wedge_markers.append(marker)

    return RuntimeMarkerFacts(
        collision_markers=tuple(collision_markers),
        light_markers=tuple(light_markers),
        role_counts=role_counts,
        role_shapes={role: frozenset(shapes) for role, shapes in role_shapes.items()},
        slot_roles={key: frozenset(roles) for key, roles in slot_roles.items()},
        span_roles={key: dict(value) for key, value in span_roles.items()},
        floor_roles=floor_roles,
        wedge_markers=tuple(wedge_markers),
        stair_directions=frozenset(stair_directions),
    )


def _load_validation_state(root_obj) -> LoadedValidationState | list[str]:
    issues: list[str] = []
    try:
        spec = metadata.read_spec_dict(root_obj, strict=True)
    except metadata.MetadataContractError as exc:
        return [f"{exc} Regenerate before export or validation."]
    try:
        effective_spec = stored_building_spec_from_mapping(spec, building_id=None, origin=(0.0, 0.0, 0.0))
    except SpecContractError as exc:
        return [f"Stored spec is corrupt: {exc} Regenerate before export or validation."]
    try:
        summary_payload = metadata.read_generation_summary(root_obj, strict=True)
    except metadata.MetadataContractError as exc:
        return [f"{exc} Regenerate before export or validation."]
    try:
        summary = parse_generation_summary(summary_payload)
    except GenerationSummaryContractError as exc:
        return [f"Stored generation summary is corrupt: {exc} Regenerate before export or validation."]
    try:
        final_section_registry = metadata.read_final_section_registry(root_obj, strict=True)
    except metadata.MetadataContractError as exc:
        return [f"{exc} Regenerate before export or validation."]
    try:
        voxel_wall_payload = metadata.read_voxel_wall_occupancy_payload(root_obj, strict=True)
    except metadata.MetadataContractError as exc:
        return [f"{exc} Regenerate before export or validation."]

    expected_root_scale = float(effective_spec.world_scale)
    if any(abs(v - expected_root_scale) > 1e-6 for v in root_obj.scale):
        issues.append(
            f"Root empty scale drifted away from stored world scale {expected_root_scale:.3f}: "
            f"{root_obj.scale[0]:.3f}, {root_obj.scale[1]:.3f}, {root_obj.scale[2]:.3f}."
        )
    if not root_obj.get(constants.BUILDING_ID_KEY):
        issues.append("Sidecar export requires a stored building id on the root.")
    if bool(root_obj.get("tbg_edit_mode_dirty")):
        issues.append("Generated root is dirty; regenerate before validation/export so stored spec and V3 wall-cell payload are authoritative.")
    root_collection_name = root_obj.get(constants.COLLECTION_NAME_KEY, "")
    if root_collection_name and bpy.data.collections.get(root_collection_name) is None:
        issues.append("Stored root collection is missing.")
    if not root_obj.users_collection:
        issues.append("Root object is not linked to any collection.")

    children = tuple(root_obj.children_recursive)
    mesh_children = tuple(child for child in children if child.type == "MESH")
    contract_markers = tuple(
        child
        for child in mesh_children
        if export_contract.parse_export_contract_marker_name(child.name) is not None
    )
    runtime_markers = tuple(child for child in mesh_children if child.get("tbg_runtime_marker"))
    render_mesh_children = tuple(runtime_render_meshes(root_obj))
    if not render_mesh_children:
        issues.append("Sidecar export requires at least one exportable render mesh.")
        return issues

    issues.extend(_summary_contract_issues(root_obj, summary))
    issues.extend(_contract_marker_issues(contract_markers))
    if issues:
        return issues

    marker_facts = _runtime_collision_maps(runtime_markers)
    if issues:
        return issues

    return LoadedValidationState(
        root_obj=root_obj,
        effective_spec=effective_spec,
        summary=summary,
        final_section_registry=final_section_registry,
        voxel_wall_payload=voxel_wall_payload,
        children=children,
        mesh_children=mesh_children,
        render_mesh_children=render_mesh_children,
        marker_facts=marker_facts,
    )


def _registry_fragment_stamp_facts(registry: dict) -> tuple[frozenset[str], frozenset[str]]:
    profiles: set[str] = set()
    run_axes: set[str] = set()
    for section in registry.get("sections", ()) if isinstance(registry, dict) else ():
        if not isinstance(section, dict):
            continue
        for fragment in section.get("source_fragments", ()):
            if not isinstance(fragment, dict):
                continue
            profile = str(fragment.get("fragment_profile", "") or "").strip()
            if profile:
                profiles.add(profile)
            run_axis = str(fragment.get("fragment_run_axis", "") or "").strip()
            if run_axis:
                run_axes.add(run_axis)
    return frozenset(profiles), frozenset(run_axes)


def _collect_validation_facts(loaded: LoadedValidationState) -> ValidationFacts:
    summary = loaded.summary
    effective_spec = loaded.effective_spec
    voxel_wall_facts = _collect_voxel_wall_facts(
        loaded.root_obj,
        loaded.mesh_children,
        loaded.voxel_wall_payload,
        effective_spec,
    )
    identity = Matrix.Identity(4)
    drifting_children = tuple(
        child.name
        for child in loaded.children
        if child.parent is loaded.root_obj and any(
            abs(child.matrix_parent_inverse[row][col] - identity[row][col]) > 1e-5
            for row in range(4)
            for col in range(4)
        )
    )
    multi_material_children = tuple(
        child.name
        for child in loaded.mesh_children
        if not child.get("tbg_is_door_leaf")
        and len([slot for slot in child.material_slots if slot.material is not None]) > 1
    )
    hidden_wall_sections = tuple(
        sorted(
            child.name
            for child in loaded.mesh_children
            if child.get("tbg_hide_with_walls") and (child.hide_viewport or child.hide_render)
        )
    )
    render_section_buckets = frozenset(
        str(child.get("tbg_section_bucket", ""))
        for child in loaded.render_mesh_children
        if str(child.get("tbg_section_bucket", ""))
    )
    registry_fragment_profiles, registry_fragment_run_axes = _registry_fragment_stamp_facts(
        loaded.final_section_registry,
    )
    brick_mesh_children = tuple(
        child
        for child in loaded.mesh_children
        if child.material_slots
        and child.material_slots[0].material is not None
        and bool(child.material_slots[0].material.get("tbg_is_brick"))
        and str(child.get("tbg_wall_emit_owner", "") or "") != "occupancy_v3"
    )
    brick_projection_modes = tuple(sorted({str(child.get("tbg_brick_uv_space", "")) for child in brick_mesh_children}))
    brick_uv_scales = tuple(
        sorted({round(float(child.get("tbg_brick_uv_scale", 0.0)), 4) for child in brick_mesh_children})
    )
    balcony_material_names = tuple(
        sorted(
            {
                slot.material.name
                for child in loaded.render_mesh_children
                if str(child.get("tbg_section_bucket", "")).startswith("Section_Openings_Balcony")
                for slot in child.material_slots
                if slot.material is not None
            }
        )
    )
    atlas_images = tuple(
        sorted(
            {
                node.image.name
                for child in loaded.mesh_children
                if str(child.get("tbg_texture_uv_source", "") or "")
                not in {"payload_roblox_part_texture_v1", "payload_material_variant_style_v1"}
                for slot in child.material_slots
                if slot.material is not None and slot.material.node_tree is not None
                for node in slot.material.node_tree.nodes
                if node.type == "TEX_IMAGE" and node.image is not None
            }
        )
    )
    preset_id = effective_spec.preset_id
    floor_count = int(effective_spec.floor_count)
    massing_profile = str(getattr(effective_spec, "massing_profile", "")).upper()
    facade_mode = normalized_facade_mode(getattr(effective_spec, "facade_mode", "SPLIT"))
    door_profile = normalized_door_profile(getattr(effective_spec, "door_profile", "HINGED"))
    roof_mode = normalized_roof_mode(getattr(effective_spec, "roof_mode", "FLAT"))
    completed_facade_floors = _completed_facade_floor_count(effective_spec)
    effective_facade_family = normalized_facade_family(effective_spec.facade_family, facade_mode=facade_mode)
    brick_story_count = _brick_story_count(effective_spec)
    brick_floor_count = min(floor_count, brick_story_count)
    panel_floor_count = max(0, floor_count - brick_story_count)
    entrance_profile = normalized_entrance_profile(effective_spec.entrance_profile)
    standard_sill_height, standard_opening_height, _standard_top_height = _window_verticals(
        float(effective_spec.floor_height),
        str(effective_spec.window_profile),
    )
    expected_open_window_verticals_by_slot: dict[tuple[str, int, int], tuple[float, float]] = {}
    for slot in summary.windows.slots:
        if not slot.open or slot.balcony_access:
            continue
        slot_key = (str(slot.side), int(slot.floor), int(slot.slot))
        expected_open_window_verticals_by_slot[slot_key] = _expected_open_window_vertical_profile(
            effective_spec,
            slot,
        )
    if expected_open_window_verticals_by_slot:
        standard_sill_height, standard_opening_height = next(iter(expected_open_window_verticals_by_slot.values()))
    left_extent, right_extent, front_extent, _back_extent = estimate_footprint_extents(effective_spec)
    render_tri_rows: list[dict[str, object]] = []
    tri_count_by_bucket: dict[str, int] = {}
    tri_count_by_category: dict[str, int] = {}
    object_count_by_bucket: dict[str, int] = {}
    unique_materials: set[str] = set()
    material_slot_count_total = 0
    frame_tri_count_total = 0
    trim_tri_count_total = 0
    stair_tri_count_total = 0
    v3_wall_source_tri_count_in_render_meshes = 0
    for child in loaded.render_mesh_children:
        tris = _mesh_triangle_count(child)
        bucket = _polybudget_bucket(child)
        category = _polybudget_category(child)
        materials = _mesh_material_names(child)
        unique_materials.update(name for name in materials if name)
        material_slot_count_total += len(materials)
        tri_count_by_bucket[bucket] = tri_count_by_bucket.get(bucket, 0) + tris
        tri_count_by_category[category] = tri_count_by_category.get(category, 0) + tris
        object_count_by_bucket[bucket] = object_count_by_bucket.get(bucket, 0) + 1
        if category == "openings":
            frame_tri_count_total += tris
        if category == "trim":
            trim_tri_count_total += tris
        if category == "stairs":
            stair_tri_count_total += tris
        if _is_v3_wall_source_render_mesh(child):
            v3_wall_source_tri_count_in_render_meshes += tris
        render_tri_rows.append(
            {
                "object_name": str(getattr(child, "name", "") or ""),
                "bucket": bucket,
                "category": category,
                "material": materials[0] if materials else "",
                "tri_count": int(tris),
                "hidden": bool(getattr(child, "hide_viewport", False)),
                "exported_render": True,
            }
        )
    tri_count = sum(int(row["tri_count"]) for row in render_tri_rows)
    non_voxel_render_tri_count = max(0, tri_count - v3_wall_source_tri_count_in_render_meshes)
    total_scene_render_tri_count = sum(_mesh_triangle_count(child) for child in loaded.mesh_children)
    tri_count_top_offenders = tuple(
        sorted(render_tri_rows, key=lambda row: int(row["tri_count"]), reverse=True)[:12]
    )

    spatial_plan = _spatial_plan(effective_spec)
    rear_access_profile = str(
        getattr(
            spatial_plan,
            "rear_access_profile",
            REAR_ACCESS_PROFILE_SERVICE_DOOR,
        )
    ).upper()
    terminal_profile = (
        str(getattr(spatial_plan.roof_room, "terminal_profile", "")).upper()
        if spatial_plan.roof_room is not None
        else ""
    )
    front_entry_stair_conflict_span = _front_entry_stair_conflict_span(effective_spec)
    front_entry_envelope = _front_entry_envelope(effective_spec)
    front_entry_approach_gap = _front_entry_approach_gap(
        effective_spec,
        door_left=float(front_entry_envelope.door_left),
        door_right=float(front_entry_envelope.door_right),
    )
    front_door_bounds = _combined_bounds(
        loaded.root_obj,
        tuple(
            child
            for child in loaded.mesh_children
            if child.get("tbg_is_door_leaf")
            and (
                child.name.endswith("Door_Main")
                or str(child.get("tbg_facade_side", "")) == "front"
            )
        ),
    )
    stair_arrival_side = str(_dogleg_metrics(effective_spec).arrival_side)
    rear_entry_planned_contract = (
        _rear_entry_opening_contract(
            effective_spec,
            spatial_plan,
            face_length=float(effective_spec.width),
        )
        if rear_access_profile != REAR_ACCESS_PROFILE_NONE and spatial_plan.rear_access
        else None
    )
    rear_entry_planned_span = (
        (
            float(rear_entry_planned_contract["span_left"]),
            float(rear_entry_planned_contract["span_right"]),
        )
        if rear_entry_planned_contract is not None
        else None
    )
    rear_entry_planned_center_x = (
        float(rear_entry_planned_contract["opening_center_x"])
        if rear_entry_planned_contract is not None
        else None
    )
    rear_entry_planned_opening_width = (
        float(rear_entry_planned_contract["opening_width"])
        if rear_entry_planned_contract is not None
        else None
    )
    service_anchor = spatial_plan.service_anchor
    contract_roof_exit_bounds = _spatial_plan_roof_room_bounds(spatial_plan)
    contract_roof_opening_bounds = _spatial_plan_roof_opening_bounds(spatial_plan)
    authored_roof_exit_bounds = _combined_bounds(
        loaded.root_obj,
        tuple(child for child in loaded.mesh_children if child.get("tbg_roof_exit_shell")),
    )
    top_room_floor_bounds = _combined_bounds(
        loaded.root_obj,
        tuple(child for child in loaded.mesh_children if child.get("tbg_top_room_floor")),
    )
    rear_door_bounds = _combined_bounds(
        loaded.root_obj,
        tuple(
            child
            for child in loaded.mesh_children
            if child.get("tbg_is_door_leaf")
            and (
                child.get("tbg_rear_through_access")
                or str(child.get("tbg_facade_side", "")) == "back"
                or child.name.endswith("Door_Rear")
            )
        ),
    )
    rear_entry_authored_span = _rear_entry_authored_span(loaded.root_obj, loaded.mesh_children)
    if rear_entry_authored_span is None and rear_door_bounds is not None:
        rear_entry_authored_span = (float(rear_door_bounds[0]), float(rear_door_bounds[1]))
    rear_shell_marker_bounds = tuple(
        object_local_bounds(loaded.root_obj, marker)
        for marker in loaded.marker_facts.collision_markers
        if str(marker.get("tbg_runtime_role", "")) == export_contract.ROLE_SHELL
        and str(marker.get("tbg_runtime_side", "")) == "back"
        and int(marker.get("tbg_runtime_floor", -1)) == 0
    )
    stair_core_sight_keepout_bounds = _core_arrival_sightline_keepout_bounds(
        effective_spec,
        start_floor=1 if getattr(effective_spec, "massing_profile", "") == MASSING_PROFILE_PILOTIS else 0,
    )
    core_shell_partition_mesh_bounds = tuple(
        object_local_bounds(loaded.root_obj, child)
        for child in loaded.mesh_children
        if bool(child.get("tbg_core_partition_shell"))
    )
    core_shell_partition_marker_bounds = tuple(
        object_local_bounds(loaded.root_obj, marker)
        for marker in loaded.marker_facts.collision_markers
        if str(marker.get("tbg_runtime_role", "")) == export_contract.ROLE_PARTITION
        and str(marker.get("tbg_runtime_partition_owner", "")) == "core_shell"
    )
    partition_marker_bounds = tuple(
        object_local_bounds(loaded.root_obj, marker)
        for marker in loaded.marker_facts.collision_markers
        if str(marker.get("tbg_runtime_role", "")) == export_contract.ROLE_PARTITION
    )
    office_partition_positions_x: tuple[float, ...] = tuple()
    office_window_approach_keepout_spans: tuple[tuple[float, float], ...] = tuple()
    office_balcony_access_keepout_spans: tuple[tuple[float, float], ...] = tuple()
    office_rear_corridor_keepout_span: tuple[float, float] | None = None
    if preset_id == "office_block":
        office_partition_positions_x = _office_authored_partition_centers_x(
            loaded.root_obj,
            loaded.marker_facts.collision_markers,
        )
        keepout_contract = _office_partition_keepout_contract(
            effective_spec,
            spatial_plan,
            face_length=float(effective_spec.width),
        )
        office_window_approach_keepout_spans = tuple(keepout_contract["window_approach_spans"] or ())
        office_balcony_access_keepout_spans = tuple(keepout_contract["balcony_access_spans"] or ())
        rear_keepout = keepout_contract["rear_corridor_span"]
        office_rear_corridor_keepout_span = (
            (float(rear_keepout[0]), float(rear_keepout[1])) if rear_keepout is not None else None
        )
    roof_blocker_bounds = tuple(
        object_local_bounds(loaded.root_obj, marker)
        for marker in loaded.marker_facts.collision_markers
        if str(marker.get("tbg_runtime_role", "")) == export_contract.ROLE_ROOF_BLOCKER
    )
    roof_exit_platform_marker_bounds = tuple(
        object_local_bounds(loaded.root_obj, marker)
        for marker in loaded.marker_facts.collision_markers
        if str(marker.get("tbg_runtime_role", "")) == export_contract.ROLE_ROOF_EXIT_PLATFORM
    )
    authored_slots_by_side_floor: dict[tuple[str, int], set[int]] = {}
    for slot in summary.windows.slots:
        side = str(slot.side)
        floor = int(slot.floor)
        authored_slots_by_side_floor.setdefault((side, floor), set()).add(int(slot.slot))
    shell_slots_by_side_floor: dict[tuple[str, int], set[int]] = {}
    for (side, floor, slot), roles in loaded.marker_facts.slot_roles.items():
        if export_contract.ROLE_SHELL not in roles:
            continue
        shell_slots_by_side_floor.setdefault((str(side), int(floor)), set()).add(int(slot))
    return ValidationFacts(
        root_obj=loaded.root_obj,
        effective_spec=effective_spec,
        summary=summary,
        mesh_children=loaded.mesh_children,
        render_mesh_children=loaded.render_mesh_children,
        marker_facts=loaded.marker_facts,
        voxel_wall_facts=voxel_wall_facts,
        door_leaves=tuple(child for child in loaded.mesh_children if child.get("tbg_is_door_leaf")),
        brick_mesh_children=brick_mesh_children,
        drifting_children=drifting_children,
        multi_material_children=multi_material_children,
        hidden_wall_sections=hidden_wall_sections,
        render_section_buckets=render_section_buckets,
        registry_fragment_profiles=registry_fragment_profiles,
        registry_fragment_run_axes=registry_fragment_run_axes,
        brick_projection_modes=brick_projection_modes,
        brick_uv_scales=brick_uv_scales,
        balcony_material_names=balcony_material_names,
        atlas_images=atlas_images,
        wide_partition_eligible=bool(loaded.root_obj.get("tbg_room_partition_eligible", False)),
        room_partition_corridor_width=float(loaded.root_obj.get("tbg_room_partition_corridor_width", 0.0)),
        preset_id=preset_id,
        floor_count=floor_count,
        massing_profile=massing_profile,
        facade_mode=facade_mode,
        door_profile=door_profile,
        roof_mode=roof_mode,
        front_entry_stair_conflict_span=front_entry_stair_conflict_span,
        front_entry_approach_band_min=float(_front_entry_approach_band_min(effective_spec)),
        front_entry_approach_gap=(float(front_entry_approach_gap) if front_entry_approach_gap is not None else None),
        front_door_bounds=front_door_bounds,
        stair_arrival_side=stair_arrival_side,
        rear_through_access=bool(spatial_plan.rear_access),
        rear_access_profile=rear_access_profile,
        rear_entry_stair_clearance_min=float(_rear_entry_stair_clearance(effective_spec)),
        rear_entry_stair_conflict_span=_rear_entry_stair_conflict_span(effective_spec),
        rear_entry_planned_center_x=rear_entry_planned_center_x,
        rear_entry_planned_opening_width=rear_entry_planned_opening_width,
        rear_entry_planned_span=rear_entry_planned_span,
        rear_entry_authored_span=rear_entry_authored_span,
        rear_door_bounds=rear_door_bounds,
        rear_shell_marker_bounds=rear_shell_marker_bounds,
        stair_core_sight_keepout_bounds=stair_core_sight_keepout_bounds,
        core_shell_partition_mesh_bounds=core_shell_partition_mesh_bounds,
        core_shell_partition_marker_bounds=core_shell_partition_marker_bounds,
        partition_marker_bounds=partition_marker_bounds,
        office_partition_positions_x=office_partition_positions_x,
        office_window_approach_keepout_spans=office_window_approach_keepout_spans,
        office_balcony_access_keepout_spans=office_balcony_access_keepout_spans,
        office_rear_corridor_keepout_span=office_rear_corridor_keepout_span,
        authored_window_slot_count_by_side_floor={key: len(slots) for key, slots in authored_slots_by_side_floor.items()},
        shell_slot_count_by_side_floor={key: len(slots) for key, slots in shell_slots_by_side_floor.items()},
        top_terminal_mode=str(spatial_plan.top_terminal_mode),
        terminal_profile=terminal_profile,
        roof_access_enabled=bool(spatial_plan.roof_access_enabled),
        contract_roof_exit_bounds=contract_roof_exit_bounds,
        contract_roof_opening_bounds=contract_roof_opening_bounds,
        authored_roof_exit_bounds=authored_roof_exit_bounds,
        top_room_floor_bounds=top_room_floor_bounds,
        roof_blocker_bounds=roof_blocker_bounds,
        roof_exit_platform_marker_bounds=roof_exit_platform_marker_bounds,
        service_anchor_id=str(service_anchor.anchor_id),
        completed_facade_floors=completed_facade_floors,
        effective_facade_family=effective_facade_family,
        brick_floor_count=brick_floor_count,
        panel_floor_count=panel_floor_count,
        entrance_profile=entrance_profile,
        standard_sill_height=standard_sill_height,
        standard_opening_height=standard_opening_height,
        expected_open_window_verticals_by_slot=expected_open_window_verticals_by_slot,
        has_stairs=loaded.marker_facts.role_counts.get(export_contract.ROLE_STAIR_STEP, 0) > 0,
        has_mid_landing=loaded.marker_facts.role_counts.get(export_contract.ROLE_STAIR_LANDING, 0) > 0,
        has_stair_window=any(slot.state == WINDOW_STATE_STAIR for slot in summary.windows.slots),
        width=float(effective_spec.width),
        depth=float(effective_spec.depth),
        wall_thickness=float(effective_spec.wall_thickness),
        entrance_left_limit=summary.entrance.left_limit,
        entrance_right_limit=summary.entrance.right_limit,
        entrance_front_limit=summary.entrance.front_limit,
        left_extent=left_extent,
        right_extent=right_extent,
        front_extent=front_extent,
        tri_count=tri_count,
        non_voxel_render_tri_count=non_voxel_render_tri_count,
        v3_wall_source_tri_count_in_render_meshes=v3_wall_source_tri_count_in_render_meshes,
        total_scene_render_tri_count=total_scene_render_tri_count,
        tri_count_by_bucket=dict(sorted(tri_count_by_bucket.items())),
        tri_count_by_category=dict(sorted(tri_count_by_category.items())),
        tri_count_top_offenders=tri_count_top_offenders,
        exported_render_object_count=len(loaded.render_mesh_children),
        object_count_by_bucket=dict(sorted(object_count_by_bucket.items())),
        unique_material_count=len(unique_materials),
        material_slot_count_total=material_slot_count_total,
        frame_tri_count_total=frame_tri_count_total,
        trim_tri_count_total=trim_tri_count_total,
        stair_tri_count_total=stair_tri_count_total,
    )


NUMERIC_SMOKE_PASS_SOURCE = "numeric_metrics_only"
NUMERIC_SMOKE_MATRIX_REQUIRED_FIELDS = (
    "preset_id",
    "seed",
    "root_name",
    "generate_stage",
    "failure_class",
    "payload_present",
    "dirty_root_after_idle",
    "payload_authored_cell_count",
    "real_visible_cell_count",
    "preview_helper_count",
    "fragment_adapter_group_count",
    "destructible_wall_fbx_render_count",
    "opening_visual_count",
    "opening_seating_source_count",
    "opening_missing_stamp_or_cut_count",
    "opening_same_plane_overlap_count",
    "opening_backfill_count",
    "cross_plane_leakage_count",
    "cut_edge_boundary_max_delta_studs",
    "max_actual_visual_gap_studs",
    "actual_missing_boundary_sides_total",
    "sub_min_residual_count",
    "trim_back_air_gap_max_studs",
    "trim_back_overlap_min_studs",
    "floating_trim_object_count",
    "frame_silhouette_thickness_min_studs",
    "frame_ring_width_min_studs",
    "frame_inner_return_depth_min_studs",
    "frame_open_boundary_edge_count",
    "frame_outer_perimeter_face_count",
    "frame_sill_or_head_mass_missing_count",
    "frame_gasket_back_overlap_min_studs",
    "frame_gasket_air_gap_max_studs",
    "unstamped_opening_trim_object_count",
    "window_cut_envelope_match_max_delta_studs",
    "door_frame_cut_envelope_match_max_delta_studs",
    "ordinary_door_panel_height_delta_studs",
    "roof_exit_door_panel_height_delta_studs",
    "roof_exit_lintel_closure_present_count",
    "roof_exit_lintel_required_count",
    "roof_exit_lintel_closure_distinct_from_frame_count",
    "roof_exit_lintel_closure_section_bucket_invalid_count",
    "roof_exit_lintel_closure_from_door_trim_count",
    "roof_exit_lintel_closure_survives_finalsectionsink_count",
    "roof_exit_top_band_coverage_ratio",
    "roof_exit_frame_inner_height_delta_studs",
    "roof_exit_frame_outer_height_delta_studs",
    "roof_exit_frame_height_delta_studs",
    "roof_exit_frame_cut_height_ratio_max",
    "roof_exit_frame_counts_as_lintel_count",
    "roof_exit_top_wall_lintel_coverage_ratio",
    "rear_door_window_clearance_overlap_count",
    "rear_door_reserved_span_window_candidate_overlap_count",
    "rear_door_reserved_span_window_overlap_max_studs",
    "terrace_exit_unclassified_top_coverage_count",
    "terrace_exit_top_band_coverage_ratio",
    "terrace_exit_owner_class_invalid_count",
    "terrace_exit_allowed_frame_inflation",
    "terrace_exit_frame_floor_penetration_count",
    "terrace_exit_frame_floor_penetration_max_studs",
    "terrace_exit_threshold_obstruction_height_max_studs",
    "terrace_exit_traversal_blocker_count",
    "terrace_exit_clear_passage_height_min_studs",
    "terrace_exit_clear_passage_width_min_studs",
    "terrace_exit_top_transom_coverage_ratio",
    "ordinary_door_unseated_count",
    "roof_exit_uncovered_cut_top_gap_count",
    "opening_visual_seal_gap_max_studs",
    "roof_exit_side_seal_gap_max_studs",
    "roof_exit_top_closure_gap_count",
    "roof_exit_cut_covered_area_ratio",
    "trim_segment_back_air_gap_max_studs",
    "trim_segment_back_overlap_min_studs",
    "parapet_cap_segment_back_air_gap_max_studs",
    "townhouse_like_parapet_height_min_studs",
    "window_fill_wrong_material_count",
    "window_fill_non_blue_count",
    "window_fill_shader_non_blue_count",
    "window_fill_missing_uv_count",
    "window_fill_shader_rgb_min",
    "window_fill_shader_rgb_max",
    "window_fill_same_plane_v3_overlap_count",
    "decorative_window_panel_count",
    "v3_material_style_preview_mismatch_count",
    "opening_bounds_off_grid_count",
    "brick_opening_adjacent_non_grid_cell_count",
    "non_voxel_render_tri_count",
    "v3_wall_source_tri_count_in_render_meshes",
    "total_scene_render_tri_count",
    "tri_count_by_bucket",
    "tri_count_by_category",
    "tri_count_top_offenders",
    "exported_render_object_count",
    "object_count_by_bucket",
    "unique_material_count",
    "material_slot_count_total",
    "frame_tri_count_total",
    "trim_tri_count_total",
    "stair_tri_count_total",
    "regenerate_status",
    "pass_calculation_source",
    "optional_human_screenshot_paths",
)
_NUMERIC_SMOKE_COUNT_FIELDS = frozenset(
    field
    for field in NUMERIC_SMOKE_MATRIX_REQUIRED_FIELDS
    if field.endswith("_count") or field.endswith("_total")
) | frozenset(
    {
        "payload_authored_cell_count",
        "real_visible_cell_count",
        "preview_helper_count",
        "fragment_adapter_group_count",
        "destructible_wall_fbx_render_count",
        "v3_wall_source_tri_count_in_render_meshes",
        "window_fill_wrong_material_count",
        "window_fill_non_blue_count",
        "window_fill_shader_non_blue_count",
        "window_fill_missing_uv_count",
        "window_fill_same_plane_v3_overlap_count",
        "decorative_window_panel_count",
        "v3_material_style_preview_mismatch_count",
        "opening_bounds_off_grid_count",
        "brick_opening_adjacent_non_grid_cell_count",
    }
)


def _json_scalar(value: object) -> object:
    if isinstance(value, float):
        if math.isfinite(value):
            return round(float(value), 6)
        return "inf" if value > 0.0 else "-inf"
    return value


def validate_numeric_smoke_matrix_row(row: dict[str, object]) -> tuple[str, ...]:
    issues: list[str] = []
    missing_fields = tuple(field for field in NUMERIC_SMOKE_MATRIX_REQUIRED_FIELDS if field not in row)
    if missing_fields:
        issues.append("missing required field(s): " + ", ".join(missing_fields))
    for field in _NUMERIC_SMOKE_COUNT_FIELDS:
        value = row.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            issues.append(f"{field} must be an integer >= 0")
    for field in ("payload_present", "dirty_root_after_idle", "terrace_exit_allowed_frame_inflation"):
        if not isinstance(row.get(field), bool):
            issues.append(f"{field} must be boolean")
    for field in ("tri_count_by_bucket", "tri_count_by_category", "object_count_by_bucket"):
        if not isinstance(row.get(field), dict):
            issues.append(f"{field} must be a dict")
    for field in ("window_fill_shader_rgb_min", "window_fill_shader_rgb_max"):
        value = row.get(field)
        if value is None:
            continue
        if not isinstance(value, list) or len(value) != 3:
            issues.append(f"{field} must be a 3-number list or null")
            continue
        if any(not isinstance(channel, (int, float)) or isinstance(channel, bool) for channel in value):
            issues.append(f"{field} must be a 3-number list or null")
    if not isinstance(row.get("tri_count_top_offenders"), list):
        issues.append("tri_count_top_offenders must be a list")
    opening_visual_count = row.get("opening_visual_count")
    for field in ("max_actual_visual_gap_studs", "cut_edge_boundary_max_delta_studs"):
        value = row.get(field)
        if isinstance(opening_visual_count, int) and opening_visual_count > 0 and value is None:
            issues.append(f"{field} is null while opening_visual_count > 0")
        if isinstance(value, (int, float)) and isinstance(value, bool):
            issues.append(f"{field} must not be boolean")
    null_contexts = {
        "trim_back_air_gap_max_studs": "floating_trim_object_count",
        "trim_back_overlap_min_studs": "floating_trim_object_count",
        "frame_silhouette_thickness_min_studs": "unstamped_opening_trim_object_count",
        "frame_ring_width_min_studs": "unstamped_opening_trim_object_count",
        "frame_inner_return_depth_min_studs": "unstamped_opening_trim_object_count",
        "frame_gasket_back_overlap_min_studs": "unstamped_opening_trim_object_count",
        "frame_gasket_air_gap_max_studs": "unstamped_opening_trim_object_count",
        "window_cut_envelope_match_max_delta_studs": "opening_visual_count",
        "door_frame_cut_envelope_match_max_delta_studs": "opening_visual_count",
        "ordinary_door_panel_height_delta_studs": "opening_visual_count",
        "roof_exit_door_panel_height_delta_studs": "roof_exit_lintel_required_count",
        "roof_exit_top_band_coverage_ratio": "roof_exit_lintel_required_count",
        "roof_exit_frame_inner_height_delta_studs": "roof_exit_lintel_required_count",
        "roof_exit_frame_outer_height_delta_studs": "roof_exit_lintel_required_count",
        "roof_exit_frame_height_delta_studs": "roof_exit_lintel_required_count",
        "roof_exit_frame_cut_height_ratio_max": "roof_exit_lintel_required_count",
        "roof_exit_top_wall_lintel_coverage_ratio": "roof_exit_lintel_required_count",
        "rear_door_reserved_span_window_overlap_max_studs": "rear_door_reserved_span_window_candidate_overlap_count",
        "terrace_exit_top_band_coverage_ratio": "terrace_exit_unclassified_top_coverage_count",
        "terrace_exit_frame_floor_penetration_max_studs": "terrace_exit_unclassified_top_coverage_count",
        "terrace_exit_threshold_obstruction_height_max_studs": "terrace_exit_unclassified_top_coverage_count",
        "terrace_exit_clear_passage_height_min_studs": "terrace_exit_unclassified_top_coverage_count",
        "terrace_exit_clear_passage_width_min_studs": "terrace_exit_unclassified_top_coverage_count",
        "terrace_exit_top_transom_coverage_ratio": "terrace_exit_unclassified_top_coverage_count",
        "opening_visual_seal_gap_max_studs": "opening_visual_count",
        "roof_exit_side_seal_gap_max_studs": "roof_exit_uncovered_cut_top_gap_count",
        "roof_exit_cut_covered_area_ratio": "roof_exit_uncovered_cut_top_gap_count",
        "trim_segment_back_air_gap_max_studs": "floating_trim_object_count",
        "trim_segment_back_overlap_min_studs": "floating_trim_object_count",
        "parapet_cap_segment_back_air_gap_max_studs": "floating_trim_object_count",
        "townhouse_like_parapet_height_min_studs": "floating_trim_object_count",
    }
    for field in null_contexts:
        value = row.get(field)
        if (
            field == "opening_visual_seal_gap_max_studs"
            and isinstance(opening_visual_count, int)
            and opening_visual_count > 0
            and value is None
        ):
            issues.append(f"{field} is null while opening_visual_count > 0")
        if isinstance(value, bool):
            issues.append(f"{field} must not be boolean")
        elif value is not None and not isinstance(value, (int, float)):
            issues.append(f"{field} must be numeric or null")
    if row.get("regenerate_status") in (None, ""):
        issues.append("regenerate_status must be set")
    if row.get("pass_calculation_source") != NUMERIC_SMOKE_PASS_SOURCE:
        issues.append("pass_calculation_source must be numeric_metrics_only")
    if not isinstance(row.get("optional_human_screenshot_paths"), list):
        issues.append("optional_human_screenshot_paths must be a list")
    if (
        isinstance(row.get("opening_visual_count"), int)
        and int(row.get("opening_visual_count", 0)) > 0
        and isinstance(row.get("opening_seating_source_count"), int)
        and int(row.get("opening_seating_source_count", 0)) == 0
    ):
        issues.append("opening visuals exist but seating source count is zero")
    return tuple(issues)


def numeric_smoke_matrix_row_passes(row: dict[str, object]) -> bool:
    if validate_numeric_smoke_matrix_row(row):
        return False
    if not row.get("payload_present"):
        return False
    if row.get("dirty_root_after_idle"):
        return False
    if row.get("payload_authored_cell_count") != row.get("real_visible_cell_count"):
        return False
    zero_fields = (
        "fragment_adapter_group_count",
        "preview_helper_count",
        "destructible_wall_fbx_render_count",
        "opening_missing_stamp_or_cut_count",
        "opening_same_plane_overlap_count",
        "opening_backfill_count",
        "cross_plane_leakage_count",
        "actual_missing_boundary_sides_total",
        "sub_min_residual_count",
        "floating_trim_object_count",
        "frame_open_boundary_edge_count",
        "frame_sill_or_head_mass_missing_count",
        "unstamped_opening_trim_object_count",
        "ordinary_door_unseated_count",
        "roof_exit_uncovered_cut_top_gap_count",
        "roof_exit_top_closure_gap_count",
        "roof_exit_lintel_closure_section_bucket_invalid_count",
        "roof_exit_lintel_closure_from_door_trim_count",
        "roof_exit_frame_counts_as_lintel_count",
        "rear_door_window_clearance_overlap_count",
        "rear_door_reserved_span_window_candidate_overlap_count",
        "terrace_exit_unclassified_top_coverage_count",
        "terrace_exit_owner_class_invalid_count",
        "terrace_exit_frame_floor_penetration_count",
        "terrace_exit_traversal_blocker_count",
        "v3_wall_source_tri_count_in_render_meshes",
        "window_fill_wrong_material_count",
        "window_fill_non_blue_count",
        "window_fill_shader_non_blue_count",
        "window_fill_missing_uv_count",
        "window_fill_same_plane_v3_overlap_count",
        "decorative_window_panel_count",
        "v3_material_style_preview_mismatch_count",
        "opening_bounds_off_grid_count",
        "brick_opening_adjacent_non_grid_cell_count",
    )
    if any(row.get(field) != 0 for field in zero_fields):
        return False
    if row.get("roof_exit_lintel_closure_present_count") != row.get("roof_exit_lintel_required_count"):
        return False
    if row.get("roof_exit_lintel_closure_distinct_from_frame_count") != row.get("roof_exit_lintel_required_count"):
        return False
    if not row.get("terrace_exit_allowed_frame_inflation"):
        return False
    has_frame_metrics = row.get("frame_silhouette_thickness_min_studs") is not None
    if has_frame_metrics:
        value = row.get("frame_outer_perimeter_face_count")
        if not isinstance(value, int) or isinstance(value, bool) or value < 4:
            return False
    opening_visual_count = int(row.get("opening_visual_count", 0))
    for field in ("cut_edge_boundary_max_delta_studs", "max_actual_visual_gap_studs"):
        value = row.get(field)
        if opening_visual_count == 0:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        if not math.isfinite(float(value)) or float(value) > 0.05:
            return False
    upper_bounds = (
        ("trim_back_air_gap_max_studs", TRIM_BACK_AIR_GAP_MAX_STUDS),
        ("window_cut_envelope_match_max_delta_studs", CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS),
        ("door_frame_cut_envelope_match_max_delta_studs", CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS),
        ("opening_visual_seal_gap_max_studs", OPENING_VISUAL_SEAL_GAP_MAX_STUDS),
        ("roof_exit_side_seal_gap_max_studs", OPENING_VISUAL_SEAL_GAP_MAX_STUDS),
        ("frame_gasket_air_gap_max_studs", TRIM_BACK_AIR_GAP_MAX_STUDS),
        ("ordinary_door_panel_height_delta_studs", CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS),
        ("roof_exit_door_panel_height_delta_studs", CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS),
        ("roof_exit_frame_inner_height_delta_studs", CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS),
        ("roof_exit_frame_outer_height_delta_studs", CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS),
        ("roof_exit_frame_height_delta_studs", CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS),
        ("roof_exit_frame_cut_height_ratio_max", 1.10),
        ("rear_door_reserved_span_window_overlap_max_studs", CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS),
        ("terrace_exit_frame_floor_penetration_max_studs", TRIM_BACK_AIR_GAP_MAX_STUDS),
        ("terrace_exit_threshold_obstruction_height_max_studs", 0.02),
        ("trim_segment_back_air_gap_max_studs", TRIM_BACK_AIR_GAP_MAX_STUDS),
        ("parapet_cap_segment_back_air_gap_max_studs", TRIM_BACK_AIR_GAP_MAX_STUDS),
    )
    for field, threshold in upper_bounds:
        value = row.get(field)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        if not math.isfinite(float(value)) or float(value) > threshold:
            return False
    lower_bounds = (
        ("trim_back_overlap_min_studs", TRIM_BACK_OVERLAP_MIN_STUDS),
        ("frame_silhouette_thickness_min_studs", FRAME_SILHOUETTE_MIN_STUDS),
        ("frame_ring_width_min_studs", FRAME_RING_WIDTH_MIN_STUDS),
        ("frame_inner_return_depth_min_studs", FRAME_INNER_RETURN_MIN_STUDS),
        ("frame_gasket_back_overlap_min_studs", TRIM_BACK_OVERLAP_MIN_STUDS),
        ("roof_exit_cut_covered_area_ratio", ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN),
        ("roof_exit_top_band_coverage_ratio", ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN),
        ("roof_exit_top_wall_lintel_coverage_ratio", ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN),
        ("terrace_exit_top_band_coverage_ratio", ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN),
        ("terrace_exit_clear_passage_height_min_studs", 1.90),
        ("terrace_exit_top_transom_coverage_ratio", ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN),
        ("trim_segment_back_overlap_min_studs", TRIM_BACK_OVERLAP_MIN_STUDS),
        ("townhouse_like_parapet_height_min_studs", RESIDENTIAL_BORDER_MIN_STUDS),
    )
    for field, threshold in lower_bounds:
        value = row.get(field)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        if not math.isfinite(float(value)) or float(value) < threshold:
            return False
    return row.get("regenerate_status") == "green"


def build_numeric_smoke_matrix_row(
    facts: ValidationFacts,
    *,
    generate_stage: str,
    validation_issues: tuple[str, ...] = (),
    dirty_root_after_idle: bool = False,
    regenerate_status: str = "not_run",
    optional_human_screenshot_paths: tuple[str, ...] = (),
) -> dict[str, object]:
    voxel = facts.voxel_wall_facts
    payload_cell_count = voxel.payload.get("authored_cell_count")
    if not isinstance(payload_cell_count, int) or isinstance(payload_cell_count, bool):
        payload_cell_count = 0
    opening_backfill_count = sum(len(opening.cut_intrusion_cell_ids) for opening in voxel.opening_visuals)
    cross_plane_leakage_count = sum(len(opening.cross_plane_leakage_cell_ids) for opening in voxel.opening_visuals)
    row: dict[str, object] = {
        "preset_id": str(facts.preset_id or "unknown"),
        "seed": int(getattr(facts.effective_spec, "seed", 0) or 0),
        "root_name": str(getattr(facts.root_obj, "name", "") or "unknown"),
        "generate_stage": str(generate_stage or "unknown"),
        "failure_class": "validation_red" if validation_issues else "green_candidate",
        "payload_present": bool(voxel.payload),
        "dirty_root_after_idle": bool(dirty_root_after_idle),
        "payload_authored_cell_count": int(payload_cell_count),
        "real_visible_cell_count": int(voxel.real_visible_cell_count),
        "preview_helper_count": len(voxel.preview_cache_object_names),
        "fragment_adapter_group_count": len(voxel.adapter_group_ids),
        "destructible_wall_fbx_render_count": len(voxel.runtime_render_wall_object_names),
        "opening_visual_count": int(voxel.opening_visual_count),
        "opening_seating_source_count": int(voxel.opening_seating_source_count),
        "opening_missing_stamp_or_cut_count": int(voxel.missing_cut_or_stamp_count),
        "opening_same_plane_overlap_count": int(voxel.same_plane_opening_cell_overlap_count),
        "opening_backfill_count": int(opening_backfill_count),
        "cross_plane_leakage_count": int(cross_plane_leakage_count),
        "cut_edge_boundary_max_delta_studs": _json_scalar(voxel.cut_edge_boundary_max_delta_studs),
        "max_actual_visual_gap_studs": _json_scalar(voxel.max_actual_visual_gap_studs),
        "actual_missing_boundary_sides_total": int(voxel.actual_missing_boundary_sides_total),
        "sub_min_residual_count": int(voxel.sub_min_residual_count),
        "trim_back_air_gap_max_studs": _json_scalar(voxel.trim_back_air_gap_max_studs),
        "trim_back_overlap_min_studs": _json_scalar(voxel.trim_back_overlap_min_studs),
        "floating_trim_object_count": int(voxel.floating_trim_object_count),
        "frame_silhouette_thickness_min_studs": _json_scalar(voxel.frame_silhouette_thickness_min_studs),
        "frame_ring_width_min_studs": _json_scalar(voxel.frame_ring_width_min_studs),
        "frame_inner_return_depth_min_studs": _json_scalar(voxel.frame_inner_return_depth_min_studs),
        "frame_open_boundary_edge_count": int(voxel.frame_open_boundary_edge_count),
        "frame_outer_perimeter_face_count": int(voxel.frame_outer_perimeter_face_count),
        "frame_sill_or_head_mass_missing_count": int(voxel.frame_sill_or_head_mass_missing_count),
        "frame_gasket_back_overlap_min_studs": _json_scalar(voxel.frame_gasket_back_overlap_min_studs),
        "frame_gasket_air_gap_max_studs": _json_scalar(voxel.frame_gasket_air_gap_max_studs),
        "unstamped_opening_trim_object_count": int(voxel.unstamped_opening_trim_object_count),
        "window_cut_envelope_match_max_delta_studs": _json_scalar(voxel.window_cut_envelope_match_max_delta_studs),
        "door_frame_cut_envelope_match_max_delta_studs": _json_scalar(voxel.door_frame_cut_envelope_match_max_delta_studs),
        "ordinary_door_panel_height_delta_studs": _json_scalar(voxel.ordinary_door_panel_height_delta_studs),
        "roof_exit_door_panel_height_delta_studs": _json_scalar(voxel.roof_exit_door_panel_height_delta_studs),
        "roof_exit_lintel_closure_present_count": int(voxel.roof_exit_lintel_closure_present_count),
        "roof_exit_lintel_required_count": int(voxel.roof_exit_lintel_required_count),
        "roof_exit_lintel_closure_distinct_from_frame_count": int(voxel.roof_exit_lintel_closure_distinct_from_frame_count),
        "roof_exit_lintel_closure_section_bucket_invalid_count": int(voxel.roof_exit_lintel_closure_section_bucket_invalid_count),
        "roof_exit_lintel_closure_from_door_trim_count": int(voxel.roof_exit_lintel_closure_from_door_trim_count),
        "roof_exit_lintel_closure_survives_finalsectionsink_count": int(voxel.roof_exit_lintel_closure_survives_finalsectionsink_count),
        "roof_exit_top_band_coverage_ratio": _json_scalar(voxel.roof_exit_top_band_coverage_ratio),
        "roof_exit_frame_inner_height_delta_studs": _json_scalar(voxel.roof_exit_frame_inner_height_delta_studs),
        "roof_exit_frame_outer_height_delta_studs": _json_scalar(voxel.roof_exit_frame_outer_height_delta_studs),
        "roof_exit_frame_height_delta_studs": _json_scalar(voxel.roof_exit_frame_height_delta_studs),
        "roof_exit_frame_cut_height_ratio_max": _json_scalar(voxel.roof_exit_frame_cut_height_ratio_max),
        "roof_exit_frame_counts_as_lintel_count": int(voxel.roof_exit_frame_counts_as_lintel_count),
        "roof_exit_top_wall_lintel_coverage_ratio": _json_scalar(voxel.roof_exit_top_wall_lintel_coverage_ratio),
        "rear_door_window_clearance_overlap_count": int(voxel.rear_door_window_clearance_overlap_count),
        "rear_door_reserved_span_window_candidate_overlap_count": int(voxel.rear_door_reserved_span_window_candidate_overlap_count),
        "rear_door_reserved_span_window_overlap_max_studs": _json_scalar(voxel.rear_door_reserved_span_window_overlap_max_studs),
        "terrace_exit_unclassified_top_coverage_count": int(voxel.terrace_exit_unclassified_top_coverage_count),
        "terrace_exit_top_band_coverage_ratio": _json_scalar(voxel.terrace_exit_top_band_coverage_ratio),
        "terrace_exit_owner_class_invalid_count": int(voxel.terrace_exit_owner_class_invalid_count),
        "terrace_exit_allowed_frame_inflation": bool(voxel.terrace_exit_allowed_frame_inflation),
        "terrace_exit_frame_floor_penetration_count": int(voxel.terrace_exit_frame_floor_penetration_count),
        "terrace_exit_frame_floor_penetration_max_studs": _json_scalar(voxel.terrace_exit_frame_floor_penetration_max_studs),
        "terrace_exit_threshold_obstruction_height_max_studs": _json_scalar(voxel.terrace_exit_threshold_obstruction_height_max_studs),
        "terrace_exit_traversal_blocker_count": int(voxel.terrace_exit_traversal_blocker_count),
        "terrace_exit_clear_passage_height_min_studs": _json_scalar(voxel.terrace_exit_clear_passage_height_min_studs),
        "terrace_exit_clear_passage_width_min_studs": _json_scalar(voxel.terrace_exit_clear_passage_width_min_studs),
        "terrace_exit_top_transom_coverage_ratio": _json_scalar(voxel.terrace_exit_top_transom_coverage_ratio),
        "ordinary_door_unseated_count": int(voxel.ordinary_door_unseated_count),
        "roof_exit_uncovered_cut_top_gap_count": int(voxel.roof_exit_uncovered_cut_top_gap_count),
        "opening_visual_seal_gap_max_studs": _json_scalar(voxel.opening_visual_seal_gap_max_studs),
        "roof_exit_side_seal_gap_max_studs": _json_scalar(voxel.roof_exit_side_seal_gap_max_studs),
        "roof_exit_top_closure_gap_count": int(voxel.roof_exit_top_closure_gap_count),
        "roof_exit_cut_covered_area_ratio": _json_scalar(voxel.roof_exit_cut_covered_area_ratio),
        "trim_segment_back_air_gap_max_studs": _json_scalar(voxel.trim_segment_back_air_gap_max_studs),
        "trim_segment_back_overlap_min_studs": _json_scalar(voxel.trim_segment_back_overlap_min_studs),
        "parapet_cap_segment_back_air_gap_max_studs": _json_scalar(voxel.parapet_cap_segment_back_air_gap_max_studs),
        "townhouse_like_parapet_height_min_studs": _json_scalar(voxel.townhouse_like_parapet_height_min_studs),
        "window_fill_wrong_material_count": int(voxel.window_fill_wrong_material_count),
        "window_fill_non_blue_count": int(voxel.window_fill_non_blue_count),
        "window_fill_shader_non_blue_count": int(voxel.window_fill_shader_non_blue_count),
        "window_fill_missing_uv_count": int(voxel.window_fill_missing_uv_count),
        "window_fill_shader_rgb_min": (
            [_json_scalar(value) for value in voxel.window_fill_shader_rgb_min]
            if voxel.window_fill_shader_rgb_min is not None
            else None
        ),
        "window_fill_shader_rgb_max": (
            [_json_scalar(value) for value in voxel.window_fill_shader_rgb_max]
            if voxel.window_fill_shader_rgb_max is not None
            else None
        ),
        "window_fill_same_plane_v3_overlap_count": int(voxel.window_fill_same_plane_v3_overlap_count),
        "decorative_window_panel_count": sum(
            1 for child in facts.mesh_children if bool(child.get("tbg_decorative_window_panel"))
        ),
        "v3_material_style_preview_mismatch_count": int(voxel.v3_material_style_preview_mismatch_count),
        "opening_bounds_off_grid_count": int(voxel.opening_bounds_off_grid_count),
        "brick_opening_adjacent_non_grid_cell_count": int(voxel.brick_opening_adjacent_non_grid_cell_count),
        "non_voxel_render_tri_count": int(facts.non_voxel_render_tri_count),
        "v3_wall_source_tri_count_in_render_meshes": int(facts.v3_wall_source_tri_count_in_render_meshes),
        "total_scene_render_tri_count": int(facts.total_scene_render_tri_count),
        "tri_count_by_bucket": dict(facts.tri_count_by_bucket),
        "tri_count_by_category": dict(facts.tri_count_by_category),
        "tri_count_top_offenders": [dict(row) for row in facts.tri_count_top_offenders],
        "exported_render_object_count": int(facts.exported_render_object_count),
        "object_count_by_bucket": dict(facts.object_count_by_bucket),
        "unique_material_count": int(facts.unique_material_count),
        "material_slot_count_total": int(facts.material_slot_count_total),
        "frame_tri_count_total": int(facts.frame_tri_count_total),
        "trim_tri_count_total": int(facts.trim_tri_count_total),
        "stair_tri_count_total": int(facts.stair_tri_count_total),
        "regenerate_status": str(regenerate_status or "not_run"),
        "pass_calculation_source": NUMERIC_SMOKE_PASS_SOURCE,
        "optional_human_screenshot_paths": list(optional_human_screenshot_paths),
    }
    schema_issues = validate_numeric_smoke_matrix_row(row)
    if schema_issues:
        row["failure_class"] = "schema_red"
    elif numeric_smoke_matrix_row_passes(row):
        row["failure_class"] = "green"
    return row


def opening_diagnostic_ledger_entries(facts: ValidationFacts) -> tuple[dict[str, object], ...]:
    voxel = facts.voxel_wall_facts
    base = {
        "root_name": str(getattr(facts.root_obj, "name", "") or "unknown"),
        "preset_id": str(facts.preset_id or "unknown"),
        "seed": int(getattr(facts.effective_spec, "seed", 0) or 0),
    }
    entries: list[dict[str, object]] = []

    def _is_defect_owner(owner_class: str | None) -> bool:
        return bool(owner_class and owner_class not in {"none", _DIAGNOSTIC_OWNER_UNKNOWN})

    def _ledger_owner_class(owner_class: str | None) -> str:
        owner = str(owner_class or "").strip() or _DIAGNOSTIC_OWNER_UNKNOWN
        return owner if _is_defect_owner(owner) else "none"

    def _opening_ledger_entry(
        opening: VoxelOpeningVisualFacts,
        *,
        owner_class: str | None,
        is_defect: bool,
        entry_type: str,
        defect_metric: str | None = None,
    ) -> dict[str, object]:
        sub_min_tuple = [
            {
                "group_id": residual.group_id,
                "cut_label": residual.cut_label,
                "side": residual.side,
                "residual_studs": residual.residual_studs,
                "threshold_studs": residual.threshold_studs,
            }
            for residual in opening.sub_min_residuals
        ]
        return {
            **base,
            "entry_type": entry_type,
            "is_defect": bool(is_defect),
            "defect_metric": defect_metric,
            "object_name": opening.object_name,
            "kind": opening.kind,
            "side": opening.side,
            "floor": opening.floor,
            "slot": opening.slot,
            "visual_bounds": list(opening.root_local_bounds),
            "stamped_cut_bounds": {
                "run_min": opening.cut_run_min,
                "run_max": opening.cut_run_max,
                "z_min": opening.cut_z_min,
                "z_max": opening.cut_z_max,
                "plane_normal_axis": opening.plane_normal_axis,
                "plane_run_axis": opening.plane_run_axis,
                "plane_pos": opening.plane_pos,
            },
            "matching_payload_cut_bounds": (
                {
                    "group_id": opening.matching_group_id,
                    "cut_label": opening.matching_cut_label,
                    "run_min": opening.cut_run_min,
                    "run_max": opening.cut_run_max,
                    "z_min": opening.cut_z_min,
                    "z_max": opening.cut_z_max,
                }
                if opening.matching_group_id and opening.matching_cut_label
                else None
            ),
            "nearest_final_cell_edges_by_side": [
                {
                    "side": edge.side,
                    "required": edge.required,
                    "nearest_edge_studs": edge.nearest_edge_studs,
                    "nearest_gap_studs": edge.nearest_gap_studs,
                    "has_adjacent_boundary": edge.has_adjacent_boundary,
                }
                for edge in opening.nearest_final_cell_edges_by_side
            ],
            "actual_max_gap_studs": _json_scalar(opening.actual_max_gap_studs),
            "actual_missing_boundary_sides": list(opening.actual_missing_boundary_sides),
            "same_plane_overlap_cells": list(opening.same_plane_overlap_cell_ids),
            "backfill_cells": list(opening.cut_intrusion_cell_ids),
            "cross_plane_leakage_cells": list(opening.cross_plane_leakage_cell_ids),
            "sub_min_residual_tuple": sub_min_tuple or None,
            "owner_class": str(owner_class or _DIAGNOSTIC_OWNER_UNKNOWN),
            "legacy_owner_class": opening.owner_class,
            "g19_g23": {
                "cut_envelope_match_delta_studs": _json_scalar(opening.cut_envelope_match_delta_studs),
                "opening_visual_seal_gap_studs": _json_scalar(opening.actual_max_gap_studs),
                "roof_exit_uncovered_cut_top_gap": bool(
                    opening.is_roof_exit
                    and opening.is_seating_source
                    and float(opening.cut_z_max) - float(opening.actual_z_max) > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
                ),
            },
        }

    ordinary_door_frames_by_key = {
        (opening.side, opening.floor, opening.slot): opening
        for opening in voxel.opening_visuals
        if opening.kind == "door" and opening.is_door_frame and not opening.is_roof_exit
    }

    def _ordinary_door_unseated(opening: VoxelOpeningVisualFacts) -> bool:
        if opening.kind != "door" or opening.is_roof_exit or opening.is_door_frame:
            return False
        if not bool(opening.object_name.endswith("Door_Main") or opening.object_name.endswith("Door_Rear")):
            return False
        frame = ordinary_door_frames_by_key.get((opening.side, opening.floor, opening.slot))
        if frame is None or frame.cut_envelope_match_delta_studs is None:
            return True
        return frame.cut_envelope_match_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS

    for stamp_issue in voxel.opening_stamp_issues:
        entries.append(
            {
                **base,
                "entry_type": "stamp_defect",
                "is_defect": True,
                "defect_metric": "unstamped_opening_trim",
                "object_name": stamp_issue.object_name,
                "kind": None,
                "side": None,
                "floor": None,
                "slot": None,
                "visual_bounds": None,
                "stamped_cut_bounds": None,
                "matching_payload_cut_bounds": None,
                "nearest_final_cell_edges_by_side": [],
                "actual_max_gap_studs": None,
                "actual_missing_boundary_sides": [],
                "same_plane_overlap_cells": [],
                "backfill_cells": [],
                "cross_plane_leakage_cells": [],
                "sub_min_residual_tuple": None,
                "owner_class": "unstamped_opening_trim",
                "legacy_owner_class": "bad_stamp",
                "reason": stamp_issue.reason,
                "g19_g23": {},
            }
        )
    for deferred in voxel.deferred_unstamped_openings:
        entries.append(
            {
                **base,
                "entry_type": "stamp_defect",
                "is_defect": True,
                "defect_metric": "unstamped_opening_trim",
                "object_name": deferred.object_name,
                "kind": None,
                "side": None,
                "floor": None,
                "slot": None,
                "visual_bounds": None,
                "stamped_cut_bounds": None,
                "matching_payload_cut_bounds": None,
                "nearest_final_cell_edges_by_side": [],
                "actual_max_gap_studs": None,
                "actual_missing_boundary_sides": [],
                "same_plane_overlap_cells": [],
                "backfill_cells": [],
                "cross_plane_leakage_cells": [],
                "sub_min_residual_tuple": None,
                "owner_class": "unstamped_opening_trim",
                "legacy_owner_class": "bad_stamp",
                "reason": deferred.reason,
                "g19_g23": {},
            }
        )
    for opening in voxel.opening_visuals:
        primary_owner = _ledger_owner_class(opening.diagnostic_owner_class)
        primary_is_defect = _is_defect_owner(primary_owner)
        entries.append(
            _opening_ledger_entry(
                opening,
                owner_class=primary_owner,
                is_defect=primary_is_defect,
                entry_type="opening_defect" if primary_is_defect else "opening_observation",
                defect_metric=primary_owner if primary_is_defect else None,
            )
        )
        extra_defects: list[tuple[str, str]] = []
        if _ordinary_door_unseated(opening):
            extra_defects.append(("ordinary_door_unseated", "ordinary_door_unseated"))
        if (
            (opening.is_window_frame or (opening.is_door_frame and not opening.is_roof_exit))
            and opening.cut_envelope_match_delta_studs is not None
            and opening.cut_envelope_match_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
        ):
            extra_defects.append(("cut_envelope_mismatch", "cut_envelope_match_delta_studs"))
        if opening.is_seating_source and opening.actual_max_gap_studs is not None and (
            not math.isfinite(float(opening.actual_max_gap_studs))
            or float(opening.actual_max_gap_studs) > OPENING_VISUAL_SEAL_GAP_MAX_STUDS
        ):
            extra_defects.append(("visual_seal_gap", "opening_visual_seal_gap_studs"))
        if (
            opening.is_roof_exit
            and opening.is_seating_source
            and float(opening.cut_z_max) - float(opening.actual_z_max) > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
        ):
            extra_defects.append(("roof_exit_lintel_unpacked", "roof_exit_uncovered_cut_top_gap"))
        seen_extra: set[str] = {primary_owner} if primary_is_defect else set()
        for owner_class, defect_metric in extra_defects:
            if owner_class in seen_extra:
                continue
            seen_extra.add(owner_class)
            entries.append(
                _opening_ledger_entry(
                    opening,
                    owner_class=owner_class,
                    is_defect=True,
                    entry_type="opening_defect",
                    defect_metric=defect_metric,
                )
            )
    for trim in voxel.trim_attachment_facts:
        owner_class = _ledger_owner_class(trim.owner_class)
        is_defect = _is_defect_owner(owner_class)
        entries.append(
            {
                **base,
                "entry_type": "trim_defect" if is_defect else "trim_observation",
                "is_defect": is_defect,
                "defect_metric": owner_class if is_defect else None,
                "object_name": trim.object_name,
                "object_bucket": trim.source_bucket,
                "kind": "trim",
                "side": trim.side,
                "floor": None,
                "slot": None,
                "visual_bounds": list(trim.root_local_bounds),
                "stamped_cut_bounds": None,
                "matching_payload_cut_bounds": None,
                "nearest_final_cell_edges_by_side": [],
                "actual_max_gap_studs": None,
                "actual_missing_boundary_sides": [],
                "same_plane_overlap_cells": [],
                "backfill_cells": [],
                "cross_plane_leakage_cells": [],
                "sub_min_residual_tuple": None,
                "owner_class": owner_class,
                "g19_g23": {
                    "trim_back_air_gap_studs": _json_scalar(trim.air_gap_studs),
                    "trim_back_overlap_studs": _json_scalar(trim.overlap_studs),
                    "trim_back_face_studs": _json_scalar(trim.trim_back_face_studs),
                    "nearest_wall_face_studs": _json_scalar(trim.nearest_wall_face_studs),
                },
            }
        )
    for frame in voxel.opening_frame_mass_facts:
        owner_class = _ledger_owner_class(frame.owner_class)
        is_defect = _is_defect_owner(owner_class)
        entries.append(
            {
                **base,
                "entry_type": "frame_defect" if is_defect else "frame_observation",
                "is_defect": is_defect,
                "defect_metric": owner_class if is_defect else None,
                "object_name": frame.object_name,
                "object_bucket": frame.source_bucket,
                "kind": frame.kind or "opening_frame",
                "side": frame.side,
                "floor": None,
                "slot": None,
                "visual_bounds": list(frame.root_local_bounds),
                "stamped_cut_bounds": None,
                "matching_payload_cut_bounds": None,
                "nearest_final_cell_edges_by_side": [],
                "actual_max_gap_studs": None,
                "actual_missing_boundary_sides": [],
                "same_plane_overlap_cells": [],
                "backfill_cells": [],
                "cross_plane_leakage_cells": [],
                "sub_min_residual_tuple": None,
                "owner_class": owner_class,
                "g19_g23": {
                    "has_opening_stamp": bool(frame.has_opening_stamp),
                    "frame_silhouette_thickness_studs": _json_scalar(frame.silhouette_thickness_studs),
                    "frame_ring_width_studs": _json_scalar(frame.ring_width_studs),
                    "frame_inner_return_depth_studs": _json_scalar(frame.inner_return_depth_studs),
                    "frame_open_boundary_edge_count": int(frame.open_boundary_edge_count),
                    "frame_outer_perimeter_face_count": int(frame.outer_perimeter_face_count),
                    "frame_sill_or_head_mass_missing": bool(frame.sill_or_head_mass_missing),
                    "frame_gasket_back_overlap_studs": _json_scalar(frame.gasket_back_overlap_studs),
                    "frame_gasket_air_gap_studs": _json_scalar(frame.gasket_air_gap_studs),
                    "cut_envelope_match_delta_studs": _json_scalar(frame.cut_envelope_match_delta_studs),
                },
            }
        )
    for rear in voxel.rear_door_reservation_facts:
        entries.append(
            {
                **base,
                "entry_type": "rear_door_reservation_defect",
                "is_defect": True,
                "defect_metric": "rear_door_reserved_span_window_candidate_overlap_count",
                "object_name": rear.object_name,
                "candidate_object_name": rear.candidate_object_name,
                "object_bucket": None,
                "kind": "rear_door_window_overlap",
                "side": "back",
                "floor": 0,
                "slot": rear.candidate_slot,
                "reserved_span": list(rear.reserved_span),
                "candidate_span": list(rear.candidate_span),
                "overlap_studs": rear.overlap_studs,
                "owner_class": rear.owner_class,
                "g19_g23": {
                    "rear_door_reserved_span_window_overlap_studs": _json_scalar(rear.overlap_studs),
                },
            }
        )
    for roof in voxel.roof_exit_top_closure_facts:
        is_defect = roof.coverage_ratio < ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
        entries.append(
            {
                **base,
                "entry_type": "roof_exit_top_closure_defect" if is_defect else "roof_exit_top_closure_observation",
                "is_defect": is_defect,
                "defect_metric": "roof_exit_top_band_coverage_ratio" if is_defect else None,
                "object_name": roof.door_object_name,
                "closure_object_names": list(roof.closure_object_names),
                "rejected_object_names": list(roof.rejected_object_names),
                "object_bucket": None,
                "kind": "roof_exit_lintel_closure",
                "side": "roof_exit",
                "floor": None,
                "slot": -1,
                "required_band": list(roof.required_band),
                "coverage_ratio": _json_scalar(roof.coverage_ratio),
                "owner_class": roof.owner_class,
                "g19_g23": {
                    "roof_exit_top_band_coverage_ratio": _json_scalar(roof.coverage_ratio),
                    "roof_exit_lintel_closure_present_count": int(voxel.roof_exit_lintel_closure_present_count),
                    "roof_exit_lintel_required_count": int(voxel.roof_exit_lintel_required_count),
                },
            }
        )
    for terrace in voxel.terrace_exit_top_facts:
        is_defect = (not terrace.owner_valid) or terrace.coverage_ratio < ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
        entries.append(
            {
                **base,
                "entry_type": "terrace_exit_top_defect" if is_defect else "terrace_exit_top_observation",
                "is_defect": is_defect,
                "defect_metric": "terrace_exit_top_band_coverage_ratio" if is_defect else None,
                "object_name": terrace.object_name,
                "object_bucket": None,
                "kind": "terrace_exit_top_owner",
                "side": terrace.side,
                "floor": terrace.floor,
                "slot": terrace.slot,
                "coverage_ratio": _json_scalar(terrace.coverage_ratio),
                "owner_valid": bool(terrace.owner_valid),
                "allowed_frame_inflation": bool(terrace.allowed_frame_inflation),
                "owner_class": terrace.owner_class if terrace.owner_valid else "terrace_exit_classification",
                "g19_g23": {
                    "terrace_exit_top_band_coverage_ratio": _json_scalar(terrace.coverage_ratio),
                    "terrace_exit_allowed_frame_inflation": bool(terrace.allowed_frame_inflation),
                },
            }
        )
    aggregate_checks = (
        (
            "ordinary_door_unseated",
            "ordinary_door_panel_height_delta_studs",
            voxel.ordinary_door_panel_height_delta_studs is not None
            and voxel.ordinary_door_panel_height_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS,
            _json_scalar(voxel.ordinary_door_panel_height_delta_studs),
        ),
        (
            "roof_exit_lintel_unpacked",
            "roof_exit_door_panel_height_delta_studs",
            voxel.roof_exit_door_panel_height_delta_studs is not None
            and voxel.roof_exit_door_panel_height_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS,
            _json_scalar(voxel.roof_exit_door_panel_height_delta_studs),
        ),
        (
            "roof_exit_lintel_unpacked",
            "roof_exit_lintel_closure_present_count",
            voxel.roof_exit_lintel_closure_present_count != voxel.roof_exit_lintel_required_count,
            {
                "present": int(voxel.roof_exit_lintel_closure_present_count),
                "required": int(voxel.roof_exit_lintel_required_count),
            },
        ),
        (
            "floating_trim_band",
            "townhouse_like_parapet_height_min_studs",
            voxel.townhouse_like_parapet_height_min_studs is not None
            and voxel.townhouse_like_parapet_height_min_studs < RESIDENTIAL_BORDER_MIN_STUDS,
            _json_scalar(voxel.townhouse_like_parapet_height_min_studs),
        ),
    )
    for owner_class, defect_metric, is_defect, measured_value in aggregate_checks:
        if not is_defect:
            continue
        entries.append(
            {
                **base,
                "entry_type": "aggregate_defect",
                "is_defect": True,
                "defect_metric": defect_metric,
                "object_name": None,
                "object_bucket": None,
                "kind": "aggregate",
                "side": None,
                "floor": None,
                "slot": None,
                "visual_bounds": None,
                "stamped_cut_bounds": None,
                "matching_payload_cut_bounds": None,
                "nearest_final_cell_edges_by_side": [],
                "actual_max_gap_studs": None,
                "actual_missing_boundary_sides": [],
                "same_plane_overlap_cells": [],
                "backfill_cells": [],
                "cross_plane_leakage_cells": [],
                "sub_min_residual_tuple": None,
                "owner_class": owner_class,
                "g19_g23": {defect_metric: measured_value},
            }
        )
    return tuple(entries)
