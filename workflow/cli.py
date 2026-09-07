"""TOONFLOW-PHASE-019 — Project CLI & Batch Runner Foundation.

This module is a thin orchestration layer on top of the existing
TOONFLOW project APIs. It exposes a small, deterministic command-line
interface for working with persistent TOONFLOW project JSON files.

The CLI does NOT duplicate:

- project validation (owned by :func:`workflow.load_project`)
- schema migration (owned by :mod:`workflow.project_migrations`)
- JSON parsing (owned by :func:`workflow.project_from_json`)
- multi-shot orchestration (owned by the multi-shot workflow)
- single-shot orchestration (owned by the single-shot workflow)
- rendering logic (owned by :mod:`toonflow_ai.generation.rendering`)
- Blender logic (owned by :mod:`toonflow_ai.generation.*`)
- AI logic (owned by :mod:`ai.planner` and :mod:`ai.ollama_client`)

The CLI is also a bpy-free, AI-free, networking-free module. The
``run`` command delegates strictly to
:func:`workflow.replay_project`, which in turn delegates to the
existing multi-shot workflow. No lower-level workflow function is
called directly from this module.

Public API
----------

The single programmatic entry point is :func:`main`:

    workflow.cli.main(argv=None) -> int

*argv* accepts an optional iterable of CLI tokens (for tests). When
omitted, ``sys.argv[1:]`` is used. The function never calls
``sys.exit`` and never mutates ``sys.argv``. Tests inject the
``load_project`` and ``replay_project`` callables through the
keyword arguments of the same name.
"""

import argparse
import sys
from typing import Any, Callable, List, Optional, Sequence, TextIO


# --- Default delegation targets -------------------------------------------


def _default_load_project(path):
    """Delegate to :func:`workflow.load_project`."""
    from .project import load_project

    return load_project(path)


def _default_replay_project(project, *, workflow_callable=None):
    """Delegate to :func:`workflow.replay_project`."""
    from .project import replay_project

    return replay_project(project, workflow_callable=workflow_callable)


def _default_verify_blender_runtime(
    *,
    blender_executable=None,
    timeout_seconds=30,
):
    """Delegate to :func:`workflow.verification.verify_blender_runtime`."""
    from .verification import verify_blender_runtime

    return verify_blender_runtime(
        blender_executable=blender_executable,
        timeout_seconds=timeout_seconds,
    )


def _default_run_batch(directory, mode, *, load_project, replay_project,
                      stdout, report_path=None, report_writer=None,
                      include=None, exclude=None, recursive=False,
                      dry_run=False, resume_from=None, report_loader=None,
                      retries=0):
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
    if retries:
        kwargs["retries"] = retries
    return run_batch(directory, mode, **kwargs)


def _default_load_batch_manifest(path):
    """Delegate to :func:`workflow.manifest.load_batch_manifest`."""
    from .manifest import load_batch_manifest

    return load_batch_manifest(path)


def _default_run_batch_manifest(
    manifest, *, run_batch, load_project, replay_project,
    stdout, report_writer, dry_run=False, resume_from=None,
    report_loader=None, retries=0,
):
    """Delegate to :func:`workflow.manifest.run_batch_manifest`."""
    from .manifest import run_batch_manifest

    kwargs = dict(
        run_batch=run_batch,
        load_project=load_project,
        replay_project=replay_project,
        stdout=stdout,
        report_writer=report_writer,
        dry_run=dry_run,
    )
    if resume_from is not None:
        kwargs["resume_from"] = resume_from
    if report_loader is not None:
        kwargs["report_loader"] = report_loader
    if retries:
        kwargs["retries"] = retries
    return run_batch_manifest(manifest, **kwargs)


def _default_dry_run_batch_manifest(manifest, *, dry_run_batch=None,
                                    resume_from=None, report_loader=None,
                                    retries=None):
    """Delegate to :func:`workflow.manifest.dry_run_batch_manifest`."""
    from .manifest import dry_run_batch_manifest

    kwargs = {}
    if dry_run_batch is not None:
        kwargs["dry_run_batch"] = dry_run_batch
    if resume_from is not None:
        kwargs["resume_from"] = resume_from
    if report_loader is not None:
        kwargs["report_loader"] = report_loader
    if retries is not None:
        kwargs["retries"] = retries
    return dry_run_batch_manifest(manifest, **kwargs)


