from __future__ import annotations

import math
from dataclasses import dataclass

from .. import constants
from ..export_contract import ROLE_SHELL
from .building_facade_opening_slots import (
    build_opening_trim as _build_opening_trim,
    build_custom_window_slot as _build_custom_window_slot,
    opening_cut_frame_envelope as _opening_cut_frame_envelope,
    ordinary_door_cut_rect as _ordinary_door_cut_rect,
    wall_opening_cut_metadata as _wall_opening_cut_metadata,
    register_linear_wall_plane as _register_linear_wall_plane,
    create_opening_box as _create_opening_box,
    slot_opening_profile as _slot_opening_profile,
)
from .building_facade_frontage_recipes import (
    build_front_entry_frame as _build_front_entry_frame,
    emit_front_wall_piece as _emit_front_wall_piece,
    emit_frontage_shell_piece as _emit_frontage_shell_piece,
)
from .building_layout import (
    FRONTAGE_TYPE_INDUSTRIAL_DEPOT,
    FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE,
    REAR_ACCESS_PROFILE_NONE,
    REAR_ACCESS_PROFILE_OPEN_BAY,
    REAR_ACCESS_PROFILE_SERVICE_DOOR,
    WINDOW_STATE_CLOSED,
    WINDOW_STATE_OPEN,
    _base_elevation,
    _orientation_rotation,
    _spatial_plan,
    _surface_coord,
)
from .building_support import (
    _create_box,
    _mark_door_leaf,
    _mark_generated,
    _mark_section,
    _mark_wall_section,
    _name,
)
from .runtime_markers import RuntimeMarkerEmitter
from .layout_facade_planning import _front_entry_envelope, _rear_entry_opening_contract, _wall_material_for_floor
from .building_occupancy import OccupancyAuthoringSession


def _emit_split_frontage_strip(
    ctx: _IndustrialFrontageContext,
    name_prefix: str,
    *,
    depth: float,
    height: float,
    center_z: float,
    normal_coord: float,
    lane_left: float,
    lane_right: float,
    material,
    section: str,
    merge_allowed: bool = True,
    runtime_side: str = "front",
    occupancy_author: OccupancyAuthoringSession | None = None,
):
    lane_pad = max(0.18, ctx.spec.wall_thickness * 0.95)
    spans = (
        (-ctx.spec.width / 2 + 0.04, lane_left - lane_pad),
        (lane_right + lane_pad, ctx.spec.width / 2 - 0.04),
    )
    for side_label, (start, end) in (("Left", spans[0]), ("Right", spans[1])):
        segment_width = end - start
        if segment_width <= 0.12:
            continue
        _emit_frontage_shell_piece(
            ctx.prefix,
            f"{name_prefix}_{side_label}",
            ctx.spec,
            ctx.collection,
            ctx.parent,
            material,
            orientation="X",
            width=segment_width,
            depth=depth,
            height=height,
            along_coord=(start + end) / 2,
            normal_coord=normal_coord,
            center_z=center_z,
            section=section,
            merge_allowed=merge_allowed,
            generated_metadata={"tbg_industrial_fascia": True, "tbg_facade_side": "front", "tbg_facade_floor": 0},
            runtime_emitter=ctx.runtime_emitter,
            runtime_side=runtime_side,
            occupancy_author=occupancy_author,
        )


def _industrial_cladding_material(materials_map):
    return materials_map["industrial_cladding"]


def _warehouse_door_center_x(spec, envelope) -> float:
    span_limit = spec.width / 2 - envelope.door_width / 2 - 0.92
    return max(-span_limit, min(span_limit, 0.0))


def _resolved_rear_entry_contract(spec) -> dict[str, float] | None:
    spatial_plan = _spatial_plan(spec)
    rear_access_profile = str(
        getattr(
            spatial_plan,
            "rear_access_profile",
            REAR_ACCESS_PROFILE_SERVICE_DOOR,
        )
    )
    if rear_access_profile == REAR_ACCESS_PROFILE_NONE:
        return None
    return _rear_entry_opening_contract(
        spec,
        spatial_plan,
        face_length=float(spec.width),
    )


def _resolved_rear_access_profile(spec) -> str:
    return str(
        getattr(
            _spatial_plan(spec),
            "rear_access_profile",
            REAR_ACCESS_PROFILE_SERVICE_DOOR,
        )
    )


def _industrial_back_window_profile(
    spec,
    *,
    start: float,
    end: float,
    slot_index: int,
    rear_access_profile: str,
) -> tuple[float, float, float]:
    opening_width, sill_h, opening_h, _top_h = _slot_opening_profile(
        spec,
        WINDOW_STATE_OPEN,
        end - start,
        spec.floor_height,
        side_key="back",
        floor_index=0,
        slot_index=slot_index,
    )
    span = max(0.0, float(end - start))
    if span <= 1e-4:
        return (0.0, 0.0, 0.0)
    standard_sill_h = float(sill_h)
    standard_opening_h = float(opening_h)
    usable_span = max(0.24, span - 0.06)
    if rear_access_profile == REAR_ACCESS_PROFILE_OPEN_BAY:
        target_sill_h = max(0.82, min(1.02, float(spec.floor_height) * 0.3))
        opening_width = min(usable_span, max(1.44, min(2.28, span * 0.92)))
        target_opening_h = max(1.12, min(1.36, float(spec.floor_height) * 0.42))
    else:
        target_sill_h = max(0.92, min(1.14, float(spec.floor_height) * 0.33))
        opening_width = min(usable_span, max(1.56, min(2.4, span * 0.9)))
        target_opening_h = max(1.1, min(1.34, float(spec.floor_height) * 0.41))
    sill_h = max(target_sill_h, min(standard_sill_h, target_sill_h + 0.12))
    opening_h = min(
        max(0.96, float(spec.floor_height) - sill_h - 0.14),
        max(target_opening_h, standard_opening_h * 0.82),
    )
    return (float(opening_width), float(sill_h), float(opening_h))


