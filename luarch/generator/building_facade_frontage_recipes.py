from __future__ import annotations

import math

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
from .building_facade_opening_slots import (
    build_custom_window_slot as _build_custom_window_slot,
    build_opening_trim as _build_opening_trim,
    opening_cut_frame_envelope as _opening_cut_frame_envelope,
    ordinary_door_cut_rect as _ordinary_door_cut_rect,
    register_linear_wall_plane as _register_linear_wall_plane,
    create_opening_box as _create_opening_box,
    wall_opening_cut_metadata as _wall_opening_cut_metadata,
)
from .building_occupancy import OccupancyAuthoringSession
from .layout_facade_planning import (
    _balcony_floor_enabled,
    _balcony_lookup,
    _balcony_material,
    _balcony_plans_for_side,
    _entry_stoop_package_ledger,
    _front_entry_package_center_span,
    _facade_window_layouts,
    _front_entry_envelope,
    _frontage_variant,
    _is_hangar_frontage,
    _is_industrial_frontage,
    _is_market_hall_frontage,
    _is_office_window_profile,
    _mandatory_ac_slot,
    _pilotis_column_positions,
    _planned_window_states,
    _selected_balcony_sides,
    _side_shell_metrics,
    _is_storefront_frontage,
    _is_timber_frontage,
    _rounded_stair_width_growth,
    _is_residential_wide,
    _slot_intervals,
    _solid_facade_spans,
    _stair_window_slots,
    _trim_material,
    _wall_material_for_floor,
    _window_verticals,
)
from .building_layout import (
    FRONTAGE_TYPE_INDUSTRIAL_DEPOT,
    FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE,
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
    FACADE_BAND_DEPTH,
    FACADE_BAND_HEIGHT,
    GROUND_FLOOR_DEFENSIVE_BASE,
    GROUND_FLOOR_MIXED_WINDOWS,
    GROUND_FLOOR_OPEN_ENTRY,
    GROUND_FLOOR_STOREFRONT,
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
    _side_sign,
    _stable_unit_float,
    _surface_coord,
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

def _facade_trim_material(materials_map, spec):
    return _trim_material(
        materials_map,
        spec.facade_family,
        facade_mode=getattr(spec, "facade_mode", None),
    )

def _emit_front_wall_piece(
    prefix,
    suffix: str,
    spec,
    collection,
    parent,
    material,
    *,
    width: float,
    center_x: float,
    center_z: float,
    height: float,
    merge_allowed: bool = True,
    generated_metadata: dict | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    wall_y: float | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    if width <= 0.04 or height <= 0.04:
        return None
    front_y = wall_y if wall_y is not None else -spec.depth / 2 + spec.wall_thickness / 2
    metadata = dict(generated_metadata or {})
    metadata["tbg_facade_side"] = "front"
    metadata["tbg_facade_floor"] = 0
    planned_name = _name(prefix, suffix)
    _register_linear_wall_plane(
        occupancy_author,
        orientation="X",
        wall_pos=front_y,
        start=center_x - width / 2,
        end=center_x + width / 2,
        base_z=center_z - height / 2,
        height=height,
        wall_t=spec.wall_thickness,
        material=material,
        source_bucket="Section_Walls_Exterior",
        source_name=f"{planned_name}:plane",
        staged_object_name=planned_name,
    )
    wall = _create_opening_box(
        planned_name,
        "X",
        width,
        spec.wall_thickness,
        height,
        center_x,
        front_y,
        center_z,
        collection,
        parent,
        material,
    )
    wall = _mark_section(
        _mark_generated(wall, **metadata),
        "Section_Walls_Exterior",
        merge_allowed=merge_allowed,
        hide_with_walls=True,
    )
    if runtime_emitter is not None and wall is not None:
        runtime_emitter.emit_box(
            role=ROLE_SHELL,
            size=(width, spec.wall_thickness, height),
            location=(center_x, front_y, center_z),
            rotation=_orientation_rotation("X"),
            source_name=wall.name,
            metadata_values={"tbg_runtime_side": "front", "tbg_runtime_floor": 0},
        )
    return wall

def _emit_frontage_shell_piece(
    prefix,
    name_suffix: str,
    spec,
    collection,
    parent,
    material,
    *,
    orientation: str,
    width: float,
    depth: float,
    height: float,
    along_coord: float,
    normal_coord: float,
    center_z: float,
    section: str = "Section_Walls_Exterior",
    merge_allowed: bool = True,
    generated_metadata: dict | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    runtime_side: str = "front",
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    if width <= 0.04 or depth <= 0.04 or height <= 0.04:
        return None
    planned_name = _name(prefix, name_suffix)
    span_start = along_coord - width / 2
    span_end = along_coord + width / 2
    if section.startswith("Section_Walls"):
        _register_linear_wall_plane(
            occupancy_author,
            orientation=orientation,
            wall_pos=normal_coord,
            start=span_start,
            end=span_end,
            base_z=center_z - height / 2,
            height=height,
            wall_t=depth,
            material=material,
            source_bucket=section,
            source_name=f"{planned_name}:plane",
            staged_object_name=planned_name,
        )
    piece = _create_opening_box(
        planned_name,
        orientation,
        width,
        depth,
        height,
        along_coord,
        normal_coord,
        center_z,
        collection,
        parent,
        material,
    )
    piece = _mark_section(
        _mark_generated(piece, **(generated_metadata or {})),
        section,
        merge_allowed=merge_allowed,
        hide_with_walls=section.startswith("Section_Walls"),
    )
    if runtime_emitter is not None and section.startswith("Section_Walls") and piece is not None:
        runtime_emitter.emit_box(
            role=ROLE_SHELL,
            size=(width, depth, height) if orientation == "X" else (depth, width, height),
            location=tuple(float(value) for value in piece.location),
            rotation=tuple(float(value) for value in piece.rotation_euler),
            source_name=piece.name,
            metadata_values={"tbg_runtime_side": runtime_side, "tbg_runtime_floor": 0},
    )
    return piece

def _build_front_entry_frame(
    prefix,
    suffix: str,
    spec,
    collection,
    parent,
    material,
    *,
    wall_pos: float,
    door_center_x: float,
    door_width: float,
    base_z: float,
    door_height: float,
    merge_allowed: bool = True,
    stamp_outer_bounds: bool = True,
    generated_metadata: dict | None = None,
    door_cut_rect: tuple[float, float, float, float] | None = None,
):
    if str(getattr(spec, "preset_id", "")).lower() == "under_construction":
        return None
    if (
        str(suffix) == "Door_Main"
        and _frontage_variant(spec) in {
            FRONTAGE_TYPE_INDUSTRIAL_DEPOT,
            FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE,
        }
    ):
        # Industrial depot/warehouse frontages author their personnel
        # entry frame in the dedicated frontage path; the legacy generic
        # Door_Main frame would duplicate the same front-door contract.
        return None

    resolved_door_cut_rect = door_cut_rect or _ordinary_door_cut_rect(
        center_x=door_center_x,
        opening_width=door_width,
        base_z=base_z,
        door_height=door_height,
    )
    door_cut_metadata = _wall_opening_cut_metadata(
        kind="door",
        orientation="X",
        side_key="front",
        floor_index=0,
        slot_index=-1,
        wall_pos=wall_pos,
        cut_rect=resolved_door_cut_rect,
    )
    frame_along_coord, frame_outer_width, frame_outer_height, frame_mid_z = _opening_cut_frame_envelope(
        door_cut_metadata
    )
    frame_along_coord = float(frame_along_coord if frame_along_coord is not None else door_center_x)
    frame_width = float(frame_outer_width if frame_outer_width is not None else door_width)
    authored_left = float(door_center_x - door_width / 2)
    authored_right = float(door_center_x + door_width / 2)

    frame = _build_opening_trim(
        prefix,
        suffix,
        "X",
        "front",
        wall_pos,
        frame_along_coord,
        door_width,
        base_z,
        door_height,
        0.0,
        spec.wall_thickness,
        collection,
        parent,
        material,
        office_style=False,
        placement="outer_proud",
        double_sided=True,
        outer_width_override=frame_outer_width,
        outer_height_override=frame_outer_height,
        opening_mid_z_override=frame_mid_z,
    )
    metadata = {
        "tbg_door_frame": True,
        "tbg_door_frame_left": authored_left,
        "tbg_door_frame_right": authored_right,
        "tbg_door_threshold_z": float(base_z),
        "tbg_door_wall_pos": float(wall_pos),
        "tbg_facade_side": "front",
        "tbg_facade_plane": "both",
    }
    metadata.update(door_cut_metadata)
    if stamp_outer_bounds:
        metadata["tbg_door_frame_outer_left"] = float(frame_along_coord - frame_width / 2)
        metadata["tbg_door_frame_outer_right"] = float(frame_along_coord + frame_width / 2)
    if generated_metadata:
        metadata.update(generated_metadata)
    return _mark_section(
        _mark_generated(frame, **metadata),
        "Section_Doors_Trim",
        # Door-frame cut stamps are per-opening scalar facts.  Merging this
        # mesh into the door-trim bucket would collapse that seating source
        # back into an unstamped composite object.
        merge_allowed=False,
    )


def _build_entry_stoop_package(
    prefix,
    name_stem: str,
    spec,
    collection,
    parent,
    material,
    *,
    center_x: float,
    landing_width: float,
    landing_depth: float,
    landing_height: float,
    landing_center_y: float,
    landing_outer_edge_y: float,
    threshold_z: float,
    stair_run: float,
    step_count: int,
    outward_sign: float,
    facade_side: str | None = None,
    stoop_variant: str | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    runtime_landing_role: str | None = None,
    runtime_wedge_role: str | None = None,
    runtime_wedge_metadata: dict | None = None,
    landing_generated_metadata: dict | None = None,
    step_generated_metadata: dict | None = None,
    package_left_x: float | None = None,
    package_right_x: float | None = None,
):
    if landing_depth <= 0.0 or landing_height <= 0.0 or threshold_z <= 0.0:
        return (None, None)

    runtime_landing_size = (landing_width, landing_depth, landing_height)
    runtime_landing_location = (center_x, landing_center_y, threshold_z - landing_height / 2)

    if package_left_x is not None and package_right_x is not None:
        resolved_package_left_x = min(float(package_left_x), float(package_right_x))
        resolved_package_right_x = max(float(package_left_x), float(package_right_x))
    else:
        half_width = max(0.0, float(landing_width) / 2)
        resolved_package_left_x = float(center_x) - half_width
        resolved_package_right_x = float(center_x) + half_width
    resolved_package_width = max(0.0, resolved_package_right_x - resolved_package_left_x)
    if resolved_package_width <= 1e-4:
        return (None, None)
    center_x = (resolved_package_left_x + resolved_package_right_x) / 2
    landing_width = min(max(0.0, float(landing_width)), resolved_package_width)
    stair_width_cap = max(landing_width, resolved_package_width)

    def _stoop_outer_sign() -> float:
        return -1.0 if float(outward_sign) < 0.0 else 1.0

    def _stoop_flight_pose(run_depth: float, *, interior_inset: float = 0.0) -> tuple[float, float]:
        run_depth = max(0.0, float(run_depth))
        interior_inset = max(0.0, float(interior_inset))
        sign = _stoop_outer_sign()
        back_edge_y = landing_outer_edge_y - sign * interior_inset
        return (back_edge_y + sign * run_depth / 2, math.pi if sign > 0.0 else 0.0)

    def _rounded_outer_landing_mesh(name: str, width: float, depth: float, height: float):
        corner_radius = min(width * 0.22, depth * 0.38, 0.32)
        front_bulge_depth = min(corner_radius * 0.55, depth * 0.14, 0.12)
        outline = _rounded_outer_outline(
            width,
            depth,
            outer_sign_value=-1.0,
            corner_radius=corner_radius,
            front_bulge_depth=front_bulge_depth,
            corner_segments=5,
            front_segments=7,
        )
        if outline is None:
            return None
        return _outline_prism_mesh(name, outline, -height / 2, height / 2)

    def _rounded_outer_outline(
        width: float,
        depth: float,
        *,
        outer_sign_value: float,
        corner_radius: float,
        front_bulge_depth: float,
        corner_segments: int,
        front_segments: int,
    ) -> list[tuple[float, float]] | None:
        half_w = width / 2
        half_d = depth / 2
        if half_w <= 0.04 or half_d <= 0.04:
            return None
        dir_sign = -1.0 if float(outer_sign_value) < 0.0 else 1.0
        corner_radius = max(0.06, float(corner_radius))
        corner_radius = min(corner_radius, half_w - 0.02, half_d * 0.78)
        if corner_radius <= 0.02:
            return None
        front_bulge_depth = max(0.0, float(front_bulge_depth))
        front_bulge_depth = min(front_bulge_depth, corner_radius * 0.72, half_d * 0.24)
        corner_segments = max(int(corner_segments), 3)
        front_segments = max(int(front_segments), 4)
        back_y = -dir_sign * half_d
        front_y = dir_sign * half_d
        side_stop_y = front_y - dir_sign * corner_radius
        if abs(back_y - side_stop_y) <= 0.02:
            return None
        front_radius_x = half_w - corner_radius
        if front_radius_x <= 0.02:
            return None

        right_center_x = half_w - corner_radius
        right_corner: list[tuple[float, float]] = []
        for idx in range(corner_segments + 1):
            alpha = (math.pi / 2) * (idx / corner_segments)
            x = right_center_x + corner_radius * math.cos(alpha)
            y = side_stop_y + dir_sign * corner_radius * math.sin(alpha)
            right_corner.append((x, y))

        front_arc: list[tuple[float, float]] = []
        for idx in range(front_segments + 1):
            theta = math.pi * (idx / front_segments)
            x = front_radius_x * math.cos(theta)
            y = front_y + dir_sign * front_bulge_depth * math.sin(theta)
            front_arc.append((x, y))

        left_corner = [(-x, y) for x, y in reversed(right_corner)]
        outline: list[tuple[float, float]] = []
        outline.extend(((-half_w, back_y), (half_w, back_y), right_corner[0]))
        outline.extend(right_corner[1:])
        outline.extend(front_arc[1:-1])
        outline.extend(left_corner)
        return outline

    def _outline_prism_mesh(name: str, outline: list[tuple[float, float]], lower_z: float, upper_z: float):
        count = len(outline)
        verts = [(x, y, lower_z) for x, y in outline] + [(x, y, upper_z) for x, y in outline]
        faces = []
        for idx in range(count):
            nxt = (idx + 1) % count
            faces.append((idx, nxt, count + nxt, count + idx))
        faces.append(tuple(range(count - 1, -1, -1)))
        faces.append(tuple(range(count, count * 2)))
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, [], faces)
        mesh.update(calc_edges=True)
        return mesh

    def _append_outline_prism(
        verts: list[tuple[float, float, float]],
        faces: list[tuple[int, ...]],
        outline: list[tuple[float, float]],
        *,
        center_x_value: float,
        center_y_value: float,
        lower_z: float,
        upper_z: float,
        include_bottom: bool = True,
        include_top: bool = True,
    ):
        base = len(verts)
        count = len(outline)
        verts.extend((center_x_value + x, center_y_value + y, lower_z) for x, y in outline)
        verts.extend((center_x_value + x, center_y_value + y, upper_z) for x, y in outline)
        for idx in range(count):
            nxt = (idx + 1) % count
            faces.append((base + idx, base + nxt, base + count + nxt, base + count + idx))
        if include_bottom:
            faces.append(tuple(base + idx for idx in range(count - 1, -1, -1)))
        if include_top:
            faces.append(tuple(base + count + idx for idx in range(count)))

    def _rounded_solid_stepped_flight_mesh(
        name: str,
        width: float,
        tread: float,
        step_count_value: int,
        step_rise_value: float,
        *,
        outer_sign_value: float,
        max_width: float | None = None,
    ):
        tread_count = max(int(step_count_value), 1)
        step_rise = max(step_rise_value, 0.05)
        run_total = tread * tread_count
        total_height = step_rise * tread_count
        back_edge = run_total / 2
        verts: list[tuple[float, float, float]] = []
        faces: list[tuple[int, ...]] = []

        top_width = max(width * 0.84, width - max(0.26, width * 0.12))
        width_growth_total = _rounded_stair_width_growth(width, run_total)
        top_depth = min(run_total, max(tread * 0.96, min(tread * 1.16, run_total * 0.44)))
        bottom_depth_target = run_total + min(0.14, max(0.06, run_total * 0.07))
        depth_growth_step = (
            (bottom_depth_target - top_depth) / max(tread_count - 1, 1)
            if tread_count > 1
            else 0.0
        )

        for idx in range(tread_count):
            progress = idx / max(tread_count - 1, 1)
            step_width = min(width + width_growth_total, top_width + width_growth_total * (progress ** 0.92))
            if max_width is not None:
                step_width = min(step_width, max(0.0, float(max_width)))
            step_depth = min(bottom_depth_target, top_depth + depth_growth_step * idx)
            corner_radius = min(step_width * 0.2, step_depth * 0.4, 0.34)
            front_bulge_depth = min(corner_radius * 0.5, step_depth * 0.12, 0.12)
            outline = _rounded_outer_outline(
                step_width,
                step_depth,
                outer_sign_value=outer_sign_value,
                corner_radius=corner_radius,
                front_bulge_depth=front_bulge_depth,
                corner_segments=4,
                front_segments=7,
            )
            if outline is None:
                continue
            tread_center_y = back_edge - step_depth / 2
            layer_lower_z = 0.0
            layer_upper_z = max(step_rise, total_height - idx * step_rise)
            if layer_upper_z <= layer_lower_z + 1e-4:
                continue
            _append_outline_prism(
                verts,
                faces,
                outline,
                center_x_value=0.0,
                center_y_value=tread_center_y,
                lower_z=layer_lower_z,
                upper_z=layer_upper_z,
                include_bottom=idx == tread_count - 1,
            )
        if not verts:
            return _solid_stepped_flight_mesh(
                name,
                width,
                tread,
                tread_count,
                step_rise,
            )
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, [], faces)
        mesh.update(calc_edges=True)
        return mesh

    outer_sign_value = _stoop_outer_sign()
    landing_name = _name(prefix, f"{name_stem}_Stoop")
    landing_variant = str(stoop_variant or "").strip().replace("-", "_").lower()
    rounded_variant = landing_variant in {"rounded"}
    rounded_unified_stoop = rounded_variant and stair_run > 0.0 and step_count > 0
    if landing_variant in {"rounded"}:
        if rounded_unified_stoop:
            anchor_width = max(0.06, min(0.22, landing_width * 0.14))
            anchor_depth = max(0.06, min(0.16, landing_depth * 0.2))
            anchor_height = max(0.06, min(0.14, landing_height * 0.3))
            anchor_back_edge_y = landing_outer_edge_y - outer_sign_value * landing_depth
            anchor_center_y = anchor_back_edge_y - outer_sign_value * max(anchor_depth * 0.5, 0.04)
            anchor_center_z = min(
                threshold_z - anchor_height * 0.55,
                max(anchor_height / 2, threshold_z - max(anchor_height, 0.08)),
            )
            runtime_landing_size = (anchor_width, anchor_depth, anchor_height)
            runtime_landing_location = (center_x, anchor_center_y, anchor_center_z)
            landing = _create_box(
                landing_name,
                (anchor_width, anchor_depth, anchor_height),
                (center_x, anchor_center_y, anchor_center_z),
                collection,
                parent,
                material,
            )
            landing.hide_viewport = True
            landing.hide_render = True
        else:
            landing_mesh = _rounded_outer_landing_mesh(
                landing_name,
                landing_width,
                landing_depth,
                threshold_z,
            )
            if landing_mesh is not None:
                landing = bpy.data.objects.new(landing_name, landing_mesh)
                collection.objects.link(landing)
                _parent_to(landing, parent)
                landing.location = Vector((center_x, landing_center_y, threshold_z / 2))
                landing.rotation_euler = Euler(
                    (0.0, 0.0, math.pi if _stoop_outer_sign() > 0.0 else 0.0),
                    "XYZ",
                )
                _assign_material(landing, material)
            else:
                landing = _create_box(
                    landing_name,
                    (landing_width, landing_depth, threshold_z),
                    (center_x, landing_center_y, threshold_z / 2),
                    collection,
                    parent,
                    material,
                )
    else:
        landing = _create_box(
            landing_name,
            (landing_width, landing_depth, landing_height),
            (center_x, landing_center_y, threshold_z - landing_height / 2),
            collection,
            parent,
            material,
        )
    if rounded_unified_stoop:
        landing = _mark_generated(
            landing,
            tbg_section_merge_allowed=False,
            **(landing_generated_metadata or {}),
        )
    else:
        landing = _mark_section(
            _mark_generated(landing, **(landing_generated_metadata or {})),
            "Section_Floors",
        )
    if runtime_emitter is not None and runtime_landing_role is not None and landing is not None:
        runtime_emitter.emit_box(
            role=runtime_landing_role,
            size=runtime_landing_size,
            location=runtime_landing_location,
            source_name=landing.name,
        )

    if stair_run <= 0.0 or step_count <= 0:
        return (landing, None)

    step_run = stair_run
    flight_inset = landing_depth if rounded_unified_stoop else 0.0
    step_rise = max(0.05, threshold_z / max(step_count, 1))
    tread = step_run / max(step_count, 1)
    stair_mesh_width = min(stair_width_cap, landing_width + 0.16)
    flight_name = _name(prefix, f"{name_stem}_Flight")
    if rounded_variant:
        step_mesh = _rounded_solid_stepped_flight_mesh(
            flight_name,
            stair_mesh_width,
            tread,
            step_count,
            step_rise,
            outer_sign_value=-1.0,
            max_width=stair_width_cap,
        )
    else:
        step_mesh = _solid_stepped_flight_mesh(
            flight_name,
            stair_mesh_width,
            tread,
            step_count,
            step_rise,
        )
    step = bpy.data.objects.new(flight_name, step_mesh)
    collection.objects.link(step)
    _parent_to(step, parent)
    if rounded_variant:
        outer_sign = _stoop_outer_sign()
        threshold_y = landing_outer_edge_y - outer_sign * landing_depth
        flight_center_y = threshold_y + outer_sign * step_run / 2
        flight_rotation_z = math.pi if outer_sign > 0.0 else 0.0
    else:
        flight_center_y, flight_rotation_z = _stoop_flight_pose(step_run, interior_inset=flight_inset)
    step.location = Vector((center_x, flight_center_y, 0.0))
    step.rotation_euler = Euler((0.0, 0.0, flight_rotation_z), "XYZ")
    _assign_material(step, material)
    step = _mark_section(
        _mark_generated(step, **(step_generated_metadata or {})),
        "Section_Floors",
    )
    if runtime_emitter is not None and runtime_wedge_role is not None and step is not None:
        runtime_emitter.emit_wedge(
            role=runtime_wedge_role,
            width=stair_mesh_width,
            depth=stair_run,
            height=threshold_z,
            location=(center_x, flight_center_y, threshold_z / 2),
            rotation=(0.0, 0.0, flight_rotation_z),
            source_name=step.name,
            metadata_values=runtime_wedge_metadata,
        )
    return (landing, step)


def _warehouse_door_center_x(spec, envelope) -> float:
    span_limit = spec.width / 2 - envelope.door_width / 2 - 0.92
    return max(-span_limit, min(span_limit, 0.0))

# hangar_open_hall

def _market_hall_frontage_geometry(spec, envelope):
    front_wall_y = -spec.depth / 2 + spec.wall_thickness / 2
    base_z = _base_elevation(spec)
    hall_width = min(spec.width - 0.32, max(envelope.frontage_width, spec.width * 0.82))
    hall_half_width = hall_width / 2
    hall_depth = max(1.52, min(2.02, max(1.62, spec.depth * 0.2)))
    recess_depth = max(0.72, min(0.98, max(spec.wall_thickness * 2.2, hall_depth * 0.48)))
    front_edge_y = front_wall_y - hall_depth + spec.wall_thickness / 2 + 0.06
    back_wall_y = front_wall_y + recess_depth
    entry_front_y = back_wall_y - spec.wall_thickness / 2
    floor_back_y = entry_front_y + 0.04
    floor_depth = floor_back_y - front_edge_y
    floor_t = max(0.1, spec.slab_thickness * 0.62)
    floor_center_y = front_edge_y + floor_depth / 2
    roof_plate_height = max(0.18, min(0.28, spec.slab_thickness * 1.18))
    roof_back_y = entry_front_y + max(0.08, spec.wall_thickness * 0.32)
    roof_plate_depth = roof_back_y - front_edge_y
    roof_plate_center_y = front_edge_y + roof_plate_depth / 2
    roof_plate_z = base_z + spec.floor_height - roof_plate_height / 2 - 0.02
    beam_height = max(0.26, min(0.38, spec.floor_height * 0.11))
    beam_depth = max(0.18, spec.wall_thickness * 0.95)
    beam_center_z = roof_plate_z - roof_plate_height / 2 - beam_height / 2
    front_beam_y = front_edge_y + beam_depth / 2
    back_beam_y = roof_back_y - beam_depth / 2
    return {
        "base_z": base_z,
        "front_wall_y": front_wall_y,
        "hall_width": hall_width,
        "hall_half_width": hall_half_width,
        "hall_depth": hall_depth,
        "recess_depth": recess_depth,
        "front_edge_y": front_edge_y,
        "back_wall_y": back_wall_y,
        "entry_front_y": entry_front_y,
        "floor_back_y": floor_back_y,
        "floor_depth": floor_depth,
        "floor_t": floor_t,
        "floor_center_y": floor_center_y,
        "roof_plate_height": roof_plate_height,
        "roof_plate_depth": roof_plate_depth,
        "roof_plate_center_y": roof_plate_center_y,
        "roof_plate_z": roof_plate_z,
        "roof_back_y": roof_back_y,
        "beam_height": beam_height,
        "beam_depth": beam_depth,
        "beam_center_z": beam_center_z,
        "front_beam_y": front_beam_y,
        "back_beam_y": back_beam_y,
    }

def _build_market_hall_front_ground(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    envelope = _front_entry_envelope(spec)
    package_center_x, _package_span_width = _front_entry_package_center_span(spec, envelope=envelope)
    wall_material = _wall_material_for_floor(materials_map, spec, 0)
    structure_material = _facade_trim_material(materials_map, spec)
    frame_material = materials_map["frame"]
    roof_material = materials_map["roof"]
    geometry = _market_hall_frontage_geometry(spec, envelope)
    base_z = geometry["base_z"]
    hall_width = geometry["hall_width"]
    hall_half_width = geometry["hall_half_width"]
    front_edge_y = geometry["front_edge_y"]
    back_wall_y = geometry["back_wall_y"]
    floor_depth = geometry["floor_depth"]
    floor_t = geometry["floor_t"]
    floor_center_y = geometry["floor_center_y"]
    roof_plate_height = geometry["roof_plate_height"]
    roof_plate_depth = geometry["roof_plate_depth"]
    roof_plate_center_y = geometry["roof_plate_center_y"]
    roof_plate_z = geometry["roof_plate_z"]
    roof_plate = _create_opening_box(
        _name(prefix, "MarketHall_RoofPlate"),
        "X",
        hall_width,
        roof_plate_depth,
        roof_plate_height,
        0.0,
        roof_plate_center_y,
        roof_plate_z,
        collection,
        parent,
        roof_material,
    )
    _mark_section(_mark_generated(roof_plate, tbg_market_hall_structure=True), "Section_Walls_Roof")

    beam_height = geometry["beam_height"]
    beam_depth = geometry["beam_depth"]
    beam_center_z = geometry["beam_center_z"]
    front_beam_y = geometry["front_beam_y"]
    back_beam_y = geometry["back_beam_y"]
    lintel = _create_opening_box(
        _name(prefix, "MarketHall_Lintel"),
        "X",
        hall_width - 0.12,
        beam_depth,
        beam_height,
        0.0,
        front_beam_y,
        beam_center_z,
        collection,
        parent,
        structure_material,
    )
    _mark_section(_mark_generated(lintel, tbg_market_hall_structure=True), "Section_Walls_Trim")

    column_width = max(0.4, min(0.54, spec.wall_thickness * 2.05))
    column_depth = max(0.28, min(0.4, spec.wall_thickness * 1.55))
    column_height = max(2.18, beam_center_z - beam_height / 2 - base_z)
    column_center_y = front_edge_y + column_depth / 2
    outer_column_center = hall_half_width - max(0.56, column_width / 2 + 0.2)
    inner_column_gap = max(0.48, column_width / 2 + 0.18)
    door_half = envelope.door_width / 2
    inner_left_center = package_center_x - door_half - inner_column_gap - column_width / 2
    inner_right_center = package_center_x + door_half + inner_column_gap + column_width / 2
    column_centers = [
        -outer_column_center,
        inner_left_center,
        inner_right_center,
        outer_column_center,
    ]
    side_beam_depth = max(0.16, beam_depth * 0.9)
    side_beam_length = max(0.24, back_beam_y - front_beam_y)
    for side_label, center_x in (("L", -outer_column_center), ("R", outer_column_center)):
        side_beam = _create_opening_box(
            _name(prefix, f"MarketHall_SideBeam_{side_label}"),
            "Y",
            side_beam_length,
            side_beam_depth,
            beam_height,
            center_x,
            front_beam_y + side_beam_length / 2,
            beam_center_z,
            collection,
            parent,
            structure_material,
        )
        _mark_section(_mark_generated(side_beam, tbg_market_hall_structure=True), "Section_Walls_Trim")

    back_beam = _create_opening_box(
        _name(prefix, "MarketHall_BackBeam"),
        "X",
        hall_width - 0.16,
        beam_depth,
        beam_height,
        0.0,
        back_beam_y,
        beam_center_z,
        collection,
        parent,
        structure_material,
    )
    _mark_section(_mark_generated(back_beam, tbg_market_hall_structure=True), "Section_Walls_Trim")

    for column_index, center in enumerate(column_centers):
        column = _create_opening_box(
            _name(prefix, f"MarketHall_Colonnade_{column_index:02d}"),
            "X",
            column_width,
            column_depth,
            column_height,
            center,
            column_center_y,
            base_z + column_height / 2,
            collection,
            parent,
            structure_material,
        )
        _mark_wall_section(
            _mark_generated(
                column,
                tbg_market_hall_structure=True,
                tbg_facade_side="front",
                tbg_facade_floor=0,
            ),
            "Section_Walls_Trim",
        )

    porch_drop = min(0.06, floor_t * 0.45)
    hall_floor = _create_opening_box(
        _name(prefix, "MarketHall_FrontFloor"),
        "X",
        hall_width,
        floor_depth,
        floor_t,
        0.0,
        floor_center_y,
        base_z - floor_t / 2 - porch_drop,
        collection,
        parent,
        materials_map["floor"],
    )
    _mark_section(
        _mark_generated(
            hall_floor,
            tbg_market_hall_structure=True,
            tbg_entry_front_limit=float(envelope.front_footprint_extent),
            tbg_entry_left_limit=float(envelope.footprint_left_extent),
            tbg_entry_right_limit=float(envelope.footprint_right_extent),
        ),
        "Section_Floors",
    )

    wall_open_margin = 0.18
    for label, start, end in (("Left", -hall_half_width, envelope.door_left - wall_open_margin), ("Right", envelope.door_right + wall_open_margin, hall_half_width)):
        width = end - start
        if width <= 0.12:
            continue
        _emit_frontage_shell_piece(
            prefix,
            f"MarketHall_BackWall_{label}",
            spec,
            collection,
            parent,
            wall_material,
            orientation="X",
            width=width,
            depth=spec.wall_thickness,
            height=spec.floor_height,
            along_coord=(start + end) / 2,
            normal_coord=back_wall_y,
            center_z=base_z + spec.floor_height / 2,
            generated_metadata={
                "tbg_market_hall_structure": True,
                "tbg_facade_side": "front",
                "tbg_facade_floor": 0,
            },
            runtime_emitter=runtime_emitter,
            occupancy_author=occupancy_author,
        )
    lintel_h = max(0.2, spec.floor_height - spec.door.height)
    _emit_frontage_shell_piece(
        prefix,
        "MarketHall_BackWall_Lintel",
        spec,
        collection,
        parent,
        wall_material,
        orientation="X",
        width=envelope.door_width,
        depth=spec.wall_thickness,
        height=lintel_h,
        along_coord=package_center_x,
        normal_coord=back_wall_y,
        center_z=base_z + spec.door.height + lintel_h / 2,
        generated_metadata={
            "tbg_market_hall_structure": True,
            "tbg_preserved_exterior_shell": True,
            "tbg_facade_side": "front",
            "tbg_facade_floor": 0,
        },
        runtime_emitter=runtime_emitter,
        occupancy_author=occupancy_author,
    )

    _build_front_entry_frame(
        prefix,
        "Door_Main",
        spec,
        collection,
        parent,
        frame_material,
        wall_pos=back_wall_y,
        door_center_x=package_center_x,
        door_width=envelope.door_width,
        base_z=base_z,
        door_height=spec.door.height,
    )

def _resolve_frontage_entry_pose(spec) -> tuple[float, float]:
    envelope = _front_entry_envelope(spec)
    front_wall_y = -spec.depth / 2 + spec.wall_thickness / 2
    door_center_x, _package_span_width = _front_entry_package_center_span(spec, envelope=envelope)
    if _is_market_hall_frontage(spec):
        return door_center_x, _market_hall_frontage_geometry(spec, envelope)["back_wall_y"]
    if _is_industrial_frontage(spec):
        if envelope.frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE:
            door_center_x = _warehouse_door_center_x(spec, envelope)
            return door_center_x, front_wall_y
        return door_center_x, front_wall_y + envelope.recess_depth
    if _is_storefront_frontage(spec):
        return door_center_x, front_wall_y
    if _is_stage1_identity_reset_family(spec):
        return door_center_x, front_wall_y
    return door_center_x, -spec.depth / 2

def _build_hangar_front_ground(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    wall_material = _wall_material_for_floor(materials_map, spec, 0)
    frame_material = materials_map["roof"]
    base_z = _base_elevation(spec)
    portal_width = min(spec.width - 3.6, max(spec.width * 0.28, 5.4))
    portal_left = -portal_width / 2
    portal_right = portal_width / 2
    frame_width = max(0.34, min(0.48, spec.wall_thickness * 1.75))
    frame_depth = max(0.18, min(0.28, spec.wall_thickness * 1.15))
    header_height = max(0.22, min(0.28, spec.floor_height * 0.06))
    portal_clear_height = spec.floor_height - header_height
    apron_depth = max(1.0, min(1.45, spec.depth * 0.09))
    apron_width = min(spec.width - 0.36, portal_width + frame_width * 2 + 0.18)
    apron_height = max(0.08, min(0.12, spec.slab_thickness * 0.62))

    def emit_portal_face(side_key: str):
        normal_coord = (
            -spec.depth / 2 + spec.wall_thickness / 2
            if side_key == "front"
            else spec.depth / 2 - spec.wall_thickness / 2
        )
        side_shell_clearance = float(spec.wall_thickness)
        for side_suffix, start, end in (
            ("Left", -spec.width / 2 + side_shell_clearance, portal_left),
            ("Right", portal_right, spec.width / 2 - side_shell_clearance),
        ):
            wing_width = end - start
            if wing_width <= max(1e-4, float(spec.wall_thickness) / 2):
                continue
            _emit_frontage_shell_piece(
                prefix,
                f"{side_key.title()}_HangarWing_{side_suffix}",
                spec,
                collection,
                parent,
                wall_material,
                orientation="X",
                width=wing_width,
                depth=spec.wall_thickness,
                height=spec.floor_height,
                along_coord=(start + end) / 2,
                normal_coord=normal_coord,
                center_z=base_z + spec.floor_height / 2,
                generated_metadata={"tbg_facade_side": side_key},
                runtime_emitter=runtime_emitter,
                runtime_side=side_key,
                occupancy_author=occupancy_author,
            )
        frame_y = _surface_coord(side_key, normal_coord, spec.wall_thickness, frame_depth, exterior=True, offset=0.01)
        for side_suffix, center_x in (("Left", portal_left - frame_width / 2), ("Right", portal_right + frame_width / 2)):
            jamb = _create_opening_box(
                _name(prefix, f"HangarPortal_Jamb_{side_key.title()}_{side_suffix}"),
                "X",
                frame_width,
                frame_depth,
                portal_clear_height,
                center_x,
                frame_y,
                base_z + portal_clear_height / 2,
                collection,
                parent,
                frame_material,
            )
            _mark_section(
                _mark_generated(jamb, tbg_hangar_portal=True, tbg_facade_side=side_key),
                "Section_Doors_Prop",
            )
        header = _create_opening_box(
            _name(prefix, f"HangarPortal_Header_{side_key.title()}"),
            "X",
            portal_width + frame_width * 2 + 0.06,
            frame_depth,
            header_height,
            0.0,
            frame_y,
            base_z + portal_clear_height + header_height / 2,
            collection,
            parent,
            frame_material,
        )
        _mark_section(
            _mark_generated(header, tbg_hangar_portal=True, tbg_facade_side=side_key),
            "Section_Doors_Prop",
        )
        apron = _create_opening_box(
            _name(prefix, f"HangarPortal_Apron_{side_key.title()}"),
            "X",
            apron_width,
            apron_depth,
            apron_height,
            0.0,
            _surface_coord(side_key, normal_coord, spec.wall_thickness, apron_depth, exterior=True, offset=0.0),
            base_z + apron_height / 2,
            collection,
            parent,
            materials_map["floor"],
        )
        _mark_section(
            _mark_generated(apron, tbg_hangar_portal=True, tbg_facade_side=side_key),
            "Section_Floors",
        )

    emit_portal_face("front")
    emit_portal_face("back")

# generic_timber

def _build_entry_cluster_detail(prefix, spec, collection, parent, materials_map):
    envelope = _front_entry_envelope(spec)
    side_sign = 1.0 if envelope.door_offset_x <= 0.0 else -1.0
    detail_x = envelope.door_offset_x + side_sign * (envelope.door_width / 2 + 0.32)
    detail_z = max(1.55, envelope.threshold_z + 1.46)
    parts = [
        ((0.18, 0.03, 0.26), (0.0, 0.0, 0.0)),
        ((0.1, 0.05, 0.08), (0.0, -0.035, 0.04)),
        ((0.08, 0.02, 0.08), (0.0, -0.025, -0.13)),
    ]
    detail_near_face = max(center[1] + size[1] / 2 for size, center in parts)
    front_y = -spec.depth / 2 + spec.wall_thickness / 2
    detail_y = _surface_coord(
        "front",
        front_y,
        spec.wall_thickness,
        detail_near_face * 2,
        exterior=True,
        offset=ENTRY_DETAIL_PROUD_OFFSET,
    )
    accent = _create_composite_box_object(
        _name(prefix, "Entry_Accent"),
        parts,
        (detail_x, detail_y, detail_z),
        collection,
        parent,
        materials_map["prop"],
    )
    _mark_section(
        _mark_generated(
            accent,
            tbg_entry_detail=True,
            tbg_facade_side="front",
            tbg_facade_plane="outer",
        ),
        "Section_Doors_Prop",
    )

def _has_authored_entry_canopy_contract(spec, envelope, *, package_width: float) -> bool:
    if not bool(getattr(getattr(spec, "door", None), "enabled", True)):
        return False
    if float(package_width) <= 1e-4:
        return False
    if float(getattr(envelope, "canopy_width", 0.0)) <= 1e-4:
        return False
    return True

def _build_ground_tactical_profile(prefix, spec, collection, parent, materials_map, runtime_emitter: RuntimeMarkerEmitter | None = None):
    if (
        not _is_timber_frontage(spec)
        and spec.massing_profile != MASSING_PROFILE_BASE_HEAVY
        and spec.ground_floor_tactical_profile == GROUND_FLOOR_MIXED_WINDOWS
    ):
        return

    envelope = _front_entry_envelope(spec)
    package_ledger = _entry_stoop_package_ledger(
        spec,
        envelope=envelope,
        facade_side="front",
    )
    package_center_x = float(package_ledger["center_x"])
    package_left_x = float(package_ledger["package_left_x"])
    package_right_x = float(package_ledger["package_right_x"])
    package_width = float(package_ledger["package_width"])
    trim_material = _facade_trim_material(materials_map, spec)

    if spec.ground_floor_tactical_profile == GROUND_FLOOR_DEFENSIVE_BASE:
        return

    if (
        _is_hangar_frontage(spec)
        or _is_storefront_frontage(spec)
        or _is_industrial_frontage(spec)
        or _is_market_hall_frontage(spec)
    ):
        return
    if _is_stage1_identity_reset_family(spec):
        return
    if not _has_authored_entry_canopy_contract(spec, envelope, package_width=package_width):
        return

    if _is_timber_frontage(spec):
        rowhouse_frontage = envelope.frontage_variant == FRONTAGE_TYPE_TIMBER_ROWHOUSE
        post_count = 4 if envelope.frontage_variant == FRONTAGE_TYPE_TIMBER_ROWHOUSE else 2
        post_width = 0.14 if envelope.frontage_variant == FRONTAGE_TYPE_TIMBER_ROWHOUSE else 0.12
        cover_depth = max(1.46, envelope.cover_depth)
        porch_center_x = package_center_x
        support_left_x = float(package_ledger["support_left_x"])
        support_right_x = float(package_ledger["support_right_x"])
        package_visible_width = max(0.0, support_right_x - support_left_x)
        cover_width = min(
            envelope.canopy_width,
            package_width,
        )
        support_span_width = min(package_visible_width, cover_width)
        roof_center_y = -spec.depth / 2 - cover_depth / 2 + 0.08
        roof_z = max(ENTRY_CANOPY_HEIGHT + 0.08, envelope.threshold_z + spec.door.height + 0.34)
        roof = _create_box(
            _name(prefix, "Porch_Cover"),
            (cover_width, cover_depth, ENTRY_CANOPY_THICKNESS),
            (porch_center_x, roof_center_y, roof_z),
            collection,
            parent,
            trim_material,
        )
        roof = _mark_section(
            _mark_generated(roof, tbg_entry_canopy=True),
            "Section_Walls_Canopy",
            hide_with_walls=True,
        )
        _emit_object_proxy_box(
            runtime_emitter,
            roof,
            metadata_values={"tbg_runtime_side": "front", "tbg_runtime_floor": 0, "tbg_runtime_feature": "entry_canopy"},
        )
        beam = _create_box(
            _name(prefix, "Porch_Beam"),
            (cover_width, 0.08, 0.18),
            (porch_center_x, -spec.depth / 2 - cover_depth + 0.08, roof_z - 0.03),
            collection,
            parent,
            materials_map["frame"],
        )
        _mark_section(_mark_generated(beam, tbg_entry_canopy=True), "Section_Doors_Prop")
        post_span_width = max(0.0, support_span_width - post_width * 1.6)
        if post_count == 2:
            post_offsets = (
                -post_span_width / 2 + post_width * 0.8,
                post_span_width / 2 - post_width * 0.8,
            )
        else:
            post_offsets = (
                -post_span_width / 2 + post_width * 0.82,
                -post_span_width * 0.18,
                post_span_width * 0.18,
                post_span_width / 2 - post_width * 0.82,
            )
        post_base_z = max(0.0, float(package_ledger["support_base_z"]))
        post_height = max(1.72 if rowhouse_frontage else 1.94, roof_z - ENTRY_CANOPY_THICKNESS / 2 - post_base_z)
        post_center_y = float(package_ledger["support_front_y"])
        for index, offset_x in enumerate(post_offsets):
            post_x = min(package_right_x - post_width / 2, max(package_left_x + post_width / 2, porch_center_x + offset_x))
            post = _create_box(
                _name(prefix, f"Porch_Post_{index:02d}"),
                (post_width, post_width, post_height),
                (
                    post_x,
                    post_center_y,
                    post_base_z + post_height / 2,
                ),
                collection,
                parent,
                materials_map["frame"],
            )
            _mark_section(_mark_generated(post, tbg_entry_canopy=True), "Section_Doors_Prop")
        _build_entry_cluster_detail(prefix, spec, collection, parent, materials_map)
        return

    canopy_depth = 1.08 if spec.ground_floor_tactical_profile == GROUND_FLOOR_OPEN_ENTRY else 0.72
    canopy_width = min(envelope.canopy_width, package_width)
    canopy_z = envelope.threshold_z + spec.door.height + 0.42 + ENTRY_CANOPY_THICKNESS / 2
    canopy = _create_box(
        _name(prefix, "Entry_Canopy"),
        (canopy_width, canopy_depth, ENTRY_CANOPY_THICKNESS),
        (
            package_center_x,
            -spec.depth / 2 - canopy_depth / 2 + 0.06,
            max(ENTRY_CANOPY_HEIGHT + 0.12, canopy_z),
        ),
        collection,
        parent,
        trim_material,
    )
    canopy = _mark_section(
        _mark_generated(canopy, tbg_entry_canopy=True),
        "Section_Walls_Canopy",
        hide_with_walls=True,
    )
    _emit_object_proxy_box(
        runtime_emitter,
        canopy,
        metadata_values={"tbg_runtime_side": "front", "tbg_runtime_floor": 0, "tbg_runtime_feature": "entry_canopy"},
    )
    canopy_underside_z = canopy.location.z - ENTRY_CANOPY_THICKNESS / 2
    canopy_front_y = canopy.location.y + canopy.dimensions.y / 2 - 0.08
    brace_half_span = min(envelope.canopy_brace_half_span, max(0.0, canopy_width / 2 - 0.04))
    for side_label, offset_sign in (("L", -1.0), ("R", 1.0)):
        brace_height = max(0.98, canopy_underside_z - (envelope.threshold_z + 1.02))
        brace_y = canopy_front_y if envelope.landing_depth <= 0.0 else max(envelope.landing_front_y + 0.1, canopy_front_y)
        brace_x = package_center_x + offset_sign * brace_half_span
        brace_x = min(package_right_x - 0.04, max(package_left_x + 0.04, brace_x))
        brace = _create_box(
            _name(prefix, f"Entry_CanopyBrace_{side_label}"),
            (0.08, 0.08, brace_height),
            (
                brace_x,
                brace_y,
                canopy_underside_z - brace_height / 2,
            ),
            collection,
            parent,
            materials_map["frame"],
        )
        brace = _mark_section(_mark_generated(brace, tbg_entry_canopy=True), "Section_Doors_Prop")
        _emit_object_proxy_box(
            runtime_emitter,
            brace,
            metadata_values={"tbg_runtime_side": "front", "tbg_runtime_floor": 0, "tbg_runtime_feature": "entry_canopy_brace"},
        )
    _build_entry_cluster_detail(prefix, spec, collection, parent, materials_map)

build_front_entry_frame = _build_front_entry_frame
build_entry_stoop_package = _build_entry_stoop_package
emit_front_wall_piece = _emit_front_wall_piece
emit_frontage_shell_piece = _emit_frontage_shell_piece
frontage_trim_material = _facade_trim_material
resolve_frontage_entry_pose = _resolve_frontage_entry_pose
build_market_hall_front_ground = _build_market_hall_front_ground
build_ground_tactical_profile = _build_ground_tactical_profile
build_hangar_front_ground = _build_hangar_front_ground
