# TBG Building Post Processor

Studio plugin stays one physical file: `plugin/TBG_BuildingPostProcessor.plugin.lua`.
The fenced contract block between `BEGIN TBG CONTRACT SYNC` / `END TBG CONTRACT SYNC` is generated from `export_contract.py` via `tools/sync_plugin_contract.py` and must not be hand-edited.

Local Studio install must have exactly one active copy: `~/Documents/Roblox/Plugins/TBG_BuildingPostProcessor.plugin.lua`. Do not also install the same file under `~/Library/Application Support/Roblox/Plugins`, and do not keep legacy `TBG_BuildingPostProcessor.lua` in an active Plugins folder, otherwise Roblox Studio registers duplicate toolbar buttons.

The plugin is a fail-closed importer/post-processor. It consumes Blender-authored runtime data and never repairs missing collision, infers collision from render meshes, or redesigns the building in Studio.

## Source of truth

- LuArch authors render meshes, primitive sidecar payloads, lights, and the RBXMX destruction seed.
- `Quick Export Selected` writes:
  - `TBG_Building_<BuildingId>.fbx`
  - `TBG_Building_<BuildingId>.rbxmx`
- FBX stays render-only for destructible wall buckets.
- RBXMX carries `__TBG_Sidecar__<BuildingId>` with:
  - `Folder "__Contract"`
  - `Part "__AuthorRoot"`
  - `Folder "Collision"`
  - `Folder "Lights"`
  - `Folder "DestructionSeed"`

## Contract and pipeline

- Current `ExportContractVersion`: `6.2.0`
- Current destruction `SeedContractVersion`: `5.0.0`
- Current `DestructionMode`: `VOXEL_WALL_CELLS_V3`
- Current payload kind/version: `AUTHORED_WALL_CELLS` / `3.0.0`
- `RenderAnchorBasis = RENDER_BOUNDS_CENTER`
- `RenderAnchorToAuthorRoot` is the authoritative offset from render bounds center to author root.
- `AuthorRootScale` is the authoritative uniform Blender root scale used to materialize V3 wall cells at FBX-imported world size.
- `RenderMeshCount`, `CollisionCount`, `LightCount`, and `RenderBoundsSize` are import-boundary preflight facts.

The plugin runs one obvious pipeline:
- `resolve -> snapshot -> preflight -> attach sidecar -> sanitize/stash -> report`

Current logical sections inside the one-file plugin:
- contract sync + policy
- model resolution + snapshots
- contract preflight + diagnostics
- sidecar attach + runtime swap
- V3 authored wall-cell decode/materialization
- render sanitization + marker stash
- ui status reporting

## What the plugin trusts from Blender

- `AUTHORED_WALL_CELLS` is the only destructible wall truth.
- One V3 `cells[]` record becomes one anchored Roblox `Part` under `__TBG_Destruction/Collision/<group_id>/Cell_<cell_id>`.
- V3 group metadata controls material family, optional style/color, and zero-child material-style projection.
- Collision role names and light role names are authoritative for the supported export contract.
- Blender validation is the semantic gate.
- Render meshes are visuals, not gameplay collision.

## What the plugin still preflights in Studio

- Exactly one imported building model is selected.
- The selected render model resolves to one `BuildingId`.
- The selected model has render `MeshPart`s and is not the temporary sidecar model.
- A matching sidecar exists in the DataModel.
- Required sidecar folders, counts, bounds, alignment data, and supported payload folders match the selected render model.
- Destruction seed transport is complete, ordered, within chunk/JSON budgets, and has V3 contract values.
- The decoded V3 payload has valid groups/cells, exact group cell counts, no positive-volume overlaps, and authored cell count within runtime budget.
- Fresh V3 groups must use zero-child projections (`MATERIAL_VARIANT_STYLE_V1` or `SOLID_COLOR_V1`); retired `ROBLOX_PART_TEXTURE_V1` payloads are blocked before runtime mutation.
- One structured preflight snapshot is shared by diagnostics, sanitize, and attach so the plugin does not rescan descendants after preflight.

If preflight fails:
- no runtime swap happens
- no render sanitization happens
- no markers are moved
- the widget shows a short blocker summary
- Output gets the full diagnostic report plus the action text:
  - `Run Blender Validate Selected, regenerate/re-export, then run the plugin again.`

## Runtime result

After a successful sidecar attach/setup:
- `__TBG_Runtime` is created under the render model
- runtime sidecar collision/lights remain attached from the imported payload
- render meshes become visual-only except approved non-destructible collidable buckets and named door leaves
- imported `Section_Openings_WindowFill` / `OWF` render parts are forced back to the Blender `TBG_WindowFill` projection (`SmoothPlastic`, descriptor-blue color, no `MaterialVariant`) so BRICK/WOOD runtime wall appearance cannot recolor closed windows
- V3 wall runtime lives only under `__TBG_Destruction/Collision`
- each V3 cell Part carries canonical `TBG_VoxelWall*` attributes and the `Destructible` tag
- V3 cell Parts get zero `Texture` children and keep `TBG_VoxelWallTextureKey` for diagnostics/future visual overlays
- named render door leaves `*_Door_Main`, `*_Door_Rear`, and `*_Door_RoofExit` stay collidable
- source markers are stashed under `__TBG_SourceMarkers`
- the render model gets:
  - `TBG_BuildingId`
  - `TBG_RuntimeContractVersion`
  - `TBG_StructureMode = DESTRUCTIBLE_PLUGIN_FIRST`

## Route policy

- Only supported wall runtime path: matching V3 sidecar attach with `AUTHORED_WALL_CELLS`.
- Rejected paths: V1/V2 wall payloads, retired `ROBLOX_PART_TEXTURE_V1`, marker conversion, repair logic, render-derived collision fallback, legacy marker auto-heal, and any path that creates per-cell Texture children.
