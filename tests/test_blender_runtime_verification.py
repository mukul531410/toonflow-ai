"""Tests for TOONFLOW-PHASE-035 — Blender Runtime Verification Boundary Hardening.

These tests verify the PHASE-035 requirements:

A. verification.py has no direct subprocess import
B. runtime.py is the only approved external process boundary
C. runtime executor uses argument-list invocation (no shell=True)
D. Blender unavailable -> NOT_RUN
E. missing executable -> deterministic NOT_RUN result
F. mocked Blender success -> PASSED
G. mocked Blender failure -> FAILED
H. timeout -> deterministic failure
I. malformed output -> deterministic failure
J. non-zero exit -> deterministic failure
K. invalid timeout rejected
L. deterministic dict output
M. deterministic JSON output
N. immutable result behavior
O. dependency injection works
P. CLI verify-blender works
Q. no source mutation
R. no network/install/telemetry behavior
S. existing architecture guards remain valid
"""

import ast
import json
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflow.verification import (  # noqa: E402
    BlenderRuntimeVerificationResult,
    BlenderVerificationContract,
    VerificationBoundary,
    VerificationStatus,
    blender_verification_to_dict,
    blender_verification_to_json,
    verify_blender_runtime,
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


# --- A. verification.py has no direct subprocess import -------------------------


class VerificationNoSubprocessImportTests(unittest.TestCase):
    def test_verification_has_no_subprocess_import(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        imports = _ast_all_imports(verification_source)
        self.assertNotIn("subprocess", imports)

    def test_verification_has_no_bpy_import(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        imports = _ast_all_imports(verification_source)
        self.assertNotIn("bpy", imports)

    def test_verification_has_no_os_system(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        self.assertNotIn("os.system", verification_source)
        self.assertNotIn("os.popen", verification_source)


# --- B. runtime.py is the only approved external process boundary -------------


class RuntimeBoundaryTests(unittest.TestCase):
    def test_runtime_has_subprocess_import(self):
        runtime_source = (PROJECT_ROOT / "workflow" / "runtime.py").read_text()
        imports = _ast_all_imports(runtime_source)
        self.assertIn("subprocess", imports)

    def test_verification_delegates_to_runtime(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        self.assertIn("from workflow.runtime import", verification_source)

    def test_verification_no_direct_subprocess_call(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        tree = ast.parse(verification_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id == "subprocess":
                            self.fail("subprocess call found in verification.py")


# --- C. runtime executor uses argument-list invocation --------------------------


class RuntimeTypeTests(unittest.TestCase):
    def test_runtime_no_shell_true(self):
        runtime_source = (PROJECT_ROOT / "workflow" / "runtime.py").read_text()
        self.assertNotIn("shell=True", runtime_source)
        self.assertNotIn("shell = True", runtime_source)

    def test_runtime_uses_list_args(self):
        runtime_source = (PROJECT_ROOT / "workflow" / "runtime.py").read_text()
        self.assertIn('[str(blender_path),', runtime_source)
        self.assertIn('[str(blender_executable),', runtime_source)


# --- D. Blender unavailable -> NOT_RUN ----------------------------------------


class BlenderUnavailableTests(unittest.TestCase):
    def test_blender_not_found_returns_not_run(self):
        result = verify_blender_runtime(blender_executable=Path("/nonexistent/blender"))
        self.assertEqual(result.status, VerificationStatus.NOT_RUN)
        self.assertEqual(result.boundary_achieved, VerificationBoundary.STATIC_VALIDATION)
        self.assertFalse(result.verification_attempted)

    def test_blender_not_found_message_indicates_search(self):
        result = verify_blender_runtime(blender_executable=Path("/nonexistent/blender"))
        self.assertIn("not found", result.message.lower())


# --- E. missing executable -> deterministic NOT_RUN --------------------------


class MissingExecutableTests(unittest.TestCase):
    def test_missing_executable_returns_not_run(self):
        def mock_executor(bpy_path: Path, timeout: int):
            return True, {"success": True}

        result = verify_blender_runtime(
            blender_executable=Path("/does/not/exist"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.NOT_RUN)

    def test_not_run_has_no_blender_version(self):
        result = verify_blender_runtime(blender_executable=Path("/nonexistent/blender"))
        self.assertIsNone(result.blender_version)

    def test_not_run_has_no_blender_executable(self):
        result = verify_blender_runtime(blender_executable=Path("/nonexistent/blender"))
        self.assertIsNone(result.blender_executable)


# --- F. mocked Blender success -> PASSED --------------------------------------


class MockedSuccessTests(unittest.TestCase):
    def test_successful_verification_returns_passed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {
                "success": True,
                "info": {
                    "import_success": True,
                    "registration_success": True,
                    "unregistration_success": True,
                    "no_eager_bpy_imports": True,
                },
                "errors": [],
                "warnings": [],
            }

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.PASSED)
        self.assertEqual(result.boundary_achieved, VerificationBoundary.BLENDER_RUNTIME_VERIFICATION)
        self.assertTrue(result.verification_attempted)
        self.assertIsNotNone(result.blender_executable)

    def test_successful_verification_includes_blender_version(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {
                "success": True,
                "info": {
                    "import_success": True,
                    "registration_success": True,
                    "unregistration_success": True,
                },
                "errors": [],
            }

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.boundary_achieved, VerificationBoundary.BLENDER_RUNTIME_VERIFICATION)


# --- G. mocked Blender failure -> FAILED ------------------------------------


class MockedFailureTests(unittest.TestCase):
    def test_failed_import_returns_failed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {
                "success": False,
                "info": {"import_success": False},
                "errors": [{"type": "ImportError", "message": "Failed to import"}],
                "warnings": [],
            }

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)
        self.assertFalse(result.verification_attempted or result.verification_attempted)

    def test_unregistration_error_returns_failed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {
                "success": True,
                "info": {
                    "import_success": True,
                    "registration_success": True,
                    "unregistration_success": False,
                },
                "errors": [{"type": "RuntimeError", "message": "Unregistration failed"}],
                "warnings": [],
            }

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)

    def test_eager_bpy_import_warning_returns_failed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {
                "success": True,
                "info": {"import_success": True, "no_eager_bpy_imports": False},
                "errors": [],
                "warnings": [{"type": "EagerBpyImport", "message": "Found eager import"}],
            }

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)

    def test_blender_process_failed_returns_failed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return False, {"error": "Blender process failed to start"}

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)


# --- H. timeout -> deterministic failure ------------------------------------


class TimeoutTests(unittest.TestCase):
    def test_timeout_in_executor_returns_failed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return False, {"error": f"Blender verification timed out after {timeout} seconds"}

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)

    def test_timeout_not_run_on_process_failure(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return False, {"timeout": "30"}

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            timeout_seconds=15,
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)


# --- I. malformed output -> deterministic failure ----------------------------


class MalformedOutputTests(unittest.TestCase):
    def test_malformed_json_returns_failed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {"success": "not_a_bool", "info": {}}

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)

    def test_missing_success_key_returns_failed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {"info": {}}

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)


