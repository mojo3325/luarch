from __future__ import annotations

from collections.abc import Callable

from .. import export_contract
from ..generator.building_layout import (
    ROOF_EXIT_SHELL_MIN_MARKER_COUNT,
    TERMINAL_PROFILE_ATTIC_OPEN,
    TERMINAL_PROFILE_FULL_ROOM,
    TERMINAL_PROFILE_STAIR_HEAD,
    _spatial_plan,
    _roof_pipe_run_safe_strip_issue,
    _roof_requires_pipe_run,
    _wall_service_pipe_band,
)
from ..generator import building_roof_services
from ..generator.building_support import object_local_bounds
from .validation_facts import SERVICE_HEAVY_WALL_PIPE_PRESET_IDS, ValidationFacts


ROLE_ROOF_EXIT_DOOR = export_contract.ROLE_ROOF_EXIT_DOOR
ROLE_ROOF_EXIT_PLATFORM = export_contract.ROLE_ROOF_EXIT_PLATFORM
ROLE_ROOF_EXIT_SHELL = export_contract.ROLE_ROOF_EXIT_SHELL
ROLE_FLOOR_BLOCKER = export_contract.ROLE_FLOOR_BLOCKER
ROLE_PARTITION = export_contract.ROLE_PARTITION

ATTIC_OPENING_COLLISION_WARNING_PREFIX = "Roof-access opening collision warning:"


def _roof_hvac_feasible(facts: ValidationFacts) -> bool:
    spec = facts.effective_spec
    if not bool(spec.stair_core.enabled):
        return False
    spatial_plan = _spatial_plan(spec)
    anchor = spatial_plan.service_anchor
    if anchor is None:
        return False
    width = min(2.35, max(1.7, spec.width * 0.16))
    depth = min(1.48, max(1.08, spec.depth * 0.13))
    base_x, base_y = building_roof_services._primary_roof_service_point(
        spec,
        spatial_plan,
        anchor,
        tangent_offset=0.0,
        inward_offset=0.0,
    )
    return (
        building_roof_services._plan_roof_service_footprint(
            spec,
            spatial_plan,
            anchor,
            x=base_x,
            y=base_y,
            footprint_x=width,
            footprint_y=depth,
            margin=0.2,
        )
        is not None
    )


def _bounds_close(
    a: tuple[float, float, float, float, float, float] | list[float] | None,
    b: tuple[float, float, float, float, float, float] | list[float] | None,
    *,
    tolerance: float = 0.18,
) -> bool:
    if a is None or b is None:
        return False
    return all(abs(float(left) - float(right)) <= tolerance for left, right in zip(a, b))


def _bounds_overlap_xy(
    a: tuple[float, float, float, float, float, float] | list[float] | None,
    b: tuple[float, float, float, float, float, float] | list[float] | None,
    *,
    tolerance: float = 1e-4,
) -> bool:
    if a is None or b is None:
        return False
    return (
        max(float(a[0]), float(b[0])) < min(float(a[1]), float(b[1])) + tolerance
        and max(float(a[2]), float(b[2])) < min(float(a[3]), float(b[3])) + tolerance
    )


def _bounds_within_xy(
    inner: tuple[float, float, float, float, float, float] | list[float] | None,
    outer: tuple[float, float, float, float, float, float] | list[float] | None,
    *,
    tolerance: float = 0.12,
) -> bool:
    if inner is None or outer is None:
        return False
    return (
        float(inner[0]) >= float(outer[0]) - tolerance
        and float(inner[1]) <= float(outer[1]) + tolerance
        and float(inner[2]) >= float(outer[2]) - tolerance
        and float(inner[3]) <= float(outer[3]) + tolerance
    )


