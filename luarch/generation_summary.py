from __future__ import annotations

from dataclasses import dataclass

from . import constants, export_contract
from .generator.building_layout import _spatial_plan, _spatial_plan_roof_room_bounds
from .generator.materials import WINDOW_FILL_EXPECTED_COLOR, WINDOW_FILL_MATERIAL_NAME
from .generator.building_support import object_local_bounds

SummaryBounds = tuple[float, float, float, float, float, float]


class GenerationSummaryContractError(ValueError):
    pass


@dataclass(frozen=True)
class SummaryChildSnapshot:
    name: str
    props: dict[str, object]
    bounds: SummaryBounds
    hide_viewport: bool
    hide_render: bool
    material_slot0_name: str
    material_diffuse_rgba: tuple[float, float, float, float] | None

    def get(self, key: str, default=None):
        return self.props.get(key, default)


@dataclass(frozen=True)
class WindowSlotSummary:
    side: str
    floor: int
    slot: int
    state: str
    open: bool
    reserved_open: bool
    reserved_closed: bool
    balcony_access: bool
    span_key: str
    sill_height: float
    opening_height: float
    opening_width: float


@dataclass(frozen=True)
class WindowBoundsSummary:
    floor: int
    bounds: SummaryBounds


@dataclass(frozen=True)
class WindowsSummary:
    slots: tuple[WindowSlotSummary, ...]
    bounds: tuple[WindowBoundsSummary, ...]
    frame_count: int
    frame_outer_clearance_min: float
    frame_inner_clearance_min: float
    open_fill_leak_count: int
    closed_fill_count: int
    closed_fill_matte_count: int
    closed_fill_glossy_count: int
    closed_fill_wrong_actual_material_count: int
    closed_fill_non_blue_actual_material_count: int
    fill_center_offset_max: float


@dataclass(frozen=True)
class BalconySummary:
    side: str
    floor: int
    span_center: float
    span_width: float
    outward_sign: float
    span_key: str
    bounds: SummaryBounds


@dataclass(frozen=True)
class FacadeAcSummary:
    side: str
    floor: int
    along: float
    half_span: float
    bounds: SummaryBounds


@dataclass(frozen=True)
class DrainpipeSummary:
    primary: bool
    visible: bool
    anchor_id: str
    bounds: SummaryBounds


@dataclass(frozen=True)
class BlockingWallPipePartSummary:
    part: str
    bounds: SummaryBounds


@dataclass(frozen=True)
class RoofServiceItemSummary:
    role: str
    anchor_id: str
    side: str
    edge_inset: float
    roof_flavor: bool
    bounds: SummaryBounds


@dataclass(frozen=True)
class ServicesSummary:
    drainpipes: tuple[DrainpipeSummary, ...]
    blocking_wall_pipe_parts: tuple[BlockingWallPipePartSummary, ...]
    roof_items: tuple[RoofServiceItemSummary, ...]


@dataclass(frozen=True)
class DoorsSummary:
    frame_count: int
    frame_outer_clearance_min: float
    frame_inner_clearance_min: float
    has_legacy_trim: bool
    has_loose_detail: bool


@dataclass(frozen=True)
class RoomPartitionsSummary:
    count: int
    frame_count: int


@dataclass(frozen=True)
class EntranceSummary:
    landing_count: int
    step_count: int
    has_interior_compensator: bool
    has_foundation_podium: bool
    top_z: float
    threshold_z: float
    left_limit: float | None
    right_limit: float | None
    front_limit: float | None
    part_bounds: tuple[SummaryBounds, ...]


@dataclass(frozen=True)
class GenerationSummaryFacts:
    addon_version: str
    summary_schema_version: str
    export_contract_version: str
    windows: WindowsSummary
    lower_facade_bounds: tuple[SummaryBounds, ...]
    perimeter_corner_overlap_names: tuple[str, ...]
    balconies: tuple[BalconySummary, ...]
    canopies: tuple[SummaryBounds, ...]
    roof_exit_bounds: SummaryBounds | None
    facade_ac: tuple[FacadeAcSummary, ...]
    services: ServicesSummary
    doors: DoorsSummary
    entry_detail_clearance_min: float
    parapet_cap_clearance_min: float
    room_partitions: RoomPartitionsSummary
    entrance: EntranceSummary


def _summary_item_bounds(root_obj, obj) -> list[float]:
    min_x, max_x, min_y, max_y, min_z, max_z = _summary_child_bounds(root_obj, obj)
    return [round(value, 4) for value in (min_x, max_x, min_y, max_y, min_z, max_z)]


def _summary_child_bounds(root_obj, child) -> SummaryBounds:
    if isinstance(child, SummaryChildSnapshot):
        return child.bounds
    return object_local_bounds(root_obj, child)


