"""Tests for TOONFLOW-PHASE-019 — Project CLI & Batch Runner Foundation.

The CLI is a thin orchestration layer on top of the existing
workflow APIs. These tests do not require Blender, bpy, Ollama, a
real renderer, or a real AI server. They exercise every command
through :func:`workflow.cli.main` with injected ``load_project``
and ``replay_project`` callables and a real temporary file system
only where strictly necessary (the ``validate`` and ``show``
commands, which load a real on-disk JSON file via
:func:`workflow.load_project`).

The tests are grouped as:

- :class:`PublicAPITests` — the public surface.
- :class:`ArgumentHandlingTests` — argument validation.
- :class:`ValidateCommandTests` — the ``validate`` command.
- :class:`ShowCommandTests` — the ``show`` command.
- :class:`RunCommandTests` — the ``run`` command.
- :class:`DependencyInjectionTests` — DI hooks.
- :class:`ArchitectureTests` — AST-based guard rails.
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
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_ROOT = PROJECT_ROOT / "addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


from workflow import (  # noqa: E402
    PROJECT_SCHEMA_VERSION,
    Project,
    ProjectInputError,
    Shot,
    load_project,
    save_project,
)
from workflow.cli import main as cli_main  # noqa: E402


CLI_SOURCE = (PROJECT_ROOT / "workflow" / "cli.py").read_text(
    encoding="utf-8",
)
MAIN_SOURCE = (PROJECT_ROOT / "workflow" / "__main__.py").read_text(
    encoding="utf-8",
)
WORKFLOW_INIT_SOURCE = (PROJECT_ROOT / "workflow" / "__init__.py").read_text(
    encoding="utf-8",
)


# --- Helpers ----------------------------------------------------------------


def _make_project(name="demo_project", description="", shots=None):
    if shots is None:
        shots = (
            Shot(concept="A husband waves in a living room"),
            Shot(
                concept="A wife smiles in the same room",
                animation="wave",
                output_path="/tmp/shot_1.png",
            ),
        )
    return Project(
        name=name,
        description=description,
        shots=tuple(shots),
    )


def _write_project(project, directory):
    path = os.path.join(directory, "project.json")
    save_project(project, path)
    return path


@dataclasses.dataclass(frozen=True)
class _FakeShotResult:
    output_path: str = ""


@dataclasses.dataclass(frozen=True)
class _FakeMultiShotResult:
    shot_results: tuple = ()
    output_paths: tuple = ()
    shot_count: int = 0


def _make_fake_replay_result(output_paths):
    n = len(output_paths)
    shot_results = tuple(_FakeShotResult(p) for p in output_paths)
    return _FakeMultiShotResult(
        shot_results=shot_results,
        output_paths=tuple(output_paths),
        shot_count=n,
    )


@contextlib.contextmanager
def _quiet_argparse_stderr():
    """Suppress argparse's stderr output during tests.

    argparse writes argument-parsing errors to ``sys.stderr``
    directly. The CLI entry point converts those errors to a
    return code, so the only thing left on stderr is the
    human-readable error message. Tests that assert return codes
    do not care about the message; this context manager keeps
    the test output clean.
    """
    saved = sys.stderr
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stderr = saved


@contextlib.contextmanager
def _tempdir():
    with tempfile.TemporaryDirectory() as td:
        yield td


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


def _ast_top_level_calls(source, name):
    """Return a list of (lineno, arg_count) for top-level calls of *name*."""
    tree = ast.parse(source)
    out = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == name:
                out.append((node.lineno, len(node.value.args)))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PublicAPITests(unittest.TestCase):
    def test_cli_main_is_callable(self):
        self.assertTrue(callable(cli_main))

    def test_workflow_package_exposes_main(self):
        # The CLI entry point is exposed from ``workflow.cli`` but
        # not added to ``workflow.__init__`` (PHASE-019 keeps the
        # public package API stable).
        import workflow.cli as cli_mod
        self.assertTrue(hasattr(cli_mod, "main"))

    def test_module_entry_point_exists(self):
        path = PROJECT_ROOT / "workflow" / "__main__.py"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("if __name__", text)
        self.assertIn("sys.exit", text)
        self.assertIn("from .cli import main", text)

    def test_existing_workflow_apis_unchanged(self):
        # The CLI must not modify or shadow any pre-existing
        # workflow public symbol.
        import workflow
        for name in (
            "create_and_render_scene",
            "create_and_render_shots",
            "WorkflowResult",
            "Shot",
            "MultiShotResult",
            "Project",
            "ProjectInputError",
            "load_project",
            "save_project",
            "replay_project",
            "PROJECT_SCHEMA_VERSION",
        ):
            self.assertTrue(hasattr(workflow, name), name)

    def test_workflow_init_does_not_expose_cli(self):
        # The CLI lives in ``workflow.cli`` and is invokable as
        # ``python -m workflow``. The top-level package keeps its
        # PHASE-015..018 public surface stable: ``main`` is not
        # re-exported from ``workflow``. (The ``cli`` submodule
        # attribute is a normal Python package side effect and is
        # allowed.)
        import workflow
        self.assertFalse(hasattr(workflow, "main"))


# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------


class ArgumentHandlingTests(unittest.TestCase):
    def test_missing_command_fails(self):
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            rc = cli_main([], stdout=buf)
        self.assertNotEqual(rc, 0)
        self.assertEqual(rc, 2)

    def test_unknown_command_fails(self):
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            rc = cli_main(["frobnicate"], stdout=buf)
        self.assertNotEqual(rc, 0)
        self.assertEqual(rc, 2)

    def test_validate_missing_path_fails(self):
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            rc = cli_main(["validate"], stdout=buf)
        self.assertNotEqual(rc, 0)
        self.assertEqual(rc, 2)

    def test_show_missing_path_fails(self):
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            rc = cli_main(["show"], stdout=buf)
        self.assertNotEqual(rc, 0)
        self.assertEqual(rc, 2)

    def test_run_missing_path_fails(self):
        with _quiet_argparse_stderr():
            buf = io.StringIO()
            rc = cli_main(["run"], stdout=buf)
        self.assertNotEqual(rc, 0)
        self.assertEqual(rc, 2)

    def test_extra_invalid_arguments_fail(self):
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            with _quiet_argparse_stderr():
                buf = io.StringIO()
                rc = cli_main(
                    ["validate", path, "extra-positional"],
                    stdout=buf,
                )
        self.assertNotEqual(rc, 0)
        self.assertEqual(rc, 2)

    def test_help_flag_exits_zero(self):
        # ``--help`` is argparse-managed. With ``exit_on_error=False``
        # the parser prints the help text to ``stdout`` and returns
        # ``0`` instead of raising ``SystemExit``. The CLI entry
        # point surfaces this as a zero return code.
        buf_out = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            rc = cli_main(["--help"], stdout=buf_out)
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# Validate command
# ---------------------------------------------------------------------------


class ValidateCommandTests(unittest.TestCase):
    def test_valid_project_succeeds(self):
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            buf = io.StringIO()
            rc = cli_main(["validate", path], stdout=buf)
        self.assertEqual(rc, 0)

    def test_current_schema_project_succeeds(self):
        with _tempdir() as td:
            project = _make_project()
            self.assertEqual(project.schema_version, PROJECT_SCHEMA_VERSION)
            path = _write_project(project, td)
            buf = io.StringIO()
            rc = cli_main(["validate", path], stdout=buf)
        self.assertEqual(rc, 0)

    def test_migrated_v1_project_succeeds(self):
        # A v1 project document must be transparently migrated
        # through load_project and validated successfully.
        with _tempdir() as td:
            path = os.path.join(td, "v1.json")
            v1_dict = {
                "schema_version": 1,
                "name": "legacy",
                "shots": [
                    {
                        "concept": "c",
                        "animation": None,
                        "animation_start_frame": 1,
                        "lip_sync": False,
                        "lip_sync_start_frame": 1,
                        "output_path": None,
                    },
                ],
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(v1_dict, fh)
            buf = io.StringIO()
            rc = cli_main(["validate", path], stdout=buf)
        self.assertEqual(rc, 0)

    def test_output_contains_project_name(self):
        with _tempdir() as td:
            path = _write_project(_make_project(name="renamed_xyz"), td)
            buf = io.StringIO()
            cli_main(["validate", path], stdout=buf)
        self.assertIn("renamed_xyz", buf.getvalue())

    def test_output_contains_schema_version(self):
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            buf = io.StringIO()
            cli_main(["validate", path], stdout=buf)
        self.assertIn(
            f"Schema version: {PROJECT_SCHEMA_VERSION}",
            buf.getvalue(),
        )

    def test_output_contains_shot_count(self):
        with _tempdir() as td:
            project = _make_project(shots=(
                Shot(concept="a"),
                Shot(concept="b"),
                Shot(concept="c"),
            ))
            path = _write_project(project, td)
            buf = io.StringIO()
            cli_main(["validate", path], stdout=buf)
        self.assertIn("Shots: 3", buf.getvalue())

    def test_output_contains_validity_message(self):
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            buf = io.StringIO()
            cli_main(["validate", path], stdout=buf)
        self.assertIn("Project is valid", buf.getvalue())

    def test_invalid_project_returns_nonzero(self):
        with _tempdir() as td:
            path = os.path.join(td, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("not json")
            buf = io.StringIO()
            rc = cli_main(["validate", path], stdout=buf)
        self.assertNotEqual(rc, 0)

    def test_schema_error_returns_nonzero(self):
        # Unsupported future schema version is rejected by the
        # project layer, which the CLI propagates as a non-zero
        # exit code.
        with _tempdir() as td:
            path = os.path.join(td, "future.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "schema_version": 99,
                        "name": "x",
                        "shots": [
                            {
                                "concept": "c",
                                "animation": None,
                                "animation_start_frame": 1,
                                "lip_sync": False,
                                "lip_sync_start_frame": 1,
                                "output_path": None,
                            }
                        ],
                    },
                    fh,
                )
            buf = io.StringIO()
            rc = cli_main(["validate", path], stdout=buf)
        self.assertNotEqual(rc, 0)

    def test_missing_file_returns_nonzero(self):
        with _tempdir() as td:
            buf = io.StringIO()
            rc = cli_main(
                ["validate", os.path.join(td, "does-not-exist.json")],
                stdout=buf,
            )
        self.assertNotEqual(rc, 0)

    def test_does_not_call_replay(self):
        # The ``validate`` command must not invoke
        # ``replay_project`` under any circumstance.
        calls = []
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            buf = io.StringIO()
            rc = cli_main(
                ["validate", path],
                stdout=buf,
                replay_project=lambda *a, **kw: calls.append((a, kw)),
            )
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])


# ---------------------------------------------------------------------------
# Show command
# ---------------------------------------------------------------------------


class ShowCommandTests(unittest.TestCase):
    def test_valid_project_succeeds(self):
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            buf = io.StringIO()
            rc = cli_main(["show", path], stdout=buf)
        self.assertEqual(rc, 0)

    def test_output_contains_project_name(self):
        with _tempdir() as td:
            path = _write_project(_make_project(name="alpha"), td)
            buf = io.StringIO()
            cli_main(["show", path], stdout=buf)
        self.assertIn("Name: alpha", buf.getvalue())

    def test_output_contains_schema_version(self):
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            buf = io.StringIO()
            cli_main(["show", path], stdout=buf)
        self.assertIn(
            f"Schema version: {PROJECT_SCHEMA_VERSION}",
            buf.getvalue(),
        )

    def test_output_contains_description(self):
        with _tempdir() as td:
            path = _write_project(
                _make_project(description="my project desc"),
                td,
            )
            buf = io.StringIO()
            cli_main(["show", path], stdout=buf)
        self.assertIn("Description: my project desc", buf.getvalue())

    def test_output_contains_shot_count(self):
        with _tempdir() as td:
            project = _make_project(shots=(
                Shot(concept="a"),
                Shot(concept="b"),
            ))
            path = _write_project(project, td)
            buf = io.StringIO()
            cli_main(["show", path], stdout=buf)
        self.assertIn("Shots: 2", buf.getvalue())

    def test_shot_ordering_is_preserved(self):
        with _tempdir() as td:
            project = _make_project(shots=(
                Shot(concept="FIRST"),
                Shot(concept="SECOND"),
                Shot(concept="THIRD"),
            ))
            path = _write_project(project, td)
            buf = io.StringIO()
            cli_main(["show", path], stdout=buf)
        out = buf.getvalue()
        first = out.find("FIRST")
        second = out.find("SECOND")
        third = out.find("THIRD")
        self.assertGreaterEqual(first, 0)
        self.assertGreater(second, first)
        self.assertGreater(third, second)

    def test_shot_details_are_deterministic(self):
        with _tempdir() as td:
            project = _make_project(shots=(
                Shot(
                    concept="c_one",
                    animation="wave",
                    output_path="/o/one.png",
                ),
            ))
            path = _write_project(project, td)
            buf1 = io.StringIO()
            cli_main(["show", path], stdout=buf1)
            buf2 = io.StringIO()
            cli_main(["show", path], stdout=buf2)
        self.assertEqual(buf1.getvalue(), buf2.getvalue())
        text = buf1.getvalue()
        self.assertIn("concept='c_one'", text)
        self.assertIn("animation='wave'", text)
        self.assertIn("output_path='/o/one.png'", text)

    def test_project_is_not_mutated(self):
        with _tempdir() as td:
            project = _make_project()
            path = _write_project(project, td)
            buf = io.StringIO()
            cli_main(["show", path], stdout=buf)
            reloaded = load_project(path)
        self.assertEqual(project.name, reloaded.name)
        self.assertEqual(
            [s.concept for s in project.shots],
            [s.concept for s in reloaded.shots],
        )

    def test_project_file_is_not_modified(self):
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            with open(path, "rb") as fh:
                before = fh.read()
            buf = io.StringIO()
            cli_main(["show", path], stdout=buf)
            with open(path, "rb") as fh:
                after = fh.read()
        self.assertEqual(before, after)

    def test_does_not_call_replay(self):
        calls = []
        with _tempdir() as td:
            path = _write_project(_make_project(), td)
            buf = io.StringIO()
            rc = cli_main(
                ["show", path],
                stdout=buf,
                replay_project=lambda *a, **kw: calls.append((a, kw)),
            )
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])


# ---------------------------------------------------------------------------
# Run command
# ---------------------------------------------------------------------------


class RunCommandTests(unittest.TestCase):
    def _run_with_fakes(
        self,
        project,
        fake_output_paths,
        *,
        load_exception=None,
        replay_exception=None,
        replay_calls_out=None,
        load_calls_out=None,
    ):
        """Helper: drive the run command with injected fakes."""
        load_calls = load_calls_out if load_calls_out is not None else []
        replay_calls = replay_calls_out if replay_calls_out is not None else []

        def fake_load(path):
            load_calls.append(path)
            if load_exception is not None:
                raise load_exception
            return project

        def fake_replay(proj, **kw):
            replay_calls.append((proj, kw))
            if replay_exception is not None:
                raise replay_exception
            return _make_fake_replay_result(fake_output_paths)

        with _tempdir() as td:
            path = _write_project(project, td)
            buf = io.StringIO()
            rc = cli_main(
                ["run", path],
                stdout=buf,
                load_project=fake_load,
                replay_project=fake_replay,
            )
        return rc, buf.getvalue(), load_calls, replay_calls

    def test_loads_the_project(self):
        project = _make_project()
        rc, _out, load_calls, _ = self._run_with_fakes(
            project, fake_output_paths=("/x/1.png",),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(load_calls), 1)

    def test_delegates_exactly_once_to_replay(self):
        project = _make_project(shots=(
            Shot(concept="a"), Shot(concept="b"),
        ))
        rc, _out, _load, replay_calls = self._run_with_fakes(
            project,
            fake_output_paths=("/x/1.png", "/x/2.png"),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(replay_calls), 1)

    def test_does_not_call_lower_level_workflow_functions(self):
        # The CLI must not import or call create_and_render_scene
        # / create_and_render_shots directly. Detect by AST and
        # by the absence of those names in cli.py.
        import workflow.cli as cli_mod
        self.assertFalse(hasattr(cli_mod, "create_and_render_scene"))
        self.assertFalse(hasattr(cli_mod, "create_and_render_shots"))
        for name in ("create_and_render_scene", "create_and_render_shots"):
            self.assertNotIn(name, CLI_SOURCE)

    def test_output_contains_project_name(self):
        project = _make_project(name="renamed_run")
        rc, out, _l, _r = self._run_with_fakes(
            project, fake_output_paths=("/x/1.png",),
        )
        self.assertEqual(rc, 0)
        self.assertIn("Project: renamed_run", out)

    def test_output_contains_shot_count(self):
        project = _make_project(shots=(
            Shot(concept="a"),
            Shot(concept="b"),
            Shot(concept="c"),
        ))
        rc, out, _l, _r = self._run_with_fakes(
            project,
            fake_output_paths=("/x/1.png", "/x/2.png", "/x/3.png"),
        )
        self.assertEqual(rc, 0)
        self.assertIn("Shots: 3", out)

    def test_output_paths_preserve_result_order(self):
        project = _make_project(shots=(
            Shot(concept="a"),
            Shot(concept="b"),
            Shot(concept="c"),
        ))
        rc, out, _l, _r = self._run_with_fakes(
            project,
            fake_output_paths=("/z/3.png", "/y/2.png", "/x/1.png"),
        )
        self.assertEqual(rc, 0)
        # Paths must appear in input/result order: /z/3, /y/2, /x/1.
        i1 = out.find("/z/3.png")
        i2 = out.find("/y/2.png")
        i3 = out.find("/x/1.png")
        self.assertGreaterEqual(i1, 0)
        self.assertGreater(i2, i1)
        self.assertGreater(i3, i2)

    def test_replay_error_returns_nonzero(self):
        project = _make_project()
        rc, _out, _l, replay_calls = self._run_with_fakes(
            project,
            fake_output_paths=(),
            replay_exception=RuntimeError("boom"),
        )
        self.assertNotEqual(rc, 0)
        self.assertEqual(len(replay_calls), 1)

    def test_loading_failure_prevents_replay(self):
        project = _make_project()
        replay_calls = []
        rc, _out, _l, replay_calls = self._run_with_fakes(
            project,
            fake_output_paths=(),
            load_exception=ProjectInputError("path", "/nope.json"),
        )
        self.assertNotEqual(rc, 0)
        self.assertEqual(replay_calls, [])

    def test_repeated_equivalent_runs_delegate_equivalently(self):
        project = _make_project()
        rc1, out1, _l1, r1 = self._run_with_fakes(
            project, fake_output_paths=("/x/1.png",),
        )
        rc2, out2, _l2, r2 = self._run_with_fakes(
            project, fake_output_paths=("/x/1.png",),
        )
        self.assertEqual(rc1, rc2)
        self.assertEqual(out1, out2)
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)

    def test_replay_called_with_loaded_project(self):
        project = _make_project(name="specific_name")
        rc, _out, _l, replay_calls = self._run_with_fakes(
            project, fake_output_paths=("/x/1.png",),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(replay_calls), 1)
        called_project, _kw = replay_calls[0]
        self.assertIs(called_project, project)

    def test_replay_forwarded_to_existing_api(self):
        # The default ``replay_project`` injection must delegate
        # to the real workflow.replay_project. Use a real
        # project file and a stub workflow_callable to confirm
        # the chain ``CLI -> replay_project -> multi-shot -> stub``.
        from workflow.shots import create_and_render_shots
        calls = []
        def stub(**fields):
            calls.append(fields)
            return _FakeShotResult(output_path=f"/o/{len(calls)}.png")
        project = _make_project(shots=(
            Shot(concept="one"),
            Shot(concept="two"),
        ))
        with _tempdir() as td:
            path = _write_project(project, td)
            buf = io.StringIO()
            # Pass through the real replay_project, which forwards
            # the stub as the multi-shot workflow_callable.
            rc = cli_main(
                ["run", path],
                stdout=buf,
                # leave load_project default
                # replace replay_project with a wrapper around the
                # real one that injects the stub workflow_callable.
                replay_project=lambda p, **kw: (
                    # call the real replay_project (via the
                    # workflow package import)
                    __import__("workflow").replay_project(
                        p, workflow_callable=stub,
                    )
                ),
            )
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["concept"], "one")
        self.assertEqual(calls[1]["concept"], "two")


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


class DependencyInjectionTests(unittest.TestCase):
    def test_fake_load_project_can_be_injected(self):
        sentinel_project = _make_project(name="sentinel")

        def fake_load(path):
            return sentinel_project

        buf = io.StringIO()
        rc = cli_main(
            ["validate", "/does/not/matter.json"],
            stdout=buf,
            load_project=fake_load,
        )
        self.assertEqual(rc, 0)
        self.assertIn("sentinel", buf.getvalue())

    def test_fake_replay_project_can_be_injected(self):
        def fake_load(path):
            return _make_project(name="dlq")

        def fake_replay(proj, **kw):
            return _make_fake_replay_result(("/a/1.png", "/a/2.png"))

        buf = io.StringIO()
        rc = cli_main(
            ["run", "/does/not/matter.json"],
            stdout=buf,
            load_project=fake_load,
            replay_project=fake_replay,
        )
        self.assertEqual(rc, 0)
        self.assertIn("Project: dlq", buf.getvalue())
        self.assertIn("/a/1.png", buf.getvalue())
        self.assertIn("/a/2.png", buf.getvalue())

    def test_validate_does_not_require_replay_project(self):
        # The ``validate`` command handler does not take a
        # ``replay_project`` argument; passing one is a no-op.
        def fake_load(path):
            return _make_project(name="v")

        def fake_replay(proj, **kw):
            raise AssertionError("replay must not be called for validate")

        buf = io.StringIO()
        rc = cli_main(
            ["validate", "/x.json"],
            stdout=buf,
            load_project=fake_load,
            replay_project=fake_replay,
        )
        self.assertEqual(rc, 0)

    def test_show_does_not_require_replay_project(self):
        def fake_load(path):
            return _make_project(name="s")

        def fake_replay(proj, **kw):
            raise AssertionError("replay must not be called for show")

        buf = io.StringIO()
        rc = cli_main(
            ["show", "/x.json"],
            stdout=buf,
            load_project=fake_load,
            replay_project=fake_replay,
        )
        self.assertEqual(rc, 0)

    def test_default_load_project_loads_real_file(self):
        with _tempdir() as td:
            path = _write_project(_make_project(name="real"), td)
            buf = io.StringIO()
            # No ``load_project`` injection: must use the real
            # ``workflow.load_project``.
            rc = cli_main(["validate", path], stdout=buf)
        self.assertEqual(rc, 0)
        self.assertIn("real", buf.getvalue())

    def test_no_bpy_dependency_in_cli(self):
        # The CLI must not import bpy. The default
        # ``load_project`` and ``replay_project`` only import
        # bpy-free workflow modules. Smoke test: importing the
        # CLI must not require bpy to be importable.
        import workflow.cli  # noqa: F401

    def test_no_ollama_or_networking_dependency(self):
        for name in _ast_all_imports(CLI_SOURCE):
            root = name.split(".")[0]
            self.assertNotIn(
                root,
                {"ai", "ollama", "ollama_client", "urllib",
                 "urllib.request", "requests", "http"},
                f"forbidden import: {name}",
            )


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


class ArchitectureTests(unittest.TestCase):
    def test_cli_does_not_import_bpy(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import: {name}",
            )

    def test_cli_does_not_import_ollama(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"ollama", "ollama_client"},
                f"forbidden ollama import: {name}",
            )

    def test_cli_does_not_import_requests(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"requests"},
                f"forbidden requests import: {name}",
            )

    def test_cli_does_not_import_urllib(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"urllib", "urllib.request"},
                f"forbidden urllib import: {name}",
            )

    def test_cli_does_not_import_pipeline(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"pipeline"},
                f"forbidden pipeline import: {name}",
            )

    def test_cli_does_not_import_asset_registry(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"asset_registry"},
                f"forbidden asset_registry import: {name}",
            )

    def test_cli_does_not_import_scene_plan(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertNotIn(
                name.split(".")[0], {"scene_plan"},
                f"forbidden scene_plan import: {name}",
            )

    def test_cli_does_not_import_toonflow_ai_generation(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertFalse(
                name.startswith("toonflow_ai"),
                f"forbidden toonflow_ai import: {name}",
            )

    def test_cli_does_not_reference_bpy_data_or_bpy_ops(self):
        # The CLI source must not contain literal bpy.data or
        # bpy.ops references.
        self.assertNotIn("bpy.data", CLI_SOURCE)
        self.assertNotIn("bpy.ops", CLI_SOURCE)

    def test_cli_does_not_call_keyframe_insert(self):
        self.assertNotIn("keyframe_insert", CLI_SOURCE)

    def test_cli_does_not_call_rendering_apis(self):
        for forbidden in (
            "render_scene(", "create_or_update_camera(",
            "from_pydata(", "bpy.ops.render",
        ):
            self.assertNotIn(forbidden, CLI_SOURCE)

    def test_cli_does_not_duplicate_schema_migration(self):
        # The CLI must not import the migration module. It
        # delegates to load_project, which owns migration.
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertNotEqual(
                name, "project_migrations",
                "CLI must not import the migration module",
            )
            self.assertFalse(
                name.endswith(".project_migrations"),
                f"CLI must not import migration module: {name}",
            )
        for forbidden in (
            "migrate_project_dict", "migrate_project_dict_to_version",
            "UnsupportedProjectSchemaError",
        ):
            self.assertNotIn(forbidden, CLI_SOURCE)

    def test_cli_does_not_call_create_and_render_scene(self):
        # Direct invocation of the single-shot workflow is
        # forbidden in the CLI. Only ``replay_project`` may be
        # called.
        self.assertNotIn("create_and_render_scene", CLI_SOURCE)

    def test_cli_does_not_call_create_and_render_shots(self):
        # The CLI must go through ``replay_project``; direct
        # calls to the multi-shot orchestrator are forbidden.
        self.assertNotIn("create_and_render_shots", CLI_SOURCE)

    def test_cli_does_not_open_files(self):
        # The CLI must not call ``open(`` directly. File I/O is
        # owned by ``workflow.load_project``.
        self.assertNotIn("open(", CLI_SOURCE)

    def test_cli_does_not_use_print_or_input(self):
        self.assertNotIn("print(", CLI_SOURCE)
        self.assertNotIn("input(", CLI_SOURCE)

    def test_top_level_imports_minimal(self):
        tree = ast.parse(CLI_SOURCE)
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
            self.assertIn(
                name,
                {"argparse", "sys", "typing"},
                f"unexpected top-level import: {name}",
            )

    def test_main_module_is_thin(self):
        # ``__main__.py`` should only re-export the CLI entry
        # point and forward to sys.exit.
        tree = ast.parse(MAIN_SOURCE)
        import_count = 0
        main_call_count = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                import_count += 1
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "main":
                    main_call_count += 1
        # At least the cli import and the sys import.
        self.assertGreaterEqual(import_count, 2)
        self.assertGreaterEqual(main_call_count, 1)
        # The __main__ module must be very short.
        self.assertLess(len(MAIN_SOURCE.splitlines()), 30)

    def test_workflow_init_not_modified_by_cli(self):
        # The CLI lives in ``workflow.cli``; the package
        # ``__init__.py`` keeps its PHASE-018 surface.
        # Specifically, no ``main`` symbol is re-exported.
        self.assertNotIn("from .cli", WORKFLOW_INIT_SOURCE)
        self.assertNotIn("import cli", WORKFLOW_INIT_SOURCE)


if __name__ == "__main__":
    unittest.main()