def _industrial_rear_flank_window_spans(
    spec,
    *,
    opening_left: float,
    opening_right: float,
    rear_access_profile: str,
) -> tuple[tuple[str, float, float], ...]:
    open_bay = rear_access_profile == REAR_ACCESS_PROFILE_OPEN_BAY
    side_margin = 0.18 if open_bay else 0.22
    opening_gap = 0.18 if open_bay else 0.24
    target_span = 2.18 if open_bay else 2.34
    min_span = 1.28 if open_bay else 1.42

    spans: list[tuple[str, float, float]] = []
    left_start_limit = -spec.width / 2 + side_margin
    left_end_limit = opening_left - opening_gap
    left_available = left_end_limit - left_start_limit
    if left_available >= min_span:
        resolved_span = min(target_span, left_available)
        spans.append(("Rear_Window_L", left_end_limit - resolved_span, left_end_limit))

    right_start_limit = opening_right + opening_gap
    right_end_limit = spec.width / 2 - side_margin
    right_available = right_end_limit - right_start_limit
    if right_available >= min_span:
        resolved_span = min(target_span, right_available)
        spans.append(("Rear_Window_R", right_start_limit, right_start_limit + resolved_span))
    return tuple(spans)


def _remaining_rear_wall_spans(
    *,
    start: float,
    end: float,
    blocked_spans: tuple[tuple[str, float, float], ...],
) -> tuple[tuple[float, float], ...]:
    remaining = [(float(start), float(end))]
    for _suffix, blocked_start, blocked_end in blocked_spans:
        next_remaining: list[tuple[float, float]] = []
        for segment_start, segment_end in remaining:
            overlap_start = max(segment_start, float(blocked_start))
            overlap_end = min(segment_end, float(blocked_end))
            if overlap_end - overlap_start <= 1e-4:
                next_remaining.append((segment_start, segment_end))
                continue
            if overlap_start - segment_start > 1e-4:
                next_remaining.append((segment_start, overlap_start))
            if segment_end - overlap_end > 1e-4:
                next_remaining.append((overlap_end, segment_end))
        remaining = next_remaining
        if not remaining:
            break
    return tuple(span for span in remaining if float(span[1]) - float(span[0]) > 1e-4)


def _emit_rear_shell_piece(
    *,
    prefix,
    spec,
    collection,
    parent,
    wall_material,
    label: str,
    start: float,
    end: float,
    back_y: float,
    base_z: float,
    height: float,
    runtime_emitter: RuntimeMarkerEmitter | None,
    occupancy_author: OccupancyAuthoringSession | None,
    metadata_values: dict[str, object],
):
    width = end - start
    if width <= 1e-4:
        return None
    planned_name = _name(prefix, label)
    _register_linear_wall_plane(
        occupancy_author,
        orientation="X",
        wall_pos=back_y,
        start=start,
        end=end,
        base_z=base_z,
        height=height,
        wall_t=spec.wall_thickness,
        material=wall_material,
        source_bucket="Section_Walls_Exterior",
        source_name=f"{planned_name}:plane",
        staged_object_name=planned_name,
    )
    piece = _create_opening_box(
        planned_name,
        "X",
        width,
        spec.wall_thickness,
        height,
        (start + end) / 2,
        back_y,
        base_z + height / 2,
        collection,
        parent,
        wall_material,
    )
    piece = _mark_wall_section(
        _mark_generated(piece, **metadata_values),
        "Section_Walls_Exterior",
    )
    if runtime_emitter is not None and piece is not None:
        runtime_emitter.emit_box(
            role=ROLE_SHELL,
            size=(width, spec.wall_thickness, height),
            location=tuple(float(value) for value in piece.location),
            rotation=tuple(float(value) for value in piece.rotation_euler),
            source_name=piece.name,
            metadata_values={"tbg_runtime_side": "back", "tbg_runtime_floor": 0, **metadata_values},
    )
    return piece


def _build_industrial_rear_open_aperture_reveal(
    prefix,
    suffix: str,
    *,
    back_y: float,
    slot_center_x: float,
    opening_width: float,
    sill_h: float,
    opening_h: float,
    base_z: float,
    spec,
    collection,
    parent,
    wall_material,
    slot_index: int,
):
    reveal = _build_opening_trim(
        prefix,
        f"{suffix}_Reveal",
        "X",
        "back",
        back_y,
        slot_center_x,
        opening_width,
        sill_h,
        opening_h,
        base_z,
        spec.wall_thickness,
        collection,
        parent,
        wall_material,
        office_style=False,
        placement="inner_reveal",
        double_sided=False,
        include_inner_returns=True,
    )
    if reveal is None:
        return None
    return _mark_wall_section(
        _mark_generated(
            reveal,
            tbg_industrial_rear_aperture=True,
            tbg_facade_side="back",
            tbg_facade_floor=0,
            tbg_facade_slot=int(slot_index),
        ),
        "Section_Walls_Exterior",
    )


def _industrial_entry_center_x(spec, envelope) -> float:
    if envelope.frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE:
        return _warehouse_door_center_x(spec, envelope)
    return envelope.door_offset_x


def _industrial_entry_wall_y(spec, front_y: float, envelope) -> float:
    return front_y


def _industrial_recipe(spec, envelope) -> dict[str, float]:
    recipe: dict[str, float] = {
        "main_bay_extra": 1.02,
        "bay_gap": 0.42,
        "side_margin": 0.2,
        "side_recess_scale": 0.88,
        "fascia_height": 0.58,
        "fascia_depth": 0.2,
        "split_target": 3.8,
        "split_max": 5.2,
        "clerestory_sill": 2.04,
        "clerestory_height": 0.56,
        "service_window_ratio": 0.58,
        "shutter_height_ratio": 0.76,
        "pier_width": 0.24,
        "frame_width": 0.18,
        "dock_height": 0.16,
        "main_clerestory_ratio": 0.58,
        "main_clerestory_height": 0.34,
    }
    if envelope.frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_DEPOT:
        recipe.update(
            {
                "main_bay_extra": 1.16,
                "bay_gap": 0.44,
                "side_recess_scale": 0.9,
                "fascia_height": 0.6,
                "fascia_depth": 0.21,
                "split_target": 3.9,
                "split_max": 5.1,
                "clerestory_sill": 2.08,
                "clerestory_height": 0.58,
                "service_window_ratio": 0.58,
                "shutter_height_ratio": 0.78,
                "pier_width": 0.24,
                "frame_width": 0.18,
                "dock_height": 0.18,
                "main_clerestory_ratio": 0.6,
                "main_clerestory_height": 0.34,
            }
        )
    elif envelope.frontage_variant == FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE:
        recipe.update(
            {
                "main_bay_extra": 1.32,
                "bay_gap": 0.48,
                "side_margin": 0.24,
                "side_recess_scale": 0.94,
                "fascia_height": 0.66,
                "fascia_depth": 0.22,
                "split_target": 4.3,
                "split_max": 5.8,
                "clerestory_sill": 2.18,
                "clerestory_height": 0.6,
                "service_window_ratio": 0.62,
                "shutter_height_ratio": 0.82,
                "pier_width": 0.28,
                "frame_width": 0.22,
                "dock_height": 0.22,
                "main_clerestory_ratio": 0.68,
                "main_clerestory_height": 0.4,
            }
        )
    return recipe


