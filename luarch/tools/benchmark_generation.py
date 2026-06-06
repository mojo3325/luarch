from __future__ import annotations

import argparse
import contextlib
import functools
import importlib
import importlib.util
import shlex
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy


REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_NAME = REPO_ROOT.name
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "tasks" / "perf_refactor_20260407" / "perf_phase0_baseline_20260407.md"
DEFAULT_ALLOWED_PRESETS = ""
DEFAULT_REPEATS = 5
SCENE_RESET_METHOD = "bpy.ops.wm.read_factory_settings(use_empty=True) before every repeat; cursor reset to (0, 0, 0)"

PARENT_METRIC_ORDER = {
    "building": (
        "operator.generate_building_execute",
        "build_scheduler.timer_callback",
    ),
    "district": (
        "operator.generate_block_execute",
        "build_scheduler.timer_callback",
        "generate_block_total",
    ),
    "selected_edit": (
        "selected_edit.trigger_edit",
        "build_scheduler.timer_callback",
        "selected_edit_finalize_wall",
    ),
}

NESTED_METRIC_ORDER = (
    "build_building_plan",
    "building.plan_consolidation",
    "building.consolidate_bucket",
    "building.finalize_consolidation",
    "building_output.plan_consolidation",
    "building_output.consolidate_bucket",
    "building_output.finalize_consolidation",
    "building_output._build_runtime_markers",
    "building_output.retile_dirty_brick_section",
    "build_building_prepare",
    "build_building_emit",
    "build_building_finalize_full",
    "build_building_finalize_edit",
    "selected_tuning_apply",
    "ensure_blockout_materials",
    "cleanup.clear_generated_building",
    "_build_wall_service_pipes",
    "_build_generation_summary",
    "_consolidate_generated_meshes",
    "cleanup.prune_empty_generated_collections",
)

PROGRESSIVE_METRIC_ORDER = (
    "preview_author_ms",
    "finalize_ms",
    "max_slice_ms",
    "p95_slice_ms",
    "slice_count",
    "time_to_first_visible_root_ms",
    "selected_edit_time_to_first_preview_ms",
    "selected_edit_time_to_preview_stable_ms",
    "time_to_finalized_root_ms",
    "scheduler_callback_ms_max",
    "scheduler_callback_ops_max",
    "scheduler_queue_depth_max",
    "longest_finalize_op_ms",
    "longest_consolidation_op_ms",
    "district_first_visible_root_ms_7x7",
    "district_first_finalized_root_ms_7x7",
    "district_half_finalized_slots_ms_7x7",
    "district_complete_ms_7x7",
    "district_preview_wave_complete_ms_7x7",
    "district_finalize_wave_complete_ms_7x7",
    "exact_spec_first_slot_ms",
    "exact_spec_repeat_slot_ms",
    "exact_spec_repeat_to_first_ratio_pct",
    "exact_spec_reuse_hits",
    "exact_spec_reuse_misses",
    "plan_building_ms",
    "plan_memo_hits",
    "plan_memo_misses",
)

FINALIZE_METRIC_KEYS = (
    "build_building_finalize_full",
    "build_building_finalize_edit",
    "building._build_runtime_markers",
    "building.plan_consolidation",
    "building.consolidate_bucket",
    "building.finalize_consolidation",
    "building.retile_dirty_brick_section",
    "building_output._build_runtime_markers",
    "_build_generation_summary",
    "building_output.plan_consolidation",
    "building_output.consolidate_bucket",
    "building_output.finalize_consolidation",
    "building_output.retile_dirty_brick_section",
    "_consolidate_generated_meshes",
)

CONSOLIDATION_METRIC_KEYS = (
    "building.plan_consolidation",
    "building.consolidate_bucket",
    "building.finalize_consolidation",
    "building_output.plan_consolidation",
    "building_output.consolidate_bucket",
    "building_output.finalize_consolidation",
    "_consolidate_generated_meshes",
)


@dataclass(frozen=True)
class Scenario:
    key: str
    kind: str
    label: str
    thermal_profile: str = "warm"
    preset_id: str | None = None
    seed: int | None = None
    width: float | None = None
    depth: float | None = None
    floor_count: int | None = None
    massing_profile: str | None = None
    rows: int | None = None
    columns: int | None = None
    block_seed: int | None = None
    spacing_x: float = 16.0
    spacing_y: float = 16.0
    lot_type: str = "ANY"
    allowed_presets: str = DEFAULT_ALLOWED_PRESETS
    exact_duplicate_preset_id: str | None = None
    exact_duplicate_seed: int | None = None
    repeats: int = 1
    optional: bool = False

    def description(self) -> str:
        profile_label = f"profile=`{self.thermal_profile}`"
        if self.kind == "building":
            description = f"{profile_label}, preset=`{self.preset_id}`, seed=`{self.seed}`"
            if self.width is not None:
                description += f", width=`{self.width}`"
            if self.depth is not None:
                description += f", depth=`{self.depth}`"
            if self.floor_count is not None:
                description += f", floors=`{self.floor_count}`"
            if self.massing_profile:
                description += f", massing=`{self.massing_profile}`"
            return description
        if self.kind == "selected_edit":
            return (
                f"{profile_label}, preset=`{self.preset_id}`, seed=`{self.seed}`, "
                "edit=`width + 0.8m`"
            )
        allowed_presets_label = self.allowed_presets if self.allowed_presets else "<full eligible pool>"
        base = (
            f"{profile_label}, "
            f"rows=`{self.rows}`, columns=`{self.columns}`, seed=`{self.block_seed}`, "
            f"spacing_x=`{self.spacing_x}`, spacing_y=`{self.spacing_y}`, "
            f"lot_type=`{self.lot_type}`, allowed_presets=`{allowed_presets_label}`"
        )
        if self.exact_duplicate_preset_id:
            duplicate_seed = self.exact_duplicate_seed if self.exact_duplicate_seed is not None else self.block_seed
            base += (
                f", exact_duplicate_preset_id=`{self.exact_duplicate_preset_id}`"
                f", exact_duplicate_seed=`{duplicate_seed}`"
            )
        return base


@dataclass
class RunResult:
    total_ms: float
    step_totals_ms: dict[str, float]
    step_calls: dict[str, int]
    step_samples_ms: dict[str, list[float]]
    progressive_metrics_ms: dict[str, float | None]
    root_count: int
    mesh_count: int
    district_variety_notes: dict[str, Any] | None = None


@dataclass
class ScenarioAggregate:
    scenario: Scenario
    runs: list[RunResult]

    def median_total_ms(self) -> float:
        return statistics.median(run.total_ms for run in self.runs)

    def repeat_totals_ms(self) -> list[float]:
        return [run.total_ms for run in self.runs]

    def median_root_count(self) -> int:
        return int(statistics.median(run.root_count for run in self.runs))

    def median_mesh_count(self) -> int:
        return int(statistics.median(run.mesh_count for run in self.runs))

    def metric_series(self, metric: str) -> list[float]:
        return [run.step_totals_ms.get(metric, 0.0) for run in self.runs]

    def metric_calls_series(self, metric: str) -> list[int]:
        return [run.step_calls.get(metric, 0) for run in self.runs]

    def metric_median_ms(self, metric: str) -> float:
        return statistics.median(self.metric_series(metric))

    def metric_median_calls(self, metric: str) -> int:
        return int(statistics.median(self.metric_calls_series(metric)))

    def metric_median_max_call_ms(self, metric: str) -> float:
        maxima = []
        for run in self.runs:
            samples = run.step_samples_ms.get(metric, [])
            maxima.append(max(samples) if samples else 0.0)
        return statistics.median(maxima) if maxima else 0.0

    def progressive_metric_series(self, metric: str) -> list[float]:
        values: list[float] = []
        for run in self.runs:
            value = run.progressive_metrics_ms.get(metric)
            if value is None:
                continue
            values.append(float(value))
        return values

    def progressive_metric_median(self, metric: str) -> float | None:
        values = self.progressive_metric_series(metric)
        if not values:
            return None
        return statistics.median(values)

    def district_variety_notes(self) -> dict[str, Any] | None:
        for run in self.runs:
            if run.district_variety_notes:
                return dict(run.district_variety_notes)
        return None


