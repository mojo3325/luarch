from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Euler, Vector

from .. import constants
from ..export_contract import (
    ROLE_BALCONY_ACCESS_OPENING,
    ROLE_BALCONY_FLOOR,
    ROLE_BALCONY_RAIL,
    ROLE_ENTRY_LANDING,
    ROLE_ENTRY_WEDGE,
    ROLE_OPEN_WINDOW_OPENING,
    ROLE_PODIUM_BLOCKER,
    ROLE_PROP_BOX,
    ROLE_SHELL,
    ROLE_WINDOW_CLOSED,
)
from .building_layout import (
    FRONTAGE_TYPE_INDUSTRIAL_DEPOT,
    FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE,
    FRONTAGE_TYPE_TIMBER_ROWHOUSE,
    AC_DEPTH,
    BALCONY_DEPTH,
    BALCONY_RAIL_HEIGHT,
    BALCONY_RAIL_THICKNESS,
    BALCONY_SLAB_THICKNESS,
    BALCONY_STRIP_DEPTH,
    BALCONY_STRIP_EXTRA_SPAN,
    ENTRY_CANOPY_HEIGHT,
    ENTRY_CANOPY_THICKNESS,
    ENTRY_DETAIL_PROUD_OFFSET,
    FACADE_BAND_DEPTH,
    FACADE_BAND_HEIGHT,
    GROUND_FLOOR_DEFENSIVE_BASE,
    GROUND_FLOOR_MIXED_WINDOWS,
    GROUND_FLOOR_OPEN_ENTRY,
    GROUND_PLINTH_DEPTH,
    INNER_FRAME_PROUD_OFFSET,
    MASSING_PROFILE_BASE_HEAVY,
    WALL_PIPE_BEND_LENGTH_MAX,
    WALL_PIPE_BEND_LENGTH_MIN,
    WALL_PIPE_CLAMP_HEIGHT,
    WALL_PIPE_DEPTH,
    WALL_PIPE_STANDOFF,
    WALL_PIPE_TWIN_OFFSET,
    WALL_PIPE_WIDTH,
    WINDOW_FRAME_OVERLAP,
    WINDOW_FRAME_PROUD_OFFSET,
    WINDOW_PANEL_OVERLAP,
    WINDOW_PANEL_THICKNESS,
    WINDOW_STATE_BALCONY,
    WINDOW_STATE_CLOSED,
    WINDOW_STATE_MASK,
    WINDOW_STATE_OPEN,
    WINDOW_STATE_STAIR,
    WINDOW_TRIM_DEPTH,
    WINDOW_TRIM_INSET,
    WINDOW_WALL_OVERLAP,
    BalconyPlan,
    _base_elevation,
    _front_entry_envelope,
    _is_multi_pane_window_profile,
    _is_panoramic_window_profile,
    _is_residential_wide,
    _is_small_square_window_profile,
    _is_tall_narrow_window_profile,
    _level_base_z,
    _opening_inset_coord,
    _opening_location,
    _orientation_rotation,
    _roof_surface_z,
    _side_sign,
    _stable_unit_float,
    _surface_coord,
    _window_verticals,
    subtract_blocked_spans,
)
from .layout_facade_planning import (
    _balcony_floor_enabled,
    _balcony_lookup,
    _balcony_plans_for_side,
    _facade_window_layouts,
    _frontage_variant,
    _is_hangar_frontage,
    _is_industrial_frontage,
    _is_market_hall_frontage,
    _is_storefront_frontage,
    _is_timber_frontage,
    _mandatory_ac_slot,
    _market_hall_support_window_side,
    _planned_window_states,
    _panel_material,
    _selected_balcony_sides,
    _stair_window_slots,
    _trim_material,
    _slot_intervals,
    _solid_facade_spans,
    _wall_material_for_floor,
)
from .building_support import (
    _assign_material,
    _create_box,
    _create_composite_box_object,
    _frame_mesh,
    _mark_door_leaf,
    _mark_generated,
    _mark_section,
    _mark_wall_section,
    _mark_service_detail,
    _name,
    _parent_to,
    _solid_stepped_flight_mesh,
)
from .runtime_markers import RuntimeMarkerEmitter, _emit_object_proxy_box
from .specs import ROOF_MODE_GABLE, ROOF_MODE_SHED

from .building_facade_opening_slots import (
    _append_planned_wall_parts,
    _plan_linear_wall_fragment,
    register_linear_wall_plane as _register_linear_wall_plane,
    build_window_slot as _build_window_slot,
    create_opening_box as _create_opening_box,
    create_wall_segment as _create_wall_segment,
    wall_opening_cut_metadata as _wall_opening_cut_metadata,
    canonical_wall_cut_rect as _canonical_wall_cut_rect,
    _window_visual_cut_rect,
    slot_opening_profile as _slot_opening_profile,
)
from .building_occupancy import OPENING_VISUAL_CLEARANCE_STUDS, OccupancyAuthoringSession

def _clamp_generic_slot_state(spec, side_key: str, floor_index: int, state: str) -> str:
    if _is_hangar_frontage(spec):
        return WINDOW_STATE_MASK
    if _is_market_hall_frontage(spec):
        if floor_index == 0:
            return WINDOW_STATE_MASK
        return state
    if _is_industrial_frontage(spec):
        if state in {WINDOW_STATE_MASK, WINDOW_STATE_BALCONY, WINDOW_STATE_STAIR}:
            return state
        return WINDOW_STATE_OPEN
    return state

