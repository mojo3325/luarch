from __future__ import annotations

import json
import math

from .. import export_contract
from ..generator.building_layout import (
    REAR_ACCESS_PROFILE_NONE,
    REAR_ACCESS_PROFILE_OPEN_BAY,
    REAR_ACCESS_PROFILE_SERVICE_DOOR,
    REAR_ACCESS_PROFILE_SHELL_ONLY,
    TERMINAL_PROFILE_ATTIC_OPEN,
    TERMINAL_PROFILE_FULL_ROOM,
    TERMINAL_PROFILE_STAIR_HEAD,
    TOP_TERMINAL_PLAYABLE_TOP_ROOM,
    _roof_surface_z,
    _terrace_transition_contract,
)
from ..generator.building_facade_frontage_recipes import (
    resolve_frontage_entry_pose as _resolve_frontage_entry_pose,
)
from ..generator.building_support import object_local_bounds
from ..generator.specs import (
    FACADE_MODE_SPLIT,
    ROOF_MODE_BARREL,
    ROOF_MODE_FLAT,
    ROOF_MODE_GABLE,
    ROOF_MODE_SHED,
    ROOF_MODE_TERRACE,
    center_stair_gameplay_requirements,
    gameplay_outer_minimums,
    normalized_balcony_mode,
    side_sign,
    supported_facade_families,
)
from .validation_facts import (
    EXPOSED_STAIR_WINDOW_OPTIONAL_PRESET_IDS,
    CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS,
    FRAME_INNER_RETURN_MIN_STUDS,
    FRAME_RING_WIDTH_MIN_STUDS,
    FRAME_SILHOUETTE_MIN_STUDS,
    MIN_NON_THICKNESS_CELL_SPAN_STUDS,
    MIN_WALL_PLANE_AREA_COVERAGE_RATIO,
    OPENING_VISUAL_SEAL_GAP_MAX_STUDS,
    ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN,
    RESIDENTIAL_BORDER_MIN_STUDS,
    SERVICE_HEAVY_WALL_PIPE_PRESET_IDS,
    TRIM_BACK_AIR_GAP_MAX_STUDS,
    TRIM_BACK_OVERLAP_MIN_STUDS,
    ValidationFacts,
    WINDOW_FILL_EXPECTED_COLOR,
    WINDOW_FILL_MATERIAL_NAME,
    WINDOW_OPTIONAL_PRESET_IDS,
    WOOD_PRESET_IDS,
)
from .validation_rules_service_roof import (
    collect_collision_runtime_roof_service_issues,
    collect_service_roof_issues,
)


ROLE_BALCONY_ACCESS_OPENING = export_contract.ROLE_BALCONY_ACCESS_OPENING
ROLE_BALCONY_FLOOR = export_contract.ROLE_BALCONY_FLOOR
ROLE_BALCONY_RAIL = export_contract.ROLE_BALCONY_RAIL
ROLE_ENTRY_LANDING = export_contract.ROLE_ENTRY_LANDING
ROLE_ENTRY_WEDGE = export_contract.ROLE_ENTRY_WEDGE
ROLE_FLOOR_BLOCKER = export_contract.ROLE_FLOOR_BLOCKER
ROLE_MAIN_ENTRY_DOOR = export_contract.ROLE_MAIN_ENTRY_DOOR
ROLE_OPEN_WINDOW_OPENING = export_contract.ROLE_OPEN_WINDOW_OPENING
ROLE_PARTITION = export_contract.ROLE_PARTITION
ROLE_PODIUM_BLOCKER = export_contract.ROLE_PODIUM_BLOCKER
ROLE_ROOF_BLOCKER = export_contract.ROLE_ROOF_BLOCKER
ROLE_ROOF_EXIT_SHELL = export_contract.ROLE_ROOF_EXIT_SHELL
ROLE_SHELL = export_contract.ROLE_SHELL
ROLE_STAIR_LANDING = export_contract.ROLE_STAIR_LANDING
ROLE_STAIR_STEP = export_contract.ROLE_STAIR_STEP
ROLE_STAIR_WEDGE = export_contract.ROLE_STAIR_WEDGE
ROLE_WINDOW_CLOSED = export_contract.ROLE_WINDOW_CLOSED
ROLE_WINDOW_SILL = export_contract.ROLE_WINDOW_SILL
RUNTIME_SHAPE_BOX = export_contract.RUNTIME_SHAPE_BOX
RUNTIME_SHAPE_WEDGE = export_contract.RUNTIME_SHAPE_WEDGE
_EXPORT_POLICY_WARNING_PREFIXES = (
    "Storefront/service upper floors have too few open windows:",
    "Building has too few open windows:",
    "Upper panel floors became fully closed; expected at least some playable open windows.",
    "Upper panel floors are too open; expected mostly closed windows.",
    "Roof-access opening collision warning:",
)


def is_export_policy_warning(issue: str) -> bool:
    return str(issue).startswith(_EXPORT_POLICY_WARNING_PREFIXES)


def _uses_legacy_collision_lane(facts: ValidationFacts) -> bool:
    structural_roles = {
        ROLE_BALCONY_FLOOR,
        ROLE_BALCONY_RAIL,
        ROLE_MAIN_ENTRY_DOOR,
        ROLE_PARTITION,
        ROLE_ROOF_BLOCKER,
        ROLE_SHELL,
        ROLE_WINDOW_CLOSED,
        ROLE_WINDOW_SILL,
    }
    return any(
        str(marker.get("tbg_runtime_role", "")) in structural_roles
        for marker in facts.marker_facts.collision_markers
    )


def _bounds_overlap_2d(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1]) and max(a[2], b[2]) < min(a[3], b[3])


