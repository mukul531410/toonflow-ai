"""TOONFLOW-PHASE-020 — Project Batch Mode & CI Integration Foundation.

This module is a thin orchestration layer on top of the existing
TOONFLOW project APIs. It provides deterministic batch execution of
multiple project JSON files from a single directory, suitable for
CI pipelines and batch render farms.

The batch layer does NOT duplicate:

- project validation (owned by :func:`workflow.load_project`)
- schema migration (owned by :mod:`workflow.project_migrations`)
- JSON parsing (owned by :func:`workflow.project_from_json`)
- multi-shot orchestration (owned by the multi-shot workflow)
- single-shot orchestration (owned by the single-shot workflow)
- rendering logic (owned by :mod:`toonflow_ai.generation.rendering`)
- Blender logic (owned by :mod:`toonflow_ai.generation.*`)
- AI logic (owned by :mod:`ai.planner` and :mod:`ai.ollama_client`)

The batch layer is also a bpy-free, AI-free, networking-free,
threading-free module. It runs projects strictly sequentially in
lexicographic filename order. It does not own any persistence, job
history, or database.

TOONFLOW-PHASE-022 — Batch Filtering & Selective Execution
---------------------------------------------------------

:mod:`workflow.batch` adds optional deterministic project selection
on top of the existing discovery: include glob patterns, exclude
glob patterns, and an optional recursive walk. The default
behavior (no new options) is byte-for-byte identical to
PHASE-020. Filtering is orchestration-only and never mutates the
file system.

TOONFLOW-PHASE-025 — Batch Dry-Run Mode
--------------------------------------

:mod:`workflow.batch` adds an immutable :class:`BatchDryRunResult`
model and a :func:`dry_run_batch` function that reuses the same
discovery and filtering semantics as :func:`run_batch` but never
loads, replays, or renders any project. The function is
deterministic, side-effect free, and suitable for CI previews.
:func:`run_batch` also accepts a ``dry_run=True`` keyword that
performs a dry run and returns exit code ``0`` without executing
any project. Dry-run is an execution-time concern only; the
manifest schema is intentionally not extended.

Public API
----------

The single programmatic entry point is :func:`run_batch`:

    workflow.batch.run_batch(
        directory, mode, *,
        include=None, exclude=None, recursive=False,
        dry_run=False,
        load_project=...,
        replay_project=...,
        report_path=None,
        report_writer=...,
        stdout=...,
    ) -> int

The single programmatic entry point for dry-run is
:func:`dry_run_batch`:

    workflow.batch.dry_run_batch(
        directory, mode, *,
        recursive=False,
        include=None,
        exclude=None,
    ) -> BatchDryRunResult
"""

import fnmatch
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, TextIO, Tuple, Union


# --- Modes -----------------------------------------------------------------


VALIDATE_MODE = "validate"
SHOW_MODE = "show"
RUN_MODE = "run"

BATCH_MODES: Tuple[str, ...] = (VALIDATE_MODE, SHOW_MODE, RUN_MODE)
_RETRIES_UNSET = object()


# --- Errors ----------------------------------------------------------------


class BatchInputError(ValueError):
    """The batch layer's own arguments are invalid.

    The batch layer is the only layer that introduces a *new*
    error class for its own arguments (mirroring
    :class:`workflow.project.ProjectInputError` and
    :class:`workflow.report.ReportInputError`). Delegated errors
    from the project layer, the multi-shot workflow, and the
    report layer propagate unchanged.

    Attributes:
        parameter: The name of the offending parameter.
        value: The offending value (preserved as-given).
    """

    def __init__(self, parameter, value):
        self.parameter = parameter
        self.value = value
        super().__init__(
            f"Batch input {parameter!r} is invalid: got {value!r}."
        )


# --- Default delegation targets -------------------------------------------


def _default_load_project(path):
    """Delegate to :func:`workflow.load_project`."""
    from .project import load_project

    return load_project(path)


def _default_replay_project(project, *, workflow_callable=None):
    """Delegate to :func:`workflow.replay_project`."""
    from .project import replay_project

    return replay_project(project, workflow_callable=workflow_callable)


def _default_report_writer(report, path, *, report_writer=None):
    """Delegate to :func:`workflow.report.save_report`."""
    from .report import save_report

    if report_writer is None:
        return save_report(report, path)
    return save_report(report, path, report_writer=report_writer)


def _default_report_loader(path):
    """Delegate to :func:`workflow.report.load_report`."""
    from .report import load_report

    return load_report(path)


# --- File discovery --------------------------------------------------------


def _is_project_json_file(name):
    """Return ``True`` if *name* is a top-level project JSON file.

    A project file is any regular file whose name ends in
    ``.json`` and is not a hidden file. The function only inspects
    the file name; the actual file system entry is examined by
    :func:`discover_projects` via :func:`os.scandir`.
    """
    if not isinstance(name, str) or not name:
        return False
    if name.startswith("."):
        return False
    if not name.endswith(".json"):
        return False
    return True


def _normalize_patterns(value, *, parameter):
    """Validate and normalize an include/exclude pattern argument.

    Accepted inputs (returned as a tuple of non-empty strings):

    - ``None`` → empty tuple (no filtering).
    - ``str`` → one-element tuple; empty / whitespace strings are
      rejected.
    - Sequence of strings → tuple; each entry must be a non-empty
      string; ``bool`` entries are rejected.

    Any other input (int, float, dict, mixed sequence, sequence
    containing non-strings) raises :class:`BatchInputError` with
    *parameter* as the offending field name.
    """
    if value is None:
        return ()
    if isinstance(value, bool):
        raise BatchInputError(parameter, value)
    if isinstance(value, str):
        if not value.strip():
            raise BatchInputError(parameter, value)
        return (value,)
    if isinstance(value, (list, tuple)):
        for entry in value:
            if isinstance(entry, bool) or not isinstance(entry, str):
                raise BatchInputError(parameter, value)
            if not entry.strip():
                raise BatchInputError(parameter, value)
        return tuple(value)
    raise BatchInputError(parameter, value)


def _validate_recursive(value, *, parameter="recursive"):
    """Validate that *value* is a real boolean.

    Rejects ``int`` (including ``0`` / ``1``), ``str``, and
    ``None``. Only ``True`` and ``False`` are accepted.
    """
    if isinstance(value, bool):
        return value
    raise BatchInputError(parameter, value)