@dataclass(frozen=True)
class InstrumentedBoundary:
    module_key: str
    attr_name: str
    metric_key: str


INSTRUMENTED_BOUNDARIES = (
    InstrumentedBoundary("building", "build_building", "build_building_total"),
    InstrumentedBoundary("block_layout", "build_building", "build_building_total"),
    InstrumentedBoundary("block_layout", "generate_block", "generate_block_total"),
    InstrumentedBoundary("build_scheduler", "_timer_callback", "build_scheduler.timer_callback"),
    InstrumentedBoundary("building", "plan_building", "build_building_plan"),
    InstrumentedBoundary("building", "_prepare_building", "build_building_prepare"),
    InstrumentedBoundary("building", "_emit_building", "build_building_emit"),
    InstrumentedBoundary("building", "_finalize_building_full", "build_building_finalize_full"),
    InstrumentedBoundary("building", "_finalize_building_edit", "build_building_finalize_edit"),
    InstrumentedBoundary("selected_tuning", "_apply_selected_building", "selected_tuning_apply"),
    InstrumentedBoundary("building", "_build_runtime_markers", "building._build_runtime_markers"),
    InstrumentedBoundary("building", "plan_consolidation", "building.plan_consolidation"),
    InstrumentedBoundary("building", "consolidate_bucket", "building.consolidate_bucket"),
    InstrumentedBoundary("building", "finalize_consolidation", "building.finalize_consolidation"),
    InstrumentedBoundary("building", "retile_dirty_brick_section", "building.retile_dirty_brick_section"),
    InstrumentedBoundary("building_output", "_build_runtime_markers", "building_output._build_runtime_markers"),
    InstrumentedBoundary("building_output", "plan_consolidation", "building_output.plan_consolidation"),
    InstrumentedBoundary("building_output", "consolidate_bucket", "building_output.consolidate_bucket"),
    InstrumentedBoundary("building_output", "finalize_consolidation", "building_output.finalize_consolidation"),
    InstrumentedBoundary("building_output", "retile_dirty_brick_section", "building_output.retile_dirty_brick_section"),
    InstrumentedBoundary("materials", "ensure_blockout_materials", "ensure_blockout_materials"),
    InstrumentedBoundary("building", "_build_wall_service_pipes", "_build_wall_service_pipes"),
    InstrumentedBoundary("building", "_build_generation_summary", "_build_generation_summary"),
    InstrumentedBoundary("building", "_consolidate_generated_meshes", "_consolidate_generated_meshes"),
    InstrumentedBoundary("cleanup", "clear_generated_building", "cleanup.clear_generated_building"),
    InstrumentedBoundary("cleanup", "prune_empty_generated_collections", "cleanup.prune_empty_generated_collections"),
)


class StepTimer:
    def __init__(self) -> None:
        self.totals: dict[str, float] = defaultdict(float)
        self.calls: dict[str, int] = defaultdict(int)
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.timeline_events: list[tuple[str, float, float, int]] = []
        self._run_started_at: float | None = None
        self._metadata_module = None

    def begin_timeline(self, metadata_module=None) -> None:
        self.timeline_events.clear()
        self._run_started_at = time.perf_counter()
        self._metadata_module = metadata_module

    def wrap(self, key: str, fn):
        @functools.wraps(fn)
        def instrumented(*args, **kwargs):
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - started) * 1000.0
                self.totals[key] += duration_ms
                self.calls[key] += 1
                self.samples[key].append(duration_ms)
                if self._run_started_at is not None:
                    elapsed_ms = (time.perf_counter() - self._run_started_at) * 1000.0
                    root_count = _count_roots(self._metadata_module) if self._metadata_module is not None else 0
                    self.timeline_events.append((key, duration_ms, elapsed_ms, int(root_count)))

        return instrumented