def _bounds_overlap_3d(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> bool:
    return (
        max(a[0], b[0]) < min(a[1], b[1])
        and max(a[2], b[2]) < min(a[3], b[3])
        and max(a[4], b[4]) < min(a[5], b[5])
    )


def _overlap_extent(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(float(a1), float(b1)) - max(float(a0), float(b0))


def _bounds_intrude_3d(
    a: list[float] | tuple[float, ...],
    b: list[float] | tuple[float, ...],
    *,
    planar_tolerance: float = 1e-3,
    vertical_tolerance: float = 1e-4,
) -> bool:
    return (
        _overlap_extent(a[0], a[1], b[0], b[1]) > planar_tolerance
        and _overlap_extent(a[2], a[3], b[2], b[3]) > planar_tolerance
        and _overlap_extent(a[4], a[5], b[4], b[5]) > vertical_tolerance
    )


def _span_contains(span: tuple[float, float], value: float, *, tolerance: float = 1e-4) -> bool:
    return float(span[0]) - tolerance <= float(value) <= float(span[1]) + tolerance


def _has_inverted_bottom_face(root_obj, obj) -> bool:
    mesh = getattr(obj, "data", None)
    if mesh is None or not hasattr(mesh, "polygons") or not mesh.polygons or not getattr(mesh, "vertices", None):
        return False
    root_inv = root_obj.matrix_world.inverted()
    min_z = min((root_inv @ (obj.matrix_world @ vertex.co)).z for vertex in mesh.vertices)
    threshold = min_z + 0.02
    for poly in mesh.polygons:
        center = root_inv @ (obj.matrix_world @ poly.center)
        normal = (root_inv.to_3x3() @ obj.matrix_world.to_3x3() @ poly.normal).normalized()
        if center.z <= threshold and normal.z > 0.35:
            return True
    return False


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _has_named_door_leaf(children, suffix: str, *, roof_exit: bool = False) -> bool:
    for child in children:
        if not child.get("tbg_is_door_leaf"):
            continue
        if roof_exit and not child.get("tbg_roof_exit_door"):
            continue
        if child.name.endswith(suffix):
            return True
    return False


def _count_mesh_tagged(facts: ValidationFacts, tag: str) -> int:
    return sum(1 for child in facts.mesh_children if child.get(tag))


def _count_render_tagged(facts: ValidationFacts, tag: str) -> int:
    return sum(1 for child in facts.render_mesh_children if child.get(tag))


def _is_authored_exterior_fragment(obj) -> bool:
    return bool(obj.get("tbg_exterior_brick")) or bool(obj.get("tbg_exterior_surface_tile"))


def _effective_render_object_count(facts: ValidationFacts) -> int:
    count = 0
    counted_opening_proof_lane = False
    for child in facts.render_mesh_children:
        if _is_authored_exterior_fragment(child):
            continue
        if child.get("tbg_wall_opening_kind"):
            if counted_opening_proof_lane:
                continue
            counted_opening_proof_lane = True
        count += 1
    return count


def _wood_floor_material_count(facts: ValidationFacts) -> int:
    return sum(
        1
        for child in facts.mesh_children
        if any(slot.material is not None and slot.material.name == "TBG_WoodFloor" for slot in child.material_slots)
    )


def _storefront_kind_counts(facts: ValidationFacts) -> dict[str, int]:
    counts: dict[str, int] = {}
    for child in facts.mesh_children:
        if not child.get("tbg_storefront_part"):
            continue
        kind = str(child.get("tbg_storefront_part_kind", "")).strip().upper()
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _light_marker_roles(facts: ValidationFacts) -> frozenset[str]:
    return frozenset(str(marker.get("tbg_runtime_role", "")) for marker in facts.marker_facts.light_markers)


def _roof_render_meshes(facts: ValidationFacts) -> tuple[object, ...]:
    return tuple(
        child
        for child in facts.render_mesh_children
        if str(child.get("tbg_section_bucket", "")) == "Section_Walls_Roof"
    )


def _roof_section_count(facts: ValidationFacts) -> int:
    return len(_roof_render_meshes(facts))


def _roof_vertical_relief(facts: ValidationFacts) -> float:
    roof_render_meshes = _roof_render_meshes(facts)
    if not roof_render_meshes:
        return 0.0
    roof_bounds = [object_local_bounds(facts.root_obj, child) for child in roof_render_meshes]
    return max(bounds[5] for bounds in roof_bounds) - min(bounds[4] for bounds in roof_bounds)


def _root_local_mesh_z_band_count(root_obj, objects: tuple[object, ...], *, precision: int = 2) -> int:
    if not objects:
        return 0
    root_inv = root_obj.matrix_world.inverted()
    values: set[float] = set()
    for obj in objects:
        mesh = getattr(obj, "data", None)
        if mesh is None or not hasattr(mesh, "vertices"):
            continue
        for vertex in mesh.vertices:
            local_coord = root_inv @ (obj.matrix_world @ vertex.co)
            values.add(round(float(local_coord.z), precision))
    return len(values)


def _roof_z_band_count(facts: ValidationFacts) -> int:
    return _root_local_mesh_z_band_count(facts.root_obj, _roof_render_meshes(facts))


def _infer_roof_opening_bounds_from_blockers(
    facts: ValidationFacts,
) -> tuple[float, float, float, float] | None:
    opening_contract_bounds = facts.contract_roof_opening_bounds or facts.contract_roof_exit_bounds
    if opening_contract_bounds is None:
        return None
    room_z_min = float(opening_contract_bounds[4])
    room_z_max = float(opening_contract_bounds[5])
    # Only the top-roof blocker band should drive roof-cutout inference.
    # Terrace transition blockers (explicit lower runtime floors) are excluded.
    z_band_padding = max(0.4, min(1.2, room_z_max - room_z_min))
    blocker_bounds: list[tuple[float, float, float, float, float, float]] = []
    for marker in facts.marker_facts.collision_markers:
        if str(marker.get("tbg_runtime_role", "")) != ROLE_ROOF_BLOCKER:
            continue
        runtime_floor = int(marker.get("tbg_runtime_floor", -1))
        if runtime_floor >= 0 and runtime_floor != facts.floor_count:
            continue
        bounds = object_local_bounds(facts.root_obj, marker)
        if float(bounds[5]) < room_z_min - z_band_padding or float(bounds[4]) > room_z_max + 0.2:
            continue
        blocker_bounds.append(bounds)
    if not blocker_bounds:
        return None
    center_x = (float(opening_contract_bounds[0]) + float(opening_contract_bounds[1])) / 2
    center_y = (float(opening_contract_bounds[2]) + float(opening_contract_bounds[3])) / 2
    left_edges: list[float] = []
    right_edges: list[float] = []
    front_edges: list[float] = []
    back_edges: list[float] = []
    for bounds in blocker_bounds:
        if float(bounds[2]) < center_y < float(bounds[3]):
            if float(bounds[1]) <= center_x + 1e-4:
                left_edges.append(float(bounds[1]))
            if float(bounds[0]) >= center_x - 1e-4:
                right_edges.append(float(bounds[0]))
        if float(bounds[0]) < center_x < float(bounds[1]):
            if float(bounds[3]) <= center_y + 1e-4:
                front_edges.append(float(bounds[3]))
            if float(bounds[2]) >= center_y - 1e-4:
                back_edges.append(float(bounds[2]))
    if not (left_edges and right_edges and front_edges and back_edges):
        return None
    opening_x0 = max(left_edges)
    opening_x1 = min(right_edges)
    opening_y0 = max(front_edges)
    opening_y1 = min(back_edges)
    if opening_x1 <= opening_x0 or opening_y1 <= opening_y0:
        return None
    return (opening_x0, opening_x1, opening_y0, opening_y1)


def _opening_contains_room(
    opening_bounds: tuple[float, float, float, float],
    room_bounds: tuple[float, float, float, float, float, float],
    *,
    tolerance: float = 0.08,
) -> bool:
    return (
        float(opening_bounds[0]) <= float(room_bounds[0]) + tolerance
        and float(opening_bounds[1]) >= float(room_bounds[1]) - tolerance
        and float(opening_bounds[2]) <= float(room_bounds[2]) + tolerance
        and float(opening_bounds[3]) >= float(room_bounds[3]) - tolerance
    )


def _roof_top_shell_sides(facts: ValidationFacts) -> frozenset[str]:
    return frozenset(
        str(marker.get("tbg_runtime_side", ""))
        for marker in facts.marker_facts.collision_markers
        if str(marker.get("tbg_runtime_role", "")) == ROLE_SHELL
        and int(marker.get("tbg_runtime_floor", -1)) == facts.floor_count
        and str(marker.get("tbg_runtime_side", "")) in {"front", "back", "left", "right"}
    )


def _terrace_transition_floor_index(facts: ValidationFacts) -> int | None:
    transition_floor_index, _upper_shell_rect, _open_sides = _terrace_transition_contract(facts.effective_spec)
    return transition_floor_index


def _shell_sides_on_floor(facts: ValidationFacts, floor_index: int) -> frozenset[str]:
    return frozenset(
        str(marker.get("tbg_runtime_side", ""))
        for marker in facts.marker_facts.collision_markers
        if str(marker.get("tbg_runtime_role", "")) == ROLE_SHELL
        and int(marker.get("tbg_runtime_floor", -1)) == int(floor_index)
        and str(marker.get("tbg_runtime_side", "")) in {"front", "back", "left", "right"}
    )


_TERRACE_RUNTIME_SOURCE_TOKENS = ("TerraceDeck", "TerraceRail", "TerraceInnerParapet")


def _is_terrace_runtime_source_name(source_name: str) -> bool:
    return bool(source_name) and any(token in source_name for token in _TERRACE_RUNTIME_SOURCE_TOKENS)


def _is_terrace_runtime_marker(marker) -> bool:
    source_name = str(marker.get("tbg_runtime_source_name", "")) or str(getattr(marker, "name", ""))
    return _is_terrace_runtime_source_name(source_name)


def _terrace_runtime_floor_mismatches(facts: ValidationFacts, expected_floor: int) -> tuple[str, ...]:
    mismatched_sources: set[str] = set()
    for marker in facts.marker_facts.collision_markers:
        source_name = str(marker.get("tbg_runtime_source_name", ""))
        if not _is_terrace_runtime_source_name(source_name):
            continue
        runtime_floor = int(marker.get("tbg_runtime_floor", -1))
        if runtime_floor != int(expected_floor):
            mismatched_sources.add(source_name)
    return tuple(sorted(mismatched_sources))


def _facade_authored_floors(facts: ValidationFacts) -> frozenset[int]:
    return frozenset(
        int(floor_index)
        for child in facts.render_mesh_children
        for floor_index in (child.get("tbg_facade_floor"),)
        if floor_index is not None
    )


def _construction_frame_count(facts: ValidationFacts) -> int:
    return _count_mesh_tagged(facts, "tbg_construction_frame")


def _bounds_center_y(bounds: tuple[float, float, float, float, float, float] | list[float]) -> float:
    return (float(bounds[2]) + float(bounds[3])) / 2


def _entry_marker_access_side(facts: ValidationFacts, marker) -> str:
    explicit_side = str(marker.get("tbg_runtime_side", "")).strip().lower()
    if explicit_side == "front":
        return "front"
    if explicit_side in {"back", "rear"}:
        return "rear"

    marker_center_y = _bounds_center_y(object_local_bounds(facts.root_obj, marker))
    front_center_y = _bounds_center_y(facts.front_door_bounds) if facts.front_door_bounds is not None else None
    rear_center_y = _bounds_center_y(facts.rear_door_bounds) if facts.rear_door_bounds is not None else None
    if front_center_y is not None and rear_center_y is not None:
        return "front" if abs(marker_center_y - front_center_y) <= abs(marker_center_y - rear_center_y) else "rear"
    if rear_center_y is not None:
        return "rear"
    if front_center_y is not None:
        return "front"
    return "front" if marker_center_y <= 0.0 else "rear"


def _rear_entry_package_role_counts(facts: ValidationFacts) -> dict[str, int]:
    roles = {ROLE_ENTRY_LANDING, ROLE_ENTRY_WEDGE, ROLE_PODIUM_BLOCKER}
    counts: dict[str, int] = {}
    for marker in facts.marker_facts.collision_markers:
        role = str(marker.get("tbg_runtime_role", ""))
        if role not in roles:
            continue
        if _entry_marker_access_side(facts, marker) != "rear":
            continue
        counts[role] = counts.get(role, 0) + 1
    return counts


def _rear_opening_blocker_names(facts: ValidationFacts) -> tuple[str, ...]:
    if not facts.rear_through_access:
        return tuple()
    opening_core_boxes: list[tuple[float, float, float, float, float, float]] = []
    spec = facts.effective_spec
    wall_t = float(facts.wall_thickness)
    wall_center_y = float(spec.depth / 2 - wall_t / 2)
    half_depth = max(0.02, wall_t / 2 - 0.003)
    for child in facts.mesh_children:
        if not child.name.endswith("Door_Rear"):
            continue
        if not child.get("tbg_is_door_leaf"):
            continue
        if not (child.get("tbg_rear_through_access") or str(child.get("tbg_facade_side", "")) == "back"):
            continue
        bounds = object_local_bounds(facts.root_obj, child)
        core_x0 = bounds[0] + 0.03
        core_x1 = bounds[1] - 0.03
        core_y0 = wall_center_y - half_depth
        core_y1 = wall_center_y + half_depth
        core_z0 = bounds[4] + 0.08
        core_z1 = bounds[5] - 0.08
        if core_x1 <= core_x0 or core_y1 <= core_y0 or core_z1 <= core_z0:
            continue
        opening_core_boxes.append((core_x0, core_x1, core_y0, core_y1, core_z0, core_z1))

    if not opening_core_boxes:
        return tuple()

    root_inv = facts.root_obj.matrix_world.inverted()
    blockers: list[str] = []
    for child in facts.mesh_children:
        if child.get("tbg_runtime_marker") or child.get("tbg_door_frame") or child.get("tbg_is_door_leaf"):
            continue
        section_bucket = str(child.get("tbg_section_bucket", ""))
        if section_bucket not in {
            "Section_Walls_Exterior",
            "Section_Walls_ExteriorSurfaceTile",
            "Section_Walls_Interior",
            "Section_Stairs_RoomShell",
            "Section_Openings_Trim_Wall",
        }:
            continue
        mesh = getattr(child, "data", None)
        if mesh is None or not hasattr(mesh, "polygons") or not mesh.polygons:
            continue
        for poly in mesh.polygons:
            center = root_inv @ (child.matrix_world @ poly.center)
            if any(
                core_bounds[0] < center.x < core_bounds[1]
                and core_bounds[2] < center.y < core_bounds[3]
                and core_bounds[4] < center.z < core_bounds[5]
                for core_bounds in opening_core_boxes
            ):
                blockers.append(child.name)
                break
    return tuple(sorted(set(blockers)))


def _has_roof_setback_meshes(facts: ValidationFacts) -> bool:
    return any("RoofSetback_" in child.name for child in facts.render_mesh_children)


def _terrace_band_rects(
    facts: ValidationFacts,
    *,
    upper_shell_rect: tuple[float, float, float, float],
    open_sides: tuple[str, ...],
) -> tuple[tuple[float, float, float, float], ...]:
    full_rect = (
        -float(facts.width) / 2,
        float(facts.width) / 2,
        -float(facts.depth) / 2,
        float(facts.depth) / 2,
    )
    full_x0, full_x1, full_y0, full_y1 = full_rect
    shell_x0, shell_x1, shell_y0, shell_y1 = (
        float(upper_shell_rect[0]),
        float(upper_shell_rect[1]),
        float(upper_shell_rect[2]),
        float(upper_shell_rect[3]),
    )
    rects: list[tuple[float, float, float, float]] = []
    for side in open_sides:
        if side == "front":
            rect = (full_x0, full_x1, full_y0, shell_y0)
        elif side == "back":
            rect = (full_x0, full_x1, shell_y1, full_y1)
        elif side == "left":
            rect = (full_x0, shell_x0, shell_y0, shell_y1)
        elif side == "right":
            rect = (shell_x1, full_x1, shell_y0, shell_y1)
        else:
            continue
        if rect[1] - rect[0] > 1e-4 and rect[3] - rect[2] > 1e-4:
            rects.append(rect)
    return tuple(rects)


def _collect_terrace_exit_issues(
    facts: ValidationFacts,
    *,
    transition_floor_index: int,
    open_sides: tuple[str, ...],
) -> list[str]:
    valid_slots = [
        slot
        for slot in facts.summary.windows.slots
        if int(slot.floor) == int(transition_floor_index)
        and str(slot.side) in open_sides
        and bool(slot.open)
        and bool(slot.reserved_open)
        and not bool(slot.balcony_access)
    ]
    exit_count = len(valid_slots)
    if exit_count == 1:
        return []
    if exit_count > 1:
        return [
            "Terrace transition floor must reserve exactly one terrace-exit opening, "
            + f"but found {exit_count}."
        ]
    return [
        "Terrace transition floor has no reserved open terrace-exit opening on any exposed terrace side."
    ]


def _collect_terrace_stack_balcony_issues(
    facts: ValidationFacts,
    *,
    transition_floor_index: int,
) -> list[str]:
    issues: list[str] = []
    terrace_stack_balconies = [
        balcony
        for balcony in facts.summary.balconies
        if int(balcony.floor) >= int(transition_floor_index)
    ]
    if terrace_stack_balconies:
        first = terrace_stack_balconies[0]
        issues.append(
            "Balcony geometry is forbidden on terrace stack floors, but found balcony on "
            + f"{first.side} F{int(first.floor):02d}."
        )
    terrace_stack_access_windows = [
        slot
        for slot in facts.summary.windows.slots
        if int(slot.floor) >= int(transition_floor_index) and bool(slot.balcony_access)
    ]
    if terrace_stack_access_windows:
        first = terrace_stack_access_windows[0]
        issues.append(
            "Balcony-access window semantics leaked onto terrace stack floors at "
            + f"{first.side} F{int(first.floor):02d} S{int(first.slot):02d}."
        )
    marker_roles = {ROLE_BALCONY_FLOOR, ROLE_BALCONY_RAIL, ROLE_BALCONY_ACCESS_OPENING}
    leaked_markers = [
        marker
        for marker in facts.marker_facts.collision_markers
        if str(marker.get("tbg_runtime_role", "")) in marker_roles
        and int(marker.get("tbg_runtime_floor", -1)) >= int(transition_floor_index)
        and not _is_terrace_runtime_marker(marker)
    ]
    if leaked_markers:
        marker = leaked_markers[0]
        issues.append(
            "Balcony runtime markers leaked onto terrace stack floors: role="
            + str(marker.get("tbg_runtime_role", ""))
            + ", floor="
            + str(int(marker.get("tbg_runtime_floor", -1)))
            + "."
        )
    return issues


def _collect_terrace_overhead_coverage_issues(
    facts: ValidationFacts,
    *,
    transition_floor_index: int,
    upper_shell_rect: tuple[float, float, float, float],
    open_sides: tuple[str, ...],
) -> list[str]:
    terrace_band_rects = _terrace_band_rects(facts, upper_shell_rect=upper_shell_rect, open_sides=open_sides)
    if not terrace_band_rects:
        return []

    offending_sources: list[str] = []
    seen: set[str] = set()
    for marker in facts.marker_facts.collision_markers:
        role = str(marker.get("tbg_runtime_role", ""))
        if role not in {ROLE_ROOF_BLOCKER, ROLE_FLOOR_BLOCKER}:
            continue
        runtime_floor = int(marker.get("tbg_runtime_floor", -1))
        is_overhead_candidate = (
            role == ROLE_ROOF_BLOCKER
            or runtime_floor > int(transition_floor_index)
            or runtime_floor < 0
        )
        if not is_overhead_candidate:
            continue
        bounds = object_local_bounds(facts.root_obj, marker)
        xy_bounds = (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
        if not any(_bounds_overlap_2d(xy_bounds, band_rect) for band_rect in terrace_band_rects):
            continue
        source_name = str(marker.get("tbg_runtime_source_name", "")) or str(getattr(marker, "name", ""))
        if source_name in seen:
            continue
        seen.add(source_name)
        offending_sources.append(source_name)

    if not offending_sources:
        return []
    return [
        "Open terrace band is covered by overhead roof/slab blocker geometry: "
        + ", ".join(offending_sources[:3])
        + ("." if len(offending_sources) <= 3 else ", ...")
    ]


def _brick_density_signature(root_obj, obj) -> dict[str, tuple[float, float]]:
    mesh = getattr(obj, "data", None)
    if mesh is None or not hasattr(mesh, "polygons") or not mesh.polygons:
        return {}
    uv_layer = getattr(mesh.uv_layers, "get", lambda _name: None)("TBG_UV")
    if uv_layer is None:
        return {}
    root_inv = root_obj.matrix_world.inverted()
    normal_transform = root_inv.to_3x3() @ obj.matrix_world.to_3x3()
    buckets: dict[str, dict[str, list[float]]] = {}
    for poly in mesh.polygons:
        normal = normal_transform @ poly.normal
        if normal.length <= 1e-8:
            continue
        normal.normalize()
        loops = list(poly.loop_indices)
        verts = [obj.matrix_world @ mesh.vertices[mesh.loops[index].vertex_index].co for index in loops]
        uvs = [uv_layer.data[index].uv.copy() for index in loops]
        if abs(normal.y) >= 0.95:
            key = "front_back"
            span_u = max(v.x for v in verts) - min(v.x for v in verts)
            span_v = max(v.z for v in verts) - min(v.z for v in verts)
        elif abs(normal.x) >= 0.95:
            key = "side"
            span_u = max(v.y for v in verts) - min(v.y for v in verts)
            span_v = max(v.z for v in verts) - min(v.z for v in verts)
        else:
            continue
        delta_u = max(uv.x for uv in uvs) - min(uv.x for uv in uvs)
        delta_v = max(uv.y for uv in uvs) - min(uv.y for uv in uvs)
        bucket = buckets.setdefault(key, {"u": [], "v": []})
        if span_u > 1e-5:
            bucket["u"].append(delta_u / span_u)
        if span_v > 1e-5:
            bucket["v"].append(delta_v / span_v)
    signatures = {}
    for key, values in buckets.items():
        if values["u"] and values["v"]:
            signatures[key] = (_median(values["u"]), _median(values["v"]))
    return signatures


def _uses_storefront_frontage(facts: ValidationFacts) -> bool:
    return (
        str(facts.effective_spec.ground_floor_tactical_profile).upper() == "STOREFRONT"
        and facts.preset_id != "clinic"
    )


def _requires_storefront_entry_evidence(facts: ValidationFacts) -> bool:
    return False


def _uses_industrial_closed_opening_language(facts: ValidationFacts) -> bool:
    return facts.preset_id in SERVICE_HEAVY_WALL_PIPE_PRESET_IDS


def _uses_profiled_industrial_doctrine(facts: ValidationFacts) -> bool:
    rear_access_profile = str(facts.rear_access_profile).upper()
    return (
        facts.preset_id in SERVICE_HEAVY_WALL_PIPE_PRESET_IDS
        and rear_access_profile in {REAR_ACCESS_PROFILE_SERVICE_DOOR, REAR_ACCESS_PROFILE_OPEN_BAY}
    )


def _industrial_rear_vertical_contract(
    facts: ValidationFacts,
    slot,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if not _uses_profiled_industrial_doctrine(facts):
        return None
    if str(slot.side) != "back" or int(slot.floor) != 0:
        return None
    if bool(slot.balcony_access) or str(slot.state) in {"MASK", "STAIR", "BALCONY"}:
        return None
    rear_access_profile = str(facts.rear_access_profile).upper()
    if rear_access_profile == REAR_ACCESS_PROFILE_OPEN_BAY:
        return ((0.56, 1.08), (0.9, 1.5))
    if rear_access_profile == REAR_ACCESS_PROFILE_SERVICE_DOOR:
        return ((0.68, 1.2), (0.95, 1.55))
    return None


def _requires_facade_windows(facts: ValidationFacts) -> bool:
    return facts.preset_id not in WINDOW_OPTIONAL_PRESET_IDS


def _skip_facade_shell_slot_guard(facts: ValidationFacts, side: str, floor: int) -> bool:
    if facts.preset_id in {"hangar", "under_construction"}:
        return True
    if facts.massing_profile == "PILOTIS" and floor == 0 and side in {"back", "left", "right"}:
        return True
    if side == "front" and floor == 0 and (
        _uses_storefront_frontage(facts)
        or _uses_industrial_closed_opening_language(facts)
        or facts.preset_id in {"clinic", "market_hall"}
    ):
        return True
    return False


def _collect_facade_shell_slot_issues(facts: ValidationFacts) -> list[str]:
    if not _uses_legacy_collision_lane(facts):
        return []
    issues: list[str] = []
    for side_floor, authored_slot_count in sorted(facts.authored_window_slot_count_by_side_floor.items()):
        side, floor = side_floor
        if authored_slot_count <= 0 or _skip_facade_shell_slot_guard(facts, side, floor):
            continue
        shell_slot_count = int(facts.shell_slot_count_by_side_floor.get((side, floor), 0))
        expected_min_shell_slots = max(1, min(authored_slot_count, (authored_slot_count + 1) // 2))
        if shell_slot_count < expected_min_shell_slots:
            issues.append(
                "Facade shell evidence collapsed around authored opening slots: "
                f"{side} F{floor:02d} shell slots {shell_slot_count} < {expected_min_shell_slots}."
            )
            break
    return issues


def _requires_exposed_stair_windows(facts: ValidationFacts) -> bool:
    return (
        facts.preset_id not in EXPOSED_STAIR_WINDOW_OPTIONAL_PRESET_IDS
        and facts.effective_spec.stair_window_mode == "EXPOSED"
        and facts.effective_spec.stair_core.enabled
        and facts.effective_spec.stair_core.placement != "CENTER"
    )


def _requires_wall_service_pipes(facts: ValidationFacts) -> bool:
    return facts.preset_id in SERVICE_HEAVY_WALL_PIPE_PRESET_IDS


def _collect_transform_material_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    if facts.drifting_children:
        issues.append("Generated children have non-identity parent inverse; regenerate transform may drift.")
    if facts.multi_material_children:
        issues.append(
            "Some merged sections still carry multiple materials, which can collapse incorrectly on Roblox import: "
            + ", ".join(sorted(facts.multi_material_children)[:6])
        )
    if facts.hidden_wall_sections:
        issues.append(
            "Wall sections are hidden, so facade/export can lose the solid exterior shell: "
            + ", ".join(facts.hidden_wall_sections[:6])
        )
    if facts.brick_mesh_children and facts.brick_projection_modes != ("ROOT_LOCAL",):
        issues.append(
            "Brick sections are not sharing one root-local UV projection contract before merge: "
            + ", ".join(facts.brick_projection_modes or ("<missing>",))
        )
    if facts.brick_mesh_children and len(facts.brick_uv_scales) > 1:
        issues.append(
            "Brick sections drifted to multiple UV scales before merge: "
            + ", ".join(str(scale) for scale in facts.brick_uv_scales)
        )
    final_bad_brick_projection = sorted(
        child.name
        for child in facts.brick_mesh_children
        if str(child.get("tbg_brick_uv_space", "")) != "ROOT_LOCAL"
    )
    if final_bad_brick_projection:
        issues.append(
            "Merged brick sections lost the shared root-local UV projection contract: "
            + ", ".join(final_bad_brick_projection[:6])
        )
    final_brick_scales = sorted(
        {
            round(float(child.get("tbg_brick_uv_scale", 0.0)), 4)
            for child in facts.brick_mesh_children
        }
    )
    if len(final_brick_scales) > 1:
        issues.append(
            "Merged brick sections are using inconsistent UV scales: "
            + ", ".join(str(scale) for scale in final_brick_scales)
        )
    if facts.brick_mesh_children:
        density_by_orientation: dict[str, list[tuple[str, float, float]]] = {}
        for child in facts.brick_mesh_children:
            for orientation, (density_u, density_v) in _brick_density_signature(facts.root_obj, child).items():
                density_by_orientation.setdefault(orientation, []).append((child.name, density_u, density_v))
        for orientation, values in density_by_orientation.items():
            if len(values) < 2:
                continue
            ref_u = _median([value[1] for value in values])
            ref_v = _median([value[2] for value in values])
            drifted = [
                name
                for name, density_u, density_v in values
                if (
                    (ref_u > 1e-6 and abs(density_u - ref_u) / ref_u > 0.08)
                    or (ref_v > 1e-6 and abs(density_v - ref_v) / ref_v > 0.08)
                )
            ]
            if drifted:
                issues.append(
                    f"Brick UV density drifted across merged {orientation} sections: "
                    + ", ".join(sorted(drifted)[:6])
                )
    if facts.summary.perimeter_corner_overlap_names:
        issues.append(
            "Side perimeter meshes still reach front/back corner planes and can flicker in Roblox: "
            + ", ".join(facts.summary.perimeter_corner_overlap_names[:8])
        )
    if len(facts.atlas_images) > 1:
        issues.append(
            "Generated building is still using multiple export texture images instead of a shared atlas: "
            + ", ".join(facts.atlas_images)
            + "."
        )
    if facts.summary.windows.slots and "Section_Openings_Frame" not in facts.render_section_buckets:
        issues.append("Merged render is missing the dedicated window-frame section.")
    if facts.summary.windows.closed_fill_wrong_actual_material_count:
        issues.append(
            "Generation summary detected closed-window fill objects with non-window actual material slot."
        )
    if facts.summary.windows.closed_fill_non_blue_actual_material_count:
        issues.append(
            "Generation summary detected closed-window fill objects whose actual material color is not matte blue."
        )
    window_fill_wrong_materials = tuple(
        fact
        for fact in facts.voxel_wall_facts.window_fill_visual_truths
        if fact.material_name != WINDOW_FILL_MATERIAL_NAME
    )
    if window_fill_wrong_materials:
        samples = ", ".join(
            f"{fact.object_name}={fact.material_name or '<missing>'}"
            for fact in window_fill_wrong_materials[:6]
        )
        issues.append(
            f"Closed-window visual material truth failed: {len(window_fill_wrong_materials)} "
            f"fill object(s) do not use actual slot-0 {WINDOW_FILL_MATERIAL_NAME}: {samples}."
        )
    non_blue_window_fills = tuple(
        fact
        for fact in facts.voxel_wall_facts.window_fill_visual_truths
        if fact.diffuse_rgba is None
        or not all(
            abs(float(fact.diffuse_rgba[index]) - float(WINDOW_FILL_EXPECTED_COLOR[index])) <= 0.05
            for index in range(3)
        )
    )
    if non_blue_window_fills:
        samples = ", ".join(
            f"{fact.object_name}={tuple(round(float(channel), 3) for channel in fact.diffuse_rgba[:3]) if fact.diffuse_rgba else '<missing>'}"
            for fact in non_blue_window_fills[:6]
        )
        issues.append(
            f"Closed-window visual color truth failed: {len(non_blue_window_fills)} "
            f"{WINDOW_FILL_MATERIAL_NAME} fill object(s) are not descriptor-blue: {samples}."
        )
    shader_non_blue_window_fills = tuple(
        fact
        for fact in facts.voxel_wall_facts.window_fill_visual_truths
        if fact.shader_rgb is None
        or not all(
            abs(float(fact.shader_rgb[index]) - float(WINDOW_FILL_EXPECTED_COLOR[index])) <= 0.05
            for index in range(3)
        )
    )
    if shader_non_blue_window_fills:
        samples = ", ".join(
            (
                f"{fact.object_name}=<missing shader sample>"
                if fact.shader_rgb is None
                else f"{fact.object_name}={tuple(round(float(channel), 3) for channel in fact.shader_rgb)}"
            )
            for fact in shader_non_blue_window_fills[:6]
        )
        issues.append(
            f"Closed-window shader truth failed: {len(shader_non_blue_window_fills)} "
            f"{WINDOW_FILL_MATERIAL_NAME} fill object(s) would not render descriptor-blue in Material Preview: {samples}."
        )
    uv_missing_window_fills = tuple(
        fact for fact in facts.voxel_wall_facts.window_fill_visual_truths if fact.uv_missing
    )
    if uv_missing_window_fills:
        issues.append(
            "Closed-window shader UV truth failed: UV-backed window-fill material is assigned to object(s) with no usable UVs: "
            + ", ".join(fact.object_name for fact in uv_missing_window_fills[:6])
            + ("." if len(uv_missing_window_fills) <= 6 else ", ...")
        )
    overlapping_window_fills = tuple(
        fact
        for fact in facts.voxel_wall_facts.window_fill_visual_truths
        if fact.same_plane_overlap_cell_ids
    )
    if overlapping_window_fills:
        samples = ", ".join(
            f"{fact.object_name} -> {', '.join(fact.same_plane_overlap_cell_ids[:3])}"
            for fact in overlapping_window_fills[:4]
        )
        issues.append(
            f"Closed-window V3 overlap truth failed: {facts.voxel_wall_facts.window_fill_same_plane_v3_overlap_count} "
            f"same-plane authored wall cell overlap(s) touch closed window fill bounds/cuts: {samples}."
        )
    door_trim_sections = [
        child
        for child in facts.render_mesh_children
        if str(child.get("tbg_section_bucket", "")) == "Section_Doors_Trim"
    ]
    if facts.summary.doors.frame_count > 0 and "Section_Doors_Trim" not in facts.render_section_buckets:
        issues.append("Merged render is missing the dedicated door-frame section.")
    elif facts.summary.doors.frame_count > 0 and not any(
        any(slot.material is not None and slot.material.name == "TBG_Frame" for slot in child.material_slots)
        for child in door_trim_sections
    ):
        issues.append("Main door frame did not survive consolidation into a dedicated TBG_Frame door section.")
    return issues


def _collect_collision_runtime_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    role_counts = facts.marker_facts.role_counts
    role_shapes = facts.marker_facts.role_shapes
    slot_roles_map = facts.marker_facts.slot_roles
    span_roles_map = facts.marker_facts.span_roles
    floor_roles = facts.marker_facts.floor_roles
    light_marker_roles = _light_marker_roles(facts)
    window_slots = facts.summary.windows.slots
    hangar_portal_family = facts.preset_id == "hangar"
    rear_access_profile = str(facts.rear_access_profile).upper()
    doorless_shell_family = rear_access_profile == REAR_ACCESS_PROFILE_SHELL_ONLY
    depot_open_bay_family = rear_access_profile == REAR_ACCESS_PROFILE_OPEN_BAY
    personnel_door_leaves = tuple(
        child for child in facts.door_leaves if not child.get("tbg_roof_exit_door")
    )

    if doorless_shell_family:
        if facts.door_leaves:
            issues.append("SHELL_ONLY rear access should not generate door leaf geometry.")
        if role_counts.get(ROLE_MAIN_ENTRY_DOOR, 0) > 0:
            issues.append("SHELL_ONLY rear access should not export main-entry door collision.")
    elif depot_open_bay_family:
        if personnel_door_leaves:
            issues.append("Depot open-bay doctrine should not generate any personnel-door leaf geometry.")
        if role_counts.get(ROLE_MAIN_ENTRY_DOOR, 0) > 0:
            issues.append("Depot open-bay doctrine should not export main-entry door collision.")
    elif not facts.door_leaves and not hangar_portal_family:
        issues.append("No generated door leaf found.")
    if (
        not doorless_shell_family
        and not depot_open_bay_family
        and facts.effective_spec.door.enabled
        and not hangar_portal_family
        and not _has_named_door_leaf(facts.mesh_children, "Door_Main")
    ):
        issues.append("Main-entry door leaf is missing the stable Door_Main render contract.")
    if facts.floor_count > 1 and not facts.has_stairs:
        issues.append("Building has multiple floors but no generated stairs.")
    if facts.floor_count > 1 and not facts.has_mid_landing:
        issues.append("Building has multiple floors but no dogleg landings.")
    if window_slots and role_counts.get(ROLE_SHELL, 0) <= 0:
        issues.append("Primitive collision is missing facade shell blockers around authored openings.")
    transition_floor_index, _terrace_shell_rect, terrace_open_sides = _terrace_transition_contract(facts.effective_spec)
    terrace_exit_floor = int(transition_floor_index) if transition_floor_index is not None else None
    terrace_open_side_set = {str(side) for side in terrace_open_sides}
    for slot in window_slots:
        if not slot.side or slot.floor < 0 or slot.slot < 0:
            continue
        slot_roles = slot_roles_map.get((slot.side, slot.floor, slot.slot), frozenset())
        if ROLE_SHELL not in slot_roles:
            issues.append(f"Window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} is missing shell collision strips.")
            break
        terrace_exit_slot = (
            terrace_exit_floor is not None
            and int(slot.floor) == terrace_exit_floor
            and str(slot.side) in terrace_open_side_set
            and bool(slot.open)
            and bool(slot.reserved_open)
            and not bool(slot.balcony_access)
        )
        if terrace_exit_slot:
            if ROLE_OPEN_WINDOW_OPENING not in slot_roles:
                issues.append(f"Terrace-exit slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} is missing OPEN_WINDOW_OPENING.")
                break
            if ROLE_BALCONY_ACCESS_OPENING in slot_roles:
                issues.append(
                    f"Terrace-exit slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} must not export BALCONY_ACCESS_OPENING."
                )
                break
            if ROLE_WINDOW_SILL in slot_roles:
                issues.append(f"Terrace-exit slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} still exports a sill blocker.")
                break
            if slot.opening_width < 0.9 or slot.opening_height < 1.8:
                issues.append(
                    f"Terrace-exit slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} is too small: "
                    f"{slot.opening_width:.2f}m x {slot.opening_height:.2f}m."
                )
                break
            continue
        if slot.balcony_access or slot.state == "BALCONY":
            if ROLE_BALCONY_ACCESS_OPENING not in slot_roles:
                issues.append(f"Balcony-access slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} is missing its opening exemption marker.")
                break
            if ROLE_WINDOW_SILL in slot_roles:
                issues.append(f"Balcony-access slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} still exports a sill blocker.")
                break
            if ROLE_OPEN_WINDOW_OPENING in slot_roles:
                issues.append(f"Balcony-access slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} is using the ordinary open-window role.")
                break
        elif slot.open:
            if ROLE_OPEN_WINDOW_OPENING not in slot_roles:
                issues.append(f"Open window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} is missing its traversable opening marker.")
                break
            if ROLE_WINDOW_SILL in slot_roles:
                issues.append(f"Open window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} still exports a legacy sill blocker.")
                break
            if ROLE_BALCONY_ACCESS_OPENING in slot_roles:
                issues.append(f"Ordinary open window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} was misclassified as a balcony-access opening.")
                break
            if slot.sill_height <= 0.0 or slot.opening_height <= 0.0:
                issues.append(f"Open window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} is missing authored opening geometry metadata.")
                break
            industrial_vertical_contract = _industrial_rear_vertical_contract(facts, slot)
            if industrial_vertical_contract is not None:
                sill_span, opening_span = industrial_vertical_contract
                if not _span_contains(sill_span, slot.sill_height, tolerance=0.02):
                    issues.append(
                        f"Industrial rear open window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} "
                        f"escaped the raised sill-height doctrine: {slot.sill_height:.2f}m not in "
                        f"[{sill_span[0]:.2f}, {sill_span[1]:.2f}]m."
                    )
                    break
                if not _span_contains(opening_span, slot.opening_height, tolerance=0.02):
                    issues.append(
                        f"Industrial rear open window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} "
                        f"escaped the tactical opening-height doctrine: {slot.opening_height:.2f}m not in "
                        f"[{opening_span[0]:.2f}, {opening_span[1]:.2f}]m."
                    )
                    break
                continue
            expected_sill_height, expected_opening_height = facts.expected_open_window_verticals_by_slot.get(
                (str(slot.side), int(slot.floor), int(slot.slot)),
                (facts.standard_sill_height, facts.standard_opening_height),
            )
            vertical_tolerance = 0.02
            if (
                slot.side == "front"
                and int(slot.floor) == max(0, facts.floor_count - 1)
                and facts.roof_mode in {ROOF_MODE_GABLE, ROOF_MODE_SHED}
            ):
                vertical_tolerance = 0.05
            if abs(slot.sill_height - expected_sill_height) > vertical_tolerance:
                issues.append(
                    f"Open window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} drifted away from the standard sill height: "
                    f"{slot.sill_height:.2f}m vs {expected_sill_height:.2f}m."
                )
                break
            if abs(slot.opening_height - expected_opening_height) > vertical_tolerance:
                issues.append(
                    f"Open window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} drifted away from the standard opening height: "
                    f"{slot.opening_height:.2f}m vs {expected_opening_height:.2f}m."
                )
                break
        elif ROLE_WINDOW_CLOSED not in slot_roles:
            issues.append(f"Closed window slot {slot.side} F{slot.floor:02d} S{slot.slot:02d} is missing its closed blocker.")
            break
    if role_counts.get(ROLE_WINDOW_SILL, 0) > 0:
        issues.append("Legacy WINDOW_SILL blockers are still present in the active runtime contract.")

    if facts.effective_spec.stair_core.enabled:
        expected_stair_runs = max(0, facts.floor_count - 1 + int(facts.roof_access_enabled))
        expected_stair_steps = expected_stair_runs * int(facts.effective_spec.stair_core.step_count)
        if expected_stair_steps > 0 and role_counts.get(ROLE_STAIR_STEP, 0) < expected_stair_steps:
            issues.append(
                f"Primitive collision is missing stair step-surfaces: {role_counts.get(ROLE_STAIR_STEP, 0)} < {expected_stair_steps}."
            )
        if role_counts.get(ROLE_STAIR_WEDGE, 0) > 0:
            issues.append("Legacy stair wedges are still present in the active runtime contract.")
        expected_stair_landings = max(1, expected_stair_runs * 2 - int(facts.roof_access_enabled))
        if role_counts.get(ROLE_STAIR_LANDING, 0) < expected_stair_landings:
            issues.append("Primitive collision is missing one or more stair landing blockers.")
        issues.extend(
            collect_collision_runtime_roof_service_issues(
                facts,
                has_named_door_leaf=_has_named_door_leaf,
            )
        )
        if role_counts.get(ROLE_STAIR_STEP, 0) > 0 and role_shapes.get(ROLE_STAIR_STEP, frozenset()) != {RUNTIME_SHAPE_BOX}:
            issues.append("Stair traversal collision is not using the explicit thin-box stair-step contract.")
        if facts.marker_facts.stair_directions != {-1.0, 1.0}:
            issues.append("Stair step export is missing one of the required ascent directions.")

    if facts.entrance_profile != "FLUSH":
        if role_counts.get(ROLE_ENTRY_LANDING, 0) <= 0:
            issues.append("Raised entrance is missing its entry landing blocker.")
        if facts.summary.entrance.threshold_z > 0.0 and role_counts.get(ROLE_ENTRY_WEDGE, 0) <= 0:
            issues.append("Raised entrance is missing its entry traversal wedge.")
        if role_shapes.get(ROLE_ENTRY_WEDGE, frozenset()) not in (frozenset(), {RUNTIME_SHAPE_WEDGE}):
            issues.append("Raised entrance traversal is not using the explicit wedge marker contract.")
        if role_counts.get(ROLE_PODIUM_BLOCKER, 0) <= 0:
            issues.append("Raised entrance is missing its foundation podium blocker.")
    if not doorless_shell_family and facts.effective_spec.door.enabled and role_counts.get(ROLE_MAIN_ENTRY_DOOR, 0) > 0:
        issues.append("Main-entry door collision still depends on a runtime blocker instead of the render door leaf.")
    if role_counts.get(ROLE_FLOOR_BLOCKER, 0) <= 0:
        issues.append("Primitive collision is missing floor blockers.")
    else:
        for floor_index in range(facts.floor_count):
            if floor_roles.get((ROLE_FLOOR_BLOCKER, floor_index), 0) <= 0:
                issues.append(f"Primitive collision is missing a floor blocker for floor {floor_index:02d}.")
                break
    if role_counts.get(ROLE_ROOF_BLOCKER, 0) <= 0:
        issues.append("Primitive collision is missing roof blockers.")
    if facts.wide_partition_eligible and role_counts.get(ROLE_PARTITION, 0) <= 0:
        issues.append("Wide-building partition geometry is missing its primitive partition blockers.")
    for balcony in facts.summary.balconies:
        if not balcony.span_key:
            continue
        span_roles = span_roles_map.get(balcony.span_key, {})
        balcony_label = balcony.span_key or f"{balcony.side} F{balcony.floor:02d}"
        if span_roles.get(ROLE_BALCONY_FLOOR, 0) <= 0 or span_roles.get(ROLE_BALCONY_RAIL, 0) < 3:
            issues.append(f"Balcony '{balcony_label}' is missing its primitive floor or rail blockers.")
            break
        if span_roles.get(ROLE_BALCONY_ACCESS_OPENING, 0) <= 0:
            issues.append(f"Balcony '{balcony_label}' is missing its balcony-access opening exemption marker.")
            break
    for wedge in facts.marker_facts.wedge_markers:
        expected_top = float(wedge.get("tbg_runtime_top_z", 0.0))
        if expected_top <= 0.0:
            continue
        bounds = object_local_bounds(facts.root_obj, wedge)
        if abs(bounds[5] - expected_top) > 0.04:
            issues.append(f"Wedge marker '{wedge.name}' does not land flush to its authored top surface.")
            break
    if not (facts.marker_facts.collision_markers or facts.marker_facts.light_markers):
        issues.append("Runtime sidecar markers are missing; RBXMX export would have no authoritative author-time source.")
    if not facts.marker_facts.light_markers:
        issues.append("RBXMX sidecar light markers are missing.")
    if facts.preset_id != "hangar" and "ROOM" not in light_marker_roles:
        issues.append("Room light markers are missing.")
    if facts.has_stairs and "STAIR" not in light_marker_roles:
        issues.append("Stair light markers are missing.")
    if facts.entrance_profile in {"STOOP_LOW", "PODIUM_HIGH"} and "ENTRY" not in light_marker_roles:
        issues.append("Raised entrance is missing its entry light marker.")
    return issues


def _collect_topology_contract_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    has_collision_markers = _uses_legacy_collision_lane(facts)
    doorless_shell_family = str(facts.rear_access_profile).upper() == REAR_ACCESS_PROFILE_SHELL_ONLY
    roller_door_count = _count_render_tagged(facts, "tbg_roller_door")
    facade_authored_floors = _facade_authored_floors(facts)

    if facts.massing_profile == "PILOTIS" and has_collision_markers:
        open_side_shells = {
            str(marker.get("tbg_runtime_side", ""))
            for marker in facts.marker_facts.collision_markers
            if str(marker.get("tbg_runtime_role", "")) == ROLE_SHELL
            and int(marker.get("tbg_runtime_floor", -1)) == 0
            and str(marker.get("tbg_runtime_side", "")) in {"back", "left", "right"}
        }
        missing_shell_sides = tuple(side for side in ("back", "left", "right") if side not in open_side_shells)
        if missing_shell_sides:
            issues.append(
                "PILOTIS massing is missing surviving ground-floor shell evidence on open sides: "
                + ", ".join(missing_shell_sides)
                + "."
            )
        if any(slot.floor == 0 and slot.side in {"back", "left", "right"} for slot in facts.summary.windows.slots):
            issues.append("PILOTIS massing still authored ground-floor window slots on open back/left/right sides.")

    issues.extend(_collect_roof_contract_issues(facts))

    if doorless_shell_family:
        if roller_door_count > 0:
            issues.append("SHELL_ONLY rear-access doctrine should not export tagged roller-door geometry.")
    elif facts.door_profile == "ROLLER":
        if roller_door_count != 1:
            issues.append(f"ROLLER door contract expects exactly one tagged roller leaf, found {roller_door_count}.")
    elif roller_door_count > 0:
        issues.append("Tagged roller-door geometry is present outside the ROLLER door contract.")

    omitted_floors = range(facts.completed_facade_floors, facts.floor_count)
    for floor_index in omitted_floors:
        if floor_index in facade_authored_floors:
            issues.append(
                f"Facade completion omitted floor {floor_index}, but tagged facade-authored render geometry is still present."
            )
            break
    for floor_index in omitted_floors:
        if any(slot.floor == floor_index for slot in facts.summary.windows.slots):
            issues.append(f"Facade completion omitted floor {floor_index}, but window slots are still authored there.")
            break
    for floor_index in omitted_floors:
        if any(balcony.floor == floor_index for balcony in facts.summary.balconies):
            issues.append(f"Facade completion omitted floor {floor_index}, but balcony geometry is still authored there.")
            break
    for floor_index in omitted_floors:
        if any(ac.floor == floor_index for ac in facts.summary.facade_ac):
            issues.append(f"Facade completion omitted floor {floor_index}, but facade AC geometry is still authored there.")
            break

    return issues


def _collect_non_terrace_roof_contract_issues(facts: ValidationFacts) -> list[str]:
    has_terrace_tagged_meshes = (
        _count_render_tagged(facts, "tbg_terrace_deck") > 0
        or _count_render_tagged(facts, "tbg_terrace_rail") > 0
        or _count_render_tagged(facts, "tbg_terrace_inner_parapet") > 0
    )
    if not has_terrace_tagged_meshes:
        return []
    if _terrace_transition_floor_index(facts) is not None:
        return []
    return ["Tagged terrace-only roof meshes are present outside the terrace-transition contract."]



def _collect_terrace_roof_contract_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    has_collision_markers = _uses_legacy_collision_lane(facts)
    transition_floor_index, upper_shell_rect, open_sides = _terrace_transition_contract(facts.effective_spec)
    if transition_floor_index is None or upper_shell_rect is None or not open_sides:
        return ["Terrace roof evidence is present, but the layout terrace-transition contract is missing."]
    if _count_render_tagged(facts, "tbg_terrace_deck") <= 0:
        issues.append("ROOF_TERRACE generated no tagged terrace deck mesh.")
    if _count_render_tagged(facts, "tbg_terrace_rail") <= 0:
        issues.append("ROOF_TERRACE generated no tagged terrace rail mesh.")
    if _count_render_tagged(facts, "tbg_terrace_inner_parapet") > 0:
        issues.append("Terrace contract forbids inner parapet compensation meshes, but they are still authored.")
    if _count_render_tagged(facts, "tbg_terrace_support") > 0:
        issues.append("Terrace contract forbids gallery/support meshes, but tagged terrace supports are still authored.")
    if has_collision_markers:
        shell_sides = _shell_sides_on_floor(facts, transition_floor_index)
        if not shell_sides:
            issues.append(
                "ROOF_TERRACE generated no reduced-shell wall/shell runtime evidence on the terrace transition floor."
            )
        floor_mismatches = _terrace_runtime_floor_mismatches(facts, transition_floor_index)
        if floor_mismatches:
            issues.append(
                "ROOF_TERRACE runtime-floor metadata must match transition_floor_index; mismatched terrace sources: "
                + ", ".join(floor_mismatches[:3])
                + ("." if len(floor_mismatches) <= 3 else ", ...")
            )
    issues.extend(
        _collect_terrace_exit_issues(
            facts,
            transition_floor_index=int(transition_floor_index),
            open_sides=tuple(open_sides),
        )
    )
    issues.extend(
        _collect_terrace_stack_balcony_issues(
            facts,
            transition_floor_index=int(transition_floor_index),
        )
    )
    issues.extend(
        _collect_terrace_overhead_coverage_issues(
            facts,
            transition_floor_index=int(transition_floor_index),
            upper_shell_rect=tuple(float(value) for value in upper_shell_rect),
            open_sides=tuple(open_sides),
        )
    )
    return issues


def _collect_barrel_roof_contract_issues(facts: ValidationFacts) -> list[str]:
    issues = _collect_non_terrace_roof_contract_issues(facts)
    has_collision_markers = _uses_legacy_collision_lane(facts)
    roof_section_count = _roof_section_count(facts)
    roof_vertical_relief = _roof_vertical_relief(facts)
    roof_z_band_count = _roof_z_band_count(facts)
    roof_top_shell_sides = _roof_top_shell_sides(facts)
    if roof_section_count <= 0:
        issues.append("ROOF_BARREL generated no authored roof render section in Section_Walls_Roof.")
    if roof_vertical_relief < max(3.0, min(facts.width, facts.depth) * 0.36):
        issues.append("ROOF_BARREL roof shell is too shallow to read as a barrel arch.")
    if roof_z_band_count < 6:
        issues.append("ROOF_BARREL roof shell is missing the authored stepped arch profile.")
    if not has_collision_markers:
        return issues
    if facts.preset_id == "hangar":
        missing_shell_sides = tuple(side for side in ("front", "back", "left", "right") if side not in roof_top_shell_sides)
        if missing_shell_sides:
            issues.append(
                "ROOF_BARREL hangar shell is missing roof-level shell closure markers on: "
                + ", ".join(missing_shell_sides)
                + "."
            )
        return issues
    missing_shell_sides = tuple(side for side in ("front", "back", "left", "right") if side not in roof_top_shell_sides)
    if missing_shell_sides:
        issues.append(
            "ROOF_BARREL is missing roof-level shell closure markers on: "
            + ", ".join(missing_shell_sides)
            + "."
        )
    return issues


def _collect_gable_roof_contract_issues(facts: ValidationFacts) -> list[str]:
    issues = _collect_non_terrace_roof_contract_issues(facts)
    has_collision_markers = _uses_legacy_collision_lane(facts)
    roof_section_count = _roof_section_count(facts)
    roof_vertical_relief = _roof_vertical_relief(facts)
    roof_top_shell_sides = _roof_top_shell_sides(facts)
    hangar_gable_family = facts.preset_id == "hangar"
    if roof_section_count <= 0:
        issues.append("ROOF_GABLE generated no authored roof render section in Section_Walls_Roof.")
    if hangar_gable_family:
        minimum_relief = max(1.2, min(facts.width, facts.depth) * 0.08)
        if roof_vertical_relief < minimum_relief:
            issues.append("ROOF_GABLE hangar shallow-gable shell is too shallow for hangar doctrine.")
    elif roof_vertical_relief < max(0.9, min(facts.width, facts.depth) * 0.18):
        issues.append("ROOF_GABLE roof shell is too shallow to read as a residential gable.")
    width = float(facts.effective_spec.width)
    depth = float(facts.effective_spec.depth)
    if abs(width - depth) <= 0.12:
        valid_shell_pairs = (("left", "right"), ("front", "back"))
    else:
        valid_shell_pairs = ((("left", "right") if width >= depth else ("front", "back")),)
    if has_collision_markers and not any(all(side in roof_top_shell_sides for side in pair) for pair in valid_shell_pairs):
        expected_shell_sides = valid_shell_pairs[0]
        missing_shell_sides = tuple(side for side in expected_shell_sides if side not in roof_top_shell_sides)
        issues.append(
            "ROOF_GABLE is missing roof-level gable-end shell closure markers on: "
            + ", ".join(missing_shell_sides)
            + "."
        )
    issues.extend(_collect_sloped_top_floor_closeout_issues(facts, roof_label="GABLE"))
    return issues


def _collect_sloped_top_floor_closeout_issues(facts: ValidationFacts, *, roof_label: str) -> list[str]:
    if str(facts.top_terminal_mode).upper() != "TOP_FLOOR_ONLY":
        return []
    if not _uses_legacy_collision_lane(facts):
        return []
    closeout_count = facts.marker_facts.floor_roles.get((ROLE_FLOOR_BLOCKER, int(facts.floor_count)), 0)
    if closeout_count > 0:
        return []
    return [
        "ROOF_"
        + roof_label
        + " is missing the TOP_FLOOR_ONLY top-floor closeout FLOOR_BLOCKER "
        + f"on runtime floor {int(facts.floor_count):02d}."
    ]


def _collect_shed_roof_contract_issues(facts: ValidationFacts) -> list[str]:
    issues = _collect_non_terrace_roof_contract_issues(facts)
    issues.extend(_collect_sloped_top_floor_closeout_issues(facts, roof_label="SHED"))
    return issues


def _roof_topology_key_for_mode(roof_mode: str) -> str:
    if roof_mode == ROOF_MODE_BARREL:
        return "BARREL"
    if roof_mode == ROOF_MODE_GABLE:
        return "GABLE"
    if roof_mode == ROOF_MODE_SHED:
        return "SHED"
    if roof_mode == ROOF_MODE_TERRACE:
        return "TERRACE"
    return "GENERIC_NON_TERRACE"


def _roof_topology_key(facts: ValidationFacts) -> str:
    if _terrace_transition_floor_index(facts) is not None:
        return "TERRACE"
    return _roof_topology_key_for_mode(str(facts.roof_mode))


def _flat_roof_wall_overlap_issue(facts: ValidationFacts) -> str | None:
    if str(facts.roof_mode) not in {ROOF_MODE_FLAT, ROOF_MODE_TERRACE}:
        return None
    if float(getattr(facts.effective_spec, "parapet_height", 0.0)) > 1e-4:
        return None
    roof_render_meshes = _roof_render_meshes(facts)
    if not roof_render_meshes:
        return None
    roof_bottom_z = min(object_local_bounds(facts.root_obj, child)[4] for child in roof_render_meshes)
    roof_surface_z = float(_roof_surface_z(facts.effective_spec))
    if roof_bottom_z < roof_surface_z - 0.02:
        return (
            "Flat roof render shell intrudes below roof surface and can co-own wall-top seams; "
            "flat roof slabs must sit on/above wall tops."
        )
    return None


def _collect_roof_contract_issues(facts: ValidationFacts) -> list[str]:
    roof_issue_collectors = {
        "GENERIC_NON_TERRACE": _collect_non_terrace_roof_contract_issues,
        "TERRACE": _collect_terrace_roof_contract_issues,
        "BARREL": _collect_barrel_roof_contract_issues,
        "GABLE": _collect_gable_roof_contract_issues,
        "SHED": _collect_shed_roof_contract_issues,
    }
    primary_topology = _roof_topology_key(facts)
    issues = roof_issue_collectors[primary_topology](facts)
    mode_topology = _roof_topology_key_for_mode(str(facts.roof_mode))
    if mode_topology != primary_topology:
        issues.extend(roof_issue_collectors[mode_topology](facts))
    terminal_profile = str(facts.terminal_profile).upper()
    if facts.roof_access_enabled:
        if str(facts.top_terminal_mode).upper() != TOP_TERMINAL_PLAYABLE_TOP_ROOM:
            issues.append("Roof-access contract drifted: roof_access_enabled=True but top_terminal_mode is not PLAYABLE_TOP_ROOM.")
        if terminal_profile not in {TERMINAL_PROFILE_ATTIC_OPEN, TERMINAL_PROFILE_FULL_ROOM, TERMINAL_PROFILE_STAIR_HEAD}:
            issues.append("Roof-access contract is missing a recognized terminal_profile for the planner-owned top terminal.")
        if facts.contract_roof_opening_bounds is None:
            issues.append("Roof-access contract is missing planner-owned roof opening bounds.")
        if facts.contract_roof_exit_bounds is None:
            issues.append("Roof-access contract is missing planner-owned terminal envelope bounds.")
    elif terminal_profile:
        issues.append("Non-walkable roof should not keep a terminal_profile contract.")
    if _uses_legacy_collision_lane(facts) and facts.roof_access_enabled and (facts.contract_roof_opening_bounds is not None or facts.contract_roof_exit_bounds is not None):
        planned_opening_bounds = facts.contract_roof_opening_bounds or facts.contract_roof_exit_bounds
        opening_bounds = _infer_roof_opening_bounds_from_blockers(facts)
        if (
            opening_bounds is not None
            and planned_opening_bounds is not None
            and not _opening_contains_room(opening_bounds, planned_opening_bounds)
        ):
            issues.append("Roof blocker cutout is narrower than the planner-owned roof opening contract and can fight the roof seam.")
        if facts.top_room_floor_bounds is not None and any(
            _bounds_intrude_3d(facts.top_room_floor_bounds, blocker_bounds)
            for blocker_bounds in facts.roof_blocker_bounds
        ):
            issues.append("Top-room floor overlaps roof blockers; roof-exit arrival seam is conflicting.")
        for platform_bounds in facts.roof_exit_platform_marker_bounds:
            if any(_bounds_intrude_3d(platform_bounds, blocker_bounds) for blocker_bounds in facts.roof_blocker_bounds):
                issues.append("Roof-exit platform blocker overlaps roof blockers; arrival seam is conflicting.")
                break
    flat_roof_overlap_issue = _flat_roof_wall_overlap_issue(facts)
    if flat_roof_overlap_issue is not None:
        issues.append(flat_roof_overlap_issue)
    return issues


def _collect_facade_opening_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    rear_access_profile = str(facts.rear_access_profile).upper()
    service_door_rear_profile = rear_access_profile == REAR_ACCESS_PROFILE_SERVICE_DOOR
    open_bay_rear_profile = rear_access_profile == REAR_ACCESS_PROFILE_OPEN_BAY
    shell_only_rear_profile = rear_access_profile == REAR_ACCESS_PROFILE_SHELL_ONLY
    doorless_shell_family = shell_only_rear_profile
    wood_floor_material_count = _wood_floor_material_count(facts)
    timber_siding_count = _count_mesh_tagged(facts, "tbg_timber_siding")
    entry_canopy_count = _count_mesh_tagged(facts, "tbg_entry_canopy")
    storefront_kind_counts = _storefront_kind_counts(facts)
    storefront_part_count = sum(storefront_kind_counts.values())
    window_mullion_count = _count_mesh_tagged(facts, "tbg_window_mullion")
    decorative_window_panel_count = _count_mesh_tagged(facts, "tbg_decorative_window_panel")
    windows = facts.summary.windows
    window_slots = windows.slots
    window_marker_count = len(window_slots)
    closed_window_count = sum(1 for slot in window_slots if not slot.open)
    reserved_closed_window_count = sum(1 for slot in window_slots if slot.reserved_closed)
    broken_reserved_open_window_count = sum(1 for slot in window_slots if slot.reserved_open and not slot.open)
    broken_reserved_closed_window_count = sum(1 for slot in window_slots if slot.reserved_closed and slot.open)
    lower_window_bounds = [item.bounds for item in windows.bounds if item.floor == 0]
    balcony_access_by_span: dict[str, int] = {}
    for slot in window_slots:
        if not slot.balcony_access:
            continue
        key = slot.span_key or f"{slot.side}:{slot.floor}"
        balcony_access_by_span[key] = balcony_access_by_span.get(key, 0) + 1
    if _uses_profiled_industrial_doctrine(facts):
        industrial_slots = [
            slot
            for slot in window_slots
            if str(slot.state) not in {"MASK", "STAIR", "BALCONY"} and not bool(slot.balcony_access)
        ]
        if not industrial_slots:
            issues.append("Wave 1 industrial doctrine lost ordinary tactical facade opening slots.")
        else:
            closed_slots = [slot for slot in industrial_slots if not bool(slot.open)]
            if closed_slots:
                slot = closed_slots[0]
                issues.append(
                    f"Wave 1 industrial doctrine requires open apertures; found closed slot {slot.side} F{slot.floor:02d} S{slot.slot:02d}."
                )
            min_width = 0.9 if open_bay_rear_profile else 1.0
            min_height = 0.9 if open_bay_rear_profile else 0.95
            for slot in industrial_slots:
                if not bool(slot.open):
                    continue
                if float(slot.opening_width) < min_width or float(slot.opening_height) < min_height:
                    issues.append(
                        f"Wave 1 industrial opening is below tactical minimum at {slot.side} F{slot.floor:02d} S{slot.slot:02d}: "
                        f"{slot.opening_width:.2f}m x {slot.opening_height:.2f}m."
                    )
                    break
    issues.extend(_collect_facade_shell_slot_issues(facts))

    supported_families = supported_facade_families(facts.facade_mode)
    if facts.effective_facade_family not in supported_families:
        issues.append(
            f"Facade family did not normalize to a supported {facts.facade_mode.lower()} style: {facts.effective_facade_family}."
        )
    if facts.floor_count >= 3 and facts.facade_mode == FACADE_MODE_SPLIT:
        if facts.brick_floor_count <= 0:
            issues.append("Multi-floor facade lost its mandatory lower brick section.")
        if facts.panel_floor_count <= 0:
            issues.append("Multi-floor facade lost its mandatory upper soft-panel section.")
    if facts.preset_id in WOOD_PRESET_IDS:
        if facts.preset_id == "wood_rowhouse" and facts.roof_mode != ROOF_MODE_GABLE:
            issues.append(f"{facts.preset_id} must ship on the GABLE roof contract, found {facts.roof_mode}.")
        if wood_floor_material_count <= 0:
            issues.append("Residential-wood archetype is missing TBG_WoodFloor material evidence on floor/stair sections.")
        if timber_siding_count <= 0 and entry_canopy_count <= 0:
            issues.append(
                "Residential-wood archetype is missing both timber-siding overlay evidence and porch/canopy frontage evidence."
            )
    storefront_frontage = _uses_storefront_frontage(facts)
    if storefront_frontage:
        if storefront_part_count <= 0:
            issues.append("STOREFRONT ground-floor profile generated no tagged storefront parts.")
        if storefront_kind_counts.get("GLAZING", 0) <= 0:
            issues.append("Storefront/service frontage is missing tagged display-glazing evidence.")
        if storefront_kind_counts.get("SIGNAGE", 0) <= 0:
            issues.append("Storefront/service frontage is missing tagged signage-band evidence.")
        if storefront_kind_counts.get("CANOPY", 0) <= 0 and entry_canopy_count <= 0:
            issues.append("Storefront/service frontage is missing tagged canopy/awning evidence.")
        if _requires_storefront_entry_evidence(facts) and storefront_kind_counts.get("ENTRY", 0) <= 0:
            issues.append("Storefront/service frontage is missing tagged recessed-entry evidence.")
    if str(facts.effective_spec.window_profile).upper() == "MULTI_PANE" and window_mullion_count <= 0:
        issues.append("MULTI_PANE window profile generated no tagged mullion geometry.")
    if window_marker_count <= 0:
        if _requires_facade_windows(facts):
            issues.append("Building has no generated facade windows.")
    else:
        terrace_exit_window_count = len(facts.voxel_wall_facts.terrace_exit_top_facts)
        expected_through_wall_frame_count = max(0, window_marker_count - terrace_exit_window_count)
        if decorative_window_panel_count:
            issues.append("Closed/stair facade windows are using decorative panels instead of framed window modules.")
        if windows.frame_count < expected_through_wall_frame_count:
            issues.append("Some facade windows are missing their through-wall frame.")
        if windows.frame_count > 0 and not (0.012 <= windows.frame_outer_clearance_min <= 0.06):
            issues.append(
                f"Exterior window frames are not sitting proudly outside the facade: clearance {windows.frame_outer_clearance_min:.3f}m."
            )
        if windows.frame_count > 0 and not (0.008 <= windows.frame_inner_clearance_min <= 0.04):
            issues.append(
                f"Interior window frames are not sitting proudly inside the room: clearance {windows.frame_inner_clearance_min:.3f}m."
            )
    if windows.open_fill_leak_count:
        issues.append("Some open windows still have an opaque fill.")
    if broken_reserved_open_window_count:
        issues.append("Reserved balcony/entry access windows are not staying open.")
    if broken_reserved_closed_window_count:
        issues.append("Reserved stair-safety windows are not staying closed.")
    if reserved_closed_window_count and closed_window_count < reserved_closed_window_count:
        issues.append("Closed-window planner lost some required stair-safe slots.")
    if closed_window_count and windows.closed_fill_count < closed_window_count:
        issues.append("Some closed facade windows are missing the matte fill treatment.")
    if closed_window_count and windows.closed_fill_matte_count < closed_window_count:
        issues.append("Closed windows are not consistently using the matte blue fill material.")
    if windows.closed_fill_glossy_count:
        issues.append("Closed windows still fall back to glossy glass instead of matte blue fills.")
    if closed_window_count and windows.fill_center_offset_max > 0.012:
        issues.append(
            f"Closed-window matte fills drifted away from the wall center plane: offset {windows.fill_center_offset_max:.3f}m."
        )
    transition_floor_index, _upper_shell_rect, _terrace_open_sides = _terrace_transition_contract(facts.effective_spec)
    balcony_candidate_floors = [
        floor_index
        for floor_index in range(1, facts.floor_count)
        if transition_floor_index is None or int(floor_index) < int(transition_floor_index)
    ]
    if (
        normalized_balcony_mode(facts.effective_spec.balcony_mode) != "NONE"
        and balcony_candidate_floors
        and not facts.summary.balconies
    ):
        issues.append("Expected balcony geometry, but none was generated.")
    if facts.summary.balconies and not balcony_access_by_span:
        issues.append("Balconies were generated without protected open-window access.")
    if facts.summary.balconies and windows.open_fill_leak_count:
        issues.append("Balcony access opening is still closed by a fill object.")
    if _requires_exposed_stair_windows(facts) and not facts.has_stair_window:
        issues.append("Expected exposed stair windows, but none were generated.")
    total_door_frame_count = facts.summary.doors.frame_count
    expected_door_frame_count = (
        0
        if facts.preset_id == "hangar" or shell_only_rear_profile or open_bay_rear_profile
        else 1 + int(service_door_rear_profile)
    )
    frame_label = "Door frame" if service_door_rear_profile else "Main door frame"
    max_inner_clearance = 0.08 if service_door_rear_profile else 0.04
    if facts.preset_id == "hangar":
        if total_door_frame_count:
            issues.append("Hangar should not export a visible door-frame contract.")
    elif doorless_shell_family:
        if total_door_frame_count:
            issues.append("Under-construction shell should not export a main door frame.")
    elif total_door_frame_count != expected_door_frame_count:
        if service_door_rear_profile:
            issues.append(
                "Shared two-sided entry contract should export exactly two door frames, "
                f"found {total_door_frame_count}."
            )
        elif open_bay_rear_profile:
            issues.append(
                "Depot open-bay doctrine should not keep a front door frame fallback, "
                f"found {total_door_frame_count}."
            )
        else:
            issues.append(f"Expected exactly one main door frame, found {total_door_frame_count}.")
    recessed_portal_family = facts.preset_id in {"clinic", "market_hall", "pharmacy"}
    if (
        facts.preset_id not in {"hangar", "under_construction"}
        and total_door_frame_count
        and not recessed_portal_family
        and not (0.012 <= facts.summary.doors.frame_outer_clearance_min <= 0.06)
    ):
        issues.append(
            f"{frame_label} is not sitting proudly outside the facade: clearance "
            f"{facts.summary.doors.frame_outer_clearance_min:.3f}m."
        )
    if (
        facts.preset_id not in {"hangar", "under_construction"}
        and total_door_frame_count
        and not recessed_portal_family
        and not (0.008 <= facts.summary.doors.frame_inner_clearance_min <= max_inner_clearance)
    ):
        issues.append(
            f"{frame_label} is not sitting proudly inside the room: clearance "
            f"{facts.summary.doors.frame_inner_clearance_min:.3f}m."
        )
    if facts.preset_id == "hangar" and total_door_frame_count:
        issues.append("Hangar should not export a visible door-frame contract.")
    if facts.summary.doors.has_legacy_trim:
        issues.append("Legacy loose door-trim geometry is still present beside the main opening frame.")
    if facts.summary.doors.has_loose_detail:
        issues.append("Door leaf still contains loose detail meshes instead of one authored leaf.")
    if not doorless_shell_family:
        door_leaf_count = len(facts.door_leaves)
        door_panel_count = sum(1 for child in facts.door_leaves if child.get("tbg_door_panel"))
        door_handle_plate_count = sum(1 for child in facts.door_leaves if child.get("tbg_door_handle_plate"))
        if door_panel_count < door_leaf_count:
            issues.append("Door leaf is missing its authored central panel treatment.")
        if door_handle_plate_count < door_leaf_count:
            issues.append("Door leaf is missing its authored handle-plate treatment.")
    if facts.preset_id == "market_hall" and facts.door_leaves:
        leaf = next(
            (child for child in facts.door_leaves if "Door_Main" in str(child.name)),
            facts.door_leaves[0],
        )
        _door_center_x, expected_plane_y = _resolve_frontage_entry_pose(facts.effective_spec)
        if abs(float(expected_plane_y) - float(leaf.location.y)) > 0.12:
            issues.append("Market hall main door is not seated on the same recessed plane as its frame.")
    if facts.summary.entry_detail_clearance_min and not (0.012 <= facts.summary.entry_detail_clearance_min <= 0.06):
        issues.append(
            f"Entry intercom/detail cluster is still embedded into the facade: clearance {facts.summary.entry_detail_clearance_min:.3f}m."
        )
    if (
        facts.summary.parapet_cap_clearance_min
        and 0.0 < facts.summary.parapet_cap_clearance_min < TRIM_BACK_OVERLAP_MIN_STUDS
    ):
        issues.append(
            f"Roof parapet caps are still too flush with the facade and can flicker: clearance {facts.summary.parapet_cap_clearance_min:.3f}m."
        )
    if facts.summary.balconies and any(name != "TBG_Balcony" for name in facts.balcony_material_names):
        issues.append(
            f"Balcony material drifted away from the neutral global balcony shader: {', '.join(sorted(set(facts.balcony_material_names)))}."
        )
    if facts.wide_partition_eligible:
        if facts.summary.room_partitions.count <= 0:
            issues.append("Wide building is missing its interior room partitions.")
        if facts.summary.room_partitions.frame_count <= 0:
            issues.append("Wide building partitions are missing framed doorless openings.")
        if facts.room_partition_corridor_width < 1.35:
            issues.append("Wide-building room partitions do not preserve a continuous traversal corridor.")
    for lower_facade in facts.summary.lower_facade_bounds:
        for lower_window in lower_window_bounds:
            if _bounds_overlap_3d(lower_facade, lower_window):
                issues.append("Lower facade mass intrudes into a lower-window sight rectangle.")
                break
        else:
            continue
        break
    for balcony in facts.summary.balconies:
        balcony_label = balcony.span_key or f"{balcony.side} F{balcony.floor:02d}"
        if abs(balcony.outward_sign - side_sign(balcony.side)) > 0.01:
            issues.append(f"Balcony '{balcony_label}' has flipped outward orientation metadata.")
        key = balcony.span_key or f"{balcony.side}:{balcony.floor}"
        if balcony_access_by_span.get(key, 0) <= 0:
            issues.append(f"Balcony '{balcony_label}' is missing its balcony-access opening exemption marker.")
    for ac in facts.summary.facade_ac:
        if ac.half_span <= 0.0:
            continue
        for balcony in facts.summary.balconies:
            if balcony.side != ac.side or balcony.floor != ac.floor:
                continue
            balcony_center = balcony.span_center
            balcony_half = balcony.span_width / 2
            if max(ac.along - ac.half_span, balcony_center - balcony_half) < min(ac.along + ac.half_span, balcony_center + balcony_half):
                issues.append("Facade AC intrudes into balcony fighting space.")
                break
    return issues


def _collect_service_entrance_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    has_collision_markers = _uses_legacy_collision_lane(facts)
    construction_frame_count = _construction_frame_count(facts)
    rear_opening_blockers = _rear_opening_blocker_names(facts)
    rear_entry_role_counts = _rear_entry_package_role_counts(facts)
    door_frame_count = facts.summary.doors.frame_count
    rear_access_profile = str(facts.rear_access_profile).upper()
    rear_profile_none = rear_access_profile == REAR_ACCESS_PROFILE_NONE
    rear_profile_service_door = rear_access_profile == REAR_ACCESS_PROFILE_SERVICE_DOOR
    rear_profile_open_bay = rear_access_profile == REAR_ACCESS_PROFILE_OPEN_BAY
    rear_profile_shell_only = rear_access_profile == REAR_ACCESS_PROFILE_SHELL_ONLY
    rear_entry_count = sum(
        1
        for child in facts.mesh_children
        if child.name.endswith("Door_Rear")
        and child.get("tbg_is_door_leaf")
        and (child.get("tbg_rear_through_access") or str(child.get("tbg_facade_side", "")) == "back")
    )
    if rear_profile_none:
        if facts.rear_through_access:
            issues.append("rear_access_profile=NONE must keep rear through-access disabled.")
        if facts.rear_entry_planned_span is not None:
            issues.append("rear_access_profile=NONE must not publish a planned rear opening span.")
        if rear_entry_count > 0 or facts.rear_door_bounds is not None:
            issues.append("rear_access_profile=NONE must not author a rear Door_Rear package.")
    else:
        if not facts.rear_through_access:
            issues.append("Rear access profile requires rear through-access, but it resolved to disabled.")
    if rear_profile_shell_only:
        expected_ring_beams = max(0, facts.floor_count - max(1, facts.completed_facade_floors))
        expected_frame_boxes = 4 + expected_ring_beams * 4 if expected_ring_beams > 0 else 4
        if construction_frame_count < expected_frame_boxes:
            issues.append(
                "Under-construction shell is missing its authored structural frame: "
                f"{construction_frame_count} < {expected_frame_boxes}."
            )
        if rear_entry_count > 0 or facts.rear_door_bounds is not None:
            issues.append("SHELL_ONLY rear access must not author a rear Door_Rear leaf package.")
    if rear_profile_open_bay and rear_entry_count > 0:
        issues.append("Depot open-bay doctrine must not author a rear Door_Rear leaf package.")
    if rear_profile_service_door and rear_entry_count <= 0:
        issues.append("Shared two-sided entry doctrine lost its authored rear through-access opening.")
    if rear_profile_service_door and door_frame_count < 2:
        issues.append("Rear through-access frame geometry is missing on the back facade.")
    if rear_profile_service_door and rear_opening_blockers:
        blockers_preview = ", ".join(rear_opening_blockers[:3])
        issues.append(
            "Rear through-access opening is blocked by wall geometry: "
            f"{blockers_preview}{'...' if len(rear_opening_blockers) > 3 else ''}."
        )
    rear_traversal_required = (
        has_collision_markers
        and rear_profile_service_door
        and facts.rear_through_access
        and facts.rear_entry_planned_span is not None
        and facts.entrance_profile != "FLUSH"
        and float(facts.summary.entrance.threshold_z) > 0.0
    )
    if rear_traversal_required:
        rear_landing_count = rear_entry_role_counts.get(ROLE_ENTRY_LANDING, 0)
        rear_wedge_count = rear_entry_role_counts.get(ROLE_ENTRY_WEDGE, 0)
        if rear_landing_count <= 0 or rear_wedge_count <= 0:
            issues.append(
                "Rear through-access is missing rear entry traversal package evidence "
                f"(ENTRY_LANDING={rear_landing_count}, ENTRY_WEDGE={rear_wedge_count})."
            )
        if (
            rear_landing_count <= 0
            and rear_wedge_count <= 0
            and rear_entry_role_counts.get(ROLE_PODIUM_BLOCKER, 0) > 0
        ):
            issues.append(
                "Rear through-access traversal package collapsed to unrelated rear PODIUM_BLOCKER-only evidence."
            )
    if not rear_profile_none and facts.rear_through_access:
        planned_span = facts.rear_entry_planned_span
        authored_span = facts.rear_entry_authored_span
        if planned_span is None:
            issues.append("Rear through-access contract is missing planned rear-opening span evidence.")
        if authored_span is None and rear_profile_service_door:
            issues.append("Rear through-access contract is missing authored rear-opening span evidence.")
        if planned_span is not None and authored_span is not None and rear_profile_service_door:
            planned_x0, planned_x1 = float(planned_span[0]), float(planned_span[1])
            authored_x0, authored_x1 = float(authored_span[0]), float(authored_span[1])
            planned_center = (
                float(facts.rear_entry_planned_center_x)
                if facts.rear_entry_planned_center_x is not None
                else (planned_x0 + planned_x1) / 2
            )
            authored_center = (authored_x0 + authored_x1) / 2
            if abs(authored_center - planned_center) > 0.14:
                issues.append(
                    "Rear through-access authored opening drifted off the planned centerline: "
                    f"{authored_center:.3f} vs {planned_center:.3f}."
                )
            if facts.rear_entry_planned_opening_width is not None:
                authored_width = authored_x1 - authored_x0
                if abs(authored_width - float(facts.rear_entry_planned_opening_width)) > 0.1:
                    issues.append(
                        "Rear through-access authored opening width drifted from planned contract: "
                        f"{authored_width:.3f} vs {float(facts.rear_entry_planned_opening_width):.3f}."
                    )
            if authored_x0 < planned_x0 - 0.08 or authored_x1 > planned_x1 + 0.08:
                issues.append(
                    "Rear through-access authored opening escaped planned rear span bounds: "
                    f"planned ({planned_x0:.3f}, {planned_x1:.3f}) vs authored ({authored_x0:.3f}, {authored_x1:.3f})."
                )
        if facts.rear_door_bounds is not None and rear_profile_service_door:
            authored_door_width = float(facts.rear_door_bounds[1] - facts.rear_door_bounds[0])
            expected_door_width = float(facts.effective_spec.door.width)
            if abs(authored_door_width - expected_door_width) > 0.16:
                issues.append(
                    "Rear through-access door width drifted from spec: "
                    f"{authored_door_width:.3f}m vs expected {expected_door_width:.3f}m."
                )
        if has_collision_markers and planned_span is not None:
            planned_x0, planned_x1 = float(planned_span[0]), float(planned_span[1])
            wall_center_y = float(facts.effective_spec.depth / 2 - facts.wall_thickness / 2)
            probe_half_depth = max(0.04, float(facts.wall_thickness) / 2 + 0.025)
            if facts.rear_door_bounds is not None:
                door_bottom_z = float(facts.rear_door_bounds[4])
                door_top_z = float(facts.rear_door_bounds[5])
            else:
                door_bottom_z = 0.0
                door_top_z = float(facts.effective_spec.door.height)
            upper_probe_z0 = door_top_z + 0.04
            upper_probe_z1 = min(
                float(door_bottom_z + facts.effective_spec.floor_height - 0.06),
                float(door_top_z + 0.48),
            )
            if upper_probe_z1 > upper_probe_z0 + 0.04:
                left_probe = (
                    planned_x0 - 0.08,
                    planned_x0 + 0.08,
                    wall_center_y - probe_half_depth,
                    wall_center_y + probe_half_depth,
                    upper_probe_z0,
                    upper_probe_z1,
                )
                right_probe = (
                    planned_x1 - 0.08,
                    planned_x1 + 0.08,
                    wall_center_y - probe_half_depth,
                    wall_center_y + probe_half_depth,
                    upper_probe_z0,
                    upper_probe_z1,
                )
                has_left_shell = any(
                    _bounds_intrude_3d(bounds, left_probe, planar_tolerance=0.008, vertical_tolerance=0.02)
                    for bounds in facts.rear_shell_marker_bounds
                )
                has_right_shell = any(
                    _bounds_intrude_3d(bounds, right_probe, planar_tolerance=0.008, vertical_tolerance=0.02)
                    for bounds in facts.rear_shell_marker_bounds
                )
                if not has_left_shell or not has_right_shell:
                    missing_side = "left+right" if (not has_left_shell and not has_right_shell) else ("left" if not has_left_shell else "right")
                    issues.append(
                        "Rear shell continuity collapsed around planned rear opening on the "
                        f"{missing_side} side (upper shell probe has no overlap)."
                    )
    if rear_profile_open_bay:
        rear_ground_open_windows = [
            slot
            for slot in facts.summary.windows.slots
            if str(slot.side) == "back"
            and int(slot.floor) == 0
            and bool(slot.open)
            and not bool(slot.balcony_access)
            and str(slot.state) not in {"MASK", "STAIR", "BALCONY"}
        ]
        if not rear_ground_open_windows:
            issues.append("OPEN_BAY rear access requires gameplay-readable rear open-window coverage.")
        else:
            min_rear_opening_width = 0.9
            min_rear_opening_height = 0.9
            if not any(
                float(slot.opening_width) >= min_rear_opening_width
                and float(slot.opening_height) >= min_rear_opening_height
                for slot in rear_ground_open_windows
            ):
                issues.append(
                    "OPEN_BAY rear access lost tactical rear opening scale "
                    f"(need >= {min_rear_opening_width:.2f}m x {min_rear_opening_height:.2f}m)."
                )
    if has_collision_markers and rear_profile_service_door and facts.rear_through_access and facts.rear_door_bounds is not None:
        if facts.rear_entry_stair_conflict_span is not None:
            conflict_x0, conflict_x1 = facts.rear_entry_stair_conflict_span
            door_x0, door_x1 = float(facts.rear_door_bounds[0]), float(facts.rear_door_bounds[1])
            if max(door_x0, conflict_x0) < min(door_x1, conflict_x1):
                issues.append("Rear through-access door overlaps stair-core conflict span on the back facade.")
        if facts.partition_marker_bounds:
            wall_center_y = float(facts.effective_spec.depth / 2 - facts.wall_thickness / 2)
            door_bounds = facts.rear_door_bounds
            corridor_bounds = (
                float(door_bounds[0] - 0.04),
                float(door_bounds[1] + 0.04),
                float(wall_center_y - facts.rear_entry_stair_clearance_min),
                float(wall_center_y + max(0.06, facts.wall_thickness / 2 + 0.02)),
                float(door_bounds[4] + 0.08),
                float(door_bounds[5] - 0.08),
            )
            if (
                corridor_bounds[1] > corridor_bounds[0]
                and corridor_bounds[3] > corridor_bounds[2]
                and corridor_bounds[5] > corridor_bounds[4]
                and any(_bounds_overlap_3d(corridor_bounds, bounds) for bounds in facts.partition_marker_bounds)
            ):
                issues.append("Rear through-access traversal corridor is intruded by partition blockers near the stair core.")
    back_floor_window_slots = {
        int(slot.slot)
        for slot in facts.summary.windows.slots
        if str(slot.side) == "back" and int(slot.floor) == 0
    }
    if has_collision_markers and not rear_profile_none and facts.rear_through_access and back_floor_window_slots:
        back_shell_slot_count = int(facts.shell_slot_count_by_side_floor.get(("back", 0), 0))
        expected_min_shell_slots = max(1, (len(back_floor_window_slots) + 1) // 2)
        if back_shell_slot_count < expected_min_shell_slots:
            issues.append(
                "Back facade shell evidence collapsed around rear through-access opening: "
                f"shell slots {back_shell_slot_count} < {expected_min_shell_slots}."
            )
    stair_keepout = facts.stair_core_sight_keepout_bounds
    if has_collision_markers and stair_keepout is not None:
        if any(
            _bounds_intrude_3d(stair_keepout, bounds, planar_tolerance=0.01, vertical_tolerance=0.02)
            for bounds in facts.core_shell_partition_marker_bounds
        ):
            issues.append("Stair-core shell partition ROLE_PARTITION intrudes into stair arrival sightline keepout volume.")
        if any(
            _bounds_intrude_3d(stair_keepout, bounds, planar_tolerance=0.01, vertical_tolerance=0.02)
            for bounds in facts.core_shell_partition_mesh_bounds
        ):
            issues.append("Stair-room shell geometry intrudes into stair arrival sightline keepout volume.")

    entrance = facts.summary.entrance
    if facts.entrance_profile != "FLUSH":
        if entrance.landing_count <= 0 or entrance.step_count <= 0:
            issues.append("Raised entrance profile is missing a usable landing or steps.")
        else:
            if abs(entrance.top_z - entrance.threshold_z) > 0.08:
                issues.append("Raised entrance landing does not meet the door threshold.")
            if facts.preset_id == "house_small" and not (0.42 <= entrance.threshold_z <= 0.55):
                issues.append(f"House stoop height drifted out of target range: {entrance.threshold_z:.2f}m.")
            if facts.preset_id in {"apartment_midrise", "office_block"} and not (1.15 <= entrance.threshold_z <= 1.30):
                issues.append(f"Podium entrance height drifted out of target range: {entrance.threshold_z:.2f}m.")
        if entrance.has_interior_compensator:
            issues.append("Raised entrance still contains interior compensator geometry.")
        if not entrance.has_foundation_podium:
            issues.append("Raised entrance is missing a foundation podium under the building.")
    if facts.preset_id == "house_small" and facts.entrance_profile != "STOOP_LOW":
        issues.append("House Small should use a raised stoop entrance, not a flush or podium variant.")
    if facts.preset_id in {"apartment_midrise", "office_block"} and facts.entrance_profile != "PODIUM_HIGH":
        issues.append("Midrise and office presets should use the high podium entrance profile.")
    entrance_left_limit = (
        float(facts.entrance_left_limit)
        if facts.entrance_left_limit is not None
        else float(facts.left_extent)
    )
    entrance_right_limit = (
        float(facts.entrance_right_limit)
        if facts.entrance_right_limit is not None
        else float(facts.right_extent)
    )
    entrance_front_limit = (
        float(facts.entrance_front_limit)
        if facts.entrance_front_limit is not None
        else float(facts.front_extent)
    )
    if entrance_front_limit > 0.0:
        for part_bounds in entrance.part_bounds:
            min_x, max_x, min_y, max_y = part_bounds[:4]
            if (
                max_x > entrance_right_limit + 0.05
                or min_x < -entrance_left_limit - 0.05
                or min_y < -entrance_front_limit - 0.05
            ):
                issues.append("Entrance_Flight leaks outside computed footprint envelope.")
                break
    for canopy_bounds in facts.summary.canopies:
        for balcony in facts.summary.balconies:
            if _bounds_overlap_2d(canopy_bounds, balcony.bounds):
                issues.append("Entry canopy overlaps balcony geometry.")
                break
        else:
            continue
        break
    return issues


def _collect_wave10_wave11_contract_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    front_conflict_span = facts.front_entry_stair_conflict_span
    if front_conflict_span is not None:
        approach_gap = facts.front_entry_approach_gap
        if approach_gap is not None and float(approach_gap) < -1e-6:
            issues.append(
                "Front-entry relief regressed: planned approach still intrudes stair-room pressure span "
                f"({approach_gap:.3f}m < 0, target >= {facts.front_entry_approach_band_min:.3f}m)."
            )
        if facts.front_door_bounds is not None:
            conflict_x0, conflict_x1 = float(front_conflict_span[0]), float(front_conflict_span[1])
            door_x0, door_x1 = float(facts.front_door_bounds[0]), float(facts.front_door_bounds[1])
            if max(door_x0, conflict_x0) < min(door_x1, conflict_x1):
                issues.append("Front-entry relief regressed: authored main door overlaps stair-core front conflict span.")
        if approach_gap is not None and float(approach_gap) >= -1e-6 and str(facts.stair_arrival_side).upper() != "FRONT":
            issues.append(
                "Front-arrival/stair-arrival coherence regressed: dogleg stair arrival is not FRONT on a relieved front-entry plan."
            )

    if facts.preset_id == "office_block" and facts.office_partition_positions_x:
        window_intrusions = tuple(
            pos
            for pos in facts.office_partition_positions_x
            if any(_span_contains(span, pos) for span in facts.office_window_approach_keepout_spans)
        )
        if window_intrusions:
            issues.append(
                "office_block partition center intrudes planned window-approach keepout span(s): "
                + ", ".join(f"{value:.4f}" for value in window_intrusions[:3])
                + ("..." if len(window_intrusions) > 3 else "")
                + "."
            )
        balcony_intrusions = tuple(
            pos
            for pos in facts.office_partition_positions_x
            if any(_span_contains(span, pos) for span in facts.office_balcony_access_keepout_spans)
        )
        if balcony_intrusions:
            issues.append(
                "office_block partition center intrudes planned balcony-access keepout span(s): "
                + ", ".join(f"{value:.4f}" for value in balcony_intrusions[:3])
                + ("..." if len(balcony_intrusions) > 3 else "")
                + "."
            )
        rear_keepout = facts.office_rear_corridor_keepout_span
        if rear_keepout is not None:
            rear_intrusions = tuple(
                pos
                for pos in facts.office_partition_positions_x
                if _span_contains(rear_keepout, pos)
            )
            if rear_intrusions:
                issues.append(
                    "office_block partition center intrudes rear through-access corridor keepout lane: "
                    + ", ".join(f"{value:.4f}" for value in rear_intrusions[:3])
                    + ("..." if len(rear_intrusions) > 3 else "")
                    + "."
                )
    return issues


def _collect_gameplay_budget_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    effective_render_object_count = _effective_render_object_count(facts)
    outer_width_min, outer_depth_min = gameplay_outer_minimums(facts.preset_id, facts.floor_count)
    if facts.width < outer_width_min - 1e-4:
        issues.append(f"Building width is below gameplay minimum: {facts.width:.2f} < {outer_width_min:.2f}.")
    if facts.depth < outer_depth_min - 1e-4:
        issues.append(f"Building depth is below gameplay minimum: {facts.depth:.2f} < {outer_depth_min:.2f}.")
    if facts.floor_count > 1:
        stair_width = float(facts.effective_spec.stair_core.stair_width)
        core_width = float(facts.effective_spec.stair_core.core_width)
        core_depth = float(facts.effective_spec.stair_core.core_depth)
        door_width = float(facts.effective_spec.door.width)
        door_height = float(facts.effective_spec.door.height)
        door_offset_x = float(facts.effective_spec.door.offset_x)
        stair_placement = str(facts.effective_spec.stair_core.placement)
        if stair_width < 1.2:
            issues.append("Multi-floor building stair width is below 1.2m gameplay minimum.")
        if core_width < 2.0 or core_depth < 4.0:
            issues.append("Multi-floor building stair core footprint is below 2.0m x 4.0m gameplay minimum.")
        if door_width < 1.2 or door_height < 2.2:
            issues.append("Multi-floor building main door is below 1.2m x 2.2m gameplay minimum.")
        if stair_placement == "CENTER":
            center_width_min, center_depth_min, required_abs_offset = center_stair_gameplay_requirements(
                facts.preset_id,
                core_width=core_width,
                core_depth=core_depth,
                door_width=door_width,
                wall_thickness=facts.wall_thickness,
            )
            if facts.width < center_width_min - 1e-4:
                issues.append(
                    f"Center-core building width is below entry-clearance minimum: {facts.width:.2f} < {center_width_min:.2f}."
                )
            if facts.depth < center_depth_min - 1e-4:
                issues.append(
                    f"Center-core building depth is below entry-lobby minimum: {facts.depth:.2f} < {center_depth_min:.2f}."
                )
            if abs(door_offset_x) < required_abs_offset - 1e-4:
                issues.append("Center-core entry door sits too close to the stair room; side entry clearance is insufficient.")
    if _has_roof_setback_meshes(facts):
        issues.append("Legacy RoofSetback clutter is still being emitted in the gameplay building flow.")
    if facts.v3_wall_source_tri_count_in_render_meshes != 0:
        issues.append(
            "V3 wall-source render leak failed: "
            f"{facts.v3_wall_source_tri_count_in_render_meshes} source-wall triangle(s) entered the non-voxel render budget."
        )
    for child in facts.mesh_children:
        bucket = str(child.get("tbg_section_bucket", "") or "")
        if bucket == "Section_Services_Helper":
            continue
        if bucket or child.get("tbg_foundation_podium"):
            if _has_inverted_bottom_face(facts.root_obj, child):
                issues.append(f"Mesh '{child.name}' still has an inverted bottom face.")
                break
    if facts.preset_id == "office_block" and facts.floor_count >= 5:
        tri_budget = 11800 if facts.floor_count < 7 else 12400
        object_budget = 28 if facts.floor_count < 7 else 32
        if facts.tri_count > tri_budget:
            issues.append(f"Office block triangle budget exceeded: {facts.tri_count} > {tri_budget}.")
        if effective_render_object_count > object_budget:
            issues.append(f"Office block object budget exceeded: {effective_render_object_count} > {object_budget}.")
    else:
        object_budget = 26 + int(facts.rear_through_access)
        if facts.preset_id == "depot":
            object_budget = 30
        if facts.preset_id == "apartment_midrise" and facts.floor_count >= 5:
            object_budget = 28
        if facts.preset_id == "apartment_midrise" and facts.floor_count >= 5 and facts.tri_count > 12000:
            issues.append(f"Apartment midrise triangle budget exceeded: {facts.tri_count} > 12000.")
        if effective_render_object_count > object_budget:
            if facts.preset_id == "depot":
                issues.append(f"Depot object budget exceeded: {effective_render_object_count} > {object_budget}.")
            else:
                issues.append(f"Generated object budget exceeded: {effective_render_object_count} > {object_budget}.")
    return issues


def _collect_destruction_export_readiness_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    voxel_wall_facts = facts.voxel_wall_facts
    occupancy_payload = voxel_wall_facts.payload
    authored_cell_count = voxel_wall_facts.total_authored_cell_count
    authored_group_count = len(voxel_wall_facts.groups)

    legacy_list_key = "wa" + "lls"
    legacy_count_key = "authored_" + "cu" + "boid_count"
    legacy_group_count_key = "cu" + "boid_count"
    forbidden_payload_keys = tuple(key for key in (legacy_list_key, legacy_count_key) if key in occupancy_payload)
    if forbidden_payload_keys:
        issues.append(
            "Authored wall-cell payload contains legacy top-level keys: "
            + ", ".join(forbidden_payload_keys)
            + "."
        )

    required_payload_keys = {
        "payload_kind",
        "payload_version",
        "cell_size_studs",
        "authored_group_count",
        "authored_cell_count",
        "wall_groups",
        "cells",
    }
    missing_payload_keys = tuple(sorted(required_payload_keys.difference(occupancy_payload.keys())))
    if missing_payload_keys:
        issues.append(
            "Authored wall-cell payload is missing top-level keys: "
            + ", ".join(missing_payload_keys)
            + "."
        )

    payload_cell_size = occupancy_payload.get("cell_size_studs")
    if not isinstance(payload_cell_size, (int, float)) or isinstance(payload_cell_size, bool) or not math.isfinite(float(payload_cell_size)):
        issues.append("Authored wall-cell payload has non-finite cell_size_studs.")
    elif abs(float(payload_cell_size) - float(export_contract.VOXEL_SIZE_STUDS)) > 1e-6:
        issues.append(
            "Authored wall-cell payload must use "
            f"cell_size_studs={float(export_contract.VOXEL_SIZE_STUDS):g}."
        )

    if occupancy_payload.get("payload_kind") != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND:
        issues.append(
            "Authored wall-cell payload must use "
            f"payload_kind='{export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND}'."
        )
    if occupancy_payload.get("payload_version") != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION:
        issues.append(
            "Authored wall-cell payload must use "
            f"payload_version='{export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION}'."
        )

    payload_group_count = occupancy_payload.get("authored_group_count")
    if not isinstance(payload_group_count, int) or isinstance(payload_group_count, bool):
        issues.append("Authored wall-cell payload has malformed authored_group_count.")
    elif payload_group_count != authored_group_count:
        issues.append(
            "Authored wall-cell payload authored_group_count does not match parsed wall_groups "
            f"({payload_group_count} != {authored_group_count})."
        )

    payload_cell_count = occupancy_payload.get("authored_cell_count")
    payload_cell_count_value: int | None = None
    if not isinstance(payload_cell_count, int) or isinstance(payload_cell_count, bool):
        issues.append("Authored wall-cell payload has malformed authored_cell_count.")
    else:
        payload_cell_count_value = int(payload_cell_count)
        if payload_cell_count_value != authored_cell_count:
            issues.append(
                "Authored wall-cell payload authored_cell_count does not match parsed cells "
                f"({payload_cell_count_value} != {authored_cell_count})."
            )

    if authored_cell_count <= 0:
        issues.append("Authored wall-cell payload is empty: no authored cells were found.")
    if authored_cell_count > export_contract.MAX_WALL_RUNTIME_PARTS:
        issues.append(
            "Authored wall-cell contract failed: authored cell budget exceeded "
            f"({authored_cell_count} > {export_contract.MAX_WALL_RUNTIME_PARTS})."
        )
    if authored_group_count <= 0:
        issues.append("Authored wall-cell contract failed: zero authored wall groups were stored.")

    try:
        payload_json = json.dumps(
            occupancy_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        chunks = export_contract.split_voxel_wall_occupancy_json(payload_json)
        if not chunks:
            issues.append("Authored wall-cell payload chunking produced zero chunks.")
        oversized_chunks = [len(chunk) for chunk in chunks if len(chunk) > export_contract.MAX_VOXEL_WALL_OCCUPANCY_CHUNK_CHARS]
        if oversized_chunks:
            issues.append(
                "Authored wall-cell payload chunk budget exceeded; max observed chunk length="
                f"{max(oversized_chunks)}."
            )
    except (TypeError, ValueError) as exc:
        issues.append(f"Authored wall-cell payload exceeds JSON/chunk budget: {exc}")

    if voxel_wall_facts.malformed_entries:
        issues.append(
            "Authored wall-cell payload contains malformed entries at "
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.malformed_entries[:8])
            + ("." if len(voxel_wall_facts.malformed_entries) <= 8 else ", ...")
        )
    if voxel_wall_facts.stale_authored_evidence:
        issues.append(
            "Authored wall-cell contract failed: stale authored visual evidence remains on "
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.stale_authored_evidence[:8])
            + ("." if len(voxel_wall_facts.stale_authored_evidence) <= 8 else ", ...")
        )
    if voxel_wall_facts.legacy_helper_evidence:
        issues.append(
            "Authored wall-cell contract failed: legacy voxel helper evidence remains on "
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.legacy_helper_evidence[:8])
            + ("." if len(voxel_wall_facts.legacy_helper_evidence) <= 8 else ", ...")
        )

    payload_group_ids = {
        group.group_id
        for group in voxel_wall_facts.groups
        if group.group_id
    }
    visible_group_ids: set[str] = set()
    if authored_group_count > 0 and not voxel_wall_facts.visible_wall_objects:
        issues.append("Authored wall-cell contract failed: no occupancy-emitted visible structural wall objects exist.")
    for visible_wall in voxel_wall_facts.visible_wall_objects:
        visible_name = visible_wall.object_name
        if visible_wall.source_bucket not in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
            issues.append(
                f"Visible structural wall '{visible_name}' has unsupported source bucket '{visible_wall.source_bucket}'."
            )
        if visible_wall.emit_owner != visible_wall.expected_emit_owner:
            issues.append(f"Visible structural wall '{visible_name}' is missing occupancy_v3 ownership stamp.")
        if visible_wall.payload_kind != visible_wall.expected_payload_kind:
            issues.append(f"Visible structural wall '{visible_name}' has stale or missing wall-cell payload kind stamp.")
        if visible_wall.payload_version != visible_wall.expected_payload_version:
            issues.append(f"Visible structural wall '{visible_name}' has stale or missing wall-cell payload version stamp.")
        if visible_wall.export_contract_version != export_contract.EXPORT_CONTRACT_VERSION:
            issues.append(f"Visible structural wall '{visible_name}' has stale or missing export contract version stamp.")
        if not visible_wall.has_composite_part_bounds:
            issues.append(
                f"Visible structural wall '{visible_name}' has no tbg_composite_part_bounds_json composite-cell bounds."
            )
        if visible_wall.scalar_cell_count is None:
            issues.append(f"Visible structural wall '{visible_name}' has missing or malformed tbg_wall_cell_count stamp.")
        elif visible_wall.composite_cell_count != visible_wall.scalar_cell_count:
            issues.append(
                f"Visible structural wall '{visible_name}' composite part count drifted from tbg_wall_cell_count "
                f"({visible_wall.composite_cell_count} != {visible_wall.scalar_cell_count})."
            )
        if visible_wall.texture_contract_cell_count != visible_wall.composite_cell_count:
            issues.append(
                f"Visible structural wall '{visible_name}' texture contract cell count does not match composite cells "
                f"({visible_wall.texture_contract_cell_count} != {visible_wall.composite_cell_count})."
            )
        expected_texture_uv_source = (
            "payload_roblox_part_texture_v1"
            if visible_wall.texture_projection == export_contract.TEXTURE_PROJECTION_ROBLOX_PART_TEXTURE_V1
            else "payload_material_variant_style_v1"
        )
        if visible_wall.texture_uv_source != expected_texture_uv_source:
            issues.append(f"Visible structural wall '{visible_name}' is not using payload material-style UV metadata.")
        if visible_wall.texture_image_period_contract not in export_contract.TEXTURE_IMAGE_PERIOD_CONTRACTS:
            issues.append(f"Visible structural wall '{visible_name}' has invalid texture image period contract.")
        if visible_wall.texture_face_axis_table_version != export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1:
            issues.append(f"Visible structural wall '{visible_name}' has invalid texture face-axis table version.")
        if not visible_wall.texture_key_set:
            issues.append(f"Visible structural wall '{visible_name}' has no texture_key preview set metadata.")
        if not visible_wall.group_ids:
            issues.append(f"Visible structural wall '{visible_name}' is missing wall group provenance.")
            continue
        visible_group_ids.update(visible_wall.group_ids)
        missing_payload_groups = tuple(sorted(set(visible_wall.group_ids).difference(payload_group_ids)))
        if missing_payload_groups:
            issues.append(
                f"Visible structural wall '{visible_name}' references missing payload group ids: "
                + ", ".join(missing_payload_groups)
                + "."
            )
    missing_visible_groups = tuple(sorted(payload_group_ids.difference(visible_group_ids)))
    if missing_visible_groups:
        issues.append(
            "Authored wall-cell contract failed: payload wall groups have no visible occupancy wall object: "
            + ", ".join(missing_visible_groups[:8])
            + ("." if len(missing_visible_groups) <= 8 else ", ...")
        )
    if payload_cell_count_value is not None and voxel_wall_facts.real_visible_cell_count != payload_cell_count_value:
        issues.append(
            "Authored wall-cell visible mesh parity failed: real composite visible cell count "
            f"{voxel_wall_facts.real_visible_cell_count} != payload authored_cell_count {payload_cell_count_value}."
        )
    if voxel_wall_facts.runtime_render_wall_object_names:
        issues.append(
            "FBX/RBXMX render mesh contract failed: destructible voxel wall authoring meshes are present in "
            "runtime_render_meshes(root): "
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.runtime_render_wall_object_names[:8])
            + ("." if len(voxel_wall_facts.runtime_render_wall_object_names) <= 8 else ", ...")
            + " Studio wall truth must come from sidecar AUTHORED_WALL_CELLS only."
        )

    if voxel_wall_facts.duplicate_group_ids:
        issues.append(
            "Authored wall-cell contract failed: group_id values must be unique; duplicates="
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.duplicate_group_ids)
            + "."
        )
    if voxel_wall_facts.duplicate_cell_ids:
        issues.append(
            "Authored wall-cell contract failed: cell_id values must be unique; duplicates="
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.duplicate_cell_ids)
            + "."
        )
    for duplicate_bounds in voxel_wall_facts.duplicate_cell_bounds:
        issues.append(
            "Authored wall-cell contract failed: duplicate exact cell bounds for cells "
            + ", ".join(f"'{name}'" for name in duplicate_bounds.cell_ids)
            + "."
        )
    for overlap in voxel_wall_facts.overlapping_cells:
        issues.append(
            "Authored wall-cell contract failed: positive-volume overlap exists between cells "
            + ", ".join(f"'{name}'" for name in overlap.cell_ids)
            + f" ({overlap.cell_pair_count} conflicting cell pair)."
        )
    if voxel_wall_facts.horizontal_cell_ids:
        issues.append(
            "Authored wall-cell contract failed: horizontal/Z-thickness cells are not valid vertical wall mass: "
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.horizontal_cell_ids[:8])
            + ("." if len(voxel_wall_facts.horizontal_cell_ids) <= 8 else ", ...")
        )
    if voxel_wall_facts.micro_span_cell_ids:
        issues.append(
            "Authored wall-cell plane-mask contract failed: run/Z micro-span cells are below "
            f"{MIN_NON_THICKNESS_CELL_SPAN_STUDS:g} studs: "
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.micro_span_cell_ids[:8])
            + ("." if len(voxel_wall_facts.micro_span_cell_ids) <= 8 else ", ...")
        )
    fragment_adapter_group_ids = tuple(
        group.group_id or group.label
        for group in voxel_wall_facts.groups
        if group.authoring_mode == "fragment_adapter"
    )
    if fragment_adapter_group_ids:
        issues.append(
            "Authored wall-cell plane-mask contract failed: gameplay wall groups are still fragment-adapter authored: "
            + ", ".join(f"'{name}'" for name in fragment_adapter_group_ids[:8])
            + ("." if len(fragment_adapter_group_ids) <= 8 else ", ...")
        )
    for coverage in voxel_wall_facts.plane_area_coverages:
        if coverage.coverage_ratio >= MIN_WALL_PLANE_AREA_COVERAGE_RATIO:
            continue
        issues.append(
            f"Authored wall-cell plane-mask contract failed: wall group '{coverage.group_id}' "
            f"covers {coverage.coverage_ratio * 100:.1f}% of expected solid mask area "
            f"({coverage.actual_cell_area_studs2:.4g}/{coverage.expected_solid_area_studs2:.4g} studs^2); "
            f"required >= {MIN_WALL_PLANE_AREA_COVERAGE_RATIO * 100:.0f}%."
        )
    for intrusion in voxel_wall_facts.opening_cut_intrusions:
        issues.append(
            f"Authored wall-cell plane-mask contract failed: wall group '{intrusion.group_id}' has cells "
            f"overlapping expanded opening clearance '{intrusion.cut_label}': "
            + ", ".join(f"'{name}'" for name in intrusion.cell_ids[:8])
            + ("." if len(intrusion.cell_ids) <= 8 else ", ...")
        )
    if voxel_wall_facts.preview_cache_object_names:
        preview_cell_text = (
            "unknown"
            if voxel_wall_facts.preview_cache_cell_count is None
            else str(voxel_wall_facts.preview_cache_cell_count)
        )
        issues.append(
            "Authored wall-cell contract failed: stale Preview Voxels helper geometry remains under finalized root "
            f"({len(voxel_wall_facts.preview_cache_object_names)} object(s), {preview_cell_text} cached cells): "
            + ", ".join(f"'{name}'" for name in voxel_wall_facts.preview_cache_object_names[:8])
            + ("." if len(voxel_wall_facts.preview_cache_object_names) <= 8 else ", ...")
        )
    if voxel_wall_facts.opening_visual_count > 0 and voxel_wall_facts.opening_seating_source_count == 0:
        issues.append(
            "Stage 2B opening visual-truth contract failed [owner=bad_visual_placement]: "
            f"{voxel_wall_facts.opening_visual_count} stamped opening visual(s) exist, but zero "
            "window/door/roof-exit seating sources were classified for actual gap checks."
        )
    if voxel_wall_facts.actual_missing_boundary_sides_total > 0:
        issues.append(
            "Stage 3 actual visual opening gap failed [owner=bad_visual_placement]: "
            f"{voxel_wall_facts.actual_missing_boundary_sides_total} seating boundary side(s) have no adjacent final cell edge."
        )
    for residual in voxel_wall_facts.sub_min_residuals:
        issues.append(
            "Stage 2B opening residual failed [owner=sub_min_residual]: "
            f"payload group '{residual.group_id}' cut '{residual.cut_label}' leaves "
            f"{residual.residual_studs:.4f} studs on {residual.side}, below "
            f"{residual.threshold_studs:.4f} studs."
        )
    for stamp_issue in voxel_wall_facts.opening_stamp_issues:
        issues.append(
            f"Stage 2B opening visual-truth contract failed [owner=bad_stamp]: opening object '{stamp_issue.object_name}' "
            f"has missing/invalid scalar stamp metadata ({stamp_issue.reason})."
        )
    for deferred in voxel_wall_facts.deferred_unstamped_openings:
        issues.append(
            f"Stage 2B opening visual-truth contract deferred [owner=bad_stamp]: opening object '{deferred.object_name}' "
            f"is outside the current stamped contract ({deferred.reason})."
        )
    for opening in voxel_wall_facts.opening_visuals:
        opening_label = (
            f"{opening.kind} {opening.side} F{opening.floor:02d} S{opening.slot:02d} "
            f"object '{opening.object_name}'"
        )
        if opening.is_terrace_exit:
            continue
        if not opening.matching_group_id or not opening.matching_cut_label:
            issues.append(
                "Stage 2B opening visual-truth contract failed [owner=bad_payload_cut]: "
                f"{opening_label} has no matching same-plane payload rect_cuts[] entry "
                f"for cut run=({opening.cut_run_min:.4f},{opening.cut_run_max:.4f}) "
                f"z=({opening.cut_z_min:.4f},{opening.cut_z_max:.4f}) "
                f"plane={opening.plane_normal_axis}@{opening.plane_pos:.4f}."
            )
            continue
        if opening.same_plane_overlap_cell_ids:
            issues.append(
                "Stage 2B same-plane opening overlap failed [owner=bad_cell_boundary]: "
                f"{opening_label} positive-volume overlaps authored cells on payload group "
                f"'{opening.matching_group_id}' cut '{opening.matching_cut_label}': "
                + ", ".join(f"'{name}'" for name in opening.same_plane_overlap_cell_ids[:8])
                + ("." if len(opening.same_plane_overlap_cell_ids) <= 8 else ", ...")
            )
        if opening.max_gap_studs is not None and (
            not math.isfinite(float(opening.max_gap_studs)) or float(opening.max_gap_studs) > 0.05
        ):
            gap_text = "missing adjacent cell boundary" if not math.isfinite(float(opening.max_gap_studs)) else f"{opening.max_gap_studs:.4f} studs"
            issues.append(
                "Stage 2B opening mask gap failed [owner=bad_cell_boundary]: "
                f"{opening_label} has {gap_text} gap on {opening.gap_side or 'unknown'} side "
                f"for payload group '{opening.matching_group_id}' cut '{opening.matching_cut_label}' "
                "(allowed <= 0.05 studs)."
            )
        if opening.is_seating_source and opening.actual_max_gap_studs is not None and (
            not math.isfinite(float(opening.actual_max_gap_studs)) or float(opening.actual_max_gap_studs) > 0.05
        ):
            gap_text = (
                "missing adjacent cell boundary"
                if not math.isfinite(float(opening.actual_max_gap_studs))
                else f"{opening.actual_max_gap_studs:.4f} studs"
            )
            issues.append(
                "Stage 3 actual visual opening gap failed [owner=bad_visual_placement]: "
                f"{opening_label} actual projected bounds "
                f"run=({opening.actual_run_min:.4f},{opening.actual_run_max:.4f}) "
                f"z=({opening.actual_z_min:.4f},{opening.actual_z_max:.4f}) "
                f"have {gap_text} gap on {opening.actual_gap_side or 'unknown'} side "
                f"for payload group '{opening.matching_group_id}' cut '{opening.matching_cut_label}' "
                "(allowed <= 0.05 studs)."
            )
        if opening.cut_intrusion_cell_ids:
            issues.append(
                "Stage 2B opening cut backfill failed [owner=bad_cell_boundary]: "
                f"{opening_label} cut '{opening.matching_cut_label}' is backfilled by authored cells "
                + ", ".join(f"'{name}'" for name in opening.cut_intrusion_cell_ids[:8])
                + ("." if len(opening.cut_intrusion_cell_ids) <= 8 else ", ...")
            )
        if opening.cross_plane_leakage_cell_ids:
            issues.append(
                "Stage 2B cross-plane opening leakage failed [owner=bad_cell_boundary]: "
                f"{opening_label} is penetrated by interior/stair cells "
                + ", ".join(f"'{name}'" for name in opening.cross_plane_leakage_cell_ids[:8])
                + ("." if len(opening.cross_plane_leakage_cell_ids) <= 8 else ", ...")
            )
    if (
        voxel_wall_facts.trim_back_air_gap_max_studs is not None
        and voxel_wall_facts.trim_back_air_gap_max_studs > TRIM_BACK_AIR_GAP_MAX_STUDS
    ):
        issues.append(
            "Stage G19 trim attachment failed [owner=floating_trim_band]: max trim back-face air gap "
            f"{voxel_wall_facts.trim_back_air_gap_max_studs:.4f} studs exceeds "
            f"{TRIM_BACK_AIR_GAP_MAX_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.trim_back_overlap_min_studs is not None
        and voxel_wall_facts.trim_back_overlap_min_studs < TRIM_BACK_OVERLAP_MIN_STUDS
    ):
        issues.append(
            "Stage G19 trim attachment failed [owner=floating_trim_band]: min trim back-face overlap "
            f"{voxel_wall_facts.trim_back_overlap_min_studs:.4f} studs is below "
            f"{TRIM_BACK_OVERLAP_MIN_STUDS:.4f} studs."
        )
    if voxel_wall_facts.floating_trim_object_count > 0:
        offenders = [
            fact.object_name
            for fact in voxel_wall_facts.trim_attachment_facts
            if fact.owner_class == "floating_trim_band"
        ]
        issues.append(
            "Stage G19 trim attachment failed [owner=floating_trim_band]: "
            f"{voxel_wall_facts.floating_trim_object_count} trim/band object(s) are detached from wall cells: "
            + ", ".join(f"'{name}'" for name in offenders[:8])
            + ("." if len(offenders) <= 8 else ", ...")
        )
    if (
        voxel_wall_facts.trim_segment_back_air_gap_max_studs is not None
        and voxel_wall_facts.trim_segment_back_air_gap_max_studs > TRIM_BACK_AIR_GAP_MAX_STUDS
    ):
        issues.append(
            "Stage G19 trim segment attachment failed [owner=floating_trim_band]: max segment back air gap "
            f"{voxel_wall_facts.trim_segment_back_air_gap_max_studs:.4f} studs exceeds "
            f"{TRIM_BACK_AIR_GAP_MAX_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.trim_segment_back_overlap_min_studs is not None
        and voxel_wall_facts.trim_segment_back_overlap_min_studs < TRIM_BACK_OVERLAP_MIN_STUDS
    ):
        issues.append(
            "Stage G19 trim segment attachment failed [owner=floating_trim_band]: min segment back overlap "
            f"{voxel_wall_facts.trim_segment_back_overlap_min_studs:.4f} studs is below "
            f"{TRIM_BACK_OVERLAP_MIN_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.parapet_cap_segment_back_air_gap_max_studs is not None
        and voxel_wall_facts.parapet_cap_segment_back_air_gap_max_studs > TRIM_BACK_AIR_GAP_MAX_STUDS
    ):
        issues.append(
            "Stage G19 parapet cap attachment failed [owner=floating_trim_band]: max cap back air gap "
            f"{voxel_wall_facts.parapet_cap_segment_back_air_gap_max_studs:.4f} studs exceeds "
            f"{TRIM_BACK_AIR_GAP_MAX_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.townhouse_like_parapet_height_min_studs is not None
        and voxel_wall_facts.townhouse_like_parapet_height_min_studs < RESIDENTIAL_BORDER_MIN_STUDS
    ):
        issues.append(
            "Stage G19 townhouse roof border failed [owner=floating_trim_band]: parapet height "
            f"{voxel_wall_facts.townhouse_like_parapet_height_min_studs:.4f} studs is below "
            f"{RESIDENTIAL_BORDER_MIN_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.frame_silhouette_thickness_min_studs is not None
        and voxel_wall_facts.frame_silhouette_thickness_min_studs < FRAME_SILHOUETTE_MIN_STUDS
    ):
        issues.append(
            "Stage G20 frame mass failed [owner=frame_mass_thin]: min frame silhouette thickness "
            f"{voxel_wall_facts.frame_silhouette_thickness_min_studs:.4f} studs is below "
            f"{FRAME_SILHOUETTE_MIN_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.frame_ring_width_min_studs is not None
        and voxel_wall_facts.frame_ring_width_min_studs < FRAME_RING_WIDTH_MIN_STUDS
    ):
        issues.append(
            "Stage G20 frame mass failed [owner=frame_mass_thin]: min frame ring width "
            f"{voxel_wall_facts.frame_ring_width_min_studs:.4f} studs is below "
            f"{FRAME_RING_WIDTH_MIN_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.frame_inner_return_depth_min_studs is not None
        and voxel_wall_facts.frame_inner_return_depth_min_studs < FRAME_INNER_RETURN_MIN_STUDS
    ):
        issues.append(
            "Stage G20 frame mass failed [owner=frame_mass_thin]: min frame inner return depth "
            f"{voxel_wall_facts.frame_inner_return_depth_min_studs:.4f} studs is below "
            f"{FRAME_INNER_RETURN_MIN_STUDS:.4f} studs."
        )
    if voxel_wall_facts.frame_open_boundary_edge_count != 0:
        issues.append(
            "Stage G20 frame topology failed [owner=frame_mass_thin]: "
            f"{voxel_wall_facts.frame_open_boundary_edge_count} open frame boundary edge(s) remain."
        )
    if (
        voxel_wall_facts.opening_frame_mass_facts
        and voxel_wall_facts.frame_outer_perimeter_face_count < 4
    ):
        issues.append(
            "Stage G20 frame topology failed [owner=frame_mass_thin]: min outer-perimeter face count "
            f"{voxel_wall_facts.frame_outer_perimeter_face_count} is below 4."
        )
    if voxel_wall_facts.frame_sill_or_head_mass_missing_count != 0:
        issues.append(
            "Stage G20 frame gasket mass failed [owner=frame_mass_thin]: "
            f"{voxel_wall_facts.frame_sill_or_head_mass_missing_count} frame(s) are missing sill/head mass."
        )
    if (
        voxel_wall_facts.frame_gasket_air_gap_max_studs is not None
        and voxel_wall_facts.frame_gasket_air_gap_max_studs > TRIM_BACK_AIR_GAP_MAX_STUDS
    ):
        issues.append(
            "Stage G20 frame contact failed [owner=frame_mass_thin]: max gasket back air gap "
            f"{voxel_wall_facts.frame_gasket_air_gap_max_studs:.4f} studs exceeds "
            f"{TRIM_BACK_AIR_GAP_MAX_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.frame_gasket_back_overlap_min_studs is not None
        and voxel_wall_facts.frame_gasket_back_overlap_min_studs < TRIM_BACK_OVERLAP_MIN_STUDS
    ):
        issues.append(
            "Stage G20 frame contact failed [owner=frame_mass_thin]: min gasket back overlap "
            f"{voxel_wall_facts.frame_gasket_back_overlap_min_studs:.4f} studs is below "
            f"{TRIM_BACK_OVERLAP_MIN_STUDS:.4f} studs."
        )
    if voxel_wall_facts.unstamped_opening_trim_object_count > 0:
        offenders = [
            fact.object_name
            for fact in voxel_wall_facts.opening_frame_mass_facts
            if not fact.has_opening_stamp
        ]
        issues.append(
            "Stage G20 frame stamp failed [owner=unstamped_opening_trim]: "
            f"{voxel_wall_facts.unstamped_opening_trim_object_count} opening frame/trim object(s) lack scalar cut stamps: "
            + ", ".join(f"'{name}'" for name in offenders[:8])
            + ("." if len(offenders) <= 8 else ", ...")
        )
    if (
        voxel_wall_facts.window_cut_envelope_match_max_delta_studs is not None
        and voxel_wall_facts.window_cut_envelope_match_max_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
    ):
        issues.append(
            "Stage G21 window cut-envelope match failed [owner=cut_envelope_mismatch]: max delta "
            f"{voxel_wall_facts.window_cut_envelope_match_max_delta_studs:.4f} studs exceeds "
            f"{CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.door_frame_cut_envelope_match_max_delta_studs is not None
        and voxel_wall_facts.door_frame_cut_envelope_match_max_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
    ):
        issues.append(
            "Stage G21 door-frame cut-envelope match failed [owner=cut_envelope_mismatch]: max delta "
            f"{voxel_wall_facts.door_frame_cut_envelope_match_max_delta_studs:.4f} studs exceeds "
            f"{CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:.4f} studs."
        )
    if voxel_wall_facts.ordinary_door_unseated_count > 0:
        issues.append(
            "Stage G21 ordinary door seating failed [owner=ordinary_door_unseated]: "
            f"{voxel_wall_facts.ordinary_door_unseated_count} ordinary door leaf/opening pair(s) lack a seated stamped frame."
        )
    if (
        voxel_wall_facts.ordinary_door_panel_height_delta_studs is not None
        and voxel_wall_facts.ordinary_door_panel_height_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
    ):
        issues.append(
            "Stage G21 ordinary door height failed [owner=ordinary_door_unseated]: max panel height delta "
            f"{voxel_wall_facts.ordinary_door_panel_height_delta_studs:.4f} studs exceeds "
            f"{CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.roof_exit_door_panel_height_delta_studs is not None
        and voxel_wall_facts.roof_exit_door_panel_height_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
    ):
        issues.append(
            "Stage G23 roof-exit door height failed [owner=roof_exit_lintel_unpacked]: panel height delta "
            f"{voxel_wall_facts.roof_exit_door_panel_height_delta_studs:.4f} studs exceeds "
            f"{CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:.4f} studs."
        )
    if voxel_wall_facts.rear_door_window_clearance_overlap_count > 0:
        issues.append(
            "Stage G21 rear-door reservation failed [owner=rear_window_candidate_collision]: "
            f"{voxel_wall_facts.rear_door_window_clearance_overlap_count} same-floor rear window candidate(s) "
            "overlap the rear-door reserved span."
        )
    if voxel_wall_facts.rear_door_reserved_span_window_candidate_overlap_count > 0:
        issues.append(
            "Stage G21 rear-door candidate mask failed [owner=rear_window_candidate_collision]: "
            f"{voxel_wall_facts.rear_door_reserved_span_window_candidate_overlap_count} candidate overlap(s), "
            f"max {voxel_wall_facts.rear_door_reserved_span_window_overlap_max_studs:.4f} studs."
        )
    if voxel_wall_facts.rear_door_reserved_span_window_overlap_max_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:
        issues.append(
            "Stage G21 rear-door reserved span overlap failed [owner=rear_window_candidate_collision]: max overlap "
            f"{voxel_wall_facts.rear_door_reserved_span_window_overlap_max_studs:.4f} studs exceeds "
            f"{CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:.4f} studs."
        )
    if voxel_wall_facts.roof_exit_lintel_closure_present_count != voxel_wall_facts.roof_exit_lintel_required_count:
        issues.append(
            "Stage G23 roof-exit lintel closure failed [owner=roof_exit_lintel_unpacked]: "
            f"{voxel_wall_facts.roof_exit_lintel_closure_present_count} present, "
            f"{voxel_wall_facts.roof_exit_lintel_required_count} required."
        )
    if (
        voxel_wall_facts.roof_exit_lintel_closure_distinct_from_frame_count
        != voxel_wall_facts.roof_exit_lintel_required_count
    ):
        issues.append(
            "Stage G23 roof-exit closure owner failed [owner=roof_exit_lintel_real_closure]: "
            f"{voxel_wall_facts.roof_exit_lintel_closure_distinct_from_frame_count} distinct non-frame closure(s), "
            f"{voxel_wall_facts.roof_exit_lintel_required_count} required."
        )
    if voxel_wall_facts.roof_exit_lintel_closure_section_bucket_invalid_count > 0:
        issues.append(
            "Stage G23 roof-exit closure bucket failed [owner=roof_exit_lintel_real_closure]: "
            f"{voxel_wall_facts.roof_exit_lintel_closure_section_bucket_invalid_count} tagged closure object(s) "
            "are outside Section_Walls_Roof."
        )
    if voxel_wall_facts.roof_exit_lintel_closure_from_door_trim_count > 0:
        issues.append(
            "Stage G23 roof-exit closure source failed [owner=roof_exit_lintel_real_closure]: "
            f"{voxel_wall_facts.roof_exit_lintel_closure_from_door_trim_count} frame/door/Section_Doors_Trim "
            "object(s) are tagged as closure."
        )
    if (
        voxel_wall_facts.roof_exit_top_band_coverage_ratio is not None
        and voxel_wall_facts.roof_exit_top_band_coverage_ratio < ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
    ):
        issues.append(
            "Stage G23 roof-exit top band coverage failed [owner=roof_exit_lintel_real_closure]: coverage ratio "
            f"{voxel_wall_facts.roof_exit_top_band_coverage_ratio:.4f} is below "
            f"{ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN:.4f}."
        )
    if (
        voxel_wall_facts.roof_exit_frame_inner_height_delta_studs is not None
        and voxel_wall_facts.roof_exit_frame_inner_height_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
    ):
        issues.append(
            "Stage G23 roof-exit frame aperture height failed [owner=roof_exit_frame_inflated]: inner height delta "
            f"{voxel_wall_facts.roof_exit_frame_inner_height_delta_studs:.4f} studs exceeds "
            f"{CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.roof_exit_frame_outer_height_delta_studs is not None
        and voxel_wall_facts.roof_exit_frame_outer_height_delta_studs > CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS
    ):
        issues.append(
            "Stage G23 roof-exit frame outer height failed [owner=roof_exit_frame_inflated]: outer height delta "
            f"{voxel_wall_facts.roof_exit_frame_outer_height_delta_studs:.4f} studs exceeds "
            f"{CUT_ENVELOPE_MATCH_MAX_DELTA_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.roof_exit_frame_cut_height_ratio_max is not None
        and voxel_wall_facts.roof_exit_frame_cut_height_ratio_max > 1.10
    ):
        issues.append(
            "Stage G23 roof-exit frame ratio failed [owner=roof_exit_frame_inflated]: frame/canonical height ratio "
            f"{voxel_wall_facts.roof_exit_frame_cut_height_ratio_max:.4f} exceeds 1.1000."
        )
    if voxel_wall_facts.roof_exit_frame_counts_as_lintel_count > 0:
        issues.append(
            "Stage G23 roof-exit frame owner failed [owner=roof_exit_frame_inflated]: "
            f"{voxel_wall_facts.roof_exit_frame_counts_as_lintel_count} roof-exit frame(s) are counted/tagged as lintel closure."
        )
    if (
        voxel_wall_facts.roof_exit_top_wall_lintel_coverage_ratio is not None
        and voxel_wall_facts.roof_exit_top_wall_lintel_coverage_ratio < ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
    ):
        issues.append(
            "Stage G23 roof-exit wall lintel coverage failed [owner=roof_exit_lintel_real_closure]: non-frame coverage ratio "
            f"{voxel_wall_facts.roof_exit_top_wall_lintel_coverage_ratio:.4f} is below "
            f"{ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN:.4f}."
        )
    if voxel_wall_facts.roof_exit_uncovered_cut_top_gap_count > 0:
        issues.append(
            "Stage G21 roof-exit cut coverage failed [owner=roof_exit_lintel_unpacked]: "
            f"{voxel_wall_facts.roof_exit_uncovered_cut_top_gap_count} roof-exit cut(s) have uncovered top gap."
        )
    if voxel_wall_facts.terrace_exit_unclassified_top_coverage_count > 0:
        issues.append(
            "Stage G23 terrace-exit classification failed [owner=terrace_exit_classification]: "
            f"{voxel_wall_facts.terrace_exit_unclassified_top_coverage_count} terrace exit opening(s) lack explicit "
            "top-owner class."
        )
    if voxel_wall_facts.terrace_exit_owner_class_invalid_count > 0:
        issues.append(
            "Stage G23 terrace-exit owner class failed [owner=terrace_exit_classification]: "
            f"{voxel_wall_facts.terrace_exit_owner_class_invalid_count} terrace top owner class value(s) are invalid."
        )
    if (
        voxel_wall_facts.terrace_exit_top_band_coverage_ratio is not None
        and voxel_wall_facts.terrace_exit_top_band_coverage_ratio < ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
    ):
        issues.append(
            "Stage G23 terrace-exit top coverage failed [owner=terrace_exit_classification]: coverage ratio "
            f"{voxel_wall_facts.terrace_exit_top_band_coverage_ratio:.4f} is below "
            f"{ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN:.4f}."
        )
    if voxel_wall_facts.terrace_exit_frame_floor_penetration_count > 0:
        issues.append(
            "Stage G23 terrace-exit floor penetration failed [owner=terrace_exit_traversal_blocker]: "
            f"{voxel_wall_facts.terrace_exit_frame_floor_penetration_count} terrace frame owner(s) penetrate below floor."
        )
    if (
        voxel_wall_facts.terrace_exit_frame_floor_penetration_max_studs is not None
        and voxel_wall_facts.terrace_exit_frame_floor_penetration_max_studs > TRIM_BACK_AIR_GAP_MAX_STUDS
    ):
        issues.append(
            "Stage G23 terrace-exit floor penetration failed [owner=terrace_exit_traversal_blocker]: max penetration "
            f"{voxel_wall_facts.terrace_exit_frame_floor_penetration_max_studs:.4f} studs exceeds "
            f"{TRIM_BACK_AIR_GAP_MAX_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.terrace_exit_threshold_obstruction_height_max_studs is not None
        and voxel_wall_facts.terrace_exit_threshold_obstruction_height_max_studs > 0.02
    ):
        issues.append(
            "Stage G23 terrace-exit threshold failed [owner=terrace_exit_traversal_blocker]: threshold obstruction "
            f"{voxel_wall_facts.terrace_exit_threshold_obstruction_height_max_studs:.4f} studs exceeds 0.0200 studs."
        )
    if voxel_wall_facts.terrace_exit_traversal_blocker_count > 0:
        issues.append(
            "Stage G23 terrace-exit traversal failed [owner=terrace_exit_traversal_blocker]: "
            f"{voxel_wall_facts.terrace_exit_traversal_blocker_count} terrace owner(s) reduce clear traversal."
        )
    if (
        voxel_wall_facts.terrace_exit_clear_passage_height_min_studs is not None
        and voxel_wall_facts.terrace_exit_clear_passage_height_min_studs < 1.90
    ):
        issues.append(
            "Stage G23 terrace-exit clear height failed [owner=terrace_exit_traversal_blocker]: clear passage height "
            f"{voxel_wall_facts.terrace_exit_clear_passage_height_min_studs:.4f} studs is below 1.9000 studs."
        )
    if (
        voxel_wall_facts.terrace_exit_top_transom_coverage_ratio is not None
        and voxel_wall_facts.terrace_exit_top_transom_coverage_ratio < ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
    ):
        issues.append(
            "Stage G23 terrace-exit transom coverage failed [owner=terrace_exit_classification]: top transom coverage "
            f"{voxel_wall_facts.terrace_exit_top_transom_coverage_ratio:.4f} is below "
            f"{ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN:.4f}."
        )
    if not voxel_wall_facts.terrace_exit_allowed_frame_inflation:
        issues.append(
            "Stage G23 terrace-exit frame owner failed [owner=terrace_exit_classification]: "
            "frame/transom inflation is not tied to an explicitly tagged terrace exit."
        )
    if (
        voxel_wall_facts.opening_visual_seal_gap_max_studs is not None
        and voxel_wall_facts.opening_visual_seal_gap_max_studs > OPENING_VISUAL_SEAL_GAP_MAX_STUDS
    ):
        issues.append(
            "Stage G22 opening visual seal failed [owner=visual_seal_gap]: max seal gap "
            f"{voxel_wall_facts.opening_visual_seal_gap_max_studs:.4f} studs exceeds "
            f"{OPENING_VISUAL_SEAL_GAP_MAX_STUDS:.4f} studs."
        )
    if (
        voxel_wall_facts.roof_exit_side_seal_gap_max_studs is not None
        and voxel_wall_facts.roof_exit_side_seal_gap_max_studs > OPENING_VISUAL_SEAL_GAP_MAX_STUDS
    ):
        issues.append(
            "Stage G23 roof-exit side seal failed [owner=visual_seal_gap]: max side seal gap "
            f"{voxel_wall_facts.roof_exit_side_seal_gap_max_studs:.4f} studs exceeds "
            f"{OPENING_VISUAL_SEAL_GAP_MAX_STUDS:.4f} studs."
        )
    if voxel_wall_facts.roof_exit_top_closure_gap_count > 0:
        issues.append(
            "Stage G23 roof-exit top closure failed [owner=roof_exit_lintel_unpacked]: "
            f"{voxel_wall_facts.roof_exit_top_closure_gap_count} roof-exit top closure gap(s) remain."
        )
    if (
        voxel_wall_facts.roof_exit_cut_covered_area_ratio is not None
        and voxel_wall_facts.roof_exit_cut_covered_area_ratio < ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN
    ):
        issues.append(
            "Stage G23 roof-exit cut coverage failed [owner=roof_exit_lintel_unpacked]: covered area ratio "
            f"{voxel_wall_facts.roof_exit_cut_covered_area_ratio:.4f} is below "
            f"{ROOF_EXIT_CUT_COVERED_AREA_RATIO_MIN:.4f}."
        )
    for protrusion in voxel_wall_facts.top_profile_protrusions:
        issues.append(
            f"Authored wall-cell plane-mask contract failed: wall group '{protrusion.group_id}' has cells "
            "protruding above the stored top profile: "
            + ", ".join(f"'{name}'" for name in protrusion.cell_ids[:8])
            + ("." if len(protrusion.cell_ids) <= 8 else ", ...")
        )

    allowed_buckets = export_contract.VOXEL_WALL_SOURCE_BUCKETS
    allowed_materials = export_contract.VOXEL_WALL_MATERIAL_FAMILIES
    allowed_visual_styles = export_contract.VOXEL_WALL_VISUAL_STYLES
    required_group_keys = {
        "group_id",
        "source_bucket",
        "material_family",
        "authoring_mode",
        "normal_axis",
        "run_axis",
        "plane_run_min_studs",
        "plane_run_max_studs",
        "plane_z_min_studs",
        "plane_z_max_studs",
        "plane_thickness_min_studs",
        "plane_thickness_max_studs",
        "display_color_rgb",
        "surface_u_origin_studs",
        "surface_v_origin_studs",
        "texture_key",
        "texture_projection",
        "texture_image_period_contract",
        "texture_face_axis_table_version",
        "studs_per_tile_u",
        "studs_per_tile_v",
        "color_modulation_policy",
        "cell_count",
    }
    required_cell_keys = {
        "cell_id",
        "group_id",
        "normal_axis",
        "run_axis",
        "min_studs",
        "size_studs",
    }
    group_lookup = {group.group_id: group for group in voxel_wall_facts.groups if group.group_id}
    cells_by_group_id: dict[str, list[object]] = {}
    for cell in voxel_wall_facts.cells:
        if cell.group_id:
            cells_by_group_id.setdefault(cell.group_id, []).append(cell)

    for group in voxel_wall_facts.groups:
        group_name = group.group_id or group.label
        if group.payload is None:
            continue
        missing_keys = tuple(sorted(required_group_keys.difference(group.payload.keys())))
        if missing_keys:
            issues.append(
                f"Authored wall-cell group '{group_name}' is missing payload keys: {', '.join(missing_keys)}."
            )
        if legacy_group_count_key in group.payload:
            issues.append(f"Authored wall-cell group '{group_name}' contains legacy group count metadata.")
        if not group.group_id:
            issues.append(f"Authored wall-cell group '{group.label}' is missing payload field 'group_id'.")
        if group.authoring_mode != "plane_mask":
            issues.append(
                f"Authored wall-cell group '{group_name}' has invalid authoring_mode '{group.authoring_mode}'; "
                "fresh gameplay wall groups must be explicit plane_mask output."
            )
        if group.source_fragment_ids:
            issues.append(
                f"Authored wall-cell group '{group_name}' still carries fragment-adapter provenance."
            )
        if group.normal_axis not in {"x", "y"}:
            issues.append(
                f"Authored wall-cell group '{group_name}' has invalid normal_axis '{group.normal_axis}'; expected 'x' or 'y'."
            )
        expected_group_run_axis = "y" if group.normal_axis == "x" else "x" if group.normal_axis == "y" else ""
        if group.run_axis not in {"x", "y"}:
            issues.append(
                f"Authored wall-cell group '{group_name}' has invalid run_axis '{group.run_axis}'; expected 'x' or 'y'."
            )
        elif expected_group_run_axis and group.run_axis != expected_group_run_axis:
            issues.append(
                f"Authored wall-cell group '{group_name}' has run_axis '{group.run_axis}' inconsistent with "
                f"normal_axis '{group.normal_axis}'."
            )
        for field_name, value in (
            ("plane_run_min_studs", group.plane_run_min_studs),
            ("plane_run_max_studs", group.plane_run_max_studs),
            ("plane_z_min_studs", group.plane_z_min_studs),
            ("plane_z_max_studs", group.plane_z_max_studs),
            ("plane_thickness_min_studs", group.plane_thickness_min_studs),
            ("plane_thickness_max_studs", group.plane_thickness_max_studs),
        ):
            if value is None:
                issues.append(f"Authored wall-cell group '{group_name}' is missing finite {field_name}.")
            elif not math.isfinite(float(value)):
                issues.append(f"Authored wall-cell group '{group_name}' has non-finite {field_name}.")
        if (
            group.plane_run_min_studs is not None
            and group.plane_run_max_studs is not None
            and float(group.plane_run_max_studs) - float(group.plane_run_min_studs) < MIN_NON_THICKNESS_CELL_SPAN_STUDS
        ):
            issues.append(f"Authored wall-cell group '{group_name}' run span is below plane-mask minimum.")
        if (
            group.plane_z_min_studs is not None
            and group.plane_z_max_studs is not None
            and float(group.plane_z_max_studs) - float(group.plane_z_min_studs) < MIN_NON_THICKNESS_CELL_SPAN_STUDS
        ):
            issues.append(f"Authored wall-cell group '{group_name}' Z span is below plane-mask minimum.")
        if (
            group.plane_thickness_min_studs is not None
            and group.plane_thickness_max_studs is not None
            and float(group.plane_thickness_max_studs) <= float(group.plane_thickness_min_studs)
        ):
            issues.append(f"Authored wall-cell group '{group_name}' has non-positive thickness span.")
        previous_profile_run = None
        for run, _z in group.top_profile:
            if previous_profile_run is not None and float(run) <= float(previous_profile_run):
                issues.append(f"Authored wall-cell group '{group_name}' top_profile run values must be strictly increasing.")
                break
            previous_profile_run = run
        for cut in group.rect_cuts:
            if not cut.kind:
                issues.append(f"Authored wall-cell group '{group_name}' has an unnamed rectangular opening cut [owner=bad_payload_cut].")
            if cut.run_min is None or cut.run_max is None or cut.z_min is None or cut.z_max is None:
                issues.append(f"Authored wall-cell group '{group_name}' has malformed rectangular opening cut '{cut.label}' [owner=bad_payload_cut].")
            elif float(cut.run_max) <= float(cut.run_min) or float(cut.z_max) <= float(cut.z_min):
                issues.append(f"Authored wall-cell group '{group_name}' has non-positive rectangular opening cut '{cut.label}' [owner=bad_payload_cut].")
        if group.source_bucket not in allowed_buckets:
            issues.append(
                f"Authored wall-cell group '{group_name}' has unsupported source bucket '{group.source_bucket}'."
            )
        if group.material_family not in allowed_materials:
            issues.append(
                f"Authored wall-cell group '{group_name}' has unsupported material family '{group.material_family}'."
            )
        if group.material_family in {"BRICK", "WOOD"} and not group.visual_style:
            issues.append(f"Authored wall-cell group '{group_name}' is missing canonical visual_style metadata.")
        if group.visual_style is not None and group.visual_style not in allowed_visual_styles:
            issues.append(
                f"Authored wall-cell group '{group_name}' has unsupported visual_style '{group.visual_style}'."
            )
        if group.display_color_rgb is None:
            issues.append(f"Authored wall-cell group '{group_name}' is missing canonical display_color_rgb metadata.")
        for field_name, value in (
            ("surface_u_origin_studs", group.surface_u_origin_studs),
            ("surface_v_origin_studs", group.surface_v_origin_studs),
        ):
            if value is None:
                issues.append(f"Authored wall-cell group '{group_name}' is missing finite {field_name}.")
            elif not math.isfinite(float(value)):
                issues.append(f"Authored wall-cell group '{group_name}' has non-finite {field_name}.")
        if not group.texture_key:
            issues.append(f"Authored wall-cell group '{group_name}' is missing texture_key.")
        if group.texture_projection not in export_contract.TEXTURE_PROJECTIONS:
            issues.append(f"Authored wall-cell group '{group_name}' has invalid texture_projection '{group.texture_projection}'.")
        expected_projection = (
            export_contract.TEXTURE_PROJECTION_MATERIAL_VARIANT_STYLE_V1
            if group.material_family in export_contract.TEXTURED_VOXEL_WALL_MATERIAL_FAMILIES and group.visual_style
            else export_contract.TEXTURE_PROJECTION_SOLID_COLOR_V1
        )
        if group.texture_projection and group.texture_projection != expected_projection:
            issues.append(
                f"Authored wall-cell group '{group_name}' texture projection classification drifted "
                f"({group.texture_projection} != {expected_projection})."
            )
        if group.texture_image_period_contract not in export_contract.TEXTURE_IMAGE_PERIOD_CONTRACTS:
            issues.append(f"Authored wall-cell group '{group_name}' has invalid texture_image_period_contract.")
        if group.texture_face_axis_table_version != export_contract.TEXTURE_FACE_AXIS_TABLE_VERSION_V1:
            issues.append(f"Authored wall-cell group '{group_name}' has invalid texture_face_axis_table_version.")
        for field_name, value in (
            ("studs_per_tile_u", group.studs_per_tile_u),
            ("studs_per_tile_v", group.studs_per_tile_v),
        ):
            if value is None or not math.isfinite(float(value)) or float(value) <= 0.0:
                issues.append(f"Authored wall-cell group '{group_name}' has invalid positive {field_name}.")
        if group.color_modulation_policy != export_contract.COLOR_MODULATION_POLICY_NONE:
            issues.append(f"Authored wall-cell group '{group_name}' has invalid color_modulation_policy '{group.color_modulation_policy}'.")
        resolved_group_cells = cells_by_group_id.get(group.group_id, [])
        if group.cell_count is None:
            issues.append(f"Authored wall-cell group '{group_name}' has malformed cell_count.")
        elif group.cell_count != len(resolved_group_cells):
            issues.append(
                f"Authored wall-cell group '{group_name}' cell_count does not match parsed cells "
                f"({group.cell_count} != {len(resolved_group_cells)})."
            )
    for cell in voxel_wall_facts.cells:
        cell_name = cell.cell_id or cell.label
        if cell.payload is None:
            continue
        missing_keys = tuple(sorted(required_cell_keys.difference(cell.payload.keys())))
        if missing_keys:
            issues.append(
                f"Authored wall cell '{cell_name}' is missing payload keys: {', '.join(missing_keys)}."
            )
        if not cell.cell_id:
            issues.append(f"Authored wall cell '{cell.label}' is missing payload field 'cell_id'.")
        if not cell.group_id:
            issues.append(f"Authored wall cell '{cell.label}' is missing payload field 'group_id'.")
        elif cell.group_id not in group_lookup:
            issues.append(f"Authored wall cell '{cell_name}' references missing wall group '{cell.group_id}'.")
        else:
            owning_group = group_lookup[cell.group_id]
            if owning_group.normal_axis and cell.normal_axis != owning_group.normal_axis:
                issues.append(
                    f"Authored wall cell '{cell_name}' normal_axis '{cell.normal_axis}' does not match group "
                    f"'{cell.group_id}' normal_axis '{owning_group.normal_axis}'."
                )
            if owning_group.run_axis and cell.run_axis != owning_group.run_axis:
                issues.append(
                    f"Authored wall cell '{cell_name}' run_axis '{cell.run_axis}' does not match group "
                    f"'{cell.group_id}' run_axis '{owning_group.run_axis}'."
                )
        if cell.source_bucket not in allowed_buckets:
            issues.append(f"Authored wall cell '{cell_name}' has unsupported source bucket '{cell.source_bucket}'.")
        if cell.material_family not in allowed_materials:
            issues.append(f"Authored wall cell '{cell_name}' has unsupported material family '{cell.material_family}'.")
        if cell.normal_axis not in {"x", "y"}:
            issues.append(
                f"Authored wall cell '{cell_name}' has invalid normal_axis '{cell.normal_axis}'; expected 'x' or 'y'."
            )
        expected_run_axis = "y" if cell.normal_axis == "x" else "x" if cell.normal_axis == "y" else ""
        if cell.run_axis not in {"x", "y"}:
            issues.append(
                f"Authored wall cell '{cell_name}' has invalid run_axis '{cell.run_axis}'; expected 'x' or 'y'."
            )
        elif expected_run_axis and cell.run_axis != expected_run_axis:
            issues.append(
                f"Authored wall cell '{cell_name}' has run_axis '{cell.run_axis}' inconsistent with normal_axis "
                f"'{cell.normal_axis}'."
            )
        if cell.display_color_rgb is None:
            issues.append(f"Authored wall cell '{cell_name}' is missing canonical display_color_rgb metadata.")
        for field_name, value in (
            ("surface_u_origin_studs", cell.surface_u_origin_studs),
            ("surface_v_origin_studs", cell.surface_v_origin_studs),
        ):
            if value is None:
                issues.append(f"Authored wall cell '{cell_name}' is missing finite {field_name}.")
            elif not math.isfinite(float(value)):
                issues.append(f"Authored wall cell '{cell_name}' has non-finite {field_name}.")
        if cell.material_family in {"BRICK", "WOOD"} and not cell.visual_style:
            issues.append(f"Authored wall cell '{cell_name}' is missing canonical visual_style metadata.")
        if cell.visual_style is not None and cell.visual_style not in allowed_visual_styles:
            issues.append(f"Authored wall cell '{cell_name}' has unsupported visual_style '{cell.visual_style}'.")
        for field_name, vector in (
            ("min_studs", cell.min_studs),
            ("size_studs", cell.size_studs),
            ("max_studs", cell.max_studs),
        ):
            if vector is None:
                issues.append(f"Authored wall cell '{cell_name}' has malformed {field_name}.")
            elif any(not math.isfinite(float(component)) for component in vector):
                issues.append(f"Authored wall cell '{cell_name}' has non-finite {field_name}.")
        if cell.size_studs is not None and any(float(component) <= 0.0 for component in cell.size_studs):
            issues.append(f"Authored wall cell '{cell_name}' must have strictly positive size_studs.")
        if cell.size_studs is not None and cell.normal_axis in {"x", "y"}:
            axis_index = 0 if cell.normal_axis == "x" else 1
            if float(cell.size_studs[axis_index]) <= 0.0:
                issues.append(f"Authored wall cell '{cell_name}' must have positive normal-axis wall thickness.")
            if float(cell.size_studs[2]) <= 0.0:
                issues.append(f"Authored wall cell '{cell_name}' must have positive vertical wall height.")
            run_axis_index = 1 if cell.normal_axis == "x" else 0
            if float(cell.size_studs[run_axis_index]) + 1e-6 < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
                issues.append(
                    f"Authored wall cell '{cell_name}' run span is below {MIN_NON_THICKNESS_CELL_SPAN_STUDS:g} studs."
                )
            if float(cell.size_studs[2]) + 1e-6 < MIN_NON_THICKNESS_CELL_SPAN_STUDS:
                issues.append(
                    f"Authored wall cell '{cell_name}' Z span is below {MIN_NON_THICKNESS_CELL_SPAN_STUDS:g} studs."
                )
    authored_count = voxel_wall_facts.total_authored_cell_count
    texture_gate_failures: list[str] = []
    expected_equal_count_gates = (
        ("texture_contract_key_present_count", voxel_wall_facts.texture_contract_key_present_count),
        ("texture_projection_valid_count", voxel_wall_facts.texture_projection_valid_count),
        ("texture_image_period_contract_valid_count", voxel_wall_facts.texture_image_period_contract_valid_count),
        ("texture_face_axis_table_valid_count", voxel_wall_facts.texture_face_axis_table_valid_count),
        ("texture_studs_per_tile_valid_count", voxel_wall_facts.texture_studs_per_tile_valid_count),
        ("cells_with_surface_uv_origin_count", voxel_wall_facts.cells_with_surface_uv_origin_count),
    )
    for gate_name, gate_value in expected_equal_count_gates:
        if int(gate_value) != int(authored_count):
            texture_gate_failures.append(f"{gate_name}={gate_value}, expected {authored_count}")
    if voxel_wall_facts.cell_surface_uv_phase_consistency_max_delta_studs > 0.001:
        texture_gate_failures.append(
            "cell_surface_uv_phase_consistency_max_delta_studs="
            f"{voxel_wall_facts.cell_surface_uv_phase_consistency_max_delta_studs:.6f} > 0.001"
        )
    if voxel_wall_facts.texture_tile_scale_max_delta_studs > 0.001:
        texture_gate_failures.append(
            f"texture_tile_scale_max_delta_studs={voxel_wall_facts.texture_tile_scale_max_delta_studs:.6f} > 0.001"
        )
    if voxel_wall_facts.visible_texture_contract_cell_count != voxel_wall_facts.real_visible_cell_count or voxel_wall_facts.visible_texture_contract_cell_count != authored_count:
        texture_gate_failures.append(
            "visible_texture_contract_cell_count="
            f"{voxel_wall_facts.visible_texture_contract_cell_count}, visible={voxel_wall_facts.real_visible_cell_count}, payload={authored_count}"
        )
    zero_count_gates = (
        ("v3_visible_root_local_uv_object_count", voxel_wall_facts.v3_visible_root_local_uv_object_count),
        ("color_modulation_policy_invalid_count", voxel_wall_facts.color_modulation_policy_invalid_count),
        ("projection_classification_drift_count", voxel_wall_facts.projection_classification_drift_count),
        ("non_axis_aligned_plane_count", voxel_wall_facts.non_axis_aligned_plane_count),
        ("texture_face_uv_implementation_invalid_count", voxel_wall_facts.texture_face_uv_implementation_invalid_count),
        ("v3_material_style_preview_mismatch_count", voxel_wall_facts.v3_material_style_preview_mismatch_count),
        ("opening_bounds_off_grid_count", voxel_wall_facts.opening_bounds_off_grid_count),
        ("brick_opening_adjacent_non_grid_cell_count", voxel_wall_facts.brick_opening_adjacent_non_grid_cell_count),
    )
    for gate_name, gate_value in zero_count_gates:
        if int(gate_value) != 0:
            texture_gate_failures.append(f"{gate_name}={gate_value}, expected 0")
    if not voxel_wall_facts.texture_preview_payload_parity:
        texture_gate_failures.append("texture_preview_payload_parity=false")
    if not voxel_wall_facts.composite_box_face_order_probe_match:
        texture_gate_failures.append("composite_box_face_order_probe_match=false")
    if texture_gate_failures:
        issues.append("V3 material-style runtime appearance numeric gates failed: " + "; ".join(texture_gate_failures) + ".")
    return issues


def collect_validation_issues(facts: ValidationFacts) -> list[str]:
    issues: list[str] = []
    for collector in (
        _collect_transform_material_issues,
        _collect_destruction_export_readiness_issues,
        _collect_topology_contract_issues,
        _collect_facade_opening_issues,
        lambda current_facts: collect_service_roof_issues(
            current_facts,
            bounds_overlap_2d=_bounds_overlap_2d,
            bounds_overlap_3d=_bounds_overlap_3d,
        ) if _uses_legacy_collision_lane(current_facts) else [],
        _collect_service_entrance_issues,
        _collect_wave10_wave11_contract_issues,
        _collect_gameplay_budget_issues,
    ):
        issues.extend(collector(facts))
    return issues
