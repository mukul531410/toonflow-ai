"""Blender-dependent lip-sync animation for TOONFLOW AI characters.

This module is the only ``bpy``-dependent piece of TOONFLOW AI
lip-sync handling. It:

- validates ``character_id`` and ``start_frame`` using the existing
  project architecture;
- resolves the previously generated TOONFLOW character root;
- resolves or creates the deterministic TOONFLOW mouth object
  (parented to the character's HEAD part);
- applies a deterministic transform per mouth state, reusing the
  pure-Python :mod:`toonflow_ai.generation.lip_sync_data` helpers;
- inserts deterministic ``scale`` keyframes at the frame numbers
  reported by :func:`lip_sync_data.lip_sync_frames`;
- keeps every side effect inside the TOONFLOW ownership boundary.

It does NOT create armatures, bones, shape keys, constraints, drivers,
or facial rigs. It does NOT touch unrelated user animation. It does NOT
modify objects owned by other TOONFLOW characters.

Public API
----------

    from toonflow_ai.generation import animate_lip_sync

    result = animate_lip_sync("husband", start_frame=1)

Repeated-call behavior
----------------------

When :func:`animate_lip_sync` is called twice with the same
``character_id`` and ``start_frame``:

- The deterministic mouth object is reused, never duplicated.
- The deterministic ``TOONFLOW_LIP_SYNC_<ID>`` Action is reused.
- Only the exact frame numbers reported by
  :func:`lip_sync_data.lip_sync_frames` are removed from the mouth
  object's ``scale`` F-Curves before new keyframes are inserted.
- Keyframes on other frames, on other parts, and on other characters
  are never touched.
"""

from .errors import (
    BlenderUnavailableError,
    InvalidStartFrameError,
    MissingCharacterError,
    UnknownCharacterError,
)
from .lip_sync_data import (
    MOUTH_LOCAL_OFFSET,
    MOUTH_MESH_SIZE,
    lip_sync_frames,
    lip_sync_sequence,
    mouth_state_z_scale,
    validate_start_frame as _validate_lip_sync_start_frame,
)
from .naming import (
    character_mouth_object_name,
    character_object_name,
    character_part_object_name,
    is_toonflow_name,
)


def _require_bpy():
    """Import ``bpy`` lazily and raise a clear error if unavailable."""
    try:
        import bpy  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only outside Blender
        raise BlenderUnavailableError(
            "The Blender 'bpy' module is not available in this Python "
            "process. animate_lip_sync() must be called from inside Blender."
        ) from exc
    return bpy


def _validate_character_id(character_id):
    if not isinstance(character_id, str) or not character_id:
        raise UnknownCharacterError(character_id)

    from asset_registry import character_exists

    if not character_exists(character_id):
        raise UnknownCharacterError(character_id)


def _validate_inputs(character_id, start_frame):
    _validate_character_id(character_id)
    # Reuse the PHASE-012 lip-sync-specific start-frame validator. It is
    # an alias of the existing ``InvalidStartFrameError`` rule.
    _validate_lip_sync_start_frame(start_frame)


def _find_character_root(bpy, character_id):
    """Return the existing TOONFLOW character root object, or ``None``."""
    expected_root = character_object_name(character_id)
    for obj in bpy.data.objects:
        if obj.name == expected_root or obj.name.startswith(expected_root + "."):
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


def _find_mouth_object(bpy, character_id):
    """Return the existing TOONFLOW mouth object for *character_id*, or ``None``."""
    expected = character_mouth_object_name(character_id)
    for obj in bpy.data.objects:
        if obj.name == expected or obj.name.startswith(expected + "."):
            if is_toonflow_name(obj.name):
                return obj
    return None


def _box_vertices(size):
    """Return a deterministic 8-vertex box of half-extents ``size/2``."""
    hx = size[0] / 2.0
    hy = size[1] / 2.0
    hz = size[2] / 2.0
    return [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]


def _box_faces():
    """Return the 6 quad faces of a unit box described in :func:`_box_vertices`."""
    return [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]


def _create_mouth_object(bpy, character_id, head_part_obj):
    """Create a deterministic TOONFLOW mouth mesh and parent it to the head.

    The mouth mesh is a small thin box centered on the head's local
    origin. Its deterministic Z scale will be keyframed by
    :func:`animate_lip_sync`.
    """
    name = character_mouth_object_name(character_id)
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(_box_vertices(MOUTH_MESH_SIZE), [], _box_faces())
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    obj.location = (
        float(MOUTH_LOCAL_OFFSET[0]),
        float(MOUTH_LOCAL_OFFSET[1]),
        float(MOUTH_LOCAL_OFFSET[2]),
    )
    # Place the mouth slightly in front of the head sphere (along +Y).
    head_radius = 0.22
    obj.location = (0.0, head_radius + MOUTH_MESH_SIZE[1] / 2.0, 0.0)
    head_part_obj.children.link(obj)
    return obj


