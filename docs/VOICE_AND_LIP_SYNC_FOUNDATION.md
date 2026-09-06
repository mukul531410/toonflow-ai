# TOONFLOW-PHASE-012 — Voice and Lip Sync Foundation

## Purpose

This phase introduces a **minimal, deterministic, bpy-free data contract**
for future voice / lip-sync work. It does not produce audio, does not
animate mouths, and does not call Blender. It only defines the stable
data structure that later phases (TTS, phoneme analysis, mouth-shape
animation) can rely on.

The rule "AI plans. Blender executes." continues to apply: this data
layer is a contract, not behavior. A future phase is responsible for
turning these mouth-state sequences into real Blender actions or shape
keys.

## Scope

In scope:

- A canonical, ordered tuple of supported mouth states.
- A canonical default mouth-state sequence for one "spoken beat".
- A canonical per-state frame-offset constant.
- Pure-Python helpers to validate sequences, compute absolute frame
  numbers, look up the state at a given index or frame, and describe a
  timeline.
- A new domain error, `UnknownMouthStateError`, exposed at the public
  generation API.
- A new doc file describing the contract.
- Tests covering all of the above.

Out of scope (explicit non-features):

- No real text-to-speech (TTS).
- No audio file loading, decoding, or analysis.
- No waveform / amplitude / phoneme extraction.
- No Blender `bpy` import in the data layer.
- No mouth-mesh animation, no shape keys, no armature bones.
- No Scene Plan schema changes.
- No changes to the Asset Registry.
- No changes to the existing animation or pose modules.

## Supported mouth states

The supported set is intentionally tiny and is the canonical
identifier vocabulary for every future phase that wants to refer to
mouth shapes:

| Identifier | Meaning |
| ---------- | ------- |
| `REST`     | Mouth closed, neutral. Used as the default and as the end of a beat. |
| `OPEN`     | Mouth open, e.g. vowel-like. |
| `CLOSED`   | Mouth closed after an open state (e.g. a stop consonant). |

The tuple is frozen and ordered. The order is `("REST", "OPEN", "CLOSED")`.

## Deterministic sequence model

The default sequence for a single spoken beat is:

```python
("REST", "OPEN", "CLOSED", "REST")
```

- starts at `REST` (silence / pre-beat rest),
- opens for a vowel-like shape,
- closes (stop consonant / consonant tail),
- returns to `REST` (silence / post-beat rest).

Callers may pass a custom sequence of any length. The same four-state
default is the recommended minimum.

## Timing model

- `LIP_SYNC_FRAME_OFFSETS = (0, 4, 8, 12)` — the canonical per-state
  frame offsets for the default 4-state beat.
- Per-state step is **4 frames** for every entry in a sequence. For
  sequences longer than 4 states, the offset continues at 4 frames per
  state so the timeline stays fully deterministic.
- Absolute frame numbers are computed as
  `start_frame + 4 * index` for the default step, or
  `start_frame + LIP_SYNC_FRAME_OFFSETS[i]` for `i < 4`.

## Public API

All symbols below are re-exported from
`toonflow_ai.generation`:

| Symbol | Purpose |
| ------ | ------- |
| `SUPPORTED_MOUTH_STATES` | The canonical tuple of mouth states. |
| `DEFAULT_LIP_SYNC_SEQUENCE` | The canonical default 4-state beat. |
| `LIP_SYNC_FRAME_OFFSETS` | The canonical frame-offset table. |
| `DEFAULT_LIP_SYNC_FRAME_OFFSETS` | Alias of the same table. |
| `is_supported_mouth_state(state)` | Pure-Python predicate. |
| `lip_sync_sequence(sequence=None)` | Validate and return a tuple of states. |
| `lip_sync_frame_offsets()` | Fresh tuple copy of the offsets table. |
| `validate_lip_sync_start_frame(start_frame)` | Same rules as PHASE-010. |
| `lip_sync_frames(start_frame, sequence=None)` | Absolute frame numbers. |
| `lip_sync_state_at(start_frame, sequence=None, index=..., frame=...)` | Lookup. |
| `lip_sync_describe(start_frame, sequence=None)` | Plain-Python description. |
| `UnknownMouthStateError` | New domain error. |

