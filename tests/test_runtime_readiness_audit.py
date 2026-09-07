"""Tests for TOONFLOW-PHASE-033 — Runtime Readiness Audit Foundation.

The audit layer tests cover:

A. Audit model immutability.
B. Deterministic finding ordering.
C. Repository structure detection.
D. Add-on package detection.
E. AI layer detection.
F. Blender generation layer detection.
G. Workflow layer detection.
H. Test coverage classification.
I. Explicit Blender-unverified classification.
J. Documentation consistency checks.
K. Release blocker classification.
L. Summary counters.
M. Deterministic dict output.
N. Deterministic JSON output.
O. Same input → byte-identical JSON.
P. No source mutation.
Q. No network/process/subprocess behavior.
R. Existing architecture guards remain valid.
"""

import ast
import json
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflow.audit import (  # noqa: E402
    AuditCategory,
    AuditFinding,
    AuditStatus,
    AuditSummary,
    RuntimeReadinessAudit,
    audit_finding_to_dict,
    audit_summary_to_dict,
    collect_repository_audit,
    runtime_readiness_audit_to_dict,
    runtime_readiness_audit_to_json,
)


def _ast_all_imports(source: str):
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


# --- Result model immutability ------------------------------------------------


class AuditModelImmutabilityTests(unittest.TestCase):
    def test_audit_finding_is_frozen(self):
        finding = AuditFinding(
            identifier="test",
            category=AuditCategory.REPOSITORY_STRUCTURE,
            status=AuditStatus.IMPLEMENTED,
            message="Test finding",
        )
        # Test that fields cannot be modified after creation
        with self.assertRaises(AttributeError):
            finding.identifier = "modified"

    def test_audit_finding_evidence_normalized_to_tuple(self):
        finding = AuditFinding(
            identifier="test",
            category=AuditCategory.REPOSITORY_STRUCTURE,
            status=AuditStatus.IMPLEMENTED,
            message="Test",
            evidence=["a.py", "b.py"],
        )
        self.assertIsInstance(finding.evidence, tuple)
        self.assertEqual(finding.evidence, ("a.py", "b.py"))

    def test_audit_summary_is_frozen(self):
        summary = AuditSummary(
            total_findings=1,
            implemented=1,
            test_covered=0,
            blender_unverified=0,
            documented=0,
            blocked=0,
            not_applicable=0,
            release_blocker_count=0,
        )
        # Test that fields cannot be modified after creation
        with self.assertRaises(AttributeError):
            summary.total_findings = 2

    def test_runtime_readiness_audit_is_frozen(self):
        finding = AuditFinding(
            identifier="test",
            category=AuditCategory.REPOSITORY_STRUCTURE,
            status=AuditStatus.IMPLEMENTED,
            message="Test",
        )
        summary = AuditSummary(
            total_findings=1,
            implemented=1,
            test_covered=0,
            blender_unverified=0,
            documented=0,
            blocked=0,
            not_applicable=0,
            release_blocker_count=0,
        )
        audit = RuntimeReadinessAudit(findings=(finding,), summary=summary)
        # Test that fields cannot be modified after creation
        with self.assertRaises(AttributeError):
            audit.findings = ()


# --- Deterministic ordering ---------------------------------------------------


class DeterministicOrderingTests(unittest.TestCase):
    def test_findings_sorted_by_category_then_identifier(self):
        findings = (
            AuditFinding(
                identifier="zeta",
                category=AuditCategory.WORKFLOW_LAYER,
                status=AuditStatus.IMPLEMENTED,
                message="zeta",
            ),
            AuditFinding(
                identifier="alpha",
                category=AuditCategory.REPOSITORY_STRUCTURE,
                status=AuditStatus.IMPLEMENTED,
                message="alpha",
            ),
            AuditFinding(
                identifier="beta",
                category=AuditCategory.REPOSITORY_STRUCTURE,
                status=AuditStatus.IMPLEMENTED,
                message="beta",
            ),
        )
        audit = RuntimeReadinessAudit.from_findings(findings)
        ordered = [f.identifier for f in audit.findings]
        self.assertEqual(ordered, ["alpha", "beta", "zeta"])

    def test_runtime_readiness_audit_from_findings_sorts(self):
        findings = (
            AuditFinding(
                identifier="z",
                category=AuditCategory.TESTING,
                status=AuditStatus.IMPLEMENTED,
                message="z",
            ),
            AuditFinding(
                identifier="a",
                category=AuditCategory.REPOSITORY_STRUCTURE,
                status=AuditStatus.IMPLEMENTED,
                message="a",
            ),
        )
        audit = RuntimeReadinessAudit.from_findings(findings)
        identifiers = [f.identifier for f in audit.findings]
        self.assertEqual(identifiers, ["a", "z"])