@dataclass(frozen=True)
class _IndustrialFrontageContext:
    prefix: str
    spec: object
    collection: object
    parent: object
    materials_map: dict
    runtime_emitter: RuntimeMarkerEmitter | None
    occupancy_author: OccupancyAuthoringSession | None
    envelope: object
    recipe: dict[str, float]
    wall_material: object
    cladding_material: object
    clerestory_material: object
    frame_material: object
    base_z: float
    front_y: float
    fascia_height: float
    fascia_depth: float
    fascia_bottom_z: float
    recess_depth: float
    main_wall_y: float
    side_recess_depth: float
    side_wall_y: float
    pier_width: float
    frame_width: float
    frame_depth: float
    frame_y: float
    main_left: float
    main_right: float
    entry_center_x: float
    entry_wall_y: float
    entry_left: float
    entry_right: float


def _build_industrial_context(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
) -> _IndustrialFrontageContext:
    envelope = _front_entry_envelope(spec)
    recipe = _industrial_recipe(spec, envelope)
    wall_material = _wall_material_for_floor(materials_map, spec, 0)
    cladding_material = _industrial_cladding_material(materials_map)
    clerestory_material = materials_map["window_fill"]
    frame_material = materials_map["frame"]
    base_z = _base_elevation(spec)
    front_y = -spec.depth / 2 + spec.wall_thickness / 2
    fascia_height = min(spec.floor_height - 0.28, max(0.42, float(recipe["fascia_height"])))
    fascia_depth = max(0.12, float(recipe["fascia_depth"]))
    fascia_bottom_z = base_z + spec.floor_height - fascia_height - 0.08
    recess_depth = max(0.52, envelope.recess_depth)
    main_wall_y = front_y + recess_depth
    side_recess_depth = max(0.42, recess_depth * float(recipe["side_recess_scale"]))
    side_wall_y = front_y + side_recess_depth
    pier_width = max(spec.wall_thickness, float(recipe["pier_width"]))
    frame_width = max(0.12, float(recipe["frame_width"]))
    frame_depth = max(0.09, min(0.18, spec.wall_thickness * 0.56))
    frame_y = _surface_coord("front", front_y, spec.wall_thickness, frame_depth, exterior=True, offset=0.022)
    main_half = min(
        spec.width / 2 - 0.82,
        max(envelope.door_width / 2 + float(recipe["main_bay_extra"]), envelope.frontage_width * 0.19),
    )
    main_left = max(-spec.width / 2 + 0.72, envelope.door_offset_x - main_half)
    main_right = min(spec.width / 2 - 0.72, envelope.door_offset_x + main_half)
    if main_right - main_left < envelope.door_width + 0.62:
        main_half = envelope.door_width / 2 + 0.31
        main_left = envelope.door_offset_x - main_half
        main_right = envelope.door_offset_x + main_half
    entry_center_x = _industrial_entry_center_x(spec, envelope)
    entry_wall_y = _industrial_entry_wall_y(spec, front_y, envelope)
    entry_left = entry_center_x - envelope.door_width / 2
    entry_right = entry_center_x + envelope.door_width / 2
    return _IndustrialFrontageContext(
        prefix=prefix,
        spec=spec,
        collection=collection,
        parent=parent,
        materials_map=materials_map,
        runtime_emitter=runtime_emitter,
        occupancy_author=occupancy_author,
        envelope=envelope,
        recipe=recipe,
        wall_material=wall_material,
        cladding_material=cladding_material,
        clerestory_material=clerestory_material,
        frame_material=frame_material,
        base_z=base_z,
        front_y=front_y,
        fascia_height=fascia_height,
        fascia_depth=fascia_depth,
        fascia_bottom_z=fascia_bottom_z,
        recess_depth=recess_depth,
        main_wall_y=main_wall_y,
        side_recess_depth=side_recess_depth,
        side_wall_y=side_wall_y,
        pier_width=pier_width,
        frame_width=frame_width,
        frame_depth=frame_depth,
        frame_y=frame_y,
        main_left=main_left,
        main_right=main_right,
        entry_center_x=entry_center_x,
        entry_wall_y=entry_wall_y,
        entry_left=entry_left,
        entry_right=entry_right,
    )


def _build_industrial_service_fascia(ctx: _IndustrialFrontageContext):
    service_plinth_height = max(0.14, float(ctx.recipe["dock_height"]))
    service_plinth_depth = max(0.12, ctx.fascia_depth * 0.72)
    _emit_split_frontage_strip(
        ctx,
        "Industrial_ServicePlinth",
        depth=service_plinth_depth,
        height=service_plinth_height,
        center_z=ctx.base_z + service_plinth_height / 2,
        normal_coord=_surface_coord("front", ctx.front_y, ctx.spec.wall_thickness, service_plinth_depth, exterior=True, offset=0.0),
        lane_left=ctx.entry_left,
        lane_right=ctx.entry_right,
        material=ctx.cladding_material,
        section="Section_Walls_Trim",
    )
    fascia = _create_opening_box(
        _name(ctx.prefix, "Industrial_ServiceFascia"),
        "X",
        ctx.spec.width - 0.08,
        ctx.fascia_depth,
        ctx.fascia_height,
        0.0,
        _surface_coord("front", ctx.front_y, ctx.spec.wall_thickness, ctx.fascia_depth, exterior=True, offset=0.0),
        ctx.fascia_bottom_z + ctx.fascia_height / 2,
        ctx.collection,
        ctx.parent,
        ctx.cladding_material,
    )
    _mark_section(
        _mark_generated(fascia, tbg_industrial_fascia=True, tbg_facade_side="front", tbg_facade_floor=0),
        "Section_Walls_Trim",
    )


