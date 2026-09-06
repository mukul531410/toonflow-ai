"""Tests for TOONFLOW-PHASE-026 — Machine-Readable Dry-Run JSON Output.

The dry-run JSON layer is exercised by:

- :class:`SerializationTests` — :func:`batch_dry_run_to_dict` and
  :func:`batch_dry_run_to_json`.
- :class:`DeterminismTests` — byte-for-byte stable serialization.
- :class:`CLIIntegrationTests` — ``--dry-run --json`` flag combinations.
- :class:`InvalidCombinationTests` — ``--json`` without ``--dry-run``.
- :class:`Phase024InteractionTests` — JSON reflects effective config.
- :class:`ManifestImmutabilityTests` — manifest file unchanged.
- :class:`DryRunSafetyTests` — load/replay never called.
- :class:`EmptySelectionTests` — empty selection is valid JSON.
- :class:`BackwardCompatibilityTests` — existing flags still work.
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
    apply_manifest_overrides,
    dry_run_batch_manifest,
    load_batch_manifest,
    save_batch_manifest,
)
from workflow.batch import (  # noqa: E402
    BatchDryRunResult,
    batch_dry_run_to_dict,
    batch_dry_run_to_json,
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


@dataclasses.dataclass(frozen=True)
class _Project:
    name: str
    shots: tuple = (_Shot(concept="c"),)


def _make_result(
    *,
    directory="d",
    mode="validate",
    recursive=False,
    include=("*.json",),
    exclude=(),
    projects=("a.json", "b.json"),
):
    return BatchDryRunResult(
        directory=Path(directory),
        mode=mode,
        recursive=bool(recursive),
        include=tuple(include),
        exclude=tuple(exclude),
        projects=tuple(Path(p) for p in projects),
    )


# ---------------------------------------------------------------------------
# A. Serialization
# ---------------------------------------------------------------------------


class SerializationTests(unittest.TestCase):
    def test_to_dict_correct_structure(self):
        r = _make_result()
        d = batch_dry_run_to_dict(r)
        self.assertEqual(set(d.keys()), {
            "directory", "mode", "recursive",
            "include", "exclude", "projects",
        })

    def test_to_dict_canonical_key_order(self):
        r = _make_result()
        d = batch_dry_run_to_dict(r)
        self.assertEqual(
            list(d.keys()),
            ["directory", "mode", "recursive",
             "include", "exclude", "projects"],
        )

    def test_to_dict_path_to_string(self):
        r = _make_result(directory="/abs/path")
        d = batch_dry_run_to_dict(r)
        self.assertEqual(d["directory"], "/abs/path")

    def test_to_dict_tuple_to_list(self):
        r = _make_result(include=("a", "b"), exclude=("c",))
        d = batch_dry_run_to_dict(r)
        self.assertEqual(d["include"], ["a", "b"])
        self.assertEqual(d["exclude"], ["c"])

    def test_to_dict_paths_to_strings(self):
        r = _make_result(projects=("a.json", "b.json"))
        d = batch_dry_run_to_dict(r)
        self.assertEqual(d["projects"], ["a.json", "b.json"])

    def test_to_dict_bool_conversion(self):
        r = _make_result(recursive=True)
        d = batch_dry_run_to_dict(r)
        self.assertIs(d["recursive"], True)

    def test_to_dict_invalid_result_rejected(self):
        with self.assertRaises(Exception) as cm:
            batch_dry_run_to_dict({"not": "a result"})
        # The batch layer raises BatchInputError for invalid input.
        self.assertIn("Batch input", str(cm.exception))

    def test_to_json_is_valid_json(self):
        r = _make_result()
        text = batch_dry_run_to_json(r)
        data = json.loads(text)
        self.assertEqual(data["mode"], "validate")

    def test_to_json_uses_indent_two(self):
        r = _make_result()
        text = batch_dry_run_to_json(r)
        # ``"directory"`` is the first key; with indent=2 it
        # sits at column 2.
        self.assertIn('\n  "directory":', text)

    def test_to_json_trailing_newline(self):
        r = _make_result()
        text = batch_dry_run_to_json(r)
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_to_json_ensure_ascii_false_preserves_unicode(self):
        r = _make_result(directory="./projets/été")
        text = batch_dry_run_to_json(r)
        self.assertIn("été", text)
        self.assertNotIn("\\u", text)

    def test_to_json_canonical_key_order(self):
        r = _make_result()
        text = batch_dry_run_to_json(r)
        first_keys = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('"') and ":" in stripped:
                key = stripped.split(":", 1)[0].strip().strip('"')
                first_keys.append(key)
        self.assertEqual(
            first_keys[:6],
            ["directory", "mode", "recursive",
             "include", "exclude", "projects"],
        )

    def test_to_json_no_timestamps_or_random(self):
        r = _make_result()
        text = batch_dry_run_to_json(r)
        for forbidden in ("timestamp", "uuid", "created_at",
                          "host", "user", "pid"):
            self.assertNotIn(forbidden, text.lower())


# ---------------------------------------------------------------------------
# B. Determinism
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_same_result_identical_json(self):
        r = _make_result()
        self.assertEqual(batch_dry_run_to_json(r), batch_dry_run_to_json(r))

    def test_repeated_serialization_byte_identical(self):
        r = _make_result()
        outputs = [batch_dry_run_to_json(r) for _ in range(5)]
        for other in outputs[1:]:
            self.assertEqual(outputs[0], other)

    def test_to_dict_repeated_byte_identical(self):
        r = _make_result()
        d1 = batch_dry_run_to_dict(r)
        d2 = batch_dry_run_to_dict(r)
        self.assertEqual(d1, d2)
        self.assertEqual(
            json.dumps(d1, indent=2, sort_keys=False, ensure_ascii=False),
            json.dumps(d2, indent=2, sort_keys=False, ensure_ascii=False),
        )

    def test_project_ordering_stable(self):
        r1 = _make_result(projects=("z.json", "a.json"))
        r2 = _make_result(projects=("a.json", "z.json"))
        d1 = batch_dry_run_to_dict(r1)
        d2 = batch_dry_run_to_dict(r2)
        self.assertEqual(d1["projects"], ["z.json", "a.json"])
        self.assertEqual(d2["projects"], ["a.json", "z.json"])

    def test_include_exclude_order_preserved(self):
        r = _make_result(include=("c", "a", "b"), exclude=("z", "x"))
        d = batch_dry_run_to_dict(r)
        self.assertEqual(d["include"], ["c", "a", "b"])
        self.assertEqual(d["exclude"], ["z", "x"])


# ---------------------------------------------------------------------------
# C. CLI integration
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

    def test_batch_dry_run_json_returns_zero(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate", "--dry-run", "--json"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)

    def test_batch_dry_run_json_output_is_json_only(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["batch", td, "validate", "--dry-run", "--json"],
                    stdout=buf,
                )
            text = buf.getvalue()
            data = json.loads(text)
            self.assertEqual(data["mode"], "validate")
            self.assertFalse(data["recursive"])
            self.assertIn("a.json", data["projects"][0])

    def test_batch_dry_run_json_no_banner_or_logging(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["batch", td, "validate", "--dry-run", "--json"],
                    stdout=buf,
                )
            text = buf.getvalue()
            # No plain-text summary lines.
            self.assertNotIn("Dry-run:", text)
            self.assertNotIn("Projects: 1", text)

    def test_batch_dry_run_json_exactly_one_document(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["batch", td, "validate", "--dry-run", "--json"],
                    stdout=buf,
                )
            text = buf.getvalue()
            # Exactly one trailing newline.
            self.assertTrue(text.endswith("\n"))
            self.assertFalse(text.endswith("\n\n"))
            # Single JSON document.
            data = json.loads(text)
            self.assertEqual(len(data["projects"]), 2)

    def test_manifest_dry_run_json_returns_zero(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            path = self._save_manifest(td, mode="validate")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--dry-run", "--json"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["mode"], "validate")

    def test_manifest_dry_run_json_reflects_overrides(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            path = self._save_manifest(
                td, mode="validate", recursive=False, include=("a.json",),
            )
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run", "--json",
                     "--include", "b.json"],
                    stdout=buf,
                )
            data = json.loads(buf.getvalue())
            self.assertEqual(data["include"], ["b.json"])
            self.assertNotIn("a.json", data["projects"][0])

    def test_plain_text_dry_run_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["batch", td, "validate", "--dry-run"],
                    stdout=buf,
                )
            text = buf.getvalue()
            self.assertIn("Dry-run:", text)
            self.assertIn("Projects: 1", text)


# ---------------------------------------------------------------------------
# D. Invalid combinations
# ---------------------------------------------------------------------------


class InvalidCombinationTests(unittest.TestCase):
    def test_batch_json_without_dry_run_returns_two(self):
        with _tempdir() as td:
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate", "--json"],
                    stdout=buf,
                )
            self.assertEqual(rc, 2)
            self.assertIn("error:", buf.getvalue())

    def test_manifest_json_without_dry_run_returns_two(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            path = os.path.join(td, "m.json")
            save_batch_manifest(
                BatchManifest(directory=td, mode="validate"), path,
            )
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["manifest", path, "--json"],
                    stdout=buf,
                )
            self.assertEqual(rc, 2)
            self.assertIn("error:", buf.getvalue())


# ---------------------------------------------------------------------------
# E. PHASE-024 interaction
# ---------------------------------------------------------------------------


class Phase024InteractionTests(unittest.TestCase):
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

    def test_no_recursive_overrides_manifest_true(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            path = self._save_manifest(td, recursive=True)
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run", "--json",
                     "--no-recursive"],
                    stdout=buf,
                )
            data = json.loads(buf.getvalue())
            self.assertFalse(data["recursive"])

    def test_recursive_overrides_manifest_false(self):
        with _tempdir() as td:
            sub = os.path.join(td, "sub")
            os.mkdir(sub)
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(sub, "b.json", _Project(name="b"))
            path = self._save_manifest(td, recursive=False)
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run", "--json",
                     "--recursive"],
                    stdout=buf,
                )
            data = json.loads(buf.getvalue())
            self.assertTrue(data["recursive"])

    def test_cli_include_replaces_manifest_include(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            path = self._save_manifest(
                td, include=("a.json", "b.json"),
            )
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run", "--json",
                     "--include", "b.json"],
                    stdout=buf,
                )
            data = json.loads(buf.getvalue())
            self.assertEqual(data["include"], ["b.json"])

    def test_cli_exclude_replaces_manifest_exclude(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            _write_project(td, "b.json", _Project(name="b"))
            path = self._save_manifest(
                td, include=("a.json", "b.json"),
                exclude=("a.json",),
            )
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run", "--json",
                     "--exclude", "b.json"],
                    stdout=buf,
                )
            data = json.loads(buf.getvalue())
            self.assertEqual(data["exclude"], ["b.json"])


# ---------------------------------------------------------------------------
# F. Manifest immutability
# ---------------------------------------------------------------------------


class ManifestImmutabilityTests(unittest.TestCase):
    def test_manifest_file_unchanged_after_dry_run_json(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            path = str(
                save_batch_manifest(m, os.path.join(td, "m.json"))
            )
            before = Path(path).read_bytes()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run", "--json"],
                    stdout=buf,
                )
            after = Path(path).read_bytes()
            self.assertEqual(before, after)

    def test_manifest_object_not_mutated_by_serialization(self):
        with _tempdir() as td:
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            snapshot = (
                m.directory, m.mode, m.include, m.exclude,
                m.recursive, m.report_path, m.schema_version,
            )
            r = dry_run_batch_manifest(m)
            batch_dry_run_to_json(r)
            self.assertEqual(
                (m.directory, m.mode, m.include, m.exclude,
                 m.recursive, m.report_path, m.schema_version),
                snapshot,
            )


# ---------------------------------------------------------------------------
# G. Dry-run safety
# ---------------------------------------------------------------------------


class DryRunSafetyTests(unittest.TestCase):
    def test_batch_dry_run_json_does_not_call_load(self):
        load_calls = []
        replay_calls = []
        def _load(p):
            load_calls.append(p)
            return _Project(name="x")
        def _replay(proj):
            replay_calls.append(proj)
            return None

        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["batch", td, "validate", "--dry-run", "--json"],
                    stdout=buf,
                    load_project=_load,
                    replay_project=_replay,
                )
        self.assertEqual(load_calls, [])
        self.assertEqual(replay_calls, [])

    def test_manifest_dry_run_json_does_not_call_load(self):
        load_calls = []
        def _load(p):
            load_calls.append(p)
            return _Project(name="x")

        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            path = str(
                save_batch_manifest(m, os.path.join(td, "m.json"))
            )
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run", "--json"],
                    stdout=buf,
                    load_project=_load,
                )
        self.assertEqual(load_calls, [])

    def test_dry_run_json_no_report_written(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            report = os.path.join(td, "r.json")
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["batch", td, "validate", "--dry-run", "--json",
                     "--report", report],
                    stdout=buf,
                )
            self.assertFalse(os.path.exists(report))

    def test_dry_run_json_does_not_modify_project_files(self):
        with _tempdir() as td:
            path = _write_project(td, "a.json", _Project(name="a"))
            before = Path(path).read_bytes()
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["batch", td, "validate", "--dry-run", "--json"],
                    stdout=buf,
                )
            after = Path(path).read_bytes()
            self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# H. Empty selection
# ---------------------------------------------------------------------------


class EmptySelectionTests(unittest.TestCase):
    def test_empty_projects_is_valid_json(self):
        r = _make_result(projects=())
        text = batch_dry_run_to_json(r)
        data = json.loads(text)
        self.assertEqual(data["projects"], [])

    def test_empty_selection_cli_returns_zero(self):
        with _tempdir() as td:
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(
                    ["batch", td, "validate", "--dry-run", "--json"],
                    stdout=buf,
                )
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["projects"], [])

    def test_empty_manifest_dry_run_json(self):
        with _tempdir() as td:
            # Place the manifest in a separate ``config``
            # subdirectory so the project directory is empty.
            cfg = os.path.join(td, "config")
            os.mkdir(cfg)
            m = BatchManifest(
                directory=td, mode="validate", recursive=False,
            )
            path = str(
                save_batch_manifest(m, os.path.join(cfg, "m.json"))
            )
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                cli_main(
                    ["manifest", path, "--dry-run", "--json"],
                    stdout=buf,
                )
            data = json.loads(buf.getvalue())
            self.assertEqual(data["projects"], [])


# ---------------------------------------------------------------------------
# I. Backward compatibility
# ---------------------------------------------------------------------------


class BackwardCompatibilityTests(unittest.TestCase):
    def test_normal_batch_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(["batch", td, "validate"], stdout=buf)
            self.assertEqual(rc, 0)
            self.assertNotIn("Dry-run:", buf.getvalue())

    def test_normal_manifest_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            path = str(
                save_batch_manifest(m, os.path.join(td, "m.json"))
            )
            buf = io.StringIO()
            with _quiet_argparse_stderr():
                rc = cli_main(["manifest", path], stdout=buf)
            # The default ``load_project`` will load and
            # validate the file, returning exit 0.
            self.assertEqual(rc, 0)
            self.assertNotIn("Dry-run:", buf.getvalue())

    def test_dry_run_batch_function_unchanged(self):
        # The PHASE-025 dry_run_batch entry point still
        # returns a BatchDryRunResult and never produces
        # JSON as a side effect.
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            r = dry_run_batch(td, "validate")
            self.assertIsInstance(r, BatchDryRunResult)

    def test_dry_run_batch_manifest_function_unchanged(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            m = BatchManifest(
                directory=td, mode="validate",
                include=("a.json",), recursive=False,
            )
            r = dry_run_batch_manifest(m)
            self.assertIsInstance(r, BatchDryRunResult)

    def test_run_batch_with_dry_run_returns_int(self):
        with _tempdir() as td:
            _write_project(td, "a.json", _Project(name="a"))
            buf = io.StringIO()
            rc = run_batch(td, "validate", stdout=buf, dry_run=True)
            self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# J. Architecture
# ---------------------------------------------------------------------------


class ArchitectureTests(unittest.TestCase):
    def test_batch_does_not_import_bpy(self):
        for name in _ast_all_imports(BATCH_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import in batch.py: {name}",
            )

    def test_manifest_does_not_import_bpy(self):
        for name in _ast_all_imports(MANIFEST_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import in manifest.py: {name}",
            )

    def test_cli_does_not_import_bpy(self):
        for name in _ast_all_imports(CLI_SOURCE):
            self.assertFalse(
                name == "bpy" or name.startswith("bpy."),
                f"forbidden bpy import in cli.py: {name}",
            )

    def test_no_threading_asyncio_subprocess(self):
        for src in (BATCH_SOURCE, MANIFEST_SOURCE, CLI_SOURCE):
            for needle in (
                "import threading", "import asyncio",
                "import subprocess", "import multiprocessing",
                "from threading", "from asyncio", "from subprocess",
                "from multiprocessing",
            ):
                self.assertNotIn(needle, src)

    def test_no_network(self):
        for src in (BATCH_SOURCE, MANIFEST_SOURCE, CLI_SOURCE):
            for needle in (
                "import requests", "import urllib", "import http",
                "import socket", "from urllib", "from requests",
            ):
                self.assertNotIn(needle, src)

    def test_no_print_or_input(self):
        for src in (BATCH_SOURCE, MANIFEST_SOURCE, CLI_SOURCE):
            for needle in ("print(", "input("):
                self.assertNotIn(needle, src)

    def test_dry_run_serializer_functions_exist(self):
        self.assertIn("def batch_dry_run_to_dict(", BATCH_SOURCE)
        self.assertIn("def batch_dry_run_to_json(", BATCH_SOURCE)

    def test_cli_validates_json_requires_dry_run(self):
        # The CLI must reject ``--json`` without ``--dry-run``.
        # We verify the validation message is present in the
        # source so future refactors keep the contract.
        self.assertIn("--json requires --dry-run", CLI_SOURCE)

    def test_json_output_uses_dedicated_serializer(self):
        # The CLI must delegate to the dedicated
        # ``batch_dry_run_to_json`` serializer rather than
        # reimplementing JSON formatting.
        self.assertIn("batch_dry_run_to_json", CLI_SOURCE)
        self.assertIn("_default_dry_run_to_json", CLI_SOURCE)


if __name__ == "__main__":
    unittest.main()
