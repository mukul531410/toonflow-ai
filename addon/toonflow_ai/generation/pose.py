"""Blender-dependent static-pose API for TOONFLOW AI characters.

This module is the only ``bpy``-dependent piece of TOONFLOW AI pose
handling. It applies immediate, static transforms to a previously
generated TOONFLOW character. It does **not** create Actions, does
**not** insert keyframes, and does **not** touch the timeline.

Public API
----------

    from toonflow_ai.generation import set_character_pose

    set_character_pose("husband", "neutral")
    set_character_pose("wife", "wave")

The function returns a deterministic description of the pose it
applied and raises a clear :class:`GenerationError` subclass on failure.
"""

from .errors import (
    BlenderUnavailableError,
    MissingCharacterError,
    UnknownCharacterError,
    UnknownPoseError,
)
from .naming import (
    character_object_name,
    character_part_object_name,
    is_toonflow_name,
)
from .poses import (
    SUPPORTED_POSES,
    is_supported_pose,
    pose_offset,
    pose_rotation_euler,
)


def _require_bpy():
    """Import ``bpy`` lazily and raise a clear error if unavailable."""
    try:
        import bpy  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only outside Blender
        raise BlenderUnavailableError(
            "The Blender 'bpy' module is not available in this Python "
            "process. set_character_pose() must be called from inside Blender."
        ) from exc
    return bpy


def _validate_inputs(character_id, pose_name):
    """Validate inputs against Asset Registry and pose set without touching bpy."""
    if not isinstance(character_id, str) or not character_id:
        raise UnknownCharacterError(character_id)

    from asset_registry import character_exists

    if not character_exists(character_id):
        raise UnknownCharacterError(character_id)

    if not is_supported_pose(pose_name):
        raise UnknownPoseError(pose_name, SUPPORTED_POSES)


def _find_character_root(bpy, character_id):
    """Return the existing TOONFLOW character root object, or ``None``."""
    expected_root = character_object_name(character_id)
    candidates = [
        obj for obj in bpy.data.objects
        if obj.name == expected_root
        or obj.name.startswith(expected_root + ".")
    ]
    for obj in candidates:
        if is_toonflow_name(obj.name):
            return obj
    return None


def _find_part_object(bpy, character_id, part):
    """Return the existing character part object, or ``None``."""
    expected = character_part_object_name(character_id, part)
    for obj in bpy.data.objects:
        if obj.name == expected or obj.name.startswith(expected + "."):
            if is_toonflow_name(obj.name):
                return obj
    return None


def _apply_pose(bpy, character_id, pose_name):
    """Apply a deterministic static transform to every character part."""
    bpy.context.view_layer.update()

    applied_parts = []
    for part in (
        "BODY",
        "HEAD",
        "LEFT_ARM",
        "RIGHT_ARM",
        "LEFT_LEG",
        "RIGHT_LEG",
    ):
        part_obj = _find_part_object(bpy, character_id, part)
        if part_obj is None:
            continue
        offset = pose_offset(pose_name, part)
        rotation = pose_rotation_euler(pose_name, part)
        part_obj.location = (
            float(offset[0]),
            float(offset[1]),
            float(offset[2]),
        )
        part_obj.rotation_euler = (
            float(rotation[0]),
            float(rotation[1]),
            float(rotation[2]),
        )
        applied_parts.append(
            {
                "part": part,
                "object_name": part_obj.name,
                "location": tuple(part_obj.location),
                "rotation_euler": tuple(part_obj.rotation_euler),
            }
        )

    return applied_parts


def set_character_pose(character_id, pose_name):
    """Apply *pose_name* to *character_id* as an immediate static transform.

    Args:
        character_id: A registered Asset Registry character identifier.
        pose_name: One of :data:`SUPPORTED_POSES`.

    Returns:
        A dictionary describing the applied pose, the affected part
        object names, and the resulting transforms.

    Raises:
        UnknownCharacterError: When *character_id* is not in the Asset
            Registry.
        UnknownPoseError: When *pose_name* is not a supported pose.
        MissingCharacterError: When no TOONFLOW character root exists
            for *character_id* yet. Call :func:`generate_scene` first.
        BlenderUnavailableError: When ``bpy`` cannot be imported.
    """
    _validate_inputs(character_id, pose_name)

    bpy = _require_bpy()

    root = _find_character_root(bpy, character_id)
    if root is None:
        raise MissingCharacterError(character_id)

    applied_parts = _apply_pose(bpy, character_id, pose_name)

    return {
        "character_id": character_id,
        "pose_name": pose_name,
        "root_object_name": root.name,
        "applied_parts": applied_parts,
    }


def supported_poses():
    """Return the tuple of supported pose identifiers."""
    return SUPPORTED_POSES


__all__ = (
    "set_character_pose",
    "supported_poses",
)