def _split_industrial_service_spans(ctx: _IndustrialFrontageContext, span_start: float, span_end: float) -> list[tuple[float, float]]:
    span = span_end - span_start
    if span <= 1.36:
        return []
    bay_gap = float(ctx.recipe["bay_gap"])
    split_target = float(ctx.recipe["split_target"])
    split_max = float(ctx.recipe["split_max"])
    if span <= split_max:
        return [(span_start, span_end)]
    bay_count = max(2, min(3, int(math.ceil(span / split_target))))
    usable = span - bay_gap * (bay_count - 1)
    if usable <= bay_count * 1.2:
        return [(span_start, span_end)]
    bay_width = usable / bay_count
    segments: list[tuple[float, float]] = []
    cursor = span_start
    for bay_index in range(bay_count):
        bay_end = span_end if bay_index == bay_count - 1 else cursor + bay_width
        segments.append((cursor, bay_end))
        cursor = bay_end + bay_gap
    return segments


def _build_industrial_bay_frame(
    ctx: _IndustrialFrontageContext,
    label: str,
    bay_left: float,
    bay_right: float,
    clear_height: float,
    *,
    bay_name: str,
    include_curb: bool = True,
):
    metadata = {
        "tbg_industrial_bay": bay_name,
        "tbg_facade_side": "front",
        "tbg_facade_floor": 0,
    }
    jamb_height = clear_height + max(0.08, clear_height * 0.04)
    header_height = max(0.18, min(0.32, clear_height * 0.12))
    curb_height = max(0.12, float(ctx.recipe["dock_height"]))
    span_width = bay_right - bay_left
    for side_label, along_coord in (("L", bay_left + ctx.frame_width / 2), ("R", bay_right - ctx.frame_width / 2)):
        jamb = _create_opening_box(
            _name(ctx.prefix, f"Industrial_{label}_FrameJamb_{side_label}"),
            "X",
            ctx.frame_width,
            ctx.frame_depth,
            jamb_height,
            along_coord,
            ctx.frame_y,
            ctx.base_z + jamb_height / 2,
            ctx.collection,
            ctx.parent,
            ctx.cladding_material,
        )
        _mark_section(_mark_generated(jamb, tbg_industrial_frame=True, **metadata), "Section_Doors_Prop")
    header = _create_opening_box(
        _name(ctx.prefix, f"Industrial_{label}_FrameHeader"),
        "X",
        span_width + ctx.frame_width * 0.9,
        ctx.frame_depth,
        header_height,
        (bay_left + bay_right) / 2,
        ctx.frame_y,
        ctx.base_z + clear_height + header_height / 2,
        ctx.collection,
        ctx.parent,
        ctx.cladding_material,
    )
    _mark_section(_mark_generated(header, tbg_industrial_frame=True, **metadata), "Section_Doors_Prop")
    if include_curb:
        curb = _create_opening_box(
            _name(ctx.prefix, f"Industrial_{label}_FrameCurb"),
            "X",
            span_width + ctx.frame_width * 0.72,
            ctx.frame_depth,
            curb_height,
            (bay_left + bay_right) / 2,
            ctx.frame_y,
            ctx.base_z + curb_height / 2,
            ctx.collection,
            ctx.parent,
            ctx.cladding_material,
        )
        _mark_section(_mark_generated(curb, tbg_industrial_frame=True, **metadata), "Section_Doors_Prop")


def _build_industrial_service_dock(ctx: _IndustrialFrontageContext, label: str, bay_left: float, bay_right: float, dock_depth: float):
    dock_height = max(0.06, ctx.spec.slab_thickness * 0.42)
    dock = _create_opening_box(
        _name(ctx.prefix, f"Industrial_{label}_Dock"),
        "X",
        bay_right - bay_left,
        dock_depth,
        dock_height,
        (bay_left + bay_right) / 2,
        ctx.front_y + dock_depth / 2,
        ctx.base_z + dock_height / 2,
        ctx.collection,
        ctx.parent,
        ctx.materials_map["floor"],
    )
    _mark_section(_mark_generated(dock, tbg_industrial_bay=label.lower()), "Section_Floors")


