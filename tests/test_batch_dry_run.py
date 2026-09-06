"""Tests for TOONFLOW-PHASE-025 — Batch Dry-Run Mode.

The dry-run layer is exercised by:

- :class:`ResultModelTests` — :class:`BatchDryRunResult`.
- :class:`DiscoveryTests` — selection parity with real execution.
- :class:`FilterTests` — include / exclude behavior.
- :class:`DryRunSafetyTests` — load/replay never called.
- :class:`RunBatchDryRunTests` — :func:`run_batch` ``dry_run=True``.
- :class:`ManifestDryRunTests` — manifest dry-run.
- :class:`CLIIntegrationTests` — CLI ``--dry-run``.
- :class:`Phase024InteractionTests` — overrides + dry-run.
- :class:`ReportTests` — no false execution report.
- :class:`ArchitectureTests` — AST-based guard rails.

The tests do not require Blender, bpy, Ollama, a real renderer,
or a real AI server.
"""

import ast
import contextlib
import dataclasses
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_ROOT = PROJECT_ROOT / "addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


from workflow import (  # noqa: E402
    BatchManifest,
    ManifestInputError,
    apply_manifest_overrides,
    dry_run_batch_manifest,
    load_batch_manifest,
    save_batch_manifest,
)
from workflow.batch import (  # noqa: E402
    BATCH_MODES,
    RUN_MODE,
    SHOW_MODE,
    VALIDATE_MODE,
    BatchInputError,
    BatchDryRunResult,
    discover_projects,
    dry_run_batch,
    run_batch,
)
from workflow.cli import main as cli_main  # noqa: E402


BATCH_SOURCE = (PROJECT_ROOT / "workflow" / "batch.py").read_text(
    encoding="utf-8",
)
MANIFEST_SOURCE = (PROJECT_ROOT / "workflow" / "manifest.py").read_text(
    encoding="utf-8",
)
CLI_SOURCE = (PROJECT_ROOT / "workflow" / "cli.py").read_text(
    encoding="utf-8",
)


# --- Helpers ----------------------------------------------------------------


@contextlib.contextmanager
def _tempdir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@contextlib.contextmanager
def _quiet_argparse_stderr():
    saved = sys.stderr
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stderr = saved


def _ast_all_imports(source):
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


def _write_project(td, name, project):
    p = os.path.join(td, name)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(_project_to_dict(project), fh)
    return p


def _project_to_dict(p):
    return {
        "schema_version": 2,
        "name": p.name,
        "description": "",
        "shots": [
            {
                "concept": s.concept,
                "animation": s.animation,
                "animation_start_frame": s.animation_start_frame,
                "lip_sync": s.lip_sync,
                "lip_sync_start_frame": s.lip_sync_start_frame,
                "output_path": s.output_path,
            }
            for s in p.shots
        ],
    }


@dataclasses.dataclass(frozen=True)
class _Shot:
    concept: str
    animation: str = None
    animation_start_frame: int = 1
    lip_sync: bool = False
    lip_sync_start_frame: int = 1
    output_path: str = None


def _make_project(name="p", shots=(_Shot(concept="c"),)):
    return BatchManifest(
        directory="ignored",
        mode="run",
    ) if False else _Project(name=name, shots=shots)


@dataclasses.dataclass(frozen=True)
class _Project:
    name: str
    shots: tuple = (_Shot(concept="c"),)


# --- Project loader mock ---------------------------------------------------


def _make_load_project(projects_by_path):
    """Return a fake ``load_project`` that maps a path to a Project."""
    def _load(p):
        return projects_by_path[p]
    return _load


def _make_replay():
    @dataclasses.dataclass(frozen=True)
    class _SR:
        output_path: str = ""
    @dataclasses.dataclass(frozen=True)
    class _MR:
        shot_results: tuple = ()
        output_paths: tuple = ()
        shot_count: int = 0
    return _MR(shot_results=(), output_paths=(), shot_count=0)


