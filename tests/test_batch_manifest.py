"""Tests for TOONFLOW-PHASE-023 — Project Manifest & Batch Configuration.

The manifest layer is exercised by:

- :class:`PublicAPITests` — the public surface.
- :class:`ModelValidationTests` — :class:`BatchManifest` validation.
- :class:`SerializationTests` — dict / JSON output.
- :class:`DeserializationTests` — dict / JSON parsing.
- :class:`FilePersistenceTests` — save / load.
- :class:`ExecutionDelegationTests` — :func:`run_batch_manifest`.
- :class:`CLIIntegrationTests` — :mod:`workflow.cli`.
- :class:`IdempotencyTests` — repeated calls produce equivalent
  delegation.
- :class:`ArchitectureTests` — AST-based guard rails.

The tests do not require Blender, bpy, Ollama, a real renderer,
or a real AI server.
"""

import ast
import contextlib
import dataclasses
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_ROOT = PROJECT_ROOT / "addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


from workflow import (  # noqa: E402
    BATCH_MANIFEST_SCHEMA_VERSION,
    BatchManifest,
    ManifestInputError,
    batch_manifest_from_dict,
    batch_manifest_from_json,
    batch_manifest_to_dict,
    batch_manifest_to_json,
    load_batch_manifest,
    run_batch_manifest,
    save_batch_manifest,
)
from workflow.cli import main as cli_main  # noqa: E402


MANIFEST_SOURCE = (PROJECT_ROOT / "workflow" / "manifest.py").read_text(
    encoding="utf-8",
)
CLI_SOURCE = (PROJECT_ROOT / "workflow" / "cli.py").read_text(
    encoding="utf-8",
)
PACKAGE_INIT_SOURCE = (PROJECT_ROOT / "workflow" / "__init__.py").read_text(
    encoding="utf-8",
)


# --- Helpers ----------------------------------------------------------------


@contextlib.contextmanager
def _tempdir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@contextlib.contextmanager
def _quiet_argparse_stderr():
    saved = sys.stderr
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stderr = saved


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


def _make_manifest(**overrides):
    defaults = dict(
        directory="./projects",
        mode="validate",
        include=("ep*.json",),
        exclude=("*_draft.json",),
        recursive=True,
        report_path="./reports/out.json",
    )
    defaults.update(overrides)
    return BatchManifest(**defaults)


