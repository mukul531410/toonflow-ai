"""Tests for TOONFLOW-PHASE-028 batch retry and failure recovery."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from workflow.batch import batch_dry_run_to_dict, dry_run_batch, run_batch
from workflow.cli import main as cli_main
from workflow.manifest import BatchManifest, run_batch_manifest
from workflow.report import BatchProjectReportEntry, BatchReport, load_report, report_to_json


class RetryExecutionTests(unittest.TestCase):
    def _projects(self, directory, *names):
        for name in names:
            (Path(directory) / name).write_text("{}", encoding="utf-8")

    def test_default_and_zero_retry_attempt_once(self):
        with tempfile.TemporaryDirectory() as td:
            self._projects(td, "a.json")
            for retries in (None, 0):
                calls = []
                output = io.StringIO()
                kwargs = {} if retries is None else {"retries": retries}
                rc = run_batch(
                    td, "validate", stdout=output,
                    load_project=lambda path: calls.append(path) or (_ for _ in ()).throw(ValueError("bad")),
                    **kwargs,
                )
                self.assertEqual(rc, 1)
                self.assertEqual(len(calls), 1)

    def test_fail_then_success_retries_and_stops(self):
        with tempfile.TemporaryDirectory() as td:
            self._projects(td, "a.json")
            calls = []
            def load(path):
                calls.append(path)
                if len(calls) < 3:
                    raise ValueError("transient")
                return object()
            rc = run_batch(td, "validate", retries=2, load_project=load, stdout=io.StringIO())
            self.assertEqual(rc, 0)
            self.assertEqual(len(calls), 3)

    def test_success_after_retry_is_reported_once_as_success(self):
        with tempfile.TemporaryDirectory() as td:
            self._projects(td, "a.json")
            report_path = Path(td) / "out-report.json"
            calls = []
            def load(path):
                calls.append(path)
                if len(calls) == 1:
                    raise ValueError("transient")
                return object()
            rc = run_batch(
                td, "validate", retries=1, load_project=load,
                report_path=report_path, stdout=io.StringIO(),
            )
            report = load_report(report_path)
            self.assertEqual(rc, 0)
            self.assertEqual(len(report.projects), 1)
            self.assertEqual(report.success_count, 1)
            self.assertTrue(report.projects[0].success)

    def test_final_failure_uses_last_error_and_later_project_runs(self):
        with tempfile.TemporaryDirectory() as td:
            self._projects(td, "a.json", "b.json")
            calls = []
            def load(path):
                calls.append(Path(path).name)
                if Path(path).name == "a.json":
                    raise ValueError(f"failure-{len(calls)}")
                return object()
            report_path = Path(td) / "report.json"
            rc = run_batch(
                td, "validate", retries=2, load_project=load,
                report_path=report_path, stdout=io.StringIO(),
            )
            report = load_report(report_path)
            self.assertEqual(rc, 1)
            self.assertEqual(calls, ["a.json", "a.json", "a.json", "b.json"])
            self.assertEqual(report.failure_count, 1)
            self.assertIn("failure-3", report.projects[0].error_message)
            self.assertTrue(report.projects[1].success)

    def test_negative_retries_is_invalid_programmatic_input(self):
        with tempfile.TemporaryDirectory() as td:
            self._projects(td, "a.json")
            output = io.StringIO()
            self.assertEqual(run_batch(td, "validate", retries=-1, stdout=output), 2)
            self.assertIn("retries", output.getvalue())


class RetryResumeTests(unittest.TestCase):
    def test_previous_success_is_skipped_and_previous_failure_retries(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as rd:
            projects = [Path(td) / name for name in ("a.json", "b.json", "c.json")]
            for path in projects:
                path.write_text("{}", encoding="utf-8")
            history = Path(rd) / "history.json"
            history.write_text(report_to_json(BatchReport(
                "validate", 2, 1, 1,
                (BatchProjectReportEntry(str(projects[0]), True),
                 BatchProjectReportEntry(str(projects[1]), False,
                                         error_type="ValueError", error_message="old")),
            )), encoding="utf-8")
            calls = []
            attempts = {"b.json": 0, "c.json": 0}
            def load(path):
                name = Path(path).name
                calls.append(name)
                attempts[name] += 1
                if name == "b.json" and attempts[name] == 1:
                    raise ValueError("retry")
                return object()
            rc = run_batch(
                td, "validate", resume_from=history, retries=1,
                load_project=load, stdout=io.StringIO(),
            )
            self.assertEqual(rc, 0)
            self.assertEqual(calls, ["b.json", "b.json", "c.json"])
            self.assertNotIn("a.json", calls)


class RetryDryRunTests(unittest.TestCase):
    def test_dry_run_does_not_execute_and_exposes_retries(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.json").write_text("{}", encoding="utf-8")
            result = dry_run_batch(td, "validate", retries=3)
            self.assertEqual(result.retries, 3)
            self.assertEqual(batch_dry_run_to_dict(result)["retries"], 3)

    def test_dry_run_default_json_contract_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.json").write_text("{}", encoding="utf-8")
            self.assertNotIn("retries", batch_dry_run_to_dict(dry_run_batch(td, "validate")))


class RetryCliManifestTests(unittest.TestCase):
    def test_cli_retries_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.json").write_text("{}", encoding="utf-8")
            output = io.StringIO()
            rc = cli_main(["batch", td, "validate", "--retries", "2", "--dry-run", "--json"], stdout=output)
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.getvalue())["retries"], 2)
            self.assertEqual(cli_main(["batch", td, "validate", "--retries", "-1"], stdout=io.StringIO()), 2)
            self.assertEqual(cli_main(["batch", td, "validate", "--retries", "bad"], stdout=io.StringIO()), 2)

    def test_manifest_forwards_retries_without_persisting_it(self):
        calls = []
        manifest = BatchManifest(directory="./projects", mode="validate")
        run_batch_manifest(
            manifest,
            run_batch=lambda *args, **kwargs: calls.append(kwargs) or 0,
            retries=2,
        )
        self.assertEqual(calls[0]["retries"], 2)
        self.assertNotIn("retries", manifest.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
