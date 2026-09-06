"""Tests for TOONFLOW-PHASE-029 retry observability."""

import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path

from workflow.batch import BatchAttemptResult, BatchProjectResult, batch_dry_run_to_dict, dry_run_batch, run_batch
from workflow.report import BatchProjectReportEntry, BatchReport, ReportInputError, load_report, report_from_json, report_to_dict, report_to_json


class AttemptModelTests(unittest.TestCase):
    def test_attempt_result_is_immutable_and_one_based(self):
        attempt = BatchAttemptResult(1, False, "ValueError: bad")
        self.assertEqual(attempt.attempt, 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            attempt.attempt = 2
        for bad in (0, -1, True, "1"):
            with self.assertRaises(ValueError):
                BatchAttemptResult(bad, False)

    def test_batch_project_result_exposes_aggregate_and_history(self):
        result = BatchProjectResult(
            "a.json", success=True,
            attempts=(BatchAttemptResult(1, False, "ValueError: bad"),
                      BatchAttemptResult(2, True)),
        )
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(result.final_attempt, 2)
        self.assertTrue(result.retried)
        self.assertEqual(result.attempt_history[1].attempt, 2)


class RetryObservabilityExecutionTests(unittest.TestCase):
    def _project(self, directory):
        path = Path(directory) / "a.json"
        path.write_text("{}", encoding="utf-8")
        return path

    def test_success_first_attempt_has_one_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            result = []
            run_batch(td, "validate", load_project=lambda path: object(),
                      stdout=io.StringIO())
            def load(path):
                return object()
            # Capture the report to inspect the final aggregate metadata.
            report_path = Path(td) / "report.json"
            run_batch(td, "validate", load_project=load,
                      report_path=report_path, stdout=io.StringIO())
            entry = load_report(report_path).projects[0]
            self.assertEqual(entry.attempts, 1)
            self.assertFalse(entry.retried)

    def test_fail_success_and_fail_fail_success_are_observable(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            report_path = Path(td) / "report.json"
            calls = [0]
            def load(path):
                calls[0] += 1
                if calls[0] < 3:
                    raise ValueError("transient")
                return object()
            run_batch(td, "validate", retries=2, load_project=load,
                      report_path=report_path, stdout=io.StringIO())
            entry = load_report(report_path).projects[0]
            self.assertEqual(entry.attempts, 3)
            self.assertTrue(entry.retried)
            self.assertTrue(entry.success)

    def test_exhaustion_records_final_failure_and_one_entry(self):
        with tempfile.TemporaryDirectory() as td:
            self._project(td)
            report_path = Path(td) / "report.json"
            run_batch(td, "validate", retries=2,
                      load_project=lambda path: (_ for _ in ()).throw(ValueError("final")),
                      report_path=report_path, stdout=io.StringIO())
            report = load_report(report_path)
            self.assertEqual(len(report.projects), 1)
            self.assertFalse(report.projects[0].success)
            self.assertEqual(report.projects[0].attempts, 3)
            self.assertTrue(report.projects[0].retried)


class ReportCompatibilityTests(unittest.TestCase):
    def _old_report_json(self):
        return json.dumps({
            "mode": "validate", "project_count": 1,
            "success_count": 1, "failure_count": 0,
            "projects": [{
                "path": "a.json", "success": True,
                "error_type": None, "error_message": None,
                "output_paths": [],
            }],
        })

    def test_old_report_defaults_to_one_attempt(self):
        entry = report_from_json(self._old_report_json()).projects[0]
        self.assertEqual(entry.attempts, 1)
        self.assertFalse(entry.retried)

    def test_retry_metadata_has_stable_optional_field_order(self):
        entry = BatchProjectReportEntry("a.json", True, attempts=2, retried=True)
        data = report_to_dict(BatchReport("validate", 1, 1, 0, (entry,)))
        self.assertEqual(list(data["projects"][0]), [
            "path", "success", "error_type", "error_message",
            "output_paths", "attempts", "retried",
        ])
        self.assertEqual(json.loads(report_to_json(BatchReport("validate", 1, 1, 0, (entry,))))["projects"][0]["attempts"], 2)

    def test_malformed_retry_metadata_rejected(self):
        data = json.loads(self._old_report_json())
        for attempts in (0, -1, True, "2"):
            data["projects"][0]["attempts"] = attempts
            data["projects"][0]["retried"] = True
            with self.assertRaises(ReportInputError):
                report_from_json(json.dumps(data))

    def test_inconsistent_retry_metadata_rejected(self):
        entry = BatchProjectReportEntry("a.json", True)
        with self.assertRaises(ReportInputError):
            BatchProjectReportEntry("a.json", True, attempts=2, retried=False)


class DryRunObservabilityTests(unittest.TestCase):
    def test_dry_run_exposes_capacity_not_actual_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.json").write_text("{}", encoding="utf-8")
            result = dry_run_batch(td, "validate", retries=2)
            data = batch_dry_run_to_dict(result)
            self.assertEqual(data["retries"], 2)
            self.assertEqual(data["max_attempts"], 3)
            self.assertNotIn("attempts", data)

    def test_dry_run_never_loads_projects(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.json").write_text("{}", encoding="utf-8")
            result = dry_run_batch(td, "validate", retries=2)
            self.assertEqual(result.projects, (Path(td, "a.json"),))


if __name__ == "__main__":
    unittest.main()
