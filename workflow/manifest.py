"""TOONFLOW-PHASE-023 — Project Manifest & Batch Configuration Foundation.

This module is a thin configuration-and-orchestration layer on top of
the existing batch execution surface. A *batch manifest* is a small,
deterministic JSON document that names a directory, a batch mode, and
the batch filter / report options that should be applied to a single
batch execution. The manifest layer contains configuration and
orchestration only.

The manifest layer does NOT duplicate:

- project discovery (owned by :func:`workflow.batch.discover_projects`);
- include / exclude filtering (owned by :func:`workflow.batch.run_batch`);
- recursive discovery (owned by :func:`workflow.batch.run_batch`);
- project validation (owned by :func:`workflow.load_project`);
- project loading (owned by :func:`workflow.load_project`);
- schema migration (owned by :mod:`workflow.project_migrations`);
- project replay (owned by :func:`workflow.replay_project`);
- report generation (owned by :mod:`workflow.report`);
- rendering logic (owned by :mod:`toonflow_ai.generation.*`);
- Blender logic (owned by :mod:`toonflow_ai.generation.*`);
- AI logic (owned by :mod:`ai.planner` and :mod:`ai.ollama_client`).

The manifest layer is also a ``bpy``-free, AI-free, networking-free,
threading-free module. It does not maintain mutable global state and
does not touch the file system beyond the explicitly requested save
and load operations.

Public API
----------

The single programmatic entry points are:

- :class:`BatchManifest` — the immutable configuration model.
- :func:`load_batch_manifest` — read and validate a manifest file.
- :func:`save_batch_manifest` — write a manifest to disk.
- :func:`run_batch_manifest` — delegate one batch execution to
  :func:`workflow.batch.run_batch`.

Schema
------

The manifest schema has its own version, separate from the project
schema. The current manifest schema version is 1. Unsupported
versions are rejected deterministically.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple, Union


# --- Schema -----------------------------------------------------------------


BATCH_MANIFEST_SCHEMA_VERSION = 1

SUPPORTED_BATCH_MANIFEST_SCHEMA_VERSIONS: Tuple[int, ...] = (1,)


# --- Errors -----------------------------------------------------------------


class ManifestInputError(ValueError):
    """A manifest-layer input is invalid.

    The manifest layer is the only layer that needs a *new* error
    class for its own arguments. All delegated errors propagate
    unchanged (``BatchInputError``, ``ProjectInputError``,
    ``ReportInputError``, ``OSError``, etc.).

    Attributes:
        parameter: The name of the offending parameter.
        value: The offending value (preserved as-given).
    """

    def __init__(self, parameter, value):
        self.parameter = parameter
        self.value = value
        super().__init__(
            f"Manifest input {parameter!r} is invalid: got {value!r}."
        )


# --- JSON formatting constants ----------------------------------------------


_INDENT = 2
_SORT_KEYS = False
_ENSURE_ASCII = False


# --- Validators -------------------------------------------------------------


def _validate_directory(value) -> str:
    """Validate the manifest ``directory`` value.

    The manifest layer does not require the directory to exist on
    disk; the actual existence check is owned by the batch layer.
    """
    if value is None:
        raise ManifestInputError("directory", value)
    if isinstance(value, bool):
        raise ManifestInputError("directory", value)
    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, os.PathLike):
        try:
            text = os.fspath(value)
        except (TypeError, ValueError):
            raise ManifestInputError("directory", value)
    elif isinstance(value, str):
        text = value
    else:
        raise ManifestInputError("directory", value)
    if not isinstance(text, str) or not text.strip():
        raise ManifestInputError("directory", value)
    return text


def _validate_mode(value) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestInputError("mode", value)
    if value not in ("validate", "show", "run"):
        raise ManifestInputError("mode", value)
    return value


def _validate_pattern_list(value, *, parameter) -> Tuple[str, ...]:
    """Normalize and validate an include / exclude pattern list."""
    if value is None:
        return ()
    if isinstance(value, bool):
        raise ManifestInputError(parameter, value)
    if isinstance(value, str):
        if not value.strip():
            raise ManifestInputError(parameter, value)
        return (value,)
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for entry in value:
            if isinstance(entry, bool) or not isinstance(entry, str):
                raise ManifestInputError(parameter, value)
            if not entry.strip():
                raise ManifestInputError(parameter, value)
            out.append(entry)
        return tuple(out)
    raise ManifestInputError(parameter, value)


def _validate_recursive(value) -> bool:
    if isinstance(value, bool):
        return value
    raise ManifestInputError("recursive", value)


def _validate_report_path(value):
    """Validate the manifest ``report_path`` value.

    The manifest layer does not own report writing; it only checks
    that the value is ``None`` or a non-empty path-like value.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ManifestInputError("report_path", value)
    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, os.PathLike):
        try:
            text = os.fspath(value)
        except (TypeError, ValueError):
            raise ManifestInputError("report_path", value)
    elif isinstance(value, str):
        text = value
    else:
        raise ManifestInputError("report_path", value)
    if not isinstance(text, str) or not text.strip():
        raise ManifestInputError("report_path", value)
    return text