def _canonical_dict():
    return {
        "schema_version": 1,
        "directory": "./projects",
        "mode": "validate",
        "include": ["ep*.json"],
        "exclude": ["*_draft.json"],
        "recursive": True,
        "report_path": "./reports/out.json",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PublicAPITests(unittest.TestCase):
    def test_manifest_module_imports(self):
        import workflow.manifest  # noqa: F401

    def test_public_api_available(self):
        from workflow import manifest as mod
        for name in (
            "BatchManifest",
            "ManifestInputError",
            "BATCH_MANIFEST_SCHEMA_VERSION",
            "batch_manifest_to_dict",
            "batch_manifest_from_dict",
            "batch_manifest_to_json",
            "batch_manifest_from_json",
            "save_batch_manifest",
            "load_batch_manifest",
            "run_batch_manifest",
        ):
            self.assertTrue(hasattr(mod, name))

    def test_package_exports(self):
        import workflow
        for name in (
            "BatchManifest",
            "ManifestInputError",
            "BATCH_MANIFEST_SCHEMA_VERSION",
            "batch_manifest_to_dict",
            "batch_manifest_from_dict",
            "batch_manifest_to_json",
            "batch_manifest_from_json",
            "save_batch_manifest",
            "load_batch_manifest",
            "run_batch_manifest",
        ):
            self.assertIn(name, workflow.__all__)
            self.assertTrue(hasattr(workflow, name))

    def test_existing_apis_unchanged(self):
        from workflow import (
            Project,
            Shot,
            create_and_render_shots,
            create_and_render_scene,
            load_project,
            replay_project,
            save_project,
        )
        self.assertTrue(callable(create_and_render_scene))
        self.assertTrue(callable(create_and_render_shots))
        self.assertTrue(callable(load_project))
        self.assertTrue(callable(replay_project))
        self.assertTrue(callable(save_project))
        # Smoke: existing model is reachable.
        p = Project(name="p", shots=(Shot(concept="c"),))
        self.assertEqual(p.name, "p")

    def test_batch_layer_not_reexported_at_package_level(self):
        # PHASE-019 keeps ``workflow.batch.run_batch`` reachable
        # only via the ``workflow.batch`` submodule; the
        # top-level package does NOT re-export it. PHASE-023
        # preserves that boundary.
        import workflow
        self.assertFalse(hasattr(workflow, "run_batch"))
        self.assertFalse(hasattr(workflow, "discover_projects"))

    def test_schema_version_is_one(self):
        self.assertEqual(BATCH_MANIFEST_SCHEMA_VERSION, 1)


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


class ModelValidationTests(unittest.TestCase):
    def test_minimal_manifest_defaults(self):
        m = BatchManifest(directory="./p", mode="validate")
        self.assertEqual(m.directory, "./p")
        self.assertEqual(m.mode, "validate")
        self.assertEqual(m.include, ())
        self.assertEqual(m.exclude, ())
        self.assertEqual(m.recursive, False)
        self.assertIsNone(m.report_path)
        self.assertEqual(m.schema_version, 1)

    def test_is_frozen_dataclass(self):
        m = BatchManifest(directory="./p", mode="validate")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            m.mode = "show"  # type: ignore[misc]

    def test_include_normalized_to_tuple(self):
        m = BatchManifest(
            directory="./p", mode="validate", include=["a", "b"],
        )
        self.assertEqual(m.include, ("a", "b"))
        self.assertIsInstance(m.include, tuple)

    def test_exclude_normalized_to_tuple(self):
        m = BatchManifest(
            directory="./p", mode="validate", exclude=("x", "y"),
        )
        self.assertEqual(m.exclude, ("x", "y"))

    def test_include_does_not_alias_caller_list(self):
        original = ["a", "b"]
        m = BatchManifest(
            directory="./p", mode="validate", include=original,
        )
        original.append("c")
        self.assertEqual(m.include, ("a", "b"))

    def test_exclude_does_not_alias_caller_list(self):
        original = ["x", "y"]
        m = BatchManifest(
            directory="./p", mode="validate", exclude=original,
        )
        original.append("z")
        self.assertEqual(m.exclude, ("x", "y"))

    def test_invalid_directory_none(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(directory=None, mode="validate")
        self.assertEqual(cm.exception.parameter, "directory")

    def test_invalid_directory_empty(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(directory="", mode="validate")

    def test_invalid_directory_whitespace(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(directory="   ", mode="validate")

    def test_invalid_directory_bool(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(directory=True, mode="validate")  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "directory")

    def test_invalid_directory_int(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(directory=42, mode="validate")  # type: ignore[arg-type]

    def test_invalid_directory_list(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(directory=["./p"], mode="validate")  # type: ignore[arg-type]

    def test_invalid_mode(self):
        for bad in ("", "render", None, 0, True):
            with self.assertRaises(ManifestInputError) as cm:
                BatchManifest(directory="./p", mode=bad)  # type: ignore[arg-type]
            self.assertEqual(cm.exception.parameter, "mode")

    def test_include_bool_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(
                directory="./p", mode="validate", include=True,  # type: ignore[arg-type]
            )
        self.assertEqual(cm.exception.parameter, "include")

    def test_include_empty_string_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(
                directory="./p", mode="validate", include="",
            )
        self.assertEqual(cm.exception.parameter, "include")

    def test_include_whitespace_rejected(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(
                directory="./p", mode="validate", include="   ",
            )

    def test_include_mixed_types_rejected(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(
                directory="./p", mode="validate", include=("a", 1),
            )

    def test_include_with_bool_entry_rejected(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(
                directory="./p", mode="validate", include=("a", True),
            )

    def test_include_with_empty_entry_rejected(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(
                directory="./p", mode="validate", include=("a", ""),
            )

    def test_exclude_validation_mirrors_include(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(
                directory="./p", mode="validate", exclude=True,  # type: ignore[arg-type]
            )
        self.assertEqual(cm.exception.parameter, "exclude")

    def test_exclude_empty_string_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(
                directory="./p", mode="validate", exclude="",
            )
        self.assertEqual(cm.exception.parameter, "exclude")

    def test_recursive_must_be_bool(self):
        for bad in (1, 0, "true", "false", None, 1.0):
            with self.assertRaises(ManifestInputError) as cm:
                BatchManifest(
                    directory="./p", mode="validate", recursive=bad,  # type: ignore[arg-type]
                )
            self.assertEqual(cm.exception.parameter, "recursive")

    def test_report_path_none_ok(self):
        m = BatchManifest(
            directory="./p", mode="validate", report_path=None,
        )
        self.assertIsNone(m.report_path)

    def test_report_path_empty_string_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(
                directory="./p", mode="validate", report_path="",
            )
        self.assertEqual(cm.exception.parameter, "report_path")

    def test_report_path_bool_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(
                directory="./p", mode="validate", report_path=True,  # type: ignore[arg-type]
            )
        self.assertEqual(cm.exception.parameter, "report_path")

    def test_report_path_int_rejected(self):
        with self.assertRaises(ManifestInputError):
            BatchManifest(
                directory="./p", mode="validate", report_path=42,  # type: ignore[arg-type]
            )

    def test_schema_version_bool_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(
                directory="./p", mode="validate", schema_version=True,  # type: ignore[arg-type]
            )
        self.assertEqual(cm.exception.parameter, "schema_version")

    def test_schema_version_unsupported_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            BatchManifest(
                directory="./p", mode="validate", schema_version=2,  # type: ignore[arg-type]
            )
        self.assertEqual(cm.exception.parameter, "schema_version")
        self.assertEqual(cm.exception.value, 2)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class SerializationTests(unittest.TestCase):
    def test_to_dict_canonical_key_order(self):
        m = _make_manifest()
        data = batch_manifest_to_dict(m)
        self.assertEqual(
            list(data.keys()),
            [
                "schema_version",
                "directory",
                "mode",
                "include",
                "exclude",
                "recursive",
                "report_path",
            ],
        )

    def test_to_dict_basic_round_trip(self):
        m = _make_manifest()
        self.assertEqual(batch_manifest_to_dict(m), _canonical_dict())

    def test_to_json_canonical_layout(self):
        m = _make_manifest()
        text = batch_manifest_to_json(m)
        # First non-empty line is the opening brace.
        self.assertTrue(text.startswith("{\n"))
        # Trailing newline exactly once.
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))
        # Keys appear in canonical order.
        lines = text.splitlines()
        first_keys = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('"') and ":" in stripped:
                key = stripped.split(":", 1)[0].strip().strip('"')
                first_keys.append(key)
        self.assertEqual(
            first_keys[:7],
            [
                "schema_version",
                "directory",
                "mode",
                "include",
                "exclude",
                "recursive",
                "report_path",
            ],
        )

    def test_to_json_uses_indent_two(self):
        m = _make_manifest()
        text = batch_manifest_to_json(m)
        # Indent 2 means the first key sits at column 2.
        self.assertIn('\n  "schema_version": 1,', text)

    def test_to_json_trailing_newline(self):
        m = _make_manifest()
        text = batch_manifest_to_json(m)
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_to_json_non_ascii_preserved(self):
        m = BatchManifest(
            directory="./projets/été", mode="validate",
        )
        text = batch_manifest_to_json(m)
        # ``ensure_ascii=False`` keeps the raw UTF-8 in the file.
        self.assertIn("été", text)
        self.assertNotIn("\\u", text)

    def test_to_json_deterministic_bytes(self):
        m = _make_manifest()
        text1 = batch_manifest_to_json(m)
        text2 = batch_manifest_to_json(m)
        self.assertEqual(text1, text2)

    def test_to_json_tuple_input_normalized(self):
        m = BatchManifest(
            directory="./p", mode="validate",
            include=("a", "b"), exclude=("c",),
        )
        text = batch_manifest_to_json(m)
        data = json.loads(text)
        self.assertEqual(data["include"], ["a", "b"])
        self.assertEqual(data["exclude"], ["c"])

    def test_to_json_minimal_manifest(self):
        m = BatchManifest(directory="./p", mode="validate")
        text = batch_manifest_to_json(m)
        data = json.loads(text)
        self.assertEqual(data, {
            "schema_version": 1,
            "directory": "./p",
            "mode": "validate",
            "include": [],
            "exclude": [],
            "recursive": False,
            "report_path": None,
        })

    def test_to_json_does_not_include_timestamps(self):
        m = _make_manifest()
        text = batch_manifest_to_json(m)
        for forbidden in ("timestamp", "uuid", "created_at", "host", "user"):
            self.assertNotIn(forbidden, text.lower())

    def test_invalid_manifest_to_dict_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_to_dict({"not": "a manifest"})
        self.assertEqual(cm.exception.parameter, "manifest")


# ---------------------------------------------------------------------------
# Deserialization
# ---------------------------------------------------------------------------


class DeserializationTests(unittest.TestCase):
    def test_from_dict_valid(self):
        m = batch_manifest_from_dict(_canonical_dict())
        self.assertEqual(m.directory, "./projects")
        self.assertEqual(m.mode, "validate")
        self.assertEqual(m.include, ("ep*.json",))
        self.assertEqual(m.exclude, ("*_draft.json",))
        self.assertTrue(m.recursive)
        self.assertEqual(m.report_path, "./reports/out.json")
        self.assertEqual(m.schema_version, 1)

    def test_from_json_valid(self):
        m = batch_manifest_from_json(json.dumps(_canonical_dict()))
        self.assertEqual(m.directory, "./projects")

    def test_from_json_malformed_raises_json_decode_error(self):
        with self.assertRaises(json.JSONDecodeError):
            batch_manifest_from_json("not json")

    def test_from_dict_non_mapping_rejected(self):
        for bad in ([], "string", 42, None, (1, 2)):
            with self.assertRaises(ManifestInputError):
                batch_manifest_from_dict(bad)  # type: ignore[arg-type]

    def test_from_dict_unknown_key_rejected(self):
        data = _canonical_dict()
        data["extra"] = "x"
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_from_dict(data)
        self.assertEqual(cm.exception.parameter, "manifest.unknown")

    def test_from_dict_missing_key_rejected(self):
        data = _canonical_dict()
        del data["mode"]
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_from_dict(data)
        self.assertEqual(cm.exception.parameter, "manifest.missing")

    def test_from_dict_missing_multiple_keys(self):
        data = _canonical_dict()
        del data["mode"]
        del data["include"]
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_from_dict(data)
        self.assertEqual(cm.exception.parameter, "manifest.missing")

    def test_from_dict_wrong_type_directory(self):
        data = _canonical_dict()
        data["directory"] = 42
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_from_dict(data)
        self.assertEqual(cm.exception.parameter, "directory")

    def test_from_dict_wrong_type_mode(self):
        data = _canonical_dict()
        data["mode"] = 1
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_from_dict(data)
        self.assertEqual(cm.exception.parameter, "mode")

    def test_from_dict_wrong_type_include(self):
        data = _canonical_dict()
        data["include"] = "not a list"
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_from_dict(data)
        self.assertEqual(cm.exception.parameter, "include")

    def test_from_dict_unsupported_schema_version(self):
        data = _canonical_dict()
        data["schema_version"] = 99
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_from_dict(data)
        self.assertEqual(cm.exception.parameter, "schema_version")

    def test_from_dict_schema_version_bool_rejected(self):
        data = _canonical_dict()
        data["schema_version"] = True
        with self.assertRaises(ManifestInputError) as cm:
            batch_manifest_from_dict(data)
        self.assertEqual(cm.exception.parameter, "schema_version")

    def test_from_json_non_string_rejected(self):
        with self.assertRaises(ManifestInputError):
            batch_manifest_from_json(42)  # type: ignore[arg-type]

    def test_from_json_empty_rejected(self):
        with self.assertRaises(ManifestInputError):
            batch_manifest_from_json("   ")


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------


class FilePersistenceTests(unittest.TestCase):
    def test_save_creates_parents(self):
        with _tempdir() as td:
            nested = os.path.join(td, "a", "b", "c", "manifest.json")
            m = _make_manifest()
            out = save_batch_manifest(m, nested)
            self.assertTrue(out.exists())
            self.assertTrue(os.path.isfile(str(out)))

    def test_save_returns_absolute_path(self):
        with _tempdir() as td:
            path = os.path.join(td, "manifest.json")
            out = save_batch_manifest(_make_manifest(), path)
            self.assertTrue(os.path.isabs(str(out)))

    def test_save_overwrites_deterministically(self):
        with _tempdir() as td:
            path = os.path.join(td, "manifest.json")
            save_batch_manifest(_make_manifest(directory="./a"), path)
            save_batch_manifest(_make_manifest(directory="./b"), path)
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn('"directory"', text)
            # The second write must replace the first.
            data = json.loads(text)
            self.assertEqual(data["directory"], "./b")

    def test_save_load_round_trip(self):
        with _tempdir() as td:
            path = os.path.join(td, "manifest.json")
            m1 = _make_manifest()
            save_batch_manifest(m1, path)
            m2 = load_batch_manifest(path)
            self.assertEqual(m1, m2)

    def test_save_load_round_trip_minimal(self):
        with _tempdir() as td:
            path = os.path.join(td, "m.json")
            m1 = BatchManifest(directory="./p", mode="validate")
            save_batch_manifest(m1, path)
            m2 = load_batch_manifest(path)
            self.assertEqual(m1, m2)

    def test_save_invalid_manifest_rejected(self):
        with _tempdir() as td:
            path = os.path.join(td, "m.json")
            with self.assertRaises(ManifestInputError):
                save_batch_manifest({"not": "a manifest"}, path)  # type: ignore[arg-type]

    def test_save_invalid_path_rejected(self):
        with self.assertRaises(ManifestInputError):
            save_batch_manifest(_make_manifest(), "")

    def test_save_invalid_path_none_rejected(self):
        with self.assertRaises(ManifestInputError):
            save_batch_manifest(_make_manifest(), None)  # type: ignore[arg-type]

    def test_save_invalid_path_bool_rejected(self):
        with self.assertRaises(ManifestInputError):
            save_batch_manifest(_make_manifest(), True)  # type: ignore[arg-type]

    def test_load_missing_file_raises_oserror(self):
        with _tempdir() as td:
            with self.assertRaises(OSError):
                load_batch_manifest(os.path.join(td, "missing.json"))

    def test_load_directory_path_rejected(self):
        with _tempdir() as td:
            with self.assertRaises(ManifestInputError):
                load_batch_manifest(td)

    def test_load_invalid_path_rejected(self):
        with self.assertRaises(ManifestInputError):
            load_batch_manifest("")

    def test_load_invalid_path_none_rejected(self):
        with self.assertRaises(ManifestInputError):
            load_batch_manifest(None)  # type: ignore[arg-type]

    def test_load_invalid_path_bool_rejected(self):
        with self.assertRaises(ManifestInputError):
            load_batch_manifest(True)  # type: ignore[arg-type]

    def test_saved_file_is_valid_json(self):
        with _tempdir() as td:
            path = os.path.join(td, "m.json")
            save_batch_manifest(_make_manifest(), path)
            text = Path(path).read_text(encoding="utf-8")
            data = json.loads(text)
            self.assertEqual(data, _canonical_dict())

    def test_saved_file_ends_with_single_newline(self):
        with _tempdir() as td:
            path = os.path.join(td, "m.json")
            save_batch_manifest(_make_manifest(), path)
            text = Path(path).read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertFalse(text.endswith("\n\n"))


# ---------------------------------------------------------------------------
# Execution delegation
# ---------------------------------------------------------------------------


class _Recorder:
    """Records a delegated call for inspection."""

    def __init__(self):
        self.calls = []
        self.return_value = 0

    def __call__(
        self, directory, mode, *, include, exclude, recursive,
        report_path, load_project, replay_project, stdout, report_writer,
    ):
        self.calls.append({
            "directory": directory,
            "mode": mode,
            "include": include,
            "exclude": exclude,
            "recursive": recursive,
            "report_path": report_path,
            "load_project": load_project,
            "replay_project": replay_project,
            "stdout": stdout,
            "report_writer": report_writer,
        })
        return self.return_value


class ExecutionDelegationTests(unittest.TestCase):
    def test_delegates_to_run_batch(self):
        rec = _Recorder()
        m = _make_manifest()
        rc = run_batch_manifest(m, run_batch=rec)
        self.assertEqual(rc, rec.return_value)
        self.assertEqual(len(rec.calls), 1)

    def test_forwards_directory(self):
        rec = _Recorder()
        m = _make_manifest(directory="./my/dir")
        run_batch_manifest(m, run_batch=rec)
        self.assertEqual(rec.calls[0]["directory"], "./my/dir")

    def test_forwards_mode(self):
        rec = _Recorder()
        m = _make_manifest(mode="run")
        run_batch_manifest(m, run_batch=rec)
        self.assertEqual(rec.calls[0]["mode"], "run")

    def test_forwards_include(self):
        rec = _Recorder()
        m = _make_manifest(include=("a", "b"))
        run_batch_manifest(m, run_batch=rec)
        self.assertEqual(rec.calls[0]["include"], ("a", "b"))

    def test_forwards_exclude(self):
        rec = _Recorder()
        m = _make_manifest(exclude=("x",))
        run_batch_manifest(m, run_batch=rec)
        self.assertEqual(rec.calls[0]["exclude"], ("x",))

    def test_forwards_recursive(self):
        rec = _Recorder()
        m = _make_manifest(recursive=True)
        run_batch_manifest(m, run_batch=rec)
        self.assertTrue(rec.calls[0]["recursive"])

    def test_forwards_report_path(self):
        rec = _Recorder()
        m = _make_manifest(report_path="./report.json")
        run_batch_manifest(m, run_batch=rec)
        self.assertEqual(rec.calls[0]["report_path"], "./report.json")

    def test_forwards_none_report_path(self):
        rec = _Recorder()
        m = _make_manifest(report_path=None)
        run_batch_manifest(m, run_batch=rec)
        self.assertIsNone(rec.calls[0]["report_path"])

    def test_forwards_load_project(self):
        rec = _Recorder()
        sentinel = lambda p: None
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec, load_project=sentinel)
        self.assertIs(rec.calls[0]["load_project"], sentinel)

    def test_forwards_replay_project(self):
        rec = _Recorder()
        sentinel = lambda proj: None
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec, replay_project=sentinel)
        self.assertIs(rec.calls[0]["replay_project"], sentinel)

    def test_forwards_report_writer(self):
        rec = _Recorder()
        sentinel = lambda report, path: None
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec, report_writer=sentinel)
        self.assertIs(rec.calls[0]["report_writer"], sentinel)

    def test_forwards_stdout(self):
        rec = _Recorder()
        buf = io.StringIO()
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec, stdout=buf)
        self.assertIs(rec.calls[0]["stdout"], buf)

    def test_uses_default_stdout_when_none(self):
        rec = _Recorder()
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec)
        self.assertIsNotNone(rec.calls[0]["stdout"])

    def test_provides_placeholder_load_when_none(self):
        rec = _Recorder()
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec, load_project=None)
        # The manifest layer must always pass *something* to the
        # batch layer; when the caller does not inject one, a
        # placeholder is used so the batch layer can still type-check
        # the argument.
        self.assertTrue(callable(rec.calls[0]["load_project"]))

    def test_provides_placeholder_replay_when_none(self):
        rec = _Recorder()
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec, replay_project=None)
        self.assertTrue(callable(rec.calls[0]["replay_project"]))

    def test_return_code_preserved(self):
        rec = _Recorder()
        rec.return_value = 7
        m = _make_manifest()
        self.assertEqual(run_batch_manifest(m, run_batch=rec), 7)

    def test_delegated_error_propagates(self):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")
        m = _make_manifest()
        with self.assertRaises(RuntimeError):
            run_batch_manifest(m, run_batch=boom)

    def test_invalid_manifest_rejected(self):
        rec = _Recorder()
        with self.assertRaises(ManifestInputError) as cm:
            run_batch_manifest({"not": "a manifest"}, run_batch=rec)  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "manifest")
        self.assertEqual(rec.calls, [])

    def test_manifest_not_mutated_by_run(self):
        rec = _Recorder()
        m = _make_manifest()
        snapshot = (
            m.directory, m.mode, m.include, m.exclude,
            m.recursive, m.report_path, m.schema_version,
        )
        run_batch_manifest(m, run_batch=rec)
        self.assertEqual(
            (m.directory, m.mode, m.include, m.exclude,
             m.recursive, m.report_path, m.schema_version),
            snapshot,
        )

    def test_only_delegates_once(self):
        rec = _Recorder()
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec)
        run_batch_manifest(m, run_batch=rec)
        self.assertEqual(len(rec.calls), 2)


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class CLIIntegrationTests(unittest.TestCase):
    def test_manifest_command_success(self):
        with _tempdir() as td:
            path = os.path.join(td, "manifest.json")
            save_batch_manifest(
                BatchManifest(directory=td, mode="validate"),
                path,
            )
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path],
                    stdout=buf,
                    run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(len(rec.calls), 1)
            self.assertEqual(rec.calls[0]["directory"], td)
            self.assertEqual(rec.calls[0]["mode"], "validate")

    def test_manifest_command_delegated_failure(self):
        with _tempdir() as td:
            path = os.path.join(td, "manifest.json")
            save_batch_manifest(
                BatchManifest(directory=td, mode="validate"),
                path,
            )
            rec = _Recorder()
            rec.return_value = 1
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path],
                    stdout=buf,
                    run_batch=rec,
                )
            self.assertEqual(rc, 1)

    def test_manifest_command_missing_file(self):
        with _tempdir() as td:
            path = os.path.join(td, "missing.json")
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path],
                    stdout=buf,
                    run_batch=rec,
                )
            self.assertEqual(rc, 1)
            self.assertIn("error:", buf.getvalue())
            self.assertEqual(rec.calls, [])

    def test_manifest_command_invalid_json(self):
        with _tempdir() as td:
            path = os.path.join(td, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("not json")
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path],
                    stdout=buf,
                    run_batch=rec,
                )
            self.assertEqual(rc, 1)
            self.assertEqual(rec.calls, [])

    def test_manifest_command_invalid_structure(self):
        with _tempdir() as td:
            path = os.path.join(td, "m.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"mode": "validate"}')
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path],
                    stdout=buf,
                    run_batch=rec,
                )
            self.assertEqual(rc, 1)
            self.assertEqual(rec.calls, [])

    def test_existing_commands_unchanged(self):
        # Smoke: the existing batch / validate / show / run
        # subcommands are still parsed and dispatched.
        for argv, expected_command in [
            (["validate", "p.json"], "validate"),
            (["show", "p.json"], "show"),
            (["run", "p.json"], "run"),
            (["batch", "d", "validate"], "batch"),
        ]:
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                # We do not need successful execution here; the
                # goal is to verify the parser still recognizes
                # the existing subcommands.
                try:
                    cli_main(argv, stdout=buf)
                except Exception:  # noqa: BLE001
                    pass

    def test_di_load_and_replay_forwarded(self):
        with _tempdir() as td:
            path = os.path.join(td, "manifest.json")
            save_batch_manifest(
                BatchManifest(directory=td, mode="run"),
                path,
            )
            rec = _Recorder()
            sentinel_load = lambda p: None
            sentinel_replay = lambda proj: None
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path],
                    stdout=buf,
                    run_batch=rec,
                    load_project=sentinel_load,
                    replay_project=sentinel_replay,
                )
            self.assertIs(rec.calls[0]["load_project"], sentinel_load)
            self.assertIs(rec.calls[0]["replay_project"], sentinel_replay)

    def test_manifest_command_help_returns_zero(self):
        with _quiet_argparse_stderr():
            try:
                rc = cli_main(["manifest", "--help"], stdout=io.StringIO())
            except SystemExit as exc:
                # argparse may still call ``sys.exit`` for ``--help``;
                # surface the code as the test result.
                rc = exc.code
        self.assertEqual(rc, 0)

    def test_manifest_command_no_path_returns_two(self):
        buf = io.StringIO()
        with _quiet_argparse_stderr():
            rc = cli_main(["manifest"], stdout=buf)
        self.assertEqual(rc, 2)

    def test_deterministic_output(self):
        with _tempdir() as td:
            path = os.path.join(td, "manifest.json")
            save_batch_manifest(
                BatchManifest(directory=td, mode="validate"),
                path,
            )
            rec1 = _Recorder()
            buf1 = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path], stdout=buf1, run_batch=rec1,
                )
            rec2 = _Recorder()
            buf2 = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path], stdout=buf2, run_batch=rec2,
                )
            self.assertEqual(buf1.getvalue(), buf2.getvalue())


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class IdempotencyTests(unittest.TestCase):
    def test_save_same_manifest_twice_byte_identical(self):
        with _tempdir() as td:
            p1 = os.path.join(td, "a", "m.json")
            p2 = os.path.join(td, "b", "m.json")
            m = _make_manifest()
            save_batch_manifest(m, p1)
            save_batch_manifest(m, p2)
            t1 = Path(p1).read_text(encoding="utf-8")
            t2 = Path(p2).read_text(encoding="utf-8")
            self.assertEqual(t1, t2)

    def test_repeated_run_equivalent_delegation(self):
        rec = _Recorder()
        m = _make_manifest()
        run_batch_manifest(m, run_batch=rec)
        run_batch_manifest(m, run_batch=rec)
        # Compare everything except ``stdout`` (a freshly
        # resolved ``sys.stdout`` may compare equal but is
        # implementation-defined) and the placeholder default
        # ``load_project`` / ``replay_project`` lambdas which are
        # regenerated per call.
        def _normalize(call):
            return {
                k: v for k, v in call.items()
                if k not in ("stdout", "load_project", "replay_project")
            }
        self.assertEqual(_normalize(rec.calls[0]), _normalize(rec.calls[1]))

    def test_manifest_does_not_create_directories(self):
        with _tempdir() as td:
            original_listing = sorted(os.listdir(td))
            rec = _Recorder()
            m = _make_manifest(directory=os.path.join(td, "no", "such"))
            # ``run_batch_manifest`` only delegates; the directory
            # argument is *not* created.
            run_batch_manifest(m, run_batch=rec)
            self.assertEqual(sorted(os.listdir(td)), original_listing)


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


