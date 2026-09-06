# Basic Scene Generation

This document describes the Blender-side scene generation layer
introduced by **TOONFLOW-PHASE-005 — Basic Scene Generation**.

It is the first phase that performs Blender `bpy` operations. It does
**not** use AI, does **not** load real assets, and uses only simple
primitive placeholders.

## Generation flow

```text
Scene Plan dictionary
        ↓
Scene Plan validation (scene_plan package)
        ↓
Asset Registry lookup (asset_registry package)
        ↓
Basic Scene Generator (addon/toonflow_ai/generation/)
        ↓
Blender scene objects
```

If any pre-generation check fails, no Blender side effect occurs.

## Public API

```python
from toonflow_ai.generation import (
    generate_scene,
    GenerationResult,
    GenerationError,
    InvalidScenePlanError,
    UnknownAssetError,
    BlenderUnavailableError,
)

result = generate_scene(scene_plan_dict)
```

`generate_scene(scene_plan_data) -> GenerationResult`

- Validates the input against the supported Scene Plan schema.
- Verifies that `scene.environment` and every character `id` exist in
  the Asset Registry.
- Raises `InvalidScenePlanError` (carrying `.errors`) when the Scene
  Plan is structurally invalid.
- Raises `UnknownAssetError` (carrying `.asset_id` and `.asset_type`)
  when an identifier is not in the Asset Registry.
- Raises `BlenderUnavailableError` when `bpy` cannot be imported (the
  function must be called from inside Blender).
- On success, returns a `GenerationResult` describing the created
  objects.

The input Scene Plan dictionary is never mutated.

## Placeholder strategy

For the registered environment (`living_room`):

- a single floor plane mesh.

For each registered character (`husband`, `wife`):

- a cylindrical body primitive
- a spherical head primitive

No materials, textures, rigs, animations, lights, cameras, or external
files are created.

## TOONFLOW ownership strategy

All generated objects live inside a single Blender collection named
`TOONFLOW`. Object names use a deterministic prefix:

- `TOONFLOW_ENV_<ENV_ID_UPPER>` — environment placeholder
- `TOONFLOW_CHARACTER_<CHAR_ID_UPPER>_BODY` — character body
- `TOONFLOW_CHARACTER_<CHAR_ID_UPPER>_HEAD` — character head

The generator never inspects, mutates, or removes objects whose names
do not start with `TOONFLOW_` or equal `TOONFLOW`.

## Idempotency strategy

Before generating, the generator removes only the previously created
TOONFLOW objects and the TOONFLOW collection (when empty). It then
recreates the placeholders. Re-running `generate_scene` with the same
Scene Plan therefore replaces, never duplicates, TOONFLOW objects.

Unrelated scene objects are never touched.

## Deterministic naming

| Concept | Name pattern |
| --- | --- |
| Collection | `TOONFLOW` |
| Environment object | `TOONFLOW_ENV_LIVING_ROOM` |
| Character body | `TOONFLOW_CHARACTER_HUSBAND_BODY` |
| Character head | `TOONFLOW_CHARACTER_HUSBAND_HEAD` |

Character X placement is deterministic and derived from the character's
index in the Scene Plan (`-1.5`, `0.0`, `+1.5`, wrapping), so the
husband and wife are always visually distinguishable by position.

## Current limitations

- Only `living_room`, `husband`, and `wife` are implemented.
- No materials, lighting, cameras, or rendering setup.
- No UI button or operator — generation is exposed only as a callable
  API. PHASE-006+ can add a UI/operator wrapper.
- Not tested live inside Blender in this phase; pure-Python tests
  cover pre-generation validation and the public API surface.
- No animations, actions, or rigs.
- No real `.blend` assets are loaded.