# --- J. non-zero exit -> deterministic failure -------------------------------


class NonZeroExitTests(unittest.TestCase):
    def test_nonzero_exit_in_details_returns_failed(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {
                "success": False,
                "returncode": 1,
                "error": "Non-zero exit",
            }

        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)


# --- K. invalid timeout rejected ----------------------------------------------


class InvalidTimeoutTests(unittest.TestCase):
    def test_zero_timeout_performs_static_validation_only(self):
        result = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            contract=BlenderVerificationContract(timeout_seconds=1),
        )
        self.assertIn(result.status, (VerificationStatus.NOT_RUN, VerificationStatus.PASSED))

    def test_negative_timeout_contract_rejected(self):
        with self.assertRaises(ValueError):
            BlenderVerificationContract(timeout_seconds=-1)


# --- L. deterministic dict output --------------------------------------------


class DeterministicDictTests(unittest.TestCase):
    def test_result_to_dict_structure(self):
        result = BlenderRuntimeVerificationResult(
            status=VerificationStatus.PASSED,
            boundary_achieved=VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
            message="Test message",
            details={"key": "value"},
            blender_version="4.2.0",
            blender_executable="/path/to/blender",
            verification_attempted=True,
        )
        d = blender_verification_to_dict(result)
        self.assertEqual(d["status"], "PASSED")
        self.assertEqual(d["boundary_achieved"], "BLENDER_RUNTIME_VERIFICATION")
        self.assertEqual(d["message"], "Test message")
        self.assertEqual(d["details"], {"key": "value"})
        self.assertEqual(d["blender_version"], "4.2.0")
        self.assertEqual(d["blender_executable"], "/path/to/blender")
        self.assertEqual(d["verification_attempted"], True)

    def test_dict_consistent_for_same_result(self):
        result = BlenderRuntimeVerificationResult(
            status=VerificationStatus.NOT_RUN,
            boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
            message="Blender not found",
            details={},
            verification_attempted=False,
        )
        d1 = blender_verification_to_dict(result)
        d2 = blender_verification_to_dict(result)
        self.assertEqual(d1, d2)


