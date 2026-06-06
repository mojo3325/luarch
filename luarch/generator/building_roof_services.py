from __future__ import annotations

import math

from ..export_contract import ROLE_PROP_BOX
from .specs import ROOF_MODE_FLAT, ROOF_MODE_TERRACE
from .building_layout import (
    ROOF_EXIT_SERVICE_CLEARANCE,
    ROOF_PIPE_BLOCK_MARGIN,
    ROOF_PIPE_EDGE_INSET,
    ROOF_PIPE_RUN_MAX,
    ROOF_PIPE_RUN_MIN,
    ROOF_PIPE_RUN_SECONDARY_LONG_DIM_MIN,
    ROOF_PIPE_STANDOFF,
    ROOF_PROP_VENT_LARGE_ROOF_DIM_MIN,
    WALL_PIPE_DEPTH,
    WALL_PIPE_WIDTH,
    ServiceAnchor,
    _roof_requires_pipe_run,
    _roof_service_bounds,
    _side_sign,
    _stable_unit_float,
    _is_stage1_identity_reset_family,
    _roof_surface_z,
    subtract_blocked_spans,
)
from .layout_facade_planning import _is_hangar_frontage
from .building_support import (
    _create_box,
    _create_composite_box_object,
    _create_cylinder,
    _mark_service_detail,
    _mark_service_object,
    _name,
    object_local_bounds,
)
from .runtime_markers import RuntimeMarkerEmitter, _emit_object_proxy_box


def _roof_mode(spec) -> str:
    return str(getattr(spec, "roof_mode", ROOF_MODE_FLAT)).upper()


def _roof_mode_supports_walkable_service_surface(roof_mode: str) -> bool:
    return str(roof_mode or ROOF_MODE_FLAT).upper() in {ROOF_MODE_FLAT, ROOF_MODE_TERRACE}


def _roof_supports_walkable_service_surface(spec) -> bool:
    return _roof_mode_supports_walkable_service_surface(_roof_mode(spec))


def _roof_service_surface_z(spec) -> float:
    roof_surface_z = _roof_surface_z(spec)
    if not _roof_supports_walkable_service_surface(spec):
        return roof_surface_z
    if float(getattr(spec, "parapet_height", 0.0)) > 1e-4:
        return roof_surface_z
    return roof_surface_z + float(getattr(spec, "slab_thickness", 0.0))


def _roof_exit_reserved_rect(spatial_plan) -> tuple[float, float, float, float] | None:
    return spatial_plan.roof_keepout


def _push_outside_rect(
    x: float,
    y: float,
    rect: tuple[float, float, float, float] | None,
    side: str,
    margin: float = 0.16,
) -> tuple[float, float]:
    if rect is None:
        return x, y
    x0, x1, y0, y1 = rect
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return x, y
    if side == "left":
        x = x0 - margin
    elif side == "right":
        x = x1 + margin
    elif side == "front":
        y = y0 - margin
    else:
        y = y1 + margin
    return x, y


def _clamp_roof_service_point(
    spec,
    x: float,
    y: float,
    *,
    half_w: float = 0.0,
    half_d: float = 0.0,
) -> tuple[float, float]:
    min_x, max_x, min_y, max_y = _roof_service_bounds(spec)
    min_x += max(0.0, half_w)
    max_x -= max(0.0, half_w)
    min_y += max(0.0, half_d)
    max_y -= max(0.0, half_d)
    if min_x > max_x:
        center_x = (min_x + max_x) / 2
        min_x = center_x
        max_x = center_x
    if min_y > max_y:
        center_y = (min_y + max_y) / 2
        min_y = center_y
        max_y = center_y
    return min(max(x, min_x), max_x), min(max(y, min_y), max_y)


