from __future__ import annotations

import math

from .. import constants
from ..export_contract import (
    ROLE_BALCONY_ACCESS_OPENING,
    ROLE_BALCONY_FLOOR,
    ROLE_BALCONY_RAIL,
    ROLE_ENTRY_LANDING,
    ROLE_ENTRY_WEDGE,
    ROLE_OPEN_WINDOW_OPENING,
    ROLE_PODIUM_BLOCKER,
    ROLE_SHELL,
    ROLE_WINDOW_CLOSED,
)
from .building_wall_service_pipes import build_wall_service_pipes as _build_wall_service_pipes_owner
from .building_facade_opening_slots import (
    _build_opening_trim,
    build_custom_window_slot as _build_custom_window_slot,
    create_opening_box as _create_opening_box,
    opening_cut_frame_envelope as _opening_cut_frame_envelope,
    ordinary_door_cut_metadata as _ordinary_door_cut_metadata,
    ordinary_door_cut_rect as _ordinary_door_cut_rect,
    register_linear_wall_plane as _register_linear_wall_plane,
    slot_opening_profile as _slot_opening_profile,
    wall_opening_cut_metadata as _wall_opening_cut_metadata,
)
from .building_facade_openings import (
    _strip_lower_facade_coplanar_bottom_caps,
    build_facade_wall as _build_facade_wall,
    build_timber_siding_overlay as _build_timber_siding_overlay,
)
from .building_facade_frontage_recipes import (
    build_entry_stoop_package as _build_entry_stoop_package,
    build_front_entry_frame as _build_front_entry_frame,
    emit_front_wall_piece as _emit_front_wall_piece,
    frontage_trim_material as _facade_trim_material,
    build_ground_tactical_profile as _build_ground_tactical_profile,
    build_hangar_front_ground as _build_hangar_front_ground,
    build_market_hall_front_ground as _build_market_hall_front_ground,
    resolve_frontage_entry_pose as _resolve_frontage_entry_pose,
)
from .building_facade_frontage_industrial import (
    build_industrial_front_ground as _build_industrial_front_ground,
    build_depot_back_ground as _build_depot_back_ground,
    build_warehouse_back_ground as _build_warehouse_back_ground,
)
from .building_facade_frontage_storefront import (
    build_storefront_front_ground as _build_storefront_front_ground,
)
from .layout_facade_planning import (
    _balcony_floor_enabled,
    _balcony_lookup,
    _balcony_material,
    _balcony_plans_for_side,
    _completed_facade_floor_count,
    _entry_stoop_package_ledger,
    _effective_entrance_profile,
    _facade_window_layouts,
    _front_entry_envelope,
    _front_entry_package_center_span,
    _frontage_variant,
    _is_hangar_frontage,
    _is_industrial_frontage,
    _is_office_window_profile,
    _is_market_hall_frontage,
    _mandatory_ac_slot,
    _planned_window_states,
    _is_residential_wide,
    _side_shell_metrics,
    _is_storefront_frontage,
    _is_timber_frontage,
    _pilotis_column_positions,
    _slot_intervals,
    _stair_window_slots,
    _trim_material,
    _window_verticals,
    _wall_material_for_floor,
)
from .building_layout import (
    FRONTAGE_TYPE_INDUSTRIAL_DEPOT,
    FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE,
    REAR_ACCESS_PROFILE_OPEN_BAY,
    REAR_ACCESS_PROFILE_SERVICE_DOOR,
    REAR_ACCESS_PROFILE_SHELL_ONLY,
    FRONTAGE_TYPE_STOREFRONT_CLINIC,
    FRONTAGE_TYPE_STOREFRONT_PHARMACY,
    FRONTAGE_TYPE_STOREFRONT_SHOP,
    FRONTAGE_TYPE_TIMBER_HOUSE,
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
    ENTRANCE_PODIUM_HIGH,
    ENTRANCE_STOOP_LOW,
    FACADE_BAND_DEPTH,
    FACADE_BAND_HEIGHT,
    GROUND_FLOOR_DEFENSIVE_BASE,
    GROUND_FLOOR_MIXED_WINDOWS,
    GROUND_FLOOR_OPEN_ENTRY,
    GROUND_FLOOR_STOREFRONT,
    GROUND_PLINTH_DEPTH,
    INNER_FRAME_PROUD_OFFSET,
    MASSING_PROFILE_BASE_HEAVY,
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
    WINDOW_TRIM_WIDTH,
    WINDOW_WALL_OVERLAP,
    BalconyPlan,
    _base_elevation,
    _floor_shell_rect,
    _is_stage1_identity_reset_family,
    _pilotis_open_side,
    _level_base_z,
    _opening_inset_coord,
    _opening_location,
    _orientation_rotation,
    _roof_surface_z,
    _surface_coord,
    _wall_service_pipe_band,
    subtract_blocked_spans,
)
from .specs import (
    FACADE_BAND_PROFILE_BRICK_REVEAL,
    FACADE_BAND_PROFILE_CONCRETE_BAND,
    FACADE_BAND_PROFILE_HEAVY_CORNICE,
    FACADE_BAND_PROFILE_NONE,
    FOUNDATION_PROFILE_EXPOSED_BRICK_BASE,
    FOUNDATION_PROFILE_HEAVY_BASE,
    FOUNDATION_PROFILE_PLAIN,
    FOUNDATION_PROFILE_STONE_BASE,
)
from .building_support import (
    _create_box,
    _frame_mesh,
    _mark_door_leaf,
    _mark_generated,
    _mark_section,
    _mark_wall_section,
    _name,
)
from .runtime_markers import RuntimeMarkerEmitter
from .building_occupancy import (
    MIN_NON_THICKNESS_CELL_SPAN_STUDS,
    OPENING_VISUAL_CLEARANCE_STUDS,
    OccupancyAuthoringSession,
)


def _rear_door_cut_rect_absorbing_edge_residue(
    cut_rect: tuple[float, float, float, float],
    *,
    plane_run_min: float,
    plane_run_max: float,
) -> tuple[float, float, float, float]:
    """Extend a rear-door cut only when its clearance leaves an unpackable edge remnant."""
    cut_min, cut_max, z_min, z_max = (float(value) for value in cut_rect)
    clearance = max(0.0, float(OPENING_VISUAL_CLEARANCE_STUDS))
    expanded_min = cut_min - clearance
    expanded_max = cut_max + clearance
    left_residue = expanded_min - float(plane_run_min)
    right_residue = float(plane_run_max) - expanded_max
    if 1e-6 < left_residue < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        cut_min = float(plane_run_min) + clearance
    if 1e-6 < right_residue < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        cut_max = float(plane_run_max) - clearance
    return (round(cut_min, 4), round(cut_max, 4), round(z_min, 4), round(z_max, 4))