def _validate_schema_version(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestInputError("schema_version", value)
    if value not in SUPPORTED_BATCH_MANIFEST_SCHEMA_VERSIONS:
        raise ManifestInputError("schema_version", value)
    return int(value)


# --- Manifest model ---------------------------------------------------------


@dataclass(frozen=True)
class BatchManifest:
    """The deterministic, immutable configuration for one batch execution.

    Attributes:
        directory: The directory containing project JSON files. Stored
            exactly as configured; not resolved against the current
            working directory. Actual path interpretation is owned by
            the batch layer.
        mode: One of ``"validate"``, ``"show"``, or ``"run"``.
        include: Tuple of include glob patterns forwarded to
            :func:`workflow.batch.run_batch`.
        exclude: Tuple of exclude glob patterns forwarded to
            :func:`workflow.batch.run_batch`. Exclude wins over
            include in the batch layer.
        recursive: When ``True``, the batch layer walks
            subdirectories.
        report_path: Optional path to a deterministic JSON report
            produced by the batch layer. When ``None``, no report is
            written.
        schema_version: The manifest schema version. Defaults to
            :data:`BATCH_MANIFEST_SCHEMA_VERSION`.
    """

    directory: Union[str, os.PathLike]
    mode: str
    include: Tuple[str, ...] = ()
    exclude: Tuple[str, ...] = ()
    recursive: bool = False
    report_path: Union[str, os.PathLike, None] = None
    schema_version: int = BATCH_MANIFEST_SCHEMA_VERSION

    def __post_init__(self):
        # The fields are already type-annotated as immutable tuple
        # values, but ``__post_init__`` runs even when the caller
        # passes a list. Normalize them defensively and re-validate.
        normalized_dir = _validate_directory(self.directory)
        if normalized_dir is not self.directory:
            object.__setattr__(self, "directory", normalized_dir)
        normalized_mode = _validate_mode(self.mode)
        if normalized_mode is not self.mode:
            object.__setattr__(self, "mode", normalized_mode)
        normalized_include = _validate_pattern_list(
            self.include, parameter="include",
        )
        if normalized_include is not self.include:
            object.__setattr__(self, "include", normalized_include)
        normalized_exclude = _validate_pattern_list(
            self.exclude, parameter="exclude",
        )
        if normalized_exclude is not self.exclude:
            object.__setattr__(self, "exclude", normalized_exclude)
        normalized_recursive = _validate_recursive(self.recursive)
        if normalized_recursive is not self.recursive:
            object.__setattr__(self, "recursive", normalized_recursive)
        normalized_report = _validate_report_path(self.report_path)
        if normalized_report is not self.report_path:
            object.__setattr__(self, "report_path", normalized_report)
        normalized_version = _validate_schema_version(self.schema_version)
        if normalized_version is not self.schema_version:
            object.__setattr__(self, "schema_version", normalized_version)


# --- Serialization helpers --------------------------------------------------


_MANIFEST_FIELDS_ORDER: Tuple[str, ...] = (
    "schema_version",
    "directory",
    "mode",
    "include",
    "exclude",
    "recursive",
    "report_path",
)


def batch_manifest_to_dict(manifest: BatchManifest) -> dict:
    """Return a JSON-compatible dict representation of *manifest*.

    The returned dict contains only built-in Python types and uses
    the canonical top-level key order so the resulting JSON is
    byte-deterministic.
    """
    if not isinstance(manifest, BatchManifest):
        raise ManifestInputError("manifest", manifest)
    return {
        "schema_version": int(manifest.schema_version),
        "directory": manifest.directory,
        "mode": manifest.mode,
        "include": list(manifest.include),
        "exclude": list(manifest.exclude),
        "recursive": bool(manifest.recursive),
        "report_path": manifest.report_path,
    }


def batch_manifest_from_dict(data: Any) -> BatchManifest:
    """Reconstruct a :class:`BatchManifest` from a dict.

    Strictly rejects malformed input. The dict must already be
    JSON-decoded; this function does not parse JSON. Unknown
    top-level keys, missing required keys, and invalid field types
    are all rejected.
    """
    if not isinstance(data, dict):
        raise ManifestInputError("manifest", data)

    unknown = sorted(set(data) - set(_MANIFEST_FIELDS_ORDER))
    if unknown:
        raise ManifestInputError("manifest.unknown", tuple(unknown))

    missing = [f for f in _MANIFEST_FIELDS_ORDER if f not in data]
    if missing:
        raise ManifestInputError("manifest.missing", tuple(missing))

    schema_version = data["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ManifestInputError("schema_version", schema_version)
    if schema_version not in SUPPORTED_BATCH_MANIFEST_SCHEMA_VERSIONS:
        raise ManifestInputError("schema_version", schema_version)

    return BatchManifest(
        directory=data["directory"],
        mode=data["mode"],
        include=tuple(data["include"]),
        exclude=tuple(data["exclude"]),
        recursive=bool(data["recursive"]),
        report_path=data["report_path"],
        schema_version=int(schema_version),
    )


def batch_manifest_to_json(manifest: BatchManifest) -> str:
    """Serialize *manifest* to a deterministic JSON string.

    Uses ``indent=2``, ``sort_keys=False``, and
    ``ensure_ascii=False``. The returned string ends with exactly
    one trailing newline.
    """
    return json.dumps(
        batch_manifest_to_dict(manifest),
        indent=_INDENT,
        sort_keys=_SORT_KEYS,
        ensure_ascii=_ENSURE_ASCII,
    ) + "\n"


def batch_manifest_from_json(text: str) -> BatchManifest:
    """Reconstruct a :class:`BatchManifest` from a JSON string.

    Malformed JSON continues to raise the standard
    :class:`json.JSONDecodeError` unchanged. Malformed structure
    raises :class:`ManifestInputError`.
    """
    if not isinstance(text, str):
        raise ManifestInputError("json", text)
    if not text.strip():
        raise ManifestInputError("json", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise
    return batch_manifest_from_dict(data)


# --- Override layer ---------------------------------------------------------


# Allowed values for the ``mode`` override. The set is duplicated
# here (intentionally) rather than imported from :mod:`workflow.batch`
# so the override layer remains a thin, bpy-free, dependency-free
# configuration helper that does not require the batch module to
# be importable.
_OVERRIDE_MODES: Tuple[str, ...] = ("validate", "show", "run")


def _validate_override_directory(value):
    """Validate the optional ``directory`` override."""
    if value is None:
        return None
    return _validate_directory(value)


def _validate_override_mode(value):
    """Validate the optional ``mode`` override."""
    if value is None:
        return None
    return _validate_mode(value)


def _validate_override_recursive(value):
    """Validate the optional ``recursive`` override.

    The override is a *tri-state* value:

    - ``None`` — no override supplied.
    - ``True`` — explicit ``--recursive``.
    - ``False`` — explicit ``--no-recursive``.

    Truthiness is intentionally NOT used to distinguish these
    three states: ``False`` is a meaningful override that must
    win over a manifest value of ``True``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ManifestInputError("recursive", value)


def _validate_override_report_path(value):
    """Validate the optional ``report_path`` override."""
    if value is None:
        return None
    return _validate_report_path(value)


def _normalize_override_patterns(value, *, parameter) -> Optional[Tuple[str, ...]]:
    """Validate an optional include / exclude override.

    The override accepts:

    - ``None`` — no override supplied; the manifest's value is
      preserved.
    - a non-empty ``str`` — a one-element tuple.
    - a sequence of non-empty strings — a tuple in CLI order.

    The override is treated as a *complete replacement* for the
    manifest's include / exclude configuration. Empty sequences
    are rejected because they would be indistinguishable from
    "no override" at the call site.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ManifestInputError(parameter, value)
    if isinstance(value, str):
        if not value.strip():
            raise ManifestInputError(parameter, value)
        return (value,)
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            raise ManifestInputError(parameter, value)
        for entry in value:
            if isinstance(entry, bool) or not isinstance(entry, str):
                raise ManifestInputError(parameter, value)
            if not entry.strip():
                raise ManifestInputError(parameter, value)
        return tuple(value)
    raise ManifestInputError(parameter, value)


def apply_manifest_overrides(
    manifest: BatchManifest,
    *,
    directory=None,
    mode=None,
    include=None,
    exclude=None,
    recursive=None,
    report_path=None,
) -> BatchManifest:
    """Return a NEW :class:`BatchManifest` with selected fields overridden.

    The function is configuration only. It does not call any
    batch execution, project loading, or file system code. The
    original manifest is never mutated.

    Precedence for every field:

    1. The corresponding override argument when not ``None``.
    2. The manifest's existing value.
    3. The :class:`BatchManifest` model's default.

    For *recursive* the override is a tri-state value: ``None``
    means "no override supplied", ``True`` means "explicit
    --recursive", and ``False`` means "explicit --no-recursive".
    Truthiness is NOT used to detect the override, so an
    explicit ``False`` correctly overrides a manifest ``True``.

    For *include* and *exclude* the override is a complete
    replacement, not a merge. Multiple CLI patterns are
    preserved in the order they were supplied.

    Args:
        manifest: The base :class:`BatchManifest`.
        directory: Optional override for *manifest.directory*.
        mode: Optional override for *manifest.mode*. Must be
            one of ``"validate"``, ``"show"``, ``"run"``.
        include: Optional override for *manifest.include*; a
            string or sequence of strings. ``None`` preserves
            the manifest value.
        exclude: Optional override for *manifest.exclude*; a
            string or sequence of strings. ``None`` preserves
            the manifest value.
        recursive: Optional tri-state override for
            *manifest.recursive*. ``None`` preserves the
            manifest value; ``True`` and ``False`` are
            explicit overrides.
        report_path: Optional override for *manifest.report_path*.
            ``None`` preserves the manifest value.

    Returns:
        A new immutable :class:`BatchManifest` with the
        overrides applied. The returned value is never the same
        object as the input.

    Raises:
        ManifestInputError: when an override is invalid. The
            original manifest is unchanged.
    """
    if not isinstance(manifest, BatchManifest):
        raise ManifestInputError("manifest", manifest)

    new_directory = _validate_override_directory(directory)
    new_mode = _validate_override_mode(mode)
    new_include = _normalize_override_patterns(include, parameter="include")
    new_exclude = _normalize_override_patterns(exclude, parameter="exclude")
    new_recursive = _validate_override_recursive(recursive)
    new_report_path = _validate_override_report_path(report_path)

    return BatchManifest(
        directory=new_directory if new_directory is not None else manifest.directory,
        mode=new_mode if new_mode is not None else manifest.mode,
        include=new_include if new_include is not None else manifest.include,
        exclude=new_exclude if new_exclude is not None else manifest.exclude,
        recursive=new_recursive if new_recursive is not None else manifest.recursive,
        report_path=(
            new_report_path if new_report_path is not None
            else manifest.report_path
        ),
        schema_version=manifest.schema_version,
    )


# --- Path validation --------------------------------------------------------


def _validate_load_path(value) -> Path:
    if value is None:
        raise ManifestInputError("path", value)
    if isinstance(value, bool):
        raise ManifestInputError("path", value)
    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, os.PathLike):
        try:
            text = os.fspath(value)
        except (TypeError, ValueError):
            raise ManifestInputError("path", value)
    elif isinstance(value, str):
        text = value
    else:
        raise ManifestInputError("path", value)
    if not isinstance(text, str) or not text.strip():
        raise ManifestInputError("path", value)
    path = Path(text)
    if path.exists() and path.is_dir():
        raise ManifestInputError("path", value)
    return path


def _validate_save_path(value) -> Path:
    if value is None:
        raise ManifestInputError("path", value)
    if isinstance(value, bool):
        raise ManifestInputError("path", value)
    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, os.PathLike):
        try:
            text = os.fspath(value)
        except (TypeError, ValueError):
            raise ManifestInputError("path", value)
    elif isinstance(value, str):
        text = value
    else:
        raise ManifestInputError("path", value)
    if not isinstance(text, str) or not text.strip():
        raise ManifestInputError("path", value)
    return Path(text)


# --- File persistence -------------------------------------------------------


def save_batch_manifest(manifest: BatchManifest, path) -> Path:
    """Serialize *manifest* and write it to *path* as JSON.

    The target path's parent directories are created when missing.
    The file is overwritten deterministically in UTF-8 with exactly
    one trailing newline. The returned value is the absolute,
    resolved :class:`pathlib.Path`.
    """
    if not isinstance(manifest, BatchManifest):
        raise ManifestInputError("manifest", manifest)
    target = _validate_save_path(path)

    parent = target.parent
    if str(parent) and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)

    payload = batch_manifest_to_json(manifest)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)
    return target.resolve()


