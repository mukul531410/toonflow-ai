"""Definitions and lookup functions for predefined TOONFLOW AI assets.

This module intentionally knows nothing about Blender files or loading.  The
stored definitions are immutable, while public lookup functions return fresh
dictionaries so callers cannot modify registry state.
"""

from types import MappingProxyType


_ENVIRONMENTS = MappingProxyType(
    {
        "living_room": MappingProxyType(
            {
                "id": "living_room",
                "asset_type": "environment",
                "display_name": "Living Room",
            }
        ),
    }
)

_CHARACTERS = MappingProxyType(
    {
        "husband": MappingProxyType(
            {
                "id": "husband",
                "asset_type": "character",
                "display_name": "Husband",
            }
        ),
        "wife": MappingProxyType(
            {
                "id": "wife",
                "asset_type": "character",
                "display_name": "Wife",
            }
        ),
    }
)


def _get_asset(definitions, asset_id: object):
    """Return a detached asset definition, or ``None`` when unknown."""
    if not isinstance(asset_id, str):
        return None

    definition = definitions.get(asset_id)
    return None if definition is None else dict(definition)


def get_environment(asset_id: object):
    """Return a copy of an environment definition, or ``None`` if unknown."""
    return _get_asset(_ENVIRONMENTS, asset_id)


def get_character(asset_id: object):
    """Return a copy of a character definition, or ``None`` if unknown."""
    return _get_asset(_CHARACTERS, asset_id)


def environment_exists(asset_id: object) -> bool:
    """Return whether *asset_id* is a registered environment."""
    return get_environment(asset_id) is not None


def character_exists(asset_id: object) -> bool:
    """Return whether *asset_id* is a registered character."""
    return get_character(asset_id) is not None
