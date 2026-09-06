"""Blender-dependent timeline animation for TOONFLOW AI characters.

This module is the only ``bpy``-dependent piece of TOONFLOW AI
animation. It:

- validates ``character_id``, ``animation_name``, and ``start_frame``
  against existing pure-Python metadata;
- resolves the previously generated TOONFLOW character parts by
  deterministic name;
- inserts deterministic ``location`` and ``rotation_euler``
  keyframes using the existing pose transforms;
- keeps every side effect inside the TOONFLOW ownership boundary.

It does NOT create armatures, bones, vertex groups, shape keys, or
constraints. It does NOT touch unrelated user animation. It does NOT
modify objects owned by other TOONFLOW characters.

Public API
----------

    from toonflow_ai.generation import animate_character

    result = animate_character("husband", "wave", start_frame=1)

Repeated-call behavior
----------------------

When ``animate_character`` is called twice with the same
``character_id`` / ``animation_name`` / ``start_frame``:

- The narrow set of frames this animation uses (start_frame, start
  + 20, start + 40) is cleared from each affected TOONFLOW part
  before new keyframes are inserted. Other frames on those parts
  are not touched.
- Other TOONFLOW animations (e.g. a future animation on the same
  character at non-overlapping frames) are not affected because
  only this animation's exact frame numbers are removed.
- Unrelated user animation on unrelated objects is never touched.
"""

from .animation_data import (
    SUPPORTED_ANIMATIONS,
    animation_frame_offsets,
    animation_frames,
    animation_sequence,
    is_supported_animation,
    validate_animation_pose_sequence,
)
from .errors import (
    BlenderUnavailableError,
    InvalidStartFrameError,
    MissingCharacterError,
    UnknownAnimationError,
    UnknownCharacterError,
)
from .naming import (
    CHARACTER_PARTS,
    character_object_name,
    character_part_object_name,
    is_toonflow_name,
)
from .poses import pose_offset, pose_rotation_euler


def _require_bpy():
    """Import ``bpy`` lazily and raise a clear error if unavailable."""
    try:
        import bpy  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only outside Blender
        raise BlenderUnavailableError(
            "The Blender 'bpy' module is not available in this Python "
            "process. animate_character() must be called from inside Blender."
        ) from exc
    return bpy


def _validate_character_id(character_id):
    if not isinstance(character_id, str) or not character_id:
        raise UnknownCharacterError(character_id)

    from asset_registry import character_exists

    if not character_exists(character_id):
        raise UnknownCharacterError(character_id)


def _validate_animation_name(animation_name):
    if not is_supported_animation(animation_name):
        raise UnknownAnimationError(animation_name, SUPPORTED_ANIMATIONS)
    validate_animation_pose_sequence(animation_name)


def _validate_start_frame(start_frame):
    # bool is a subclass of int in Python; explicitly reject it.
    if isinstance(start_frame, bool) or not isinstance(start_frame, int):
        raise InvalidStartFrameError(start_frame)
    if start_frame < 1:
        raise InvalidStartFrameError(start_frame)


def _validate_inputs(character_id, animation_name, start_frame):
    _validate_character_id(character_id)
    _validate_animation_name(animation_name)
    _validate_start_frame(start_frame)


def _find_character_root(bpy, character_id):
    expected_root = character_object_name(character_id)
    for obj in bpy.data.objects:
        if obj.name == expected_root or obj.name.startswith(expected_root + "."):
            if is_toonflow_name(obj.name):
                return obj
    return None


def _find_part_object(bpy, character_id, part):
    expected = character_part_object_name(character_id, part)
    for obj in bpy.data.objects:
        if obj.name == expected or obj.name.startswith(expected + "."):
            if is_toonflow_name(obj.name):
                return obj
    return None


def _ensure_animation_data(bpy, part_obj, character_id, animation_name):
    """Ensure *part_obj* has an ``animation_data`` block and a deterministic Action."""
    action_name = (
        "TOONFLOW_ANIM_"
        + character_id.upper().replace(" ", "_")
        + "_"
        + animation_name.upper().replace(" ", "_")
    )
    if part_obj.animation_data is None:
        part_obj.animation_data_create()
    action = bpy.data.actions.get(action_name)
    if action is None:
        action = bpy.data.actions.new(action_name)
    part_obj.animation_data.action = action
    return action


