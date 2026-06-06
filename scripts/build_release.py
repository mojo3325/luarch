#!/usr/bin/env python3
from __future__ import annotations

import argparse
import zipfile
from ast import literal_eval
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "luarch"
DIST = ROOT / "dist"


EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    ".claude-out",
    ".orch",
    ".exports",
    "dist",
    "build",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".blend1",
    ".blend2",
}


def should_include(path: Path) -> bool:
    parts = set(path.parts)
    if parts.intersection(EXCLUDE_DIRS):
        return False
    if path.name == ".DS_Store":
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def package_version() -> str:
    init_path = PACKAGE / "__init__.py"
    for line in init_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith('"version"'):
            value = stripped.split(":", 1)[1].strip().rstrip(",")
            version_tuple = literal_eval(value)
            return ".".join(str(part) for part in version_tuple)
    raise RuntimeError("Could not find bl_info version in luarch/__init__.py")


def build_release(version: str) -> Path:
    DIST.mkdir(exist_ok=True)
    output = DIST / f"luarch-v{version}.zip"
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if not path.is_file() or not should_include(path.relative_to(ROOT)):
                continue
            archive.write(path, path.relative_to(ROOT))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Blender-installable LuArch release zip.")
    parser.add_argument("--version", default=package_version(), help="Version suffix for the release archive.")
    args = parser.parse_args()

    output = build_release(str(args.version))
    print(output)


if __name__ == "__main__":
    main()