def snapshot_summary_child(root_obj, child) -> SummaryChildSnapshot:
    bounds = object_local_bounds(root_obj, child)
    props = {str(key): child.get(key) for key in child.keys()}
    material = child.material_slots[0].material if getattr(child, "material_slots", None) and child.material_slots else None
    return SummaryChildSnapshot(
        name=str(child.name),
        props=props,
        bounds=bounds,
        hide_viewport=bool(getattr(child, "hide_viewport", False)),
        hide_render=bool(getattr(child, "hide_render", False)),
        material_slot0_name=str(material.name) if material is not None else "",
        material_diffuse_rgba=(
            tuple(float(channel) for channel in material.diffuse_color[:4])
            if material is not None and getattr(material, "diffuse_color", None) is not None
            else None
        ),
    )


def _summary_child_material_slot0_name(child) -> str:
    if isinstance(child, SummaryChildSnapshot):
        return str(child.material_slot0_name or "")
    material = child.material_slots[0].material if getattr(child, "material_slots", None) and child.material_slots else None
    return str(material.name) if material is not None else ""


def _summary_child_material_diffuse_rgba(child) -> tuple[float, float, float, float] | None:
    if isinstance(child, SummaryChildSnapshot):
        return child.material_diffuse_rgba
    material = child.material_slots[0].material if getattr(child, "material_slots", None) and child.material_slots else None
    if material is None or getattr(material, "diffuse_color", None) is None:
        return None
    return tuple(float(channel) for channel in material.diffuse_color[:4])


def _window_fill_actual_color_is_blue(child, *, tolerance: float = 0.05) -> bool:
    color = _summary_child_material_diffuse_rgba(child)
    if color is None:
        return False
    return all(
        abs(float(color[index]) - float(WINDOW_FILL_EXPECTED_COLOR[index])) <= tolerance
        for index in range(3)
    )


def _combine_bounds(bounds_items: list[list[float]]) -> list[float] | None:
    if not bounds_items:
        return None
    min_x = min(item[0] for item in bounds_items)
    max_x = max(item[1] for item in bounds_items)
    min_y = min(item[2] for item in bounds_items)
    max_y = max(item[3] for item in bounds_items)
    min_z = min(item[4] for item in bounds_items)
    max_z = max(item[5] for item in bounds_items)
    return [round(value, 4) for value in (min_x, max_x, min_y, max_y, min_z, max_z)]


def _wall_face_coord_for_side(spec, side_key: str) -> float:
    if side_key == "front":
        return -spec.depth / 2
    if side_key == "back":
        return spec.depth / 2
    if side_key == "left":
        return -spec.width / 2
    if side_key == "right":
        return spec.width / 2
    raise ValueError(f"Unsupported side key for wall face lookup: {side_key}")


def _inner_wall_face_coord_for_side(spec, side_key: str) -> float:
    wall_t = float(spec.wall_thickness)
    if side_key == "front":
        return -spec.depth / 2 + wall_t
    if side_key == "back":
        return spec.depth / 2 - wall_t
    if side_key == "left":
        return -spec.width / 2 + wall_t
    if side_key == "right":
        return spec.width / 2 - wall_t
    raise ValueError(f"Unsupported side key for inner wall face lookup: {side_key}")


