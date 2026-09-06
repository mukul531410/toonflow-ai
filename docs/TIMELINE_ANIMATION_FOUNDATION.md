# Timeline Animation Foundation

This document describes **TOONFLOW-PHASE-010 — Timeline Animation
Foundation**.

This phase adds the first minimal timeline-based character animation
on top of the existing character hierarchy and pose foundation. It
does **not** introduce skeletal rigs, bones, vertex groups, shape
keys, constraints, lip sync, or AI-driven animation. It does **not**
modify the Scene Plan schema, AI planning, or Ollama integration.

## Animation architecture

```text
animation_data.py      (pure Python)
    SUPPORTED_ANIMATIONS, animation_sequence,
    animation_frame_offsets, animation_frames,
    animation_pose_at, animation_uses_pose,
    animation_describe, validate_animation_pose_sequence
        ↓
animation.py           (Blender-dependent)
    animate_character(character_id, animation_name, start_frame=1)
        ↓
bpy
    - resolve TOONFLOW character root + parts by deterministic name
    - assign/reuse a deterministic Action
    - clear this animation's exact frame numbers on location +
      rotation_euler data paths
    - insert new keyframes via keyframe_insert(...)
```

The pure-Python ``animation_data`` module reuses ``poses`` constants
and never redefines pose transforms. ``animation.py`` reuses
``pose_offset`` / ``pose_rotation_euler`` directly.

## Public API

```python
from toonflow_ai.generation import animate_character

result = animate_character("husband", "wave", start_frame=1)
```

- ``animate_character(character_id, animation_name, start_frame=1)``
  validates inputs, resolves the previously generated TOONFLOW
  character, and inserts deterministic keyframes.
- ``supported_animations()`` returns ``("wave",)``.
- ``from toonflow_ai.generation import SUPPORTED_ANIMATIONS`` exposes
  the constant.

## Supported animations

| Animation | Pose sequence | Frames (when ``start_frame=1``) |
| --- | --- | --- |
| `wave` | `neutral → wave → neutral` | `1, 21, 41` |

Additional animations can be added later by extending
``_ANIMATIONS`` in ``animation_data.py``. Each animation must reuse
existing pose names — pose transforms are never duplicated.

## Animation sequence

The ``wave`` animation reuses the existing ``neutral`` and ``wave``
poses. Per pose:

- frame = ``start_frame + frame_offsets[index]``
- ``frame_offsets = (0, 20, 40)`` (deterministic)

The same pose data is reused; no numeric rotation/offset values are
duplicated in ``animation_data.py``.

## Frame timing

Frame offsets are stored once in ``ANIMATION_FRAME_OFFSETS = (0, 20,
40)`` and applied relative to the explicit ``start_frame`` argument.
The full animation occupies ``start_frame`` through
``start_frame + 40``.

```text
start_frame          + 0     neutral   (keyframe)
start_frame          + 20    wave      (keyframe)
start_frame          + 40    neutral   (keyframe)
```

There is no random timing. The animation plays linearly between
keyframes using Blender's default interpolation; no explicit
F-Curve handles are authored.

## Keyframe behavior

For each affected TOONFLOW character part (BODY, HEAD, LEFT_ARM,
RIGHT_ARM, LEFT_LEG, RIGHT_LEG):

1. A deterministic Action ``TOONFLOW_ANIM_<CHAR_ID>_<ANIMATION>`` is
   created on first call and reused on subsequent calls.
2. The part's ``animation_data`` block is ensured to exist.
3. For each pose in the animation sequence:
   - ``location`` and ``rotation_euler`` are set from the pose
     transforms via ``pose_offset`` / ``pose_rotation_euler``.
   - ``obj.keyframe_insert(data_path="location", frame=...)`` is
     called.
   - ``obj.keyframe_insert(data_path="rotation_euler", frame=...)``
     is called.

Keyframes are inserted only on TOONFLOW-owned character parts. No
armature, bones, vertex groups, shape keys, constraints, drivers, or
manually constructed F-Curves are used.

## Pose reuse strategy

- ``animation_data.py`` imports ``is_supported_pose`` /
  ``SUPPORTED_POSES`` from ``poses`` and stores only pose *names* in
  ``_ANIMATIONS``.
- ``animation.py`` imports ``pose_offset`` and ``pose_rotation_euler``
  from ``poses`` and applies them per part.
- A numeric rotation like ``-1.5707963267948966`` exists exactly once
  in the project, inside ``poses.py``. It does not appear in either
  animation module.

## Start frame validation

``start_frame`` is validated explicitly and rejected on any
non-conforming value:

| Value | Result |
| --- | --- |
| ``int >= 1`` | accepted |
| ``bool`` (incl. ``True``/``False``) | rejected (bool is a subclass of ``int`` in Python; explicitly blocked) |
| ``float`` | rejected |
| ``str`` | rejected |
| zero or negative | rejected |
| ``None`` | rejected |

The validator never silently clamps, coerces, or truncates input.
``InvalidStartFrameError`` carries the offending value.

## Error behavior

| Error | Trigger |
| --- | --- |
| `UnknownCharacterError` | empty / non-string / unregistered `character_id`. |
| `MissingCharacterError` | `animate_character` is called before `generate_scene` produced the requested character root. |
| `UnknownAnimationError` | non-string / unsupported `animation_name`. Carries `.animation_name` and `.supported`. |
| `InvalidStartFrameError` | any invalid `start_frame` (see table). Carries `.start_frame`. |
| `BlenderUnavailableError` | `bpy` cannot be imported. |

The animation module never prints directly; callers are responsible
for surfacing errors.

## Ownership safety

Only TOONFLOW-owned objects belonging to the requested character are
touched:

- The character root is resolved by ``character_object_name(id)``.
- Each part is resolved by ``character_part_object_name(id, part)``.
- Both helpers match the deterministic naming introduced in
  TOONFLOW-PHASE-009; ``is_toonflow_name`` rejects anything outside
  the ``TOONFLOW_`` prefix.
- Other TOONFLOW characters, unrelated user objects, unrelated user
  Actions, and unrelated keyframes are never inspected, modified, or
  removed.

## Repeated-call / idempotency behavior

Calling ``animate_character("husband", "wave", start_frame=1)`` twice
is deterministic and idempotent:

- The same Action ``TOONFLOW_ANIM_HUSBAND_WAVE`` is reused on every
  affected part (no duplicate Actions).
- Before each call, only the exact frame numbers this animation uses
  (``start_frame``, ``start_frame + 20``, ``start_frame + 40``) are
  removed from each affected part's ``location`` and
  ``rotation_euler`` F-Curves. Any other keyframes on those parts
  (e.g. a future animation on different frames, or static pose data
  inserted by ``set_character_pose``) are preserved.
- Other Actions on the same part are not touched.
- Other TOONFLOW parts (other characters, environment) are not
  touched.

Calling ``animate_character`` with a different ``start_frame`` simply
moves the deterministic keyframe set to that new range while leaving
unrelated keyframes untouched.

## Current limitations

- Only one animation is supported (``wave``).
- ``wave`` moves only the right arm; other parts return to
  ``neutral`` at each keyframe.
- Linear interpolation only — no authored F-Curves, easing, or
  custom handles.
- No bone-based or armature-based animation.
- No lip sync, mouth shape, audio, or camera choreography.
- No UI / operator wiring for animation in this phase.
- Live timeline / keyframe behavior inside Blender could not be
  exercised in this phase because Blender is not installed. Pure-
  Python tests cover input validation, naming, deterministic frames,
  pose reuse, dependency boundaries, and a stubbed ``bpy`` end-to-end
  behavior test.