def _validate_retries(value):
    """Validate the number of additional attempts for one project."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BatchInputError("retries", value)
    return value


def _relpath_posix(root, path):
    """Return the relative path from *root* to *path* using ``/``.

    Both arguments are expected to be string paths produced by
    :func:`os.path.join` against the same root. The result uses
    forward slashes for cross-platform glob compatibility.
    """
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


def _matches_any(rel_posix, patterns):
    """Return ``True`` if *rel_posix* matches any of *patterns*.

    Uses :func:`fnmatch.fnmatchcase` for case-sensitive matching,
    which is deterministic across platforms.
    """
    for pattern in patterns:
        if fnmatch.fnmatchcase(rel_posix, pattern):
            return True
    return False


def _discover_non_recursive(directory):
    """Discover project JSON files in the direct children of *directory*.

    Returns a list of absolute string paths sorted by
    ``(relative POSIX path)`` in lexicographic order. For
    non-recursive discovery the relative path equals the
    filename.
    """
    entries = list(os.scandir(directory))
    names = sorted(
        entry.name
        for entry in entries
        if _is_project_json_file(entry.name) and entry.is_file()
    )
    return [os.path.join(directory, name) for name in names]


def _discover_recursive(directory):
    """Recursively discover project JSON files under *directory*.

    Hidden directories (names starting with ``.``) are skipped.
    Every regular file whose name matches
    :func:`_is_project_json_file` is eligible. The result is
    sorted by the relative POSIX path (forward slashes) in
    lexicographic order, which is fully deterministic and
    independent of the file system enumeration order.
    """
    matches: List[str] = []

    def _walk(current):
        try:
            entries = list(os.scandir(current))
        except OSError:
            return
        # Sort by name to make the walk order deterministic.
        entries.sort(key=lambda e: e.name)
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                # Skip hidden files and hidden directories.
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    _walk(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    if _is_project_json_file(name):
                        matches.append(entry.path)
            except OSError:
                # Skip entries we cannot stat; they are not
                # eligible for batch execution.
                continue

    _walk(directory)
    matches.sort(key=lambda p: _relpath_posix(directory, p))
    return matches


def discover_projects(
    directory,
    *,
    include=None,
    exclude=None,
    recursive=False,
):
    """Return a deterministically ordered list of project JSON files.

    The discovery honors optional include / exclude glob patterns
    and an optional recursive walk. When none of the new
    options are provided, the behavior is byte-for-byte
    identical to PHASE-020: non-recursive, filename-only
    lexicographic order, ``*.json`` files that are not hidden,
    subdirectories ignored.

    Args:
        directory: A string or path-like value pointing to an
            existing directory.
        include: Optional include glob. Accepted as a single
            non-empty string or a sequence of non-empty strings.
            When ``None`` (the default), all eligible files are
            candidates. Patterns match the relative POSIX path
            from *directory* (which is just the filename for
            non-recursive discovery).
        exclude: Optional exclude glob. Same accepted types as
            *include*. When a file matches both include and
            exclude, exclude wins.
        recursive: When ``True``, walk into subdirectories.
            Subdirectories whose name starts with ``.`` are
            skipped. When ``False`` (the default), only direct
            children are considered.

    Returns:
        A list of string paths to project JSON files, in
        deterministic lexicographic order by relative POSIX
        path. The order is independent of the file system
        enumeration order.

    Raises:
        BatchInputError: when *include*, *exclude*, or
            *recursive* is invalid.
        OSError: when *directory* does not exist, is not a
            directory, or cannot be read.
    """
    include_patterns = _normalize_patterns(include, parameter="include")
    exclude_patterns = _normalize_patterns(exclude, parameter="exclude")
    recursive = _validate_recursive(recursive)

    if recursive:
        candidates = _discover_recursive(directory)
    else:
        candidates = _discover_non_recursive(directory)

    if not include_patterns and not exclude_patterns:
        return candidates

    selected: List[str] = []
    for path in candidates:
        rel = _relpath_posix(directory, path)
        if include_patterns and not _matches_any(rel, include_patterns):
            continue
        if exclude_patterns and _matches_any(rel, exclude_patterns):
            continue
        selected.append(path)
    return selected


# --- Result model ----------------------------------------------------------


class BatchProjectResult:
    """The outcome of processing one project within a batch run.

    Attributes:
        path: The absolute or relative path to the project file.
        success: ``True`` if the project loaded (and, for
            ``run`` mode, replayed) successfully.
        error: ``None`` on success, otherwise a string with the
            exception type and message.
        project: The loaded :class:`workflow.Project` instance, or
            ``None`` on load failure.
        result: The :class:`workflow.MultiShotResult` for ``run``
            mode, or ``None`` for ``validate`` / ``show`` modes
            and on failure.
    """

    def __init__(self, path, *, success, error=None, project=None,
                 result=None, attempts=()):
        self.path = path
        self.success = bool(success)
        self.error = error
        self.project = project
        self.result = result
        self.attempt_history = tuple(attempts)

    @property
    def attempts(self):
        return len(self.attempt_history) or 1

    @property
    def attempt_count(self):
        return self.attempts

    @property
    def final_attempt(self):
        return self.attempt_count

    @property
    def retried(self):
        return self.attempt_count > 1


@dataclass(frozen=True)
class BatchAttemptResult:
    """The normalized outcome of one current-invocation attempt."""

    attempt: int
    success: bool
    error: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise BatchInputError("attempt", self.attempt)
        if self.attempt < 1:
            raise BatchInputError("attempt", self.attempt)
        if type(self.success) is not bool:
            raise BatchInputError("success", self.success)
        if self.error is not None and not isinstance(self.error, str):
            raise BatchInputError("error", self.error)
        if self.success and self.error is not None:
            raise BatchInputError("error", self.error)


@dataclass(frozen=True)
class BatchOperationalSummary:
    """Analytical counters derived from one batch selection and its results."""

    selected: int
    skipped: int
    executed: int
    succeeded: int
    failed: int
    retried: int
    total_attempts: int
    pending: int = 0

    def __post_init__(self):
        fields = (
            "selected", "skipped", "executed", "succeeded", "failed",
            "retried", "total_attempts", "pending",
        )
        for field_name in fields:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BatchInputError(field_name, value)
        expected_selected = (
            self.skipped + self.pending
            if self.executed == 0 and self.pending
            else self.skipped + self.executed
        )
        if self.selected != expected_selected:
            raise BatchInputError("summary.selected", self.selected)
        if self.executed != self.succeeded + self.failed:
            raise BatchInputError("summary.executed", self.executed)
        if self.retried > self.executed:
            raise BatchInputError("summary.retried", self.retried)
        if self.total_attempts < self.executed:
            raise BatchInputError("summary.total_attempts", self.total_attempts)


def build_batch_operational_summary(
    project_results=(), *, selected=None, skipped=0, pending=0,
    dry_run=False,
):
    """Derive deterministic operational counters without executing anything."""
    results = tuple(project_results)
    if dry_run:
        if selected is None:
            selected = skipped + pending
        return BatchOperationalSummary(
            selected=selected, skipped=skipped, executed=0,
            succeeded=0, failed=0, retried=0, total_attempts=0,
            pending=pending,
        )
    executed = len(results)
    if selected is None:
        selected = skipped + executed
    succeeded = sum(1 for result in results if bool(getattr(result, "success", False)))
    failed = executed - succeeded
    retried = sum(1 for result in results if bool(getattr(result, "retried", False)))
    total_attempts = sum(
        int(getattr(result, "attempts", getattr(result, "attempt_count", 1)))
        for result in results
    )
    return BatchOperationalSummary(
        selected=selected, skipped=skipped, executed=executed,
        succeeded=succeeded, failed=failed, retried=retried,
        total_attempts=total_attempts, pending=pending,
    )


summarize_batch = build_batch_operational_summary


@dataclass(frozen=True)
class BatchResultExport:
    """Immutable analytical export of one current batch result."""

    directory: Any
    mode: str
    recursive: bool
    include: Tuple[str, ...]
    exclude: Tuple[str, ...]
    projects: Tuple[Any, ...]
    summary: BatchOperationalSummary
    selected_projects: Tuple[Any, ...] = ()
    skipped_projects: Tuple[Any, ...] = ()
    pending_projects: Tuple[Any, ...] = ()
    dry_run: bool = False

    def __post_init__(self):
        for field_name in (
            "include", "exclude", "projects", "selected_projects",
            "skipped_projects", "pending_projects",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple):
                object.__setattr__(self, field_name, tuple(value))
        if not isinstance(self.summary, BatchOperationalSummary):
            raise BatchInputError("summary", self.summary)
        if type(self.dry_run) is not bool:
            raise BatchInputError("dry_run", self.dry_run)


@dataclass(frozen=True)
class BatchResultValidation:
    """Deterministic, immutable validation findings."""

    valid: bool
    findings: Tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.valid) is not bool:
            raise BatchInputError("valid", self.valid)
        if not isinstance(self.findings, tuple):
            object.__setattr__(self, "findings", tuple(self.findings))
        if not all(isinstance(finding, str) for finding in self.findings):
            raise BatchInputError("findings", self.findings)
        if self.valid and self.findings:
            raise BatchInputError("findings", self.findings)


def _validation(findings):
    ordered = tuple(findings)
    return BatchResultValidation(not ordered, ordered)


def validate_batch_operational_summary(summary, *, dry_run=False):
    """Validate summary counters and their normal/dry-run invariants."""
    if not isinstance(summary, BatchOperationalSummary):
        return _validation(("summary must be BatchOperationalSummary",))
    findings = []
    counters = (
        "selected", "skipped", "executed", "succeeded", "failed",
        "retried", "total_attempts", "pending",
    )
    for field_name in counters:
        value = getattr(summary, field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            findings.append(f"summary.{field_name} must be a nonnegative integer")
    if findings:
        return _validation(findings)
    if dry_run:
        if summary.selected != summary.skipped + summary.pending:
            findings.append("dry-run selected must equal skipped plus pending")
        for field_name in ("executed", "succeeded", "failed", "retried", "total_attempts"):
            if getattr(summary, field_name) != 0:
                findings.append(f"dry-run {field_name} must be zero")
    else:
        if summary.selected != summary.skipped + summary.executed:
            findings.append("selected must equal skipped plus executed")
        if summary.executed != summary.succeeded + summary.failed:
            findings.append("executed must equal succeeded plus failed")
        if summary.retried > summary.executed:
            findings.append("retried must not exceed executed")
        if summary.total_attempts < summary.executed:
            findings.append("total_attempts must be at least executed")
        if summary.total_attempts < summary.retried:
            findings.append("total_attempts must be at least retried")
    return _validation(findings)


def validate_batch_results(project_results):
    """Validate final project results without executing or mutating them."""
    try:
        results = tuple(project_results)
    except TypeError:
        return _validation(("project_results must be iterable",))
    findings = []
    for index, result in enumerate(results):
        prefix = f"projects[{index}]"
        if not isinstance(getattr(result, "path", None), str) or not result.path:
            findings.append(f"{prefix}.path must be a nonempty string")
        if type(getattr(result, "success", None)) is not bool:
            findings.append(f"{prefix}.success must be boolean")
        attempts = getattr(result, "attempts", None)
        retried = getattr(result, "retried", None)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            findings.append(f"{prefix}.attempts must be a positive integer")
        if type(retried) is not bool:
            findings.append(f"{prefix}.retried must be boolean")
        elif isinstance(attempts, int) and not isinstance(attempts, bool) and attempts >= 1:
            if retried != (attempts > 1):
                findings.append(f"{prefix}.retried must agree with attempts")
        history = getattr(result, "attempt_history", None)
        if history:
            if not isinstance(history, tuple):
                findings.append(f"{prefix}.attempt_history must be a tuple")
            else:
                for expected, attempt in enumerate(history, 1):
                    if not isinstance(attempt, BatchAttemptResult):
                        findings.append(f"{prefix}.attempt_history contains an invalid attempt")
                        continue
                    if attempt.attempt != expected:
                        findings.append(f"{prefix}.attempt_history numbering is not sequential")
                if history and history[-1].success != getattr(result, "success", None):
                    findings.append(f"{prefix}.final attempt must match success")
                if len(history) != getattr(result, "attempts", None):
                    findings.append(f"{prefix}.attempts must match attempt history")
    return _validation(findings)


def validate_batch_result_export(export):
    """Validate an immutable export and its derived summary."""
    if not isinstance(export, BatchResultExport):
        return _validation(("export must be BatchResultExport",))
    findings = []
    if export.mode not in BATCH_MODES:
        findings.append("export.mode is invalid")
    if type(export.recursive) is not bool:
        findings.append("export.recursive must be boolean")
    for field_name in ("include", "exclude"):
        if not all(isinstance(value, str) for value in getattr(export, field_name)):
            findings.append(f"export.{field_name} must contain strings")
    summary_validation = validate_batch_operational_summary(
        export.summary, dry_run=export.dry_run,
    )
    findings.extend(summary_validation.findings)
    if export.dry_run:
        if export.projects:
            findings.append("dry-run export must not contain project results")
        expected = build_batch_operational_summary(
            (), selected=len(export.selected_projects),
            skipped=len(export.skipped_projects),
            pending=len(export.pending_projects), dry_run=True,
        )
    else:
        project_validation = validate_batch_results(export.projects)
        findings.extend(project_validation.findings)
        expected = build_batch_operational_summary(
            export.projects, selected=len(export.selected_projects),
            skipped=len(export.skipped_projects), pending=len(export.pending_projects),
        )
    if export.summary != expected:
        findings.append("export.summary does not match its source structures")
    if not set(export.skipped_projects).issubset(set(export.selected_projects)):
        findings.append("skipped projects must be selected projects")
    if not set(export.pending_projects).issubset(set(export.selected_projects)):
        findings.append("pending projects must be selected projects")
    return _validation(findings)


def validate_batch_result_export_or_raise(export):
    """Raise :class:`BatchInputError` when an export is inconsistent."""
    validation = validate_batch_result_export(export)
    if not validation.valid:
        raise BatchInputError("export", validation.findings)
    return export


def _export_project_to_dict(project):
    """Convert a final project result/report entry to JSON-safe data."""
    path = getattr(project, "path", None)
    if not isinstance(path, str) or not path:
        raise BatchInputError("project.path", path)
    error = getattr(project, "error", None)
    error_type = getattr(project, "error_type", None)
    error_message = getattr(project, "error_message", None)
    if error is not None and error_type is None:
        if ": " in str(error):
            error_type, _, error_message = str(error).partition(": ")
        else:
            error_type, error_message = "Exception", str(error)
    data = {
        "path": path,
        "success": bool(getattr(project, "success", False)),
        "error_type": error_type,
        "error_message": error_message,
        "attempts": int(getattr(project, "attempts", 1)),
        "retried": bool(getattr(project, "retried", False)),
    }
    result = getattr(project, "result", None)
    raw_output_paths = getattr(project, "output_paths", None)
    if raw_output_paths is not None:
        output_values = raw_output_paths
    else:
        output_values = getattr(result, "output_paths", ()) or ()
    data["output_paths"] = [
        str(value) for value in output_values
    ]
    return data


def _export_summary_to_dict(summary):
    return {
        "selected": summary.selected,
        "skipped": summary.skipped,
        "executed": summary.executed,
        "succeeded": summary.succeeded,
        "failed": summary.failed,
        "retried": summary.retried,
        "total_attempts": summary.total_attempts,
        "pending": summary.pending,
    }


def export_batch_result(
    directory,
    mode=None,
    project_results=(),
    *,
    recursive=False,
    include=(),
    exclude=(),
    selected_projects=None,
    skipped_projects=(),
    pending_projects=None,
    dry_run=False,
):
    """Build a deterministic export from final results or a dry-run result."""
    if isinstance(directory, BatchDryRunResult):
        if mode is not None or project_results != ():
            raise BatchInputError("result", directory)
        return export_batch_result(
            str(directory.directory), directory.mode, (),
            recursive=directory.recursive, include=directory.include,
            exclude=directory.exclude,
            selected_projects=directory.selected_projects,
            skipped_projects=directory.skipped_projects,
            pending_projects=directory.pending_projects,
            dry_run=True,
        )
    results = tuple(project_results)
    if mode not in BATCH_MODES:
        raise BatchInputError("mode", mode)
    selected = tuple(selected_projects) if selected_projects is not None else tuple(
        skipped_projects
    ) + tuple(getattr(result, "path", "") for result in results)
    skipped = tuple(skipped_projects)
    if pending_projects is None:
        if dry_run:
            skipped_set = set(skipped)
            pending = tuple(path for path in selected if path not in skipped_set)
        else:
            pending = ()
    else:
        pending = tuple(pending_projects)
    summary = build_batch_operational_summary(
        results, selected=len(selected), skipped=len(skipped),
        pending=len(pending), dry_run=dry_run,
    )
    return BatchResultExport(
        directory=directory,
        mode=mode,
        recursive=bool(recursive),
        include=tuple(include),
        exclude=tuple(exclude),
        projects=() if dry_run else tuple(results),
        summary=summary,
        selected_projects=selected,
        skipped_projects=skipped,
        pending_projects=pending,
        dry_run=dry_run,
    )


def batch_result_to_dict(export):
    """Convert a :class:`BatchResultExport` to ordered JSON-safe data."""
    if not isinstance(export, BatchResultExport):
        raise BatchInputError("export", export)
    data = {
        "directory": str(export.directory).replace(os.sep, "/"),
        "mode": export.mode,
        "recursive": bool(export.recursive),
        "include": list(export.include),
        "exclude": list(export.exclude),
        "dry_run": bool(export.dry_run),
        "projects": [
            _export_project_to_dict(project) for project in export.projects
        ],
        "summary": _export_summary_to_dict(export.summary),
        "selected_projects": [
            str(path).replace(os.sep, "/") for path in export.selected_projects
        ],
        "skipped_projects": [
            str(path).replace(os.sep, "/") for path in export.skipped_projects
        ],
        "pending_projects": [
            str(path).replace(os.sep, "/") for path in export.pending_projects
        ],
    }
    return data


def batch_result_to_json(export) -> str:
    """Serialize a batch export using deterministic pretty JSON."""
    return json.dumps(
        batch_result_to_dict(export),
        indent=2,
        sort_keys=False,
        ensure_ascii=False,
    ) + "\n"


@dataclass(frozen=True)
class BatchResumeResult:
    """Deterministic, immutable resume planning for selected projects."""

    selected_projects: Tuple[Any, ...]
    skipped_projects: Tuple[Any, ...]
    pending_projects: Tuple[Any, ...]

    def __post_init__(self):
        for field_name in ("selected_projects", "skipped_projects", "pending_projects"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple):
                object.__setattr__(self, field_name, tuple(value))


def _normalize_project_path(path):
    """Normalize separators and redundant components without case folding."""
    return os.path.normpath(os.fspath(path)).replace("\\", "/")


def plan_batch_resume(projects, previous_report):
    """Plan skips from successful entries in an existing BatchReport.

    Matching uses normalized separators and redundant path components while
    preserving case. The current selection is authoritative and its order is
    retained in every result tuple.
    """
    if previous_report is None:
        raise BatchInputError("previous_report", previous_report)
    entries = getattr(previous_report, "projects", None)
    if entries is None:
        raise BatchInputError("previous_report", previous_report)
    selected = tuple(projects)
    occurrences = {}
    for entry in entries:
        path = getattr(entry, "path", None)
        if isinstance(path, str) and path:
            key = _normalize_project_path(path)
            occurrences[key] = occurrences.get(key, 0) + 1
    successful = {
        _normalize_project_path(entry.path)
        for entry in entries
        if isinstance(getattr(entry, "path", None), str)
        and getattr(entry, "path", "")
        and type(getattr(entry, "success", None)) is bool
        and getattr(entry, "success") is True
        and occurrences.get(_normalize_project_path(entry.path)) == 1
    }
    skipped = tuple(
        path for path in selected
        if _normalize_project_path(path) in successful
    )
    skipped_keys = {_normalize_project_path(path) for path in skipped}
    pending = tuple(
        path for path in selected
        if _normalize_project_path(path) not in skipped_keys
    )
    return BatchResumeResult(selected, skipped, pending)


# --- Per-mode execution ----------------------------------------------------


def _execute_validate(path, *, load_project, stdout):
    """Run the ``validate`` mode for one project file.

    Returns a :class:`BatchProjectResult`.
    """
    try:
        project = load_project(path)
    except (OSError, ValueError, TypeError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        stdout.write(f"{path}: ERROR: {msg}\n")
        return BatchProjectResult(path, success=False, error=msg)
    except Exception as exc:  # noqa: BLE001 - batch boundary
        msg = f"{type(exc).__name__}: {exc}"
        stdout.write(f"{path}: ERROR: {msg}\n")
        return BatchProjectResult(path, success=False, error=msg)
    stdout.write(f"{path}: OK\n")
    return BatchProjectResult(path, success=True, project=project)


def _format_show_summary(project) -> List[str]:
    """Return the deterministic per-project show lines for *project*."""
    lines = [
        f"  Name: {project.name}",
        f"  Schema version: {project.schema_version}",
        f"  Description: {project.description}",
        f"  Shots: {len(project.shots)}",
    ]
    for index, shot in enumerate(project.shots):
        lines.append(
            f"  Shot {index}: "
            f"concept={shot.concept!r} "
            f"animation={shot.animation!r} "
            f"lip_sync={shot.lip_sync!r} "
            f"output_path={shot.output_path!r}"
        )
    return lines


def _execute_show(path, *, load_project, stdout):
    """Run the ``show`` mode for one project file.

    Returns a :class:`BatchProjectResult`.
    """
    try:
        project = load_project(path)
    except (OSError, ValueError, TypeError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        stdout.write(f"{path}: ERROR: {msg}\n")
        return BatchProjectResult(path, success=False, error=msg)
    except Exception as exc:  # noqa: BLE001 - batch boundary
        msg = f"{type(exc).__name__}: {exc}"
        stdout.write(f"{path}: ERROR: {msg}\n")
        return BatchProjectResult(path, success=False, error=msg)
    stdout.write(f"{path}:\n")
    for line in _format_show_summary(project):
        stdout.write(f"{line}\n")
    return BatchProjectResult(path, success=True, project=project)


def _execute_run(path, *, load_project, replay_project, stdout):
    """Run the ``run`` mode for one project file.

    Loads the project first; on load failure, replay is NOT
    invoked. On successful load, delegates to *replay_project*
    exactly once. Returns a :class:`BatchProjectResult`.
    """
    try:
        project = load_project(path)
    except (OSError, ValueError, TypeError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        stdout.write(f"{path}: ERROR: {msg}\n")
        return BatchProjectResult(path, success=False, error=msg)
    except Exception as exc:  # noqa: BLE001 - batch boundary
        msg = f"{type(exc).__name__}: {exc}"
        stdout.write(f"{path}: ERROR: {msg}\n")
        return BatchProjectResult(path, success=False, error=msg)
    try:
        result = replay_project(project)
    except (OSError, ValueError, TypeError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        stdout.write(f"{path}: ERROR: {msg}\n")
        return BatchProjectResult(
            path, success=False, error=msg, project=project,
        )
    except Exception as exc:  # noqa: BLE001 - batch boundary
        msg = f"{type(exc).__name__}: {exc}"
        stdout.write(f"{path}: ERROR: {msg}\n")
        return BatchProjectResult(
            path, success=False, error=msg, project=project,
        )
    output_paths = tuple(getattr(result, "output_paths", ()) or ())
    stdout.write(f"{path}: OK ({len(output_paths)} shot(s))\n")
    for index, output_path in enumerate(output_paths):
        stdout.write(f"  Shot {index}: output_path={output_path!r}\n")
    return BatchProjectResult(
        path, success=True, project=project, result=result,
    )


# --- Summary ---------------------------------------------------------------


def _format_summary(total, succeeded, failed, *, operational_summary=None):
    """Return the deterministic batch summary lines."""
    lines = [
        "",
        "Summary:",
        f"  Projects: {total}",
        f"  Succeeded: {succeeded}",
        f"  Failed: {failed}",
        "",
    ]
    if operational_summary is not None:
        lines.extend([
            f"  Selected: {operational_summary.selected}",
            f"  Skipped: {operational_summary.skipped}",
            f"  Executed: {operational_summary.executed}",
            f"  Retried: {operational_summary.retried}",
            f"  Total attempts: {operational_summary.total_attempts}",
            "",
        ])
    return lines


# --- Dry-run ---------------------------------------------------------------


@dataclass(frozen=True)
class BatchDryRunResult:
    """The deterministic preview of a batch execution.

    The result is produced by :func:`dry_run_batch` (or by
    :func:`run_batch` with ``dry_run=True``). It describes
    exactly which projects *would* be selected for execution
    under the given configuration, without loading, replaying,
    rendering, or otherwise mutating any project.

    Attributes:
        directory: The directory that would be scanned, as
            supplied to the dry-run entry point. Stored as
            :class:`pathlib.Path`.
        mode: The batch mode (``"validate"``, ``"show"``, or
            ``"run"``).
        recursive: Whether subdirectories would be walked.
        include: Tuple of include glob patterns, after
            normalization. Empty tuple when no include filter
            was supplied.
        exclude: Tuple of exclude glob patterns, after
            normalization. Empty tuple when no exclude filter
            was supplied.
        projects: Tuple of :class:`pathlib.Path` values that
            *would* be executed, in deterministic
            lexicographic order by relative POSIX path. May be
            empty.
    """

    directory: Path
    mode: str
    recursive: bool
    include: Tuple[str, ...]
    exclude: Tuple[str, ...]
    projects: Tuple[Path, ...]
    selected_projects: Optional[Tuple[Path, ...]] = None
    skipped_projects: Tuple[Path, ...] = ()
    pending_projects: Optional[Tuple[Path, ...]] = None
    resume_applied: bool = False
    retries: Optional[int] = None
    max_attempts: Optional[int] = None
    retry_configured: bool = False
    operational_summary_available: bool = False

    def __post_init__(self):
        # Defensive normalization: even though the fields are
        # annotated as tuples, callers (and tests) may pass
        # lists. Convert to tuples and ensure the result
        # never aliases a caller-provided mutable collection.
        if not isinstance(self.include, tuple):
            object.__setattr__(self, "include", tuple(self.include))
        if not isinstance(self.exclude, tuple):
            object.__setattr__(self, "exclude", tuple(self.exclude))
        if not isinstance(self.projects, tuple):
            object.__setattr__(self, "projects", tuple(self.projects))
        if self.selected_projects is None:
            object.__setattr__(self, "selected_projects", self.projects)
        elif not isinstance(self.selected_projects, tuple):
            object.__setattr__(self, "selected_projects", tuple(self.selected_projects))
        if not isinstance(self.skipped_projects, tuple):
            object.__setattr__(self, "skipped_projects", tuple(self.skipped_projects))
        if self.pending_projects is None:
            object.__setattr__(self, "pending_projects", self.projects)
        elif not isinstance(self.pending_projects, tuple):
            object.__setattr__(self, "pending_projects", tuple(self.pending_projects))


def _validate_mode_for_dry_run(mode) -> str:
    if not isinstance(mode, str) or not mode:
        raise BatchInputError("mode", mode)
    if mode not in BATCH_MODES:
        raise BatchInputError("mode", mode)
    return mode


def dry_run_batch(
    directory,
    mode,
    *,
    recursive=False,
    include=None,
    exclude=None,
    resume_from=None,
    report_loader: Callable = _default_report_loader,
    retries=_RETRIES_UNSET,
) -> BatchDryRunResult:
    """Return the deterministic preview of a batch execution.

    The function reuses the existing :func:`discover_projects`
    selection semantics, so for any given configuration the
    ``projects`` tuple is exactly the set of files a real
    :func:`run_batch` call would attempt to execute.

    The function never calls :func:`workflow.load_project`,
    :func:`workflow.replay_project`, or any rendering / AI /
    Blender code. It is pure orchestration: validation plus
    discovery.

    Args:
        directory: A string or path-like value pointing to the
            directory to scan.
        mode: One of ``"validate"``, ``"show"``, ``"run"``.
        recursive: When ``True``, walk into subdirectories.
            Must be a real boolean.
        include: Optional include glob pattern or sequence of
            patterns. Forwarded to :func:`discover_projects`.
        exclude: Optional exclude glob pattern or sequence of
            patterns. Forwarded to :func:`discover_projects`.

    Returns:
        A new :class:`BatchDryRunResult`. The ``projects``
        tuple may be empty when the directory is missing, is
        not a directory, or the filters selected zero files.
        In every case the result is a valid immutable value
        with a deterministic shape.

    Raises:
        BatchInputError: when *mode*, *recursive*, *include*,
            or *exclude* is invalid.
        OSError: when the directory does not exist or is not
            a directory. The exception is propagated
            unchanged.
    """
    normalized_mode = _validate_mode_for_dry_run(mode)
    normalized_recursive = _validate_recursive(recursive)
    retry_configured = retries is not _RETRIES_UNSET
    normalized_retries = _validate_retries(
        0 if not retry_configured else retries,
    )
    include_patterns = _normalize_patterns(include, parameter="include")
    exclude_patterns = _normalize_patterns(exclude, parameter="exclude")

    project_paths = discover_projects(
        directory,
        include=include_patterns or None,
        exclude=exclude_patterns or None,
        recursive=normalized_recursive,
    )

    resume = None
    if resume_from is not None:
        resume = plan_batch_resume(
            project_paths, report_loader(resume_from),
        )
    selected_paths = tuple(Path(p) for p in project_paths)
    skipped_paths = tuple(Path(p) for p in (resume.skipped_projects if resume else ()))
    pending_paths = tuple(Path(p) for p in (resume.pending_projects if resume else project_paths))

    directory_path = Path(str(directory))
    return BatchDryRunResult(
        directory=directory_path,
        mode=normalized_mode,
        recursive=bool(normalized_recursive),
        include=tuple(include_patterns),
        exclude=tuple(exclude_patterns),
        projects=pending_paths,
        selected_projects=selected_paths,
        skipped_projects=skipped_paths,
        pending_projects=pending_paths,
        resume_applied=resume_from is not None,
        retries=normalized_retries if retry_configured else None,
        max_attempts=(normalized_retries + 1) if retry_configured else None,
        retry_configured=retry_configured,
        operational_summary_available=True,
    )


def _format_dry_run_summary(
    mode, project_paths, recursive, include_patterns, exclude_patterns,
):
    """Return the deterministic dry-run summary lines.

    The output is intentionally simple and machine-friendly. It
    lists the configuration that was effective and the
    (possibly empty) set of projects that *would* be executed.
    """
    lines = [
        "Dry-run:",
        f"  Mode: {mode}",
        f"  Recursive: {bool(recursive)}",
        f"  Include: {list(include_patterns)}",
        f"  Exclude: {list(exclude_patterns)}",
        f"  Projects: {len(project_paths)}",
    ]
    for path in project_paths:
        lines.append(f"  - {path}")
    return lines


def run_batch(
    directory,
    mode,
    *,
    include=None,
    exclude=None,
    recursive=False,
    dry_run: bool = False,
    load_project: Callable = _default_load_project,
    replay_project: Callable = _default_replay_project,
    stdout: Optional[TextIO] = None,
    report_path=None,
    report_writer: Optional[Callable] = None,
    resume_from=None,
    report_loader: Callable = _default_report_loader,
    retries=0,
) -> int:
    """Run a deterministic batch over a directory of project files.

    Args:
        directory: A string or path-like value pointing to a
            directory of project JSON files. The directory must
            exist and be a directory. It is scanned non-recursively
            for ``*.json`` files; subdirectories and hidden files
            are ignored.
        mode: One of ``"validate"``, ``"show"``, ``"run"``.
        include: Optional include glob pattern or sequence of
            patterns. Forwarded to :func:`discover_projects`.
            When ``None`` (the default), all eligible files are
            candidates.
        exclude: Optional exclude glob pattern or sequence of
            patterns. Forwarded to :func:`discover_projects`.
            When a file matches both include and exclude, exclude
            wins.
        recursive: When ``True``, walk into subdirectories. When
            ``False`` (the default), only direct children are
            considered. Must be a real boolean.
        dry_run: When ``True``, perform a dry run. The function
            validates the inputs, runs the same discovery and
            filtering that a real execution would, and returns
            exit code ``0`` without loading, replaying, or
            rendering any project, and without writing a
            report. When ``False`` (the default), the existing
            behavior is preserved byte-for-byte.
        load_project: Dependency-injection point replacing
            :func:`workflow.load_project`.
        replay_project: Dependency-injection point replacing
            :func:`workflow.replay_project`. Only used by
            ``"run"`` mode.
        stdout: Optional output stream. When ``None``, defaults to
            :data:`sys.stdout`.
        report_path: Optional path for a deterministic JSON
            report. When ``None`` (the default), no report is
            written. When provided, a :class:`workflow.report.BatchReport`
            is constructed from the executed project results and
            written to *report_path* via the report layer. The
            report contains only the projects actually selected
            and executed by this filtered batch run. The report
            is only written when at least one project was
            executed; early-exit cases (unknown mode, missing
            directory, empty directory, empty selection after
            filtering) do not produce a report. When
            ``dry_run=True``, the report is never written.
        report_writer: Optional dependency-injection point for
            the report layer. When ``None``, the default
            writer (:func:`workflow.report.save_report`) is used.

    Returns:
        An integer exit code:

        - ``0`` — all selected projects succeeded, or
          ``dry_run=True``.
        - ``1`` — one or more projects failed, no eligible
          project files were found, or the include / exclude
          filters selected zero files. Dry-run never returns
          ``1`` for an empty selection; empty selection in
          dry-run is a valid successful preview (exit code
          ``0``).
        - ``2`` — invalid arguments (unknown mode or invalid
          include / exclude / recursive value).

    The function never calls :func:`sys.exit` and never mutates
    :data:`sys.argv`. It is safe to invoke directly from unit
    tests.
    """
    # ``stdout`` is imported lazily so the module can be imported
    # in environments where ``sys`` is patched.
    import sys as _sys
    if stdout is None:
        stdout = _sys.stdout

    if mode not in BATCH_MODES:
        stdout.write(
            f"error: unknown batch mode: {mode!r} "
            f"(choose from {list(BATCH_MODES)})\n"
        )
        return 2

    # Validate the filtering arguments up front so that invalid
    # values produce a deterministic exit code 2 and a clear
    # error message before any file system access.
    try:
        include_patterns = _normalize_patterns(include, parameter="include")
    except BatchInputError as exc:
        stdout.write(f"error: {exc}\n")
        return 2
    try:
        exclude_patterns = _normalize_patterns(exclude, parameter="exclude")
    except BatchInputError as exc:
        stdout.write(f"error: {exc}\n")
        return 2
    try:
        recursive = _validate_recursive(recursive)
    except BatchInputError as exc:
        stdout.write(f"error: {exc}\n")
        return 2
    try:
        dry_run = _validate_recursive(dry_run)
    except BatchInputError as exc:
        stdout.write(f"error: {exc}\n")
        return 2
    try:
        retries = _validate_retries(retries)
    except BatchInputError as exc:
        stdout.write(f"error: {exc}\n")
        return 2

    if resume_from is not None and report_path is not None:
        try:
            if Path(os.path.abspath(os.fspath(resume_from))) == Path(
                os.path.abspath(os.fspath(report_path))
            ):
                stdout.write("error: --resume-from cannot equal --report\n")
                return 1
        except (TypeError, ValueError):
            stdout.write("error: invalid resume/report path\n")
            return 1

    # Discover projects (with optional filtering). ``os.scandir``
    # raises ``FileNotFoundError`` (a subclass of ``OSError``)
    # when the path does not exist, and ``NotADirectoryError``
    # (also ``OSError``) when the path is not a directory.
    try:
        project_paths = discover_projects(
            directory,
            include=include_patterns or None,
            exclude=exclude_patterns or None,
            recursive=recursive,
        )
    except (OSError, NotADirectoryError) as exc:
        stdout.write(f"error: {exc}\n")
        return 1

    selected_project_count = len(project_paths)

    resume = None
    if resume_from is not None:
        try:
            resume = plan_batch_resume(
                project_paths, report_loader(resume_from),
            )
        except (OSError, ValueError, TypeError) as exc:
            stdout.write(f"error: {exc}\n")
            return 1

    if dry_run:
        # Dry-run is a successful preview. Empty selection is
        # valid; never written as a report. Never invoke
        # ``load_project`` or ``replay_project``.
        dry_result = BatchDryRunResult(
            directory=Path(str(directory)), mode=mode,
            recursive=recursive, include=tuple(include_patterns),
            exclude=tuple(exclude_patterns),
            projects=tuple(Path(p) for p in (resume.pending_projects if resume else project_paths)),
            selected_projects=tuple(Path(p) for p in project_paths),
            skipped_projects=tuple(Path(p) for p in (resume.skipped_projects if resume else ())),
            pending_projects=tuple(Path(p) for p in (resume.pending_projects if resume else project_paths)),
            resume_applied=resume_from is not None,
            retries=retries if retries else None,
            max_attempts=(retries + 1) if retries else None,
            retry_configured=bool(retries),
            operational_summary_available=True,
        )
        if resume_from is not None:
            for path in dry_result.skipped_projects:
                stdout.write(f"{path}: SKIP (previous success)\n")
            project_paths = list(resume.pending_projects)
        for line in _format_dry_run_summary(
            mode, project_paths, recursive,
            include_patterns, exclude_patterns,
        ):
            stdout.write(f"{line}\n")
        if resume_from is not None:
            stdout.write(f"  Selected: {len(dry_result.selected_projects)}\n")
            stdout.write(f"  Skipped: {len(dry_result.skipped_projects)}\n")
            stdout.write(f"  Pending: {len(dry_result.pending_projects)}\n")
        return 0

    if resume is not None:
        project_paths = list(resume.pending_projects)

    if not project_paths:
        if resume is not None and resume.selected_projects:
            stdout.write("\nSummary:\n  Projects: 0\n  Succeeded: 0\n  Failed: 0\n\n")
            return 0
        # Distinguish between "no eligible files on disk" and
        # "filters selected zero files" with a deterministic
        # message that mentions the active filters when relevant.
        if include_patterns or exclude_patterns:
            stdout.write(
                f"error: no project JSON files matched the active "
                f"filters in {directory!r}\n"
            )
        else:
            stdout.write(
                f"error: no eligible project JSON files found in "
                f"{directory!r}\n"
            )
        return 1

    results: List[BatchProjectResult] = []
    if resume is not None:
        for path in resume.skipped_projects:
            stdout.write(f"{path}: SKIP (previous success)\n")
    for path in project_paths:
        attempt_history = []
        for attempt in range(retries + 1):
            if mode == VALIDATE_MODE:
                result = _execute_validate(
                    path, load_project=load_project, stdout=stdout,
                )
            elif mode == SHOW_MODE:
                result = _execute_show(
                    path, load_project=load_project, stdout=stdout,
                )
            else:  # RUN_MODE
                result = _execute_run(
                    path,
                    load_project=load_project,
                    replay_project=replay_project,
                    stdout=stdout,
                )
            attempt_history.append(BatchAttemptResult(
                attempt=attempt + 1,
                success=result.success,
                error=result.error,
            ))
            if result.success or attempt == retries:
                result.attempt_history = tuple(attempt_history)
                results.append(result)
                break

    succeeded = sum(1 for r in results if r.success)
    failed = len(results) - succeeded
    operational_summary = build_batch_operational_summary(
        results,
        selected=(len(resume.selected_projects) if resume is not None
                  else selected_project_count),
        skipped=(len(resume.skipped_projects) if resume is not None else 0),
    )
    for line in _format_summary(
        len(results), succeeded, failed,
        operational_summary=operational_summary,
    ):
        stdout.write(f"{line}\n")

    # Optional report writing. The report is only written when
    # at least one project was executed (the early-exit cases
    # above already returned) and when ``report_path`` was
    # provided. The report is built and persisted by the
    # dedicated report layer; the batch layer does not own
    # JSON serialization.
    if report_path is not None and results:
        from .report import batch_result_to_report

        report = batch_result_to_report(mode, results)
        _default_report_writer(
            report, report_path, report_writer=report_writer,
        )

    return 0 if failed == 0 else 1


# --- Dry-run JSON serialization ---------------------------------------------


_DRY_RUN_JSON_INDENT = 2
_DRY_RUN_JSON_SORT_KEYS = False
_DRY_RUN_JSON_ENSURE_ASCII = False


_DRY_RUN_FIELDS_ORDER: Tuple[str, ...] = (
    "directory",
    "mode",
    "recursive",
    "include",
    "exclude",
    "projects",
)


def batch_dry_run_to_dict(result) -> dict:
    """Return a JSON-compatible dict representation of *result*.

    The dict is built in canonical key order so the resulting
    JSON is byte-deterministic. Path values are converted to
    deterministic strings using forward slashes (matching the
    PHASE-022 ``discover_projects`` convention). The
    ``include``, ``exclude``, and ``projects`` fields are
    converted to JSON arrays. No timestamps, UUIDs,
    environment data, or random values are introduced.

    Args:
        result: A :class:`BatchDryRunResult` instance.

    Returns:
        A new dict with the canonical top-level key order.

    Raises:
        BatchInputError: when *result* is not a
            :class:`BatchDryRunResult`.
    """
    if not isinstance(result, BatchDryRunResult):
        raise BatchInputError("result", result)
    data = {
        "directory": str(result.directory).replace(os.sep, "/"),
        "mode": result.mode,
        "recursive": bool(result.recursive),
        "include": list(result.include),
        "exclude": list(result.exclude),
        "projects": [
            str(p).replace(os.sep, "/") for p in result.projects
        ],
    }
    if result.operational_summary_available:
        summary = build_batch_operational_summary(
            (), selected=len(result.selected_projects),
            skipped=len(result.skipped_projects),
            pending=len(result.pending_projects), dry_run=True,
        )
        data.update({
            "selected": summary.selected,
            "skipped": summary.skipped,
            "pending": summary.pending,
            "executed": summary.executed,
            "succeeded": summary.succeeded,
            "failed": summary.failed,
            "retried": summary.retried,
            "total_attempts": summary.total_attempts,
        })
    if result.resume_applied:
        data.update({
            "selected_projects": [
                str(p).replace(os.sep, "/") for p in result.selected_projects
            ],
            "skipped_projects": [
                str(p).replace(os.sep, "/") for p in result.skipped_projects
            ],
            "pending_projects": [
                str(p).replace(os.sep, "/") for p in result.pending_projects
            ],
        })
    if result.retry_configured:
        data["retries"] = int(result.retries)
        data["max_attempts"] = int(result.max_attempts)
    return data


def batch_dry_run_to_json(result) -> str:
    """Return a deterministic JSON string for *result*.

    Uses ``indent=2``, ``sort_keys=False``, and
    ``ensure_ascii=False``. The returned string ends with
    exactly one trailing newline, matching the existing
    report and manifest JSON conventions.

    The serializer is pure: it never touches the file
    system, never mutates *result*, and never invokes any
    project, rendering, AI, or network code.
    """
    data = batch_dry_run_to_dict(result)
    return json.dumps(
        data,
        indent=_DRY_RUN_JSON_INDENT,
        sort_keys=_DRY_RUN_JSON_SORT_KEYS,
        ensure_ascii=_DRY_RUN_JSON_ENSURE_ASCII,
    ) + "\n"


__all__ = (
    "run_batch",
    "discover_projects",
    "BatchProjectResult",
    "BatchAttemptResult",
    "BatchResumeResult",
    "plan_batch_resume",
    "BatchInputError",
    "BATCH_MODES",
    "VALIDATE_MODE",
    "SHOW_MODE",
    "RUN_MODE",
    "BatchDryRunResult",
    "dry_run_batch",
    "batch_dry_run_to_dict",
    "batch_dry_run_to_json",
    "BatchOperationalSummary",
    "build_batch_operational_summary",
    "summarize_batch",
    "BatchResultExport",
    "export_batch_result",
    "batch_result_to_dict",
    "batch_result_to_json",
    "BatchResultValidation",
    "validate_batch_operational_summary",
    "validate_batch_results",
    "validate_batch_result_export",
    "validate_batch_result_export_or_raise",
    "_validate_retries",
)