def load_batch_manifest(path) -> BatchManifest:
    """Load and validate a :class:`BatchManifest` from *path*."""
    target = _validate_load_path(path)
    with open(target, "r", encoding="utf-8") as fh:
        text = fh.read()
    return batch_manifest_from_json(text)


# --- Default delegation targets --------------------------------------------


def _default_run_batch(directory, mode, *, include, exclude, recursive,
                       report_path, load_project, replay_project, stdout,
                       report_writer, dry_run=False, resume_from=None,
                       report_loader=None, retries=None):
    """Delegate to :func:`workflow.batch.run_batch`."""
    from .batch import run_batch

    kwargs = dict(
        include=include,
        exclude=exclude,
        recursive=recursive,
        dry_run=dry_run,
        load_project=load_project,
        replay_project=replay_project,
        stdout=stdout,
        report_path=report_path,
        report_writer=report_writer,
    )
    if resume_from is not None:
        kwargs["resume_from"] = resume_from
    if report_loader is not None:
        kwargs["report_loader"] = report_loader
    if retries is not None:
        kwargs["retries"] = retries
    return run_batch(directory, mode, **kwargs)


def _default_dry_run_batch(directory, mode, *, include, exclude, recursive,
                            resume_from=None, report_loader=None, retries=None):
    """Delegate to :func:`workflow.batch.dry_run_batch`."""
    from .batch import dry_run_batch

    kwargs = dict(
        include=include,
        exclude=exclude,
        recursive=recursive,
    )
    if resume_from is not None:
        kwargs["resume_from"] = resume_from
    if report_loader is not None:
        kwargs["report_loader"] = report_loader
    if retries is not None:
        kwargs["retries"] = retries
    return dry_run_batch(directory, mode, **kwargs)


