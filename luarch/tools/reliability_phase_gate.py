from __future__ import annotations

import argparse
import addon_utils
import importlib
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_NAME = REPO_ROOT.name
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "tasks" / "strategic_reset" / "artifacts" / "phase_0" / "frozen_corpus.json"

CAMERA_DIRECTION = Vector((1.25, -1.45, 1.0)).normalized()
CAMERA_MARGIN = 1.35
RENDER_SIZE = (960, 540)
REQUIRED_PROOF_KEYS = (
    "sample_id",
    "preset_id",
    "seed",
    "scene_overrides",
    "expected",
    "generate",
    "regenerate",
    "parity",
)
ENTRY_COLLISION_ROLES = frozenset(
    {
        "ENTRY_LANDING",
        "ENTRY_WEDGE",
        "PODIUM_BLOCKER",
    }
)
MULTI_ROOT_SCOPE_CORPUS = (
    ("office_block", 1, "first_root_office"),
    ("townhouse", 1880987040, "second_root_townhouse"),
    ("wood_house", 1880987040, "third_root_wood_house"),
)


@dataclass(frozen=True)
class EditCase:
    case_id: str
    updates: dict[str, Any]
    export_smoke: bool = False
    regenerate_after_apply: bool = False
    expected: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class Sample:
    sample_id: str
    preset_id: str
    seed: int
    scene_overrides: dict[str, Any]
    access_class: str
    export_smoke: bool
    expected: dict[str, Any]
    edit_cases: tuple[EditCase, ...] = ()


def _blender_cli_args() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _ensure_import_path() -> None:
    parent = str(REPO_ROOT.parent)
    if parent in sys.path:
        sys.path.remove(parent)
    sys.path.insert(0, parent)


def _is_module_from_repo(module: Any) -> bool:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return False
    try:
        resolved = Path(str(module_file)).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return resolved.is_relative_to(REPO_ROOT)


def _purge_addon_modules() -> None:
    prefix = f"{ADDON_NAME}."
    stale_names = [
        module_name
        for module_name in tuple(sys.modules.keys())
        if module_name == ADDON_NAME or module_name.startswith(prefix)
    ]
    for module_name in stale_names:
        sys.modules.pop(module_name, None)


def _load_repo_addon_from_file() -> Any:
    addon_init = REPO_ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        ADDON_NAME,
        addon_init,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to create module spec for addon at {addon_init}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[ADDON_NAME] = module
    spec.loader.exec_module(module)
    return module


def _import_repo_addon() -> Any:
    existing = sys.modules.get(ADDON_NAME)
    if existing is not None and not _is_module_from_repo(existing):
        _purge_addon_modules()
    addon = importlib.import_module(ADDON_NAME)
    if not _is_module_from_repo(addon):
        _purge_addon_modules()
        addon = _load_repo_addon_from_file()
    if not _is_module_from_repo(addon):
        addon_path = getattr(addon, "__file__", "<unknown>")
        raise RuntimeError(
            f"Failed to import repo addon '{ADDON_NAME}' from '{REPO_ROOT}'; "
            f"resolved module path: {addon_path}"
        )
    return addon


def _disable_non_repo_addon_copy() -> None:
    def _safe_disable() -> None:
        try:
            addon_utils.disable(ADDON_NAME, default_set=False)
        except TypeError:
            addon_utils.disable(ADDON_NAME)
        except Exception:
            return

    loaded = sys.modules.get(ADDON_NAME)
    if loaded is not None and not _is_module_from_repo(loaded):
        _safe_disable()
        _purge_addon_modules()
        return

    for module in addon_utils.modules():
        if getattr(module, "__name__", "") != ADDON_NAME:
            continue
        if _is_module_from_repo(module):
            continue
        _safe_disable()
        _purge_addon_modules()
        return


def _ensure_addon_runtime(modules: dict[str, Any]) -> None:
    addon = modules["addon"]
    properties_mod = modules["properties"]
    modules["presets"].ensure_loaded()

    for cls in reversed(tuple(getattr(addon, "CLASSES", ()))):
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is None or existing is cls:
            continue
        try:
            bpy.utils.unregister_class(existing)
        except RuntimeError:
            pass

    for cls in getattr(addon, "CLASSES", ()):
        try:
            bpy.utils.register_class(cls)
        except (RuntimeError, ValueError) as exc:
            if "already registered" in str(exc):
                continue
            existing = getattr(bpy.types, cls.__name__, None)
            if existing is not None and existing is not cls:
                try:
                    bpy.utils.unregister_class(existing)
                except (RuntimeError, ValueError):
                    pass
                bpy.utils.register_class(cls)
            elif existing is cls:
                continue
            else:
                raise

    if hasattr(bpy.types.Scene, "tbg_building") or hasattr(bpy.types.Scene, "tbg_block"):
        try:
            properties_mod.unregister_scene_properties()
        except (RuntimeError, ValueError, AttributeError):
            pass
    properties_mod.register_scene_properties()

    scene = bpy.context.scene
    missing = [
        attr
        for attr in ("tbg_building", "tbg_block")
        if not hasattr(scene, attr)
    ]
    if missing:
        raise RuntimeError(
            "Addon runtime is not available after scene reset; missing scene properties: "
            + ", ".join(missing)
        )


def _load_modules() -> dict[str, Any]:
    _ensure_import_path()
    _disable_non_repo_addon_copy()
    addon = _import_repo_addon()
    modules = {
        "addon": addon,
        "constants": importlib.import_module(f"{ADDON_NAME}.constants"),
        "metadata": importlib.import_module(f"{ADDON_NAME}.metadata"),
        "properties": importlib.import_module(f"{ADDON_NAME}.properties"),
        "presets": importlib.import_module(f"{ADDON_NAME}.presets"),
        "specs": importlib.import_module(f"{ADDON_NAME}.generator.specs"),
        "validation": importlib.import_module(f"{ADDON_NAME}.services.validation"),
        "validation_facts": importlib.import_module(f"{ADDON_NAME}.services.validation_facts"),
        "selected_tuning": importlib.import_module(f"{ADDON_NAME}.services.selected_building_tuning"),
        "build_scheduler": importlib.import_module(f"{ADDON_NAME}.services.build_scheduler"),
        "export_rbxmx": importlib.import_module(f"{ADDON_NAME}.export_rbxmx"),
        "quick_export": importlib.import_module(f"{ADDON_NAME}.operators.quick_export_building"),
        "toggle_walls": importlib.import_module(f"{ADDON_NAME}.operators.toggle_walls"),
    }
    _ensure_addon_runtime(modules)
    return modules


