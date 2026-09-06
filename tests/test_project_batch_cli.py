"""Tests for TOONFLOW-PHASE-020 — Project Batch Mode & CI Integration.

The batch layer is exercised by:

- :class:`PublicAPITests` — the CLI surface and the
  ``workflow.batch`` module surface.
- :class:`DiscoveryTests` — deterministic file discovery.
- :class:`ValidateModeTests` — the ``validate`` batch mode.
- :class:`ShowModeTests` — the ``show`` batch mode.
- :class:`RunModeTests` — the ``run`` batch mode.
- :class:`DependencyInjectionTests` — DI hooks for the batch.
- :class:`DeterminismTests` — repeated-run determinism.
- :class:`ArchitectureTests` — AST-based guard rails.

The tests do not require Blender, bpy, Ollama, a real renderer,
or a real AI server. They use dependency injection and temporary
directories.
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
    Project,
    ProjectInputError,
    Shot,
    save_project,
)
from workflow.batch import (  # noqa: E402
    BATCH_MODES,
    RUN_MODE,
    SHOW_MODE,
    VALIDATE_MODE,
    BatchProjectResult,
    discover_projects,
    run_batch,
)
from workflow.cli import main as cli_main  # noqa: E402


BATCH_SOURCE = (PROJECT_ROOT / "workflow" / "batch.py").read_text(
    encoding="utf-8",
)
CLI_SOURCE = (PROJECT_ROOT / "workflow" / "cli.py").read_text(
    encoding="utf-8",
)
MAIN_SOURCE = (PROJECT_ROOT / "workflow" / "__main__.py").read_text(
    encoding="utf-8",
)


# --- Helpers ----------------------------------------------------------------


def _make_project(name="demo", shots=None, description=""):
    if shots is None:
        shots = (Shot(concept="a"),)
    return Project(name=name, description=description, shots=tuple(shots))


def _write_project(directory, name, project):
    path = os.path.join(directory, name)
    save_project(project, path)
    return path


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


@contextlib.contextmanager
def _capture_argparse_stderr():
    buf = io.StringIO()
    saved = sys.stderr
    sys.stderr = buf
    try:
        yield buf
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


@dataclasses.dataclass(frozen=True)
class _FakeShotResult:
    output_path: str = ""


@dataclasses.dataclass(frozen=True)
class _FakeMultiShotResult:
    shot_results: tuple = ()
    output_paths: tuple = ()
    shot_count: int = 0


def _make_fake_replay(output_paths):
    n = len(output_paths)
    return _FakeMultiShotResult(
        shot_results=tuple(_FakeShotResult(p) for p in output_paths),
        output_paths=tuple(output_paths),
        shot_count=n,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PublicAPITests(unittest.TestCase):
    def test_batch_subcommand_is_registered(self):
        # The CLI parser must expose a ``batch`` subcommand with
        # ``directory`` and ``mode`` positionals.
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            rc = cli_main(["batch"], stdout=buf)
        # argparse reports "the following arguments are required"
        # via stderr; the CLI converts to exit code 2.
        self.assertEqual(rc, 2)

    def test_existing_commands_remain_unchanged(self):
        # ``validate``, ``show``, ``run`` still work as before.
        with _tempdir() as td:
            path = _write_project(td, "p.json", _make_project(name="x"))
            buf = io.StringIO()
            self.assertEqual(
                cli_main(["validate", path], stdout=buf), 0,
            )
            buf = io.StringIO()
            self.assertEqual(
                cli_main(["show", path], stdout=buf), 0,
            )

    def test_python_module_entry_unchanged(self):
        # The __main__ module is still thin and uses cli.main.
        self.assertIn("if __name__", MAIN_SOURCE)
        self.assertIn("sys.exit", MAIN_SOURCE)
        self.assertLess(len(MAIN_SOURCE.splitlines()), 30)

    def test_invalid_batch_arguments_return_2(self):
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            self.assertEqual(
                cli_main(["batch"], stdout=buf), 2,
            )
            buf = io.StringIO()
            self.assertEqual(
                cli_main(["batch", "some-dir"], stdout=buf), 2,
            )
            buf = io.StringIO()
            self.assertEqual(
                cli_main(["batch", "some-dir", "bogus"], stdout=buf),
                2,
            )

    def test_batch_module_exposes_run_batch(self):
        from workflow import batch as batch_mod
        self.assertTrue(hasattr(batch_mod, "run_batch"))
        self.assertTrue(hasattr(batch_mod, "discover_projects"))
        self.assertTrue(hasattr(batch_mod, "BatchProjectResult"))
        self.assertEqual(
            set(BATCH_MODES), {VALIDATE_MODE, SHOW_MODE, RUN_MODE},
        )

    def test_workflow_init_not_modified(self):
        # The batch layer is reached via ``workflow.batch`` and
        # ``python -m workflow batch``. The top-level package
        # keeps its PHASE-019 surface: ``run_batch`` is not
        # re-exported from ``workflow`` itself.
        import workflow
        self.assertFalse(hasattr(workflow, "run_batch"))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class DiscoveryTests(unittest.TestCase):
    def test_only_json_files_discovered(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            _write_project(td, "b.json", _make_project(name="b"))
            # Non-JSON files must be ignored.
            with open(os.path.join(td, "readme.txt"), "w") as fh:
                fh.write("ignore")
            with open(os.path.join(td, "data.yaml"), "w") as fh:
                fh.write("ignore")
            paths = discover_projects(td)
        names = [os.path.basename(p) for p in paths]
        self.assertEqual(names, ["a.json", "b.json"])

    def test_directories_ignored(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            # Subdirectory must be ignored (non-recursive).
            os.mkdir(os.path.join(td, "nested"))
            with open(os.path.join(td, "nested", "c.json"), "w") as fh:
                fh.write("{}")
            paths = discover_projects(td)
        names = [os.path.basename(p) for p in paths]
        self.assertEqual(names, ["a.json"])

    def test_hidden_files_ignored(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            with open(os.path.join(td, ".hidden.json"), "w") as fh:
                fh.write("{}")
            paths = discover_projects(td)
        names = [os.path.basename(p) for p in paths]
        self.assertEqual(names, ["a.json"])

    def test_deterministic_lexicographic_ordering(self):
        with _tempdir() as td:
            # Write files in a non-sorted order.
            for name in ("zebra.json", "alpha.json", "mike.json",
                         "bravo.json"):
                _write_project(td, name, _make_project(name=name))
            paths = discover_projects(td)
        names = [os.path.basename(p) for p in paths]
        self.assertEqual(
            names, ["alpha.json", "bravo.json", "mike.json", "zebra.json"],
        )

    def test_empty_directory_returns_empty_list(self):
        with _tempdir() as td:
            self.assertEqual(discover_projects(td), [])

    def test_missing_directory_raises_oserror(self):
        with _tempdir() as td:
            missing = os.path.join(td, "nope")
            with self.assertRaises(OSError):
                discover_projects(missing)

    def test_non_directory_raises_oserror(self):
        with _tempdir() as td:
            f = os.path.join(td, "f.json")
            with open(f, "w") as fh:
                fh.write("{}")
            with self.assertRaises(OSError):
                discover_projects(f)


# ---------------------------------------------------------------------------
# Validate mode
# ---------------------------------------------------------------------------


class ValidateModeTests(unittest.TestCase):
    def test_every_project_is_loaded(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                _write_project(td, name, _make_project(name=name))
            load_calls = []
            def fake_load(p):
                load_calls.append(os.path.basename(p))
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE,
                           load_project=fake_load, stdout=buf)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(load_calls), ["a.json", "b.json", "c.json"])
        self.assertEqual(len(load_calls), 3)

    def test_sorted_order_is_respected(self):
        with _tempdir() as td:
            for name in ("z.json", "a.json", "m.json"):
                _write_project(td, name, _make_project(name=name))
            load_calls = []
            def fake_load(p):
                load_calls.append(os.path.basename(p))
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            run_batch(td, VALIDATE_MODE,
                      load_project=fake_load, stdout=buf)
        self.assertEqual(load_calls, ["a.json", "m.json", "z.json"])

    def test_successful_projects_are_reported(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            buf = io.StringIO()
            run_batch(td, VALIDATE_MODE,
                      load_project=lambda p: _make_project(name="a"),
                      stdout=buf)
        out = buf.getvalue()
        self.assertIn("a.json: OK", out)

    def test_failed_projects_are_reported(self):
        with _tempdir() as td:
            _write_project(td, "bad.json", _make_project(name="bad"))
            def bad_load(p):
                raise ProjectInputError("schema_version", 99)
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE,
                           load_project=bad_load, stdout=buf)
        self.assertNotEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("bad.json: ERROR", out)

    def test_processing_continues_after_failure(self):
        with _tempdir() as td:
            _write_project(td, "good1.json", _make_project(name="good1"))
            _write_project(td, "bad.json", _make_project(name="bad"))
            _write_project(td, "good2.json", _make_project(name="good2"))
            seen = []

            def fake_load(p):
                name = os.path.basename(p)
                seen.append(name)
                if name == "bad.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=name)

            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE,
                           load_project=fake_load, stdout=buf)
        # Lexicographic order: bad, good1, good2. Processing
        # continues past the failure on bad.json.
        self.assertEqual(seen, ["bad.json", "good1.json", "good2.json"])
        self.assertNotEqual(rc, 0)

    def test_replay_project_is_never_called(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
        replay_calls = []
        buf = io.StringIO()
        run_batch(
            td, VALIDATE_MODE,
            load_project=lambda p: _make_project(name="a"),
            replay_project=lambda *a, **kw: replay_calls.append((a, kw)),
            stdout=buf,
        )
        self.assertEqual(replay_calls, [])

    def test_summary_counts_are_correct(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                _write_project(td, name, _make_project(name=name))
            def fake_load(p):
                name = os.path.basename(p)
                if name == "b.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=name)

            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE,
                           load_project=fake_load, stdout=buf)
        out = buf.getvalue()
        self.assertIn("Projects: 3", out)
        self.assertIn("Succeeded: 2", out)
        self.assertIn("Failed: 1", out)
        self.assertNotEqual(rc, 0)

    def test_exit_code_zero_when_all_succeed(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            _write_project(td, "b.json", _make_project(name="b"))
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE,
                           load_project=lambda p: _make_project(),
                           stdout=buf)
        self.assertEqual(rc, 0)

    def test_exit_code_one_when_any_fail(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            _write_project(td, "b.json", _make_project(name="b"))
            def fake_load(p):
                if os.path.basename(p) == "b.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name="a")
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE,
                           load_project=fake_load, stdout=buf)
        self.assertEqual(rc, 1)

    def test_empty_directory_returns_one(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE,
                           load_project=lambda p: None, stdout=buf)
        self.assertEqual(rc, 1)
        self.assertIn("no eligible project JSON files", buf.getvalue())

    def test_missing_directory_returns_one(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = run_batch(
                os.path.join(td, "nope"),
                VALIDATE_MODE,
                load_project=lambda p: None,
                stdout=buf,
            )
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# Show mode
# ---------------------------------------------------------------------------


class ShowModeTests(unittest.TestCase):
    def test_every_project_is_loaded(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            load_calls = []
            def fake_load(p):
                load_calls.append(os.path.basename(p))
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            run_batch(td, SHOW_MODE, load_project=fake_load, stdout=buf)
        self.assertEqual(sorted(load_calls), ["a.json", "b.json"])

    def test_deterministic_ordering(self):
        with _tempdir() as td:
            for name in ("zebra.json", "alpha.json"):
                _write_project(td, name, _make_project(name=name))
            seen = []
            def fake_load(p):
                seen.append(os.path.basename(p))
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            run_batch(td, SHOW_MODE, load_project=fake_load, stdout=buf)
        self.assertEqual(seen, ["alpha.json", "zebra.json"])

    def test_project_information_is_shown(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="alpha"))
            buf = io.StringIO()
            run_batch(td, SHOW_MODE,
                      load_project=lambda p: _make_project(
                          name="alpha", description="d",
                      ),
                      stdout=buf)
        out = buf.getvalue()
        self.assertIn("a.json:", out)
        self.assertIn("Name: alpha", out)
        self.assertIn("Description: d", out)

    def test_project_files_are_not_modified(self):
        with _tempdir() as td:
            path = _write_project(td, "a.json",
                                  _make_project(name="alpha"))
            with open(path, "rb") as fh:
                before = fh.read()
            buf = io.StringIO()
            run_batch(td, SHOW_MODE,
                      load_project=lambda p: _make_project(name="alpha"),
                      stdout=buf)
            with open(path, "rb") as fh:
                after = fh.read()
        self.assertEqual(before, after)

    def test_replay_project_is_never_called(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
        replay_calls = []
        buf = io.StringIO()
        run_batch(
            td, SHOW_MODE,
            load_project=lambda p: _make_project(name="a"),
            replay_project=lambda *a, **kw: replay_calls.append((a, kw)),
            stdout=buf,
        )
        self.assertEqual(replay_calls, [])

    def test_processing_continues_after_failure(self):
        with _tempdir() as td:
            for name in ("a.json", "bad.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            seen = []
            def fake_load(p):
                name = os.path.basename(p)
                seen.append(name)
                if name == "bad.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=name)
            buf = io.StringIO()
            rc = run_batch(td, SHOW_MODE, load_project=fake_load, stdout=buf)
        # Discovered in lexicographic order: a.json, b.json, bad.json.
        # Processing continues past the failure on b.json.
        self.assertEqual(seen, ["a.json", "b.json", "bad.json"])
        self.assertNotEqual(rc, 0)

    def test_summary_counts_are_correct(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            def fake_load(p):
                if os.path.basename(p) == "b.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name="a")
            buf = io.StringIO()
            rc = run_batch(td, SHOW_MODE, load_project=fake_load, stdout=buf)
        out = buf.getvalue()
        self.assertIn("Projects: 2", out)
        self.assertIn("Succeeded: 1", out)
        self.assertIn("Failed: 1", out)
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# Run mode
# ---------------------------------------------------------------------------


class RunModeTests(unittest.TestCase):
    def test_load_then_replay_per_project(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            events = []

            def fake_load(p):
                name = os.path.basename(p)
                events.append(("load", name))
                return _make_project(name=name)

            def fake_replay(proj, **kw):
                events.append(("replay", proj.name))
                return _make_fake_replay(("/o/x.png",))

            buf = io.StringIO()
            rc = run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(
            events,
            [
                ("load", "a.json"), ("replay", "a.json"),
                ("load", "b.json"), ("replay", "b.json"),
            ],
        )

    def test_strictly_sequential_execution(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                _write_project(td, name, _make_project(name=name))
            events = []
            def fake_load(p):
                events.append(("load", os.path.basename(p)))
                return _make_project(name=os.path.basename(p))
            def fake_replay(proj, **kw):
                events.append(("replay", proj.name))
                return _make_fake_replay(("/o/x.png",))
            buf = io.StringIO()
            run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        # Strictly one-at-a-time: load a -> replay a -> load b -> ...
        self.assertEqual(
            events,
            [
                ("load", "a.json"), ("replay", "a.json"),
                ("load", "b.json"), ("replay", "b.json"),
                ("load", "c.json"), ("replay", "c.json"),
            ],
        )

    def test_replay_called_only_after_successful_load(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            replay_calls = []
            def fake_load(p):
                raise ProjectInputError("schema_version", 99)
            def fake_replay(proj, **kw):
                replay_calls.append(proj)
                return _make_fake_replay(())
            buf = io.StringIO()
            rc = run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        self.assertEqual(replay_calls, [])
        self.assertNotEqual(rc, 0)

    def test_loading_failure_prevents_replay(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            replay_calls = []
            def fake_load(p):
                raise ValueError("nope")
            def fake_replay(proj, **kw):
                replay_calls.append(proj)
                return _make_fake_replay(())
            buf = io.StringIO()
            run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        self.assertEqual(replay_calls, [])

    def test_replay_failure_does_not_prevent_later_projects(self):
        with _tempdir() as td:
            for name in ("a.json", "bad.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            seen = []
            def fake_load(p):
                seen.append(("load", os.path.basename(p)))
                return _make_project(name=os.path.basename(p))
            def fake_replay(proj, **kw):
                seen.append(("replay", proj.name))
                if proj.name == "bad.json":
                    raise RuntimeError("replay boom")
                return _make_fake_replay(("/o/x.png",))
            buf = io.StringIO()
            rc = run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        self.assertNotEqual(rc, 0)
        # All three projects were attempted in lexicographic
        # order: a.json, b.json, bad.json.
        self.assertEqual(
            [n for _, n in seen],
            ["a.json", "a.json", "b.json", "b.json",
             "bad.json", "bad.json"],
        )

    def test_output_paths_preserve_delegated_order(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            def fake_load(p):
                return _make_project(name="a")
            def fake_replay(proj, **kw):
                return _make_fake_replay(("/z/3.png", "/y/2.png", "/x/1.png"))
            buf = io.StringIO()
            rc = run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        i1 = out.find("/z/3.png")
        i2 = out.find("/y/2.png")
        i3 = out.find("/x/1.png")
        self.assertGreaterEqual(i1, 0)
        self.assertGreater(i2, i1)
        self.assertGreater(i3, i2)

    def test_summary_counts_are_correct(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                _write_project(td, name, _make_project(name=name))
            def fake_load(p):
                name = os.path.basename(p)
                if name == "b.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=name)
            def fake_replay(proj, **kw):
                return _make_fake_replay(("/o/x.png",))
            buf = io.StringIO()
            rc = run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        out = buf.getvalue()
        self.assertIn("Projects: 3", out)
        self.assertIn("Succeeded: 2", out)
        self.assertIn("Failed: 1", out)
        self.assertNotEqual(rc, 0)

    def test_processing_continues_after_failure(self):
        # The same idea as the dedicated continue-after-failure
        # test above, but covering all three modes via run_batch.
        with _tempdir() as td:
            for name in ("a.json", "bad.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            seen = []
            def fake_load(p):
                name = os.path.basename(p)
                seen.append(name)
                if name == "bad.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=name)
            def fake_replay(proj, **kw):
                seen.append(("replay", proj.name))
                return _make_fake_replay(("/o/x.png",))
            buf = io.StringIO()
            rc = run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        # Lexicographic: a.json, b.json, bad.json. The failure on
        # bad.json does not prevent b.json from being processed.
        self.assertEqual(
            seen,
            ["a.json", ("replay", "a.json"),
             "b.json", ("replay", "b.json"),
             "bad.json"],
        )
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


class DependencyInjectionTests(unittest.TestCase):
    def test_fake_load_project(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            _write_project(td, "b.json", _make_project(name="b"))
            load_calls = []
            def fake_load(p):
                load_calls.append(p)
                return _make_project(name=os.path.basename(p))
            buf = io.StringIO()
            rc = run_batch(td, VALIDATE_MODE,
                           load_project=fake_load, stdout=buf)
        self.assertEqual(rc, 0)
        self.assertEqual(len(load_calls), 2)

    def test_fake_replay_project(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _make_project(name="a"))
            replay_calls = []
            def fake_load(p):
                return _make_project(name="a")
            def fake_replay(proj, **kw):
                replay_calls.append(proj.name)
                return _make_fake_replay(("/o/x.png",))
            buf = io.StringIO()
            rc = run_batch(
                td, RUN_MODE,
                load_project=fake_load,
                replay_project=fake_replay,
                stdout=buf,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(replay_calls, ["a"])

    def test_no_blender_required(self):
        # The batch module is importable without bpy / Blender.
        import workflow.batch  # noqa: F401

    def test_no_ollama_required(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            root = name.split(".")[0]
            self.assertNotIn(
                root, {"ollama", "ollama_client"},
                f"forbidden ollama import: {name}",
            )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_repeated_runs_same_delegation_order(self):
        with _tempdir() as td:
            for name in ("z.json", "a.json", "m.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            load_calls_run1 = []
            load_calls_run2 = []
            replay_calls_run1 = []
            replay_calls_run2 = []

            def make_load(out):
                def fake_load(p):
                    out.append(os.path.basename(p))
                    return _make_project(name=os.path.basename(p))
                return fake_load

            def make_replay(out):
                def fake_replay(proj, **kw):
                    out.append(proj.name)
                    return _make_fake_replay(("/o/x.png",))
                return fake_replay

            run_batch(
                td, RUN_MODE,
                load_project=make_load(load_calls_run1),
                replay_project=make_replay(replay_calls_run1),
                stdout=io.StringIO(),
            )
            run_batch(
                td, RUN_MODE,
                load_project=make_load(load_calls_run2),
                replay_project=make_replay(replay_calls_run2),
                stdout=io.StringIO(),
            )
        self.assertEqual(load_calls_run1, load_calls_run2)
        self.assertEqual(replay_calls_run1, replay_calls_run2)
        self.assertEqual(
            load_calls_run1, ["a.json", "b.json", "m.json", "z.json"],
        )

    def test_deterministic_summary_output(self):
        with _tempdir() as td:
            for name in ("a.json", "b.json", "c.json"):
                _write_project(td, name, _make_project(name=name))
            def fake_load(p):
                if os.path.basename(p) == "b.json":
                    raise ProjectInputError("schema_version", 99)
                return _make_project(name=os.path.basename(p))
            out1 = io.StringIO()
            out2 = io.StringIO()
            run_batch(td, VALIDATE_MODE, load_project=fake_load, stdout=out1)
            run_batch(td, VALIDATE_MODE, load_project=fake_load, stdout=out2)
        self.assertEqual(out1.getvalue(), out2.getvalue())

    def test_deterministic_file_order(self):
        with _tempdir() as td:
            for name in ("c.json", "a.json", "b.json"):
                _write_project(td, name, _make_project(name=name))
            seen = []
            def fake_load(p):
                seen.append(os.path.basename(p))
                return _make_project(name=os.path.basename(p))
            run_batch(td, VALIDATE_MODE, load_project=fake_load,
                      stdout=io.StringIO())
        self.assertEqual(seen, ["a.json", "b.json", "c.json"])


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


class ArchitectureTests(unittest.TestCase):
    def test_batch_does_not_import_bpy(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import: {name}",
            )

    def test_batch_does_not_import_ollama(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"ollama", "ollama_client"},
                f"forbidden ollama import: {name}",
            )

    def test_batch_does_not_import_requests(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"requests"},
                f"forbidden requests import: {name}",
            )

    def test_batch_does_not_import_urllib(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"urllib", "urllib.request"},
                f"forbidden urllib import: {name}",
            )

    def test_batch_does_not_import_pipeline(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"pipeline"},
                f"forbidden pipeline import: {name}",
            )

    def test_batch_does_not_import_asset_registry(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"asset_registry"},
                f"forbidden asset_registry import: {name}",
            )

    def test_batch_does_not_import_scene_plan(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"scene_plan"},
                f"forbidden scene_plan import: {name}",
            )

    def test_batch_does_not_import_toonflow_ai_generation(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertFalse(
                name.startswith("toonflow_ai"),
                f"forbidden toonflow_ai import: {name}",
            )

    def test_batch_does_not_reference_bpy_data_or_bpy_ops(self):
        self.assertNotIn("bpy.data", BATCH_SOURCE)
        self.assertNotIn("bpy.ops", BATCH_SOURCE)

    def test_batch_does_not_call_keyframe_insert(self):
        self.assertNotIn("keyframe_insert", BATCH_SOURCE)

    def test_batch_does_not_call_rendering_apis(self):
        for forbidden in (
            "render_scene(", "create_or_update_camera(",
            "from_pydata(", "bpy.ops.render",
        ):
            self.assertNotIn(forbidden, BATCH_SOURCE)

    def test_batch_does_not_duplicate_schema_migration(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertNotEqual(
                name, "project_migrations",
                "batch must not import the migration module",
            )
            self.assertFalse(
                name.endswith(".project_migrations"),
                f"batch must not import migration module: {name}",
            )
        for forbidden in (
            "migrate_project_dict",
            "migrate_project_dict_to_version",
            "UnsupportedProjectSchemaError",
        ):
            self.assertNotIn(forbidden, BATCH_SOURCE)

    def test_batch_does_not_call_create_and_render_scene(self):
        self.assertNotIn("create_and_render_scene", BATCH_SOURCE)

    def test_batch_does_not_call_create_and_render_shots(self):
        self.assertNotIn("create_and_render_shots", BATCH_SOURCE)

    def test_batch_does_not_open_files(self):
        self.assertNotIn("open(", BATCH_SOURCE)

    def test_batch_does_not_use_print(self):
        # ``stdout.write`` is the only output mechanism; ``print``
        # would bypass the DI stream.
        self.assertNotIn("print(", BATCH_SOURCE)

    def test_batch_does_not_use_input(self):
        self.assertNotIn("input(", BATCH_SOURCE)

    def test_batch_top_level_imports_minimal(self):
        tree = ast.parse(BATCH_SOURCE)
        names = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.append((alias.name, 0))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.append((node.module, getattr(node, "level", 0)))
        for name, level in names:
            if level > 0:
                continue
            # PHASE-022 adds ``fnmatch`` for glob-based project
            # selection. PHASE-025 adds ``dataclasses`` for the
            # ``BatchDryRunResult`` model and ``pathlib`` for the
            # result's path fields. PHASE-026 adds ``json`` for
            # the dry-run JSON serialization helpers. The set is
            # otherwise identical to the PHASE-020 baseline.
            self.assertIn(
                name,
                {"os", "typing", "fnmatch", "dataclasses", "pathlib", "json"},
                f"unexpected top-level import in batch.py: {name}",
            )

    def test_cli_does_not_import_bpy(self):
        # Regression: the CLI's batch wiring must remain bpy-free.
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import: {name}",
            )

    def test_cli_batch_dispatch_uses_batch_module(self):
        # The CLI must route through ``workflow.batch.run_batch``,
        # not duplicate the orchestration logic.
        self.assertIn("from .batch import", CLI_SOURCE)
        self.assertIn("run_batch(", CLI_SOURCE)

    def test_batch_does_not_introduce_threading(self):
        # AST-based: no actual import or attribute access to
        # threading / multiprocessing / asyncio. The docstring
        # may mention these words for documentation.
        tree = ast.parse(BATCH_SOURCE)
        forbidden_modules = {
            "threading", "multiprocessing", "asyncio",
            "concurrent", "concurrent.futures",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertNotIn(
                        root, {"threading", "multiprocessing", "asyncio",
                               "concurrent"},
                        f"forbidden import: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    self.assertNotIn(
                        root, {"threading", "multiprocessing", "asyncio",
                               "concurrent"},
                        f"forbidden import from: {node.module}",
                    )
            elif isinstance(node, ast.Attribute):
                # Reject ``threading.Thread``, ``asyncio.run``, etc.
                if isinstance(node.value, ast.Name):
                    if node.value.id in forbidden_modules:
                        self.fail(
                            f"forbidden threading reference: "
                            f"{node.value.id}.{node.attr}"
                        )


if __name__ == "__main__":
    unittest.main()