# --- Execution --------------------------------------------------------------


def run_batch_manifest(
    manifest: BatchManifest,
    *,
    run_batch: Callable = _default_run_batch,
    load_project: Optional[Callable] = None,
    replay_project: Optional[Callable] = None,
    stdout=None,
    report_writer: Optional[Callable] = None,
    dry_run: bool = False,
    resume_from=None,
    report_loader: Optional[Callable] = None,
    retries=None,
) -> int:
    """Delegate one batch execution to :func:`workflow.batch.run_batch`.

    The manifest layer is the only place where the manifest's
    configuration is translated into batch-layer arguments. The
    manifest layer does not call :func:`discover_projects` directly
    and does not call :func:`load_project` or :func:`replay_project`
    directly; all of those responsibilities belong to the batch
    layer.

    Args:
        manifest: A :class:`BatchManifest` instance.
        run_batch: Dependency-injection point replacing
            :func:`workflow.batch.run_batch`. Used by tests to
            observe the forwarded arguments without executing
            any batch logic.
        load_project: Forwarded to *run_batch* as
            ``load_project``. When ``None``, the batch layer's
            default is used.
        replay_project: Forwarded to *run_batch* as
            ``replay_project``. When ``None``, the batch layer's
            default is used.
        stdout: Forwarded to *run_batch* as ``stdout``. When
            ``None``, the batch layer defaults to
            :data:`sys.stdout`.
        report_writer: Forwarded to *run_batch* as
            ``report_writer``. When ``None``, the batch layer's
            default is used.
        dry_run: When ``True``, the delegated ``run_batch`` is
            invoked with ``dry_run=True``. The function still
            returns an integer exit code (always ``0`` when
            ``dry_run=True``). When ``False`` (the default),
            the existing behavior is preserved.

    Returns:
        The integer exit code produced by
        :func:`workflow.batch.run_batch`.

    Raises:
        ManifestInputError: when *manifest* is not a
            :class:`BatchManifest`.
        Any error from the delegated batch layer, propagated
        unchanged.
    """
    if not isinstance(manifest, BatchManifest):
        raise ManifestInputError("manifest", manifest)

    # Lazily import :data:`sys` so the module can be imported in
    # environments where ``sys`` is patched.
    import sys as _sys
    if stdout is None:
        stdout = _sys.stdout

    forwarded_load = load_project if load_project is not None else (lambda p: None)
    forwarded_replay = replay_project if replay_project is not None else (lambda proj: None)

    kwargs = dict(
        include=manifest.include,
        exclude=manifest.exclude,
        recursive=manifest.recursive,
        report_path=manifest.report_path,
        load_project=forwarded_load,
        replay_project=forwarded_replay,
        stdout=stdout,
        report_writer=report_writer,
    )
    if dry_run:
        kwargs["dry_run"] = True
    if resume_from is not None:
        kwargs["resume_from"] = resume_from
    if report_loader is not None:
        kwargs["report_loader"] = report_loader
    if retries is not None:
        kwargs["retries"] = retries
    return run_batch(manifest.directory, manifest.mode, **kwargs)


