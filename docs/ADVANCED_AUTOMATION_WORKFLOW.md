# TOONFLOW-PHASE-015 — Advanced Automation Workflow

## Purpose

This phase adds the **high-level deterministic orchestration entry
point** for TOONFLOW AI. It composes the existing public APIs into one
controlled end-to-end workflow:

    concept
      -> AI planning
      -> scene generation
      -> optional character animation
      -> optional lip sync
      -> camera setup / update
      -> render

The workflow is intentionally a **thin orchestration layer**. It
contains no business logic of its own. It does not import `bpy`, it
does not call AI directly, it does not perform Scene Plan validation,
it does not manipulate the Asset Registry, it does not create or
delete Blender objects, it does not insert keyframes, and it does not
configure render settings. Every such side effect is delegated to the
dedicated TOONFLOW modules.

## Architecture

```
    +--------------------------------------+
    | workflow.create_and_render_scene     |  (bpy-free orchestrator)
    +----------------+---------------------+
                     |
                     v
    +--------------------------------------+
    | pipeline.create_scene_from_concept   |  (PHASE-007)
    |   ai.plan_scene  (Ollama)            |
    |   toonflow_ai.generation.generate_scene
    +----------------+---------------------+
                     |
                     v
    +--------------------------------------+
    | toonflow_ai.generation.animate_character  (optional, PHASE-010)
    +--------------------------------------+
                     |
                     v
    +--------------------------------------+
    | toonflow_ai.generation.animate_lip_sync    (optional, PHASE-013)
    +--------------------------------------+
                     |
                     v
    +--------------------------------------+
    | toonflow_ai.generation.create_or_update_camera  (PHASE-011)
    +--------------------------------------+
                     |
                     v
    +--------------------------------------+
    | toonflow_ai.generation.render_scene        (PHASE-014)
    +--------------------------------------+
                     |
                     v
                 output image
```

The workflow package is a small sibling of the existing `pipeline`
package. It sits one layer above the existing layers and reuses their
public APIs exclusively.

## Public API

```python
from workflow import create_and_render_scene

result = create_and_render_scene(
    "A husband and wife are in a living room",
)
```

Optional parameters:

```python
from workflow import create_and_render_scene

result = create_and_render_scene(
    concept="A husband and wife are in a living room",
    animation="wave",
    animation_start_frame=1,
    lip_sync=True,
    lip_sync_start_frame=1,
    output_path="/tmp/toonflow_render.png",
)
```

The result is a `WorkflowResult` dataclass:

| Key | Meaning |
| --- | ------- |
| `scene_plan` | The validated Scene Plan returned by the concept pipeline. |
| `generation_result` | The `GenerationResult` returned by scene generation. |
| `animation_results` | Tuple of per-character animation results, or `None` when animation was not requested. |
| `lip_sync_results` | Tuple of per-character lip-sync results, or `None` when lip sync was not requested. |
| `camera_result` | The deterministic camera description returned by `create_or_update_camera`. |
| `render_result` | The deterministic render description returned by `render_scene`. |
| `output_path` | The resolved absolute output path used by the render step. |

The function also accepts five optional injection points (used by
tests and by alternative callers) that replace the default
delegations:

| Parameter | Default |
| --------- | ------- |
| `pipeline` | `pipeline.create_scene_from_concept` |
| `animator` | `toonflow_ai.generation.animate_character` |
| `lip_sync_callable` | `toonflow_ai.generation.animate_lip_sync` |
| `camera` | `toonflow_ai.generation.create_or_update_camera` |
| `renderer` | `toonflow_ai.generation.render_scene` |

## Execution order

The workflow order is fixed and deterministic:

1. Validate the high-level workflow inputs (concept, animation,
   lip_sync, output_path, start frames).
2. Concept-to-Scene pipeline (AI planning + scene generation).
3. Optional character animation, applied to every generated
   character returned by the generation result.
4. Optional lip-sync animation, applied to every generated
   character.
5. Camera update / create.
6. Render.

Rendering never runs before the camera step. Character animation and
lip-sync never run before scene generation. Input validation always
runs first, so a bad input fails before any delegated layer is
called.

## Optional animation behavior

When `animation` is `None` or an empty string, the workflow does not
invoke the animation layer. The result's `animation_results` is
`None`.

When `animation` is a non-empty string, the workflow calls the
configured animator once per generated character (using the
`character_ids` returned by the generation result). For
`animation="wave"`, the existing `wave` animation is applied to every
generated character. The per-character results are aggregated into a
tuple in `animation_results`.

The workflow does not invent new animation definitions and does not
add AI-based animation selection. It only forwards the configured
animation name to the existing animation API.

## Optional lip-sync behavior

When `lip_sync` is `False`, the workflow does not invoke the
lip-sync layer. The result's `lip_sync_results` is `None`.

When `lip_sync` is `True`, the workflow calls the configured
lip-sync callable once per generated character, using the configured
`lip_sync_start_frame` and the default sequence. The per-character
results are aggregated into a tuple in `lip_sync_results`.

The workflow does not implement TTS, audio generation, phoneme
extraction, or speech-to-text. It only orchestrates the existing
lip-sync layer.

## Camera integration

The camera step always calls the existing
`toonflow_ai.generation.create_or_update_camera`. The workflow does
not duplicate camera naming, placement, or orientation logic. The
camera step never creates a second camera; it reuses the
PHASE-011 camera automation.