def _default_load_report(path):
    from .report import load_report

    return load_report(path)


def _format_dry_run_result(result) -> str:
    """Return a deterministic multi-line representation of *result*."""
    lines = [
        "Dry-run:",
        f"  Mode: {result.mode}",
        f"  Recursive: {bool(result.recursive)}",
        f"  Include: {list(result.include)}",
        f"  Exclude: {list(result.exclude)}",
        f"  Projects: {len(result.projects)}",
    ]
    for path in result.projects:
        lines.append(f"  - {path}")
    if getattr(result, "operational_summary_available", False):
        lines.extend([
            f"  Selected: {len(result.selected_projects)}",
            f"  Skipped: {len(result.skipped_projects)}",
            f"  Pending: {len(result.pending_projects)}",
            "  Executed: 0",
            "  Succeeded: 0",
            "  Failed: 0",
            "  Retried: 0",
            "  Total attempts: 0",
        ])
    if getattr(result, "retries", None) is not None:
        lines.append(f"  Retries: {result.retries}")
        lines.append(f"  Max attempts: {result.max_attempts}")
    if getattr(result, "resume_applied", False) and not getattr(
        result, "operational_summary_available", False
    ):
        lines.extend([
            f"  Selected: {len(result.selected_projects)}",
            f"  Skipped: {len(result.skipped_projects)}",
            f"  Pending: {len(result.pending_projects)}",
        ])
    return "\n".join(lines) + "\n"


def _default_dry_run_to_json(result) -> str:
    """Delegate to :func:`workflow.batch.batch_dry_run_to_json`."""
    from .batch import batch_dry_run_to_json
    return batch_dry_run_to_json(result)


def _default_apply_manifest_overrides(manifest, **overrides):
    """Delegate to :func:`workflow.manifest.apply_manifest_overrides`."""
    from .manifest import apply_manifest_overrides

    return apply_manifest_overrides(manifest, **overrides)


