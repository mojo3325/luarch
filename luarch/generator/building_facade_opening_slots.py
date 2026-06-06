from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import bpy
from mathutils import Euler, Vector

from .. import constants
from ..export_contract import (
    VOXEL_SIZE_STUDS,
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
    FRONTAGE_TYPE_STOREFRONT_PHARMACY,
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
    WINDOW_TRIM_WIDTH,
    WINDOW_WALL_OVERLAP,
    BalconyPlan,
    _base_elevation,
    _front_entry_envelope,
    _is_office_window_profile,
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
    resolve_authored_voxel_wall_material_metadata,
    _solid_stepped_flight_mesh,
)
from .building_occupancy import (
    AtomicWallFragment,
    MIN_NON_THICKNESS_CELL_SPAN_STUDS,
    OPENING_VISUAL_CLEARANCE_STUDS,
    OccupancyAuthoringSession,
)
from .runtime_markers import RuntimeMarkerEmitter, _emit_object_proxy_box


@dataclass(frozen=True)
class _PlannedWallFragment:
    fragment: AtomicWallFragment
    local_size: tuple[float, float, float]
    local_center: tuple[float, float, float]
    marker_role: str
    marker_metadata: dict[str, object]


OPENING_FRAME_MASS_MIN_DEPTH_STUDS = 0.10
OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS = 0.06


def _create_opening_frame(
    name: str,
    orientation: str,
    visible_positive_depth: bool,
    outer_width: float,
    depth: float,
    outer_height: float,
    inner_width: float,
    inner_height: float,
    along_coord: float,
    normal_coord: float,
    z_center: float,
    collection,
    parent,
    material,
    *,
    inner_center_z_offset: float = 0.0,
    include_inner_returns: bool = True,
    double_sided: bool = False,
):
    mesh = _frame_mesh(
        name,
        outer_width,
        depth,
        outer_height,
        inner_width,
        inner_height,
        visible_positive_depth=visible_positive_depth,
        inner_center_z_offset=inner_center_z_offset,
        include_inner_returns=include_inner_returns,
        double_sided=double_sided,
    )
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    _parent_to(obj, parent)
    obj.location = Vector(_opening_location(orientation, along_coord, normal_coord, z_center))
    obj.rotation_euler = Euler(_orientation_rotation(orientation), "XYZ")
    _assign_material(obj, material)
    return obj

def _create_opening_box(
    name: str,
    orientation: str,
    width: float,
    depth: float,
    height: float,
    along_coord: float,
    normal_coord: float,
    z_center: float,
    collection,
    parent,
    material,
    *,
    rotation_z: float = 0.0,
    origin_mode: str = "CENTER",
):
    return _create_box(
        name,
        (width, depth, height),
        _opening_location(orientation, along_coord, normal_coord, z_center),
        collection,
        parent,
        material,
        rotation=_orientation_rotation(orientation, rotation_z),
        origin_mode=origin_mode,
    )

def _create_wall_segment(
    name: str,
    orientation: str,
    wall_pos: float,
    start: float,
    end: float,
    base_z: float,
    height: float,
    wall_t: float,
    collection,
    parent,
    material,
):
    span = end - start
    if span <= 1e-4 or height <= 1e-4:
        return None

    if orientation == "X":
        size = (span, wall_t, height)
        location = ((start + end) / 2, wall_pos, base_z + height / 2)
    else:
        size = (wall_t, span, height)
        location = (wall_pos, (start + end) / 2, base_z + height / 2)
    return _create_box(name, size, location, collection, parent, material)


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


def _plan_linear_wall_fragment(
    *,
    orientation: str,
    wall_pos: float,
    start: float,
    end: float,
    base_z: float,
    height: float,
    wall_t: float,
    ref_along: float,
    ref_z: float,
    material,
    source_bucket: str,
    source_name: str,
    staged_object_name: str,
    marker_role: str = ROLE_SHELL,
    marker_metadata: dict[str, object] | None = None,
) -> _PlannedWallFragment | None:
    span = float(end) - float(start)
    height = float(height)
    if span < MIN_NON_THICKNESS_CELL_SPAN_STUDS or height < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        return None
    local_size = (span, float(wall_t), height)
    local_center = (((float(start) + float(end)) / 2) - float(ref_along), 0.0, float(base_z) + height / 2 - float(ref_z))
    if orientation == "X":
        world_center = (float(ref_along) + local_center[0], float(wall_pos), float(ref_z) + local_center[2])
        world_size = local_size
        normal_axis = "y"
    else:
        world_center = (float(wall_pos), float(ref_along) + local_center[0], float(ref_z) + local_center[2])
        world_size = (float(wall_t), span, height)
        normal_axis = "x"
    material_family, visual_style, display_color_rgb = _resolved_structural_material_metadata(material)
    return _PlannedWallFragment(
        fragment=AtomicWallFragment.from_center_size(
            center=world_center,
            size=world_size,
            source_bucket=source_bucket,
            material_family=material_family,
            normal_axis=normal_axis,
            visual_style=visual_style,
            display_color_rgb=display_color_rgb,
            source_name=source_name,
            staged_object_names=(staged_object_name,),
        ),
        local_size=local_size,
        local_center=local_center,
        marker_role=marker_role,
        marker_metadata=dict(marker_metadata or {}),
    )


def _register_planned_wall_fragments(
    occupancy_author: OccupancyAuthoringSession | None,
    planned_fragments: list[_PlannedWallFragment] | tuple[_PlannedWallFragment, ...],
) -> None:
    _ = (occupancy_author, planned_fragments)
    raise RuntimeError(
        "_register_planned_wall_fragments(...) is disabled for V3 gameplay authoring; "
        "register an explicit wall plane and rectangular cuts instead."
    )


def _register_linear_wall_plane(
    occupancy_author: OccupancyAuthoringSession | None,
    *,
    orientation: str,
    wall_pos: float,
    start: float,
    end: float,
    base_z: float,
    height: float,
    wall_t: float,
    material,
    source_bucket: str,
    source_name: str,
    staged_object_name: str,
    rect_cuts: Iterable[tuple] | None = None,
):
    if occupancy_author is None:
        return None
    span = float(end) - float(start)
    height = float(height)
    if span < MIN_NON_THICKNESS_CELL_SPAN_STUDS or height < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
        return None
    material_family, visual_style, display_color_rgb = _resolved_structural_material_metadata(material)
    if orientation == "X":
        normal_axis = "y"
        thickness_min = float(wall_pos) - float(wall_t) / 2
        thickness_max = float(wall_pos) + float(wall_t) / 2
    else:
        normal_axis = "x"
        thickness_min = float(wall_pos) - float(wall_t) / 2
        thickness_max = float(wall_pos) + float(wall_t) / 2
    plane = occupancy_author.register_wall_plane(
        plane_id=source_name,
        normal_axis=normal_axis,
        thickness_min=thickness_min,
        thickness_max=thickness_max,
        run_min=float(start),
        run_max=float(end),
        z_min=float(base_z),
        z_max=float(base_z) + height,
        source_bucket=source_bucket,
        material_family=material_family,
        visual_style=visual_style,
        display_color_rgb=display_color_rgb,
        source_name=source_name,
        staged_object_names=(staged_object_name,),
    )
    for cut in rect_cuts or ():
        kind, run_min, run_max, z_min, z_max = cut[:5]
        clearance_studs = float(cut[5]) if len(cut) >= 6 else float(OPENING_VISUAL_CLEARANCE_STUDS)
        plane.add_rect_cut(
            kind,
            run_min=run_min,
            run_max=run_max,
            z_min=z_min,
            z_max=z_max,
            clearance_studs=clearance_studs,
        )
    return plane


def _window_visual_cut_rect(
    *,
    spec,
    state: str,
    side_key: str,
    floor_index: int,
    slot_index: int,
    slot_min: float,
    slot_max: float,
    base_z: float,
    floor_height: float,
    opening_width: float,
    sill_h: float,
    opening_h: float,
) -> tuple[float, float, float, float]:
    _ = (state, side_key, floor_index, slot_index, floor_height)
    outer_width, outer_height = _window_frame_outer_envelope(
        opening_width=opening_width,
        opening_height=opening_h,
        office_style=_is_office_window_profile(spec.window_profile),
    )
    center_along = (float(slot_min) + float(slot_max)) / 2
    center_z = float(base_z) + float(sill_h) + float(opening_h) / 2
    return (
        center_along - outer_width / 2,
        center_along + outer_width / 2,
        center_z - outer_height / 2,
        center_z + outer_height / 2,
    )


