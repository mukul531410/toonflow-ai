"""Blender-dependent rendering pipeline for TOONFLOW AI.

This module is the only ``bpy``-dependent piece of TOONFLOW AI
rendering. It:

- imports ``bpy`` lazily and raises the existing
  :class:`BlenderUnavailableError` if unavailable;
- consumes the existing deterministic ``TOONFLOW_CAMERA`` produced by
  the camera automation layer (PHASE-011) — it never creates a second
  camera and never falls back to an unrelated user camera;
- configures a minimal, deterministic set of render settings on the
  current Blender scene;
- renders the current scene to a deterministic output path;
- returns a deterministic description of the render.

It does NOT regenerate the scene, modify characters, modify animation
or lip-sync data, call AI, or load external assets.

Public API
----------

    from toonflow_ai.generation import render_scene

    result = render_scene()
    result = render_scene(output_path="/tmp/toonflow_render.png")

Ownership and safety
--------------------

- The renderer only mutates the scene's render settings, the file
  format, the output path, and (when needed) the active camera
  assignment. It never deletes, renames, or moves unrelated user
  objects, cameras, or collections.
- The renderer never creates a second ``TOONFLOW_CAMERA``. If the
  camera is missing or of the wrong type, the renderer raises a
  clear domain error and leaves the scene untouched.
- Repeated calls with the same output path are deterministic: the
  same file is overwritten with a deterministic configuration.
"""

import os
from pathlib import Path

from .camera_data import TOONFLOW_CAMERA_NAME
from .errors import (
    BlenderUnavailableError,
    InvalidCameraTypeError,
    InvalidOutputPathError,
    MissingCameraError,
    RenderError,
)
from .render_data import (
    RENDER_ENGINE,
    RENDER_FILE_FORMAT,
    RENDER_OUTPUT_FILENAME,
    RENDER_RESOLUTION_PERCENTAGE,
    RENDER_RESOLUTION_X,
    RENDER_RESOLUTION_Y,
    RENDER_OUTPUT_FILENAME as _DEFAULT_OUTPUT_FILENAME,
    default_output_path,
    is_supported_file_format,
    is_supported_render_engine,
    render_settings_describe,
    validate_output_path,
)


def _require_bpy():
    """Import ``bpy`` lazily and raise a clear error if unavailable."""
    try:
        import bpy  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only outside Blender
        raise BlenderUnavailableError(
            "The Blender 'bpy' module is not available in this Python "
            "process. render_scene() must be called from inside Blender."
        ) from exc
    return bpy


def _find_toonflow_camera(bpy):
    """Return the existing TOONFLOW camera object (typed CAMERA), or ``None``.

    Raises:
        InvalidCameraTypeError: when an object named
            :data:`TOONFLOW_CAMERA_NAME` exists but is not of type
            ``CAMERA``.
    """
    obj = bpy.data.objects.get(TOONFLOW_CAMERA_NAME)
    if obj is None:
        return None
    if getattr(obj, "type", None) != "CAMERA":
        raise InvalidCameraTypeError(TOONFLOW_CAMERA_NAME, getattr(obj, "type", None))
    return obj


def _resolve_output_path(value):
    """Resolve and validate the output path argument.

    When *value* is ``None``, the deterministic default output path is
    returned.
    """
    validated = validate_output_path(value)
    if validated is None:
        blend_path = None
        try:
            bpy = _require_bpy()
            blend_path = getattr(bpy.data, "filepath", "") or None
        except BlenderUnavailableError:
            blend_path = None
        return default_output_path(blend_path)
    return Path(validated).resolve()


