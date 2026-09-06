"""Tests for TOONFLOW-PHASE-022 — Batch Filtering & Selective Execution.

The filtering layer is exercised by:

- :class:`PublicAPITests` — the public surface.
- :class:`IncludeFilterTests` — include pattern behavior.
- :class:`ExcludeFilterTests` — exclude pattern behavior.
- :class:`RecursiveDiscoveryTests` — recursive walk.
- :class:`CombinedSelectionTests` — include + exclude + recursive.
- :class:`ExecutionTests` — selection vs execution.
- :class:`ReportIntegrationTests` — report integration.
- :class:`EmptySelectionTests` — zero matches after filtering.
- :class:`ErrorTests` — error model and validation.
- :class:`CLIIntegrationTests` — CLI options.
- :class:`DeterminismTests` — repeated-run determinism.
- :class:`ArchitectureTests` — AST-based guard rails.
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
    Project,
    ProjectInputError,
    Shot,
    save_project,
)
from workflow.batch import (  # noqa: E402
    BATCH_MODES,
    RUN_MODE,
    SHOW_MODE,
    VALIDATE_MODE,
    BatchInputError,
    BatchProjectResult,
    discover_projects,
    run_batch,
)
from workflow.cli import main as cli_main  # noqa: E402


BATCH_SOURCE = (PROJECT_ROOT / "workflow" / "batch.py").read_text(
    encoding="utf-8",
)
CLI_SOURCE = (PROJECT_ROOT / "workflow" / "cli.py").read_text(
    encoding="utf-8",
)


# --- Helpers ----------------------------------------------------------------


def _make_project(name="demo", shots=None):
    if shots is None:
        shots = (Shot(concept="c"),)
    return Project(name=name, shots=tuple(shots))


def _write_project(directory, name, project):
    path = os.path.join(directory, name)
    save_project(project, path)
    return path


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


def _make_fake_replay(output_paths):
    @dataclasses.dataclass(frozen=True)
    class _FakeShotResult:
        output_path: str = ""

    @dataclasses.dataclass(frozen=True)
    class _FakeMultiShotResult:
        shot_results: tuple = ()
        output_paths: tuple = ()
        shot_count: int = 0

    n = len(output_paths)
    return _FakeMultiShotResult(
        shot_results=tuple(_FakeShotResult(p) for p in output_paths),
        output_paths=tuple(output_paths),
        shot_count=n,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PublicAPITests(unittest.TestCase):
    def test_batch_input_error_exported(self):
        from workflow import batch as mod
        self.assertTrue(hasattr(mod, "BatchInputError"))
        self.assertTrue(issubclass(BatchInputError, ValueError))

    def test_discover_projects_accepts_new_keyword_args(self):
        # Must not raise when called with the new keyword args
        # against an empty directory.
        with _tempdir() as td:
            discover_projects(td)
            discover_projects(td, include="*.json")
            discover_projects(td, exclude="draft_*.json")
            discover_projects(td, recursive=True)
            discover_projects(
                td, include=("a.json", "b.json"),
                exclude="c.json", recursive=False,
            )

    def test_run_batch_accepts_new_keyword_args(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf,
                include="a.json",
            )
        self.assertEqual(rc, 0)

    def test_cli_batch_subcommand_has_new_options(self):
        # With ``exit_on_error=False``, ``--help`` returns 0
        # instead of raising SystemExit. We just confirm the
        # call is accepted and the batch subcommand is wired.
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            rc = cli_main(["batch", "--help"], stdout=buf)
        self.assertEqual(rc, 0)

    def test_existing_batch_api_preserved(self):
        # The existing PHASE-020 surface is unchanged.
        from workflow import batch as mod
        for name in (
            "run_batch", "discover_projects", "BatchProjectResult",
            "BATCH_MODES", "VALIDATE_MODE", "SHOW_MODE", "RUN_MODE",
        ):
            self.assertTrue(hasattr(mod, name), name)


# ---------------------------------------------------------------------------
# Include filter
# ---------------------------------------------------------------------------


class IncludeFilterTests(unittest.TestCase):
    def test_single_include_string(self):
        with _tempdir() as td:
            for name in ("demo_a.json", "prod_b.json", "draft_c.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(td, include="demo_*.json")
        self.assertEqual(
            [os.path.basename(p) for p in paths], ["demo_a.json"],
        )

    def test_multiple_include_sequence(self):
        with _tempdir() as td:
            for name in ("demo_a.json", "prod_b.json", "draft_c.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(
                td, include=("demo_*.json", "prod_*.json"),
            )
        self.assertEqual(
            [os.path.basename(p) for p in paths],
            ["demo_a.json", "prod_b.json"],
        )

    def test_no_include_keeps_all(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(td)
        self.assertEqual(
            [os.path.basename(p) for p in paths],
            ["a.json", "b.json", "c.json"],
        )

    def test_include_selecting_nothing(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(td, include="nope_*.json")
        self.assertEqual(paths, [])

    def test_duplicate_include_patterns_no_duplicate_execution(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(
                td, include=("a.json", "a.json"),
            )
        self.assertEqual(
            [os.path.basename(p) for p in paths], ["a.json"],
        )

    def test_invalid_include_bool_rejected(self):
        with self.assertRaises(BatchInputError) as ctx:
            discover_projects("/tmp", include=True)
        self.assertEqual(ctx.exception.parameter, "include")

    def test_invalid_include_int_rejected(self):
        with self.assertRaises(BatchInputError):
            discover_projects("/tmp", include=42)

    def test_invalid_include_empty_string_rejected(self):
        with self.assertRaises(BatchInputError):
            discover_projects("/tmp", include="")

    def test_invalid_include_whitespace_rejected(self):
        with self.assertRaises(BatchInputError):
            discover_projects("/tmp", include="   ")

    def test_invalid_include_mixed_sequence_rejected(self):
        with self.assertRaises(BatchInputError):
            discover_projects("/tmp", include=("a.json", 42))

    def test_invalid_include_bool_in_sequence_rejected(self):
        with self.assertRaises(BatchInputError):
            discover_projects("/tmp", include=("a.json", True))


# ---------------------------------------------------------------------------
# Exclude filter
# ---------------------------------------------------------------------------


class ExcludeFilterTests(unittest.TestCase):
    def test_single_exclude_string(self):
        with _tempdir() as td:
            for name in ("demo_a.json", "draft_b.json", "demo_c.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(td, exclude="draft_*.json")
        self.assertEqual(
            [os.path.basename(p) for p in paths],
            ["demo_a.json", "demo_c.json"],
        )

    def test_multiple_exclude_sequence(self):
        with _tempdir() as td:
            for name in ("a.json", "b_backup.json", "c.json", "tmp_d.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(
                td, exclude=("*_backup.json", "tmp_*.json"),
            )
        self.assertEqual(
            [os.path.basename(p) for p in paths], ["a.json", "c.json"],
        )

    def test_exclude_everything(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(td, exclude="*.json")
        self.assertEqual(paths, [])

    def test_exclude_wins_over_include(self):
        with _tempdir() as td:
            for name in ("keep.json", "draft_keep.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(
                td, include="*.json", exclude="draft_*.json",
            )
        self.assertEqual(
            [os.path.basename(p) for p in paths], ["keep.json"],
        )

    def test_duplicate_exclude_patterns_no_side_effects(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(
                td, exclude=("a.json", "a.json"),
            )
        self.assertEqual([os.path.basename(p) for p in paths], ["b.json"])

    def test_invalid_exclude_bool_rejected(self):
        with self.assertRaises(BatchInputError) as ctx:
            discover_projects("/tmp", exclude=True)
        self.assertEqual(ctx.exception.parameter, "exclude")

    def test_invalid_exclude_empty_rejected(self):
        with self.assertRaises(BatchInputError):
            discover_projects("/tmp", exclude="")


# ---------------------------------------------------------------------------
# Recursive discovery
# ---------------------------------------------------------------------------


class RecursiveDiscoveryTests(unittest.TestCase):
    def test_default_remains_non_recursive(self):
        with _tempdir() as td:
            _write_project(td, "top.json", _make_project(name="top"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "nested.json", _make_project(name="nested"))
            paths = discover_projects(td)
        self.assertEqual(
            [os.path.basename(p) for p in paths], ["top.json"],
        )

    def test_recursive_discovers_nested(self):
        with _tempdir() as td:
            _write_project(td, "top.json", _make_project(name="top"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "nested.json", _make_project(name="nested"))
            paths = discover_projects(td, recursive=True)
        self.assertEqual(
            sorted(os.path.relpath(p, td).replace(os.sep, "/")
                   for p in paths),
            ["sub/nested.json", "top.json"],
        )

    def test_recursive_nested_ordering_deterministic(self):
        with _tempdir() as td:
            # Create many nested dirs in a non-sorted order.
            names = ["zeta", "alpha", "mike", "bravo"]
            for sub in names:
                d = os.path.join(td, sub)
                os.mkdir(d)
                _write_project(d, f"in_{sub}.json",
                               _make_project(name=sub))
            # Also top-level.
            _write_project(td, "root.json", _make_project(name="root"))
            paths = discover_projects(td, recursive=True)
        rels = [os.path.relpath(p, td).replace(os.sep, "/") for p in paths]
        self.assertEqual(
            rels,
            sorted(rels),
            "recursive result must already be deterministically sorted",
        )

    def test_recursive_nested_directories_not_executed_as_files(self):
        with _tempdir() as td:
            # A directory whose name happens to end in .json
            # must NOT be treated as a project file.
            d = os.path.join(td, "trick.json")
            os.mkdir(d)
            _write_project(d, "inside.json", _make_project(name="inside"))
            _write_project(td, "real.json", _make_project(name="real"))
            paths = discover_projects(td, recursive=True)
        rels = [os.path.relpath(p, td).replace(os.sep, "/") for p in paths]
        self.assertEqual(
            rels, ["real.json", "trick.json/inside.json"],
        )

    def test_recursive_hidden_directory_skipped(self):
        with _tempdir() as td:
            _write_project(td, "top.json", _make_project(name="top"))
            hidden = os.path.join(td, ".hidden")
            os.mkdir(hidden)
            _write_project(hidden, "h.json", _make_project(name="h"))
            paths = discover_projects(td, recursive=True)
        self.assertEqual(
            [os.path.basename(p) for p in paths], ["top.json"],
        )

    def test_recursive_plus_include_on_relative_path(self):
        with _tempdir() as td:
            _write_project(td, "root.json", _make_project(name="root"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "nested.json", _make_project(name="nested"))
            paths = discover_projects(
                td, recursive=True, include="sub/*.json",
            )
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("nested.json"))

    def test_recursive_plus_exclude_on_relative_path(self):
        with _tempdir() as td:
            _write_project(td, "keep.json", _make_project(name="keep"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "skip.json", _make_project(name="skip"))
            paths = discover_projects(
                td, recursive=True, exclude="sub/*.json",
            )
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("keep.json"))


# ---------------------------------------------------------------------------
# Combined selection
# ---------------------------------------------------------------------------


class CombinedSelectionTests(unittest.TestCase):
    def test_include_plus_exclude(self):
        with _tempdir() as td:
            for name in ("a.json", "draft_b.json", "c.json", "draft_d.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(
                td, include="*.json", exclude="draft_*.json",
            )
        self.assertEqual(
            [os.path.basename(p) for p in paths], ["a.json", "c.json"],
        )

    def test_include_plus_recursive(self):
        with _tempdir() as td:
            _write_project(td, "root.json", _make_project(name="root"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "nested.json",
                           _make_project(name="nested"))
            paths = discover_projects(
                td, recursive=True, include="sub/*.json",
            )
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("nested.json"))

    def test_exclude_plus_recursive(self):
        with _tempdir() as td:
            _write_project(td, "root.json", _make_project(name="root"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "nested.json",
                           _make_project(name="nested"))
            paths = discover_projects(
                td, recursive=True, exclude="root.json",
            )
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("nested.json"))

    def test_include_exclude_recursive(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "b.json", _make_project(name="b"))
            _write_project(sub, "draft_c.json",
                           _make_project(name="c"))
            # ``*.json`` matches across ``/`` in fnmatch, so it
            # selects all four files. ``*draft_*.json`` removes
            # the nested draft. Exclude wins.
            paths = discover_projects(
                td, recursive=True,
                include=("*.json",), exclude=("*draft_*.json",),
            )
        rels = [os.path.relpath(p, td).replace(os.sep, "/")
                for p in paths]
        self.assertEqual(sorted(rels), ["a.json", "sub/b.json"])


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class ExecutionTests(unittest.TestCase):
    def test_only_selected_files_loaded(self):
        with _tempdir() as td:
            for name in ("demo_a.json", "prod_b.json", "draft_c.json"):
                _write_project(td, name, _make_project(name=name))
            load_calls = []
            def fake_load(p):
                load_calls.append(os.path.basename(p))
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf,
                include=("demo_*.json", "prod_*.json"),
                load_project=fake_load,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(
            sorted(load_calls), ["demo_a.json", "prod_b.json"],
        )

    def test_excluded_files_never_loaded(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            load_calls = []
            def fake_load(p):
                load_calls.append(os.path.basename(p))
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf,
                exclude="a.json",
                load_project=fake_load,
            )
        self.assertEqual(load_calls, ["b.json"])

    def test_excluded_files_never_replayed(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            replay_calls = []
            def fake_load(p):
                return _make_project(name=os.path.basename(p))
            def fake_replay(proj, **kw):
                replay_calls.append(proj.name)
                return _make_fake_replay(("/o/x.png",))
            buf = io.StringIO()
            run_batch(
                td, RUN_MODE, stdout=buf,
                exclude="a.json",
                load_project=fake_load,
                replay_project=fake_replay,
            )
        self.assertEqual(replay_calls, ["b.json"])

    def test_selected_files_execute_in_deterministic_order(self):
        with _tempdir() as td:
            for name in ("z.json", "a.json", "m.json"):
                _write_project(td, name, _make_project(name=name))
            seen = []
            def fake_load(p):
                seen.append(os.path.basename(p))
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf,
                load_project=fake_load,
            )
        self.assertEqual(seen, ["a.json", "m.json", "z.json"])

    def test_continue_on_error_preserved_with_filters(self):
        with _tempdir() as td:
            for name in ("a.json", "bad.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            seen = []
            def fake_load(p):
                name = os.path.basename(p)
                seen.append(name)
                if name == "bad.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=name)
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf,
                load_project=fake_load,
            )
        self.assertNotEqual(rc, 0)
        # Lex order: a, b, bad.
        self.assertEqual(seen, ["a.json", "b.json", "bad.json"])


# ---------------------------------------------------------------------------
# Report integration
# ---------------------------------------------------------------------------


class ReportIntegrationTests(unittest.TestCase):
    def test_report_includes_only_selected_projects(self):
        with _tempdir() as td:
            for name in ("demo_a.json", "draft_b.json", "demo_c.json"):
                _write_project(td, name, _make_project(name=name))
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf,
                include="demo_*.json",
                report_path=report,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["project_count"], 2)
        names = [os.path.basename(p["path"]) for p in data["projects"]]
        self.assertEqual(sorted(names), ["demo_a.json", "demo_c.json"])

    def test_filtered_out_projects_absent(self):
        with _tempdir() as td:
            for name in ("keep.json", "skip.json"):
                _write_project(td, name, _make_project(name=name))
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf,
                exclude="skip.json",
                report_path=report,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        names = [os.path.basename(p["path"]) for p in data["projects"]]
        self.assertEqual(names, ["keep.json"])

    def test_output_paths_preserved_with_filters(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            def fake_load(p):
                return _make_project(name="a")
            def fake_replay(proj, **kw):
                return _make_fake_replay(("/o/1.png", "/o/2.png"))
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            run_batch(
                td, RUN_MODE, stdout=buf,
                report_path=report,
                load_project=fake_load,
                replay_project=fake_replay,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(
            data["projects"][0]["output_paths"],
            ["/o/1.png", "/o/2.png"],
        )

    def test_existing_report_behavior_unchanged_without_filters(self):
        # Without filters, the report behavior is identical to
        # PHASE-021.
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf,
                report_path=report,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["project_count"], 1)


# ---------------------------------------------------------------------------
# Empty selection
# ---------------------------------------------------------------------------


class EmptySelectionTests(unittest.TestCase):
    def test_empty_selection_returns_one(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            load_calls = []
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf,
                include="nonexistent_*.json",
                load_project=lambda p: load_calls.append(p),
            )
        self.assertEqual(rc, 1)
        self.assertEqual(load_calls, [])

    def test_empty_selection_does_not_call_replay(self):
        with _tempdir() as td:
            for name in ("a.json",):
                _write_project(td, name, _make_project(name=name))
        replay_calls = []
        def fake_load(p):
            return _make_project(name=os.path.basename(p))
        def fake_replay(proj, **kw):
            replay_calls.append(proj)
            return _make_fake_replay(())
        buf = io.StringIO()
        rc = run_batch(
            td, RUN_MODE, stdout=buf,
            include="nonexistent_*.json",
            load_project=fake_load,
            replay_project=fake_replay,
        )
        self.assertEqual(rc, 1)
        self.assertEqual(replay_calls, [])

    def test_empty_selection_deterministic_output(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            def run_once(include):
                buf = io.StringIO()
                run_batch(
                    td, VALIDATE_MODE, stdout=buf,
                    include=include,
                    load_project=lambda p: None,
                )
                return buf.getvalue()
            out1 = run_once("nope_*.json")
            out2 = run_once("nope_*.json")
        self.assertEqual(out1, out2)
        self.assertIn("no project JSON files matched", out1)

    def test_empty_selection_no_report(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf,
                include="nonexistent_*.json",
                report_path=report,
            )
            self.assertFalse(os.path.exists(report))
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------


class ErrorTests(unittest.TestCase):
    def test_batch_input_error_attributes(self):
        err = BatchInputError("include", 42)
        self.assertEqual(err.parameter, "include")
        self.assertEqual(err.value, 42)
        self.assertIsInstance(err, ValueError)

    def test_batch_input_error_message(self):
        err = BatchInputError("recursive", "true")
        self.assertIn("recursive", str(err))
        self.assertIn("true", str(err))

    def test_run_batch_rejects_invalid_recursive_int(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE, recursive=1, stdout=buf)
        self.assertEqual(rc, 2)
        self.assertIn("recursive", buf.getvalue())

    def test_run_batch_rejects_invalid_recursive_string(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE, recursive="true",
                           stdout=buf)
        self.assertEqual(rc, 2)

    def test_run_batch_rejects_invalid_recursive_none(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE, recursive=None,
                           stdout=buf)
        self.assertEqual(rc, 2)

    def test_run_batch_rejects_invalid_include(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE, include=42, stdout=buf)
        self.assertEqual(rc, 2)
        self.assertIn("include", buf.getvalue())

    def test_run_batch_rejects_invalid_exclude(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE, exclude=42, stdout=buf)
        self.assertEqual(rc, 2)
        self.assertIn("exclude", buf.getvalue())

    def test_run_batch_preserves_mode_validation(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = run_batch(td, "bogus", stdout=buf)
        self.assertEqual(rc, 2)
        self.assertIn("unknown batch mode", buf.getvalue())


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class CLIIntegrationTests(unittest.TestCase):
    def test_include_option_forwarded(self):
        with _tempdir() as td:
            for name in ("demo_a.json", "draft_b.json"):
                _write_project(td, name, _make_project(name=name))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate",
                     "--include", "demo_*.json"],
                    stdout=buf,
                )
        self.assertEqual(rc, 0)
        # Only the demo project should appear in output.
        self.assertIn("demo_a.json: OK", buf.getvalue())
        self.assertNotIn("draft_b.json", buf.getvalue())

    def test_exclude_option_forwarded(self):
        with _tempdir() as td:
            for name in ("a.json", "draft_b.json"):
                _write_project(td, name, _make_project(name=name))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate",
                     "--exclude", "draft_*.json"],
                    stdout=buf,
                )
        self.assertEqual(rc, 0)
        self.assertIn("a.json: OK", buf.getvalue())
        self.assertNotIn("draft_b.json", buf.getvalue())

    def test_recursive_option_forwarded(self):
        with _tempdir() as td:
            _write_project(td, "top.json", _make_project(name="top"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "nested.json",
                           _make_project(name="nested"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate", "--recursive"],
                    stdout=buf,
                )
        self.assertEqual(rc, 0)
        self.assertIn("top.json: OK", buf.getvalue())
        self.assertIn("nested.json: OK", buf.getvalue())

    def test_repeated_include_accumulates(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                _write_project(td, name, _make_project(name=name))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate",
                     "--include", "a.json",
                     "--include", "b.json"],
                    stdout=buf,
                )
        self.assertEqual(rc, 0)
        self.assertIn("a.json: OK", buf.getvalue())
        self.assertIn("b.json: OK", buf.getvalue())
        self.assertNotIn("c.json", buf.getvalue())

    def test_existing_batch_invocation_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(["batch", td, "validate"], stdout=buf)
        self.assertEqual(rc, 0)
        self.assertIn("a.json: OK", buf.getvalue())

    def test_existing_commands_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                self.assertEqual(
                    cli_main(["validate", os.path.join(td, "a.json")],
                             stdout=buf),
                    0,
                )
                buf = io.StringIO()
                self.assertEqual(
                    cli_main(["show", os.path.join(td, "a.json")],
                             stdout=buf),
                    0,
                )

    def test_cli_with_all_new_options_and_report(self):
        with _tempdir() as td:
            for name in ("demo_a.json", "draft_b.json"):
                _write_project(td, name, _make_project(name=name))
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate",
                     "--include", "demo_*.json",
                     "--exclude", "draft_*.json",
                     "--report", report],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["project_count"], 1)
        self.assertEqual(
            os.path.basename(data["projects"][0]["path"]),
            "demo_a.json",
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_repeated_discovery_same_order(self):
        with _tempdir() as td:
            for name in ("z.json", "a.json", "m.json"):
                _write_project(td, name, _make_project(name=name))
            def run_once():
                return discover_projects(
                    td, include=("a.json", "m.json"),
                )
            out1 = run_once()
            out2 = run_once()
        self.assertEqual(out1, out2)

    def test_repeated_run_batch_same_output(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                _write_project(td, name, _make_project(name=name))
            def run_once(include):
                buf = io.StringIO()
                run_batch(
                    td, VALIDATE_MODE, stdout=buf,
                    include=include,
                    load_project=lambda p: _make_project(name=os.path.basename(p)),
                )
                return buf.getvalue()
            out1 = run_once("a.json")
            out2 = run_once("a.json")
        self.assertEqual(out1, out2)

    def test_recursive_order_independent_of_creation_order(self):
        with _tempdir() as td:
            # Create subdirs in a non-sorted order; the result
            # must always be sorted.
            for sub in ["z", "a", "m"]:
                d = os.path.join(td, sub)
                os.mkdir(d)
                _write_project(d, f"{sub}.json",
                               _make_project(name=sub))
        out1 = [os.path.relpath(p, td).replace(os.sep, "/")
                for p in discover_projects(td, recursive=True)]
        # Run a second time; should be identical.
        out2 = [os.path.relpath(p, td).replace(os.sep, "/")
                for p in discover_projects(td, recursive=True)]
        self.assertEqual(out1, out2)
        self.assertEqual(out1, sorted(out1))


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


class ArchitectureTests(unittest.TestCase):
    def test_batch_does_not_import_bpy(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import: {name}",
            )

    def test_batch_does_not_import_ollama(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"ollama", "ollama_client"},
                f"forbidden ollama import: {name}",
            )

    def test_batch_does_not_import_requests(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"requests"},
                f"forbidden requests import: {name}",
            )

    def test_batch_does_not_import_urllib(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"urllib", "urllib.request"},
                f"forbidden urllib import: {name}",
            )

    def test_batch_does_not_import_pipeline(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"pipeline"},
                f"forbidden pipeline import: {name}",
            )

    def test_batch_does_not_import_asset_registry(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"asset_registry"},
                f"forbidden asset_registry import: {name}",
            )

    def test_batch_does_not_import_scene_plan(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"scene_plan"},
                f"forbidden scene_plan import: {name}",
            )

    def test_batch_does_not_import_toonflow_ai_generation(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertFalse(
                name.startswith("toonflow_ai"),
                f"forbidden toonflow_ai import: {name}",
            )

    def test_batch_does_not_call_rendering_apis(self):
        for forbidden in (
            "render_scene(", "create_or_update_camera(",
            "from_pydata(", "bpy.ops.render",
            "create_and_render_scene",
            "create_and_render_shots",
        ):
            self.assertNotIn(forbidden, BATCH_SOURCE)

    def test_batch_does_not_use_print(self):
        self.assertNotIn("print(", BATCH_SOURCE)

    def test_batch_does_not_use_input(self):
        self.assertNotIn("input(", BATCH_SOURCE)

    def test_batch_does_not_use_threading(self):
        # AST-based: no actual import or attribute access to
        # threading / multiprocessing / asyncio.
        tree = ast.parse(BATCH_SOURCE)
        forbidden_modules = {"threading", "multiprocessing", "asyncio",
                             "concurrent"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertNotIn(
                        root, forbidden_modules,
                        f"forbidden import: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    self.assertNotIn(
                        root, forbidden_modules,
                        f"forbidden import from: {node.module}",
                    )

    def test_cli_does_not_serialize_json(self):
        self.assertNotIn("import json", CLI_SOURCE)
        self.assertNotIn("json.dumps", CLI_SOURCE)

    def test_cli_forwards_new_options(self):
        for token in ("--include", "--exclude", "--recursive",
                      "include=", "exclude=", "recursive="):
            self.assertIn(token, CLI_SOURCE,
                          f"CLI must forward {token!r}")


if __name__ == "__main__":
    unittest.main()