def _nonnegative_int(value):
    """Parse a non-negative integer for argparse."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("retries must be a non-negative integer")
    if parsed < 0:
        raise argparse.ArgumentTypeError("retries must be a non-negative integer")
    return parsed


# --- Argument parser -------------------------------------------------------


def _build_parser():
    """Build and return the top-level :class:`argparse.ArgumentParser`.

    The parser exposes three subcommands, each taking a single
    positional ``path`` argument. The parser raises standard
    :class:`argparse.ArgumentError` / exits with code 2 for
    invalid usage, which is exactly what the tests expect.
    """
    parser = argparse.ArgumentParser(
        prog="python -m workflow",
        description=(
            "TOONFLOW project CLI: validate, show, or run a "
            "persistent TOONFLOW project JSON file."
        ),
        # ``exit_on_error=False`` keeps ``parse_args`` from calling
        # ``sys.exit`` on argument-parsing failure; the CLI entry
        # point converts the raised ``ArgumentError`` to a return
        # code so unit tests can observe the behavior without
        # sys.exit side effects.
        exit_on_error=False,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    p_validate = subparsers.add_parser(
        "validate",
        help="Load and validate a project file.",
        description=(
            "Load a project file, transparently applying any "
            "schema migration, and report a deterministic "
            "summary."
        ),
    )
    p_validate.add_argument(
        "path",
        help="Path to the project JSON file.",
    )

    p_show = subparsers.add_parser(
        "show",
        help="Display a deterministic project summary.",
        description=(
            "Load a project file and print a deterministic, "
            "human-readable summary including every shot."
        ),
    )
    p_show.add_argument(
        "path",
        help="Path to the project JSON file.",
    )

    p_run = subparsers.add_parser(
        "run",
        help="Replay (run) a project file through the workflow.",
        description=(
            "Load a project file and replay it through the "
            "existing multi-shot workflow."
        ),
    )
    p_run.add_argument(
        "path",
        help="Path to the project JSON file.",
    )

    p_batch = subparsers.add_parser(
        "batch",
        help="Run a CI-friendly batch over a directory of project files.",
        description=(
            "Discover project JSON files in a directory and run "
            "the chosen mode (validate, show, or run) on each, "
            "strictly sequentially, in deterministic "
            "lexicographic order."
        ),
    )
    p_batch.add_argument(
        "directory",
        help="Path to the directory of project JSON files.",
    )
    p_batch.add_argument(
        "mode",
        choices=("validate", "show", "run"),
        help="Batch mode to apply to every discovered project.",
    )
    p_batch.add_argument(
        "--report",
        dest="report",
        default=None,
        help=(
            "Optional path to a deterministic JSON report "
            "(PHASE-021). When omitted, no report is written."
        ),
    )
    p_batch.add_argument(
        "--resume-from",
        dest="resume_from",
        default=None,
        help="Optional existing BatchReport JSON used for continuation.",
    )
    p_batch.add_argument(
        "--retries", type=_nonnegative_int, default=None,
        help="Number of additional attempts after the first attempt.",
    )
    p_batch.add_argument(
        "--include",
        dest="include",
        action="append",
        default=None,
        help=(
            "Optional include glob pattern. May be repeated to "
            "add multiple include patterns. Patterns match the "
            "relative path from the batch directory (forward "
            "slashes). PHASE-022."
        ),
    )
    p_batch.add_argument(
        "--exclude",
        dest="exclude",
        action="append",
        default=None,
        help=(
            "Optional exclude glob pattern. May be repeated to "
            "add multiple exclude patterns. Exclude wins over "
            "include. PHASE-022."
        ),
    )
    p_batch.add_argument(
        "--recursive",
        dest="recursive",
        action="store_true",
        default=False,
        help=(
            "When set, walk into subdirectories to discover "
            "project JSON files. By default, only direct "
            "children of the directory are considered. "
            "PHASE-022."
        ),
    )
    p_batch.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help=(
            "Preview the batch selection without loading, "
            "replaying, or rendering any project. The "
            "existing discovery and filtering semantics are "
            "reused; no report is written. PHASE-025."
        ),
    )
    p_batch.add_argument(
        "--json",
        dest="dry_run_json",
        action="store_true",
        default=False,
        help=(
            "Emit the dry-run result as deterministic JSON "
            "on stdout. Requires --dry-run. Plain-text "
            "output is suppressed when --json is supplied. "
            "PHASE-026."
        ),
    )

    p_manifest = subparsers.add_parser(
        "manifest",
        help="Run a batch from a deterministic JSON manifest file.",
        description=(
            "Load a deterministic JSON batch manifest, validate "
            "it, and delegate one batch execution to the "
            "existing batch layer. The manifest layer is "
            "configuration and orchestration only. PHASE-023, "
            "PHASE-024."
        ),
    )
    p_manifest.add_argument(
        "path",
        help="Path to the batch manifest JSON file.",
    )
    p_manifest.add_argument(
        "--directory",
        dest="manifest_directory",
        default=None,
        help=(
            "Override the manifest's batch directory. The "
            "manifest JSON file itself is never modified. "
            "PHASE-024."
        ),
    )
    p_manifest.add_argument(
        "--mode",
        dest="manifest_mode",
        choices=("validate", "show", "run"),
        default=None,
        help=(
            "Override the manifest's batch mode. PHASE-024."
        ),
    )
    p_manifest.add_argument(
        "--include",
        dest="manifest_include",
        action="append",
        default=None,
        help=(
            "Override the manifest's include glob patterns. "
            "May be repeated. Replaces (does not merge with) "
            "the manifest's include list. PHASE-024."
        ),
    )
    p_manifest.add_argument(
        "--exclude",
        dest="manifest_exclude",
        action="append",
        default=None,
        help=(
            "Override the manifest's exclude glob patterns. "
            "May be repeated. Replaces (does not merge with) "
            "the manifest's exclude list. PHASE-024."
        ),
    )
    p_manifest.add_argument(
        "--recursive",
        dest="manifest_recursive",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Override the manifest's recursive flag. Use "
            "--no-recursive to explicitly disable recursion. "
            "When neither flag is supplied, the manifest's "
            "value is preserved. PHASE-024."
        ),
    )
    p_manifest.add_argument(
        "--report",
        dest="manifest_report",
        default=None,
        help=(
            "Override the manifest's report path. PHASE-024."
        ),
    )
    p_manifest.add_argument(
        "--resume-from",
        dest="manifest_resume_from",
        default=None,
        help="Optional existing BatchReport JSON used for continuation.",
    )
    p_manifest.add_argument(
        "--retries", dest="manifest_retries", type=_nonnegative_int, default=None,
        help="Number of additional attempts after the first attempt.",
    )
    p_manifest.add_argument(
        "--dry-run",
        dest="manifest_dry_run",
        action="store_true",
        default=False,
        help=(
            "Preview the manifest-driven batch selection "
            "without loading, replaying, or rendering any "
            "project. CLI overrides are applied first; the "
            "manifest file is never modified. PHASE-025."
        ),
    )
    p_manifest.add_argument(
        "--json",
        dest="manifest_dry_run_json",
        action="store_true",
        default=False,
        help=(
            "Emit the dry-run result as deterministic JSON "
            "on stdout. Requires --dry-run. Plain-text "
            "output is suppressed when --json is supplied. "
            "PHASE-026."
        ),
    )

    p_verify = subparsers.add_parser(
        "verify-blender",
        help="Verify the TOONFLOW AI add-on package in Blender.",
        description=(
            "Run a deterministic verification contract against "
            "the TOONFLOW AI add-on package inside a real "
            "Blender runtime. This command does NOT modify "
            "project source files, batch semantics, or any "
            "existing contracts. PHASE-034."
        ),
    )
    p_verify.add_argument(
        "--blender",
        dest="blender_executable",
        default=None,
        help=(
            "Path to the Blender executable. If not provided, "
            "the verifier will attempt to auto-detect Blender "
            "in the system PATH and common installation paths."
        ),
    )
    p_verify.add_argument(
        "--json",
        dest="verify_json",
        action="store_true",
        default=False,
        help=(
            "Emit the verification result as deterministic JSON "
            "on stdout. Plain-text output is suppressed when "
            "--json is supplied."
        ),
    )
    p_verify.add_argument(
        "--timeout",
        dest="timeout_seconds",
        type=int,
        default=30,
        help=(
            "Timeout in seconds for the Blender verification "
            "process. Default: 30."
        ),
    )

    return parser


# --- Output helpers --------------------------------------------------------


def _format_validate_output(project) -> str:
    """Return the deterministic ``validate`` summary for *project*."""
    lines = [
        "Project is valid",
        f"Name: {project.name}",
        f"Schema version: {project.schema_version}",
        f"Shots: {len(project.shots)}",
    ]
    return "\n".join(lines) + "\n"


def _format_show_output(project) -> str:
    """Return the deterministic ``show`` summary for *project*."""
    lines = [
        f"Name: {project.name}",
        f"Schema version: {project.schema_version}",
        f"Description: {project.description}",
        f"Shots: {len(project.shots)}",
    ]
    for index, shot in enumerate(project.shots):
        lines.append(
            f"Shot {index}: "
            f"concept={shot.concept!r} "
            f"animation={shot.animation!r} "
            f"lip_sync={shot.lip_sync!r} "
            f"output_path={shot.output_path!r}"
        )
    return "\n".join(lines) + "\n"


def _format_run_output(project, result) -> str:
    """Return the deterministic ``run`` summary for *result*."""
    lines = [
        f"Project: {project.name}",
        f"Shots: {len(project.shots)}",
    ]
    # Use the multi-shot result's ``output_paths`` when available so
    # the CLI displays paths in execution order. Fall back to an
    # empty tuple when the result is missing or shaped differently.
    output_paths = tuple(getattr(result, "output_paths", ()) or ())
    for index, output_path in enumerate(output_paths):
        lines.append(f"Shot {index}: output_path={output_path!r}")
    return "\n".join(lines) + "\n"


# --- Command handlers ------------------------------------------------------


def _cmd_validate(
    path,
    *,
    load_project: Callable = _default_load_project,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run the ``validate`` command. Returns the exit code.

    Expected project / schema / IO errors are converted to a
    deterministic error message on *stdout* and a non-zero exit
    code. Unexpected errors propagate (no broad catch).
    """
    try:
        project = load_project(path)
    except (OSError, ValueError, TypeError) as exc:
        stdout.write(f"error: {exc}\n")
        return 1
    stdout.write(_format_validate_output(project))
    return 0


