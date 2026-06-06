# Release Preparation Report

Date: 2026-06-06

## Summary

- Created a clean review-ready repository from the local LuArch workspace.
- Copied the Blender addon into a package directory: `luarch/`.
- Removed local caches, generated exports, `.claude-out`, `.exports`, `.DS_Store`, and private working-tree artifacts from the public package.
- Replaced public-risk addon author metadata with a neutral maintainer name.
- Replaced local absolute live-smoke `.blend` paths with `examples/live_smoke.blend`.
- Added root OSS documentation: README, GPL-3.0 license, contributing guide, changelog, security policy.
- Added public docs for quickstart, validation, export pipeline, architecture, roadmap, publishing, and release notes.
- Captured final README media into `docs/media/hero-wide.png`, `docs/media/gallery-grid-3x3.png`, and `docs/media/plugin-icon.png`.
- Kept only final PNG media in the repository; generated gallery source cards are temporary build artifacts.
- Added SVG fallback/diagram media.
- Added release builder and Blender install smoke scripts.
- Built `dist/luarch-v0.2.0.zip`.
- Initialized git, committed the public repository, and tagged `v0.2.0`.

## Verification

- `python3 -m compileall luarch` -> PASS.
- `python3 scripts/build_release.py` -> PASS.
- `unzip -l dist/luarch-v0.2.0.zip` -> PASS; release zip contains only the addon package.
- Release zip audit for `__pycache__`, `.pyc`, `.DS_Store`, `.exports`, `.claude-out`, and private local paths -> PASS.
- Public tree audit for private local paths -> PASS.
- Blender 4.5.3 background install smoke using isolated `BLENDER_USER_CONFIG` and `BLENDER_USER_SCRIPTS` -> PASS; addon installed, enabled, and registered `Scene.tbg_building` / `Scene.tbg_block`.
- Blender background landing media capture -> PASS; wrote `docs/media/hero-wide.png` and `docs/media/gallery-grid-3x3.png`.

## Git State

- Branch: `main`
- Commit: current `main` HEAD
- Tag: `v0.2.0`
- Release asset: `dist/luarch-v0.2.0.zip`

## Remaining External Steps

- Create a private GitHub repository for visual review.
- Add it as `origin` and push `main` plus tag `v0.2.0`.
- Create a private GitHub release and upload `dist/luarch-v0.2.0.zip`.
- After owner approval, switch the repository to public.
- Review repository visibility and release settings before making the repository public.
