"""Tests for TOONFLOW AI Basic Scene Generation pre-generation validation.

These tests are pure Python: they do not require Blender. They verify:

1. Invalid Scene Plan is rejected before any Blender side effect.
2. Unknown environment is rejected.
3. Unknown character is rejected.
4. A valid Scene Plan passes pre-generation validation.
5. The input Scene Plan is never mutated.

Run from the project root:

    python -m unittest discover -s tests -v
"""

import importlib
import importlib.util
import types
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_PKG_PATH = PROJECT_ROOT / "addon" / "toonflow_ai"
if str(ADDON_PKG_PATH) not in sys.path:
    sys.path.insert(0, str(ADDON_PKG_PATH))


def _ensure_pkg(name, path):
    if name in sys.modules:
        return sys.modules[name]
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(path)]
    sys.modules[name] = pkg
    return pkg


_ensure_pkg("toonflow_ai", ADDON_PKG_PATH)

generation_pkg = importlib.import_module("toonflow_ai.generation")
validation_mod = importlib.import_module("toonflow_ai.generation.validation")
errors_mod = importlib.import_module("toonflow_ai.generation.errors")
naming_mod = importlib.import_module("toonflow_ai.generation.naming")


VALID_PLAN = {
    "version": "0.1",
    "scene": {"environment": "living_room"},
    "characters": [
        {"id": "husband", "role": "husband"},
        {"id": "wife", "role": "wife"},
    ],
}


class GenerationPackageImportTests(unittest.TestCase):
    def test_generate_scene_is_exported(self):
        self.assertTrue(hasattr(generation_pkg, "generate_scene"))
        self.assertTrue(callable(generation_pkg.generate_scene))

    def test_generation_result_is_exported(self):
        self.assertTrue(hasattr(generation_pkg, "GenerationResult"))

    def test_errors_are_exported(self):
        for name in (
            "GenerationError",
            "InvalidScenePlanError",
            "UnknownAssetError",
            "BlenderUnavailableError",
        ):
            self.assertTrue(hasattr(generation_pkg, name), name)

    def test_validation_does_not_import_bpy(self):
        import inspect

        src = inspect.getsource(validation_mod)
        self.assertNotIn("import bpy", src)
        self.assertNotIn("from bpy", src)

    def test_naming_is_deterministic(self):
        self.assertEqual(
            naming_mod.env_object_name("living_room"),
            "TOONFLOW_ENV_LIVING_ROOM",
        )
        self.assertEqual(
            naming_mod.character_object_name("husband"),
            "TOONFLOW_CHARACTER_HUSBAND",
        )
        self.assertEqual(
            naming_mod.character_object_name("wife"),
            "TOONFLOW_CHARACTER_WIFE",
        )

    def test_is_toonflow_name(self):
        self.assertTrue(naming_mod.is_toonflow_name("TOONFLOW"))
        self.assertTrue(naming_mod.is_toonflow_name("TOONFLOW_ENV_LIVING_ROOM"))
        self.assertTrue(naming_mod.is_toonflow_name("TOONFLOW_CHARACTER_HUSBAND"))
        self.assertFalse(naming_mod.is_toonflow_name("Cube"))
        self.assertFalse(naming_mod.is_toonflow_name("Light"))


class InvalidScenePlanRejectionTests(unittest.TestCase):
    def test_non_dictionary_is_rejected(self):
        with self.assertRaises(errors_mod.InvalidScenePlanError) as ctx:
            validation_mod.validate_scene_plan_for_generation("not a plan")
        self.assertEqual(len(ctx.exception.errors), 1)

    def test_missing_version_is_rejected(self):
        bad = {
            "scene": {"environment": "living_room"},
            "characters": [],
        }
        with self.assertRaises(errors_mod.InvalidScenePlanError):
            validation_mod.validate_scene_plan_for_generation(bad)

    def test_unknown_environment_is_rejected(self):
        bad = {
            "version": "0.1",
            "scene": {"environment": "castle"},
            "characters": [],
        }
        with self.assertRaises(errors_mod.UnknownAssetError) as ctx:
            validation_mod.validate_scene_plan_for_generation(bad)
        self.assertEqual(ctx.exception.asset_id, "castle")
        self.assertEqual(ctx.exception.asset_type, "environment")

    def test_unknown_character_is_rejected(self):
        bad = {
            "version": "0.1",
            "scene": {"environment": "living_room"},
            "characters": [{"id": "stranger", "role": "guest"}],
        }
        with self.assertRaises(errors_mod.UnknownAssetError) as ctx:
            validation_mod.validate_scene_plan_for_generation(bad)
        self.assertEqual(ctx.exception.asset_id, "stranger")
        self.assertEqual(ctx.exception.asset_type, "character")

    def test_duplicate_character_id_is_rejected(self):
        bad = {
            "version": "0.1",
            "scene": {"environment": "living_room"},
            "characters": [
                {"id": "husband", "role": "husband"},
                {"id": "husband", "role": "wife"},
            ],
        }
        with self.assertRaises(errors_mod.InvalidScenePlanError):
            validation_mod.validate_scene_plan_for_generation(bad)


class ValidScenePlanAcceptanceTests(unittest.TestCase):
    def test_minimal_valid_plan_passes(self):
        plan = {
            "version": "0.1",
            "scene": {"environment": "living_room"},
            "characters": [],
        }
        validation_mod.validate_scene_plan_for_generation(plan)

    def test_full_valid_plan_passes(self):
        validation_mod.validate_scene_plan_for_generation(VALID_PLAN)

    def test_input_plan_is_not_mutated(self):
        snapshot = {
            "version": VALID_PLAN["version"],
            "scene": dict(VALID_PLAN["scene"]),
            "characters": [dict(c) for c in VALID_PLAN["characters"]],
        }
        validation_mod.validate_scene_plan_for_generation(VALID_PLAN)
        self.assertEqual(VALID_PLAN, snapshot)


class BlenderUnavailableTests(unittest.TestCase):
    def test_generate_scene_raises_when_bpy_missing(self):
        with self.assertRaises(errors_mod.GenerationError):
            generation_pkg.generate_scene(VALID_PLAN)


if __name__ == "__main__":
    unittest.main()