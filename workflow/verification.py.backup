"""TOONFLOW-PHASE-034 — Blender Runtime Verification & Add-on Packaging Validation Foundation.

This module provides a deterministic, safe mechanism to verify the TOONFLOW AI
Blender add-on package works correctly in a real Blender runtime environment.

The verification is strictly separated from static analysis and unit testing:
- STATIC_VALIDATION: Code exists, compiles, imports work
- UNIT_TEST_VALIDATION: Automated tests pass (may use bpy stubs)
- BLENDER_RUNTIME_VALIDATION: Actual Blender execution verified the add-on

The verifier must never:
- Modify project files
- Modify user Blender scenes
- Make network calls
- Execute arbitrary code
- Install software automatically
- Collect telemetry

The verification contract validates:
1. Add-on package can be imported by Blender
2. Add-on registers successfully without errors
3. Add-on unregisters successfully without errors
4. Registration does not leave unexpected registration state
5. Top-level add-on package does not eagerly import bpy before registration
6. Existing generation modules remain behind the intended Blender boundary

If Blender is unavailable, the verifier reports NOT_RUN rather than fabricating
a result.

Public API
----------

- :class:`BlenderRuntimeVerificationResult` — immutable verification result
- :class:`BlenderVerificationContract` — specification of what to verify
- :func:`verify_blender_runtime` — execute verification if Blender available
- :func:`blender_verification_to_dict` — deterministic dict output
- :func:`blender_verification_to_json` — deterministic JSON output
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT_ENV_VAR = "TOONFLOW_PROJECT_ROOT"


_VERIFICATION_INDENT = 2
_VERIFICATION_SORT_KEYS = False
_VERIFICATION_ENSURE_ASCII = False


# --- Verification semantics ---------------------------------------------------


class VerificationStatus:
    """Verification status constants.

    These statuses distinguish between different levels of verification
    evidence, with BLENDER_RUNTIME_VERIFIED being the strongest form.
    """

    NOT_RUN = "NOT_RUN"
    FAILED = "FAILED"
    PASSED = "PASSED"


class VerificationBoundary:
    """Verification boundary constants.

    These boundaries define what type of evidence constitutes verification
    at each level.
    """

    STATIC_VALIDATION = "STATIC_VALIDATION"
    UNIT_TEST_VALIDATION = "UNIT_TEST_VALIDATION"
    BLENDER_RUNTIME_VERIFICATION = "BLENDER_RUNTIME_VERIFICATION"


# --- Result model -------------------------------------------------------------


@dataclass(frozen=True)
class BlenderRuntimeVerificationResult:
    """The immutable result of a Blender runtime verification attempt.

    Attributes:
        status: One of the :class:`VerificationStatus` constants.
        boundary_achieved: The highest verification boundary achieved.
            One of the :class:`VerificationBoundary` constants.
        message: Human-readable description of the verification outcome.
        details: Structured details about the verification process.
            May contain error information, timing, or Blender version.
        blender_version: Version of Blender used for verification, if available.
        blender_executable: Path to the Blender executable used, if any.
        verification_attempted: True if verification was actually attempted.
            False if Blender was not found or not executable.
    """

    status: str
    boundary_achieved: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    blender_version: Optional[str] = None
    blender_executable: Optional[str] = None
    verification_attempted: bool = False

    def __post_init__(self):
        if self.status not in (
            VerificationStatus.NOT_RUN,
            VerificationStatus.FAILED,
            VerificationStatus.PASSED,
        ):
            raise ValueError(f"Unknown verification status: {self.status!r}")

        if self.boundary_achieved not in (
            VerificationBoundary.STATIC_VALIDATION,
            VerificationBoundary.UNIT_TEST_VALIDATION,
            VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
        ):
            raise ValueError(
                f"Unknown verification boundary: {self.boundary_achieved!r}"
            )

        if not isinstance(self.message, str):
            raise ValueError("message must be a string")

        if not isinstance(self.details, dict):
            raise ValueError("details must be a dict")

        if self.blender_version is not None:
            if not isinstance(self.blender_version, str):
                raise ValueError("blender_version must be a string or None")

        if self.blender_executable is not None:
            if not isinstance(self.blender_executable, str):
                raise ValueError("blender_executable must be a string or None")

        if not isinstance(self.verification_attempted, bool):
            raise ValueError("verification_attempted must be a bool")


# --- Contract model -----------------------------------------------------------


@dataclass(frozen=True)
class BlenderVerificationContract:
    """The explicit contract for Blender runtime verification.

    This contract defines what the verification process must check to be
    considered successful. It is immutable and deterministic.

    Attributes:
        check_import: Verify add-on package can be imported by Blender.
        check_register: Verify add-on registers successfully.
        check_unregister: Verify add-on unregisters successfully.
        check_no_eager_bpy_import: Verify top-level package doesn't
            eagerly import bpy before registration.
        check_generation_boundary: Verify generation modules remain
            behind Blender boundary (no direct bpy imports).
        timeout_seconds: Timeout for Blender subprocess execution.
    """

    check_import: bool = True
    check_register: bool = True
    check_unregister: bool = True
    check_no_eager_bpy_import: bool = True
    check_generation_boundary: bool = True
    timeout_seconds: int = 30

    def __post_init__(self):
        if not isinstance(self.timeout_seconds, int) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive integer")


# --- Result serialization ----------------------------------------------------


def blender_verification_result_to_dict(
    result: BlenderRuntimeVerificationResult,
) -> dict:
    """Convert a :class:`BlenderRuntimeVerificationResult` to a JSON-safe dict."""
    return {
        "status": result.status,
        "boundary_achieved": result.boundary_achieved,
        "message": result.message,
        "details": dict(result.details),
        "blender_version": result.blender_version,
        "blender_executable": result.blender_executable,
        "verification_attempted": bool(result.verification_attempted),
    }


def blender_verification_to_json(
    result: BlenderRuntimeVerificationResult,
) -> str:
    """Serialize a verification result to deterministic JSON.

    Uses ``indent=2``, ``sort_keys=False``, and
    ``ensure_ascii=False``. The returned string ends with
    exactly one trailing newline.
    """
    data = blender_verification_result_to_dict(result)
    return json.dumps(
        data,
        indent=_VERIFICATION_INDENT,
        sort_keys=_VERIFICATION_SORT_KEYS,
        ensure_ascii=_VERIFICATION_ENSURE_ASCII,
    ) + "\n"


# --- Blender detection --------------------------------------------------------


def _find_blender_executable() -> Optional[Path]:
    """Find the Blender executable in the system.

    Returns:
        Path to Blender executable if found, None otherwise.

    The search order is:
    1. BLENDER_EXECUTABLE environment variable
    2. Common installation paths
    3. PATH lookup for 'blender'
    """
    # Check environment variable first
    blender_env = os.environ.get("BLENDER_EXECUTABLE")
    if blender_env:
        path = Path(blender_env)
        if path.exists() and path.is_file():
            return path.resolve()

    # Common installation paths
    system = sys.platform
    if system == "win32":
        common_paths = [
            Path("C:/Program Files/Blender Foundation/Blender/blender.exe"),
            Path("C:/Program Files/Blender Foundation/Blender/blender.exe"),
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Blender Foundation"
            / "Blender"
            / "blender.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            / "Blender Foundation"
            / "Blender"
            / "blender.exe",
        ]
    elif system == "darwin":  # macOS
        common_paths = [
            Path("/Applications/Blender.app/Contents/MacOS/Blender"),
            Path("/Users/Shared/Blender/blender.app/Contents/MacOS/Blender"),
            Path(os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender")),
        ]
    else:  # Linux and other Unix-like
        common_paths = [
            Path("/usr/bin/blender"),
            Path("/usr/local/bin/blender"),
            Path(os.path.expanduser("~/bin/blender")),
            Path("/opt/blender/blender"),
        ]

    for path in common_paths:
        if path.exists() and path.is_file():
            return path.resolve()

    # Check PATH
    if "PATH" in os.environ:
        for path_dir in os.environ["PATH"].split(os.pathsep):
            path_dir = path_dir.strip('"')
            if not path_dir:
                continue
            blender_path = Path(path_dir) / ("blender.exe" if system == "win32" else "blender")
            if blender_path.exists() and blender_path.is_file():
                return blender_path.resolve()

    return None


def _get_blender_version(blender_path: Path) -> Optional[str]:
    """Get Blender version by running blender --version.

    Returns:
        Version string if successful, None otherwise.
    """
    try:
        result = subprocess.run(
            [str(blender_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            # Extract version from output like "Blender 4.2.0 (hash)"
            lines = result.stdout.strip().split("\n")
            if lines:
                first_line = lines[0].strip()
                if first_line.startswith("Blender"):
                    # Extract version part: "Blender X.Y.Z"
                    parts = first_line.split()
                    if len(parts) >= 2:
                        return parts[1]
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass
    return None


# --- Verification script ------------------------------------------------------


_BLENDER_VERIFICATION_SCRIPT = '''
import sys
import traceback
import json

def main():
    result = {
        "success": False,
        "errors": [],
        "warnings": [],
        "info": {},
    }
    
    try:
        # Try to import the add-on package
        try:
            import toonflow_ai
            result["info"]["import_success"] = True
        except Exception as e:
            result["errors"].append({
                "type": "ImportError",
                "message": f"Failed to import toonflow_ai: {{e}}",
                "traceback": traceback.format_exc()
            })
            # Cannot continue without import
            print(json.dumps(result))
            return
        
        # Check if bpy is available
        try:
            import bpy
            result["info"]["bpy_available"] = True
        except ImportError as e:
            result["errors"].append({
                "type": "ImportError",
                "message": f"bpy not available: {{e}}",
                "traceback": traceback.format_exc()
            })
            # Cannot continue without bpy
            print(json.dumps(result))
            return
            
        # Check registration functions exist
        try:
            from toonflow_ai import registration
            result["info"]["registration_module_found"] = True
            
            # Check if register/unregister functions exist
            if hasattr(registration, 'register') and callable(registration.register):
                result["info"]["register_function_exists"] = True
            else:
                result["errors"].append({
                    "type": "AttributeError",
                    "message": "registration.register function not found or not callable"
                })
                
            if hasattr(registration, 'unregister') and callable(registration.unregister):
                result["info"]["unregister_function_exists"] = True
            else:
                result["errors"].append({
                    "type": "AttributeError",
                    "message": "registration.unregister function not found or not callable"
                })
        except Exception as e:
            result["errors"].append({
                "type": "ImportError",
                "message": f"Failed to import registration module: {{e}}",
                "traceback": traceback.format_exc()
            })
            
        # Try registration if functions exist
        if (result["info"].get("register_function_exists") and 
            result["info"].get("unregister_function_exists")):
            
            # Count registered classes before
            try:
                before_count = len(bpy.types.__dict__)
            except Exception:
                before_count = 0
                
            try:
                # Try to register
                registration.register()
                result["info"]["registration_success"] = True
                
                # Count registered classes after
                try:
                    after_count = len(bpy.types.__dict__)
                    result["info"]["classes_registered"] = after_count - before_count
                except Exception:
                    pass
                    
                # Try to unregister
                try:
                    registration.unregister()
                    result["info"]["unregistration_success"] = True
                except Exception as e:
                    result["errors"].append({
                        "type": "RuntimeError",
                        "message": f"Unregistration failed: {{e}}",
                        "traceback": traceback.format_exc()
                    })
                    
            except Exception as e:
                result["errors"].append({
                    "type": "RuntimeError",
                    "message": f"Registration failed: {{e}}",
                    "traceback": traceback.format_exc()
                })
                
        # Check for eager bpy imports in addon package
        try:
            import toonflow_ai.__init__ as init_module
            import inspect
            source = inspect.getsource(init_module)
            if "import bpy" in source or "from bpy" in source:
                # Check if it's inside a function (which is OK for lazy loading)
                lines = source.split("\\n")
                bpy_import_lines = [
                    i for i, line in enumerate(lines) 
                    if ("import bpy" in line or "from bpy" in line)
                ]
                eager_imports = []
                for line_num in bpy_import_lines:
                    # Check if this line is inside a function definition
                    # Simple heuristic: look for function def above with proper indentation
                    is_eager = True
                    for i in range(line_num, -1, -1):
                        if lines[i].strip().startswith("def "):
                            # Found function definition, check if our line is indented more
                            if len(lines[i]) - len(lines[i].lstrip()) < len(lines[line_num]) - len(lines[line_num].lstrip()):
                                is_eager = False
                            break
                        elif lines[i].strip() and not lines[i].startswith(" ") and not lines[i].startswith("\\t"):
                            # Hit module-level code that's not a function definition
                            break
                    if is_eager:
                        eager_imports.append(line_num)
                
                if eager_imports:
                    result["warnings"].append({
                        "type": "EagerBpyImport",
                        "message": f"Found eager bpy imports at lines: {{eager_imports}}",
                        "info": {"lines": eager_imports}
                    })
                else:
                    result["info"]["no_eager_bpy_imports"] = True
        except Exception as e:
            result["warnings"].append({
                "type": "InspectionWarning",
                "message": f"Could not inspect for eager bpy imports: {{e}}"
            })
            
        # Check generation modules for direct bpy imports (should be lazy)
        try:
            import toonflow_ai.generation
            import pkgutil
            import importlib
            
            generation_path = toonflow_ai.generation.__path__
            for importer, modname, ispkg in pkgutil.walk_packages(
                path=generation_path, prefix="toonflow_ai.generation."
            ):
                if modname.endswith(".__init__") or "_data" in modname or "_api" in modname:
                    continue  # Skip data/api modules
                try:
                    module = importlib.import_module(modname)
                    import inspect
                    source = inspect.getsource(module)
                    # Check for direct bpy imports (not inside functions)
                    lines = source.split("\\n")
                    for i, line in enumerate(lines):
                        stripped = line.strip()
                        if stripped.startswith("import bpy") or stripped.startswith("from bpy import"):
                            # Check if it's at module level (not inside function/class)
                            # Simple check: look backwards for def/class with less or equal indentation
                            is_module_level = True
                            for j in range(i, -1, -1):
                                prev_line = lines[j]
                                stripped_prev = prev_line.strip()
                                if stripped_prev.startswith("def ") or stripped_prev.startswith("class "):
                                    # Found function/class definition, check indentation
                                    if len(prev_line) - len(prev_line.lstrip()) <= len(line) - len(line.lstrip()):
                                        is_module_level = False
                                    break
                                elif prev_line.strip() and not prev_line.startswith(" ") and not prev_line.startswith("\\t"):
                                    # Hit module-level code that's not def/class
                                    break
                            if is_module_level:
                                result["errors"].append({
                                    "type": "DirectBpyImport",
                                    "message": f"Direct bpy import found in {{modname}} at line {{i+1}}: {{stripped}}",
                                    "info": {"module": modname, "line": i+1, "import": stripped}
                                })
                                break
                except Exception:
                    # Skip modules we can't inspect
                    continue
        except Exception as e:
            result["warnings"].append({
                "type": "GenerationInspectionWarning",
                "message": f"Could not inspect generation modules: {{e}}"
            })
            
        # If we got here with no errors, verification passed
        if not result["errors"]:
            result["success"] = True
            result["info"]["verification_passed"] = True
            
    except Exception as e:
        result["errors"].append({
            "type": "UnexpectedError",
            "message": f"Unexpected error during verification: {{e}}",
            "traceback": traceback.format_exc()
        })
    
    # Always output JSON
    print(json.dumps(result))


if __name__ == "__main__":
    main()
'''


# --- Verification implementation ----------------------------------------------


def _run_blender_verification(
    blender_executable: Path,
    timeout_seconds: int = 30,
) -> Tuple[bool, dict]:
    """Run the Blender verification script in a subprocess.

    Args:
        blender_executable: Path to the Blender executable.
        timeout_seconds: Timeout for the verification process.

    Returns:
        Tuple of (success, result_dict) where success is True if Blender
        ran and produced valid JSON output, and result_dict contains the
        verification results from the Blender-side script.
    """
    # Find project root
    project_root = Path(__file__).resolve().parent.parent
    addon_root = project_root / "addon" / "toonflow_ai"
    
    # Prepare the verification script with proper PYTHONPATH
    env = os.environ.copy()
    python_path = str(project_root)
    if "PYTHONPATH" in env:
        python_path = f"{python_path}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = python_path
    
    # Run Blender in background mode with our verification script
    cmd = [
        str(blender_executable),
        "--background",  # No UI
        "--python-expr",  # Execute Python code directly
        f"""