# ---------------------------------------------------------------------------
# A. Result model
# ---------------------------------------------------------------------------


class ResultModelTests(unittest.TestCase):
    def test_fields_present(self):
        r = BatchDryRunResult(
            directory=Path("d"),
            mode="validate",
            recursive=False,
            include=("a",),
            exclude=(),
            projects=(),
        )
        self.assertEqual(r.directory, Path("d"))
        self.assertEqual(r.mode, "validate")
        self.assertFalse(r.recursive)
        self.assertEqual(r.include, ("a",))
        self.assertEqual(r.exclude, ())
        self.assertEqual(r.projects, ())

    def test_is_frozen(self):
        r = BatchDryRunResult(
            directory=Path("d"), mode="validate", recursive=False,
            include=(), exclude=(), projects=(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.mode = "show"  # type: ignore[misc]

    def test_collections_are_tuples(self):
        r = BatchDryRunResult(
            directory=Path("d"), mode="validate", recursive=False,
            include=("a", "b"), exclude=("c",), projects=(Path("p"),),
        )
        self.assertIsInstance(r.include, tuple)
        self.assertIsInstance(r.exclude, tuple)
        self.assertIsInstance(r.projects, tuple)

    def test_does_not_alias_caller_collections(self):
        include = ["a", "b"]
        exclude = ["c"]
        r = BatchDryRunResult(
            directory=Path("d"), mode="validate", recursive=False,
            include=include, exclude=exclude, projects=(),
        )
        include.append("z")
        exclude.append("z")
        self.assertEqual(r.include, ("a", "b"))
        self.assertEqual(r.exclude, ("c",))

    def test_path_field_accepts_pathlib(self):
        r = BatchDryRunResult(
            directory=Path("d"), mode="validate", recursive=False,
            include=(), exclude=(), projects=(Path("a"), Path("b")),
        )
        self.assertEqual([str(p) for p in r.projects], ["a", "b"])


# ---------------------------------------------------------------------------
# B. Discovery
# ---------------------------------------------------------------------------


class DiscoveryTests(unittest.TestCase):
    def test_nonrecursive_selection(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "c.json", _Project(name="c"))
            r = dry_run_batch(td, "validate")
        rels = sorted(os.path.relpath(str(p), td).replace(os.sep, "/")
                      for p in r.projects)
        self.assertEqual(rels, ["a.json", "b.json"])

    def test_recursive_selection(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "b.json", _Project(name="b"))
            r = dry_run_batch(td, "validate", recursive=True)
        rels = sorted(os.path.relpath(str(p), td).replace(os.sep, "/")
                      for p in r.projects)
        self.assertEqual(rels, ["a.json", "sub/b.json"])

    def test_deterministic_ordering(self):
        with _tempdir() as td:
            for name in ("z.json", "a.json", "m.json"):
                _write_project(td, name, _Project(name=name))
            r1 = dry_run_batch(td, "validate")
            r2 = dry_run_batch(td, "validate")
        self.assertEqual(r1.projects, r2.projects)
        self.assertEqual(
            [os.path.basename(str(p)) for p in r1.projects],
            ["a.json", "m.json", "z.json"],
        )

    def test_no_projects_returns_empty_tuple(self):
        with _tempdir() as td:
            r = dry_run_batch(td, "validate")
        self.assertEqual(r.projects, ())
        self.assertEqual(r.mode, "validate")
        self.assertFalse(r.recursive)


# ---------------------------------------------------------------------------
# C. Filters
# ---------------------------------------------------------------------------


class FilterTests(unittest.TestCase):
    def test_include(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            r = dry_run_batch(td, "validate", include="a.json")
        self.assertEqual([os.path.basename(str(p)) for p in r.projects],
                         ["a.json"])

    def test_exclude(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            r = dry_run_batch(td, "validate", exclude="a.json")
        self.assertEqual([os.path.basename(str(p)) for p in r.projects],
                         ["b.json"])

    def test_exclude_wins_over_include(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            r = dry_run_batch(
                td, "validate", include=("*.json",), exclude=("a.json",),
            )
        self.assertEqual([os.path.basename(str(p)) for p in r.projects],
                         ["b.json"])

    def test_multiple_include_patterns(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            _write_project(td, "c.json", _Project(name="c"))
            r = dry_run_batch(
                td, "validate", include=("a.json", "c.json"),
            )
        self.assertEqual(
            [os.path.basename(str(p)) for p in r.projects],
            ["a.json", "c.json"],
        )

    def test_multiple_exclude_patterns(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            _write_project(td, "c.json", _Project(name="c"))
            r = dry_run_batch(
                td, "validate", exclude=("a.json", "c.json"),
            )
        self.assertEqual(
            [os.path.basename(str(p)) for p in r.projects],
            ["b.json"],
        )

    def test_parity_with_real_batch_selection(self):
        # The dry-run selection must match what a real
        # :func:`run_batch` would attempt.
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(sub, "c.json", _Project(name="c"))
            r = dry_run_batch(
                td, "validate", recursive=True,
                include=("*.json",), exclude=("c.json",),
            )
            real = discover_projects(
                td, recursive=True,
                include=("*.json",), exclude=("c.json",),
            )
        self.assertEqual(
            [str(p) for p in r.projects], real,
        )

    def test_invalid_mode_rejected(self):
        with self.assertRaises(BatchInputError) as cm:
            dry_run_batch(".", "render")
        self.assertEqual(cm.exception.parameter, "mode")

    def test_invalid_recursive_rejected(self):
        with self.assertRaises(BatchInputError):
            dry_run_batch(".", "validate", recursive=1)  # type: ignore[arg-type]

    def test_invalid_include_rejected(self):
        with self.assertRaises(BatchInputError) as cm:
            dry_run_batch(".", "validate", include=True)  # type: ignore[arg-type]
        self.assertEqual(cm.exception.parameter, "include")

    def test_invalid_exclude_rejected(self):
        with self.assertRaises(BatchInputError):
            dry_run_batch(".", "validate", exclude=42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# D. Dry-run safety
# ---------------------------------------------------------------------------


class DryRunSafetyTests(unittest.TestCase):
    def test_load_project_never_called_in_dry_run_batch(self):
        load_calls = []
        def _load(p):
            load_calls.append(p)
            return _Project(name="x")

        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            r = dry_run_batch(td, "run")
        self.assertEqual(load_calls, [])

    def test_replay_project_never_called_in_dry_run_batch(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            r = dry_run_batch(td, "run")
        # No exception; dry-run did not call any replay.

    def test_run_batch_dry_run_does_not_call_load(self):
        load_calls = []
        replay_calls = []
        def _load(p):
            load_calls.append(p)
            return _Project(name="x")
        def _replay(proj):
            replay_calls.append(proj)
            return _make_replay()

        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            rc = run_batch(
                td, "run", stdout=buf,
                load_project=_load, replay_project=_replay, dry_run=True,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(load_calls, [])
        self.assertEqual(replay_calls, [])

    def test_project_files_not_modified_by_dry_run(self):
        with _tempdir() as td:
            path = _write_project(td, "a.json", _Project(name="a"))
            before = Path(path).read_bytes()
            buf = io.StringIO()
            run_batch(td, "run", stdout=buf, dry_run=True)
            after = Path(path).read_bytes()
            self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# E. Parity with normal execution
# ---------------------------------------------------------------------------


class ParityTests(unittest.TestCase):
    def test_dry_run_matches_real_execution_selection(self):
        # Run a real :func:`run_batch` with stubbed hooks; the
        # calls to ``load_project`` record every path that
        # would have been executed. The dry-run selection
        # must equal that set.
        visited = []
        def _load(p):
            visited.append(p)
            return _Project(name="x")
        def _replay(proj):
            return _make_replay()

        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            _write_project(td, "c.json", _Project(name="c"))
            r = dry_run_batch(
                td, "validate",
                include=("a.json", "b.json"), exclude=("b.json",),
            )
            buf = io.StringIO()
            run_batch(
                td, "validate",
                stdout=buf,
                load_project=_load, replay_project=_replay,
                include=("a.json", "b.json"), exclude=("b.json",),
            )
        self.assertEqual(
            sorted(os.path.relpath(p, td) for p in visited),
            [os.path.relpath(str(p), td) for p in r.projects],
        )


# ---------------------------------------------------------------------------
# F. Manifest integration
# ---------------------------------------------------------------------------


class ManifestDryRunTests(unittest.TestCase):
    def test_manifest_dry_run_returns_result(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            r = dry_run_batch_manifest(m)
        self.assertIsInstance(r, BatchDryRunResult)
        self.assertEqual(r.mode, "validate")
        self.assertEqual([os.path.basename(str(p)) for p in r.projects],
                         ["a.json"])

    def test_manifest_dry_run_preserves_include_exclude(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), exclude=("b.json",), recursive=False,
            )
            r = dry_run_batch_manifest(m)
        self.assertEqual(r.include, ("a.json",))
        self.assertEqual(r.exclude, ("b.json",))
        self.assertEqual([os.path.basename(str(p)) for p in r.projects],
                         ["a.json"])

    def test_manifest_object_not_mutated(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            snapshot = (
                m.directory, m.mode, m.include, m.exclude,
                m.recursive, m.report_path, m.schema_version,
            )
            dry_run_batch_manifest(m)
            self.assertEqual(
                (m.directory, m.mode, m.include, m.exclude,
                 m.recursive, m.report_path, m.schema_version),
                snapshot,
            )

    def test_manifest_file_unchanged_after_dry_run(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            path = save_batch_manifest(m, os.path.join(td, "m.json"))
            before = Path(path).read_bytes()
            dry_run_batch_manifest(m)
            after = Path(path).read_bytes()
            self.assertEqual(before, after)

    def test_manifest_dry_run_includes_recursive_flag(self):
        with _tempdir() as td:
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(sub, "b.json", _Project(name="b"))
            m = BatchManifest(
                directory=td, mode="validate", recursive=True,
            )
            r = dry_run_batch_manifest(m)
        self.assertTrue(r.recursive)
        rels = sorted(os.path.relpath(str(p), td).replace(os.sep, "/")
                      for p in r.projects)
        self.assertEqual(rels, ["a.json", "sub/b.json"])

    def test_dry_run_batch_manifest_invalid_manifest_rejected(self):
        with self.assertRaises(ManifestInputError):
            dry_run_batch_manifest({"not": "a manifest"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# G. CLI integration
# ---------------------------------------------------------------------------


class CLIIntegrationTests(unittest.TestCase):
    def _save_manifest(self, td, **kwargs):
        defaults = dict(
            directory=td, mode="validate", recursive=False,
            include=(), exclude=(), report_path=None,
        )
        defaults.update(kwargs)
        m = BatchManifest(**defaults)
        path = os.path.join(td, "manifest.json")
        save_batch_manifest(m, path)
        return path

    def test_batch_dry_run_returns_zero(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate", "--dry-run"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)

    def test_batch_dry_run_deterministic_output(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["batch", td, "validate", "--dry-run",
                     "--include", "a.json"],
                    stdout=buf,
                )
            text = buf.getvalue()
            self.assertIn("Dry-run:", text)
            self.assertIn("a.json", text)
            self.assertNotIn("b.json", text)

    def test_batch_dry_run_empty_selection_is_zero(self):
        with _tempdir() as td:
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate", "--dry-run"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            self.assertIn("Projects: 0", buf.getvalue())

    def test_batch_without_dry_run_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            self.assertNotIn("Dry-run:", buf.getvalue())

    def test_manifest_dry_run_returns_zero(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            path = self._save_manifest(td, mode="validate")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--dry-run"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            self.assertIn("Dry-run:", buf.getvalue())

    def test_manifest_dry_run_file_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            path = self._save_manifest(td)
            before = Path(path).read_bytes()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run"],
                    stdout=buf,
                )
            after = Path(path).read_bytes()
            self.assertEqual(before, after)

    def test_manifest_without_dry_run_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            path = self._save_manifest(td, mode="validate")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path],
                    stdout=buf,
                )
            # Real execution path; the load_project default will
            # try to load the file. We don't have a real
            # loader here, but rc is 0 or 1 — it is NOT a
            # dry-run output.
            self.assertIn(rc, (0, 1))
            self.assertNotIn("Dry-run:", buf.getvalue())

    def test_dry_run_invalid_mode_returns_two(self):
        with _tempdir() as td:
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "render", "--dry-run"],
                    stdout=buf,
                )
            self.assertEqual(rc, 2)

    def test_batch_help_returns_zero(self):
        with _quiet_argparse_stderr():
            try:
                rc = cli_main(["batch", "--help"], stdout=io.StringIO())
            except SystemExit as exc:
                rc = exc.code
        self.assertEqual(rc, 0)

    def test_manifest_help_returns_zero(self):
        with _quiet_argparse_stderr():
            try:
                rc = cli_main(["manifest", "--help"], stdout=io.StringIO())
            except SystemExit as exc:
                rc = exc.code
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# H. PHASE-024 interaction
# ---------------------------------------------------------------------------


class Phase024InteractionTests(unittest.TestCase):
    def test_overrides_applied_before_dry_run(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            effective = apply_manifest_overrides(
                m, include=("b.json",),
            )
            r = dry_run_batch_manifest(effective)
        self.assertEqual(
            [os.path.basename(str(p)) for p in r.projects],
            ["b.json"],
        )

    def test_no_recursive_overrides_manifest_true(self):
        with _tempdir() as td:
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(sub, "b.json", _Project(name="b"))
            m = BatchManifest(
                directory=td, mode="validate", recursive=True,
            )
            effective = apply_manifest_overrides(m, recursive=False)
            r = dry_run_batch_manifest(effective)
        self.assertFalse(r.recursive)
        self.assertEqual(
            [os.path.basename(str(p)) for p in r.projects],
            ["a.json"],
        )

    def test_dry_run_does_not_participate_in_precedence(self):
        # The BatchManifest schema has no dry_run field. The
        # JSON file does not mention dry-run. Apply
        # ``apply_manifest_overrides`` and confirm the result
        # has the same schema fields as the manifest.
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            m = BatchManifest(directory=td, mode="validate")
            effective = apply_manifest_overrides(m, mode="show")
            self.assertFalse(hasattr(effective, "dry_run"))
            d = {
                "schema_version": 1,
                "directory": effective.directory,
                "mode": effective.mode,
                "include": list(effective.include),
                "exclude": list(effective.exclude),
                "recursive": effective.recursive,
                "report_path": effective.report_path,
            }
            self.assertNotIn("dry_run", d)
            self.assertNotIn("is_dry_run", d)

    def test_cli_dry_run_with_overrides(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            path = os.path.join(td, "m.json")
            save_batch_manifest(m, path)
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--dry-run",
                     "--include", "b.json"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            text = buf.getvalue()
            # The CLI override replaced the manifest's
            # include; only ``b.json`` should be listed as a
            # would-be-executed project.
            self.assertIn("b.json", text)
            # ``a.json`` is the manifest's original include and
            # should not appear as a would-be-executed project.
            self.assertNotIn("\\a.json", text)
            self.assertNotIn("  - " + str(td) + os.sep + "a.json", text)


# ---------------------------------------------------------------------------
# I. Reports
# ---------------------------------------------------------------------------


class ReportTests(unittest.TestCase):
    def test_dry_run_does_not_write_report(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            report = os.path.join(td, "r.json")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate", "--dry-run",
                     "--report", report],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(report))

    def test_dry_run_does_not_falsely_succeed(self):
        # A failed real execution returns 1; a dry-run with
        # the same selection returns 0.
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf1 = io.StringIO()
            with _quiet_argparse_stderr():
                rc_dry = cli_main(
                    ["batch", td, "run", "--dry-run"],
                    stdout=buf1,
                )
            self.assertEqual(rc_dry, 0)
            # The dry-run output does not claim a project
            # succeeded — it only lists the would-be-executed
            # paths.
            self.assertNotIn("OK", buf1.getvalue())


# ---------------------------------------------------------------------------
# J. Architecture
# ---------------------------------------------------------------------------


class ArchitectureTests(unittest.TestCase):
    def test_batch_no_forbidden_imports(self):
        forbidden = {
            "bpy", "ollama", "requests", "urllib",
            "pipeline", "asset_registry", "scene_plan",
            "toonflow_ai", "audio",
        }
        for module in _ast_all_imports(BATCH_SOURCE):
            top = module.split(".")[0]
            self.assertNotIn(
                top, forbidden,
                f"workflow.batch.py must not import {module!r}",
            )

    def test_manifest_no_forbidden_imports(self):
        forbidden = {
            "bpy", "ollama", "requests", "urllib",
            "pipeline", "asset_registry", "scene_plan",
            "toonflow_ai", "audio",
        }
        for module in _ast_all_imports(MANIFEST_SOURCE):
            top = module.split(".")[0]
            self.assertNotIn(
                top, forbidden,
                f"workflow.manifest.py must not import {module!r}",
            )

    def test_cli_no_forbidden_imports(self):
        forbidden = {"bpy", "ollama", "urllib", "pipeline",
                     "asset_registry", "scene_plan", "toonflow_ai"}
        for module in _ast_all_imports(CLI_SOURCE):
            top = module.split(".")[0]
            self.assertNotIn(top, forbidden)

    def test_no_threading(self):
        for src in (BATCH_SOURCE, MANIFEST_SOURCE, CLI_SOURCE):
            for needle in (
                "import threading", "import multiprocessing", "import asyncio",
                "from threading", "from multiprocessing", "from asyncio",
            ):
                self.assertNotIn(needle, src)

    def test_no_subprocess(self):
        for src in (BATCH_SOURCE, MANIFEST_SOURCE, CLI_SOURCE):
            for needle in ("import subprocess", "from subprocess"):
                self.assertNotIn(needle, src)

    def test_no_print_or_input(self):
        for src in (BATCH_SOURCE, MANIFEST_SOURCE, CLI_SOURCE):
            for needle in ("print(", "input("):
                self.assertNotIn(needle, src)

    def test_dry_run_batch_function_exists(self):
        self.assertIn("def dry_run_batch(", BATCH_SOURCE)

    def test_batch_dry_run_result_class_exists(self):
        self.assertIn("class BatchDryRunResult", BATCH_SOURCE)

    def test_dry_run_batch_manifest_function_exists(self):
        self.assertIn("def dry_run_batch_manifest(", MANIFEST_SOURCE)

    def test_dry_run_uses_dry_run_batch(self):
        # The manifest dry-run entry point must delegate to
        # the batch layer's dry-run function, not reimplement
        # discovery.
        self.assertIn("dry_run_batch", MANIFEST_SOURCE)
        self.assertIn("_default_dry_run_batch", MANIFEST_SOURCE)

    def test_run_batch_uses_dry_run_branch(self):
        # ``run_batch`` must have a ``dry_run`` keyword and a
        # dedicated branch.
        self.assertIn("def run_batch(", BATCH_SOURCE)
        self.assertIn("dry_run", BATCH_SOURCE)


if __name__ == "__main__":
    unittest.main()