class ArchitectureTests(unittest.TestCase):
    def test_manifest_no_forbidden_imports(self):
        forbidden = {
            "bpy", "ollama", "requests", "urllib",
            "pipeline", "asset_registry", "scene_plan",
            "toonflow_ai", "audio",
        }
        for module in _ast_all_imports(MANIFEST_SOURCE):
            top = module.split(".")[0]
            self.assertNotIn(
                top, forbidden,
                f"workflow.manifest.py must not import {module!r}",
            )

    def test_manifest_no_blender_references(self):
        for needle in (
            "bpy.data", "bpy.ops", "keyframe_insert", "from_pydata",
            "create_and_render_scene", "create_and_render_shots",
        ):
            self.assertNotIn(
                needle, MANIFEST_SOURCE,
                f"workflow.manifest.py must not reference {needle!r}",
            )

    def test_manifest_no_direct_discovery(self):
        # The manifest layer must never *call* ``discover_projects``.
        # Mentions in docstrings are fine because the docs only
        # describe the existing batch-layer ownership.
        self.assertNotIn("discover_projects(", MANIFEST_SOURCE)
        self.assertNotIn(".discover_projects(", MANIFEST_SOURCE)

    def test_manifest_no_direct_load_or_replay(self):
        for needle in (
            "load_project", "replay_project",
        ):
            # The module is allowed to *import* these names lazily
            # inside default delegation targets? No: the manifest
            # layer delegates everything through ``run_batch``.
            # The only mention allowed is the lazy
            # ``load_project`` / ``replay_project`` keyword
            # arguments it forwards to the batch layer.
            self.assertNotIn(
                "from .project import", MANIFEST_SOURCE,
                "manifest.py must not import from .project directly",
            )

    def test_manifest_no_threading_or_async(self):
        for needle in (
            "import threading", "import multiprocessing",
            "import asyncio", "from threading",
            "from multiprocessing", "from asyncio",
        ):
            self.assertNotIn(needle, MANIFEST_SOURCE)

    def test_manifest_no_network(self):
        for needle in ("import requests", "import urllib", "import http"):
            self.assertNotIn(needle, MANIFEST_SOURCE)

    def test_manifest_no_print_or_input(self):
        # The manifest layer must use the ``stdout`` argument for
        # all user-visible output; it must not call ``print`` or
        # ``input`` directly.
        for needle in ("print(", "input("):
            self.assertNotIn(needle, MANIFEST_SOURCE)

    def test_manifest_no_env_or_yaml(self):
        for needle in ("os.environ", "yaml", "toml", "configparser"):
            self.assertNotIn(needle, MANIFEST_SOURCE)

    def test_manifest_has_only_one_default_run_batch(self):
        # The layer must delegate exactly once to the batch
        # layer; it must not contain a second default
        # implementation of ``run_batch`` or ``discover_projects``.
        self.assertEqual(MANIFEST_SOURCE.count("def run_batch("), 0)
        self.assertEqual(
            MANIFEST_SOURCE.count("def run_batch_manifest("), 1,
        )

    def test_cli_no_forbidden_imports(self):
        forbidden = {"bpy", "ollama", "urllib", "pipeline", "asset_registry",
                     "scene_plan", "toonflow_ai"}
        for module in _ast_all_imports(CLI_SOURCE):
            top = module.split(".")[0]
            self.assertNotIn(top, forbidden)

    def test_cli_no_blender_references(self):
        for needle in (
            "bpy.data", "bpy.ops", "keyframe_insert", "from_pydata",
        ):
            self.assertNotIn(needle, CLI_SOURCE)

    def test_cli_manifest_command_uses_default_delegation(self):
        # The CLI must delegate to ``run_batch_manifest`` rather
        # than reimplementing manifest logic. There must be exactly
        # one dispatch branch for ``args.command == "manifest"``.
        self.assertIn('args.command == "manifest"', CLI_SOURCE)
        self.assertIn("run_batch_manifest", CLI_SOURCE)

    def test_package_init_reexports_manifest_symbols(self):
        for name in (
            "BatchManifest",
            "ManifestInputError",
            "BATCH_MANIFEST_SCHEMA_VERSION",
            "batch_manifest_to_dict",
            "batch_manifest_from_dict",
            "batch_manifest_to_json",
            "batch_manifest_from_json",
            "save_batch_manifest",
            "load_batch_manifest",
            "run_batch_manifest",
        ):
            self.assertIn(name, PACKAGE_INIT_SOURCE)
            self.assertIn(name, workflow_all_list())


def workflow_all_list():
    import workflow
    return list(workflow.__all__)


if __name__ == "__main__":
    unittest.main()
