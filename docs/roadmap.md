# Roadmap

LuArch is early, but the repository is maintained as a real open-source Blender addon: installable release zips, reproducible media, validation gates, issue triage, and a documented export pipeline.

## Current Focus

- Keep the release zip installable in Blender 4.5+.
- Improve README and quickstart media with real generated output.
- Keep validation/export documentation aligned with the addon UI.
- Track reproducible bugs through GitHub Issues.
- Keep the optional Roblox Studio post-processor documented as an optional workflow, not a required dependency.

## Near Term: v0.2.x

- Add a Blender extension manifest when the packaging target is finalized.
- Add more focused smoke tests for generation, validation, and export.
- Document common validation failures and fixes with screenshots.
- Add a short Studio post-processor walkthrough.
- Add small example payloads/scenes that are safe to publish.
- Improve preset browser documentation and preset naming.

## Medium Term

- More building archetypes and preset families.
- More interior/cutaway examples.
- Better district/block layout examples.
- Export examples for non-Roblox workflows.
- More detailed release QA notes.
- CI checks for packaging and documentation links.

## Longer Term

- Public example scenes for common urban layouts.
- More material/style controls while keeping low-poly readability.
- Better preset search/filter UX.
- Deeper validation diagnostics surfaced in the Blender UI.
- Optional benchmark snapshots for generation performance.

## Issue Labels

Recommended GitHub labels:

- `bug`: incorrect behavior or regression.
- `docs`: documentation, screenshots, release notes, or examples.
- `preset`: preset quality, variation, or generation output.
- `validation`: validation facts, errors, or export-readiness checks.
- `export`: FBX/RBXMX export pipeline behavior.
- `roblox`: optional Studio post-processor workflow.
- `good first issue`: small scoped maintenance work.

## Not Planned for the First Public Release

- Publishing unrelated private products.
- Adding commercial licensing code.
- Rewriting the generator architecture.
- Claiming usage numbers, customers, or downloads that do not exist.
