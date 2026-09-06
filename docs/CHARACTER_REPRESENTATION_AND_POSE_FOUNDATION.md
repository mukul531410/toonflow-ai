# Character Representation & Pose Foundation

This document describes **TOONFLOW-PHASE-009 — Character Representation
& Pose Foundation**.

This phase extends the existing primitive placeholder characters into
a deterministic, multi-part hierarchy and adds a small static-pose
foundation. It does **not** introduce skeletal rigs, armatures,
timeline animation, keyframes, or animation Actions. It does **not**
modify the Scene Plan schema, AI planning, or Ollama integration.

## Character hierarchy

Each generated character is a small, deterministic parent/child
hierarchy:

```text
TOONFLOW_CHARACTER_<ID>          (root Empty, "PLAIN_AXES")
├── TOONFLOW_CHARACTER_<ID>_BODY            (cylinder)
├── TOONFLOW_CHARACTER_<ID>_HEAD            (sphere)
├── TOONFLOW_CHARACTER_<ID>_LEFT_ARM        (cylinder)
├── TOONFLOW_CHARACTER_<ID>_RIGHT_ARM       (cylinder)
├── TOONFLOW_CHARACTER_<ID>_LEFT_LEG        (cylinder)
└── TOONFLOW_CHARACTER_<ID>_RIGHT_LEG       (cylinder)
```

The root is created with `bpy.data.objects.new(name, None)` — an
`Empty` object with `empty_display_type = "PLAIN_AXES"` so it is
visible in the viewport. Each part is a primitive mesh (`bpy.ops`-free
construction via `bpy.data.meshes.new(...).from_pydata(...)`) that
is linked to the TOONFLOW collection and parented to the root
(`parent.children.link(obj)`).

## Required parts

| Part | Geometry | Local offset (relative to root) |
| --- | --- | --- |
| `BODY` | cylinder, r=0.35, h=1.8 | (0, 0, 0.9) |
| `HEAD` | sphere, r=0.22 | (0, 0, 1.8 + 0.22) |
| `LEFT_ARM` | cylinder, r=0.12, h=0.8 | (0.47, 0, 1.4) |
| `RIGHT_ARM` | cylinder, r=0.12, h=0.8 | (-0.47, 0, 1.4) |
| `LEFT_LEG` | cylinder, r=0.14, h=0.9 | (0.175, 0, -0.4) |
| `RIGHT_LEG` | cylinder, r=0.14, h=0.9 | (-0.175, 0, -0.4) |

Local offsets are deterministic and live inside the root, so
re-parenting or moving the root keeps the relative pose intact.

## Naming strategy

| Concept | Name pattern |
| --- | --- |
| Collection | `TOONFLOW` |
| Environment object | `TOONFLOW_ENV_LIVING_ROOM` |
| Character root | `TOONFLOW_CHARACTER_<ID>` |
| Character part | `TOONFLOW_CHARACTER_<ID>_<PART>` |

Naming helpers live in `toonflow_ai.generation.naming`:

- `character_object_name(character_id)` — root name (backward
  compatible with TOONFLOW-PHASE-005).
- `character_part_object_name(character_id, part)` — deterministic
  part name; raises `ValueError` on unknown parts.
- `character_part_names(character_id)` — tuple of every part name
  for a given character.
- `CHARACTER_PARTS` — the canonical part tuple.

`is_toonflow_name(name)` accepts the collection name, `TOONFLOW_ENV_*`,
and any `TOONFLOW_CHARACTER_*` (root or part) so the cleanup helper
used by the generator continues to recognize every new object.

## Placement strategy

Character X placement is unchanged from PHASE-005:

```python
offsets = [-CHARACTER_SPREAD, 0.0, CHARACTER_SPREAD]   # -1.5, 0.0, 1.5
character_x = offsets[index % len(offsets)]
```

`CHARACTER_SPREAD = 1.5`. Placement is fully deterministic; no random
values are used.

The character's root Empty is placed at `(character_x, 0.0, 0.0)`.
All parts use deterministic local offsets, so two characters remain
visually distinguishable by position.

## Pose API

```python
from toonflow_ai.generation import set_character_pose

result = set_character_pose("husband", "wave")
```

- `set_character_pose(character_id, pose_name)` applies an immediate,
  static transform to every part of the previously generated
  character. No keyframes, no Actions, no timeline data.
- `supported_poses()` returns the tuple `("neutral", "wave")`.
- `from toonflow_ai.generation import SUPPORTED_POSES` exposes the
  tuple at the package level.

### Supported poses

| Pose | Behavior |
| --- | --- |
| `neutral` | Every part uses its default local offset and zero Euler rotation. |
| `wave` | Identical to neutral except `RIGHT_ARM` Euler Z = -π/2 (about -90°). Visually distinct from neutral. |

The pose data is defined in `toonflow_ai.generation.poses`:

- `pose_offset(pose_name, part) -> (x, y, z)`
- `pose_rotation_euler(pose_name, part) -> (x, y, z)`
- `pose_describe(pose_name) -> dict`

These helpers are pure Python and unit-tested.

## Error behavior

| Error | Trigger |
| --- | --- |
| `UnknownCharacterError` | `character_id` not in the Asset Registry, empty, or not a string. |
| `UnknownPoseError` | `pose_name` is not in `SUPPORTED_POSES`, is not a string, or is `None`. |
| `MissingCharacterError` | `set_character_pose` is called before `generate_scene` produced the requested TOONFLOW character root. |
| `BlenderUnavailableError` | `bpy` cannot be imported (must be called from inside Blender). |

The pose API never creates missing characters, never modifies
unrelated Blender objects, and never prints directly. Errors carry
the relevant attributes (`character_id`, `pose_name`, `supported`)
so future UI / operator layers can map them to useful messages.

## Generation integration

The existing `toonflow_ai.generation.generate_scene` now produces
the full multi-part hierarchy. Generation is unchanged from a
caller's perspective — same Scene Plan input, same
`GenerationResult` output shape, with `character_object_names`
expanded to include the root plus every part.

## Ownership and cleanup behavior

The existing TOONFLOW ownership boundary is preserved. The cleanup
helper `_remove_existing_toonflow_objects` filters by the
`TOONFLOW_` prefix; the new character roots and parts all match
that prefix, so re-running `generate_scene` (or reapplying a pose
after regeneration) safely removes only TOONFLOW-owned objects.

Unrelated user objects are never inspected, modified, or removed.

## Idempotency strategy

- Generation: `_remove_existing_toonflow_objects` runs before any
  new objects are created, then every new character root and part
  is built deterministically.
- Posing: `set_character_pose` finds the existing part objects by
  deterministic name and overwrites their `location` and
  `rotation_euler`. Reapplying the same pose is a no-op state-wise.

## Current limitations

- No skeletal armatures, no drivers, no Constraints.
- No keyframes, no Actions, no timeline animation.
- No pose interpolation or transition logic — only static
  immediate transforms.
- Only two poses are supported (`neutral`, `wave`).
- No pose selection in the Blender UI; the API is callable only.
- Visual primitives are intentionally crude (4-sided cylinders,
  6-vertex spheres).
- Live visual hierarchy/pose testing inside Blender was not
  performed in this phase; pure-Python tests cover naming, pose
  data, validation, dependency boundaries, and the static
  structure of the Blender modules.