def _authored_wall_pos(child, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = child.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _outer_wall_face_coord_for_child(spec, child, side_key: str) -> float:
    wall_pos = _authored_wall_pos(child, ("tbg_window_wall_pos", "tbg_door_wall_pos"))
    if wall_pos is None:
        return _wall_face_coord_for_side(spec, side_key)
    wall_t = float(spec.wall_thickness)
    if side_key in {"front", "left"}:
        return wall_pos - wall_t / 2
    return wall_pos + wall_t / 2


def _inner_wall_face_coord_for_child(spec, child, side_key: str) -> float:
    wall_pos = _authored_wall_pos(child, ("tbg_window_wall_pos", "tbg_door_wall_pos"))
    if wall_pos is None:
        return _inner_wall_face_coord_for_side(spec, side_key)
    wall_t = float(spec.wall_thickness)
    if side_key in {"front", "left"}:
        return wall_pos + wall_t / 2
    return wall_pos - wall_t / 2


def _outer_clearance_from_bounds(bounds: SummaryBounds | list[float], side_key: str, wall_face: float) -> float:
    min_x, max_x, min_y, max_y = bounds[:4]
    if side_key == "front":
        return round(wall_face - max_y, 4)
    if side_key == "back":
        return round(min_y - wall_face, 4)
    if side_key == "left":
        return round(wall_face - max_x, 4)
    if side_key == "right":
        return round(min_x - wall_face, 4)
    raise ValueError(f"Unsupported side key for clearance lookup: {side_key}")


def _through_wall_outer_clearance_from_bounds(bounds: SummaryBounds | list[float], side_key: str, wall_face: float) -> float:
    min_x, max_x, min_y, max_y = bounds[:4]
    if side_key == "front":
        return round(wall_face - min_y, 4)
    if side_key == "back":
        return round(max_y - wall_face, 4)
    if side_key == "left":
        return round(wall_face - min_x, 4)
    if side_key == "right":
        return round(max_x - wall_face, 4)
    raise ValueError(f"Unsupported side key for through-wall clearance lookup: {side_key}")


def _through_wall_inner_clearance_from_bounds(bounds: SummaryBounds | list[float], side_key: str, wall_face: float) -> float:
    min_x, max_x, min_y, max_y = bounds[:4]
    if side_key == "front":
        return round(max_y - wall_face, 4)
    if side_key == "back":
        return round(wall_face - min_y, 4)
    if side_key == "left":
        return round(max_x - wall_face, 4)
    if side_key == "right":
        return round(wall_face - min_x, 4)
    raise ValueError(f"Unsupported side key for through-wall inner clearance lookup: {side_key}")


def _summary_object(value, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise GenerationSummaryContractError(f"{label} must be a JSON object.")
    return value


def _summary_list(value, *, label: str) -> list:
    if not isinstance(value, list):
        raise GenerationSummaryContractError(f"{label} must be a JSON array.")
    return value


def _summary_bool(value, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise GenerationSummaryContractError(f"{label} must be a boolean.")
    return value


def _summary_int(value, *, label: str) -> int:
    if isinstance(value, bool):
        raise GenerationSummaryContractError(f"{label} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GenerationSummaryContractError(f"{label} must be an integer.") from exc


def _summary_float(value, *, label: str) -> float:
    if isinstance(value, bool):
        raise GenerationSummaryContractError(f"{label} must be numeric.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise GenerationSummaryContractError(f"{label} must be numeric.") from exc


def _summary_optional_float(value, *, label: str) -> float | None:
    if value is None:
        return None
    return _summary_float(value, label=label)


def _summary_text(value, *, label: str) -> str:
    if not isinstance(value, str):
        raise GenerationSummaryContractError(f"{label} must be a string.")
    return value


def _summary_bounds(value, *, label: str) -> SummaryBounds:
    bounds = _summary_list(value, label=label)
    if len(bounds) != 6:
        raise GenerationSummaryContractError(f"{label} must contain 6 numeric bounds values.")
    return tuple(_summary_float(item, label=f"{label}[{index}]") for index, item in enumerate(bounds))


def _summary_bounds_array(value, *, label: str) -> tuple[SummaryBounds, ...]:
    return tuple(
        _summary_bounds(item, label=f"{label}[{index}]")
        for index, item in enumerate(_summary_list(value, label=label))
    )


def build_generation_summary(
    root_obj,
    spec=None,
    spatial_plan=None,
    *,
    summary_children: tuple[SummaryChildSnapshot, ...] | None = None,
) -> dict:
    children = list(summary_children) if summary_children is not None else [
        child for child in root_obj.children_recursive if child.type == "MESH"
    ]
    window_markers = [child for child in children if child.get("tbg_window_marker")]
    window_slots = sorted(
        (
            {
                "side": str(child.get("tbg_window_side", "")),
                "floor": int(child.get("tbg_window_floor", -1)),
                "slot": int(child.get("tbg_facade_slot", child.get("tbg_window_slot", -1))),
                "state": str(child.get("tbg_window_state", "")),
                "open": bool(child.get("tbg_window_open")),
                "reserved_open": bool(child.get("tbg_window_reserved_open")),
                "reserved_closed": bool(child.get("tbg_window_reserved_closed")),
                "balcony_access": bool(child.get("tbg_balcony_access")),
                "span_key": str(child.get("tbg_balcony_span_key", "")),
                "sill_height": round(float(child.get("tbg_window_sill_height", 0.0)), 4),
                "opening_height": round(float(child.get("tbg_window_opening_height", 0.0)), 4),
                "opening_width": round(float(child.get("tbg_window_opening_width", 0.0)), 4),
            }
            for child in window_markers
            if str(child.get("tbg_window_side", ""))
            and int(child.get("tbg_window_floor", -1)) >= 0
            and int(child.get("tbg_facade_slot", child.get("tbg_window_slot", -1))) >= 0
        ),
        key=lambda item: (item["side"], item["floor"], item["slot"]),
    )
    window_bounds = [
        {
            "floor": int(child.get("tbg_window_floor", -1)),
            "bounds": _summary_item_bounds(root_obj, child),
        }
        for child in window_markers
    ]
    window_frames = [child for child in children if child.get("tbg_window_frame_outer")]
    door_frames = [
        child
        for child in children
        if child.get("tbg_door_frame")
        and str(child.get("tbg_facade_side", "front")) in {"front", "back", "left", "right"}
    ]
    open_windows = [child for child in window_markers if child.get("tbg_window_open")]
    fake_open_windows = [child for child in open_windows if child.get("tbg_window_has_fill")]
    closed_window_fills = [child for child in children if child.get("tbg_window_fill")]
    matte_window_fills = [
        child
        for child in closed_window_fills
        if str(child.get("tbg_window_fill_mode", "")) == "matte"
        and str(child.get("tbg_window_fill_material", "")) == WINDOW_FILL_MATERIAL_NAME
    ]
    glossy_window_fills = [
        child
        for child in closed_window_fills
        if str(child.get("tbg_window_fill_material", "")) == "TBG_Glass"
    ]
    wrong_actual_window_fill_materials = [
        child
        for child in closed_window_fills
        if _summary_child_material_slot0_name(child) != WINDOW_FILL_MATERIAL_NAME
    ]
    non_blue_actual_window_fills = [
        child
        for child in closed_window_fills
        if not _window_fill_actual_color_is_blue(child)
    ]
    lower_facade_bounds = [
        _summary_item_bounds(root_obj, child)
        for child in children
        if child.get("tbg_lower_facade_blocker")
    ]
    perimeter_corner_overlap_names = []
    if spec is not None:
        side_prefixes = (
            "Left_F",
            "Right_F",
            "FacadeBand_Left",
            "FacadeBand_Right",
            "Parapet_Left",
            "Parapet_Right",
            "ParapetCap_Left",
            "ParapetCap_Right",
        )
        front_limit = -spec.depth / 2 + 0.005
        back_limit = spec.depth / 2 - 0.005
        for child in children:
            if not any(child.name.startswith(prefix) for prefix in side_prefixes):
                continue
            if (
                child.get("tbg_window_marker")
                or child.get("tbg_window_frame_outer")
                or child.get("tbg_window_fill")
                or child.get("tbg_balcony")
                or child.get("tbg_entry_canopy")
                or child.get("tbg_drainpipe")
                or child.get("tbg_roof_service")
                or child.get("tbg_service_detail")
                or child.get("tbg_facade_ac")
                or child.get("tbg_is_door_leaf")
            ):
                continue
            _min_x, _max_x, min_y, max_y, _min_z, _max_z = _summary_child_bounds(root_obj, child)
            if min_y <= front_limit or max_y >= back_limit:
                perimeter_corner_overlap_names.append(child.name)
    perimeter_corner_overlap_names = sorted(set(perimeter_corner_overlap_names))

    window_outer_frame_clearance_min = 0.0
    window_inner_frame_clearance_min = 0.0
    door_frame_clearance_min = 0.0
    door_inner_frame_clearance_min = 0.0
    entry_detail_clearance_min = 0.0
    window_fill_center_offset_max = 0.0
    parapet_cap_clearance_min = 0.0
    if spec is not None:
        window_clearances = []
        for child in window_frames:
            side_key = str(child.get("tbg_facade_side", ""))
            if side_key not in {"front", "back", "left", "right"}:
                continue
            wall_face = _outer_wall_face_coord_for_child(spec, child, side_key)
            window_clearances.append(
                _through_wall_outer_clearance_from_bounds(_summary_child_bounds(root_obj, child), side_key, wall_face)
            )
        inner_window_clearances = []
        for child in window_frames:
            side_key = str(child.get("tbg_facade_side", ""))
            if side_key not in {"front", "back", "left", "right"}:
                continue
            wall_face = _inner_wall_face_coord_for_child(spec, child, side_key)
            inner_window_clearances.append(
                _through_wall_inner_clearance_from_bounds(_summary_child_bounds(root_obj, child), side_key, wall_face)
            )
        door_frame_clearances = []
        for child in door_frames:
            side_key = str(child.get("tbg_facade_side", "front"))
            wall_face = _outer_wall_face_coord_for_child(spec, child, side_key)
            door_frame_clearances.append(
                _through_wall_outer_clearance_from_bounds(_summary_child_bounds(root_obj, child), side_key, wall_face)
            )
        inner_door_clearances = []
        for child in door_frames:
            side_key = str(child.get("tbg_facade_side", "front"))
            wall_face = _inner_wall_face_coord_for_child(spec, child, side_key)
            inner_door_clearances.append(
                _through_wall_inner_clearance_from_bounds(_summary_child_bounds(root_obj, child), side_key, wall_face)
            )
        entry_detail_clearances = []
        for child in children:
            if not child.get("tbg_entry_detail"):
                continue
            side_key = str(child.get("tbg_facade_side", "front"))
            wall_face = _wall_face_coord_for_side(spec, side_key)
            entry_detail_clearances.append(
                _outer_clearance_from_bounds(_summary_child_bounds(root_obj, child), side_key, wall_face)
            )
        fill_center_offsets = []
        for child in closed_window_fills:
            side_key = str(child.get("tbg_facade_side", ""))
            wall_pos = float(child.get("tbg_window_wall_pos", 0.0))
            if side_key not in {"front", "back", "left", "right"}:
                continue
            bounds = _summary_child_bounds(root_obj, child)
            center_coord = (bounds[2] + bounds[3]) / 2 if side_key in {"front", "back"} else (bounds[0] + bounds[1]) / 2
            fill_center_offsets.append(abs(center_coord - wall_pos))
        parapet_cap_clearances = []
        for child in children:
            if not child.get("tbg_parapet_cap"):
                continue
            side_key = str(child.get("tbg_facade_side", ""))
            if side_key not in {"front", "back", "left", "right"}:
                continue
            wall_face = _wall_face_coord_for_side(spec, side_key)
            parapet_cap_clearances.append(
                _outer_clearance_from_bounds(_summary_child_bounds(root_obj, child), side_key, wall_face)
            )
        if window_clearances:
            window_outer_frame_clearance_min = round(min(window_clearances), 4)
        if inner_window_clearances:
            window_inner_frame_clearance_min = round(min(inner_window_clearances), 4)
        if door_frame_clearances:
            door_frame_clearance_min = round(min(door_frame_clearances), 4)
        if inner_door_clearances:
            door_inner_frame_clearance_min = round(min(inner_door_clearances), 4)
        if entry_detail_clearances:
            entry_detail_clearance_min = round(min(entry_detail_clearances), 4)
        if fill_center_offsets:
            window_fill_center_offset_max = round(max(fill_center_offsets), 4)
        if parapet_cap_clearances:
            parapet_cap_clearance_min = round(min(parapet_cap_clearances), 4)

    balconies = []
    for child in children:
        if not child.get("tbg_balcony"):
            continue
        balconies.append(
            {
                "side": str(child.get("tbg_balcony_side", "")),
                "floor": int(child.get("tbg_balcony_floor", -1)),
                "span_center": float(child.get("tbg_balcony_span_center", 0.0)),
                "span_width": float(child.get("tbg_balcony_span_width", 0.0)),
                "outward_sign": float(child.get("tbg_balcony_outward_sign", 0.0)),
                "span_key": str(child.get("tbg_balcony_span_key", "")),
                "bounds": _summary_item_bounds(root_obj, child),
            }
        )

    canopies = [_summary_item_bounds(root_obj, child) for child in children if child.get("tbg_entry_canopy")]
    roof_exit_bounds = None
    if spec is not None:
        spatial_plan = _spatial_plan(spec) if spatial_plan is None else spatial_plan
        roof_exit_bounds = _spatial_plan_roof_room_bounds(spatial_plan)
        if roof_exit_bounds is not None:
            roof_exit_bounds = [round(value, 4) for value in roof_exit_bounds]
    facade_ac = []
    for child in children:
        if not child.get("tbg_facade_ac"):
            continue
        facade_ac.append(
            {
                "side": str(child.get("tbg_facade_side", "")),
                "floor": int(child.get("tbg_facade_floor", -1)),
                "along": float(child.get("tbg_facade_along", 0.0)),
                "half_span": float(child.get("tbg_facade_half_span", 0.0)),
                "bounds": _summary_item_bounds(root_obj, child),
            }
        )

    drainpipes = []
    wall_pipe_parts = []
    roof_service = []
    for child in children:
        pipe_part = str(child.get("tbg_wall_pipe_part", ""))
        if pipe_part in {"trunk", "top_bend", "bottom_bend"}:
            wall_pipe_parts.append(
                {
                    "part": pipe_part,
                    "bounds": _summary_item_bounds(root_obj, child),
                }
            )
        if child.get("tbg_drainpipe"):
            bounds = _summary_item_bounds(root_obj, child)
            drainpipes.append(
                {
                    "primary": bool(child.get("tbg_drainpipe_primary") or child.get("tbg_primary_service_riser")),
                    "visible": bool(child.get("tbg_drainpipe_visible")),
                    "anchor_id": str(child.get("tbg_service_anchor_id", "")),
                    "bounds": bounds,
                }
            )
        if child.get("tbg_roof_service") or child.get("tbg_service_role") in {"cooling_duct", "utility_cabinet"}:
            roof_service.append(
                {
                    "role": str(child.get("tbg_service_role", "")),
                    "anchor_id": str(child.get("tbg_service_anchor_id", "")),
                    "side": str(child.get("tbg_pipe_side", child.get("tbg_service_anchor_side", ""))),
                    "edge_inset": float(child.get("tbg_roof_pipe_edge_inset", 0.0)),
                    "roof_flavor": bool(child.get("tbg_roof_flavor")),
                    "bounds": _summary_item_bounds(root_obj, child),
                }
            )

    entrance_part_bounds = [
        _summary_item_bounds(root_obj, child)
        for child in children
        if child.get("tbg_entrance_part") in {"landing", "step"} and not (child.hide_viewport and child.hide_render)
    ]
    entrance_parts = [
        child
        for child in children
        if child.get("tbg_entrance_part") in {"landing", "step"}
    ]
    landing = next((child for child in children if child.get("tbg_entrance_part") == "landing"), None)
    entrance_left_limit = None
    entrance_right_limit = None
    entrance_front_limit = None
    for child in entrance_parts:
        left_limit = child.get("tbg_entry_left_limit")
        right_limit = child.get("tbg_entry_right_limit")
        front_limit = child.get("tbg_entry_front_limit")
        if left_limit is not None and right_limit is not None and front_limit is not None:
            try:
                entrance_left_limit = float(left_limit)
                entrance_right_limit = float(right_limit)
                entrance_front_limit = float(front_limit)
                break
            except (TypeError, ValueError):
                continue
    entrance = {
        "landing_count": sum(1 for child in children if child.get("tbg_entrance_part") == "landing"),
        "step_count": sum(1 for child in children if child.get("tbg_entrance_part") == "step"),
        "has_interior_compensator": any(child.get("tbg_entry_interior") for child in children),
        "has_foundation_podium": any(child.get("tbg_foundation_podium") for child in children),
        "top_z": float(landing.get("tbg_entrance_top_z", 0.0)) if landing else 0.0,
        "threshold_z": float(landing.get("tbg_entrance_threshold_z", 0.0)) if landing else 0.0,
        "left_limit": entrance_left_limit,
        "right_limit": entrance_right_limit,
        "front_limit": entrance_front_limit,
        "part_bounds": entrance_part_bounds,
    }
    return {
        constants.SUMMARY_ADDON_VERSION_FIELD: constants.ADDON_VERSION,
        constants.SUMMARY_SCHEMA_VERSION_FIELD: constants.SUMMARY_SCHEMA_VERSION,
        constants.SUMMARY_EXPORT_CONTRACT_VERSION_FIELD: export_contract.EXPORT_CONTRACT_VERSION,
        "windows": {
            "slots": window_slots,
            "bounds": window_bounds,
            "frame_count": len(window_frames),
            "frame_outer_clearance_min": window_outer_frame_clearance_min,
            "frame_inner_clearance_min": window_inner_frame_clearance_min,
            "open_fill_leak_count": len(fake_open_windows),
            "closed_fill_count": len(closed_window_fills),
            "closed_fill_matte_count": len(matte_window_fills),
            "closed_fill_glossy_count": len(glossy_window_fills),
            "closed_fill_wrong_actual_material_count": len(wrong_actual_window_fill_materials),
            "closed_fill_non_blue_actual_material_count": len(non_blue_actual_window_fills),
            "fill_center_offset_max": window_fill_center_offset_max,
        },
        "lower_facade_bounds": lower_facade_bounds,
        "perimeter_corner_overlap_names": perimeter_corner_overlap_names,
        "balconies": balconies,
        "canopies": canopies,
        "roof_exit_bounds": roof_exit_bounds,
        "facade_ac": facade_ac,
        "services": {
            "drainpipes": drainpipes,
            "blocking_wall_pipe_parts": wall_pipe_parts,
            "roof_items": roof_service,
        },
        "doors": {
            "frame_count": len(door_frames),
            "frame_outer_clearance_min": door_frame_clearance_min,
            "frame_inner_clearance_min": door_inner_frame_clearance_min,
            "has_legacy_trim": any("DoorTrim_" in child.name for child in children),
            "has_loose_detail": any(child.get("tbg_door_detail") for child in children),
        },
        "entry_detail_clearance_min": entry_detail_clearance_min,
        "parapet_cap_clearance_min": parapet_cap_clearance_min,
        "room_partitions": {
            "count": sum(1 for child in children if child.get("tbg_room_partition")),
            "frame_count": sum(1 for child in children if child.get("tbg_room_partition_frame")),
        },
        "entrance": entrance,
    }


def parse_generation_summary(summary: dict) -> GenerationSummaryFacts:
    if not isinstance(summary, dict):
        raise GenerationSummaryContractError("Stored generation summary must decode to a JSON object.")
    windows = _summary_object(summary.get("windows"), label="Stored generation summary.windows")
    services = _summary_object(summary.get("services"), label="Stored generation summary.services")
    doors = _summary_object(summary.get("doors"), label="Stored generation summary.doors")
    room_partitions = _summary_object(
        summary.get("room_partitions"),
        label="Stored generation summary.room_partitions",
    )
    entrance = _summary_object(summary.get("entrance"), label="Stored generation summary.entrance")
    roof_exit_bounds = summary.get("roof_exit_bounds")
    return GenerationSummaryFacts(
        addon_version=_summary_text(
            summary.get(constants.SUMMARY_ADDON_VERSION_FIELD),
            label=f"Stored generation summary.{constants.SUMMARY_ADDON_VERSION_FIELD}",
        ),
        summary_schema_version=_summary_text(
            summary.get(constants.SUMMARY_SCHEMA_VERSION_FIELD),
            label=f"Stored generation summary.{constants.SUMMARY_SCHEMA_VERSION_FIELD}",
        ),
        export_contract_version=_summary_text(
            summary.get(constants.SUMMARY_EXPORT_CONTRACT_VERSION_FIELD),
            label=f"Stored generation summary.{constants.SUMMARY_EXPORT_CONTRACT_VERSION_FIELD}",
        ),
        windows=WindowsSummary(
            slots=tuple(
                WindowSlotSummary(
                    side=_summary_text(item.get("side"), label=f"windows.slots[{index}].side"),
                    floor=_summary_int(item.get("floor"), label=f"windows.slots[{index}].floor"),
                    slot=_summary_int(item.get("slot"), label=f"windows.slots[{index}].slot"),
                    state=_summary_text(item.get("state"), label=f"windows.slots[{index}].state"),
                    open=_summary_bool(item.get("open"), label=f"windows.slots[{index}].open"),
                    reserved_open=_summary_bool(
                        item.get("reserved_open"),
                        label=f"windows.slots[{index}].reserved_open",
                    ),
                    reserved_closed=_summary_bool(
                        item.get("reserved_closed"),
                        label=f"windows.slots[{index}].reserved_closed",
                    ),
                    balcony_access=_summary_bool(
                        item.get("balcony_access"),
                        label=f"windows.slots[{index}].balcony_access",
                    ),
                    span_key=_summary_text(item.get("span_key"), label=f"windows.slots[{index}].span_key"),
                    sill_height=_summary_float(
                        item.get("sill_height"),
                        label=f"windows.slots[{index}].sill_height",
                    ),
                    opening_height=_summary_float(
                        item.get("opening_height"),
                        label=f"windows.slots[{index}].opening_height",
                    ),
                    opening_width=_summary_float(
                        item.get("opening_width"),
                        label=f"windows.slots[{index}].opening_width",
                    ),
                )
                for index, item in enumerate(
                    _summary_list(windows.get("slots"), label="Stored generation summary.windows.slots")
                )
                for item in [_summary_object(item, label=f"Stored generation summary.windows.slots[{index}]")]
            ),
            bounds=tuple(
                WindowBoundsSummary(
                    floor=_summary_int(item.get("floor"), label=f"windows.bounds[{index}].floor"),
                    bounds=_summary_bounds(item.get("bounds"), label=f"windows.bounds[{index}].bounds"),
                )
                for index, item in enumerate(
                    _summary_list(windows.get("bounds"), label="Stored generation summary.windows.bounds")
                )
                for item in [_summary_object(item, label=f"Stored generation summary.windows.bounds[{index}]")]
            ),
            frame_count=_summary_int(windows.get("frame_count"), label="windows.frame_count"),
            frame_outer_clearance_min=_summary_float(
                windows.get("frame_outer_clearance_min"),
                label="windows.frame_outer_clearance_min",
            ),
            frame_inner_clearance_min=_summary_float(
                windows.get("frame_inner_clearance_min"),
                label="windows.frame_inner_clearance_min",
            ),
            open_fill_leak_count=_summary_int(
                windows.get("open_fill_leak_count"),
                label="windows.open_fill_leak_count",
            ),
            closed_fill_count=_summary_int(
                windows.get("closed_fill_count"),
                label="windows.closed_fill_count",
            ),
            closed_fill_matte_count=_summary_int(
                windows.get("closed_fill_matte_count"),
                label="windows.closed_fill_matte_count",
            ),
            closed_fill_glossy_count=_summary_int(
                windows.get("closed_fill_glossy_count"),
                label="windows.closed_fill_glossy_count",
            ),
            closed_fill_wrong_actual_material_count=_summary_int(
                windows.get("closed_fill_wrong_actual_material_count", 0),
                label="windows.closed_fill_wrong_actual_material_count",
            ),
            closed_fill_non_blue_actual_material_count=_summary_int(
                windows.get("closed_fill_non_blue_actual_material_count", 0),
                label="windows.closed_fill_non_blue_actual_material_count",
            ),
            fill_center_offset_max=_summary_float(
                windows.get("fill_center_offset_max"),
                label="windows.fill_center_offset_max",
            ),
        ),
        lower_facade_bounds=_summary_bounds_array(
            summary.get("lower_facade_bounds"),
            label="Stored generation summary.lower_facade_bounds",
        ),
        perimeter_corner_overlap_names=tuple(
            _summary_text(item, label=f"Stored generation summary.perimeter_corner_overlap_names[{index}]")
            for index, item in enumerate(
                _summary_list(
                    summary.get("perimeter_corner_overlap_names"),
                    label="Stored generation summary.perimeter_corner_overlap_names",
                )
            )
        ),
        balconies=tuple(
            BalconySummary(
                side=_summary_text(item.get("side"), label=f"balconies[{index}].side"),
                floor=_summary_int(item.get("floor"), label=f"balconies[{index}].floor"),
                span_center=_summary_float(item.get("span_center"), label=f"balconies[{index}].span_center"),
                span_width=_summary_float(item.get("span_width"), label=f"balconies[{index}].span_width"),
                outward_sign=_summary_float(item.get("outward_sign"), label=f"balconies[{index}].outward_sign"),
                span_key=_summary_text(item.get("span_key"), label=f"balconies[{index}].span_key"),
                bounds=_summary_bounds(item.get("bounds"), label=f"balconies[{index}].bounds"),
            )
            for index, item in enumerate(
                _summary_list(summary.get("balconies"), label="Stored generation summary.balconies")
            )
            for item in [_summary_object(item, label=f"Stored generation summary.balconies[{index}]")]
        ),
        canopies=_summary_bounds_array(summary.get("canopies"), label="Stored generation summary.canopies"),
        roof_exit_bounds=None
        if roof_exit_bounds is None
        else _summary_bounds(roof_exit_bounds, label="Stored generation summary.roof_exit_bounds"),
        facade_ac=tuple(
            FacadeAcSummary(
                side=_summary_text(item.get("side"), label=f"facade_ac[{index}].side"),
                floor=_summary_int(item.get("floor"), label=f"facade_ac[{index}].floor"),
                along=_summary_float(item.get("along"), label=f"facade_ac[{index}].along"),
                half_span=_summary_float(item.get("half_span"), label=f"facade_ac[{index}].half_span"),
                bounds=_summary_bounds(item.get("bounds"), label=f"facade_ac[{index}].bounds"),
            )
            for index, item in enumerate(
                _summary_list(summary.get("facade_ac"), label="Stored generation summary.facade_ac")
            )
            for item in [_summary_object(item, label=f"Stored generation summary.facade_ac[{index}]")]
        ),
        services=ServicesSummary(
            drainpipes=tuple(
                DrainpipeSummary(
                    primary=_summary_bool(item.get("primary"), label=f"services.drainpipes[{index}].primary"),
                    visible=_summary_bool(item.get("visible"), label=f"services.drainpipes[{index}].visible"),
                    anchor_id=_summary_text(item.get("anchor_id"), label=f"services.drainpipes[{index}].anchor_id"),
                    bounds=_summary_bounds(item.get("bounds"), label=f"services.drainpipes[{index}].bounds"),
                )
                for index, item in enumerate(
                    _summary_list(services.get("drainpipes"), label="Stored generation summary.services.drainpipes")
                )
                for item in [_summary_object(item, label=f"Stored generation summary.services.drainpipes[{index}]")]
            ),
            blocking_wall_pipe_parts=tuple(
                BlockingWallPipePartSummary(
                    part=_summary_text(
                        item.get("part"),
                        label=f"services.blocking_wall_pipe_parts[{index}].part",
                    ),
                    bounds=_summary_bounds(
                        item.get("bounds"),
                        label=f"services.blocking_wall_pipe_parts[{index}].bounds",
                    ),
                )
                for index, item in enumerate(
                    _summary_list(
                        services.get("blocking_wall_pipe_parts"),
                        label="Stored generation summary.services.blocking_wall_pipe_parts",
                    )
                )
                for item in [
                    _summary_object(
                        item,
                        label=f"Stored generation summary.services.blocking_wall_pipe_parts[{index}]",
                    )
                ]
            ),
            roof_items=tuple(
                RoofServiceItemSummary(
                    role=_summary_text(item.get("role"), label=f"services.roof_items[{index}].role"),
                    anchor_id=_summary_text(item.get("anchor_id"), label=f"services.roof_items[{index}].anchor_id"),
                    side=_summary_text(item.get("side"), label=f"services.roof_items[{index}].side"),
                    edge_inset=_summary_float(
                        item.get("edge_inset"),
                        label=f"services.roof_items[{index}].edge_inset",
                    ),
                    roof_flavor=_summary_bool(
                        item.get("roof_flavor"),
                        label=f"services.roof_items[{index}].roof_flavor",
                    ),
                    bounds=_summary_bounds(item.get("bounds"), label=f"services.roof_items[{index}].bounds"),
                )
                for index, item in enumerate(
                    _summary_list(services.get("roof_items"), label="Stored generation summary.services.roof_items")
                )
                for item in [_summary_object(item, label=f"Stored generation summary.services.roof_items[{index}]")]
            ),
        ),
        doors=DoorsSummary(
            frame_count=_summary_int(doors.get("frame_count"), label="doors.frame_count"),
            frame_outer_clearance_min=_summary_float(
                doors.get("frame_outer_clearance_min"),
                label="doors.frame_outer_clearance_min",
            ),
            frame_inner_clearance_min=_summary_float(
                doors.get("frame_inner_clearance_min"),
                label="doors.frame_inner_clearance_min",
            ),
            has_legacy_trim=_summary_bool(doors.get("has_legacy_trim"), label="doors.has_legacy_trim"),
            has_loose_detail=_summary_bool(doors.get("has_loose_detail"), label="doors.has_loose_detail"),
        ),
        entry_detail_clearance_min=_summary_float(
            summary.get("entry_detail_clearance_min"),
            label="Stored generation summary.entry_detail_clearance_min",
        ),
        parapet_cap_clearance_min=_summary_float(
            summary.get("parapet_cap_clearance_min"),
            label="Stored generation summary.parapet_cap_clearance_min",
        ),
        room_partitions=RoomPartitionsSummary(
            count=_summary_int(room_partitions.get("count"), label="room_partitions.count"),
            frame_count=_summary_int(room_partitions.get("frame_count"), label="room_partitions.frame_count"),
        ),
        entrance=EntranceSummary(
            landing_count=_summary_int(entrance.get("landing_count"), label="entrance.landing_count"),
            step_count=_summary_int(entrance.get("step_count"), label="entrance.step_count"),
            has_interior_compensator=_summary_bool(
                entrance.get("has_interior_compensator"),
                label="entrance.has_interior_compensator",
            ),
            has_foundation_podium=_summary_bool(
                entrance.get("has_foundation_podium"),
                label="entrance.has_foundation_podium",
            ),
            top_z=_summary_float(entrance.get("top_z"), label="entrance.top_z"),
            threshold_z=_summary_float(entrance.get("threshold_z"), label="entrance.threshold_z"),
            left_limit=_summary_optional_float(entrance.get("left_limit"), label="entrance.left_limit"),
            right_limit=_summary_optional_float(entrance.get("right_limit"), label="entrance.right_limit"),
            front_limit=_summary_optional_float(entrance.get("front_limit"), label="entrance.front_limit"),
            part_bounds=_summary_bounds_array(
                entrance.get("part_bounds"),
                label="Stored generation summary.entrance.part_bounds",
            ),
        ),
    )
