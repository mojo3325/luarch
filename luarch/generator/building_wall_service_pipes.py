from __future__ import annotations

from ..export_contract import ROLE_PROP_BOX
from .layout_facade_planning import (
    _is_industrial_frontage,
    _selected_balcony_sides,
    _solid_facade_spans,
)
from .building_layout import (
    WALL_PIPE_BEND_LENGTH_MAX,
    WALL_PIPE_BEND_LENGTH_MIN,
    WALL_PIPE_CLAMP_HEIGHT,
    WALL_PIPE_DEPTH,
    WALL_PIPE_STANDOFF,
    WALL_PIPE_TWIN_OFFSET,
    WALL_PIPE_WIDTH,
    _side_sign,
    _stable_unit_float,
    subtract_blocked_spans,
)
from .building_support import (
    _create_box,
    _create_composite_box_object,
    _mark_generated,
    _mark_section,
    _mark_service_detail,
    _name,
)
from .runtime_markers import RuntimeMarkerEmitter, _emit_object_proxy_box

_REQUIRED_VISIBLE_WALL_PIPE_PRESET_IDS = frozenset({"depot", "utility_block", "warehouse"})


def build_wall_service_pipes(
    prefix,
    spec,
    collection,
    parent,
    materials_map,
    *,
    pipe_band,
    entry,
    facade_facts,
    spatial_plan,
    runtime_emitter: RuntimeMarkerEmitter | None = None,
):
    """Own the facade wall-pipe subsystem after frontage-local gating."""

    if str(getattr(spec, "preset_id", "")).lower() == "under_construction":
        return

    pipe_top = float(pipe_band["pipe_top"])
    pipe_bottom = float(pipe_band["pipe_bottom"])
    pipe_height = float(pipe_band["pipe_height"])
    clamp_count = max(2 if spec.floor_count <= 1 else 3, min(5, int(pipe_height / 0.95)))
    anchor = spatial_plan.service_anchor
    balcony_sides = _selected_balcony_sides(spec) if spec.floor_count > 1 else set()
    candidates: list[dict[str, float | str | bool]] = []
    seen: set[tuple[str, float, float, float]] = set()
    side_window_bands = {
        side_key: list(side_data["window_bands"])
        for side_key, side_data in facade_facts.items()
    }

    def _intersect_spans(
        existing: list[tuple[float, float]],
        incoming: list[tuple[float, float]],
        *,
        minimum_span: float,
    ) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for existing_start, existing_end in existing:
            for incoming_start, incoming_end in incoming:
                start = max(existing_start, incoming_start)
                end = min(existing_end, incoming_end)
                if end - start >= minimum_span:
                    result.append((start, end))
        return result

    anchor_along_x = anchor.roof_origin_x
    anchor_along_y = anchor.roof_origin_y
    allowed_sides: set[str] | None = None
    if _is_industrial_frontage(spec):
        allowed_sides = {"left", "right", "back"}
        allowed_sides.discard(anchor.wall_side)
        if not allowed_sides:
            return
    preferred_sides: list[str] = []
    if anchor.wall_side != "back":
        preferred_sides.append(anchor.wall_side)
    if anchor.wall_side in {"front", "back"}:
        preferred_sides.extend(["right", "left"])
    else:
        preferred_sides.extend(["front", "right", "left"])
    preferred_sides.extend(["back", anchor.wall_side])
    ordered_sides: list[str] = []
    for side in preferred_sides:
        if side not in ordered_sides:
            ordered_sides.append(side)

    for idx, side in enumerate(ordered_sides):
        if allowed_sides is not None and side not in allowed_sides:
            continue
        if side in {"front", "back"} and side in balcony_sides:
            continue
        side_data = facade_facts[side]
        floor_facts = side_data["floor_facts"]
        active_floor_facts = [floor_data for floor_data in floor_facts if floor_data.get("active", True)]
        if not active_floor_facts:
            continue

        # Pilotis and terrace floors can remove facade ownership on only part of
        # the stack. Keep the pipe on facades that still share a stable along-axis
        # center, then intersect the solid spans across the remaining active floors.
        def _along_center(floor_data) -> float:
            shell_rect = floor_data.get("shell_rect")
            if not shell_rect:
                return 0.0
            x0, x1, y0, y1 = shell_rect
            return (x0 + x1) / 2 if side in {"front", "back"} else (y0 + y1) / 2

        reference_center = _along_center(active_floor_facts[0])
        if any(abs(_along_center(floor_data) - reference_center) > 1e-4 for floor_data in active_floor_facts[1:]):
            continue

        facade_length = min(float(floor_data.get("length", side_data["length"])) for floor_data in active_floor_facts)
        spans: list[tuple[float, float]] = []
        minimum_span = max(0.18, WALL_PIPE_WIDTH + 0.04)
        for floor_index, floor_data in enumerate(active_floor_facts):
            floor_spans = _solid_facade_spans(
                float(floor_data.get("length", side_data["length"])),
                floor_data.get("layout", side_data["layout"]),
                floor_data.get("masked_slots", side_data["masked_slots"]),
                opening_margin=max(0.16, WALL_PIPE_WIDTH * 0.55),
            )
            if floor_index == 0:
                spans = floor_spans
            else:
                spans = _intersect_spans(spans, floor_spans, minimum_span=minimum_span)
            if not spans:
                break
        band_min_z = pipe_bottom - WALL_PIPE_WIDTH / 2 - 0.02
        band_max_z = pipe_top + WALL_PIPE_WIDTH / 2 + 0.02
        for along_min, along_max, min_z, max_z in side_window_bands[side]:
            if max_z < band_min_z or min_z > band_max_z:
                continue
            spans = subtract_blocked_spans(
                spans,
                along_min,
                along_max,
                padding=0.08,
                minimum_span=minimum_span,
            )
        if side == "front":
            spans = subtract_blocked_spans(
                spans,
                entry.entry_exclusion_left,
                entry.entry_exclusion_right,
                padding=0.18,
                minimum_span=minimum_span,
            )
        if not spans:
            continue
        visible = side != "back"
        anchor_along = anchor_along_x if side in {"front", "back"} else anchor_along_y
        for span_index, (span_start, span_end) in enumerate(spans):
            span_width = span_end - span_start
            along = min(max(anchor_along, span_start + WALL_PIPE_WIDTH / 2), span_end - WALL_PIPE_WIDTH / 2)
            if span_width - WALL_PIPE_WIDTH < 0.08:
                along = (span_start + span_end) / 2
            max_local_bend_run = span_width / 2 + WALL_PIPE_WIDTH / 2
            edge_bias = abs(along) / max(0.01, facade_length / 2)
            score = 6.1 - idx * 0.75 + span_width * 0.8 + edge_bias * 0.35 + (0.25 if visible else 0.0)
            score += max(-0.45, min(0.32, max_local_bend_run - WALL_PIPE_BEND_LENGTH_MIN)) * 1.3
            if span_index in {0, len(spans) - 1}:
                score += 0.18
            key = (side, round(along, 3), round(span_start, 3), round(span_end, 3))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "side": side,
                    "along": along,
                    "score": score,
                    "visible": visible,
                    "span_start": span_start,
                    "span_end": span_end,
                    "facade_length": facade_length,
                }
            )

    ranked = sorted(candidates, key=lambda item: float(item["score"]), reverse=True)
    if not ranked:
        return

    visible_ranked = [item for item in ranked if bool(item["visible"])]
    if not visible_ranked and str(getattr(spec, "preset_id", "")).lower() not in _REQUIRED_VISIBLE_WALL_PIPE_PRESET_IDS:
        return
    selected = visible_ranked[0] if visible_ranked else ranked[0]
    side = str(selected["side"])
    along = float(selected["along"])
    normal_sign = _side_sign(side)
    span_start = float(selected["span_start"])
    span_end = float(selected["span_end"])
    pw = WALL_PIPE_WIDTH
    pd = WALL_PIPE_DEPTH
    standoff = WALL_PIPE_STANDOFF
    is_lateral = side in {"left", "right"}

    if side == "front":
        wall_face_coord = -spec.depth / 2
        y_pipe = wall_face_coord + normal_sign * (standoff + pd / 2)
        x_pipe = along
    elif side == "back":
        wall_face_coord = spec.depth / 2
        y_pipe = wall_face_coord + normal_sign * (standoff + pd / 2)
        x_pipe = along
    elif side == "left":
        wall_face_coord = -spec.width / 2
        x_pipe = wall_face_coord + normal_sign * (standoff + pd / 2)
        y_pipe = along
    else:
        wall_face_coord = spec.width / 2
        x_pipe = wall_face_coord + normal_sign * (standoff + pd / 2)
        y_pipe = along

    pipe_face = (pd, pw, pipe_height) if is_lateral else (pw, pd, pipe_height)
    local_positive_clearance = span_end - along
    local_negative_clearance = along - span_start
    positive_bend_run_max = local_positive_clearance + pw / 2
    negative_bend_run_max = local_negative_clearance + pw / 2
    preferred_bend_dir = 1.0 if positive_bend_run_max >= negative_bend_run_max else -1.0
    if abs(along) > 0.18:
        preferred_bend_dir = 1.0 if along > 0.0 else -1.0
    elif _stable_unit_float(spec.seed, "wall_pipe_bend_side", spec.preset_id, side) > 0.72:
        preferred_bend_dir *= -1.0
    preferred_run_max = positive_bend_run_max if preferred_bend_dir > 0.0 else negative_bend_run_max
    alternate_run_max = negative_bend_run_max if preferred_bend_dir > 0.0 else positive_bend_run_max
    bend_dir = preferred_bend_dir
    if preferred_run_max < WALL_PIPE_BEND_LENGTH_MIN - 0.06 and alternate_run_max > preferred_run_max + 0.06:
        bend_dir *= -1.0
    available_bend_run = positive_bend_run_max if bend_dir > 0.0 else negative_bend_run_max
    opposite_span_clearance = local_negative_clearance if bend_dir > 0.0 else local_positive_clearance
    top_bend_length = WALL_PIPE_BEND_LENGTH_MIN + _stable_unit_float(spec.seed, "wall_pipe_top_bend", spec.preset_id) * (WALL_PIPE_BEND_LENGTH_MAX - WALL_PIPE_BEND_LENGTH_MIN)
    top_bend_length = min(top_bend_length, available_bend_run)
    bottom_bend_length = min(
        max(pw, top_bend_length - 0.12),
        max(pw, available_bend_run - 0.1),
        available_bend_run,
    )
    top_bend_offset = bend_dir * (top_bend_length / 2 - pw / 2)
    bottom_bend_offset = bend_dir * (bottom_bend_length / 2 - pw / 2)

    twin_roll = _stable_unit_float(spec.seed, "pipe_cluster_twin", spec.preset_id)
    has_twin_pipe = twin_roll > 0.46
    if spec.floor_count <= 1:
        has_twin_pipe = False
    has_twin_pipe = has_twin_pipe and opposite_span_clearance >= WALL_PIPE_TWIN_OFFSET + pw / 2 + 0.04
    twin_offset = WALL_PIPE_TWIN_OFFSET * (-bend_dir)
    if has_twin_pipe:
        if is_lateral:
            x2, y2 = x_pipe, y_pipe + twin_offset
        else:
            x2, y2 = x_pipe + twin_offset, y_pipe

    clamp_depth = standoff + pd + 0.08
    clamp_normal_coord = wall_face_coord + normal_sign * (clamp_depth / 2)

    def _emit_wall_pipe_segment(obj, size, location, *, segment: str, pipe_index: int | None = None):
        if runtime_emitter is None or obj is None:
            return
        metadata_values = {
            "tbg_runtime_feature": f"wall_pipe_{segment}",
            "tbg_runtime_anchor": anchor.anchor_id,
            "tbg_runtime_side": side,
            "tbg_runtime_segment": segment,
        }
        if pipe_index is not None:
            metadata_values["tbg_runtime_pipe_index"] = int(pipe_index)
        runtime_emitter.emit_box(
            role=ROLE_PROP_BOX,
            size=size,
            location=location,
            source_name=obj.name,
            metadata_values=metadata_values,
        )

    def _mark_pipe_part(
        obj,
        part: str,
        *,
        is_primary: bool = False,
        is_drainpipe: bool = False,
        pipe_index: int | None = None,
    ):
        if obj is None:
            return None
        metadata_values = {
            "tbg_service_anchor_id": anchor.anchor_id,
            "tbg_service_anchor_side": anchor.wall_side,
            "tbg_service_anchor_kind": anchor.kind,
            "tbg_pipe_side": side,
            "tbg_wall_pipe_part": part,
            "tbg_service_role": "wall_pipe",
        }
        if is_drainpipe:
            metadata_values.update(
                {
                    "tbg_drainpipe": True,
                    "tbg_drainpipe_primary": bool(is_primary),
                    "tbg_primary_service_riser": bool(is_primary),
                    "tbg_drainpipe_visible": bool(selected["visible"]),
                    "tbg_pipe_outward_sign": float(normal_sign),
                    "tbg_wall_pipe_cluster": True,
                    "tbg_wall_pipe_has_twin": bool(has_twin_pipe),
                }
            )
        else:
            metadata_values["tbg_service_detail"] = True
        if pipe_index is not None:
            metadata_values["tbg_wall_pipe_index"] = int(pipe_index)
        bucket = "Section_Services_Prop" if is_drainpipe else "Section_Services_Helper"
        return _mark_section(_mark_generated(obj, **metadata_values), bucket)

    def _build_pipe_body(pipe_idx: int, px: float, py: float, is_primary: bool):
        pipe_center_z = pipe_bottom + pipe_height / 2
        pipe_obj = _create_box(
            _name(prefix, f"WallPipe_{pipe_idx:02d}"),
            pipe_face,
            (px, py, pipe_center_z),
            collection,
            parent,
            materials_map["prop"],
        )
        pipe_obj = _mark_pipe_part(
            pipe_obj,
            "trunk",
            is_primary=is_primary,
            is_drainpipe=True,
            pipe_index=pipe_idx,
        )
        _emit_wall_pipe_segment(pipe_obj, pipe_face, (px, py, pipe_center_z), segment="trunk", pipe_index=pipe_idx)
        return pipe_obj

    def _bend_parts(run_length: float):
        entry_depth = standoff + pd + 0.1
        if is_lateral:
            return [
                ((pd, run_length, pw), (0.0, 0.0, 0.0)),
                (
                    (entry_depth, pd, pw),
                    (-normal_sign * (standoff / 2 + 0.02), bend_dir * (run_length / 2 - pd / 2), 0.0),
                ),
            ]
        return [
            ((run_length, pd, pw), (0.0, 0.0, 0.0)),
            (
                (pd, entry_depth, pw),
                (bend_dir * (run_length / 2 - pd / 2), -normal_sign * (standoff / 2 + 0.02), 0.0),
            ),
        ]

    def _build_pipe_bend(pipe_idx: int, *, px: float, py: float, z: float, segment: str, run_length: float):
        bend_obj = _create_composite_box_object(
            _name(prefix, f"WallPipe_{segment.title().replace('_', '')}_{pipe_idx:02d}"),
            _bend_parts(run_length),
            (px, py, z),
            collection,
            parent,
            materials_map["prop"],
        )
        bend_obj = _mark_pipe_part(
            bend_obj,
            segment,
            is_primary=pipe_idx == 0,
            is_drainpipe=True,
            pipe_index=pipe_idx,
        )
        _emit_object_proxy_box(
            runtime_emitter,
            bend_obj,
            metadata_values={
                "tbg_runtime_feature": f"wall_pipe_{segment}",
                "tbg_runtime_anchor": anchor.anchor_id,
                "tbg_runtime_side": side,
                "tbg_runtime_segment": segment,
                "tbg_runtime_pipe_index": int(pipe_idx),
            },
        )
        return bend_obj

    _build_pipe_body(0, x_pipe, y_pipe, is_primary=True)
    if has_twin_pipe:
        _build_pipe_body(1, x2, y2, is_primary=False)

    if is_lateral:
        top_bend_loc = (x_pipe, y_pipe + top_bend_offset, pipe_top - pw / 2)
        bottom_bend_loc = (x_pipe, y_pipe + bottom_bend_offset, pipe_bottom + pw / 2)
    else:
        top_bend_loc = (x_pipe + top_bend_offset, y_pipe, pipe_top - pw / 2)
        bottom_bend_loc = (x_pipe + bottom_bend_offset, y_pipe, pipe_bottom + pw / 2)

    _build_pipe_bend(
        0,
        px=top_bend_loc[0],
        py=top_bend_loc[1],
        z=top_bend_loc[2],
        segment="top_bend",
        run_length=top_bend_length,
    )
    _build_pipe_bend(
        0,
        px=bottom_bend_loc[0],
        py=bottom_bend_loc[1],
        z=bottom_bend_loc[2],
        segment="bottom_bend",
        run_length=bottom_bend_length,
    )

    if has_twin_pipe:
        if is_lateral:
            twin_top_bend_loc = (x2, y2 + top_bend_offset, pipe_top - pw / 2)
            twin_bottom_bend_loc = (x2, y2 + bottom_bend_offset, pipe_bottom + pw / 2)
        else:
            twin_top_bend_loc = (x2 + top_bend_offset, y2, pipe_top - pw / 2)
            twin_bottom_bend_loc = (x2 + bottom_bend_offset, y2, pipe_bottom + pw / 2)
        _build_pipe_bend(
            1,
            px=twin_top_bend_loc[0],
            py=twin_top_bend_loc[1],
            z=twin_top_bend_loc[2],
            segment="top_bend",
            run_length=top_bend_length,
        )
        _build_pipe_bend(
            1,
            px=twin_bottom_bend_loc[0],
            py=twin_bottom_bend_loc[1],
            z=twin_bottom_bend_loc[2],
            segment="bottom_bend",
            run_length=bottom_bend_length,
        )

    clamp_span = abs(twin_offset) + pw + 0.1 if has_twin_pipe else pw + 0.12
    if has_twin_pipe:
        if is_lateral:
            clamp_tangent_center = (y_pipe + y2) / 2
        else:
            clamp_tangent_center = (x_pipe + x2) / 2
    else:
        clamp_tangent_center = y_pipe if is_lateral else x_pipe

    for ci in range(clamp_count):
        clamp_z = pipe_bottom + pipe_height * ((ci + 1) / (clamp_count + 1))
        if is_lateral:
            clamp_size = (clamp_depth, clamp_span, WALL_PIPE_CLAMP_HEIGHT)
            clamp_loc = (clamp_normal_coord, clamp_tangent_center, clamp_z)
        else:
            clamp_size = (clamp_span, clamp_depth, WALL_PIPE_CLAMP_HEIGHT)
            clamp_loc = (clamp_tangent_center, clamp_normal_coord, clamp_z)
        clamp = _create_box(
            _name(prefix, f"WallPipe_Bracket_{ci:02d}"),
            clamp_size,
            clamp_loc,
            collection,
            parent,
            materials_map["helper"],
        )
        _mark_service_detail(clamp, anchor)

    node_roll = _stable_unit_float(spec.seed, "wall_pipe_node", spec.preset_id, side)
    node_size = None
    node_loc = None
    if node_roll < 0.62:
        node_height = 0.38
        node_tangent = (
            (y_pipe + y2) / 2
            if has_twin_pipe and is_lateral
            else (x_pipe + x2) / 2
            if has_twin_pipe
            else (y_pipe if is_lateral else x_pipe)
        )
        if is_lateral:
            node_size = (standoff + pd + 0.12, 0.42 if has_twin_pipe else 0.34, node_height)
            node_loc = (
                wall_face_coord + normal_sign * (node_size[0] / 2 - 0.02),
                node_tangent,
                pipe_bottom + pipe_height * 0.34,
            )
        else:
            node_size = (0.42 if has_twin_pipe else 0.34, standoff + pd + 0.12, node_height)
            node_loc = (
                node_tangent,
                wall_face_coord + normal_sign * (node_size[1] / 2 - 0.02),
                pipe_bottom + pipe_height * 0.34,
            )
        node = _create_box(
            _name(prefix, "WallPipe_Node_00"),
            node_size,
            node_loc,
            collection,
            parent,
            materials_map["prop"],
        )
        node = _mark_section(
            _mark_generated(
                node,
                tbg_service_utility=True,
                tbg_service_anchor_id=anchor.anchor_id,
                tbg_service_anchor_side=anchor.wall_side,
                tbg_service_anchor_kind=anchor.kind,
                tbg_wall_pipe_has_node=True,
            ),
            "Section_Services_Prop",
        )
        _emit_object_proxy_box(
            runtime_emitter,
            node,
            metadata_values={
                "tbg_runtime_feature": "wall_pipe_node",
                "tbg_runtime_anchor": anchor.anchor_id,
                "tbg_runtime_side": side,
            },
        )