def dry_run_batch_manifest(
    manifest: BatchManifest,
    *,
    dry_run_batch: Callable = _default_dry_run_batch,
    resume_from=None,
    report_loader: Optional[Callable] = None,
    retries=None,
) -> "BatchDryRunResult":
    """Return the deterministic preview of a manifest execution.

    The function applies the manifest's already-resolved
    configuration to a dry-run selection. The manifest
    instance is never mutated; the file on disk is never
    written.

    Dry-run is an execution-time concern only. The
    :class:`BatchManifest` schema intentionally does NOT
    persist a ``dry_run`` field; the option lives on this
    function and on the ``manifest`` subcommand's
    ``--dry-run`` flag.

    Args:
        manifest: A :class:`BatchManifest` instance.
        dry_run_batch: Dependency-injection point replacing
            :func:`workflow.batch.dry_run_batch`. Used by
            tests to observe the forwarded arguments without
            performing real discovery.

    Returns:
        A :class:`workflow.batch.BatchDryRunResult` produced
        by the delegated dry-run call.

    Raises:
        ManifestInputError: when *manifest* is not a
            :class:`BatchManifest`.
        Any error from the delegated dry-run call, propagated
        unchanged.
    """
    if not isinstance(manifest, BatchManifest):
        raise ManifestInputError("manifest", manifest)

    kwargs = dict(
        include=manifest.include,
        exclude=manifest.exclude,
        recursive=manifest.recursive,
    )
    if resume_from is not None:
        kwargs["resume_from"] = resume_from
    if report_loader is not None:
        kwargs["report_loader"] = report_loader
    if retries is not None:
        kwargs["retries"] = retries
    return dry_run_batch(manifest.directory, manifest.mode, **kwargs)


__all__ = (
    "BATCH_MANIFEST_SCHEMA_VERSION",
    "BatchManifest",
    "ManifestInputError",
    "batch_manifest_to_dict",
    "batch_manifest_from_dict",
    "batch_manifest_to_json",
    "batch_manifest_from_json",
    "save_batch_manifest",
    "load_batch_manifest",
    "run_batch_manifest",
    "apply_manifest_overrides",
    "dry_run_batch_manifest",
)
