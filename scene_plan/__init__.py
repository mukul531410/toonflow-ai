"""Scene Plan data contract for TOONFLOW AI.

This package is intentionally independent from:
- Blender (no bpy imports)
- AI providers
- The Blender add-on UI/registration layer

It defines the minimal structured Scene Plan that future AI planners
will produce and that future Blender automation will consume, plus a
deterministic validation layer for that contract.

MVP scope (TOONFLOW-PHASE-003):
- version
- scene.environment
- characters[].id, characters[].role
"""

from .schema import SUPPORTED_VERSIONS
from .validation import (
    ValidationError,
    ValidationResult,
    validate_scene_plan,
)

__all__ = (
    "SUPPORTED_VERSIONS",
    "ValidationError",
    "ValidationResult",
    "validate_scene_plan",
)