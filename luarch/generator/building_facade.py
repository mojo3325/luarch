from __future__ import annotations

from dataclasses import replace

from .building_facade_frontage import (
    build_facade_bands as _build_facade_bands,
    build_foundation_podium as _build_foundation_podium,
    build_main_door as _build_main_door,
    build_outer_shell as _build_outer_shell,
    build_outer_shell_step as _build_outer_shell_step,
    build_wall_service_pipes as _build_wall_service_pipes,
)
from .building_facade_openings import (
    window_envelope_bands_by_slot_for_floor as _window_envelope_bands_by_slot_for_floor,
    window_envelope_bands_for_floor as _window_envelope_bands_for_floor,
)
from .building_facade_opening_slots import ordinary_door_cut_rect as _ordinary_door_cut_rect
from .building_occupancy import (
    MIN_NON_THICKNESS_CELL_SPAN_STUDS,
    OPENING_VISUAL_CLEARANCE_STUDS,
    OccupancyAuthoringSession,
)
from .building_layout import (
    BalconyPlan,
    WINDOW_STATE_CLOSED,
    WINDOW_STATE_MASK,
    WINDOW_STATE_OPEN,
    _pilotis_open_side,
)
from .layout_facade_planning import (
    _balcony_floor_enabled,
    _balcony_lookup,
    _balcony_plans_for_side,
    _facade_floor_active,
    _facade_window_layouts,
    _mandatory_ac_slot,
    _planned_window_states,
    _rear_entry_opening_contract,
    _reserve_terrace_exit_opening,
    _selected_balcony_sides,
    _side_shell_metrics,
    _slot_intervals,
    _stair_window_slots,
)


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


def _office_balcony_budget_tier(spec) -> str:
    if str(getattr(spec, "preset_id", "")).lower() != "office_block":
        return ""
    floor_count = int(getattr(spec, "floor_count", 0))
    width = float(getattr(spec, "width", 0.0))
    depth = float(getattr(spec, "depth", 0.0))
    envelope_area = width * depth
    if floor_count >= 7 or envelope_area >= 150.0:
        return "high"
    if floor_count >= 6 or envelope_area >= 132.0:
        return "medium"
    return ""


def _slot_indices_overlapping_span(
    slot_intervals: tuple[tuple[int, float, float], ...],
    span_left: float,
    span_right: float,
    *,
    tolerance: float = 1e-4,
) -> set[int]:
    left = float(min(span_left, span_right))
    right = float(max(span_left, span_right))
    if right - left <= tolerance:
        return set()
    return {
        int(slot_index)
        for slot_index, slot_min, slot_max in slot_intervals
        if min(float(slot_max), right) - max(float(slot_min), left) > tolerance
    }


def _slot_indices_with_sub_min_opening_gap(
    spec,
    side_key: str,
    floor_index: int,
    slot_intervals: tuple[tuple[int, float, float], ...],
    planned_states: dict[int, str],
    span_left: float,
    span_right: float,
    *,
    min_gap: float = float(MIN_NON_THICKNESS_CELL_SPAN_STUDS),
    tolerance: float = 1e-4,
) -> set[int]:
    """Return slots whose actual opening cut would leave a sub-min wall sliver."""

    left = float(min(span_left, span_right))
    right = float(max(span_left, span_right))
    if right - left <= tolerance:
        return set()

    reserved: set[int] = set()
    for slot_index, band in _window_envelope_bands_by_slot_for_floor(
        spec,
        side_key,
        floor_index,
        slot_intervals,
        planned_states,
    ).items():
        band_left = float(min(band[0], band[1]))
        band_right = float(max(band[0], band[1]))
        if min(band_right, right) - max(band_left, left) > tolerance:
            reserved.add(int(slot_index))
            continue
        right_gap = band_left - right
        left_gap = left - band_right
        if tolerance < right_gap < min_gap or tolerance < left_gap < min_gap:
            reserved.add(int(slot_index))
    return reserved