def _service_anchor_point(spec, anchor: ServiceAnchor, *, tangent_offset: float = 0.0, inward_offset: float = 0.0) -> tuple[float, float]:
    if anchor.wall_side in {"left", "right"}:
        tangent_x, tangent_y = 0.0, 1.0
        inward_x, inward_y = (-_side_sign(anchor.wall_side), 0.0)
    else:
        tangent_x, tangent_y = 1.0, 0.0
        inward_x, inward_y = (0.0, -_side_sign(anchor.wall_side))
    x, y = _clamp_roof_service_point(
        spec,
        anchor.roof_origin_x + tangent_x * tangent_offset + inward_x * inward_offset,
        anchor.roof_origin_y + tangent_y * tangent_offset + inward_y * inward_offset,
    )
    if anchor.source_rect is not None:
        x0, x1, y0, y1 = anchor.source_rect
        x = min(max(x, x0 + 0.18), x1 - 0.18)
        y = min(max(y, y0 + 0.18), y1 - 0.18)
    return x, y


def _primary_roof_service_point(
    spec,
    spatial_plan,
    anchor: ServiceAnchor,
    *,
    tangent_offset: float = 0.0,
    inward_offset: float = 0.0,
) -> tuple[float, float]:
    if anchor.kind == "CORE":
        min_x, max_x, min_y, max_y = _roof_service_bounds(spec)
        reserved = _roof_exit_reserved_rect(spatial_plan)
        if anchor.wall_side in {"left", "right"}:
            base_x = min_x if anchor.wall_side == "left" else max_x
            base_y = anchor.roof_origin_y
            x = base_x
            y = base_y + tangent_offset
            x += -_side_sign(anchor.wall_side) * inward_offset
            if reserved is not None and reserved[2] <= y <= reserved[3]:
                lower = reserved[2] - 0.44
                upper = reserved[3] + 0.44
                if lower >= min_y and (upper > max_y or abs(base_y - lower) <= abs(upper - base_y)):
                    y = lower
                elif upper <= max_y:
                    y = upper
        else:
            base_x = anchor.roof_origin_x
            base_y = min_y if anchor.wall_side == "front" else max_y
            x = base_x + tangent_offset
            y = base_y
            y += -_side_sign(anchor.wall_side) * inward_offset
            if reserved is not None and reserved[0] <= x <= reserved[1]:
                lower = reserved[0] - 0.44
                upper = reserved[1] + 0.44
                if lower >= min_x and (upper > max_x or abs(base_x - lower) <= abs(upper - base_x)):
                    x = lower
                elif upper <= max_x:
                    x = upper
        x, y = _push_outside_rect(x, y, reserved, anchor.wall_side, margin=0.2)
        return _clamp_roof_service_point(spec, x, y)

    if anchor.source_rect is None:
        return _service_anchor_point(spec, anchor, tangent_offset=tangent_offset, inward_offset=inward_offset)

    x0, x1, y0, y1 = anchor.source_rect
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    clearance = 0.74

    if anchor.wall_side in {"left", "right"}:
        tangent_x, tangent_y = 0.0, 1.0
        inward_x, inward_y = (-_side_sign(anchor.wall_side), 0.0)
        base_x = x0 - clearance if anchor.wall_side == "left" else x1 + clearance
        base_y = cy
    else:
        tangent_x, tangent_y = 1.0, 0.0
        inward_x, inward_y = (0.0, -_side_sign(anchor.wall_side))
        base_x = cx
        base_y = y0 - clearance if anchor.wall_side == "front" else y1 + clearance

    return _clamp_roof_service_point(
        spec,
        base_x + tangent_x * tangent_offset + inward_x * inward_offset,
        base_y + tangent_y * tangent_offset + inward_y * inward_offset,
    )