def _cmd_show(
    path,
    *,
    load_project: Callable = _default_load_project,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run the ``show`` command. Returns the exit code.

    Expected project / schema / IO errors are converted to a
    deterministic error message on *stdout* and a non-zero exit
    code. Unexpected errors propagate (no broad catch).
    """
    try:
        project = load_project(path)
    except (OSError, ValueError, TypeError) as exc:
        stdout.write(f"error: {exc}\n")
        return 1
    stdout.write(_format_show_output(project))
    return 0


def _cmd_run(
    path,
    *,
    load_project: Callable = _default_load_project,
    replay_project: Callable = _default_replay_project,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run the ``run`` command. Returns the exit code.

    The handler loads the project and then delegates to
    :func:`workflow.replay_project` exactly once. No lower-level
    workflow function is called directly. Expected project /
    workflow / IO errors are converted to a deterministic error
    message on *stdout* and a non-zero exit code.
    """
    try:
        project = load_project(path)
    except (OSError, ValueError, TypeError) as exc:
        stdout.write(f"error: {exc}\n")
        return 1
    try:
        result = replay_project(project)
    except (OSError, ValueError, TypeError) as exc:
        stdout.write(f"error: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary, see comment
        # The CLI is the process boundary: any uncaught exception
        # from the delegated workflow must surface as a
        # deterministic non-zero exit code with a readable
        # message instead of a raw traceback. The underlying
        # exception type and message are preserved in the output;
        # only the stack trace is elided.
        stdout.write(f"error: {type(exc).__name__}: {exc}\n")
        return 1
    stdout.write(_format_run_output(project, result))
    return 0


# --- Command dispatch ------------------------------------------------------


def _dispatch(
    args,
    *,
    load_project: Callable,
    replay_project: Callable,
    stdout: TextIO,
    run_batch: Callable = _default_run_batch,
    load_batch_manifest: Callable = _default_load_batch_manifest,
    run_batch_manifest: Callable = _default_run_batch_manifest,
    apply_manifest_overrides: Callable = _default_apply_manifest_overrides,
    dry_run_batch_manifest: Callable = _default_dry_run_batch_manifest,
    dry_run_to_json: Callable = _default_dry_run_to_json,
    load_report: Callable = _default_load_report,
    verify_blender_runtime: Callable = _default_verify_blender_runtime,
) -> int:
    """Dispatch parsed argparse *args* to the matching command handler."""
    if args.command == "validate":
        return _cmd_validate(
            args.path,
            load_project=load_project,
            stdout=stdout,
        )
    if args.command == "show":
        return _cmd_show(
            args.path,
            load_project=load_project,
            stdout=stdout,
        )
    if args.command == "run":
        return _cmd_run(
            args.path,
            load_project=load_project,
            replay_project=replay_project,
            stdout=stdout,
        )
    if args.command == "batch":
        # ``--json`` requires ``--dry-run``. Validate up
        # front so the failure mode is consistent with
        # argparse-style exit code 2.
        if getattr(args, "dry_run_json", False) and not getattr(
            args, "dry_run", False
        ):
            stdout.write(
                "error: --json requires --dry-run\n"
            )
            return 2
        if getattr(args, "dry_run", False):
            # Reuse the existing batch-layer dry-run entry
            # point so the selection semantics stay aligned
            # with the plain-text dry-run path.
            from .batch import dry_run_batch
            try:
                retry_kwargs = {}
                if getattr(args, "retries", None) is not None:
                    retry_kwargs["retries"] = args.retries
                result = dry_run_batch(
                    args.directory,
                    args.mode,
                    recursive=getattr(args, "recursive", False),
                    include=getattr(args, "include", None),
                    exclude=getattr(args, "exclude", None),
                    **({"resume_from": args.resume_from,
                        "report_loader": load_report}
                       if getattr(args, "resume_from", None) is not None
                       else {}),
                    **retry_kwargs,
                )
            except (OSError, ValueError, TypeError) as exc:
                stdout.write(f"error: {exc}\n")
                return 1
            if getattr(args, "dry_run_json", False):
                stdout.write(dry_run_to_json(result))
                return 0
            stdout.write(_format_dry_run_result(result))
            return 0
        kwargs = dict(
            load_project=load_project,
            replay_project=replay_project,
            stdout=stdout,
            report_path=getattr(args, "report", None),
            include=getattr(args, "include", None),
            exclude=getattr(args, "exclude", None),
            recursive=getattr(args, "recursive", False),
            dry_run=False,
        )
        if getattr(args, "resume_from", None) is not None:
            kwargs["resume_from"] = args.resume_from
            kwargs["report_loader"] = load_report
        if getattr(args, "retries", None) is not None:
            kwargs["retries"] = args.retries
        return run_batch(args.directory, args.mode, **kwargs)
    if args.command == "manifest":
        # ``--json`` requires ``--dry-run`` on the manifest
        # subcommand as well.
        if getattr(args, "manifest_dry_run_json", False) and not getattr(
            args, "manifest_dry_run", False
        ):
            stdout.write(
                "error: --json requires --dry-run\n"
            )
            return 2
        try:
            manifest = load_batch_manifest(args.path)
        except (OSError, ValueError, TypeError) as exc:
            stdout.write(f"error: {exc}\n")
            return 1
        try:
            effective = apply_manifest_overrides(
                manifest,
                directory=getattr(args, "manifest_directory", None),
                mode=getattr(args, "manifest_mode", None),
                include=getattr(args, "manifest_include", None),
                exclude=getattr(args, "manifest_exclude", None),
                recursive=getattr(args, "manifest_recursive", None),
                report_path=getattr(args, "manifest_report", None),
            )
        except (ValueError, TypeError) as exc:
            stdout.write(f"error: {exc}\n")
            return 1
        if getattr(args, "manifest_dry_run", False):
            try:
                retry_kwargs = {}
                if getattr(args, "manifest_retries", None) is not None:
                    retry_kwargs["retries"] = args.manifest_retries
                result = dry_run_batch_manifest(
                    effective,
                    **({"resume_from": args.manifest_resume_from,
                        "report_loader": load_report}
                       if getattr(args, "manifest_resume_from", None) is not None
                              else {}),
                          **retry_kwargs,
                )
            except (OSError, ValueError, TypeError) as exc:
                stdout.write(f"error: {exc}\n")
                return 1
            if getattr(args, "manifest_dry_run_json", False):
                stdout.write(dry_run_to_json(result))
                return 0
            stdout.write(_format_dry_run_result(result))
            return 0
        kwargs = dict(
            run_batch=run_batch,
            load_project=load_project,
            replay_project=replay_project,
            stdout=stdout,
            report_writer=None,
            dry_run=False,
        )
        if getattr(args, "manifest_resume_from", None) is not None:
            kwargs["resume_from"] = args.manifest_resume_from
            kwargs["report_loader"] = load_report
        if getattr(args, "manifest_retries", None) is not None:
            kwargs["retries"] = args.manifest_retries
        return run_batch_manifest(effective, **kwargs)
    elif args.command == "verify-blender":
        try:
            result = verify_blender_runtime(
                blender_executable=getattr(args, "blender_executable", None),
                timeout_seconds=getattr(args, "timeout_seconds", 30),
            )
            if getattr(args, "verify_json", False):
                from .verification import blender_verification_to_json
                stdout.write(blender_verification_to_json(result))
            else:
                lines = [
                    f"Blender Runtime Verification: {result.status}",
                    f"Boundary: {result.boundary_achieved}",
                    f"Message: {result.message}",
                ]
                if result.blender_version:
                    lines.append(f"Blender Version: {result.blender_version}")
                if result.verification_attempted:
                    lines.append("Verification Attempted: Yes")
                else:
                    lines.append("Verification Attempted: No")
                stdout.write("\n".join(lines) + "\n")
            return 0 if result.status == "PASSED" else 1
        except Exception as exc:  # pragma: no cover - defensive
            stdout.write(f"error: {exc}\n")
            return 1
    # argparse rejects unknown commands, so this branch is defensive.
    stdout.write(f"error: unknown command: {args.command!r}\n")
    return 2


# --- Public entry point ----------------------------------------------------


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    load_project: Callable = _default_load_project,
    replay_project: Callable = _default_replay_project,
    stdout: Optional[TextIO] = None,
    run_batch: Callable = _default_run_batch,
    load_batch_manifest: Callable = _default_load_batch_manifest,
    run_batch_manifest: Callable = _default_run_batch_manifest,
    apply_manifest_overrides: Callable = _default_apply_manifest_overrides,
    dry_run_batch_manifest: Callable = _default_dry_run_batch_manifest,
    dry_run_to_json: Callable = _default_dry_run_to_json,
    load_report: Callable = _default_load_report,
    verify_blender_runtime: Callable = _default_verify_blender_runtime,
) -> int:
    """Programmatic entry point for the TOONFLOW project CLI.

    Args:
        argv: Optional sequence of CLI tokens. When ``None``, uses
            ``sys.argv[1:]``. The function never mutates
            ``sys.argv``.
        load_project: Dependency-injection point replacing
            :func:`workflow.load_project`. Tests use this to
            exercise the CLI without a real file system.
        replay_project: Dependency-injection point replacing
            :func:`workflow.replay_project`. Tests use this to
            exercise the ``run`` command without Blender.
        stdout: Optional stream for human-readable output. When
            ``None``, defaults to :data:`sys.stdout`.
        run_batch: Dependency-injection point replacing
            :func:`workflow.batch.run_batch`. Used by the
            ``batch`` subcommand and by the manifest subcommand.
        load_batch_manifest: Dependency-injection point replacing
            :func:`workflow.manifest.load_batch_manifest`. Used
            by the ``manifest`` subcommand.
        run_batch_manifest: Dependency-injection point replacing
            :func:`workflow.manifest.run_batch_manifest`. Used by
            the ``manifest`` subcommand.
        verify_blender_runtime: Dependency-injection point replacing
            :func:`workflow.verification.verify_blender_runtime`.
            Used by the ``verify-blender`` subcommand. PHASE-034.

    Returns:
        An integer exit code. ``0`` on success, non-zero on
        invalid arguments or expected project / workflow
        failure. Unexpected errors follow normal Python CLI
        behavior (no broad catch).
    """
    if stdout is None:
        stdout = sys.stdout

    parser = _build_parser()
    tokens = list(argv) if argv is not None else None
    try:
        args = parser.parse_args(tokens)
    except SystemExit as exc:
        # Belt-and-suspenders: even with exit_on_error=False, an
        # explicit ``parser.error`` call can still raise
        # SystemExit. Convert any such exit to a plain integer
        # return so ``main`` is safe to call from tests and never
        # raises SystemExit.
        code = exc.code
        if isinstance(code, int):
            return code
        return 2
    except argparse.ArgumentError as exc:
        # Argument parsing failed. Report a deterministic error
        # and return the conventional argparse exit code (2).
        stdout.write(f"error: {exc}\n")
        return 2
    if not args.command:
        stdout.write("error: the following arguments are required: command\n")
        return 2
    return _dispatch(
        args,
        load_project=load_project,
        replay_project=replay_project,
        stdout=stdout,
        run_batch=run_batch,
        load_batch_manifest=load_batch_manifest,
        run_batch_manifest=run_batch_manifest,
        apply_manifest_overrides=apply_manifest_overrides,
        dry_run_batch_manifest=dry_run_batch_manifest,
        dry_run_to_json=dry_run_to_json,
        load_report=load_report,
        verify_blender_runtime=verify_blender_runtime,
    )


__all__ = (
    "main",
    "_default_verify_blender_runtime",
)
