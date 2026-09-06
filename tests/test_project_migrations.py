"""Tests for TOONFLOW-PHASE-018 ``workflow.project_migrations``.

The migration module is pure-Python, ``bpy``-free, AI-free, and
dependency-free, so the tests do not need the ``bpy`` stub machinery
used by the other workflow / generation test modules.

The tests are grouped as:

- :class:`ConstantsTests` — exported constants and their invariants.
- :class:`UnsupportedProjectSchemaErrorTests` — the structured error.
- :class:`VersionValidationTests` — ``_validate_schema_version_value``.
- :class:`MigrationPathTests` — ``_build_migration_path``.
- :class:`MigrateToVersionTests` — ``migrate_project_dict_to_version``.
- :class:`MigrateProjectDictTests` — ``migrate_project_dict``.
- :class:`V1ToV2MigrationTests` — the single registered migration step.
- :class:`DeepCopyTests` — the ``_deep_copy`` helper.
- :class:`ProjectIntegrationTests` — integration with
  :func:`workflow.project.project_from_dict`.
- :class:`ArchitectureTests` — guard rails (no ``bpy``, no AI, etc.).
"""

import ast
import re
import unittest

from workflow.project_migrations import (
    PROJECT_SCHEMA_VERSION,
    SUPPORTED_PROJECT_SCHEMA_VERSIONS,
    DESCRIPTION_FIELD,
    UnsupportedProjectSchemaError,
    migrate_project_dict,
    migrate_project_dict_to_version,
    _validate_schema_version_value,
    _build_migration_path,
    _deep_copy,
    _migrate_v1_to_v2,
    _MIGRATION_STEPS,
)


MIGRATIONS_PATH = "workflow.project_migrations"
MODULE_SOURCE = open(
    "workflow/project_migrations.py", "r", encoding="utf-8",
).read()


def _ast_all_imports(source):
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(node.module)
    return out


def _ast_top_level_imports(source):
    tree = ast.parse(source)
    out = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append((node.module, getattr(node, "level", 0)))
    return out


def _make_v1_dict(name="alpha", shots=None, **extra):
    """Build a minimal v1 project dict for tests.

    Shots in v1 are full PHASE-017 shot dicts (concept, animation,
    animation_start_frame, lip_sync, lip_sync_start_frame,
    output_path). The v1 -> v2 migration does not touch shot shape.
    """
    if shots is None:
        shots = [_make_v1_shot()]
    data = {
        "schema_version": 1,
        "name": name,
        "shots": list(shots),
    }
    data.update(extra)
    return data


def _make_v1_shot(concept="c", animation="walk", animation_start_frame=1,
                  lip_sync=None, lip_sync_start_frame=None,
                  output_path="/tmp/out.mp4"):
    return {
        "concept": concept,
        "animation": animation,
        "animation_start_frame": animation_start_frame,
        "lip_sync": lip_sync,
        "lip_sync_start_frame": lip_sync_start_frame,
        "output_path": output_path,
    }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class ConstantsTests(unittest.TestCase):
    def test_current_schema_version_is_int(self):
        self.assertIsInstance(PROJECT_SCHEMA_VERSION, int)
        self.assertNotIsInstance(PROJECT_SCHEMA_VERSION, bool)

    def test_current_schema_version_is_positive(self):
        self.assertGreaterEqual(PROJECT_SCHEMA_VERSION, 1)

    def test_supported_versions_is_tuple_of_ints(self):
        self.assertIsInstance(SUPPORTED_PROJECT_SCHEMA_VERSIONS, tuple)
        for v in SUPPORTED_PROJECT_SCHEMA_VERSIONS:
            self.assertIsInstance(v, int)
            self.assertNotIsInstance(v, bool)
            self.assertGreaterEqual(v, 1)

    def test_supported_versions_contains_current(self):
        self.assertIn(PROJECT_SCHEMA_VERSION, SUPPORTED_PROJECT_SCHEMA_VERSIONS)

    def test_supported_versions_is_strictly_ascending(self):
        versions = list(SUPPORTED_PROJECT_SCHEMA_VERSIONS)
        for a, b in zip(versions, versions[1:]):
            self.assertLess(a, b)

    def test_supported_versions_excludes_duplicates(self):
        versions = list(SUPPORTED_PROJECT_SCHEMA_VERSIONS)
        self.assertEqual(len(versions), len(set(versions)))

    def test_description_field_is_string(self):
        self.assertIsInstance(DESCRIPTION_FIELD, str)
        self.assertGreater(len(DESCRIPTION_FIELD), 0)