def _keep_roof_service_point_clear_of_exit(
    spec,
    spatial_plan,
    anchor: ServiceAnchor,
    x: float,
    y: float,
    footprint_x: float,
    footprint_y: float,
    *,
    margin: float = 0.08,
) -> tuple[float, float] | None:
    half_w = footprint_x / 2
    half_d = footprint_y / 2
    reserved = _roof_exit_reserved_rect(spatial_plan)
    if reserved is None:
        return _clamp_roof_service_point(spec, x, y, half_w=half_w, half_d=half_d)
    expanded = (
        reserved[0] - half_w,
        reserved[1] + half_w,
        reserved[2] - half_d,
        reserved[3] + half_d,
    )
    clamped_origin = _clamp_roof_service_point(spec, x, y, half_w=half_w, half_d=half_d)
    if not (expanded[0] <= clamped_origin[0] <= expanded[1] and expanded[2] <= clamped_origin[1] <= expanded[3]):
        return clamped_origin

    candidates: list[tuple[float, float]] = []
    for side in (anchor.wall_side, "front", "back", "left", "right"):
        candidate = _push_outside_rect(clamped_origin[0], clamped_origin[1], expanded, side, margin=margin)
        candidate = _clamp_roof_service_point(spec, candidate[0], candidate[1], half_w=half_w, half_d=half_d)
        if expanded[0] <= candidate[0] <= expanded[1] and expanded[2] <= candidate[1] <= expanded[3]:
            continue
        candidates.append(candidate)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (item[0] - clamped_origin[0]) ** 2 + (item[1] - clamped_origin[1]) ** 2,
    )


def _plan_roof_service_footprint(
    spec,
    spatial_plan,
    anchor: ServiceAnchor,
    *,
    x: float,
    y: float,
    footprint_x: float,
    footprint_y: float,
    margin: float,
) -> tuple[float, float] | None:
    min_x, max_x, min_y, max_y = _roof_service_bounds(spec)
    if (max_x - min_x) < footprint_x or (max_y - min_y) < footprint_y:
        return None
    point = _keep_roof_service_point_clear_of_exit(
        spec,
        spatial_plan,
        anchor,
        x,
        y,
        footprint_x,
        footprint_y,
        margin=margin,
    )
    if point is None:
        return None
    return point


def _build_roof_hvac_unit(prefix, spec, spatial_plan, idx: int, x: float, y: float, roof_top_z: float, collection, parent, materials_map, anchor: ServiceAnchor, runtime_emitter: RuntimeMarkerEmitter | None = None):
    width = min(2.35, max(1.7, spec.width * 0.16))
    depth = min(1.48, max(1.08, spec.depth * 0.13))
    body_height = 0.84
    lid_height = 0.05
    planned_point = _plan_roof_service_footprint(
        spec,
        spatial_plan,
        anchor,
        x=x,
        y=y,
        footprint_x=width,
        footprint_y=depth,
        margin=0.2,
    )
    if planned_point is None:
        return None
    x, y = planned_point
    unit = _create_composite_box_object(
        _name(prefix, f"RoofProp_HVAC_{idx:02d}"),
        [
            ((width, depth, body_height), (0.0, 0.0, body_height / 2)),
            ((width * 0.98, depth * 0.98, lid_height), (0.0, 0.0, body_height + lid_height / 2)),
        ],
        (x, y, roof_top_z),
        collection,
        parent,
        materials_map["prop"],
    )
    unit = _mark_service_object(unit, anchor, "hvac")
    _emit_object_proxy_box(
        runtime_emitter,
        unit,
        metadata_values={
            "tbg_runtime_feature": "roof_hvac",
            "tbg_runtime_anchor": anchor.anchor_id,
        },
    )

    fan_count = 3 if width >= 2.0 else 2
    fan_radius = min(width, depth) * (0.18 if fan_count == 3 else 0.21)
    fan_depth_val = 0.06
    fan_spacing = width * (0.24 if fan_count == 3 else 0.28)
    fan_z = roof_top_z + body_height + lid_height + fan_depth_val / 2 + 0.014
    for fi in range(fan_count):
        fan_offset_x = (fi - (fan_count - 1) / 2) * fan_spacing
        fan = _create_cylinder(
            _name(prefix, f"RoofProp_HVAC_{idx:02d}_Fan_{fi:02d}"),
            fan_radius,
            fan_depth_val,
            (x + fan_offset_x, y, fan_z),
            collection,
            parent,
            materials_map["helper"],
            rotation=(math.pi / 2, 0.0, 0.0),
            sides=12,
        )
        _mark_service_detail(fan, anchor)

    intake_bar_count = 2
    intake_y = y + depth * 0.47 + 0.015
    for bar_idx in range(intake_bar_count):
        intake = _create_box(
            _name(prefix, f"RoofProp_HVAC_{idx:02d}_Intake_{bar_idx:02d}"),
            (width * 0.74, 0.026, 0.032),
            (
                x,
                intake_y,
                roof_top_z + body_height * (0.28 + bar_idx * 0.2),
            ),
            collection,
            parent,
            materials_map["helper"],
        )
        _mark_service_detail(intake, anchor)
    return unit