def _expanded_wall_cut_rect(cut_rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    clearance = max(0.0, float(OPENING_VISUAL_CLEARANCE_STUDS))
    run_min, run_max, z_min, z_max = (float(value) for value in cut_rect)
    return (
        round(run_min - clearance, 4),
        round(run_max + clearance, 4),
        round(z_min - clearance, 4),
        round(z_max + clearance, 4),
    )


def _snap_rect_to_nearest_wall_grid_span(
    cut_rect: tuple[float, float, float, float],
    *,
    grid_origin_run: float,
    grid_origin_z: float,
    plane_run_min: float,
    plane_run_max: float,
    plane_z_min: float,
    plane_z_max: float,
    cell_size: float = VOXEL_SIZE_STUDS,
) -> tuple[float, float, float, float]:
    run_min, run_max, z_min, z_max = (float(value) for value in cut_rect)
    cell_size = max(1e-5, float(cell_size))

    def _snap_axis(min_value: float, max_value: float, origin: float, plane_min: float, plane_max: float) -> tuple[float, float]:
        cells = max(1, int(math.ceil(max(1e-6, float(max_value) - float(min_value)) / cell_size - 1e-7)))
        center = (float(min_value) + float(max_value)) / 2.0
        start_index = int(round((center - float(origin)) / cell_size - cells / 2.0))
        snapped_min = float(origin) + start_index * cell_size
        snapped_max = snapped_min + cells * cell_size
        if snapped_min < float(plane_min):
            snapped_min = float(plane_min)
            snapped_max = snapped_min + cells * cell_size
        if snapped_max > float(plane_max):
            snapped_max = float(plane_max)
            snapped_min = snapped_max - cells * cell_size
        if snapped_min < float(plane_min) - 1e-6 or snapped_max > float(plane_max) + 1e-6:
            snapped_min = max(float(plane_min), float(min_value))
            snapped_max = min(float(plane_max), float(max_value))
        return snapped_min, snapped_max

    snapped_run = _snap_axis(run_min, run_max, grid_origin_run, plane_run_min, plane_run_max)
    snapped_z = _snap_axis(z_min, z_max, grid_origin_z, plane_z_min, plane_z_max)
    snapped = (snapped_run[0], snapped_run[1], snapped_z[0], snapped_z[1])
    if snapped[1] - snapped[0] <= 1e-5 or snapped[3] - snapped[2] <= 1e-5:
        return tuple(round(value, 4) for value in cut_rect)
    return tuple(round(value, 4) for value in snapped)


def _canonical_wall_cut_rect(
    cut_rect: tuple[float, float, float, float],
    *,
    grid_origin_run: float | None = None,
    grid_origin_z: float | None = None,
    plane_run_min: float | None = None,
    plane_run_max: float | None = None,
    plane_z_min: float | None = None,
    plane_z_max: float | None = None,
) -> tuple[float, float, float, float]:
    expanded = _expanded_wall_cut_rect(cut_rect)
    if (
        grid_origin_run is None
        or grid_origin_z is None
        or plane_run_min is None
        or plane_run_max is None
        or plane_z_min is None
        or plane_z_max is None
    ):
        return expanded
    return _snap_rect_to_nearest_wall_grid_span(
        expanded,
        grid_origin_run=float(grid_origin_run),
        grid_origin_z=float(grid_origin_z),
        plane_run_min=float(plane_run_min),
        plane_run_max=float(plane_run_max),
        plane_z_min=float(plane_z_min),
        plane_z_max=float(plane_z_max),
    )


def _plane_axes_for_orientation(orientation: str) -> tuple[str, str]:
    return ("y", "x") if orientation == "X" else ("x", "y")


def _wall_opening_cut_metadata(
    *,
    kind: str,
    orientation: str,
    side_key: str,
    floor_index: int,
    slot_index: int,
    wall_pos: float,
    cut_rect: tuple[float, float, float, float],
    cut_rect_is_canonical: bool = False,
    grid_origin_run: float | None = None,
    grid_origin_z: float | None = None,
    plane_run_min: float | None = None,
    plane_run_max: float | None = None,
    plane_z_min: float | None = None,
    plane_z_max: float | None = None,
) -> dict[str, object]:
    normal_axis, run_axis = _plane_axes_for_orientation(orientation)
    run_min, run_max, z_min, z_max = (
        tuple(round(float(value), 4) for value in cut_rect)
        if cut_rect_is_canonical
        else _canonical_wall_cut_rect(
            cut_rect,
            grid_origin_run=grid_origin_run,
            grid_origin_z=grid_origin_z,
            plane_run_min=plane_run_min,
            plane_run_max=plane_run_max,
            plane_z_min=plane_z_min,
            plane_z_max=plane_z_max,
        )
    )
    return {
        "tbg_wall_opening_kind": str(kind),
        "tbg_wall_opening_side": str(side_key),
        "tbg_wall_opening_floor": int(floor_index),
        "tbg_wall_opening_slot": int(slot_index),
        "tbg_wall_cut_run_min": run_min,
        "tbg_wall_cut_run_max": run_max,
        "tbg_wall_cut_z_min": z_min,
        "tbg_wall_cut_z_max": z_max,
        "tbg_wall_plane_normal_axis": normal_axis,
        "tbg_wall_plane_run_axis": run_axis,
        "tbg_wall_plane_pos": round(float(wall_pos), 4),
    }


def _opening_cut_frame_envelope(
    opening_cut_metadata: dict[str, object] | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    if not opening_cut_metadata:
        return None, None, None, None
    try:
        cut_run_min = float(opening_cut_metadata["tbg_wall_cut_run_min"])
        cut_run_max = float(opening_cut_metadata["tbg_wall_cut_run_max"])
        cut_z_min = float(opening_cut_metadata["tbg_wall_cut_z_min"])
        cut_z_max = float(opening_cut_metadata["tbg_wall_cut_z_max"])
    except (KeyError, TypeError, ValueError):
        return None, None, None, None
    if cut_run_max <= cut_run_min or cut_z_max <= cut_z_min:
        return None, None, None, None
    # The wall-cut stamp is already the canonical, clearance-expanded
    # opening rect.  Seating frames on this exact envelope keeps visible
    # trim, door/window leaves, and V3 wall-cell cuts in one contract.
    return (
        (cut_run_min + cut_run_max) / 2.0,
        cut_run_max - cut_run_min,
        cut_z_max - cut_z_min,
        (cut_z_min + cut_z_max) / 2.0,
    )


def _door_visual_cut_rect(
    *,
    center_along: float,
    opening_width: float,
    base_z: float,
    opening_height: float,
) -> tuple[float, float, float, float]:
    outer_width, outer_height = _window_frame_outer_envelope(
        opening_width=float(opening_width),
        opening_height=float(opening_height),
        office_style=False,
    )
    center_z = float(base_z) + float(opening_height) / 2
    center_along = float(center_along)
    return (
        center_along - outer_width / 2,
        center_along + outer_width / 2,
        center_z - outer_height / 2,
        center_z + outer_height / 2,
    )


def _ordinary_door_cut_rect(
    *,
    center_x: float,
    opening_width: float,
    base_z: float,
    door_height: float,
) -> tuple[float, float, float, float]:
    return _door_visual_cut_rect(
        center_along=center_x,
        opening_width=opening_width,
        base_z=base_z,
        opening_height=door_height,
    )


def _ordinary_door_cut_metadata(
    *,
    side_key: str,
    orientation: str,
    wall_pos: float,
    center_x: float,
    opening_width: float,
    base_z: float,
    door_height: float,
    cut_rect: tuple[float, float, float, float] | None = None,
) -> dict[str, object]:
    return _wall_opening_cut_metadata(
        kind="door",
        orientation=orientation,
        side_key=side_key,
        floor_index=0,
        slot_index=-1,
        wall_pos=wall_pos,
        cut_rect=cut_rect
        or _ordinary_door_cut_rect(
            center_x=center_x,
            opening_width=opening_width,
            base_z=base_z,
            door_height=door_height,
        ),
    )


def _append_planned_wall_parts(
    parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    marker_parts: list[tuple[tuple[float, float, float], tuple[float, float, float], str, dict]] | None,
    planned_fragments: list[_PlannedWallFragment] | tuple[_PlannedWallFragment, ...],
) -> None:
    for planned_fragment in planned_fragments:
        part = (planned_fragment.local_size, planned_fragment.local_center)
        parts.append(part)
        if marker_parts is not None:
            marker_parts.append(
                (
                    planned_fragment.local_size,
                    planned_fragment.local_center,
                    planned_fragment.marker_role,
                    dict(planned_fragment.marker_metadata),
                )
            )

def _section_bucket_fragment(value: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in value)
    text = text.strip("_")
    return text or "slot"

def _balcony_section_bucket(side_key: str, floor_index: int, span_key: str) -> str:
    return (
        f"Section_Openings_Balcony_{_section_bucket_fragment(side_key)}"
        f"_F{max(0, int(floor_index)):02d}_{_section_bucket_fragment(span_key)}"
    )

def _append_wall_part(
    parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    *,
    start: float,
    end: float,
    base_z: float,
    height: float,
    wall_t: float,
    ref_along: float,
    ref_z: float,
    marker_parts: list[tuple[tuple[float, float, float], tuple[float, float, float], str, dict]] | None = None,
    marker_role: str = ROLE_SHELL,
    marker_metadata: dict | None = None,
):
    span = end - start
    if span <= 1e-4 or height <= 1e-4:
        return
    part = ((span, wall_t, height), (((start + end) / 2) - ref_along, 0.0, base_z + height / 2 - ref_z))
    parts.append(part)
    if marker_parts is not None:
        marker_parts.append((part[0], part[1], marker_role, dict(marker_metadata or {})))

def _use_wide_opening(spec, state: str, side_key: str, floor_index: int, slot_index: int, slot_width: float) -> bool:
    if state not in {WINDOW_STATE_CLOSED, WINDOW_STATE_OPEN}:
        return False
    if _is_storefront_frontage(spec) and side_key == "front" and floor_index > 0:
        return False
    roll = _stable_unit_float(spec.seed, "wide_opening", side_key, floor_index, slot_index)
    wide_ratio = max(0.0, min(1.0, float(spec.wide_window_ratio)))
    if _is_office_window_profile(spec.window_profile):
        return slot_width >= 1.45 and roll <= wide_ratio
    if _is_panoramic_window_profile(spec.window_profile):
        return slot_width >= 1.35
    if (
        _is_small_square_window_profile(spec.window_profile)
        or _is_tall_narrow_window_profile(spec.window_profile)
        or _is_multi_pane_window_profile(spec.window_profile)
    ):
        return False
    if _is_residential_wide(spec.window_profile):
        return side_key in {"front", "back", "left", "right"} and floor_index > 0 and slot_width >= 1.2 and roll <= wide_ratio
    if slot_width < 1.75 or floor_index == 0 or side_key not in {"front", "back"}:
        return False
    return roll <= wide_ratio

def _industrial_opening_profile(spec, slot_width: float, floor_height: float, *, side_key: str, floor_index: int):
    frontage_variant = _frontage_variant(spec)
    if frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_DEPOT:
        sill_h = 1.18
        opening_h = 1.0
        width_ratio = 0.72
        width_min = 0.92
        width_max = 1.9
        if side_key in {"front", "back"} or floor_index > 0:
            sill_h = max(0.92, sill_h - 0.08)
            opening_h = min(1.12, opening_h + 0.08)
    elif frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE:
        sill_h = 1.18
        opening_h = 1.08
        width_ratio = 0.8
        width_min = 1.16
        width_max = 2.4
        if side_key in {"left", "right"}:
            width_ratio = 0.84
            width_max = 2.46
    else:
        sill_h = 1.2
        opening_h = 1.0
        width_ratio = 0.74
        width_min = 1.0
        width_max = 2.1

    sill_h = min(floor_height - 0.44, sill_h)
    opening_h = min(opening_h, max(0.72, floor_height - sill_h - 0.2))
    top_h = max(0.22, floor_height - sill_h - opening_h)
    width_target = max(width_min, slot_width * width_ratio)
    width_cap = max(width_min, slot_width - min(0.18, slot_width * 0.12))
    opening_width = min(width_target, width_cap, width_max)
    return opening_width, sill_h, opening_h, top_h

def _market_hall_opening_profile(slot_width: float, floor_height: float, window_profile: str, *, floor_index: int):
    sill_h, opening_h, top_h = _window_verticals(floor_height, window_profile)
    width_target = max(0.72, slot_width * 0.5)
    width_cap = max(0.76, slot_width - min(0.26, slot_width * 0.2))
    width_max = 1.2
    if floor_index > 1:
        width_max = 1.0

    opening_width = min(width_target, width_cap, width_max)
    return opening_width, sill_h, opening_h, top_h

def _pharmacy_opening_profile(slot_width: float, floor_height: float, *, side_key: str, floor_index: int):
    if side_key == "front":
        sill_h = min(floor_height - 0.58, max(0.82, floor_height * 0.25))
        opening_h = min(1.26, max(0.98, floor_height - sill_h - 0.42))
        width_target = max(0.92, slot_width * 0.56)
        width_cap = max(0.82, slot_width - min(0.18, slot_width * 0.12))
        width_max = 1.32
    else:
        sill_h = min(floor_height - 0.6, max(0.76, floor_height * 0.23))
        opening_h = min(1.12, max(0.9, floor_height - sill_h - 0.46))
        width_target = max(0.82, slot_width * 0.48)
        width_cap = max(0.76, slot_width - min(0.16, slot_width * 0.1))
        width_max = 1.12
    if floor_index > 0:
        sill_h = min(floor_height - 0.56, sill_h + 0.08)
        opening_h = min(opening_h, max(0.84, floor_height - sill_h - 0.34))
    top_h = max(0.24, floor_height - sill_h - opening_h)
    opening_width = min(width_target, width_cap, width_max)
    return opening_width, sill_h, opening_h, top_h


def _ordinary_grid_safe_window_profile(slot_width: float, floor_height: float):
    """Ordinary framed windows must seat inside one stable 2x2 V3 wall-cell aperture."""

    opening_h = min(1.08, max(0.94, floor_height * 0.32))
    sill_h = min(
        max(0.82, floor_height - opening_h - 0.72),
        max(0.86, floor_height * 0.31),
    )
    sill_h = max(0.72, min(sill_h, floor_height - opening_h - 0.58))
    width_cap = max(0.72, slot_width - min(0.18, slot_width * 0.14))
    opening_width = min(width_cap, max(0.86, opening_h * 1.02), 1.08)
    top_h = max(0.58, floor_height - sill_h - opening_h)
    return opening_width, sill_h, opening_h, top_h


def _under_construction_opening_profile(slot_width: float, floor_height: float, window_profile: str, *, floor_index: int):
    sill_h, opening_h, top_h = _window_verticals(floor_height, window_profile)
    width_target = max(0.88, slot_width * 0.6)
    width_cap = max(0.72, slot_width - min(0.16, slot_width * 0.12))
    opening_width = min(width_target, width_cap, 1.34)
    return opening_width, sill_h, opening_h, top_h

def _slot_opening_profile(spec, state: str, slot_width: float, floor_height: float, *, side_key: str, floor_index: int, slot_index: int):
    if state == WINDOW_STATE_BALCONY:
        opening_width = max(0.92, slot_width - 0.12)
        sill_h = 0.0
        opening_h = min(2.34, max(2.13, floor_height - 0.42))
        top_h = max(0.24, floor_height - sill_h - opening_h)
        return opening_width, sill_h, opening_h, top_h

    if state == WINDOW_STATE_STAIR:
        opening_width = max(0.48, min(slot_width * 0.58, 0.72))
        sill_h = min(1.02, max(0.88, floor_height * 0.3))
        opening_h = min(1.14, max(0.96, floor_height - sill_h - 0.64))
        top_h = max(0.3, floor_height - sill_h - opening_h)
        return opening_width, sill_h, opening_h, top_h

    if _is_timber_frontage(spec) and state in {WINDOW_STATE_CLOSED, WINDOW_STATE_OPEN}:
        return _ordinary_grid_safe_window_profile(slot_width, floor_height)

    if _is_market_hall_frontage(spec) and (side_key != "front" or floor_index > 0) and state in {WINDOW_STATE_CLOSED, WINDOW_STATE_OPEN}:
        return _ordinary_grid_safe_window_profile(slot_width, floor_height)

    if _is_market_hall_frontage(spec) and side_key == "front":
        return _market_hall_opening_profile(
            slot_width,
            floor_height,
            spec.window_profile,
            floor_index=floor_index,
        )
    frontage_variant = _frontage_variant(spec)
    if frontage_variant == FRONTAGE_TYPE_STOREFRONT_PHARMACY:
        return _pharmacy_opening_profile(
            slot_width,
            floor_height,
            side_key=side_key,
            floor_index=floor_index,
        )
    if str(getattr(spec, "preset_id", "")).lower() == "under_construction":
        return _under_construction_opening_profile(
            slot_width,
            floor_height,
            spec.window_profile,
            floor_index=floor_index,
        )
    if _is_industrial_frontage(spec):
        return _industrial_opening_profile(
            spec,
            slot_width,
            floor_height,
            side_key=side_key,
            floor_index=floor_index,
        )

    sill_h, opening_h, top_h = _window_verticals(floor_height, spec.window_profile)
    if _is_panoramic_window_profile(spec.window_profile):
        opening_width = max(1.38, slot_width - min(0.04, slot_width * 0.03))
    elif _is_small_square_window_profile(spec.window_profile):
        opening_width = min(
            max(0.42, slot_width - min(0.12, slot_width * 0.14)),
            max(0.44, opening_h * 1.08),
        )
    elif _is_tall_narrow_window_profile(spec.window_profile):
        opening_width = min(
            max(0.48, slot_width - min(0.14, slot_width * 0.16)),
            max(0.5, opening_h * 0.54),
        )
    elif _is_multi_pane_window_profile(spec.window_profile):
        opening_width = min(
            max(0.82, slot_width - min(0.12, slot_width * 0.1)),
            max(0.92, opening_h * 1.02),
        )
    elif _use_wide_opening(spec, state, side_key, floor_index, slot_index, slot_width):
        opening_width = max(1.2, slot_width - min(0.08, slot_width * 0.04))
    else:
        opening_width = max(0.72, slot_width - min(0.18, slot_width * 0.14))
    return opening_width, sill_h, opening_h, top_h


def _terrace_exit_opening_profile(slot_width: float, floor_height: float) -> tuple[float, float, float, float]:
    opening_width = max(0.96, slot_width - 0.08)
    sill_h = 0.0
    opening_h = min(2.18, max(1.98, floor_height - 0.34))
    top_h = max(0.18, floor_height - sill_h - opening_h)
    return opening_width, sill_h, opening_h, top_h

def _build_multi_pane_mullions(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    along_coord: float,
    opening_width: float,
    opening_sill: float,
    opening_height: float,
    base_z: float,
    fill_depth: float,
    collection,
    parent,
    materials_map,
    *,
    window_profile: str,
    floor_index: int,
    slot_index: int,
    opening_cut_metadata: dict[str, object] | None = None,
):
    if not _is_multi_pane_window_profile(window_profile):
        return

    _ = opening_cut_metadata
    mid_z = base_z + opening_sill + opening_height / 2
    mullion_depth = max(OPENING_FRAME_MASS_MIN_DEPTH_STUDS, fill_depth + 0.004)
    vertical_width = max(OPENING_FRAME_MASS_MIN_DEPTH_STUDS, min(0.12, opening_width * 0.08))
    horizontal_height = max(OPENING_FRAME_MASS_MIN_DEPTH_STUDS, min(0.12, opening_height * 0.07))
    vertical_height = max(0.32, opening_height - 0.12)
    horizontal_width = max(0.32, opening_width - 0.12)
    horizontal_offsets = [0.0]
    if opening_height >= opening_width * 1.4:
        horizontal_offsets = [-opening_height * 0.2, opening_height * 0.2]

    mullion_specs = [
        ("Vertical", vertical_width, vertical_height, 0.0, 0.0),
        *(
            (f"Horizontal_{index:02d}", horizontal_width, horizontal_height, 0.0, offset)
            for index, offset in enumerate(horizontal_offsets)
        ),
    ]
    for label, width, height, along_offset, z_offset in mullion_specs:
        keep_observable = label == "Vertical" and floor_index == 0 and slot_index in {0, 1}
        mullion = _create_opening_box(
            _name(prefix, f"{suffix}_Mullion_{label}"),
            orientation,
            width,
            mullion_depth,
            height,
            along_coord + along_offset,
            wall_pos,
            mid_z + z_offset,
            collection,
            parent,
            materials_map["frame"],
        )
        _mark_section(
            _mark_generated(
                mullion,
                tbg_window_mullion=True,
                tbg_facade_side=side_key,
                tbg_facade_plane="center",
                tbg_facade_floor=int(floor_index),
                tbg_facade_slot=int(slot_index),
                **(opening_cut_metadata or {}),
            ),
            "Section_Openings_WindowFill",
            merge_allowed=not keep_observable and opening_cut_metadata is None,
        )

def _build_opening_trim(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    along_coord: float,
    opening_width: float,
    opening_sill: float,
    opening_height: float,
    base_z: float,
    wall_t: float,
    collection,
    parent,
    trim_material,
    *,
    office_style: bool,
    placement: str = "outer_proud",
    double_sided: bool = False,
    include_inner_returns: bool = True,
    outer_width_override: float | None = None,
    outer_height_override: float | None = None,
    inner_width_override: float | None = None,
    inner_height_override: float | None = None,
    opening_mid_z_override: float | None = None,
):
    outer_width, outer_height = _window_frame_outer_envelope(
        opening_width=opening_width,
        opening_height=opening_height,
        office_style=office_style,
    )
    if outer_width_override is not None and float(outer_width_override) > 0.0:
        outer_width = float(outer_width_override)
    if outer_height_override is not None and float(outer_height_override) > 0.0:
        outer_height = float(outer_height_override)
    if double_sided:
        trim_depth = wall_t + WINDOW_FRAME_PROUD_OFFSET + INNER_FRAME_PROUD_OFFSET
        trim_center = wall_pos + _side_sign(side_key) * (WINDOW_FRAME_PROUD_OFFSET - INNER_FRAME_PROUD_OFFSET) / 2
    else:
        trim_depth = max(
            OPENING_FRAME_MASS_MIN_DEPTH_STUDS,
            min(max(WINDOW_TRIM_DEPTH, OPENING_FRAME_MASS_MIN_DEPTH_STUDS), wall_t * (0.2 if office_style else 0.24)),
        )
        if placement == "inner_reveal":
            trim_center = _opening_inset_coord(
                side_key,
                wall_pos,
                wall_t,
                trim_depth,
                inset=WINDOW_TRIM_INSET + (0.004 if office_style else 0.0),
                interior=True,
            )
        elif placement == "inner_proud":
            trim_center = _surface_coord(
                side_key,
                wall_pos,
                wall_t,
                trim_depth,
                exterior=False,
                offset=INNER_FRAME_PROUD_OFFSET,
            )
        else:
            trim_center = _surface_coord(
                side_key,
                wall_pos,
                wall_t,
                trim_depth,
                exterior=True,
                offset=WINDOW_FRAME_PROUD_OFFSET,
            )
    inner_width = min(
        max(0.18, opening_width - WINDOW_FRAME_OVERLAP),
        max(0.18, outer_width - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2),
    )
    inner_height = min(
        max(0.18, opening_height - WINDOW_FRAME_OVERLAP),
        max(0.18, outer_height - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2),
    )
    if inner_width_override is not None and float(inner_width_override) > 0.0:
        inner_width = min(
            max(0.18, float(inner_width_override)),
            max(0.18, outer_width - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2),
        )
    if inner_height_override is not None and float(inner_height_override) > 0.0:
        inner_height = min(
            max(0.18, float(inner_height_override)),
            max(0.18, outer_height - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2),
        )
    opening_mid_z = (
        float(opening_mid_z_override)
        if opening_mid_z_override is not None
        else base_z + opening_sill + opening_height / 2
    )
    visible_positive_depth = _side_sign(side_key) > 0.0
    if not double_sided and placement.startswith("inner"):
        visible_positive_depth = not visible_positive_depth
    return _create_opening_frame(
        _name(prefix, f"{suffix}_Frame"),
        orientation,
        visible_positive_depth,
        outer_width,
        trim_depth,
        outer_height,
        inner_width,
        inner_height,
        along_coord,
        trim_center,
        opening_mid_z,
        collection,
        parent,
        trim_material,
        include_inner_returns=include_inner_returns,
        double_sided=double_sided,
    )


def _window_frame_outer_envelope(
    *,
    opening_width: float,
    opening_height: float,
    office_style: bool,
) -> tuple[float, float]:
    trim_half = max(0.09, min(WINDOW_TRIM_WIDTH, opening_width * (0.1 if office_style else 0.12)))
    outer_width = opening_width + trim_half * (1.95 if office_style else 2.15)
    outer_height = opening_height + trim_half * (1.68 if office_style else 1.92)
    return outer_width, outer_height


def _build_terrace_exit_transom_frame(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    along_coord: float,
    opening_width: float,
    opening_height: float,
    base_z: float,
    wall_t: float,
    collection,
    parent,
    frame_material,
    *,
    floor_index: int,
    slot_index: int,
    merge_allowed: bool = True,
    extra_metadata: dict | None = None,
):
    ring = float(OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS)
    jamb_width = max(ring, min(0.10, opening_width * 0.08))
    transom_height = max(ring, min(0.12, opening_height * 0.06))
    frame_depth = max(OPENING_FRAME_MASS_MIN_DEPTH_STUDS, float(wall_t) + 0.03)
    passage_width = max(0.0, float(opening_width))
    passage_height = max(0.0, float(opening_height))
    outer_width = passage_width + jamb_width * 2.0
    parts = [
        ((jamb_width, frame_depth, passage_height), (-passage_width / 2.0 - jamb_width / 2.0, 0.0, passage_height / 2.0)),
        ((jamb_width, frame_depth, passage_height), (passage_width / 2.0 + jamb_width / 2.0, 0.0, passage_height / 2.0)),
        ((outer_width, frame_depth, transom_height), (0.0, 0.0, passage_height + transom_height / 2.0)),
    ]
    frame = _create_composite_box_object(
        _name(prefix, f"{suffix}_TerraceTransomFrame"),
        parts,
        _opening_location(orientation, along_coord, wall_pos, float(base_z)),
        collection,
        parent,
        frame_material,
        rotation=_orientation_rotation(orientation),
    )
    metadata = {
        "tbg_terrace_exit": True,
        "tbg_terrace_top_owner_class": "TERRACE_TRANSOM_FRAME",
        "tbg_terrace_exit_side": side_key,
        "tbg_terrace_exit_floor": int(floor_index),
        "tbg_terrace_exit_slot": int(slot_index),
        "tbg_terrace_floor_z": float(round(base_z, 4)),
        "tbg_terrace_clear_passage_width": float(round(passage_width, 4)),
        "tbg_terrace_clear_passage_height": float(round(passage_height, 4)),
        "tbg_terrace_threshold_obstruction_height": 0.0,
        "tbg_terrace_no_threshold": True,
        "tbg_terrace_top_band_run_min": float(round(along_coord - outer_width / 2.0, 4)),
        "tbg_terrace_top_band_run_max": float(round(along_coord + outer_width / 2.0, 4)),
        "tbg_terrace_top_band_z_min": float(round(base_z + passage_height, 4)),
        "tbg_terrace_top_band_z_max": float(round(base_z + passage_height + transom_height, 4)),
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _mark_section(
        _mark_generated(
            frame,
            tbg_facade_side=side_key,
            tbg_facade_plane="both",
            tbg_facade_floor=int(floor_index),
            tbg_facade_slot=int(slot_index),
            **metadata,
        ),
        "Section_Openings_Frame",
        merge_allowed=merge_allowed,
    )


def _is_decorative_window_module(
    *,
    state: str,
    protect_opening: bool,
    terrace_exit: bool,
    balcony_span_key: str | None,
) -> bool:
    _ = state, protect_opening, terrace_exit, balcony_span_key
    return False


def _decorative_window_panel_mesh(
    name: str,
    *,
    width: float,
    height: float,
    grid_offset: float = 0.006,
):
    half_w = float(width) / 2.0
    half_h = float(height) / 2.0
    strip_w = max(0.035, min(0.07, float(width) * 0.08))
    strip_h = max(0.035, min(0.07, float(height) * 0.08))
    mid_w = max(0.028, strip_w * 0.68)
    mid_h = max(0.028, strip_h * 0.68)

    quads = [
        (-half_w, half_w, -half_h, half_h, 0.0),
        (-half_w, -half_w + strip_w, -half_h, half_h, grid_offset),
        (half_w - strip_w, half_w, -half_h, half_h, grid_offset),
        (-half_w, half_w, half_h - strip_h, half_h, grid_offset),
        (-half_w, half_w, -half_h, -half_h + strip_h, grid_offset),
        (-mid_w / 2.0, mid_w / 2.0, -half_h + strip_h, half_h - strip_h, grid_offset * 1.5),
        (-half_w + strip_w, half_w - strip_w, -mid_h / 2.0, mid_h / 2.0, grid_offset * 1.5),
    ]
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for x0, x1, z0, z1, y in quads:
        base = len(verts)
        verts.extend(
            (
                (x0, y, z0),
                (x1, y, z0),
                (x1, y, z1),
                (x0, y, z1),
            )
        )
        faces.append((base, base + 1, base + 2, base + 3))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    for polygon in mesh.polygons:
        polygon.material_index = 0
    return mesh


def _build_decorative_window_panel(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    along_coord: float,
    opening_width: float,
    opening_sill: float,
    opening_height: float,
    base_z: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    *,
    floor_index: int,
    slot_index: int,
    merge_allowed: bool = False,
    extra_metadata: dict | None = None,
    opening_cut_metadata: dict[str, object] | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    panel_along_coord = float(along_coord)
    cut_along_coord, cut_width, cut_height, cut_mid_z = _opening_cut_frame_envelope(opening_cut_metadata)
    if cut_along_coord is not None:
        panel_along_coord = cut_along_coord
    panel_width = max(0.34, float(cut_width) if cut_width is not None else opening_width + WINDOW_PANEL_OVERLAP * 1.6)
    panel_height = max(0.42, float(cut_height) if cut_height is not None else opening_height + WINDOW_PANEL_OVERLAP * 1.25)
    panel_depth = max(0.04, min(max(WINDOW_PANEL_THICKNESS * 1.8, wall_t * 0.26), 0.052))
    panel_mid_z = float(cut_mid_z) if cut_mid_z is not None else base_z + opening_sill + opening_height / 2.0
    mesh = _decorative_window_panel_mesh(_name(prefix, f"{suffix}_DecorativePanelMesh"), width=panel_width, height=panel_height)
    mesh.materials.append(materials_map["window_fill"])
    panel = bpy.data.objects.new(_name(prefix, f"{suffix}_DecorativePanel"), mesh)
    collection.objects.link(panel)
    _parent_to(panel, parent)
    panel.location = Vector(_opening_location(orientation, panel_along_coord, wall_pos, panel_mid_z))
    panel.rotation_euler = Euler(_orientation_rotation(orientation), "XYZ")
    _mark_section(
        _mark_generated(
            panel,
            tbg_decorative_window_panel=True,
            tbg_window_fill=True,
            tbg_window_mullion=True,
            tbg_window_fill_mode="matte",
            tbg_window_panel_style="decorative_grid_panel",
            tbg_window_fill_material=materials_map["window_fill"].name,
            tbg_facade_side=side_key,
            tbg_facade_plane="center",
            tbg_facade_floor=int(floor_index),
            tbg_facade_slot=int(slot_index),
            tbg_window_wall_pos=float(wall_pos),
            tbg_window_fill_centered=True,
            **(opening_cut_metadata or {}),
        ),
        "Section_Openings_WindowFill",
        merge_allowed=merge_allowed and opening_cut_metadata is None,
    )
    if extra_metadata:
        _mark_generated(panel, **extra_metadata)
    if runtime_emitter is not None:
        runtime_emitter.emit_box(
            role=ROLE_WINDOW_CLOSED,
            size=(panel_width, panel_depth, panel_height),
            location=_opening_location(orientation, panel_along_coord, wall_pos, panel_mid_z),
            rotation=_orientation_rotation(orientation),
            source_name=panel.name,
            metadata_values={
                "tbg_runtime_side": side_key,
                "tbg_runtime_floor": int(floor_index),
                "tbg_runtime_slot": int(slot_index),
            },
        )
    return panel


def _build_window_frame(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    along_coord: float,
    opening_width: float,
    opening_sill: float,
    opening_height: float,
    base_z: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    *,
    state: str,
    window_profile: str,
    floor_index: int,
    slot_index: int,
    merge_allowed: bool = True,
    extra_metadata: dict | None = None,
    opening_cut_metadata: dict[str, object] | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    office_style = _is_office_window_profile(window_profile)
    frame_along_coord = float(along_coord)
    cut_along_coord, frame_outer_width, frame_outer_height, frame_mid_z = _opening_cut_frame_envelope(
        opening_cut_metadata
    )
    if cut_along_coord is not None:
        frame_along_coord = cut_along_coord
    authored_outer_width, authored_outer_height = _window_frame_outer_envelope(
        opening_width=opening_width,
        opening_height=opening_height,
        office_style=office_style,
    )
    authored_inner_width = min(
        max(0.18, opening_width - WINDOW_FRAME_OVERLAP),
        max(0.18, authored_outer_width - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2),
    )
    authored_inner_height = min(
        max(0.18, opening_height - WINDOW_FRAME_OVERLAP),
        max(0.18, authored_outer_height - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2),
    )
    scaled_inner_width: float | None = None
    scaled_inner_height: float | None = None
    if frame_outer_width is not None and frame_outer_height is not None:
        width_scale = float(frame_outer_width) / max(0.01, float(authored_outer_width))
        height_scale = float(frame_outer_height) / max(0.01, float(authored_outer_height))
        scaled_inner_width = min(
            max(0.18, authored_inner_width * width_scale),
            max(0.18, float(frame_outer_width) - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2),
        )
        scaled_inner_height = min(
            max(0.18, authored_inner_height * height_scale),
            max(0.18, float(frame_outer_height) - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2),
        )
    frame = _build_opening_trim(
        prefix,
        suffix,
        orientation,
        side_key,
        wall_pos,
        frame_along_coord,
        opening_width,
        opening_sill,
        opening_height,
        base_z,
        wall_t,
        collection,
        parent,
        materials_map["frame"],
        office_style=office_style,
        placement="outer_proud",
        include_inner_returns=not office_style,
        double_sided=True,
        outer_width_override=frame_outer_width,
        outer_height_override=frame_outer_height,
        inner_width_override=scaled_inner_width,
        inner_height_override=scaled_inner_height,
        opening_mid_z_override=frame_mid_z,
    )
    if frame is not None:
        _mark_section(
            _mark_generated(
                frame,
                tbg_window_frame_outer=True,
                tbg_facade_side=side_key,
                tbg_facade_plane="both",
                tbg_facade_floor=int(floor_index),
                tbg_facade_slot=int(slot_index),
                tbg_window_wall_pos=float(wall_pos),
                **(opening_cut_metadata or {}),
            ),
            "Section_Openings_Frame",
            merge_allowed=merge_allowed and opening_cut_metadata is None,
        )
        if extra_metadata:
            _mark_generated(frame, **extra_metadata)
        frame["tbg_window_has_fill"] = False

    if state == WINDOW_STATE_OPEN:
        return frame

    visual_opening_width = float(scaled_inner_width) if scaled_inner_width is not None else float(opening_width)
    visual_opening_height = float(scaled_inner_height) if scaled_inner_height is not None else float(opening_height)
    fill_width = max(0.34, visual_opening_width + WINDOW_PANEL_OVERLAP * 1.6)
    fill_height = max(0.42, visual_opening_height + WINDOW_PANEL_OVERLAP * 1.25)
    if frame_outer_width is not None:
        fill_width = min(fill_width, max(0.34, float(frame_outer_width) - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2))
    if frame_outer_height is not None:
        fill_height = min(fill_height, max(0.42, float(frame_outer_height) - OPENING_FRAME_MASS_MIN_RING_WIDTH_STUDS * 2))
    fill_depth = max(0.04, min(max(WINDOW_PANEL_THICKNESS * 1.8, wall_t * 0.26), 0.052))
    fill_center = wall_pos
    fill_along_coord = frame_along_coord if cut_along_coord is not None else float(along_coord)
    mid_z = float(frame_mid_z) if frame_mid_z is not None else base_z + opening_sill + opening_height / 2
    fill = _create_opening_box(
        _name(prefix, f"{suffix}_Fill"),
        orientation,
        fill_width,
        fill_depth,
        fill_height,
        fill_along_coord,
        fill_center,
        mid_z,
        collection,
        parent,
        materials_map["window_fill"],
    )
    _mark_section(
        _mark_generated(
            fill,
            tbg_window_fill=True,
            tbg_window_fill_mode="matte",
            tbg_window_fill_material=materials_map["window_fill"].name,
            tbg_facade_side=side_key,
            tbg_facade_plane="center",
            tbg_facade_floor=int(floor_index),
            tbg_facade_slot=int(slot_index),
            tbg_window_wall_pos=float(wall_pos),
            tbg_window_fill_centered=True,
            **(opening_cut_metadata or {}),
        ),
        "Section_Openings_WindowFill",
        merge_allowed=merge_allowed and opening_cut_metadata is None,
    )
    if extra_metadata:
        _mark_generated(fill, **extra_metadata)
    if runtime_emitter is not None:
        runtime_emitter.emit_box(
            role=ROLE_WINDOW_CLOSED,
            size=(fill_width, fill_depth, fill_height),
            location=_opening_location(orientation, fill_along_coord, fill_center, mid_z),
            rotation=_orientation_rotation(orientation),
            source_name=fill.name,
            metadata_values={
                "tbg_runtime_side": side_key,
                "tbg_runtime_floor": int(floor_index),
                "tbg_runtime_slot": int(slot_index),
            },
        )
    if frame is not None:
        frame["tbg_window_has_fill"] = True
    _build_multi_pane_mullions(
        prefix,
        suffix,
        orientation,
        side_key,
        wall_pos,
        fill_along_coord,
        visual_opening_width,
        (mid_z - visual_opening_height / 2.0) - base_z,
        visual_opening_height,
        base_z,
        fill_depth,
        collection,
        parent,
        materials_map,
        window_profile=window_profile,
        floor_index=floor_index,
        slot_index=slot_index,
        opening_cut_metadata=opening_cut_metadata,
    )
    return frame or fill

def _build_balcony(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    along_coord: float,
    opening_width: float,
    base_z: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    *,
    facade_family: str,
    span_width: float | None = None,
    span_center: float | None = None,
    style: str = "SHORT",
    floor_index: int = 0,
    expected_bays: int = 1,
    span_key: str | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    _ = facade_family  # Balcony shader is global; family is retained for call compatibility.
    slab_width = max(opening_width + 0.9, span_width or 0.0)
    slab_depth = BALCONY_STRIP_DEPTH if style == "STRIP" else BALCONY_DEPTH
    slab_center_coord = along_coord if span_center is None else span_center
    slab_center = _surface_coord(side_key, wall_pos, wall_t, slab_depth, exterior=True, offset=0.08)
    slab_z = base_z + 0.08 - BALCONY_SLAB_THICKNESS / 2
    outward_sign = _side_sign(side_key)
    parapet_height = BALCONY_RAIL_HEIGHT
    parapet_thickness = BALCONY_RAIL_THICKNESS
    side_depth = slab_depth + 0.14
    parapet_z = parapet_height / 2 + BALCONY_SLAB_THICKNESS / 2 - 0.02
    parts = [
        ((slab_width, slab_depth, BALCONY_SLAB_THICKNESS), (0.0, 0.0, 0.0)),
        (
            (slab_width - 0.08, parapet_thickness, parapet_height),
            (0.0, outward_sign * (slab_depth / 2 - parapet_thickness / 2), parapet_z),
        ),
        (
            (parapet_thickness, side_depth, parapet_height),
            (-slab_width / 2 + parapet_thickness / 2, outward_sign * (slab_depth / 2 - side_depth / 2), parapet_z),
        ),
        (
            (parapet_thickness, side_depth, parapet_height),
            (slab_width / 2 - parapet_thickness / 2, outward_sign * (slab_depth / 2 - side_depth / 2), parapet_z),
        ),
    ]
    slab = _create_composite_box_object(
        _name(prefix, f"{suffix}_Balcony"),
        parts,
        _opening_location(orientation, slab_center_coord, slab_center, slab_z),
        collection,
        parent,
        materials_map["balcony"],
        rotation=_orientation_rotation(orientation),
    )
    _mark_section(
        _mark_generated(
            slab,
            tbg_balcony=True,
            tbg_balcony_side=side_key,
            tbg_balcony_style=style,
            tbg_balcony_span_width=float(round(slab_width, 4)),
            tbg_balcony_outward_sign=float(outward_sign),
            tbg_balcony_floor=int(floor_index),
            tbg_balcony_expected_bays=int(expected_bays),
            tbg_balcony_span_center=float(round(slab_center_coord, 4)),
            tbg_balcony_span_key=span_key or "",
        ),
        _balcony_section_bucket(side_key, floor_index, span_key or ""),
    )
    if runtime_emitter is not None and slab is not None:
        runtime_emitter.emit_composite_boxes(
            parts=parts,
            base_location=_opening_location(orientation, slab_center_coord, slab_center, slab_z),
            rotation=_orientation_rotation(orientation),
            roles=[ROLE_BALCONY_FLOOR, ROLE_BALCONY_RAIL, ROLE_BALCONY_RAIL, ROLE_BALCONY_RAIL],
            source_name=slab.name,
            metadata_values={
                "tbg_runtime_side": side_key,
                "tbg_runtime_floor": int(floor_index),
                "tbg_runtime_span_key": span_key or "",
            },
        )
    return slab

def _build_facade_ac(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    along_coord: float,
    opening_width: float,
    sill_h: float,
    base_z: float,
    wall_t: float,
    collection,
    parent,
    prop_material,
    *,
    floor_index: int,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    ac_width = max(0.34, min(0.62, opening_width * 0.45))
    ac_height = 0.36
    ac_center = _surface_coord(side_key, wall_pos, wall_t, AC_DEPTH, exterior=True, offset=0.05)
    ac_z = base_z + max(0.36, sill_h - ac_height / 2 - 0.1)
    face_offset = _side_sign(side_key) * 0.012
    grille_height = ac_height * 0.14
    quads = [
        (-ac_width / 2, ac_width / 2, -ac_height / 2, ac_height / 2, 0.0),
        (-ac_width * 0.38, ac_width * 0.38, -grille_height / 2, grille_height / 2, face_offset),
        (-ac_width * 0.38, ac_width * 0.38, ac_height * 0.18, ac_height * 0.18 + grille_height, face_offset * 1.5),
    ]
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for x0, x1, z0, z1, y in quads:
        base = len(verts)
        verts.extend(((x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)))
        faces.append((base, base + 1, base + 2, base + 3))
    mesh = bpy.data.meshes.new(_name(prefix, f"{suffix}_FacadeACMesh"))
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(prop_material)
    unit = bpy.data.objects.new(_name(prefix, f"{suffix}_FacadeAC"), mesh)
    collection.objects.link(unit)
    _parent_to(unit, parent)
    unit.location = Vector(_opening_location(orientation, along_coord, ac_center, ac_z))
    unit.rotation_euler = Euler(_orientation_rotation(orientation), "XYZ")
    _mark_section(_mark_generated(unit, tbg_facade_ac=True), "Section_Services_Prop")
    unit["tbg_facade_side"] = side_key
    unit["tbg_facade_floor"] = int(floor_index)
    unit["tbg_facade_along"] = float(round(along_coord, 4))
    unit["tbg_facade_half_span"] = float(round(ac_width / 2, 4))
    if runtime_emitter is not None:
        runtime_emitter.emit_box(
            role=ROLE_PROP_BOX,
            size=(ac_width, AC_DEPTH, ac_height),
            location=_opening_location(orientation, along_coord, ac_center, ac_z),
            rotation=_orientation_rotation(orientation),
            source_name=unit.name,
            metadata_values={
                "tbg_runtime_side": side_key,
                "tbg_runtime_floor": int(floor_index),
                "tbg_runtime_feature": "facade_ac",
            },
        )

def _build_masked_window_slot(
    prefix,
    suffix,
    orientation: str,
    wall_pos: float,
    slot_min: float,
    slot_max: float,
    base_z: float,
    floor_height: float,
    wall_t: float,
    collection,
    parent,
    wall_material,
    *,
    marker_metadata: dict,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    slot_width = slot_max - slot_min
    segment_name = _name(prefix, f"{suffix}_Mask")
    _register_linear_wall_plane(
        occupancy_author,
        orientation=orientation,
        wall_pos=wall_pos,
        start=slot_min,
        end=slot_max,
        base_z=base_z,
        height=floor_height,
        wall_t=wall_t,
        material=wall_material,
        source_bucket="Section_Walls_Exterior",
        source_name=f"{segment_name}:plane",
        staged_object_name=segment_name,
    )
    planned_fragment = _plan_linear_wall_fragment(
        orientation=orientation,
        wall_pos=wall_pos,
        start=slot_min,
        end=slot_max,
        base_z=base_z,
        height=floor_height,
        wall_t=wall_t,
        ref_along=(slot_min + slot_max) / 2,
        ref_z=base_z + floor_height / 2,
        material=wall_material,
        source_bucket="Section_Walls_Exterior",
        source_name=f"{segment_name}:mask",
        staged_object_name=segment_name,
        marker_metadata=marker_metadata,
    )
    segment = _create_wall_segment(
        segment_name,
        orientation,
        wall_pos,
        slot_min,
        slot_max,
        base_z,
        floor_height,
        wall_t,
        collection,
        parent,
        wall_material,
    )
    segment = _mark_wall_section(segment, "Section_Walls_Exterior")
    if runtime_emitter is not None and segment is not None:
        runtime_emitter.emit_box(
            role=ROLE_SHELL,
            size=(slot_width, wall_t, floor_height) if orientation == "X" else (wall_t, slot_width, floor_height),
            location=tuple(float(value) for value in segment.location),
            rotation=tuple(float(value) for value in segment.rotation_euler),
            source_name=segment.name,
            metadata_values=marker_metadata,
        )

def _build_window_slot_shell(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    slot_min: float,
    slot_max: float,
    base_z: float,
    floor_height: float,
    wall_t: float,
    collection,
    parent,
    wall_material,
    *,
    spec,
    state: str,
    opening_width: float,
    sill_h: float,
    opening_h: float,
    top_h: float,
    floor_index: int,
    slot_index: int,
    marker_metadata: dict,
    occupancy_author: OccupancyAuthoringSession | None = None,
    cut_rect: tuple[float, float, float, float] | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    slot_center = (slot_min + slot_max) / 2
    reveal = max(0.0, (slot_max - slot_min - opening_width) / 2)
    # Stage 4A cuboid-authoritative rule: same-plane authored shell pieces must
    # meet exactly, not overlap. The old shell overlap padding was only masking
    # visual seams; under canonical cuboid payloads it becomes duplicate facade
    # registration against adjacent pier spans.
    lateral_overlap = 0.0
    vertical_overlap = 0.0
    facade_mid_z = base_z + floor_height / 2
    open_min = slot_center - opening_width / 2
    open_max = slot_center + opening_width / 2
    cut_min, cut_max, cut_z_min, cut_z_max = cut_rect or _window_visual_cut_rect(
        spec=spec,
        state=state,
        side_key=side_key,
        floor_index=floor_index,
        slot_index=slot_index,
        slot_min=slot_min,
        slot_max=slot_max,
        base_z=base_z,
        floor_height=floor_height,
        opening_width=opening_width,
        sill_h=sill_h,
        opening_h=opening_h,
    )
    wall_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    wall_marker_parts: list[tuple[tuple[float, float, float], tuple[float, float, float], str, dict]] = []
    planned_name = _name(prefix, f"{suffix}_Wall")
    _register_linear_wall_plane(
        occupancy_author,
        orientation=orientation,
        wall_pos=wall_pos,
        start=slot_min,
        end=slot_max,
        base_z=base_z,
        height=floor_height,
        wall_t=wall_t,
        material=wall_material,
        source_bucket="Section_Walls_Exterior",
        source_name=f"{planned_name}:plane",
        staged_object_name=planned_name,
        rect_cuts=(("opening", cut_min, cut_max, cut_z_min, cut_z_max, 0.0),),
    )
    planned_fragments: list[_PlannedWallFragment] = []

    if reveal > 1e-4:
        planned_fragment = _plan_linear_wall_fragment(
            orientation=orientation,
            wall_pos=wall_pos,
            start=slot_min,
            end=slot_min + reveal + lateral_overlap,
            base_z=base_z,
            height=floor_height,
            wall_t=wall_t,
            ref_along=slot_center,
            ref_z=facade_mid_z,
            material=wall_material,
            source_bucket="Section_Walls_Exterior",
            source_name=f"{planned_name}:left",
            staged_object_name=planned_name,
            marker_metadata={**marker_metadata, "tbg_runtime_part": "left"},
        )
        if planned_fragment is not None:
            planned_fragments.append(planned_fragment)
        planned_fragment = _plan_linear_wall_fragment(
            orientation=orientation,
            wall_pos=wall_pos,
            start=slot_max - reveal - lateral_overlap,
            end=slot_max,
            base_z=base_z,
            height=floor_height,
            wall_t=wall_t,
            ref_along=slot_center,
            ref_z=facade_mid_z,
            material=wall_material,
            source_bucket="Section_Walls_Exterior",
            source_name=f"{planned_name}:right",
            staged_object_name=planned_name,
            marker_metadata={**marker_metadata, "tbg_runtime_part": "right"},
        )
        if planned_fragment is not None:
            planned_fragments.append(planned_fragment)

    if sill_h > 0.0:
        planned_fragment = _plan_linear_wall_fragment(
            orientation=orientation,
            wall_pos=wall_pos,
            start=open_min,
            end=open_max,
            base_z=base_z,
            height=sill_h + vertical_overlap,
            wall_t=wall_t,
            ref_along=slot_center,
            ref_z=facade_mid_z,
            material=wall_material,
            source_bucket="Section_Walls_Exterior",
            source_name=f"{planned_name}:sill",
            staged_object_name=planned_name,
            marker_role=ROLE_SHELL,
            marker_metadata={**marker_metadata, "tbg_runtime_part": "sill"},
        )
        if planned_fragment is not None:
            planned_fragments.append(planned_fragment)
    if top_h > 0.0:
        planned_fragment = _plan_linear_wall_fragment(
            orientation=orientation,
            wall_pos=wall_pos,
            start=open_min,
            end=open_max,
            base_z=base_z + sill_h + opening_h - vertical_overlap,
            height=top_h + vertical_overlap,
            wall_t=wall_t,
            ref_along=slot_center,
            ref_z=facade_mid_z,
            material=wall_material,
            source_bucket="Section_Walls_Exterior",
            source_name=f"{planned_name}:top",
            staged_object_name=planned_name,
            marker_metadata={**marker_metadata, "tbg_runtime_part": "top"},
        )
        if planned_fragment is not None:
            planned_fragments.append(planned_fragment)
    if not planned_fragments:
        return
    _append_planned_wall_parts(wall_parts, wall_marker_parts, planned_fragments)

    wall_obj = _create_composite_box_object(
        planned_name,
        wall_parts,
        _opening_location(orientation, slot_center, wall_pos, facade_mid_z),
        collection,
        parent,
        wall_material,
        rotation=_orientation_rotation(orientation),
    )
    if wall_obj is None:
        return

    _mark_section(wall_obj, "Section_Walls_Exterior")
    wall_obj["tbg_facade_side"] = side_key
    wall_obj["tbg_facade_floor"] = int(floor_index)
    wall_obj["tbg_facade_slot"] = int(slot_index)
    if runtime_emitter is None:
        return

    collision_parts: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    collision_roles: list[str] = []
    collision_metadata: list[dict] = []
    for size, local_center, role, metadata_values in wall_marker_parts:
        if role == ROLE_SHELL and state == WINDOW_STATE_BALCONY and metadata_values.get("tbg_runtime_part") == "sill":
            continue
        collision_parts.append((size, local_center))
        collision_roles.append(role)
        collision_metadata.append(metadata_values)
    if collision_parts:
        runtime_emitter.emit_composite_boxes(
            parts=collision_parts,
            base_location=_opening_location(orientation, slot_center, wall_pos, facade_mid_z),
            rotation=_orientation_rotation(orientation),
            roles=collision_roles,
            source_name=wall_obj.name,
            metadata_values=marker_metadata,
            per_part_metadata=collision_metadata,
        )

def _build_window_slot_visual(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    slot_center: float,
    base_z: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    spec,
    *,
    state: str,
    protect_opening: bool,
    floor_index: int,
    slot_index: int,
    balcony_span_key: str | None,
    opening_width: float,
    sill_h: float,
    opening_h: float,
    merge_allowed: bool = True,
    extra_metadata: dict | None = None,
    terrace_exit: bool = False,
    opening_cut_metadata: dict[str, object] | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    runtime_state = WINDOW_STATE_OPEN if terrace_exit and state == WINDOW_STATE_BALCONY else state
    if terrace_exit:
        window_marker = _build_terrace_exit_transom_frame(
            prefix,
            suffix,
            orientation,
            side_key,
            wall_pos,
            slot_center,
            opening_width,
            opening_h,
            base_z,
            wall_t,
            collection,
            parent,
            materials_map["frame"],
            floor_index=floor_index,
            slot_index=slot_index,
            merge_allowed=False,
            extra_metadata=extra_metadata,
        )
    elif _is_decorative_window_module(
        state=runtime_state,
        protect_opening=protect_opening,
        terrace_exit=terrace_exit,
        balcony_span_key=balcony_span_key,
    ):
        window_marker = _build_decorative_window_panel(
            prefix,
            suffix,
            orientation,
            side_key,
            wall_pos,
            slot_center,
            opening_width,
            sill_h,
            opening_h,
            base_z,
            wall_t,
            collection,
            parent,
            materials_map,
            floor_index=floor_index,
            slot_index=slot_index,
            merge_allowed=merge_allowed,
            extra_metadata=extra_metadata,
            opening_cut_metadata=opening_cut_metadata,
            runtime_emitter=runtime_emitter,
        )
    else:
        window_marker = _build_window_frame(
            prefix,
            suffix,
            orientation,
            side_key,
            wall_pos,
            slot_center,
            opening_width,
            sill_h,
            opening_h,
            base_z,
            wall_t,
            collection,
            parent,
            materials_map,
            state=WINDOW_STATE_OPEN if runtime_state == WINDOW_STATE_BALCONY else runtime_state,
            window_profile=spec.window_profile,
            floor_index=floor_index,
            slot_index=slot_index,
            merge_allowed=merge_allowed,
            extra_metadata=extra_metadata,
            opening_cut_metadata=opening_cut_metadata,
            runtime_emitter=runtime_emitter,
        )
    if window_marker is None:
        return None

    _mark_generated(
        window_marker,
        tbg_window_marker=True,
        tbg_window_open=bool(runtime_state in {WINDOW_STATE_OPEN, WINDOW_STATE_BALCONY}),
        tbg_window_side=side_key,
        tbg_window_floor=int(floor_index),
        tbg_window_state=runtime_state,
        tbg_balcony_access=bool(runtime_state == WINDOW_STATE_BALCONY),
        tbg_balcony_span_key=balcony_span_key or "",
        tbg_window_reserved_open=bool(
            protect_opening
            or runtime_state == WINDOW_STATE_BALCONY
            or (runtime_state == WINDOW_STATE_OPEN and bool(balcony_span_key))
        ),
        tbg_window_reserved_closed=bool(runtime_state == WINDOW_STATE_STAIR),
        tbg_window_sill_height=float(round(sill_h, 4)),
        tbg_window_opening_height=float(round(opening_h, 4)),
        tbg_window_opening_width=float(round(opening_width, 4)),
        **(opening_cut_metadata or {}),
    )
    return window_marker

def _emit_window_slot_opening_marker(
    runtime_emitter: RuntimeMarkerEmitter | None,
    role: str,
    *,
    orientation: str,
    slot_center: float,
    wall_pos: float,
    base_z: float,
    wall_t: float,
    opening_width: float,
    sill_h: float,
    opening_h: float,
    source_name: str,
    marker_metadata: dict,
):
    if runtime_emitter is None:
        return
    runtime_emitter.emit_box(
        role=role,
        size=(opening_width, wall_t, opening_h),
        location=_opening_location(orientation, slot_center, wall_pos, base_z + sill_h + opening_h / 2),
        rotation=_orientation_rotation(orientation),
        source_name=source_name,
        collidable=False,
        metadata_values=marker_metadata,
    )

def _build_custom_window_slot(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    slot_min: float,
    slot_max: float,
    base_z: float,
    floor_height: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    spec,
    *,
    state: str,
    protect_opening: bool,
    floor_index: int,
    slot_index: int,
    opening_width: float,
    sill_h: float,
    opening_h: float,
    balcony_span_key: str | None = None,
    merge_allowed: bool = True,
    extra_metadata: dict | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    if state == WINDOW_STATE_BALCONY:
        opening_h = float(opening_h) + float(sill_h)
        sill_h = 0.0
    top_h = max(0.0, floor_height - sill_h - opening_h)
    return _build_window_slot_core(
        prefix,
        suffix,
        orientation,
        side_key,
        wall_pos,
        slot_min,
        slot_max,
        base_z,
        floor_height,
        wall_t,
        collection,
        parent,
        materials_map,
        spec,
        state=state,
        place_ac=False,
        protect_opening=protect_opening,
        floor_index=floor_index,
        slot_index=slot_index,
        opening_width=opening_width,
        sill_h=sill_h,
        opening_h=opening_h,
        top_h=top_h,
        balcony_span_key=balcony_span_key,
        merge_allowed=merge_allowed,
        extra_metadata=extra_metadata,
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
    )

def _build_window_slot_attachments(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    slot_center: float,
    base_z: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    spec,
    *,
    state: str,
    place_ac: bool,
    floor_index: int,
    balcony_span_width: float | None,
    balcony_span_center: float | None,
    balcony_style: str,
    balcony_expected_bays: int,
    balcony_span_key: str | None,
    opening_width: float,
    sill_h: float,
    protect_opening: bool,
    terrace_exit: bool,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    if state == WINDOW_STATE_BALCONY and not terrace_exit:
        _build_balcony(
            prefix,
            suffix,
            orientation,
            side_key,
            wall_pos,
            slot_center,
            opening_width,
            base_z,
            wall_t,
            collection,
            parent,
            materials_map,
            facade_family=spec.facade_family,
            span_width=balcony_span_width,
            span_center=balcony_span_center,
            style=balcony_style,
            floor_index=floor_index,
            expected_bays=balcony_expected_bays,
            span_key=balcony_span_key,
            runtime_emitter=runtime_emitter,
        )

    if place_ac:
        _build_facade_ac(
            prefix,
            suffix,
            orientation,
            side_key,
            wall_pos,
            slot_center,
            opening_width,
            sill_h,
            base_z,
            wall_t,
            collection,
            parent,
            materials_map["prop"],
            floor_index=floor_index,
            runtime_emitter=runtime_emitter,
        )

def _build_window_slot_core(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    slot_min: float,
    slot_max: float,
    base_z: float,
    floor_height: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    spec,
    *,
    state: str,
    place_ac: bool,
    protect_opening: bool,
    floor_index: int,
    slot_index: int,
    opening_width: float,
    sill_h: float,
    opening_h: float,
    top_h: float,
    balcony_span_width: float | None = None,
    balcony_span_center: float | None = None,
    balcony_style: str = "SHORT",
    balcony_expected_bays: int = 1,
    balcony_span_key: str | None = None,
    merge_allowed: bool = True,
    extra_metadata: dict | None = None,
    terrace_exit: bool = False,
    stamp_opening_cut: bool = True,
    wall_plane_start: float | None = None,
    wall_plane_end: float | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    slot_center = (slot_min + slot_max) / 2
    wall_material = _wall_material_for_floor(materials_map, spec, floor_index)
    effective_span_key = None if terrace_exit else balcony_span_key
    marker_metadata = {
        "tbg_runtime_side": side_key,
        "tbg_runtime_floor": int(floor_index),
        "tbg_runtime_slot": int(slot_index),
        "tbg_runtime_span_key": effective_span_key or "",
    }
    terrace_exit_metadata = (
        {
            "tbg_terrace_exit": True,
            "tbg_terrace_top_owner_class": "TERRACE_TRANSOM_FRAME",
            "tbg_terrace_exit_side": side_key,
            "tbg_terrace_exit_floor": int(floor_index),
            "tbg_terrace_exit_slot": int(slot_index),
        }
        if terrace_exit
        else {}
    )

    if state == WINDOW_STATE_MASK:
        _build_masked_window_slot(
            prefix,
            suffix,
            orientation,
            wall_pos,
            slot_min,
            slot_max,
            base_z,
            floor_height,
            wall_t,
            collection,
            parent,
            wall_material,
            marker_metadata=marker_metadata,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )
        return None

    window_cut_rect = _window_visual_cut_rect(
        spec=spec,
        state=state,
        side_key=side_key,
        floor_index=floor_index,
        slot_index=slot_index,
        slot_min=slot_min,
        slot_max=slot_max,
        base_z=base_z,
        floor_height=floor_height,
        opening_width=opening_width,
        sill_h=sill_h,
        opening_h=opening_h,
    )
    floor_flush_opening = terrace_exit or state == WINDOW_STATE_BALCONY
    if floor_flush_opening:
        window_cut_rect = (
            float(window_cut_rect[0]),
            float(window_cut_rect[1]),
            float(base_z),
            float(base_z + floor_height) if terrace_exit else float(window_cut_rect[3]),
        )
    floor_grid_z = float(_level_base_z(spec, floor_index))
    canonical_cut_rect = _canonical_wall_cut_rect(
        window_cut_rect,
        grid_origin_run=float(wall_plane_start) if wall_plane_start is not None else None,
        grid_origin_z=floor_grid_z,
        plane_run_min=float(wall_plane_start) if wall_plane_start is not None else None,
        plane_run_max=float(wall_plane_end) if wall_plane_end is not None else None,
        plane_z_min=floor_grid_z,
        plane_z_max=floor_grid_z + float(floor_height),
    )
    opening_cut_metadata = (
        _wall_opening_cut_metadata(
            kind="window",
            orientation=orientation,
            side_key=side_key,
            floor_index=floor_index,
            slot_index=slot_index,
            wall_pos=wall_pos,
            cut_rect=canonical_cut_rect,
            cut_rect_is_canonical=True,
        )
        if stamp_opening_cut
        else None
    )
    if terrace_exit and opening_cut_metadata is not None:
        opening_cut_metadata["tbg_wall_cut_z_min"] = round(float(base_z), 4)
        opening_cut_metadata["tbg_wall_cut_z_max"] = round(float(base_z + floor_height), 4)

    _build_window_slot_shell(
        prefix,
        suffix,
        orientation,
        side_key,
        wall_pos,
        slot_min,
        slot_max,
        base_z,
        floor_height,
        wall_t,
        collection,
        parent,
        wall_material,
        spec=spec,
        state=state,
        opening_width=opening_width,
        sill_h=sill_h,
        opening_h=opening_h,
        top_h=top_h,
        floor_index=floor_index,
        slot_index=slot_index,
        marker_metadata=marker_metadata,
        occupancy_author=occupancy_author,
        cut_rect=canonical_cut_rect,
        runtime_emitter=runtime_emitter,
    )
    window_marker = _build_window_slot_visual(
        prefix,
        suffix,
        orientation,
        side_key,
        wall_pos,
        slot_center,
        base_z,
        wall_t,
        collection,
        parent,
        materials_map,
        spec,
        state=state,
        protect_opening=protect_opening,
        floor_index=floor_index,
        slot_index=slot_index,
        balcony_span_key=effective_span_key,
        opening_width=opening_width,
        sill_h=sill_h,
        opening_h=opening_h,
        merge_allowed=merge_allowed,
        extra_metadata={**(extra_metadata or {}), **terrace_exit_metadata},
        terrace_exit=terrace_exit,
        opening_cut_metadata=opening_cut_metadata,
        runtime_emitter=runtime_emitter,
    )

    source_name = str(window_marker.name if window_marker is not None else suffix)
    if state == WINDOW_STATE_BALCONY and not terrace_exit:
        _emit_window_slot_opening_marker(
            runtime_emitter,
            ROLE_BALCONY_ACCESS_OPENING,
            orientation=orientation,
            slot_center=slot_center,
            wall_pos=wall_pos,
            base_z=base_z,
            wall_t=wall_t,
            opening_width=opening_width,
            sill_h=sill_h,
            opening_h=opening_h,
            source_name=source_name,
            marker_metadata=marker_metadata,
        )
    if state == WINDOW_STATE_OPEN or terrace_exit:
        _emit_window_slot_opening_marker(
            runtime_emitter,
            ROLE_OPEN_WINDOW_OPENING,
            orientation=orientation,
            slot_center=slot_center,
            wall_pos=wall_pos,
            base_z=base_z,
            wall_t=wall_t,
            opening_width=opening_width,
            sill_h=sill_h,
            opening_h=opening_h,
            source_name=source_name,
            marker_metadata=marker_metadata,
        )

    _build_window_slot_attachments(
        prefix,
        suffix,
        orientation,
        side_key,
        wall_pos,
        slot_center,
        base_z,
        wall_t,
        collection,
        parent,
        materials_map,
        spec,
        state=state,
        place_ac=place_ac,
        floor_index=floor_index,
        balcony_span_width=balcony_span_width,
        balcony_span_center=balcony_span_center,
        balcony_style=balcony_style,
        balcony_expected_bays=balcony_expected_bays,
        balcony_span_key=effective_span_key,
        opening_width=opening_width,
        sill_h=sill_h,
        protect_opening=protect_opening,
        terrace_exit=terrace_exit,
        runtime_emitter=runtime_emitter,
    )
    return window_marker

def _build_window_slot(
    prefix,
    suffix,
    orientation: str,
    side_key: str,
    wall_pos: float,
    slot_min: float,
    slot_max: float,
    base_z: float,
    floor_height: float,
    wall_t: float,
    collection,
    parent,
    materials_map,
    spec,
    *,
    state: str,
    place_ac: bool,
    protect_opening: bool,
    floor_index: int,
    slot_index: int,
    balcony_span_width: float | None = None,
    balcony_span_center: float | None = None,
    balcony_style: str = "SHORT",
    balcony_expected_bays: int = 1,
    balcony_span_key: str | None = None,
    terrace_exit: bool = False,
    profile_floor_height: float | None = None,
    stamp_opening_cut: bool = True,
    wall_plane_start: float | None = None,
    wall_plane_end: float | None = None,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    slot_width = slot_max - slot_min
    effective_state = WINDOW_STATE_OPEN if terrace_exit and state == WINDOW_STATE_BALCONY else state
    if terrace_exit:
        opening_width, sill_h, opening_h, top_h = _terrace_exit_opening_profile(slot_width, floor_height)
    else:
        opening_profile_height = float(profile_floor_height) if profile_floor_height is not None else float(floor_height)
        opening_width, sill_h, opening_h, top_h = _slot_opening_profile(
            spec,
            effective_state,
            slot_width,
            opening_profile_height,
            side_key=side_key,
            floor_index=floor_index,
            slot_index=slot_index,
        )
        top_h = max(0.0, float(floor_height) - float(sill_h) - float(opening_h))
        if top_h <= 0.0:
            opening_h = max(0.42, float(floor_height) - float(sill_h) - 0.02)
            top_h = max(0.0, float(floor_height) - float(sill_h) - float(opening_h))
        if effective_state == WINDOW_STATE_BALCONY:
            opening_h = float(opening_h) + float(sill_h)
            sill_h = 0.0
            top_h = max(0.0, float(floor_height) - float(opening_h))
    _build_window_slot_core(
        prefix,
        suffix,
        orientation,
        side_key,
        wall_pos,
        slot_min,
        slot_max,
        base_z,
        floor_height,
        wall_t,
        collection,
        parent,
        materials_map,
        spec,
        state=effective_state,
        place_ac=place_ac,
        protect_opening=protect_opening,
        floor_index=floor_index,
        slot_index=slot_index,
        opening_width=opening_width,
        sill_h=sill_h,
        opening_h=opening_h,
        top_h=top_h,
        balcony_span_width=balcony_span_width,
        balcony_span_center=balcony_span_center,
        balcony_style=balcony_style,
        balcony_expected_bays=balcony_expected_bays,
        balcony_span_key=balcony_span_key,
        terrace_exit=terrace_exit,
        stamp_opening_cut=stamp_opening_cut,
        wall_plane_start=wall_plane_start,
        wall_plane_end=wall_plane_end,
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
    )
    return bool(place_ac)

create_opening_frame = _create_opening_frame
create_opening_box = _create_opening_box
create_wall_segment = _create_wall_segment
slot_opening_profile = _slot_opening_profile
build_opening_trim = _build_opening_trim
build_window_frame = _build_window_frame
build_balcony = _build_balcony
build_facade_ac = _build_facade_ac
build_masked_window_slot = _build_masked_window_slot
build_custom_window_slot = _build_custom_window_slot
build_window_slot = _build_window_slot
register_linear_wall_plane = _register_linear_wall_plane
window_visual_cut_rect = _window_visual_cut_rect
canonical_wall_cut_rect = _canonical_wall_cut_rect
wall_opening_cut_metadata = _wall_opening_cut_metadata
door_visual_cut_rect = _door_visual_cut_rect
ordinary_door_cut_rect = _ordinary_door_cut_rect
ordinary_door_cut_metadata = _ordinary_door_cut_metadata
opening_cut_frame_envelope = _opening_cut_frame_envelope
