"""TOONFLOW-PHASE-035 — Blender Runtime Execution Boundary.

This module isolates external Blender process invocation behind an
explicit runtime boundary. The pure verification layer in
:mod:`workflow.verification` never directly imports subprocess.

The runtime boundary is responsible for:
- Safe Blender executable discovery
- Getting Blender version information
- Running the controlled Blender verification script via
  argument-list subprocess invocation only

Forbidden within this module (enforced by tests and architecture):
- shell=True
- shell command strings
- arbitrary command fragments
- arbitrary Python execution
- network access
- software installation/download
- telemetry

Public API
----------
- :func:`find_blender_executable` — locate Blender in the system
- :func:`get_blender_version` — query Blender version safely
- :func:`execute_blender_verification` — run verification script
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple


# --- Blender discovery -------------------------------------------------------


def find_blender_executable() -> Optional[Path]:
    """Find the Blender executable in the system.

    Returns:
        Path to Blender executable if found, None otherwise.
    """
    blender_env = os.environ.get("BLENDER_EXECUTABLE")
    if blender_env:
        path = Path(blender_env)
        if path.exists() and path.is_file():
            return path.resolve()

    system = sys.platform
    if system == "win32":
        common_paths = [
            Path("C:/Program Files/Blender Foundation/Blender/blender.exe"),
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Blender Foundation" / "Blender" / "blender.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            / "Blender Foundation" / "Blender" / "blender.exe",
        ]
    elif system == "darwin":
        common_paths = [
            Path("/Applications/Blender.app/Contents/MacOS/Blender"),
            Path("/Users/Shared/Blender/blender.app/Contents/MacOS/Blender"),
            Path(os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender")),
        ]
    else:
        common_paths = [
            Path("/usr/bin/blender"),
            Path("/usr/local/bin/blender"),
            Path(os.path.expanduser("~/bin/blender")),
            Path("/opt/blender/blender"),
        ]

    for path in common_paths:
        if path.exists() and path.is_file():
            return path.resolve()

    if "PATH" in os.environ:
        for path_dir in os.environ["PATH"].split(os.pathsep):
            path_dir = path_dir.strip('"')
            if not path_dir:
                continue
            blender_path = Path(path_dir) / ("blender.exe" if system == "win32" else "blender")
            if blender_path.exists() and blender_path.is_file():
                return blender_path.resolve()

    return None


# --- Blender version ---------------------------------------------------------


def get_blender_version(blender_path: Path) -> Optional[str]:
    """Get Blender version by running blender --version.

    Uses argument-list subprocess invocation only (no shell=True).

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
            lines = result.stdout.strip().split("\n")
            if lines:
                first_line = lines[0].strip()
                if first_line.startswith("Blender"):
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
        try:
            import toonflow_ai
            result["info"]["import_success"] = True
        except Exception as e:
            result["errors"].append({
                "type": "ImportError",
                "message": f"Failed to import toonflow_ai: {e}",
                "traceback": traceback.format_exc()
            })
            print(json.dumps(result))
            return

        try:
            import bpy
            result["info"]["bpy_available"] = True
        except ImportError as e:
            result["errors"].append({
                "type": "ImportError",
                "message": f"bpy not available: {e}",
                "traceback": traceback.format_exc()
            })
            print(json.dumps(result))
            return

        try:
            from toonflow_ai import registration
            result["info"]["registration_module_found"] = True
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
                "message": f"Failed to import registration module: {e}",
                "traceback": traceback.format_exc()
            })

        if (result["info"].get("register_function_exists") and
            result["info"].get("unregister_function_exists")):
            try:
                registration.register()
                result["info"]["registration_success"] = True
                try:
                    after_count = len(bpy.types.__dict__)
                    result["info"]["classes_registered"] = after_count
                except Exception:
                    pass
                try:
                    registration.unregister()
                    result["info"]["unregistration_success"] = True
                except Exception as e:
                    result["errors"].append({
                        "type": "RuntimeError",
                        "message": f"Unregistration failed: {e}",
                        "traceback": traceback.format_exc()
                    })
            except Exception as e:
                result["errors"].append({
                    "type": "RuntimeError",
                    "message": f"Registration failed: {e}",
                    "traceback": traceback.format_exc()
                })

        if not result["errors"]:
            result["success"] = True
            result["info"]["verification_passed"] = True

    except Exception as e:
        result["errors"].append({
            "type": "UnexpectedError",
            "message": f"Unexpected error during verification: {e}",
            "traceback": traceback.format_exc()
        })

    print(json.dumps(result))


if __name__ == "__main__":
    main()
'''


# --- Verification execution --------------------------------------------------


def execute_blender_verification(
    blender_executable: Path,
    timeout_seconds: int = 30,
) -> Tuple[bool, dict]:
    """Run the Blender verification script in a subprocess.

    Uses argument-list subprocess invocation only (no shell=True).

    Args:
        blender_executable: Path to the Blender executable.
        timeout_seconds: Timeout for the verification process.

    Returns:
        Tuple of (success, result_dict). success is True if Blender
        ran and produced valid JSON output.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive integer")

    project_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    python_path = str(project_root)
    if "PYTHONPATH" in env:
        python_path = f"{python_path}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = python_path

    cmd = [
        str(blender_executable),
        "--background",
        "--python-expr",
        f"""
import sys
import os
sys.path.insert(0, os.path.abspath(r"{project_root}"))
{_BLENDER_VERIFICATION_SCRIPT}
main()
""",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )

        try:
            output_lines = result.stdout.strip().split("\n")
            json_output = None
            for line in output_lines:
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    json_output = line
                    break

            if json_output is None:
                stderr_lines = result.stderr.strip().split("\n")
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
                    "returncode": result.returncode,
                }

            result_data = json.loads(json_output)
            return True, result_data

        except (json.JSONDecodeError, ValueError) as e:
            return False, {
                "error": f"Failed to parse JSON output from Blender: {e}",
                "stdout": result.stdout[:500],
                "stderr": result.stderr[:500],
                "returncode": result.returncode,
            }

    except subprocess.TimeoutExpired:
        return False, {
            "error": f"Blender verification timed out after {timeout_seconds} seconds",
            "timeout": timeout_seconds,
        }
    except Exception as e:
        return False, {
            "error": f"Failed to run Blender verification: {e}",
            "exception_type": type(e).__name__,
        }