def _build_roof_vent_stack(prefix, spec, spatial_plan, idx: int, x: float, y: float, roof_top_z: float, collection, parent, materials_map, anchor: ServiceAnchor, runtime_emitter: RuntimeMarkerEmitter | None = None):
    width = 0.68
    depth = 0.56
    body_height = 0.42
    cap_height = 0.06
    planned_point = _plan_roof_service_footprint(
        spec,
        spatial_plan,
        anchor,
        x=x,
        y=y,
        footprint_x=width,
        footprint_y=depth,
        margin=0.16,
    )
    if planned_point is None:
        return None
    x, y = planned_point
    vent = _create_composite_box_object(
        _name(prefix, f"RoofProp_Vent_{idx:02d}"),
        [
            ((width, depth, 0.06), (0.0, 0.0, 0.03)),
            ((width, depth, body_height), (0.0, 0.0, 0.06 + body_height / 2)),
            ((width * 0.94, depth * 0.94, cap_height), (0.0, 0.0, 0.06 + body_height + cap_height / 2)),
        ],
        (x, y, roof_top_z),
        collection,
        parent,
        materials_map["prop"],
    )
    vent = _mark_service_object(vent, anchor, "vent")
    _emit_object_proxy_box(
        runtime_emitter,
        vent,
        metadata_values={
            "tbg_runtime_feature": "roof_vent",
            "tbg_runtime_anchor": anchor.anchor_id,
        },
    )
    cap = _create_cylinder(
        _name(prefix, f"RoofProp_Vent_{idx:02d}_Cap_00"),
        min(width, depth) * 0.22,
        0.06,
        (x, y, roof_top_z + 0.06 + body_height + cap_height + 0.05),
        collection,
        parent,
        materials_map["helper"],
        rotation=(math.pi / 2, 0.0, 0.0),
        sides=10,
    )
    _mark_service_detail(cap, anchor)
    return vent


def _roof_blocked_rects(
    spec,
    spatial_plan,
    *,
    occupied_bounds: list[tuple[float, float, float, float]] | None = None,
) -> list[tuple[float, float, float, float]]:
    blocked_rects = list(occupied_bounds or [])
    roof_exit_rect = _roof_exit_reserved_rect(spatial_plan)
    if roof_exit_rect is not None:
        blocked_rects.append(roof_exit_rect)
    return blocked_rects


def _roof_pipe_strip_center(spec, side: str, strip_inset: float) -> float:
    if side == "front":
        return -spec.depth / 2 + strip_inset
    if side == "back":
        return spec.depth / 2 - strip_inset
    if side == "left":
        return -spec.width / 2 + strip_inset
    return spec.width / 2 - strip_inset


def _roof_pipe_interval(
    *,
    along_x: bool,
    normal_center: float,
    tangent_min: float,
    tangent_max: float,
    blocked_rects: list[tuple[float, float, float, float]],
    preferred_tangent: float,
) -> tuple[float, float] | None:
    normal_half = WALL_PIPE_DEPTH / 2 + ROOF_PIPE_BLOCK_MARGIN
    intervals = [(tangent_min, tangent_max)]
    for rect in blocked_rects:
        if along_x:
            if rect[3] < normal_center - normal_half or rect[2] > normal_center + normal_half:
                continue
            intervals = subtract_blocked_spans(
                intervals,
                rect[0],
                rect[1],
                padding=ROOF_PIPE_BLOCK_MARGIN,
                minimum_span=ROOF_PIPE_RUN_MIN,
            )
        else:
            if rect[1] < normal_center - normal_half or rect[0] > normal_center + normal_half:
                continue
            intervals = subtract_blocked_spans(
                intervals,
                rect[2],
                rect[3],
                padding=ROOF_PIPE_BLOCK_MARGIN,
                minimum_span=ROOF_PIPE_RUN_MIN,
            )
    if not intervals:
        return None
    return max(
        intervals,
        key=lambda item: (
            item[1] - item[0],
            -abs(((item[0] + item[1]) / 2) - preferred_tangent),
        ),
    )