# ---------------------------------------------------------------------------
# UnsupportedProjectSchemaError
# ---------------------------------------------------------------------------


class UnsupportedProjectSchemaErrorTests(unittest.TestCase):
    def test_is_value_error(self):
        err = UnsupportedProjectSchemaError(99, (1, 2), 2)
        self.assertIsInstance(err, ValueError)

    def test_attributes_round_trip(self):
        err = UnsupportedProjectSchemaError(99, (1, 2), 2)
        self.assertEqual(err.provided_version, 99)
        self.assertEqual(tuple(err.supported_versions), (1, 2))
        self.assertEqual(err.current_version, 2)

    def test_supported_versions_is_tuple(self):
        err = UnsupportedProjectSchemaError(0, [1, 2], 2)
        self.assertIsInstance(err.supported_versions, tuple)
        self.assertEqual(err.supported_versions, (1, 2))

    def test_current_version_is_int(self):
        err = UnsupportedProjectSchemaError(5, (1, 2), 2)
        self.assertIsInstance(err.current_version, int)
        self.assertNotIsInstance(err.current_version, bool)

    def test_message_mentions_provided_and_supported_and_current(self):
        err = UnsupportedProjectSchemaError(99, (1, 2), 2)
        msg = str(err)
        self.assertIn("99", msg)
        self.assertIn("1", msg)
        self.assertIn("2", msg)

    def test_can_be_raised_and_caught_as_value_error(self):
        with self.assertRaises(ValueError):
            raise UnsupportedProjectSchemaError(3, (1, 2), 2)

    def test_provided_version_preserved_as_given(self):
        # Provided version is preserved unchanged for diagnostics even
        # if it is not a positive int.
        err = UnsupportedProjectSchemaError("v9", (1, 2), 2)
        self.assertEqual(err.provided_version, "v9")


# ---------------------------------------------------------------------------
# _validate_schema_version_value
# ---------------------------------------------------------------------------


class VersionValidationTests(unittest.TestCase):
    def test_accepts_positive_int(self):
        for v in (1, 2, 3, 100):
            self.assertEqual(
                _validate_schema_version_value(v, parameter="schema_version"),
                v,
            )

    def test_returns_int(self):
        result = _validate_schema_version_value(2, parameter="schema_version")
        self.assertIsInstance(result, int)
        self.assertNotIsInstance(result, bool)

    def test_rejects_none_with_type_error(self):
        with self.assertRaises(TypeError):
            _validate_schema_version_value(None, parameter="schema_version")

    def test_rejects_bool_with_type_error(self):
        with self.assertRaises(TypeError):
            _validate_schema_version_value(True, parameter="schema_version")
        with self.assertRaises(TypeError):
            _validate_schema_version_value(False, parameter="schema_version")

    def test_rejects_string_with_type_error(self):
        with self.assertRaises(TypeError):
            _validate_schema_version_value("1", parameter="schema_version")

    def test_rejects_float_with_type_error(self):
        with self.assertRaises(TypeError):
            _validate_schema_version_value(1.0, parameter="schema_version")

    def test_rejects_list_with_type_error(self):
        with self.assertRaises(TypeError):
            _validate_schema_version_value([1], parameter="schema_version")

    def test_rejects_zero_with_value_error(self):
        with self.assertRaises(ValueError):
            _validate_schema_version_value(0, parameter="schema_version")

    def test_rejects_negative_with_value_error(self):
        with self.assertRaises(ValueError):
            _validate_schema_version_value(-1, parameter="schema_version")

    def test_value_error_is_not_type_error(self):
        # 0 is an int but not >= 1 -> ValueError, not TypeError.
        try:
            _validate_schema_version_value(0, parameter="schema_version")
        except TypeError:
            self.fail("ValueError scenario raised TypeError")
        except ValueError:
            pass

    def test_type_error_is_not_value_error(self):
        # True is a bool -> TypeError, not ValueError.
        try:
            _validate_schema_version_value(True, parameter="schema_version")
        except ValueError:
            self.fail("TypeError scenario raised ValueError")
        except TypeError:
            pass

    def test_message_mentions_parameter(self):
        try:
            _validate_schema_version_value(None, parameter="my_param")
        except TypeError as exc:
            self.assertIn("my_param", str(exc))


