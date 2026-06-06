# Quick Start

This guide walks through the basic Blender workflow.

## 1. Install

1. Download the release zip.
2. In Blender, open `Edit -> Preferences -> Add-ons`.
3. Click `Install...`.
4. Select the zip.
5. Enable `LuArch`.

## 2. Generate a Building

1. Open the 3D View sidebar.
2. Select the `LuArch` tab.
3. In `Single Building`, choose a preset.
4. Click `Randomize Settings` for a deterministic variant.
5. Click `Generate Building`.

The addon creates a generated root object and child meshes for walls, openings, roof elements, doors, trims, and runtime/export metadata.

## 3. Edit the Selected Building

Select a generated building root or one of its children. Supported settings can be adjusted from the sidebar.

Use:

- `Commit Selected Edits` to finalize selected changes.
- `Reset Selected from Stored Spec` to rebuild from the stored spec.
- `Toggle Walls` to inspect interior/traversal shapes.
- `Validate Selected` before export.

## 4. Export

1. Select the generated building.
2. Pick an export folder.
3. Click `Quick Export Selected`.

The export writes:

- an FBX render mesh file;
- an RBXMX sidecar file for the optional Roblox Studio pipeline.

## 5. Validate Before Shipping

Run `Validate Selected` before export. Validation is the gate that catches stale metadata, unsupported runtime payloads, and export-readiness problems.

