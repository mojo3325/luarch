from __future__ import annotations

import math

import bpy
from mathutils import Euler, Vector

from ..export_contract import (
    ROLE_ATTIC_OPENING,
    ROLE_BALCONY_RAIL,
    ROLE_FLOOR_BLOCKER,
    ROLE_ROOF_BLOCKER,
    ROLE_ROOF_EXIT_SHELL,
    ROLE_SHELL,
    VOXEL_SIZE_STUDS,
)
from .specs import (
    ROOF_MODE_BARREL,
    ROOF_MODE_FLAT,
    ROOF_MODE_GABLE,
    ROOF_MODE_SAWTOOTH,
    ROOF_MODE_SHED,
    ROOF_MODE_TERRACE,
)
from .building_layout import (
    BALCONY_RAIL_HEIGHT,
    BALCONY_RAIL_THICKNESS,
    _side_sign,
    PARAPET_CAP_DEPTH,
    PARAPET_CAP_HEIGHT,
    PARAPET_CAP_PROUD_OFFSET,
    PARAPET_THICKNESS_MIN,
    PARAPET_THICKNESS_SCALE,
    TERMINAL_PROFILE_ATTIC_OPEN,
    TERMINAL_PROFILE_FULL_ROOM,
    TERMINAL_PROFILE_STAIR_HEAD,
    TOP_TERMINAL_TOP_FLOOR_ONLY,
    _base_elevation,
    _level_base_z,
    _opening_location,
    _orientation_rotation,
    _roof_surface_z,
    _spatial_plan,
    _slab_center_z,
    _surface_coord,
)
from .layout_constants import INNER_FRAME_PROUD_OFFSET
from .layout_facade_planning import (
    _is_hangar_frontage,
    _is_industrial_frontage,
    _is_market_hall_frontage,
    _trim_material,
    _wall_material_for_floor,
)
from .building_support import (
    _assign_material,
    _create_box,
    _create_composite_box_object,
    _frame_mesh,
    _mark_generated,
    _mark_section,
    _mark_wall_section,
    _mesh_from_pydata,
    _name,
    _parent_to,
    resolve_authored_voxel_wall_material_metadata,
)
from .building_occupancy import (
    MIN_NON_THICKNESS_CELL_SPAN_STUDS,
    OPENING_VISUAL_CLEARANCE_STUDS,
    OccupancyAuthoringSession,
)
from .building_layout import WINDOW_FRAME_OVERLAP, WINDOW_FRAME_PROUD_OFFSET, WINDOW_TRIM_WIDTH
from .building_facade_opening_slots import (
    opening_cut_frame_envelope as _opening_cut_frame_envelope,
)
from .runtime_markers import RuntimeMarkerEmitter

from .building_roof_exit import _build_roof_exit
from .building_roof_services import _build_roof_props as _build_roof_props_owner, _roof_mode


def _roof_longitudinal_axis(spec) -> str:
    return "X" if spec.width >= spec.depth else "Y"


def _roof_cladding_material(materials_map):
    return materials_map["industrial_cladding"]


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


def _normal_axis_for_side_key(side_key: str) -> str:
    side = str(side_key or "").lower()
    if side in {"left", "right"}:
        return "x"
    if side in {"front", "back"}:
        return "y"
    raise ValueError(f"Unsupported wall side key for authored cell normal axis: {side_key!r}.")


def _normal_axis_for_profile_axis(axis: str) -> str:
    return "x" if str(axis).upper() == "X" else "y"


def _profile_opening_cut_metadata(
    *,
    kind: str,
    orientation: str,
    side_key: str,
    floor_index: int,
    slot_index: int,
    wall_pos: float,
    cut_rect: tuple[float, float, float, float],
    clearance_studs: float = OPENING_VISUAL_CLEARANCE_STUDS,
) -> dict[str, object]:
    clearance = max(0.0, float(clearance_studs))
    run_min, run_max, z_min, z_max = (float(value) for value in cut_rect)
    orientation_key = str(orientation).upper()
    normal_axis, run_axis = ("y", "x") if orientation_key == "X" else ("x", "y")
    return {
        "tbg_wall_opening_kind": str(kind),
        "tbg_wall_opening_side": str(side_key),
        "tbg_wall_opening_floor": int(floor_index),
        "tbg_wall_opening_slot": int(slot_index),
        "tbg_wall_cut_run_min": round(run_min - clearance, 4),
        "tbg_wall_cut_run_max": round(run_max + clearance, 4),
        "tbg_wall_cut_z_min": round(z_min - clearance, 4),
        "tbg_wall_cut_z_max": round(z_max + clearance, 4),
        "tbg_wall_plane_normal_axis": normal_axis,
        "tbg_wall_plane_run_axis": run_axis,
        "tbg_wall_plane_pos": round(float(wall_pos), 4),
    }