def _build_industrial_main_bay_side_walls(ctx: _IndustrialFrontageContext):
    clear_height = max(ctx.spec.door.height + 0.22, ctx.fascia_bottom_z - ctx.base_z - 0.06)
    return_depth = max(ctx.spec.wall_thickness, ctx.pier_width)
    _build_industrial_bay_frame(ctx, "Main", ctx.main_left, ctx.main_right, clear_height, bay_name="main")
    for side_label, normal_x in (("L", ctx.main_left + return_depth / 2), ("R", ctx.main_right - return_depth / 2)):
        _emit_frontage_shell_piece(
            ctx.prefix,
            f"Industrial_MainReturn_{side_label}",
            ctx.spec,
            ctx.collection,
            ctx.parent,
            ctx.wall_material,
            orientation="Y",
            width=ctx.recess_depth,
            depth=return_depth,
            height=clear_height,
            along_coord=ctx.front_y + ctx.recess_depth / 2,
            normal_coord=normal_x,
            center_z=ctx.base_z + clear_height / 2,
            generated_metadata={"tbg_industrial_bay": "main", "tbg_facade_side": "front", "tbg_facade_floor": 0},
            runtime_emitter=ctx.runtime_emitter,
            occupancy_author=ctx.occupancy_author,
        )
    for side_label, span_start, span_end in (
        ("Left", ctx.main_left, ctx.envelope.door_left),
        ("Right", ctx.envelope.door_right, ctx.main_right),
    ):
        span = span_end - span_start
        if span <= 0.1:
            continue
        _emit_frontage_shell_piece(
            ctx.prefix,
            f"Industrial_MainBackWall_{side_label}",
            ctx.spec,
            ctx.collection,
            ctx.parent,
            ctx.wall_material,
            orientation="X",
            width=span,
            depth=ctx.spec.wall_thickness,
            height=min(clear_height, ctx.spec.door.height + 0.18),
            along_coord=(span_start + span_end) / 2,
            normal_coord=ctx.main_wall_y,
            center_z=ctx.base_z + min(clear_height, ctx.spec.door.height + 0.18) / 2,
            generated_metadata={"tbg_industrial_bay": "main", "tbg_facade_side": "front", "tbg_facade_floor": 0},
            runtime_emitter=ctx.runtime_emitter,
            occupancy_author=ctx.occupancy_author,
        )
    lintel_height = max(0.18, clear_height - ctx.spec.door.height)
    _emit_frontage_shell_piece(
        ctx.prefix,
        "Industrial_MainBackWall_Lintel",
        ctx.spec,
        ctx.collection,
        ctx.parent,
        ctx.wall_material,
        orientation="X",
        width=ctx.envelope.door_width,
        depth=ctx.spec.wall_thickness,
        height=lintel_height,
        along_coord=ctx.envelope.door_offset_x,
        normal_coord=ctx.main_wall_y,
        center_z=ctx.base_z + ctx.spec.door.height + lintel_height / 2,
        generated_metadata={"tbg_industrial_bay": "main", "tbg_facade_side": "front", "tbg_facade_floor": 0},
        runtime_emitter=ctx.runtime_emitter,
        occupancy_author=ctx.occupancy_author,
    )
    clerestory_height = min(
        float(ctx.recipe["main_clerestory_height"]),
        max(0.24, clear_height - ctx.spec.door.height - 0.12),
    )
    if clerestory_height > 0.18:
        clerestory_width = min(
            ctx.main_right - ctx.main_left - 0.28,
            max(ctx.envelope.door_width + 0.72, (ctx.main_right - ctx.main_left) * float(ctx.recipe["main_clerestory_ratio"])),
        )
        main_clerestory = _create_opening_box(
            _name(ctx.prefix, "Industrial_MainClerestory"),
            "X",
            clerestory_width,
            max(0.05, ctx.spec.wall_thickness * 0.22),
            clerestory_height,
            ctx.envelope.door_offset_x,
            _surface_coord("front", ctx.main_wall_y, ctx.spec.wall_thickness, max(0.05, ctx.spec.wall_thickness * 0.22), exterior=True, offset=0.018),
            ctx.base_z + clear_height - clerestory_height / 2 - 0.04,
            ctx.collection,
            ctx.parent,
            ctx.clerestory_material,
        )
        _mark_section(
            _mark_generated(main_clerestory, tbg_industrial_transom=True, tbg_industrial_bay="main"),
            "Section_Openings_WindowFill",
        )
    bay_floor = _create_opening_box(
        _name(ctx.prefix, "Industrial_MainBayFloor"),
        "X",
        ctx.main_right - ctx.main_left,
        ctx.recess_depth,
        max(0.06, ctx.spec.slab_thickness * 0.42),
        (ctx.main_left + ctx.main_right) / 2,
        ctx.front_y + ctx.recess_depth / 2,
        ctx.base_z + max(0.06, ctx.spec.slab_thickness * 0.42) / 2,
        ctx.collection,
        ctx.parent,
        ctx.materials_map["floor"],
    )
    _mark_section(
        _mark_generated(
            bay_floor,
            tbg_industrial_bay="main",
            tbg_entry_front_limit=float(ctx.envelope.front_footprint_extent),
            tbg_entry_left_limit=float(ctx.envelope.footprint_left_extent),
            tbg_entry_right_limit=float(ctx.envelope.footprint_right_extent),
        ),
        "Section_Floors",
    )
    header = _create_opening_box(
        _name(ctx.prefix, "Industrial_MainHeader"),
        "X",
        ctx.main_right - ctx.main_left + 0.12,
        0.1,
        0.18,
        (ctx.main_left + ctx.main_right) / 2,
        _surface_coord("front", ctx.main_wall_y, ctx.spec.wall_thickness, 0.1, exterior=True, offset=0.026),
        ctx.base_z + ctx.spec.door.height + 0.12,
        ctx.collection,
        ctx.parent,
        ctx.cladding_material,
    )
    _mark_section(_mark_generated(header, tbg_industrial_bay="main"), "Section_Doors_Prop")
    _build_front_entry_frame(
        ctx.prefix,
        "Door_Main",
        ctx.spec,
        ctx.collection,
        ctx.parent,
        ctx.frame_material,
        wall_pos=ctx.front_y,
        door_center_x=ctx.envelope.door_offset_x,
        door_width=ctx.envelope.door_width,
        base_z=ctx.base_z,
        door_height=ctx.spec.door.height,
    )


def _emit_industrial_front_face_solid(ctx: _IndustrialFrontageContext, label: str, span_start: float, span_end: float):
    width = span_end - span_start
    if width <= 0.12:
        return
    _emit_front_wall_piece(
        ctx.prefix,
        label,
        ctx.spec,
        ctx.collection,
        ctx.parent,
        ctx.wall_material,
        width=width,
        center_x=(span_start + span_end) / 2,
        center_z=ctx.base_z + ctx.spec.floor_height / 2,
        height=ctx.spec.floor_height,
        occupancy_author=ctx.occupancy_author,
        runtime_emitter=ctx.runtime_emitter,
    )


def _build_industrial_front_personnel_entry(ctx: _IndustrialFrontageContext, label: str, door_center_x: float) -> tuple[float, float]:
    door_left = door_center_x - ctx.envelope.door_width / 2
    door_right = door_center_x + ctx.envelope.door_width / 2
    lintel_height = max(0.18, ctx.spec.floor_height - ctx.spec.door.height)
    _emit_front_wall_piece(
        ctx.prefix,
        f"{label}_Lintel",
        ctx.spec,
        ctx.collection,
        ctx.parent,
        ctx.wall_material,
        width=ctx.envelope.door_width,
        center_x=door_center_x,
        center_z=ctx.base_z + ctx.spec.door.height + lintel_height / 2,
        height=lintel_height,
        occupancy_author=ctx.occupancy_author,
        runtime_emitter=ctx.runtime_emitter,
        wall_y=ctx.entry_wall_y,
    )
    _build_front_entry_frame(
        ctx.prefix,
        label,
        ctx.spec,
        ctx.collection,
        ctx.parent,
        ctx.frame_material,
        wall_pos=ctx.entry_wall_y,
        door_center_x=door_center_x,
        door_width=ctx.envelope.door_width,
        base_z=ctx.base_z,
        door_height=ctx.spec.door.height,
    )
    door_center_z = ctx.base_z + ctx.spec.door.height / 2
    hinge_x = door_center_x - ctx.spec.door.width / 2 if ctx.spec.door.hinge == constants.HINGE_LEFT else door_center_x + ctx.spec.door.width / 2
    origin_mode = "HINGE_LEFT" if ctx.spec.door.hinge == constants.HINGE_LEFT else "HINGE_RIGHT"
    door = _create_box(
        _name(ctx.prefix, "Door_Main"),
        (ctx.spec.door.width, ctx.spec.door.thickness, ctx.spec.door.height),
        (hinge_x, ctx.entry_wall_y + ctx.spec.door.thickness / 2 + 0.015, door_center_z),
        ctx.collection,
        ctx.parent,
        ctx.materials_map["door"],
        origin_mode=origin_mode,
    )
    door = _mark_generated(door, tbg_door_panel=True, tbg_door_handle_plate=True)
    _mark_door_leaf(door, open_rotation_z=math.radians(95.0 if ctx.spec.door.hinge == constants.HINGE_LEFT else -95.0))
    return door_left, door_right