def _ensure_mouth_object(bpy, character_id):
    """Return the deterministic TOONFLOW mouth object, creating it if missing."""
    existing = _find_mouth_object(bpy, character_id)
    if existing is not None:
        return existing
    head = _find_part_object(bpy, character_id, "HEAD")
    if head is None:
        return None
    return _create_mouth_object(bpy, character_id, head)


def _ensure_action(bpy, character_id):
    """Return a deterministic ``TOONFLOW_LIP_SYNC_<ID>`` Action, creating it if missing."""
    action_name = (
        "TOONFLOW_LIP_SYNC_"
        + character_id.upper().replace(" ", "_")
    )
    action = bpy.data.actions.get(action_name)
    if action is None:
        action = bpy.data.actions.new(action_name)
    return action


def _ensure_animation_data(bpy, mouth_obj, action):
    """Attach *action* to *mouth_obj*, creating ``animation_data`` if needed."""
    if mouth_obj.animation_data is None:
        mouth_obj.animation_data_create()
    mouth_obj.animation_data.action = action
    return mouth_obj.animation_data


def _clear_lip_sync_frames(bpy, mouth_obj, start_frame, sequence):
    """Remove only the exact lip-sync frames from *mouth_obj*'s scale F-Curve."""
    if mouth_obj.animation_data is None or mouth_obj.animation_data.action is None:
        return 0

    target_frames = set(lip_sync_frames(start_frame, sequence=sequence))
    removed = 0
    for fcurve in list(mouth_obj.animation_data.action.fcurves):
        if fcurve.data_path != "scale":
            continue
        for kp in list(fcurve.keyframe_points):
            if int(round(kp.co.x)) in target_frames:
                fcurve.keyframe_points.remove(kp)
                removed += 1
    return removed


def animate_lip_sync(character_id, start_frame=1, sequence=None):
    """Insert deterministic mouth-scale keyframes for *character_id*.

    Args:
        character_id: A registered Asset Registry character identifier.
        start_frame: Integer >= 1 marking the first keyframe.
        sequence: Optional custom mouth-state sequence. When ``None``
            the :data:`lip_sync_data.DEFAULT_LIP_SYNC_SEQUENCE` is used.

    Returns:
        A dictionary describing the lip-sync animation: the mouth
        object name, the inserted frames, the mouth-state sequence,
        the reused Action name, and the start frame.

    Raises:
        UnknownCharacterError: when *character_id* is unknown / empty /
            not a string.
        InvalidStartFrameError: when *start_frame* is not an integer
            >= 1, or is a ``bool``.
        MissingCharacterError: when no TOONFLOW character root exists
            for *character_id* yet.
        BlenderUnavailableError: when ``bpy`` cannot be imported.

    Side effects:
        - Creates or reuses the deterministic
          ``TOONFLOW_CHARACTER_<ID>_MOUTH`` object, parented to the
          character's HEAD part.
        - Creates or reuses a deterministic
          ``TOONFLOW_LIP_SYNC_<ID>`` Action on the mouth object.
        - Removes only the exact frame numbers used by this lip-sync
          run from the mouth's ``scale`` F-Curve, then inserts the new
          keyframes.
        - Never inspects, mutates, or removes objects outside the
          TOONFLOW ownership boundary.
    """
    states = lip_sync_sequence(sequence)
    _validate_inputs(character_id, start_frame)

    bpy = _require_bpy()

    root = _find_character_root(bpy, character_id)
    if root is None:
        raise MissingCharacterError(character_id)

    mouth = _ensure_mouth_object(bpy, character_id)
    if mouth is None:
        # The character root exists but its HEAD part is missing — this
        # is treated as a missing character (nothing to lip-sync).
        raise MissingCharacterError(character_id)

    action = _ensure_action(bpy, character_id)
    _ensure_animation_data(bpy, mouth, action)
    removed = _clear_lip_sync_frames(bpy, mouth, start_frame, states)

    frames = lip_sync_frames(start_frame, sequence=states)
    keyframes = []
    for index, state in enumerate(states):
        frame = frames[index]
        z_scale = mouth_state_z_scale(state)
        mouth.scale = (1.0, 1.0, float(z_scale))
        mouth.keyframe_insert(data_path="scale", frame=frame)
        keyframes.append(
            {
                "frame": int(frame),
                "state": state,
                "scale": tuple(mouth.scale),
            }
        )

    return {
        "character_id": character_id,
        "start_frame": int(start_frame),
        "mouth_object_name": mouth.name,
        "action_name": action.name,
        "root_object_name": root.name,
        "states": tuple(states),
        "frames": tuple(int(f) for f in frames),
        "removed_existing_frames": int(removed),
        "keyframes": keyframes,
    }


def supported_mouth_states():
    """Return the tuple of supported mouth-state identifiers."""
    from .lip_sync_data import SUPPORTED_MOUTH_STATES

    return SUPPORTED_MOUTH_STATES


__all__ = (
    "animate_lip_sync",
    "supported_mouth_states",
)
