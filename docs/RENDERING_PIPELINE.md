# TOONFLOW-PHASE-014 — Rendering Pipeline

## Purpose

This phase adds the **first minimal deterministic Blender rendering
pipeline** for TOONFLOW AI. It consumes the existing TOONFLOW scene
and the existing deterministic TOONFLOW camera and renders the
current frame to a deterministic output path.

The rule "AI plans. Blender executes." continues to apply. The
renderer:

- never regenerates the scene;
- never modifies characters, animation, or lip-sync data;
- never calls AI, Ollama, or any external service;
- never creates a second camera or falls back to an unrelated user
  camera;
- only mutates the current scene's render settings and the active
  camera assignment.

## Architecture

```
Concept
  -> AI planner
  -> Scene Plan validation
  -> Asset Registry validation
  -> Scene Generation
  -> Character Pose / Animation
  -> Camera Automation
  -> Lip Sync
  -> Rendering Pipeline   (THIS PHASE)
```

```
render_data.py            (pure Python, bpy-free)
    RENDER_RESOLUTION_X, RENDER_RESOLUTION_Y,
    RENDER_RESOLUTION_PERCENTAGE, RENDER_FILE_FORMAT,
    RENDER_ENGINE, RENDER_OUTPUT_FILENAME,
    default_output_path(), validate_output_path(),
    render_settings_describe()
        |
        v
toonflow_ai.generation.rendering   (Blender-dependent, lazy bpy)
    _find_toonflow_camera()
    _resolve_output_path()
    _configure_render_settings()
    _perform_render()  -- the one allowed bpy.ops call
        |
        v
bpy.ops.render.render(write_still=True)
        |
        v
toonflow_render.png
```

The pure-Python data layer is the single source of truth for the
deterministic render constants and the default output path. The
Blender module is the only `bpy`-dependent piece of the renderer.

## Public API

```python
from toonflow_ai.generation import render_scene, render_describe

# Pure-Python description; does not import bpy.
info = render_describe()

# Render the current Blender scene to the deterministic default path.
result = render_scene()

# Render to a custom path.
result = render_scene(output_path="/tmp/toonflow_render.png")
```

`render_describe()` returns a deterministic dictionary that does NOT
touch Blender:

| Key | Meaning |
| --- | ------- |
| `camera_name` | The deterministic TOONFLOW camera name. |
| `default_output_filename` | The deterministic default file name. |
| `config` | The deterministic render settings description. |

`render_scene(output_path=None)` returns a deterministic dictionary
describing the actual render:

| Key | Meaning |
| --- | ------- |
| `camera_name` | The TOONFLOW camera used. |
| `scene_name` | The active Blender scene name. |
| `output_path` | The absolute, resolved output path. |
| `output_filename` | The file name component of the output path. |
| `default_filename` | The deterministic default file name. |
| `applied_settings` | The render settings actually applied. |
| `config` | The deterministic render settings description. |

## Camera requirement behavior

The renderer reuses the existing PHASE-011 camera automation
(`toonflow_ai.generation.create_or_update_camera` /
:data:`camera_data.TOONFLOW_CAMERA_NAME`). It does NOT create a
second camera, does NOT duplicate any camera placement math, and does
NOT fall back to an unrelated user camera.

| Scene state | Result |
| ----------- | ------ |
| `TOONFLOW_CAMERA` exists and is of type `CAMERA` | Used. |
| `TOONFLOW_CAMERA` does not exist | `MissingCameraError`. |
| An object named `TOONFLOW_CAMERA` exists but is not type `CAMERA` | `InvalidCameraTypeError`; the object is NOT modified or removed. |
| An unrelated user camera exists | Ignored. The renderer does not use it. |

`create_or_update_camera()` is the supported way to ensure the
camera exists before calling `render_scene()`. The renderer does not
call it itself — it consumes the existing scene.

## Deterministic render settings

| Setting | Value | Source |
| ------- | ----- | ------ |
| Engine | `BLENDER_EEVEE_NEXT` | `RENDER_ENGINE` |
| Resolution X | 512 | `RENDER_RESOLUTION_X` |
| Resolution Y | 512 | `RENDER_RESOLUTION_Y` |
| Resolution % | 100 | `RENDER_RESOLUTION_PERCENTAGE` |
| File format | `PNG` | `RENDER_FILE_FORMAT` |
| Film transparency | `False` | fixed |
| Output path | deterministic default or user-supplied | `default_output_path` / `validate_output_path` |

Supported engines and file formats are listed in
:data:`render_data.SUPPORTED_RENDER_ENGINES` and
:data:`render_data.SUPPORTED_FILE_FORMATS`.

## Output path behavior

`render_scene(output_path=None)`:

- When `output_path` is `None`, the deterministic default is
  `<parent-of-current-blend-file>/toonflow_render.png` when a
  `.blend` file is open. When no blend file is open, the default
  becomes `<current-working-directory>/toonflow_render.png`. The
  function uses :mod:`pathlib` and returns an absolute path.
- When `output_path` is a non-empty `str` or `os.PathLike`, it is
  validated and resolved to an absolute :class:`pathlib.Path`.
- When the parent directory of the output path does not exist, it is
  created just before the render. Pre-existing files inside that
  directory are NOT deleted.
