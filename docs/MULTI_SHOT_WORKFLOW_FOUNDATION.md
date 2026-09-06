# TOONFLOW-PHASE-016 — Multi-Shot Workflow Foundation

## Purpose

This phase adds a **pure-Python multi-shot orchestration layer** on
top of the existing
[Advanced Automation Workflow](ADVANCED_AUTOMATION_WORKFLOW.md) API
(`workflow.create_and_render_scene`). The new layer runs multiple
independent shots through the single-shot workflow in a fixed,
deterministic order.

The multi-shot orchestrator contains **no business logic of its
own**. It does not import `bpy`, does not call AI or Ollama, does not
make HTTP calls, does not perform Scene Plan validation, does not
manipulate the Asset Registry, does not create or delete Blender
objects, and does not resolve output paths. Every such
responsibility remains owned by the existing single-shot workflow
and the lower-level generation, animation, lip-sync, camera, and
rendering layers.

## Architecture

```
multi-shot workflow  (this phase, bpy-free)
    |
    v
workflow.create_and_render_scene  (PHASE-015)
    |
    v
existing TOONFLOW pipeline
    (AI planning -> scene generation ->
     optional animation -> optional lip sync ->
     camera -> render)
```

The multi-shot layer sits one level above
:func:`workflow.create_and_render_scene`. It does not know about
`bpy`, AI, Ollama, HTTP, the Asset Registry, the Scene Plan, or
any generation API. It only knows about the
:func:`workflow.create_and_render_scene` contract and the
:class:`workflow.WorkflowResult` it returns.

## Public API

```python
from workflow import (
    Shot,
    create_and_render_shots,
    MultiShotResult,
    MultiShotInputError,
)

shots = (
    Shot(
        concept="A husband waves in a living room",
        animation="wave",
        output_path="shot_01.png",
    ),
    Shot(
        concept="A wife stands in the same room",
        lip_sync=True,
        output_path="shot_02.png",
    ),
)

result = create_and_render_shots(shots)
```

`create_and_render_shots(shots, *, workflow_callable=...)` returns a
deterministic :class:`MultiShotResult` and supports dependency
injection via the optional `workflow_callable` parameter (which
defaults to :func:`workflow.create_and_render_scene`).

## Shot model

A :class:`Shot` is a small immutable dataclass with the same
parameters as the single-shot workflow, minus the top-level
`workflow_callable` injection hook:

| Field | Type | Default | Meaning |
| ----- | ---- | ------- | ------- |
| `concept` | `str` | (required) | A non-empty text concept for the AI planner. |
| `animation` | `Optional[str]` | `None` | Optional animation name (e.g. `"wave"`). |
| `animation_start_frame` | `int` | `1` | First keyframe of the optional animation. |
| `lip_sync` | `bool` | `False` | Whether to apply the deterministic lip-sync animation. |
| `lip_sync_start_frame` | `int` | `1` | First keyframe of the optional lip-sync animation. |
| `output_path` | `Optional[str]` | `None` | Optional output path. `None` → deterministic default inside the renderer. |

The defaults match the existing single-shot workflow defaults. The
multi-shot layer does **not** add its own semantic validation for
these fields; the single-shot workflow and the lower-level
delegated layers already own that validation and raise their own
structured errors.

Duck-typed shot objects are also accepted: any object that exposes
the same field names (`concept`, `animation`, `animation_start_frame`,
`lip_sync`, `lip_sync_start_frame`, `output_path`) is forwarded to
the injected workflow callable unchanged.

## Result model

A :class:`MultiShotResult` is a frozen dataclass:

| Key | Type | Meaning |
| --- | ---- | ------- |
| `shot_results` | `tuple` | Tuple of per-shot results returned by the delegated single-shot workflow, in execution order. |
| `output_paths` | `tuple[str, ...]` | Tuple of resolved absolute output paths, in execution order. |
| `shot_count` | `int` | The number of shots that were executed successfully. Equal to `len(shot_results)`. |

The result preserves execution order, is immutable, and contains
no duplicated scene-generation data.

## Execution order

Shots execute **strictly in input order**. The algorithm is:

```
validate shots
validate workflow_callable

results = []
output_paths = []
for shot in shots:
    result = workflow_callable(
        concept=shot.concept,
        animation=shot.animation,
        animation_start_frame=shot.animation_start_frame,
        lip_sync=shot.lip_sync,
        lip_sync_start_frame=shot.lip_sync_start_frame,
        output_path=shot.output_path,
    )
    results.append(result)
    output_paths.append(str(getattr(result, "output_path", "") or ""))

return MultiShotResult(
    shot_results=tuple(results),
    output_paths=tuple(output_paths),
    shot_count=len(results),
)
```

There is no threading, no async, no parallel rendering, no job
queue, and no background worker.

## Delegation model

The multi-shot layer delegates only to a single callable that
matches the :func:`workflow.create_and_render_scene` signature. The
default callable is :func:`workflow.create_and_render_scene` itself.

The multi-shot layer must **not** import:

- `pipeline`
- `asset_registry`
- `scene_plan`
- `toonflow_ai.generation`

It must **not** call any lower-level generation, animation,
lip-sync, camera, or rendering API directly. Those responsibilities
remain owned by the existing workflow and generation layers.

## Dependency injection

`create_and_render_shots` accepts one optional injection hook:

```python
create_and_render_shots(
    shots,
    *,
    workflow_callable=_default_workflow_callable,
)
```

