#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

import bpy


def main() -> None:
    release_zip = Path(os.environ["LUARCH_RELEASE_ZIP"]).resolve()
    if not release_zip.exists():
        raise FileNotFoundError(release_zip)

    bpy.ops.preferences.addon_install(filepath=str(release_zip), overwrite=True)
    bpy.ops.preferences.addon_enable(module="luarch")

    addon = bpy.context.preferences.addons.get("luarch")
    if addon is None:
        raise RuntimeError("luarch addon was not enabled")

    scene = bpy.context.scene
    if not hasattr(scene, "tbg_building"):
        raise RuntimeError("Scene.tbg_building was not registered")
    if not hasattr(scene, "tbg_block"):
        raise RuntimeError("Scene.tbg_block was not registered")

    print("SMOKE_INSTALL_OK")


if __name__ == "__main__":
    main()

