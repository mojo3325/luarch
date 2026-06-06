from __future__ import annotations

import math

from ..export_contract import ROLE_ROOF_EXIT_SHELL
from .building_layout import (
    TERMINAL_PROFILE_ATTIC_OPEN,
    TERMINAL_PROFILE_FULL_ROOM,
    TERMINAL_PROFILE_STAIR_HEAD,
    _centered_opening_shell_parts,
)
from .layout_facade_planning import (
    _is_hangar_frontage,
    _is_industrial_frontage,
    _wall_material_for_floor,
)
from .building_support import (
    _create_box,
    _mark_door_leaf,
    _mark_generated,
    _mark_section,
    _mark_wall_section,
    _name,
    resolve_authored_voxel_wall_material_metadata,
)
from .building_occupancy import (
    MIN_NON_THICKNESS_CELL_SPAN_STUDS,
    OPENING_VISUAL_CLEARANCE_STUDS,
    OccupancyAuthoringSession,
)
from .building_facade_opening_slots import (
    OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS,
    _wall_opening_cut_metadata,
    create_opening_frame as _create_opening_frame,
    opening_cut_frame_envelope as _opening_cut_frame_envelope,
)
from .runtime_markers import RuntimeMarkerEmitter


def _display_color_tuple(display_color_rgb: dict[str, int] | None) -> tuple[int, int, int] | None:
    if not isinstance(display_color_rgb, dict):
        return None
    try:
        return (
            int(display_color_rgb["r"]),
            int(display_color_rgb["g"]),
            int(display_color_rgb["b"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _resolved_structural_material_metadata(material) -> tuple[str, str | None, tuple[int, int, int] | None]:
    material_name = str(getattr(material, "name", "") or "").strip()
    resolved = resolve_authored_voxel_wall_material_metadata(material_name)
    if resolved is None:
        return ("PLASTER", None, None)
    return (
        str(resolved.material_family),
        str(resolved.visual_style) if resolved.visual_style else None,
        _display_color_tuple(resolved.display_color_rgb),
    )


def _register_shell_fragment(
    occupancy_author: OccupancyAuthoringSession | None,
    *,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    normal_axis: str,
    material,
    source_bucket: str,
    source_name: str,
    rect_cuts: tuple[tuple[str, float, float, float, float], ...] = (),
) -> None:
    if occupancy_author is None:
        return
    material_family, visual_style, display_color_rgb = _resolved_structural_material_metadata(material)
    sx, sy, sz = (float(value) for value in size)
    cx, cy, cz = (float(value) for value in location)
    if normal_axis == "x":
        thickness_min = cx - sx / 2
        thickness_max = cx + sx / 2
        run_min = cy - sy / 2
        run_max = cy + sy / 2
    elif normal_axis == "y":
        thickness_min = cy - sy / 2
        thickness_max = cy + sy / 2
        run_min = cx - sx / 2
        run_max = cx + sx / 2
    else:
        raise ValueError("Roof-exit shell wall-plane normal_axis must be 'x' or 'y'.")
    plane = occupancy_author.register_wall_plane(
        plane_id=source_name,
        normal_axis=normal_axis,
        thickness_min=thickness_min,
        thickness_max=thickness_max,
        run_min=run_min,
        run_max=run_max,
        z_min=cz - sz / 2,
        z_max=cz + sz / 2,
        source_bucket=source_bucket,
        material_family=material_family,
        visual_style=visual_style,
        display_color_rgb=display_color_rgb,
        source_name=source_name,
        staged_object_names=(source_name,),
    )
    for kind, run_min, run_max, z_min, z_max in rect_cuts:
        plane.add_rect_cut(kind, run_min=run_min, run_max=run_max, z_min=z_min, z_max=z_max)


def _trim_y_normal_shell_occupancy_to_side_walls(
    *,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    shell_x0: float,
    shell_x1: float,
    wall_thickness: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    width, depth, height = (float(value) for value in size)
    x, y, z = (float(value) for value in location)
    x0 = x - width / 2
    x1 = x + width / 2
    trim_x0 = max(x0, float(shell_x0) + float(wall_thickness))
    trim_x1 = min(x1, float(shell_x1) - float(wall_thickness))
    if trim_x1 - trim_x0 <= 1e-4:
        return None
    return (
        (trim_x1 - trim_x0, depth, height),
        ((trim_x0 + trim_x1) / 2, y, z),
    )


def _build_roof_exit(
    prefix,
    spec,
    spatial_plan,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    if (
        _is_hangar_frontage(spec)
        or str(getattr(spec, "preset_id", "")).lower() == "under_construction"
        or not spec.stair_core.enabled
        or not spatial_plan.roof_access_enabled
        or spatial_plan.roof_room is None
    ):
        return

    roof_room = spatial_plan.roof_room
    terminal_profile = str(getattr(roof_room, "terminal_profile", TERMINAL_PROFILE_FULL_ROOM)).upper()
    door_w = float(roof_room.door_width)
    door_h = float(roof_room.door_height)
    roof_cap_thickness = float(spec.slab_thickness)
    minimum_packable_door_lintel_height = (
        float(door_h)
        + float(OPENING_VISUAL_CLEARANCE_STUDS)
        + float(MIN_NON_THICKNESS_CELL_SPAN_STUDS)
        + 0.01
    )
    shell_wall_height = min(
        float(roof_room.height),
        max(
            minimum_packable_door_lintel_height,
            float(door_h + 0.18),
            float(roof_room.height - roof_cap_thickness),
        ),
    )
    wall_z = float(roof_room.base_z + shell_wall_height / 2)
    roof_z = float(roof_room.base_z + shell_wall_height + roof_cap_thickness / 2)
    wall_material = (
        _wall_material_for_floor(materials_map, spec, max(0, spec.floor_count - 1))
        if roof_room.shell_bucket == "Section_Walls_Exterior"
        else materials_map["interior_wall"]
    )
    shell_bucket = roof_room.shell_bucket
    shell_x0, shell_x1, shell_y0, shell_y1 = (float(v) for v in roof_room.footprint)
    shell_width = shell_x1 - shell_x0
    shell_depth = shell_y1 - shell_y0
    shell_cx = (shell_x0 + shell_x1) / 2
    shell_cy = (shell_y0 + shell_y1) / 2
    opening_rect = roof_room.opening_rect if roof_room.opening_rect is not None else roof_room.footprint
    opening_x0, opening_x1, opening_y0, opening_y1 = (float(v) for v in opening_rect)
    opening_width = max(0.0, opening_x1 - opening_x0)
    opening_depth = max(0.0, opening_y1 - opening_y0)
    opening_cx = (opening_x0 + opening_x1) / 2
    wall_side = str(roof_room.door_wall).lower()
    door_on_back = wall_side == "back"

    if opening_width <= 1e-4 or opening_depth <= 1e-4:
        return

    roof_cap_inset = max(0.02, min(0.04, spec.wall_thickness * 0.25))
    roof_cap_width = max(0.24, shell_width - roof_cap_inset * 2)
    roof_cap_depth = max(0.24, shell_depth - roof_cap_inset * 2)
    industrial_frontage = _is_industrial_frontage(spec)

    def _emit_shell_box(
        name: str,
        size: tuple[float, float, float],
        location: tuple[float, float, float],
        *,
        normal_axis: str,
        register_occupancy: bool = True,
        rect_cuts: tuple[tuple[str, float, float, float, float], ...] = (),
        extra_metadata: dict[str, object] | None = None,
        section_bucket: str | None = None,
        merge_allowed: bool = True,
    ):
        occupancy_size = size
        occupancy_location = location
        if normal_axis == "y":
            trimmed = _trim_y_normal_shell_occupancy_to_side_walls(
                size=size,
                location=location,
                shell_x0=shell_x0,
                shell_x1=shell_x1,
                wall_thickness=float(spec.wall_thickness),
            )
            if trimmed is None:
                occupancy_size = None
                occupancy_location = None
            else:
                occupancy_size, occupancy_location = trimmed
        if register_occupancy and occupancy_size is not None and occupancy_location is not None:
            _register_shell_fragment(
                occupancy_author,
                size=occupancy_size,
                location=occupancy_location,
                normal_axis=normal_axis,
                material=wall_material,
                source_bucket=shell_bucket,
                source_name=name,
                rect_cuts=rect_cuts,
            )
        shell_obj = _create_box(name, size, location, collection, parent, wall_material)
        metadata_values = {"tbg_roof_exit_shell": True}
        if extra_metadata:
            metadata_values.update(extra_metadata)
        target_bucket = str(section_bucket or shell_bucket)
        shell_obj = _mark_section(
            _mark_generated(shell_obj, **metadata_values),
            target_bucket,
            merge_allowed=merge_allowed,
            hide_with_walls=True,
        )
        if runtime_emitter is not None and shell_obj is not None:
            runtime_emitter.emit_box(
                role=ROLE_ROOF_EXIT_SHELL,
                size=tuple(float(value) for value in shell_obj.dimensions),
                location=tuple(float(value) for value in shell_obj.location),
                source_name=shell_obj.name,
                metadata_values={"tbg_runtime_floor": int(spec.floor_count)},
            )
        return shell_obj

    def _emit_roof_cap_box(name: str, size: tuple[float, float, float], location: tuple[float, float, float]):
        roof_obj = _create_box(name, size, location, collection, parent, materials_map["roof"])
        roof_obj = _mark_wall_section(_mark_generated(roof_obj, tbg_roof_exit_shell=True), "Section_Walls_Roof")
        if runtime_emitter is not None and roof_obj is not None:
            runtime_emitter.emit_box(
                role=ROLE_ROOF_EXIT_SHELL,
                size=tuple(float(value) for value in roof_obj.dimensions),
                location=tuple(float(value) for value in roof_obj.location),
                source_name=roof_obj.name,
                metadata_values={"tbg_runtime_floor": int(spec.floor_count)},
            )
        return roof_obj

    def _emit_stair_head_shell():
        base_z = float(roof_room.base_z)
        shell_wall_t = max(0.12, min(0.24, float(spec.wall_thickness) * 1.02))
        shell_height = max(
            1.8,
            min(
                2.14,
                float(roof_room.height) - max(0.12, roof_cap_thickness * 0.3),
            ),
        )
        shell_center_z = base_z + shell_height / 2
        opaque_wall_y = shell_y0 + shell_wall_t / 2 if door_on_back else shell_y1 - shell_wall_t / 2
        portal_wall_y = shell_y1 - shell_wall_t / 2 if door_on_back else shell_y0 + shell_wall_t / 2

        if shell_depth > 1e-4:
            _emit_shell_box(
                _name(prefix, "RoofExit_StairHead_LeftWall"),
                (shell_wall_t, shell_depth, shell_height),
                (shell_x0 + shell_wall_t / 2, shell_cy, shell_center_z),
                normal_axis="x",
            )
            _emit_shell_box(
                _name(prefix, "RoofExit_StairHead_RightWall"),
                (shell_wall_t, shell_depth, shell_height),
                (shell_x1 - shell_wall_t / 2, shell_cy, shell_center_z),
                normal_axis="x",
            )

        _emit_shell_box(
            _name(prefix, "RoofExit_StairHead_BackWall"),
            (shell_width, shell_wall_t, shell_height),
            (shell_cx, opaque_wall_y, shell_center_z),
            normal_axis="y",
        )

        portal_clear_width = min(
            max(0.94, max(opening_width, door_w) + 0.22),
            max(0.42, shell_width - shell_wall_t * 2.2),
        )
        portal_margin = max(0.08, shell_wall_t * 0.7)
        portal_left = max(shell_x0 + portal_margin, opening_cx - portal_clear_width / 2)
        portal_right = min(shell_x1 - portal_margin, opening_cx + portal_clear_width / 2)
        if portal_right - portal_left <= 0.42:
            portal_left = shell_cx - portal_clear_width / 2
            portal_right = shell_cx + portal_clear_width / 2
            portal_left = max(shell_x0 + portal_margin, portal_left)
            portal_right = min(shell_x1 - portal_margin, portal_right)
        portal_clear_width = max(0.0, portal_right - portal_left)
        portal_cx = (portal_left + portal_right) / 2 if portal_clear_width > 1e-4 else shell_cx
        portal_lintel_h = max(
            0.16,
            min(0.24, max(roof_cap_thickness, shell_height * 0.12)),
        )
        portal_clear_height = max(
            door_h + 0.08,
            min(shell_height - portal_lintel_h, shell_height - 0.12),
        )
        occupancy_run_min = shell_x0 + shell_wall_t
        occupancy_run_max = shell_x1 - shell_wall_t
        if occupancy_run_max - occupancy_run_min > 1e-4:
            _register_shell_fragment(
                occupancy_author,
                size=(occupancy_run_max - occupancy_run_min, shell_wall_t, shell_height),
                location=((occupancy_run_min + occupancy_run_max) / 2, portal_wall_y, shell_center_z),
                normal_axis="y",
                material=wall_material,
                source_bucket=shell_bucket,
                source_name=_name(prefix, "RoofExit_StairHead_PortalWall:plane"),
                rect_cuts=(
                    (
                        "portal",
                        portal_left,
                        portal_right,
                        base_z,
                        base_z + portal_clear_height,
                    ),
                ),
            )
        if portal_left - shell_x0 > 1e-4:
            _emit_shell_box(
                _name(prefix, "RoofExit_StairHead_PortalLeft"),
                (portal_left - shell_x0, shell_wall_t, shell_height),
                ((shell_x0 + portal_left) / 2, portal_wall_y, shell_center_z),
                normal_axis="y",
                register_occupancy=False,
            )
        if shell_x1 - portal_right > 1e-4:
            _emit_shell_box(
                _name(prefix, "RoofExit_StairHead_PortalRight"),
                (shell_x1 - portal_right, shell_wall_t, shell_height),
                ((portal_right + shell_x1) / 2, portal_wall_y, shell_center_z),
                normal_axis="y",
                register_occupancy=False,
            )
        if portal_lintel_h > 1e-4 and portal_clear_width > 1e-4:
            _emit_shell_box(
                _name(prefix, "RoofExit_StairHead_PortalLintel"),
                (portal_clear_width, shell_wall_t, portal_lintel_h),
                (portal_cx, portal_wall_y, base_z + portal_clear_height + portal_lintel_h / 2),
                normal_axis="y",
                register_occupancy=False,
            )

        cap_inset = max(roof_cap_inset, shell_wall_t * 0.18)
        cap_width = max(0.24, shell_width - cap_inset * 2)
        cap_depth = max(0.24, shell_depth - cap_inset * 2)
        _emit_roof_cap_box(
            _name(prefix, "RoofExit_Roof"),
            (cap_width, cap_depth, roof_cap_thickness),
            (shell_cx, shell_cy, base_z + shell_height + roof_cap_thickness / 2),
        )

    def _emit_windowed_side_wall(side_label: str, wall_center_x: float):
        window_sill = max(0.88, min(1.12, shell_wall_height * 0.38))
        window_height = max(0.82, min(1.06, shell_wall_height - window_sill - 0.34))
        window_width = min(max(0.9, shell_depth * 0.44), shell_depth - 0.34)
        if window_width <= 0.4 or shell_wall_height - window_sill <= 0.24:
            _emit_shell_box(
                _name(prefix, f"RoofExit_{side_label}"),
                (spec.wall_thickness, shell_depth, shell_wall_height),
                (wall_center_x, shell_cy, wall_z),
                normal_axis="x",
            )
            return
        _register_shell_fragment(
            occupancy_author,
            size=(spec.wall_thickness, shell_depth, shell_wall_height),
            location=(wall_center_x, shell_cy, wall_z),
            normal_axis="x",
            material=wall_material,
            source_bucket=shell_bucket,
            source_name=_name(prefix, f"RoofExit_{side_label}:plane"),
            rect_cuts=(
                (
                    "window",
                    shell_cy - window_width / 2,
                    shell_cy + window_width / 2,
                    roof_room.base_z + window_sill,
                    roof_room.base_z + window_sill + window_height,
                ),
            ),
        )
        lower_height = max(0.0, min(window_sill, shell_wall_height - 0.2))
        if lower_height > 1e-4:
            _emit_shell_box(
                _name(prefix, f"RoofExit_{side_label}_Lower"),
                (spec.wall_thickness, shell_depth, lower_height),
                (wall_center_x, shell_cy, roof_room.base_z + lower_height / 2),
                normal_axis="x",
                register_occupancy=False,
            )
        upper_shell = _centered_opening_shell_parts(
            wall_width=shell_depth,
            wall_depth=spec.wall_thickness,
            wall_height=shell_wall_height - lower_height,
            opening_width=window_width,
            opening_height=window_height,
            wall_center_along=shell_cy,
            wall_center_normal=wall_center_x,
            base_z=roof_room.base_z + lower_height,
            orientation="Y",
        )
        if not upper_shell:
            _emit_shell_box(
                _name(prefix, f"RoofExit_{side_label}_UpperFallback"),
                (spec.wall_thickness, shell_depth, shell_wall_height - lower_height),
                (wall_center_x, shell_cy, roof_room.base_z + lower_height + (shell_wall_height - lower_height) / 2),
                normal_axis="x",
                register_occupancy=False,
            )
            return
        for part_label, (part_size, part_location) in upper_shell.items():
            _emit_shell_box(
                _name(prefix, f"RoofExit_{side_label}_{part_label.title()}"),
                tuple(float(value) for value in part_size),
                tuple(float(value) for value in part_location),
                normal_axis="x",
                register_occupancy=False,
            )

    if terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN:
        return

    if terminal_profile == TERMINAL_PROFILE_STAIR_HEAD:
        _emit_stair_head_shell()
        return

    # FULL_ROOM path: enclosed terminal room with roof cap + door.
    if industrial_frontage:
        _emit_windowed_side_wall("Left", shell_x0 + spec.wall_thickness / 2)
        _emit_windowed_side_wall("Right", shell_x1 - spec.wall_thickness / 2)
    else:
        _emit_shell_box(
            _name(prefix, "RoofExit_Left"),
            (spec.wall_thickness, shell_depth, shell_wall_height),
            (shell_x0 + spec.wall_thickness / 2, shell_cy, wall_z),
            normal_axis="x",
        )
        _emit_shell_box(
            _name(prefix, "RoofExit_Right"),
            (spec.wall_thickness, shell_depth, shell_wall_height),
            (shell_x1 - spec.wall_thickness / 2, shell_cy, wall_z),
            normal_axis="x",
        )

    if roof_room.door_wall == "back":
        solid_y = shell_y0 + spec.wall_thickness / 2
        door_y = shell_y1 - spec.wall_thickness / 2
        opening_label = "RoofExit_Back"
        solid_wall = _emit_shell_box(
            _name(prefix, "RoofExit_Front_Solid"),
            (shell_width, spec.wall_thickness, shell_wall_height),
            (shell_cx, solid_y, wall_z),
            normal_axis="y",
        )
    else:
        solid_y = shell_y1 - spec.wall_thickness / 2
        door_y = shell_y0 + spec.wall_thickness / 2
        opening_label = "RoofExit_Front"
        solid_wall = _emit_shell_box(
            _name(prefix, "RoofExit_Back_Solid"),
            (shell_width, spec.wall_thickness, shell_wall_height),
            (shell_cx, solid_y, wall_z),
            normal_axis="y",
        )

    cut_clearance = max(0.0, float(OPENING_VISUAL_CLEARANCE_STUDS))
    wall_top_z = float(roof_room.base_z + shell_wall_height)
    roof_exit_cut_top_z = float(roof_room.base_z + door_h)
    expanded_cut_top_residual = round(wall_top_z - (roof_exit_cut_top_z + cut_clearance), 6)
    if 0.0 < expanded_cut_top_residual < float(MIN_NON_THICKNESS_CELL_SPAN_STUDS):
        roof_exit_cut_top_z = wall_top_z - cut_clearance
    opening_shell_height = door_h

    opening_shell_width = door_w + cut_clearance * 2.0
    opening_shell = _centered_opening_shell_parts(
        wall_width=shell_width,
        wall_depth=spec.wall_thickness,
        wall_height=shell_wall_height,
        opening_width=opening_shell_width,
        opening_height=opening_shell_height,
        wall_center_along=shell_cx,
        wall_center_normal=door_y,
        base_z=float(roof_room.base_z),
        orientation="X",
    )
    roof_exit_cut_rect = (
        float(shell_cx - door_w / 2),
        float(shell_cx + door_w / 2),
        float(roof_room.base_z),
        roof_exit_cut_top_z,
    )
    roof_exit_cut_metadata = _wall_opening_cut_metadata(
        kind="door",
        orientation="X",
        side_key="roof_exit",
        floor_index=int(spec.floor_count),
        slot_index=-1,
        wall_pos=door_y,
        cut_rect=roof_exit_cut_rect,
    )
    door_frame_center_x, door_frame_width, _cut_frame_height, _cut_frame_center_z = _opening_cut_frame_envelope(
        roof_exit_cut_metadata
    )
    door_frame_center_x = float(door_frame_center_x if door_frame_center_x is not None else shell_cx)
    door_frame_width = float(door_frame_width if door_frame_width is not None else door_w)
    frame_ring_width = float(OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS)
    door_frame_inner_height = float(door_h)
    door_frame_height = float(door_h + frame_ring_width * 2.0)
    door_frame_center_z = float(roof_room.base_z + door_h / 2)
    roof_exit_frame = _create_opening_frame(
        _name(prefix, "Door_RoofExit_Frame"),
        "X",
        roof_room.door_wall == "back",
        door_frame_width,
        max(0.10, float(spec.wall_thickness) + 0.03),
        door_frame_height,
        max(0.18, door_frame_width - 0.12),
        max(0.18, door_frame_inner_height),
        door_frame_center_x,
        door_y,
        door_frame_center_z,
        collection,
        parent,
        materials_map["frame"],
        double_sided=True,
    )
    _mark_section(
        _mark_generated(
            roof_exit_frame,
            tbg_door_frame=True,
            tbg_roof_exit_frame=True,
            tbg_facade_side="roof_exit",
            tbg_facade_plane="both",
            tbg_facade_floor=int(spec.floor_count),
            tbg_roof_exit_frame_expected_inner_height=float(round(door_frame_inner_height, 4)),
            tbg_roof_exit_frame_expected_outer_height=float(round(door_frame_height, 4)),
            tbg_roof_exit_frame_authored_door_height=float(round(door_h, 4)),
            **roof_exit_cut_metadata,
        ),
        "Section_Doors_Trim",
        merge_allowed=False,
    )
    occupancy_run_min = shell_x0 + float(spec.wall_thickness)
    occupancy_run_max = shell_x1 - float(spec.wall_thickness)
    if occupancy_run_max - occupancy_run_min > 1e-4:
        _register_shell_fragment(
            occupancy_author,
            size=(occupancy_run_max - occupancy_run_min, spec.wall_thickness, shell_wall_height),
            location=((occupancy_run_min + occupancy_run_max) / 2, door_y, wall_z),
            normal_axis="y",
            material=wall_material,
            source_bucket=shell_bucket,
            source_name=_name(prefix, f"{opening_label}:plane"),
            rect_cuts=(
                (
                    "door",
                    *roof_exit_cut_rect,
                ),
            ),
        )
    left_opening = opening_shell.get("left")
    right_opening = opening_shell.get("right")
    lintel_opening = opening_shell.get("lintel")
    left_side = (
        _emit_shell_box(_name(prefix, f"{opening_label}_Left"), *left_opening, normal_axis="y", register_occupancy=False)
        if left_opening is not None
        else None
    )
    right_side = (
        _emit_shell_box(_name(prefix, f"{opening_label}_Right"), *right_opening, normal_axis="y", register_occupancy=False)
        if right_opening is not None
        else None
    )
    lintel = (
        _emit_shell_box(
            _name(prefix, f"{opening_label}_Lintel"),
            *lintel_opening,
            normal_axis="y",
            register_occupancy=False,
            extra_metadata={
                "tbg_roof_exit_lintel_closure": True,
                "tbg_roof_exit_lintel_closure_kind": "WALL_LINTEL",
                "tbg_facade_side": "roof_exit",
                "tbg_wall_opening_side": "roof_exit",
                **roof_exit_cut_metadata,
            },
            section_bucket="Section_Walls_Roof",
            merge_allowed=False,
        )
        if lintel_opening is not None
        else None
    )
    roof_cap = _create_box(
        _name(prefix, "RoofExit_Roof"),
        (roof_cap_width, roof_cap_depth, spec.slab_thickness),
        (shell_cx, shell_cy, roof_z),
        collection,
        parent,
        materials_map["roof"],
    )
    roof_cap = _mark_wall_section(_mark_generated(roof_cap, tbg_roof_exit_shell=True), "Section_Walls_Roof")
    if runtime_emitter is not None:
        for shell_obj in (left_side, right_side, lintel, roof_cap):
            if shell_obj is None:
                continue
            runtime_emitter.emit_box(
                role=ROLE_ROOF_EXIT_SHELL,
                size=tuple(float(value) for value in shell_obj.dimensions),
                location=tuple(float(value) for value in shell_obj.location),
                source_name=shell_obj.name,
                metadata_values={"tbg_runtime_floor": int(spec.floor_count)},
            )

    door = _create_box(
        _name(prefix, "Door_RoofExit"),
        (door_frame_width, spec.door.thickness, door_h),
        (door_frame_center_x - door_frame_width / 2, door_y, float(roof_room.base_z + door_h / 2)),
        collection,
        parent,
        materials_map["door"],
        origin_mode="HINGE_LEFT",
    )
    door = _mark_generated(
        door,
        tbg_door_panel=True,
        tbg_door_handle_plate=True,
        tbg_roof_exit_door=True,
        tbg_facade_side="roof_exit",
        tbg_facade_floor=int(spec.floor_count),
        **roof_exit_cut_metadata,
    )
    roof_exit_open_rotation = math.radians(-95.0 if roof_room.door_wall == "back" else 95.0)
    _mark_door_leaf(door, open_rotation_z=roof_exit_open_rotation)
