"""Deterministic naming utilities for TOONFLOW AI generated objects.

These helpers are intentionally pure Python so they can be unit tested
without Blender. The ``bpy``-side code uses the constants and helpers
here to name objects consistently.

Character hierarchy
-------------------

Each generated character is a small deterministic hierarchy:

    TOONFLOW_CHARACTER_<ID>          (root Empty)
    ├── TOONFLOW_CHARACTER_<ID>_BODY
    ├── TOONFLOW_CHARACTER_<ID>_HEAD
    ├── TOONFLOW_CHARACTER_<ID>_LEFT_ARM
    ├── TOONFLOW_CHARACTER_<ID>_RIGHT_ARM
    ├── TOONFLOW_CHARACTER_<ID>_LEFT_LEG
    └── TOONFLOW_CHARACTER_<ID>_RIGHT_LEG

The root name is the legacy ``character_object_name(id)`` and is kept
for backward compatibility with TOONFLOW-PHASE-005.

Cleanup helpers (e.g. ``is_toonflow_name``) accept any name starting
with ``TOONFLOW_ENV_`` or ``TOONFLOW_CHARACTER_``, so the new part
names remain inside the TOONFLOW ownership boundary automatically.
"""

from asset_registry import get_character, get_environment


TOONFLOW_COLLECTION_NAME = "TOONFLOW"

CHARACTER_PARTS = (
    "BODY",
    "HEAD",
    "LEFT_ARM",
    "RIGHT_ARM",
    "LEFT_LEG",
    "RIGHT_LEG",
)


def env_object_name(environment_id: str) -> str:
    """Return the deterministic Blender object name for an environment.

    Example:
        >>> env_object_name("living_room")
        'TOONFLOW_ENV_LIVING_ROOM'
    """
    return "TOONFLOW_ENV_" + _safe_upper(environment_id)


def character_object_name(character_id: str) -> str:
    """Return the deterministic Blender object name for a character root.

    Backward-compatible: this is the same root name that
    TOONFLOW-PHASE-005 used for the (now extended) character
    hierarchy.

    Example:
        >>> character_object_name("husband")
        'TOONFLOW_CHARACTER_HUSBAND'
    """
    return "TOONFLOW_CHARACTER_" + _safe_upper(character_id)


def character_part_object_name(character_id: str, part: str) -> str:
    """Return the deterministic Blender object name for a character part.

    Example:
        >>> character_part_object_name("husband", "LEFT_ARM")
        'TOONFLOW_CHARACTER_HUSBAND_LEFT_ARM'
    """
    normalized_part = _normalize_part(part)
    if normalized_part not in CHARACTER_PARTS:
        raise ValueError(
            f"Unknown character part {part!r}; expected one of {CHARACTER_PARTS}."
        )
    return (
        "TOONFLOW_CHARACTER_"
        + _safe_upper(character_id)
        + "_"
        + normalized_part
    )


def character_part_names(character_id: str):
    """Yield every deterministic character-part object name for *character_id*."""
    return tuple(character_part_object_name(character_id, p) for p in CHARACTER_PARTS)


def character_mouth_object_name(character_id: str) -> str:
    """Return the deterministic Blender object name for a character mouth.

    Example:
        >>> character_mouth_object_name("husband")
        'TOONFLOW_CHARACTER_HUSBAND_MOUTH'
    """
    return "TOONFLOW_CHARACTER_" + _safe_upper(character_id) + "_MOUTH"


def is_toonflow_name(name: str) -> bool:
    """Return True if ``name`` follows the TOONFLOW deterministic prefix."""
    return (
        name == TOONFLOW_COLLECTION_NAME
        or name.startswith("TOONFLOW_ENV_")
        or name.startswith("TOONFLOW_CHARACTER_")
    )


def character_spawn_index(character_id: str) -> int:
    """Return a deterministic, stable integer for character placement.

    Characters are placed along the X axis. We hash the character id so
    placement does not depend on the order characters appear in the
    Scene Plan. Hashing is not for security; it is just a stable
    deterministic spread.
    """
    return abs(hash(("toonflow", "character", character_id))) % 1000


def _safe_upper(value: str) -> str:
    """Uppercase and sanitize for use in a Blender object name."""
    return "".join(
        ch if (ch.isalnum() or ch == "_") else "_"
        for ch in str(value).upper()
    )


def _normalize_part(part: str) -> str:
    """Normalize a character part identifier to its canonical form."""
    cleaned = "".join(
        ch if (ch.isalnum() or ch == "_") else "_"
        for ch in str(part).strip().upper()
    )
    aliases = {
        "ARM_LEFT": "LEFT_ARM",
        "ARM_RIGHT": "RIGHT_ARM",
        "LEG_LEFT": "LEFT_LEG",
        "LEG_RIGHT": "RIGHT_LEG",
    }
    return aliases.get(cleaned, cleaned)


def known_environment_ids():
    """Yield the set of currently registered environment identifiers."""
    return tuple(get_environment(eid)["id"] for eid in ("living_room",))


def known_character_ids():
    """Yield the set of currently registered character identifiers."""
    return tuple(get_character(cid)["id"] for cid in ("husband", "wife"))