from __future__ import annotations

import math

import bpy
from mathutils import Euler, Vector

from ..export_contract import (
    ROLE_FLOOR_BLOCKER,
    ROLE_PARTITION,
    ROLE_ROOF_EXIT_PLATFORM,
    ROLE_SHELL,
    ROLE_STAIR_LANDING,
    ROLE_STAIR_RAMP,
    ROLE_STAIR_STEP,
)
from .building_layout import (
    RAIL_HEIGHT,
    RAIL_THICKNESS,
    STRINGER_THICKNESS,
    MASSING_PROFILE_PILOTIS,
    TERMINAL_PROFILE_ATTIC_OPEN,
    TERMINAL_PROFILE_FULL_ROOM,
    TERMINAL_PROFILE_STAIR_HEAD,
    WIDE_PARTITION_FRAME_DEPTH,
    WIDE_PARTITION_FRAME_PROUD,
    WIDE_PARTITION_FRAME_REVEAL,
    WIDE_PARTITION_OPENING_HEIGHT,
    WIDE_PARTITION_OPENING_WIDTH,
    WIDE_PARTITION_TOP_GAP,
    _adjacent_exterior_sides,
    _base_elevation,
    _completed_facade_floor_count,
    _core_bounds,
    _core_arrival_opening_center_x,
    _core_arrival_opening_width,
    _dogleg_metrics,
    _interior_bounds,
    _interior_bounds_for_rect,
    _level_base_z,
    _opening_location,
    _orientation_rotation,
    _rects_almost_equal,
    _slab_center_z,
    _spatial_plan,
    _wide_partition_positions,
    slab_planar_sections,
)
from .layout_facade_planning import _is_hangar_frontage, _is_market_hall_frontage
from .building_support import (
    _assign_material,
    _composite_box_mesh,
    _create_box,
    _create_composite_box_object,
    _frame_mesh,
    _mark_generated,
    _mark_section,
    _mark_wall_section,
    _name,
    _parent_to,
    resolve_authored_voxel_wall_material_metadata,
    _stepped_flight_mesh,
)
from .building_occupancy import MIN_NON_THICKNESS_CELL_SPAN_STUDS, OccupancyAuthoringSession
from .runtime_markers import RuntimeMarkerEmitter

SECTION_STAIRS_ROOM_SHELL = "Section_Stairs_RoomShell"


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


def _register_structural_box_plane(
    occupancy_author: OccupancyAuthoringSession | None,
    *,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    normal_axis: str,
    material,
    source_bucket: str,
    source_name: str,
) -> None:
    if occupancy_author is None:
        return
    material_family, visual_style, display_color_rgb = _resolved_structural_material_metadata(material)
    center_x, center_y, center_z = (float(value) for value in location)
    size_x, size_y, size_z = (float(value) for value in size)
    if normal_axis == "x":
        thickness_min = center_x - size_x / 2
        thickness_max = center_x + size_x / 2
        run_min = center_y - size_y / 2
        run_max = center_y + size_y / 2
    elif normal_axis == "y":
        thickness_min = center_y - size_y / 2
        thickness_max = center_y + size_y / 2
        run_min = center_x - size_x / 2
        run_max = center_x + size_x / 2
    else:
        raise ValueError("Structural occupancy wall box normal_axis must be 'x' or 'y'.")
    if run_max - run_min <= MIN_NON_THICKNESS_CELL_SPAN_STUDS + 1e-4:
        return
    if size_z <= MIN_NON_THICKNESS_CELL_SPAN_STUDS + 1e-4:
        return
    occupancy_author.register_wall_plane(
        plane_id=f"{source_name}:plane",
        normal_axis=normal_axis,
        thickness_min=thickness_min,
        thickness_max=thickness_max,
        run_min=run_min,
        run_max=run_max,
        z_min=center_z - size_z / 2,
        z_max=center_z + size_z / 2,
        source_bucket=source_bucket,
        material_family=material_family,
        visual_style=visual_style,
        display_color_rgb=display_color_rgb,
        source_name=source_name,
        staged_object_names=(source_name,),
    )


def _stair_core_variant(spec) -> str:
    return str(getattr(getattr(spec, "stair_core", None), "variant", "DEFAULT") or "DEFAULT").upper()


def _core_arrival_opening_bounds(spec, metrics) -> tuple[float, float, float]:
    opening_w = _core_arrival_opening_width(spec, metrics)
    opening_center_x = _core_arrival_opening_center_x(spec, metrics)
    opening_h = min(2.3, max(2.05, spec.floor_height - 0.55))
    opening_x0 = max(float(metrics.x0), float(opening_center_x - opening_w / 2))
    opening_x1 = min(float(metrics.x1), float(opening_center_x + opening_w / 2))
    return opening_x0, opening_x1, opening_h


def _build_floor_pieces(prefix, spec, collection, parent, material, runtime_emitter: RuntimeMarkerEmitter | None = None):
    def _floor_slab_mesh_from_sections(
        name: str,
        sections: list[tuple[str, tuple[float, float], tuple[float, float]]],
        thickness: float,
    ):
        rects: list[tuple[float, float, float, float]] = []
        min_axis = 1e-4
        for _suffix, (width, depth), (x, y) in sections:
            width = float(width)
            depth = float(depth)
            if width <= min_axis or depth <= min_axis:
                continue
            rects.append((float(x) - width / 2, float(x) + width / 2, float(y) - depth / 2, float(y) + depth / 2))
        if not rects or thickness <= min_axis:
            return None

        xs = sorted({coord for x0, x1, _y0, _y1 in rects for coord in (x0, x1)})
        ys = sorted({coord for _x0, _x1, y0, y1 in rects for coord in (y0, y1)})
        covered: set[tuple[int, int]] = set()
        for x_idx in range(len(xs) - 1):
            cell_x0, cell_x1 = xs[x_idx], xs[x_idx + 1]
            if cell_x1 - cell_x0 <= min_axis:
                continue
            cx = (cell_x0 + cell_x1) / 2
            for y_idx in range(len(ys) - 1):
                cell_y0, cell_y1 = ys[y_idx], ys[y_idx + 1]
                if cell_y1 - cell_y0 <= min_axis:
                    continue
                cy = (cell_y0 + cell_y1) / 2
                if any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, x1, y0, y1 in rects):
                    covered.add((x_idx, y_idx))

        parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
        for x_idx, y_idx in sorted(covered):
            x0, x1 = xs[x_idx], xs[x_idx + 1]
            y0, y1 = ys[y_idx], ys[y_idx + 1]
            parts.append(
                (
                    (x1 - x0, y1 - y0, float(thickness)),
                    ((x0 + x1) / 2, (y0 + y1) / 2, 0.0),
                )
            )

        return _composite_box_mesh(name, parts)

    def _emit_floor(
        name: str,
        sections: list[tuple[str, tuple[float, float], tuple[float, float]]],
        z: float,
        *,
        floor_index: int,
    ):
        mesh = _floor_slab_mesh_from_sections(name, sections, float(spec.slab_thickness))
        if mesh is None:
            return None
        floor_obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(floor_obj)
        _parent_to(floor_obj, parent)
        floor_obj.location = Vector((0.0, 0.0, z))
        _assign_material(floor_obj, material)
        if runtime_emitter is not None:
            for _suffix, (width, depth), (x, y) in sections:
                if min(float(width), float(depth), float(spec.slab_thickness)) <= 1e-4:
                    continue
                runtime_emitter.emit_box(
                    role=ROLE_FLOOR_BLOCKER,
                    size=(float(width), float(depth), float(spec.slab_thickness)),
                    location=(float(x), float(y), z),
                    source_name=floor_obj.name,
                    metadata_values={"tbg_runtime_floor": int(floor_index)},
                )
        return _mark_section(floor_obj, "Section_Floors")

    for floor in range(spec.floor_count):
        z = _slab_center_z(_level_base_z(spec, floor), spec.slab_thickness)
        split_for_core = bool(spec.stair_core.enabled and floor > 0)
        sections = slab_planar_sections(spec, split_for_core=split_for_core)
        name = _name(prefix, f"Floor_{floor:02d}")
        _emit_floor(
            name,
            sections,
            z,
            floor_index=floor,
        )