def _split_open_bay_spans(
    *,
    span_start: float,
    span_end: float,
    bay_count: int,
    gap: float,
) -> list[tuple[float, float]]:
    span = float(span_end) - float(span_start)
    if bay_count <= 0 or span <= 1e-4:
        return []
    usable = span - max(0.0, gap) * max(0, bay_count - 1)
    if usable <= 1e-4:
        return []
    bay_w = usable / bay_count
    result: list[tuple[float, float]] = []
    cursor = float(span_start)
    for bay_idx in range(bay_count):
        right = float(span_end) if bay_idx == bay_count - 1 else cursor + bay_w
        result.append((cursor, right))
        cursor = right + max(0.0, gap)
    return result


def _emit_front_solids_for_openings(
    ctx: _IndustrialFrontageContext,
    *,
    label_prefix: str,
    openings: list[tuple[float, float]],
) -> None:
    sorted_openings = sorted(
        (max(-ctx.spec.width / 2, left), min(ctx.spec.width / 2, right))
        for left, right in openings
        if right - left > 0.1
    )
    cursor = -ctx.spec.width / 2
    gap_index = 0
    for open_left, open_right in sorted_openings:
        if open_left > cursor + 0.1:
            _emit_industrial_front_face_solid(
                ctx,
                f"{label_prefix}_Solid_{gap_index:02d}",
                cursor,
                open_left,
            )
            gap_index += 1
        cursor = max(cursor, open_right)
    if cursor < ctx.spec.width / 2 - 0.1:
        _emit_industrial_front_face_solid(
            ctx,
            f"{label_prefix}_Solid_{gap_index:02d}",
            cursor,
            ctx.spec.width / 2,
        )


def _build_industrial_depot_front_ground(ctx: _IndustrialFrontageContext):
    bay_span_start = -ctx.spec.width / 2 + 0.48
    bay_span_end = ctx.spec.width / 2 - 0.48
    available_span = bay_span_end - bay_span_start
    if available_span <= 1.72:
        return

    bay_count = 4 if available_span >= 10.8 else 3 if available_span >= 7.8 else 2 if available_span >= 5.0 else 1
    bay_gap = 0.26
    bays = _split_open_bay_spans(
        span_start=bay_span_start,
        span_end=bay_span_end,
        bay_count=bay_count,
        gap=bay_gap,
    )
    clear_height = max(2.36, min(2.86, ctx.fascia_bottom_z - ctx.base_z - 0.06))
    for bay_idx, (bay_left, bay_right) in enumerate(bays):
        if bay_right - bay_left <= 1.52:
            continue
        _build_industrial_bay_frame(
            ctx,
            f"Depot_Bay_{bay_idx + 1:02d}",
            bay_left,
            bay_right,
            clear_height,
            bay_name=f"bay_{bay_idx + 1:02d}",
            include_curb=False,
        )

    _emit_front_solids_for_openings(ctx, label_prefix="Depot", openings=list(bays))


def _build_industrial_warehouse_front_ground(ctx: _IndustrialFrontageContext):
    door_center_x = ctx.entry_center_x
    door_left, door_right = _build_industrial_front_personnel_entry(ctx, "Warehouse_Door", door_center_x)
    loading_left = -ctx.spec.width / 2 + 0.52
    loading_right = min(door_left - 0.32, ctx.spec.width / 2 - 0.92)
    loading_width = loading_right - loading_left
    if loading_width < max(5.9, ctx.spec.width * 0.36):
        loading_width = max(5.9, ctx.spec.width * 0.36)
        loading_right = min(door_left - 0.24, loading_left + loading_width)
    loading_clear_height = max(2.9, min(3.26, ctx.fascia_bottom_z - ctx.base_z - 0.06))
    _build_industrial_bay_frame(ctx, "Warehouse_Loading", loading_left, loading_right, loading_clear_height, bay_name="main", include_curb=False)
    openings = [(loading_left, loading_right), (door_left, door_right)]
    _emit_front_solids_for_openings(ctx, label_prefix="Warehouse", openings=openings)