def _resolve_rear_door_cut_context(spec, rear_opening_contract: dict[str, float]) -> dict[str, object] | None:
    wall_left = float(rear_opening_contract["span_left"])
    wall_right = float(rear_opening_contract["span_right"])
    wall_width = max(0.0, wall_right - wall_left)
    opening_width = min(float(rear_opening_contract["opening_width"]), max(0.0, wall_width - 0.04))
    if opening_width <= 0.0:
        return None
    opening_center_x = float(rear_opening_contract["opening_center_x"])
    half_opening = opening_width / 2
    if wall_width > opening_width:
        opening_center_x = max(wall_left + half_opening, min(wall_right - half_opening, opening_center_x))
    envelope = _front_entry_envelope(spec)
    stoop_variant = _entry_stoop_variant(spec, facade_side="back")
    package_ledger = _entry_stoop_package_ledger(
        spec,
        envelope=envelope,
        facade_side="back",
        package_center_x=opening_center_x,
        stoop_variant=stoop_variant,
    )
    base_z = _base_elevation(spec)
    package_center_x = float(package_ledger["center_x"])
    base_cut_rect = _ordinary_door_cut_rect(
        center_x=package_center_x,
        opening_width=opening_width,
        base_z=base_z,
        door_height=spec.door.height,
    )
    cut_rect = _rear_door_cut_rect_absorbing_edge_residue(
        base_cut_rect,
        plane_run_min=-float(spec.width) / 2,
        plane_run_max=float(spec.width) / 2,
    )
    return {
        "base_z": base_z,
        "back_y": spec.depth / 2 - spec.wall_thickness / 2,
        "door_center_z": base_z + spec.door.height / 2,
        "envelope": envelope,
        "stoop_variant": stoop_variant,
        "package_ledger": package_ledger,
        "package_center_x": package_center_x,
        "opening_width": opening_width,
        "cut_rect": cut_rect,
    }