def _blocked_facade_ac_slots(
    count: int,
    balcony_leaders: dict[int, BalconyPlan],
    balcony_members: dict[int, int],
    protected_openings: dict[int, int],
) -> set[int]:
    blocked_for_ac = {idx for idx, leader in balcony_members.items() if leader in balcony_leaders}
    for idx in list(blocked_for_ac):
        blocked_for_ac.update({idx - 1, idx + 1})
    blocked_for_ac = {idx for idx in blocked_for_ac if 0 <= idx < count}
    blocked_for_ac.update(protected_openings)
    return blocked_for_ac

def _build_timber_siding_overlay(
    prefix,
    side_label: str,
    side_key: str,
    orientation: str,
    wall_pos: float,
    floor_index: int,
    base_z: float,
    floor_height: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    spec,
    *,
    side_facts,
    opening_bands_override: list[tuple[float, float, float, float]] | None = None,
):
    if not _is_timber_frontage(spec):
        return

    floor_facts = side_facts["floor_facts"][floor_index]
    if not floor_facts.get("active", True):
        return

    length = float(floor_facts.get("length", side_facts["length"]))
    along_center = float(floor_facts.get("along_center", 0.0))
    if length <= 0.2:
        return

    frontage_variant = _frontage_variant(spec)
    rowhouse_frontage = frontage_variant == FRONTAGE_TYPE_TIMBER_ROWHOUSE
    course_step = 0.26 if rowhouse_frontage else 0.32
    course_height = 0.14 if rowhouse_frontage else 0.16
    board_depth = max(0.02, min(0.03, wall_t * 0.14))
    board_center = _surface_coord(side_key, wall_pos, wall_t, board_depth, exterior=True, offset=0.0)
    facade_mid_z = base_z + floor_height / 2
    slot_intervals = floor_facts.get("slot_intervals", side_facts["slot_intervals"])
    planned_states = floor_facts["planned_states"]
    facade_start = along_center - length / 2
    facade_end = along_center + length / 2
    floor_grid_z = float(_level_base_z(spec, floor_index))
    opening_bands = _merge_opening_bands(
        _window_envelope_bands_for_floor(spec, side_key, floor_index, slot_intervals, planned_states),
        opening_bands_override,
    )
    opening_bands = [
        (
            float(canonical[0]) - along_center,
            float(canonical[1]) - along_center,
            float(canonical[2]),
            float(canonical[3]),
        )
        for canonical in (
            _canonical_wall_cut_rect(
                (float(along_min), float(along_max), float(min_z), float(max_z)),
                grid_origin_run=facade_start,
                grid_origin_z=floor_grid_z,
                plane_run_min=facade_start,
                plane_run_max=facade_end,
                plane_z_min=floor_grid_z,
                plane_z_max=floor_grid_z + float(floor_height),
            )
            for along_min, along_max, min_z, max_z in opening_bands
        )
    ]
    trim_material = _trim_material(
        materials_map,
        spec.facade_family,
        facade_mode=getattr(spec, "facade_mode", None),
    )
    board_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    trim_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []

    def _solid_spans(z_min: float, z_max: float, *, padding: float, minimum_span: float) -> list[tuple[float, float]]:
        spans = [(-length / 2, length / 2)]
        for along_min, along_max, min_z, max_z in opening_bands:
            if max_z <= z_min + 0.01 or min_z >= z_max - 0.01:
                continue
            spans = subtract_blocked_spans(
                spans,
                along_min,
                along_max,
                padding=padding,
                minimum_span=minimum_span,
            )
            if not spans:
                break
        return spans

    skirt_bottom = base_z + 0.04
    skirt_top = min(base_z + floor_height - 0.14, base_z + max(0.18, min(0.28, floor_height * 0.14)))
    for span_start, span_end in _solid_spans(skirt_bottom, skirt_top, padding=0.06, minimum_span=0.14):
        span = span_end - span_start
        if span <= 0.14:
            continue
        trim_parts.append(
            (
                (span, board_depth, skirt_top - skirt_bottom),
                (((span_start + span_end) / 2), 0.0, (skirt_bottom + skirt_top) / 2 - facade_mid_z),
            )
        )

    frieze_height = max(0.14, min(0.22, floor_height * 0.11))
    frieze_top = base_z + floor_height - 0.06
    frieze_bottom = max(skirt_top + 0.18, frieze_top - frieze_height)
    for span_start, span_end in _solid_spans(frieze_bottom, frieze_top, padding=0.04, minimum_span=0.16):
        span = span_end - span_start
        if span <= 0.16:
            continue
        trim_parts.append(
            (
                (span, board_depth, frieze_top - frieze_bottom),
                (((span_start + span_end) / 2), 0.0, (frieze_bottom + frieze_top) / 2 - facade_mid_z),
            )
        )

    course_bottom = skirt_top + 0.04
    course_top_limit = frieze_bottom - 0.04
    while course_bottom + 0.04 < course_top_limit:
        band_bottom = course_bottom
        band_top = min(course_top_limit, course_bottom + course_height)
        spans = _solid_spans(band_bottom, band_top, padding=0.05, minimum_span=0.12)
        band_height = band_top - band_bottom
        if spans and band_height > 0.02:
            band_center_z = band_bottom + band_height / 2
            for span_start, span_end in spans:
                span = span_end - span_start
                if span <= 0.12:
                    continue
                board_parts.append(
                    (
                        (span, board_depth, band_height),
                        (((span_start + span_end) / 2), 0.0, band_center_z - facade_mid_z),
                    )
                )
        course_bottom += course_step

    if board_parts:
        boards = _create_composite_box_object(
            _name(prefix, f"{side_label}_F{floor_index:02d}_TimberBoards"),
            board_parts,
            _opening_location(orientation, along_center, board_center, facade_mid_z),
            collection,
            parent,
            _panel_material(
                materials_map,
                spec.facade_family,
                facade_mode=getattr(spec, "facade_mode", None),
            ),
            rotation=_orientation_rotation(orientation),
        )
        if boards is not None:
            _mark_wall_section(
                _mark_generated(
                    boards,
                    tbg_timber_siding=True,
                    tbg_facade_side=side_key,
                    tbg_facade_floor=int(floor_index),
                ),
                "Section_Walls_ExteriorSurfaceTile",
            )

    if trim_parts:
        trim_overlay = _create_composite_box_object(
            _name(prefix, f"{side_label}_F{floor_index:02d}_TimberTrimBands"),
            trim_parts,
            _opening_location(orientation, along_center, board_center, facade_mid_z),
            collection,
            parent,
            trim_material,
            rotation=_orientation_rotation(orientation),
        )
        if trim_overlay is not None:
            _mark_section(
                _mark_generated(
                    trim_overlay,
                    tbg_timber_siding=True,
                    tbg_timber_trim_band=True,
                    tbg_facade_side=side_key,
                    tbg_facade_floor=int(floor_index),
                ),
                "Section_Walls_Trim",
                hide_with_walls=True,
            )

    corner_depth = max(0.03, min(0.038, wall_t * 0.18))
    corner_width = max(0.16, min(0.22, length * 0.07))
    trim_center = _surface_coord(side_key, wall_pos, wall_t, corner_depth, exterior=True, offset=0.004)
    trim_height = max(0.28, floor_height - 0.06)
    trim_z = base_z + trim_height / 2
    for edge_label, along_coord in (
        ("L", along_center - length / 2 + corner_width / 2),
        ("R", along_center + length / 2 - corner_width / 2),
    ):
        trim = _create_opening_box(
            _name(prefix, f"{side_label}_F{floor_index:02d}_TimberCorner_{edge_label}"),
            orientation,
            corner_width,
            corner_depth,
            trim_height,
            along_coord,
            trim_center,
            trim_z,
            collection,
            parent,
            trim_material,
        )
        _mark_section(
            _mark_generated(
                trim,
                tbg_timber_siding=True,
                tbg_timber_corner_trim=True,
                tbg_facade_side=side_key,
                tbg_facade_floor=int(floor_index),
            ),
            "Section_Walls_Trim",
            hide_with_walls=True,
        )