def _build_under_construction_frame(
    prefix,
    spec,
    collection,
    parent,
    material,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    if str(getattr(spec, "preset_id", "")).lower() != "under_construction" or int(spec.floor_count) < 2:
        return

    start_floor = max(1, _completed_facade_floor_count(spec))
    if start_floor >= int(spec.floor_count):
        return

    column_span = max(0.22, min(0.34, spec.wall_thickness * 1.3))
    beam_depth = max(0.3, min(0.4, max(spec.slab_thickness * 2.1, spec.wall_thickness * 0.9)))
    beam_gap = max(0.12, min(0.18, max(spec.slab_thickness * 1.05, beam_depth * 0.3)))
    beam_width_x = max(0.4, spec.width - column_span * 2)
    beam_width_y = max(0.4, spec.depth - column_span * 2)
    if beam_width_x <= 0.3 or beam_width_y <= 0.3:
        return

    column_x = spec.width / 2 - column_span / 2 - spec.wall_thickness
    column_y = spec.depth / 2 - column_span / 2 - spec.wall_thickness
    column_bottom_z = _level_base_z(spec, start_floor)
    column_top_z = _level_base_z(spec, int(spec.floor_count))
    column_height = max(spec.floor_height, column_top_z - column_bottom_z)
    column_center_z = column_bottom_z + column_height / 2

    def _emit_shell_box(name: str, size: tuple[float, float, float], location: tuple[float, float, float], *, part: str):
        obj = _create_box(name, size, location, collection, parent, material)
        obj = _mark_section(
            _mark_generated(
                obj,
                tbg_construction_frame=True,
                tbg_construction_frame_part=part,
            ),
            "Section_Walls_Trim",
            hide_with_walls=True,
        )
        if runtime_emitter is not None and obj is not None:
            runtime_emitter.emit_box(
                role=ROLE_SHELL,
                size=size,
                location=location,
                source_name=obj.name,
                metadata_values={
                    "tbg_runtime_feature": "construction_frame",
                    "tbg_construction_frame_part": part,
                },
            )
        return obj

    for x_sign in (-1.0, 1.0):
        for y_sign in (-1.0, 1.0):
            _emit_shell_box(
                _name(prefix, f"Construction_Frame_Column_{'R' if x_sign > 0 else 'L'}{'B' if y_sign > 0 else 'F'}"),
                (column_span, column_span, column_height),
                (x_sign * column_x, y_sign * column_y, column_center_z),
                part="corner_column",
            )

    for floor in range(start_floor, int(spec.floor_count)):
        beam_center_z = _level_base_z(spec, floor) - spec.slab_thickness - beam_gap - beam_depth / 2
        for side_label, center_y in (("Front", -column_y), ("Back", column_y)):
            _emit_shell_box(
                _name(prefix, f"Construction_Frame_{side_label}_F{floor:02d}"),
                (beam_width_x, column_span, beam_depth),
                (0.0, center_y, beam_center_z),
                part="ring_beam",
            )
        for side_label, center_x in (("Left", -column_x), ("Right", column_x)):
            _emit_shell_box(
                _name(prefix, f"Construction_Frame_{side_label}_F{floor:02d}"),
                (column_span, beam_width_y, beam_depth),
                (center_x, 0.0, beam_center_z),
                part="ring_beam",
            )


def _build_partition_wall_y_with_openings(
    prefix,
    side_label,
    spec,
    y,
    collection,
    parent,
    material,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    *,
    start_floor: int = 0,
    top_floor_shell_clearance: float = 0.0,
):
    metrics = _dogleg_metrics(spec)
    opening_x0, opening_x1, opening_h = _core_arrival_opening_bounds(spec, metrics)
    min_axis = max(1e-6, float(spec.wall_thickness) / 2)

    for floor in range(start_floor, spec.floor_count):
        z0 = _level_base_z(spec, floor)
        shell_clearance = float(top_floor_shell_clearance) if int(floor) == int(spec.floor_count) - 1 else 0.0
        shell_height = max(0.0, float(spec.floor_height) - shell_clearance)
        if shell_height <= min_axis:
            continue
        wall_center_z = z0 + shell_height / 2
        opening_top_z = z0 + opening_h
        emitted_parts = []
        part_specs: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = []
        side_shell_clearance = float(spec.wall_thickness)
        left_owner_x = float(metrics.x0) + side_shell_clearance
        right_owner_x = float(metrics.x1) - side_shell_clearance
        left_w = max(0.0, opening_x0 - left_owner_x)
        if left_w > min_axis:
            size = (left_w, float(spec.wall_thickness), shell_height)
            if min(size) > min_axis:
                part_specs.append(
                    (
                        "Left",
                        size,
                        (left_owner_x + left_w / 2, float(y), wall_center_z),
                    )
                )
        right_w = max(0.0, right_owner_x - opening_x1)
        if right_w > min_axis:
            size = (right_w, float(spec.wall_thickness), shell_height)
            if min(size) > min_axis:
                part_specs.append(
                    (
                        "Right",
                        size,
                        (opening_x1 + right_w / 2, float(y), wall_center_z),
                    )
                )
        lintel_h = max(0.0, shell_height - opening_h)
        lintel_w = max(0.0, opening_x1 - opening_x0)
        if lintel_h > min_axis and lintel_w > min_axis:
            size = (lintel_w, float(spec.wall_thickness), lintel_h)
            if min(size) > min_axis:
                part_specs.append(
                    (
                        "Lintel",
                        size,
                        ((opening_x0 + opening_x1) / 2, float(y), opening_top_z + lintel_h / 2),
                    )
                )
        for suffix, size, location in part_specs:
            source_name = _name(prefix, f"{side_label}_F{floor:02d}_{suffix}")
            _register_structural_box_plane(
                occupancy_author,
                size=size,
                location=location,
                normal_axis="y",
                material=material,
                source_bucket=SECTION_STAIRS_ROOM_SHELL,
                source_name=source_name,
            )
            part_obj = _create_box(
                source_name,
                size,
                location,
                collection,
                parent,
                material,
            )
            part_obj = _mark_section(
                _mark_generated(part_obj, tbg_room_partition=True),
                SECTION_STAIRS_ROOM_SHELL,
                hide_with_walls=False,
            )
            emitted_parts.append(part_obj)
        if runtime_emitter is not None:
            for part_obj in emitted_parts:
                if part_obj is None:
                    continue
                runtime_emitter.emit_box(
                    role=ROLE_PARTITION,
                    size=tuple(float(value) for value in part_obj.dimensions),
                    location=tuple(float(value) for value in part_obj.location),
                    source_name=part_obj.name,
                    metadata_values={"tbg_runtime_floor": int(floor)},
                )


def _use_per_floor_core_room_shell(spec) -> bool:
    return str(getattr(spec, "preset_id", "")).lower() in {
        "house_small",
        "house_wide",
        "wood_house",
        "wood_rowhouse",
        "townhouse",
        "apartment_lowrise",
    }


def _core_arrival_sightline_keepout_bounds(
    spec,
    *,
    start_floor: int = 0,
) -> tuple[float, float, float, float, float, float] | None:
    if not bool(getattr(spec, "stair_core", None) and spec.stair_core.enabled):
        return None
    if int(start_floor) >= int(spec.floor_count):
        return None
    metrics = _dogleg_metrics(spec)
    x0, x1, _opening_h = _core_arrival_opening_bounds(spec, metrics)
    if x1 <= x0 + 1e-4:
        return None

    run_depth = float(metrics.landing_depth + max(metrics.lower_tread, metrics.upper_tread) * 1.15)
    if str(metrics.arrival_side) == "FRONT":
        y0 = float(metrics.y0 - spec.wall_thickness / 2 - 0.02)
        y1 = float(min(metrics.y1, metrics.arrival_landing_y + run_depth))
    else:
        y0 = float(max(metrics.y0, metrics.arrival_landing_y - run_depth))
        y1 = float(metrics.y1 + spec.wall_thickness / 2 + 0.02)
    if y1 <= y0 + 1e-4:
        return None

    z0 = float(_level_base_z(spec, start_floor) + max(0.04, spec.slab_thickness * 0.6))
    z1 = float(_level_base_z(spec, int(spec.floor_count)) - max(0.04, spec.slab_thickness * 0.35))
    if z1 <= z0 + 1e-4:
        return None
    return (x0, x1, y0, y1, z0, z1)


def _subtract_keepout_from_box(
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    keepout_bounds: tuple[float, float, float, float, float, float] | None,
    *,
    preserve_vertical_remainders: bool = True,
) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    if keepout_bounds is None:
        return [(size, location)]
    half_x, half_y, half_z = size[0] / 2, size[1] / 2, size[2] / 2
    box_bounds = (
        location[0] - half_x,
        location[0] + half_x,
        location[1] - half_y,
        location[1] + half_y,
        location[2] - half_z,
        location[2] + half_z,
    )
    cut_x0 = max(float(box_bounds[0]), float(keepout_bounds[0]))
    cut_x1 = min(float(box_bounds[1]), float(keepout_bounds[1]))
    cut_y0 = max(float(box_bounds[2]), float(keepout_bounds[2]))
    cut_y1 = min(float(box_bounds[3]), float(keepout_bounds[3]))
    cut_z0 = max(float(box_bounds[4]), float(keepout_bounds[4]))
    cut_z1 = min(float(box_bounds[5]), float(keepout_bounds[5]))
    if cut_x1 <= cut_x0 + 1e-4 or cut_y1 <= cut_y0 + 1e-4 or cut_z1 <= cut_z0 + 1e-4:
        return [(size, location)]

    parts_bounds = [
        (box_bounds[0], cut_x0, box_bounds[2], box_bounds[3], box_bounds[4], box_bounds[5]),
        (cut_x1, box_bounds[1], box_bounds[2], box_bounds[3], box_bounds[4], box_bounds[5]),
        (cut_x0, cut_x1, box_bounds[2], cut_y0, box_bounds[4], box_bounds[5]),
        (cut_x0, cut_x1, cut_y1, box_bounds[3], box_bounds[4], box_bounds[5]),
    ]
    if preserve_vertical_remainders:
        parts_bounds.extend(
            (
                (cut_x0, cut_x1, cut_y0, cut_y1, box_bounds[4], cut_z0),
                (cut_x0, cut_x1, cut_y0, cut_y1, cut_z1, box_bounds[5]),
            )
        )
    result: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for part_x0, part_x1, part_y0, part_y1, part_z0, part_z1 in parts_bounds:
        if (
            part_x1 - part_x0 <= 1e-4
            or part_y1 - part_y0 <= 1e-4
            or part_z1 - part_z0 <= 1e-4
        ):
            continue
        result.append(
            (
                (part_x1 - part_x0, part_y1 - part_y0, part_z1 - part_z0),
                ((part_x0 + part_x1) / 2, (part_y0 + part_y1) / 2, (part_z0 + part_z1) / 2),
            )
        )
    return result


def _build_core_partitions(
    prefix,
    spec,
    collection,
    parent,
    material,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    if not spec.stair_core.enabled:
        return

    start_floor = 1 if getattr(spec, "massing_profile", "") == MASSING_PROFILE_PILOTIS else 0
    if start_floor >= spec.floor_count:
        return

    metrics = _dogleg_metrics(spec)
    spatial_plan = _spatial_plan(spec)
    total_h = (spec.floor_count - start_floor) * spec.floor_height
    wall_z = _level_base_z(spec, start_floor) + total_h / 2
    adjacent = _adjacent_exterior_sides(spec)
    keepout_bounds = _core_arrival_sightline_keepout_bounds(spec, start_floor=start_floor)
    per_floor_core_room_shell = _use_per_floor_core_room_shell(spec)
    top_floor_shell_clearance = (
        float(spec.slab_thickness)
        if bool(getattr(spatial_plan, "roof_access_enabled", False))
        else 0.0
    )

    def _core_shell_occupancy_box(
        name: str,
        part_size: tuple[float, float, float],
        part_location: tuple[float, float, float],
        *,
        normal_axis: str,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        if normal_axis != "y" or name not in {"Core_Front_Solid", "Core_Back_Solid"}:
            return part_size, part_location
        x0 = float(part_location[0]) - float(part_size[0]) / 2
        x1 = float(part_location[0]) + float(part_size[0]) / 2
        if "LEFT" not in adjacent:
            x0 += float(spec.wall_thickness)
        if "RIGHT" not in adjacent:
            x1 -= float(spec.wall_thickness)
        if x1 <= x0 + max(1e-4, float(spec.wall_thickness) * 0.25):
            return None
        return (
            (x1 - x0, float(part_size[1]), float(part_size[2])),
            ((x0 + x1) / 2, float(part_location[1]), float(part_location[2])),
        )

    def _emit_core_shell_box(
        name: str,
        size: tuple[float, float, float],
        location: tuple[float, float, float],
        *,
        normal_axis: str,
    ):
        shell_segments = [((float(size[0]), float(size[1]), float(size[2])), location)]
        if per_floor_core_room_shell:
            shell_segments = []
            for floor in range(start_floor, spec.floor_count):
                shell_height = (
                    max(0.0, float(spec.floor_height) - top_floor_shell_clearance)
                    if floor == spec.floor_count - 1
                    else float(spec.floor_height)
                )
                if shell_height <= 1e-4:
                    continue
                shell_segments.append(
                    (
                        (float(size[0]), float(size[1]), shell_height),
                        (float(location[0]), float(location[1]), _level_base_z(spec, floor) + shell_height / 2),
                    )
                )
        for segment_index, (segment_size, segment_location) in enumerate(shell_segments):
            clipped_parts = _subtract_keepout_from_box(
                segment_size,
                segment_location,
                keepout_bounds,
                preserve_vertical_remainders=False,
            )
            for idx, (part_size, part_location) in enumerate(clipped_parts):
                if len(shell_segments) == 1 and len(clipped_parts) == 1:
                    part_name = name
                elif len(clipped_parts) == 1:
                    part_name = f"{name}_F{start_floor + segment_index:02d}"
                else:
                    floor_suffix = f"_F{start_floor + segment_index:02d}" if len(shell_segments) > 1 else ""
                    part_name = f"{name}{floor_suffix}_K{idx:02d}"
                source_name = _name(prefix, part_name)
                occupancy_box = _core_shell_occupancy_box(
                    name,
                    part_size,
                    part_location,
                    normal_axis=normal_axis,
                )
                if occupancy_box is not None:
                    occupancy_size, occupancy_location = occupancy_box
                    _register_structural_box_plane(
                        occupancy_author,
                        size=occupancy_size,
                        location=occupancy_location,
                        normal_axis=normal_axis,
                        material=material,
                        source_bucket=SECTION_STAIRS_ROOM_SHELL,
                        source_name=source_name,
                    )
                wall = _create_box(
                    source_name,
                    part_size,
                    part_location,
                    collection,
                    parent,
                    material,
                )
                wall = _mark_section(
                    _mark_generated(wall, tbg_room_partition=True, tbg_core_partition_shell=True),
                    SECTION_STAIRS_ROOM_SHELL,
                    hide_with_walls=False,
                )
                if runtime_emitter is not None and wall is not None:
                    runtime_emitter.emit_box(
                        role=ROLE_PARTITION,
                        size=tuple(float(value) for value in part_size),
                        location=tuple(float(value) for value in part_location),
                        source_name=wall.name,
                        metadata_values={"tbg_runtime_partition_owner": "core_shell"},
                    )

    if "LEFT" not in adjacent:
        _emit_core_shell_box(
            "Core_Left",
            (spec.wall_thickness, metrics.core_depth, total_h),
            (metrics.x0 + spec.wall_thickness / 2, metrics.cy, wall_z),
            normal_axis="x",
        )
    if "RIGHT" not in adjacent:
        _emit_core_shell_box(
            "Core_Right",
            (spec.wall_thickness, metrics.core_depth, total_h),
            (metrics.x1 - spec.wall_thickness / 2, metrics.cy, wall_z),
            normal_axis="x",
        )

    if metrics.opposite_side == "FRONT" and "FRONT" not in adjacent:
        _emit_core_shell_box(
            "Core_Front_Solid",
            (metrics.core_width, spec.wall_thickness, total_h),
            (metrics.cx, metrics.y0 + spec.wall_thickness / 2, wall_z),
            normal_axis="y",
        )
    elif metrics.opposite_side == "BACK" and "BACK" not in adjacent:
        _emit_core_shell_box(
            "Core_Back_Solid",
            (metrics.core_width, spec.wall_thickness, total_h),
            (metrics.cx, metrics.y1 - spec.wall_thickness / 2, wall_z),
            normal_axis="y",
        )

    if metrics.arrival_side == "FRONT" and "FRONT" not in adjacent:
        _build_partition_wall_y_with_openings(
            prefix,
            "Core_Front_Open",
            spec,
            metrics.y0 + spec.wall_thickness / 2,
            collection,
            parent,
            material,
            runtime_emitter=runtime_emitter,
            occupancy_author=occupancy_author,
            start_floor=start_floor,
            top_floor_shell_clearance=top_floor_shell_clearance,
        )
    elif metrics.arrival_side == "BACK" and "BACK" not in adjacent:
        _build_partition_wall_y_with_openings(
            prefix,
            "Core_Back_Open",
            spec,
            metrics.y1 - spec.wall_thickness / 2,
            collection,
            parent,
            material,
            runtime_emitter=runtime_emitter,
            occupancy_author=occupancy_author,
            start_floor=start_floor,
            top_floor_shell_clearance=top_floor_shell_clearance,
        )


def _build_partition_wall_x_with_opening(
    prefix,
    side_label,
    spec,
    x,
    opening_center_y,
    opening_width,
    collection,
    parent,
    wall_material,
    frame_material,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    *,
    floors: tuple[int, ...] | None = None,
    interior_bounds: tuple[float, float, float, float] | None = None,
):
    inner_x0, inner_x1, inner_y0, inner_y1 = (
        _interior_bounds(spec) if interior_bounds is None else interior_bounds
    )
    if not (inner_x0 + spec.wall_thickness <= x <= inner_x1 - spec.wall_thickness):
        return

    opening_width = min(opening_width, inner_y1 - inner_y0 - 1.0)
    if opening_width <= 0.0:
        return
    opening_center_y = min(max(opening_center_y, inner_y0 + opening_width / 2 + 0.25), inner_y1 - opening_width / 2 - 0.25)
    opening_min = opening_center_y - opening_width / 2
    opening_max = opening_center_y + opening_width / 2
    preserve_single_floor_evidence = int(spec.floor_count) == 1
    partition_height = max(2.45, spec.floor_height - WIDE_PARTITION_TOP_GAP)
    opening_h = min(WIDE_PARTITION_OPENING_HEIGHT, max(2.15, partition_height - 0.42))
    lintel_h = max(0.22, partition_height - opening_h)
    frame_depth = max(spec.wall_thickness + WIDE_PARTITION_FRAME_PROUD * 2, WIDE_PARTITION_FRAME_DEPTH)

    floor_indices = tuple(range(spec.floor_count)) if floors is None else floors
    for floor in floor_indices:
        z0 = _level_base_z(spec, floor)
        front_span = opening_min - inner_y0
        back_span = inner_y1 - opening_max
        if front_span > 0.08:
            front_size = (spec.wall_thickness, front_span, partition_height)
            front_location = (x, (inner_y0 + opening_min) / 2, z0 + partition_height / 2)
            front_source_name = _name(prefix, f"{side_label}_F{floor:02d}_Front")
            _register_structural_box_plane(
                occupancy_author,
                size=front_size,
                location=front_location,
                normal_axis="x",
                material=wall_material,
                source_bucket="Section_Walls_Interior",
                source_name=front_source_name,
            )
            front = _mark_section(
                _mark_generated(
                    _create_box(
                        front_source_name,
                        front_size,
                        front_location,
                        collection,
                        parent,
                        wall_material,
                    ),
                    tbg_room_partition=True,
                ),
                "Section_Walls_Interior",
                merge_allowed=not preserve_single_floor_evidence,
                hide_with_walls=False,
            )
            if runtime_emitter is not None and front is not None:
                runtime_emitter.emit_box(
                    role=ROLE_PARTITION,
                    size=(spec.wall_thickness, front_span, partition_height),
                    location=(x, (inner_y0 + opening_min) / 2, z0 + partition_height / 2),
                    source_name=front.name,
                    metadata_values={"tbg_runtime_floor": int(floor)},
                )
        if back_span > 0.08:
            back_size = (spec.wall_thickness, back_span, partition_height)
            back_location = (x, (opening_max + inner_y1) / 2, z0 + partition_height / 2)
            back_source_name = _name(prefix, f"{side_label}_F{floor:02d}_Back")
            _register_structural_box_plane(
                occupancy_author,
                size=back_size,
                location=back_location,
                normal_axis="x",
                material=wall_material,
                source_bucket="Section_Walls_Interior",
                source_name=back_source_name,
            )
            back = _mark_section(
                _mark_generated(
                    _create_box(
                        back_source_name,
                        back_size,
                        back_location,
                        collection,
                        parent,
                        wall_material,
                    ),
                    tbg_room_partition=True,
                ),
                "Section_Walls_Interior",
                merge_allowed=not preserve_single_floor_evidence,
                hide_with_walls=False,
            )
            if runtime_emitter is not None and back is not None:
                runtime_emitter.emit_box(
                    role=ROLE_PARTITION,
                    size=(spec.wall_thickness, back_span, partition_height),
                    location=(x, (opening_max + inner_y1) / 2, z0 + partition_height / 2),
                    source_name=back.name,
                    metadata_values={"tbg_runtime_floor": int(floor)},
                )
        lintel_size = (spec.wall_thickness, opening_width, lintel_h)
        lintel_location = (x, opening_center_y, z0 + opening_h + lintel_h / 2)
        lintel_source_name = _name(prefix, f"{side_label}_F{floor:02d}_Lintel")
        _register_structural_box_plane(
            occupancy_author,
            size=lintel_size,
            location=lintel_location,
            normal_axis="x",
            material=wall_material,
            source_bucket="Section_Walls_Interior",
            source_name=lintel_source_name,
        )
        lintel = _mark_section(
            _mark_generated(
                _create_box(
                    lintel_source_name,
                    lintel_size,
                    lintel_location,
                    collection,
                    parent,
                    wall_material,
                ),
                tbg_room_partition=True,
            ),
            "Section_Walls_Interior",
            merge_allowed=not preserve_single_floor_evidence,
            hide_with_walls=False,
        )
        if runtime_emitter is not None and lintel is not None:
            runtime_emitter.emit_box(
                role=ROLE_PARTITION,
                size=(spec.wall_thickness, opening_width, lintel_h),
                location=(x, opening_center_y, z0 + opening_h + lintel_h / 2),
                source_name=lintel.name,
                metadata_values={"tbg_runtime_floor": int(floor)},
            )
        frame_inner_width = max(0.18, opening_width - WIDE_PARTITION_FRAME_REVEAL)
        frame_inner_height = max(0.18, opening_h - WIDE_PARTITION_FRAME_REVEAL)
        frame_name = _name(prefix, f"{side_label}_F{floor:02d}_Frame")
        frame_mesh = _frame_mesh(
            frame_name,
            opening_width + 0.24,
            frame_depth,
            opening_h + 0.24,
            frame_inner_width,
            frame_inner_height,
            visible_positive_depth=True,
            double_sided=True,
        )
        frame = bpy.data.objects.new(frame_name, frame_mesh)
        collection.objects.link(frame)
        _parent_to(frame, parent)
        frame.location = Vector(_opening_location("Y", opening_center_y, x, z0 + opening_h / 2))
        frame.rotation_euler = Euler(_orientation_rotation("Y"), "XYZ")
        _assign_material(frame, frame_material)
        _mark_section(
            _mark_generated(frame, tbg_room_partition_frame=True),
            "Section_Openings_Frame",
            merge_allowed=not preserve_single_floor_evidence,
        )


def _build_wide_room_partitions(
    prefix,
    spec,
    spatial_plan,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    if _is_hangar_frontage(spec) or _is_market_hall_frontage(spec):
        parent["tbg_room_partition_eligible"] = False
        parent["tbg_room_partition_corridor_width"] = 0.0
        return
    parent["tbg_room_partition_corridor_width"] = 0.0
    authored_any = False
    corridor_width = 0.0
    for floor_plan in tuple(getattr(spatial_plan, "floors", ()) or ()):
        floor = int(floor_plan.floor_index)
        floor_inner_bounds = _interior_bounds_for_rect(floor_plan.footprint, spec.wall_thickness)
        positions = _wide_partition_positions(spec, interior_bounds=floor_inner_bounds)
        if not positions:
            continue
        inner_x0, inner_x1, inner_y0, inner_y1 = floor_inner_bounds
        opening_center_y = min(
            max(0.0, inner_y0 + WIDE_PARTITION_OPENING_WIDTH / 2 + 0.25),
            inner_y1 - WIDE_PARTITION_OPENING_WIDTH / 2 - 0.25,
        )
        opening_width = min(
            inner_y1 - inner_y0 - 1.0,
            max(WIDE_PARTITION_OPENING_WIDTH, min(2.2, (inner_y1 - inner_y0) * 0.28)),
        )
        if opening_width <= 0.0:
            continue
        authored_any = True
        corridor_width = max(corridor_width, float(opening_width))
        for idx, x in enumerate(positions):
            _build_partition_wall_x_with_opening(
                prefix,
                f"RoomPartition_{idx:02d}",
                spec,
                x,
                opening_center_y,
                opening_width,
                collection,
                parent,
                materials_map["interior_wall"],
                materials_map["trim"],
                runtime_emitter=runtime_emitter,
                occupancy_author=occupancy_author,
                floors=(floor,),
                interior_bounds=floor_inner_bounds,
            )
    parent["tbg_room_partition_eligible"] = authored_any
    parent["tbg_room_partition_corridor_width"] = float(round(corridor_width, 4))


def _build_landing(
    name,
    width,
    depth,
    top_z,
    x,
    y,
    collection,
    parent,
    material,
    thickness,
    *,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    runtime_role: str = ROLE_STAIR_LANDING,
    runtime_metadata: dict | None = None,
    generated_metadata: dict | None = None,
):
    landing = _create_box(
        name,
        (width, depth, thickness),
        (x, y, top_z - thickness / 2),
        collection,
        parent,
        material,
    )
    if generated_metadata:
        landing = _mark_generated(landing, **generated_metadata)
    if runtime_emitter is not None and landing is not None:
        runtime_emitter.emit_box(
            role=runtime_role,
            size=(width, depth, thickness),
            location=(x, y, top_z - thickness / 2),
            source_name=landing.name,
            metadata_values=runtime_metadata,
        )
    return _mark_section(landing, "Section_Stairs_Landings")


def _landing_rect_from_center(
    *,
    center_x: float,
    center_y: float,
    width: float,
    depth: float,
) -> tuple[float, float, float, float]:
    return (
        float(center_x - width / 2),
        float(center_x + width / 2),
        float(center_y - depth / 2),
        float(center_y + depth / 2),
    )


def _rect_center_size(rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, x1, y0, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    return float((x0 + x1) / 2), float((y0 + y1) / 2), float(x1 - x0), float(y1 - y0)


def _build_landing_from_rect(
    name,
    *,
    rect: tuple[float, float, float, float],
    top_z: float,
    collection,
    parent,
    material,
    thickness: float,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    runtime_role: str = ROLE_STAIR_LANDING,
    runtime_metadata: dict | None = None,
    generated_metadata: dict | None = None,
):
    center_x, center_y, width, depth = _rect_center_size(rect)
    if width <= 1e-4 or depth <= 1e-4:
        return None
    return _build_landing(
        name,
        width,
        depth,
        top_z,
        center_x,
        center_y,
        collection,
        parent,
        material,
        thickness,
        runtime_emitter=runtime_emitter,
        runtime_role=runtime_role,
        runtime_metadata=runtime_metadata,
        generated_metadata=generated_metadata,
    )


def _build_landing_side_guards(
    name,
    *,
    rect: tuple[float, float, float, float],
    top_z: float,
    collection,
    parent,
    material,
    open_sides: set[str] | None = None,
):
    open_side_set = {str(side).upper() for side in (open_sides or set())}
    center_x, center_y, width, depth = _rect_center_size(rect)
    if width <= RAIL_THICKNESS * 2.0 or depth <= RAIL_THICKNESS * 4.0:
        return

    rail_depth = depth - RAIL_THICKNESS * 2.0
    if rail_depth <= RAIL_THICKNESS:
        return

    x0 = center_x - width / 2
    x1 = center_x + width / 2
    y0 = center_y - depth / 2
    y1 = center_y + depth / 2
    left_x = x0 + RAIL_THICKNESS / 2
    right_x = x1 - RAIL_THICKNESS / 2

    post_height = max(0.72, RAIL_HEIGHT)
    end_inset = min(max(0.12, RAIL_THICKNESS * 2.5), max(0.12, depth / 2 - RAIL_THICKNESS))
    front_y = y0 + end_inset
    back_y = y1 - end_inset
    if back_y < front_y:
        front_y = center_y
        back_y = center_y

    guard_sides: list[float] = []
    parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    if "LEFT" not in open_side_set:
        guard_sides.append(left_x)
    if "RIGHT" not in open_side_set:
        guard_sides.append(right_x)
    for side_x in guard_sides:
        parts.append(((RAIL_THICKNESS, rail_depth, RAIL_THICKNESS), (side_x - center_x, 0.0, RAIL_HEIGHT)))
    for post_x in guard_sides:
        for post_y in (front_y, back_y):
            parts.append(
                (
                    (RAIL_THICKNESS, RAIL_THICKNESS, post_height),
                    (post_x - center_x, post_y - center_y, post_height / 2),
                )
            )
    if not parts:
        return

    _mark_section(
        _create_composite_box_object(
            name,
            parts,
            (center_x, center_y, top_z),
            collection,
            parent,
            material,
        ),
        "Section_Stairs_Flights",
    )


def _build_planned_top_arrival(
    prefix,
    *,
    floor_index: int,
    top_level_z: float,
    rects: tuple[tuple[float, float, float, float], ...],
    terminal_profile: str | None,
    roof_room_footprint: tuple[float, float, float, float] | None,
    collection,
    parent,
    material,
    thickness: float,
    mark_roof_terminal: bool,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    resolved_terminal_profile = str(terminal_profile or "").upper()
    for rect_index, rect in enumerate(rects):
        is_landing_rect = rect_index == 0
        is_roof_room_support_rect = False
        is_connector_rect = False
        if mark_roof_terminal and not is_landing_rect:
            if resolved_terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN:
                is_roof_room_support_rect = True
            elif roof_room_footprint is not None:
                footprint_x0, footprint_x1, footprint_y0, footprint_y1 = (
                    float(value) for value in roof_room_footprint
                )
                rect_x0, rect_x1, rect_y0, rect_y1 = (float(value) for value in rect)
                within_roof_room_footprint = (
                    rect_x0 >= footprint_x0 - 1e-4
                    and rect_x1 <= footprint_x1 + 1e-4
                    and rect_y0 >= footprint_y0 - 1e-4
                    and rect_y1 <= footprint_y1 + 1e-4
                )
                if _rects_almost_equal(rect, roof_room_footprint) or within_roof_room_footprint:
                    is_roof_room_support_rect = True
                else:
                    is_connector_rect = True
            else:
                is_connector_rect = True

        if is_landing_rect:
            landing_name = "Roof_Landing"
            runtime_label = "Roof_Landing"
        elif is_connector_rect:
            landing_name = "Roof_Landing_Connector_01"
            runtime_label = "Roof_Landing_Connector"
        else:
            landing_name = f"Roof_TopRoom_Floor_{rect_index:02d}"
            runtime_label = "Roof_TopRoom_Floor"
        runtime_role = ROLE_ROOF_EXIT_PLATFORM if is_roof_room_support_rect else ROLE_STAIR_LANDING
        generated_metadata = {
            "tbg_roof_exit_platform_piece": int(rect_index),
            "tbg_roof_exit_connector": bool(is_connector_rect),
        }
        if is_roof_room_support_rect:
            generated_metadata.update(
                {
                    "tbg_roof_exit_platform": True,
                    "tbg_top_room_floor": True,
                }
            )
        _build_landing_from_rect(
            _name(prefix, landing_name),
            rect=rect,
            top_z=top_level_z,
            collection=collection,
            parent=parent,
            material=material,
            thickness=thickness,
            runtime_emitter=runtime_emitter,
            runtime_role=runtime_role,
            runtime_metadata={
                "tbg_runtime_floor": int(floor_index),
                "tbg_runtime_label": runtime_label,
                "tbg_runtime_piece": int(rect_index),
            },
            generated_metadata=generated_metadata,
        )


def _build_flight_steps(
    prefix,
    floor_index,
    label,
    lane_x,
    start_y,
    direction,
    tread,
    step_count,
    base_z,
    step_rise,
    step_t,
    flight_width,
    collection,
    parent,
    material,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    *,
    variant: str = "DEFAULT",
):
    run_total = tread * step_count
    rise_total = step_rise * step_count
    start_edge_y = start_y - direction * tread / 2
    end_edge_y = start_edge_y + direction * run_total
    mid_y = (start_edge_y + end_edge_y) / 2
    flight_name = _name(prefix, f"Stair_F{floor_index:02d}_{label}_Flight")
    visual_width = max(0.28, flight_width - 0.16) if str(variant).upper() == "OPEN" else flight_width
    mesh = _stepped_flight_mesh(
        flight_name,
        visual_width,
        tread,
        step_count,
        step_rise,
        step_t,
    )
    obj = bpy.data.objects.new(flight_name, mesh)
    collection.objects.link(obj)
    _parent_to(obj, parent)
    obj.location = Vector((lane_x, mid_y, base_z))
    obj.rotation_euler = Euler((0.0, 0.0, math.pi if direction < 0 else 0.0), "XYZ")
    _assign_material(obj, material)
    _mark_section(
        _mark_generated(
            obj,
            tbg_stair_flight=True,
            tbg_stair_floor=int(floor_index),
            tbg_stair_label=str(label),
            tbg_stair_direction=float(direction),
            tbg_stair_run_total=float(run_total),
            tbg_stair_rise_total=float(rise_total),
            tbg_stair_width=float(flight_width),
            tbg_stair_variant=str(variant).upper(),
            tbg_stair_runtime_source=obj.name,
        ),
        "Section_Stairs_Flights",
    )
    if runtime_emitter is not None:
        slope_len = math.hypot(run_total, rise_total)
        runtime_emitter.emit_box(
            role=ROLE_STAIR_RAMP,
            size=(flight_width, slope_len, max(0.08, min(0.14, step_rise * 0.5))),
            location=(lane_x, mid_y, base_z + rise_total / 2),
            rotation=(math.atan2(rise_total, run_total) * direction, 0.0, 0.0),
            source_name=obj.name,
            metadata_values={
                "tbg_runtime_floor": int(floor_index),
                "tbg_runtime_label": str(label),
                "tbg_runtime_direction": float(direction),
            },
        )
        surface_depth = tread + min(0.08, max(0.04, tread * 0.22))
        surface_height = min(0.07, max(0.045, min(step_t + 0.01, step_rise * 0.45)))
        start_edge = -run_total / 2
        collision_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
        per_part_metadata: list[dict] = []
        for step_index in range(max(step_count, 1)):
            tread_center_y = start_edge + step_index * tread + tread / 2
            tread_top_z = (step_index + 1) * step_rise
            collision_parts.append(
                (
                    (flight_width, surface_depth, surface_height),
                    (0.0, tread_center_y, tread_top_z - surface_height / 2),
                )
            )
            per_part_metadata.append(
                {
                    "tbg_runtime_floor": int(floor_index),
                    "tbg_runtime_label": str(label),
                    "tbg_runtime_direction": float(direction),
                    "tbg_runtime_step_index": int(step_index),
                    "tbg_runtime_top_z": float(base_z + tread_top_z),
                }
            )
        runtime_emitter.emit_composite_boxes(
            parts=collision_parts,
            base_location=(lane_x, mid_y, base_z),
            rotation=(0.0, 0.0, math.pi if direction < 0 else 0.0),
            roles=[ROLE_STAIR_STEP] * len(collision_parts),
            source_name=obj.name,
            metadata_values={
                "tbg_runtime_floor": int(floor_index),
                "tbg_runtime_label": str(label),
                "tbg_runtime_direction": float(direction),
            },
            per_part_metadata=per_part_metadata,
        )


def _build_flight_support(
    prefix,
    floor_index,
    label,
    lane_x,
    start_y,
    direction,
    tread,
    step_count,
    base_z,
    step_rise,
    flight_width,
    collection,
    parent,
    material,
    *,
    railing_enabled=False,
    variant: str = "DEFAULT",
):
    if step_count <= 0:
        return

    run_total = tread * step_count
    rise_total = step_rise * step_count
    slope_len = math.hypot(run_total, rise_total)
    angle = math.atan2(rise_total, run_total) * direction
    start_edge_y = start_y - direction * tread / 2
    end_edge_y = start_y + direction * (step_count - 0.5) * tread
    mid_y = (start_edge_y + end_edge_y) / 2
    mid_z = base_z + rise_total / 2

    parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    x_offset = max(0.18, flight_width / 2 - 0.06)
    if str(variant).upper() == "OPEN":
        center_stringer_width = max(0.12, min(0.2, flight_width * 0.18))
        parts.append(((center_stringer_width, slope_len, 0.1), (0.0, 0.0, -0.025)))
    else:
        parts.append(((STRINGER_THICKNESS, slope_len, 0.12), (-x_offset, 0.0, -0.02)))
        parts.append(((STRINGER_THICKNESS, slope_len, 0.12), (x_offset, 0.0, -0.02)))

    if railing_enabled:
        rail_positions: list[float]
        if str(variant).upper() == "OPEN":
            rail_offset = max(0.16, flight_width / 2 - 0.04)
            rail_positions = [-rail_offset, rail_offset]
        else:
            rail_positions = [-x_offset, x_offset]
        for x in rail_positions:
            parts.append(((RAIL_THICKNESS, slope_len, RAIL_THICKNESS), (x, 0.0, RAIL_HEIGHT)))

        post_edge_inset = min(max(0.16, tread * 0.85), max(0.16, slope_len / 2 - 0.08))
        post_span = max(0.0, slope_len - post_edge_inset * 2.0)
        if post_span <= 1e-4:
            post_alongs = [0.0]
        else:
            target_spacing = max(0.8, min(1.15, tread * 4.0))
            post_count = max(2, min(3, int(math.ceil(post_span / target_spacing)) + 1))
            post_step = post_span / (post_count - 1)
            start_along = -post_span / 2
            post_alongs = [start_along + index * post_step for index in range(post_count)]

        post_height = max(0.72, RAIL_HEIGHT)
        post_center_z = post_height / 2
        for x in rail_positions:
            for along in post_alongs:
                parts.append(((RAIL_THICKNESS, RAIL_THICKNESS, post_height), (x, along, post_center_z)))

    if not parts:
        return

    _mark_section(
        _create_composite_box_object(
            _name(prefix, f"Stair_F{floor_index:02d}_{label}_Support"),
            parts,
            (lane_x, mid_y, mid_z),
            collection,
            parent,
            material,
            rotation=(angle, 0.0, 0.0),
        ),
        "Section_Stairs_Flights",
    )


def _build_stairs(prefix, spec, spatial_plan, collection, parent, material, runtime_emitter: RuntimeMarkerEmitter | None = None):
    if not spec.stair_core.enabled:
        return

    metrics = _dogleg_metrics(spec)
    stair_variant = _stair_core_variant(spec)
    railing_enabled = bool(getattr(spec.stair_core, "railing_enabled", False))
    step_t = min(0.08, max(0.05, metrics.step_rise * 0.45))
    if spatial_plan.stair_run_count <= 0:
        return

    for floor in range(spatial_plan.stair_run_count):
        for part in (
            "lower_steps",
            "upper_steps",
            "lower_support",
            "upper_support",
            "mid_landing",
            "top_landing",
        ):
            _build_stair_step(
                prefix,
                spec,
                spatial_plan,
                collection,
                parent,
                material,
                floor,
                part,
                runtime_emitter=runtime_emitter,
            )


def _build_stair_step(
    prefix,
    spec,
    spatial_plan,
    collection,
    parent,
    material,
    floor: int,
    part: str,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    if not spec.stair_core.enabled or spatial_plan.stair_run_count <= 0:
        return
    if int(floor) < 0 or int(floor) >= int(spatial_plan.stair_run_count):
        return

    metrics = _dogleg_metrics(spec)
    stair_variant = _stair_core_variant(spec)
    railing_enabled = bool(getattr(spec.stair_core, "railing_enabled", False))
    step_t = min(0.08, max(0.05, metrics.step_rise * 0.45))
    base_z = _level_base_z(spec, floor)
    mid_level_z = base_z + metrics.lower_steps * metrics.step_rise
    top_level_z = base_z + spec.floor_height

    if part == "lower_steps":
        _build_flight_steps(
            prefix,
            floor,
            "Lower",
            metrics.lower_x,
            metrics.lower_start_y,
            metrics.lower_direction,
            metrics.lower_tread,
            metrics.lower_steps,
            base_z,
            metrics.step_rise,
            step_t,
            metrics.flight_width,
            collection,
            parent,
            material,
            runtime_emitter=runtime_emitter,
            variant=stair_variant,
        )
        return
    if part == "upper_steps":
        _build_flight_steps(
            prefix,
            floor,
            "Upper",
            metrics.upper_x,
            metrics.upper_start_y,
            metrics.upper_direction,
            metrics.upper_tread,
            metrics.upper_steps,
            mid_level_z,
            metrics.step_rise,
            step_t,
            metrics.flight_width,
            collection,
            parent,
            material,
            runtime_emitter=runtime_emitter,
            variant=stair_variant,
        )
        return
    if part == "lower_support":
        _build_flight_support(
            prefix,
            floor,
            "Lower",
            metrics.lower_x,
            metrics.lower_start_y,
            metrics.lower_direction,
            metrics.lower_tread,
            metrics.lower_steps,
            base_z,
            metrics.step_rise,
            metrics.flight_width,
            collection,
            parent,
            material,
            railing_enabled=railing_enabled,
            variant=stair_variant,
        )
        return
    if part == "upper_support":
        _build_flight_support(
            prefix,
            floor,
            "Upper",
            metrics.upper_x,
            metrics.upper_start_y,
            metrics.upper_direction,
            metrics.upper_tread,
            metrics.upper_steps,
            mid_level_z,
            metrics.step_rise,
            metrics.flight_width,
            collection,
            parent,
            material,
            railing_enabled=railing_enabled,
            variant=stair_variant,
        )
        return
    if part == "mid_landing":
        mid_landing_rect = _landing_rect_from_center(
            center_x=metrics.cx,
            center_y=metrics.mid_landing_y,
            width=metrics.clear_width,
            depth=metrics.landing_depth,
        )
        _build_landing_from_rect(
            _name(prefix, f"Stair_F{floor:02d}_MidLanding"),
            rect=mid_landing_rect,
            top_z=mid_level_z,
            collection=collection,
            parent=parent,
            material=material,
            thickness=spec.slab_thickness,
            runtime_emitter=runtime_emitter,
            runtime_metadata={"tbg_runtime_floor": int(floor), "tbg_runtime_label": "MidLanding"},
        )
        return
    if part == "top_landing":
        is_roof_exit_landing = (
            floor == spatial_plan.stair_run_count - 1
            and bool(spatial_plan.top_arrival_rects)
        )
        if is_roof_exit_landing:
            _build_planned_top_arrival(
                prefix,
                floor_index=floor,
                top_level_z=top_level_z,
                rects=spatial_plan.top_arrival_rects,
                terminal_profile=getattr(getattr(spatial_plan, "roof_room", None), "terminal_profile", None),
                roof_room_footprint=getattr(getattr(spatial_plan, "roof_room", None), "footprint", None),
                collection=collection,
                parent=parent,
                material=material,
                thickness=spec.slab_thickness,
                mark_roof_terminal=bool(spatial_plan.roof_access_enabled),
                runtime_emitter=runtime_emitter,
            )
            return
        top_landing_rect = _landing_rect_from_center(
            center_x=metrics.cx,
            center_y=metrics.arrival_landing_y,
            width=metrics.clear_width,
            depth=metrics.landing_depth,
        )
        _build_landing_from_rect(
            _name(prefix, f"Stair_F{floor:02d}_TopLanding"),
            rect=top_landing_rect,
            top_z=top_level_z,
            collection=collection,
            parent=parent,
            material=material,
            thickness=spec.slab_thickness,
            runtime_emitter=runtime_emitter,
            runtime_role=ROLE_STAIR_LANDING,
            runtime_metadata={"tbg_runtime_floor": int(floor), "tbg_runtime_label": f"Stair_F{floor:02d}_TopLanding"},
        )
        return
    raise ValueError(f"Unsupported stair step part: {part}")
