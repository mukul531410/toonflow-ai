# Blender UI & Pipeline Integration

This document describes the Blender-side user interface introduced by
**TOONFLOW-PHASE-008 — Blender UI & Pipeline Integration**.

The goal of this phase is to expose the existing
**AI Concept-to-Scene Pipeline** (TOONFLOW-PHASE-007) through a small
Blender panel. No new AI, validation, asset, or scene-generation logic
is added — the UI delegates to existing packages.

## End-to-end flow

```text
Blender UI (panel)
    ↓
Blender Operator (toonflow.generate_scene)
    ↓
pipeline.create_scene_from_concept()
    ↓
ai.plan_scene()        (PHASE-006 local Ollama)
    ↓
scene_plan.validate_scene_plan()
    ↓
asset_registry lookups
    ↓
toonflow_ai.generation.generate_scene()  (PHASE-005)
    ↓
Blender scene objects
```

## UI location

A single side panel is added to the 3D View sidebar under the
**TOONFLOW** tab:

- `bl_space_type = "VIEW_3D"`
- `bl_region_type = "UI"`
- `bl_category = "TOONFLOW"`

The panel contains only:

1. a multiline **Concept** text input,
2. a **Generate Scene** button,
3. a **Last status** label updated from the most recent operator run.

No model selector, API key field, asset selector, animation, camera,
or rendering controls are exposed. No new tab or unrelated panel is
created.

## Concept input

The concept is stored in a Blender `PropertyGroup` attached to the
scene:

```text
bpy.types.Scene.toonflow.concept       (StringProperty, subtype='MULTILINE')
bpy.types.Scene.toonflow.last_status   (StringProperty)
```

The property is namespaced under `Scene.toonflow` so unrelated scene
data is never touched. The input supports practical multiline text
without changing the Scene Plan schema.

The operator rejects empty or whitespace-only concepts before invoking
the pipeline; the user sees an ERROR report and the status label is
updated.

## Generate Scene operator

```python
bpy.ops.toonflow.generate_scene()
```

- `bl_idname = "toonflow.generate_scene"`
- `bl_label = "Generate Scene"`

Behavior:

1. Read the concept from `Scene.toonflow.concept`.
2. Strip whitespace; reject if empty.
3. Call `pipeline.create_scene_from_concept(concept)`.
4. Translate every known domain error into a Blender `ERROR` report
   and update `Scene.toonflow.last_status`.
5. On success, report an `INFO` message containing the deterministic
   object names produced by the generator, and update the status label.
6. Never print Python tracebacks to the user; unexpected exceptions
   print the traceback to the Blender console and report a generic
   error message.

The operator never imports `urllib`, never builds prompts, never
parses model JSON, never validates Scene Plans, never looks up assets,
and never creates Blender objects. All of that lives in the existing
packages.

## Error reporting

Each known domain error from the existing layers maps to a clear
Blender `ERROR` report:

| Source | Exception | Operator message |
| --- | --- | --- |
| UI | empty/whitespace concept | `Concept must not be empty.` |
| `ai.errors` | `InvalidConceptError` | `Concept is empty or not a valid string.` |
| `ai.errors` | `OllamaUnavailableError` | `Local Ollama service is unreachable...` |
| `ai.errors` | `OllamaTimeoutError` | `Local Ollama did not respond before the timeout...` |
| `ai.errors` | `OllamaHTTPError` | `Local Ollama returned HTTP <code>. <detail>` |
| `ai.errors` | `OllamaResponseError` | `Local Ollama returned an unusable response.` |
| `ai.errors` | `InvalidModelJSONError` | `The model returned text that is not valid JSON.` |
| `ai.errors` | `InvalidScenePlanError` | `The model's JSON failed Scene Plan validation. <N> error(s).` |
| `toonflow_ai.generation.errors` | `InvalidScenePlanError` | `Generated Scene Plan failed validation. <N> error(s).` |
| `toonflow_ai.generation.errors` | `UnknownAssetError` | `Scene Plan referenced unknown <type> <id>; check the Asset Registry.` |
| `toonflow_ai.generation.errors` | `BlenderUnavailableError` | `Blender 'bpy' module is unavailable in this process.` |

Errors propagate unchanged from each layer; the operator only
translates them to operator reports. Unexpected exceptions are caught
by a defensive `except Exception` block that prints the traceback to
Blender's console and reports `Unexpected TOONFLOW AI error: <type>: <msg>`
without exposing the raw stack to the user.

## Status feedback

- Successful runs: `INFO` report listing the generated environment
  and character object names; `Scene.toonflow.last_status` is updated.
- Failed runs: `ERROR` report with the reason; `Scene.toonflow.last_status`
  is updated.

No progress percentages or animations are used.

## Registration lifecycle

`addon/toonflow_ai/registration.py` registers and unregisters:

1. UI panel
2. Operator
3. Scene-scoped `PropertyGroup` and `Scene.toonflow` pointer

Unregistration happens in reverse order. The top-level
`addon/toonflow_ai/__init__.py` exposes `register()` and
`unregister()` and declares a minimal `bl_info` block.

Submodules that import `bpy` (`properties`, `operator`, `ui`) are
**not** imported at package load time. The top-level package import
remains `bpy`-free so pure-Python tests and other packages (including
`pipeline`) can import `toonflow_ai.generation` without Blender.

## Local Ollama dependency

Successful execution of this UI requires:

- a running local Ollama service (default `http://127.0.0.1:11434`),
- the configured model available locally (default `llama3.2`),
- a Blender-capable runtime for the generation layer.

The operator surfaces failures from either dependency as clear
`ERROR` reports.

## Current limitations

- The UI exposes only `living_room`, `husband`, and `wife`; it relies
  on the Asset Registry and existing pipeline.
- No progress indicator, no model selector, no API key field, no
  asset selector, no animation/camera/rendering controls.
- No persistent operator history.
- No batch generation; one concept per operator invocation.
- Live panel/operator testing inside Blender was not possible in this
  phase because Blender is not installed in the test environment.
  Pure-Python tests cover the operator's error mapping, `execute()`
  logic, property/UI static structure, and dependency boundaries.