def _blender_cli_args() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _repo_git(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _current_commit_hash() -> str:
    return _repo_git(["git", "rev-parse", "HEAD"])


def _is_worktree_dirty() -> bool:
    return bool(_repo_git(["git", "status", "--short"]))


def _ensure_import_path() -> None:
    parent = str(REPO_ROOT.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)


def _evict_nonlocal_addon_modules() -> None:
    prefix = f"{ADDON_NAME}."
    for module_name, module in tuple(sys.modules.items()):
        if module_name != ADDON_NAME and not module_name.startswith(prefix):
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            module_path = Path(module_file).resolve()
        except OSError:
            continue
        if module_path == REPO_ROOT / "__init__.py" or REPO_ROOT in module_path.parents:
            continue
        del sys.modules[module_name]


def _import_local_addon_package():
    init_path = REPO_ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        ADDON_NAME,
        init_path,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot create import spec for addon package at {init_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[ADDON_NAME] = module
    spec.loader.exec_module(module)
    return module


def _load_modules() -> dict[str, Any]:
    _ensure_import_path()
    _evict_nonlocal_addon_modules()
    addon = _import_local_addon_package()
    addon_file = Path(getattr(addon, "__file__", "")).resolve()
    if addon_file != REPO_ROOT / "__init__.py":
        raise RuntimeError(f"Resolved addon module from unexpected path: {addon_file}")
    if not hasattr(bpy.types.Scene, "tbg_building"):
        addon.register()
    modules = {
        "addon": addon,
        "metadata": importlib.import_module(f"{ADDON_NAME}.metadata"),
        "presets": importlib.import_module(f"{ADDON_NAME}.presets"),
        "properties": importlib.import_module(f"{ADDON_NAME}.properties"),
        "specs": importlib.import_module(f"{ADDON_NAME}.generator.specs"),
        "building": importlib.import_module(f"{ADDON_NAME}.generator.building"),
        "building_output": importlib.import_module(f"{ADDON_NAME}.generator.building_output"),
        "block_layout": importlib.import_module(f"{ADDON_NAME}.generator.block_layout"),
        "materials": importlib.import_module(f"{ADDON_NAME}.generator.materials"),
        "cleanup": importlib.import_module(f"{ADDON_NAME}.services.cleanup"),
        "build_scheduler": importlib.import_module(f"{ADDON_NAME}.services.build_scheduler"),
        "selected_tuning": importlib.import_module(f"{ADDON_NAME}.services.selected_building_tuning"),
    }
    modules["presets"].ensure_loaded()
    return modules


def _with_thermal_profiles(base_scenarios: list[Scenario], *, warm_repeats: int, cold_repeats: int) -> list[Scenario]:
    profiled: list[Scenario] = []
    for base in base_scenarios:
        cold_values = {
            **base.__dict__,
            "key": f"{base.key}.cold",
            "label": f"{base.label} [cold]",
            "thermal_profile": "cold",
            "repeats": max(1, int(cold_repeats)),
        }
        warm_values = {
            **base.__dict__,
            "key": f"{base.key}.warm",
            "label": f"{base.label} [warm]",
            "thermal_profile": "warm",
            "repeats": max(1, int(warm_repeats)),
        }
        profiled.append(
            Scenario(**cold_values)
        )
        profiled.append(
            Scenario(**warm_values)
        )
    return profiled


def _scenario_definitions(
    include_stress: bool,
    include_content_expansion: bool,
    *,
    warm_repeats: int,
    cold_repeats: int,
) -> list[Scenario]:
    base_scenarios = [
        Scenario(
            key="building.motel.reference",
            kind="building",
            label="Single building: motel reference case",
            preset_id="motel",
            seed=424242,
            width=14.2,
            depth=12.0,
            floor_count=3,
            massing_profile="BOX",
        ),
        Scenario(
            key="building.apartment_midrise.seed1001",
            kind="building",
            label="Single building: apartment_midrise / seed 1001",
            preset_id="apartment_midrise",
            seed=1001,
        ),
        Scenario(
            key="building.office_block.seed1001",
            kind="building",
            label="Single building: office_block / seed 1001",
            preset_id="office_block",
            seed=1001,
        ),
        Scenario(
            key="selected_edit.house_small.seed1",
            kind="selected_edit",
            label="Selected edit sweep: house_small / seed 1",
            preset_id="house_small",
            seed=1,
        ),
        Scenario(
            key="district.grid2x2_default",
            kind="district",
            label="District: 2x2 default",
            rows=2,
            columns=2,
            block_seed=5001,
        ),
        Scenario(
            key="district.grid4x4_default",
            kind="district",
            label="District: 4x4 default",
            rows=4,
            columns=4,
            block_seed=5001,
        ),
        Scenario(
            key="district.grid7x7_default",
            kind="district",
            label="District: 7x7 reference",
            rows=7,
            columns=7,
            block_seed=5001,
            optional=True,
        ),
        Scenario(
            key="district.grid5x5_exact_duplicates",
            kind="district",
            label="District: 5x5 exact-spec duplicates",
            rows=5,
            columns=5,
            block_seed=7301,
            lot_type="RESIDENTIAL",
            exact_duplicate_preset_id="house_small",
            exact_duplicate_seed=7301,
            optional=True,
        ),
    ]
    if include_stress:
        base_scenarios.append(
            Scenario(
                key="district.grid5x5_default",
                kind="district",
                label="District: 5x5 stress",
                rows=5,
                columns=5,
                block_seed=5001,
                optional=True,
            )
        )
    if include_content_expansion:
        base_scenarios.extend(
            [
                Scenario(
                    key="district.grid3x3_residential_expanded",
                    kind="district",
                    label="District: 3x3 residential expanded",
                    rows=3,
                    columns=3,
                    block_seed=5001,
                    lot_type="RESIDENTIAL",
                    allowed_presets="",
                    optional=True,
                ),
                Scenario(
                    key="district.grid3x3_commercial_expanded",
                    kind="district",
                    label="District: 3x3 commercial expanded",
                    rows=3,
                    columns=3,
                    block_seed=5001,
                    lot_type="COMMERCIAL",
                    allowed_presets="",
                    optional=True,
                ),
            ]
        )
    return _with_thermal_profiles(
        base_scenarios,
        warm_repeats=warm_repeats,
        cold_repeats=cold_repeats,
    )


def _filter_scenarios(scenarios: list[Scenario], selected_keys: list[str]) -> list[Scenario]:
    normalized = {str(value).strip() for value in selected_keys if str(value).strip()}
    if not normalized:
        return scenarios
    filtered: list[Scenario] = []
    for scenario in scenarios:
        base_key = scenario.key.rsplit(".", 1)[0] if scenario.key.endswith((".cold", ".warm")) else scenario.key
        if scenario.key in normalized or base_key in normalized:
            filtered.append(scenario)
    if not filtered:
        requested = ", ".join(sorted(normalized))
        raise RuntimeError(f"No scenarios matched --scenario-key filter(s): {requested}")
    return filtered


def _reset_scene(modules: dict[str, Any]) -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "tbg_building"):
        modules["addon"].register()
    scene = bpy.context.scene
    scene.cursor.location = (0.0, 0.0, 0.0)
    return scene


def _apply_building_payload(scene: bpy.types.Scene, modules: dict[str, Any], *, preset_id: str, seed: int) -> None:
    settings = scene.tbg_building
    properties_mod = modules["properties"]
    presets_mod = modules["presets"]
    pointer = properties_mod.suppress_preset_callback(settings)
    try:
        payload = modules["specs"].normalized_payload_from_mapping(presets_mod.build_randomized_payload(preset_id, seed))
        presets_mod.apply_payload(settings, payload, include_preset_id=True)
        settings.seed = int(seed)
    finally:
        properties_mod.resume_preset_callback(pointer)


def _apply_scenario_overrides(scene: bpy.types.Scene, scenario: Scenario) -> None:
    settings = scene.tbg_building
    if scenario.width is not None:
        settings.width = float(scenario.width)
    if scenario.depth is not None:
        settings.depth = float(scenario.depth)
    if scenario.floor_count is not None:
        settings.floor_count = int(scenario.floor_count)
    if scenario.massing_profile:
        settings.massing_profile = str(scenario.massing_profile)


def _configure_block(scene: bpy.types.Scene, scenario: Scenario) -> None:
    block = scene.tbg_block
    block.rows = int(scenario.rows or 1)
    block.columns = int(scenario.columns or 1)
    block.seed = int(scenario.block_seed or 0)
    block.spacing_x = float(scenario.spacing_x)
    block.spacing_y = float(scenario.spacing_y)
    block.lot_type = str(scenario.lot_type or "ANY")
    block.allowed_presets = scenario.allowed_presets


def _count_roots(metadata_mod) -> int:
    return sum(1 for obj in bpy.data.objects if metadata_mod.is_root_object(obj))


def _count_meshes() -> int:
    return sum(1 for obj in bpy.data.objects if obj.type == "MESH")


def _prepare_thermal_profile(modules: dict[str, Any], scenario: Scenario) -> None:
    if scenario.thermal_profile == "warm":
        modules["materials"].ensure_blockout_materials()


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    p = max(0.0, min(100.0, float(p)))
    rank = (p / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(len(ordered) - 1, lower + 1)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower]) * (1.0 - weight) + float(ordered[upper]) * weight


def _slice_samples_ms(
    timer: StepTimer,
    scenario: Scenario,
    *,
    scheduler_samples_ms: tuple[float, ...] = (),
) -> list[float]:
    if scheduler_samples_ms:
        return [float(sample) for sample in scheduler_samples_ms]
    if scenario.kind == "district":
        samples = list(timer.samples.get("build_building_total", ()))
        if samples:
            return samples
        return list(timer.samples.get("generate_block_total", ()))
    return list(timer.samples.get("build_building_total", ()))


def _time_to_first_visible_root_ms(timer: StepTimer, *, total_ms: float) -> float:
    for _metric_key, _duration_ms, elapsed_ms, root_count in timer.timeline_events:
        if root_count > 0:
            return float(elapsed_ms)
    return float(total_ms)


def _max_sample_for_metrics(timer: StepTimer, metric_keys: tuple[str, ...]) -> float | None:
    longest: float | None = None
    for metric_key in metric_keys:
        samples = timer.samples.get(metric_key, ())
        if not samples:
            continue
        sample_max = max(float(sample) for sample in samples)
        if longest is None or sample_max > longest:
            longest = sample_max
    return longest


def _scheduler_metric_tuple(build_scheduler_mod) -> tuple[float | None, float | None, float | None, tuple[float, ...]]:
    if not hasattr(build_scheduler_mod, "runtime_metrics_snapshot"):
        return None, None, None, ()
    snapshot = build_scheduler_mod.runtime_metrics_snapshot()
    callback_samples = tuple(float(value) for value in snapshot.get("scheduler_callback_samples_ms", ()))
    callback_ms_max = float(snapshot.get("scheduler_callback_ms_max", 0.0)) if callback_samples else None
    callback_ops_max = (
        float(snapshot.get("scheduler_callback_ops_max", 0))
        if snapshot.get("scheduler_callback_op_samples")
        else None
    )
    queue_depth_max = (
        float(snapshot.get("scheduler_queue_depth_max", 0))
        if callback_samples
        else None
    )
    return callback_ms_max, callback_ops_max, queue_depth_max, callback_samples


