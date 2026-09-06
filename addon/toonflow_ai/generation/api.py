"""Public API for TOONFLOW AI Basic Scene Generation.

    from toonflow_ai.generation import generate_scene, GenerationResult

Behavior:

- Validates the input Scene Plan against the Scene Plan schema.
- Verifies that referenced environment and character identifiers exist
  in the Asset Registry.
- On any validation failure, raises a clear ``GenerationError`` subclass
  (``InvalidScenePlanError`` or ``UnknownAssetError``); no Blender side
  effects occur.
- On success, generates a minimal placeholder Blender scene containing:

    - a floor plane named ``TOONFLOW_ENV_<ENV_ID>``
    - per-character body+head primitives named
      ``TOONFLOW_CHARACTER_<CHAR_ID>_BODY`` and ``..._HEAD``

  All generated objects are placed inside a single ``TOONFLOW``
  collection.

- Re-running with the same Scene Plan replaces only the previously
  generated TOONFLOW objects; no unrelated scene objects are touched.

This phase does NOT use AI and does NOT load real Blender assets.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from .blender_generator import generate_in_blender
from .errors import (
    BlenderUnavailableError,
    GenerationError,
    InvalidScenePlanError,
    UnknownAssetError,
)
from .validation import validate_scene_plan_for_generation


@dataclass(frozen=True)
class GenerationResult:
    """The outcome of a successful ``generate_scene`` call.

    Attributes:
        collection_name: Name of the Blender collection that owns the
            generated objects.
        environment_id: Identifier of the environment that was generated.
        environment_object_names: Names of the created environment
            objects (deterministic).
        character_ids: Identifiers of the characters that were generated,
            in the order they appeared in the Scene Plan.
        character_object_names: Names of the created character objects
            (deterministic).
    """

    collection_name: str
    environment_id: str
    environment_object_names: List[str]
    character_ids: List[str]
    character_object_names: List[str]


__all__ = (
    "generate_scene",
    "GenerationResult",
    "GenerationError",
    "InvalidScenePlanError",
    "UnknownAssetError",
    "BlenderUnavailableError",
)


def generate_scene(scene_plan_data: Any) -> GenerationResult:
    """Generate a minimal Blender scene from a validated Scene Plan.

    Args:
        scene_plan_data: A Scene Plan dictionary. The input is not mutated.

    Returns:
        A :class:`GenerationResult` describing the objects that were
        created.

    Raises:
        InvalidScenePlanError: When ``scene_plan_data`` does not match
            the supported Scene Plan schema. The ``errors`` attribute
            exposes the underlying validation errors.
        UnknownAssetError: When the Scene Plan references an environment
            or character identifier that is not registered in the Asset
            Registry. The ``asset_id`` and ``asset_type`` attributes
            expose the offending value.
        BlenderUnavailableError: When ``bpy`` cannot be imported (the
            function must be called from inside Blender).
    """
    validate_scene_plan_for_generation(scene_plan_data)

    summary = generate_in_blender(scene_plan_data)

    return GenerationResult(
        collection_name=summary["collection_name"],
        environment_id=summary["environment_id"],
        environment_object_names=list(summary["environment_object_names"]),
        character_ids=list(summary["character_ids"]),
        character_object_names=list(summary["character_object_names"]),
    )