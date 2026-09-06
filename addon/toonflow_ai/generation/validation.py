"""Pre-generation validation for TOONFLOW AI scene generation.

This module is pure Python: it does not import ``bpy``. It combines:

1. Scene Plan schema validation (delegated to the ``scene_plan`` package).
2. Asset Registry existence checks for the referenced environment and
   character identifiers.

The result is a single, deterministic gate that runs **before** any
Blender side effect.

Nothing here mutates the input Scene Plan dictionary.
"""

from typing import Mapping, Sequence

from asset_registry import character_exists, environment_exists
from scene_plan import validate_scene_plan

from .errors import InvalidScenePlanError, UnknownAssetError


def validate_scene_plan_for_generation(scene_plan_data: object) -> None:
    """Validate a Scene Plan dict for the generation pipeline.

    Raises:
        InvalidScenePlanError: When the Scene Plan fails schema validation.
        UnknownAssetError: When the Scene Plan references an environment
            or character identifier that is not present in the Asset
            Registry.

    The input is never mutated.
    """
    plan_result = validate_scene_plan(scene_plan_data)
    if not plan_result.is_valid:
        raise InvalidScenePlanError(plan_result.errors)

    if not isinstance(scene_plan_data, Mapping):
        raise InvalidScenePlanError(plan_result.errors)

    environment_id = scene_plan_data["scene"]["environment"]
    if not environment_exists(environment_id):
        raise UnknownAssetError(environment_id, "environment")

    characters = scene_plan_data["characters"]
    if not isinstance(characters, Sequence):
        raise InvalidScenePlanError(plan_result.errors)

    seen_ids = set()
    for character in characters:
        cid = character["id"]
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        if not character_exists(cid):
            raise UnknownAssetError(cid, "character")