## Render integration

The render step always calls the existing
`toonflow_ai.generation.render_scene`, passing the user-supplied
`output_path` through unchanged. The workflow does not configure
render settings, does not resolve output paths itself, and does not
duplicate render validation logic.

## Error propagation

Errors from the delegated layers propagate **unchanged** whenever
possible. The workflow does not wrap delegated errors in a generic
exception, and it does not hide domain-specific errors.

| Delegated layer | Error class (propagated unchanged) |
| --------------- | ---------------------------------- |
| AI planner | `InvalidConceptError`, `OllamaUnavailableError`, `OllamaTimeoutError`, `OllamaHTTPError`, `OllamaResponseError`, `InvalidModelJSONError`, `InvalidScenePlanError`, `PlannerError` |
| Scene generation | `InvalidScenePlanError`, `UnknownAssetError`, `BlenderUnavailableError`, `GenerationError` |
| Animation | `UnknownAnimationError`, `InvalidStartFrameError`, `UnknownCharacterError`, `MissingCharacterError`, `BlenderUnavailableError` |
| Lip sync | `UnknownCharacterError`, `InvalidStartFrameError`, `MissingCharacterError`, `BlenderUnavailableError`, `UnknownMouthStateError` |
| Camera | `BlenderUnavailableError`, `MissingCameraError`, `InvalidCameraTypeError`, `GenerationError` |
| Render | `BlenderUnavailableError`, `MissingCameraError`, `InvalidCameraTypeError`, `InvalidOutputPathError`, `RenderError` |

The workflow adds exactly one new error class for its own
top-level inputs:

- `workflow.WorkflowInputError(parameter, value)` — raised when a
  high-level workflow input is invalid (for example, an empty
  `concept`, a non-string `animation`, a non-`bool` `lip_sync`, a
  non-int start frame). It is a `ValueError` subclass and is the
  only workflow-specific error.

## Ownership and safety behavior

The workflow itself does not:

- delete objects
- remove cameras
- remove collections
- manipulate `bpy.data`
- manipulate `bpy.ops`
- modify F-Curves
- insert keyframes
- create meshes
- call AI or Ollama directly
- make HTTP / urllib / requests calls
- import audio libraries
- perform Scene Plan validation
- manipulate the Asset Registry
- perform rendering
- configure render settings

All Blender mutations remain inside the dedicated TOONFLOW modules.
The workflow package is `bpy`-free. This is enforced by AST-based
architecture tests.

## Idempotency

Repeated calls of `create_and_render_scene` with the same inputs
delegate deterministically to the existing layers, which each carry
their own idempotency guarantees:

- `pipeline.create_scene_from_concept` and `generate_scene` only
  touch TOONFLOW-owned objects.
- `animate_character` reuses TOONFLOW Actions and replaces only its
  own keyframes.
- `animate_lip_sync` reuses the TOONFLOW mouth object and Action
  and replaces only its own keyframes.
- `create_or_update_camera` reuses the TOONFLOW camera.
- `render_scene` overwrites the same output file with the same
  configuration.

The workflow itself never creates a second cleanup mechanism.

## Testing strategy

Tests live in `tests/test_workflow.py` and cover:

- **Public API exposure** — `create_and_render_scene`,
  `WorkflowResult`, and `WorkflowInputError` are exported.
- **Execution order** — the workflow runs pipeline, then
  animation (if requested), then lip-sync (if requested), then
  camera, then render, in that order.
- **Optional branches** — animation disabled / empty / non-string,
  lip-sync disabled, custom output_path, combined animation +
  lip-sync + render.
- **Error propagation** — errors from each delegated layer
  (pipeline, animator, lip-sync, camera, render) propagate
  unchanged and prevent later steps from running.
- **Input validation** — bad concept / animation / lip_sync / start
  frames raise `WorkflowInputError` and prevent any delegation.
- **Idempotent delegation** — repeated calls with the same inputs
  produce equivalent results.
- **Architecture** — AST-based proof that the workflow package is
  `bpy`-free, does not import AI / Ollama / HTTP / urllib / audio
  modules, does not reference `bpy.data` or `bpy.ops`, does not
  import the Asset Registry or Scene Plan directly, does not call
  `keyframe_insert` or `from_pydata`, does not perform a direct
  `bpy.ops.render.render` call, and does not print / read / open
  files.

The tests use dependency injection (custom `pipeline`, `animator`,
`lip_sync_callable`, `camera`, `renderer` callables) so they do not
require Blender, Ollama, or a real scene.

## Known limitations

- The workflow does not yet compose multiple shots, multiple
  cameras, or a render queue.
- The workflow does not expose a streaming / async API.
- The workflow does not implement a job history or a database.
- The animation / lip-sync are simple per-character loops; future
  phases can introduce richer per-character policies without
  changing the workflow signature.

## Explicit non-features

This phase does NOT implement:

- new AI planning or AI animation selection
- TTS, audio generation, phoneme extraction
- video rendering, FFmpeg
- batch processing or render queue
- asynchronous job system or threading
- Blender modal operators or new UI
- new Scene Plan fields or new asset types
- cloud APIs, API keys, database, or persistent job history
- external downloads

This phase is strictly orchestration of the existing TOONFLOW
public APIs.