def _window_envelope_bands_by_slot_for_floor(
    spec,
    side_key: str,
    floor_index: int,
    slot_intervals: tuple[tuple[int, float, float], ...],
    planned_states: dict[int, str],
) -> dict[int, tuple[float, float, float, float]]:
    if side_key == "front" and floor_index == 0:
        return {}

    bounds: dict[int, tuple[float, float, float, float]] = {}
    base_z = _level_base_z(spec, floor_index)
    for slot_index, slot_min, slot_max in slot_intervals:
        state = _clamp_generic_slot_state(
            spec,
            side_key,
            floor_index,
            planned_states.get(slot_index, WINDOW_STATE_CLOSED),
        )
        if state == WINDOW_STATE_MASK:
            continue
        _opening_width, sill_h, opening_h, _top_h = _slot_opening_profile(
            spec,
            state,
            slot_max - slot_min,
            spec.floor_height,
            side_key=side_key,
            floor_index=floor_index,
            slot_index=slot_index,
        )
        band = _window_visual_cut_rect(
            spec=spec,
            state=state,
            side_key=side_key,
            floor_index=floor_index,
            slot_index=slot_index,
            slot_min=slot_min,
            slot_max=slot_max,
            base_z=base_z,
            floor_height=spec.floor_height,
            opening_width=_opening_width,
            sill_h=sill_h,
            opening_h=opening_h,
        )
        if state == WINDOW_STATE_BALCONY:
            band = (
                float(band[0]),
                float(band[1]),
                float(base_z),
                float(band[3]),
            )
        bounds[int(slot_index)] = band
    return bounds


def _window_envelope_bands_for_floor(
    spec,
    side_key: str,
    floor_index: int,
    slot_intervals: tuple[tuple[int, float, float], ...],
    planned_states: dict[int, str],
) -> list[tuple[float, float, float, float]]:
    return list(
        _window_envelope_bands_by_slot_for_floor(
            spec,
            side_key,
            floor_index,
            slot_intervals,
            planned_states,
        ).values()
    )


