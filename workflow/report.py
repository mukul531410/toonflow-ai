"""TOONFLOW-PHASE-021 — Project Report & CI Artifacts.

This module is a thin, pure-Python serialization layer for batch
execution reports. It consumes :class:`workflow.batch.BatchProjectResult`
values (or equivalent structured inputs) and produces deterministic
machine-readable artifacts suitable for CI pipelines.

The report layer is:

- pure Python (standard library only)
- deterministic (no timestamps, UUIDs, environment metadata)
- Blender-free (``bpy`` is never imported)
- AI-free (no Ollama, no AI planning)
- network-free (no HTTP, no urllib, no requests)
- orchestration-only (it does not discover, load, replay, or render)

It does NOT duplicate:

- project discovery (owned by :mod:`workflow.batch`)
- project loading (owned by :func:`workflow.load_project`)
- schema migration (owned by :mod:`workflow.project_migrations`)
- batch execution (owned by :mod:`workflow.batch`)
- rendering logic (owned by :mod:`toonflow_ai.generation.*`)

Public API
----------

The single programmatic entry point for persistence is
:func:`save_report`. The single programmatic entry point for
building a :class:`BatchReport` from batch results is
:func:`batch_result_to_report`.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple, Union


# --- Errors ----------------------------------------------------------------


class ReportInputError(ValueError):
    """The report layer inputs are invalid.

    Attributes:
        parameter: The name of the offending parameter.
        value: The offending value (preserved as-given).
    """

    def __init__(self, parameter, value):
        self.parameter = parameter
        self.value = value
        super().__init__(
            f"Report input {parameter!r} is invalid: got {value!r}."
        )


# --- Project entry ---------------------------------------------------------


@dataclass(frozen=True)
class BatchProjectReportEntry:
    """A single per-project report entry.

    Attributes:
        path: The path to the project file as supplied to the
            batch layer. The report preserves the path verbatim;
            it is not resolved or rewritten.
        success: ``True`` if the project loaded (and, for ``run``
            mode, replayed) successfully.
        error_type: ``None`` on success, otherwise the exception
            class name as a string.
        error_message: ``None`` on success, otherwise the
            exception message as a string.
        output_paths: Tuple of resolved output paths, in
            execution order, for successful ``run`` mode. Empty
            tuple for ``validate`` / ``show`` modes and for
            failures.
    """

    path: str
    success: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    output_paths: Tuple[str, ...] = ()
    attempts: int = 1
    retried: bool = False

    def __post_init__(self):
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
            raise ReportInputError("attempts", self.attempts)
        if self.attempts < 1:
            raise ReportInputError("attempts", self.attempts)
        if type(self.retried) is not bool:
            raise ReportInputError("retried", self.retried)
        if self.retried != (self.attempts > 1):
            raise ReportInputError("retried", self.retried)


# --- Top-level report model ------------------------------------------------


@dataclass(frozen=True)
class BatchReport:
    """The deterministic machine-readable outcome of a batch run.

    Attributes:
        mode: The batch mode (``"validate"``, ``"show"``, or
            ``"run"``).
        project_count: The number of discovered projects that
            were executed.
        success_count: The number of projects that succeeded.
        failure_count: The number of projects that failed.
        projects: Tuple of :class:`BatchProjectReportEntry`
            values, in deterministic execution order.
    """

    mode: str
    project_count: int
    success_count: int
    failure_count: int
    projects: Tuple[BatchProjectReportEntry, ...] = ()


# --- Construction ----------------------------------------------------------


def batch_result_to_report(
    mode,
    project_results,
    *,
    project_count=None,
):
    """Build a :class:`BatchReport` from batch results.

    Args:
        mode: The batch mode string. Must be one of
            ``"validate"``, ``"show"``, ``"run"``.
        project_results: An iterable of objects exposing the
            attributes consumed by :func:`_result_to_entry`
            (typically :class:`workflow.batch.BatchProjectResult`).
        project_count: Optional explicit project count. When
            ``None``, the count is derived from *project_results*.
            The two values must agree when both are provided.

    Returns:
        A new :class:`BatchReport` instance.

    Raises:
        ReportInputError: when *mode* is invalid or the result
            count is inconsistent.
    """
    if not isinstance(mode, str) or mode not in ("validate", "show", "run"):
        raise ReportInputError("mode", mode)

    entries: List[BatchProjectReportEntry] = []
    for item in project_results:
        entries.append(_result_to_entry(item))

    if project_count is not None:
        if isinstance(project_count, bool) or not isinstance(project_count, int):
            raise ReportInputError("project_count", project_count)
        if project_count < 0:
            raise ReportInputError("project_count", project_count)
        if project_count != len(entries):
            raise ReportInputError("project_count", project_count)

    success_count = sum(1 for e in entries if e.success)
    failure_count = len(entries) - success_count

    return BatchReport(
        mode=mode,
        project_count=len(entries),
        success_count=success_count,
        failure_count=failure_count,
        projects=tuple(entries),
    )


def _result_to_entry(item) -> BatchProjectReportEntry:
    """Convert a batch result item into a report entry.

    Accepts :class:`workflow.batch.BatchProjectResult` or any
    duck-typed object exposing ``path``, ``success``, and
    optional ``error`` and ``result`` attributes.
    """
    if item is None:
        raise ReportInputError("project_result", item)

    path = getattr(item, "path", None)
    if not isinstance(path, str) or not path:
        raise ReportInputError("project_result.path", path)

    success = bool(getattr(item, "success", False))

    error_message = getattr(item, "error", None)
    if success or error_message is None:
        error_type = None
        error_message_clean = None
    else:
        # ``error`` is a "<TypeName>: <message>" string produced
        # by the batch layer. Split it deterministically.
        error_message_clean = str(error_message)
        if ": " in error_message_clean:
            error_type, _, error_message_clean = error_message_clean.partition(": ")
        else:
            error_type = "Exception"

    output_paths: Tuple[str, ...] = ()
    if success:
        result_obj = getattr(item, "result", None)
        if result_obj is not None:
            raw_paths = getattr(result_obj, "output_paths", ()) or ()
            output_paths = tuple(str(p) for p in raw_paths)

    return BatchProjectReportEntry(
        path=path,
        success=success,
        error_type=error_type,
        error_message=error_message_clean,
        output_paths=output_paths,
        attempts=max(1, int(getattr(item, "attempt_count", 1))),
        retried=bool(getattr(item, "retried", False)),
    )


# --- Serialization ---------------------------------------------------------


def report_to_dict(report) -> dict:
    """Convert a :class:`BatchReport` to a plain dict.

    The dict is built in canonical key order so the resulting
    JSON is byte-deterministic.
    """
    if not isinstance(report, BatchReport):
        raise ReportInputError("report", report)

    projects_list = []
    for entry in report.projects:
        if not isinstance(entry, BatchProjectReportEntry):
            raise ReportInputError("report.projects", entry)
        # Build the per-project dict in canonical key order. The
        # ``output_paths`` key is included even when empty so the
        # shape is uniform across modes; CI consumers can rely on
        # every entry having the same key set.
        entry_dict = {
            "path": entry.path,
            "success": bool(entry.success),
            "error_type": entry.error_type,
            "error_message": entry.error_message,
            "output_paths": list(entry.output_paths),
        }
        if entry.attempts != 1 or entry.retried:
            entry_dict["attempts"] = int(entry.attempts)
            entry_dict["retried"] = bool(entry.retried)
        projects_list.append(entry_dict)

    return {
        "mode": report.mode,
        "project_count": int(report.project_count),
        "success_count": int(report.success_count),
        "failure_count": int(report.failure_count),
        "projects": projects_list,
    }


def report_to_json(report) -> str:
    """Serialize a :class:`BatchReport` to a deterministic JSON string.

    Uses ``indent=2``, ``sort_keys=False``, and
    ``ensure_ascii=False``. The returned string ends with exactly
    one trailing newline.
    """
    data = report_to_dict(report)
    return json.dumps(
        data,
        indent=2,
        sort_keys=False,
        ensure_ascii=False,
    ) + "\n"


def report_from_dict(data) -> BatchReport:
    """Reconstruct a :class:`BatchReport` from decoded JSON data."""
    if not isinstance(data, dict):
        raise ReportInputError("report", data)
    expected = {"mode", "project_count", "success_count", "failure_count", "projects"}
    if set(data) != expected:
        raise ReportInputError("report", data)
    if data["mode"] not in ("validate", "show", "run"):
        raise ReportInputError("report.mode", data["mode"])
    for field_name in ("project_count", "success_count", "failure_count"):
        value = data[field_name]
        if type(value) is not int or value < 0:
            raise ReportInputError(f"report.{field_name}", value)
    projects = data["projects"]
    if not isinstance(projects, list):
        raise ReportInputError("report.projects", projects)
    entries = []
    for raw in projects:
        if not isinstance(raw, dict):
            raise ReportInputError("report.projects", raw)
        base_fields = {"path", "success", "error_type", "error_message", "output_paths"}
        optional_fields = {"attempts", "retried"}
        if set(raw) not in (base_fields, base_fields | optional_fields):
            raise ReportInputError("report.projects", raw)
        if not isinstance(raw["path"], str) or not raw["path"]:
            raise ReportInputError("report.projects.path", raw["path"])
        if type(raw["success"]) is not bool:
            raise ReportInputError("report.projects.success", raw["success"])
        output_paths = raw["output_paths"]
        if not isinstance(output_paths, list) or not all(
            isinstance(path, str) for path in output_paths
        ):
            raise ReportInputError("report.projects.output_paths", output_paths)
        attempts = raw.get("attempts", 1)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            raise ReportInputError("report.projects.attempts", attempts)
        retried = raw.get("retried", attempts > 1)
        entries.append(BatchProjectReportEntry(
            path=raw["path"],
            success=raw["success"],
            error_type=raw["error_type"],
            error_message=raw["error_message"],
            output_paths=tuple(output_paths),
            attempts=attempts,
            retried=retried,
        ))
    report = BatchReport(
        mode=data["mode"],
        project_count=data["project_count"],
        success_count=data["success_count"],
        failure_count=data["failure_count"],
        projects=tuple(entries),
    )
    if report_to_dict(report) != data:
        raise ReportInputError("report", data)
    if report.project_count != len(report.projects):
        raise ReportInputError("report.project_count", report.project_count)
    if report.success_count != sum(entry.success for entry in report.projects):
        raise ReportInputError("report.success_count", report.success_count)
    if report.failure_count != report.project_count - report.success_count:
        raise ReportInputError("report.failure_count", report.failure_count)
    return report


def report_from_json(text) -> BatchReport:
    """Reconstruct a :class:`BatchReport` from JSON text."""
    if not isinstance(text, str) or not text.strip():
        raise ReportInputError("json", text)
    return report_from_dict(json.loads(text))


# --- Path validation -------------------------------------------------------


def _validate_report_path(value) -> Path:
    """Validate *value* as a non-empty report output path.

    Returns a :class:`pathlib.Path` for the validated value.
    Raises :class:`ReportInputError` for invalid inputs.
    """
    if value is None:
        raise ReportInputError("path", value)
    if isinstance(value, bool):
        raise ReportInputError("path", value)
    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, os.PathLike):
        text = os.fspath(value)
    elif isinstance(value, str):
        text = value
    else:
        raise ReportInputError("path", value)
    if not text or not text.strip():
        raise ReportInputError("path", value)
    return Path(text)


# --- Persistence -----------------------------------------------------------


def save_report(report, path, *, report_writer: Optional[Callable] = None):
    """Serialize *report* and write it to *path* as JSON.

    Args:
        report: A :class:`BatchReport` instance.
        path: A non-empty string or path-like value. Parent
            directories are created when missing. The returned
            value is the absolute, resolved path.
        report_writer: Optional injection point. When ``None``,
            the default writer is used (creates parent
            directories and writes UTF-8 JSON with a single
            trailing newline). Tests may inject a writer that
            captures the payload without touching the file
            system.

    Returns:
        The absolute :class:`pathlib.Path` of the written file.

    Raises:
        ReportInputError: when *report* or *path* is invalid.
        OSError: when the file cannot be written. The
            underlying ``OSError`` propagates unchanged.
    """
    if not isinstance(report, BatchReport):
        raise ReportInputError("report", report)
    validated_path = _validate_report_path(path)

    payload = report_to_json(report)

    if report_writer is None:
        _default_report_writer(validated_path, payload)
    else:
        report_writer(validated_path, payload)

    return validated_path.resolve()


def load_report(path) -> BatchReport:
    """Load and validate a :class:`BatchReport` from a JSON file."""
    validated_path = _validate_report_path(path)
    if validated_path.exists() and validated_path.is_dir():
        raise ReportInputError("path", path)
    return report_from_json(validated_path.read_text(encoding="utf-8"))


def _default_report_writer(path: Path, payload: str) -> None:
    """Write *payload* to *path*, creating parent dirs as needed.

    The file is written in UTF-8 with newline translation
    disabled so the JSON output (which already ends with a
    single ``\\n``) is preserved exactly.
    """
    parent = path.parent
    if str(parent) and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(payload)


__all__ = (
    "BatchReport",
    "BatchProjectReportEntry",
    "ReportInputError",
    "batch_result_to_report",
    "report_to_dict",
    "report_to_json",
    "report_from_dict",
    "report_from_json",
    "save_report",
    "load_report",
)