def build_industrial_front_ground(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    ctx = _build_industrial_context(
        prefix,
        spec,
        collection,
        parent,
        materials_map,
        occupancy_author=occupancy_author,
        runtime_emitter=runtime_emitter,
    )
    variant = ctx.envelope.frontage_variant
    if variant != FRONTAGE_TYPE_INDUSTRIAL_WAREHOUSE:
        _build_industrial_service_fascia(ctx)
    if variant == FRONTAGE_TYPE_INDUSTRIAL_DEPOT:
        _build_industrial_depot_front_ground(ctx)
        return
    _build_industrial_warehouse_front_ground(ctx)


def _build_aux_doorway(
    prefix,
    suffix: str,
    side_key: str,
    wall_pos: float,
    door_center_x: float,
    spec,
    collection,
    parent,
    material,
    frame_material,
):
    base_z = _base_elevation(spec)
    door_cut_rect = _ordinary_door_cut_rect(
        center_x=door_center_x,
        opening_width=spec.door.width,
        base_z=base_z,
        door_height=spec.door.height,
    )
    door_cut_metadata = _wall_opening_cut_metadata(
        kind="door",
        orientation="X",
        side_key=side_key,
        floor_index=0,
        slot_index=-1,
        wall_pos=wall_pos,
        cut_rect=door_cut_rect,
    )
    frame_along_coord, frame_outer_width, frame_outer_height, frame_mid_z = _opening_cut_frame_envelope(
        door_cut_metadata
    )
    frame_along_coord = float(frame_along_coord if frame_along_coord is not None else door_center_x)
    frame = _build_opening_trim(
        prefix,
        suffix,
        "X",
        side_key,
        wall_pos,
        frame_along_coord,
        spec.door.width,
        base_z,
        spec.door.height,
        0.0,
        spec.wall_thickness,
        collection,
        parent,
        frame_material,
        office_style=False,
        placement="outer_proud",
        double_sided=True,
        outer_width_override=frame_outer_width,
        outer_height_override=frame_outer_height,
        opening_mid_z_override=frame_mid_z,
    )
    _mark_section(
        _mark_generated(
            frame,
            tbg_door_frame=True,
            tbg_door_frame_left=float(door_center_x - spec.door.width / 2),
            tbg_door_frame_right=float(door_center_x + spec.door.width / 2),
            tbg_door_wall_pos=float(wall_pos),
            tbg_facade_side=side_key,
            tbg_facade_plane="both",
            **door_cut_metadata,
        ),
        "Section_Doors_Trim",
        merge_allowed=False,
    )
    door_center_z = base_z + spec.door.height / 2
    hinge_x = door_center_x - spec.door.width / 2 if spec.door.hinge == constants.HINGE_LEFT else door_center_x + spec.door.width / 2
    origin_mode = "HINGE_LEFT" if spec.door.hinge == constants.HINGE_LEFT else "HINGE_RIGHT"
    rotation_sign = -1.0 if side_key == "back" else 1.0
    open_rotation = math.radians(95.0 * rotation_sign) if spec.door.hinge == constants.HINGE_LEFT else math.radians(-95.0 * rotation_sign)
    leaf_y = wall_pos - spec.door.thickness / 2 - 0.015 if side_key == "back" else wall_pos + spec.door.thickness / 2 + 0.015
    door = _create_box(
        _name(prefix, suffix),
        (spec.door.width, spec.door.thickness, spec.door.height),
        (hinge_x, leaf_y, door_center_z),
        collection,
        parent,
        material,
        origin_mode=origin_mode,
    )
    door = _mark_generated(
        door,
        tbg_door_panel=True,
        tbg_door_handle_plate=True,
        tbg_facade_side=side_key,
        tbg_facade_floor=0,
        tbg_rear_through_access=(side_key == "back"),
        **door_cut_metadata,
    )
    _mark_door_leaf(door, open_rotation_z=open_rotation)
    return frame, door


def build_warehouse_back_ground(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    rear_access_profile = _resolved_rear_access_profile(spec)
    if rear_access_profile != REAR_ACCESS_PROFILE_SERVICE_DOOR:
        return
    envelope = _front_entry_envelope(spec)
    rear_contract = _resolved_rear_entry_contract(spec)
    wall_material = _wall_material_for_floor(materials_map, spec, 0)
    frame_material = materials_map["frame"]
    back_y = spec.depth / 2 - spec.wall_thickness / 2
    base_z = _base_elevation(spec)
    door_center_x = (
        float(rear_contract["opening_center_x"])
        if rear_contract is not None
        else _warehouse_door_center_x(spec, envelope)
    )
    rear_opening_width = max(envelope.door_width + 0.14, min(spec.width * 0.22, envelope.door_width + 0.54))
    if rear_contract is not None:
        contract_span = float(rear_contract["span_right"]) - float(rear_contract["span_left"])
        rear_opening_width = min(contract_span - 0.02, rear_opening_width)
        rear_opening_width = max(envelope.door_width + 0.04, rear_opening_width)
    else:
        rear_opening_width = max(envelope.door_width + 0.14, rear_opening_width)
    door_left = door_center_x - rear_opening_width / 2
    door_right = door_center_x + rear_opening_width / 2
    back_window_specs = _industrial_rear_flank_window_spans(
        spec,
        opening_left=door_left,
        opening_right=door_right,
        rear_access_profile=rear_access_profile,
    )
    lintel_h = max(0.0, spec.floor_height - spec.door.height)
    for label, start, end in (
        ("Back_F00_Left", -spec.width / 2, door_left),
        ("Back_F00_Right", door_right, spec.width / 2),
    ):
        for segment_index, (segment_start, segment_end) in enumerate(
            _remaining_rear_wall_spans(start=start, end=end, blocked_spans=back_window_specs)
        ):
            _emit_rear_shell_piece(
                prefix=prefix,
                spec=spec,
                collection=collection,
                parent=parent,
                wall_material=wall_material,
                label=f"{label}_{segment_index:02d}",
                start=segment_start,
                end=segment_end,
                back_y=back_y,
                base_z=base_z,
                height=spec.floor_height,
                runtime_emitter=runtime_emitter,
                occupancy_author=occupancy_author,
                metadata_values={"tbg_warehouse_rear_entry": True, "tbg_facade_side": "back", "tbg_facade_floor": 0},
            )
    if lintel_h > 1e-4:
        _emit_rear_shell_piece(
            prefix=prefix,
            spec=spec,
            collection=collection,
            parent=parent,
            wall_material=wall_material,
            label="Back_F00_Lintel",
            start=door_left,
            end=door_right,
            back_y=back_y,
            base_z=base_z + spec.door.height,
            height=lintel_h,
            runtime_emitter=runtime_emitter,
            occupancy_author=occupancy_author,
            metadata_values={"tbg_warehouse_rear_entry": True, "tbg_facade_side": "back", "tbg_facade_floor": 0},
        )
    _build_aux_doorway(
        prefix,
        "Door_Rear",
        "back",
        back_y,
        door_center_x,
        spec,
        collection,
        parent,
        materials_map["door"],
        frame_material,
    )
    for slot_index, (suffix, start, end) in enumerate(back_window_specs):
        if end - start <= 0.92:
            continue
        opening_width, sill_h, opening_h = _industrial_back_window_profile(
            spec,
            start=start,
            end=end,
            slot_index=slot_index,
            rear_access_profile=rear_access_profile,
        )
        _build_custom_window_slot(
            prefix,
            suffix,
            "X",
            "back",
            back_y,
            start,
            end,
            base_z,
            spec.floor_height,
            spec.wall_thickness,
            collection,
            parent,
            materials_map,
            spec,
            state=WINDOW_STATE_OPEN,
            protect_opening=False,
            floor_index=0,
            slot_index=slot_index,
            opening_width=opening_width,
            sill_h=sill_h,
            opening_h=opening_h,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )
        _build_industrial_rear_open_aperture_reveal(
            prefix,
            suffix,
            back_y=back_y,
            slot_center_x=(start + end) / 2,
            opening_width=opening_width,
            sill_h=sill_h,
            opening_h=opening_h,
            base_z=base_z,
            spec=spec,
            collection=collection,
            parent=parent,
            wall_material=wall_material,
            slot_index=slot_index,
        )


def build_depot_back_ground(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    occupancy_author: OccupancyAuthoringSession | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    rear_access_profile = _resolved_rear_access_profile(spec)
    if rear_access_profile != REAR_ACCESS_PROFILE_OPEN_BAY:
        return
    envelope = _front_entry_envelope(spec)
    rear_contract = _resolved_rear_entry_contract(spec)
    wall_material = _wall_material_for_floor(materials_map, spec, 0)
    frame_material = materials_map["frame"]
    back_y = spec.depth / 2 - spec.wall_thickness / 2
    base_z = _base_elevation(spec)
    bay_center_x = (
        float(rear_contract["opening_center_x"])
        if rear_contract is not None
        else float(envelope.door_offset_x)
    )
    bay_width = max(4.4, min(spec.width * 0.54, spec.width - 1.2))
    if rear_contract is not None:
        contract_span = float(rear_contract["span_right"]) - float(rear_contract["span_left"])
        bay_width = min(contract_span - 0.02, bay_width)
    bay_width = max(3.6, bay_width)
    bay_left = bay_center_x - bay_width / 2
    bay_right = bay_center_x + bay_width / 2
    back_window_specs = _industrial_rear_flank_window_spans(
        spec,
        opening_left=bay_left,
        opening_right=bay_right,
        rear_access_profile=rear_access_profile,
    )
    clear_height = max(2.52, min(spec.floor_height - 0.08, spec.floor_height * 0.82))
    lintel_h = max(0.12, spec.floor_height - clear_height)
    for label, start, end in (
        ("Back_F00_Left", -spec.width / 2, bay_left),
        ("Back_F00_Right", bay_right, spec.width / 2),
    ):
        for segment_index, (segment_start, segment_end) in enumerate(
            _remaining_rear_wall_spans(start=start, end=end, blocked_spans=back_window_specs)
        ):
            _emit_rear_shell_piece(
                prefix=prefix,
                spec=spec,
                collection=collection,
                parent=parent,
                wall_material=wall_material,
                label=f"{label}_{segment_index:02d}",
                start=segment_start,
                end=segment_end,
                back_y=back_y,
                base_z=base_z,
                height=spec.floor_height,
                runtime_emitter=runtime_emitter,
                occupancy_author=occupancy_author,
                metadata_values={"tbg_facade_side": "back", "tbg_facade_floor": 0},
            )
    if lintel_h > 1e-4 and bay_width > 0.12:
        _emit_rear_shell_piece(
            prefix=prefix,
            spec=spec,
            collection=collection,
            parent=parent,
            wall_material=wall_material,
            label="Back_F00_Lintel",
            start=bay_left,
            end=bay_right,
            back_y=back_y,
            base_z=base_z + clear_height,
            height=lintel_h,
            runtime_emitter=runtime_emitter,
            occupancy_author=occupancy_author,
            metadata_values={"tbg_facade_side": "back", "tbg_facade_floor": 0},
        )
    for side_label, along_coord in (("L", bay_left + 0.11), ("R", bay_right - 0.11)):
        jamb = _create_opening_box(
            _name(prefix, f"Back_Bay_FrameJamb_{side_label}"),
            "X",
            0.22,
            max(0.08, spec.wall_thickness * 0.56),
            clear_height,
            along_coord,
            _surface_coord("back", back_y, spec.wall_thickness, max(0.08, spec.wall_thickness * 0.56), exterior=True, offset=0.02),
            base_z + clear_height / 2,
            collection,
            parent,
            frame_material,
        )
        _mark_section(
            _mark_generated(
                jamb,
                tbg_industrial_frame=True,
                tbg_rear_through_access=True,
                tbg_facade_side="back",
            ),
            "Section_Doors_Prop",
        )
    header = _create_opening_box(
        _name(prefix, "Back_Bay_FrameHeader"),
        "X",
        max(0.32, bay_width + 0.18),
        max(0.08, spec.wall_thickness * 0.56),
        max(0.16, lintel_h),
        bay_center_x,
        _surface_coord("back", back_y, spec.wall_thickness, max(0.08, spec.wall_thickness * 0.56), exterior=True, offset=0.02),
        base_z + clear_height + max(0.16, lintel_h) / 2,
        collection,
        parent,
        frame_material,
    )
    _mark_section(
        _mark_generated(
            header,
            tbg_industrial_frame=True,
            tbg_rear_through_access=True,
            tbg_facade_side="back",
        ),
        "Section_Doors_Prop",
    )
    for slot_index, (suffix, start, end) in enumerate(back_window_specs):
        if end - start <= 0.92:
            continue
        opening_width, sill_h, opening_h = _industrial_back_window_profile(
            spec,
            start=start,
            end=end,
            slot_index=slot_index,
            rear_access_profile=rear_access_profile,
        )
        _build_custom_window_slot(
            prefix,
            suffix,
            "X",
            "back",
            back_y,
            start,
            end,
            base_z,
            spec.floor_height,
            spec.wall_thickness,
            collection,
            parent,
            materials_map,
            spec,
            state=WINDOW_STATE_OPEN,
            protect_opening=False,
            floor_index=0,
            slot_index=slot_index,
            opening_width=opening_width,
            sill_h=sill_h,
            opening_h=opening_h,
            occupancy_author=occupancy_author,
            runtime_emitter=runtime_emitter,
        )
        _build_industrial_rear_open_aperture_reveal(
            prefix,
            suffix,
            back_y=back_y,
            slot_center_x=(start + end) / 2,
            opening_width=opening_width,
            sill_h=sill_h,
            opening_h=opening_h,
            base_z=base_z,
            spec=spec,
            collection=collection,
            parent=parent,
            wall_material=wall_material,
            slot_index=slot_index,
        )


warehouse_door_center_x = _warehouse_door_center_x