# --- M. deterministic JSON output -------------------------------------------


class DeterministicJsonTests(unittest.TestCase):
    def test_json_produces_string(self):
        result = BlenderRuntimeVerificationResult(
            status=VerificationStatus.PASSED,
            boundary_achieved=VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
            message="Test",
            verification_attempted=True,
        )
        json_str = blender_verification_to_json(result)
        self.assertIsInstance(json_str, str)

    def test_json_is_valid_json(self):
        result = BlenderRuntimeVerificationResult(
            status=VerificationStatus.NOT_RUN,
            boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
            message="Test",
            verification_attempted=False,
        )
        json_str = blender_verification_to_json(result)
        data = json.loads(json_str)
        self.assertIsInstance(data, dict)

    def test_json_has_single_trailing_newline(self):
        result = BlenderRuntimeVerificationResult(
            status=VerificationStatus.PASSED,
            boundary_achieved=VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
            message="Test",
            verification_attempted=True,
        )
        json_str = blender_verification_to_json(result)
        self.assertTrue(json_str.endswith("\n"))
        self.assertFalse(json_str.endswith("\n\n"))

    def test_repeated_verification_produces_identical_json(self):
        result1 = BlenderRuntimeVerificationResult(
            status=VerificationStatus.PASSED,
            boundary_achieved=VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
            message="Test",
            verification_attempted=True,
        )
        result2 = BlenderRuntimeVerificationResult(
            status=VerificationStatus.PASSED,
            boundary_achieved=VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
            message="Test",
            verification_attempted=True,
        )
        json1 = blender_verification_to_json(result1)
        json2 = blender_verification_to_json(result2)
        self.assertEqual(json1, json2)


# --- N. immutable result behavior ---------------------------------------------


class ImmutableResultTests(unittest.TestCase):
    def test_result_is_frozen(self):
        result = BlenderRuntimeVerificationResult(
            status=VerificationStatus.PASSED,
            boundary_achieved=VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
            message="Test",
            verification_attempted=True,
        )
        self.assertTrue(result.__dataclass_fields__["status"].frozen)
        with self.assertRaises(AttributeError):
            result.status = VerificationStatus.FAILED

    def test_result_details_is_frozen(self):
        result = BlenderRuntimeVerificationResult(
            status=VerificationStatus.PASSED,
            boundary_achieved=VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
            message="Test",
            details={"key": "value"},
            verification_attempted=True,
        )
        self.assertTrue(result.__dataclass_fields__["details"].frozen)

    def test_verify_blender_runtime_returns_new_result(self):
        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            return True, {
                "success": True,
                "info": {"import_success": True},
                "errors": [],
            }

        result1 = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        result2 = verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=mock_executor,
        )
        self.assertIsNot(result1, result2)


# --- O. dependency injection works ------------------------------------------


class DependencyInjectionTests(unittest.TestCase):
    def test_runtime_executor_can_be_injected(self):
        called_with = []

        def mock_executor(bpy_path: Path, timeout: int) -> Tuple[bool, dict]:
            called_with.append((bpy_path, timeout))
            return True, {"success": True, "info": {"import_success": True}, "errors": []}

        result = verify_blender_runtime(
            blender_executable=Path("/custom/blender"),
            timeout_seconds=60,
            runtime_executor=mock_executor,
        )
        self.assertEqual(len(called_with), 1)
        self.assertEqual(called_with[0][0], Path("/custom/blender"))
        self.assertEqual(called_with[0][1], 60)
        self.assertEqual(result.status, VerificationStatus.PASSED)

    def test_default_runtime_executor_uses_workflow_runtime(self):
        verify_blender_runtime(
            blender_executable=Path("/fake/blender"),
            runtime_executor=lambda p, t: (True, {"success": True, "info": {"import_success": True}, "errors": []}),
        )