# ---------------------------------------------------------------------------
# _build_migration_path
# ---------------------------------------------------------------------------


class MigrationPathTests(unittest.TestCase):
    def test_identity_path_when_source_equals_target(self):
        self.assertEqual(_build_migration_path(2, 2), [])

    def test_v1_to_v2_single_step(self):
        path = _build_migration_path(1, 2)
        self.assertEqual(len(path), 1)
        src, fn = path[0]
        self.assertEqual(src, 1)
        self.assertIs(fn, _migrate_v1_to_v2)

    def test_migration_steps_cover_all_supported_gaps(self):
        # The ordered registry must be a complete bridge between every
        # adjacent pair of supported versions.
        versions = list(SUPPORTED_PROJECT_SCHEMA_VERSIONS)
        for a, b in zip(versions, versions[1:]):
            step = next(
                ((src, fn) for src, fn in _MIGRATION_STEPS if src == a),
                None,
            )
            self.assertIsNotNone(
                step, f"no migration step registered for {a} -> {b}"
            )

    def test_reverse_migration_raises(self):
        with self.assertRaises(UnsupportedProjectSchemaError):
            _build_migration_path(2, 1)

    def test_unknown_source_raises(self):
        with self.assertRaises(UnsupportedProjectSchemaError) as ctx:
            _build_migration_path(99, 2)
        self.assertEqual(ctx.exception.provided_version, 99)

    def test_unknown_target_raises(self):
        # Source=1 has no path to target=99 (no migration from 1 all
        # the way to 99). The error is raised with a ``provided_version``
        # that points at the first unreachable intermediate version.
        with self.assertRaises(UnsupportedProjectSchemaError):
            _build_migration_path(1, 99)

    def test_unknown_target_far_above_source_raises(self):
        # Source is unknown AND target is unknown. The error is raised.
        with self.assertRaises(UnsupportedProjectSchemaError):
            _build_migration_path(50, 99)

    def test_path_is_ordered_ascending(self):
        path = _build_migration_path(1, 2)
        versions_in_path = [src for src, _ in path] + [
            path[-1][0] + 1 if path else None,
        ]
        # versions_in_path = [1, 2] for v1 -> v2
        self.assertEqual(versions_in_path, [1, 2])


# ---------------------------------------------------------------------------
# migrate_project_dict_to_version
# ---------------------------------------------------------------------------


class MigrateToVersionTests(unittest.TestCase):
    def test_v1_to_current_produces_v2_with_description(self):
        data = _make_v1_dict()
        result = migrate_project_dict_to_version(data, 2)
        self.assertEqual(result["schema_version"], 2)
        self.assertIn(DESCRIPTION_FIELD, result)
        self.assertEqual(result[DESCRIPTION_FIELD], "")

    def test_v2_to_current_is_passthrough_deepcopy(self):
        data = {
            "schema_version": 2,
            "name": "x",
            "description": "hello",
            "shots": [{"concept": "a"}],
        }
        result = migrate_project_dict_to_version(data, 2)
        self.assertEqual(result, data)
        # Independent copy: mutating result must not affect input.
        result["name"] = "mutated"
        self.assertEqual(data["name"], "x")

    def test_does_not_mutate_input(self):
        data = _make_v1_dict(name="keep_me", shots=[{"concept": "c"}])
        snapshot = {
            "schema_version": data["schema_version"],
            "name": data["name"],
            "shots": [dict(s) for s in data["shots"]],
        }
        _ = migrate_project_dict_to_version(data, 2)
        self.assertEqual(data, snapshot)

    def test_rejects_non_dict_input(self):
        for bad in (None, "x", 42, [1, 2]):
            with self.assertRaises(TypeError):
                migrate_project_dict_to_version(bad, 2)

    def test_rejects_unsupported_target_with_value_error(self):
        with self.assertRaises(UnsupportedProjectSchemaError):
            migrate_project_dict_to_version(_make_v1_dict(), 99)

    def test_rejects_unsupported_source_with_value_error(self):
        with self.assertRaises(UnsupportedProjectSchemaError):
            migrate_project_dict_to_version(
                {"schema_version": 99, "name": "x", "shots": []}, 2,
            )

    def test_rejects_non_int_target(self):
        with self.assertRaises(TypeError):
            migrate_project_dict_to_version(_make_v1_dict(), "2")
        with self.assertRaises(TypeError):
            migrate_project_dict_to_version(_make_v1_dict(), True)

    def test_rejects_zero_or_negative_target(self):
        with self.assertRaises(ValueError):
            migrate_project_dict_to_version(_make_v1_dict(), 0)
        with self.assertRaises(ValueError):
            migrate_project_dict_to_version(_make_v1_dict(), -1)

    def test_rejects_missing_schema_version(self):
        with self.assertRaises(UnsupportedProjectSchemaError):
            migrate_project_dict_to_version({"name": "x", "shots": []}, 2)

    def test_rejects_non_int_source(self):
        with self.assertRaises(TypeError):
            migrate_project_dict_to_version(
                {"schema_version": "v1", "name": "x", "shots": []}, 2,
            )

    def test_rejects_reverse_migration(self):
        with self.assertRaises(UnsupportedProjectSchemaError):
            migrate_project_dict_to_version(
                {
                    "schema_version": 2,
                    "name": "x",
                    "description": "",
                    "shots": [],
                },
                1,
            )