def _clear_animation_frames(bpy, part_obj, animation_name, start_frame):
    """Remove this animation's frames from *part_obj* without touching others.

    Targets ``location`` and ``rotation_euler`` data paths and only the
    exact frame numbers this animation uses. Unrelated keyframes on the
    same part at different frames are preserved.
    """
    if part_obj.animation_data is None or part_obj.animation_data.action is None:
        return 0

    action = part_obj.animation_data.action
    target_frames = set(animation_frames(animation_name, start_frame))
    removed = 0
    for fcurve in list(action.fcurves):
        if fcurve.data_path not in ("location", "rotation_euler"):
            continue
        for kp in list(fcurve.keyframe_points):
            if int(round(kp.co.x)) in target_frames:
                fcurve.keyframe_points.remove(kp)
                removed += 1
    return removed


def animate_character(character_id, animation_name, start_frame=1):
    """Insert deterministic keyframes for *animation_name* on *character_id*.

    Args:
        character_id: A registered Asset Registry character identifier.
        animation_name: One of :data:`SUPPORTED_ANIMATIONS`.
        start_frame: Integer >= 1 marking the first keyframe.

    Returns:
        A dictionary describing the animation: the affected part
        object names, the inserted frames, the reused pose names, and
        the start frame.

    Raises:
        UnknownCharacterError: when *character_id* is unknown / empty /
            not a string.
        UnknownAnimationError: when *animation_name* is unknown.
        InvalidStartFrameError: when *start_frame* is not an integer
            >= 1, or is a ``bool``.
        MissingCharacterError: when no TOONFLOW character root exists
            for *character_id* yet.
        BlenderUnavailableError: when ``bpy`` cannot be imported.

    Side effects:
        - Creates or reuses a deterministic ``TOONFLOW_ANIM_<ID>_<NAME>``
          Action on each affected TOONFLOW character part.
        - Removes only the exact frame numbers used by this animation
          from each affected TOONFLOW part, then inserts the new
          keyframes.
        - Never inspects, mutates, or removes objects outside the
          TOONFLOW ownership boundary.
    """
    _validate_inputs(character_id, animation_name, start_frame)

    bpy = _require_bpy()

    root = _find_character_root(bpy, character_id)
    if root is None:
        raise MissingCharacterError(character_id)

    parts_summary = []
    sequence = animation_sequence(animation_name)
    offsets = animation_frame_offsets()

    for part in CHARACTER_PARTS:
        part_obj = _find_part_object(bpy, character_id, part)
        if part_obj is None:
            continue

        action = _ensure_animation_data(bpy, part_obj, character_id, animation_name)
        removed = _clear_animation_frames(bpy, part_obj, animation_name, start_frame)

        part_frames = []
        for index, pose_name in enumerate(sequence):
            frame = start_frame + offsets[index]
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
            part_obj.keyframe_insert(data_path="location", frame=frame)
            part_obj.keyframe_insert(data_path="rotation_euler", frame=frame)
            part_frames.append(
                {
                    "frame": frame,
                    "pose_name": pose_name,
                    "location": tuple(part_obj.location),
                    "rotation_euler": tuple(part_obj.rotation_euler),
                }
            )

        parts_summary.append(
            {
                "part": part,
                "object_name": part_obj.name,
                "action_name": action.name,
                "removed_existing_frames": removed,
                "keyframes": part_frames,
            }
        )

    return {
        "character_id": character_id,
        "animation_name": animation_name,
        "start_frame": int(start_frame),
        "frame_offsets": tuple(offsets),
        "pose_sequence": tuple(sequence),
        "root_object_name": root.name,
        "parts": parts_summary,
    }


def supported_animations():
    """Return the tuple of supported animation identifiers."""
    return SUPPORTED_ANIMATIONS


__all__ = (
    "animate_character",
    "supported_animations",
)