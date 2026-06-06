# Architecture Overview

LuArch is organized around a few source-of-truth boundaries.

## Main Flow

```text
presets -> BuildingSpec -> generator -> metadata -> validation -> export
```

## Key Areas

- `presets.py` and `presets/buildings.json`: preset loading and deterministic randomized payloads.
- `generator/`: building layout, facade, roof, wall, material, and district generation.
- `metadata.py`: root metadata and stored spec handling.
- `generation_summary.py`: generated building summary facts.
- `services/validation*.py`: validation fact collection and rule checks.
- `export_rbxmx.py`: RBXMX sidecar serialization.
- `plugin/`: optional Roblox Studio post-processor.

## Design Principles

- Deterministic preset + seed behavior.
- Editable generated output.
- Validation before export.
- Render geometry and runtime metadata are separate.
- Runtime/export contracts should fail closed instead of guessing.

