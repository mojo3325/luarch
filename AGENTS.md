# LuArch -- AI Assistant Guide

This document is the high-level operating guide for AI agents working on the LuArch Blender addon. It exists so agents can contribute safely without guessing project boundaries, release rules, or validation expectations.

For implementation details, inspect the code first. If a future `TDD.md` or equivalent technical design document exists, treat it as the detailed source of truth for module contracts and budgets.

## 0) Project Context

- `luarch` is a Blender 4.5+ addon for procedural low-poly tactical building generation.
- Generation is preset-driven and seed-backed, so variants must be reproducible.
- Buildings are meant to be editable in Blender and useful for game-engine workflows.
- The public repository includes addon source, README media, release packaging, documentation, and GitHub project hygiene files.

## 1) AI Role And Boundaries

Agents may:

- inspect and explain addon code;
- improve documentation and README media references;
- implement scoped Python changes;
- update release packaging;
- review generated artifacts for leakage, broken links, and installability.

Agents must not:

- turn LuArch into a generic 3D assistant;
- add telemetry, activation, online checks, or obfuscated payloads;
- commit local `.blend` files, generated caches, private screenshots, or private project paths;
- invent release claims that were not verified;
- change public behavior without updating docs and verification notes.

## 2) Technical Stack

- Language: Python 3.10+ for the Blender addon.
- Runtime: Blender 4.5+.
- Primary APIs: Blender data API, `bmesh`, and addon registration APIs.
- `bpy.ops` should be used only when the data API is not a reasonable fit.
- Packaging is handled by `scripts/build_release.py`.

## 3) Repository Structure

```text
luarch/
  __init__.py                 addon registration
  properties.py               Blender scene/property definitions
  constants.py                shared constants and enum values
  presets.py                  preset loading and randomization data
  metadata.py                 generated root metadata
  generator/                  building generation pipeline
  operators/                  Blender operator wrappers
  services/                   validation, cleanup, scheduling
  ui/                         sidebar panels
docs/
  media/                      README images and final public media
  quickstart.md               user workflow
  export-pipeline.md          export notes
  validation.md               validation notes
scripts/
  build_release.py            release zip builder
```

## 4) User Workflow

1. Install and enable the addon in Blender.
2. Select a building preset.
3. Randomize or configure settings.
4. Generate a building.
5. Inspect and tune the result.
6. Use wall visibility / interior views where available.
7. Validate the generated building before export.
8. Build the release zip only after local checks pass.

## 5) Core Principles

**Determinism:** preset + seed behavior must remain reproducible.

**Readable low-poly output:** silhouettes, broad value grouping, and clean geometry matter more than noisy detail.

**Editable authoring:** generated buildings should remain understandable in Blender, not become opaque one-off artifacts.

**Validation as a gate:** validation is not optional decoration. If a change affects generation, export, naming, metadata, or structure, verification must cover it.

**Simple ownership:** prefer small, direct changes over broad abstractions. If code becomes longer and more fragile without a correctness gain, the change is suspect.

## 6) Blender / MCP Discipline

When working through Blender automation or MCP:

1. Inspect scene state before acting.
2. Inspect object data before modifying generated roots, collections, or meshes.
3. Never assume current mode, selection, active object, camera, or viewport state.
4. Apply risky changes in small steps and verify after each meaningful operation.
5. Capture visual proof after substantial geometry or material changes.
6. Do not close unrelated Blender windows or touch scenes that are not part of this repository's workflow.

If Blender is unavailable, complete static checks and state clearly that live viewport verification was not run.

## 7) Shared Contracts

Several contracts connect generation, validation, documentation, and release packaging:

- **Preset payloads:** preset names, defaults, ranges, and seed behavior must stay coherent.
- **Root metadata:** generated roots should keep enough metadata for inspection and future regeneration workflows.
- **Object naming:** generated collections and objects need stable, readable names for cleanup, validation, and export.
- **Wall visibility / interior inspection:** features that hide walls or expose interiors must preserve stair, room, and roof readability.
- **Release package shape:** release zips must install as a Blender addon without extra wrapper folders or stale names.

Do not change one side of a contract without checking the affected modules, README, validation docs, and release script.