def _base_progressive_metrics(
    timer: StepTimer,
    scenario: Scenario,
    *,
    total_ms: float,
    build_scheduler_mod=None,
    overrides: dict[str, float | None] | None = None,
) -> dict[str, float | None]:
    scheduler_callback_ms_max, scheduler_callback_ops_max, scheduler_queue_depth_max, scheduler_samples = (
        _scheduler_metric_tuple(build_scheduler_mod)
        if build_scheduler_mod is not None
        else (None, None, None, ())
    )
    slice_samples = _slice_samples_ms(timer, scenario, scheduler_samples_ms=scheduler_samples)
    slice_count = len(slice_samples)
    max_slice_ms = max(slice_samples) if slice_samples else None
    p95_slice_ms = _percentile(slice_samples, 95.0) if slice_samples else None
    preview_author_ms: float | None = 0.0
    if scenario.kind == "selected_edit":
        preview_author_ms = None
    finalize_ms = float(timer.totals.get("build_building_finalize_full", 0.0)) or None
    time_to_finalized_root_ms = float(total_ms)
    if scenario.kind == "selected_edit":
        time_to_finalized_root_ms = None

    metrics: dict[str, float | None] = {
        "preview_author_ms": float(preview_author_ms) if preview_author_ms is not None else None,
        "finalize_ms": float(finalize_ms) if finalize_ms is not None else None,
        "max_slice_ms": float(max_slice_ms) if max_slice_ms is not None else None,
        "p95_slice_ms": float(p95_slice_ms) if p95_slice_ms is not None else None,
        "slice_count": float(slice_count) if slice_count > 0 else None,
        "time_to_first_visible_root_ms": _time_to_first_visible_root_ms(timer, total_ms=total_ms),
        "selected_edit_time_to_first_preview_ms": None,
        "selected_edit_time_to_preview_stable_ms": None,
        "time_to_finalized_root_ms": float(time_to_finalized_root_ms) if time_to_finalized_root_ms is not None else None,
        "scheduler_callback_ms_max": scheduler_callback_ms_max,
        "scheduler_callback_ops_max": scheduler_callback_ops_max,
        "scheduler_queue_depth_max": scheduler_queue_depth_max,
        "longest_finalize_op_ms": _max_sample_for_metrics(timer, FINALIZE_METRIC_KEYS),
        "longest_consolidation_op_ms": _max_sample_for_metrics(timer, CONSOLIDATION_METRIC_KEYS),
        "district_first_visible_root_ms_7x7": None,
        "district_first_finalized_root_ms_7x7": None,
        "district_half_finalized_slots_ms_7x7": None,
        "district_complete_ms_7x7": None,
        "district_preview_wave_complete_ms_7x7": None,
        "district_finalize_wave_complete_ms_7x7": None,
        "exact_spec_first_slot_ms": None,
        "exact_spec_repeat_slot_ms": None,
        "exact_spec_repeat_to_first_ratio_pct": None,
        "exact_spec_reuse_hits": None,
        "exact_spec_reuse_misses": None,
        "plan_building_ms": None,
        "plan_memo_hits": None,
        "plan_memo_misses": None,
    }
    if overrides:
        metrics.update(overrides)
    return metrics


def _sleep_for_scheduler_interval(next_interval: float | None) -> None:
    if next_interval is None:
        return
    time.sleep(max(0.0005, min(0.05, float(next_interval))))


def _scheduler_tick_once(build_scheduler_mod) -> float:
    callback = getattr(build_scheduler_mod, "_timer_callback", None)
    if callback is None:
        ok, message = build_scheduler_mod.flush(force_ready=False)
        if not ok:
            raise RuntimeError(f"Scheduler flush failed: {message}")
        return 0.001
    next_interval = callback()
    return float(next_interval) if next_interval is not None else 0.001


@contextlib.contextmanager
def _instrumented_modules(modules: dict[str, Any], timer: StepTimer):
    originals = {}
    for boundary in INSTRUMENTED_BOUNDARIES:
        owner = modules[boundary.module_key]
        if not hasattr(owner, boundary.attr_name):
            continue
        original = getattr(owner, boundary.attr_name)
        originals[(owner, boundary.attr_name)] = original
        setattr(owner, boundary.attr_name, timer.wrap(boundary.metric_key, original))

    try:
        yield
    finally:
        for (owner, attr), original in originals.items():
            setattr(owner, attr, original)


def _generated_roots(metadata_mod) -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if metadata_mod.is_root_object(obj)]


def _reset_building_runtime_caches(modules: dict[str, Any]) -> None:
    for fn_name in ("reset_exact_spec_reuse_runtime_state", "reset_plan_memo_runtime_state"):
        reset_fn = getattr(modules["building"], fn_name, None)
        if callable(reset_fn):
            reset_fn()


@contextlib.contextmanager
def _exact_duplicate_plan_patch(modules: dict[str, Any], scenario: Scenario):
    duplicate_preset = str(getattr(scenario, "exact_duplicate_preset_id", "") or "").strip()
    if scenario.kind != "district" or not duplicate_preset:
        yield
        return
    block_layout_mod = modules["block_layout"]
    plan_exact_duplicates = getattr(block_layout_mod, "plan_block_exact_duplicates", None)
    if not callable(plan_exact_duplicates):
        raise RuntimeError("block_layout.plan_block_exact_duplicates(...) is not available.")
    original_plan_block = getattr(block_layout_mod, "plan_block")
    duplicate_seed = (
        int(scenario.exact_duplicate_seed)
        if scenario.exact_duplicate_seed is not None
        else int(scenario.block_seed or 0)
    )

    def _patched_plan_block(context):
        return plan_exact_duplicates(
            context,
            preset_id=duplicate_preset,
            duplicate_seed=duplicate_seed,
        )

    setattr(block_layout_mod, "plan_block", _patched_plan_block)
    try:
        yield
    finally:
        setattr(block_layout_mod, "plan_block", original_plan_block)


def _run_building_scenario(modules: dict[str, Any], scenario: Scenario) -> RunResult:
    scene = _reset_scene(modules)
    _reset_building_runtime_caches(modules)
    _prepare_thermal_profile(modules, scenario)
    _apply_building_payload(scene, modules, preset_id=str(scenario.preset_id), seed=int(scenario.seed or 0))
    _apply_scenario_overrides(scene, scenario)
    timer = StepTimer()
    timer.begin_timeline(modules["metadata"])
    if hasattr(modules["build_scheduler"], "reset_runtime_metrics"):
        modules["build_scheduler"].reset_runtime_metrics()
    with _instrumented_modules(modules, timer):
        operator_started = time.perf_counter()
        operator_result = bpy.ops.tbg.generate_building()
        operator_ms = (time.perf_counter() - operator_started) * 1000.0
        if "FINISHED" not in set(operator_result):
            raise RuntimeError(f"{scenario.key}: generate-building operator did not finish ({operator_result}).")
        timer.totals["operator.generate_building_execute"] += operator_ms
        timer.calls["operator.generate_building_execute"] += 1
        timer.samples["operator.generate_building_execute"].append(operator_ms)

        deadline = time.perf_counter() + 90.0
        first_visible_ms: float | None = None
        preview_author_ms: float | None = None
        finalized_ms: float | None = None
        while time.perf_counter() < deadline:
            elapsed_ms = (time.perf_counter() - operator_started) * 1000.0
            roots = _generated_roots(modules["metadata"])
            root = roots[0] if roots else None
            if root is not None and first_visible_ms is None:
                first_visible_ms = float(elapsed_ms)
            if root is not None and bool(root.get("tbg_edit_mode_dirty")) and preview_author_ms is None:
                preview_author_ms = float(elapsed_ms)
            if root is not None and preview_author_ms is not None and not bool(root.get("tbg_edit_mode_dirty")):
                finalized_ms = float(elapsed_ms)
                if not modules["build_scheduler"].has_pending_jobs():
                    break
            next_interval = _scheduler_tick_once(modules["build_scheduler"])
            _sleep_for_scheduler_interval(next_interval)

        if finalized_ms is None:
            raise RuntimeError(f"{scenario.key}: building did not reach finalized root state in time.")

    root_count = _count_roots(modules["metadata"])
    if root_count != 1:
        raise RuntimeError(f"{scenario.key}: expected 1 generated root, got {root_count}")
    if preview_author_ms is None:
        preview_author_ms = first_visible_ms if first_visible_ms is not None else float(finalized_ms)
    finalize_ms = max(0.0, float(finalized_ms) - float(preview_author_ms))
    total_ms = float(finalized_ms)
    progressive = _base_progressive_metrics(
        timer,
        scenario,
        total_ms=total_ms,
        build_scheduler_mod=modules["build_scheduler"],
        overrides={
            "preview_author_ms": float(preview_author_ms),
            "finalize_ms": float(finalize_ms),
            "time_to_first_visible_root_ms": float(first_visible_ms if first_visible_ms is not None else total_ms),
            "time_to_finalized_root_ms": float(finalized_ms),
        },
    )
    return RunResult(
        total_ms=total_ms,
        step_totals_ms=dict(timer.totals),
        step_calls=dict(timer.calls),
        step_samples_ms={key: list(values) for key, values in timer.samples.items()},
        progressive_metrics_ms=progressive,
        root_count=root_count,
        mesh_count=_count_meshes(),
        district_variety_notes=None,
    )