# ---------------------------------------------------------------------------
# migrate_project_dict
# ---------------------------------------------------------------------------


class MigrateProjectDictTests(unittest.TestCase):
    def test_default_target_is_current_version(self):
        data = _make_v1_dict()
        result = migrate_project_dict(data)
        self.assertEqual(result["schema_version"], PROJECT_SCHEMA_VERSION)

    def test_v1_input_becomes_current(self):
        data = _make_v1_dict()
        result = migrate_project_dict(data)
        self.assertEqual(result["schema_version"], PROJECT_SCHEMA_VERSION)
        self.assertEqual(result[DESCRIPTION_FIELD], "")

    def test_v2_input_becomes_current_unchanged_semantically(self):
        data = {
            "schema_version": 2,
            "name": "alpha",
            "description": "hello world",
            "shots": [{"concept": "c"}],
        }
        result = migrate_project_dict(data)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["name"], "alpha")
        self.assertEqual(result["description"], "hello world")
        self.assertEqual(result["shots"], [{"concept": "c"}])

    def test_does_not_mutate_input(self):
        data = _make_v1_dict(name="keep")
        before = {
            "schema_version": 1,
            "name": "keep",
            "shots": [_make_v1_shot()],
        }
        _ = migrate_project_dict(data)
        self.assertEqual(data, before)

    def test_propagates_type_error_for_non_dict(self):
        with self.assertRaises(TypeError):
            migrate_project_dict(None)

    def test_propagates_value_error_for_unsupported_version(self):
        with self.assertRaises(UnsupportedProjectSchemaError):
            migrate_project_dict({"schema_version": 99, "name": "x", "shots": []})


# ---------------------------------------------------------------------------
# _migrate_v1_to_v2
# ---------------------------------------------------------------------------


class V1ToV2MigrationTests(unittest.TestCase):
    def test_sets_schema_version_to_2(self):
        data = _make_v1_dict()
        result = _migrate_v1_to_v2(data)
        self.assertEqual(result["schema_version"], 2)

    def test_adds_empty_description_when_missing(self):
        data = _make_v1_dict()
        self.assertNotIn(DESCRIPTION_FIELD, data)
        result = _migrate_v1_to_v2(data)
        self.assertEqual(result[DESCRIPTION_FIELD], "")

    def test_preserves_existing_description(self):
        data = _make_v1_dict(**{DESCRIPTION_FIELD: "kept"})
        result = _migrate_v1_to_v2(data)
        self.assertEqual(result[DESCRIPTION_FIELD], "kept")

    def test_preserves_name(self):
        data = _make_v1_dict(name="alpha")
        result = _migrate_v1_to_v2(data)
        self.assertEqual(result["name"], "alpha")

    def test_preserves_shots_deep(self):
        data = _make_v1_dict(shots=[{"concept": "a", "nested": {"k": "v"}}])
        result = _migrate_v1_to_v2(data)
        self.assertEqual(result["shots"], data["shots"])
        # Independent copy: mutating inner shot must not affect input.
        result["shots"][0]["nested"]["k"] = "mutated"
        self.assertEqual(data["shots"][0]["nested"]["k"], "v")

    def test_does_not_mutate_input(self):
        data = _make_v1_dict()
        snapshot = {
            "schema_version": 1,
            "name": data["name"],
            "shots": [dict(s) for s in data["shots"]],
        }
        _ = _migrate_v1_to_v2(data)
        self.assertEqual(data, snapshot)

    def test_produces_independent_dict(self):
        data = _make_v1_dict()
        result = _migrate_v1_to_v2(data)
        result["name"] = "different"
        self.assertEqual(data["name"], "alpha")