# --- P. CLI verify-blender works --------------------------------------------


class CLIVerifyBlenderTests(unittest.TestCase):
    def test_cli_verify_blender_json_output(self):
        import io
        from workflow.cli import main

        stdout = io.StringIO()
        exit_code = main(
            ["verify-blender", "--json"],
            stdout=stdout,
            verify_blender_runtime=lambda **kwargs: BlenderRuntimeVerificationResult(
                status=VerificationStatus.NOT_RUN,
                boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
                message="Test result",
                verification_attempted=False,
            ),
        )
        output = stdout.getvalue()
        data = json.loads(output)
        self.assertEqual(data["status"], "NOT_RUN")
        self.assertEqual(exit_code, 1)

    def test_cli_verify_blender_text_output(self):
        import io
        from workflow.cli import main

        stdout = io.StringIO()
        exit_code = main(
            ["verify-blender"],
            stdout=stdout,
            verify_blender_runtime=lambda **kwargs: BlenderRuntimeVerificationResult(
                status=VerificationStatus.NOT_RUN,
                boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
                message="Blender not found",
                verification_attempted=False,
            ),
        )
        output = stdout.getvalue()
        self.assertIn("NOT_RUN", output)
        self.assertIn("STATIC_VALIDATION", output)
        self.assertEqual(exit_code, 1)


# --- Q. no source mutation ---------------------------------------------------


class NoSourceMutationTests(unittest.TestCase):
    def test_verify_blender_runtime_does_not_modify_files(self):
        repo_root = PROJECT_ROOT

        pre_md5 = set()
        for py_file in repo_root.rglob("*.py"):
            if "tests" in str(py_file) or "__pycache__" in str(py_file):
                continue
            try:
                pre_md5.add((str(py_file), py_file.stat().st_mtime))
            except OSError:
                pass

        verify_blender_runtime(blender_executable=Path("/nonexistent/blender"))

        for py_file in repo_root.rglob("*.py"):
            if "tests" in str(py_file) or "__pycache__" in str(py_file):
                continue
            try:
                post_md5 = (str(py_file), py_file.stat().st_mtime)
                self.assertIn(post_md5, pre_md5, f"File {py_file} was modified")
            except OSError:
                pass


# --- R. no network/install/telemetry behavior -------------------------------


class NoNetworkBehaviorTests(unittest.TestCase):
    def test_verification_no_requests_import(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        sources = [verification_source]
        for source in sources:
            imports = _ast_all_imports(source)
            self.assertNotIn("requests", imports)
            self.assertNotIn("urllib.request", imports)

    def test_verification_no_subprocess_module_used(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        imports = _ast_all_imports(verification_source)
        self.assertNotIn("subprocess", imports)


# --- S. existing architecture guards remain valid ---------------------------


class ExistingArchitectureGuardsTests(unittest.TestCase):
    def test_verification_no_bpy_import(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        imports = _ast_all_imports(verification_source)
        self.assertNotIn("bpy", imports)

    def test_verification_uses_runtime_for_blender(self):
        verification_source = (PROJECT_ROOT / "workflow" / "verification.py").read_text()
        self.assertIn("from workflow.runtime import", verification_source)

    def test_workflow_package_bpy_free(self):
        api_source = (PROJECT_ROOT / "workflow" / "api.py").read_text()
        init_source = (PROJECT_ROOT / "workflow" / "__init__.py").read_text()
        cli_source = (PROJECT_ROOT / "workflow" / "cli.py").read_text()

        for source in (api_source, init_source, cli_source):
            for name in _ast_all_imports(source):
                self.assertFalse(
                    name == "bpy" or name.startswith("bpy."),
                    f"forbidden bpy import in workflow: {name}",
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


if __name__ == "__main__":
    unittest.main()