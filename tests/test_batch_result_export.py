"""Tests for TOONFLOW-PHASE-031 batch result export."""

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from workflow.batch import (
    BatchAttemptResult,
    BatchProjectResult,
    BatchResultExport,
    batch_result_to_dict,
    batch_result_to_json,
    build_batch_operational_summary,
    dry_run_batch,
    export_batch_result,
)
from workflow.manifest import BatchManifest, dry_run_batch_manifest


class ExportTests(unittest.TestCase):
    def _result(self, path, success, attempts=1):
        history = tuple(
            BatchAttemptResult(
                index,
                success if index == attempts else False,
                None if success and index == attempts else "ValueError: failed",
            )
            for index in range(1, attempts + 1)
        )
        return BatchProjectResult(path, success=success, attempts=history)

    def test_export_model_is_frozen_and_deterministic(self):
        result = self._result("a.json", True)
        export = export_batch_result(
            ".", "validate", (result,), selected_projects=("a.json",),
        )
        self.assertIsInstance(export, BatchResultExport)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            export.mode = "run"
        self.assertEqual(batch_result_to_dict(export), batch_result_to_dict(export))
        self.assertEqual(batch_result_to_json(export), batch_result_to_json(export))

    def test_mixed_results_match_operational_summary(self):
        results = (
            self._result("a.json", True),
            self._result("b.json", True, 2),
            self._result("c.json", False, 3),
        )
        export = export_batch_result(
            "./projects", "validate", results,
            recursive=True, include=("*.json",), exclude=("draft*",),
            selected_projects=("a.json", "b.json", "c.json", "d.json"),
            skipped_projects=("d.json",),
        )
        expected = build_batch_operational_summary(
            results, selected=4, skipped=1,
        )
        self.assertEqual(export.summary, expected)
        data = batch_result_to_dict(export)
        self.assertEqual(list(data), [
            "directory", "mode", "recursive", "include", "exclude",
            "dry_run", "projects", "summary", "selected_projects",
            "skipped_projects", "pending_projects",
        ])
        self.assertEqual(data["summary"]["total_attempts"], 6)
        self.assertEqual(data["summary"]["retried"], 2)
        self.assertEqual(len(data["projects"]), 3)

    def test_retry_and_final_outcome_are_exported_without_attempt_history(self):
        result = self._result("a.json", True, 2)
        data = batch_result_to_dict(export_batch_result(
            ".", "validate", (result,), selected_projects=("a.json",),
        ))
        project = data["projects"][0]
        self.assertEqual(project["attempts"], 2)
        self.assertTrue(project["retried"])
        self.assertNotIn("attempt_history", project)
        self.assertTrue(project["success"])

    def test_dry_run_export_has_no_project_execution_records(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.json").write_text("{}", encoding="utf-8")
            result = dry_run_batch(td, "validate", retries=2)
            export = export_batch_result(result)
            data = batch_result_to_dict(export)
            self.assertEqual(data["projects"], [])
            self.assertEqual(data["summary"]["selected"], 1)
            self.assertEqual(data["summary"]["pending"], 1)
            self.assertEqual(data["summary"]["executed"], 0)
            self.assertEqual(data["summary"]["total_attempts"], 0)

    def test_dry_run_resume_preserves_partitions(self):
        with tempfile.TemporaryDirectory() as td:
            paths = [Path(td, name) for name in ("a.json", "b.json")]
            for path in paths:
                path.write_text("{}", encoding="utf-8")
            historical = type("Report", (), {
                "projects": (type("Entry", (), {"path": str(paths[0]), "success": True})(),),
            })()
            result = dry_run_batch(
                td, "validate", resume_from="history.json",
                report_loader=lambda path: historical,
            )
            data = batch_result_to_dict(export_batch_result(result))
            self.assertEqual(data["summary"]["selected"], 2)
            self.assertEqual(data["summary"]["skipped"], 1)
            self.assertEqual(data["summary"]["pending"], 1)
            self.assertEqual(data["summary"]["succeeded"], 0)

    def test_manifest_and_direct_dry_run_exports_match(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.json").write_text("{}", encoding="utf-8")
            manifest = BatchManifest(directory=td, mode="validate", include=("*.json",))
            direct = export_batch_result(dry_run_batch(
                td, "validate", include=manifest.include, retries=1,
            ))
            via_manifest = export_batch_result(dry_run_batch_manifest(
                manifest, retries=1,
            ))
            self.assertEqual(
                batch_result_to_dict(direct), batch_result_to_dict(via_manifest),
            )
            self.assertEqual(manifest.include, ("*.json",))

    def test_json_is_json_safe_and_has_no_environment_fields(self):
        export = export_batch_result(
            ".", "validate", (self._result("a.json", True),),
            selected_projects=("a.json",),
        )
        text = batch_result_to_json(export)
        parsed = json.loads(text)
        self.assertEqual(parsed["mode"], "validate")
        self.assertTrue(text.endswith("\n"))
        for forbidden in ("timestamp", "uuid", "hostname", "attempt_history"):
            self.assertNotIn(forbidden, text.lower())


if __name__ == "__main__":
    unittest.main()