def _plan_roof_pipe_run(
    *,
    side: str,
    strip_center: float,
    preferred_tangent: float,
    tangent_min: float,
    tangent_max: float,
    blocked_rects: list[tuple[float, float, float, float]],
    roof_top_z: float,
    stem_height: float,
) -> dict[str, object] | None:
    along_x = side in {"front", "back"}
    interval = _roof_pipe_interval(
        along_x=along_x,
        normal_center=strip_center,
        tangent_min=tangent_min,
        tangent_max=tangent_max,
        blocked_rects=blocked_rects,
        preferred_tangent=preferred_tangent,
    )
    if interval is None:
        return None

    run_diameter = WALL_PIPE_WIDTH
    run_depth = WALL_PIPE_DEPTH
    interval_span = interval[1] - interval[0]
    run_length = min(ROOF_PIPE_RUN_MAX, max(ROOF_PIPE_RUN_MIN, interval_span - 0.18))
    if run_length > interval_span:
        return None

    tangent_center = min(max(preferred_tangent, interval[0] + run_length / 2), interval[1] - run_length / 2)
    tube_center = (0.0, 0.0, ROOF_PIPE_STANDOFF + run_diameter / 2)
    leg_size = (run_depth, run_depth, stem_height)
    penetration_size = (run_depth + 0.1, run_depth + 0.1, 0.028)
    if along_x:
        run_size = (run_length, run_depth, run_diameter)
        location = (tangent_center, strip_center, roof_top_z)
        leg_centers = (
            (-run_length / 2 + run_depth / 2, 0.0, stem_height / 2),
            (run_length / 2 - run_depth / 2, 0.0, stem_height / 2),
        )
        clamp_size = (0.05, run_depth + 0.08, stem_height)
        occupied_rect = (
            tangent_center - run_length / 2,
            tangent_center + run_length / 2,
            strip_center - run_depth / 2,
            strip_center + run_depth / 2,
        )
    else:
        run_size = (run_depth, run_length, run_diameter)
        location = (strip_center, tangent_center, roof_top_z)
        leg_centers = (
            (0.0, -run_length / 2 + run_depth / 2, stem_height / 2),
            (0.0, run_length / 2 - run_depth / 2, stem_height / 2),
        )
        clamp_size = (run_depth + 0.08, 0.05, stem_height)
        occupied_rect = (
            strip_center - run_depth / 2,
            strip_center + run_depth / 2,
            tangent_center - run_length / 2,
            tangent_center + run_length / 2,
        )

    clamp_count = max(3, min(5, int(run_length / 0.55)))
    clamp_locations = []
    for clamp_idx in range(clamp_count):
        frac = (clamp_idx + 1) / (clamp_count + 1)
        if along_x:
            clamp_locations.append(
                (
                    tangent_center - run_length / 2 + run_length * frac,
                    strip_center,
                    roof_top_z + stem_height / 2,
                )
            )
        else:
            clamp_locations.append(
                (
                    strip_center,
                    tangent_center - run_length / 2 + run_length * frac,
                    roof_top_z + stem_height / 2,
                )
            )

    penetration_locations = [
        (
            location[0] + leg_center[0],
            location[1] + leg_center[1],
            roof_top_z + penetration_size[2] / 2,
        )
        for leg_center in leg_centers
    ]
    return {
        "run_length": run_length,
        "run_size": run_size,
        "location": location,
        "tube_center": tube_center,
        "leg_size": leg_size,
        "leg_centers": leg_centers,
        "clamp_size": clamp_size,
        "clamp_locations": clamp_locations,
        "penetration_size": penetration_size,
        "penetration_locations": penetration_locations,
        "occupied_rect": occupied_rect,
    }