def _run_district_scenario(modules: dict[str, Any], scenario: Scenario) -> RunResult:
    scene = _reset_scene(modules)
    _reset_building_runtime_caches(modules)
    _prepare_thermal_profile(modules, scenario)
    _configure_block(scene, scenario)
    timer = StepTimer()
    timer.begin_timeline(modules["metadata"])
    if hasattr(modules["build_scheduler"], "reset_runtime_metrics"):
        modules["build_scheduler"].reset_runtime_metrics()
    if hasattr(modules["block_layout"], "reset_district_runtime_metrics"):
        modules["block_layout"].reset_district_runtime_metrics()
    snapshot_fn = getattr(modules["block_layout"], "district_runtime_snapshot", None)
    expected_roots = int(scenario.rows or 0) * int(scenario.columns or 0)

    def _coerce_optional_ms(value) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    with _exact_duplicate_plan_patch(modules, scenario):
        with _instrumented_modules(modules, timer):
            operator_started = time.perf_counter()
            operator_result = bpy.ops.tbg.generate_block()
            operator_ms = (time.perf_counter() - operator_started) * 1000.0
            if "FINISHED" not in set(operator_result):
                raise RuntimeError(f"{scenario.key}: generate-block operator did not finish ({operator_result}).")
            timer.totals["operator.generate_block_execute"] += operator_ms
            timer.calls["operator.generate_block_execute"] += 1
            timer.samples["operator.generate_block_execute"].append(operator_ms)

            first_visible_ms: float | None = None
            first_finalized_root_ms: float | None = None
            half_finalized_slots_ms: float | None = None
            preview_wave_complete_ms: float | None = None
            finalize_wave_complete_ms: float | None = None
            district_complete_ms: float | None = None
            runtime_shape = ""
            half_target = int((expected_roots + 1) // 2)
            timeout_seconds = max(180.0, float(expected_roots) * 8.0)
            deadline = time.perf_counter() + timeout_seconds
            while time.perf_counter() < deadline:
                elapsed_ms = (time.perf_counter() - operator_started) * 1000.0
                roots = _generated_roots(modules["metadata"])
                if roots and first_visible_ms is None:
                    first_visible_ms = float(elapsed_ms)
                finalized_root_count = sum(1 for root in roots if not bool(root.get("tbg_edit_mode_dirty")))
                if finalized_root_count > 0 and first_finalized_root_ms is None:
                    first_finalized_root_ms = float(elapsed_ms)
                if half_target > 0 and finalized_root_count >= half_target and half_finalized_slots_ms is None:
                    half_finalized_slots_ms = float(elapsed_ms)
                if (
                    roots
                    and preview_wave_complete_ms is None
                    and len(roots) >= expected_roots
                    and all(bool(root.get("tbg_edit_mode_dirty")) for root in roots)
                ):
                    preview_wave_complete_ms = float(elapsed_ms)
                if (
                    roots
                    and len(roots) >= expected_roots
                    and finalized_root_count >= expected_roots
                    and not modules["build_scheduler"].has_pending_jobs()
                ):
                    finalize_wave_complete_ms = float(elapsed_ms)
                    district_complete_ms = float(elapsed_ms)
                    break

                if callable(snapshot_fn):
                    snapshot = snapshot_fn() or {}
                    status = str(snapshot.get("status", "")).strip().lower()
                    snapshot_runtime_shape = str(snapshot.get("runtime_shape", "")).strip().lower()
                    if snapshot_runtime_shape:
                        runtime_shape = snapshot_runtime_shape
                    snapshot_first_visible = _coerce_optional_ms(snapshot.get("first_visible_root_ms"))
                    snapshot_first_finalized = _coerce_optional_ms(snapshot.get("first_finalized_root_ms"))
                    snapshot_half_finalized = _coerce_optional_ms(snapshot.get("half_finalized_slots_ms"))
                    snapshot_district_complete = _coerce_optional_ms(snapshot.get("district_complete_ms"))
                    snapshot_preview_complete = _coerce_optional_ms(snapshot.get("preview_wave_complete_ms"))
                    snapshot_finalize_complete = _coerce_optional_ms(snapshot.get("finalize_wave_complete_ms"))
                    if first_visible_ms is None and snapshot_first_visible is not None:
                        first_visible_ms = snapshot_first_visible
                    if first_finalized_root_ms is None and snapshot_first_finalized is not None:
                        first_finalized_root_ms = snapshot_first_finalized
                    if half_finalized_slots_ms is None and snapshot_half_finalized is not None:
                        half_finalized_slots_ms = snapshot_half_finalized
                    if preview_wave_complete_ms is None and snapshot_preview_complete is not None:
                        preview_wave_complete_ms = snapshot_preview_complete
                    if snapshot_finalize_complete is not None:
                        finalize_wave_complete_ms = snapshot_finalize_complete
                    if snapshot_district_complete is not None:
                        district_complete_ms = snapshot_district_complete
                    if status == "failed":
                        error_message = str(snapshot.get("error", "")).strip() or "District runtime reported failure."
                        raise RuntimeError(f"{scenario.key}: {error_message}")
                    if (
                        status == "completed"
                        and (district_complete_ms is not None or finalize_wave_complete_ms is not None)
                        and not modules["build_scheduler"].has_pending_jobs()
                    ):
                        if district_complete_ms is None and finalize_wave_complete_ms is not None:
                            district_complete_ms = float(finalize_wave_complete_ms)
                        break

                next_interval = _scheduler_tick_once(modules["build_scheduler"])
                _sleep_for_scheduler_interval(next_interval)

    timeout_snapshot = snapshot_fn() if callable(snapshot_fn) else {}
    if district_complete_ms is None and finalize_wave_complete_ms is not None:
        district_complete_ms = float(finalize_wave_complete_ms)
    if district_complete_ms is None:
        raise RuntimeError(
            f"{scenario.key}: district generation did not reach completion in time "
            f"(status={timeout_snapshot.get('status')}, "
            f"runtime_shape={timeout_snapshot.get('runtime_shape')}, "
            f"preview_completed_slots={timeout_snapshot.get('preview_completed_slots')}, "
            f"finalize_completed_slots={timeout_snapshot.get('finalize_completed_slots')}, "
            f"first_visible_root_ms={timeout_snapshot.get('first_visible_root_ms')}, "
            f"first_finalized_root_ms={timeout_snapshot.get('first_finalized_root_ms')}, "
            f"half_finalized_slots_ms={timeout_snapshot.get('half_finalized_slots_ms')}, "
            f"district_complete_ms={timeout_snapshot.get('district_complete_ms')}, "
            f"preview_wave_complete_ms={timeout_snapshot.get('preview_wave_complete_ms')}, "
            f"finalize_wave_complete_ms={timeout_snapshot.get('finalize_wave_complete_ms')})."
        )
    if not runtime_shape:
        runtime_shape = str(timeout_snapshot.get("runtime_shape", "")).strip().lower()
    if not runtime_shape:
        runtime_shape = "preview_finalize_waves" if preview_wave_complete_ms is not None else "unknown"

    total_ms = float(district_complete_ms)
    root_count = _count_roots(modules["metadata"])
    if root_count != expected_roots:
        raise RuntimeError(f"{scenario.key}: expected {expected_roots} generated roots, got {root_count}")
    roots = _generated_roots(modules["metadata"])
    if any(bool(root.get("tbg_edit_mode_dirty")) for root in roots):
        raise RuntimeError(f"{scenario.key}: district generation finished with dirty preview roots.")

    is_rolling_runtime = runtime_shape == "rolling_preview_finalize"
    preview_author_ms: float | None = None
    finalize_ms: float | None = None
    if not is_rolling_runtime and preview_wave_complete_ms is not None:
        preview_author_ms = float(preview_wave_complete_ms)
        finalize_ms = max(0.0, float(total_ms) - float(preview_wave_complete_ms))
    district_overrides: dict[str, float | None] = {}
    district_overrides["preview_author_ms"] = preview_author_ms
    district_overrides["finalize_ms"] = float(finalize_ms) if finalize_ms is not None else None
    district_overrides["time_to_first_visible_root_ms"] = float(first_visible_ms if first_visible_ms is not None else total_ms)
    district_overrides["time_to_finalized_root_ms"] = float(total_ms)
    if int(scenario.rows or 0) == 7 and int(scenario.columns or 0) == 7:
        district_overrides["district_first_visible_root_ms_7x7"] = float(first_visible_ms if first_visible_ms is not None else total_ms)
        district_overrides["district_first_finalized_root_ms_7x7"] = (
            float(first_finalized_root_ms) if first_finalized_root_ms is not None else None
        )
        district_overrides["district_half_finalized_slots_ms_7x7"] = (
            float(half_finalized_slots_ms) if half_finalized_slots_ms is not None else None
        )
        district_overrides["district_complete_ms_7x7"] = float(total_ms)
        district_overrides["district_preview_wave_complete_ms_7x7"] = (
            float(preview_wave_complete_ms) if (preview_wave_complete_ms is not None and not is_rolling_runtime) else None
        )
        district_overrides["district_finalize_wave_complete_ms_7x7"] = (
            float(finalize_wave_complete_ms)
            if (finalize_wave_complete_ms is not None and not is_rolling_runtime)
            else None
        )
    exact_first_slot_ms = _coerce_optional_ms(timeout_snapshot.get("exact_spec_first_slot_ms"))
    exact_repeat_slot_ms = _coerce_optional_ms(timeout_snapshot.get("exact_spec_repeat_slot_ms"))
    exact_repeat_ratio = _coerce_optional_ms(timeout_snapshot.get("exact_spec_repeat_to_first_ratio"))
    district_overrides["exact_spec_first_slot_ms"] = (
        float(exact_first_slot_ms) if exact_first_slot_ms is not None else None
    )
    district_overrides["exact_spec_repeat_slot_ms"] = (
        float(exact_repeat_slot_ms) if exact_repeat_slot_ms is not None else None
    )
    district_overrides["exact_spec_repeat_to_first_ratio_pct"] = (
        float(exact_repeat_ratio) * 100.0 if exact_repeat_ratio is not None else None
    )
    district_overrides["exact_spec_reuse_hits"] = float(timeout_snapshot.get("exact_spec_reuse_hits", 0))
    district_overrides["exact_spec_reuse_misses"] = float(timeout_snapshot.get("exact_spec_reuse_misses", 0))
    district_overrides["plan_building_ms"] = float(timer.totals.get("build_building_plan", 0.0))
    plan_snapshot_fn = getattr(modules["building"], "plan_memo_runtime_snapshot", None)
    plan_snapshot = plan_snapshot_fn() if callable(plan_snapshot_fn) else {}
    district_overrides["plan_memo_hits"] = float(plan_snapshot.get("hits", 0))
    district_overrides["plan_memo_misses"] = float(plan_snapshot.get("misses", 0))
    progressive = _base_progressive_metrics(
        timer,
        scenario,
        total_ms=total_ms,
        build_scheduler_mod=modules["build_scheduler"],
        overrides=district_overrides,
    )
    planned_frequency = tuple(
        (str(preset_id), int(count))
        for preset_id, count in tuple(timeout_snapshot.get("planned_preset_frequency", ()))
    )
    district_variety_notes: dict[str, Any] = {
        "family_spread_count": int(timeout_snapshot.get("planned_family_spread_count", len(planned_frequency))),
        "preset_frequency": planned_frequency,
        "repeated_neighbor_signatures": int(timeout_snapshot.get("planned_repeated_neighbor_signatures", 0)),
        "office_midrise_share": float(timeout_snapshot.get("planned_office_midrise_share", 0.0)),
        "content_pool_ceiling": dict(timeout_snapshot.get("content_pool_ceiling", {})),
        "resolved_eligible_preset_pool": tuple(timeout_snapshot.get("resolved_eligible_preset_pool", ())),
        "planned_exact_spec_unique_count": int(timeout_snapshot.get("planned_exact_spec_unique_count", 0)),
        "planned_exact_spec_duplicate_slot_count": int(
            timeout_snapshot.get("planned_exact_spec_duplicate_slot_count", 0)
        ),
        "exact_spec_reuse_hits": int(timeout_snapshot.get("exact_spec_reuse_hits", 0)),
        "exact_spec_reuse_misses": int(timeout_snapshot.get("exact_spec_reuse_misses", 0)),
        "exact_spec_first_slot_ms": (
            float(timeout_snapshot.get("exact_spec_first_slot_ms"))
            if timeout_snapshot.get("exact_spec_first_slot_ms") is not None
            else None
        ),
        "exact_spec_repeat_slot_ms": (
            float(timeout_snapshot.get("exact_spec_repeat_slot_ms"))
            if timeout_snapshot.get("exact_spec_repeat_slot_ms") is not None
            else None
        ),
        "exact_spec_repeat_to_first_ratio": (
            float(timeout_snapshot.get("exact_spec_repeat_to_first_ratio"))
            if timeout_snapshot.get("exact_spec_repeat_to_first_ratio") is not None
            else None
        ),
        "plan_building_ms": float(timer.totals.get("build_building_plan", 0.0)),
        "plan_memo_hits": int(plan_snapshot.get("hits", 0)),
        "plan_memo_misses": int(plan_snapshot.get("misses", 0)),
        "runtime_shape": runtime_shape,
        "first_finalized_root_ms": float(first_finalized_root_ms) if first_finalized_root_ms is not None else None,
        "half_finalized_slots_ms": float(half_finalized_slots_ms) if half_finalized_slots_ms is not None else None,
        "district_complete_ms": float(total_ms),
    }
    return RunResult(
        total_ms=total_ms,
        step_totals_ms=dict(timer.totals),
        step_calls=dict(timer.calls),
        step_samples_ms={key: list(values) for key, values in timer.samples.items()},
        progressive_metrics_ms=progressive,
        root_count=root_count,
        mesh_count=_count_meshes(),
        district_variety_notes=district_variety_notes,
    )


def _wait_for_selected_preview(
    selected_tuning_mod,
    build_scheduler_mod,
    scene,
    *,
    started_at: float,
    timeout_seconds: float = 10.0,
) -> tuple[float, float]:
    deadline = time.perf_counter() + float(timeout_seconds)
    first_preview_ms: float | None = None
    preview_stable_ms: float | None = None
    while time.perf_counter() < deadline:
        next_interval = _scheduler_tick_once(build_scheduler_mod)
        root_name = str(getattr(scene, "tbg_selected_root_name", "") or "")
        root = bpy.data.objects.get(root_name) if root_name else None
        if root is not None and bool(root.get("tbg_edit_mode_dirty")) and first_preview_ms is None:
            first_preview_ms = (time.perf_counter() - started_at) * 1000.0
        if first_preview_ms is not None and not selected_tuning_mod.is_rebuild_pending(scene):
            preview_stable_ms = (time.perf_counter() - started_at) * 1000.0
            break
        _sleep_for_scheduler_interval(next_interval)
    if first_preview_ms is None or preview_stable_ms is None:
        raise RuntimeError("Selected-edit preview did not stabilize within timeout.")
    return float(first_preview_ms), float(preview_stable_ms)


def _run_selected_edit_scenario(modules: dict[str, Any], scenario: Scenario) -> RunResult:
    scene = _reset_scene(modules)
    _reset_building_runtime_caches(modules)
    _prepare_thermal_profile(modules, scenario)
    _apply_building_payload(scene, modules, preset_id=str(scenario.preset_id), seed=int(scenario.seed or 0))
    base_spec = modules["specs"].building_spec_from_settings(scene.tbg_building, building_id=None, origin=(0.0, 0.0, 0.0))
    base_root = modules["building"].build_building(bpy.context, base_spec)
    base_root = modules["metadata"].resolve_root_from_object(base_root) or base_root
    modules["selected_tuning"].select_and_bind_root(bpy.context, base_root)
    if not modules["selected_tuning"].refresh_selected_building_binding(bpy.context):
        raise RuntimeError(f"{scenario.key}: failed to bind selected-building proxy")

    selected_settings = scene.tbg_selected_building
    target_width = float(selected_settings.width) + 0.8
    timer = StepTimer()
    timer.begin_timeline(modules["metadata"])
    if hasattr(modules["build_scheduler"], "reset_runtime_metrics"):
        modules["build_scheduler"].reset_runtime_metrics()
    finalize_ms = 0.0
    with _instrumented_modules(modules, timer):
        started = time.perf_counter()
        selected_settings.width = target_width
        trigger_ms = (time.perf_counter() - started) * 1000.0
        timer.totals["selected_edit.trigger_edit"] += trigger_ms
        timer.calls["selected_edit.trigger_edit"] += 1
        timer.samples["selected_edit.trigger_edit"].append(trigger_ms)
        first_preview_ms, preview_stable_ms = _wait_for_selected_preview(
            modules["selected_tuning"],
            modules["build_scheduler"],
            scene,
            started_at=started,
        )
        finalize_started = time.perf_counter()
        finalize_ok, finalize_message = modules["selected_tuning"].apply_selected_building(scene, context=bpy.context)
        if not finalize_ok:
            raise RuntimeError(f"{scenario.key}: selected-edit finalize failed: {finalize_message}")
        finalize_ms = (time.perf_counter() - finalize_started) * 1000.0
    root_count = _count_roots(modules["metadata"])
    if root_count != 1:
        raise RuntimeError(f"{scenario.key}: expected 1 generated root after selected-edit sweep, got {root_count}")

    total_ms = float(preview_stable_ms)
    step_totals_ms = dict(timer.totals)
    step_calls = dict(timer.calls)
    step_samples_ms = {key: list(values) for key, values in timer.samples.items()}
    step_totals_ms["selected_edit_finalize_wall"] = float(finalize_ms)
    step_calls["selected_edit_finalize_wall"] = 1
    step_samples_ms["selected_edit_finalize_wall"] = [float(finalize_ms)]
    progressive = _base_progressive_metrics(
        timer,
        scenario,
        total_ms=total_ms,
        build_scheduler_mod=modules["build_scheduler"],
    )
    progressive["preview_author_ms"] = float(preview_stable_ms)
    progressive["finalize_ms"] = float(finalize_ms)
    progressive["time_to_first_visible_root_ms"] = float(first_preview_ms)
    progressive["selected_edit_time_to_first_preview_ms"] = float(first_preview_ms)
    progressive["selected_edit_time_to_preview_stable_ms"] = float(preview_stable_ms)
    progressive["time_to_finalized_root_ms"] = float(preview_stable_ms + finalize_ms)
    return RunResult(
        total_ms=total_ms,
        step_totals_ms=step_totals_ms,
        step_calls=step_calls,
        step_samples_ms=step_samples_ms,
        progressive_metrics_ms=progressive,
        root_count=root_count,
        mesh_count=_count_meshes(),
        district_variety_notes=None,
    )


def _run_scenario(modules: dict[str, Any], scenario: Scenario) -> RunResult:
    if scenario.kind == "building":
        return _run_building_scenario(modules, scenario)
    if scenario.kind == "selected_edit":
        return _run_selected_edit_scenario(modules, scenario)
    return _run_district_scenario(modules, scenario)


def _aggregate_scenarios(modules: dict[str, Any], scenarios: list[Scenario]) -> list[ScenarioAggregate]:
    aggregates: list[ScenarioAggregate] = []
    for scenario in scenarios:
        runs = [_run_scenario(modules, scenario) for _ in range(max(1, int(scenario.repeats)))]
        aggregates.append(ScenarioAggregate(scenario=scenario, runs=runs))
    return aggregates


def _format_ms(value: float) -> str:
    return f"{value:.2f}"


def _format_share(value: float, total: float) -> str:
    if total <= 1e-9:
        return "0.0%"
    return f"{(value / total) * 100.0:.1f}%"


def _metric_rows(
    aggregate: ScenarioAggregate,
    metrics: tuple[str, ...],
    *,
    sort_descending: bool,
) -> list[tuple[str, float, float, int, str]]:
    rows: list[tuple[str, float, float, int, str]] = []
    total_ms = aggregate.median_total_ms()
    for metric in metrics:
        median_value = aggregate.metric_median_ms(metric)
        median_max_call = aggregate.metric_median_max_call_ms(metric)
        median_calls = aggregate.metric_median_calls(metric)
        if median_calls <= 0:
            continue
        rows.append((metric, median_value, median_max_call, median_calls, _format_share(median_value, total_ms)))
    if sort_descending:
        rows.sort(key=lambda item: item[1], reverse=True)
    return rows


def _parent_rows_for_scenario(aggregate: ScenarioAggregate) -> list[tuple[str, float, float, int, str]]:
    return _metric_rows(
        aggregate,
        PARENT_METRIC_ORDER[aggregate.scenario.kind],
        sort_descending=False,
    )


def _nested_rows_for_scenario(aggregate: ScenarioAggregate) -> list[tuple[str, float, float, int, str]]:
    return _metric_rows(
        aggregate,
        NESTED_METRIC_ORDER,
        sort_descending=True,
    )


def _progressive_rows_for_scenario(aggregate: ScenarioAggregate) -> list[tuple[str, float | None]]:
    return [
        (metric, aggregate.progressive_metric_median(metric))
        for metric in PROGRESSIVE_METRIC_ORDER
    ]


def _markdown_summary_table(aggregates: list[ScenarioAggregate]) -> list[str]:
    lines = [
        "| Scenario | Kind | Thermal Profile | Repeats | Median total ms | Median roots | Median meshes |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for aggregate in aggregates:
        lines.append(
            "| {label} | {kind} | {profile} | {repeats} | {total} | {roots} | {meshes} |".format(
                label=aggregate.scenario.label,
                kind=aggregate.scenario.kind,
                profile=aggregate.scenario.thermal_profile,
                repeats=len(aggregate.runs),
                total=_format_ms(aggregate.median_total_ms()),
                roots=aggregate.median_root_count(),
                meshes=aggregate.median_mesh_count(),
            )
        )
    return lines


def _markdown_metric_table(rows: list[tuple[str, float, float, int, str]]) -> list[str]:
    lines = [
        "| Metric | Median total ms | Median max single call ms | Median calls | Share of scenario |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for metric, median_value, median_max_call, median_calls, share in rows:
        lines.append(
            f"| `{metric}` | {_format_ms(median_value)} | {_format_ms(median_max_call)} | {median_calls} | {share} |"
        )
    return lines


def _markdown_progressive_table(rows: list[tuple[str, float | None]]) -> list[str]:
    lines = [
        "| Progressive Metric | Median value |",
        "| --- | ---: |",
    ]
    for metric, median_value in rows:
        if median_value is None:
            lines.append(f"| `{metric}` | `unavailable` |")
            continue
        lines.append(f"| `{metric}` | {_format_ms(float(median_value))} |")
    return lines


def _markdown_district_variety_notes(notes: dict[str, Any]) -> list[str]:
    preset_frequency = tuple(notes.get("preset_frequency", ()))
    preset_frequency_label = ", ".join(f"{preset_id}:{count}" for preset_id, count in preset_frequency) or "n/a"
    resolved_pool = tuple(notes.get("resolved_eligible_preset_pool", ()))
    resolved_pool_label = ", ".join(str(item) for item in resolved_pool) or "n/a"
    content_pool_ceiling = dict(notes.get("content_pool_ceiling", {}))
    ceiling_pairs = ", ".join(f"{key}:{value}" for key, value in sorted(content_pool_ceiling.items())) or "n/a"
    exact_first_slot_ms = notes.get("exact_spec_first_slot_ms")
    exact_repeat_slot_ms = notes.get("exact_spec_repeat_slot_ms")
    exact_first_label = _format_ms(float(exact_first_slot_ms)) if exact_first_slot_ms is not None else "n/a"
    exact_repeat_label = _format_ms(float(exact_repeat_slot_ms)) if exact_repeat_slot_ms is not None else "n/a"
    exact_ratio = notes.get("exact_spec_repeat_to_first_ratio")
    exact_ratio_label = (
        f"{float(exact_ratio) * 100.0:.1f}%"
        if exact_ratio is not None
        else "n/a"
    )
    first_finalized_ms = notes.get("first_finalized_root_ms")
    first_finalized_label = _format_ms(float(first_finalized_ms)) if first_finalized_ms is not None else "n/a"
    half_finalized_ms = notes.get("half_finalized_slots_ms")
    half_finalized_label = _format_ms(float(half_finalized_ms)) if half_finalized_ms is not None else "n/a"
    district_complete_ms = notes.get("district_complete_ms")
    district_complete_label = _format_ms(float(district_complete_ms)) if district_complete_ms is not None else "n/a"
    return [
        "District variety notes",
        "",
        f"- Runtime shape: `{str(notes.get('runtime_shape', 'n/a') or 'n/a')}`",
        f"- Family spread count: `{int(notes.get('family_spread_count', 0))}`",
        f"- Preset frequency: `{preset_frequency_label}`",
        f"- Repeated-neighbor signature count: `{int(notes.get('repeated_neighbor_signatures', 0))}`",
        f"- Office/midrise share: `{float(notes.get('office_midrise_share', 0.0)) * 100.0:.1f}%`",
        f"- Resolved eligible preset pool: `{resolved_pool_label}`",
        f"- Current content ceiling (explicit): `{ceiling_pairs}`",
        f"- First finalized root ms: `{first_finalized_label}`",
        f"- Half finalized slots ms: `{half_finalized_label}`",
        f"- District complete ms: `{district_complete_label}`",
        f"- Planned exact-spec unique slots: `{int(notes.get('planned_exact_spec_unique_count', 0))}`",
        f"- Planned exact-spec duplicate slots: `{int(notes.get('planned_exact_spec_duplicate_slot_count', 0))}`",
        f"- Exact-spec reuse hits/misses: `{int(notes.get('exact_spec_reuse_hits', 0))}/{int(notes.get('exact_spec_reuse_misses', 0))}`",
        f"- Exact-spec first-slot median ms: `{exact_first_label}`",
        f"- Exact-spec repeat-slot median ms: `{exact_repeat_label}`",
        f"- Exact-spec repeat-to-first ratio: `{exact_ratio_label}`",
        f"- Plan-building total ms: `{_format_ms(float(notes.get('plan_building_ms', 0.0)))}`",
        f"- Plan-memo hits/misses: `{int(notes.get('plan_memo_hits', 0))}/{int(notes.get('plan_memo_misses', 0))}`",
        "",
    ]


def _render_report(
    *,
    aggregates: list[ScenarioAggregate],
    warm_repeats: int,
    cold_repeats: int,
    include_stress: bool,
    include_content_expansion: bool,
    command_line: str,
    baseline_commit: str,
    worktree_dirty: bool,
    output_path: Path,
) -> str:
    lines = [
        "# Perf Baseline Results",
        "",
        "Generated by `tools/benchmark_generation.py` from a headless Blender run.",
        "",
        "## Run Metadata",
        f"- Commit hash: `{baseline_commit}`",
        f"- Worktree dirty during capture: `{'yes' if worktree_dirty else 'no'}`",
        f"- Blender version: `{bpy.app.version_string}`",
        f"- Harness path: `{REPO_ROOT / 'tools' / 'benchmark_generation.py'}`",
        f"- Output path: `{output_path}`",
        f"- Command: `{command_line}`",
        f"- Scene reset method: `{SCENE_RESET_METHOD}`",
        f"- Warm repeats per scenario: `{warm_repeats}`",
        f"- Cold repeats per scenario: `{cold_repeats}`",
        f"- Larger stress district included: `{'yes' if include_stress else 'no'}`",
        f"- Content-expansion district scenarios included: `{'yes' if include_content_expansion else 'no'}`",
        "- Progressive metrics show `unavailable` when a metric does not apply to the current runtime path.",
        "",
        "## Scenario Definitions",
    ]
    for aggregate in aggregates:
        lines.append(f"- `{aggregate.scenario.key}`: {aggregate.scenario.description()}")

    lines.extend(
        [
            "",
            "## Scenario Medians",
            *_markdown_summary_table(aggregates),
            "",
            "## Per-Scenario Direct Timers",
            "",
        ]
    )
    for aggregate in aggregates:
        parent_rows = _parent_rows_for_scenario(aggregate)
        nested_rows = _nested_rows_for_scenario(aggregate)
        lines.extend(
            [
                f"### {aggregate.scenario.key}",
                "",
                "Parent totals",
                "",
                *_markdown_metric_table(parent_rows),
                "",
                "Nested direct timers",
                "",
                *_markdown_metric_table(nested_rows),
                "",
                "Progressive metrics",
                "",
                *_markdown_progressive_table(_progressive_rows_for_scenario(aggregate)),
                "",
            ]
        )
        district_variety_notes = aggregate.district_variety_notes()
        if district_variety_notes:
            lines.extend(_markdown_district_variety_notes(district_variety_notes))
        lines.extend(
            [
                f"- Repeat totals ms: `{', '.join(_format_ms(value) for value in aggregate.repeat_totals_ms())}`",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure luarch generation timings in headless Blender.")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help="Warm repeat count per scenario. Default: %(default)s")
    parser.add_argument(
        "--cold-repeats",
        type=int,
        default=1,
        help="Cold repeat count per scenario. Default: %(default)s",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Markdown report path. Default: docs/tasks/perf_refactor_20260407/perf_phase0_baseline_20260407.md",
    )
    parser.add_argument(
        "--include-stress",
        action="store_true",
        help="Include an additional 5x5 district stress case (2x2 and 4x4 are always included).",
    )
    parser.add_argument(
        "--include-content-expansion",
        action="store_true",
        help="Include additive 3x3 residential/commercial district scenarios that exercise the expanded late block pools.",
    )
    parser.add_argument(
        "--scenario-key",
        action="append",
        default=[],
        help="Optional scenario key filter (supports multiple flags). Matches exact key before thermal suffix, or full profiled key.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    output_path = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    modules = _load_modules()
    warm_repeats = max(1, int(args.repeats))
    cold_repeats = max(1, int(args.cold_repeats))
    scenarios = _scenario_definitions(
        bool(args.include_stress),
        bool(args.include_content_expansion),
        warm_repeats=warm_repeats,
        cold_repeats=cold_repeats,
    )
    scenarios = _filter_scenarios(scenarios, list(args.scenario_key or []))
    aggregates = _aggregate_scenarios(modules, scenarios)
    content = _render_report(
        aggregates=aggregates,
        warm_repeats=warm_repeats,
        cold_repeats=cold_repeats,
        include_stress=bool(args.include_stress),
        include_content_expansion=bool(args.include_content_expansion),
        command_line=" ".join(shlex.quote(part) for part in sys.argv),
        baseline_commit=_current_commit_hash(),
        worktree_dirty=_is_worktree_dirty(),
        output_path=output_path,
    )
    _write_report(output_path, content)
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(_blender_cli_args()))
