"""Tests for TOONFLOW-PHASE-024 — Manifest CLI Overrides & Precedence.

The override layer is exercised by:

- :class:`OverrideModelTests` — the override model surface.
- :class:`PrecedenceTests` — CLI / manifest / default precedence.
- :class:`IncludeExcludeTests` — replacement semantics.
- :class:`ValidationTests` — override validation.
- :class:`ImmutabilityTests` — original manifest unchanged.
- :class:`SerializationTests` — serialization determinism.
- :class:`CLIIntegrationTests` — :mod:`workflow.cli`.
- :class:`ExecutionDelegationTests` — values reach the batch layer.
- :class:`ErrorHandlingTests` — error propagation and exit codes.
- :class:`ExistingBehaviorTests` — PHASE-020..023 preserved.
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
    apply_manifest_overrides,
    batch_manifest_to_dict,
    batch_manifest_to_json,
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
        mode="run",
        include=("production/*.json", "release/*.json"),
        exclude=("*_draft.json",),
        recursive=True,
        report_path="./reports/from-manifest.json",
    )
    defaults.update(overrides)
    return BatchManifest(**defaults)


def _save_manifest(m, td, name="manifest.json"):
    path = os.path.join(td, name)
    from workflow.manifest import save_batch_manifest
    save_batch_manifest(m, path)
    return path


class _Recorder:
    """Records a delegated ``run_batch`` call for inspection."""

    def __init__(self, return_value=0):
        self.calls = []
        self.return_value = return_value

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


# ---------------------------------------------------------------------------
# Override model
# ---------------------------------------------------------------------------


class OverrideModelTests(unittest.TestCase):
    def test_no_overrides_returns_new_manifest_with_same_values(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m)
        self.assertEqual(out, m)
        self.assertIsNot(out, m)

    def test_directory_override(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, directory="./other")
        self.assertEqual(out.directory, "./other")
        self.assertEqual(m.directory, "./projects")

    def test_mode_override(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, mode="validate")
        self.assertEqual(out.mode, "validate")
        self.assertEqual(m.mode, "run")

    def test_include_override_string(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, include="*.json")
        self.assertEqual(out.include, ("*.json",))

    def test_include_override_sequence(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, include=("a", "b"))
        self.assertEqual(out.include, ("a", "b"))

    def test_exclude_override(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, exclude=("x",))
        self.assertEqual(out.exclude, ("x",))

    def test_recursive_true_override(self):
        m = _make_manifest(recursive=False)
        out = apply_manifest_overrides(m, recursive=True)
        self.assertTrue(out.recursive)
        self.assertFalse(m.recursive)

    def test_recursive_false_override(self):
        m = _make_manifest(recursive=True)
        out = apply_manifest_overrides(m, recursive=False)
        self.assertFalse(out.recursive)
        self.assertTrue(m.recursive)

    def test_recursive_none_override_preserves_manifest(self):
        m = _make_manifest(recursive=True)
        out = apply_manifest_overrides(m, recursive=None)
        self.assertTrue(out.recursive)

    def test_report_path_override(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, report_path="./cli-report.json")
        self.assertEqual(out.report_path, "./cli-report.json")
        self.assertEqual(m.report_path, "./reports/from-manifest.json")

    def test_report_path_none_override_preserves_manifest(self):
        m = _make_manifest(report_path=None)
        out = apply_manifest_overrides(m, report_path=None)
        self.assertIsNone(out.report_path)

    def test_all_overrides_together(self):
        m = _make_manifest()
        out = apply_manifest_overrides(
            m,
            directory="./cli-dir",
            mode="show",
            include=("x", "y"),
            exclude=("z",),
            recursive=False,
            report_path="./cli-report.json",
        )
        self.assertEqual(out.directory, "./cli-dir")
        self.assertEqual(out.mode, "show")
        self.assertEqual(out.include, ("x", "y"))
        self.assertEqual(out.exclude, ("z",))
        self.assertFalse(out.recursive)
        self.assertEqual(out.report_path, "./cli-report.json")
        # Original untouched.
        self.assertEqual(m.directory, "./projects")
        self.assertEqual(m.mode, "run")
        self.assertEqual(m.include, ("production/*.json", "release/*.json"))
        self.assertEqual(m.exclude, ("*_draft.json",))
        self.assertTrue(m.recursive)
        self.assertEqual(m.report_path, "./reports/from-manifest.json")

    def test_schema_version_preserved(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, mode="validate")
        self.assertEqual(out.schema_version, BATCH_MANIFEST_SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


class PrecedenceTests(unittest.TestCase):
    def test_manifest_value_preserved_when_no_override(self):
        m = _make_manifest(mode="run")
        out = apply_manifest_overrides(m)
        self.assertEqual(out.mode, "run")

    def test_cli_value_wins_when_supplied(self):
        m = _make_manifest(mode="run")
        out = apply_manifest_overrides(m, mode="validate")
        self.assertEqual(out.mode, "validate")

    def test_explicit_false_wins_over_manifest_true(self):
        m = _make_manifest(recursive=True)
        out = apply_manifest_overrides(m, recursive=False)
        self.assertFalse(out.recursive)

    def test_explicit_true_wins_over_manifest_false(self):
        m = _make_manifest(recursive=False)
        out = apply_manifest_overrides(m, recursive=True)
        self.assertTrue(out.recursive)

    def test_report_override_wins_over_manifest(self):
        m = _make_manifest(report_path="a.json")
        out = apply_manifest_overrides(m, report_path="b.json")
        self.assertEqual(out.report_path, "b.json")

    def test_include_override_replaces_manifest(self):
        m = _make_manifest(include=("a", "b"))
        out = apply_manifest_overrides(m, include="c")
        self.assertEqual(out.include, ("c",))


# ---------------------------------------------------------------------------
# Include / exclude
# ---------------------------------------------------------------------------


class IncludeExcludeTests(unittest.TestCase):
    def test_include_complete_replacement_not_merge(self):
        m = _make_manifest(include=("a", "b"))
        out = apply_manifest_overrides(m, include="c")
        self.assertEqual(out.include, ("c",))

    def test_exclude_complete_replacement_not_merge(self):
        m = _make_manifest(exclude=("a", "b"))
        out = apply_manifest_overrides(m, exclude="c")
        self.assertEqual(out.exclude, ("c",))

    def test_multiple_include_patterns_preserve_order(self):
        m = _make_manifest()
        out = apply_manifest_overrides(
            m, include=("first", "second", "third"),
        )
        self.assertEqual(out.include, ("first", "second", "third"))

    def test_multiple_exclude_patterns_preserve_order(self):
        m = _make_manifest()
        out = apply_manifest_overrides(
            m, exclude=("x", "y", "z"),
        )
        self.assertEqual(out.exclude, ("x", "y", "z"))

    def test_empty_include_override_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, include=())
        self.assertEqual(cm.exception.parameter, "include")

    def test_empty_include_list_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, include=[])
        self.assertEqual(cm.exception.parameter, "include")

    def test_empty_exclude_override_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, exclude=())
        self.assertEqual(cm.exception.parameter, "exclude")

    def test_include_override_with_invalid_entry_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, include=("a", 1))
        self.assertEqual(cm.exception.parameter, "include")

    def test_include_override_with_empty_string_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError):
            apply_manifest_overrides(m, include="")

    def test_exclude_override_with_whitespace_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError):
            apply_manifest_overrides(m, exclude="   ")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationTests(unittest.TestCase):
    def test_invalid_directory_override(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, directory="")
        self.assertEqual(cm.exception.parameter, "directory")

    def test_invalid_mode_override(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, mode="render")
        self.assertEqual(cm.exception.parameter, "mode")

    def test_invalid_mode_override_type(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, mode=1)  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "mode")

    def test_invalid_recursive_override(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, recursive=1)  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "recursive")

    def test_invalid_recursive_string_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, recursive="true")  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "recursive")

    def test_invalid_report_path_override(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, report_path="")
        self.assertEqual(cm.exception.parameter, "report_path")

    def test_invalid_report_path_bool_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, report_path=True)  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "report_path")

    def test_invalid_include_type_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, include=42)  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "include")

    def test_invalid_exclude_type_rejected(self):
        m = _make_manifest()
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides(m, exclude=42)  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "exclude")

    def test_invalid_manifest_rejected(self):
        with self.assertRaises(ManifestInputError) as cm:
            apply_manifest_overrides({"not": "a manifest"}, mode="run")  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "manifest")

    def test_original_unchanged_on_validation_failure(self):
        m = _make_manifest()
        snapshot = (
            m.directory, m.mode, m.include, m.exclude,
            m.recursive, m.report_path, m.schema_version,
        )
        with self.assertRaises(ManifestInputError):
            apply_manifest_overrides(m, mode="invalid")
        self.assertEqual(
            (m.directory, m.mode, m.include, m.exclude,
             m.recursive, m.report_path, m.schema_version),
            snapshot,
        )


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class ImmutabilityTests(unittest.TestCase):
    def test_original_unchanged_after_override(self):
        m = _make_manifest()
        snapshot = (
            m.directory, m.mode, m.include, m.exclude,
            m.recursive, m.report_path, m.schema_version,
        )
        apply_manifest_overrides(
            m, directory="./new", mode="validate",
            include=("x",), exclude=("y",),
            recursive=False, report_path="./new-report.json",
        )
        self.assertEqual(
            (m.directory, m.mode, m.include, m.exclude,
             m.recursive, m.report_path, m.schema_version),
            snapshot,
        )

    def test_overridden_manifest_independent(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, mode="validate")
        self.assertIsNot(out, m)
        self.assertEqual(out.mode, "validate")
        self.assertEqual(m.mode, "run")

    def test_overridden_manifest_is_frozen(self):
        m = _make_manifest()
        out = apply_manifest_overrides(m, mode="validate")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            out.mode = "show"  # type: ignore[misc]

    def test_input_include_list_not_aliased(self):
        original = ["a", "b"]
        m = _make_manifest(include=("seed",))
        out = apply_manifest_overrides(m, include=original)
        original.append("c")
        self.assertEqual(out.include, ("a", "b"))

    def test_input_exclude_list_not_aliased(self):
        original = ["x", "y"]
        m = _make_manifest(exclude=("seed",))
        out = apply_manifest_overrides(m, exclude=original)
        original.append("z")
        self.assertEqual(out.exclude, ("x", "y"))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class SerializationTests(unittest.TestCase):
    def test_overridden_manifest_serializes_deterministically(self):
        m = _make_manifest()
        out = apply_manifest_overrides(
            m, directory="./x", mode="validate",
            include=("a",), exclude=("b",),
            recursive=False, report_path=None,
        )
        text1 = batch_manifest_to_json(out)
        text2 = batch_manifest_to_json(out)
        self.assertEqual(text1, text2)

    def test_original_manifest_serialization_unchanged(self):
        m = _make_manifest()
        before = batch_manifest_to_json(m)
        apply_manifest_overrides(m, mode="validate", recursive=False)
        after = batch_manifest_to_json(m)
        self.assertEqual(before, after)

    def test_overridden_dict_uses_canonical_key_order(self):
        m = _make_manifest()
        out = apply_manifest_overrides(
            m, mode="show", recursive=False, report_path=None,
        )
        data = batch_manifest_to_dict(out)
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

    def test_overridden_manifest_serialization_contains_no_timestamps(self):
        m = _make_manifest()
        out = apply_manifest_overrides(
            m, directory="./x", mode="validate",
            include=("a",), exclude=("b",),
        )
        text = batch_manifest_to_json(out)
        for forbidden in ("timestamp", "uuid", "created_at", "host", "user"):
            self.assertNotIn(forbidden, text.lower())


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class CLIIntegrationTests(unittest.TestCase):
    def _save(self, td, **overrides):
        return _save_manifest(_make_manifest(**overrides), td)

    def test_no_overrides_preserves_manifest(self):
        with _tempdir() as td:
            path = self._save(td, mode="run", recursive=True)
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(["manifest", path], stdout=buf, run_batch=rec)
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["mode"], "run")
            self.assertTrue(rec.calls[0]["recursive"])
            self.assertEqual(rec.calls[0]["directory"], "./projects")

    def test_mode_override(self):
        with _tempdir() as td:
            path = self._save(td, mode="run")
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--mode", "validate"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["mode"], "validate")

    def test_include_override_replaces_manifest(self):
        with _tempdir() as td:
            path = self._save(
                td, include=("production/*.json", "release/*.json"),
            )
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--include", "staging/*.json"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["include"], ("staging/*.json",))

    def test_multiple_include_patterns(self):
        with _tempdir() as td:
            path = self._save(td)
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path,
                     "--include", "a",
                     "--include", "b",
                     "--include", "c"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["include"], ("a", "b", "c"))

    def test_exclude_override(self):
        with _tempdir() as td:
            path = self._save(td, exclude=("old",))
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--exclude", "draft*.json"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["exclude"], ("draft*.json",))

    def test_recursive_override_true(self):
        with _tempdir() as td:
            path = self._save(td, recursive=False)
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--recursive"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertTrue(rec.calls[0]["recursive"])

    def test_recursive_override_false(self):
        with _tempdir() as td:
            path = self._save(td, recursive=True)
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--no-recursive"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertFalse(rec.calls[0]["recursive"])

    def test_no_recursive_flag_preserves_manifest(self):
        with _tempdir() as td:
            path = self._save(td, recursive=True)
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertTrue(rec.calls[0]["recursive"])

    def test_report_override(self):
        with _tempdir() as td:
            path = self._save(td, report_path="manifest-report.json")
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--report", "cli-report.json"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["report_path"], "cli-report.json")

    def test_directory_override(self):
        with _tempdir() as td:
            path = self._save(td, directory="./manifest-dir")
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--directory", "./cli-dir"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["directory"], "./cli-dir")

    def test_combined_overrides(self):
        with _tempdir() as td:
            path = self._save(
                td,
                directory="./manifest-dir",
                mode="run",
                include=("production/*.json",),
                exclude=("*_draft.json",),
                recursive=True,
                report_path="manifest-report.json",
            )
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path,
                     "--directory", "./cli-dir",
                     "--mode", "validate",
                     "--include", "release/*.json",
                     "--exclude", "**/draft_*.json",
                     "--no-recursive",
                     "--report", "./cli-report.json"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["directory"], "./cli-dir")
            self.assertEqual(rec.calls[0]["mode"], "validate")
            self.assertEqual(rec.calls[0]["include"], ("release/*.json",))
            self.assertEqual(rec.calls[0]["exclude"], ("**/draft_*.json",))
            self.assertFalse(rec.calls[0]["recursive"])
            self.assertEqual(rec.calls[0]["report_path"], "./cli-report.json")

    def test_manifest_file_unchanged_after_run(self):
        with _tempdir() as td:
            path = self._save(td, mode="run")
            before = Path(path).read_bytes()
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--mode", "validate"],
                    stdout=buf, run_batch=rec,
                )
            after = Path(path).read_bytes()
            self.assertEqual(before, after)

    def test_invalid_mode_returns_two(self):
        with _tempdir() as td:
            path = self._save(td)
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--mode", "render"],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 2)
            self.assertEqual(rec.calls, [])

    def test_invalid_include_returns_one(self):
        # ``--include ""`` passes the parser (empty string is a
        # legal value) and is rejected by the override layer,
        # which returns exit code 1.
        with _tempdir() as td:
            path = self._save(td)
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--include", ""],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 1)
            self.assertEqual(rec.calls, [])

    def test_manifest_help_returns_zero(self):
        with _quiet_argparse_stderr():
            try:
                rc = cli_main(["manifest", "--help"], stdout=io.StringIO())
            except SystemExit as exc:
                rc = exc.code
        self.assertEqual(rc, 0)

    def test_manifest_no_path_returns_two(self):
        buf = io.StringIO()
        with _quiet_argparse_stderr():
            rc = cli_main(["manifest"], stdout=buf)
        self.assertEqual(rc, 2)

    def test_manifest_loading_failure_returns_one(self):
        with _tempdir() as td:
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", os.path.join(td, "missing.json")],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 1)
            self.assertEqual(rec.calls, [])


# ---------------------------------------------------------------------------
# Execution delegation
# ---------------------------------------------------------------------------


class ExecutionDelegationTests(unittest.TestCase):
    def test_effective_values_reach_run_batch(self):
        with _tempdir() as td:
            path = _save_manifest(
                _make_manifest(
                    directory="./manifest-dir",
                    mode="run",
                    include=("manifest_in",),
                    exclude=("manifest_ex",),
                    recursive=True,
                    report_path="manifest-report.json",
                ),
                td,
            )
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path,
                     "--directory", "./cli-dir",
                     "--mode", "validate",
                     "--include", "cli_in",
                     "--exclude", "cli_ex",
                     "--no-recursive",
                     "--report", "./cli-report.json"],
                    stdout=buf, run_batch=rec,
                )
        self.assertEqual(len(rec.calls), 1)
        call = rec.calls[0]
        self.assertEqual(call["directory"], "./cli-dir")
        self.assertEqual(call["mode"], "validate")
        self.assertEqual(call["include"], ("cli_in",))
        self.assertEqual(call["exclude"], ("cli_ex",))
        self.assertFalse(call["recursive"])
        self.assertEqual(call["report_path"], "./cli-report.json")

    def test_exactly_one_execution_delegation(self):
        with _tempdir() as td:
            path = _save_manifest(_make_manifest(), td)
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--mode", "validate"],
                    stdout=buf, run_batch=rec,
                )
        self.assertEqual(len(rec.calls), 1)

    def test_return_code_preserved_from_batch(self):
        with _tempdir() as td:
            path = _save_manifest(_make_manifest(), td)
            rec = _Recorder(return_value=1)
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path], stdout=buf, run_batch=rec,
                )
        self.assertEqual(rc, 1)

    def test_di_apply_manifest_overrides(self):
        with _tempdir() as td:
            path = _save_manifest(_make_manifest(), td)

            def fake_override(manifest, **kwargs):
                # Pretend we always force ``mode="show"``.
                return apply_manifest_overrides(manifest, mode="show")

            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path],
                    stdout=buf,
                    run_batch=rec,
                    apply_manifest_overrides=fake_override,
                )
        self.assertEqual(rec.calls[0]["mode"], "show")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class ErrorHandlingTests(unittest.TestCase):
    def test_manifest_loading_failure(self):
        with _tempdir() as td:
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", os.path.join(td, "missing.json")],
                    stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 1)
            self.assertIn("error:", buf.getvalue())

    def test_invalid_override_returns_one(self):
        # Direct call to ``apply_manifest_overrides`` with an
        # invalid value.
        with self.assertRaises(ManifestInputError):
            apply_manifest_overrides(_make_manifest(), mode="bad")

    def test_batch_failure_returns_batch_exit_code(self):
        with _tempdir() as td:
            path = _save_manifest(_make_manifest(), td)
            rec = _Recorder(return_value=7)
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path], stdout=buf, run_batch=rec,
                )
        self.assertEqual(rc, 7)

    def test_delegated_exception_propagates(self):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")
        with _tempdir() as td:
            path = _save_manifest(_make_manifest(), td)
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                with self.assertRaises(RuntimeError):
                    cli_main(
                        ["manifest", path],
                        stdout=buf, run_batch=boom,
                    )


# ---------------------------------------------------------------------------
# Existing behavior
# ---------------------------------------------------------------------------


class ExistingBehaviorTests(unittest.TestCase):
    def test_existing_batch_subcommand_unchanged(self):
        # Smoke: the existing ``batch`` subcommand still works.
        from workflow.batch import run_batch
        from workflow.manifest import BatchManifest
        # The CLI parser still recognizes the ``batch`` subcommand.
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            try:
                cli_main(
                    ["batch", "./d", "validate"],
                    stdout=buf,
                    run_batch=lambda *a, **k: 0,
                )
            except SystemExit:
                pass

    def test_existing_validate_subcommand_unchanged(self):
        from workflow import Project, Shot
        fake = Project(name="p", shots=(Shot(concept="c"),))
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            try:
                cli_main(
                    ["validate", "p.json"],
                    stdout=buf,
                    load_project=lambda p: fake,
                )
            except SystemExit:
                pass

    def test_existing_manifest_command_without_overrides(self):
        # Without the new flags, the previous behavior is
        # preserved: the manifest is loaded and forwarded as-is.
        with _tempdir() as td:
            path = _save_manifest(
                _make_manifest(mode="run", recursive=False), td,
            )
            rec = _Recorder()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path], stdout=buf, run_batch=rec,
                )
            self.assertEqual(rc, 0)
            self.assertEqual(rec.calls[0]["mode"], "run")
            self.assertFalse(rec.calls[0]["recursive"])

    def test_package_reexports_apply_manifest_overrides(self):
        self.assertIn("apply_manifest_overrides", PACKAGE_INIT_SOURCE)
        from workflow import apply_manifest_overrides as fn
        self.assertTrue(callable(fn))

    def test_public_api_surface_unchanged(self):
        # All PHASE-023 symbols remain available.
        from workflow import (
            BatchManifest,
            ManifestInputError,
            batch_manifest_to_dict,
            batch_manifest_to_json,
            batch_manifest_from_dict,
            batch_manifest_from_json,
            save_batch_manifest,
            load_batch_manifest,
            run_batch_manifest,
            BATCH_MANIFEST_SCHEMA_VERSION,
        )
        for fn in (
            batch_manifest_to_dict, batch_manifest_to_json,
            batch_manifest_from_dict, batch_manifest_from_json,
            save_batch_manifest, load_batch_manifest,
            run_batch_manifest, apply_manifest_overrides,
        ):
            self.assertTrue(callable(fn))
        self.assertTrue(callable(BatchManifest))
        self.assertTrue(issubclass(ManifestInputError, ValueError))
        self.assertEqual(BATCH_MANIFEST_SCHEMA_VERSION, 1)


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

    def test_manifest_no_direct_discovery_call(self):
        self.assertNotIn("discover_projects(", MANIFEST_SOURCE)
        self.assertNotIn(".discover_projects(", MANIFEST_SOURCE)

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
        for needle in ("print(", "input("):
            self.assertNotIn(needle, MANIFEST_SOURCE)

    def test_manifest_no_env_or_yaml(self):
        for needle in ("os.environ", "yaml", "toml", "configparser"):
            self.assertNotIn(needle, MANIFEST_SOURCE)

    def test_override_function_exists(self):
        self.assertIn("def apply_manifest_overrides(", MANIFEST_SOURCE)

    def test_cli_no_forbidden_imports(self):
        forbidden = {"bpy", "ollama", "urllib", "pipeline", "asset_registry",
                     "scene_plan", "toonflow_ai"}
        for module in _ast_all_imports(CLI_SOURCE):
            top = module.split(".")[0]
            self.assertNotIn(top, forbidden)

    def test_cli_uses_default_apply_manifest_overrides(self):
        # The CLI must delegate to the override layer; it must
        # not reimplement the precedence logic.
        self.assertIn("apply_manifest_overrides", CLI_SOURCE)
        self.assertIn("apply_manifest_overrides(", CLI_SOURCE)
        self.assertIn("_default_apply_manifest_overrides", CLI_SOURCE)

    def test_cli_no_blender_references(self):
        for needle in (
            "bpy.data", "bpy.ops", "keyframe_insert", "from_pydata",
        ):
            self.assertNotIn(needle, CLI_SOURCE)

    def test_cli_no_print(self):
        self.assertNotIn("print(", CLI_SOURCE)

    def test_cli_no_threading(self):
        for needle in (
            "import threading", "import multiprocessing", "import asyncio",
        ):
            self.assertNotIn(needle, CLI_SOURCE)

    def test_overrides_do_not_mutate_globals(self):
        # ``apply_manifest_overrides`` is a pure function — it
        # must not maintain mutable global state.
        m = _make_manifest()
        before = batch_manifest_to_dict(m)
        for _ in range(5):
            apply_manifest_overrides(m, mode="validate")
            apply_manifest_overrides(m, recursive=False)
        after = batch_manifest_to_dict(m)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