`start_frame` validation is delegated to the existing
`InvalidStartFrameError` from PHASE-010: the value must be an `int`
(`bool` is explicitly rejected) and must be `>= 1`. This keeps the
lip-sync foundation consistent with the rest of the generation API.

## Validation behavior

| Input | Result |
| ----- | ------ |
| `start_frame=10` | OK; first frame is 10. |
| `start_frame=1.0` | `InvalidStartFrameError`. |
| `start_frame=True` | `InvalidStartFrameError`. |
| `start_frame=0` | `InvalidStartFrameError`. |
| `start_frame=-3` | `InvalidStartFrameError`. |
| `sequence=["REST", "OPEN"]` | OK. |
| `sequence=["SMILE"]` | `UnknownMouthStateError`. |
| `sequence=[]` | `ValueError`. |
| `sequence="OPEN"` | `TypeError`. |
| `sequence=[1, 2]` | `TypeError`. |
| `index=-1` | `ValueError`. |
| `index=999` | Clamped to the last state. |
| `frame < start_frame` | Returns the first state. |
| `frame` past the end | Returns the last state. |
| both `index` and `frame` given | `ValueError`. |
| neither given | `ValueError`. |

## Bpy-free architecture

`lip_sync_data.py` does **not** import `bpy`. It is testable on any
machine — even where Blender is not installed. A future Blender-side
module may import it and convert its data structures into real
`bpy.types.Action` / shape-key / armature keyframes, but that work is
explicitly out of scope for PHASE-012.

The module also does not import any of:

- the local `ai`, `pipeline`, `scene_plan`, or `asset_registry` packages,
- third-party TTS / audio libraries (`wave`, `soundfile`, `librosa`,
  `speech_recognition`, …),
- network libraries (`urllib`, `requests`),
- the local `ollama` client.

These constraints are enforced by static-architecture tests in
`tests/test_lip_sync.py`.

## Limitations

- The mouth-state vocabulary is fixed. There are exactly three
  identifiers and they are uppercase ASCII.
- The default sequence is a single spoken beat. Future phases may
  compose multiple beats; this phase does not define a "multi-beat"
  composition model.
- The frame-step is fixed at 4 frames per state for the default
  cadence. Callers who pass a longer sequence keep the 4-frame step
  for every entry.
- This phase does not generate, edit, or play any audio file.
- This phase does not keyframe anything in Blender.

## Public-API behavior summary

```python
from toonflow_ai.generation import (
    SUPPORTED_MOUTH_STATES,
    DEFAULT_LIP_SYNC_SEQUENCE,
    LIP_SYNC_FRAME_OFFSETS,
    is_supported_mouth_state,
    lip_sync_sequence,
    lip_sync_frame_offsets,
    lip_sync_frames,
    lip_sync_state_at,
    lip_sync_describe,
    validate_lip_sync_start_frame,
    UnknownMouthStateError,
)

# Default timeline starting at frame 1
lip_sync_frames(1)  # -> (1, 5, 9, 13)
lip_sync_describe(1)
# -> {
#      "start_frame": 1,
#      "states": ("REST", "OPEN", "CLOSED", "REST"),
#      "frame_offsets": (0, 4, 8, 12),
#      "frames": (1, 5, 9, 13),
#      "duration_frames": 12,
#    }

# Look up by frame
lip_sync_state_at(1, frame=6)   # -> "OPEN"
lip_sync_state_at(1, frame=12)  # -> "CLOSED"

# Look up by index
lip_sync_state_at(1, index=0)   # -> "REST"
lip_sync_state_at(1, index=3)   # -> "REST"

# Custom sequence
lip_sync_frames(10, sequence=["OPEN", "REST"])  # -> (10, 14)
```