def _merge_opening_bands(
    *band_groups: list[tuple[float, float, float, float]] | tuple[tuple[float, float, float, float], ...] | None,
) -> list[tuple[float, float, float, float]]:
    merged: list[tuple[float, float, float, float]] = []
    seen: set[tuple[float, float, float, float]] = set()
    for band_group in band_groups:
        for band in band_group or ():
            normalized = (float(band[0]), float(band[1]), float(band[2]), float(band[3]))
            if normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _sloped_top_front_shell_height(spec, *, side_key: str, floor_index: int, floor_height: float) -> float:
    roof_mode = str(getattr(spec, "roof_mode", "")).upper()
    if int(floor_index) == max(0, int(getattr(spec, "floor_count", 0)) - 1) and roof_mode in {
        ROOF_MODE_GABLE,
        ROOF_MODE_SHED,
    }:
        roof_axis_x = float(getattr(spec, "width", 0.0)) >= float(getattr(spec, "depth", 0.0))
        sloped_shell_sides = {"front", "back"} if roof_axis_x else {"left", "right"}
        if side_key in sloped_shell_sides:
            shell_overlap = max(0.05, float(spec.slab_thickness) * 0.45)
            return max(0.0, float(floor_height) - float(spec.slab_thickness) + shell_overlap)
    return float(floor_height)


def _strip_lower_facade_coplanar_bottom_caps(parent, *, side_key: str, floor_index: int, seam_z: float) -> None:
    if floor_index != 0:
        return
    if side_key not in {"front", "back", "left", "right"}:
        return
    if parent is None:
        return

    target_buckets = {"Section_Walls_Exterior", "Section_Openings_Trim_Wall"}
    if side_key == "front":
        target_buckets.add("Section_Walls_Trim")
    seam_z = float(seam_z)
    z_epsilon = 1e-3

    for child in getattr(parent, "children_recursive", ()):
        if getattr(child, "type", "") != "MESH":
            continue
        if str(child.get("tbg_facade_side", "")) != side_key:
            continue
        try:
            facade_floor = int(child.get("tbg_facade_floor", -1))
        except (TypeError, ValueError):
            facade_floor = -1
        if facade_floor != floor_index:
            continue
        if str(child.get("tbg_section_bucket", "")) not in target_buckets:
            continue

        mesh = getattr(child, "data", None)
        if mesh is None:
            continue
        bm = bmesh.new()
        bm.from_mesh(mesh)
        world_matrix = child.matrix_world.copy()
        normal_matrix = world_matrix.to_3x3()
        faces_to_delete = []
        for face in bm.faces:
            world_normal = (normal_matrix @ face.normal).normalized()
            if world_normal.z > -0.5:
                continue
            world_zs = [(world_matrix @ vert.co).z for vert in face.verts]
            if world_zs and max(abs(z - seam_z) for z in world_zs) <= z_epsilon:
                faces_to_delete.append(face)
        if faces_to_delete:
            bmesh.ops.delete(bm, geom=faces_to_delete, context="FACES")
            bm.to_mesh(mesh)
            mesh.update()
        bm.free()


