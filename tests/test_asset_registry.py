"""Tests for the stdlib-only TOONFLOW AI Asset Registry.

Run from the project root:

    python -m unittest discover -s tests -v
"""

import inspect
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asset_registry.registry as registry  # noqa: E402
from asset_registry import (  # noqa: E402
    character_exists,
    environment_exists,
    get_character,
    get_environment,
)


class EnvironmentRegistryTests(unittest.TestCase):
    def test_existing_environment_lookup(self):
        self.assertEqual(
            get_environment("living_room"),
            {
                "id": "living_room",
                "asset_type": "environment",
                "display_name": "Living Room",
            },
        )

    def test_unknown_environment_returns_none(self):
        self.assertIsNone(get_environment("castle"))

    def test_existing_environment_exists(self):
        self.assertTrue(environment_exists("living_room"))

    def test_unknown_environment_does_not_exist(self):
        self.assertFalse(environment_exists("castle"))


class CharacterRegistryTests(unittest.TestCase):
    def test_existing_character_lookup(self):
        self.assertEqual(
            get_character("husband"),
            {
                "id": "husband",
                "asset_type": "character",
                "display_name": "Husband",
            },
        )

    def test_unknown_character_returns_none(self):
        self.assertIsNone(get_character("villain"))

    def test_existing_character_exists(self):
        self.assertTrue(character_exists("wife"))

    def test_unknown_character_does_not_exist(self):
        self.assertFalse(character_exists("villain"))


class RegistrySafetyTests(unittest.TestCase):
    def test_returned_definition_does_not_mutate_registry(self):
        definition = get_environment("living_room")
        definition["display_name"] = "Changed"

        self.assertEqual(get_environment("living_room")["display_name"], "Living Room")

    def test_environment_and_character_lookups_are_isolated(self):
        self.assertIsNone(get_environment("husband"))
        self.assertIsNone(get_character("living_room"))

    def test_non_string_identifiers_are_unknown(self):
        self.assertIsNone(get_environment(None))
        self.assertIsNone(get_character(["husband"]))


class DependencySafetyTests(unittest.TestCase):
    def test_registry_has_no_bpy_dependency(self):
        self.assertNotIn("bpy", inspect.getsource(registry))

    def test_registry_uses_standard_library_only(self):
        self.assertEqual(registry.MappingProxyType.__module__, "builtins")


if __name__ == "__main__":
    unittest.main()
