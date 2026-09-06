# Scene Plan Data Contract

The Scene Plan is the structured data contract between future AI planners
and future Blender automation in TOONFLOW AI.

This document applies to TOONFLOW-PHASE-003. It is the authoritative
description of the MVP contract.

## Design principles

- **Explicit** — every required field is documented.
- **Small** — only what current phases actually need.
- **Easy to validate** — validation rules are deterministic and exhaustive.
- **Easy to extend** — versioned; new versions can coexist.
- **Independent** — no `bpy`, no AI provider, no third-party dependency.

## Current version

`version = "0.1"` is the only supported version. Unknown versions are
rejected by validation.

## Top-level shape

```python
{
    "version": "0.1",
    "scene": {
        "environment": "<non-empty string>"
    },
    "characters": [
        {"id": "<non-empty string>", "role": "<non-empty string>"},
        ...
    ]
}
```

All top-level fields (`version`, `scene`, `characters`) are required.

### `scene.environment`

Identifier of a predefined environment. In PHASE-003 this is treated as an
opaque non-empty string; concrete environments are introduced in later
phases (e.g. PHASE-004 Asset Registry).

### `characters[]`

Each character entry requires:

- `id` — non-empty string; used as a stable identifier within the plan.
  IDs must be unique across the `characters` list.
- `role` — non-empty string; opaque in PHASE-003.

Duplicate `id` values are rejected.

## Out of scope for this phase

The following are deliberately NOT part of the MVP contract and must not
appear in PHASE-003 Scene Plans:

- dialogue, voice, lip sync
- emotions, actions, animations
- positions, transforms
- cameras, lighting, rendering settings
- asset file paths
- timing, shots
- multiple scenes

These belong to future phases and will be added in later schema versions.

## Validation API

The validation layer lives in the top-level `scene_plan` package
(stdlib only). It is fully separate from the Blender add-on.

```python
from scene_plan import validate_scene_plan, ValidationResult

result: ValidationResult = validate_scene_plan(data)

if result.is_valid:
    ...  # proceed
else:
    for err in result.errors:
        print(err.path, err.message)
```

- `validate_scene_plan(data) -> ValidationResult`
  - Accepts any Python value (typically a dict).
  - Returns a `ValidationResult`; never raises.
  - Never mutates the input.
  - Never prints.
  - Collects all errors before returning (non-short-circuiting), so the
    caller can see every problem at once.

- `ValidationResult`
  - `.is_valid: bool`
  - `.errors: list[ValidationError]` (empty when valid)
  - Truthy when `is_valid` is True.

- `ValidationError`
  - `.path: str` — dotted JSON-pointer-like path (e.g. `"characters[2].id"`).
    Empty string for top-level (non-dict) errors.
  - `.message: str` — human-readable description.

## Validation rules

1. Input must be a `dict`.
2. `version` must exist and be a supported string.
3. `scene` must exist and be a `dict`.
4. `scene.environment` must exist and be a non-empty string.
5. `characters` must exist and be a `list`.
6. Each character must be a `dict`.
7. Each character must have non-empty string `id` and `role`.
8. Character `id` values must be unique across the list.

Invalid plans are rejected. The validator never silently repairs data.