# Contributing

Thanks for improving LuArch.

## Development Setup

1. Clone the repository.
2. Install Blender 4.5 or newer.
3. Symlink or copy `luarch/` into your Blender addons directory.
4. Enable the addon in Blender preferences.

Basic checks:

```bash
python3 -m compileall luarch
python3 scripts/build_release.py
```

## Pull Requests

Keep changes focused. A good PR should include:

- What changed.
- Why it changed.
- How it was tested.
- Screenshots for visible Blender output changes.
- Notes about export or validation impact.

## Code Expectations

- Preserve deterministic preset + seed behavior.
- Keep Blender generation, validation, export, and Studio-side contracts aligned.
- Do not hide invalid geometry behind fallback repair logic.
- Prefer simple data-driven changes over broad rewrites.
- Avoid adding dependencies unless they solve a concrete problem.

## Testing Expectations

For generator changes:

- Run `python3 -m compileall luarch`.
- Generate at least one building in Blender.
- Run `Validate Selected`.
- If export code changed, run `Quick Export Selected`.

For documentation-only changes, proofread the affected docs and verify links.