def _configure_render_settings(bpy, scene, output_path):
    """Apply the deterministic render settings to *scene*."""
    render = scene.render
    if is_supported_render_engine(RENDER_ENGINE):
        try:
            render.engine = RENDER_ENGINE
        except (TypeError, ValueError):
            pass

    render.resolution_x = int(RENDER_RESOLUTION_X)
    render.resolution_y = int(RENDER_RESOLUTION_Y)
    render.resolution_percentage = int(RENDER_RESOLUTION_PERCENTAGE)

    image_settings = render.image_settings
    if is_supported_file_format(RENDER_FILE_FORMAT):
        image_settings.file_format = RENDER_FILE_FORMAT

    render.filepath = str(output_path)

    # Film transparency: disabled. Keep deterministic and local.
    try:
        render.film_transparent = False
    except (AttributeError, TypeError):
        pass

    return {
        "engine": getattr(render, "engine", RENDER_ENGINE),
        "resolution_x": int(getattr(render, "resolution_x", RENDER_RESOLUTION_X)),
        "resolution_y": int(getattr(render, "resolution_y", RENDER_RESOLUTION_Y)),
        "resolution_percentage": int(
            getattr(render, "resolution_percentage", RENDER_RESOLUTION_PERCENTAGE)
        ),
        "file_format": getattr(image_settings, "file_format", RENDER_FILE_FORMAT),
        "film_transparent": bool(getattr(render, "film_transparent", False)),
    }


def _ensure_output_directory(output_path):
    """Create the parent directory of *output_path* if it does not exist.

    The directory is created owned by the renderer; pre-existing files
    inside it are NOT deleted.
    """
    parent = Path(output_path).parent
    if str(parent) and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def _perform_render(bpy, scene):
    """Invoke the Blender render operation.

    The standard Blender way to render the current scene to the path
    configured on ``scene.render.filepath`` is
    :func:`bpy.ops.render.render`. This is the one place in the
    rendering pipeline that uses ``bpy.ops``; every other interaction
    uses the data API.
    """
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:  # pragma: no cover - exercised only inside Blender
        raise RenderError(scene.render.filepath, cause=exc) from exc


def render_scene(output_path=None):
    """Render the current Blender scene to * ``output_path*.

    Args:
        output_path: Optional output path. When ``None``, the
            deterministic default output path is used (see
            :func:`render_data.default_output_path`).

    Returns:
        A deterministic dictionary describing the render: the camera
        name, the active scene name, the resolved output path, the
        applied render settings, and the ``bpy.ops`` call that was
        issued.

    Raises:
        BlenderUnavailableError: when ``bpy`` cannot be imported.
        MissingCameraError: when no ``TOONFLOW_CAMERA`` exists.
        InvalidCameraTypeError: when ``TOONFLOW_CAMERA`` exists but is
            not of type ``CAMERA``.
        InvalidOutputPathError: when * ``output_path* is invalid.
        RenderError: when the Blender render operation itself fails.

    Side effects:
        - Mutates only the current scene's render settings and the
          active camera assignment.
        - Writes (or overwrites) the file at the resolved output path.
        - Never deletes, renames, or mutates unrelated user objects.
    """
    bpy = _require_bpy()

    camera = _find_toonflow_camera(bpy)
    if camera is None:
        raise MissingCameraError(TOONFLOW_CAMERA_NAME)

    resolved_path = _resolve_output_path(output_path)
    _ensure_output_directory(resolved_path)

    scene = bpy.context.scene
    scene.camera = camera

    applied_settings = _configure_render_settings(bpy, scene, resolved_path)
    _perform_render(bpy, scene)

    return {
        "camera_name": camera.name,
        "scene_name": scene.name,
        "output_path": str(resolved_path),
        "output_filename": Path(resolved_path).name,
        "default_filename": _DEFAULT_OUTPUT_FILENAME,
        "applied_settings": applied_settings,
        "config": render_settings_describe(),
    }


def render_describe():
    """Return a deterministic, plain-Python description of the renderer.

    The function does not import ``bpy`` and does not touch the
    Blender scene. It is safe to call from any environment.
    """
    return {
        "camera_name": TOONFLOW_CAMERA_NAME,
        "default_output_filename": _DEFAULT_OUTPUT_FILENAME,
        "config": render_settings_describe(),
    }


__all__ = (
    "render_scene",
    "render_describe",
)