def _build_roof_pipe_run(
    prefix,
    collection,
    parent,
    materials_map,
    anchor: ServiceAnchor,
    *,
    side: str,
    run_idx: int,
    strip_center: float,
    strip_inset: float,
    preferred_tangent: float,
    tangent_min: float,
    tangent_max: float,
    blocked_rects: list[tuple[float, float, float, float]],
    roof_top_z: float,
    stem_height: float,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    plan = _plan_roof_pipe_run(
        side=side,
        strip_center=strip_center,
        preferred_tangent=preferred_tangent,
        tangent_min=tangent_min,
        tangent_max=tangent_max,
        blocked_rects=blocked_rects,
        roof_top_z=roof_top_z,
        stem_height=stem_height,
    )
    if plan is None:
        return None, None

    run_obj = _create_composite_box_object(
        _name(prefix, f"RoofPipe_Run_{run_idx:02d}"),
        [
            (plan["run_size"], plan["tube_center"]),
            (plan["leg_size"], plan["leg_centers"][0]),
            (plan["leg_size"], plan["leg_centers"][1]),
        ],
        plan["location"],
        collection,
        parent,
        materials_map["prop"],
    )
    run_obj = _mark_service_object(run_obj, anchor, "roof_pipe_run")
    if run_obj is not None:
        run_obj["tbg_pipe_side"] = side
        run_obj["tbg_roof_pipe_edge_inset"] = float(strip_inset)
        run_obj["tbg_roof_pipe_length"] = float(plan["run_length"])
        run_obj["tbg_roof_pipe_strip_center"] = float(strip_center)
    if runtime_emitter is not None and run_obj is not None:
        runtime_emitter.emit_box(
            role=ROLE_PROP_BOX,
            size=plan["run_size"],
            location=(
                float(plan["location"][0] + plan["tube_center"][0]),
                float(plan["location"][1] + plan["tube_center"][1]),
                float(plan["location"][2] + plan["tube_center"][2]),
            ),
            source_name=run_obj.name,
            metadata_values={
                "tbg_runtime_feature": "roof_pipe_run",
                "tbg_runtime_anchor": anchor.anchor_id,
                "tbg_runtime_side": side,
                "tbg_runtime_segment": "roof_run",
                "tbg_runtime_pipe_index": int(run_idx),
            },
        )

    for clamp_idx, clamp_loc in enumerate(plan["clamp_locations"]):
        clamp = _create_box(
            _name(prefix, f"RoofPipe_Run_Clamp_{run_idx:02d}_{clamp_idx:02d}"),
            plan["clamp_size"],
            clamp_loc,
            collection,
            parent,
            materials_map["helper"],
        )
        _mark_service_detail(clamp, anchor)

    for end_idx, penetration_loc in enumerate(plan["penetration_locations"]):
        penetration = _create_box(
            _name(prefix, f"RoofPipe_Run_Penetration_{run_idx:02d}_{end_idx:02d}"),
            plan["penetration_size"],
            penetration_loc,
            collection,
            parent,
            materials_map["helper"],
        )
        _mark_service_detail(penetration, anchor)

    return run_obj, plan["occupied_rect"]


def _build_roof_pipe_runs(
    prefix,
    spec,
    spatial_plan,
    collection,
    parent,
    materials_map,
    anchor: ServiceAnchor,
    *,
    occupied_bounds: list[tuple[float, float, float, float]] | None = None,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    if not _roof_requires_pipe_run(spec):
        return []

    min_x, max_x, min_y, max_y = _roof_service_bounds(spec)
    strip_inset = max(ROOF_PIPE_EDGE_INSET, spec.parapet_height + 0.28)
    stem_height = ROOF_PIPE_STANDOFF + WALL_PIPE_WIDTH * 0.82
    roof_top_z = _roof_service_surface_z(spec)
    base_blocked_rects = _roof_blocked_rects(spec, spatial_plan, occupied_bounds=occupied_bounds)
    candidate_sides = [anchor.wall_side]
    if anchor.wall_side in {"front", "back"}:
        candidate_sides.extend(["left", "right", "back" if anchor.wall_side == "front" else "front"])
    else:
        candidate_sides.extend(["front", "back", "left" if anchor.wall_side == "right" else "right"])
    ordered_sides: list[str] = []
    for side in candidate_sides:
        if side not in ordered_sides:
            ordered_sides.append(side)

    for side in ordered_sides:
        along_x = side in {"front", "back"}
        preferred_tangent = anchor.roof_origin_x if along_x else anchor.roof_origin_y
        tangent_min = min_x + strip_inset if along_x else min_y + strip_inset
        tangent_max = max_x - strip_inset if along_x else max_y - strip_inset
        if tangent_max - tangent_min < ROOF_PIPE_RUN_MIN:
            continue

        strip_center = _roof_pipe_strip_center(spec, side, strip_inset)
        blocked_rects = list(base_blocked_rects)
        created: list[object] = []

        primary_obj, primary_rect = _build_roof_pipe_run(
            prefix,
            collection,
            parent,
            materials_map,
            anchor,
            side=side,
            run_idx=0,
            strip_center=strip_center,
            strip_inset=strip_inset,
            preferred_tangent=preferred_tangent,
            tangent_min=tangent_min,
            tangent_max=tangent_max,
            blocked_rects=blocked_rects,
            roof_top_z=roof_top_z,
            stem_height=stem_height,
            runtime_emitter=runtime_emitter,
        )
        if primary_obj is None:
            continue
        created.append(primary_obj)
        if primary_rect is not None:
            blocked_rects.append(primary_rect)

        secondary_center = strip_center - _side_sign(side) * max(0.56, WALL_PIPE_DEPTH + 0.22)
        if along_x:
            secondary_valid = min_y + strip_inset <= secondary_center <= max_y - strip_inset
        else:
            secondary_valid = min_x + strip_inset <= secondary_center <= max_x - strip_inset
        if secondary_valid and max(spec.width, spec.depth) >= ROOF_PIPE_RUN_SECONDARY_LONG_DIM_MIN and _stable_unit_float(spec.seed, "roof_pipe_run_secondary", spec.preset_id, side) < 0.38:
            secondary_obj, _secondary_rect = _build_roof_pipe_run(
                prefix,
                collection,
                parent,
                materials_map,
                anchor,
                side=side,
                run_idx=1,
                strip_center=secondary_center,
                strip_inset=strip_inset,
                preferred_tangent=preferred_tangent,
                tangent_min=tangent_min,
                tangent_max=tangent_max,
                blocked_rects=blocked_rects,
                roof_top_z=roof_top_z,
                stem_height=stem_height,
                runtime_emitter=runtime_emitter,
            )
            if secondary_obj is not None:
                created.append(secondary_obj)
        return created
    return []


def _roof_pipe_run_feasible(
    spec,
    spatial_plan,
    *,
    occupied_bounds: list[tuple[float, float, float, float]] | None = None,
) -> bool:
    if not _roof_requires_pipe_run(spec):
        return False

    min_x, max_x, min_y, max_y = _roof_service_bounds(spec)
    strip_inset = max(ROOF_PIPE_EDGE_INSET, spec.parapet_height + 0.28)
    tangent_candidate_span_x = (max_x - strip_inset) - (min_x + strip_inset)
    tangent_candidate_span_y = (max_y - strip_inset) - (min_y + strip_inset)
    if max(tangent_candidate_span_x, tangent_candidate_span_y) < ROOF_PIPE_RUN_MIN:
        return False

    anchor = spatial_plan.service_anchor
    base_blocked_rects = _roof_blocked_rects(spec, spatial_plan, occupied_bounds=occupied_bounds)
    candidate_sides = [anchor.wall_side]
    if anchor.wall_side in {"front", "back"}:
        candidate_sides.extend(["left", "right", "back" if anchor.wall_side == "front" else "front"])
    else:
        candidate_sides.extend(["front", "back", "left" if anchor.wall_side == "right" else "right"])
    ordered_sides: list[str] = []
    for side in candidate_sides:
        if side not in ordered_sides:
            ordered_sides.append(side)

    for side in ordered_sides:
        along_x = side in {"front", "back"}
        preferred_tangent = anchor.roof_origin_x if along_x else anchor.roof_origin_y
        tangent_min = min_x + strip_inset if along_x else min_y + strip_inset
        tangent_max = max_x - strip_inset if along_x else max_y - strip_inset
        if tangent_max - tangent_min < ROOF_PIPE_RUN_MIN:
            continue
        strip_center = _roof_pipe_strip_center(spec, side, strip_inset)
        if _plan_roof_pipe_run(
            side=side,
            strip_center=strip_center,
            preferred_tangent=preferred_tangent,
            tangent_min=tangent_min,
            tangent_max=tangent_max,
            blocked_rects=list(base_blocked_rects),
            roof_top_z=_roof_surface_z(spec),
            stem_height=ROOF_PIPE_STANDOFF + WALL_PIPE_WIDTH * 0.82,
        ) is not None:
            return True
    return False


def _build_roof_props(prefix, spec, spatial_plan, collection, parent, materials_map, runtime_emitter: RuntimeMarkerEmitter | None = None):
    if _is_hangar_frontage(spec) or _is_stage1_identity_reset_family(spec) or spec.roof_prop_profile == "NONE" or not _roof_supports_walkable_service_surface(spec):
        return

    roof_top_z = _roof_service_surface_z(spec)
    anchor = spatial_plan.service_anchor
    cluster_base_z = roof_top_z
    hvac_point = _primary_roof_service_point(spec, spatial_plan, anchor, tangent_offset=0.0, inward_offset=0.0)
    main_hvac = _build_roof_hvac_unit(
        prefix,
        spec,
        spatial_plan,
        0,
        hvac_point[0],
        hvac_point[1],
        cluster_base_z,
        collection,
        parent,
        materials_map,
        anchor,
        runtime_emitter=runtime_emitter,
    )

    occupied_bounds: list[tuple[float, float, float, float]] = []
    if main_hvac is not None:
        bounds = object_local_bounds(parent, main_hvac)
        occupied_bounds.append((bounds[0], bounds[1], bounds[2], bounds[3]))

    large_roof = max(spec.width, spec.depth) >= ROOF_PROP_VENT_LARGE_ROOF_DIM_MIN
    if large_roof or spec.service_profile == "HEAVY":
        vent_point = _service_anchor_point(
            spec,
            anchor,
            tangent_offset=max(0.86, min(spec.width, spec.depth) * 0.1),
            inward_offset=0.42,
        )
        if occupied_bounds:
            vent_half_w = 0.68 / 2
            vent_half_d = 0.56 / 2
            vent_rect = (
                vent_point[0] - vent_half_w,
                vent_point[0] + vent_half_w,
                vent_point[1] - vent_half_d,
                vent_point[1] + vent_half_d,
            )
            main_rect = occupied_bounds[0]
            if not (
                vent_rect[1] <= main_rect[0]
                or vent_rect[0] >= main_rect[1]
                or vent_rect[3] <= main_rect[2]
                or vent_rect[2] >= main_rect[3]
            ):
                vent_point = _service_anchor_point(
                    spec,
                    anchor,
                    tangent_offset=-max(1.18, min(spec.width, spec.depth) * 0.15),
                    inward_offset=0.52,
                )
        vent = _build_roof_vent_stack(
            prefix,
            spec,
            spatial_plan,
            1,
            vent_point[0],
            vent_point[1],
            cluster_base_z,
            collection,
            parent,
            materials_map,
            anchor,
            runtime_emitter=runtime_emitter,
        )
        if vent is not None:
            bounds = object_local_bounds(parent, vent)
            occupied_bounds.append((bounds[0], bounds[1], bounds[2], bounds[3]))

        _build_roof_pipe_runs(
            prefix,
            spec,
            spatial_plan,
            collection,
            parent,
            materials_map,
            anchor,
            occupied_bounds=occupied_bounds,
            runtime_emitter=runtime_emitter,
        )