def _top_profile_function_points(profile: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    """Convert render outline points into the packer's run -> top_z function."""
    top_by_lateral: dict[float, float] = {}
    for lateral, z in profile:
        lateral_key = round(float(lateral), 4)
        z_value = round(float(z), 4)
        top_by_lateral[lateral_key] = max(z_value, top_by_lateral.get(lateral_key, z_value))
    points = tuple(sorted(top_by_lateral.items()))
    if len(points) < 2:
        return ()
    return points


def _top_profile_with_opening_boundary_knots(
    profile: list[tuple[float, float]],
    top_profile: tuple[tuple[float, float], ...],
    *,
    opening_lateral_span: tuple[float, float] | None,
) -> tuple[tuple[float, float], ...]:
    if opening_lateral_span is None or len(top_profile) < 2:
        return top_profile
    profile_min = float(top_profile[0][0])
    profile_max = float(top_profile[-1][0])
    opening_min, opening_max = sorted((float(opening_lateral_span[0]), float(opening_lateral_span[1])))
    boundary_span = float(MIN_NON_THICKNESS_CELL_SPAN_STUDS)
    top_by_lateral = {round(float(run), 4): round(float(z), 4) for run, z in top_profile}
    for lateral in (opening_min - boundary_span, opening_max + boundary_span):
        if lateral <= profile_min + 1e-4 or lateral >= profile_max - 1e-4:
            continue
        top_z = _profile_top_z_at_lateral(profile, lateral)
        if top_z is None:
            continue
        lateral_key = round(float(lateral), 4)
        z_value = round(float(top_z), 4)
        top_by_lateral[lateral_key] = max(z_value, top_by_lateral.get(lateral_key, z_value))
    return tuple(sorted(top_by_lateral.items()))


def _register_shell_fragment(
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
    sx, sy, sz = (float(value) for value in size)
    cx, cy, cz = (float(value) for value in location)
    if sz <= MIN_NON_THICKNESS_CELL_SPAN_STUDS + 1e-4:
        return
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
        raise ValueError("Roof shell wall-plane normal_axis must be 'x' or 'y'.")
    if run_max - run_min <= MIN_NON_THICKNESS_CELL_SPAN_STUDS + 1e-4:
        return
    occupancy_author.register_wall_plane(
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


def _register_profile_shell_plane(
    occupancy_author: OccupancyAuthoringSession | None,
    *,
    name: str,
    profile: list[tuple[float, float]],
    depth: float,
    axis: str,
    location: tuple[float, float, float],
    material,
    source_bucket: str,
    opening_lateral_span: tuple[float, float] | None = None,
    opening_base_z: float | None = None,
    opening_height: float | None = None,
    opening_clearance_studs: float = OPENING_VISUAL_CLEARANCE_STUDS,
) -> None:
    if occupancy_author is None or depth <= 1e-4 or len(profile) < 2:
        return
    material_family, visual_style, display_color_rgb = _resolved_structural_material_metadata(material)
    axis_key = str(axis).upper()
    normal_axis = _normal_axis_for_profile_axis(axis_key)
    top_profile = _top_profile_function_points(profile)
    if len(top_profile) < 2:
        return
    top_profile = _top_profile_with_opening_boundary_knots(
        profile,
        top_profile,
        opening_lateral_span=opening_lateral_span,
    )
    lateral_values = [float(point[0]) for point in top_profile]
    z_values = [float(point[1]) for point in top_profile]
    base_z = min(float(point[1]) for point in profile)
    if axis_key == "X":
        thickness_min = float(location[0]) - float(depth) / 2
        thickness_max = float(location[0]) + float(depth) / 2
        run_offset = float(location[1])
    else:
        thickness_min = float(location[1]) - float(depth) / 2
        thickness_max = float(location[1]) + float(depth) / 2
        run_offset = float(location[0])
    plane = occupancy_author.register_wall_plane(
        plane_id=f"{name}:plane",
        normal_axis=normal_axis,
        thickness_min=thickness_min,
        thickness_max=thickness_max,
        run_min=run_offset + min(lateral_values),
        run_max=run_offset + max(lateral_values),
        z_min=base_z,
        z_max=max(z_values),
        source_bucket=source_bucket,
        material_family=material_family,
        visual_style=visual_style,
        display_color_rgb=display_color_rgb,
        source_name=f"{name}:plane",
        staged_object_names=(name,),
    )
    plane.set_top_profile((run_offset + float(lateral), float(z)) for lateral, z in top_profile)
    if opening_lateral_span is not None and opening_base_z is not None and opening_height is not None:
        opening_min, opening_max = sorted((float(opening_lateral_span[0]), float(opening_lateral_span[1])))
        if opening_max - opening_min > 1e-4 and float(opening_height) > 1e-4:
            plane.add_rect_cut(
                "attic_opening",
                run_min=run_offset + opening_min,
                run_max=run_offset + opening_max,
                z_min=float(opening_base_z),
                z_max=float(opening_base_z) + float(opening_height),
                clearance_studs=opening_clearance_studs,
            )


def _emit_roof_blocker_box(
    runtime_emitter: RuntimeMarkerEmitter | None,
    *,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    source_name: str,
    metadata_values: dict | None = None,
):
    if runtime_emitter is None:
        return None
    return runtime_emitter.emit_box(
        role=ROLE_ROOF_BLOCKER,
        size=size,
        location=location,
        source_name=source_name,
        metadata_values=metadata_values,
    )


def _emit_shell_marker_box(
    runtime_emitter: RuntimeMarkerEmitter | None,
    *,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    source_name: str,
    side_key: str,
    floor_index: int,
):
    if runtime_emitter is None:
        return None
    return runtime_emitter.emit_box(
        role=ROLE_SHELL,
        size=size,
        location=location,
        source_name=source_name,
        metadata_values={"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)},
    )


def _emit_shell_markers(
    runtime_emitter: RuntimeMarkerEmitter | None,
    *,
    marker_specs: list[tuple[tuple[float, float, float], tuple[float, float, float], str, str]],
    floor_index: int,
):
    for size, location, source_name, side_key in marker_specs:
        _emit_shell_marker_box(
            runtime_emitter,
            size=size,
            location=location,
            source_name=source_name,
            side_key=side_key,
            floor_index=floor_index,
        )


def _emit_roof_blocker_volume(
    runtime_emitter: RuntimeMarkerEmitter | None,
    *,
    width: float,
    depth: float,
    bottom_z: float,
    height: float,
    source_name: str,
    center_x: float = 0.0,
    center_y: float = 0.0,
    metadata_values: dict | None = None,
):
    _emit_roof_blocker_box(
        runtime_emitter,
        size=(width, depth, height),
        location=(float(center_x), float(center_y), bottom_z + height / 2),
        source_name=source_name,
        metadata_values=metadata_values,
    )


def _emit_roof_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    collection,
    parent,
    material,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    emit_runtime_blocker: bool = True,
):
    roof_obj = _create_box(name, size, location, collection, parent, material, rotation=rotation)
    if roof_obj is not None and emit_runtime_blocker:
        _emit_roof_blocker_box(
            runtime_emitter,
            size=size,
            location=location,
            source_name=roof_obj.name,
        )
    return _mark_wall_section(roof_obj, "Section_Walls_Roof")


def _rect_from_size_location(
    size: tuple[float, float, float],
    location: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    width, depth, _height = (float(value) for value in size)
    x, y, _z = (float(value) for value in location)
    return (x - width / 2, x + width / 2, y - depth / 2, y + depth / 2)


def _register_shell_slab_fragments(
    occupancy_author: OccupancyAuthoringSession | None,
    *,
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    side_key: str,
    material,
    occupancy_exclusion_bounds: tuple[float, float, float, float] | None = None,
) -> None:
    if occupancy_author is None:
        return
    source_rect = _rect_from_size_location(size, location)
    split_rects = _split_rect_by_opening(source_rect, occupancy_exclusion_bounds)
    for split_suffix, split_rect in split_rects:
        split_slab = _rect_to_size_center(split_rect, z=float(location[2]), thickness=float(size[2]))
        if split_slab is None:
            continue
        split_size, split_location = split_slab
        split_name = name if split_suffix == "Main" else f"{name}_Occ_{split_suffix}"
        _register_shell_fragment(
            occupancy_author,
            size=split_size,
            location=split_location,
            normal_axis=_normal_axis_for_side_key(side_key),
            material=material,
            source_bucket="Section_Walls_Exterior",
            source_name=split_name,
        )


def _emit_shell_slab(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    collection,
    parent,
    material,
    *,
    side_key: str,
    floor_index: int,
    roof_exit_shell: bool = False,
    occupancy_author: OccupancyAuthoringSession | None = None,
    occupancy_exclusion_bounds: tuple[float, float, float, float] | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    _register_shell_slab_fragments(
        occupancy_author,
        name=name,
        size=size,
        location=location,
        side_key=side_key,
        material=material,
        occupancy_exclusion_bounds=occupancy_exclusion_bounds,
    )
    shell_obj = _create_box(name, size, location, collection, parent, material)
    if shell_obj is not None:
        shell_obj = _mark_generated(shell_obj, tbg_preserved_exterior_shell=True)
        if roof_exit_shell:
            shell_obj = _mark_generated(shell_obj, tbg_roof_exit_shell=True)
            if runtime_emitter is not None:
                runtime_emitter.emit_box(
                    role=ROLE_ROOF_EXIT_SHELL,
                    size=size,
                    location=location,
                    source_name=shell_obj.name,
                    metadata_values={"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)},
                )
            return _mark_section(
                shell_obj,
                "Section_Walls_Exterior",
                merge_allowed=False,
                hide_with_walls=True,
            )
        else:
            _emit_shell_marker_box(
                runtime_emitter,
                size=size,
                location=location,
                source_name=shell_obj.name,
                side_key=side_key,
                floor_index=floor_index,
            )
    return _mark_wall_section(shell_obj, "Section_Walls_Exterior")


def _emit_shell_slabs(
    prefix: str,
    *,
    slab_specs: list[tuple[str, tuple[float, float, float], tuple[float, float, float], str]],
    collection,
    parent,
    material,
    floor_index: int,
    occupancy_author: OccupancyAuthoringSession | None = None,
    occupancy_exclusion_bounds: tuple[float, float, float, float] | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    emitted = []
    for suffix, size, location, side_key in slab_specs:
        emitted.append(
            _emit_shell_slab(
                _name(prefix, suffix),
                size=size,
                location=location,
                collection=collection,
                parent=parent,
                material=material,
                side_key=side_key,
                floor_index=floor_index,
                occupancy_author=occupancy_author,
                occupancy_exclusion_bounds=occupancy_exclusion_bounds,
                runtime_emitter=runtime_emitter,
            )
        )
    return emitted


def _emit_tagged_composite_section(
    name: str,
    *,
    parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    collection,
    parent,
    material,
    bucket: str,
    tag: str,
    hide_with_walls: bool = False,
):
    if not parts:
        return None
    obj = _create_composite_box_object(name, parts, (0.0, 0.0, 0.0), collection, parent, material)
    return _mark_section(
        _mark_generated(obj, **{tag: True}),
        bucket,
        merge_allowed=False,
        hide_with_walls=hide_with_walls,
    )


def _create_profile_prism_object(
    name: str,
    *,
    profile: list[tuple[float, float]],
    depth: float,
    axis: str,
    location: tuple[float, float, float],
    collection,
    parent,
    material,
    bucket: str,
    caps: bool = True,
):
    if depth <= 1e-4 or len(profile) < 3:
        return None

    half_depth = depth / 2
    verts: list[tuple[float, float, float]] = []
    for axis_coord in (-half_depth, half_depth):
        for lateral_coord, z_coord in profile:
            if axis == "X":
                verts.append((axis_coord, lateral_coord, z_coord))
            else:
                verts.append((lateral_coord, axis_coord, z_coord))

    count = len(profile)
    faces: list[tuple[int, ...]] = []
    for index in range(count):
        next_index = (index + 1) % count
        faces.append((index, next_index, count + next_index, count + index))
    if caps:
        faces.append(tuple(range(count)))
        faces.append(tuple(range(count * 2 - 1, count - 1, -1)))

    mesh = _mesh_from_pydata(name, verts, faces, recalc_normals=True)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    _parent_to(obj, parent)
    obj.location = Vector(location)
    obj.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    _assign_material(obj, material)
    return _mark_wall_section(obj, bucket)


def _profile_shell_fragment_specs(
    *,
    profile: list[tuple[float, float]],
    depth: float,
    axis: str,
    location: tuple[float, float, float],
    opening_lateral_span: tuple[float, float] | None = None,
    opening_base_z: float | None = None,
    opening_height: float | None = None,
) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    if depth <= 1e-4 or len(profile) < 2:
        return []
    base_z = min(float(point[1]) for point in profile)
    profile_min = min(float(point[0]) for point in profile)
    profile_max = max(float(point[0]) for point in profile)
    aperture_enabled = (
        opening_lateral_span is not None
        and opening_base_z is not None
        and opening_height is not None
        and float(opening_height) > 1e-4
    )
    if aperture_enabled:
        opening_min, opening_max = sorted((float(opening_lateral_span[0]), float(opening_lateral_span[1])))
        opening_min = max(profile_min, opening_min)
        opening_max = min(profile_max, opening_max)
        if opening_max - opening_min <= 1e-4:
            aperture_enabled = False
        opening_top_z = float(opening_base_z) + float(opening_height)
    else:
        opening_min = opening_max = 0.0
        opening_top_z = base_z

    cell_span = max(0.1, float(VOXEL_SIZE_STUDS))
    raw_knots = [profile_min, profile_max]
    raw_knots.extend(float(point[0]) for point in profile if profile_min < float(point[0]) < profile_max)
    lateral = profile_min + cell_span
    while lateral < profile_max - 1e-5:
        raw_knots.append(lateral)
        lateral += cell_span
    if aperture_enabled:
        raw_knots.extend((opening_min, opening_max))
    knots = sorted(raw_knots)
    deduped_knots: list[float] = []
    for knot in knots:
        if not deduped_knots or abs(knot - deduped_knots[-1]) > 1e-5:
            deduped_knots.append(knot)

    fragment_specs: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for segment_start, segment_end in zip(deduped_knots, deduped_knots[1:]):
        segment_width = float(segment_end - segment_start)
        if segment_width <= 1e-4:
            continue
        segment_mid = (segment_start + segment_end) / 2
        top_samples: list[float | None] = [_profile_top_z_at_lateral(profile, segment_mid)]
        if segment_start > profile_min + 1e-5:
            top_samples.append(_profile_top_z_at_lateral(profile, segment_start))
        if segment_end < profile_max - 1e-5:
            top_samples.append(_profile_top_z_at_lateral(profile, segment_end))
        top_values = [float(value) for value in top_samples if value is not None]
        if not top_values:
            continue
        segment_top_z = min(top_values)
        if segment_top_z <= base_z + 1e-4:
            continue
        segment_base_z = base_z
        if aperture_enabled and opening_min <= segment_mid <= opening_max:
            segment_base_z = max(segment_base_z, min(opening_top_z, segment_top_z))
        segment_height = float(segment_top_z - segment_base_z)
        if segment_height <= 1e-4:
            continue
        if axis == "X":
            fragment_specs.append(
                (
                    (float(depth), segment_width, segment_height),
                    (
                        float(location[0]),
                        float(location[1] + segment_mid),
                        float(segment_base_z + segment_height / 2),
                    ),
                )
            )
        else:
            fragment_specs.append(
                (
                    (segment_width, float(depth), segment_height),
                    (
                        float(location[0] + segment_mid),
                        float(location[1]),
                        float(segment_base_z + segment_height / 2),
                    ),
                )
            )
    return fragment_specs


def _emit_shell_closure(
    name: str,
    *,
    profile: list[tuple[float, float]],
    depth: float,
    axis: str,
    location: tuple[float, float, float],
    collection,
    parent,
    material,
    side_key: str,
    marker_size: tuple[float, float, float],
    marker_center_z: float,
    floor_index: int,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    _register_profile_shell_plane(
        occupancy_author,
        name=name,
        profile=profile,
        depth=depth,
        axis=axis,
        location=location,
        material=material,
        source_bucket="Section_Walls_Exterior",
    )
    closure = _create_profile_prism_object(
        name,
        profile=profile,
        depth=depth,
        axis=axis,
        location=location,
        collection=collection,
        parent=parent,
        material=material,
        bucket="Section_Walls_Roof",
    )
    if closure is not None:
        closure = _mark_generated(closure, tbg_preserved_exterior_shell=True)
    _emit_shell_markers(
        runtime_emitter,
        marker_specs=[
            (
                marker_size,
                (float(location[0]), float(location[1]), float(marker_center_z)),
                closure.name if closure is not None else name,
                side_key,
            )
        ],
        floor_index=floor_index,
    )
    return closure


def _profile_top_z_at_lateral(
    profile: list[tuple[float, float]],
    lateral: float,
    *,
    epsilon: float = 1e-5,
) -> float | None:
    if not profile:
        return None
    candidates: list[float] = []
    count = len(profile)
    for index in range(count):
        lat_a, z_a = profile[index]
        lat_b, z_b = profile[(index + 1) % count]
        lat_a = float(lat_a)
        lat_b = float(lat_b)
        z_a = float(z_a)
        z_b = float(z_b)
        seg_min = min(lat_a, lat_b)
        seg_max = max(lat_a, lat_b)
        if float(lateral) < seg_min - epsilon or float(lateral) > seg_max + epsilon:
            continue
        if abs(lat_b - lat_a) <= epsilon:
            if abs(float(lateral) - lat_a) <= epsilon:
                candidates.append(max(z_a, z_b))
            continue
        t = (float(lateral) - lat_a) / (lat_b - lat_a)
        if -epsilon <= t <= 1.0 + epsilon:
            candidates.append(z_a + (z_b - z_a) * t)
    if not candidates:
        return None
    return max(candidates)


def _clamped_aperture_height(
    *,
    profile: list[tuple[float, float]],
    opening_lateral_span: tuple[float, float] | None,
    opening_base_z: float,
    requested_height: float,
    head_clearance: float = 0.08,
    minimum_height: float = 0.72,
) -> float | None:
    if opening_lateral_span is None:
        return None
    opening_min, opening_max = sorted((float(opening_lateral_span[0]), float(opening_lateral_span[1])))
    lateral_samples = (opening_min, (opening_min + opening_max) / 2, opening_max)
    top_values = [
        float(value)
        for value in (_profile_top_z_at_lateral(profile, sample) for sample in lateral_samples)
        if value is not None
    ]
    if not top_values:
        return None
    available_height = min(top_values) - float(opening_base_z) - float(head_clearance)
    if available_height <= minimum_height:
        return None
    return min(float(requested_height), float(available_height))


_APERTURE_SCRATCH_COLLECTION_NAME = "TBG_ApertureScratch"


def _aperture_scratch_collection(fallback_collection):
    scene = getattr(bpy.context, "scene", None)
    scene_collection = getattr(scene, "collection", None) if scene is not None else None
    if scene_collection is None:
        return fallback_collection
    scratch = bpy.data.collections.get(_APERTURE_SCRATCH_COLLECTION_NAME)
    if scratch is None:
        scratch = bpy.data.collections.new(_APERTURE_SCRATCH_COLLECTION_NAME)
    if scratch.name not in [child.name for child in scene_collection.children]:
        scene_collection.children.link(scratch)
    return scratch


def _emit_shell_closure_with_aperture(
    name: str,
    *,
    profile: list[tuple[float, float]],
    depth: float,
    axis: str,
    location: tuple[float, float, float],
    collection,
    parent,
    material,
    side_key: str,
    floor_index: int,
    opening_lateral_span: tuple[float, float],
    opening_base_z: float,
    opening_height: float,
    marker_size: tuple[float, float, float],
    marker_center_z: float,
    opening_clearance_studs: float = OPENING_VISUAL_CLEARANCE_STUDS,
    roof_exit_shell: bool = False,
    frame_material=None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    fragment_specs = _profile_shell_fragment_specs(
        profile=profile,
        depth=depth,
        axis=axis,
        location=location,
        opening_lateral_span=opening_lateral_span,
        opening_base_z=opening_base_z,
        opening_height=opening_height,
    )
    roof_exit_marker_specs: list[tuple[tuple[float, float, float], tuple[float, float, float]]] | None = list(fragment_specs)
    _register_profile_shell_plane(
        occupancy_author,
        name=name,
        profile=profile,
        depth=depth,
        axis=axis,
        location=location,
        material=material,
        source_bucket="Section_Walls_Exterior",
        opening_lateral_span=opening_lateral_span,
        opening_base_z=opening_base_z,
        opening_height=opening_height,
        opening_clearance_studs=opening_clearance_studs,
    )

    def _build_profile_prism(
        profile_points: list[tuple[float, float]] | None = None,
        *,
        build_collection=None,
        build_parent=None,
    ):
        resolved_profile = profile if profile_points is None else profile_points
        half_depth = depth / 2
        verts: list[tuple[float, float, float]] = []
        for axis_coord in (-half_depth, half_depth):
            for lateral_coord, z_coord in resolved_profile:
                if axis == "X":
                    verts.append((axis_coord, lateral_coord, z_coord))
                else:
                    verts.append((lateral_coord, axis_coord, z_coord))

        count = len(resolved_profile)
        faces: list[tuple[int, ...]] = []
        for index in range(count):
            next_index = (index + 1) % count
            faces.append((index, next_index, count + next_index, count + index))
        faces.append(tuple(range(count)))
        faces.append(tuple(range(count * 2 - 1, count - 1, -1)))

        mesh = _mesh_from_pydata(name, verts, faces, recalc_normals=True)
        obj = bpy.data.objects.new(name, mesh)
        resolved_collection = collection if build_collection is None else build_collection
        resolved_parent = parent if build_parent is None else build_parent
        resolved_collection.objects.link(obj)
        _parent_to(obj, resolved_parent)
        obj.location = Vector(location)
        obj.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
        _assign_material(obj, material)
        return obj

    def _mark_closure_object(obj):
        source_name = obj.name if obj is not None else name
        marker_location = (float(location[0]), float(location[1]), float(marker_center_z))
        marker_metadata = {"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)}
        if obj is not None:
            obj = _mark_generated(obj, tbg_preserved_exterior_shell=True)
        _emit_shell_marker_box(
            runtime_emitter,
            size=marker_size,
            location=marker_location,
            source_name=source_name,
            side_key=side_key,
            floor_index=floor_index,
        )
        if roof_exit_shell:
            if obj is not None:
                obj = _mark_generated(obj, tbg_roof_exit_shell=True)
            for exit_marker_size, exit_marker_location in roof_exit_marker_specs or ((marker_size, marker_location),):
                if runtime_emitter is None:
                    continue
                runtime_emitter.emit_box(
                    role=ROLE_ROOF_EXIT_SHELL,
                    size=exit_marker_size,
                    location=exit_marker_location,
                    source_name=source_name,
                    metadata_values=marker_metadata,
                )
            return _mark_section(
                obj,
                "Section_Walls_Roof",
                merge_allowed=False,
                hide_with_walls=True,
            )
        return _mark_wall_section(obj, "Section_Walls_Roof")

    def _emit_full_shell():
        return _mark_closure_object(_build_profile_prism())

    def _emit_attic_opening_marker(
        span_start: float,
        span_end: float,
        *,
        source_name: str,
    ) -> None:
        if runtime_emitter is None:
            return
        opening_min, opening_max = sorted((float(span_start), float(span_end)))
        opening_width = float(opening_max - opening_min)
        opening_height_value = float(opening_height)
        if opening_width <= 1e-4 or opening_height_value <= 1e-4:
            return
        along_coord = (opening_min + opening_max) / 2
        marker_metadata = {"tbg_runtime_side": side_key, "tbg_runtime_floor": int(floor_index)}
        if axis == "X":
            marker_size = (float(depth), opening_width, opening_height_value)
            marker_location = (
                float(location[0]),
                float(location[1] + along_coord),
                float(opening_base_z + opening_height_value / 2),
            )
        else:
            marker_size = (opening_width, float(depth), opening_height_value)
            marker_location = (
                float(location[0] + along_coord),
                float(location[1]),
                float(opening_base_z + opening_height_value / 2),
            )
        runtime_emitter.emit_box(
            role=ROLE_ATTIC_OPENING,
            size=marker_size,
            location=marker_location,
            source_name=source_name,
            collidable=False,
            metadata_values=marker_metadata,
        )

    def _profile_contour_between(span_start: float, span_end: float) -> list[tuple[float, float]]:
        raw_knots = [float(span_start), float(span_end)]
        raw_knots.extend(
            float(point[0]) for point in profile if float(span_start) < float(point[0]) < float(span_end)
        )
        contour: list[tuple[float, float]] = []
        for knot in sorted(raw_knots):
            top_z = _profile_top_z_at_lateral(profile, knot)
            if top_z is None:
                continue
            point = (float(knot), float(top_z))
            if contour and abs(point[0] - contour[-1][0]) <= 1e-5 and abs(point[1] - contour[-1][1]) <= 1e-5:
                continue
            contour.append(point)
        return contour

    def _clean_profile_polygon(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        cleaned: list[tuple[float, float]] = []
        for point in points:
            resolved = (float(point[0]), float(point[1]))
            if cleaned and abs(resolved[0] - cleaned[-1][0]) <= 1e-5 and abs(resolved[1] - cleaned[-1][1]) <= 1e-5:
                continue
            cleaned.append(resolved)
        if len(cleaned) >= 2 and abs(cleaned[0][0] - cleaned[-1][0]) <= 1e-5 and abs(cleaned[0][1] - cleaned[-1][1]) <= 1e-5:
            cleaned.pop()
        return cleaned

    def _append_profile_prism_piece(
        verts: list[tuple[float, float, float]],
        faces: list[tuple[int, ...]],
        profile_points: list[tuple[float, float]],
    ) -> None:
        resolved_profile = _clean_profile_polygon(profile_points)
        if len(resolved_profile) < 3:
            return
        half_depth = depth / 2
        vert_offset = len(verts)
        for axis_coord in (-half_depth, half_depth):
            for lateral_coord, z_coord in resolved_profile:
                if axis == "X":
                    verts.append((axis_coord, lateral_coord, z_coord))
                else:
                    verts.append((lateral_coord, axis_coord, z_coord))
        count = len(resolved_profile)
        for index in range(count):
            next_index = (index + 1) % count
            faces.append(
                (
                    vert_offset + index,
                    vert_offset + next_index,
                    vert_offset + count + next_index,
                    vert_offset + count + index,
                )
            )
        faces.append(tuple(vert_offset + index for index in range(count)))
        faces.append(tuple(vert_offset + index for index in range(count * 2 - 1, count - 1, -1)))

    if depth <= 1e-4 or len(profile) < 3 or float(opening_height) <= 1e-4:
        return _emit_full_shell()

    profile_min = min(float(point[0]) for point in profile)
    profile_max = max(float(point[0]) for point in profile)
    opening_min, opening_max = sorted((float(opening_lateral_span[0]), float(opening_lateral_span[1])))
    opening_min = max(profile_min, opening_min)
    opening_max = min(profile_max, opening_max)
    if opening_max - opening_min <= 1e-4:
        return _emit_full_shell()

    base_z = min(float(point[1]) for point in profile)
    opening_top_z = float(opening_base_z + opening_height)
    if opening_top_z <= base_z + 1e-4:
        return _emit_full_shell()

    raw_knots = [profile_min, profile_max, opening_min, opening_max]
    raw_knots.extend(float(point[0]) for point in profile if profile_min < float(point[0]) < profile_max)
    knots = sorted(raw_knots)
    deduped_knots: list[float] = []
    for knot in knots:
        if not deduped_knots or abs(knot - deduped_knots[-1]) > 1e-5:
            deduped_knots.append(knot)
    piece_profiles: list[list[tuple[float, float]]] = []
    if opening_min - profile_min > 1e-4:
        left_contour = _profile_contour_between(profile_min, opening_min)
        piece_profiles.append([(float(profile_min), float(base_z)), *left_contour, (float(opening_min), float(base_z))])
    if profile_max - opening_max > 1e-4:
        right_contour = _profile_contour_between(opening_max, profile_max)
        piece_profiles.append([(float(opening_max), float(base_z)), *right_contour, (float(profile_max), float(base_z))])
    if opening_base_z - base_z > 1e-4:
        piece_profiles.append(
            [
                (float(opening_min), float(base_z)),
                (float(opening_min), float(opening_base_z)),
                (float(opening_max), float(opening_base_z)),
                (float(opening_max), float(base_z)),
            ]
        )
    head_contour = _profile_contour_between(opening_min, opening_max)
    if head_contour:
        head_piece_top = min(float(point[1]) for point in head_contour)
        if head_piece_top - opening_top_z > 1e-4:
            piece_profiles.append(
                [
                    (float(opening_min), float(opening_top_z)),
                    *head_contour,
                    (float(opening_max), float(opening_top_z)),
                ]
            )

    closure_verts: list[tuple[float, float, float]] = []
    closure_faces: list[tuple[int, ...]] = []
    for piece_profile in piece_profiles:
        _append_profile_prism_piece(closure_verts, closure_faces, piece_profile)

    if len(closure_verts) < 6 or not closure_faces:
        return _emit_full_shell()

    apertured_mesh = _mesh_from_pydata(name, closure_verts, closure_faces, recalc_normals=True)
    apertured_obj = bpy.data.objects.new(name, apertured_mesh)
    collection.objects.link(apertured_obj)
    _parent_to(apertured_obj, parent)
    apertured_obj.location = Vector(location)
    apertured_obj.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    _assign_material(apertured_obj, material)
    _build_sloped_attic_window_frame(
        f"{name}_Frame",
        axis=axis,
        side_key=side_key,
        location=location,
        wall_depth=depth,
        opening_lateral_span=(opening_min, opening_max),
        opening_base_z=opening_base_z,
        opening_height=float(opening_top_z - opening_base_z),
        wall_base_z=base_z,
        floor_index=floor_index,
        opening_clearance_studs=opening_clearance_studs,
        collection=collection,
        parent=parent,
        material=frame_material,
    )
    _emit_attic_opening_marker(opening_min, opening_max, source_name=name)
    return _mark_closure_object(apertured_obj)


def _emit_top_floor_closeout(
    prefix: str,
    *,
    spec,
    collection,
    parent,
    material,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    footprint_rect: tuple[float, float, float, float] | None = None,
    cutout_rect: tuple[float, float, float, float] | None = None,
):
    spatial_plan = _spatial_plan(spec)
    if str(getattr(spatial_plan, "top_terminal_mode", "")).upper() != TOP_TERMINAL_TOP_FLOOR_ONLY:
        return None
    top_floor_index = max(0, int(spec.floor_count) - 1)
    if footprint_rect is None:
        x0, x1, y0, y1 = spatial_plan.floors[top_floor_index].footprint
    else:
        x0, x1, y0, y1 = footprint_rect
    width = float(x1 - x0)
    depth = float(y1 - y0)
    if width <= 1e-4 or depth <= 1e-4:
        return None
    runtime_closeout_z = float(_slab_center_z(_roof_surface_z(spec), spec.slab_thickness))
    authored_inset = max(0.0, float(spec.wall_thickness))
    closeout_x0 = min(x1, x0 + authored_inset)
    closeout_x1 = max(closeout_x0, x1 - authored_inset)
    closeout_y0 = min(y1, y0 + authored_inset)
    authored_rect = (float(closeout_x0), float(closeout_x1), float(closeout_y0), float(y1))
    closeout_rects = _split_rect_by_opening(authored_rect, cutout_rect)
    emitted = []
    for suffix, closeout_rect in closeout_rects:
        rect_info = _rect_to_size_center(closeout_rect, z=runtime_closeout_z, thickness=float(spec.slab_thickness))
        if rect_info is None:
            continue
        closeout_size, closeout_location = rect_info
        closeout = _create_box(
            _name(prefix, "TopFloor_Closeout" if suffix == "Main" else f"TopFloor_Closeout_{suffix}"),
            closeout_size,
            closeout_location,
            collection,
            parent,
            material,
        )
        closeout = _mark_section(closeout, "Section_Floors")
        emitted.append(closeout)
        if runtime_emitter is not None and closeout is not None:
            runtime_emitter.emit_box(
                role=ROLE_FLOOR_BLOCKER,
                size=closeout_size,
                location=closeout_location,
                source_name=closeout.name,
                metadata_values={"tbg_runtime_floor": int(spec.floor_count)},
            )
    return emitted[0] if emitted else None


def _rect_to_size_center(rect: tuple[float, float, float, float], *, z: float, thickness: float):
    x0, x1, y0, y1 = rect
    width = float(x1 - x0)
    depth = float(y1 - y0)
    if width <= 1e-4 or depth <= 1e-4:
        return None
    return (width, depth, float(thickness)), (float((x0 + x1) / 2), float((y0 + y1) / 2), float(z))


def _top_mass_rect(spec) -> tuple[object, tuple[float, float, float, float], tuple[float, float, float, float]]:
    spatial_plan = _spatial_plan(spec)
    full_rect = (-spec.width / 2, spec.width / 2, -spec.depth / 2, spec.depth / 2)
    top_floor_index = max(0, int(spec.floor_count) - 1)
    top_floor_rect = full_rect
    floors = tuple(getattr(spatial_plan, "floors", ()) or ())
    if 0 <= top_floor_index < len(floors):
        top_floor_rect = tuple(float(value) for value in floors[top_floor_index].footprint)
    transition_floor_index = spatial_plan.transition_floor_index
    upper_shell_rect = spatial_plan.upper_shell_rect
    roof_rect = top_floor_rect
    if transition_floor_index is not None and upper_shell_rect is not None:
        roof_rect = tuple(float(value) for value in upper_shell_rect)
    if roof_rect[1] - roof_rect[0] <= 1e-4 or roof_rect[3] - roof_rect[2] <= 1e-4:
        roof_rect = full_rect
    return spatial_plan, roof_rect, full_rect


def _sloped_roof_rect_with_terrace_clearance(
    roof_rect: tuple[float, float, float, float],
    *,
    spatial_plan,
    clearance: float = 0.02,
) -> tuple[float, float, float, float]:
    trimmed = [float(value) for value in roof_rect]
    for side in tuple(getattr(spatial_plan, "terrace_open_sides", ()) or ()):
        if side == "front":
            trimmed[2] += clearance
        elif side == "back":
            trimmed[3] -= clearance
        elif side == "left":
            trimmed[0] += clearance
        elif side == "right":
            trimmed[1] -= clearance
    if trimmed[1] - trimmed[0] <= 1e-4 or trimmed[3] - trimmed[2] <= 1e-4:
        return tuple(float(value) for value in roof_rect)
    return tuple(trimmed)


def _gable_ridge_rise(spec, *, slope_span: float, hangar_frontage: bool) -> float:
    if hangar_frontage:
        return max(1.2, min(2.05, slope_span * 0.1 + spec.parapet_height * 0.2))
    ridge_rise = max(1.1, min(spec.floor_height * 0.95, slope_span * 0.34 + spec.parapet_height * 0.35))
    if str(getattr(spec, "preset_id", "")).lower() in {"wood_house", "wood_rowhouse"}:
        ridge_rise = max(
            ridge_rise,
            min(max(1.2, min(spec.width, spec.depth) * 0.2), max(1.2, spec.floor_height * 1.35)),
        )
    return ridge_rise


def _sloped_shell_cross_section(*, slope_run: float, rise: float, shell_thickness: float) -> dict[str, float]:
    pitch = math.atan2(float(rise), float(slope_run))
    cos_p = max(math.cos(pitch), 1e-3)
    axial_half_thickness = float(shell_thickness) * 0.5
    vertical_half_thickness = axial_half_thickness / cos_p
    return {
        "pitch": pitch,
        "vertical_half_thickness": vertical_half_thickness,
        "axial_half_thickness": axial_half_thickness,
    }


def _sloped_roof_shell_length(*, slope_run: float, rise: float, shell_thickness: float) -> float:
    xs = _sloped_shell_cross_section(
        slope_run=slope_run,
        rise=rise,
        shell_thickness=shell_thickness,
    )
    return math.hypot(float(slope_run), float(rise)) + xs["axial_half_thickness"] * 2.0


def _roof_underside_z_at_local_xy(roof_obj, *, local_x: float, local_y: float) -> float | None:
    if roof_obj is None or getattr(roof_obj, "type", None) != "MESH":
        return None
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = roof_obj.evaluated_get(depsgraph)
        matrix_local = eval_obj.matrix_local.copy()
        inverse_matrix = matrix_local.inverted()
        bbox = [matrix_local @ Vector(corner) for corner in eval_obj.bound_box]
        z_min = min(v.z for v in bbox) - 0.25
        z_max = max(v.z for v in bbox) + 0.25
        origin = Vector((float(local_x), float(local_y), float(z_min)))
        target = Vector((float(local_x), float(local_y), float(z_max)))
        ray_origin = inverse_matrix @ origin
        ray_target = inverse_matrix @ target
        ray_vector = ray_target - ray_origin
        ray_length = ray_vector.length
        if ray_length <= 1e-6:
            return None
        hit, location, _normal, _index = eval_obj.ray_cast(ray_origin, ray_vector.normalized(), distance=ray_length + 0.5)
        if not hit:
            return None
        return float((matrix_local @ location).z)
    except Exception:
        return None


def _sloped_end_closure_spec(
    *,
    axis: str,
    side_key: str,
    roof_rect: tuple[float, float, float, float],
    roof_center: tuple[float, float],
    shell_depth: float,
    overhang: float,
    span: float,
    height: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    roof_x0, roof_x1, roof_y0, roof_y1 = (float(value) for value in roof_rect)
    roof_center_x, roof_center_y = (float(roof_center[0]), float(roof_center[1]))
    closure_depth = float(shell_depth) + float(overhang)
    closure_shift = float(overhang) * 0.5
    if axis == "X":
        if side_key == "left":
            center = (roof_x0 + shell_depth / 2 - closure_shift, roof_center_y, 0.0)
        else:
            center = (roof_x1 - shell_depth / 2 + closure_shift, roof_center_y, 0.0)
        marker_size = (closure_depth, float(span), float(height))
    else:
        if side_key == "front":
            center = (roof_center_x, roof_y0 + shell_depth / 2 - closure_shift, 0.0)
        else:
            center = (roof_center_x, roof_y1 - shell_depth / 2 + closure_shift, 0.0)
        marker_size = (float(span), closure_depth, float(height))
    return center, marker_size, closure_depth


def _terrace_side_strip_rect(
    full_rect: tuple[float, float, float, float],
    upper_shell_rect: tuple[float, float, float, float],
    side_key: str,
) -> tuple[float, float, float, float] | None:
    full_x0, full_x1, full_y0, full_y1 = full_rect
    shell_x0, shell_x1, shell_y0, shell_y1 = upper_shell_rect
    if side_key == "front":
        return (full_x0, full_x1, full_y0, shell_y0)
    if side_key == "back":
        return (full_x0, full_x1, shell_y1, full_y1)
    if side_key == "left":
        return (full_x0, shell_x0, shell_y0, shell_y1)
    if side_key == "right":
        return (shell_x1, full_x1, shell_y0, shell_y1)
    return None


def _split_rect_by_opening(
    rect: tuple[float, float, float, float],
    opening_bounds: tuple[float, float, float, float] | None,
) -> list[tuple[str, tuple[float, float, float, float]]]:
    if opening_bounds is None:
        return [("Main", rect)]
    x0, x1, y0, y1 = rect
    open_x0 = max(float(x0), float(opening_bounds[0]))
    open_x1 = min(float(x1), float(opening_bounds[1]))
    open_y0 = max(float(y0), float(opening_bounds[2]))
    open_y1 = min(float(y1), float(opening_bounds[3]))
    if open_x1 - open_x0 <= 1e-4 or open_y1 - open_y0 <= 1e-4:
        return [("Main", rect)]
    if (
        open_x0 <= float(x0) + 1e-4
        and open_x1 >= float(x1) - 1e-4
        and open_y0 <= float(y0) + 1e-4
        and open_y1 >= float(y1) - 1e-4
    ):
        return []
    slabs = [
        ("Left", (x0, open_x0, y0, y1)),
        ("Right", (open_x1, x1, y0, y1)),
        ("Front", (open_x0, open_x1, y0, open_y0)),
        ("Back", (open_x0, open_x1, open_y1, y1)),
    ]
    resolved = [item for item in slabs if item[1][1] - item[1][0] > 1e-4 and item[1][3] - item[1][2] > 1e-4]
    return resolved


def _resolve_attic_breach_side(
    *,
    end_sides: tuple[str, ...],
    preferred_side: str | None,
    opening_rect: tuple[float, float, float, float] | None,
    roof_rect: tuple[float, float, float, float],
) -> str | None:
    preferred = str(preferred_side or "").lower()
    if preferred in end_sides:
        return preferred
    if opening_rect is None:
        return None
    open_cx = (float(opening_rect[0]) + float(opening_rect[1])) / 2
    open_cy = (float(opening_rect[2]) + float(opening_rect[3])) / 2
    roof_x0, roof_x1, roof_y0, roof_y1 = (float(value) for value in roof_rect)
    side_distances = {
        "front": abs(open_cy - roof_y0),
        "back": abs(roof_y1 - open_cy),
        "left": abs(open_cx - roof_x0),
        "right": abs(roof_x1 - open_cx),
    }
    candidates = [side for side in end_sides if side in side_distances]
    if not candidates:
        return None
    return min(candidates, key=lambda side: side_distances[side])


def _opening_lateral_span_for_side(
    *,
    opening_rect: tuple[float, float, float, float] | None,
    axis: str,
    location: tuple[float, float, float],
) -> tuple[float, float] | None:
    if opening_rect is None:
        return None
    if axis == "X":
        return (
            float(opening_rect[2] - float(location[1])),
            float(opening_rect[3] - float(location[1])),
        )
    return (
        float(opening_rect[0] - float(location[0])),
        float(opening_rect[1] - float(location[0])),
    )


def _attic_combat_opening_span(
    *,
    spec,
    roof_room,
    axis: str,
    location: tuple[float, float, float],
) -> tuple[float, float] | None:
    if roof_room is None:
        return None
    x0, x1, y0, y1 = (float(value) for value in roof_room.footprint)
    minimum_span = max(0.88, float(getattr(spec, "stair_width", 0.0)) * 0.56, float(getattr(spec, "wall_thickness", 0.0)) * 4.0)
    maximum_span = max(minimum_span, min(1.42, float(getattr(spec, "floor_height", 0.0)) * 0.48))
    if axis == "X":
        center = (y0 + y1) / 2
        cross_span = min(y1 - y0, min(maximum_span, max(minimum_span, (y1 - y0) * 0.26)))
        opening_rect = (x0, x1, center - cross_span / 2, center + cross_span / 2)
    else:
        center = (x0 + x1) / 2
        cross_span = min(x1 - x0, min(maximum_span, max(minimum_span, (x1 - x0) * 0.26)))
        opening_rect = (center - cross_span / 2, center + cross_span / 2, y0, y1)
    return _opening_lateral_span_for_side(
        opening_rect=opening_rect,
        axis=axis,
        location=location,
    )


def _attic_combat_aperture_request(
    *,
    spec,
    roof_room,
    roof_base_z: float,
) -> tuple[float, float]:
    attic_base_z = float(getattr(roof_room, "base_z", roof_base_z))
    pocket_height = max(0.0, float(getattr(roof_room, "height", 0.0)))
    sill_height = max(0.72, min(0.98, pocket_height * 0.2, float(getattr(spec, "floor_height", 0.0)) * 0.28))
    requested_height = max(0.82, min(1.08, pocket_height * 0.42, float(getattr(spec, "floor_height", 0.0)) * 0.36))
    return attic_base_z + sill_height, requested_height


def _sloped_attic_window_span(
    *,
    spec,
    profile: list[tuple[float, float]],
    minimum_margin: float = 0.34,
) -> tuple[float, float] | None:
    if len(profile) < 3:
        return None
    profile_min = min(float(point[0]) for point in profile)
    profile_max = max(float(point[0]) for point in profile)
    span_total = float(profile_max - profile_min)
    if span_total <= minimum_margin * 2 + 0.2:
        return None
    max_width = 1.72 if _is_market_hall_frontage(spec) else 1.34
    target_width = max(0.94, min(max_width, span_total * 0.28))
    opening_width = min(target_width, span_total - minimum_margin * 2)
    if opening_width <= 0.24:
        return None
    center = (profile_min + profile_max) / 2
    return (center - opening_width / 2, center + opening_width / 2)


def _shed_highside_window_span(
    *,
    spec,
    span_total: float,
    minimum_margin: float = 0.42,
) -> tuple[float, float] | None:
    if float(span_total) <= minimum_margin * 2 + 0.2:
        return None
    max_width = 2.2 if _is_market_hall_frontage(spec) else 1.56
    target_width = max(1.14, min(max_width, float(span_total) * 0.34))
    opening_width = min(target_width, float(span_total) - minimum_margin * 2)
    if opening_width <= 0.24:
        return None
    return (-opening_width / 2, opening_width / 2)


def _build_sloped_attic_window_frame(
    name: str,
    *,
    axis: str,
    side_key: str,
    location: tuple[float, float, float],
    wall_depth: float,
    opening_lateral_span: tuple[float, float],
    opening_base_z: float,
    opening_height: float,
    wall_base_z: float,
    floor_index: int,
    collection,
    parent,
    material,
    opening_clearance_studs: float = OPENING_VISUAL_CLEARANCE_STUDS,
):
    opening_min, opening_max = sorted((float(opening_lateral_span[0]), float(opening_lateral_span[1])))
    opening_width = float(opening_max - opening_min)
    if material is None or opening_width <= 1e-4 or float(opening_height) <= 1e-4:
        return None
    trim_half = max(0.09, min(WINDOW_TRIM_WIDTH, opening_width * 0.12))
    outer_width = opening_width + trim_half * 2.15
    outer_height = float(opening_height) + trim_half * 1.92
    inner_width = max(0.18, opening_width - WINDOW_FRAME_OVERLAP)
    inner_height = max(0.18, float(opening_height) - WINDOW_FRAME_OVERLAP)
    frame_depth = max(0.03, float(wall_depth) + WINDOW_FRAME_PROUD_OFFSET + INNER_FRAME_PROUD_OFFSET)
    run_offset = float(location[1]) if axis == "X" else float(location[0])
    along_coord = float(run_offset + (opening_min + opening_max) / 2)
    wall_center = float(location[0] if axis == "X" else location[1])
    orientation = "Y" if axis == "X" else "X"
    opening_cut_metadata = _profile_opening_cut_metadata(
        kind="window",
        orientation=orientation,
        side_key=side_key,
        floor_index=int(floor_index),
        slot_index=-1,
        wall_pos=wall_center,
        cut_rect=(
            float(run_offset + opening_min),
            float(run_offset + opening_max),
            float(opening_base_z),
            float(opening_base_z + opening_height),
        ),
        clearance_studs=opening_clearance_studs,
    )
    cut_along_coord, frame_outer_width, frame_outer_height, frame_mid_z = _opening_cut_frame_envelope(
        opening_cut_metadata
    )
    if cut_along_coord is not None:
        along_coord = float(cut_along_coord)
    if frame_outer_width is not None:
        outer_width = float(frame_outer_width)
    if frame_outer_height is not None:
        outer_height = float(frame_outer_height)
    if frame_mid_z is not None:
        z_center = float(frame_mid_z)
    else:
        z_center = float(opening_base_z + opening_height / 2)
    min_ring = 0.06
    inner_width = min(inner_width, max(0.18, outer_width - min_ring * 2.0))
    inner_height = min(inner_height, max(0.18, outer_height - min_ring * 2.0))
    normal_coord = wall_center + _side_sign(side_key) * (WINDOW_FRAME_PROUD_OFFSET - INNER_FRAME_PROUD_OFFSET) / 2
    mesh = _frame_mesh(
        name,
        outer_width,
        frame_depth,
        outer_height,
        inner_width,
        inner_height,
        visible_positive_depth=side_key in {"back", "right"},
        include_inner_returns=True,
        double_sided=True,
    )
    frame = bpy.data.objects.new(name, mesh)
    collection.objects.link(frame)
    _parent_to(frame, parent)
    frame.location = Vector(
        _opening_location(
            orientation,
            along_coord,
            normal_coord,
            z_center,
        )
    )
    frame.rotation_euler = Euler(_orientation_rotation(orientation), "XYZ")
    _assign_material(frame, material)
    return _mark_section(
        _mark_generated(
            frame,
            tbg_attic_window_frame=True,
            tbg_window_frame_outer=True,
            tbg_facade_side=side_key,
            tbg_facade_floor=int(floor_index),
            tbg_facade_slot=-1,
            **opening_cut_metadata,
        ),
        "Section_Openings_Frame",
        merge_allowed=False,
    )


def _attic_cheek_height_from_profile(
    *,
    roof_profile: list[tuple[float, float]],
    lateral_value: float,
    base_z: float,
    fallback_height: float,
    roof_clearance: float = 0.06,
) -> float:
    top_z = _profile_top_z_at_lateral(roof_profile, lateral_value)
    if top_z is None:
        return float(fallback_height)
    return max(0.72, float(top_z) - float(base_z) - float(roof_clearance))


def _emit_attic_side_cheeks(
    prefix: str,
    *,
    spec,
    roof_room,
    roof_rect: tuple[float, float, float, float],
    axis: str,
    roof_profile: list[tuple[float, float]],
    roof_center: tuple[float, float],
    collection,
    parent,
    material,
    thickness: float,
    floor_index: int,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    roof_side_objects: dict[str, object] | None = None,
):
    if roof_room is None:
        return
    x0, x1, y0, y1 = (float(value) for value in roof_room.footprint)
    roof_x0, roof_x1, roof_y0, roof_y1 = (float(value) for value in roof_rect)
    base_z = float(roof_room.base_z) - float(getattr(spec, "slab_thickness", 0.0))
    thickness = max(float(thickness), max(float(getattr(spec, "wall_thickness", 0.0)), 0.14))
    roof_center_x, roof_center_y = (float(roof_center[0]), float(roof_center[1]))

    def _emit_eave_filler(
        suffix: str,
        *,
        side_key: str,
        inner_lateral: float,
        outer_lateral: float,
        span: float,
    ) -> None:
        if span <= 1e-4:
            return
        inner_top_z = _profile_top_z_at_lateral(roof_profile, inner_lateral)
        outer_top_z = _profile_top_z_at_lateral(roof_profile, outer_lateral)
        if inner_top_z is None or outer_top_z is None:
            return
        if inner_top_z <= base_z + 1e-4 and outer_top_z <= base_z + 1e-4:
            return
        filler = _create_profile_prism_object(
            _name(prefix, f"Roof_EaveFill_{suffix}"),
            profile=[
                (outer_lateral, base_z),
                (inner_lateral, base_z),
                (inner_lateral, float(inner_top_z)),
                (outer_lateral, float(outer_top_z)),
            ],
            depth=span,
            axis=axis,
            location=(roof_center_x, roof_center_y, 0.0),
            collection=collection,
            parent=parent,
            material=material,
            bucket="Section_Walls_Roof",
        )
        if filler is not None:
            _mark_generated(
                filler,
                tbg_preserved_exterior_shell=True,
                tbg_roof_eave_fill=True,
                tbg_facade_side=side_key,
            )

    if axis == "X":
        span = max(0.0, x1 - x0)
        _emit_eave_filler(
            "Front",
            side_key="front",
            inner_lateral=y0 + thickness - roof_center_y,
            outer_lateral=roof_y0 - roof_center_y,
            span=span,
        )
        _emit_eave_filler(
            "Back",
            side_key="back",
            inner_lateral=y1 - thickness - roof_center_y,
            outer_lateral=roof_y1 - roof_center_y,
            span=span,
        )
    else:
        span = max(0.0, y1 - y0)
        _emit_eave_filler(
            "Left",
            side_key="left",
            inner_lateral=x0 + thickness - roof_center_x,
            outer_lateral=roof_x0 - roof_center_x,
            span=span,
        )
        _emit_eave_filler(
            "Right",
            side_key="right",
            inner_lateral=x1 - thickness - roof_center_x,
            outer_lateral=roof_x1 - roof_center_x,
            span=span,
        )
    return


def _build_sloped_attic_open_package(
    prefix: str,
    *,
    roof_name: str,
    spec,
    roof_room,
    terminal_profile: str,
    attic_opening_rect: tuple[float, float, float, float] | None,
    roof_rect: tuple[float, float, float, float],
    axis: str,
    roof_profile: list[tuple[float, float]],
    end_specs: tuple[tuple[str, tuple[float, float, float], tuple[float, float, float], float], ...],
    shell_depth: float,
    roof_center: tuple[float, float],
    roof_base_z: float,
    marker_center_z: float,
    collection,
    parent,
    material,
    floor_index: int,
    frame_material=None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    roof_side_objects: dict[str, object] | None = None,
):
    attic_open_enabled = terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN and roof_room is not None
    attic_combat_base_z, attic_combat_height = _attic_combat_aperture_request(
        spec=spec,
        roof_room=roof_room,
        roof_base_z=roof_base_z,
    )

    for side_key, location, marker_size, closure_depth in end_specs:
        closure_name = _name(prefix, f"{roof_name}_End_{side_key.title()}")
        if attic_open_enabled:
            opening_lateral_span = _sloped_attic_window_span(
                spec=spec,
                profile=roof_profile,
            )
            opening_height = _clamped_aperture_height(
                profile=roof_profile,
                opening_lateral_span=opening_lateral_span,
                opening_base_z=attic_combat_base_z,
                requested_height=attic_combat_height,
                minimum_height=0.24,
            )
            if opening_lateral_span is not None and opening_height is not None:
                _emit_shell_closure_with_aperture(
                    closure_name,
                    profile=roof_profile,
                    depth=closure_depth,
                    axis=axis,
                    location=location,
                    collection=collection,
                    parent=parent,
                    material=material,
                    side_key=side_key,
                    floor_index=floor_index,
                    opening_lateral_span=opening_lateral_span,
                    opening_base_z=attic_combat_base_z,
                    opening_height=opening_height,
                    marker_size=marker_size,
                    marker_center_z=marker_center_z,
                    opening_clearance_studs=(
                        0.0
                        if str(getattr(spec, "preset_id", "")).lower() in {"wood_house", "wood_rowhouse"}
                        and str(roof_name) == "Roof_Gable"
                        and side_key in {"left", "right"}
                        else OPENING_VISUAL_CLEARANCE_STUDS
                    ),
                    roof_exit_shell=True,
                    frame_material=frame_material,
                    occupancy_author=occupancy_author,
                    runtime_emitter=runtime_emitter,
                )
                continue
        _emit_shell_closure(
            closure_name,
            profile=roof_profile,
            depth=closure_depth,
            axis=axis,
            location=location,
            collection=collection,
            parent=parent,
            material=material,
            side_key=side_key,
            marker_size=marker_size,
            marker_center_z=marker_center_z,
            floor_index=floor_index,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )

    if attic_open_enabled:
        _emit_attic_side_cheeks(
            prefix,
            spec=spec,
            roof_room=roof_room,
            roof_rect=roof_rect,
            axis=axis,
            roof_profile=roof_profile,
            roof_center=roof_center,
            collection=collection,
            parent=parent,
            material=material,
            thickness=shell_depth,
            floor_index=floor_index,
            runtime_emitter=runtime_emitter,
            roof_side_objects=roof_side_objects,
        )


def _emit_sloped_roof_blockers(
    runtime_emitter: RuntimeMarkerEmitter | None,
    *,
    roof_rect: tuple[float, float, float, float],
    bottom_z: float,
    height: float,
    source_name: str,
    opening_rect: tuple[float, float, float, float] | None = None,
):
    if runtime_emitter is None:
        return
    blocker_rects = _split_rect_by_opening(roof_rect, opening_rect)
    if not blocker_rects:
        return
    for suffix, blocker_rect in blocker_rects:
        x0, x1, y0, y1 = (float(value) for value in blocker_rect)
        width = x1 - x0
        depth = y1 - y0
        if width <= 1e-4 or depth <= 1e-4:
            continue
        blocker_name = source_name if suffix == "Main" else f"{source_name}_{suffix}"
        _emit_roof_blocker_volume(
            runtime_emitter,
            width=width,
            depth=depth,
            bottom_z=bottom_z,
            height=height,
            source_name=blocker_name,
            center_x=(x0 + x1) / 2,
            center_y=(y0 + y1) / 2,
        )


def _planner_roof_opening_rect(spatial_plan) -> tuple[float, float, float, float] | None:
    roof_room = getattr(spatial_plan, "roof_room", None)
    if roof_room is None:
        return None
    opening_rect = roof_room.opening_rect if roof_room.opening_rect is not None else roof_room.footprint
    x0, x1, y0, y1 = (float(opening_rect[0]), float(opening_rect[1]), float(opening_rect[2]), float(opening_rect[3]))
    if x1 - x0 <= 1e-4 or y1 - y0 <= 1e-4:
        return None
    return (x0, x1, y0, y1)


def _planner_flat_roof_cutout_rect(spatial_plan) -> tuple[float, float, float, float] | None:
    roof_room = getattr(spatial_plan, "roof_room", None)
    if roof_room is None:
        return None
    terminal_profile = str(getattr(roof_room, "terminal_profile", "")).upper()
    if terminal_profile in {TERMINAL_PROFILE_FULL_ROOM, TERMINAL_PROFILE_STAIR_HEAD}:
        cutout_rect = tuple(float(value) for value in roof_room.footprint)
        if cutout_rect[1] - cutout_rect[0] <= 1e-4 or cutout_rect[3] - cutout_rect[2] <= 1e-4:
            return None
        return cutout_rect
    return _planner_roof_opening_rect(spatial_plan)


def _inset_rect_for_open_sides(
    rect: tuple[float, float, float, float],
    *,
    open_sides: tuple[str, ...],
    inset: float,
) -> tuple[float, float, float, float]:
    inset_value = max(0.0, float(inset))
    if inset_value <= 1e-6:
        return rect
    x0, x1, y0, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    side_set = set(str(side).strip().lower() for side in open_sides)
    if "front" in side_set:
        y0 += inset_value
    if "back" in side_set:
        y1 -= inset_value
    if "left" in side_set:
        x0 += inset_value
    if "right" in side_set:
        x1 -= inset_value
    if x1 - x0 <= 1e-4 or y1 - y0 <= 1e-4:
        return rect
    return (x0, x1, y0, y1)


def _union_rect_2d(
    primary: tuple[float, float, float, float] | None,
    secondary: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    if primary is None:
        return secondary
    if secondary is None:
        return primary
    return (
        min(float(primary[0]), float(secondary[0])),
        max(float(primary[1]), float(secondary[1])),
        min(float(primary[2]), float(secondary[2])),
        max(float(primary[3]), float(secondary[3])),
    )


def _emit_terrace_transition_geometry(
    prefix,
    spec,
    *,
    spatial_plan,
    full_rect: tuple[float, float, float, float],
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
) -> bool:
    transition_floor_index = spatial_plan.transition_floor_index
    terrace_rect = spatial_plan.upper_shell_rect
    terrace_open_sides = tuple(spatial_plan.terrace_open_sides)
    terrace_enabled = transition_floor_index is not None and terrace_rect is not None and bool(terrace_open_sides)
    if not terrace_enabled:
        return False

    terrace_floor_index = int(transition_floor_index)
    terrace_z = _level_base_z(spec, terrace_floor_index)
    terrace_deck_t = max(0.05, min(0.12, spec.slab_thickness * 0.45))

    deck_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    deck_side_keys: list[str] = []
    for side_key in terrace_open_sides:
        strip_rect = _terrace_side_strip_rect(full_rect, terrace_rect, side_key)
        if strip_rect is None:
            continue
        deck_part = _rect_to_size_center(strip_rect, z=terrace_z + terrace_deck_t / 2, thickness=terrace_deck_t)
        if deck_part is None:
            continue
        deck_parts.append(deck_part)
        deck_side_keys.append(side_key)
    if deck_parts:
        deck_obj = _emit_tagged_composite_section(
            _name(prefix, "TerraceDeck"),
            parts=deck_parts,
            collection=collection,
            parent=parent,
            material=materials_map["floor"],
            bucket="Section_Floors",
            tag="tbg_terrace_deck",
        )
        if runtime_emitter is not None and deck_obj is not None:
            runtime_emitter.emit_composite_boxes(
                parts=deck_parts,
                base_location=(0.0, 0.0, 0.0),
                role=ROLE_FLOOR_BLOCKER,
                source_name=deck_obj.name,
                metadata_values={"tbg_runtime_floor": terrace_floor_index},
            )

    rail_z = terrace_z + BALCONY_RAIL_HEIGHT / 2
    rail_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    rail_side_keys: list[str] = []
    for side_key in terrace_open_sides:
        candidate_rects: list[tuple[str, tuple[float, float, float, float]]] = []
        if side_key == "front":
            candidate_rects.extend(
                (
                    ("front", (full_rect[0], full_rect[1], full_rect[2], full_rect[2] + BALCONY_RAIL_THICKNESS)),
                    ("left", (full_rect[0], full_rect[0] + BALCONY_RAIL_THICKNESS, full_rect[2], terrace_rect[2])),
                    ("right", (full_rect[1] - BALCONY_RAIL_THICKNESS, full_rect[1], full_rect[2], terrace_rect[2])),
                )
            )
        elif side_key == "back":
            candidate_rects.extend(
                (
                    ("back", (full_rect[0], full_rect[1], full_rect[3] - BALCONY_RAIL_THICKNESS, full_rect[3])),
                    ("left", (full_rect[0], full_rect[0] + BALCONY_RAIL_THICKNESS, terrace_rect[3], full_rect[3])),
                    ("right", (full_rect[1] - BALCONY_RAIL_THICKNESS, full_rect[1], terrace_rect[3], full_rect[3])),
                )
            )
        elif side_key == "left":
            candidate_rects.extend(
                (
                    ("left", (full_rect[0], full_rect[0] + BALCONY_RAIL_THICKNESS, full_rect[2], full_rect[3])),
                    ("front", (full_rect[0], terrace_rect[0], full_rect[2], full_rect[2] + BALCONY_RAIL_THICKNESS)),
                    ("back", (full_rect[0], terrace_rect[0], full_rect[3] - BALCONY_RAIL_THICKNESS, full_rect[3])),
                )
            )
        elif side_key == "right":
            candidate_rects.extend(
                (
                    ("right", (full_rect[1] - BALCONY_RAIL_THICKNESS, full_rect[1], full_rect[2], full_rect[3])),
                    ("front", (terrace_rect[1], full_rect[1], full_rect[2], full_rect[2] + BALCONY_RAIL_THICKNESS)),
                    ("back", (terrace_rect[1], full_rect[1], full_rect[3] - BALCONY_RAIL_THICKNESS, full_rect[3])),
                )
            )
        for rail_side_key, rail_rect in candidate_rects:
            rail_part = _rect_to_size_center(rail_rect, z=rail_z, thickness=BALCONY_RAIL_HEIGHT)
            if rail_part is None:
                continue
            if rail_part in rail_parts:
                continue
            rail_parts.append(rail_part)
            rail_side_keys.append(rail_side_key)
    if rail_parts:
        rail_obj = _emit_tagged_composite_section(
            _name(prefix, "TerraceRail"),
            parts=rail_parts,
            collection=collection,
            parent=parent,
            material=materials_map["frame"],
            bucket="Section_Walls_Trim",
            tag="tbg_terrace_rail",
            hide_with_walls=True,
        )
        if runtime_emitter is not None and rail_obj is not None:
            runtime_emitter.emit_composite_boxes(
                parts=rail_parts,
                base_location=(0.0, 0.0, 0.0),
                role=ROLE_BALCONY_RAIL,
                source_name=rail_obj.name,
                metadata_values={"tbg_runtime_floor": terrace_floor_index},
                per_part_metadata=[
                    {"tbg_runtime_side": side_key, "tbg_runtime_floor": terrace_floor_index}
                    for side_key in rail_side_keys
                ],
            )

    return True


def _build_flat_roof(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    roof_surface_z = _roof_surface_z(spec)
    preset_id = str(getattr(spec, "preset_id", "")).lower()
    wall_material = _wall_material_for_floor(materials_map, spec, max(0, spec.floor_count - 1))
    trim_material = _trim_material(
        materials_map,
        spec.facade_family,
        facade_mode=getattr(spec, "facade_mode", None),
    )
    spatial_plan, roof_shell_rect, full_rect = _top_mass_rect(spec)
    transition_floor_index = spatial_plan.transition_floor_index
    terrace_rect = spatial_plan.upper_shell_rect
    terrace_open_sides = tuple(spatial_plan.terrace_open_sides)
    terrace_enabled = transition_floor_index is not None and terrace_rect is not None and bool(terrace_open_sides)
    market_hall_frontage = _is_market_hall_frontage(spec)
    _emit_terrace_transition_geometry(
        prefix,
        spec,
        spatial_plan=spatial_plan,
        full_rect=full_rect,
        collection=collection,
        parent=parent,
        materials_map=materials_map,
        runtime_emitter=runtime_emitter,
    )

    roof_opening_bounds = _planner_flat_roof_cutout_rect(spatial_plan)
    if not bool(spec.stair_core.enabled):
        roof_opening_bounds = None
    roof_slab_rect = roof_shell_rect
    has_parapet = float(spec.parapet_height) > 1e-4
    roof_z = (
        _slab_center_z(roof_surface_z, spec.slab_thickness)
        if has_parapet
        else roof_surface_z + float(spec.slab_thickness) / 2
    )
    # Never shrink the slab source rect when a planner opening is present:
    # roof cutout must be cut from the exact planner-owned opening contract.
    if terrace_enabled and roof_opening_bounds is None:
        roof_slab_rect = _inset_rect_for_open_sides(
            roof_shell_rect,
            open_sides=terrace_open_sides,
            inset=max(0.006, min(0.024, float(spec.wall_thickness) * 0.08)),
        )
    roof_slabs = _split_rect_by_opening(roof_slab_rect, roof_opening_bounds)
    for suffix, rect in roof_slabs:
        slab = _rect_to_size_center(rect, z=roof_z, thickness=spec.slab_thickness)
        if slab is None:
            continue
        (width, depth, slab_t), (x, y, z) = slab
        _emit_roof_box(
            _name(prefix, "Roof_Main" if suffix == "Main" else f"Roof_{suffix}"),
            (width, depth, slab_t),
            (x, y, z),
            collection,
            parent,
            materials_map["roof"],
            runtime_emitter=runtime_emitter,
        )

    parapet_t = max(spec.wall_thickness * PARAPET_THICKNESS_SCALE, PARAPET_THICKNESS_MIN)
    roof_x0, roof_x1, roof_y0, roof_y1 = roof_shell_rect
    roof_width = max(0.01, roof_x1 - roof_x0)
    roof_depth = max(0.01, roof_y1 - roof_y0)
    side_parapet_span = max(0.01, roof_depth - parapet_t * 2.0)
    parapet_z = roof_surface_z + spec.parapet_height / 2
    roof_exit_wall_bounds = None
    roof_room = getattr(spatial_plan, "roof_room", None)
    if roof_room is not None:
        terminal_profile = str(getattr(roof_room, "terminal_profile", "")).upper()
        if terminal_profile in {TERMINAL_PROFILE_FULL_ROOM, TERMINAL_PROFILE_STAIR_HEAD}:
            footprint = tuple(float(value) for value in roof_room.footprint)
            if footprint[1] - footprint[0] > 1e-4 and footprint[3] - footprint[2] > 1e-4:
                roof_exit_wall_bounds = footprint
    if has_parapet:
        _emit_shell_slabs(
            prefix,
            slab_specs=[
                ("Parapet_Front", (roof_width, parapet_t, spec.parapet_height), ((roof_x0 + roof_x1) / 2, roof_y0 + parapet_t / 2, parapet_z), "front"),
                ("Parapet_Back", (roof_width, parapet_t, spec.parapet_height), ((roof_x0 + roof_x1) / 2, roof_y1 - parapet_t / 2, parapet_z), "back"),
                ("Parapet_Left", (parapet_t, side_parapet_span, spec.parapet_height), (roof_x0 + parapet_t / 2, (roof_y0 + roof_y1) / 2, parapet_z), "left"),
                ("Parapet_Right", (parapet_t, side_parapet_span, spec.parapet_height), (roof_x1 - parapet_t / 2, (roof_y0 + roof_y1) / 2, parapet_z), "right"),
            ],
            collection=collection,
            parent=parent,
            material=wall_material,
            floor_index=spec.floor_count,
            occupancy_author=occupancy_author,
            occupancy_exclusion_bounds=roof_exit_wall_bounds,
            runtime_emitter=runtime_emitter,
        )
    if not terrace_enabled and market_hall_frontage:
            fascia_height = max(0.22, min(0.34, spec.floor_height * 0.1))
            fascia_depth = max(0.18, min(0.28, parapet_t * 1.18))
            fascia_z = roof_surface_z - fascia_height / 2 + 0.02
            side_fascia_span = max(0.01, roof_depth - fascia_depth * 2.0)
            for side_key, size, location in (
                (
                    "front",
                    (roof_width, fascia_depth, fascia_height),
                    (
                        (roof_x0 + roof_x1) / 2,
                        _surface_coord(
                            "front",
                            roof_y0 + parapet_t / 2,
                            parapet_t,
                            fascia_depth,
                            exterior=True,
                            offset=0.008,
                        ),
                        fascia_z,
                    ),
                ),
                (
                    "back",
                    (roof_width, fascia_depth, fascia_height),
                    (
                        (roof_x0 + roof_x1) / 2,
                        _surface_coord(
                            "back",
                            roof_y1 - parapet_t / 2,
                            parapet_t,
                            fascia_depth,
                            exterior=True,
                            offset=0.008,
                        ),
                        fascia_z,
                    ),
                ),
                (
                    "left",
                    (fascia_depth, side_fascia_span, fascia_height),
                    (
                        _surface_coord(
                            "left",
                            roof_x0 + parapet_t / 2,
                            parapet_t,
                            fascia_depth,
                            exterior=True,
                            offset=0.008,
                        ),
                        (roof_y0 + roof_y1) / 2,
                        fascia_z,
                    ),
                ),
                (
                    "right",
                    (fascia_depth, side_fascia_span, fascia_height),
                    (
                        _surface_coord(
                            "right",
                            roof_x1 - parapet_t / 2,
                            parapet_t,
                            fascia_depth,
                            exterior=True,
                            offset=0.008,
                        ),
                        (roof_y0 + roof_y1) / 2,
                        fascia_z,
                    ),
                ),
            ):
                fascia = _create_box(
                    _name(prefix, f"Roof_HallFascia_{side_key.title()}"),
                    size,
                    location,
                    collection,
                    parent,
                    materials_map["prop"],
                )
                _mark_wall_section(
                    _mark_generated(fascia, tbg_market_hall_roof_band=True, tbg_facade_side=side_key),
                    "Section_Walls_Trim",
                )
    if has_parapet and not terrace_enabled:
        parapet_cap_z = roof_surface_z + spec.parapet_height - PARAPET_CAP_HEIGHT / 2
        side_cap_span = max(0.01, roof_depth - PARAPET_CAP_DEPTH * 2.0)
        cap = _create_box(
            _name(prefix, "ParapetCap_Front"),
            (roof_width, PARAPET_CAP_DEPTH, PARAPET_CAP_HEIGHT),
            (
                (roof_x0 + roof_x1) / 2,
                _surface_coord(
                    "front",
                    roof_y0 + parapet_t / 2,
                    parapet_t,
                    PARAPET_CAP_DEPTH,
                    exterior=True,
                    offset=0.0,
                ),
                parapet_cap_z,
            ),
            collection,
            parent,
            trim_material,
        )
        _mark_wall_section(
            _mark_generated(cap, tbg_parapet_cap=True, tbg_facade_side="front", tbg_facade_plane="outer"),
            "Section_Walls_Trim",
        )
        cap = _create_box(
            _name(prefix, "ParapetCap_Back"),
            (roof_width, PARAPET_CAP_DEPTH, PARAPET_CAP_HEIGHT),
            (
                (roof_x0 + roof_x1) / 2,
                _surface_coord(
                    "back",
                    roof_y1 - parapet_t / 2,
                    parapet_t,
                    PARAPET_CAP_DEPTH,
                    exterior=True,
                    offset=0.0,
                ),
                parapet_cap_z,
            ),
            collection,
            parent,
            trim_material,
        )
        _mark_wall_section(
            _mark_generated(cap, tbg_parapet_cap=True, tbg_facade_side="back", tbg_facade_plane="outer"),
            "Section_Walls_Trim",
        )
        cap = _create_box(
            _name(prefix, "ParapetCap_Left"),
            (PARAPET_CAP_DEPTH, side_cap_span, PARAPET_CAP_HEIGHT),
            (
                _surface_coord(
                    "left",
                    roof_x0 + parapet_t / 2,
                    parapet_t,
                    PARAPET_CAP_DEPTH,
                    exterior=True,
                    offset=0.0,
                ),
                (roof_y0 + roof_y1) / 2,
                parapet_cap_z,
            ),
            collection,
            parent,
            trim_material,
        )
        _mark_wall_section(
            _mark_generated(cap, tbg_parapet_cap=True, tbg_facade_side="left", tbg_facade_plane="outer"),
            "Section_Walls_Trim",
        )
        cap = _create_box(
            _name(prefix, "ParapetCap_Right"),
            (PARAPET_CAP_DEPTH, side_cap_span, PARAPET_CAP_HEIGHT),
            (
                _surface_coord(
                    "right",
                    roof_x1 - parapet_t / 2,
                    parapet_t,
                    PARAPET_CAP_DEPTH,
                    exterior=True,
                    offset=0.0,
                ),
                (roof_y0 + roof_y1) / 2,
                parapet_cap_z,
            ),
            collection,
            parent,
            trim_material,
        )
        _mark_wall_section(
            _mark_generated(cap, tbg_parapet_cap=True, tbg_facade_side="right", tbg_facade_plane="outer"),
            "Section_Walls_Trim",
        )


def _build_barrel_roof(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    roof_surface_z = _roof_surface_z(spec)
    base_z = _base_elevation(spec)
    wall_material = _wall_material_for_floor(materials_map, spec, max(0, spec.floor_count - 1))
    _spatial_plan_ref, roof_rect, _full_rect = _top_mass_rect(spec)
    _emit_terrace_transition_geometry(
        prefix,
        spec,
        spatial_plan=_spatial_plan_ref,
        full_rect=_full_rect,
        collection=collection,
        parent=parent,
        materials_map=materials_map,
        runtime_emitter=runtime_emitter,
    )
    roof_x0, roof_x1, roof_y0, roof_y1 = roof_rect
    roof_width = max(0.01, float(roof_x1 - roof_x0))
    roof_depth = max(0.01, float(roof_y1 - roof_y0))
    roof_center_x = float((roof_x0 + roof_x1) / 2)
    roof_center_y = float((roof_y0 + roof_y1) / 2)
    hangar_barrel = _is_hangar_frontage(spec)
    axis = "Y" if hangar_barrel else _roof_longitudinal_axis(spec)
    long_span = roof_width if axis == "X" else roof_depth
    arch_span = roof_depth if axis == "X" else roof_width
    wall_t = max(spec.wall_thickness, 0.16 if hangar_barrel else 0.14)
    roof_shell_t = min(0.3, max(0.14, spec.slab_thickness * (1.45 if hangar_barrel else 1.35)))
    if hangar_barrel:
        half_span = arch_span / 2
        spring_height = min(2.2, max(1.55, spec.floor_height * 0.38))
        outer_rise = min(
            max(spec.floor_height * 0.92, arch_span * 0.34),
            max(spec.floor_height * 1.26, arch_span * 0.42),
        )
        inner_half_span = max(half_span - roof_shell_t * 0.9, half_span * 0.78)
        inner_rise = max(outer_rise - roof_shell_t, outer_rise * 0.8)
        segment_count = max(12, min(18, int(round(arch_span * 0.72))))
        spring_z = base_z + spring_height
        roof_height = spring_height + outer_rise
        angles = [math.pi - math.pi * index / segment_count for index in range(segment_count + 1)]
        outer_arc = [(math.cos(angle) * half_span, spring_z + math.sin(angle) * outer_rise) for angle in angles]
        inner_arc = [
            (math.cos(angle) * inner_half_span, spring_z + math.sin(angle) * inner_rise)
            for angle in reversed(angles)
        ]
    else:
        spring_height = min(1.25, max(0.6, spec.parapet_height * 0.95))
        radius = max(arch_span / 2, roof_shell_t * 2.2)
        inner_radius = max(radius - roof_shell_t, radius * 0.72)
        segment_count = max(8, min(12, int(round(arch_span))))
        spring_z = roof_surface_z + spring_height
        roof_height = spring_height + radius
        angles = [math.pi - math.pi * index / segment_count for index in range(segment_count + 1)]
        outer_arc = [(math.cos(angle) * radius, spring_z + math.sin(angle) * radius) for angle in angles]
        inner_arc = [(math.cos(angle) * inner_radius, spring_z + math.sin(angle) * inner_radius) for angle in reversed(angles)]

    prism_depth = long_span - wall_t if hangar_barrel else long_span
    prism_location = (
        (roof_center_x, roof_center_y + wall_t / 2, 0.0)
        if hangar_barrel
        else (roof_center_x, roof_center_y, 0.0)
    )
    roof_obj = _create_profile_prism_object(
        _name(prefix, "Roof_Barrel"),
        profile=outer_arc + inner_arc,
        depth=prism_depth,
        axis=axis,
        location=prism_location,
        collection=collection,
        parent=parent,
        material=materials_map["roof"],
        bucket="Section_Walls_Roof",
        caps=not hangar_barrel,
    )
    _emit_roof_blocker_box(
        runtime_emitter,
        size=(roof_width, roof_depth, roof_height),
        location=(roof_center_x, roof_center_y, roof_surface_z + roof_height / 2),
        source_name=roof_obj.name if roof_obj is not None else _name(prefix, "Roof_Barrel_Blocker"),
    )

    end_cap_inset = 0.0 if hangar_barrel else 0.0
    if axis == "X":
        side_specs = (
            ("front", (roof_width, wall_t, spring_height), (roof_center_x, roof_y0 + wall_t / 2, roof_surface_z + spring_height / 2)),
            ("back", (roof_width, wall_t, spring_height), (roof_center_x, roof_y1 - wall_t / 2, roof_surface_z + spring_height / 2)),
        )
        end_specs = (
            ("left", (roof_x0 + wall_t / 2 + end_cap_inset, roof_center_y, 0.0), (wall_t, roof_depth, roof_height)),
            ("right", (roof_x1 - wall_t / 2 - end_cap_inset, roof_center_y, 0.0), (wall_t, roof_depth, roof_height)),
        )
    else:
        side_specs = (
            ("left", (wall_t, roof_depth, spring_height), (roof_x0 + wall_t / 2, roof_center_y, (base_z if hangar_barrel else roof_surface_z) + spring_height / 2)),
            ("right", (wall_t, roof_depth, spring_height), (roof_x1 - wall_t / 2, roof_center_y, (base_z if hangar_barrel else roof_surface_z) + spring_height / 2)),
        )
        end_specs = (
            ("front", (roof_center_x, roof_y0 + wall_t / 2 + end_cap_inset, 0.0), (roof_width, wall_t, roof_height)),
            ("back", (roof_center_x, roof_y1 - wall_t / 2 - end_cap_inset, 0.0), (roof_width, wall_t, roof_height)),
        )

    for side_key, size, location in side_specs:
        if hangar_barrel:
            _emit_shell_markers(
                runtime_emitter,
                marker_specs=[(size, location, roof_obj.name if roof_obj is not None else _name(prefix, "Roof_Barrel"), side_key)],
                floor_index=spec.floor_count,
            )
            continue
        _emit_shell_slabs(
            prefix,
            slab_specs=[(f"Roof_Barrel_Spring_{side_key.title()}", size, location, side_key)],
            collection=collection,
            parent=parent,
            material=wall_material,
            floor_index=spec.floor_count,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )

    if hangar_barrel:
        end_profile = [
            (-arch_span / 2, base_z),
            (-arch_span / 2, spring_z),
            *outer_arc[1:-1],
            (arch_span / 2, spring_z),
            (arch_span / 2, base_z),
        ]
    else:
        end_profile = [
            (-arch_span / 2, roof_surface_z),
            (-arch_span / 2, spring_z),
            *outer_arc[1:-1],
            (arch_span / 2, spring_z),
            (arch_span / 2, roof_surface_z),
        ]
    for side_key, location, marker_size in end_specs:
        marker_center_z = float((base_z if hangar_barrel else roof_surface_z) + roof_height / 2)
        if hangar_barrel:
            _emit_shell_markers(
                runtime_emitter,
                marker_specs=[
                    (
                        marker_size,
                        (float(location[0]), float(location[1]), marker_center_z),
                        roof_obj.name if roof_obj is not None else _name(prefix, f"Roof_Barrel_End_{side_key.title()}"),
                        side_key,
                    )
                ],
                floor_index=spec.floor_count,
            )
            continue
        _emit_shell_closure(
            _name(prefix, f"Roof_Barrel_End_{side_key.title()}"),
            profile=end_profile,
            depth=wall_t,
            axis=axis,
            location=location,
            collection=collection,
            parent=parent,
            material=wall_material,
            side_key=side_key,
            marker_size=marker_size,
            marker_center_z=marker_center_z,
            floor_index=spec.floor_count,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )


def _build_gable_roof(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    roof_surface_z = _roof_surface_z(spec)
    wall_material = _wall_material_for_floor(materials_map, spec, max(0, spec.floor_count - 1))
    industrial_frontage = _is_industrial_frontage(spec)
    closure_material = _roof_cladding_material(materials_map) if industrial_frontage else wall_material
    _spatial_plan_ref, roof_rect, _full_rect = _top_mass_rect(spec)
    roof_room = getattr(_spatial_plan_ref, "roof_room", None)
    terminal_profile = str(getattr(roof_room, "terminal_profile", "")).upper()
    attic_opening_rect = (
        _planner_roof_opening_rect(_spatial_plan_ref)
        if terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN
        else None
    )
    roof_rect = _sloped_roof_rect_with_terrace_clearance(roof_rect, spatial_plan=_spatial_plan_ref)
    _emit_terrace_transition_geometry(
        prefix,
        spec,
        spatial_plan=_spatial_plan_ref,
        full_rect=_full_rect,
        collection=collection,
        parent=parent,
        materials_map=materials_map,
        runtime_emitter=runtime_emitter,
    )
    roof_x0, roof_x1, roof_y0, roof_y1 = roof_rect
    roof_width = max(0.01, float(roof_x1 - roof_x0))
    roof_depth = max(0.01, float(roof_y1 - roof_y0))
    roof_center_x = float((roof_x0 + roof_x1) / 2)
    roof_center_y = float((roof_y0 + roof_y1) / 2)
    hangar_frontage = _is_hangar_frontage(spec)
    axis = "Y" if hangar_frontage else _roof_longitudinal_axis(spec)
    roof_shell_t = min(0.28, max(0.14, spec.slab_thickness * (1.2 if hangar_frontage else 1.15)))
    overhang = 0.02 if hangar_frontage else min(0.4, max(0.22, min(roof_width, roof_depth) * 0.035))
    _emit_top_floor_closeout(
        prefix,
        spec=spec,
        collection=collection,
        parent=parent,
        material=materials_map["floor"],
        runtime_emitter=runtime_emitter,
        footprint_rect=roof_rect,
        cutout_rect=attic_opening_rect,
    )

    if axis == "X":
        slope_span = roof_depth
        along_length = roof_width + overhang * 2
        ridge_rise = _gable_ridge_rise(spec, slope_span=slope_span, hangar_frontage=hangar_frontage)
        slope_run = slope_span / 2 + overhang
        xs = _sloped_shell_cross_section(
            slope_run=slope_run,
            rise=ridge_rise,
            shell_thickness=roof_shell_t,
        )
        slope_length = _sloped_roof_shell_length(
            slope_run=slope_run,
            rise=ridge_rise,
            shell_thickness=roof_shell_t,
        )
        pitch = xs["pitch"]
        slope_center_z = roof_surface_z + ridge_rise / 2
        front_back_offset = roof_depth / 4 + overhang / 2
        end_profile_run = front_back_offset + math.cos(pitch) * slope_length / 2

        front_roof_obj = _emit_roof_box(
            _name(prefix, "Roof_Gable_Front"),
            (along_length, slope_length, roof_shell_t),
            (roof_center_x, roof_center_y - front_back_offset, slope_center_z),
            collection,
            parent,
            materials_map["roof"],
            rotation=(pitch, 0.0, 0.0),
            runtime_emitter=runtime_emitter,
            emit_runtime_blocker=False,
        )
        back_roof_obj = _emit_roof_box(
            _name(prefix, "Roof_Gable_Back"),
            (along_length, slope_length, roof_shell_t),
            (roof_center_x, roof_center_y + front_back_offset, slope_center_z),
            collection,
            parent,
            materials_map["roof"],
            rotation=(-pitch, 0.0, 0.0),
            runtime_emitter=runtime_emitter,
            emit_runtime_blocker=False,
        )
        roof_side_objects = {"front": front_roof_obj, "back": back_roof_obj}

        end_profile_lift = xs["vertical_half_thickness"]
        end_profile = [
            (-end_profile_run, roof_surface_z),
            (-end_profile_run, roof_surface_z + end_profile_lift),
            (0.0, roof_surface_z + ridge_rise + end_profile_lift),
            (end_profile_run, roof_surface_z + end_profile_lift),
            (end_profile_run, roof_surface_z),
        ]
        left_location, left_marker_size, left_closure_depth = _sloped_end_closure_spec(
            axis=axis,
            side_key="left",
            roof_rect=roof_rect,
            roof_center=(roof_center_x, roof_center_y),
            shell_depth=spec.wall_thickness,
            overhang=overhang,
            span=end_profile_run * 2,
            height=ridge_rise,
        )
        right_location, right_marker_size, right_closure_depth = _sloped_end_closure_spec(
            axis=axis,
            side_key="right",
            roof_rect=roof_rect,
            roof_center=(roof_center_x, roof_center_y),
            shell_depth=spec.wall_thickness,
            overhang=overhang,
            span=end_profile_run * 2,
            height=ridge_rise,
        )
        end_specs = (
            ("left", left_location, left_marker_size, left_closure_depth),
            ("right", right_location, right_marker_size, right_closure_depth),
        )
        roof_side_objects = {"front": front_roof_obj, "back": back_roof_obj}
    else:
        slope_span = roof_width
        along_length = roof_depth + overhang * 2
        ridge_rise = _gable_ridge_rise(spec, slope_span=slope_span, hangar_frontage=hangar_frontage)
        slope_run = slope_span / 2 + overhang
        xs = _sloped_shell_cross_section(
            slope_run=slope_run,
            rise=ridge_rise,
            shell_thickness=roof_shell_t,
        )
        slope_length = _sloped_roof_shell_length(
            slope_run=slope_run,
            rise=ridge_rise,
            shell_thickness=roof_shell_t,
        )
        pitch = xs["pitch"]
        slope_center_z = roof_surface_z + ridge_rise / 2
        left_right_offset = roof_width / 4 + overhang / 2
        end_profile_run = left_right_offset + math.cos(pitch) * slope_length / 2

        left_roof_obj = _emit_roof_box(
            _name(prefix, "Roof_Gable_Left"),
            (slope_length, along_length, roof_shell_t),
            (roof_center_x - left_right_offset, roof_center_y, slope_center_z),
            collection,
            parent,
            materials_map["roof"],
            rotation=(0.0, -pitch, 0.0),
            runtime_emitter=runtime_emitter,
            emit_runtime_blocker=False,
        )
        right_roof_obj = _emit_roof_box(
            _name(prefix, "Roof_Gable_Right"),
            (slope_length, along_length, roof_shell_t),
            (roof_center_x + left_right_offset, roof_center_y, slope_center_z),
            collection,
            parent,
            materials_map["roof"],
            rotation=(0.0, pitch, 0.0),
            runtime_emitter=runtime_emitter,
            emit_runtime_blocker=False,
        )
        roof_side_objects = {"left": left_roof_obj, "right": right_roof_obj}

        end_profile_lift = xs["vertical_half_thickness"]
        end_profile = [
            (-end_profile_run, roof_surface_z),
            (-end_profile_run, roof_surface_z + end_profile_lift),
            (0.0, roof_surface_z + ridge_rise + end_profile_lift),
            (end_profile_run, roof_surface_z + end_profile_lift),
            (end_profile_run, roof_surface_z),
        ]
        front_location, front_marker_size, front_closure_depth = _sloped_end_closure_spec(
            axis=axis,
            side_key="front",
            roof_rect=roof_rect,
            roof_center=(roof_center_x, roof_center_y),
            shell_depth=spec.wall_thickness,
            overhang=overhang,
            span=end_profile_run * 2,
            height=ridge_rise,
        )
        back_location, back_marker_size, back_closure_depth = _sloped_end_closure_spec(
            axis=axis,
            side_key="back",
            roof_rect=roof_rect,
            roof_center=(roof_center_x, roof_center_y),
            shell_depth=spec.wall_thickness,
            overhang=overhang,
            span=end_profile_run * 2,
            height=ridge_rise,
        )
        end_specs = (
            ("front", front_location, front_marker_size, front_closure_depth),
            ("back", back_location, back_marker_size, back_closure_depth),
        )
        roof_side_objects = {"left": left_roof_obj, "right": right_roof_obj}

    _build_sloped_attic_open_package(
        prefix,
        roof_name="Roof_Gable",
        spec=spec,
        roof_room=roof_room,
        terminal_profile=terminal_profile,
        attic_opening_rect=attic_opening_rect,
        roof_rect=roof_rect,
        axis=axis,
        roof_profile=end_profile,
        end_specs=end_specs,
        shell_depth=spec.wall_thickness,
        roof_center=(roof_center_x, roof_center_y),
        roof_base_z=roof_surface_z,
        marker_center_z=roof_surface_z + ridge_rise / 2,
        collection=collection,
        parent=parent,
        material=closure_material,
        floor_index=spec.floor_count,
        frame_material=materials_map["frame"],
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
        roof_side_objects=roof_side_objects,
    )
    if _is_hangar_frontage(spec):
        _emit_shell_markers(
            runtime_emitter,
            marker_specs=[
                (
                    (spec.wall_thickness, roof_depth, ridge_rise),
                    (float(marker_x), roof_center_y, float(roof_surface_z + ridge_rise / 2)),
                    _name(prefix, f"Roof_Gable_HangarMarker_{side_key.title()}"),
                    side_key,
                )
                for side_key, marker_x in (
                    ("left", roof_x0 + spec.wall_thickness / 2),
                    ("right", roof_x1 - spec.wall_thickness / 2),
                )
            ],
            floor_index=spec.floor_count,
        )

    _emit_sloped_roof_blockers(
        runtime_emitter,
        roof_rect=roof_rect,
        bottom_z=roof_surface_z,
        height=ridge_rise + roof_shell_t,
        source_name=_name(prefix, "Roof_Gable_Blocker"),
        opening_rect=attic_opening_rect,
    )


def _build_shed_roof(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    roof_surface_z = _roof_surface_z(spec)
    wall_material = _wall_material_for_floor(materials_map, spec, max(0, spec.floor_count - 1))
    _spatial_plan_ref, roof_rect, _full_rect = _top_mass_rect(spec)
    roof_room = getattr(_spatial_plan_ref, "roof_room", None)
    terminal_profile = str(getattr(roof_room, "terminal_profile", "")).upper()
    attic_opening_rect = (
        _planner_roof_opening_rect(_spatial_plan_ref)
        if terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN
        else None
    )
    roof_rect = _sloped_roof_rect_with_terrace_clearance(roof_rect, spatial_plan=_spatial_plan_ref)
    _emit_terrace_transition_geometry(
        prefix,
        spec,
        spatial_plan=_spatial_plan_ref,
        full_rect=_full_rect,
        collection=collection,
        parent=parent,
        materials_map=materials_map,
        runtime_emitter=runtime_emitter,
    )
    roof_x0, roof_x1, roof_y0, roof_y1 = roof_rect
    roof_width = max(0.01, float(roof_x1 - roof_x0))
    roof_depth = max(0.01, float(roof_y1 - roof_y0))
    roof_center_x = float((roof_x0 + roof_x1) / 2)
    roof_center_y = float((roof_y0 + roof_y1) / 2)
    industrial_frontage = _is_industrial_frontage(spec)
    cladding_material = _roof_cladding_material(materials_map) if industrial_frontage else wall_material
    axis = _roof_longitudinal_axis(spec)
    wall_t = max(spec.wall_thickness, 0.18 if industrial_frontage else 0.14)
    roof_shell_t = min(
        0.28 if industrial_frontage else 0.24,
        max(0.14 if industrial_frontage else 0.12, spec.slab_thickness * (1.24 if industrial_frontage else 1.15)),
    )
    overhang = (
        0.02
        if industrial_frontage and str(getattr(spec, "preset_id", "")).strip().lower() == "hangar"
        else min(0.4, max(0.22, min(roof_width, roof_depth) * 0.035))
    )
    _emit_top_floor_closeout(
        prefix,
        spec=spec,
        collection=collection,
        parent=parent,
        material=materials_map["floor"],
        runtime_emitter=runtime_emitter,
        footprint_rect=roof_rect,
        cutout_rect=attic_opening_rect,
    )

    edge_band_material = (
        materials_map["roof"] if industrial_frontage and str(getattr(spec, "preset_id", "")) == "warehouse" else cladding_material
    )
    roof_side_objects = None

    def _emit_edge_band(name: str, size: tuple[float, float, float], location: tuple[float, float, float]):
        band = _create_box(name, size, location, collection, parent, edge_band_material)
        return _mark_wall_section(band, "Section_Walls_Roof")

    attic_combat_base_z, attic_combat_height = _attic_combat_aperture_request(
        spec=spec,
        roof_room=roof_room,
        roof_base_z=roof_surface_z,
    )

    if axis == "X":
        slope_span = roof_depth
        along_length = roof_width
        rise = (
            max(1.16, min(spec.floor_height * 0.98, slope_span * 0.34 + spec.parapet_height * 0.46))
            if industrial_frontage
            else max(0.9, min(spec.floor_height * 0.85, slope_span * 0.24 + spec.parapet_height * 0.35))
        )
        xs = _sloped_shell_cross_section(
            slope_run=slope_span,
            rise=rise,
            shell_thickness=roof_shell_t,
        )
        slope_length = _sloped_roof_shell_length(
            slope_run=slope_span,
            rise=rise,
            shell_thickness=roof_shell_t,
        )
        pitch = xs["pitch"]
        roof_obj = _emit_roof_box(
            _name(prefix, "Roof_Shed"),
            (along_length, slope_length, roof_shell_t),
            (roof_center_x, roof_center_y, roof_surface_z + rise / 2),
            collection,
            parent,
            materials_map["roof"],
            rotation=(pitch, 0.0, 0.0),
            runtime_emitter=runtime_emitter,
            emit_runtime_blocker=False,
        )
        highside_width = max(0.2, roof_width - wall_t * 2.0)
        highside_profile = [
            (-highside_width / 2, roof_surface_z),
            (-highside_width / 2, roof_surface_z + rise),
            (highside_width / 2, roof_surface_z + rise),
            (highside_width / 2, roof_surface_z),
        ]
        highside_span = (
            _shed_highside_window_span(spec=spec, span_total=roof_width)
            if terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN and roof_room is not None
            else None
        )
        highside_height = _clamped_aperture_height(
            profile=highside_profile,
            opening_lateral_span=highside_span,
            opening_base_z=attic_combat_base_z,
            requested_height=attic_combat_height,
            minimum_height=0.24,
        )
        if highside_span is not None and highside_height is not None:
            _emit_shell_closure_with_aperture(
                _name(prefix, "Roof_Shed_HighSide_Back"),
                profile=highside_profile,
                depth=wall_t,
                axis="Y",
                location=(roof_center_x, roof_y1 - wall_t / 2, 0.0),
                collection=collection,
                parent=parent,
                material=cladding_material,
                side_key="back",
                floor_index=spec.floor_count,
                opening_lateral_span=highside_span,
                opening_base_z=attic_combat_base_z,
                opening_height=highside_height,
                marker_size=(highside_width, wall_t, rise),
                marker_center_z=roof_surface_z + rise / 2,
                frame_material=materials_map["frame"],
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
        else:
            _emit_shell_slabs(
                prefix,
                slab_specs=[("Roof_Shed_HighSide_Back", (highside_width, wall_t, rise), (roof_center_x, roof_y1 - wall_t / 2, roof_surface_z + rise / 2), "back")],
                collection=collection,
                parent=parent,
                material=cladding_material,
                floor_index=spec.floor_count,
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
        end_profile_lift = xs["vertical_half_thickness"]
        end_profile = [
            (-roof_depth / 2, roof_surface_z),
            (-roof_depth / 2, roof_surface_z + end_profile_lift),
            (roof_depth / 2, roof_surface_z + rise + end_profile_lift),
            (roof_depth / 2, roof_surface_z),
        ]
        left_location, left_marker_size, left_closure_depth = _sloped_end_closure_spec(
            axis=axis,
            side_key="left",
            roof_rect=roof_rect,
            roof_center=(roof_center_x, roof_center_y),
            shell_depth=wall_t,
            overhang=overhang,
            span=roof_depth,
            height=rise,
        )
        right_location, right_marker_size, right_closure_depth = _sloped_end_closure_spec(
            axis=axis,
            side_key="right",
            roof_rect=roof_rect,
            roof_center=(roof_center_x, roof_center_y),
            shell_depth=wall_t,
            overhang=overhang,
            span=roof_depth,
            height=rise,
        )
        end_specs = (
            ("left", left_location, left_marker_size, left_closure_depth),
            ("right", right_location, right_marker_size, right_closure_depth),
        )
    else:
        slope_span = roof_width
        along_length = roof_depth
        rise = (
            max(1.16, min(spec.floor_height * 0.98, slope_span * 0.34 + spec.parapet_height * 0.46))
            if industrial_frontage
            else max(0.9, min(spec.floor_height * 0.85, slope_span * 0.24 + spec.parapet_height * 0.35))
        )
        xs = _sloped_shell_cross_section(
            slope_run=slope_span,
            rise=rise,
            shell_thickness=roof_shell_t,
        )
        slope_length = _sloped_roof_shell_length(
            slope_run=slope_span,
            rise=rise,
            shell_thickness=roof_shell_t,
        )
        pitch = xs["pitch"]
        roof_obj = _emit_roof_box(
            _name(prefix, "Roof_Shed"),
            (slope_length, along_length, roof_shell_t),
            (roof_center_x, roof_center_y, roof_surface_z + rise / 2),
            collection,
            parent,
            materials_map["roof"],
            rotation=(0.0, -pitch, 0.0),
            runtime_emitter=runtime_emitter,
            emit_runtime_blocker=False,
        )
        highside_depth = max(0.2, roof_depth - wall_t * 2.0)
        highside_profile = [
            (-highside_depth / 2, roof_surface_z),
            (-highside_depth / 2, roof_surface_z + rise),
            (highside_depth / 2, roof_surface_z + rise),
            (highside_depth / 2, roof_surface_z),
        ]
        highside_span = (
            _shed_highside_window_span(spec=spec, span_total=roof_depth)
            if terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN and roof_room is not None
            else None
        )
        highside_height = _clamped_aperture_height(
            profile=highside_profile,
            opening_lateral_span=highside_span,
            opening_base_z=attic_combat_base_z,
            requested_height=attic_combat_height,
            minimum_height=0.24,
        )
        if highside_span is not None and highside_height is not None:
            _emit_shell_closure_with_aperture(
                _name(prefix, "Roof_Shed_HighSide_Right"),
                profile=highside_profile,
                depth=wall_t,
                axis="X",
                location=(roof_x1 - wall_t / 2, roof_center_y, 0.0),
                collection=collection,
                parent=parent,
                material=cladding_material,
                side_key="right",
                floor_index=spec.floor_count,
                opening_lateral_span=highside_span,
                opening_base_z=attic_combat_base_z,
                opening_height=highside_height,
                marker_size=(wall_t, highside_depth, rise),
                marker_center_z=roof_surface_z + rise / 2,
                frame_material=materials_map["frame"],
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
        else:
            _emit_shell_slabs(
                prefix,
                slab_specs=[("Roof_Shed_HighSide_Right", (wall_t, highside_depth, rise), (roof_x1 - wall_t / 2, roof_center_y, roof_surface_z + rise / 2), "right")],
                collection=collection,
                parent=parent,
                material=cladding_material,
                floor_index=spec.floor_count,
                occupancy_author=occupancy_author,
                runtime_emitter=runtime_emitter,
            )
        end_profile_lift = xs["vertical_half_thickness"]
        end_profile = [
            (-roof_width / 2, roof_surface_z),
            (-roof_width / 2, roof_surface_z + end_profile_lift),
            (roof_width / 2, roof_surface_z + rise + end_profile_lift),
            (roof_width / 2, roof_surface_z),
        ]
        front_location, front_marker_size, front_closure_depth = _sloped_end_closure_spec(
            axis=axis,
            side_key="front",
            roof_rect=roof_rect,
            roof_center=(roof_center_x, roof_center_y),
            shell_depth=wall_t,
            overhang=overhang,
            span=roof_width,
            height=rise,
        )
        back_location, back_marker_size, back_closure_depth = _sloped_end_closure_spec(
            axis=axis,
            side_key="back",
            roof_rect=roof_rect,
            roof_center=(roof_center_x, roof_center_y),
            shell_depth=wall_t,
            overhang=overhang,
            span=roof_width,
            height=rise,
        )
        end_specs = (
            ("front", front_location, front_marker_size, front_closure_depth),
            ("back", back_location, back_marker_size, back_closure_depth),
        )

    _build_sloped_attic_open_package(
        prefix,
        roof_name="Roof_Shed",
        spec=spec,
        roof_room=roof_room,
        terminal_profile=terminal_profile,
        attic_opening_rect=attic_opening_rect,
        roof_rect=roof_rect,
        axis=axis,
        roof_profile=end_profile,
        end_specs=end_specs,
        shell_depth=wall_t,
        roof_center=(roof_center_x, roof_center_y),
        roof_base_z=roof_surface_z,
        marker_center_z=roof_surface_z + rise / 2,
        collection=collection,
        parent=parent,
        material=cladding_material,
        floor_index=spec.floor_count,
        frame_material=materials_map["frame"],
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
        roof_side_objects=roof_side_objects,
    )

    if industrial_frontage:
        edge_band_height = max(0.14, min(0.28, rise * 0.18))
        edge_band_depth = max(0.12, wall_t * 0.86)
        if axis == "X":
            _emit_edge_band(
                _name(prefix, "Roof_Shed_LowEave_Front"),
                (roof_width, edge_band_depth, edge_band_height),
                (
                    roof_center_x,
                    _surface_coord("front", roof_y0 + wall_t / 2, wall_t, edge_band_depth, exterior=True, offset=0.012),
                    roof_surface_z + edge_band_height / 2,
                ),
            )
            _emit_edge_band(
                _name(prefix, "Roof_Shed_HighCoping_Back"),
                (roof_width, edge_band_depth, edge_band_height),
                (
                    roof_center_x,
                    _surface_coord("back", roof_y1 - wall_t / 2, wall_t, edge_band_depth, exterior=True, offset=0.012),
                    roof_surface_z + rise - edge_band_height / 2,
                ),
            )
        else:
            _emit_edge_band(
                _name(prefix, "Roof_Shed_LowEave_Left"),
                (edge_band_depth, roof_depth, edge_band_height),
                (
                    _surface_coord("left", roof_x0 + wall_t / 2, wall_t, edge_band_depth, exterior=True, offset=0.012),
                    roof_center_y,
                    roof_surface_z + edge_band_height / 2,
                ),
            )
            _emit_edge_band(
                _name(prefix, "Roof_Shed_HighCoping_Right"),
                (edge_band_depth, roof_depth, edge_band_height),
                (
                    _surface_coord("right", roof_x1 - wall_t / 2, wall_t, edge_band_depth, exterior=True, offset=0.012),
                    roof_center_y,
                    roof_surface_z + rise - edge_band_height / 2,
                ),
            )

    _emit_sloped_roof_blockers(
        runtime_emitter,
        roof_rect=roof_rect,
        bottom_z=roof_surface_z,
        height=rise + roof_shell_t,
        source_name=roof_obj.name if roof_obj is not None else _name(prefix, "Roof_Shed_Blocker"),
        opening_rect=attic_opening_rect,
    )


def _build_sawtooth_roof(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    roof_surface_z = _roof_surface_z(spec)
    wall_material = _wall_material_for_floor(materials_map, spec, max(0, spec.floor_count - 1))
    _spatial_plan_ref, roof_rect, _full_rect = _top_mass_rect(spec)
    _emit_terrace_transition_geometry(
        prefix,
        spec,
        spatial_plan=_spatial_plan_ref,
        full_rect=_full_rect,
        collection=collection,
        parent=parent,
        materials_map=materials_map,
        runtime_emitter=runtime_emitter,
    )
    roof_x0, roof_x1, roof_y0, roof_y1 = roof_rect
    roof_width = max(0.01, float(roof_x1 - roof_x0))
    roof_depth = max(0.01, float(roof_y1 - roof_y0))
    roof_center_x = float((roof_x0 + roof_x1) / 2)
    roof_center_y = float((roof_y0 + roof_y1) / 2)
    industrial_frontage = _is_industrial_frontage(spec)
    cladding_material = _roof_cladding_material(materials_map) if industrial_frontage else wall_material
    axis = _roof_longitudinal_axis(spec)
    wall_t = max(spec.wall_thickness, 0.18 if industrial_frontage else 0.14)
    roof_shell_t = min(
        0.26 if industrial_frontage else 0.22,
        max(0.14 if industrial_frontage else 0.12, spec.slab_thickness * (1.16 if industrial_frontage else 1.08)),
    )
    along_length = roof_width if axis == "X" else roof_depth
    repeat_span = roof_depth if axis == "X" else roof_width
    target_tooth_span = (
        max(1.54, min(2.32, repeat_span * 0.23 + along_length * 0.06))
        if industrial_frontage
        else max(1.8, min(2.8, repeat_span * 0.28 + along_length * 0.08))
    )
    tooth_count = max(3, min(7, int(round(repeat_span / target_tooth_span)))) if industrial_frontage else max(2, min(6, int(round(repeat_span / target_tooth_span))))
    tooth_span = repeat_span / tooth_count
    clerestory_t = (
        max(0.24, min(0.36, tooth_span * 0.3))
        if industrial_frontage
        else max(0.18, min(0.28, tooth_span * 0.24))
    )
    slope_run = max(tooth_span - clerestory_t, tooth_span * (0.6 if industrial_frontage else 0.68))
    rise = (
        max(1.08, min(spec.floor_height * 0.86, tooth_span * 0.62 + spec.parapet_height * 0.26))
        if industrial_frontage
        else max(0.9, min(spec.floor_height * 0.72, tooth_span * 0.55 + spec.parapet_height * 0.2))
    )
    slope_length = _sloped_roof_shell_length(
        slope_run=slope_run,
        rise=rise,
        shell_thickness=roof_shell_t,
    )
    pitch = math.atan2(rise, slope_run)

    if axis == "X":
        min_lateral = -roof_depth / 2
        max_lateral = roof_depth / 2
        profile = [(min_lateral, roof_surface_z)]
        for tooth_index in range(tooth_count):
            tooth_start = min_lateral + tooth_index * tooth_span
            tooth_end = min(max_lateral, tooth_start + tooth_span)
            slope_start = min(tooth_end, tooth_start + clerestory_t)
            clerestory_name = _name(prefix, f"Roof_Sawtooth_Clerestory_{tooth_index:02d}")
            if tooth_index == 0:
                _emit_shell_slabs(
                    prefix,
                    slab_specs=[
                        (
                            f"Roof_Sawtooth_Clerestory_{tooth_index:02d}",
                            (roof_width, slope_start - tooth_start, rise),
                            (roof_center_x, roof_center_y + tooth_start + (slope_start - tooth_start) / 2, roof_surface_z + rise / 2),
                            "front",
                        )
                    ],
                    collection=collection,
                    parent=parent,
                    material=cladding_material,
                    floor_index=spec.floor_count,
                    occupancy_author=occupancy_author,
                    runtime_emitter=runtime_emitter,
                )
            else:
                clerestory_size = (roof_width, slope_start - tooth_start, rise)
                clerestory_location = (
                    roof_center_x,
                    roof_center_y + tooth_start + (slope_start - tooth_start) / 2,
                    roof_surface_z + rise / 2,
                )
                _register_shell_fragment(
                    occupancy_author,
                    size=clerestory_size,
                    location=clerestory_location,
                    normal_axis="y",
                    material=cladding_material,
                    source_bucket="Section_Walls_Exterior",
                    source_name=clerestory_name,
                )
                clerestory = _create_box(
                    clerestory_name,
                    clerestory_size,
                    clerestory_location,
                    collection,
                    parent,
                    cladding_material,
                )
                _mark_wall_section(
                    _mark_generated(clerestory, tbg_preserved_exterior_shell=True),
                    "Section_Walls_Exterior",
                )
            _emit_roof_box(
                _name(prefix, f"Roof_Sawtooth_Slope_{tooth_index:02d}"),
                (along_length, slope_length, roof_shell_t),
                (roof_center_x, roof_center_y + slope_start + (tooth_end - slope_start) / 2, roof_surface_z + rise / 2),
                collection,
                parent,
                materials_map["roof"],
                rotation=(-pitch, 0.0, 0.0),
                runtime_emitter=runtime_emitter,
                emit_runtime_blocker=False,
            )
            profile.extend(
                [
                    (tooth_start, roof_surface_z + rise),
                    (slope_start, roof_surface_z + rise),
                    (tooth_end, roof_surface_z),
                ]
            )

        end_specs = (
            ("left", (roof_x0 + wall_t / 2, roof_center_y, 0.0), (wall_t, roof_depth, rise)),
            ("right", (roof_x1 - wall_t / 2, roof_center_y, 0.0), (wall_t, roof_depth, rise)),
        )
    else:
        min_lateral = -roof_width / 2
        max_lateral = roof_width / 2
        profile = [(min_lateral, roof_surface_z)]
        for tooth_index in range(tooth_count):
            tooth_start = min_lateral + tooth_index * tooth_span
            tooth_end = min(max_lateral, tooth_start + tooth_span)
            slope_start = min(tooth_end, tooth_start + clerestory_t)
            clerestory_name = _name(prefix, f"Roof_Sawtooth_Clerestory_{tooth_index:02d}")
            if tooth_index == 0:
                _emit_shell_slabs(
                    prefix,
                    slab_specs=[
                        (
                            f"Roof_Sawtooth_Clerestory_{tooth_index:02d}",
                            (slope_start - tooth_start, roof_depth, rise),
                            (roof_center_x + tooth_start + (slope_start - tooth_start) / 2, roof_center_y, roof_surface_z + rise / 2),
                            "left",
                        )
                    ],
                    collection=collection,
                    parent=parent,
                    material=cladding_material,
                    floor_index=spec.floor_count,
                    occupancy_author=occupancy_author,
                    runtime_emitter=runtime_emitter,
                )
            else:
                clerestory_size = (slope_start - tooth_start, roof_depth, rise)
                clerestory_location = (
                    roof_center_x + tooth_start + (slope_start - tooth_start) / 2,
                    roof_center_y,
                    roof_surface_z + rise / 2,
                )
                _register_shell_fragment(
                    occupancy_author,
                    size=clerestory_size,
                    location=clerestory_location,
                    normal_axis="x",
                    material=cladding_material,
                    source_bucket="Section_Walls_Exterior",
                    source_name=clerestory_name,
                )
                clerestory = _create_box(
                    clerestory_name,
                    clerestory_size,
                    clerestory_location,
                    collection,
                    parent,
                    cladding_material,
                )
                _mark_wall_section(
                    _mark_generated(clerestory, tbg_preserved_exterior_shell=True),
                    "Section_Walls_Exterior",
                )
            _emit_roof_box(
                _name(prefix, f"Roof_Sawtooth_Slope_{tooth_index:02d}"),
                (slope_length, along_length, roof_shell_t),
                (roof_center_x + slope_start + (tooth_end - slope_start) / 2, roof_center_y, roof_surface_z + rise / 2),
                collection,
                parent,
                materials_map["roof"],
                rotation=(0.0, pitch, 0.0),
                runtime_emitter=runtime_emitter,
                emit_runtime_blocker=False,
            )
            profile.extend(
                [
                    (tooth_start, roof_surface_z + rise),
                    (slope_start, roof_surface_z + rise),
                    (tooth_end, roof_surface_z),
                ]
            )

        end_specs = (
            ("front", (roof_center_x, roof_y0 + wall_t / 2, 0.0), (roof_width, wall_t, rise)),
            ("back", (roof_center_x, roof_y1 - wall_t / 2, 0.0), (roof_width, wall_t, rise)),
        )

    for side_key, location, marker_size in end_specs:
        _emit_shell_closure(
            _name(prefix, f"Roof_Sawtooth_End_{side_key.title()}"),
            profile=profile,
            depth=wall_t,
            axis=axis,
            location=location,
            collection=collection,
            parent=parent,
            material=cladding_material,
            side_key=side_key,
            marker_size=marker_size,
            marker_center_z=roof_surface_z + rise / 2,
            floor_index=spec.floor_count,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )

    _emit_roof_blocker_volume(
        runtime_emitter,
        width=roof_width,
        depth=roof_depth,
        bottom_z=roof_surface_z,
        height=rise + roof_shell_t,
        source_name=_name(prefix, "Roof_Sawtooth_Blocker"),
        center_x=roof_center_x,
        center_y=roof_center_y,
    )


_ROOF_FAMILY_BUILDERS = {
    ROOF_MODE_FLAT: _build_flat_roof,
    ROOF_MODE_TERRACE: _build_flat_roof,
    ROOF_MODE_BARREL: _build_barrel_roof,
    ROOF_MODE_GABLE: _build_gable_roof,
    ROOF_MODE_SHED: _build_shed_roof,
    ROOF_MODE_SAWTOOTH: _build_sawtooth_roof,
}


def _build_roof(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    roof_mode = _roof_mode(spec)
    builder = _ROOF_FAMILY_BUILDERS.get(roof_mode)
    if builder is None:
        raise ValueError(f"Unsupported roof mode: {roof_mode}")
    return builder(
        prefix,
        spec,
        collection,
        parent,
        materials_map,
        runtime_emitter=runtime_emitter,
        occupancy_author=occupancy_author,
    )


def _skip_office_roof_props(spec) -> bool:
    if str(getattr(spec, "preset_id", "")).lower() != "office_block":
        return False
    if int(getattr(spec, "floor_count", 0)) < 5:
        return False
    balcony_mode = str(getattr(getattr(spec, "balcony", None), "mode", "")).upper()
    return int(getattr(spec, "floor_count", 0)) >= 6 or balcony_mode == "STRIP"


def _build_roof_props(prefix, spec, spatial_plan, collection, parent, materials_map, runtime_emitter: RuntimeMarkerEmitter | None = None):
    if _skip_office_roof_props(spec):
        return None
    return _build_roof_props_owner(
        prefix,
        spec,
        spatial_plan,
        collection,
        parent,
        materials_map,
        runtime_emitter=runtime_emitter,
    )
