# Validation

`Validate Selected` is the engineering gate before export.

Validation checks that the selected generated building has a coherent root, stored spec, generation summary, export contract metadata, and supported runtime payloads.

## When to Run

Run validation:

- before `Quick Export Selected`;
- after large selected-building edits;
- after changing presets or generator code;
- before reporting a generated building as production-ready.

## What It Protects

Validation is designed to catch:

- missing or stale root metadata;
- unsupported export contract versions;
- broken sidecar/runtime payloads;
- invalid wall-cell payload shape;
- stale legacy wall metadata;
- impossible runtime counts or malformed generated state.

## Failure Policy

If validation fails, fix the source data or regenerate the building. The addon should not silently repair export-critical runtime data at the final boundary.

