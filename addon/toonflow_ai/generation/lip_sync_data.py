"""Voice and Lip Sync Foundation data layer for TOONFLOW AI.

This module is pure Python and intentionally has no ``bpy`` import. It
defines the deterministic data contract for future voice / lip-sync
phases:

- a tiny fixed set of supported mouth states;
- a deterministic default mouth-state sequence;
- a deterministic per-state frame-offset constant;
- validation, timing, and description helpers.

This module is a FOUNDATION only. It does NOT perform text-to-speech,
does NOT load audio files, does NOT analyze waveforms, and does NOT
extract phonemes. Future phases can use these data structures as a
stable contract.

The module follows the same conventions as
:mod:`toonflow_ai.generation.animation_data`:

- ``SUPPORTED_MOUTH_STATES`` is the canonical ordered tuple;
- `` `` is a single deterministic constant;
- input sequences are validated explicitly, never silently coerced;
- the input ``sequence`` argument is never mutated.
"""

from .errors import InvalidStartFrameError, UnknownMouthStateError


SUPPORTED_MOUTH_STATES = ("REST", "OPEN", "CLOSED")


DEFAULT_LIP_SYNC_SEQUENCE = ("REST", "OPEN", "CLOSED", "REST")


LIP_SYNC_FRAME_OFFSETS = (0, 4, 8, 12)


DEFAULT_LIP_SYNC_FRAME_OFFSETS = LIP_SYNC_FRAME_OFFSETS


# Deterministic per-state Z scale applied to the mouth object.
# REST = neutral (1.0); OPEN = vertically expanded (2.0);
# CLOSED = vertically compressed (0.5). Visibly different, transform-based.
MOUTH_STATE_Z_SCALES = {
    "REST": 1.0,
    "OPEN": 2.0,
    "CLOSED": 0.5,
}


# Deterministic local offset of the mouth object relative to the HEAD part.
# Placed just in front of the head sphere so the difference is visible.
MOUTH_LOCAL_OFFSET = (0.0, 0.0, 0.0)


# Deterministic dimensions of the mouth mesh (a thin box).
MOUTH_MESH_SIZE = (0.18, 0.05, 0.06)


def is_supported_mouth_state(state: object) -> bool:
    """Return True if * ``state* is a supported mouth-state identifier."""
    return isinstance(state, str) and state in SUPPORTED_MOUTH_STATES


def _normalize_sequence(sequence):
    """Validate and return a tuple of supported mouth states.

    Raises:
        TypeError: when *sequence`` is not iterable or contains non-strings.
        UnknownMouthStateError: when a state is not supported.
        ValueError: when *sequence`` is empty.
    """
    if isinstance(sequence, (str, bytes)):
        raise TypeError(
            "mouth-state sequence must be an iterable of strings; "
            f"got {type(sequence).__name__}."
        )
    try:
        items = tuple(sequence)
    except TypeError as exc:
        raise TypeError(
            "mouth-state sequence must be an iterable of strings."
        ) from exc

    if not items:
        raise ValueError("mouth-state sequence must not be empty.")

    for index, state in enumerate(items):
        if not isinstance(state, str):
            raise TypeError(
                f"mouth-state sequence[{index}] must be a string; "
                f"got {type(state).__name__}."
            )
        if not is_supported_mouth_state(state):
            raise UnknownMouthStateError(state, SUPPORTED_MOUTH_STATES)
    return items


def lip_sync_sequence(sequence=None):
    """Return the deterministic tuple of mouth states for the timeline.

    When *sequence`` is `` `` the
    :data:`DEFAULT_LIP_SYNC_SEQUENCE` is returned.

    Raises:
        TypeError: when *sequence`` is not a non-string iterable of strings.
        UnknownMouthStateError: when a state is not supported.
        ValueError: when *sequence`` is empty.
    """
    if sequence is None:
        return tuple(DEFAULT_LIP_SYNC_SEQUENCE)
    return _normalize_sequence(sequence)


def lip_sync_frame_offsets():
    """Return the deterministic tuple of frame offsets between mouth states.

    Each call returns a fresh ``tuple`` so callers can safely mutate the
    result without affecting the module-level constant.
    """
    return tuple(LIP_SYNC_FRAME_OFFSETS[i] for i in range(len(LIP_SYNC_FRAME_OFFSETS)))


def _offsets_for_length(length):
    """Return a tuple of per-state frame offsets for a sequence of *length*.

    The first ``len(LIP_SYNC_FRAME_OFFSETS)`` entries match the canonical
    table; any additional entries continue at the same per-state step
    of 4 frames so the result is fully deterministic.
    """
    if length <= 0:
        return ()
    step = LIP_SYNC_FRAME_OFFSETS[1] - LIP_SYNC_FRAME_OFFSETS[0]
    return tuple(LIP_SYNC_FRAME_OFFSETS[0] + step * i for i in range(length))