## 8) Source Of Truth

- Code is the primary source of truth when docs drift.
- `luarch/presets.py` and related preset data define generation options.
- `luarch/metadata.py` defines generated-root metadata behavior.
- `luarch/services/validation.py` defines the validation gate.
- `README.md` and `docs/` define public-facing claims.
- `scripts/build_release.py` defines package layout.

If a future `TDD.md` exists, treat it as the single technical design source of truth and update it before broad architectural changes.

## 9) Agent Orchestration Workflow

Use AI agents deliberately:

- `explorer`: read-only research, call-site mapping, file ownership, evidence collection.
- `planner`: decision-complete plans for larger or risky changes.
- `fast_coder`: scoped implementation when the plan is clear.
- `critical_judge`: crash, data-loss, packaging, and release-blocking review.
- `debt_judge`: simplification review and overengineering detection.
- `mental_judge`: scenario-based logic review when runtime behavior is subtle.
- `done_judge`: final check against the requested outcome.

Fan-out/fan-in rules:

1. Split only independent work into agents.
2. Give every agent a rich prompt: goal, scope, constraints, exact files, output format, and stop condition.
3. Keep research read-only unless implementation is explicitly required.
4. Do not let two agents edit the same file in parallel.
5. The orchestrator must triage agent results; judge reports are evidence, not automatic commands.
6. Close the loop with verification before reporting completion.

Project orchestration rules:

- No-regression is more important than refactor aesthetics.
- Prefer the simplest change that fixes the root cause.
- Do not hide bugs behind fallback geometry, validator bypasses, or extra state layers.
- If a visual issue survives several attempts, stop guessing and compare the broken path against the nearest working generator path.
- If upstream planning or core logic is proven green, the next diff must target the real downstream owner shown by evidence.
- Keep durable plans and review notes useful; remove stale temporary notes after the initiative is complete.

## 10) Planning Artifact Rules

- Keep durable plans and review notes under `docs/` only when they are useful to future maintainers.
- Do not commit private orchestration transcripts, throwaway scratch files, or internal review drafts.
- If user decisions affect implementation, preserve them as explicit source-of-truth notes in the relevant plan or report.

## 11) Verification Doctrine

Before release-facing changes:

```bash
python3 -m compileall luarch scripts
python3 scripts/build_release.py
unzip -l dist/luarch-v0.2.0.zip
```

For README/media changes:

- verify every referenced image exists;
- inspect the rendered README on GitHub after push;
- keep only final approved PNG/JPG media;
- do not commit temporary renders.

For generation changes:

- run compile checks;
- run addon-level smoke checks when Blender is available;
- visually inspect representative generated buildings;
- do not claim live visual verification if only static checks ran.

For high-risk generation changes, use an observe -> change -> verify loop:

1. Capture the current failing or target case.
2. Make the smallest owner-focused change.
3. Run static checks.
4. Validate in Blender when possible.
5. Capture visual proof.
6. Record remaining issues before starting the next change.

Headless checks do not replace visual proof when the task is about form, lighting, readability, interiors, wall visibility, openings, stairs, or roof access.

## 12) Release Rules

- Repository history should stay clean and understandable.
- Release zips should contain installable addon files only.
- Do not leave old release zips, caches, or local scratch files in the repository unless intentionally tracked.
- Keep repository private until final visual review is complete.
- Before making public, run a leakage audit for private paths, internal planning text, and stale repository names.

## 13) Development Principles

- Keep solutions simple.
- Reuse existing generator structure before adding new abstractions.
- Prefer explicit data flow over implicit global state.
- Keep module boundaries clear: operators and UI are thin wrappers; generator and services own domain behavior.
- Preserve deterministic preset + seed behavior.
- Keep geometry budget and object count reasonable for game-engine use.
- Use Blender data API and `bmesh` over careless `bpy.ops`.
- Treat facts, code, and visual proof as stronger than guesses.

## 14) Assistant Behavior

- Inspect before changing.
- Prefer root-cause fixes over fallback patches.
- Avoid speculative rewrites.
- Keep communication concise and factual.
- If the user writes in Russian, answer in Russian.
- If a task depends on missing product intent, ask; if it depends on repository facts, inspect first.
