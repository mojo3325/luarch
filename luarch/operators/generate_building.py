from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import traceback

import bpy
from mathutils import Vector

from .. import constants, export_contract, metadata
from ..generator.building import (
    create_build_finalize_sequence,
    create_build_preview_sequence,
    plan_building,
)
from ..generator.building_layout import _terrace_transition_contract
from ..generator.building_support import composite_part_root_local_bounds
from ..generator.specs import building_spec_from_mapping, building_spec_from_settings
from ..services import build_scheduler, cleanup, selected_building_tuning


ROW_Y_TOLERANCE = 0.25
ROW_Z_TOLERANCE = 0.25
ROW_SPACING = 2.0
_FRESH_FAILURE_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "tasks"
    / "voxel_wall_cells_v3_emergency_single_truth_smoke_20260425"
)
_FRESH_FAILURE_TRACEBACK_DIR = _FRESH_FAILURE_ARTIFACT_ROOT / "failure_tracebacks"
_FRESH_FAILURE_RUN_LOG = _FRESH_FAILURE_ARTIFACT_ROOT / "run_log.md"
_FRESH_FAILURE_ISSUES_LEDGER = _FRESH_FAILURE_ARTIFACT_ROOT / "issues_ledger.md"
_FRESH_FAILURE_MATRIX = _FRESH_FAILURE_ARTIFACT_ROOT / "matrix.json"


def _scene_by_name(scene_name: str):
    scene_name = str(scene_name or "").strip()
    if not scene_name:
        return None
    return bpy.data.scenes.get(scene_name)


def _set_generate_status(scene_name: str, status: str) -> None:
    scene = _scene_by_name(scene_name)
    if scene is None:
        return
    selected_building_tuning._set_root_status(scene, status, force_redraw=True)


def _generate_failure_status(message: str) -> str:
    detail = str(message or "").strip()
    recent_errors = build_scheduler.recent_errors()
    if recent_errors:
        latest = str(recent_errors[-1] or "").strip()
        if latest and latest != detail:
            detail = f"{detail} [{latest}]" if detail else latest
    return f"Generate failed: {detail or 'Unknown scheduler failure.'}"


def _continued_job(*, label: str, execute, delay_seconds: float = 0.0, dedupe_key: str = "", replace_dedupe: bool = False, message: str = ""):
    return build_scheduler.JobContinuation(
        label=label,
        execute=execute,
        delay_seconds=delay_seconds,
        dedupe_key=dedupe_key,
        replace_dedupe=replace_dedupe,
        message=message,
    )


def _fresh_failure_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fresh_failure_slug(value: object) -> str:
    text = str(value or "unknown").strip() or "unknown"
    cleaned = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in text)
    return cleaned[:80] or "unknown"


def _fresh_failure_root_name(root_obj=None, *, fallback: str = "") -> str:
    try:
        root_name = str(getattr(root_obj, "name", "") or "")
    except ReferenceError:
        root_name = ""
    return root_name or str(fallback or "unknown")


def _fresh_failure_artifact_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path(__file__).resolve().parents[1]))
    except ValueError:
        return str(path)


def _fresh_failure_identity(spec=None, root_obj=None, *, root_name_override: str = "") -> dict[str, object]:
    root_name = _fresh_failure_root_name(root_obj, fallback=root_name_override)
    preset = str(getattr(spec, "preset_id", "") or "")
    seed = getattr(spec, "seed", "")
    try:
        root_exists = root_obj is not None and getattr(root_obj, "name", "") in bpy.data.objects
    except ReferenceError:
        root_exists = False
    if root_exists:
        try:
            effective_spec = metadata.read_effective_spec_dict(root_obj, allow_legacy_dirty=True) or {}
        except Exception:
            effective_spec = {}
        preset = str(effective_spec.get("preset_id") or preset or "")
        seed = effective_spec.get("seed", seed)
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = str(seed or "")
    return {
        "preset": preset or "unknown",
        "seed": seed,
        "root_name": root_name,
    }