def _overlap_extent(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(float(a1), float(b1)) - max(float(a0), float(b0))


def _bounds_intrude_3d(
    a: tuple[float, float, float, float, float, float] | list[float] | None,
    b: tuple[float, float, float, float, float, float] | list[float] | None,
    *,
    planar_tolerance: float = 0.02,
    vertical_tolerance: float = 0.04,
) -> bool:
    if a is None or b is None:
        return False
    return (
        _overlap_extent(a[0], a[1], b[0], b[1]) > planar_tolerance
        and _overlap_extent(a[2], a[3], b[2], b[3]) > planar_tolerance
        and _overlap_extent(a[4], a[5], b[4], b[5]) > vertical_tolerance
    )


def _inset_xy_bounds(
    bounds: tuple[float, float, float, float, float, float] | list[float] | None,
    *,
    inset: float,
) -> tuple[float, float, float, float, float, float] | None:
    if bounds is None:
        return None
    x0, x1, y0, y1, z0, z1 = (float(value) for value in bounds)
    max_inset_x = max(0.0, (x1 - x0) / 2 - 1e-4)
    max_inset_y = max(0.0, (y1 - y0) / 2 - 1e-4)
    resolved_inset = min(float(inset), max_inset_x, max_inset_y)
    return (x0 + resolved_inset, x1 - resolved_inset, y0 + resolved_inset, y1 - resolved_inset, z0, z1)


def _roof_access_opening_collision_warnings(facts: ValidationFacts) -> list[str]:
    terminal_profile = str(facts.terminal_profile).upper()
    if terminal_profile != TERMINAL_PROFILE_ATTIC_OPEN or facts.contract_roof_opening_bounds is None:
        return []
    opening_bounds = facts.contract_roof_opening_bounds
    opening_width = float(opening_bounds[1]) - float(opening_bounds[0])
    opening_depth = float(opening_bounds[3]) - float(opening_bounds[2])
    keepout_inset = min(0.18, max(0.08, min(opening_width, opening_depth) * 0.16))
    shell_keepout_bounds = _inset_xy_bounds(opening_bounds, inset=keepout_inset)
    if shell_keepout_bounds is None:
        shell_keepout_bounds = opening_bounds
    warnings: list[str] = []
    seen_sources: set[tuple[str, str]] = set()
    for marker in facts.marker_facts.collision_markers:
        role = str(marker.get("tbg_runtime_role", ""))
        if role not in {ROLE_FLOOR_BLOCKER, ROLE_ROOF_EXIT_PLATFORM, ROLE_PARTITION, ROLE_ROOF_EXIT_SHELL}:
            continue
        target_bounds = shell_keepout_bounds if role == ROLE_ROOF_EXIT_SHELL else opening_bounds
        marker_bounds = object_local_bounds(facts.root_obj, marker)
        if not _bounds_intrude_3d(target_bounds, marker_bounds):
            continue
        source_name = str(marker.get("tbg_runtime_source_name", "")) or str(getattr(marker, "name", ""))
        dedupe_key = (role, source_name)
        if dedupe_key in seen_sources:
            continue
        seen_sources.add(dedupe_key)
        warnings.append(
            f"{ATTIC_OPENING_COLLISION_WARNING_PREFIX} attic throat is intruded by {role} marker '{source_name}'."
        )
    return warnings


def _top_room_floor_supports(
    floor_bounds: tuple[float, float, float, float, float, float] | list[float] | None,
    room_bounds: tuple[float, float, float, float, float, float] | list[float] | None,
) -> bool:
    if floor_bounds is None or room_bounds is None:
        return False
    contains_2d = (
        float(floor_bounds[0]) <= float(room_bounds[0]) + 0.04
        and float(floor_bounds[1]) >= float(room_bounds[1]) - 0.04
        and float(floor_bounds[2]) <= float(room_bounds[2]) + 0.04
        and float(floor_bounds[3]) >= float(room_bounds[3]) - 0.04
    )
    top_alignment = abs(float(floor_bounds[5]) - float(room_bounds[4])) <= 0.12
    return contains_2d and top_alignment


def _roof_exit_full_room_cap_overlap_issue(facts: ValidationFacts) -> str | None:
    shell_marker_bounds: list[tuple[str, tuple[float, float, float, float, float, float]]] = []
    for marker in facts.marker_facts.collision_markers:
        if str(marker.get("tbg_runtime_role", "")) != ROLE_ROOF_EXIT_SHELL:
            continue
        source_name = str(marker.get("tbg_runtime_source_name", "")) or str(getattr(marker, "name", ""))
        shell_marker_bounds.append((source_name, object_local_bounds(facts.root_obj, marker)))
    if not shell_marker_bounds:
        return None
    roof_cap_bounds = [bounds for source_name, bounds in shell_marker_bounds if "RoofExit_Roof" in source_name]
    wall_bounds = [bounds for source_name, bounds in shell_marker_bounds if "RoofExit_Roof" not in source_name]
    if not roof_cap_bounds or not wall_bounds:
        return None
    cap_bottom_z = min(float(bounds[4]) for bounds in roof_cap_bounds)
    wall_top_z = max(float(bounds[5]) for bounds in wall_bounds)
    if cap_bottom_z + 0.02 < wall_top_z:
        return "FULL_ROOM roof cap intrudes into roof-exit shell walls; walls must terminate below the cap."
    return None


def collect_collision_runtime_roof_service_issues(
    facts: ValidationFacts,
    *,
    has_named_door_leaf: Callable[..., bool],
) -> list[str]:
    issues: list[str] = []
    walkable_roof = facts.roof_access_enabled
    terminal_profile = str(facts.terminal_profile).upper()
    profile_attic_open = terminal_profile == TERMINAL_PROFILE_ATTIC_OPEN
    profile_full_room = terminal_profile == TERMINAL_PROFILE_FULL_ROOM
    profile_stair_head = terminal_profile == TERMINAL_PROFILE_STAIR_HEAD
    profile_known = profile_attic_open or profile_full_room or profile_stair_head
    if not walkable_roof:
        if (
            facts.summary.roof_exit_bounds is not None
            or sum(1 for child in facts.door_leaves if child.get("tbg_roof_exit_door")) > 0
            or has_named_door_leaf(facts.mesh_children, "Door_RoofExit", roof_exit=True)
            or facts.marker_facts.role_counts.get(ROLE_ROOF_EXIT_PLATFORM, 0) > 0
            or facts.marker_facts.role_counts.get(ROLE_ROOF_EXIT_SHELL, 0) > 0
            or facts.authored_roof_exit_bounds is not None
            or facts.top_room_floor_bounds is not None
        ):
            issues.append("Non-walkable roofs should not author roof-exit door, platform, shell, or bounds.")
        return issues
    if not profile_known:
        issues.append("Walkable roof is missing a recognized planner-owned terminal_profile contract.")
    if not facts.effective_spec.stair_core.enabled:
        return issues

    role_counts = facts.marker_facts.role_counts
    roof_exit_door_count = sum(1 for child in facts.door_leaves if child.get("tbg_roof_exit_door"))
    if facts.preset_id == "under_construction":
        if roof_exit_door_count > 0 or has_named_door_leaf(facts.mesh_children, "Door_RoofExit", roof_exit=True):
            issues.append("Under-construction shell should not generate a roof-exit door leaf.")
        if (
            role_counts.get(ROLE_ROOF_EXIT_PLATFORM, 0) > 0
            or role_counts.get(ROLE_ROOF_EXIT_SHELL, 0) > 0
            or role_counts.get(ROLE_ROOF_EXIT_DOOR, 0) > 0
        ):
            issues.append("Under-construction shell should not export roof-exit runtime blockers.")
        return issues
    if profile_attic_open or profile_stair_head:
        if roof_exit_door_count > 0 or has_named_door_leaf(facts.mesh_children, "Door_RoofExit", roof_exit=True):
            issues.append("ATTIC_OPEN/STAIR_HEAD roof terminals must not author a Door_RoofExit leaf.")
    elif profile_full_room:
        if roof_exit_door_count <= 0:
            issues.append("Stair-core building is missing its roof-exit door leaf.")
        elif not has_named_door_leaf(facts.mesh_children, "Door_RoofExit", roof_exit=True):
            issues.append("Roof-exit door leaf is missing the stable Door_RoofExit render contract.")
    elif roof_exit_door_count > 0 or has_named_door_leaf(facts.mesh_children, "Door_RoofExit", roof_exit=True):
        issues.append("Unknown terminal profile authored a Door_RoofExit leaf.")
    if role_counts.get(ROLE_ROOF_EXIT_PLATFORM, 0) <= 0:
        issues.append("Primitive collision is missing the roof-exit arrival platform blocker.")
    if profile_attic_open:
        minimum_shell_count = 3
    elif profile_stair_head:
        minimum_shell_count = 5
    else:
        minimum_shell_count = ROOF_EXIT_SHELL_MIN_MARKER_COUNT
    if role_counts.get(ROLE_ROOF_EXIT_SHELL, 0) < minimum_shell_count:
        issues.append("Primitive collision is missing one or more roof-exit shell blockers.")
    if role_counts.get(ROLE_ROOF_EXIT_DOOR, 0) > 0:
        issues.append("Roof-exit door collision still depends on a runtime blocker instead of the render door leaf.")
    if facts.contract_roof_exit_bounds is None:
        issues.append("Walkable roof lost its contract-owned roof-exit bounds.")
    elif facts.summary.roof_exit_bounds is None:
        issues.append("Roof-exit summary bounds are missing from the contract-owned top room.")
    elif not _bounds_close(facts.summary.roof_exit_bounds, facts.contract_roof_exit_bounds):
        issues.append("Stored roof-exit bounds drifted away from the shared top-room contract.")
    if facts.authored_roof_exit_bounds is None:
        issues.append("Roof-exit shell geometry is missing from the authored top-room package.")
    elif facts.contract_roof_exit_bounds is not None:
        authored_bounds = facts.authored_roof_exit_bounds
        contract_bounds = facts.contract_roof_exit_bounds
        if profile_full_room:
            if not _bounds_close(authored_bounds, contract_bounds):
                issues.append("Authored roof-exit shell drifted away from the shared top-room footprint.")
        else:
            contract_opening_bounds = facts.contract_roof_opening_bounds
            if contract_opening_bounds is None:
                issues.append("Open roof terminal is missing planner-owned roof opening bounds.")
            else:
                if profile_attic_open:
                    if not _bounds_overlap_xy(authored_bounds, contract_bounds, tolerance=0.02):
                        issues.append("ATTIC_OPEN roof terminal shell does not overlap the planner-owned attic support envelope.")
                else:
                    if not _bounds_overlap_xy(authored_bounds, contract_opening_bounds, tolerance=0.02):
                        issues.append("Open roof terminal shell does not overlap the planner-owned roof opening footprint.")
                    authored_center_x = (float(authored_bounds[0]) + float(authored_bounds[1])) / 2
                    opening_center_x = (float(contract_opening_bounds[0]) + float(contract_opening_bounds[1])) / 2
                    if abs(authored_center_x - opening_center_x) > 0.2:
                        issues.append("Open roof terminal shell drifted away from planner opening centerline.")
            if not profile_attic_open and not _bounds_within_xy(authored_bounds, contract_bounds, tolerance=0.22):
                issues.append("Open roof terminal shell escaped the planner-owned terminal envelope.")
            authored_base_z = float(authored_bounds[4])
            contract_base_z = float(contract_bounds[4])
            if abs(authored_base_z - contract_base_z) > 0.22:
                issues.append("Open roof terminal shell base drifted away from planner-owned top-floor support elevation.")
    if facts.top_room_floor_bounds is None:
        issues.append("Walkable roof is missing planner-owned top-arrival/support floor geometry.")
    elif not _top_room_floor_supports(
        facts.top_room_floor_bounds,
        facts.contract_roof_exit_bounds,
    ):
        issues.append("Roof-exit room is missing a real supported top-room floor.")
    if profile_full_room:
        cap_overlap_issue = _roof_exit_full_room_cap_overlap_issue(facts)
        if cap_overlap_issue is not None:
            issues.append(cap_overlap_issue)
    issues.extend(_roof_access_opening_collision_warnings(facts))
    return issues


def collect_service_roof_issues(
    facts: ValidationFacts,
    *,
    bounds_overlap_2d: Callable[[list[float] | tuple[float, ...], list[float] | tuple[float, ...]], bool],
    bounds_overlap_3d: Callable[[list[float] | tuple[float, ...], list[float] | tuple[float, ...]], bool],
) -> list[str]:
    issues: list[str] = []
    requires_wall_service_pipes = facts.preset_id in SERVICE_HEAVY_WALL_PIPE_PRESET_IDS
    walkable_roof = facts.roof_access_enabled
    drainpipes = facts.summary.services.drainpipes
    primary_risers = [pipe for pipe in drainpipes if pipe.primary]
    wall_pipe_parts = facts.summary.services.blocking_wall_pipe_parts
    roof_service = facts.summary.services.roof_items
    roof_hvac = [item for item in roof_service if item.role == "hvac"]
    roof_vents = [item for item in roof_service if item.role == "vent"]
    roof_pipe_runs = [item for item in roof_service if item.role == "roof_pipe_run"]
    window_bounds = facts.summary.windows.bounds

    if facts.preset_id == "under_construction" and drainpipes:
        issues.append("Under-construction shell should not spawn facade service pipes or clamps.")

    if (
        walkable_roof
        and facts.effective_spec.roof_prop_profile != "NONE"
        and not roof_hvac
        and _roof_hvac_feasible(facts)
    ):
        issues.append("Expected one clean rooftop HVAC family, but no main HVAC unit was generated.")
    if len(roof_hvac) > 1:
        issues.append(f"Rooftop HVAC family spawned too many main units: {len(roof_hvac)} > 1.")
    if len(roof_vents) > 1:
        issues.append(f"Rooftop service spawned too many subordinate vents: {len(roof_vents)} > 1.")
    if any(item.role == "service_box" for item in roof_service):
        issues.append("Legacy roof service boxes are still present in the rooftop HVAC family.")
    if requires_wall_service_pipes and not drainpipes:
        issues.append("Building has no generated wall service pipes.")
    if drainpipes and not any(pipe.visible for pipe in drainpipes):
        issues.append("Building has wall pipes, but no clearly visible primary pipe.")
    if requires_wall_service_pipes and not primary_risers:
        issues.append("Building is missing a primary wall-mounted service pipe.")
    for pipe_part in wall_pipe_parts:
        for window in window_bounds:
            if bounds_overlap_3d(pipe_part.bounds, window.bounds):
                issues.append(f"Wall pipe part '{pipe_part.part}' overlaps a facade window opening.")
                break
        else:
            continue
        break
    for pipe_part in wall_pipe_parts:
        for balcony in facts.summary.balconies:
            if bounds_overlap_3d(pipe_part.bounds, balcony.bounds):
                issues.append(f"Wall pipe part '{pipe_part.part}' intrudes into balcony fighting space.")
                break
        else:
            continue
        break

    if walkable_roof and facts.effective_spec.roof_prop_profile == "RESIDENTIAL":
        flavor_props = [item for item in roof_service if item.roof_flavor]
        if len(flavor_props) > 1:
            issues.append(f"Residential roof flavour prop budget exceeded: {len(flavor_props)} tagged parts.")

    anchor_ids = {item.anchor_id for item in drainpipes + tuple(roof_service) if item.anchor_id}
    if walkable_roof and roof_service and not any(
        item.anchor_id
        for item in roof_service
        if item.role in {"hvac", "vent", "roof_pipe_run", "flavor_antenna", "flavor_dish"}
    ):
        issues.append("Roof-service props are missing anchor metadata.")
    if len(anchor_ids) > 1:
        issues.append("Roof-service and wall-pipe geometry disagree on the chosen service anchor.")
    elif anchor_ids and facts.service_anchor_id and next(iter(anchor_ids)) != facts.service_anchor_id:
        issues.append("Roof-service and wall-pipe geometry drifted away from the shared service anchor.")
    heavy_roof_service = [item for item in roof_service if item.role in {"hvac", "vent", "roof_pipe_run"}]
    if not walkable_roof and facts.summary.roof_exit_bounds:
        issues.append("Non-walkable ordinary roof still serializes roof-exit bounds.")
    if facts.summary.roof_exit_bounds:
        for item in heavy_roof_service:
            if bounds_overlap_2d(item.bounds, facts.summary.roof_exit_bounds):
                if item.role == "roof_pipe_run":
                    issues.append("Roof pipe run intrudes into the roof-exit room.")
                else:
                    issues.append("Heavy roof service intrudes into the roof-exit room.")
                break

    if (
        walkable_roof
        and facts.effective_spec.roof_prop_profile != "NONE"
        and _roof_requires_pipe_run(facts.effective_spec)
        and building_roof_services._roof_pipe_run_feasible(facts.effective_spec, _spatial_plan(facts.effective_spec))
        and not roof_pipe_runs
    ):
        issues.append("Large roof is missing its authored horizontal roof-pipe run.")
    for run in roof_pipe_runs:
        edge_inset = max(0.01, run.edge_inset or 0.0)
        strip_issue = _roof_pipe_run_safe_strip_issue(
            facts.effective_spec,
            side=run.side,
            edge_inset=edge_inset,
            bounds=run.bounds,
            width=facts.width,
            depth=facts.depth,
        )
        if strip_issue == "missing_metadata":
            issues.append("Roof pipe run is missing safe-strip metadata.")
            break
        if strip_issue == "outside_strip":
            issues.append("Roof pipe run leaks outside the safe roof strip.")
            break
        if strip_issue == "drifted_strip":
            issues.append("Roof pipe run drifted away from its intended roof strip.")
            break

    if primary_risers:
        pipe_band = _wall_service_pipe_band(facts.effective_spec, entrance_profile=facts.entrance_profile)
        min_z = float(primary_risers[0].bounds[4])
        max_z = float(primary_risers[0].bounds[5])
        if min_z < float(pipe_band["validation_min_bottom"]):
            issues.append("Primary wall pipe cluster sits too low on the facade.")
        if min_z > float(pipe_band["validation_max_bottom"]):
            issues.append("Primary wall pipe cluster is floating too close to the roofline.")
        if max_z - min_z > float(pipe_band["validation_max_span"]):
            issues.append("Primary wall pipe still reads like an overlong facade riser.")
        if max_z - min_z < float(pipe_band["validation_min_span"]):
            issues.append("Primary wall pipe cluster became too short to read clearly.")
        if max_z < float(pipe_band["validation_expected_top"]):
            issues.append("Primary wall pipe is not reaching the upper facade service band.")
        if facts.summary.roof_exit_bounds and bounds_overlap_2d(primary_risers[0].bounds, facts.summary.roof_exit_bounds):
            issues.append("Primary wall pipe intrudes into the roof-exit room.")
    return issues
