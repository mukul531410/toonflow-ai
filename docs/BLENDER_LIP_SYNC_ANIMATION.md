# TOONFLOW-PHASE-013 — Blender Lip Sync Animation Application

## Purpose

This phase connects the existing pure-Python
[Voice and Lip Sync Foundation](VOICE_AND_LIP_SYNC_FOUNDATION.md) data
layer (PHASE-012) to Blender. It introduces the first actual
deterministic, timeline-based mouth animation in TOONFLOW AI.

The rule "AI plans. Blender executes." continues to apply: PHASE-012
defines the deterministic contract, PHASE-013 turns that contract into
real Blender objects and keyframes.

## Architecture

```
lip_sync_data.py            (pure Python, bpy-free)
        │
        │ lip_sync_sequence(), lip_sync_frames(), mouth_state_z_scale()
        │ validate_start_frame(), MOUTH_STATE_Z_SCALES, ...
        ▼
toonflow_ai.generation.lip_sync   (Blender-dependent)
        │
        │ validate character_id / start_frame
        │ resolve / create TOONFLOW_CHARACTER_<ID>_MOUTH
        │ parent to character HEAD
        │ ensure TOONFLOW_LIP_SYNC_<ID> Action
        │ clear targeted scale keyframes
        │ insert deterministic scale keyframes
        ▼
bpy.data.actions / bpy.data.objects
```

The Blender module is the only `bpy`-dependent piece of the
lip-sync stack. The pure-Python data layer remains the single source
of truth for the supported mouth states, the default sequence, the
per-state frame offsets, and the per-state transform values.

## Public API

```python
from toonflow_ai.generation import animate_lip_sync

result = animate_lip_sync("husband", start_frame=1)
```

A custom sequence can be passed when needed:

```python
from toonflow_ai.generation import animate_lip_sync

result = animate_lip_sync(
    "husband",
    start_frame=10,
    sequence=["REST", "OPEN", "CLOSED"],
)
```

The function returns a deterministic dictionary:

| Key | Meaning |
| --- | ------- |
| `character_id` | The resolved character id. |
| `start_frame` | The validated start frame. |
| `mouth_object_name` | The deterministic mouth object name. |
| `action_name` | The deterministic Action name. |
| `root_object_name` | The deterministic character root name. |
| `states` | The normalized mouth-state sequence. |
| `frames` | The absolute frame numbers used. |
| `removed_existing_frames` | Number of pre-existing keyframes cleared. |
| `keyframes` | Per-state keyframe detail (frame, state, scale). |

## Mouth object naming

A new naming helper follows the existing naming architecture:

```python
from toonflow_ai.generation import character_mouth_object_name

character_mouth_object_name("husband")  # -> "TOONFLOW_CHARACTER_HUSBAND_MOUTH"
character_mouth_object_name("wife")     # -> "TOONFLOW_CHARACTER_WIFE_MOUTH"
```

The mouth object is therefore inside the existing TOONFLOW ownership
boundary (`is_toonflow_name` returns `True` for it) and is automatically
removed by `generate_scene()` regeneration.

## Mouth hierarchy / parenting

```
TOONFLOW_CHARACTER_<ID>            (Empty, root)
├── TOONFLOW_CHARACTER_<ID>_HEAD
│   └── TOONFLOW_CHARACTER_<ID>_MOUTH   ← created / reused here
├── TOONFLOW_CHARACTER_<ID>_BODY
└── ...
```

The mouth object is parented to the character's HEAD part. A repeated
`animate_lip_sync()` call reuses the existing mouth object — it is
never duplicated.

## Supported mouth states

The mouth uses the three PHASE-012 states:

| State | Z scale | Visual intent |
| ----- | ------- | ------------- |
| `REST` | `1.0` | Neutral / default mouth. |
| `OPEN` | `2.0` | Vertically expanded (vowel-like). |
| `CLOSED` | `0.5` | Vertically compressed (stop consonant). |

The values are deterministic and live in
`lip_sync_data.MOUTH_STATE_Z_SCALES` so future phases (e.g. real
phoneme analysis) can override them in a single place.

## Frame timing

The default sequence and frame offsets are reused unchanged from
PHASE-012:

- `DEFAULT_LIP_SYNC_SEQUENCE = ("REST", "OPEN", "CLOSED", "REST")`
- `LIP_SYNC_FRAME_OFFSETS = (0, 4, 8, 12)`

For `start_frame = 1` the deterministic timeline is:

| State   | Frame |
| ------- | ----- |
| `REST`  | 1     |
| `OPEN`  | 5     |
| `CLOSED`| 9     |
| `REST`  | 13    |

The Blender module does not hardcode these numbers; it always reads
them from `lip_sync_data.lip_sync_frames(start_frame, sequence=...)`.