def _fresh_failure_prepare_artifacts() -> None:
    _FRESH_FAILURE_TRACEBACK_DIR.mkdir(parents=True, exist_ok=True)
    if not _FRESH_FAILURE_RUN_LOG.exists():
        _FRESH_FAILURE_RUN_LOG.write_text("# Fresh Generate Failure Run Log\n\n", encoding="utf-8")
    if not _FRESH_FAILURE_ISSUES_LEDGER.exists():
        _FRESH_FAILURE_ISSUES_LEDGER.write_text("# Fresh Generate Issues Ledger\n\n", encoding="utf-8")
    if not _FRESH_FAILURE_MATRIX.exists():
        _FRESH_FAILURE_MATRIX.write_text("[]\n", encoding="utf-8")


def _fresh_failure_append_markdown(path: Path, text: str) -> None:
    _fresh_failure_prepare_artifacts()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _fresh_failure_append_matrix(row: dict[str, object]) -> None:
    _fresh_failure_prepare_artifacts()
    try:
        existing = json.loads(_FRESH_FAILURE_MATRIX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = []
    if not isinstance(existing, list):
        existing = []
    existing.append(row)
    _FRESH_FAILURE_MATRIX.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _capture_fresh_failure_traceback(
    *,
    stage: str,
    failure_class: str,
    spec=None,
    root_obj=None,
    root_name_override: str = "",
    exc: BaseException,
) -> str:
    try:
        _fresh_failure_prepare_artifacts()
        identity = _fresh_failure_identity(spec, root_obj, root_name_override=root_name_override)
        timestamp = _fresh_failure_timestamp()
        file_name = (
            f"{timestamp.replace(':', '')}_"
            f"{_fresh_failure_slug(identity['preset'])}_"
            f"{_fresh_failure_slug(identity['seed'])}_"
            f"{_fresh_failure_slug(identity['root_name'])}_"
            f"{_fresh_failure_slug(stage)}.txt"
        )
        path = _FRESH_FAILURE_TRACEBACK_DIR / file_name
        traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        path.write_text(
            "\n".join(
                (
                    f"timestamp: {timestamp}",
                    f"preset: {identity['preset']}",
                    f"seed: {identity['seed']}",
                    f"root_name: {identity['root_name']}",
                    f"stage: {stage}",
                    f"failure_class: {failure_class}",
                    "",
                    traceback_text,
                )
            ),
            encoding="utf-8",
        )
        return _fresh_failure_artifact_path(path)
    except Exception as artifact_exc:
        print(f"TBG fresh-generate failure traceback capture failed: {artifact_exc}")
        return ""


def _record_fresh_failure_pre_cleanup_issue(
    *,
    stage: str,
    failure_class: str,
    spec=None,
    root_obj=None,
    root_name_override: str = "",
    issue: str,
) -> None:
    try:
        identity = _fresh_failure_identity(spec, root_obj, root_name_override=root_name_override)
        timestamp = _fresh_failure_timestamp()
        _fresh_failure_append_markdown(
            _FRESH_FAILURE_ISSUES_LEDGER,
            (
                f"## {timestamp} — {failure_class} before cleanup\n\n"
                f"- preset: `{identity['preset']}`\n"
                f"- seed: `{identity['seed']}`\n"
                f"- root_name: `{identity['root_name']}`\n"
                f"- stage: `{stage}`\n"
                f"- issue: {issue}\n"
                f"- cleanup_result: pending\n\n"
            ),
        )
    except Exception as artifact_exc:
        print(f"TBG fresh-generate pre-cleanup issue capture failed: {artifact_exc}")


def _scheduler_evidence(*, scheduler_job_id: int | None = None, scheduler_label: str = "") -> dict[str, object]:
    job_status = ""
    job_message = ""
    if scheduler_job_id is not None:
        try:
            job_status, job_message = build_scheduler.job_status(int(scheduler_job_id))
        except Exception as exc:
            job_status = "capture_failed"
            job_message = str(exc)
    return {
        "scheduler_label": str(scheduler_label or ""),
        "scheduler_job_id": int(scheduler_job_id) if scheduler_job_id is not None else None,
        "scheduler_job_status": job_status,
        "scheduler_job_message": job_message,
        "scheduler_recent_errors": list(build_scheduler.recent_errors()),
        "scheduler_has_pending_jobs": bool(build_scheduler.has_pending_jobs()),
    }


def _record_fresh_failure_artifact(
    *,
    stage: str,
    failure_class: str,
    spec=None,
    root_obj=None,
    root_name_override: str = "",
    traceback_path: str = "",
    first_contract_issue: str = "",
    contract_issues: tuple[str, ...] = (),
    cleanup_result: str = "",
    operator_status: str = "",
    scheduler_job_id: int | None = None,
    scheduler_label: str = "",
    failure_message: str = "",
) -> None:
    try:
        identity = _fresh_failure_identity(spec, root_obj, root_name_override=root_name_override)
        timestamp = _fresh_failure_timestamp()
        evidence = _scheduler_evidence(scheduler_job_id=scheduler_job_id, scheduler_label=scheduler_label)
        row: dict[str, object] = {
            "timestamp": timestamp,
            "preset": identity["preset"],
            "seed": identity["seed"],
            "root_name": identity["root_name"],
            "stage": str(stage),
            "failure_class": str(failure_class),
            "traceback_path": str(traceback_path or ""),
            "first_contract_issue": str(first_contract_issue or ""),
            "contract_issues": list(contract_issues),
            "cleanup_result": str(cleanup_result or ""),
            "operator_status": str(operator_status or ""),
            "failure_message": str(failure_message or ""),
            **evidence,
        }
        _fresh_failure_append_matrix(row)
        _fresh_failure_append_markdown(
            _FRESH_FAILURE_RUN_LOG,
            (
                f"- {timestamp} `{failure_class}` stage=`{stage}` preset=`{identity['preset']}` "
                f"seed=`{identity['seed']}` root=`{identity['root_name']}` "
                f"traceback=`{traceback_path or ''}` issue=`{first_contract_issue or ''}` "
                f"cleanup=`{cleanup_result or ''}` operator_status=`{operator_status or ''}`\n"
            ),
        )
        _fresh_failure_append_markdown(
            _FRESH_FAILURE_ISSUES_LEDGER,
            (
                f"## {timestamp} — {failure_class}\n\n"
                f"- preset: `{identity['preset']}`\n"
                f"- seed: `{identity['seed']}`\n"
                f"- root_name: `{identity['root_name']}`\n"
                f"- stage: `{stage}`\n"
                f"- traceback_path: `{traceback_path or ''}`\n"
                f"- first_contract_issue: {first_contract_issue or ''}\n"
                f"- cleanup_result: {cleanup_result or ''}\n"
                f"- operator_status: {operator_status or ''}\n"
                f"- scheduler_label: `{evidence['scheduler_label']}`\n"
                f"- scheduler_job_status: `{evidence['scheduler_job_status']}`\n"
                f"- scheduler_recent_errors: `{evidence['scheduler_recent_errors']}`\n"
                f"- failure_message: {failure_message or ''}\n\n"
            ),
        )
    except Exception as artifact_exc:
        print(f"TBG fresh-generate failure artifact capture failed: {artifact_exc}")


def _is_top_level_building_root(scene, obj) -> bool:
    if not _is_tbg_placement_obstacle(obj):
        return False
    top_level = {collection.name for collection in scene.collection.children}
    return any(collection.name in top_level for collection in obj.users_collection)


def _is_tbg_root_name(name: str) -> bool:
    name = str(name or "")
    return name.startswith(f"{constants.ROOT_COLLECTION_PREFIX}_") and name.endswith("_ROOT")


def _is_tbg_collection_name(name: str) -> bool:
    name = str(name or "")
    return name == constants.ROOT_COLLECTION_PREFIX or name.startswith(f"{constants.ROOT_COLLECTION_PREFIX}_")


def _is_tbg_placement_obstacle(obj) -> bool:
    if obj is None:
        return False
    if bool(obj.get(constants.ROOT_OBJECT_KEY)):
        return True
    if bool(obj.get("tbg_edit_mode_dirty")) or obj.get("tbg_edit_spec_json") is not None:
        return True
    if _is_tbg_root_name(getattr(obj, "name", "")):
        return True
    return getattr(obj, "parent", None) is None and any(
        _is_tbg_collection_name(getattr(collection, "name", "")) for collection in getattr(obj, "users_collection", ())
    )


def _spec_width_for_root(root) -> float | None:
    spec = metadata.read_effective_spec_dict(root, allow_legacy_dirty=True)
    if not spec:
        return None
    try:
        resolved = building_spec_from_mapping(spec, building_id=None, origin=(0.0, 0.0, 0.0))
    except Exception:
        return None
    return float(resolved.width) * float(getattr(resolved, "world_scale", 1.0))


def _object_hierarchy_world_bounds(root) -> tuple[float, float, float, float, float, float] | None:
    candidates = [root, *tuple(getattr(root, "children_recursive", ()))]
    points: list[Vector] = []
    for obj in candidates:
        if obj is None or obj.name not in bpy.data.objects:
            continue
        bound_box = getattr(obj, "bound_box", None)
        if not bound_box or len(bound_box) != 8:
            continue
        matrix_world = getattr(obj, "matrix_world", None)
        if matrix_world is None:
            continue
        points.extend(matrix_world @ Vector(corner) for corner in bound_box)
    if not points:
        return None
    return (
        min(point.x for point in points),
        max(point.x for point in points),
        min(point.y for point in points),
        max(point.y for point in points),
        min(point.z for point in points),
        max(point.z for point in points),
    )


def _right_edge_for_root(root) -> float:
    spec_width = _spec_width_for_root(root)
    if spec_width is not None and spec_width > 1e-4:
        return float(root.location.x) + float(spec_width) / 2.0
    bounds = _object_hierarchy_world_bounds(root)
    if bounds is not None:
        return float(bounds[1])
    return float(root.location.x) + 4.0


def _visible_v3_wall_counts(root_obj) -> tuple[int, int]:
    visible_object_count = 0
    visible_composite_cell_count = 0
    for child in tuple(getattr(root_obj, "children_recursive", ())):
        if child is None or child.name not in bpy.data.objects or child.type != "MESH":
            continue
        if str(child.get("tbg_section_bucket", "") or "") not in export_contract.VOXEL_WALL_SOURCE_BUCKETS:
            continue
        if str(child.get("tbg_wall_emit_owner", "") or "") != "occupancy_v3":
            continue
        if str(child.get("tbg_wall_payload_kind", "") or "") != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_KIND:
            continue
        if str(child.get("tbg_wall_payload_version", "") or "") != export_contract.AUTHORED_WALL_CELLS_PAYLOAD_VERSION:
            continue
        visible_object_count += 1
        visible_composite_cell_count += len(composite_part_root_local_bounds(root_obj, child))
    return visible_object_count, visible_composite_cell_count


def _fresh_generate_contract_issues(root_obj) -> tuple[str, ...]:
    issues: list[str] = []
    if root_obj is None or root_obj.name not in bpy.data.objects:
        return ("generated root no longer exists",)
    if not bool(root_obj.get(constants.ROOT_OBJECT_KEY)):
        issues.append("missing tbg_is_root")
    if bool(root_obj.get("tbg_edit_mode_dirty")):
        issues.append("still marked tbg_edit_mode_dirty")
    if not root_obj.get(constants.SPEC_JSON_KEY):
        issues.append("missing tbg_spec_json")
    if not root_obj.get(constants.GENERATION_SUMMARY_KEY):
        issues.append("missing generation summary")
    if not root_obj.get(constants.FINAL_SECTION_REGISTRY_KEY):
        issues.append("missing final section registry")
    try:
        payload = metadata.read_voxel_wall_occupancy_payload(root_obj, strict=True)
    except Exception as exc:
        issues.append(f"invalid V3 payload: {exc}")
        payload = {}
    payload_cell_count = int(payload.get("authored_cell_count", 0) or 0) if isinstance(payload, dict) else 0
    if payload_cell_count <= 0:
        issues.append("missing authored wall cells")
    visible_object_count, visible_cell_count = _visible_v3_wall_counts(root_obj)
    if visible_object_count <= 0:
        issues.append("missing visible V3 wall meshes")
    if payload_cell_count > 0 and visible_cell_count != payload_cell_count:
        issues.append(f"visible V3 cell count drift payload={payload_cell_count} visible={visible_cell_count}")
    return tuple(issues)


def _delete_fresh_transaction_root(root_obj) -> str:
    if root_obj is None or root_obj.name not in bpy.data.objects:
        cleanup.prune_empty_generated_collections()
        return "no generated root remained"
    root_name = str(root_obj.name)
    try:
        result = cleanup.delete_generated_building_hierarchy(root_obj)
    except Exception as exc:
        cleanup.prune_empty_generated_collections()
        return f"cleanup failed for {root_name}: {exc}"
    return (
        f"cleaned {root_name} "
        f"({int(result.get('removed_objects', 0))} object(s), "
        f"{int(result.get('removed_collections', 0))} collection(s))"
    )


def _next_row_origin(scene, origin: tuple[float, float, float], width: float) -> tuple[float, float, float]:
    row_roots = []
    for obj in bpy.data.objects:
        if not _is_top_level_building_root(scene, obj):
            continue
        if abs(obj.location.y - origin[1]) > ROW_Y_TOLERANCE:
            continue
        if abs(obj.location.z - origin[2]) > ROW_Z_TOLERANCE:
            continue
        row_roots.append(obj)

    return _next_row_origin_after_right_edges(
        origin,
        width,
        (_right_edge_for_root(root) for root in row_roots),
    )


def _next_row_origin_after_right_edges(
    origin: tuple[float, float, float],
    width: float,
    right_edges,
) -> tuple[float, float, float]:
    right_edges = tuple(float(edge) for edge in right_edges)
    if not right_edges:
        return origin
    max_right_edge = max(right_edges)
    min_center_x = max_right_edge + ROW_SPACING + width / 2
    return (
        max(origin[0], min_center_x),
        origin[1],
        origin[2],
    )


class TBG_OT_generate_building(bpy.types.Operator):
    bl_idname = "tbg.generate_building"
    bl_label = "Generate Building"
    bl_description = "Generate a tactical building blockout from the current settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.tbg_building
        cursor_origin = tuple(float(v) for v in context.scene.cursor.location)
        preview_plan = plan_building(
            building_spec_from_settings(settings, building_id=None, origin=cursor_origin)
        )
        preview_spec = preview_plan.spec
        if str(getattr(preview_spec, "massing_profile", "")).upper() == "TOP_SETBACK":
            if _terrace_transition_contract(preview_spec)[0] is None:
                self.report({"ERROR"}, "Terrace requires a larger footprint; increase width/depth or disable Terrace.")
                return {"CANCELLED"}
        if abs(float(settings.width) - float(preview_spec.width)) > 1e-6:
            settings.width = float(preview_spec.width)
        if abs(float(settings.depth) - float(preview_spec.depth)) > 1e-6:
            settings.depth = float(preview_spec.depth)
        preview_width = float(preview_spec.width) * float(getattr(preview_spec, "world_scale", 1.0))
        origin = _next_row_origin(context.scene, cursor_origin, preview_width)
        planned_spec = preview_plan if origin == cursor_origin else plan_building(
            building_spec_from_settings(settings, building_id=None, origin=origin)
        )
        spec = planned_spec.spec
        scene_name = str(getattr(context.scene, "name_full", "") or getattr(context.scene, "name", ""))
        if str(getattr(spec, "massing_profile", "")).upper() == "TOP_SETBACK":
            if _terrace_transition_contract(spec)[0] is None:
                self.report({"ERROR"}, "Terrace requires a larger footprint; increase width/depth or disable Terrace.")
                return {"CANCELLED"}

        operator_status = "FINISHED: queued preview-first building generation"
        generate_job_id_holder: dict[str, int | None] = {"id": None}

        def _generate_job():
            _set_generate_status(scene_name, "Generate queued job is now running.")
            job_context = bpy.context
            cleanup.prune_empty_generated_collections()
            sequence = create_build_preview_sequence(
                job_context,
                spec,
                suppress_viewport_emit=True,
            )

            def _preview_step():
                try:
                    completed = sequence.step()
                except Exception as exc:
                    root_name_before_cleanup = _fresh_failure_root_name(sequence.root_obj)
                    traceback_path = _capture_fresh_failure_traceback(
                        stage="preview",
                        failure_class="exception",
                        spec=spec,
                        root_obj=sequence.root_obj,
                        root_name_override=root_name_before_cleanup,
                        exc=exc,
                    )
                    cleanup_status = _delete_fresh_transaction_root(sequence.root_obj)
                    failure = f"Generate preview failed: {exc}; {cleanup_status}."
                    _record_fresh_failure_artifact(
                        stage="preview",
                        failure_class="exception",
                        spec=spec,
                        root_obj=sequence.root_obj,
                        root_name_override=root_name_before_cleanup,
                        traceback_path=traceback_path,
                        cleanup_result=cleanup_status,
                        operator_status=operator_status,
                        scheduler_job_id=generate_job_id_holder["id"],
                        scheduler_label="generate-building",
                        failure_message=failure,
                    )
                    _set_generate_status(scene_name, _generate_failure_status(failure))
                    return False, failure
                if not completed:
                    _set_generate_status(scene_name, "Generate preview is running.")
                    return _continued_job(
                        label="generate-building",
                        execute=_preview_step,
                        message="Continuing preview-first building generation.",
                    )

                cleanup.prune_empty_generated_collections()
                root = metadata.resolve_root_from_object(sequence.root_obj) or sequence.root_obj
                selected_building_tuning.select_and_bind_root(job_context, root)
                root_identity = (root.name, str(root.get("tbg_building_id", "")))
                finalize_dedupe_key = f"generate-finalize:{root_identity[1] or root_identity[0]}"
                finalize_job_id_holder: dict[str, int | None] = {"id": None}
                _set_generate_status(scene_name, f"Generated preview for {root.name}; finalizing...")

                def _finalize_followup():
                    active_context = bpy.context
                    target_root = bpy.data.objects.get(root_identity[0])
                    if target_root is None:
                        issue = f"dropped finalize follow-up for {root_identity[0] or 'generated root'}"
                        _record_fresh_failure_pre_cleanup_issue(
                            stage="finalize_followup",
                            failure_class="dropped_followup",
                            spec=spec,
                            root_name_override=root_identity[0],
                            issue=issue,
                        )
                        cleanup.prune_empty_generated_collections()
                        failure = f"Generate finalize failed: dropped finalize follow-up for {root_identity[0] or 'generated root'}."
                        _record_fresh_failure_artifact(
                            stage="finalize_followup",
                            failure_class="dropped_followup",
                            spec=spec,
                            root_name_override=root_identity[0],
                            first_contract_issue=issue,
                            cleanup_result="pruned empty generated collections",
                            operator_status=operator_status,
                            scheduler_job_id=finalize_job_id_holder["id"],
                            scheduler_label=f"generate-finalize:{root_identity[0] or 'generated root'}",
                            failure_message=failure,
                        )
                        _set_generate_status(scene_name, _generate_failure_status(failure))
                        return False, failure
                    active_scene = bpy.data.scenes.get(scene_name) if scene_name else getattr(active_context, "scene", None)
                    if (
                        active_scene is not None
                        and selected_building_tuning.is_rebuild_pending(active_scene)
                        and selected_building_tuning.bound_root_name(active_scene) == target_root.name
                    ):
                        return _continued_job(
                            label=f"generate-finalize:{target_root.name}",
                            execute=_finalize_followup,
                            delay_seconds=0.15,
                            dedupe_key=finalize_dedupe_key,
                            replace_dedupe=True,
                            message=f"Deferred finalize follow-up for {target_root.name}.",
                        )

                    cleanup.prune_empty_generated_collections()
                    effective_spec_dict = metadata.read_effective_spec_dict(target_root, allow_legacy_dirty=True)
                    effective_spec = building_spec_from_mapping(
                        effective_spec_dict or spec.to_dict(),
                        building_id=str(target_root.get("tbg_building_id", "")) or None,
                        origin=tuple(target_root.location),
                    )
                    finalize_sequence = create_build_finalize_sequence(
                        active_context,
                        effective_spec,
                        existing_root=target_root,
                        suppress_viewport_emit=True,
                    )

                    def _finalize_step():
                        latest_root = bpy.data.objects.get(root_identity[0])
                        if latest_root is None:
                            issue = f"dropped finalize step for {root_identity[0] or 'generated root'}"
                            _record_fresh_failure_pre_cleanup_issue(
                                stage="finalize_step",
                                failure_class="dropped_followup",
                                spec=spec,
                                root_name_override=root_identity[0],
                                issue=issue,
                            )
                            cleanup.prune_empty_generated_collections()
                            failure = f"Generate finalize failed: dropped finalize follow-up for {root_identity[0] or 'generated root'}."
                            _record_fresh_failure_artifact(
                                stage="finalize_step",
                                failure_class="dropped_followup",
                                spec=spec,
                                root_name_override=root_identity[0],
                                first_contract_issue=issue,
                                cleanup_result="pruned empty generated collections",
                                operator_status=operator_status,
                                scheduler_job_id=finalize_job_id_holder["id"],
                                scheduler_label=f"generate-finalize:{root_identity[0] or 'generated root'}",
                                failure_message=failure,
                            )
                            _set_generate_status(scene_name, _generate_failure_status(failure))
                            return False, failure
                        latest_scene = bpy.data.scenes.get(scene_name) if scene_name else getattr(bpy.context, "scene", None)
                        if (
                            latest_scene is not None
                            and selected_building_tuning.is_rebuild_pending(latest_scene)
                            and selected_building_tuning.bound_root_name(latest_scene) == latest_root.name
                        ):
                            return _continued_job(
                                label=f"generate-finalize:{latest_root.name}",
                                execute=_finalize_step,
                                delay_seconds=0.15,
                                dedupe_key=finalize_dedupe_key,
                                replace_dedupe=True,
                                message=f"Deferred finalize follow-up for {latest_root.name}.",
                            )
                        try:
                            completed_finalize = finalize_sequence.step()
                        except Exception as exc:
                            root_name_before_cleanup = _fresh_failure_root_name(latest_root)
                            traceback_path = _capture_fresh_failure_traceback(
                                stage="finalize",
                                failure_class="exception",
                                spec=effective_spec,
                                root_obj=latest_root,
                                root_name_override=root_name_before_cleanup,
                                exc=exc,
                            )
                            cleanup_status = _delete_fresh_transaction_root(latest_root)
                            failure = f"Generate finalize failed: {exc}; {cleanup_status}."
                            _record_fresh_failure_artifact(
                                stage="finalize",
                                failure_class="exception",
                                spec=effective_spec,
                                root_obj=latest_root,
                                root_name_override=root_name_before_cleanup,
                                traceback_path=traceback_path,
                                cleanup_result=cleanup_status,
                                operator_status=operator_status,
                                scheduler_job_id=finalize_job_id_holder["id"],
                                scheduler_label=f"generate-finalize:{root_name_before_cleanup}",
                                failure_message=failure,
                            )
                            _set_generate_status(scene_name, _generate_failure_status(failure))
                            return False, failure
                        if not completed_finalize:
                            _set_generate_status(scene_name, f"Finalizing {latest_root.name}...")
                            return _continued_job(
                                label=f"generate-finalize:{latest_root.name}",
                                execute=_finalize_step,
                                dedupe_key=finalize_dedupe_key,
                                message=f"Continuing finalize follow-up for {latest_root.name}.",
                            )
                        cleanup.prune_empty_generated_collections()
                        rebound_root = metadata.resolve_root_from_object(finalize_sequence.root_obj) or finalize_sequence.root_obj
                        contract_issues = _fresh_generate_contract_issues(rebound_root)
                        if contract_issues:
                            first_issue = str(contract_issues[0])
                            root_name_before_cleanup = _fresh_failure_root_name(rebound_root)
                            _record_fresh_failure_pre_cleanup_issue(
                                stage="finalize_contract",
                                failure_class="contract_issue",
                                spec=effective_spec,
                                root_obj=rebound_root,
                                root_name_override=root_name_before_cleanup,
                                issue=first_issue,
                            )
                            cleanup_status = _delete_fresh_transaction_root(rebound_root)
                            failure = (
                                "Generate finalize failed: finalized root is not canonical "
                                f"({'; '.join(contract_issues)}); {cleanup_status}."
                            )
                            _record_fresh_failure_artifact(
                                stage="finalize_contract",
                                failure_class="contract_issue",
                                spec=effective_spec,
                                root_obj=rebound_root,
                                root_name_override=root_name_before_cleanup,
                                first_contract_issue=first_issue,
                                contract_issues=contract_issues,
                                cleanup_result=cleanup_status,
                                operator_status=operator_status,
                                scheduler_job_id=finalize_job_id_holder["id"],
                                scheduler_label=f"generate-finalize:{root_name_before_cleanup}",
                                failure_message=failure,
                            )
                            _set_generate_status(scene_name, _generate_failure_status(failure))
                            return False, failure
                        selected_building_tuning.select_and_bind_root(bpy.context, rebound_root)
                        _set_generate_status(scene_name, f"Generated {rebound_root.name}; finalize completed.")
                        return True, f"Generated preview for {rebound_root.name}; finalize completed."

                    return _finalize_step()

                finalize_job_id_holder["id"] = build_scheduler.enqueue_job(
                    label=f"generate-finalize:{root.name}",
                    execute=_finalize_followup,
                    delay_seconds=0.15,
                    dedupe_key=finalize_dedupe_key,
                    replace_dedupe=True,
                )
                return True, f"Queued preview build for {root.name}"

            return _preview_step()

        generate_job_id_holder["id"] = build_scheduler.enqueue_job(
            label="generate-building",
            execute=_generate_job,
        )
        _set_generate_status(scene_name, "Queued preview-first building generation.")
        if abs(float(settings.width) - float(spec.width)) > 1e-6:
            settings.width = float(spec.width)
        if abs(float(settings.depth) - float(spec.depth)) > 1e-6:
            settings.depth = float(spec.depth)
        self.report({"INFO"}, "Queued preview-first building generation.")
        return {"FINISHED"}
