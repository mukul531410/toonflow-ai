"""Tests for TOONFLOW-PHASE-021 — Project Report & CI Artifacts.

The report layer is exercised by:

- :class:`PublicAPITests` — the public surface.
- :class:`ReportModelTests` — the report model and validation.
- :class:`SerializationTests` — dict / JSON output.
- :class:`FilePersistenceTests` — ``save_report`` and
  path validation.
- :class:`BatchIntegrationTests` — integration with
  :mod:`workflow.batch`.
- :class:`CLIIntegrationTests` — integration with the
  ``python -m workflow`` CLI.
- :class:`DeterminismTests` — repeated-run determinism.
- :class:`ErrorTests` — error model.
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
    Project,
    ProjectInputError,
    Shot,
    save_project,
)
from workflow.batch import (  # noqa: E402
    BatchProjectResult,
    RUN_MODE,
    SHOW_MODE,
    VALIDATE_MODE,
    run_batch,
)
from workflow.cli import main as cli_main  # noqa: E402
from workflow.report import (  # noqa: E402
    BatchProjectReportEntry,
    BatchReport,
    ReportInputError,
    batch_result_to_report,
    report_to_dict,
    report_to_json,
    save_report,
)


REPORT_SOURCE = (PROJECT_ROOT / "workflow" / "report.py").read_text(
    encoding="utf-8",
)
BATCH_SOURCE = (PROJECT_ROOT / "workflow" / "batch.py").read_text(
    encoding="utf-8",
)
CLI_SOURCE = (PROJECT_ROOT / "workflow" / "cli.py").read_text(
    encoding="utf-8",
)


# --- Helpers ----------------------------------------------------------------


def _make_project(name="demo", description="", shots=None):
    if shots is None:
        shots = (Shot(concept="c"),)
    return Project(name=name, description=description, shots=tuple(shots))


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
    def test_report_module_imports(self):
        import workflow.report  # noqa: F401

    def test_public_api_available(self):
        from workflow import report as mod
        for name in (
            "BatchReport",
            "BatchProjectReportEntry",
            "ReportInputError",
            "batch_result_to_report",
            "report_to_dict",
            "report_to_json",
            "save_report",
        ):
            self.assertTrue(hasattr(mod, name), name)

    def test_workflow_package_does_not_re_export_report(self):
        # The report layer is reached via ``workflow.report`` and
        # ``python -m workflow batch --report``. The top-level
        # package keeps its PHASE-020 surface: report symbols are
        # not re-exported from ``workflow`` itself.
        import workflow
        for name in (
            "BatchReport", "ReportInputError", "save_report",
            "report_to_json", "report_to_dict",
            "batch_result_to_report",
        ):
            self.assertFalse(hasattr(workflow, name), name)

    def test_cli_remains_callable(self):
        # The CLI entry point is still importable and callable.
        self.assertTrue(callable(cli_main))

    def test_existing_workflow_apis_unchanged(self):
        import workflow
        for name in (
            "create_and_render_scene",
            "create_and_render_shots",
            "WorkflowResult",
            "Shot",
            "MultiShotResult",
            "Project",
            "ProjectInputError",
            "load_project",
            "save_project",
            "replay_project",
            "PROJECT_SCHEMA_VERSION",
        ):
            self.assertTrue(hasattr(workflow, name), name)

    def test_existing_batch_api_unchanged(self):
        import workflow.batch
        for name in (
            "run_batch", "discover_projects", "BatchProjectResult",
            "BATCH_MODES", "VALIDATE_MODE", "SHOW_MODE", "RUN_MODE",
        ):
            self.assertTrue(hasattr(workflow.batch, name), name)


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------


class ReportModelTests(unittest.TestCase):
    def test_valid_report(self):
        entry = BatchProjectReportEntry(
            path="/a/b.json", success=True,
        )
        r = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(entry,),
        )
        self.assertEqual(r.mode, "validate")
        self.assertEqual(r.project_count, 1)
        self.assertEqual(r.success_count, 1)
        self.assertEqual(r.failure_count, 0)
        self.assertEqual(len(r.projects), 1)

    def test_report_is_frozen(self):
        entry = BatchProjectReportEntry(path="/a.json", success=True)
        r = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(entry,),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.mode = "run"  # type: ignore[misc]

    def test_entry_is_frozen(self):
        entry = BatchProjectReportEntry(path="/a.json", success=True)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.path = "/b.json"  # type: ignore[misc]

    def test_invalid_mode_raises(self):
        with self.assertRaises(ReportInputError) as ctx:
            batch_result_to_report("bogus", [])
        self.assertEqual(ctx.exception.parameter, "mode")

    def test_non_string_mode_raises(self):
        for bad in (None, 2, b"validate"):
            with self.assertRaises(ReportInputError):
                batch_result_to_report(bad, [])

    def test_invalid_project_count_raises(self):
        # ``None`` is a valid sentinel meaning "auto-derive from
        # project_results" and must not raise. The remaining
        # values are invalid types or out-of-range.
        for bad in (-1, "x", True, 1.5, 2):
            with self.assertRaises(ReportInputError) as ctx:
                batch_result_to_report(
                    "validate", [], project_count=bad,
                )
            self.assertEqual(ctx.exception.parameter, "project_count")

    def test_inconsistent_project_count_raises(self):
        entry = BatchProjectReportEntry(path="/a.json", success=True)
        with self.assertRaises(ReportInputError) as ctx:
            batch_result_to_report(
                "validate", [entry], project_count=2,
            )
        self.assertEqual(ctx.exception.parameter, "project_count")

    def test_invalid_project_entry_path_raises(self):
        for bad in (None, "", 123):
            with self.assertRaises(ReportInputError):
                batch_result_to_report(
                    "validate",
                    [type("F", (), {"path": bad, "success": True})()],
                )

    def test_batch_result_to_report_success(self):
        r = BatchProjectResult(
            path="/x.json", success=True,
            project=_make_project(name="x"),
        )
        report = batch_result_to_report("validate", [r])
        self.assertEqual(report.project_count, 1)
        self.assertEqual(report.success_count, 1)
        self.assertEqual(report.failure_count, 0)
        self.assertEqual(report.projects[0].path, "/x.json")
        self.assertTrue(report.projects[0].success)
        self.assertIsNone(report.projects[0].error_type)
        self.assertIsNone(report.projects[0].error_message)

    def test_batch_result_to_report_failure(self):
        r = BatchProjectResult(
            path="/bad.json", success=False,
            error="ProjectInputError: project.schema_version 99 is unsupported",
        )
        report = batch_result_to_report("validate", [r])
        entry = report.projects[0]
        self.assertFalse(entry.success)
        self.assertEqual(entry.error_type, "ProjectInputError")
        self.assertEqual(
            entry.error_message,
            "project.schema_version 99 is unsupported",
        )

    def test_batch_result_to_report_run_with_output_paths(self):
        result = _make_fake_replay(("/o/1.png", "/o/2.png"))
        r = BatchProjectResult(
            path="/a.json", success=True,
            project=_make_project(name="a"), result=result,
        )
        report = batch_result_to_report("run", [r])
        self.assertEqual(
            tuple(report.projects[0].output_paths),
            ("/o/1.png", "/o/2.png"),
        )

    def test_batch_result_to_report_empty(self):
        report = batch_result_to_report("validate", [])
        self.assertEqual(report.project_count, 0)
        self.assertEqual(report.success_count, 0)
        self.assertEqual(report.failure_count, 0)
        self.assertEqual(report.projects, ())


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class SerializationTests(unittest.TestCase):
    def _make_report(self):
        e1 = BatchProjectReportEntry(path="/a.json", success=True)
        e2 = BatchProjectReportEntry(
            path="/bad.json", success=False,
            error_type="ProjectInputError",
            error_message="project.schema_version 99 is unsupported",
        )
        return BatchReport(
            mode="validate", project_count=2,
            success_count=1, failure_count=1,
            projects=(e1, e2),
        )

    def test_canonical_key_order(self):
        d = report_to_dict(self._make_report())
        self.assertEqual(
            list(d.keys()),
            ["mode", "project_count", "success_count",
             "failure_count", "projects"],
        )
        proj = d["projects"][0]
        self.assertEqual(
            list(proj.keys()),
            ["path", "success", "error_type", "error_message",
             "output_paths"],
        )

    def test_deterministic_json(self):
        r = self._make_report()
        self.assertEqual(report_to_json(r), report_to_json(r))

    def test_trailing_newline(self):
        text = report_to_json(self._make_report())
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_non_ascii_preserved(self):
        e = BatchProjectReportEntry(
            path="/jp.json", success=True,
        )
        r = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(e,),
        )
        # Embed a non-ASCII value via a custom entry path.
        e_jp = BatchProjectReportEntry(
            path="/\u3053\u3093\u306b\u3061\u306f.json",
            success=True,
        )
        r2 = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(e_jp,),
        )
        text = report_to_json(r2)
        self.assertIn("\u3053\u3093\u306b\u3061\u306f", text)
        # And it should not be escaped to \\uXXXX.
        self.assertNotIn("\\u3053", text)

    def test_indent_two(self):
        text = report_to_json(self._make_report())
        # The first key is indented by 2 spaces.
        self.assertIn('\n  "mode":', text)

    def test_success_value_is_true(self):
        d = report_to_dict(self._make_report())
        self.assertIs(d["projects"][0]["success"], True)
        self.assertIs(d["projects"][1]["success"], False)

    def test_invalid_report_raises(self):
        with self.assertRaises(ReportInputError):
            report_to_dict("not a report")
        with self.assertRaises(ReportInputError):
            report_to_json(None)

    def test_run_mode_includes_output_paths(self):
        e = BatchProjectReportEntry(
            path="/a.json", success=True,
            output_paths=("/o/1.png", "/o/2.png"),
        )
        r = BatchReport(
            mode="run", project_count=1,
            success_count=1, failure_count=0,
            projects=(e,),
        )
        d = report_to_dict(r)
        self.assertEqual(d["projects"][0]["output_paths"],
                         ["/o/1.png", "/o/2.png"])


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------


class FilePersistenceTests(unittest.TestCase):
    def test_save_report_returns_absolute_path(self):
        with _tempdir() as td:
            e = BatchProjectReportEntry(path="/a.json", success=True)
            r = BatchReport(
                mode="validate", project_count=1,
                success_count=1, failure_count=0,
                projects=(e,),
            )
            target = os.path.join(td, "sub", "report.json")
            returned = save_report(r, target)
            self.assertTrue(os.path.isabs(str(returned)))
            self.assertTrue(returned.exists())

    def test_parent_directories_created(self):
        with _tempdir() as td:
            e = BatchProjectReportEntry(path="/a.json", success=True)
            r = BatchReport(
                mode="validate", project_count=1,
                success_count=1, failure_count=0,
                projects=(e,),
            )
            target = os.path.join(td, "deep", "nested", "report.json")
            save_report(r, target)
            self.assertTrue(os.path.exists(target))

    def test_existing_report_overwritten_deterministically(self):
        with _tempdir() as td:
            target = os.path.join(td, "report.json")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("old content")
            e = BatchProjectReportEntry(path="/a.json", success=True)
            r = BatchReport(
                mode="validate", project_count=1,
                success_count=1, failure_count=0,
                projects=(e,),
            )
            save_report(r, target)
            with open(target, encoding="utf-8") as fh:
                content = fh.read()
            self.assertNotIn("old content", content)
            self.assertIn("validate", content)

    def test_path_validation_rejects_empty(self):
        e = BatchProjectReportEntry(path="/a.json", success=True)
        r = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(e,),
        )
        for bad in ("", "   ", None, 123, True):
            with self.assertRaises(ReportInputError) as ctx:
                save_report(r, bad)
            self.assertEqual(ctx.exception.parameter, "path")

    def test_path_validation_rejects_whitespace_only(self):
        e = BatchProjectReportEntry(path="/a.json", success=True)
        r = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(e,),
        )
        with self.assertRaises(ReportInputError) as ctx:
            save_report(r, "\t\n  ")
        self.assertEqual(ctx.exception.parameter, "path")

    def test_invalid_report_raises(self):
        with _tempdir() as td:
            target = os.path.join(td, "r.json")
            for bad in (None, "x", 123, [1]):
                with self.assertRaises(ReportInputError) as ctx:
                    save_report(bad, target)
                self.assertEqual(ctx.exception.parameter, "report")

    def test_injected_writer_is_used(self):
        with _tempdir() as td:
            e = BatchProjectReportEntry(path="/a.json", success=True)
            r = BatchReport(
                mode="validate", project_count=1,
                success_count=1, failure_count=0,
                projects=(e,),
            )
            target = os.path.join(td, "r.json")
            captured = []
            def writer(path, payload):
                captured.append((path, payload))
            returned = save_report(r, target, report_writer=writer)
            self.assertEqual(len(captured), 1)
            self.assertEqual(str(captured[0][0]), target)
            self.assertIn("validate", captured[0][1])
            self.assertTrue(str(returned).endswith("r.json"))

    def test_oserror_propagates(self):
        e = BatchProjectReportEntry(path="/a.json", success=True)
        r = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(e,),
        )
        # An obviously invalid path that the OS / Path will
        # reject when the file system tries to operate on it.
        with self.assertRaises((OSError, ValueError, ReportInputError)):
            save_report(r, "\x00invalid")


# ---------------------------------------------------------------------------
# Batch integration
# ---------------------------------------------------------------------------


class BatchIntegrationTests(unittest.TestCase):
    def test_report_not_written_when_no_report_path(self):
        with _tempdir() as td:
            save_project(
                _make_project(name="a"),
                os.path.join(td, "a.json"),
            )
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE, stdout=buf)
            # No files were created in td beyond the project.
            self.assertEqual(sorted(os.listdir(td)), ["a.json"])
        self.assertEqual(rc, 0)

    def test_report_written_when_requested(self):
        with _tempdir() as td:
            save_project(
                _make_project(name="a"),
                os.path.join(td, "a.json"),
            )
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf, report_path=report,
            )
            self.assertTrue(os.path.exists(report))
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(rc, 0)
        self.assertEqual(data["mode"], "validate")
        self.assertEqual(data["project_count"], 1)
        self.assertEqual(data["success_count"], 1)

    def test_all_projects_included(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                save_project(
                    _make_project(name=name[:-5]),
                    os.path.join(td, name),
                )
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf, report_path=report,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["project_count"], 3)
        self.assertEqual(len(data["projects"]), 3)

    def test_success_and_failure_counts_correct(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                save_project(
                    _make_project(name=name[:-5]),
                    os.path.join(td, name),
                )
            report = os.path.join(td, "report.json")
            def fake_load(p):
                if os.path.basename(p) == "b.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf,
                report_path=report, load_project=fake_load,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 1)
        self.assertEqual(data["project_count"], 2)

    def test_project_ordering_preserved(self):
        with _tempdir() as td:
            for name in ("z.json", "a.json", "m.json"):
                save_project(
                    _make_project(name=name[:-5]),
                    os.path.join(td, name),
                )
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf, report_path=report,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        names = [
            os.path.basename(p["path"]) for p in data["projects"]
        ]
        self.assertEqual(names, ["a.json", "m.json", "z.json"])

    def test_run_output_paths_included(self):
        with _tempdir() as td:
            save_project(
                _make_project(name="a"),
                os.path.join(td, "a.json"),
            )
            report = os.path.join(td, "report.json")
            def fake_load(p):
                return _make_project(name="a")
            def fake_replay(proj, **kw):
                return _make_fake_replay(("/o/1.png", "/o/2.png"))
            buf = io.StringIO()
            run_batch(
                td, RUN_MODE, stdout=buf,
                report_path=report,
                load_project=fake_load,
                replay_project=fake_replay,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["mode"], "run")
        self.assertEqual(
            data["projects"][0]["output_paths"],
            ["/o/1.png", "/o/2.png"],
        )

    def test_failures_represented_deterministically(self):
        with _tempdir() as td:
            for name in ("a.json", "bad.json"):
                save_project(
                    _make_project(name=name[:-5]),
                    os.path.join(td, name),
                )
            report = os.path.join(td, "report.json")
            def fake_load(p):
                if os.path.basename(p) == "bad.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf,
                report_path=report, load_project=fake_load,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(rc, 1)
        bad = next(p for p in data["projects"]
                   if p["path"].endswith("bad.json"))
        self.assertFalse(bad["success"])
        self.assertEqual(bad["error_type"], "ProjectInputError")
        self.assertIn("schema_version", bad["error_message"])

    def test_continue_on_error_preserved(self):
        # PHASE-020 continue-on-error behavior must be unchanged
        # when a report is requested.
        with _tempdir() as td:
            for name in ("a.json", "bad.json", "b.json"):
                save_project(
                    _make_project(name=name[:-5]),
                    os.path.join(td, name),
                )
            report = os.path.join(td, "report.json")
            seen = []
            def fake_load(p):
                seen.append(os.path.basename(p))
                if os.path.basename(p) == "bad.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf,
                report_path=report, load_project=fake_load,
            )
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(rc, 1)
        # Lex order: a, b, bad.
        self.assertEqual(seen, ["a.json", "b.json", "bad.json"])
        self.assertEqual(data["project_count"], 3)

    def test_report_not_written_for_empty_directory(self):
        with _tempdir() as td:
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            rc = run_batch(
                td, VALIDATE_MODE, stdout=buf, report_path=report,
            )
            self.assertFalse(os.path.exists(report))
        self.assertEqual(rc, 1)

    def test_report_not_written_for_missing_directory(self):
        with _tempdir() as td:
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            rc = run_batch(
                os.path.join(td, "nope"), VALIDATE_MODE,
                stdout=buf, report_path=report,
            )
            self.assertFalse(os.path.exists(report))
        self.assertEqual(rc, 1)

    def test_report_not_written_for_unknown_mode(self):
        with _tempdir() as td:
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            rc = run_batch(
                td, "bogus", stdout=buf, report_path=report,
            )
            self.assertFalse(os.path.exists(report))
        self.assertEqual(rc, 2)

    def test_injected_report_writer_used(self):
        with _tempdir() as td:
            save_project(
                _make_project(name="a"),
                os.path.join(td, "a.json"),
            )
            captured = []
            def writer(path, payload):
                captured.append((path, payload))
            buf = io.StringIO()
            run_batch(
                td, VALIDATE_MODE, stdout=buf,
                report_path="/virtual/report.json",
                report_writer=writer,
            )
        self.assertEqual(len(captured), 1)
        self.assertIn("validate", captured[0][1])


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class CLIIntegrationTests(unittest.TestCase):
    def test_report_flag_accepted(self):
        with _tempdir() as td:
            save_project(
                _make_project(name="a"),
                os.path.join(td, "a.json"),
            )
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate", "--report", report],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(report))

    def test_report_flag_omitted_backward_compatible(self):
        with _tempdir() as td:
            save_project(
                _make_project(name="a"),
                os.path.join(td, "a.json"),
            )
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            # Only the project file exists; no report file.
            self.assertEqual(sorted(os.listdir(td)), ["a.json"])

    def test_invalid_cli_usage_unchanged(self):
        # Existing CLI argument validation must remain exit 2.
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            self.assertEqual(
                cli_main(["batch"], stdout=buf), 2,
            )
            buf = io.StringIO()
            self.assertEqual(
                cli_main(["batch", "some-dir"], stdout=buf), 2,
            )

    def test_report_path_forwarded_to_batch(self):
        # The CLI must forward the report path. We verify by
        # injecting a fake run_batch via the CLI DI surface is
        # not available; the CLI dispatches to the real
        # ``_default_run_batch`` which calls the real
        # ``run_batch``. We exercise the public ``run_batch``
        # directly in the batch-integration tests. Here we
        # only verify the CLI does not raise and that the
        # report file appears.
        with _tempdir() as td:
            save_project(
                _make_project(name="a"),
                os.path.join(td, "a.json"),
            )
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "show", "--report", report],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(report))

    def test_show_mode_report(self):
        with _tempdir() as td:
            save_project(
                _make_project(name="a", description="d"),
                os.path.join(td, "a.json"),
            )
            report = os.path.join(td, "report.json")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "show", "--report", report],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            with open(report, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["mode"], "show")
        self.assertEqual(data["success_count"], 1)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_repeated_runs_produce_byte_identical_reports(self):
        with _tempdir() as td:
            projects_dir = os.path.join(td, "projects")
            os.mkdir(projects_dir)
            for name in ("a.json", "b.json", "c.json"):
                save_project(
                    _make_project(name=name[:-5]),
                    os.path.join(projects_dir, name),
                )
            r1 = os.path.join(td, "r1.json")
            r2 = os.path.join(td, "r2.json")
            run_batch(
                projects_dir, VALIDATE_MODE,
                stdout=io.StringIO(), report_path=r1,
            )
            run_batch(
                projects_dir, VALIDATE_MODE,
                stdout=io.StringIO(), report_path=r2,
            )
            with open(r1, encoding="utf-8") as fh:
                t1 = fh.read()
            with open(r2, encoding="utf-8") as fh:
                t2 = fh.read()
        self.assertEqual(t1, t2)

    def test_repeated_serialization_byte_identical(self):
        e = BatchProjectReportEntry(path="/a.json", success=True)
        r = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(e,),
        )
        self.assertEqual(report_to_json(r), report_to_json(r))


# ---------------------------------------------------------------------------
# Error tests
# ---------------------------------------------------------------------------


class ErrorTests(unittest.TestCase):
    def test_report_input_error_attributes(self):
        err = ReportInputError("path", "")
        self.assertEqual(err.parameter, "path")
        self.assertEqual(err.value, "")
        self.assertIsInstance(err, ValueError)

    def test_report_input_error_message(self):
        err = ReportInputError("mode", "bogus")
        self.assertIn("mode", str(err))
        self.assertIn("bogus", str(err))

    def test_save_report_oserror_propagates(self):
        e = BatchProjectReportEntry(path="/a.json", success=True)
        r = BatchReport(
            mode="validate", project_count=1,
            success_count=1, failure_count=0,
            projects=(e,),
        )
        # Path that the OS / Path will reject.
        with self.assertRaises((OSError, ValueError, ReportInputError)):
            save_report(r, "\x00bad\x00")


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


class ArchitectureTests(unittest.TestCase):
    def test_report_does_not_import_bpy(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import: {name}",
            )

    def test_report_does_not_import_ollama(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"ollama", "ollama_client"},
                f"forbidden ollama import: {name}",
            )

    def test_report_does_not_import_requests(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"requests"},
                f"forbidden requests import: {name}",
            )

    def test_report_does_not_import_urllib(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"urllib", "urllib.request"},
                f"forbidden urllib import: {name}",
            )

    def test_report_does_not_import_http(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"http"},
                f"forbidden http import: {name}",
            )

    def test_report_does_not_import_pipeline(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"pipeline"},
                f"forbidden pipeline import: {name}",
            )

    def test_report_does_not_import_asset_registry(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"asset_registry"},
                f"forbidden asset_registry import: {name}",
            )

    def test_report_does_not_import_scene_plan(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"scene_plan"},
                f"forbidden scene_plan import: {name}",
            )

    def test_report_does_not_import_toonflow_ai_generation(self):
        for name in _ast_all_imports(REPORT_SOURCE):
            self.assertFalse(
                name.startswith("toonflow_ai"),
                f"forbidden toonflow_ai import: {name}",
            )

    def test_report_does_not_reference_bpy_data_or_bpy_ops(self):
        self.assertNotIn("bpy.data", REPORT_SOURCE)
        self.assertNotIn("bpy.ops", REPORT_SOURCE)

    def test_report_does_not_call_keyframe_insert(self):
        self.assertNotIn("keyframe_insert", REPORT_SOURCE)

    def test_report_does_not_call_rendering_apis(self):
        for forbidden in (
            "render_scene(", "create_or_update_camera(",
            "from_pydata(", "bpy.ops.render",
        ):
            self.assertNotIn(forbidden, REPORT_SOURCE)

    def test_report_does_not_call_workflow_executors(self):
        for forbidden in (
            "create_and_render_scene",
            "create_and_render_shots",
        ):
            self.assertNotIn(forbidden, REPORT_SOURCE)

    def test_report_does_not_use_print(self):
        self.assertNotIn("print(", REPORT_SOURCE)

    def test_report_does_not_use_input(self):
        self.assertNotIn("input(", REPORT_SOURCE)

    def test_report_open_calls_controlled(self):
        # ``open(`` is allowed only inside ``_default_report_writer``.
        # Count occurrences and confirm they are inside that
        # function body.
        tree = ast.parse(REPORT_SOURCE)
        opens = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "open":
                    opens.append((node.lineno, len(node.args)))
        # Exactly one open() call (the file write in
        # _default_report_writer).
        self.assertEqual(
            len(opens), 1,
            f"expected exactly one controlled open() call, got {opens}",
        )

    def test_report_top_level_imports_minimal(self):
        tree = ast.parse(REPORT_SOURCE)
        names = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.append((alias.name, 0))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.append((node.module, getattr(node, "level", 0)))
        for name, level in names:
            if level > 0:
                continue
            self.assertIn(
                name,
                {"json", "os", "dataclasses", "pathlib", "typing"},
                f"unexpected top-level import: {name}",
            )

    def test_batch_does_not_own_json_serialization(self):
        # The batch layer historically did not import ``json``;
        # the report layer owned JSON serialization. PHASE-026
        # deliberately adds the ``batch_dry_run_to_json``
        # helper to the batch layer for the dry-run result
        # only. The report layer still owns the execution
        # report JSON (``report_to_json``).
        #
        # The batch layer may still delegate to the report
        # layer's public entry points (``batch_result_to_report``,
        # ``save_report``); that wiring is owned by PHASE-021
        # and must not be duplicated or replaced.
        #
        # This test now asserts the specific narrow exception:
        # ``json`` is allowed, but the report layer's JSON
        # serialization helpers must not be reimplemented
        # in the batch layer.
        for forbidden in (
            "report_to_dict", "report_to_json",
        ):
            self.assertNotIn(
                forbidden, BATCH_SOURCE,
                f"batch.py must not reference report JSON helpers: {forbidden}",
            )
        # The batch layer must not import anything from the
        # report layer (it uses lazy import inside the report
        # writing branch instead).
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertFalse(
                name.startswith("from .report") or name.startswith("from workflow.report") or name == ".report",
                f"batch.py must not import from the report layer: {name}",
            )

    def test_cli_does_not_serialize_json(self):
        # The CLI must not import ``json`` for report purposes.
        # (It does not need to; the report layer owns JSON.)
        self.assertNotIn("import json", CLI_SOURCE)
        self.assertNotIn("json.dumps", CLI_SOURCE)
        self.assertNotIn("json.dump", CLI_SOURCE)

    def test_cli_forwards_report_path(self):
        # The CLI must wire the ``--report`` value to run_batch.
        self.assertIn("--report", CLI_SOURCE)
        self.assertIn("report_path", CLI_SOURCE)
        self.assertIn("report_writer", CLI_SOURCE)


if __name__ == "__main__":
    unittest.main()