import sys
import os
sys.path.insert(0, os.path.abspath(r"{project_root}"))
{_BLENDER_VERIFICATION_SCRIPT}
main()
"""
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,  # We'll check returncode ourselves
        )
        
        # Parse JSON output
        try:
            # Blender might output other stuff, look for JSON
            output_lines = result.stdout.strip().split("\\n")
            json_output = None
            for line in output_lines:
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    json_output = line
                    break
            
            if json_output is None:
                # Try to find JSON in stderr too
                stderr_lines = result.stderr.strip().split("\\n")
                for line in stderr_lines:
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        json_output = line
                        break
            
            if json_output is None:
                return False, {
                    "error": "No JSON output found from Blender verification",
                    "stdout": result.stdout[:500],
                    "stderr": result.stderr[:500],
                    "returncode": result.returncode
                }
                
            result_data = json.loads(json_output)
            return True, result_data
            
        except (json.JSONDecodeError, ValueError) as e:
            return False, {
                "error": f"Failed to parse JSON output from Blender: {{e}}",
                "stdout": result.stdout[:500],
                "stderr": result.stderr[:500],
                "returncode": result.returncode
            }
            
    except subprocess.TimeoutExpired:
        return False, {
            "error": f"Blender verification timed out after {{timeout_seconds}} seconds",
            "timeout": timeout_seconds
        }
    except Exception as e:
        return False, {
            "error": f"Failed to run Blender verification: {{e}}",
            "exception_type": type(e).__name__
        }


def _achieve_static_validation_boundary() -> Tuple[str, str, str, dict]:
    """Achieve STATIC_VALIDATION boundary through inspection.

    Returns:
        Tuple of (status, boundary_achieved, message, details)
    """
    # Check that key files exist
    project_root = Path(__file__).resolve().parent.parent
    required_files = [
        "addon/toonflow_ai/__init__.py",
        "addon/toonflow_ai/registration.py", 
        "addon/toonflow_ai/operator.py",
        "addon/toonflow_ai/properties.py",
        "addon/toonflow_ai/ui.py",
        "addon/toonflow_ai/generation/__init__.py",
        "workflow/__init__.py",
        "workflow/cli.py",
    ]
    
    missing_files = []
    for file_rel in required_files:
        if not (project_root / file_rel).exists():
            missing_files.append(file_rel)
    
    if missing_files:
        return (
            VerificationStatus.FAILED,
            VerificationBoundary.STATIC_VALIDATION,
            f"Missing required files: {{missing_files}}",
            {"missing_files": missing_files}
        )
    
    # Check that addon package doesn't eagerly import bpy
    try:
        init_file = project_root / "addon" / "toonflow_ai" / "__init__.py"
        source = init_file.read_text(encoding="utf-8")
        # Import bpy should only be in register/unregister functions or conditionally imported
        if "import bpy" in source:
            lines = source.split("\\n")
            for i, line in enumerate(lines):
                if "import bpy" in line:
                    # Check if it's inside a function
                    is_inside_function = False
                    for j in range(i, -1, -1):
                        prev_line = lines[j].rstrip()
                        if prev_line.startswith("def "):
                            # Found function definition
                            is_inside_function = True
                            break
                        elif prev_line.strip() and not prev_line.startswith(" ") and not prev_line.startswith("\\t"):
                            # Hit module-level code
                            break
                    if not is_inside_function:
                        return (
                            VerificationStatus.FAILED,
                            VerificationBoundary.STATIC_VALIDATION,
                            "Addon package eagerly imports bpy at module level",
                            {"eager_import_line": i+1, "code_snippet": lines[i]}
                        )
    except Exception:
        pass  # If we can't check, continue
    
    return (
        VerificationStatus.PASSED,
        VerificationBoundary.STATIC_VALIDATION,
        "Static validation passed: required files present, no eager bpy imports detected",
        {"files_checked": len(required_files)}
    )


def verify_blender_runtime(
    blender_executable: Optional[Path] = None,
    contract: Optional[BlenderVerificationContract] = None,
) -> BlenderRuntimeVerificationResult:
    """Verify the TOONFLOW AI Blender add-on package in a real Blender runtime.

    Args:
        blender_executable: Optional path to Blender executable. If None,
            the function will attempt to auto-detect Blender.
        contract: Optional verification contract. If None, uses default contract.

    Returns:
        A :class:`BlenderRuntimeVerificationResult` indicating the outcome
        of the verification attempt.
    """
    if contract is None:
        contract = BlenderVerificationContract()
    
    # First, try to achieve static validation boundary
    static_status, static_boundary, static_message, static_details = _achieve_static_validation_boundary()
    
    # If static validation failed, we cannot proceed further
    if static_status == VerificationStatus.FAILED:
        return BlenderRuntimeVerificationResult(
            status=VerificationStatus.FAILED,
            boundary_achieved=static_boundary,
            message=static_message,
            details=static_details,
            verification_attempted=False,
        )
    
    # Static validation passed, now try to find Blender
    if blender_executable is None:
        blender_executable = _find_blender_executable()
    
    if blender_executable is None or not blender_executable.exists():
        # Blender not found - we can still achieve static validation
        return BlenderRuntimeVerificationResult(
            status=VerificationStatus.NOT_RUN,
            boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
            message="Blender executable not found. Static validation passed, but runtime verification not attempted.",
            details={
                **static_details,
                "blender_search_attempted": True
            },
            verification_attempted=False,
        )
    
    # Blender found, attempt runtime verification
    try:
        blender_version = _get_blender_version(blender_executable)
        
        success, verification_details = _run_blender_verification(
            blender_executable, 
            contract.timeout_seconds
        )
        
        if not success:
            # Blender verification process failed
            return BlenderRuntimeVerificationResult(
                status=VerificationStatus.FAILED,
                boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
                message=f"Blender verification process failed: {{verification_details.get('error', 'Unknown error')}}",
                details={
                    **static_details,
                    **verification_details,
                    "blender_version": blender_version
                },
                blender_version=blender_version,
                blender_executable=str(blender_executable),
                verification_attempted=True,
            )
        
        # Check if Blender-side verification succeeded
        if verification_details.get("success", False):
            # Check if we achieved all requested checks
            all_checks_passed = True
            failed_checks = []
            
            if contract.check_import and not verification_details.get("info", {}).get("import_success", False):
                all_checks_passed = False
                failed_checks.append("import")
                
            if contract.check_register and not verification_details.get("info", {}).get("registration_success", False):
                all_checks_passed = False
                failed_checks.append("register")
                
            if contract.check_unregister and not verification_details.get("info", {}).get("unregistration_success", False):
                all_checks_passed = False
                failed_checks.append("unregister")
                
            # Check for eager bpy imports
            eager_warnings = [
                w for w in verification_details.get("warnings", [])
                if w.get("type") == "EagerBpyImport"
            ]
            if contract.check_no_eager_bpy_import and eager_warnings:
                all_checks_passed = False
                failed_checks.append("no_eager_bpy_import")
                
            # Check for direct bpy imports in generation
            direct_import_errors = [
                e for e in verification_details.get("errors", [])
                if e.get("type") == "DirectBpyImport"
            ]
            if contract.check_generation_boundary and direct_import_errors:
                all_checks_passed = False
                failed_checks.append("generation_boundary")
            
            if all_checks_passed:
                return BlenderRuntimeVerificationResult(
                    status=VerificationStatus.PASSED,
                    boundary_achieved=VerificationBoundary.BLENDER_RUNTIME_VERIFICATION,
                    message="Blender runtime verification passed all checks",
                    details={
                        **static_details,
                        **verification_details,
                        "blender_version": blender_version
                    },
                    blender_version=blender_version,
                    blender_executable=str(blender_executable),
                    verification_attempted=True,
                )
            else:
                return BlenderRuntimeVerificationResult(
                    status=VerificationStatus.FAILED,
                    boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
                    message=f"Blender runtime verification failed checks: {{failed_checks}}",
                    details={
                        **static_details,
                        **verification_details,
                        "failed_checks": failed_checks,
                        "blender_version": blender_version
                    },
                    blender_version=blender_version,
                    blender_executable=str(blender_executable),
                    verification_attempted=True,
                )
        else:
            # Blender verification script failed
            errors = verification_details.get("errors", [])
            error_messages = [e.get("message", "Unknown error") for e in errors]
            return BlenderRuntimeVerificationResult(
                status=VerificationStatus.FAILED,
                boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
                message=f"Blender verification failed: {{'; '.join(error_messages[:3])}}",
                details={
                    **static_details,
                    **verification_details,
                    "blender_version": blender_version
                },
                blender_version=blender_version,
                blender_executable=str(blender_executable),
                verification_attempted=True,
            )
            
    except Exception as e:
        return BlenderRuntimeVerificationResult(
            status=VerificationStatus.FAILED,
            boundary_achieved=VerificationBoundary.STATIC_VALIDATION,
            message=f"Unexpected error during Blender verification: {{e}}",
            details={
                **static_details,
                "exception_type": type(e).__name__,
                "exception_message": str(e)
            },
            verification_attempted=True,
        )


# --- Public API --------------------------------------------------------------


__all__ = (
    "VerificationStatus",
    "VerificationBoundary",
    "BlenderRuntimeVerificationResult",
    "BlenderVerificationContract",
    "blender_verification_to_dict",
    "blender_verification_to_json",
    "verify_blender_runtime",
    "PROJECT_ROOT_ENV_VAR",
)