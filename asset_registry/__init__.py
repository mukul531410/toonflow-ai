"""Read-only registry of predefined TOONFLOW AI assets.

The registry is independent from Blender, Scene Plan validation, and AI
providers.  It maps known asset identifiers to minimal asset metadata only.
"""

from .registry import (
    character_exists,
    environment_exists,
    get_character,
    get_environment,
)

__all__ = (
    "get_environment",
    "get_character",
    "environment_exists",
    "character_exists",
)