def _rear_entry_visual_cut_span(spec, opening_contract: dict[str, float]) -> tuple[float, float]:
    """Planner reservation span matching the actual rear-door visual/cut envelope."""

    fallback = (
        float(opening_contract["span_left"]),
        float(opening_contract["span_right"]),
    )
    try:
        cut_rect = _ordinary_door_cut_rect(
            center_x=float(opening_contract["opening_center_x"]),
            opening_width=float(opening_contract["opening_width"]),
            base_z=0.0,
            door_height=float(spec.door.height),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return fallback
    clearance = max(0.0, float(OPENING_VISUAL_CLEARANCE_STUDS))
    return (float(cut_rect[0]) - clearance, float(cut_rect[1]) + clearance)


def _compact_office_balcony_plans(spec, *, plans: list[BalconyPlan]) -> list[BalconyPlan]:
    tier = _office_balcony_budget_tier(spec)
    if tier == "" or not plans:
        return plans
    ordered = sorted(
        plans,
        key=lambda plan: (
            -len(plan.member_indices),
            0 if str(plan.style).upper() == "STRIP" else 1,
            abs(int(plan.leader_idx)),
            int(plan.leader_idx),
        ),
    )
    keep_count = 1
    return ordered[:keep_count]


def _floor_side_layout_facts(spec, spatial_plan, side_key: str, floor_index: int):
    shell_rect = spatial_plan.floors[floor_index].footprint
    shell_width = shell_rect[1] - shell_rect[0]
    shell_depth = shell_rect[3] - shell_rect[2]
    along_center = (
        (shell_rect[0] + shell_rect[1]) / 2.0
        if side_key in {"front", "back"}
        else (shell_rect[2] + shell_rect[3]) / 2.0
    )
    floor_spec = spec
    if abs(shell_width - spec.width) > 1e-4 or abs(shell_depth - spec.depth) > 1e-4:
        floor_spec = replace(spec, width=shell_width, depth=shell_depth)
    terrace_shell = (
        spatial_plan.transition_floor_index is not None
        and spatial_plan.upper_shell_rect is not None
        and int(floor_index) == int(spatial_plan.transition_floor_index)
    )

    front_layout, back_layout, side_layout, masks = _facade_window_layouts(floor_spec, spatial_plan)
    stair_slots = _stair_window_slots(floor_spec, masks)
    if side_key == "front":
        layout = front_layout
    elif side_key == "back":
        layout = back_layout
    else:
        layout = side_layout
    length, wall_pos = _side_shell_metrics(shell_rect, side_key, spec.wall_thickness)
    centered_intervals = tuple(
        (slot_index, slot_min + along_center, slot_max + along_center)
        for slot_index, slot_min, slot_max in _slot_intervals(length, layout[0], layout[1], layout[2])
    )
    return {
        "layout": layout,
        "length": length,
        "masked_slots": masks[side_key],
        "stair_slot": stair_slots.get(side_key),
        "slot_intervals": centered_intervals,
        "along_center": along_center,
        "shell_rect": shell_rect,
        "wall_pos": wall_pos,
        "terrace_shell": terrace_shell,
        "floor_spec": floor_spec,
    }


def _derive_facade_facts(spec, spatial_plan):
    front_layout, back_layout, side_layout, masks = _facade_window_layouts(spec, spatial_plan)
    stair_slots = _stair_window_slots(spec, masks)
    transition_floor_index = spatial_plan.transition_floor_index
    terrace_open_sides = set(spatial_plan.terrace_open_sides)
    terrace_exit_assigned = False
    selected_balcony_sides = _selected_balcony_sides(spec)
    apartment_midrise_front_fallback_floors: set[int] = set()
    apartment_midrise_balcony_fallback = (
        str(getattr(spec, "preset_id", "")).lower() == "apartment_midrise"
        and selected_balcony_sides == {"front"}
    )
    side_span = max(0.01, spec.depth - spec.wall_thickness * 2.0)
    base_specs = {
        "front": {
            "length": spec.width,
            "layout": front_layout,
            "masked_slots": masks["front"],
            "stair_slot": stair_slots.get("front"),
        },
        "back": {
            "length": spec.width,
            "layout": back_layout,
            "masked_slots": masks["back"],
            "stair_slot": stair_slots.get("back"),
        },
        "left": {
            "length": side_span,
            "layout": side_layout,
            "masked_slots": masks["left"],
            "stair_slot": stair_slots.get("left"),
        },
        "right": {
            "length": side_span,
            "layout": side_layout,
            "masked_slots": masks["right"],
            "stair_slot": stair_slots.get("right"),
        },
    }
    facade_facts = {}

    for side_key, base_spec in base_specs.items():
        floor_facts = []
        window_bands: list[tuple[float, float, float, float]] = []
        active_floors: list[bool] = []

        for floor_index in range(spec.floor_count):
            floor_layout_facts = _floor_side_layout_facts(spec, spatial_plan, side_key, floor_index)
            terrace_side_open = (
                transition_floor_index is not None
                and int(floor_index) == int(transition_floor_index)
                and side_key in terrace_open_sides
            )
            floor_active = (
                _facade_floor_active(spec, floor_index)
                and not _pilotis_open_side(spec, side_key, floor_index)
            )
            active_floors.append(floor_active)

            planned_states = {}
            protected_openings = {}
            blocked_for_ac = set()
            mandatory_ac_slot = None
            balcony_leaders: dict[int, BalconyPlan] = {}
            balcony_members: dict[int, int] = {}
            masked_slots_for_planning = set(floor_layout_facts["masked_slots"])
            rear_entry_opening_span = None
            rear_entry_opening_contract = None
            terrace_exit_slot = None

            if floor_active:
                if side_key == "back" and floor_index == 0 and spatial_plan.rear_access:
                    rear_entry_opening_contract = _rear_entry_opening_contract(
                        floor_layout_facts["floor_spec"],
                        spatial_plan,
                        face_length=floor_layout_facts["length"],
                    )
                    if rear_entry_opening_contract is not None:
                        rear_entry_opening_span = _rear_entry_visual_cut_span(
                            floor_layout_facts["floor_spec"],
                            rear_entry_opening_contract,
                        )
                        rear_entry_planning_mask_span = (
                            rear_entry_opening_span[0] - float(MIN_NON_THICKNESS_CELL_SPAN_STUDS),
                            rear_entry_opening_span[1] + float(MIN_NON_THICKNESS_CELL_SPAN_STUDS),
                        )
                        masked_slots_for_planning.update(
                            _slot_indices_overlapping_span(
                                floor_layout_facts["slot_intervals"],
                                rear_entry_planning_mask_span[0],
                                rear_entry_planning_mask_span[1],
                            )
                        )
                active_balcony_plans: list[BalconyPlan] = []
                if side_key in {"front", "back"} and _balcony_floor_enabled(spec, floor_index):
                    allow_unselected_side = (
                        apartment_midrise_balcony_fallback
                        and side_key == "back"
                        and floor_index in apartment_midrise_front_fallback_floors
                    )
                    active_balcony_plans = _balcony_plans_for_side(
                        floor_layout_facts["floor_spec"],
                        side_key,
                        floor_layout_facts["layout"],
                        masked_slots_for_planning,
                        allow_unselected_side=allow_unselected_side,
                    )
                    if (
                        apartment_midrise_balcony_fallback
                        and side_key == "front"
                        and not active_balcony_plans
                    ):
                        apartment_midrise_front_fallback_floors.add(int(floor_index))
                    if (
                        apartment_midrise_balcony_fallback
                        and side_key == "back"
                        and floor_index in apartment_midrise_front_fallback_floors
                        and not active_balcony_plans
                        and floor_layout_facts["layout"][0] > 0
                        and len(masked_slots_for_planning) >= floor_layout_facts["layout"][0]
                    ):
                        # Apartment-midrise baseline can reach a fully masked fallback
                        # back facade after front-side exclusion. For upper floors this
                        # is an over-clamp; keep only the explicit stair mask when retrying.
                        relaxed_masked_slots: set[int] = set()
                        stair_slot = floor_layout_facts["stair_slot"]
                        if stair_slot is not None:
                            relaxed_masked_slots.add(int(stair_slot))
                        active_balcony_plans = _balcony_plans_for_side(
                            floor_layout_facts["floor_spec"],
                            side_key,
                            floor_layout_facts["layout"],
                            relaxed_masked_slots,
                            allow_unselected_side=True,
                        )
                        if active_balcony_plans:
                            masked_slots_for_planning = relaxed_masked_slots
                    active_balcony_plans = _compact_office_balcony_plans(
                        spec,
                        plans=active_balcony_plans,
                    )
                balcony_leaders, balcony_members = _balcony_lookup(active_balcony_plans)
                planned_states, protected_openings = _planned_window_states(
                    floor_layout_facts["floor_spec"],
                    side_key,
                    floor_index,
                    floor_layout_facts["layout"][0],
                    masked_slots_for_planning,
                    floor_layout_facts["stair_slot"],
                    active_balcony_plans,
                )
                if rear_entry_opening_span is not None:
                    rear_entry_planning_mask_span = (
                        rear_entry_opening_span[0] - float(MIN_NON_THICKNESS_CELL_SPAN_STUDS),
                        rear_entry_opening_span[1] + float(MIN_NON_THICKNESS_CELL_SPAN_STUDS),
                    )
                    rear_reserved_slots = _slot_indices_overlapping_span(
                        floor_layout_facts["slot_intervals"],
                        rear_entry_planning_mask_span[0],
                        rear_entry_planning_mask_span[1],
                    )
                    rear_reserved_slots.update(
                        _slot_indices_with_sub_min_opening_gap(
                            floor_layout_facts["floor_spec"],
                            side_key,
                            floor_index,
                            floor_layout_facts["slot_intervals"],
                            planned_states,
                            rear_entry_opening_span[0],
                            rear_entry_opening_span[1],
                        )
                    )
                    for slot_index in rear_reserved_slots:
                        planned_states[slot_index] = WINDOW_STATE_MASK
                    protected_openings = {
                        slot_index: leader
                        for slot_index, leader in protected_openings.items()
                        if slot_index not in rear_reserved_slots
                    }
                    masked_slots_for_planning.update(rear_reserved_slots)
                blocked_for_ac = _blocked_facade_ac_slots(
                    floor_layout_facts["layout"][0],
                    balcony_leaders,
                    balcony_members,
                    protected_openings,
                )
                mandatory_ac_slot = _mandatory_ac_slot(
                    floor_layout_facts["floor_spec"],
                    side_key,
                    floor_index,
                    floor_layout_facts["layout"][0],
                    masked_slots_for_planning,
                    blocked_for_ac,
                )
                if not spatial_plan.floors[floor_index].is_traversable and floor_index > 0:
                    planned_states = {
                        slot_index: WINDOW_STATE_CLOSED
                        for slot_index in range(floor_layout_facts["layout"][0])
                        if slot_index not in masked_slots_for_planning
                    }
                    protected_openings = {}
                    blocked_for_ac = set()
                    mandatory_ac_slot = None
                terrace_exit_assigned, terrace_exit_slot = _reserve_terrace_exit_opening(
                    spec,
                    spatial_plan=spatial_plan,
                    side_key=side_key,
                    floor_index=floor_index,
                    count=floor_layout_facts["layout"][0],
                    masked_slots=masked_slots_for_planning,
                    planned_states=planned_states,
                    protected_openings=protected_openings,
                    exit_already_assigned=terrace_exit_assigned,
                    slot_intervals=floor_layout_facts["slot_intervals"],
                )
                if terrace_exit_slot is not None:
                    blocked_for_ac.add(terrace_exit_slot)
                    if mandatory_ac_slot == terrace_exit_slot:
                        mandatory_ac_slot = None
                floor_window_bands = _window_envelope_bands_for_floor(
                    floor_layout_facts["floor_spec"],
                    side_key,
                    floor_index,
                    floor_layout_facts["slot_intervals"],
                    planned_states,
                )
                if rear_entry_opening_span is not None:
                    span_left, span_right = rear_entry_opening_span
                    floor_window_bands = [
                        band
                        for band in floor_window_bands
                        if min(float(band[1]), span_right) - max(float(band[0]), span_left) <= 1e-4
                    ]
                    blocked_for_ac.difference_update(
                        _slot_indices_overlapping_span(
                            floor_layout_facts["slot_intervals"],
                            span_left,
                            span_right,
                        )
                    )
                    if mandatory_ac_slot in _slot_indices_overlapping_span(
                        floor_layout_facts["slot_intervals"],
                        span_left,
                        span_right,
                    ):
                        mandatory_ac_slot = None
                window_bands.extend(floor_window_bands)

            floor_facts.append(
                {
                    "active": floor_active,
                    "planned_states": planned_states,
                    "protected_openings": protected_openings,
                    "blocked_for_ac": blocked_for_ac,
                    "mandatory_ac_slot": mandatory_ac_slot,
                    "balcony_leaders": balcony_leaders,
                    "balcony_members": balcony_members,
                    "length": floor_layout_facts["length"],
                    "layout": floor_layout_facts["layout"],
                    "masked_slots": masked_slots_for_planning,
                    "stair_slot": floor_layout_facts["stair_slot"],
                    "slot_intervals": floor_layout_facts["slot_intervals"],
                    "along_center": floor_layout_facts["along_center"],
                    "shell_rect": floor_layout_facts["shell_rect"],
                    "wall_pos": floor_layout_facts["wall_pos"],
                    "terrace_shell": floor_layout_facts["terrace_shell"],
                    "terrace_open_side": terrace_side_open,
                    "terrace_exit_slot": terrace_exit_slot,
                    "rear_entry_opening_span": rear_entry_opening_span if floor_active else None,
                    "rear_entry_opening_contract": rear_entry_opening_contract if floor_active else None,
                }
            )

        facade_facts[side_key] = {
            "side_key": side_key,
            "length": base_spec["length"],
            "layout": base_spec["layout"],
            "count": base_spec["layout"][0],
            "masked_slots": base_spec["masked_slots"],
            "stair_slot": base_spec["stair_slot"],
            "slot_intervals": tuple(
                _slot_intervals(
                    base_spec["length"],
                    base_spec["layout"][0],
                    base_spec["layout"][1],
                    base_spec["layout"][2],
                )
            ),
            "floor_facts": floor_facts,
            "window_bands": window_bands,
            "active_floors": tuple(active_floors),
        }

    return facade_facts


def _build_outer_shell_floor_side(
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