`workflow_callable` is a keyword-only parameter. The default
implementation forwards the shot's fields to
:func:`workflow.create_and_render_scene`. Tests replace it with a
fake to assert ordering, forwarding, error propagation, and
idempotency without requiring Blender, Ollama, or a real render
engine.

## Error propagation

Errors from the delegated single-shot workflow propagate
**unchanged**. The multi-shot layer does not wrap lower-level
errors, does not print errors, and does not swallow exceptions.

When a shot fails, execution **stops immediately** and the failing
shot's error is re-raised. Later shots are **not** executed. The
result is never returned in the failure case.

The only new error class is :class:`MultiShotInputError`, raised
for invalid top-level multi-shot inputs:

| Input | Raised |
| ----- | ------ |
| `shots` is not a non-empty sequence | `MultiShotInputError("shots", ...)` |
| `shots` is empty | `MultiShotInputError("shots", ...)` |
| Any element of `shots` is not a :class:`Shot`-like value | `MultiShotInputError("shots[i]", ...)` |
| `workflow_callable` is not callable | `MultiShotInputError("workflow_callable", ...)` |

`MultiShotInputError` is a `ValueError` subclass and is the only
multi-shot-layer-specific error.

## Output path ownership

The multi-shot layer must **not** resolve or modify output paths.
Each shot's `output_path` is forwarded to the injected workflow
callable unchanged. The rendering layer remains the sole owner of
`default_output_path`, `validate_output_path`, render path
resolution, and directory creation.

## Idempotency

The multi-shot orchestrator itself:

- creates no Blender objects;
- maintains no global mutable state;
- mutates no input shot objects;
- preserves input order;
- delegates deterministically.

Repeated calls with the same shot inputs and the same
`workflow_callable` produce equivalent delegation behavior. The
multi-shot layer may reuse the existing idempotency guarantees of
:func:`workflow.create_and_render_scene` and the lower-level
generation / animation / lip-sync / camera / rendering APIs.

## Ownership and safety boundaries

The multi-shot module must be:

- `bpy`-free
- AI-free / Ollama-free
- HTTP-free / urllib-free / requests-free
- audio-free
- `pipeline`-free
- `asset_registry`-free
- `scene_plan`-free
- `toonflow_ai.generation`-free

It must not:

- call `keyframe_insert` or `from_pydata`;
- reference `bpy.data` or `bpy.ops`;
- print / read / open files;
- import threading, async, queue, database, or storage modules.

These constraints are enforced by AST-based architecture tests in
`tests/test_multi_shot_workflow.py`.

## Testing strategy

Tests live in `tests/test_multi_shot_workflow.py` and cover:

- **Public API exposure** — `Shot`, `MultiShotResult`,
  `MultiShotInputError`, and `create_and_render_shots` are exported
  through the `workflow` package; the result and shot models are
  frozen; defaults match the single-shot workflow.
- **Execution order** — shots 1, 2, 3 execute in exactly that
  order; the result preserves order.
- **Delegation** — every shot field is forwarded to the injected
  workflow callable unchanged; default values are forwarded
  correctly; output paths are passed through unchanged; duck-typed
  shot objects are accepted.
- **Error propagation** — delegated errors propagate unchanged;
  execution stops at the first failing shot; later shots are not
  executed; the first-shot failure short-circuits the entire run.
- **Input validation** — non-sequence input, empty sequence,
  non-callable workflow callable, and invalid shot values are all
  rejected with `MultiShotInputError`; validation runs before any
  delegation.
- **Result behavior** — result is immutable; results preserve
  order; output paths preserve order; `shot_count` is deterministic.
- **Idempotency** — repeated calls with the same inputs produce
  equivalent delegation; shot objects are not mutated.
- **Architecture** — AST-based proof that the multi-shot module
  contains no `bpy` import, no `bpy.data` / `bpy.ops` reference, no
  `keyframe_insert`, no `from_pydata`, no AI / Ollama / HTTP /
  urllib / audio import, no `pipeline` / `asset_registry` /
  `scene_plan` / `toonflow_ai.generation` import, no print / input
  / open, and that the default `workflow_callable` delegates to
  `workflow.create_and_render_scene`.

The tests use dependency injection (custom `workflow_callable`)
so they require neither Blender, nor `bpy`, nor Ollama, nor a real
render engine.

## Known limitations

- The multi-shot layer is strictly sequential. There is no
  parallelism, no queue, and no async API.
- The multi-shot layer does not implement retries; a failing shot
  fails the entire run.
- The multi-shot layer does not implement a job history or
  persistent project storage.
- The multi-shot layer does not implement cross-shot camera
  switching; each shot is a self-contained
  `create_and_render_scene` invocation.
- The multi-shot layer does not implement cross-shot timeline
  editing, video rendering, or FFmpeg.

## Explicit non-features

This phase does NOT implement:

- multiple cameras or camera switching;
- camera math or shot-specific Blender objects;
- video rendering, FFmpeg, or timeline editing;
- threading, async, queues, or background workers;
- databases, persistent project storage, or job history;
- retries, progress percentages, or batch cloud rendering;
- Blender modal operators or new UI controls;
- any direct call to `bpy`, `ai`, `ollama`, `urllib`, `requests`,
  `asset_registry`, `scene_plan`, or `toonflow_ai.generation`.

This phase is strictly orchestration of the existing single-shot
workflow.