# ---------------------------------------------------------------------------
# _deep_copy
# ---------------------------------------------------------------------------


class DeepCopyTests(unittest.TestCase):
    def test_returns_equal_but_independent_dict(self):
        data = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
        result = _deep_copy(data)
        self.assertEqual(result, data)
        result["b"].append(4)
        self.assertEqual(data["b"], [1, 2, 3])

    def test_preserves_non_ascii_strings(self):
        data = {"name": "\u3053\u3093\u306b\u3061\u306f", "emoji": "\U0001F600"}
        result = _deep_copy(data)
        self.assertEqual(result["name"], "\u3053\u3093\u306b\u3061\u306f")
        self.assertEqual(result["emoji"], "\U0001F600")

    def test_preserves_unicode_key_order(self):
        data = {"z": 1, "a": 2, "\u00e9": 3}
        result = _deep_copy(data)
        self.assertEqual(list(result.keys()), ["z", "a", "\u00e9"])

    def test_preserves_falsy_values(self):
        data = {"a": 0, "b": "", "c": False, "d": None, "e": []}
        result = _deep_copy(data)
        self.assertEqual(result, data)
        # Independent containers.
        result["e"].append(1)
        self.assertEqual(data["e"], [])

    def test_deep_copy_of_nested_structures(self):
        data = {"l1": {"l2": {"l3": [1, 2, {"k": "v"}]}}}
        result = _deep_copy(data)
        result["l1"]["l2"]["l3"][2]["k"] = "mutated"
        self.assertEqual(data["l1"]["l2"]["l3"][2]["k"], "v")

    def test_rejects_non_json_compatible(self):
        # ``_deep_copy`` uses a JSON round-trip, so objects that are not
        # JSON-encodable (e.g. a custom class) must fail.
        class NotEncodable:
            pass
        with self.assertRaises((TypeError, ValueError)):
            _deep_copy({"x": NotEncodable()})


# ---------------------------------------------------------------------------
# Project integration
# ---------------------------------------------------------------------------


class ProjectIntegrationTests(unittest.TestCase):
    def setUp(self):
        from workflow.project import project_from_dict, Project
        self.project_from_dict = project_from_dict
        self.Project = Project

    def test_v1_dict_round_trips_through_from_dict(self):
        v1 = _make_v1_dict(name="legacy", shots=[_make_v1_shot(concept="a")])
        project = self.project_from_dict(v1)
        self.assertEqual(project.name, "legacy")
        self.assertEqual(project.description, "")
        self.assertEqual(project.schema_version, PROJECT_SCHEMA_VERSION)

    def test_v1_dict_with_existing_description_preserved(self):
        v1 = _make_v1_dict(
            name="legacy",
            **{DESCRIPTION_FIELD: "kept"},
        )
        project = self.project_from_dict(v1)
        self.assertEqual(project.description, "kept")

    def test_v2_dict_round_trips_through_from_dict(self):
        v2 = {
            "schema_version": 2,
            "name": "modern",
            "description": "desc",
            "shots": [_make_v1_shot(concept="x")],
        }
        project = self.project_from_dict(v2)
        self.assertEqual(project.name, "modern")
        self.assertEqual(project.description, "desc")
        self.assertEqual(project.schema_version, 2)

    def test_load_does_not_mutate_caller_dict(self):
        v1 = _make_v1_dict(name="a", shots=[_make_v1_shot(concept="c")])
        snapshot = {
            "schema_version": 1,
            "name": "a",
            "shots": [_make_v1_shot(concept="c")],
        }
        _ = self.project_from_dict(v1)
        self.assertEqual(v1, snapshot)

    def test_unsupported_version_raises_project_input_error(self):
        from workflow.project import ProjectInputError
        with self.assertRaises(ProjectInputError) as ctx:
            self.project_from_dict({
                "schema_version": 99, "name": "x",
                "shots": [_make_v1_shot()],
            })
        self.assertEqual(ctx.exception.parameter, "project.schema_version")

    def test_round_trip_preserves_data(self):
        original = {
            "schema_version": 1,
            "name": "trip",
            "shots": [
                _make_v1_shot(concept="a"),
                _make_v1_shot(concept="b"),
            ],
        }
        project = self.project_from_dict(original)
        from workflow.project import project_to_dict
        d2 = project_to_dict(project)
        self.assertEqual(d2["schema_version"], 2)
        self.assertEqual(d2["name"], "trip")
        self.assertEqual(d2["description"], "")
        self.assertEqual(d2["shots"], original["shots"])