def _emit_hangar_shell_piece(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    start: float,
    end: float,
    base_z: float,
    height: float,
    wall_t: float,
    collection,
    parent,
    material,
    *,
    floor_index: int,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    segment_name = _name(prefix, suffix)
    _register_linear_wall_plane(
        occupancy_author,
        orientation=orientation,
        wall_pos=wall_pos,
        start=start,
        end=end,
        base_z=base_z,
        height=height,
        wall_t=wall_t,
        material=material,
        source_bucket="Section_Walls_Exterior",
        source_name=f"{segment_name}:plane",
        staged_object_name=segment_name,
    )
    planned_fragment = _plan_linear_wall_fragment(
        orientation=orientation,
        wall_pos=wall_pos,
        start=start,
        end=end,
        base_z=base_z,
        height=height,
        wall_t=wall_t,
        ref_along=(start + end) / 2,
        ref_z=base_z + height / 2,
        material=material,
        source_bucket="Section_Walls_Exterior",
        source_name=segment_name,
        staged_object_name=segment_name,
        marker_metadata={"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)},
    )
    segment = _create_wall_segment(
        segment_name,
        orientation,
        wall_pos,
        start,
        end,
        base_z,
        height,
        wall_t,
        collection,
        parent,
        material,
    )
    segment = _mark_wall_section(
        _mark_generated(
            segment,
            tbg_hangar_shell=True,
            tbg_facade_side=side_key,
            tbg_facade_floor=int(floor_index),
        ),
        "Section_Walls_Exterior",
    )
    if runtime_emitter is not None and segment is not None:
        span = end - start
        runtime_emitter.emit_box(
            role=ROLE_SHELL,
            size=(span, wall_t, height) if orientation == "X" else (wall_t, span, height),
            location=tuple(float(value) for value in segment.location),
            rotation=tuple(float(value) for value in segment.rotation_euler),
            source_name=segment.name,
            metadata_values={"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)},
        )

def _build_hangar_shell_face(
    prefix,
    side_label: str,
    side_key: str,
    orientation: str,
    wall_pos: float,
    floor_index: int,
    base_z: float,
    floor_height: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    spec,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    wall_material = _wall_material_for_floor(materials_map, spec, floor_index)
    face_length = spec.width if orientation == "X" else spec.depth
    if side_key == "front" and floor_index == 0:
        return False
    if floor_index > 0:
        return False
    if side_key == "back":
        return False
    if side_key in {"left", "right"}:
        wall_height = floor_height
        bay_count = 3 if face_length <= 15.2 else 4
        side_margin = max(0.9, face_length * 0.075)
        bay_width = min(3.15, max(2.3, face_length * 0.17))
        usable_length = face_length - side_margin * 2
        gap = max(0.5, (usable_length - bay_width * bay_count) / max(1, bay_count - 1))
        strip_start = -face_length / 2 + side_margin
        bay_spans: list[tuple[float, float]] = []
        for bay_index in range(bay_count):
            span_start = strip_start + bay_index * (bay_width + gap)
            span_end = span_start + bay_width
            if span_end > face_length / 2 - side_margin + 1e-4:
                break
            bay_spans.append((span_start, span_end))

        sill_h = 0.52
        window_h = max(2.55, min(3.28, wall_height - sill_h - 0.42))
        lintel_height = max(0.18, wall_height - sill_h - window_h)
        fill_depth = max(0.05, wall_t * 0.22)
        opening_cuts = [
            ("hangar_window", slot_min, slot_max, base_z + sill_h, base_z + sill_h + window_h)
            for slot_min, slot_max in bay_spans
        ]
        plane_registered = _register_linear_wall_plane(
            occupancy_author,
            orientation=orientation,
            wall_pos=wall_pos,
            start=-face_length / 2,
            end=face_length / 2,
            base_z=base_z,
            height=wall_height,
            wall_t=wall_t,
            material=wall_material,
            source_bucket="Section_Walls_Exterior",
            source_name=_name(prefix, f"{side_label}_F{floor_index:02d}_HangarPlane"),
            staged_object_name=_name(prefix, f"{side_label}_F{floor_index:02d}_HangarPlane"),
            rect_cuts=opening_cuts,
        ) is not None
        piece_occupancy_author = None if plane_registered else occupancy_author
        shell_cursor = -face_length / 2
        for span_index, (slot_min, slot_max) in enumerate(bay_spans):
            solid_end = slot_min
            if solid_end - shell_cursor > 0.08:
                _emit_hangar_shell_piece(
                    prefix,
                    f"{side_label}_F{floor_index:02d}_HangarShell_{span_index:02d}",
                    orientation,
                    side_key,
                    wall_pos,
                    shell_cursor,
                    solid_end,
                    base_z,
                    wall_height,
                    wall_t,
                    collection,
                    parent,
                    wall_material,
                    floor_index=floor_index,
                    occupancy_author=piece_occupancy_author,
                    runtime_emitter=runtime_emitter,
                )
            shell_cursor = slot_max
        if face_length / 2 - shell_cursor > 0.08:
            _emit_hangar_shell_piece(
                prefix,
                f"{side_label}_F{floor_index:02d}_HangarShell_End",
                orientation,
                side_key,
                wall_pos,
                shell_cursor,
                face_length / 2,
                base_z,
                wall_height,
                wall_t,
                collection,
                parent,
                wall_material,
                floor_index=floor_index,
                occupancy_author=piece_occupancy_author,
                runtime_emitter=runtime_emitter,
            )

        target_open = max(
            0,
            min(
                len(bay_spans),
                max(
                    int(getattr(spec, "combat_open_window_min", 0)),
                    int(round(len(bay_spans) * max(0.0, min(1.0, float(getattr(spec, "open_window_ratio", 0.0)))))),
                ),
            ),
        )
        open_slots = {
            idx
            for idx, _score in sorted(
                (
                    (
                        idx,
                        _stable_unit_float(spec.seed, "hangar_window_open_rank", side_key, floor_index, idx),
                    )
                    for idx in range(len(bay_spans))
                ),
                key=lambda item: item[1],
            )[:target_open]
        }
        for slot_index, (slot_min, slot_max) in enumerate(bay_spans):
            _emit_hangar_shell_piece(
                prefix,
                f"{side_label}_HangarBaySill_{slot_index:02d}",
                orientation,
                side_key,
                wall_pos,
                slot_min,
                slot_max,
                base_z,
                sill_h,
                wall_t,
                collection,
                parent,
                wall_material,
                floor_index=floor_index,
                occupancy_author=piece_occupancy_author,
                runtime_emitter=runtime_emitter,
            )
            _emit_hangar_shell_piece(
                prefix,
                f"{side_label}_HangarBayLintel_{slot_index:02d}",
                orientation,
                side_key,
                wall_pos,
                slot_min,
                slot_max,
                base_z + sill_h + window_h,
                lintel_height,
                wall_t,
                collection,
                parent,
                wall_material,
                floor_index=floor_index,
                occupancy_author=piece_occupancy_author,
                runtime_emitter=runtime_emitter,
            )

            slot_center = (slot_min + slot_max) / 2
            cut_clearance = max(0.0, float(OPENING_VISUAL_CLEARANCE_STUDS))
            fill_size = max(0.18, slot_max - slot_min + cut_clearance * 2.0)
            fill_height = max(0.18, window_h + cut_clearance * 2.0)
            if slot_index in open_slots:
                continue
            fill = _create_box(
                _name(prefix, f"{side_label}_HangarBayFill_{slot_index:02d}"),
                (fill_depth, fill_size, fill_height) if orientation == "Y" else (fill_size, fill_depth, fill_height),
                (
                    wall_pos if orientation == "Y" else slot_center,
                    slot_center if orientation == "Y" else wall_pos,
                    base_z + sill_h + window_h / 2,
                ),
                collection,
                parent,
                materials_map["window_fill"],
            )
            opening_cut_metadata = _wall_opening_cut_metadata(
                kind="window",
                orientation=orientation,
                side_key=side_key,
                floor_index=floor_index,
                slot_index=slot_index,
                wall_pos=wall_pos,
                cut_rect=(slot_min, slot_max, base_z + sill_h, base_z + sill_h + window_h),
            )
            _mark_section(
                _mark_generated(
                    fill,
                    tbg_hangar_window=True,
                    tbg_facade_side=side_key,
                    tbg_facade_floor=int(floor_index),
                    **opening_cut_metadata,
                ),
                "Section_Openings_WindowFill",
                merge_allowed=False,
            )
        return False

    wall_height = floor_height
    _emit_hangar_shell_piece(
        prefix,
        f"{side_label}_F{floor_index:02d}_HangarShell",
        orientation,
        side_key,
        wall_pos,
        -face_length / 2,
        face_length / 2,
        base_z,
        wall_height,
        wall_t,
        collection,
        parent,
        wall_material,
        floor_index=floor_index,
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
    )
    return False

def _build_facade_wall(
    prefix,
    side_label: str,
    side_key: str,
    orientation: str,
    wall_pos: float,
    floor_index: int,
    base_z: float,
    floor_height: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    spec,
    forced_ac_slot: int | None = None,
    *,
    side_facts,
    opening_bands_override: list[tuple[float, float, float, float]] | None = None,
    rect_cuts_override: list[tuple[float, float, float, float]] | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    floor_facts = side_facts["floor_facts"][floor_index]
    if not floor_facts.get("active", True):
        return False
    shell_floor_height = _sloped_top_front_shell_height(
        spec,
        side_key=side_key,
        floor_index=floor_index,
        floor_height=floor_height,
    )
    if shell_floor_height <= 1e-4:
        return False
    if _is_hangar_frontage(spec):
        return _build_hangar_shell_face(
            prefix,
            side_label,
            side_key,
            orientation,
            wall_pos,
            floor_index,
            base_z,
            shell_floor_height,
            wall_t,
            collection,
            parent,
            materials_map,
            spec,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )
    if side_key == "front" and floor_index == 0 and (
        _is_storefront_frontage(spec) or _is_industrial_frontage(spec) or _is_market_hall_frontage(spec)
    ):
        return False

    count, slot_width, pier_width = floor_facts.get("layout", side_facts["layout"])
    length = float(floor_facts.get("length", side_facts["length"]))
    wall_along_center = float(floor_facts.get("along_center", 0.0))
    intervals = floor_facts.get("slot_intervals", side_facts["slot_intervals"])
    planned_states = floor_facts["planned_states"]
    protected_openings = floor_facts["protected_openings"]
    blocked_for_ac = floor_facts["blocked_for_ac"]
    mandatory_ac_idx = floor_facts["mandatory_ac_slot"]
    balcony_leaders = floor_facts["balcony_leaders"]
    balcony_members = floor_facts["balcony_members"]
    wall_material = _wall_material_for_floor(materials_map, spec, floor_index)
    piers_object_name = _name(prefix, f"{side_label}_F{floor_index:02d}_Piers")
    slot_shell_object_name = _name(prefix, f"{side_label}_F{floor_index:02d}_SlotShell")
    pier_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    pier_marker_parts: list[tuple[tuple[float, float, float], tuple[float, float, float], str, dict]] = []
    slot_shell_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    slot_shell_marker_parts: list[tuple[tuple[float, float, float], tuple[float, float, float], str, dict]] = []
    facade_start = wall_along_center - length / 2
    facade_end = wall_along_center + length / 2
    floor_grid_z = float(_level_base_z(spec, floor_index))
    facade_mid_z = base_z + shell_floor_height / 2
    window_opening_bands = _window_envelope_bands_for_floor(spec, side_key, floor_index, intervals, planned_states)
    window_rect_cuts = tuple(
        _canonical_wall_cut_rect(
            band,
            grid_origin_run=facade_start,
            grid_origin_z=floor_grid_z,
            plane_run_min=facade_start,
            plane_run_max=facade_end,
            plane_z_min=floor_grid_z,
            plane_z_max=floor_grid_z + shell_floor_height,
        )
        for band in window_opening_bands
    )
    # Rear-through door overrides follow the ordinary-door contract: the wall
    # plane applies the same clearance as the front door, not a grid-sized window aperture.
    override_rect_cuts = tuple(rect_cuts_override or ())
    rect_cuts = tuple(("opening", band_min, band_max, band_z_min, band_z_max, 0.0) for band_min, band_max, band_z_min, band_z_max in window_rect_cuts) + tuple(
        ("opening", band_min, band_max, band_z_min, band_z_max) for band_min, band_max, band_z_min, band_z_max in override_rect_cuts
    )
    plane_registered = _register_linear_wall_plane(
        occupancy_author,
        orientation=orientation,
        wall_pos=wall_pos,
        start=facade_start,
        end=facade_end,
        base_z=base_z,
        height=shell_floor_height,
        wall_t=wall_t,
        material=wall_material,
        source_bucket="Section_Walls_Exterior",
        source_name=f"{slot_shell_object_name}:plane",
        staged_object_name=slot_shell_object_name,
        rect_cuts=rect_cuts,
    ) is not None
    child_occupancy_author = None if plane_registered else occupancy_author
    # Only explicit override bands are allowed to suppress facade piers.
    # Generic window-envelope bands describe slot openings and must not erase shell piers.
    pier_suppression_bands = opening_bands_override if opening_bands_override is not None else ()

    def _subtract_band_from_rect(
        rects: list[tuple[float, float, float, float]],
        *,
        band_min: float,
        band_max: float,
        band_z_min: float,
        band_z_max: float,
    ) -> list[tuple[float, float, float, float]]:
        next_rects: list[tuple[float, float, float, float]] = []
        for rect_min, rect_max, rect_z_min, rect_z_max in rects:
            cut_min = max(rect_min, band_min)
            cut_max = min(rect_max, band_max)
            cut_z_min = max(rect_z_min, band_z_min)
            cut_z_max = min(rect_z_max, band_z_max)
            if cut_max <= cut_min + 1e-4 or cut_z_max <= cut_z_min + 1e-4:
                next_rects.append((rect_min, rect_max, rect_z_min, rect_z_max))
                continue
            for candidate_min, candidate_max, candidate_z_min, candidate_z_max in (
                (rect_min, cut_min, rect_z_min, rect_z_max),
                (cut_max, rect_max, rect_z_min, rect_z_max),
                (cut_min, cut_max, rect_z_min, cut_z_min),
                (cut_min, cut_max, cut_z_max, rect_z_max),
            ):
                if candidate_max - candidate_min > 1e-4 and candidate_z_max - candidate_z_min > 1e-4:
                    next_rects.append((candidate_min, candidate_max, candidate_z_min, candidate_z_max))
        return next_rects

    for idx in range(count + 1):
        pier_start = wall_along_center - length / 2 + idx * (slot_width + pier_width)
        pier_end = pier_start + pier_width
        pier_rects: list[tuple[float, float, float, float]] = [
            (pier_start, pier_end, base_z, base_z + shell_floor_height)
        ]
        for band_min, band_max, band_z_min, band_z_max in pier_suppression_bands:
            pier_rects = _subtract_band_from_rect(
                pier_rects,
                band_min=float(band_min),
                band_max=float(band_max),
                band_z_min=float(band_z_min),
                band_z_max=float(band_z_max),
            )
            if not pier_rects:
                break
        for rect_min, rect_max, rect_z_min, rect_z_max in pier_rects:
            planned_fragment = _plan_linear_wall_fragment(
                orientation=orientation,
                wall_pos=wall_pos,
                start=rect_min,
                end=rect_max,
                base_z=rect_z_min,
                height=rect_z_max - rect_z_min,
                wall_t=wall_t,
                ref_along=0.0,
                ref_z=facade_mid_z,
                material=wall_material,
                source_bucket="Section_Walls_Exterior",
                source_name=f"{piers_object_name}:pier_{idx:02d}",
                staged_object_name=piers_object_name,
                marker_metadata={
                    "tbg_runtime_side": side_key,
                    "tbg_runtime_floor": int(floor_index),
                    "tbg_runtime_slot": int(idx),
                },
            )
            if planned_fragment is None:
                continue
            _append_planned_wall_parts(pier_parts, pier_marker_parts, (planned_fragment,))
    if pier_parts:
        piers = _create_composite_box_object(
            piers_object_name,
            pier_parts,
            _opening_location(orientation, 0.0, wall_pos, facade_mid_z),
            collection,
            parent,
            wall_material,
            rotation=_orientation_rotation(orientation),
        )
        piers = _mark_wall_section(piers, "Section_Walls_Exterior")
        if runtime_emitter is not None and piers is not None:
            runtime_emitter.emit_composite_boxes(
                parts=[(size, center) for size, center, _role, _metadata in pier_marker_parts],
                base_location=_opening_location(orientation, 0.0, wall_pos, facade_mid_z),
                rotation=_orientation_rotation(orientation),
                role=ROLE_SHELL,
                source_name=piers.name,
                per_part_metadata=[metadata_values for _size, _center, _role, metadata_values in pier_marker_parts],
                metadata_values={"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)},
            )

    _build_timber_siding_overlay(
        prefix,
        side_label,
        side_key,
        orientation,
        wall_pos,
        floor_index,
        base_z,
        shell_floor_height,
        wall_t,
        collection,
        parent,
        materials_map,
        spec,
        side_facts=side_facts,
        opening_bands_override=opening_bands_override,
    )

    ac_emitted = False
    for idx, slot_min, slot_max in intervals:
        slot_rects: list[tuple[float, float, float, float]] = [
            (float(slot_min), float(slot_max), float(base_z), float(base_z + shell_floor_height))
        ]
        slot_has_opening_override = False
        for band_min, band_max, band_z_min, band_z_max in pier_suppression_bands:
            cut_min = max(float(slot_min), float(band_min))
            cut_max = min(float(slot_max), float(band_max))
            cut_z_min = max(float(base_z), float(band_z_min))
            cut_z_max = min(float(base_z + shell_floor_height), float(band_z_max))
            if cut_max <= cut_min + 1e-4 or cut_z_max <= cut_z_min + 1e-4:
                continue
            slot_has_opening_override = True
            slot_rects = _subtract_band_from_rect(
                slot_rects,
                band_min=float(band_min),
                band_max=float(band_max),
                band_z_min=float(band_z_min),
                band_z_max=float(band_z_max),
            )
            if not slot_rects:
                break
        if slot_has_opening_override:
            for rect_min, rect_max, rect_z_min, rect_z_max in slot_rects:
                planned_fragment = _plan_linear_wall_fragment(
                    orientation=orientation,
                    wall_pos=wall_pos,
                    start=rect_min,
                    end=rect_max,
                    base_z=rect_z_min,
                    height=rect_z_max - rect_z_min,
                    wall_t=wall_t,
                    ref_along=0.0,
                    ref_z=facade_mid_z,
                    material=wall_material,
                    source_bucket="Section_Walls_Exterior",
                    source_name=f"{slot_shell_object_name}:slot_{idx:02d}",
                    staged_object_name=slot_shell_object_name,
                    marker_metadata={
                        "tbg_runtime_side": side_key,
                        "tbg_runtime_floor": int(floor_index),
                        "tbg_runtime_slot": int(idx),
                    },
                )
                if planned_fragment is None:
                    continue
                _append_planned_wall_parts(slot_shell_parts, slot_shell_marker_parts, (planned_fragment,))
            continue
        state = _clamp_generic_slot_state(
            spec,
            side_key,
            floor_index,
            planned_states.get(idx, WINDOW_STATE_CLOSED),
        )
        terrace_exit_slot = floor_facts.get("terrace_exit_slot")
        terrace_exit = terrace_exit_slot is not None and int(idx) == int(terrace_exit_slot)

        state_suffix = {
            WINDOW_STATE_MASK: "Mask",
            WINDOW_STATE_CLOSED: "Window",
            WINDOW_STATE_OPEN: "OpenWindow",
            WINDOW_STATE_BALCONY: "Balcony",
            WINDOW_STATE_STAIR: "StairWindow",
        }[state]
        if terrace_exit:
            state_suffix = "TerraceExit"
        place_ac = (
            state in {WINDOW_STATE_CLOSED, WINDOW_STATE_OPEN}
            and idx not in blocked_for_ac
            and not (side_key == "front" and (floor_index == 0 or _is_storefront_frontage(spec)))
            and not _is_market_hall_frontage(spec)
            and (
                idx == forced_ac_slot
                or
                idx == mandatory_ac_idx
                or _stable_unit_float(spec.seed, "facade_ac", side_key, floor_index, idx) < spec.facade_ac_ratio
            )
        )
        balcony_plan = balcony_leaders.get(idx)
        balcony_span_width = None
        balcony_span_center = None
        balcony_style = "SHORT"
        balcony_expected_bays = 1
        balcony_span_key = None
        if balcony_plan is not None:
            member_intervals = [intervals[member_idx] for member_idx in balcony_plan.member_indices]
            span_start = min(item[1] for item in member_intervals)
            span_end = max(item[2] for item in member_intervals)
            balcony_span_width = span_end - span_start + (
                BALCONY_STRIP_EXTRA_SPAN if balcony_plan.style == "STRIP" else 0.38
            )
            balcony_span_center = (span_start + span_end) / 2
            balcony_style = balcony_plan.style
            # The current runtime contract exposes one explicit traversal opening per balcony span.
            balcony_expected_bays = 1
            balcony_span_key = f"{side_key}:{floor_index}:{balcony_plan.leader_idx}"
        else:
            leader_idx = None if terrace_exit else balcony_members.get(idx, protected_openings.get(idx))
            if leader_idx is not None:
                balcony_span_key = f"{side_key}:{floor_index}:{leader_idx}"
        profile_floor_height = float(spec.floor_height) if shell_floor_height + 1e-4 < float(spec.floor_height) else float(shell_floor_height)
        ac_emitted = _build_window_slot(
            prefix,
            f"{side_label}_F{floor_index:02d}_{state_suffix}_{idx:02d}",
            orientation,
            side_key,
            wall_pos,
            slot_min,
            slot_max,
            base_z,
            shell_floor_height,
            wall_t,
            collection,
            parent,
            materials_map,
            spec,
            state=state,
            place_ac=place_ac,
            protect_opening=idx in protected_openings,
            floor_index=floor_index,
            slot_index=idx,
            balcony_span_width=balcony_span_width,
            balcony_span_center=balcony_span_center,
            balcony_style=balcony_style,
            balcony_expected_bays=balcony_expected_bays,
            balcony_span_key=balcony_span_key,
            terrace_exit=terrace_exit,
            profile_floor_height=profile_floor_height,
            stamp_opening_cut=True,
            occupancy_author=child_occupancy_author,
            wall_plane_start=facade_start,
            wall_plane_end=facade_end,
            runtime_emitter=runtime_emitter,
        ) or ac_emitted
    if slot_shell_parts:
        slot_shell = _create_composite_box_object(
            slot_shell_object_name,
            slot_shell_parts,
            _opening_location(orientation, 0.0, wall_pos, facade_mid_z),
            collection,
            parent,
            wall_material,
            rotation=_orientation_rotation(orientation),
        )
        slot_shell = _mark_wall_section(slot_shell, "Section_Walls_Exterior")
        if runtime_emitter is not None and slot_shell is not None:
            runtime_emitter.emit_composite_boxes(
                parts=[(size, center) for size, center, _role, _metadata in slot_shell_marker_parts],
                base_location=_opening_location(orientation, 0.0, wall_pos, facade_mid_z),
                rotation=_orientation_rotation(orientation),
                role=ROLE_SHELL,
                source_name=slot_shell.name,
                per_part_metadata=[metadata_values for _size, _center, _role, metadata_values in slot_shell_marker_parts],
                metadata_values={"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)},
            )
    _strip_lower_facade_coplanar_bottom_caps(
        parent,
        side_key=side_key,
        floor_index=floor_index,
        seam_z=base_z,
    )
    return ac_emitted

window_envelope_bands_by_slot_for_floor = _window_envelope_bands_by_slot_for_floor
window_envelope_bands_for_floor = _window_envelope_bands_for_floor
build_timber_siding_overlay = _build_timber_siding_overlay
build_facade_wall = _build_facade_wall
