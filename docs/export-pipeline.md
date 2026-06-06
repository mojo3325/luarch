# Export Pipeline

LuArch keeps visual meshes and runtime metadata separate.

## Blender Output

The Blender addon authors:

- visible low-poly render geometry;
- materials and atlas metadata;
- building root metadata;
- validation facts;
- export contract data;
- runtime sidecar data.

## Quick Export

`Quick Export Selected` writes:

- `TBG_Building_<id>.fbx`
- `TBG_Building_<id>.rbxmx`

The FBX is the render mesh. The RBXMX is the sidecar contract used by the optional Roblox Studio post-processor.

## Optional Roblox Studio Plugin

The included Studio plugin is optional. It consumes the sidecar, checks the contract, attaches runtime data, and prepares the imported building for Roblox-side use.

The plugin is intentionally fail-closed: if required sidecar data is missing or stale, it reports the blocker instead of guessing or repairing from render meshes.

## Why This Split Exists

Render meshes are visuals. Runtime collision, destruction, markers, and lights need their own source of truth. Keeping them separate makes validation stricter and export behavior easier to reason about.

