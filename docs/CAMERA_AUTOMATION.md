# Camera Automation

This document describes **TOONFLOW-PHASE-011 — Camera Automation**.

This phase adds a minimal deterministic camera automation foundation
on top of the existing scene-generation pipeline. It does **not**
introduce AI-driven camera placement, animated cameras, rendering
controls, keyframing, or constraints. It does **not** modify the
Scene Plan schema, AI planning, or Ollama integration.

## Purpose

Provide a single deterministic `` camera that frames the generated
TOONFLOW scene so that downstream phases (e.g. rendering) can rely on
a known camera transform without having to recompute framing from
scratch.

## Ownership strategy

The camera uses deterministic TOONFLOW ownership.
- Camera name: `` `` (always).
- Collection: the existing TOONFLOW collection is reused.
- The cleanup helper in
  :mod:`toonflow_ai.generation.blender_generator` was given the
  smallest possible targeted change: it excludes `` `` from the
  set of TOONFLOW objects deleted during regeneration. This means
  :func:`generate_scene` can run repeatedly without destroying the
  camera setup.

The camera module never deletes, renames, or modifies unrelated
user cameras or scene objects. It never assigns constraints, drivers,
or animation data to any object.

## Deterministic camera name

| Concept | Name |
| --- | --- |
| Camera object | `` |
| Camera data block | `` |

The camera name is exposed through
``toonflow_ai.generation.TOONFLOW_CAMERA_NAME`` and
``toonflow_ai.generation.camera_object_name()``.

## Deterministic placement

| Concept | Value |
| --- | --- |
| World-space location | ``(0.0, 5.0, 2.5)`` |
| World-space target | ``(0.0, 0.0, 1.0)`` |
| Focal length | ``50.0`` mm |
| Sensor width | ``36.0`` mm |

The exact numeric values are selected to frame the existing
generated scene (characters spread along X at ±1.5 with the floor
centered at origin) from a slightly elevated, in-front angle. There
is no random placement and no AI involvement.

The orientation is computed deterministically using a closed-form
yaw / pitch decomposition of the ( ``target `` − ``position `` )
vector. No constraints, no animation, no `` `` calls are used.

## Target / framing behavior

The camera always aims at the deterministic target
``(0.0, 0.0, 1.0)`` — roughly the middle of the generated character
heights. The framing is wide enough to include the floor plane and
the two generated characters along the X axis.

## Idempotency

``create_or_update_camera()`` is fully idempotent:

- If `` `` does not exist, it a new camera is created.
- If `` `` already exists and is a real camera, it is reused
  and its its location / rotation / data is overwritten with the
  deterministic configuration.
- If an object named `` `` exists but is not a camera (e.g.
  user created an Empty with that name), a clear
  :class:`toonflow_ai.generation.GenerationError` is raised and the
  unrelated object is left untouched.
- Repeated calls never duplicate the camera.
- Repeated calls apply the exact same transform.

Repeated ``generate_scene`` calls also preserve the camera thanks to
the smallest cleanup change noted in **Ownership strategy**.

## Public API

```python
from toonflow_ai.generation import (
    create_or_update_camera,
    TOONFLOW_CAMERA_NAME,
    camera_object_name,
    camera_position,
    camera_target,
    camera_lens,
    camera_sensor_width,
    camera_describe,
    is_toonflow_camera_name,
)

result = create_or_update_camera()
```

``create_or_update_camera()`` returns a deterministic dictionary:

```python
{
    "camera_name": "TOONFLOW_CAMERA",
    "collection_name": "TOONFLOW",
    "location": (0.0, 5.0, 2.5),
    "rotation_euler": (pitch, 0.0, yaw),
    "lens": 50.0,
    "sensor_width": 36.0,
    "target": (0.0, 0.0, 1.0),
    "reused": False,
    "config": camera_describe(),
}
```

## bpy dependency boundary

- :mod:`toonflow_ai.generation.camera_data` is **pure Python**, with
  no `` import.
- :mod:`toonflow_ai.generation.camera` is the only `` in this
  phase that imports `` (lazily).
- The existing ``ai``, ``pipeline``, ``scene_plan``, and
  ``asset_registry`` packages are confirmed `` in the new
  tests.

## Error behavior

| Trigger | Exception |
| --- | |
| `` cannot be imported | `` |
| Object named `` exists but is not a camera | `` |

The camera module never prints directly; callers surface errors.

## Current limitations

- Only one camera is supported (`` ``); there is no support for
  multiple cameras, multi-shot setup, or cutaways.
- Camera placement uses a single fixed framing; it does not adapt
  dynamically to scene contents beyond the fixed target.
- No camera animation, no tracking constraints, no depth-of-field
  setup, no lens / sensor profile per environment.
- The camera's deterministic camera name `` is `` is
  excluded from scene cleanup cleanup so it survives regeneration.
  All other TOONFLOW objects continue to follow the existing
  cleanup behavior unchanged.
- Live Blender execution could not be exercised in this phase
  because Blender is not installed in the test environment.