def _build_rear_through_opening(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    rear_opening_contract: dict[str, float],
    *,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    door_context = _resolve_rear_door_cut_context(spec, rear_opening_contract)
    if door_context is None:
        return
    base_z = float(door_context["base_z"])
    back_y = float(door_context["back_y"])
    door_center_z = float(door_context["door_center_z"])
    envelope = door_context["envelope"]
    stoop_variant = door_context["stoop_variant"]
    package_ledger = door_context["package_ledger"]
    package_center_x = float(door_context["package_center_x"])
    opening_width = float(door_context["opening_width"])
    door_cut_metadata = _wall_opening_cut_metadata(
        kind="door",
        orientation="X",
        side_key="back",
        floor_index=0,
        slot_index=-1,
        wall_pos=back_y,
        cut_rect=door_context["cut_rect"],
    )
    frame_along_coord, frame_outer_width, frame_outer_height, frame_mid_z = _opening_cut_frame_envelope(
        door_cut_metadata
    )
    frame_along_coord = float(frame_along_coord if frame_along_coord is not None else package_center_x)
    frame_width = float(frame_outer_width if frame_outer_width is not None else opening_width)
    # Keep rear through-access gameplay/visual contract separate from the
    # clearance-expanded wall-cell cut used for seating/validation.
    authored_left = float(package_center_x - opening_width / 2)
    authored_right = float(package_center_x + opening_width / 2)

    frame = _build_opening_trim(
        prefix,
        "Door_Rear",
        "X",
        "back",
        back_y,
        frame_along_coord,
        opening_width,
        0.0,
        spec.door.height,
        base_z,
        spec.wall_thickness,
        collection,
        parent,
        materials_map["frame"],
        office_style=False,
        placement="outer_proud",
        double_sided=True,
        outer_width_override=frame_outer_width,
        outer_height_override=frame_outer_height,
        opening_mid_z_override=frame_mid_z,
    )
    if frame is not None:
        _mark_section(
            _mark_generated(
                frame,
                tbg_door_frame=True,
                tbg_door_frame_left=authored_left,
                tbg_door_frame_right=authored_right,
                tbg_door_frame_outer_left=float(frame_along_coord - frame_width / 2),
                tbg_door_frame_outer_right=float(frame_along_coord + frame_width / 2),
                tbg_door_threshold_z=float(base_z),
                tbg_facade_side="back",
                tbg_facade_plane="both",
                tbg_rear_through_access=True,
                **door_cut_metadata,
            ),
            "Section_Doors_Trim",
            merge_allowed=False,
        )

    if str(getattr(spec, "door_profile", "HINGED")).upper() == "ROLLER" and not _is_storefront_frontage(spec):
        panel_depth = max(0.05, min(spec.wall_thickness, max(spec.door.thickness, spec.wall_thickness * 0.4)))
        rear_door = _create_box(
            _name(prefix, "Door_Rear"),
            (opening_width, panel_depth, spec.door.height),
            (package_center_x, back_y - panel_depth / 2 - 0.015, door_center_z),
            collection,
            parent,
            materials_map["door"],
        )
        rear_door = _mark_generated(
            rear_door,
            tbg_door_panel=True,
            tbg_door_handle_plate=True,
            tbg_rear_through_access=True,
            tbg_facade_side="back",
            tbg_facade_floor=0,
            **door_cut_metadata,
        )
        _mark_door_leaf(rear_door, open_rotation_z=0.0)
    else:
        if spec.door.hinge == constants.HINGE_LEFT:
            hinge_x = package_center_x - opening_width / 2
            origin_mode = "HINGE_LEFT"
            open_rotation = math.radians(95.0)
        else:
            hinge_x = package_center_x + opening_width / 2
            origin_mode = "HINGE_RIGHT"
            open_rotation = math.radians(-95.0)
        rear_door = _create_box(
            _name(prefix, "Door_Rear"),
            (opening_width, spec.door.thickness, spec.door.height),
            (hinge_x, back_y - spec.door.thickness / 2 - 0.015, door_center_z),
            collection,
            parent,
            materials_map["door"],
            origin_mode=origin_mode,
        )
        rear_door = _mark_generated(
            rear_door,
            tbg_door_panel=True,
            tbg_door_handle_plate=True,
            tbg_rear_through_access=True,
            tbg_facade_side="back",
            tbg_facade_floor=0,
            **door_cut_metadata,
        )
        _mark_door_leaf(rear_door, open_rotation_z=open_rotation)

    _build_entry_stoop_package(
        prefix,
        "Rear",
        spec,
        collection,
        parent,
        _frontage_walk_material(materials_map, timber=_is_timber_frontage(spec)),
        center_x=package_center_x,
        landing_width=float(package_ledger["package_width"]),
        landing_depth=envelope.landing_depth,
        landing_height=envelope.landing_height,
        landing_center_y=spec.depth / 2 + envelope.landing_depth / 2 - 0.04,
        landing_outer_edge_y=spec.depth / 2 + envelope.landing_depth - 0.04,
        threshold_z=envelope.threshold_z,
        stair_run=envelope.stair_run,
        step_count=envelope.step_count,
        outward_sign=1.0,
        facade_side="back",
        stoop_variant=stoop_variant,
        package_left_x=float(package_ledger["package_left_x"]),
        package_right_x=float(package_ledger["package_right_x"]),
        runtime_emitter=runtime_emitter,
        runtime_landing_role=ROLE_ENTRY_LANDING,
        runtime_wedge_role=ROLE_ENTRY_WEDGE,
        runtime_wedge_metadata={
            "tbg_runtime_floor": 0,
            "tbg_runtime_threshold_z": float(envelope.threshold_z),
        },
        landing_generated_metadata={
            "tbg_rear_through_access": True,
            "tbg_facade_side": "back",
            "tbg_facade_floor": 0,
        },
        step_generated_metadata={
            "tbg_rear_through_access": True,
            "tbg_facade_side": "back",
            "tbg_facade_floor": 0,
        },
    )


def _rear_entry_opening_contract(
    floor_facts,
) -> dict[str, float] | None:
    opening_contract = floor_facts.get("rear_entry_opening_contract")
    if not isinstance(opening_contract, dict):
        return None
    try:
        span_left = float(opening_contract["span_left"])
        span_right = float(opening_contract["span_right"])
        opening_center_x = float(opening_contract["opening_center_x"])
        opening_width = float(opening_contract["opening_width"])
    except (TypeError, ValueError, KeyError):
        return None
    if span_right - span_left <= 1e-4 or opening_width <= 1e-4:
        return None
    return {
        "span_left": span_left,
        "span_right": span_right,
        "opening_center_x": opening_center_x,
        "opening_width": opening_width,
    }


def _rear_entry_wall_span(
    floor_facts,
) -> tuple[float, float] | None:
    opening_contract = _rear_entry_opening_contract(floor_facts)
    if opening_contract is None:
        return None
    span_min = float(opening_contract["span_left"])
    span_max = float(opening_contract["span_right"])
    if span_max - span_min <= 1e-4:
        return None
    return (span_min, span_max)

def _frontage_walk_material(materials_map, *, timber: bool):
    if timber:
        return materials_map.get("wood_floor", materials_map["floor"])
    return materials_map["floor"]


def _entry_stoop_variant(spec, *, facade_side: str) -> str | None:
    side_key = str(facade_side or "").lower()
    if side_key == "back":
        return str(getattr(spec, "rear_stoop_variant", "STRAIGHT") or "STRAIGHT")
    return str(getattr(spec, "front_stoop_variant", "ROUNDED") or "ROUNDED")


def _mandatory_facade_ac_target(spec, facade_facts) -> tuple[str, int, int] | None:
    for side_key in ("right", "left", "back"):
        side_facts = facade_facts[side_key]
        for floor_index in range(spec.floor_count - 1, -1, -1):
            floor_facts = side_facts["floor_facts"][floor_index]
            if not floor_facts.get("active", True):
                continue
            slot_index = floor_facts["mandatory_ac_slot"]
            if slot_index is None:
                continue
            state = floor_facts["planned_states"].get(slot_index, WINDOW_STATE_CLOSED)
            if state not in {WINDOW_STATE_CLOSED, WINDOW_STATE_OPEN}:
                continue
            return side_key, floor_index, slot_index
    return None

def _build_entrance_stoop(prefix, spec, collection, parent, material, runtime_emitter: RuntimeMarkerEmitter | None = None):
    envelope = _front_entry_envelope(spec)
    stoop_variant = _entry_stoop_variant(spec, facade_side="front")
    package_ledger = _entry_stoop_package_ledger(
        spec,
        envelope=envelope,
        facade_side="front",
        stoop_variant=stoop_variant,
    )
    package_center_x = float(package_ledger["center_x"])
    package_left_x = float(package_ledger["package_left_x"])
    package_right_x = float(package_ledger["package_right_x"])
    _build_entry_stoop_package(
        prefix,
        "Entrance",
        spec,
        collection,
        parent,
        material,
        center_x=package_center_x,
        landing_width=float(package_ledger["package_width"]),
        landing_depth=envelope.landing_depth,
        landing_height=envelope.landing_height,
        landing_center_y=envelope.landing_center_y,
        landing_outer_edge_y=envelope.landing_front_y,
        threshold_z=envelope.threshold_z,
        stair_run=envelope.stair_run,
        step_count=envelope.step_count,
        outward_sign=-1.0,
        facade_side="front",
        stoop_variant=stoop_variant,
        package_left_x=package_left_x,
        package_right_x=package_right_x,
        runtime_emitter=runtime_emitter,
        runtime_landing_role=ROLE_ENTRY_LANDING,
        runtime_wedge_role=ROLE_ENTRY_WEDGE,
        runtime_wedge_metadata={
            "tbg_runtime_floor": 0,
            "tbg_runtime_threshold_z": float(envelope.threshold_z),
        },
        landing_generated_metadata={
            "tbg_entrance_part": "landing",
            "tbg_entrance_top_z": envelope.threshold_z,
            "tbg_entrance_threshold_z": envelope.threshold_z,
            "tbg_entry_front_limit": float(envelope.front_footprint_extent),
            "tbg_entry_left_limit": float(abs(package_left_x)),
            "tbg_entry_right_limit": float(abs(package_right_x)),
        },
        step_generated_metadata={
            "tbg_entrance_part": "step",
            "tbg_entrance_top_z": envelope.threshold_z,
            "tbg_entrance_threshold_z": envelope.threshold_z,
            "tbg_entrance_top_step": True,
            "tbg_entry_front_limit": float(envelope.front_footprint_extent),
            "tbg_entry_left_limit": float(abs(package_left_x)),
            "tbg_entry_right_limit": float(abs(package_right_x)),
        },
    )

def _build_pilotis_columns(
    prefix,
    side_label: str,
    side_key: str,
    orientation: str,
    wall_pos: float,
    floor_index: int,
    base_z: float,
    floor_height: float,
    spec,
    collection,
    parent,
    material,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    columns = _pilotis_column_positions(spec, side_key)
    if not columns:
        return
    structural_depth = max(spec.wall_thickness, min(0.38, spec.wall_thickness * 1.6))
    beam_height = max(0.2, min(0.34, floor_height * 0.1))
    column_height = max(0.72, floor_height - beam_height)
    beam_center_z = base_z + floor_height - beam_height / 2
    column_center_z = base_z + column_height / 2
    span_start = columns[0][1]
    span_end = columns[-1][2]
    beam = _create_opening_box(
        _name(prefix, f"{side_label}_F{floor_index:02d}_PilotisBeam"),
        orientation,
        span_end - span_start,
        structural_depth,
        beam_height,
        (span_start + span_end) / 2,
        wall_pos,
        beam_center_z,
        collection,
        parent,
        material,
    )
    beam = _mark_wall_section(
        _mark_generated(
            beam,
            tbg_pilotis_beam=True,
            tbg_facade_side=side_key,
            tbg_facade_floor=int(floor_index),
        ),
        "Section_Walls_Exterior",
    )
    if runtime_emitter is not None and beam is not None:
        runtime_emitter.emit_box(
            role=ROLE_SHELL,
            size=(span_end - span_start, structural_depth, beam_height)
            if orientation == "X"
            else (structural_depth, span_end - span_start, beam_height),
            location=tuple(float(value) for value in beam.location),
            rotation=tuple(float(value) for value in beam.rotation_euler),
            source_name=beam.name,
            metadata_values={"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)},
        )

    if _is_market_hall_frontage(spec):
        spandrel_height = max(0.24, min(0.42, floor_height * 0.13))
        spandrel = _create_opening_box(
            _name(prefix, f"{side_label}_F{floor_index:02d}_PilotisSpandrel"),
            orientation,
            span_end - span_start,
            structural_depth,
            spandrel_height,
            (span_start + span_end) / 2,
            wall_pos,
            beam_center_z - beam_height / 2 - spandrel_height / 2 - 0.04,
            collection,
            parent,
            material,
        )
        _mark_wall_section(
            _mark_generated(
                spandrel,
                tbg_pilotis_spandrel=True,
                tbg_facade_side=side_key,
                tbg_facade_floor=int(floor_index),
            ),
            "Section_Walls_Exterior",
        )

    for column_index, (center, span_start, span_end) in enumerate(columns):
        span = span_end - span_start
        if span <= 1e-4:
            continue
        column = _create_opening_box(
            _name(prefix, f"{side_label}_F{floor_index:02d}_Pilotis_{column_index:02d}"),
            orientation,
            span,
            structural_depth,
            column_height,
            center,
            wall_pos,
            column_center_z,
            collection,
            parent,
            material,
        )
        column = _mark_wall_section(
            _mark_generated(
                column,
                tbg_pilotis_column=True,
                tbg_facade_side=side_key,
                tbg_facade_floor=int(floor_index),
            ),
            "Section_Walls_Exterior",
        )
        if runtime_emitter is not None and column is not None:
            runtime_emitter.emit_box(
                role=ROLE_SHELL,
                size=(span, structural_depth, column_height)
                if orientation == "X"
                else (structural_depth, span, column_height),
                location=tuple(float(value) for value in column.location),
                rotation=tuple(float(value) for value in column.rotation_euler),
                source_name=column.name,
                metadata_values={"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)},
            )

def _build_foundation_profile_accents(prefix, spec, collection, parent, materials_map):
    if _is_timber_frontage(spec):
        return

    profile = str(getattr(spec, "foundation_profile", FOUNDATION_PROFILE_PLAIN)).upper()
    if profile == FOUNDATION_PROFILE_PLAIN:
        return

    sill_h, _opening_h, _top_h = _window_verticals(spec.floor_height, spec.window_profile)
    max_height = max(0.12, sill_h - 0.06)
    wall_material = _wall_material_for_floor(materials_map, spec, 0)
    trim_material = _facade_trim_material(materials_map, spec)
    if profile == FOUNDATION_PROFILE_HEAVY_BASE:
        accent_height = min(max_height, max(0.22, min(0.86, spec.floor_height * 0.3)))
        accent_depth = max(0.1, spec.wall_thickness * 0.52)
        accent_material = trim_material
        accent_section = "Section_Walls_Trim"
    elif profile == FOUNDATION_PROFILE_STONE_BASE:
        accent_height = min(max_height, max(0.2, min(0.72, spec.floor_height * 0.24)))
        accent_depth = max(0.09, spec.wall_thickness * 0.44)
        accent_material = trim_material
        accent_section = "Section_Walls_Trim"
    elif profile == FOUNDATION_PROFILE_EXPOSED_BRICK_BASE:
        accent_height = min(max_height, max(0.18, min(0.62, spec.floor_height * 0.2)))
        accent_depth = max(0.07, spec.wall_thickness * 0.32)
        accent_material = wall_material
        accent_section = "Section_Walls_Exterior"
    else:
        return

    if accent_height <= 0.1:
        return

    front_intervals = [(-spec.width / 2, spec.width / 2)]
    if not _is_storefront_frontage(spec):
        entry = _front_entry_envelope(spec)
        front_intervals = subtract_blocked_spans(
            front_intervals,
            entry.door_left,
            entry.door_right,
            padding=0.08,
            minimum_span=0.16,
        )
    strips = [
        ("Front", "X", front_intervals, -spec.depth / 2 + spec.wall_thickness / 2, "front"),
        ("Back", "X", [(-spec.width / 2, spec.width / 2)], spec.depth / 2 - spec.wall_thickness / 2, "back"),
        (
            "Left",
            "Y",
            [(-spec.depth / 2 + spec.wall_thickness, spec.depth / 2 - spec.wall_thickness)],
            -spec.width / 2 + spec.wall_thickness / 2,
            "left",
        ),
        (
            "Right",
            "Y",
            [(-spec.depth / 2 + spec.wall_thickness, spec.depth / 2 - spec.wall_thickness)],
            spec.width / 2 - spec.wall_thickness / 2,
            "right",
        ),
    ]
    center_z = accent_height / 2
    accent_proud_offset = max(0.02, accent_depth * 0.18)
    for side_label, orientation, intervals, wall_pos, side_key in strips:
        for index, (start, end) in enumerate(intervals):
            span = end - start
            if span <= 1e-4:
                continue
            strip = _create_opening_box(
                _name(prefix, f"FoundationAccent_{side_label}_{index:02d}"),
                orientation,
                span,
                accent_depth,
                accent_height,
                (start + end) / 2,
                _surface_coord(
                    side_key,
                    wall_pos,
                    spec.wall_thickness,
                    accent_depth,
                    exterior=True,
                    offset=accent_proud_offset,
                ),
                center_z,
                collection,
                parent,
                accent_material,
            )
            _mark_wall_section(_mark_generated(strip, tbg_foundation_accent=True), accent_section)


def _entry_foundation_cut_contract(
    spec,
    *,
    foundation_width: float,
    foundation_depth: float,
) -> tuple[float, float, float] | None:
    if not bool(getattr(getattr(spec, "door", None), "enabled", True)):
        return None
    if (
        _is_hangar_frontage(spec)
        or _is_storefront_frontage(spec)
        or _is_industrial_frontage(spec)
        or _is_market_hall_frontage(spec)
    ):
        return None
    envelope = _front_entry_envelope(spec)
    if float(envelope.threshold_z) <= 0.0:
        return None
    x0 = -float(foundation_width) / 2
    x1 = float(foundation_width) / 2
    y0 = -float(foundation_depth) / 2
    y1 = float(foundation_depth) / 2
    cut_left = max(x0, float(envelope.entry_exclusion_left))
    cut_right = min(x1, float(envelope.entry_exclusion_right))
    if cut_right - cut_left <= 0.08:
        return None
    threshold_y = (
        float(envelope.landing_front_y + envelope.landing_depth)
        if float(envelope.landing_depth) > 1e-4
        else -float(spec.depth) / 2 + float(spec.wall_thickness) / 2
    )
    if threshold_y <= y0 + 0.02:
        return None
    cut_back_y = threshold_y + max(0.08, float(spec.wall_thickness) * 0.5)
    cut_back_y = min(y1 - 0.02, cut_back_y)
    cut_back_y = max(y0 + 0.14, cut_back_y)
    if cut_back_y - y0 <= 0.1:
        return None
    return (cut_left, cut_right, cut_back_y)


def _build_foundation_podium_render(
    prefix,
    *,
    spec,
    collection,
    parent,
    material,
    width: float,
    depth: float,
    height: float,
    base_name: str = "Foundation_Podium",
    extra_metadata: dict[str, object] | None = None,
) -> tuple[object, ...]:
    foundation_parts: list[object] = []

    def _emit_part(
        *,
        name_suffix: str,
        part_width: float,
        part_depth: float,
        center_x: float,
        center_y: float,
    ) -> None:
        if part_width <= 1e-4 or part_depth <= 1e-4:
            return
        object_name = (
            _name(prefix, base_name)
            if name_suffix == "Body"
            else _name(prefix, f"{base_name}_{name_suffix}")
        )
        piece = _create_box(
            object_name,
            (part_width, part_depth, height),
            (center_x, center_y, height / 2),
            collection,
            parent,
            material,
        )
        metadata = {
            "tbg_foundation_podium": True,
            "tbg_foundation_top_z": float(height),
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        foundation_parts.append(
            _mark_section(
                _mark_generated(piece, **metadata),
                "Section_Floors",
            )
        )

    x0 = -float(width) / 2
    x1 = float(width) / 2
    y0 = -float(depth) / 2
    y1 = float(depth) / 2
    cut = _entry_foundation_cut_contract(
        spec,
        foundation_width=width,
        foundation_depth=depth,
    )
    if cut is None:
        _emit_part(
            name_suffix="Body",
            part_width=width,
            part_depth=depth,
            center_x=0.0,
            center_y=0.0,
        )
        return tuple(foundation_parts)

    cut_left, cut_right, cut_back_y = cut
    _emit_part(
        name_suffix="Back",
        part_width=width,
        part_depth=y1 - cut_back_y,
        center_x=0.0,
        center_y=(cut_back_y + y1) / 2,
    )
    _emit_part(
        name_suffix="FrontLeft",
        part_width=cut_left - x0,
        part_depth=cut_back_y - y0,
        center_x=(x0 + cut_left) / 2,
        center_y=(y0 + cut_back_y) / 2,
    )
    _emit_part(
        name_suffix="FrontRight",
        part_width=x1 - cut_right,
        part_depth=cut_back_y - y0,
        center_x=(cut_right + x1) / 2,
        center_y=(y0 + cut_back_y) / 2,
    )
    return tuple(foundation_parts)


def _build_foundation_podium(prefix, spec, collection, parent, material, materials_map, runtime_emitter: RuntimeMarkerEmitter | None = None):
    base_elevation = _base_elevation(spec)
    if base_elevation <= 0.0:
        return
    foundation_render_height = max(0.02, base_elevation - float(spec.slab_thickness))
    if _is_timber_frontage(spec):
        trim_material = _facade_trim_material(materials_map, spec)
        wall_material = _wall_material_for_floor(materials_map, spec, 0)
        timber_setback = max(0.14, min(0.22, spec.wall_thickness * 0.92))
        foundation_width = max(spec.width * 0.62, spec.width - timber_setback * 2)
        foundation_depth = max(spec.depth * 0.62, spec.depth - timber_setback * 2)
        foundation_parts = _build_foundation_podium_render(
            prefix,
            spec=spec,
            collection=collection,
            parent=parent,
            material=wall_material,
            width=foundation_width,
            depth=foundation_depth,
            height=foundation_render_height,
            base_name="Foundation_TimberBase",
            extra_metadata={"tbg_timber_foundation": True},
        )
        foundation = foundation_parts[0] if foundation_parts else None
        if runtime_emitter is not None:
            runtime_emitter.emit_box(
                role=ROLE_PODIUM_BLOCKER,
                size=(foundation_width, foundation_depth, base_elevation),
                location=(0.0, 0.0, base_elevation / 2),
                source_name=foundation.name if foundation is not None else _name(prefix, "Foundation_TimberBase"),
            )

        cap_height = max(0.08, min(0.16, foundation_render_height * 0.3))
        cap_depth = max(0.05, min(0.08, spec.wall_thickness * 0.44))
        cap_z = foundation_render_height - cap_height / 2
        cap_proud_offset = max(0.02, cap_depth * 0.35)
        for label, size, location in (
            (
                "Front",
                (foundation_width, cap_depth, cap_height),
                (0.0, -foundation_depth / 2 + cap_depth / 2 - cap_proud_offset, cap_z),
            ),
            (
                "Back",
                (foundation_width, cap_depth, cap_height),
                (0.0, foundation_depth / 2 - cap_depth / 2 + cap_proud_offset, cap_z),
            ),
            (
                "Left",
                (cap_depth, foundation_depth - cap_depth * 2, cap_height),
                (-foundation_width / 2 + cap_depth / 2 - cap_proud_offset, 0.0, cap_z),
            ),
            (
                "Right",
                (cap_depth, foundation_depth - cap_depth * 2, cap_height),
                (foundation_width / 2 - cap_depth / 2 + cap_proud_offset, 0.0, cap_z),
            ),
        ):
            cap = _create_box(
                _name(prefix, f"Foundation_TimberCap_{label}"),
                size,
                location,
                collection,
                parent,
                trim_material,
            )
            _mark_section(
                _mark_generated(cap, tbg_timber_foundation=True, tbg_foundation_cap=True),
                "Section_Walls_Trim",
                hide_with_walls=True,
            )
        return

    _build_foundation_profile_accents(prefix, spec, collection, parent, materials_map)
    foundation_width = spec.width + GROUND_PLINTH_DEPTH * 2
    foundation_depth = spec.depth + GROUND_PLINTH_DEPTH * 2
    foundation_parts = _build_foundation_podium_render(
        prefix,
        spec=spec,
        collection=collection,
        parent=parent,
        material=material,
        width=foundation_width,
        depth=foundation_depth,
        height=foundation_render_height,
        base_name="Foundation_Podium",
    )
    foundation = foundation_parts[0] if foundation_parts else None
    if runtime_emitter is not None:
        runtime_emitter.emit_box(
            role=ROLE_PODIUM_BLOCKER,
            size=(foundation_width, foundation_depth, base_elevation),
            location=(0.0, 0.0, base_elevation / 2),
            source_name=foundation.name if foundation is not None else _name(prefix, "Foundation_Podium"),
        )

def _build_front_ground(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    front_facts=None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    wall_material = _wall_material_for_floor(materials_map, spec, 0)
    envelope = _front_entry_envelope(spec)
    door_center_x, _door_recess_y = _resolve_frontage_entry_pose(spec)
    _package_center_x, visible_opening_width = _front_entry_package_center_span(spec, envelope=envelope)
    visible_opening_left = door_center_x - visible_opening_width / 2
    visible_opening_right = door_center_x + visible_opening_width / 2
    base_z = _base_elevation(spec)
    front_y = -spec.depth / 2 + spec.wall_thickness / 2
    lintel_h = max(0.0, spec.floor_height - spec.door.height)
    left_w = visible_opening_left - (-spec.width / 2)
    right_w = spec.width / 2 - visible_opening_right
    hangar_frontage = _is_hangar_frontage(spec)
    storefront_mode = not hangar_frontage and spec.ground_floor_tactical_profile == GROUND_FLOOR_STOREFRONT
    roller_mode = not hangar_frontage and str(getattr(spec, "door_profile", "HINGED")).upper() == "ROLLER"
    ground_floor_facts = front_facts["floor_facts"][0] if front_facts is not None else None
    timber_frontage = _is_timber_frontage(spec)
    frontage_variant = _frontage_variant(spec) if _is_storefront_frontage(spec) else None
    walk_material = _frontage_walk_material(materials_map, timber=timber_frontage)

    if hangar_frontage:
        _build_hangar_front_ground(
            prefix,
            spec,
            collection,
            parent,
            materials_map,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )
        return
    if _is_storefront_frontage(spec):
        _build_storefront_front_ground(
            prefix,
            spec,
            collection,
            parent,
            materials_map,
            ground_floor_facts,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )
        return
    if _is_industrial_frontage(spec):
        _build_industrial_front_ground(
            prefix,
            spec,
            collection,
            parent,
            materials_map,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )
        return
    if _is_market_hall_frontage(spec):
        _build_market_hall_front_ground(
            prefix,
            spec,
            collection,
            parent,
            materials_map,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )
        return

    front_door_cut_rect = _ordinary_door_cut_rect(
        center_x=door_center_x,
        opening_width=envelope.door_width,
        base_z=base_z,
        door_height=spec.door.height,
    )
    front_plane_registered = False
    if not roller_mode:
        front_plane_registered = _register_linear_wall_plane(
            occupancy_author,
            orientation="X",
            wall_pos=front_y,
            start=-spec.width / 2,
            end=spec.width / 2,
            base_z=base_z,
            height=spec.floor_height,
            wall_t=spec.wall_thickness,
            material=wall_material,
            source_bucket="Section_Walls_Exterior",
            source_name=f"{_name(prefix, 'Front_F00')}:plane",
            staged_object_name=_name(prefix, "Front_F00"),
            rect_cuts=(("door", *front_door_cut_rect),),
        ) is not None
    front_wall_occupancy_author = None if front_plane_registered else occupancy_author

    def build_front_window_bay(
        label: str,
        span_start: float,
        span_end: float,
        slot_index: int,
        *,
        storefront: bool,
        force_open: bool,
    ) -> bool:
        span = span_end - span_start
        if span < 2.2:
            return False
        state = WINDOW_STATE_OPEN if force_open else (
            ground_floor_facts["planned_states"].get(slot_index, WINDOW_STATE_CLOSED)
            if ground_floor_facts is not None
            else WINDOW_STATE_CLOSED
        )
        if storefront:
            opening_width = min(3.2, span - max(0.26, span * 0.12) * 2)
            if opening_width < 1.8:
                return False
            opening_sill, opening_height, top_h = _window_verticals(spec.floor_height, spec.window_profile)
            lintel_height = top_h
        else:
            opening_width, opening_sill, opening_height, top_h = _slot_opening_profile(
                spec,
                state,
                span,
                spec.floor_height,
                side_key="front",
                floor_index=0,
                slot_index=slot_index,
            )
            lintel_height = top_h
        center_x = (span_start + span_end) / 2
        opening_left = center_x - opening_width / 2
        opening_right = center_x + opening_width / 2
        protect_opening = bool(
            ground_floor_facts is not None and slot_index in ground_floor_facts["protected_openings"]
        )
        storefront_metadata = (
            {
                "tbg_storefront_window": True,
                "tbg_storefront_part": True,
                "tbg_storefront_part_kind": "Glazing",
                "tbg_storefront_slot": int(slot_index),
            }
            if storefront
            else None
        )

        for part_label, start, end, center_z, height in (
            ("PierLeft", span_start, opening_left, base_z + spec.floor_height / 2, spec.floor_height),
            ("PierRight", opening_right, span_end, base_z + spec.floor_height / 2, spec.floor_height),
            ("Sill", opening_left, opening_right, base_z + opening_sill / 2, opening_sill),
            ("Lintel", opening_left, opening_right, base_z + opening_sill + opening_height + lintel_height / 2, lintel_height),
        ):
            _emit_front_wall_piece(
                prefix,
                f"{label}_{part_label}",
                spec,
                collection,
                parent,
                wall_material,
                width=end - start,
                center_x=(start + end) / 2,
                center_z=center_z,
                height=height,
                occupancy_author=front_wall_occupancy_author,
                runtime_emitter=runtime_emitter,
            )

        _build_custom_window_slot(
            prefix,
            label,
            "X",
            "front",
            front_y,
            span_start,
            span_end,
            base_z,
            spec.floor_height,
            spec.wall_thickness,
            collection,
            parent,
            materials_map,
            spec,
            state=state,
            protect_opening=protect_opening,
            floor_index=0,
            slot_index=slot_index,
            opening_width=opening_width,
            sill_h=opening_sill,
            opening_h=opening_height,
            occupancy_author=front_wall_occupancy_author,
            merge_allowed=False,
            extra_metadata=storefront_metadata,
            runtime_emitter=runtime_emitter,
        )
        return True

    for label, width, center_x in (
        ("Front_F00_Left", left_w, -spec.width / 2 + left_w / 2),
        ("Front_F00_Right", right_w, visible_opening_right + right_w / 2),
    ):
        if width <= 1e-4:
            continue
        if storefront_mode or roller_mode:
            span_start = center_x - width / 2
            span_end = center_x + width / 2
            if build_front_window_bay(
                label,
                span_start,
                span_end,
                0 if "Left" in label else 1,
                storefront=storefront_mode,
                force_open=roller_mode,
            ):
                continue
        _emit_front_wall_piece(
            prefix,
            label,
            spec,
            collection,
            parent,
            wall_material,
            width=width,
            center_x=center_x,
            center_z=base_z + spec.floor_height / 2,
            height=spec.floor_height,
            occupancy_author=front_wall_occupancy_author,
            runtime_emitter=runtime_emitter,
        )
    if lintel_h > 1e-4:
        _emit_front_wall_piece(
            prefix,
            "Front_F00_Lintel",
            spec,
            collection,
            parent,
            wall_material,
            width=visible_opening_width,
            center_x=door_center_x,
            center_z=base_z + spec.door.height + lintel_h / 2,
            height=lintel_h,
            occupancy_author=front_wall_occupancy_author,
            runtime_emitter=runtime_emitter,
        )

    if timber_frontage and front_facts is not None:
        _build_timber_siding_overlay(
            prefix,
            "Front",
            "front",
            "X",
            front_y,
            0,
            base_z,
            spec.floor_height,
            spec.wall_thickness,
            collection,
            parent,
            materials_map,
            spec,
            side_facts=front_facts,
            opening_bands_override=[
                (
                    visible_opening_left - 0.06,
                    visible_opening_right + 0.06,
                    base_z,
                    base_z + spec.door.height + 0.08,
                )
            ],
        )
    _strip_lower_facade_coplanar_bottom_caps(
        parent,
        side_key="front",
        floor_index=0,
        seam_z=base_z,
    )

    _build_front_entry_frame(
        prefix,
        "Door_Main",
        spec,
        collection,
        parent,
        materials_map["frame"],
        wall_pos=front_y,
        door_center_x=door_center_x,
        door_width=envelope.door_width,
        base_z=base_z,
        door_height=spec.door.height,
        door_cut_rect=front_door_cut_rect,
    )

    _build_ground_tactical_profile(prefix, spec, collection, parent, materials_map, runtime_emitter=runtime_emitter)
    if _is_stage1_identity_reset_family(spec) and str(getattr(spec, "preset_id", "")).lower() not in {"motel", "under_construction"}:
        return
    _build_entrance_stoop(prefix, spec, collection, parent, walk_material, runtime_emitter=runtime_emitter)

def _build_facade_bands(prefix, spec, collection, parent, materials_map):
    profile = str(getattr(spec, "facade_band_profile", "")).upper()
    if profile == FACADE_BAND_PROFILE_NONE:
        return
    completed_floors = _completed_facade_floor_count(spec)
    if completed_floors <= 0:
        return

    trim_material = _facade_trim_material(materials_map, spec)

    def band_layers(level_index: int) -> list[tuple[str, float, float, float, object, str]]:
        wall_material = _wall_material_for_floor(materials_map, spec, min(max(level_index - 1, 0), spec.floor_count - 1))
        if profile == FACADE_BAND_PROFILE_BRICK_REVEAL:
            return [("Reveal", max(0.04, spec.wall_thickness * 0.26), FACADE_BAND_HEIGHT * 0.82, 0.0, wall_material, "Section_Walls_Exterior")]
        if profile == FACADE_BAND_PROFILE_CONCRETE_BAND:
            return [("Concrete", max(FACADE_BAND_DEPTH * 1.2, spec.wall_thickness * 0.54), FACADE_BAND_HEIGHT * 1.15, 0.0, trim_material, "Section_Walls_Trim")]
        if profile == FACADE_BAND_PROFILE_HEAVY_CORNICE:
            return [
                ("Cornice", max(FACADE_BAND_DEPTH * 1.45, spec.wall_thickness * 0.62), FACADE_BAND_HEIGHT * 1.35, 0.0, trim_material, "Section_Walls_Trim"),
                ("Lip", max(FACADE_BAND_DEPTH * 0.7, spec.wall_thickness * 0.34), FACADE_BAND_HEIGHT * 0.42, FACADE_BAND_HEIGHT * 0.78, wall_material, "Section_Walls_Exterior"),
            ]
        return [("Trim", max(FACADE_BAND_DEPTH, spec.wall_thickness * 0.45), FACADE_BAND_HEIGHT, 0.0, trim_material, "Section_Walls_Trim")]

    band_levels = [
        (floor, _level_base_z(spec, floor), (-spec.width / 2, spec.width / 2, -spec.depth / 2, spec.depth / 2))
        for floor in range(1, completed_floors)
    ]
    if completed_floors >= spec.floor_count:
        band_levels.append(
            (
                spec.floor_count,
                _roof_surface_z(spec) - FACADE_BAND_HEIGHT / 2,
                _floor_shell_rect(spec, spec.floor_count - 1),
            )
        )

    for idx, (level_index, level_z, shell_rect) in enumerate(band_levels):
        x0, x1, y0, y1 = shell_rect
        for layer_name, band_depth, band_height, z_offset, material, section in band_layers(level_index):
            front_width = max(0.01, x1 - x0)
            side_band_span = max(0.01, y1 - y0 - band_depth * 2.0)
            center_z = max(band_height / 2, level_z + z_offset)
            front_y = y0 + spec.wall_thickness / 2
            back_y = y1 - spec.wall_thickness / 2
            left_x = x0 + spec.wall_thickness / 2
            right_x = x1 - spec.wall_thickness / 2
            _mark_wall_section(
                _create_opening_box(
                    _name(prefix, f"FacadeBand_{layer_name}_Front_{idx:02d}"),
                    "X",
                    front_width,
                    band_depth,
                    band_height,
                    (x0 + x1) / 2,
                    _surface_coord("front", front_y, spec.wall_thickness, band_depth, exterior=True, offset=0.0),
                    center_z,
                    collection,
                    parent,
                    material,
                ),
                section,
            )
            _mark_wall_section(
                _create_opening_box(
                    _name(prefix, f"FacadeBand_{layer_name}_Back_{idx:02d}"),
                    "X",
                    front_width,
                    band_depth,
                    band_height,
                    (x0 + x1) / 2,
                    _surface_coord("back", back_y, spec.wall_thickness, band_depth, exterior=True, offset=0.0),
                    center_z,
                    collection,
                    parent,
                    material,
                ),
                section,
            )
            _mark_wall_section(
                _create_opening_box(
                    _name(prefix, f"FacadeBand_{layer_name}_Left_{idx:02d}"),
                    "Y",
                    side_band_span,
                    band_depth,
                    band_height,
                    (y0 + y1) / 2,
                    _surface_coord("left", left_x, spec.wall_thickness, band_depth, exterior=True, offset=0.0),
                    center_z,
                    collection,
                    parent,
                    material,
                ),
                section,
            )
            _mark_wall_section(
                _create_opening_box(
                    _name(prefix, f"FacadeBand_{layer_name}_Right_{idx:02d}"),
                    "Y",
                    side_band_span,
                    band_depth,
                    band_height,
                    (y0 + y1) / 2,
                    _surface_coord("right", right_x, spec.wall_thickness, band_depth, exterior=True, offset=0.0),
                    center_z,
                    collection,
                    parent,
                    material,
                ),
                section,
            )

def _build_main_door(
    prefix,
    spec,
    spatial_plan,
    collection,
    parent,
    material,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    *,
    facade_facts=None,
):
    if not spec.door.enabled:
        return None
    if _is_hangar_frontage(spec):
        return None

    envelope = _front_entry_envelope(spec)
    door_center_x, door_recess_y = _resolve_frontage_entry_pose(spec)
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    if preset_id in {"warehouse", "depot"}:
        door_recess_y = -spec.depth / 2 + spec.wall_thickness / 2
    if _is_market_hall_frontage(spec):
        front_y = door_recess_y
        door_center_z = _base_elevation(spec) + spec.door.height / 2
        hinge_x = door_center_x - envelope.door_width / 2 if spec.door.hinge == constants.HINGE_LEFT else door_center_x + envelope.door_width / 2
        origin_mode = "HINGE_LEFT" if spec.door.hinge == constants.HINGE_LEFT else "HINGE_RIGHT"
        open_rotation = math.radians(95.0) if spec.door.hinge == constants.HINGE_LEFT else math.radians(-95.0)
        door = _create_box(
            _name(prefix, "Door_Main"),
            (envelope.door_width, spec.door.thickness, spec.door.height),
            (hinge_x, front_y, door_center_z),
            collection,
            parent,
            material,
            origin_mode=origin_mode,
        )
        door = _mark_generated(door, tbg_door_panel=True, tbg_door_handle_plate=True)
        return _mark_door_leaf(door, open_rotation_z=open_rotation)
    front_y = door_recess_y + spec.door.thickness / 2 + 0.015
    door_center_z = _base_elevation(spec) + spec.door.height / 2
    if str(getattr(spec, "door_profile", "HINGED")).upper() == "ROLLER" and not _is_storefront_frontage(spec):
        panel_depth = max(0.05, min(spec.wall_thickness, max(spec.door.thickness, spec.wall_thickness * 0.4)))
        door = _create_box(
            _name(prefix, "Door_Main"),
            (envelope.door_width, panel_depth, spec.door.height),
            (door_center_x, door_recess_y, door_center_z),
            collection,
            parent,
            material,
        )
        door = _mark_generated(
            door,
            tbg_door_panel=True,
            tbg_door_handle_plate=True,
            tbg_roller_door=True,
        )
        door = _mark_door_leaf(door, open_rotation_z=0.0)
        if runtime_emitter is not None and door is not None:
            runtime_emitter.emit_box(
                role=ROLE_WINDOW_CLOSED,
                size=(envelope.door_width, panel_depth, spec.door.height),
                location=(door_center_x, door_recess_y, door_center_z),
                source_name=door.name,
                metadata_values={"tbg_runtime_side": "front", "tbg_runtime_floor": 0, "tbg_runtime_slot": -1},
            )
        return door

    door_cut_rect = _ordinary_door_cut_rect(
        center_x=door_center_x,
        opening_width=envelope.door_width,
        base_z=_base_elevation(spec),
        door_height=spec.door.height,
    )
    door_cut_metadata = _ordinary_door_cut_metadata(
        side_key="front",
        orientation="X",
        wall_pos=-spec.depth / 2 + spec.wall_thickness / 2,
        center_x=door_center_x,
        opening_width=envelope.door_width,
        base_z=_base_elevation(spec),
        door_height=spec.door.height,
        cut_rect=door_cut_rect,
    )
    if spec.door.hinge == constants.HINGE_LEFT:
        hinge_x = door_center_x - envelope.door_width / 2
        origin_mode = "HINGE_LEFT"
        open_rotation = math.radians(95.0)
    else:
        hinge_x = door_center_x + envelope.door_width / 2
        origin_mode = "HINGE_RIGHT"
        open_rotation = math.radians(-95.0)

    door = _create_box(
        _name(prefix, "Door_Main"),
        (envelope.door_width, spec.door.thickness, spec.door.height),
        (hinge_x, front_y, door_center_z),
        collection,
        parent,
        material,
        origin_mode=origin_mode,
    )
    door = _mark_generated(
        door,
        tbg_door_panel=True,
        tbg_door_handle_plate=True,
        **door_cut_metadata,
    )
    door = _mark_door_leaf(door, open_rotation_z=open_rotation)
    return door

def _build_outer_shell_step(
    prefix,
    spec,
    spatial_plan,
    collection,
    parent,
    materials_map,
    side_key: str,
    floor: int,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    *,
    facade_facts=None,
):
    wall_t = spec.wall_thickness
    rear_access_profile = str(
        getattr(
            spatial_plan,
            "rear_access_profile",
            REAR_ACCESS_PROFILE_SERVICE_DOOR,
        )
    )
    frontage_variant = _frontage_variant(spec)
    forced_ac_target = _mandatory_facade_ac_target(spec, facade_facts)
    front_facts = facade_facts["front"]
    back_facts = facade_facts["back"]
    left_facts = facade_facts["left"]
    right_facts = facade_facts["right"]

    side_map = {
        "back": ("Back", "X", back_facts),
        "left": ("Left", "Y", left_facts),
        "right": ("Right", "Y", right_facts),
        "front": ("Front", "X", front_facts),
    }
    if side_key not in side_map:
        raise ValueError(f"Unsupported outer-shell side: {side_key}")

    side_label, orientation, side_facts = side_map[side_key]
    if side_key == "front" and floor == 0:
        if front_facts["floor_facts"][0].get("active", True):
            _build_front_ground(
                prefix,
                spec,
                collection,
                parent,
                materials_map,
                front_facts,
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
        return

    floor_facts = side_facts["floor_facts"][floor]
    if side_key == "back" and floor == 0:
        if (
            frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE
            and rear_access_profile == REAR_ACCESS_PROFILE_SERVICE_DOOR
        ):
            _build_warehouse_back_ground(
                prefix,
                spec,
                collection,
                parent,
                materials_map,
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
            return
        if (
            frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_DEPOT
            and rear_access_profile == REAR_ACCESS_PROFILE_OPEN_BAY
        ):
            _build_depot_back_ground(
                prefix,
                spec,
                collection,
                parent,
                materials_map,
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
            return
    if _pilotis_open_side(spec, side_key, floor):
        _build_pilotis_columns(
            prefix,
            side_label,
            side_key,
            orientation,
            floor_facts["wall_pos"],
            floor,
            _level_base_z(spec, floor),
            spec.floor_height,
            spec,
            collection,
            parent,
            _wall_material_for_floor(materials_map, spec, floor),
            runtime_emitter=runtime_emitter,
        )
        return
    if not floor_facts.get("active", True):
        return
    rear_entry_band = None
    rear_entry_rect_cuts = None
    rear_opening_contract = None
    if (
        side_key == "back"
        and floor == 0
        and spatial_plan.rear_access
        and rear_access_profile in {REAR_ACCESS_PROFILE_SERVICE_DOOR, REAR_ACCESS_PROFILE_SHELL_ONLY}
    ):
        rear_opening_contract = _rear_entry_opening_contract(floor_facts)
        rear_door_context = _resolve_rear_door_cut_context(spec, rear_opening_contract)
        if rear_door_context is not None:
            rear_entry_rect_cuts = [rear_door_context["cut_rect"]]
            rear_entry_band = [rear_door_context["cut_rect"]]
    _build_facade_wall(
        prefix,
        side_label,
        side_key,
        orientation,
        floor_facts["wall_pos"],
        floor,
        _level_base_z(spec, floor),
        spec.floor_height,
        wall_t,
        collection,
        parent,
        materials_map,
        spec,
        forced_ac_slot=(
            forced_ac_target[2]
            if forced_ac_target is not None and forced_ac_target[0] == side_key and forced_ac_target[1] == floor
            else None
        ),
        side_facts=side_facts,
        opening_bands_override=rear_entry_band,
        rect_cuts_override=rear_entry_rect_cuts,
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
    )
    if rear_opening_contract is not None and rear_access_profile == REAR_ACCESS_PROFILE_SERVICE_DOOR:
        _build_rear_through_opening(
            prefix,
            spec,
            collection,
            parent,
            materials_map,
            rear_opening_contract,
            runtime_emitter=runtime_emitter,
        )


def _build_outer_shell(
    prefix,
    spec,
    spatial_plan,
    collection,
    parent,
    materials_map,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    *,
    facade_facts=None,
):
    for floor in range(spec.floor_count):
        for side_key in ("back", "left", "right", "front"):
            _build_outer_shell_step(
                prefix,
                spec,
                spatial_plan,
                collection,
                parent,
                materials_map,
                side_key,
                floor,
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
                facade_facts=facade_facts,
            )

def _build_wall_service_pipes(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    *,
    facade_facts=None,
    spatial_plan=None,
):
    """Build facade-mounted service pipe clusters — reference-matched style.

    Primary ownership is a decorative wall-mounted cluster that lives in solid
    facade gaps, not a full roof-to-ground riser.
    """
    if (
        _is_hangar_frontage(spec)
        or _is_timber_frontage(spec)
        or _is_storefront_frontage(spec)
        or _is_market_hall_frontage(spec)
        or str(getattr(spec, "preset_id", "")).lower() == "under_construction"
    ):
        return

    pipe_band = _wall_service_pipe_band(spec)
    if not bool(pipe_band["spawnable"]):
        return
    entry = _front_entry_envelope(spec)
    _build_wall_service_pipes_owner(
        prefix,
        spec,
        collection,
        parent,
        materials_map,
        pipe_band=pipe_band,
        entry=entry,
        facade_facts=facade_facts,
        spatial_plan=spatial_plan,
        runtime_emitter=runtime_emitter,
    )

build_foundation_podium = _build_foundation_podium
build_facade_bands = _build_facade_bands
build_main_door = _build_main_door
build_outer_shell = _build_outer_shell
build_outer_shell_step = _build_outer_shell_step
build_wall_service_pipes = _build_wall_service_pipes
