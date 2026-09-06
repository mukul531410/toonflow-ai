"""Animation metadata for TOONFLOW AI characters.

This module is pure Python and intentionally has no ``bpy`` import. It
defines the supported animation identifiers and maps each one to a
deterministic sequence of pose identifiers and frame offsets. The
Blender-side ``animation.py`` module reads this data and inserts
keyframes.

This module does NOT duplicate pose transform data — it only stores
references to existing pose names. The actual offset/rotation tuples
live in :mod:`toonflow_ai.generation.poses` and are reused through
``pose_offset`` / ``pose_rotation_euler``.
"""

from .poses import SUPPORTED_POSES, is_supported_pose


ANIMATION_FRAME_OFFSETS = (0, 20, 40)


_ANIMATIONS = {
    "wave": ("neutral", "wave", "neutral"),
}


SUPPORTED_ANIMATIONS = tuple(_ANIMATIONS.keys())


def is_supported_animation(animation_name: object) -> bool:
    """Return True if *animation_name* is a supported animation identifier."""
    return (
        isinstance(animation_name, str)
        and animation_name in _ANIMATIONS
    )


def animation_sequence(animation_name: str):
    """Return the deterministic tuple of pose names for *animation_name*."""
    return tuple(_ANIMATIONS[animation_name])


def animation_frame_offsets():
    """Return the deterministic tuple of frame offsets between keyframes."""
    return tuple(ANIMATION_FRAME_OFFSETS)


def animation_frames(animation_name: str, start_frame: int):
    """Return the absolute deterministic frame numbers for the animation.

    Raises:
        KeyError: when *animation_name* is not registered.
    """
    sequence = animation_sequence(animation_name)
    offsets = animation_frame_offsets()
    if len(sequence) != len(offsets):
        raise ValueError(
            "Animation sequence and frame offsets must have matching length; "
            f"got {len(sequence)} vs {len(offsets)}."
        )
    return tuple(start_frame + offsets[i] for i in range(len(sequence)))


def animation_pose_at(animation_name: str, index: int) -> str:
    """Return the pose name at the given *index* of the animation."""
    return _ANIMATIONS[animation_name][index]


def animation_uses_pose(animation_name: str, pose_name: str) -> bool:
    """Return True if *animation_name* references *pose_name*."""
    return pose_name in _ANIMATIONS[animation_name]


def animation_describe(animation_name: str):
    """Return a deterministic, plain-Python description of *animation_name*."""
    sequence = _ANIMATIONS[animation_name]
    offsets = animation_frame_offsets()
    return {
        "name": animation_name,
        "poses": tuple(sequence),
        "frame_offsets": tuple(offsets),
        "frame_count": len(sequence),
    }


def validate_animation_pose_sequence(animation_name: str) -> None:
    """Ensure every pose referenced by *animation_name* is supported.

    Raises:
        ValueError: when a pose is unknown or the sequence is empty.
    """
    sequence = _ANIMATIONS[animation_name]
    if not sequence:
        raise ValueError(
            f"Animation {animation_name!r} has an empty pose sequence."
        )
    for pose_name in sequence:
        if not is_supported_pose(pose_name):
            raise ValueError(
                f"Animation {animation_name!r} references unknown pose "
                f"{pose_name!r}; supported poses: {list(SUPPORTED_POSES)}."
            )


__all__ = (
    "SUPPORTED_ANIMATIONS",
    "ANIMATION_FRAME_OFFSETS",
    "is_supported_animation",
    "animation_sequence",
    "animation_frame_offsets",
    "animation_frames",
    "animation_pose_at",
    "animation_uses_pose",
    "animation_describe",
    "validate_animation_pose_sequence",
)