- When `output_path` is empty, not a string/PathLike, or otherwise
  invalid, `InvalidOutputPathError` is raised.

`render_scene` returns the resolved absolute path in the
`output_path` key of the result dictionary, so callers can verify
exactly which file was written.

## Ownership and safety behavior

- The renderer only mutates:
  - the current scene's `render` settings (engine, resolution, file
    format, filepath, film_transparent);
  - the current scene's active camera assignment (set to the
    TOONFLOW camera).
- The renderer never deletes, renames, or moves unrelated user
  objects, cameras, or collections.
- The renderer never invokes any other TOONFLOW generation entry
  point (`generate_scene`, `set_character_pose`, `animate_character`,
  `animate_lip_sync`, `create_or_update_camera`).
- The renderer never modifies animation data, lip-sync data, or
  character data.
- The renderer never calls AI, Ollama, HTTP, urllib, or any external
  service.
- The renderer never imports `wave`, `soundfile`, `librosa`,
  `speech_recognition`, or any other audio library.
- The renderer never edits the asset registry, scene plan, or
  pipeline.

## Idempotency behavior

Repeated calls of `render_scene()`:

- Never create new objects in the scene.
- Never create or replace the TOONFLOW camera.
- Never modify animation, lip-sync, or character data.
- Overwrite (or create) the same output file with the same
  deterministic configuration.
- Call `bpy.ops.render.render(write_still=True)` exactly once per
  invocation.

The renderer is intentionally a *consumer* of the existing scene
state, not a producer.

## Error behavior

| Case | Raised |
| ---- | ------ |
| `bpy` cannot be imported | `BlenderUnavailableError` |
| `TOONFLOW_CAMERA` does not exist | `MissingCameraError` (carries `camera_name`) |
| Object named `TOONFLOW_CAMERA` is not a camera | `InvalidCameraTypeError` (carries `camera_name`, `actual_type`); the object is NOT modified or removed |
| `output_path` is invalid (empty, non-string, root-only) | `InvalidOutputPathError` (carries `value`) |
| `bpy.ops.render.render` raises | `RenderError` (carries `output_path`, `cause`) |

All new errors derive from the existing `GenerationError`. The
renderer never prints raw tracebacks; it raises structured errors
with deterministic data.

## Testing strategy

Tests live in `tests/test_rendering.py` and cover:

- **Public API exposure** — `render_scene`, `render_describe`, the
  render data constants, and the new error classes are re-exported
  through `toonflow_ai.generation`.
- **Pure data layer** — AST-based proof that `render_data.py` does
  not import `bpy` or any audio / network / AI module.
- **Lazy bpy import** — AST-based proof that the only `import bpy`
  in `rendering.py` lives inside `_require_bpy()`.
- **Blender-unavailable behavior** — the renderer raises
  `BlenderUnavailableError` when `bpy` cannot be imported.
- **Camera requirement** — missing camera, wrong-type object, and
  unrelated user camera scenarios all behave as documented.
- **Deterministic render settings** — the stub scene receives the
  expected resolution, percentage, file format, and filepath.
- **Output path behavior** — default path resolution (with and
  without a current blend file) and custom path handling.
- **Output path validation** — `validate_output_path` accepts valid
  values, rejects empty / non-string / root-only values, and returns
  `None` for `None`.
- **Idempotency** — repeated calls do not create new objects, do
  not create new cameras, and do not modify unrelated user objects.
- **Render invocation** — `bpy.ops.render.render(write_still=True)`
  is called exactly once per `render_scene` invocation; render
  failure raises `RenderError` with the cause.
- **Architecture / dependency boundaries** — AST-based proof that
  the renderer does not import AI, Ollama, HTTP/urllib/requests,
  audio modules, the asset registry, the scene plan, the pipeline,
  or any other generation entry point; does not print; uses the
  existing TOONFLOW_CAMERA_NAME constant from `camera_data`.

Because Blender is not installed in the host environment, the tests
exercise the renderer against a controlled bpy stub and verify that
the expected render operation is invoked. They do not pretend that
live Blender rendering was tested.

## Known limitations

- Only the current frame is rendered. Animation timeline rendering
  is intentionally out of scope for this phase.
- Only PNG output is supported. A future phase can extend
  `SUPPORTED_FILE_FORMATS` to add JPG / EXR / etc.
- The renderer is intentionally local: no GPU selection, no render
  farm, no cloud rendering, no HDRI downloads, no external asset
  loading, no post-processing, no compositing, no denoising.
- The renderer does not create the camera. Callers must call
  `create_or_update_camera()` first to ensure `TOONFLOW_CAMERA`
  exists.
- The default output filename is fixed (`toonflow_render.png`).

## Explicit non-features

This phase does NOT implement:

- Blender render UI controls or render presets
- batch rendering, multi-camera rendering, multi-shot editing
- video rendering, FFmpeg pipeline, audio rendering
- cloud rendering, GPU selection UI, render farms
- HDRI downloading, external asset downloading
- AI image generation or AI render enhancement
- post-processing pipeline, compositing nodes, denoising
- Scene Plan schema changes
- Ollama / AI / pipeline changes
- asset registry changes
- character generation, animation, camera automation, or lip-sync
  changes
