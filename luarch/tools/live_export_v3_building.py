from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import bpy

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import reliability_phase_gate as gate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and quick-export a fresh V3 building for Studio smoke.")
    parser.add_argument("--preset", default="townhouse")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", required=True)
    return parser.parse_args(gate._blender_cli_args())


def main() -> None:
    args = _parse_args()
    out_dir = Path(args.out).expanduser().resolve(strict=False)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    modules = gate._load_modules()
    scene = gate._reset_scene(modules)
    sample = gate.Sample(
        sample_id=f"{args.preset}_{args.seed}",
        preset_id=str(args.preset),
        seed=int(args.seed),
        scene_overrides={},
        access_class="live_export",
        export_smoke=True,
        expected={},
    )
    gate._apply_building_payload(scene, modules, sample)
    generate_result = bpy.ops.tbg.generate_building("EXEC_DEFAULT")
    if "FINISHED" not in generate_result:
        raise RuntimeError(f"Generate failed: {sorted(generate_result)}")
    success, message = modules["build_scheduler"].flush(force_ready=True)
    if not success:
        raise RuntimeError(f"Queued generate failed: {message}")

    root = gate._require_single_root(modules["metadata"])
    issues = modules["validation"].validate_root(root)
    if issues:
        raise RuntimeError("Validation failed before export: " + " | ".join(str(issue) for issue in issues))

    scene.tbg_building.quick_export_directory = str(out_dir) + "/"
    gate._select_root(root)
    export_result = bpy.ops.tbg.quick_export_building("EXEC_DEFAULT")
    if "FINISHED" not in export_result:
        raise RuntimeError(f"Quick export failed: {sorted(export_result)}")

    exports = sorted(path.name for path in out_dir.iterdir() if path.is_file())
    sidecars = [path for path in out_dir.glob("*.rbxmx")]
    fbxs = [path for path in out_dir.glob("*.fbx")]
    if len(sidecars) != 1 or len(fbxs) != 1:
        raise RuntimeError(f"Expected one FBX and one RBXMX, got files={exports}")
    text = sidecars[0].read_text(encoding="utf-8", errors="ignore")
    summary = {
        "preset": args.preset,
        "seed": args.seed,
        "root": root.name,
        "files": exports,
        "sidecar": str(sidecars[0]),
        "fbx": str(fbxs[0]),
        "has_authored_wall_cells": "AUTHORED_WALL_CELLS" in text,
        "has_v3_payload": "VOXEL_WALL_CELLS_V3" in text or "3.0.0" in text,
        "has_roblox_part_texture_v1": "ROBLOX_PART_TEXTURE_V1" in text,
        "has_solid_color_v1": "SOLID_COLOR_V1" in text,
    }
    (out_dir / "live_export_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