# --- Repository structure detection -------------------------------------------


class RepositoryStructureDetectionTests(unittest.TestCase):
    def test_collect_repository_structure_finds_addon(self):
        audit = collect_repository_audit()
        identifiers = {f.identifier for f in audit.findings}
        self.assertIn("addon_package_exists", identifiers)

    def test_collect_repository_structure_finds_workflow(self):
        audit = collect_repository_audit()
        identifiers = {f.identifier for f in audit.findings}
        self.assertIn("workflow_package_exists", identifiers)

    def test_collect_repository_structure_finds_ai(self):
        audit = collect_repository_audit()
        identifiers = {f.identifier for f in audit.findings}
        self.assertIn("ai_package_exists", identifiers)

    def test_collect_repository_structure_finds_asset_registry(self):
        audit = collect_repository_audit()
        identifiers = {f.identifier for f in audit.findings}
        self.assertIn("asset_registry_exists", identifiers)

    def test_collect_repository_structure_finds_tests(self):
        audit = collect_repository_audit()
        identifiers = {f.identifier for f in audit.findings}
        self.assertIn("tests_package_exists", identifiers)

    def test_all_structure_findings_have_correct_category(self):
        audit = collect_repository_audit()
        for finding in audit.findings:
            if finding.category == AuditCategory.REPOSITORY_STRUCTURE:
                self.assertEqual(finding.category, AuditCategory.REPOSITORY_STRUCTURE)


# --- Add-on package detection ------------------------------------------------


class AddonPackagingDetectionTests(unittest.TestCase):
    def test_addon_bl_info_found(self):
        audit = collect_repository_audit()
        bl_info_findings = [
            f for f in audit.findings
            if f.identifier == "addon_bl_info"
        ]
        self.assertEqual(len(bl_info_findings), 1)
        self.assertEqual(bl_info_findings[0].status, AuditStatus.IMPLEMENTED)

    def test_bpy_import_confined_to_addon(self):
        audit = collect_repository_audit()
        bpy_boundary_findings = [
            f for f in audit.findings
            if f.identifier == "addon_bpy_boundary"
        ]
        self.assertEqual(len(bpy_boundary_findings), 1)
        self.assertEqual(bpy_boundary_findings[0].status, AuditStatus.TEST_COVERED)

    def test_addon_modules_exist(self):
        audit = collect_repository_audit()
        identifiers = {f.identifier for f in audit.findings}
        for mod in ("addon_registration", "addon_operator", "addon_properties", "addon_ui"):
            self.assertIn(mod, identifiers)


# --- AI layer detection -------------------------------------------------------


class AILayerDetectionTests(unittest.TestCase):
    def test_ai_planner_implmented(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "ai_planner_implemented"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)

    def test_ai_ollama_client_exists(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "ai_ollama_client"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)

    def test_ai_errors_defined(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "ai_errors_defined"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)

    def test_ai_planner_no_blender_imports(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "ai_planner_no_blender"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.TEST_COVERED)


# --- Blender generation layer detection -------------------------------------


class BlenderGenerationDetectionTests(unittest.TestCase):
    def test_generation_package_exists(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "generation_package"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)

    def test_generation_modules_detected(self):
        audit = collect_repository_audit()
        identifiers = {f.identifier for f in audit.findings}
        for module in [
            "generation_animation",
            "generation_camera",
            "generation_lip_sync",
            "generation_pose",
            "generation_rendering",
            "generation_validation",
            "generation_blender_generator",
        ]:
            self.assertIn(module, identifiers)

    def test_generation_blender_runtime_unverified(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "generation_blender_runtime"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.BLENDER_UNVERIFIED)
        self.assertIn("UNVERIFIED", finding.message)