def _parse_edit_cases(items: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> tuple[EditCase, ...]:
    cases: list[EditCase] = []
    for item in items or ():
        cases.append(
            EditCase(
                case_id=str(item["case_id"]),
                updates=dict(item.get("updates", {})),
                export_smoke=bool(item.get("export_smoke", False)),
                regenerate_after_apply=bool(item.get("regenerate_after_apply", False)),
                expected=dict(item.get("expected", {})),
                notes=str(item.get("notes", "")),
            )
        )
    return tuple(cases)


def _parse_manifest(path: Path) -> tuple[dict[str, Any], list[Sample]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    samples = [
        Sample(
            sample_id=str(item["sample_id"]),
            preset_id=str(item["preset_id"]),
            seed=int(item["seed"]),
            scene_overrides=dict(item.get("scene_overrides", {})),
            access_class=str(item.get("access_class", "")),
            export_smoke=bool(item.get("export_smoke", False)),
            expected=dict(item.get("expected", {})),
            edit_cases=_parse_edit_cases(item.get("edit_cases")),
        )
        for item in payload.get("samples", [])
    ]
    return payload, samples


def _resolve_sample_ids(manifest: dict[str, Any], argv_ids: list[str] | None) -> list[str] | None:
    if not argv_ids:
        return None
    ids: list[str] = []
    sets = dict(manifest.get("sets", {}))
    for raw_id in argv_ids:
        key = str(raw_id).strip()
        if not key:
            continue
        if key in sets:
            ids.extend(str(item) for item in sets[key])
            continue
        ids.append(key)
    seen: set[str] = set()
    ordered: list[str] = []
    for sample_id in ids:
        if sample_id in seen:
            continue
        seen.add(sample_id)
        ordered.append(sample_id)
    return ordered


def _filter_samples(samples: list[Sample], allowed_ids: list[str] | None) -> list[Sample]:
    if allowed_ids is None:
        return samples
    allowed = set(allowed_ids)
    filtered = [sample for sample in samples if sample.sample_id in allowed]
    missing = [sample_id for sample_id in allowed_ids if sample_id not in {sample.sample_id for sample in filtered}]
    if missing:
        raise SystemExit(f"Unknown sample ids: {', '.join(missing)}")
    return filtered


def _reset_scene(modules: dict[str, Any]) -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _ensure_addon_runtime(modules)
    scene = bpy.context.scene
    scene.cursor.location = (0.0, 0.0, 0.0)
    return scene


def _apply_building_payload(scene: bpy.types.Scene, modules: dict[str, Any], sample: Sample) -> None:
    settings = scene.tbg_building
    properties_mod = modules["properties"]
    presets_mod = modules["presets"]
    specs_mod = modules["specs"]
    pointer = properties_mod.suppress_preset_callback(settings)
    try:
        payload = presets_mod.build_randomized_payload(sample.preset_id, sample.seed)
        payload.update(sample.scene_overrides)
        payload["preset_id"] = sample.preset_id
        payload["seed"] = int(sample.seed)
        normalized = specs_mod.normalized_payload_from_mapping(payload)
        presets_mod.apply_payload(settings, normalized, include_preset_id=True)
        settings.seed = int(sample.seed)
    finally:
        properties_mod.resume_preset_callback(pointer)


def _generated_roots(metadata_mod) -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if metadata_mod.is_root_object(obj)]


def _require_single_root(metadata_mod) -> bpy.types.Object:
    roots = _generated_roots(metadata_mod)
    if len(roots) != 1:
        raise RuntimeError(f"Expected exactly one generated root, found {len(roots)}")
    return roots[0]


def _root_preset_id(modules: dict[str, Any], root_obj: bpy.types.Object) -> str:
    try:
        spec = modules["metadata"].read_spec_dict(root_obj, strict=True)
    except Exception:
        return "unknown"
    return str(spec.get("preset_id", "") or "unknown")


def _collect_matrix_row_for_root(
    modules: dict[str, Any],
    root_obj: bpy.types.Object,
    *,
    stage: str,
    issues: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    loaded = modules["validation_facts"]._load_validation_state(root_obj)
    if isinstance(loaded, list):
        raise RuntimeError("; ".join(str(issue) for issue in loaded))
    facts = modules["validation_facts"]._collect_validation_facts(loaded)
    row = modules["validation_facts"].build_numeric_smoke_matrix_row(
        facts,
        generate_stage=stage,
        validation_issues=tuple(str(issue) for issue in issues),
        dirty_root_after_idle=False,
        regenerate_status="green" if not issues else "red",
    )
    row["scene_root_count"] = len(_generated_roots(modules["metadata"]))
    row["active_root_name"] = str(root_obj.name)
    return row


def _generate_root_without_scene_reset(
    modules: dict[str, Any],
    preset_id: str,
    seed: int,
) -> bpy.types.Object:
    before = {obj.name for obj in _generated_roots(modules["metadata"])}
    sample = Sample(
        sample_id=f"{preset_id}_{seed}",
        preset_id=preset_id,
        seed=int(seed),
        scene_overrides={},
        access_class="multi_root_scope",
        export_smoke=False,
        expected={},
    )
    _apply_building_payload(bpy.context.scene, modules, sample)
    generate_result = bpy.ops.tbg.generate_building("EXEC_DEFAULT")
    if "FINISHED" not in generate_result:
        raise RuntimeError(f"{preset_id}_{seed}: Generate Building did not finish: {sorted(generate_result)}")
    success, message = modules["build_scheduler"].flush(force_ready=True)
    if not success:
        raise RuntimeError(f"{preset_id}_{seed}: queued generate flush failed: {message}")
    roots = _generated_roots(modules["metadata"])
    new_roots = [root for root in roots if root.name not in before]
    matches = [root for root in new_roots if _root_preset_id(modules, root) == preset_id]
    if not matches:
        matches = [root for root in roots if _root_preset_id(modules, root) == preset_id]
    if not matches:
        raise RuntimeError(f"{preset_id}_{seed}: generated root not found; roots={[root.name for root in roots]}")
    return matches[-1]


def _run_multi_root_scope_smoke(modules: dict[str, Any], phase_root: Path) -> list[dict[str, Any]]:
    _reset_scene(modules)
    artifact_dir = phase_root / "multiroot_scope"
    matrix: list[dict[str, Any]] = []
    issues_ledger: list[str] = ["# Multi-root scope issues", ""]
    generated_roots: list[tuple[str, bpy.types.Object]] = []

    for preset_id, seed, case_id in MULTI_ROOT_SCOPE_CORPUS:
        root_obj = _generate_root_without_scene_reset(modules, preset_id, seed)
        generated_roots.append((case_id, root_obj))
        issues = modules["validation"].validate_root(root_obj)
        matrix.append(_collect_matrix_row_for_root(modules, root_obj, stage=case_id, issues=issues))
        for issue in issues:
            issues_ledger.append(f"- `{case_id}` `{root_obj.name}` — {issue}")

    for case_id, root_obj in generated_roots:
        issues = modules["validation"].validate_root(root_obj)
        stage = f"final_revalidate_{case_id}"
        matrix.append(_collect_matrix_row_for_root(modules, root_obj, stage=stage, issues=issues))
        for issue in issues:
            issues_ledger.append(f"- `{stage}` `{root_obj.name}` — {issue}")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    _write_json(artifact_dir / "matrix.json", matrix)
    _write_text(artifact_dir / "issues_ledger.md", "\n".join(issues_ledger) + "\n")
    return matrix


def _select_root(root_obj: bpy.types.Object) -> None:
    view_layer = bpy.context.view_layer
    for obj in view_layer.objects:
        try:
            obj.select_set(False)
        except RuntimeError:
            continue
    root_obj.select_set(True)
    view_layer.objects.active = root_obj
    bpy.context.view_layer.update()


def _ensure_render_scene(scene: bpy.types.Scene) -> None:
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_x = RENDER_SIZE[0]
    scene.render.resolution_y = RENDER_SIZE[1]
    scene.render.film_transparent = False
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"


def _visible_render_meshes(root_obj: bpy.types.Object) -> list[bpy.types.Object]:
    return [
        child
        for child in root_obj.children_recursive
        if child.type == "MESH"
        and not child.hide_render
        and not child.get("tbg_runtime_marker")
        and not child.get("tbg_contract_marker")
    ]


def _world_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    if not objects:
        raise RuntimeError("No visible render meshes available for screenshot capture.")
    min_corner = Vector((float("inf"), float("inf"), float("inf")))
    max_corner = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            min_corner.x = min(min_corner.x, point.x)
            min_corner.y = min(min_corner.y, point.y)
            min_corner.z = min(min_corner.z, point.z)
            max_corner.x = max(max_corner.x, point.x)
            max_corner.y = max(max_corner.y, point.y)
            max_corner.z = max(max_corner.z, point.z)
    return min_corner, max_corner


def _render_root(scene: bpy.types.Scene, root_obj: bpy.types.Object, output_path: Path) -> None:
    _ensure_render_scene(scene)
    visible_meshes = _visible_render_meshes(root_obj)
    min_corner, max_corner = _world_bounds(visible_meshes)
    center = (min_corner + max_corner) * 0.5
    extents = max_corner - min_corner
    radius = max(extents.x, extents.y, extents.z, 1.0) * CAMERA_MARGIN

    camera_data = bpy.data.cameras.new(name="TBG_PhaseGateCamera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = radius * 2.1
    camera = bpy.data.objects.new("TBG_PhaseGateCamera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + CAMERA_DIRECTION * radius * 2.5
    camera.rotation_euler = CAMERA_DIRECTION.to_track_quat("-Z", "Y").to_euler()

    camera_clip_end = max(1000.0, radius * 10.0)
    camera_data.clip_end = camera_clip_end
    scene.camera = camera
    scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=True)

    bpy.data.objects.remove(camera, do_unlink=True)
    bpy.data.cameras.remove(camera_data, do_unlink=True)


def _named_door_counts(root_obj: bpy.types.Object) -> dict[str, int]:
    counts = {"main": 0, "rear": 0, "roof_exit": 0}
    for child in root_obj.children_recursive:
        if child.type != "MESH" or not child.get("tbg_is_door_leaf"):
            continue
        if child.get("tbg_roof_exit_door") or child.name.endswith("Door_RoofExit"):
            counts["roof_exit"] += 1
        elif child.get("tbg_rear_through_access") or child.name.endswith("Door_Rear") or str(child.get("tbg_facade_side", "")) == "back":
            counts["rear"] += 1
        else:
            counts["main"] += 1
    return counts


def _wall_service_present(facts) -> bool:
    services = facts.summary.services
    return bool(services.drainpipes or services.blocking_wall_pipe_parts)


def _roof_exit_present(facts, named_doors: dict[str, int]) -> bool:
    return bool(facts.summary.roof_exit_bounds or facts.authored_roof_exit_bounds or named_doors["roof_exit"] > 0)


def _storefront_entry_count(facts) -> int:
    return sum(
        1
        for child in facts.mesh_children
        if child.get("tbg_storefront_part")
        and str(child.get("tbg_storefront_part_kind", "")).strip().upper() == "ENTRY"
    )


def _warehouse_rear_entry_count(facts) -> int:
    return sum(
        1 for child in facts.mesh_children if child.name.endswith("Door_Rear") and child.get("tbg_is_door_leaf")
    )


def _evaluate_expected(sample: Sample, facts, named_doors: dict[str, int]) -> dict[str, Any]:
    warehouse_rear_entry_count = _warehouse_rear_entry_count(facts)
    observed = {
        "front_door": named_doors["main"] > 0,
        "rear_access": "present" if (facts.rear_through_access or named_doors["rear"] > 0 or warehouse_rear_entry_count > 0) else "absent",
        "roof_exit": _roof_exit_present(facts, named_doors),
        "wall_service": "present" if _wall_service_present(facts) else "absent",
    }
    checks: dict[str, Any] = {}
    for key, expected_value in sample.expected.items():
        actual = observed.get(key)
        if key in {"front_door", "roof_exit"}:
            passed = bool(actual) is bool(expected_value)
        elif key in {"rear_access", "wall_service"}:
            if expected_value == "required":
                passed = actual == "present"
            elif expected_value == "forbidden":
                passed = actual == "absent"
            else:
                passed = True
        else:
            passed = actual == expected_value
        checks[key] = {
            "expected": expected_value,
            "actual": actual,
            "passed": passed,
        }
    return checks


def _load_facts(modules: dict[str, Any], root_obj: bpy.types.Object):
    loaded = modules["validation_facts"]._load_validation_state(root_obj)
    if isinstance(loaded, list):
        raise RuntimeError("Validation state load failed: " + " | ".join(loaded))
    return modules["validation_facts"]._collect_validation_facts(loaded)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _json_default(value: Any):
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _round_bounds(bounds: tuple[float, float, float, float, float, float]) -> list[float]:
    return [round(float(item), 4) for item in bounds]


def _object_local_bounds(root_obj: bpy.types.Object, child: bpy.types.Object) -> tuple[float, float, float, float, float, float]:
    support_mod = importlib.import_module(f"{ADDON_NAME}.generator.building_support")
    return tuple(float(item) for item in support_mod.object_local_bounds(root_obj, child))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def _owner_modules_for_case(failing_invariants: list[str]) -> list[str]:
    combined = " | ".join(str(item).lower() for item in failing_invariants)
    if "stoop" in combined or "selected" in combined or "entry collision" in combined:
        return [
            "generator/building_facade_frontage.py",
            "services/selected_building_tuning.py",
            "services/validation_rules.py",
        ]
    if "roof" in combined:
        return [
            "generator/building_roof.py",
            "generator/building_roof_exit.py",
            "generator/building_roof_services.py",
            "services/validation_rules_service_roof.py",
        ]
    if "service" in combined or "pipe" in combined:
        return [
            "generator/building_wall_service_pipes.py",
            "generator/building_roof_services.py",
            "services/validation_rules_service_roof.py",
        ]
    if "door" in combined or "entry" in combined or "frame" in combined:
        return [
            "generator/building_facade_frontage.py",
            "generator/building_facade_openings.py",
            "generator/building_facade_opening_slots.py",
        ]
    return [
        "services/validation_rules.py",
    ]


def _spec_for_parity(spec_payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(spec_payload)
    normalized.pop("building_id", None)
    return normalized


def _clear_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _export_smoke(modules: dict[str, Any], sample: Sample, root_obj: bpy.types.Object, sample_dir: Path) -> dict[str, Any]:
    return _export_smoke_with_label(modules, sample, root_obj, sample_dir, artifact_label="")


def _export_smoke_with_label(
    modules: dict[str, Any],
    sample: Sample,
    root_obj: bpy.types.Object,
    sample_dir: Path,
    *,
    artifact_label: str,
) -> dict[str, Any]:
    export_dir = sample_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    settings = bpy.context.scene.tbg_building
    settings.quick_export_directory = str(export_dir) + "/"
    _select_root(root_obj)
    operator_error = ""
    try:
        result = bpy.ops.tbg.quick_export_building("EXEC_DEFAULT")
    except RuntimeError as exc:
        result = {"CANCELLED"}
        operator_error = str(exc)
    export_log = {
        "operator_result": sorted(result),
        "operator_error": operator_error,
        "files": [],
        "status": "FINISHED" if "FINISHED" in result else "CANCELLED",
    }
    for file_path in sorted(export_dir.glob("*")):
        export_log["files"].append(
            {
                "name": file_path.name,
                "size_bytes": file_path.stat().st_size,
            }
        )
    prefix = f"{artifact_label}_" if artifact_label else ""
    _write_text(sample_dir / f"{prefix}export.txt", json.dumps(export_log, indent=2, sort_keys=True) + "\n")
    _write_text(
        sample_dir / f"{prefix}studio_attach.txt",
        "SKIPPED: Studio attach smoke is not available from this headless Blender harness. "
        "Run the exported sample through the Roblox Studio plugin or Studio MCP in a separate pass.\n",
    )
    shutil.rmtree(export_dir, ignore_errors=True)
    return export_log


def _marker_snapshot(root_obj: bpy.types.Object, marker: bpy.types.Object) -> dict[str, Any]:
    return {
        "name": marker.name,
        "role": str(marker.get("tbg_runtime_role", "")),
        "shape": str(marker.get("tbg_runtime_shape", "")),
        "side": str(marker.get("tbg_runtime_side", "")),
        "floor": int(marker.get("tbg_runtime_floor", -1)),
        "slot": int(marker.get("tbg_runtime_slot", -1)),
        "span_key": str(marker.get("tbg_runtime_span_key", "")),
        "direction": round(float(marker.get("tbg_runtime_direction", 0.0)), 4),
        "bounds": _round_bounds(_object_local_bounds(root_obj, marker)),
    }


def _collision_markers_for_root(root_obj: bpy.types.Object) -> tuple[bpy.types.Object, ...]:
    return tuple(
        child
        for child in root_obj.children_recursive
        if child.type == "MESH"
        and child.get("tbg_runtime_marker")
        and str(child.get("tbg_runtime_kind", "")) == "COLLISION"
    )


def _entry_collision_signature(root_obj: bpy.types.Object, collision_markers: tuple[bpy.types.Object, ...], *, side: str) -> list[dict[str, Any]]:
    aliases = {"back", "rear"} if side == "rear" else {side}
    signature = [
        _marker_snapshot(root_obj, marker)
        for marker in collision_markers
        if str(marker.get("tbg_runtime_side", "")).strip().lower() in aliases
        and str(marker.get("tbg_runtime_role", "")).strip().upper() in ENTRY_COLLISION_ROLES
    ]
    return sorted(
        signature,
        key=lambda item: (
            item["role"],
            item["shape"],
            item["side"],
            item["floor"],
            item["slot"],
            item["span_key"],
            tuple(item["bounds"]),
        ),
    )


def _role_counts_by_side(collision_markers: tuple[bpy.types.Object, ...]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {"front": {}, "rear": {}}
    for marker in collision_markers:
        role = str(marker.get("tbg_runtime_role", "")).strip().upper()
        if role not in ENTRY_COLLISION_ROLES:
            continue
        raw_side = str(marker.get("tbg_runtime_side", "")).strip().lower()
        if raw_side == "front":
            side = "front"
        elif raw_side in {"back", "rear"}:
            side = "rear"
        else:
            continue
        counts[side][role] = counts[side].get(role, 0) + 1
    return counts


def _bounds_center_y(bounds: list[float] | tuple[float, ...]) -> float:
    return (float(bounds[2]) + float(bounds[3])) * 0.5


def _classified_entry_collision_signatures(
    root_obj: bpy.types.Object,
    collision_markers: tuple[bpy.types.Object, ...],
    *,
    front_door_bounds: tuple[float, float, float, float, float, float] | None,
    rear_door_bounds: tuple[float, float, float, float, float, float] | None,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"front": [], "rear": []}
    front_center_y = _bounds_center_y(front_door_bounds) if front_door_bounds is not None else None
    rear_center_y = _bounds_center_y(rear_door_bounds) if rear_door_bounds is not None else None
    for marker in collision_markers:
        role = str(marker.get("tbg_runtime_role", "")).strip().upper()
        if role not in ENTRY_COLLISION_ROLES:
            continue
        snapshot = _marker_snapshot(root_obj, marker)
        marker_center_y = _bounds_center_y(snapshot["bounds"])
        if front_center_y is not None and rear_center_y is not None:
            side = "front" if abs(marker_center_y - front_center_y) <= abs(marker_center_y - rear_center_y) else "rear"
        elif front_center_y is not None:
            side = "front"
        elif rear_center_y is not None:
            side = "rear"
        else:
            side = "front" if marker_center_y <= 0.0 else "rear"
        grouped[side].append(snapshot)
    for side in grouped:
        grouped[side] = sorted(
            grouped[side],
            key=lambda item: (
                item["role"],
                item["shape"],
                item["floor"],
                item["slot"],
                item["span_key"],
                tuple(item["bounds"]),
            ),
        )
    return grouped


def _classified_entry_role_counts(signatures: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {"front": {}, "rear": {}}
    for side, items in signatures.items():
        for item in items:
            role = str(item["role"])
            counts[side][role] = counts[side].get(role, 0) + 1
    return counts


def _axis_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(float(a1), float(b1)) - max(float(a0), float(b0)))


def _rounded_stoop_overlap_issue(
    signatures: list[dict[str, Any]],
) -> str | None:
    landing = next((item for item in signatures if str(item.get("role")) == "ENTRY_LANDING"), None)
    wedge = next((item for item in signatures if str(item.get("role")) == "ENTRY_WEDGE"), None)
    if landing is None or wedge is None:
        return None
    landing_bounds = landing.get("bounds") or ()
    wedge_bounds = wedge.get("bounds") or ()
    if len(landing_bounds) != 6 or len(wedge_bounds) != 6:
        return None
    overlap_y = _axis_overlap(landing_bounds[2], landing_bounds[3], wedge_bounds[2], wedge_bounds[3])
    overlap_z = _axis_overlap(landing_bounds[4], landing_bounds[5], wedge_bounds[4], wedge_bounds[5])
    if overlap_y > 0.02 and overlap_z > 0.02:
        return (
            "rounded stoop runtime package still stacks ENTRY_LANDING on top of ENTRY_WEDGE "
            f"(overlap_y={overlap_y:.3f}, overlap_z={overlap_z:.3f})"
        )
    return None


def _v3_visible_uv_static_gate_metrics() -> dict[str, Any]:
    source_path = REPO_ROOT / "generator" / "building_output.py"
    source = source_path.read_text(encoding="utf-8")
    function_marker = "def _apply_v3_visible_wall_roblox_part_texture_uv"
    fallback_marker = "def _apply_visible_panel_face_fit_uv"
    if function_marker not in source or fallback_marker not in source:
        return {
            "v3_visible_uv_path_atlas_call_count": 1,
            "texture_face_uv_implementation_invalid_count_static": 1,
        }
    body = source.split(function_marker, 1)[1].split(fallback_marker, 1)[0]
    atlas_calls = body.count("_apply_material_uv(") + body.count("_retile_brick_section(")
    modulo_formulas = body.count("%") + body.count("modulo")
    root_local_assignments = body.count('tbg_brick_uv_space"] = "ROOT_LOCAL"') + body.count("tbg_brick_uv_space'] = 'ROOT_LOCAL'")
    return {
        "v3_visible_uv_path_atlas_call_count": int(atlas_calls),
        "texture_face_uv_implementation_invalid_count_static": int(modulo_formulas + root_local_assignments),
    }


def _texture_gate_metrics_from_facts(facts: Any | None) -> dict[str, Any]:
    if facts is None:
        return {}
    voxel = facts.voxel_wall_facts
    metrics = {
        "payload_authored_cell_count": int(voxel.total_authored_cell_count),
        "visible_v3_composite_cell_count": int(voxel.real_visible_cell_count),
        "texture_contract_key_present_count": int(voxel.texture_contract_key_present_count),
        "texture_projection_valid_count": int(voxel.texture_projection_valid_count),
        "texture_image_period_contract_valid_count": int(voxel.texture_image_period_contract_valid_count),
        "texture_face_axis_table_valid_count": int(voxel.texture_face_axis_table_valid_count),
        "texture_studs_per_tile_valid_count": int(voxel.texture_studs_per_tile_valid_count),
        "cells_with_surface_uv_origin_count": int(voxel.cells_with_surface_uv_origin_count),
        "cell_surface_uv_phase_consistency_max_delta_studs": float(voxel.cell_surface_uv_phase_consistency_max_delta_studs),
        "texture_tile_scale_max_delta_studs": float(voxel.texture_tile_scale_max_delta_studs),
        "visible_texture_contract_cell_count": int(voxel.visible_texture_contract_cell_count),
        "v3_visible_root_local_uv_object_count": int(voxel.v3_visible_root_local_uv_object_count),
        "texture_preview_payload_parity": bool(voxel.texture_preview_payload_parity),
        "color_modulation_policy_invalid_count": int(voxel.color_modulation_policy_invalid_count),
        "projection_classification_drift_count": int(voxel.projection_classification_drift_count),
        "non_axis_aligned_plane_count": int(voxel.non_axis_aligned_plane_count),
        "composite_box_face_order_probe_match": bool(voxel.composite_box_face_order_probe_match),
        "texture_face_uv_implementation_invalid_count": int(voxel.texture_face_uv_implementation_invalid_count),
        "window_fill_wrong_material_count": int(voxel.window_fill_wrong_material_count),
        "window_fill_non_blue_count": int(voxel.window_fill_non_blue_count),
        "window_fill_shader_non_blue_count": int(voxel.window_fill_shader_non_blue_count),
        "window_fill_missing_uv_count": int(voxel.window_fill_missing_uv_count),
        "window_fill_shader_rgb_min": (
            [float(value) for value in voxel.window_fill_shader_rgb_min]
            if voxel.window_fill_shader_rgb_min is not None
            else None
        ),
        "window_fill_shader_rgb_max": (
            [float(value) for value in voxel.window_fill_shader_rgb_max]
            if voxel.window_fill_shader_rgb_max is not None
            else None
        ),
        "window_fill_same_plane_v3_overlap_count": int(voxel.window_fill_same_plane_v3_overlap_count),
        "decorative_window_panel_count": sum(
            1 for child in facts.mesh_children if bool(child.get("tbg_decorative_window_panel"))
        ),
        "v3_material_style_preview_mismatch_count": int(voxel.v3_material_style_preview_mismatch_count),
        "pass_calculation_source": "numeric_metrics_only",
    }
    metrics.update(_v3_visible_uv_static_gate_metrics())
    return metrics


def _capture_observation(
    modules: dict[str, Any],
    sample: Sample,
    root_obj: bpy.types.Object,
    *,
    sample_dir: Path,
    image_name: str,
    run_export_smoke: bool,
    export_artifact_label: str = "",
    allow_contractless: bool = False,
) -> dict[str, Any]:
    scene = bpy.context.scene
    _select_root(root_obj)
    _render_root(scene, root_obj, sample_dir / image_name)
    fallback_issue: str | None = None
    try:
        facts = _load_facts(modules, root_obj)
        collision_markers = facts.marker_facts.collision_markers
        entry_signatures = _classified_entry_collision_signatures(
            root_obj,
            collision_markers,
            front_door_bounds=facts.front_door_bounds,
            rear_door_bounds=facts.rear_door_bounds,
        )
        entry_role_counts = _classified_entry_role_counts(entry_signatures)
        named_doors = _named_door_counts(root_obj)
        checks = _evaluate_expected(sample, facts, named_doors)
        issues = modules["validation"].validate_root(root_obj)
        storefront_entry_count = _storefront_entry_count(facts)
        warehouse_rear_entry_count = _warehouse_rear_entry_count(facts)
        rear_through_access = bool(facts.rear_through_access)
        roof_exit_present = _roof_exit_present(facts, named_doors)
        wall_service_present = _wall_service_present(facts)
        roof_access_enabled = bool(facts.roof_access_enabled)
        top_terminal_mode = str(facts.top_terminal_mode)
        roof_mode = str(facts.roof_mode)
        door_profile = str(facts.door_profile)
        drainpipe_count = len(facts.summary.services.drainpipes)
        roof_service_roles = sorted({item.role for item in facts.summary.services.roof_items})
        summary_roof_exit_bounds = list(facts.summary.roof_exit_bounds) if facts.summary.roof_exit_bounds else None
        authored_roof_exit_bounds = list(facts.authored_roof_exit_bounds) if facts.authored_roof_exit_bounds else None
        contract_roof_exit_bounds = list(facts.contract_roof_exit_bounds) if facts.contract_roof_exit_bounds else None
        render_section_buckets = sorted(facts.render_section_buckets)
        hidden_wall_sections = list(facts.hidden_wall_sections)
        tri_count = int(facts.tri_count)
        width = round(float(facts.width), 4)
        depth = round(float(facts.depth), 4)
        summary_payload = modules["metadata"].read_generation_summary(root_obj)
        texture_gate_metrics = _texture_gate_metrics_from_facts(facts)
    except RuntimeError as exc:
        if not allow_contractless:
            raise
        fallback_issue = str(exc)
        facts = None
        collision_markers = _collision_markers_for_root(root_obj)
        entry_signatures = {
            "front": _entry_collision_signature(root_obj, collision_markers, side="front"),
            "rear": _entry_collision_signature(root_obj, collision_markers, side="rear"),
        }
        entry_role_counts = _role_counts_by_side(collision_markers)
        named_doors = _named_door_counts(root_obj)
        checks = {}
        issues = [fallback_issue]
        storefront_entry_count = 0
        warehouse_rear_entry_count = 0
        rear_through_access = bool(root_obj.get("tbg_rear_through_access", False))
        roof_exit_present = False
        wall_service_present = False
        roof_access_enabled = False
        top_terminal_mode = "<preview>"
        stored_spec_preview = modules["metadata"].read_spec_dict(root_obj)
        roof_mode = str(stored_spec_preview.get("roof_mode", ""))
        door_profile = str(stored_spec_preview.get("door_profile", ""))
        drainpipe_count = 0
        roof_service_roles = []
        summary_roof_exit_bounds = None
        authored_roof_exit_bounds = None
        contract_roof_exit_bounds = None
        render_section_buckets = sorted(
            {
                str(child.get("tbg_section_bucket", ""))
                for child in root_obj.children_recursive
                if child.type == "MESH" and str(child.get("tbg_section_bucket", ""))
            }
        )
        hidden_wall_sections = []
        tri_count = sum(
            max(1, len(poly.vertices) - 2)
            for child in root_obj.children_recursive
            if child.type == "MESH"
            and not child.get("tbg_runtime_marker")
            and not child.get("tbg_contract_marker")
            for poly in getattr(getattr(child, "data", None), "polygons", [])
        )
        width = round(float(stored_spec_preview.get("width", 0.0)), 4)
        depth = round(float(stored_spec_preview.get("depth", 0.0)), 4)
        summary_payload = modules["metadata"].read_generation_summary(root_obj)
        texture_gate_metrics = _texture_gate_metrics_from_facts(None)

    observation = {
        "root_name": root_obj.name,
        "building_id": str(root_obj.get(modules["constants"].BUILDING_ID_KEY, "")),
        "collection_name": str(root_obj.get(modules["constants"].COLLECTION_NAME_KEY, "")),
        "issue_count": len(issues),
        "issues": list(issues),
        "validation_facts_fallback": fallback_issue,
        "requires_regeneration": modules["validation"].validation_requires_regeneration(issues),
        "named_doors": named_doors,
        "rear_through_access": rear_through_access,
        "roof_exit_present": roof_exit_present,
        "wall_service_present": wall_service_present,
        "roof_access_enabled": roof_access_enabled,
        "top_terminal_mode": top_terminal_mode,
        "roof_mode": roof_mode,
        "door_profile": door_profile,
        "storefront_entry_count": storefront_entry_count,
        "warehouse_rear_entry_count": warehouse_rear_entry_count,
        "drainpipe_count": drainpipe_count,
        "roof_service_roles": roof_service_roles,
        "summary_roof_exit_bounds": summary_roof_exit_bounds,
        "authored_roof_exit_bounds": authored_roof_exit_bounds,
        "contract_roof_exit_bounds": contract_roof_exit_bounds,
        "render_section_buckets": render_section_buckets,
        "hidden_wall_sections": hidden_wall_sections,
        "tri_count": tri_count,
        "width": width,
        "depth": depth,
        "collision_marker_count": len(collision_markers),
        "marker_role_counts": dict(
            sorted(
                (
                    str(marker.get("tbg_runtime_role", "")).strip().upper(),
                    sum(
                        1
                        for other in collision_markers
                        if str(other.get("tbg_runtime_role", "")).strip().upper()
                        == str(marker.get("tbg_runtime_role", "")).strip().upper()
                    ),
                )
                for marker in collision_markers
            )
        ),
        "marker_role_shapes": {
            role: sorted(
                {
                    str(marker.get("tbg_runtime_shape", "")).strip().upper()
                    for marker in collision_markers
                    if str(marker.get("tbg_runtime_role", "")).strip().upper() == role
                }
            )
            for role in sorted(
                {
                    str(marker.get("tbg_runtime_role", "")).strip().upper()
                    for marker in collision_markers
                }
            )
        },
        "entry_collision_signatures": entry_signatures,
        "entry_collision_role_counts": entry_role_counts,
        "expected_checks": checks,
        "summary_payload": summary_payload,
        "stored_spec": modules["metadata"].read_spec_dict(root_obj),
        "texture_gate_metrics": texture_gate_metrics,
    }
    if run_export_smoke:
        observation["export_smoke"] = _export_smoke_with_label(
            modules,
            sample,
            root_obj,
            sample_dir,
            artifact_label=export_artifact_label,
        )
    return observation


def _toggle_walls(root_obj: bpy.types.Object) -> dict[str, Any]:
    _select_root(root_obj)
    result = bpy.ops.tbg.toggle_walls("EXEC_DEFAULT")
    return {"operator_result": sorted(result), "walls_hidden": bool(root_obj.get("tbg_walls_hidden", False))}


def _normalized_payload_from_mapping(modules: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return modules["specs"].normalized_payload_from_mapping(dict(payload))


def _edited_payload(modules: dict[str, Any], base_payload: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(base_payload)
    candidate.update(updates)
    return _normalized_payload_from_mapping(modules, candidate)


def _edit_mismatch_map(
    final_payload: dict[str, Any],
    expected_payload: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    mismatches: dict[str, dict[str, Any]] = {}
    for key in sorted(updates):
        actual = final_payload.get(key)
        expected = expected_payload.get(key)
        if actual == expected:
            continue
        mismatches[key] = {"expected": expected, "actual": actual}
    return mismatches


def _stoop_side_for_key(key: str) -> str | None:
    if key == "front_stoop_variant":
        return "front"
    if key == "rear_stoop_variant":
        return "rear"
    return None


def _boolish_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no", "off"}
    return False


def _edit_case_corpus_drift_record(
    sample: Sample,
    sample_dir: Path,
    edit_case: EditCase,
    *,
    drift_kind: str,
    details: list[str],
) -> dict[str, Any]:
    return {
        "case_id": f"{sample.sample_id}:selected_edit:{edit_case.case_id}:{drift_kind}",
        "sample_id": sample.sample_id,
        "operation": f"selected_edit:{edit_case.case_id}",
        "classification": "corpus_drift",
        "drift_kind": drift_kind,
        "details": sorted(set(str(item) for item in details if str(item).strip())),
        "artifact_root": str(sample_dir.relative_to(sample_dir.parent.parent)),
        "owner_modules": [
            "generator/layout_facade_planning.py",
            "services/selected_building_tuning.py",
            "tools/reliability_phase_gate.py",
        ],
    }


def _edit_case_issue_records(
    sample: Sample,
    sample_dir: Path,
    edit_case: EditCase,
    case_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for issue in case_payload.get("issues", []):
        issues.append(
            {
                "case_id": f"{sample.sample_id}:selected_edit:{edit_case.case_id}:{issue}",
                "sample_id": sample.sample_id,
                "operation": f"selected_edit:{edit_case.case_id}",
                "failing_invariants": [issue],
                "validate_signature": sorted(case_payload["final"]["issues"]),
                "artifact_root": str(sample_dir.relative_to(sample_dir.parent.parent)),
                "owner_modules": _owner_modules_for_case([issue]),
            }
        )
    for phase_name in ("preview", "final", "regenerate"):
        observation = case_payload.get(phase_name)
        if not observation:
            continue
        issues_list = sorted(observation.get("issues", []))
        if not issues_list:
            continue
        issues.append(
            {
                "case_id": f"{sample.sample_id}:selected_edit:{edit_case.case_id}:{phase_name}:validation",
                "sample_id": sample.sample_id,
                "operation": f"selected_edit:{edit_case.case_id}:{phase_name}",
                "failing_invariants": issues_list,
                "validate_signature": issues_list,
                "artifact_root": str(sample_dir.relative_to(sample_dir.parent.parent)),
                "owner_modules": _owner_modules_for_case(issues_list),
            }
        )
    return issues


def _run_edit_case(
    modules: dict[str, Any],
    sample: Sample,
    edit_case: EditCase,
    sample_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    scene = bpy.context.scene
    root_obj = _require_single_root(modules["metadata"])
    _select_root(root_obj)
    modules["selected_tuning"].select_and_bind_root(bpy.context, root_obj)
    modules["selected_tuning"].refresh_selected_building_binding(bpy.context)

    before_observation = _capture_observation(
        modules,
        sample,
        root_obj,
        sample_dir=sample_dir,
        image_name=f"edit_{edit_case.case_id}_before.png",
        run_export_smoke=False,
    )
    before_payload = _normalized_payload_from_mapping(modules, before_observation["stored_spec"])
    expected_payload = _edited_payload(modules, before_payload, edit_case.updates)
    applicability = modules["selected_tuning"].entry_stoop_edit_applicability_from_payload(expected_payload)
    inapplicable_keys: dict[str, str] = {}
    for key in sorted(edit_case.updates):
        side = _stoop_side_for_key(key)
        if side is None:
            continue
        side_info = dict(applicability.get(side, {}))
        if bool(side_info.get("applicable", False)):
            continue
        inapplicable_keys[key] = str(side_info.get("reason", "resolved stoop capability is inapplicable")).strip()
    if inapplicable_keys:
        drift_details = [
            f"{key}: {reason}"
            for key, reason in sorted(inapplicable_keys.items())
        ]
        if _boolish_false(edit_case.expected.get("applicable", True)):
            drift_details.append("manifest expected marks this selected-edit case as inapplicable")
        else:
            drift_details.append("manifest selected-edit case is inapplicable under current resolved capability")
        case_payload = {
            "case_id": edit_case.case_id,
            "updates": edit_case.updates,
            "notes": edit_case.notes,
            "expected": edit_case.expected,
            "status": "inapplicable",
            "applicability": applicability,
            "inapplicable_updates": inapplicable_keys,
            "before": before_observation,
            "preview": None,
            "final": None,
            "regenerate": None,
            "stored_spec_equal_to_target": None,
            "stored_spec_mismatches": {},
            "issues": [],
        }
        _write_json(sample_dir / "edits" / f"{edit_case.case_id}.json", case_payload)
        return case_payload, [], [
            _edit_case_corpus_drift_record(
                sample,
                sample_dir,
                edit_case,
                drift_kind="inapplicable_selected_edit",
                details=drift_details,
            )
        ]

    selected_settings = scene.tbg_selected_building
    for key, value in edit_case.updates.items():
        if not hasattr(selected_settings, key):
            raise RuntimeError(f"{sample.sample_id}:{edit_case.case_id}: unknown selected-building field '{key}'")
        setattr(selected_settings, key, value)

    success, message = modules["build_scheduler"].flush(force_ready=True)
    if not success:
        raise RuntimeError(f"{sample.sample_id}:{edit_case.case_id}: preview flush failed: {message}")

    preview_root = _require_single_root(modules["metadata"])
    preview_observation = _capture_observation(
        modules,
        sample,
        preview_root,
        sample_dir=sample_dir,
        image_name=f"edit_{edit_case.case_id}_preview.png",
        run_export_smoke=False,
        allow_contractless=True,
    )

    success, message = modules["selected_tuning"].apply_selected_building(scene, context=bpy.context)
    if not success:
        raise RuntimeError(f"{sample.sample_id}:{edit_case.case_id}: finalize failed: {message}")

    final_root = _require_single_root(modules["metadata"])
    final_observation = _capture_observation(
        modules,
        sample,
        final_root,
        sample_dir=sample_dir,
        image_name=f"edit_{edit_case.case_id}_final.png",
        run_export_smoke=edit_case.export_smoke,
        export_artifact_label=f"edit_{edit_case.case_id}",
    )
    final_payload = _normalized_payload_from_mapping(modules, final_observation["stored_spec"])

    regenerate_observation: dict[str, Any] | None = None
    if edit_case.regenerate_after_apply:
        _select_root(final_root)
        regenerate_result = bpy.ops.tbg.regenerate_building("EXEC_DEFAULT")
        if "FINISHED" not in regenerate_result:
            raise RuntimeError(
                f"{sample.sample_id}:{edit_case.case_id}: post-edit regenerate failed: {sorted(regenerate_result)}"
            )
        regenerate_root = _require_single_root(modules["metadata"])
        regenerate_observation = _capture_observation(
            modules,
            sample,
            regenerate_root,
            sample_dir=sample_dir,
            image_name=f"edit_{edit_case.case_id}_regenerate.png",
            run_export_smoke=False,
        )

    issues: list[str] = []
    payload_mismatches = _edit_mismatch_map(final_payload, expected_payload, edit_case.updates)
    if payload_mismatches:
        issues.append("selected edit stored spec mismatch")
    for key in sorted(edit_case.updates):
        side = _stoop_side_for_key(key)
        if side is None:
            continue
        updated_value = str(expected_payload.get(key, "")).strip().upper()
        if before_payload.get(key) == expected_payload.get(key):
            continue
        before_signature = before_observation["entry_collision_signatures"][side]
        final_signature = final_observation["entry_collision_signatures"][side]
        if before_signature == final_signature:
            issues.append(f"{side} stoop selected edit left collision package unchanged")
        if updated_value == "ROUNDED":
            rounded_overlap_issue = _rounded_stoop_overlap_issue(final_signature)
            if rounded_overlap_issue is not None:
                issues.append(f"{side} {rounded_overlap_issue}")
    if edit_case.export_smoke:
        export_log = final_observation.get("export_smoke", {})
        if export_log.get("status") != "FINISHED":
            issues.append("selected edit export smoke failed")
    if regenerate_observation is not None:
        regenerate_payload = _normalized_payload_from_mapping(modules, regenerate_observation["stored_spec"])
        if regenerate_payload != final_payload:
            issues.append("selected edit regenerate drifted away from finalized stored spec")

    case_payload = {
        "case_id": edit_case.case_id,
        "updates": edit_case.updates,
        "notes": edit_case.notes,
        "expected": edit_case.expected,
        "status": "applied",
        "applicability": applicability,
        "before": before_observation,
        "preview": preview_observation,
        "final": final_observation,
        "regenerate": regenerate_observation,
        "stored_spec_equal_to_target": not payload_mismatches,
        "stored_spec_mismatches": payload_mismatches,
        "issues": sorted(set(issues)),
    }
    _write_json(sample_dir / "edits" / f"{edit_case.case_id}.json", case_payload)
    return case_payload, _edit_case_issue_records(sample, sample_dir, edit_case, case_payload), []


def _selected_edit_parity_issues(
    sample: Sample,
    sample_dir: Path,
    selected_edits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    by_case_id = {str(item["case_id"]): item for item in selected_edits}
    comparisons = (
        ("front_stoop_straight", "front_stoop_rounded", "front"),
        ("rear_stoop_straight", "rear_stoop_rounded", "rear"),
    )
    for left_case_id, right_case_id, side in comparisons:
        left = by_case_id.get(left_case_id)
        right = by_case_id.get(right_case_id)
        if not left or not right:
            continue
        if str(left.get("status", "applied")).strip().lower() != "applied":
            continue
        if str(right.get("status", "applied")).strip().lower() != "applied":
            continue
        left_signature = left["final"]["entry_collision_signatures"][side]
        right_signature = right["final"]["entry_collision_signatures"][side]
        if left_signature != right_signature:
            continue
        issues.append(
            {
                "case_id": f"{sample.sample_id}:selected_edit:{side}:variant_parity",
                "sample_id": sample.sample_id,
                "operation": "selected_edit_variant_parity",
                "failing_invariants": [f"{side} stoop rounded/straight parity collapsed to identical collision output"],
                "validate_signature": sorted(
                    set(left["final"]["issues"]) | set(right["final"]["issues"])
                ),
                "artifact_root": str(sample_dir.relative_to(sample_dir.parent.parent)),
                "owner_modules": _owner_modules_for_case([f"{side} stoop rounded/straight parity collapsed"]),
            }
        )
    return issues


def _generate_sample(
    modules: dict[str, Any],
    sample: Sample,
    phase_root: Path,
    *,
    manifest_relpath: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    scene = _reset_scene(modules)
    _apply_building_payload(scene, modules, sample)
    sample_dir = phase_root / sample.sample_id
    _clear_directory(sample_dir)

    generate_result = bpy.ops.tbg.generate_building("EXEC_DEFAULT")
    if "FINISHED" not in generate_result:
        raise RuntimeError(f"{sample.sample_id}: Generate Building did not finish: {sorted(generate_result)}")
    success, message = modules["build_scheduler"].flush(force_ready=True)
    if not success:
        raise RuntimeError(f"{sample.sample_id}: queued generate flush failed: {message}")
    root_obj = _require_single_root(modules["metadata"])
    generate_observation = _capture_observation(
        modules,
        sample,
        root_obj,
        sample_dir=sample_dir,
        image_name="generate.png",
        run_export_smoke=sample.export_smoke,
    )

    toggle_result = _toggle_walls(root_obj)
    _render_root(scene, root_obj, sample_dir / "toggle_walls.png")

    _select_root(root_obj)
    regenerate_result = bpy.ops.tbg.regenerate_building("EXEC_DEFAULT")
    if "FINISHED" not in regenerate_result:
        raise RuntimeError(f"{sample.sample_id}: Regenerate Selected did not finish: {sorted(regenerate_result)}")
    root_obj = _require_single_root(modules["metadata"])
    regenerate_observation = _capture_observation(
        modules,
        sample,
        root_obj,
        sample_dir=sample_dir,
        image_name="regenerate.png",
        run_export_smoke=False,
    )

    selected_edits: list[dict[str, Any]] = []
    edit_known_bad_cases: list[dict[str, Any]] = []
    edit_corpus_drift_cases: list[dict[str, Any]] = []
    for edit_case in sample.edit_cases:
        edit_payload, edit_known_bad, edit_corpus_drift = _run_edit_case(modules, sample, edit_case, sample_dir)
        selected_edits.append(edit_payload)
        edit_known_bad_cases.extend(edit_known_bad)
        edit_corpus_drift_cases.extend(edit_corpus_drift)
    if selected_edits:
        _write_json(sample_dir / "selected_edits.json", {"cases": selected_edits})

    combined_issues = sorted(set(generate_observation["issues"]) | set(regenerate_observation["issues"]))
    _write_text(sample_dir / "validate.txt", "\n".join(combined_issues) + ("\n" if combined_issues else ""))
    proof_payload = {
        "sample_id": sample.sample_id,
        "preset_id": sample.preset_id,
        "seed": sample.seed,
        "scene_overrides": sample.scene_overrides,
        "access_class": sample.access_class,
        "export_smoke": sample.export_smoke,
        "expected": sample.expected,
        "generate": generate_observation,
        "toggle_walls": toggle_result,
        "regenerate": regenerate_observation,
        "selected_edits": selected_edits,
        "corpus_drift": edit_corpus_drift_cases,
        "parity": {
            "validation_issue_sets_equal": sorted(generate_observation["issues"]) == sorted(regenerate_observation["issues"]),
            "summary_equal": generate_observation["summary_payload"] == regenerate_observation["summary_payload"],
            "stored_spec_equal": _spec_for_parity(generate_observation["stored_spec"])
            == _spec_for_parity(regenerate_observation["stored_spec"]),
            "named_doors_equal": generate_observation["named_doors"] == regenerate_observation["named_doors"],
            "roof_exit_equal": generate_observation["roof_exit_present"] == regenerate_observation["roof_exit_present"],
            "wall_service_equal": generate_observation["wall_service_present"] == regenerate_observation["wall_service_present"],
        },
    }
    _write_json(sample_dir / "proof.json", proof_payload)

    known_bad_cases: list[dict[str, Any]] = []
    corpus_drift_cases: list[dict[str, Any]] = list(edit_corpus_drift_cases)
    all_checks = {
        phase_name: payload["expected_checks"]
        for phase_name, payload in (("generate", generate_observation), ("regenerate", regenerate_observation))
    }
    for phase_name, check_map in all_checks.items():
        for key, check in check_map.items():
            if check["passed"]:
                continue
            corpus_drift_cases.append(
                {
                    "case_id": f"{sample.sample_id}:{phase_name}:{key}:manifest_expected_mismatch",
                    "sample_id": sample.sample_id,
                    "operation": phase_name,
                    "classification": "corpus_drift",
                    "drift_kind": "manifest_expected_mismatch",
                    "details": [
                        (
                            f"{key}: expected={check.get('expected')!r}, "
                            f"actual={check.get('actual')!r}"
                        )
                    ],
                    "artifact_root": str(sample_dir.relative_to(phase_root.parent.parent)),
                    "owner_modules": [
                        manifest_relpath,
                        "tools/reliability_phase_gate.py",
                    ],
                }
            )
    for phase_name, observation in (("generate", generate_observation), ("regenerate", regenerate_observation)):
        if not observation["issues"]:
            continue
        failing_invariants = sorted(observation["issues"])
        known_bad_cases.append(
            {
                "case_id": f"{sample.sample_id}:{phase_name}:validation",
                "sample_id": sample.sample_id,
                "operation": phase_name,
                "failing_invariants": failing_invariants,
                "validate_signature": failing_invariants,
                "artifact_root": str(sample_dir.relative_to(phase_root.parent.parent)),
                "owner_modules": _owner_modules_for_case(failing_invariants),
            }
        )
    known_bad_cases.extend(edit_known_bad_cases)
    if selected_edits:
        known_bad_cases.extend(_selected_edit_parity_issues(sample, sample_dir, selected_edits))
    return proof_payload, known_bad_cases, corpus_drift_cases


def _validate_artifact_contract(phase_root: Path, manifest: dict[str, Any], samples: list[Sample]) -> list[str]:
    missing: list[str] = []
    required_files = tuple(str(item) for item in manifest.get("required_files", []))
    required_export_files = tuple(str(item) for item in manifest.get("required_export_smoke_files", []))
    required_selected_edit_files = tuple(str(item) for item in manifest.get("required_selected_edit_files", []))
    for sample in samples:
        sample_dir = phase_root / sample.sample_id
        for name in required_files:
            if not (sample_dir / name).exists():
                missing.append(f"{sample.sample_id}:{name}")
        if sample.export_smoke:
            for name in required_export_files:
                if not (sample_dir / name).exists():
                    missing.append(f"{sample.sample_id}:{name}")
        if sample.edit_cases:
            for name in required_selected_edit_files:
                if not (sample_dir / name).exists():
                    missing.append(f"{sample.sample_id}:{name}")
            for edit_case in sample.edit_cases:
                edit_payload = None
                edit_payload_path = sample_dir / "edits" / f"{edit_case.case_id}.json"
                if edit_payload_path.exists():
                    try:
                        edit_payload = json.loads(edit_payload_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        edit_payload = None
                for suffix in ("before.png", "preview.png", "final.png"):
                    if str((edit_payload or {}).get("status", "")).strip().lower() == "inapplicable":
                        continue
                    path = sample_dir / f"edit_{edit_case.case_id}_{suffix}"
                    if not path.exists():
                        missing.append(f"{sample.sample_id}:{path.name}")
                if not edit_payload_path.exists():
                    missing.append(f"{sample.sample_id}:edits/{edit_case.case_id}.json")
                if edit_case.regenerate_after_apply:
                    if str((edit_payload or {}).get("status", "")).strip().lower() == "inapplicable":
                        continue
                    regenerate_png = sample_dir / f"edit_{edit_case.case_id}_regenerate.png"
                    if not regenerate_png.exists():
                        missing.append(f"{sample.sample_id}:{regenerate_png.name}")
                if edit_case.export_smoke:
                    if str((edit_payload or {}).get("status", "")).strip().lower() == "inapplicable":
                        continue
                    prefix = f"edit_{edit_case.case_id}_"
                    for name in ("export.txt", "studio_attach.txt"):
                        if not (sample_dir / f"{prefix}{name}").exists():
                            missing.append(f"{sample.sample_id}:{prefix}{name}")
        proof_path = sample_dir / "proof.json"
        if proof_path.exists():
            proof_payload = json.loads(proof_path.read_text(encoding="utf-8"))
            for key in REQUIRED_PROOF_KEYS:
                if key not in proof_payload:
                    missing.append(f"{sample.sample_id}:proof.json missing key {key}")
            if sample.edit_cases and "selected_edits" not in proof_payload:
                missing.append(f"{sample.sample_id}:proof.json missing key selected_edits")
    return missing


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture or replay the LuArch reliability phase gate corpus.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to the machine-usable frozen corpus manifest.",
    )
    parser.add_argument(
        "--phase",
        type=str,
        default="phase_0",
        help="Artifact phase directory name under docs/tasks/strategic_reset/artifacts/.",
    )
    parser.add_argument(
        "--sample-id",
        action="append",
        default=[],
        help="Specific sample id or manifest set name to execute. Repeatable.",
    )
    parser.add_argument(
        "--multi-root-scope-smoke",
        action="store_true",
        help="Also run the live-style multi-root validation scope regression without resetting between generated roots.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    manifest_relpath = str(manifest_path.relative_to(REPO_ROOT))
    manifest, samples = _parse_manifest(manifest_path)
    selected_ids = _resolve_sample_ids(manifest, list(args.sample_id))
    selected_samples = _filter_samples(samples, selected_ids)
    if not selected_samples:
        raise SystemExit("No samples selected.")

    modules = _load_modules()
    artifact_root = REPO_ROOT / str(manifest.get("artifact_root", "docs/tasks/strategic_reset/artifacts"))
    phase_root = artifact_root / str(args.phase)
    phase_root.mkdir(parents=True, exist_ok=True)

    proof_index: list[dict[str, Any]] = []
    known_bad_cases: list[dict[str, Any]] = []
    corpus_drift_cases: list[dict[str, Any]] = []
    for sample in selected_samples:
        proof_payload, sample_known_bad, sample_corpus_drift = _generate_sample(
            modules,
            sample,
            phase_root,
            manifest_relpath=manifest_relpath,
        )
        proof_index.append(
            {
                "sample_id": sample.sample_id,
                "artifact_root": str((phase_root / sample.sample_id).relative_to(REPO_ROOT)),
                "issue_count_generate": len(proof_payload["generate"]["issues"]),
                "issue_count_regenerate": len(proof_payload["regenerate"]["issues"]),
                "corpus_drift_count": len(sample_corpus_drift),
                "parity": proof_payload["parity"],
                "pass_calculation_source": "numeric_metrics_only",
            }
        )
        known_bad_cases.extend(sample_known_bad)
        corpus_drift_cases.extend(sample_corpus_drift)

    multi_root_matrix: list[dict[str, Any]] = []
    if bool(getattr(args, "multi_root_scope_smoke", False)):
        multi_root_matrix = _run_multi_root_scope_smoke(modules, phase_root)
        red_multi_root = [row for row in multi_root_matrix if row.get("failure_class") != "green"]
        if red_multi_root:
            known_bad_cases.append(
                {
                    "case_id": "multi_root_scope:validation",
                    "sample_id": "multi_root_scope",
                    "operation": "multi_root_scope",
                    "failing_invariants": [
                        f"{row.get('generate_stage')}: {row.get('failure_class')}"
                        for row in red_multi_root
                    ],
                    "validate_signature": [
                        f"{row.get('generate_stage')}: {row.get('failure_class')}"
                        for row in red_multi_root
                    ],
                    "artifact_root": str((phase_root / "multiroot_scope").relative_to(REPO_ROOT)),
                    "owner_modules": ["tools/reliability_phase_gate.py"],
                }
            )

    missing = _validate_artifact_contract(phase_root, manifest, selected_samples)
    _write_json(
        phase_root / "proof_index.json",
        {
            "phase": str(args.phase),
            "manifest": str(manifest_path.relative_to(REPO_ROOT)),
            "samples": proof_index,
            "missing_artifacts": missing,
            "multi_root_scope": {
                "enabled": bool(getattr(args, "multi_root_scope_smoke", False)),
                "rows": len(multi_root_matrix),
                "green_rows": len(
                    [row for row in multi_root_matrix if row.get("failure_class") == "green"]
                ),
                "red_rows": len(
                    [row for row in multi_root_matrix if row.get("failure_class") != "green"]
                ),
                "artifact_root": (
                    str((phase_root / "multiroot_scope").relative_to(REPO_ROOT))
                    if bool(getattr(args, "multi_root_scope_smoke", False))
                    else None
                ),
            },
        },
    )
    _write_json(
        phase_root / "corpus_drift.json",
        {
            "phase": str(args.phase),
            "manifest": str(manifest_path.relative_to(REPO_ROOT)),
            "cases": sorted(corpus_drift_cases, key=lambda item: str(item.get("case_id", ""))),
        },
    )
    if str(args.phase) == "phase_0":
        _write_json(phase_root / "known_bad_corpus.json", {"cases": known_bad_cases})

    if missing:
        raise SystemExit("Artifact contract missing files: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(_blender_cli_args()))