def validate_start_frame(start_frame):
    """Validate * ``start_frame* using the existing PHASE-010 rules.

    - must be an int (bool is rejected);
    - must be >= 1.

    Raises:
        InvalidStartFrameError: when * ``start_frame* is invalid.
    """
    if isinstance(start_frame, bool) or not isinstance(start_frame, int):
        raise InvalidStartFrameError(start_frame)
    if start_frame < 1:
        raise InvalidStartFrameError(start_frame)
    return int(start_frame)


def lip_sync_frames(start_frame, sequence=None):
    """Return the deterministic absolute frame numbers for the lip-sync timeline.

    The returned tuple has the same length as the normalized
    *sequence``. Each element is ``start_frame + offset[i]`` where
    ``offset[i]`` follows :data:`LIP_SYNC_FRAME_OFFSETS` and continues
    at the same 4-frame step for any extra entries.

    Raises:
        InvalidStartFrameError: when * ``start_frame* is invalid.
        TypeError: when *sequence`` is not a non-string iterable of strings.
        UnknownMouthStateError: when a state is not supported.
        ValueError: when *sequence`` is empty.
    """
    validate_start_frame(start_frame)
    states = _normalize_sequence(sequence) if sequence is not None else tuple(DEFAULT_LIP_SYNC_SEQUENCE)
    chosen = _offsets_for_length(len(states))
    return tuple(int(start_frame) + chosen[i] for i in range(len(states)))


def lip_sync_state_at(start_frame, sequence=None, index=None, frame=None):
    """Return the mouth state at a given position or absolute frame.

    Provide exactly one of * ``index* or * ``frame*.

    - When * ``index* is given (>= 0), the state at that position in the
      normalized sequence is returned.
    - When * ``frame* is given, the state whose
      ``start_frame + LIP_SYNC_FRAME_OFFSETS[i] <= frame`` with the
      largest such ``i`` is returned. Negative frames return
      `` ``state*; frames past the end return the last state.

    Raises:
        ValueError: when both or neither of * ``index* / * ``frame* is
            given, or when * ``index* is negative.
        InvalidStartFrameError: when * ``start_frame* is invalid.
    """
    if (index is None) == (frame is None):
        raise ValueError(
            "Exactly one of 'index' or 'frame' must be provided."
        )
    states = _normalize_sequence(sequence) if sequence is not None else tuple(DEFAULT_LIP_SYNC_SEQUENCE)
    validate_start_frame(start_frame)
    frames = lip_sync_frames(start_frame, sequence=states)
    if index is not None:
        if index < 0:
            raise ValueError("'index' must be >= 0.")
        if index >= len(states):
            return states[-1]
        return states[index]
    if frame < int(start_frame):
        return states[0]
    chosen_index = 0
    for i, f in enumerate(frames):
        if f <= frame:
            chosen_index = i
        else:
            break
    return states[chosen_index]


def lip_sync_describe(start_frame, sequence=None):
    """Return a deterministic, plain-Python description of the lip-sync timeline."""
    states = _normalize_sequence(sequence) if sequence is not None else tuple(DEFAULT_LIP_SYNC_SEQUENCE)
    validate_start_frame(start_frame)
    frames = lip_sync_frames(start_frame, sequence=states)
    offsets = _offsets_for_length(len(states))
    return {
        "start_frame": int(start_frame),
        "states": tuple(states),
        "frame_offsets": tuple(offsets),
        "frames": frames,
        "duration_frames": int(frames[-1] - int(start_frame)) if frames else 0,
    }


def mouth_state_z_scale(state: str) -> float:
    """Return the deterministic Z scale for * ``state*.

    Raises:
        UnknownMouthStateError: when * ``state* is not supported.
    """
    if not is_supported_mouth_state(state):
        raise UnknownMouthStateError(state, SUPPORTED_MOUTH_STATES)
    return float(MOUTH_STATE_Z_SCALES[state])


def mouth_state_describe(state: str):
    """Return a deterministic description of a single mouth state.

    Raises:
        UnknownMouthStateError: when * ``state* is not supported.
    """
    if not is_supported_mouth_state(state):
        raise UnknownMouthStateError(state, SUPPORTED_MOUTH_STATES)
    return {
        "state": state,
        "z_scale": float(MOUTH_STATE_Z_SCALES[state]),
    }


__all__ = (
    "SUPPORTED_MOUTH_STATES",
    "DEFAULT_LIP_SYNC_SEQUENCE",
    "LIP_SYNC_FRAME_OFFSETS",
    "DEFAULT_LIP_SYNC_FRAME_OFFSETS",
    "MOUTH_STATE_Z_SCALES",
    "MOUTH_LOCAL_OFFSET",
    "MOUTH_MESH_SIZE",
    "is_supported_mouth_state",
    "lip_sync_sequence",
    "lip_sync_frame_offsets",
    "validate_start_frame",
    "lip_sync_frames",
    "lip_sync_state_at",
    "lip_sync_describe",
    "mouth_state_z_scale",
    "mouth_state_describe",
)