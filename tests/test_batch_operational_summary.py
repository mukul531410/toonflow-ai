"""Tests for TOONFLOW-PHASE-030 operational summaries."""

import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path

from workflow.batch import (
    BatchAttemptResult,
    BatchOperationalSummary,
    BatchProjectResult,
    batch_dry_run_to_dict,
    build_batch_operational_summary,
    dry_run_batch,
    summarize_batch,
)
from workflow.manifest import BatchManifest, dry_run_batch_manifest, run_batch_manifest


class SummaryModelTests(unittest.TestCase):
    def test_model_is_immutable_and_accepts_zeroes(self):
        summary = BatchOperationalSummary(0, 0, 0, 0, 0, 0, 0)
        self.assertEqual(summary.selected, 0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            summary.selected = 1

    def test_negative_and_inconsistent_counts_rejected(self):
        with self.assertRaises(ValueError):
            BatchOperationalSummary(-1, 0, 0, 0, 0, 0, 0)
        with self.assertRaises(ValueError):
            BatchOperationalSummary(2, 0, 1, 1, 1, 0, 1)

    def test_synthetic_retry_summary_is_deterministic(self):
        def result(success, attempts):
            return BatchProjectResult(
                "project.json", success=success,
                attempts=tuple(
                    BatchAttemptResult(index, index == attempts and success,
                                       None if index == attempts and success else "ValueError: fail")
                    for index in range(1, attempts + 1)
                ),
            )
        results = (result(True, 1), result(True, 2), result(True, 3), result(False, 3))
        summary = build_batch_operational_summary(results, selected=6, skipped=2)
        self.assertEqual(summary, summarize_batch(results, selected=6, skipped=2))
        self.assertEqual((summary.selected, summary.skipped, summary.executed), (6, 2, 4))
        self.assertEqual((summary.succeeded, summary.failed), (3, 1))
        self.assertEqual((summary.retried, summary.total_attempts), (3, 9))


class DryRunSummaryTests(unittest.TestCase):
    def test_dry_run_has_pending_and_no_actual_execution(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ("a.json", "b.json"):
                Path(td, name).write_text("{}", encoding="utf-8")
            result = dry_run_batch(td, "validate")
            summary = build_batch_operational_summary(
                (), selected=len(result.selected_projects),
                skipped=len(result.skipped_projects),
                pending=len(result.pending_projects), dry_run=True,
            )
            self.assertEqual(summary.selected, 2)
            self.assertEqual(summary.pending, 2)
            self.assertEqual(summary.executed, 0)
            self.assertEqual(summary.total_attempts, 0)

    def test_dry_run_json_contains_summary_counters_only(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.json").write_text("{}", encoding="utf-8")
            data = batch_dry_run_to_dict(dry_run_batch(td, "validate", retries=2))
            self.assertEqual(
                {data[key] for key in ("selected", "pending", "executed", "succeeded", "failed", "retried", "total_attempts")},
                {1, 0},
            )
            self.assertEqual(data["selected"], 1)
            self.assertEqual(data["pending"], 1)
            self.assertEqual(data["total_attempts"], 0)
            self.assertNotIn("attempts", data)
            self.assertEqual(json.dumps(data, sort_keys=False), json.dumps(data, sort_keys=False))


class ManifestSummaryTests(unittest.TestCase):
    def test_manifest_dry_run_preserves_summary_semantics_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.json").write_text("{}", encoding="utf-8")
            manifest = BatchManifest(directory=td, mode="validate")
            before = manifest
            direct = dry_run_batch(td, "validate", retries=2)
            via_manifest = dry_run_batch_manifest(manifest, retries=2)
            self.assertEqual(len(direct.projects), len(via_manifest.projects))
            self.assertEqual(direct.selected_projects, via_manifest.selected_projects)
            self.assertEqual(direct.pending_projects, via_manifest.pending_projects)
            self.assertEqual(manifest, before)

    def test_manifest_execution_forwards_summary_inputs_without_persisting(self):
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