# ---------------------------------------------------------------------------
# Architecture guard rails
# ---------------------------------------------------------------------------


class ArchitectureTests(unittest.TestCase):
    def test_module_is_bpy_free(self):
        for name in _ast_all_imports(MODULE_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import: {name}",
            )

    def test_module_does_not_import_bpy(self):
        # Re-stated to be explicit: bpy is the only import we forbid.
        for name in _ast_all_imports(MODULE_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import: {name}",
            )

    def test_module_does_not_reference_bpy_in_code(self):
        # The docstring may mention the string ``bpy`` for context, but
        # no actual code path may reference the ``bpy`` module.
        tree = ast.parse(MODULE_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "bpy":
                self.fail("code references the bpy module")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "bpy":
                    self.fail(f"code references bpy.{node.attr}")

    def test_module_is_ai_free(self):
        for name in _ast_all_imports(MODULE_SOURCE):
            root = name.split(".")[0]
            self.assertNotIn(
                root,
                {"ai", "ollama", "ollama_client", "urllib", "urllib.request",
                 "requests", "http", "speech_recognition"},
                f"forbidden import: {name}",
            )

    def test_module_does_not_import_audio_libraries(self):
        for name in _ast_all_imports(MODULE_SOURCE):
            root = name.split(".")[0]
            self.assertNotIn(
                root,
                {"wave", "soundfile", "librosa", "audio"},
                f"forbidden audio import: {name}",
            )

    def test_module_does_not_import_pipeline_or_generation(self):
        for name in _ast_all_imports(MODULE_SOURCE):
            root = name.split(".")[0]
            self.assertNotIn(
                root,
                {"pipeline", "asset_registry", "scene_plan",
                 "toonflow_ai"},
                f"forbidden import: {name}",
            )

    def test_top_level_imports_minimal(self):
        for name, level in _ast_top_level_imports(MODULE_SOURCE):
            if level > 0:
                # Relative import — allowed.
                continue
            self.assertIn(
                name,
                {"typing", "json"},
                f"unexpected top-level import: {name}",
            )

    def test_no_print_or_input_calls(self):
        self.assertNotIn("print(", MODULE_SOURCE)
        self.assertNotIn("input(", MODULE_SOURCE)

    def test_no_open_calls(self):
        # The module does not do file I/O itself; that is owned by
        # ``workflow.project``.
        self.assertNotIn("open(", MODULE_SOURCE)

    def test_public_api_is_minimal(self):
        # Only the documented public surface is re-exported.
        import workflow.project_migrations as mod
        expected = {
            "PROJECT_SCHEMA_VERSION",
            "SUPPORTED_PROJECT_SCHEMA_VERSIONS",
            "UnsupportedProjectSchemaError",
            "migrate_project_dict",
            "migrate_project_dict_to_version",
        }
        for name in expected:
            self.assertTrue(hasattr(mod, name), name)
        # And no extra public symbols beyond the documented ones.
        # ``__all__`` is the authoritative public list.
        self.assertTrue(hasattr(mod, "__all__"))
        for name in mod.__all__:
            self.assertTrue(hasattr(mod, name), name)

    def test_dunder_all_matches_documented_surface(self):
        import workflow.project_migrations as mod
        self.assertEqual(
            set(mod.__all__),
            {
                "PROJECT_SCHEMA_VERSION",
                "SUPPORTED_PROJECT_SCHEMA_VERSIONS",
                "UnsupportedProjectSchemaError",
                "migrate_project_dict",
                "migrate_project_dict_to_version",
            },
        )


if __name__ == "__main__":
    unittest.main()
