"""Tests for TOONFLOW-PHASE-032 batch result consistency validation."""

import dataclasses
import tempfile
import unittest
from pathlib import Path

from workflow.batch import (
    BatchAttemptResult,
    BatchOperationalSummary,
    BatchProjectResult,
    BatchResultExport,
    build_batch_operational_summary,
    dry_run_batch,
    export_batch_result,
    validate_batch_operational_summary,
    validate_batch_result_export,
    validate_batch_result_export_or_raise,
    validate_batch_results,
)


class ValidationTests(unittest.TestCase):
    def _summary(self, **values):
        fields = dict(
            selected=2, skipped=0, executed=2, succeeded=1,
            failed=1, retried=0, total_attempts=2, pending=0,
        )
        fields.update(values)
        summary = object.__new__(BatchOperationalSummary)
        for name, value in fields.items():
            object.__setattr__(summary, name, value)
        return summary

    def _result(self, path, success=True, attempts=1):
        history = tuple(
            BatchAttemptResult(index, index == attempts and success,
                               None if index == attempts and success else "ValueError: failed")
            for index in range(1, attempts + 1)
        )
        return BatchProjectResult(path, success=success, attempts=history)

    def test_valid_normal_results_and_summary(self):
        results = (self._result("a.json"), self._result("b.json", False))
        validation = validate_batch_results(results)
        self.assertTrue(validation.valid)
        summary = build_batch_operational_summary(results, selected=2)
        self.assertTrue(validate_batch_operational_summary(summary).valid)

    def test_invalid_summary_findings_are_stable(self):
        summary = self._summary(selected=3, total_attempts=0)
        first = validate_batch_operational_summary(summary)
        second = validate_batch_operational_summary(summary)
        self.assertFalse(first.valid)
        self.assertEqual(first, second)
        self.assertEqual(first.findings, (
            "selected must equal skipped plus executed",
            "total_attempts must be at least executed",
        ))

    def test_dry_run_summary_uses_dry_run_invariants(self):
        valid = self._summary(
            selected=3, skipped=1, executed=0, succeeded=0,
            failed=0, retried=0, total_attempts=0, pending=2,
        )
        self.assertTrue(validate_batch_operational_summary(valid, dry_run=True).valid)
        invalid = self._summary(
            selected=3, skipped=1, executed=1, succeeded=1,
            failed=0, retried=0, total_attempts=1, pending=2,
        )
        self.assertFalse(validate_batch_operational_summary(invalid, dry_run=True).valid)

    def test_project_attempt_history_and_final_state_are_checked(self):
        result = self._result("a.json", True, 2)
        self.assertTrue(validate_batch_results((result,)).valid)
        malformed = object.__new__(BatchProjectResult)
        object.__setattr__(malformed, "path", "a.json")
        object.__setattr__(malformed, "success", True)
        object.__setattr__(malformed, "error", None)
        object.__setattr__(malformed, "project", None)
        object.__setattr__(malformed, "result", None)
        object.__setattr__(malformed, "attempt_history", (BatchAttemptResult(2, True),))
        self.assertFalse(validate_batch_results((malformed,)).valid)

    def test_export_consistency_and_strict_validation(self):
        result = self._result("a.json", True, 2)
        export = export_batch_result(
            ".", "validate", (result,), selected_projects=("a.json",),
        )
        self.assertTrue(validate_batch_result_export(export).valid)
        self.assertIs(validate_batch_result_export_or_raise(export), export)
        forged = object.__new__(BatchResultExport)
        for name, value in (
            ("directory", "."), ("mode", "validate"), ("recursive", False),
            ("include", ()), ("exclude", ()), ("projects", (result,)),
            ("summary", build_batch_operational_summary((result,), selected=1)),
            ("selected_projects", ("a.json",)), ("skipped_projects", ()),
            ("pending_projects", ()), ("dry_run", False),
        ):
            object.__setattr__(forged, name, value)
        object.__setattr__(forged, "summary", self._summary(
            selected=1, skipped=0, executed=0, succeeded=0,
            failed=0, total_attempts=0,
        ))
        validation = validate_batch_result_export(forged)
        self.assertFalse(validation.valid)
        with self.assertRaises(ValueError):
            validate_batch_result_export_or_raise(forged)

    def test_dry_run_export_rejects_fabricated_project_records(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.json").write_text("{}", encoding="utf-8")
            dry_result = dry_run_batch(td, "validate")
            export = export_batch_result(dry_result)
            self.assertTrue(validate_batch_result_export(export).valid)
            forged = object.__new__(BatchResultExport)
            for field in dataclasses.fields(BatchResultExport):
                value = getattr(export, field.name)
                object.__setattr__(forged, field.name, value)
            object.__setattr__(forged, "projects", (self._result("a.json"),))
            self.assertFalse(validate_batch_result_export(forged).valid)

    def test_validation_does_not_mutate_inputs(self):
        result = self._result("a.json")
        export = export_batch_result(
            ".", "validate", (result,), selected_projects=("a.json",),
        )
        before = export.projects
        validate_batch_result_export(export)
        self.assertEqual(export.projects, before)


if __name__ == "__main__":
    unittest.main()