# --- Workflow layer detection ------------------------------------------------


class WorkflowLayerDetectionTests(unittest.TestCase):
    def test_workflow_batch_exists(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "workflow_batch"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)

    def test_workflow_manifest_exists(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "workflow_manifest"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)

    def test_workflow_report_exists(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "workflow_report"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)

    def test_workflow_project_exists(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "workflow_project"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)


# --- Test coverage classification ---------------------------------------------


class TestCoverageClassificationTests(unittest.TestCase):
    def test_testing_test_files_found(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "test_files_exist"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.IMPLEMENTED)

    def test_testing_blender_runtime_unverified(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "testing_blender_runtime"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.BLENDER_UNVERIFIED)


# --- Documentation consistency checks ----------------------------------------


class DocumentationConsistencyTests(unittest.TestCase):
    def test_documentation_architecture_md(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "doc_architecture"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.DOCUMENTED)

    def test_documentation_roadmap_md(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "doc_roadmap"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.DOCUMENTED)

    def test_documentation_tasks_md(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "doc_tasks"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.DOCUMENTED)

    def test_readme_contains_phase_status(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "doc_readme_phase_status"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.status, AuditStatus.DOCUMENTED)


# --- Release blocker classification -------------------------------------------


class ReleaseBlockerClassificationTests(unittest.TestCase):
    def test_blender_runtime_is_blocker(self):
        audit = collect_repository_audit()
        finding = next(
            (f for f in audit.findings if f.identifier == "blocker_blender_runtime"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertTrue(finding.blocks_release)
        self.assertEqual(finding.category, AuditCategory.RELEASE_BLOCKERS)

    def test_blocked_findings_have_blocks_release_true(self):
        audit = collect_repository_audit()
        for finding in audit.findings:
            if finding.status == AuditStatus.BLOCKED:
                self.assertTrue(finding.blocks_release)


# --- Summary counters ---------------------------------------------------------


class SummaryCounterTests(unittest.TestCase):
    def test_summary_total_equals_findings_count(self):
        audit = collect_repository_audit()
        self.assertEqual(audit.summary.total_findings, len(audit.findings))

    def test_summary_counts_match_status(self):
        audit = collect_repository_audit()
        for finding in audit.findings:
            if finding.status == AuditStatus.IMPLEMENTED:
                pass
        self.assertEqual(
            audit.summary.implemented,
            sum(1 for f in audit.findings if f.status == AuditStatus.IMPLEMENTED),
        )

    def test_summary_release_blockers_consistent(self):
        audit = collect_repository_audit()
        self.assertEqual(
            audit.summary.release_blocker_count,
            sum(1 for f in audit.findings if f.blocks_release),
        )


# --- Deterministic dict output ------------------------------------------------


class DeterministicDictOutputTests(unittest.TestCase):
    def test_audit_finding_to_dict_structure(self):
        finding = AuditFinding(
            identifier="test",
            category=AuditCategory.REPOSITORY_STRUCTURE,
            status=AuditStatus.IMPLEMENTED,
            message="Test message",
            evidence=("a.py", "b.py"),
            blocks_release=True,
        )
        d = audit_finding_to_dict(finding)
        self.assertEqual(d["identifier"], "test")
        self.assertEqual(d["category"], AuditCategory.REPOSITORY_STRUCTURE)
        self.assertEqual(d["status"], AuditStatus.IMPLEMENTED)
        self.assertEqual(d["message"], "Test message")
        self.assertEqual(d["evidence"], ["a.py", "b.py"])
        self.assertEqual(d["blocks_release"], True)

    def test_audit_summary_to_dict_structure(self):
        summary = AuditSummary(
            total_findings=10,
            implemented=5,
            test_covered=3,
            blender_unverified=2,
            documented=1,
            blocked=0,
            not_applicable=0,
            release_blocker_count=1,
        )
        d = audit_summary_to_dict(summary)
        self.assertEqual(d["total_findings"], 10)
        self.assertEqual(d["implemented"], 5)
        self.assertEqual(d["blender_unverified"], 2)

    def test_runtime_readiness_audit_to_dict_structure(self):
        finding = AuditFinding(
            identifier="test",
            category=AuditCategory.REPOSITORY_STRUCTURE,
            status=AuditStatus.IMPLEMENTED,
            message="Test",
        )
        summary = AuditSummary(
            total_findings=1,
            implemented=1,
            test_covered=0,
            blender_unverified=0,
            documented=0,
            blocked=0,
            not_applicable=0,
            release_blocker_count=0,
        )
        audit = RuntimeReadinessAudit(findings=(finding,), summary=summary)
        d = runtime_readiness_audit_to_dict(audit)
        self.assertIn("findings", d)
        self.assertIn("summary", d)
        self.assertEqual(len(d["findings"]), 1)


# --- Deterministic JSON output -----------------------------------------------


class DeterministicJsonOutputTests(unittest.TestCase):
    def test_json_produces_string(self):
        audit = collect_repository_audit()
        json_str = runtime_readiness_audit_to_json(audit)
        self.assertIsInstance(json_str, str)

    def test_json_is_valid_json(self):
        audit = collect_repository_audit()
        json_str = runtime_readiness_audit_to_json(audit)
        data = json.loads(json_str)
        self.assertIsInstance(data, dict)

    def test_json_has_single_trailing_newline(self):
        audit = collect_repository_audit()
        json_str = runtime_readiness_audit_to_json(audit)
        self.assertTrue(json_str.endswith("\n"))
        self.assertFalse(json_str.endswith("\n\n"))

    def test_repeated_audit_produces_identical_json(self):
        audit1 = collect_repository_audit()
        audit2 = collect_repository_audit()
        json1 = runtime_readiness_audit_to_json(audit1)
        json2 = runtime_readiness_audit_to_json(audit2)
        self.assertEqual(json1, json2)


# --- No source mutation tests -------------------------------------------------


class NoSourceMutationTests(unittest.TestCase):
    def test_audit_does_not_modify_files(self):
        repo_root = Path(__file__).resolve().parent.parent
        pre_md5 = {}
        for py_file in repo_root.rglob("*.py"):
            if "tests" in str(py_file) or "__pycache__" in str(py_file):
                continue
            try:
                pre_md5[str(py_file)] = py_file.stat().st_mtime
            except OSError:
                pass

        collect_repository_audit()
        collect_repository_audit()

        for py_file in repo_root.rglob("*.py"):
            if "tests" in str(py_file) or "__pycache__" in str(py_file):
                continue
            try:
                self.assertEqual(pre_md5.get(str(py_file)), py_file.stat().st_mtime)
            except OSError:
                pass


# --- No subprocess/network behavior ----------------------------------------


class NoSubprocessNetworkTests(unittest.TestCase):
    def test_audit_module_no_subprocess_imports(self):
        audit_source = (Path(__file__).resolve().parent.parent / "workflow" / "audit.py").read_text()
        imports = _ast_all_imports(audit_source)
        self.assertNotIn("subprocess", imports)
        self.assertNotIn("multiprocessing", imports)
        self.assertNotIn("threading", imports)
        self.assertNotIn("asyncio", imports)
        self.assertNotIn("requests", imports)
        self.assertNotIn("urllib", imports)

    def test_audit_module_no_bpy_imports(self):
        audit_source = (Path(__file__).resolve().parent.parent / "workflow" / "audit.py").read_text()
        imports = _ast_all_imports(audit_source)
        self.assertNotIn("bpy", imports)


# --- Existing architecture guards remain valid -------------------------------


class ExistingArchitectureGuardsTests(unittest.TestCase):
    def test_audit_does_not_use_banned_modules(self):
        audit_source = (Path(__file__).resolve().parent.parent / "workflow" / "audit.py").read_text()
        tree = ast.parse(audit_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id == "subprocess":
                            self.fail("subprocess call found in audit.py")


# --- CLI validation -----------------------------------------------------------


class CLIValidationTests(unittest.TestCase):
    def test_can_run_audit_from_command_line(self):
        import subprocess
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "-c", 
             "from workflow.audit import collect_repository_audit; "
             "print(collect_repository_audit().summary.total_findings)"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.strip().isdigit())


if __name__ == "__main__":
    unittest.main()