"""Tests for the TOONFLOW AI Scene Plan validation layer.

Uses only the Python standard library (unittest). No Blender required.
Run from the project root:

    python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

# Make the project root importable so `import scene_plan` works regardless
# of where the test runner is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scene_plan import ValidationError, ValidationResult, validate_scene_plan  # noqa: E402
from scene_plan.schema import SUPPORTED_VERSIONS  # noqa: E402


VALID_MINIMAL = {
    "version": "0.1",
    "scene": {"environment": "living_room"},
    "characters": [],
}

VALID_MULTIPLE = {
    "version": "0.1",
    "scene": {"environment": "kitchen"},
    "characters": [
        {"id": "husband", "role": "husband"},
        {"id": "wife", "role": "wife"},
    ],
}


class ValidScenePlanTests(unittest.TestCase):
    def test_minimal_valid(self):
        result = validate_scene_plan(VALID_MINIMAL)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_multiple_characters(self):
        result = validate_scene_plan(VALID_MULTIPLE)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_input_is_not_mutated(self):
        snapshot = {
            "version": "0.1",
            "scene": {"environment": "garden"},
            "characters": [{"id": "kid", "role": "child"}],
        }
        before = {
            "version": snapshot["version"],
            "scene": dict(snapshot["scene"]),
            "characters": [dict(c) for c in snapshot["characters"]],
        }
        validate_scene_plan(snapshot)
        self.assertEqual(snapshot, before)

    def test_returns_validation_result(self):
        result = validate_scene_plan(VALID_MINIMAL)
        self.assertIsInstance(result, ValidationResult)
        self.assertTrue(bool(result))

    def test_supported_versions_is_non_empty(self):
        self.assertTrue(SUPPORTED_VERSIONS)
        self.assertIn("0.1", SUPPORTED_VERSIONS)


class InvalidScenePlanTests(unittest.TestCase):
    def assertInvalid(self, data, expected_substrings):
        result = validate_scene_plan(data)
        self.assertFalse(result.is_valid)
        self.assertTrue(result.errors, "expected at least one error")
        joined = " | ".join(
            f"{e.path}: {e.message}" for e in result.errors
        )
        for needle in expected_substrings:
            self.assertIn(needle, joined, msg=f"missing {needle!r} in: {joined}")

    def test_non_dictionary_input(self):
        result = validate_scene_plan("not a plan")
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 1)
        self.assertIsInstance(result.errors[0], ValidationError)
        self.assertIn("dictionary", result.errors[0].message)

    def test_list_input_rejected(self):
        result = validate_scene_plan([])
        self.assertFalse(result.is_valid)
        self.assertIn("dictionary", result.errors[0].message)

    def test_none_input_rejected(self):
        result = validate_scene_plan(None)
        self.assertFalse(result.is_valid)
        self.assertIn("dictionary", result.errors[0].message)

    def test_missing_version(self):
        data = {"scene": {"environment": "x"}, "characters": []}
        self.assertInvalid(data, ["version"])

    def test_unsupported_version(self):
        data = {
            "version": "99.0",
            "scene": {"environment": "x"},
            "characters": [],
        }
        self.assertInvalid(data, ["Unsupported version"])

    def test_non_string_version(self):
        data = {"version": 1, "scene": {"environment": "x"}, "characters": []}
        self.assertInvalid(data, ["version", "must be a string"])

    def test_missing_scene(self):
        data = {"version": "0.1", "characters": []}
        self.assertInvalid(data, ["scene"])

    def test_scene_not_a_dict(self):
        data = {"version": "0.1", "scene": "living_room", "characters": []}
        self.assertInvalid(data, ["scene", "must be a dictionary"])

    def test_missing_environment(self):
        data = {"version": "0.1", "scene": {}, "characters": []}
        self.assertInvalid(data, ["environment"])

    def test_empty_environment(self):
        data = {"version": "0.1", "scene": {"environment": ""}, "characters": []}
        self.assertInvalid(data, ["environment", "non-empty"])

    def test_non_string_environment(self):
        data = {"version": "0.1", "scene": {"environment": 5}, "characters": []}
        self.assertInvalid(data, ["environment", "non-empty"])

    def test_missing_characters(self):
        data = {"version": "0.1", "scene": {"environment": "x"}}
        self.assertInvalid(data, ["characters"])

    def test_characters_not_a_list(self):
        data = {
            "version": "0.1",
            "scene": {"environment": "x"},
            "characters": {"id": "husband", "role": "husband"},
        }
        self.assertInvalid(data, ["characters", "must be a list"])

    def test_character_missing_id(self):
        data = {
            "version": "0.1",
            "scene": {"environment": "x"},
            "characters": [{"role": "wife"}],
        }
        self.assertInvalid(data, ["characters[0].id"])

    def test_character_missing_role(self):
        data = {
            "version": "0.1",
            "scene": {"environment": "x"},
            "characters": [{"id": "wife"}],
        }
        self.assertInvalid(data, ["characters[0].role"])

    def test_character_not_a_dict(self):
        data = {
            "version": "0.1",
            "scene": {"environment": "x"},
            "characters": ["wife"],
        }
        self.assertInvalid(data, ["characters[0]", "must be a dictionary"])

    def test_empty_character_id(self):
        data = {
            "version": "0.1",
            "scene": {"environment": "x"},
            "characters": [{"id": "", "role": "wife"}],
        }
        self.assertInvalid(data, ["characters[0].id", "non-empty"])

    def test_empty_character_role(self):
        data = {
            "version": "0.1",
            "scene": {"environment": "x"},
            "characters": [{"id": "wife", "role": ""}],
        }
        self.assertInvalid(data, ["characters[0].role", "non-empty"])

    def test_duplicate_character_ids(self):
        data = {
            "version": "0.1",
            "scene": {"environment": "x"},
            "characters": [
                {"id": "husband", "role": "husband"},
                {"id": "husband", "role": "wife"},
            ],
        }
        self.assertInvalid(data, ["Duplicate character id"])

    def test_duplicate_ids_after_empty_string(self):
        data = {
            "version": "0.1",
            "scene": {"environment": "x"},
            "characters": [
                {"id": "", "role": "a"},
                {"id": "", "role": "b"},
            ],
        }
        # Both ids are empty strings — should fail both on "non-empty"
        # and on duplicate; the duplicate check requires non-empty so
        # we only expect non-empty errors here. This guards against the
        # false-positive duplicate reported for two "" ids.
        result = validate_scene_plan(data)
        self.assertFalse(result.is_valid)
        self.assertFalse(any("Duplicate character id" in e.message for e in result.errors))


if __name__ == "__main__":
    unittest.main()