# LuArch Agent Guide

This repository is maintained with AI-assisted development. Agents are expected to work like disciplined engineering collaborators: inspect first, change second, verify before reporting.

## Project Context

LuArch is a Blender addon for generating procedural low-poly tactical buildings. The repository contains the addon source, documentation, release packaging, and media used by the GitHub README.

Primary workflows:

- Generate editable building variants from presets and seeds.
- Keep README media and release artifacts polished for open-source review.
- Maintain deterministic generation, validation, and export behavior.

## Agent Roles

- `explorer`: read-only investigation, file mapping, usage tracing, and evidence gathering.
- `planner`: decision-complete implementation plans for larger changes.
- `fast_coder`: scoped implementation once the plan is clear.
- `critical_judge`: crash, data-loss, packaging, or release-blocking review.
- `debt_judge`: simplification review and overengineering checks.
- `done_judge`: final DoD verification against the original request.

Use fan-out only when the work splits cleanly. Keep prompts specific: goal, scope, constraints, output format, relevant file paths, and stop condition.

## Development Rules

- Preserve deterministic preset and seed behavior.
- Do not add online checks, telemetry, activation, or generated binary payloads.
- Do not commit temporary Blender caches, local screenshots, or private project files.
- Keep release history clean: one meaningful commit per publication batch.
- Prefer Blender data API and clear Python over broad rewrites.
- Keep public docs understandable to a reviewer who has never seen the project.

## Verification

Run before release changes:

```bash
python3 -m compileall luarch scripts
python3 scripts/build_release.py
```

For visual/media changes, inspect README rendering locally or on GitHub after push.

## Release Checklist

- README images load.
- Release zip contains only final addon files.
- `rg` audit is clean for private paths and internal review notes.
- Repository remains private until visual review is complete.
