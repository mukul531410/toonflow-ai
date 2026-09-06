"""Deterministic render configuration for TOONFLOW AI.

This module is pure Python and intentionally has no ``bpy`` import. It
defines the deterministic render settings and the deterministic
default output path used by the Blender-side :mod:`rendering` module.

The renderer itself is Blender-dependent and lives in
:mod:`toonflow_ai.generation.rendering`. This module is the single
source of truth for render constants and output-path resolution.
"""

import os
from pathlib import Path


RENDER_RESOLUTION_X = 512
RENDER_RESOLUTION_Y = 512
RENDER_RESOLUTION_PERCENTAGE = 100


RENDER_FILE_FORMAT = "PNG"


RENDER_ENGINE = "BLENDER_EEVEE_NEXT"


RENDER_OUTPUT_FILENAME = "toonflow_render.png"


SUPPORTED_FILE_FORMATS = ("PNG",)


SUPPORTED_RENDER_ENGINES = ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES")


def is_supported_file_format(fmt: object) -> bool:
    """Return True if * ``fmt* is a supported render file format."""
    return isinstance(fmt, str) and fmt in SUPPORTED_FILE_FORMATS


def is_supported_render_engine(engine: object) -> bool:
    """Return True if * ``engine* is a known render engine identifier."""
    return isinstance(engine, str) and engine in SUPPORTED_RENDER_ENGINES


def render_settings_describe():
    """Return a deterministic, plain-Python description of the render settings."""
    return {
        "engine": RENDER_ENGINE,
        "resolution_x": int(RENDER_RESOLUTION_X),
        "resolution_y": int(RENDER_RESOLUTION_Y),
        "resolution_percentage": int(RENDER_RESOLUTION_PERCENTAGE),
        "file_format": RENDER_FILE_FORMAT,
        "output_filename": RENDER_OUTPUT_FILENAME,
    }


def default_output_path(blend_file_path=None):
    """Return the deterministic default output path for a render.

    Resolution order:

    1. When * ``blend_file_path* is a non-empty string or path-like object
       whose file name ends with ``.blend`` (or any string with a parent
       directory), the output path is the *parent* of the blend file
       joined with :data:`RENDER_OUTPUT_FILENAME`.
    2. Otherwise, the output path is the current working directory
       joined with :data:`RENDER_OUTPUT_FILENAME`.

    The returned value is an absolute :class:`pathlib.Path`.
    """
    if blend_file_path is not None and (
        isinstance(blend_file_path, (str, os.PathLike)) and str(blend_file_path)
    ):
        candidate = Path(blend_file_path)
        parent = candidate.parent
        if str(parent):
            return (parent / RENDER_OUTPUT_FILENAME).resolve()
    return (Path.cwd() / RENDER_OUTPUT_FILENAME).resolve()


def validate_output_path(value):
    """Validate a user-supplied output path.

    Accepts:

    - a non-empty :class:`str` or :class:`os.PathLike` whose parent
      directory exists or can be created (we do not create it here;
      the renderer creates it just before writing);
    - the value ``None`` (use the default path).

    Returns the value as a :class:`pathlib.Path`. When *value* is
    ``None``, the function returns ``None`` so the caller can resolve
    the default itself.

    Raises:
        InvalidOutputPathError: when *value* is invalid.
    """
    if value is None:
        return None
    from .errors import InvalidOutputPathError

    if not isinstance(value, (str, os.PathLike)):
        raise InvalidOutputPathError(value)
    try:
        text = os.fspath(value)
    except (TypeError, ValueError):
        raise InvalidOutputPathError(value)
    if not isinstance(text, str) or not text.strip():
        raise InvalidOutputPathError(value)
    try:
        path = Path(text)
    except (TypeError, ValueError):
        raise InvalidOutputPathError(value)
    if not path.name:
        raise InvalidOutputPathError(value)
    return path


__all__ = (
    "RENDER_RESOLUTION_X",
    "RENDER_RESOLUTION_Y",
    "RENDER_RESOLUTION_PERCENTAGE",
    "RENDER_FILE_FORMAT",
    "RENDER_ENGINE",
    "RENDER_OUTPUT_FILENAME",
    "SUPPORTED_FILE_FORMATS",
    "SUPPORTED_RENDER_ENGINES",
    "is_supported_file_format",
    "is_supported_render_engine",
    "render_settings_describe",
    "default_output_path",
    "validate_output_path",
)