## Keyframe behavior

- The mouth object's `scale` F-Curve is the only F-Curve touched.
- Three F-Curves are created/used, one per axis (`x`, `y`, `z`),
  matching how Blender represents vector data paths.
- Only the exact frame numbers used by this lip-sync run are removed
  from those F-Curves before new keyframes are inserted. Keyframes on
  other frames, on other F-Curves, on other objects, and on other
  characters are never touched.
- `data_path` is exclusively `"scale"`. `location` and
  `rotation_euler` are not touched.

## Action ownership strategy

A single deterministic Action is created and reused per character:

```
TOONFLOW_LIP_SYNC_<CHARACTER_ID>
```

Examples:

- `TOONFLOW_LIP_SYNC_HUSBAND`
- `TOONFLOW_LIP_SYNC_WIFE`

The Action is attached only to the mouth object. No other F-Curves are
added to it, no other Actions are created, and no other objects receive
an `animation_data` block.

## Idempotency

Calling `animate_lip_sync("husband", start_frame=1)` repeatedly:

- Creates the mouth object on the first call, reuses it on every
  subsequent call.
- Creates the Action on the first call, reuses it on every subsequent
  call.
- Removes only the exact frame numbers in
  `lip_sync_frames(start_frame, sequence=...)` from the mouth's scale
  F-Curves, then re-inserts them. The resulting keyframe set is
  identical to the first call.
- Never touches unrelated user objects, unrelated characters, or
  unrelated keyframes.

## Error behavior

The function reuses the existing project error classes. It never prints
raw tracebacks.

| Input | Result |
| ----- | ------ |
| `character_id` not a string / empty | `UnknownCharacterError` |
| `character_id` not in the Asset Registry | `UnknownCharacterError` |
| `start_frame` not an int / `bool` / `float` / `None` / `str` | `InvalidStartFrameError` |
| `start_frame` `< 1` | `InvalidStartFrameError` |
| No TOONFLOW character root for the id | `MissingCharacterError` |
| Character root exists but the HEAD part is missing | `MissingCharacterError` |
| `bpy` not importable | `BlenderUnavailableError` |
| Custom sequence contains an unknown state | `UnknownMouthStateError` (re-raised from the data layer) |

## Dependency boundaries

The Blender module imports `bpy` lazily and only inside functions
that need it. It does NOT import:

- AI / Ollama / network / `urllib` / `requests` modules
- audio libraries (`wave`, `soundfile`, `librosa`,
  `speech_recognition`, `audio`)
- TTS / speech / phoneme code
- armatures, bones, shape keys, constraints, drivers, or `bpy.ops`

The pure-Python data layer remains bpy-free and is verified by an
AST-based architecture test.

## Limitations

- The mouth is a single primitive mesh (a thin box). There are no
  lips, no teeth, no tongue, no facial rig.
- The visual difference between states is a single Z scale change.
  Future phases can layer additional transform channels (X scale, Y
  scale, jaw rotation, etc.) by extending `MOUTH_STATE_Z_SCALES` or
  by introducing a richer per-state transform table in
  `lip_sync_data.py`.
- The default sequence is a single spoken beat. Multi-beat composition
  is intentionally out of scope and is reserved for a future phase.
- No audio input is consumed. The animation always runs on the
  deterministic default sequence unless an explicit `sequence` is
  provided.
- The mouth mesh is created on first call only. It is not re-created
  on later calls.

## Example usage

```python
from toonflow_ai.generation import (
    generate_scene,
    animate_lip_sync,
)

# 1. Generate the deterministic TOONFLOW scene + characters.
generate_scene(plan_dict)

# 2. Apply the default 4-state lip-sync beat starting at frame 1.
result = animate_lip_sync("husband", start_frame=1)
# result["frames"] == (1, 5, 9, 13)
# result["mouth_object_name"] == "TOONFLOW_CHARACTER_HUSBAND_MOUTH"
# result["action_name"] == "TOONFLOW_LIP_SYNC_HUSBAND"
# result["states"] == ("REST", "OPEN", "CLOSED", "REST")

# 3. A second character, custom sequence, custom start.
result2 = animate_lip_sync(
    "wife",
    start_frame=30,
    sequence=["OPEN", "REST", "CLOSED"],
)
# result2["frames"] == (30, 34, 38)
```

## Out of scope (explicit non-features)

This phase does NOT implement:

- real audio input / TTS / speech-to-text
- phoneme detection
- word-to-mouth synchronization
- automatic AI lip sync
- shape keys
- facial rigs
- armatures / bones
- Blender UI controls
- camera animation
- rendering
- Scene Plan schema changes
- cloud services / API keys
