"""Deterministic camera configuration for TOONFLOW AI.

This module is pure Python and intentionally has no ``bpy`` import. It
defines:

- the deterministic TOONFLOW-owned camera name,
- the deterministic camera placement,
- the deterministic target / framing position,
- a small description helper.

The Blender-side ``camera`` module reads this data and applies the
transforms. Pose, animation, AI, pipeline, scene-plan, and asset
registry packages must remain untouched.
"""

TOONFLOW_CAMERA_NAME = "TOONFLOW_CAMERA"


_CAMERA_POSITION = (0.0, 5.0, 2.5)

_CAMERA_TARGET = (0.0, 0.0, 1.0)

_CAMERA_LENS = 50.0

_CAMERA_SENSOR_WIDTH = 36.0


def camera_object_name():
    """Return the deterministic Blender object name for the TOONFLOW camera."""
    return TOONFLOW_CAMERA_NAME


def camera_position():
    """Return the deterministic world-space camera position tuple."""
    return tuple(_CAMERA_POSITION)


def camera_target():
    """Return the deterministic world-space camera target tuple."""
    return tuple(_CAMERA_TARGET)


def camera_lens():
    """Return the deterministic focal-length (mm)."""
    return float(_CAMERA_LENS)


def camera_sensor_width():
    """Return the deterministic sensor width (mm)."""
    return float(_CAMERA_SENSOR_WIDTH)


def camera_describe():
    """Return a deterministic, plain-Python description of the camera."""
    return {
        "name": TOONFLOW_CAMERA_NAME,
        "location": tuple(_CAMERA_POSITION),
        "target": tuple(_CAMERA_TARGET),
        "lens": float(_CAMERA_LENS),
        "sensor_width": float(_CAMERA_SENSOR_WIDTH),
    }


def is_toonflow_camera_name(name: object) -> bool:
    """Return True if *name* matches the deterministic TOONFLOW camera name."""
    return isinstance(name, str) and name == TOONFLOW_CAMERA_NAME


__all__ = (
    "TOONFLOW_CAMERA_NAME",
    "camera_object_name",
    "camera_position",
    "camera_target",
    "camera_lens",
    "camera_sensor_width",
    "camera_describe",
    "is_toonflow_camera_name",
)