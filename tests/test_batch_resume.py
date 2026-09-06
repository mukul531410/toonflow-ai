"""Tests for TOONFLOW-PHASE-027 batch resume and continuation."""

import dataclasses
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from workflow.batch import (
    BatchResumeResult,
    BatchProjectResult,
    batch_dry_run_to_dict,
    dry_run_batch,
    plan_batch_resume,
    run_batch,
)
from workflow.cli import main as cli_main
from workflow.manifest import BatchManifest, dry_run_batch_manifest, run_batch_manifest
from workflow.report import (
    BatchProjectReportEntry,
    BatchReport,
    load_report,
    report_to_json,
)


class ResumeModelTests(unittest.TestCase):
    def test_result_is_frozen_and_normalizes_tuples(self):
        selected = ["a.json"]
        result = BatchResumeResult(selected, ["a.json"], [])
        selected.append("b.json")
        self.assertEqual(result.selected_projects, ("a.json",))
        self.assertIsInstance(result.pending_projects, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.pending_projects = ()

    def test_planner_success_only_and_deterministic(self):
        report = BatchReport(
            mode="validate", project_count=3, success_count=1, failure_count=2,
            projects=(
                BatchProjectReportEntry("b.json", True),
                BatchProjectReportEntry("a.json", False),
                BatchProjectReportEntry("unknown.json", False),
            ),
        )
        result = plan_batch_resume(("unknown.json", "b.json", "new.json"), report)
        self.assertEqual(result.selected_projects, ("unknown.json", "b.json", "new.json"))
        self.assertEqual(result.skipped_projects, ("b.json",))
        self.assertEqual(result.pending_projects, ("unknown.json", "new.json"))

    def test_duplicate_history_is_ambiguous(self):
        entry = BatchProjectReportEntry("a.json", True)
        report = BatchReport("validate", 2, 2, 0, (entry, entry))
        result = plan_batch_resume(("a.json",), report)
        self.assertEqual(result.skipped_projects, ())
        self.assertEqual(result.pending_projects, ("a.json",))

    def test_path_matching_normalizes_separators_without_case_folding(self):
        report = BatchReport(
            "validate", 1, 1, 0,
            (BatchProjectReportEntry("folder\\a.json", True),),
        )
        result = plan_batch_resume(("folder/a.json", "FOLDER/a.json"), report)
        self.assertEqual(result.skipped_projects, ("folder/a.json",))
        self.assertEqual(result.pending_projects, ("FOLDER/a.json",))


class ResumeExecutionTests(unittest.TestCase):
    def _files(self, directory, names):
        for name in names:
            path = Path(directory) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")

    def _report(self, path, *entries):
        report = BatchReport(
            "validate", len(entries), sum(e.success for e in entries),
            sum(not e.success for e in entries), tuple(entries),
        )
        Path(path).write_text(report_to_json(report), encoding="utf-8")

    def test_only_pending_projects_are_loaded_in_order(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as rd:
            self._files(td, ("a.json", "b.json", "c.json"))
            history = Path(rd) / "previous.json"
            self._report(history, BatchProjectReportEntry(str(Path(td) / "a.json"), True),
                         BatchProjectReportEntry(str(Path(td) / "b.json"), False))
            calls = []
            output = io.StringIO()
            rc = run_batch(
                td, "validate", resume_from=history,
                load_project=lambda path: calls.append(path) or object(), stdout=output,
            )
            self.assertEqual(rc, 0)
            self.assertEqual([Path(p).name for p in calls], ["b.json", "c.json"])
            self.assertIn("a.json: SKIP", output.getvalue())

    def test_filters_are_applied_before_resume(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as rd:
            self._files(td, ("a.json", "b.json", "c.json"))
            history = Path(rd) / "previous.json"
            self._report(history, BatchProjectReportEntry(str(Path(td) / "a.json"), True),
                         BatchProjectReportEntry(str(Path(td) / "b.json"), True))
            calls = []
            rc = run_batch(
                td, "validate", include="b.json", exclude="a.json",
                resume_from=history,
                load_project=lambda path: calls.append(path) or object(), stdout=io.StringIO(),
            )
            self.assertEqual(rc, 0)
            self.assertEqual(calls, [])

    def test_previous_report_is_read_only_and_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            self._files(td, ("a.json",))
            history = Path(td).parent / "history.json"
            self._report(history, BatchProjectReportEntry(str(Path(td) / "a.json"), True))
            before = history.read_bytes()
            output = io.StringIO()
            rc = run_batch(td, "validate", resume_from=history, report_path=history, stdout=output)
            self.assertEqual(rc, 1)
            self.assertEqual(history.read_bytes(), before)
            self.assertIn("cannot equal", output.getvalue())


class ResumeDryRunAndCliTests(unittest.TestCase):
    def test_dry_run_partitions_and_json(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as rd:
            for name in ("a.json", "b.json"):
                (Path(td) / name).write_text("{}", encoding="utf-8")
            history = Path(rd) / "previous.json"
            report = BatchReport("validate", 1, 1, 0,
                                 (BatchProjectReportEntry(str(Path(td) / "a.json"), True),))
            history.write_text(report_to_json(report), encoding="utf-8")
            result = dry_run_batch(td, "validate", resume_from=history)
            self.assertEqual([p.name for p in result.selected_projects], ["a.json", "b.json"])
            self.assertEqual([p.name for p in result.skipped_projects], ["a.json"])
            self.assertEqual([p.name for p in result.pending_projects], ["b.json"])
            data = batch_dry_run_to_dict(result)
            self.assertEqual([Path(p).name for p in data["skipped_projects"]], ["a.json"])

    def test_cli_resume_dry_run_json_is_json_only(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as rd:
            (Path(td) / "a.json").write_text("{}", encoding="utf-8")
            history = Path(rd) / "previous.json"
            history.write_text(report_to_json(BatchReport(
                "validate", 1, 1, 0,
                (BatchProjectReportEntry(str(Path(td) / "a.json"), True),),
            )), encoding="utf-8")
            output = io.StringIO()
            rc = cli_main(["batch", td, "validate", "--resume-from", str(history),
                           "--dry-run", "--json"], stdout=output)
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.getvalue())["skipped_projects"], [str(Path(td) / "a.json").replace(os.sep, "/")])

    def test_manifest_resume_is_execution_time_only(self):
        calls = []
        manifest = BatchManifest(directory="./projects", mode="validate")
        run_batch_manifest(
            manifest, run_batch=lambda *args, **kwargs: calls.append(kwargs) or 0,
            resume_from="history.json",
        )
        self.assertEqual(calls[0]["resume_from"], "history.json")
        self.assertNotIn("resume_from", manifest.__dataclass_fields__)

    def test_missing_resume_file_returns_one(self):
        output = io.StringIO()
        rc = run_batch(".", "validate", resume_from="missing-report.json", stdout=output)
        self.assertEqual(rc, 1)

    def test_report_loader_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "report.json"
            report = BatchReport("validate", 1, 1, 0,
                                 (BatchProjectReportEntry("a.json", True),))
            path.write_text(report_to_json(report), encoding="utf-8")
            self.assertEqual(load_report(path), report)


if __name__ == "__main__":
    unittest.main()
