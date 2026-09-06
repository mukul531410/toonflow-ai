"""Blender-dependent camera automation for TOONFLOW AI.

This module is the only ``bpy``-dependent piece of TOONFLOW AI camera
handling. It:

- imports ``bpy`` lazily and raises the existing
  ``BlenderUnavailableError`` if unavailable;
- finds or creates the deterministic TOONFLOW-owned camera
  (``TOONFLOW_CAMERA``);
- ensures the object is a real Blender camera object;
- applies the deterministic camera transform from
  :mod:`toonflow_ai.generation.camera_data`;
- orients the camera toward the deterministic target using Blender's
  data API (no constraints, no animation, no ``bpy.ops``);
- returns a deterministic description of the camera.

It does **not** delete, rename, or modify unrelated user cameras or
scene objects.

Public API
----------

    from toonflow_ai.generation import create_or_update_camera

    create_or_update_camera()
"""

from .camera_data import (
    TOONFLOW_CAMERA_NAME,
    camera_describe,
    camera_lens,
    camera_object_name,
    camera_position,
    camera_sensor_width,
    camera_target,
)
from .errors import BlenderUnavailableError, GenerationError
from .naming import TOONFLOW_COLLECTION_NAME


def _require_bpy():
    """Import ``bpy`` lazily and raise a clear error if unavailable."""
    try:
        import bpy  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only outside Blender
        raise BlenderUnavailableError(
            "The Blender 'bpy' module is not available in this Python "
            "process. create_or_update_camera() must be called from inside Blender."
        ) from exc
    return bpy


def _ensure_toonflow_collection(bpy):
    """Return the TOONFLOW collection, creating it if necessary."""
    coll = bpy.data.collections.get(TOONFLOW_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(TOONFLOW_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(coll)
    return coll


def _find_existing_camera(bpy):
    """Return the existing TOONFLOW camera object (typed CAMERA), or ``None``."""
    obj = bpy.data.objects.get(camera_object_name())
    if obj is not None and obj.type == "CAMERA":
        return obj
    return None


def _wrong_type_under_camera_name(bpy):
    """Return the object under TOONFLOW_CAMERA name if it is not a camera."""
    obj = bpy.data.objects.get(camera_object_name())
    if obj is None:
        return None
    if obj.type != "CAMERA":
        return obj
    return None


def _remove_wrong_type_object(bpy, obj):
    """Safely remove a non-camera object that occupies the TOONFLOW_CAMERA name."""
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass


def _create_camera_object(bpy, collection):
    """Create a new ``TOONFLOW_CAMERA`` camera object inside *collection*."""
    cam_data = bpy.data.cameras.new(camera_object_name() + "_DATA")
    cam_data.lens = camera_lens()
    cam_data.sensor_width = camera_sensor_width()

    obj = bpy.data.objects.new(camera_object_name(), cam_data)
    collection.objects.link(obj)
    return obj


def _apply_transform(bpy, cam_obj):
    """Apply the deterministic location + look-at orientation to *cam_obj*."""
    position = camera_position()
    target = camera_target()

    cam_obj.location = (
        float(position[0]),
        float(position[1]),
        float(position[2]),
    )

    import math

    dx = float(target[0]) - float(position[0])
    dy = float(target[1]) - float(position[1])
    dz = float(target[2]) - float(position[2])

    # distance in the XZ plane used for the yaw angle
    horiz = math.sqrt(dx * dx + dy * dy)
    if horiz == 0.0:
        yaw = 0.0
    else:
        # Blender cameras look down -Y by default. yaw rotates around +Z
        # so that the -Y axis points toward (dx, dy, dz).
        yaw = math.atan2(dx, -dy)

    pitch = math.atan2(dz, horiz) if horiz != 0.0 else 0.0

    cam_obj.rotation_euler = (
        float(pitch),
        0.0,
        float(yaw),
    )


def create_or_update_camera():
    """Create or update the deterministic TOONFLOW-owned camera.

    Returns:
        A deterministic dictionary describing the camera: name,
        location, target, lens, sensor width, whether it was reused,
        and the collection it belongs to.

    Raises:
        BlenderUnavailableError: When ``bpy`` cannot be imported.
        GenerationError: When an object named ``TOONFLOW_CAMERA``
            exists that cannot be safely turned into a camera.
    """
    bpy = _require_bpy()

    collection = _ensure_toonflow_collection(bpy)

    existing = _find_existing_camera(bpy)
    if existing is None:
        wrong = _wrong_type_under_camera_name(bpy)
        if wrong is not None:
            raise GenerationError(
                f"Object named {TOONFLOW_CAMERA_NAME!r} exists but is a "
                f"{wrong.type!r}; refusing to modify unrelated scene state."
            )
        cam_obj = _create_camera_object(bpy, collection)
        reused = False
    else:
        cam_obj = existing
        # Make sure the camera data lens is kept in sync.
        if cam_obj.data is not None:
            cam_obj.data.lens = camera_lens()
            cam_obj.data.sensor_width = camera_sensor_width()
        # Ensure the camera is in the TOONFLOW collection. If it was
        # somehow orphaned or in another collection, link it.
        if cam_obj.name not in collection.objects:
            try:
                collection.objects.link(cam_obj)
            except RuntimeError:
                pass
        reused = True

    _apply_transform(bpy, cam_obj)

    position = cam_obj.location
    rotation = cam_obj.rotation_euler

    return {
        "camera_name": cam_obj.name,
        "collection_name": collection.name,
        "location": (float(position[0]), float(position[1]), float(position[2])),
        "rotation_euler": (
            float(rotation[0]),
            float(rotation[1]),
            float(rotation[2]),
        ),
        "lens": camera_lens(),
        "sensor_width": camera_sensor_width(),
        "target": camera_target(),
        "reused": reused,
        "config": camera_describe(),
    }


__all__ = (
    "create_or_update_camera",
)