"""Tests for TOONFLOW-PHASE-017 — Persistent Project Model & Deterministic Replay."""
import ast
import dataclasses
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


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
    create_and_render_scene,
    create_and_render_shots,
    load_project,
    project_from_dict,
    project_from_json,
    project_to_dict,
    project_to_json,
    replay_project,
    save_project,
)
import workflow.project as project_mod  # noqa: E402


PROJECT_SOURCE = (PROJECT_ROOT / "workflow" / "project.py").read_text(
    encoding="utf-8"
)
WORKFLOW_INIT_SOURCE = (PROJECT_ROOT / "workflow" / "__init__.py").read_text(
    encoding="utf-8"
)


# --- Helpers ----------------------------------------------------------------

def _make_project():
    return Project(
        name="demo_project",
        shots=(
            Shot(concept="A husband waves in a living room"),
            Shot(concept="A wife smiles in the same room", animation="wave"),
        ),
    )


def _fake_per_shot_workflow(*, concept, animation, animation_start_frame,
                            lip_sync, lip_sync_start_frame, output_path):
    """Stand-in for workflow.create_and_render_scene that records calls."""
    _fake_per_shot_workflow.calls.append({
        "concept": concept,
        "animation": animation,
        "animation_start_frame": animation_start_frame,
        "lip_sync": lip_sync,
        "lip_sync_start_frame": lip_sync_start_frame,
        "output_path": output_path,
    })
    index = len(_fake_per_shot_workflow.calls) - 1
    return _FakeResult(
        output_path=f"/r/shot_{index}.png",
    )


@dataclasses.dataclass(frozen=True)
class _FakeResult:
    output_path: str = ""


# --- A. Public API exposure ------------------------------------------------

class PublicApiTests(unittest.TestCase):
    def test_project_exported(self):
        self.assertTrue(callable(Project))

    def test_project_input_error_exported(self):
        self.assertTrue(callable(ProjectInputError))

    def test_project_schema_version_exported(self):
        # PHASE-018: the current schema version is now 2 (v1 is the
        # supported old version migrated forward to v2 by
        # ``project_from_dict``).
        self.assertEqual(PROJECT_SCHEMA_VERSION, 2)

    def test_helpers_exported(self):
        for name in (
            "project_to_dict", "project_from_dict",
            "project_to_json", "project_from_json",
            "save_project", "load_project", "replay_project",
        ):
            self.assertTrue(hasattr(__import__("workflow", fromlist=[name]), name), name)

    def test_existing_public_apis_remain(self):
        # Regression: do not break PHASE-015/016 exports.
        for name in (
            "create_and_render_scene", "WorkflowResult",
            "create_and_render_shots", "Shot",
            "MultiShotResult", "MultiShotInputError",
        ):
            self.assertTrue(hasattr(__import__("workflow", fromlist=[name]), name), name)

    def test_project_is_frozen(self):
        p = _make_project()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.name = "other"  # type: ignore[misc]

    def test_project_input_error_is_value_error(self):
        self.assertTrue(issubclass(ProjectInputError, ValueError))


# --- B. Project model -------------------------------------------------------

class ProjectModelTests(unittest.TestCase):
    def test_valid_creation(self):
        p = _make_project()
        self.assertEqual(p.name, "demo_project")
        self.assertEqual(len(p.shots), 2)
        for shot in p.shots:
            self.assertIsInstance(shot, Shot)

    def test_default_schema_version(self):
        p = _make_project()
        self.assertEqual(p.schema_version, PROJECT_SCHEMA_VERSION)

    def test_explicit_schema_version(self):
        p = Project(name="x", shots=(Shot(concept="a"),), schema_version=1)
        self.assertEqual(p.schema_version, 1)

    def test_shots_normalized_to_tuple(self):
        p = Project(name="x", shots=[Shot(concept="a")])
        self.assertIsInstance(p.shots, tuple)

    def test_invalid_name_rejected(self):
        for bad in (None, "", "   ", 1, True, [], {}):
            with self.assertRaises(ProjectInputError) as ctx:
                Project(name=bad, shots=(Shot(concept="a"),))
            self.assertEqual(ctx.exception.parameter, "name")

    def test_empty_shots_rejected(self):
        with self.assertRaises(ProjectInputError) as ctx:
            Project(name="x", shots=())
        self.assertEqual(ctx.exception.parameter, "shots")

    def test_non_shot_rejected(self):
        for bad in ([Shot(concept="ok"), "not a shot"], [42]):
            with self.assertRaises(ProjectInputError) as ctx:
                Project(name="x", shots=bad)
            self.assertIn("shots[", ctx.exception.parameter)

    def test_invalid_schema_version_rejected(self):
        # PHASE-018: schema_version=2 is the current supported
        # version and is therefore accepted. Only unsupported or
        # type-invalid versions are rejected. Type-invalid values
        # surface as ``ProjectInputError("schema_version", ...)``
        # while unsupported values surface as
        # ``ProjectInputError("schema_version", ...)`` as well (the
        # ``Project.__post_init__`` check raises a single error
        # class for both kinds).
        for bad in (0, -1, "1", True, None):
            with self.assertRaises(ProjectInputError) as ctx:
                Project(name="x", shots=(Shot(concept="a"),), schema_version=bad)
            self.assertEqual(ctx.exception.parameter, "schema_version")

    def test_unsupported_schema_version_rejected(self):
        with self.assertRaises(ProjectInputError) as ctx:
            Project(name="x", shots=(Shot(concept="a"),), schema_version=99)
        self.assertEqual(ctx.exception.parameter, "schema_version")


# --- C. Serialization -------------------------------------------------------

class SerializationTests(unittest.TestCase):
    def test_project_to_dict_structure(self):
        p = _make_project()
        d = project_to_dict(p)
        # PHASE-018: schema v2 adds ``description`` at the top level.
        self.assertEqual(
            set(d.keys()),
            {"schema_version", "name", "description", "shots"},
        )
        self.assertEqual(d["schema_version"], PROJECT_SCHEMA_VERSION)
        self.assertEqual(d["name"], "demo_project")
        self.assertEqual(d["description"], "")
        self.assertEqual(len(d["shots"]), 2)
        shot0 = d["shots"][0]
        self.assertEqual(
            set(shot0.keys()),
            {
                "concept", "animation", "animation_start_frame",
                "lip_sync", "lip_sync_start_frame", "output_path",
            },
        )
        self.assertEqual(shot0["concept"], "A husband waves in a living room")
        self.assertIsNone(shot0["animation"])
        self.assertEqual(shot0["animation_start_frame"], 1)
        self.assertFalse(shot0["lip_sync"])
        self.assertEqual(shot0["lip_sync_start_frame"], 1)
        self.assertIsNone(shot0["output_path"])

    def test_project_to_dict_rejects_non_project(self):
        with self.assertRaises(ProjectInputError):
            project_to_dict({"name": "x", "shots": []})  # type: ignore[arg-type]

    def test_deterministic_serialization(self):
        p = _make_project()
        s1 = project_to_json(p)
        s2 = project_to_json(p)
        self.assertEqual(s1, s2)

    def test_stable_key_ordering(self):
        p = _make_project()
        s = project_to_json(p)
        # schema_version before name before shots.
        sv_i = s.index('"schema_version"')
        nm_i = s.index('"name"')
        sh_i = s.index('"shots"')
        self.assertLess(sv_i, nm_i)
        self.assertLess(nm_i, sh_i)

    def test_json_output_round_trips(self):
        p = _make_project()
        s = project_to_json(p)
        loaded = json.loads(s)
        self.assertEqual(loaded, project_to_dict(p))

    def test_non_ascii_concept_round_trips(self):
        p = Project(
            name="unicode_demo",
            shots=(Shot(concept="家族がリビングにいる"),),
        )
        s = project_to_json(p)
        # The original concept must survive verbatim.
        self.assertIn("家族がリビングにいる", s)
        loaded = project_from_json(s)
        self.assertEqual(loaded.shots[0].concept, "家族がリビングにいる")

    def test_no_timestamps_or_randomness(self):
        p = _make_project()
        # Repeated serializations must be byte-identical.
        self.assertEqual(project_to_json(p), project_to_json(p))
        # No date / time / random substrings.
        for needle in ("T", ":", "+00:00", "uuid", "random"):
            # ":", "+00:00" could be in JSON itself; restrict to "uuid"/"random".
            if needle in {"uuid", "random"}:
                self.assertNotIn(needle, project_to_json(p).lower())


# --- D. Deserialization -----------------------------------------------------

class DeserializationTests(unittest.TestCase):
    def test_valid_round_trip_dict(self):
        p = _make_project()
        d = project_to_dict(p)
        loaded = project_from_dict(d)
        self.assertEqual(loaded, p)

    def test_valid_round_trip_json(self):
        p = _make_project()
        s = project_to_json(p)
        loaded = project_from_json(s)
        self.assertEqual(loaded, p)

    def test_non_mapping_rejected(self):
        for bad in (None, [1, 2], "string", 1, 3.14):
            with self.assertRaises(ProjectInputError):
                project_from_dict(bad)  # type: ignore[arg-type]

    def test_missing_name_rejected(self):
        with self.assertRaises(ProjectInputError) as ctx:
            project_from_dict({"schema_version": 1, "shots": [{"concept": "a"}]})
        self.assertEqual(ctx.exception.parameter, "project.name")

    def test_missing_shots_rejected(self):
        with self.assertRaises(ProjectInputError) as ctx:
            project_from_dict({"schema_version": 1, "name": "x"})
        self.assertEqual(ctx.exception.parameter, "project.shots")

    def test_empty_shots_rejected(self):
        with self.assertRaises(ProjectInputError) as ctx:
            project_from_dict({"schema_version": 1, "name": "x", "shots": []})
        self.assertEqual(ctx.exception.parameter, "project.shots")

    def test_invalid_name_rejected(self):
        with self.assertRaises(ProjectInputError):
            project_from_dict({
                "schema_version": 1, "name": "", "shots": [{"concept": "a"}],
            })

    def test_invalid_schema_version_rejected(self):
        # PHASE-018: schema_version=2 is the current supported
        # version and is therefore accepted. Only unsupported or
        # type-invalid versions are rejected. The migration layer
        # reports type errors (non-int, None, bool) as
        # ``ProjectInputError("project", ...)`` and out-of-range
        # or unsupported values as
        # ``ProjectInputError("project.schema_version", ...)``.
        type_bad = ("1", None, True)
        value_bad = (0, -1)
        expected_param_for_type = "project"
        expected_param_for_value = "project.schema_version"
        for bad in type_bad:
            with self.assertRaises(ProjectInputError) as ctx:
                project_from_dict({
                    "schema_version": bad, "name": "x", "shots": [{"concept": "a"}],
                })
            self.assertEqual(
                ctx.exception.parameter, expected_param_for_type,
                f"bad={bad!r} expected param={expected_param_for_type!r} "
                f"got {ctx.exception.parameter!r}",
            )
        for bad in value_bad:
            with self.assertRaises(ProjectInputError) as ctx:
                project_from_dict({
                    "schema_version": bad, "name": "x", "shots": [{"concept": "a"}],
                })
            self.assertEqual(
                ctx.exception.parameter, expected_param_for_value,
                f"bad={bad!r} expected param={expected_param_for_value!r} "
                f"got {ctx.exception.parameter!r}",
            )

    def test_unsupported_schema_version_rejected(self):
        # Future versions (e.g. 99) are rejected.
        with self.assertRaises(ProjectInputError) as ctx:
            project_from_dict({
                "schema_version": 99, "name": "x", "shots": [{"concept": "a"}],
            })
        self.assertEqual(ctx.exception.parameter, "project.schema_version")

    def test_missing_schema_version_rejected(self):
        with self.assertRaises(ProjectInputError) as ctx:
            project_from_dict({"name": "x", "shots": [{"concept": "a"}]})
        self.assertEqual(ctx.exception.parameter, "project.schema_version")

    def test_unknown_top_level_keys_rejected(self):
        with self.assertRaises(ProjectInputError) as ctx:
            project_from_dict({
                "schema_version": 1, "name": "x",
                "shots": [{
                    "concept": "a", "animation": None, "animation_start_frame": 1,
                    "lip_sync": False, "lip_sync_start_frame": 1, "output_path": None,
                }],
                "extra": 1,
            })
        self.assertEqual(ctx.exception.parameter, "project.unknown")

    def test_malformed_shot_rejected(self):
        with self.assertRaises(ProjectInputError):
            project_from_dict({
                "schema_version": 1, "name": "x", "shots": ["not a dict"],
            })

    def test_shot_missing_field_rejected(self):
        with self.assertRaises(ProjectInputError):
            project_from_dict({
                "schema_version": 1, "name": "x",
                "shots": [{"concept": "a"}],  # missing animation, etc.
            })

    def test_shot_unknown_field_rejected(self):
        with self.assertRaises(ProjectInputError):
            project_from_dict({
                "schema_version": 1, "name": "x",
                "shots": [{
                    "concept": "a", "animation": None, "animation_start_frame": 1,
                    "lip_sync": False, "lip_sync_start_frame": 1, "output_path": None,
                    "extra": True,
                }],
            })

    def test_malformed_json_rejected(self):
        with self.assertRaises(json.JSONDecodeError):
            project_from_json("{not valid json")
        with self.assertRaises(ProjectInputError):
            project_from_json("")
        with self.assertRaises(ProjectInputError):
            project_from_json(None)  # type: ignore[arg-type]


# --- E. File persistence ----------------------------------------------------

class FilePersistenceTests(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            path = tmpdir / "demo.json"
            project = _make_project()
            returned = save_project(project, path)
            self.assertTrue(returned.is_absolute())
            self.assertTrue(returned.exists())
            loaded = load_project(returned)
            self.assertEqual(loaded, project)

    def test_save_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            path = tmpdir / "a" / "b" / "c" / "demo.json"
            project = _make_project()
            returned = save_project(project, path)
            self.assertTrue(returned.exists())
            loaded = load_project(returned)
            self.assertEqual(loaded, project)

    def test_save_accepts_pathlike(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            path = tmpdir / "demo.json"
            save_project(_make_project(), path)
            self.assertTrue(path.exists())

    def test_save_invalid_path_rejected(self):
        for bad in (None, "", "   ", 1, [], {}):
            with self.assertRaises(ProjectInputError) as ctx:
                save_project(_make_project(), bad)  # type: ignore[arg-type]
            self.assertEqual(ctx.exception.parameter, "path")

    def test_save_invalid_project_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.json"
            with self.assertRaises(ProjectInputError):
                save_project({"name": "x", "shots": []}, path)  # type: ignore[arg-type]

    def test_load_invalid_path_rejected(self):
        for bad in (None, "", "   ", 1, [], {}):
            with self.assertRaises(ProjectInputError):
                load_project(bad)  # type: ignore[arg-type]

    def test_load_directory_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ProjectInputError):
                load_project(d)

    def test_repeated_save_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "demo.json"
            project = _make_project()
            save_project(project, path)
            first = path.read_text(encoding="utf-8")
            save_project(project, path)
            second = path.read_text(encoding="utf-8")
            self.assertEqual(first, second)

    def test_repeated_load_equivalent(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "demo.json"
            project = _make_project()
            save_project(project, path)
            a = load_project(path)
            b = load_project(path)
            self.assertEqual(a, b)

    def test_load_malformed_json_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_project(path)


# --- F. Replay --------------------------------------------------------------

class ReplayTests(unittest.TestCase):
    def setUp(self):
        _fake_per_shot_workflow.calls = []

    def test_replay_forwards_shots_in_order(self):
        project = _make_project()
        replay_project(project, workflow_callable=_fake_per_shot_workflow)
        # Two shots -> two per-shot workflow calls, in order.
        self.assertEqual(len(_fake_per_shot_workflow.calls), 2)
        self.assertEqual(
            _fake_per_shot_workflow.calls[0]["concept"],
            "A husband waves in a living room",
        )
        self.assertEqual(
            _fake_per_shot_workflow.calls[1]["concept"],
            "A wife smiles in the same room",
        )

    def test_replay_propagates_delegated_errors_unchanged(self):
        class CustomFailure(Exception):
            pass

        def failing_workflow(**_kwargs):
            raise CustomFailure("boom")

        project = _make_project()
        with self.assertRaises(CustomFailure) as ctx:
            replay_project(project, workflow_callable=failing_workflow)
        self.assertEqual(str(ctx.exception), "boom")

    def test_replay_does_not_mutate_project(self):
        project = _make_project()
        original_shots = project.shots
        replay_project(project, workflow_callable=_fake_per_shot_workflow)
        self.assertIs(project.shots, original_shots)
        self.assertEqual(project.name, "demo_project")
        self.assertEqual(len(project.shots), 2)

    def test_replay_repeated_equivalent_delegation(self):
        project = _make_project()
        replay_project(project, workflow_callable=_fake_per_shot_workflow)
        replay_project(project, workflow_callable=_fake_per_shot_workflow)
        # Two calls, each forwarding both shots in the same order.
        self.assertEqual(len(_fake_per_shot_workflow.calls), 4)
        self.assertEqual(
            _fake_per_shot_workflow.calls[0]["concept"],
            _fake_per_shot_workflow.calls[2]["concept"],
        )
        self.assertEqual(
            _fake_per_shot_workflow.calls[1]["concept"],
            _fake_per_shot_workflow.calls[3]["concept"],
        )

    def test_replay_default_delegates_to_multi_shot(self):
        # The replay helper must route through create_and_render_shots.
        self.assertIn("create_and_render_shots", PROJECT_SOURCE)

    def test_replay_rejects_non_project(self):
        with self.assertRaises(ProjectInputError):
            replay_project({"name": "x", "shots": []})  # type: ignore[arg-type]


@dataclasses.dataclass(frozen=True)
class _FakeResult:  # noqa: F811 -- re-declared to keep tests self-contained
    output_path: str = ""


# --- G. Architecture / dependency boundary tests ---------------------------

def _ast_imports_top_level(source):
    tree = ast.parse(source)
    out = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, 0))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append((node.module, getattr(node, "level", 0)))
    return out


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


class ProjectArchitectureTests(unittest.TestCase):
    def test_project_module_is_bpy_free(self):
        for source in (PROJECT_SOURCE, WORKFLOW_INIT_SOURCE):
            for name in _ast_all_imports(source):
                self.assertFalse(
                    name == "bpy" or name.startswith("bpy."),
                    f"forbidden bpy import: {name}",
                )

    def test_no_bpy_data_or_bpy_ops(self):
        tree = ast.parse(PROJECT_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in {"data", "ops"}:
                    root = node
                    while isinstance(root, ast.Attribute):
                        root = root.value
                    if isinstance(root, ast.Name) and root.id == "bpy":
                        self.fail(f"forbidden bpy.{node.attr} reference")

    def test_no_keyframe_insert_or_from_pydata(self):
        self.assertNotIn("keyframe_insert", PROJECT_SOURCE)
        self.assertNotIn("from_pydata", PROJECT_SOURCE)

    def test_no_ai_ollama_http_urllib_audio(self):
        forbidden = {
            "ai", "ollama", "ollama_client", "urllib", "urllib.request",
            "requests", "http", "wave", "soundfile", "librosa",
            "speech_recognition", "audio",
        }
        for name in _ast_all_imports(PROJECT_SOURCE):
            self.assertNotIn(
                name.split(".")[0],
                forbidden,
                f"forbidden import in project.py: {name}",
            )

    def test_does_not_import_toonflow_ai_generation(self):
        for name in _ast_all_imports(PROJECT_SOURCE):
            self.assertFalse(
                name.startswith("toonflow_ai"),
                f"forbidden import: {name}",
            )

    def test_does_not_import_pipeline_asset_registry_or_scene_plan(self):
        forbidden = {"pipeline", "asset_registry", "scene_plan"}
        for name in _ast_all_imports(PROJECT_SOURCE):
            self.assertNotIn(
                name.split(".")[0],
                forbidden,
                f"forbidden import: {name}",
            )

    def test_no_print_input_open(self):
        for source in (PROJECT_SOURCE, WORKFLOW_INIT_SOURCE):
            self.assertNotIn("print(", source)
            self.assertNotIn("input(", source)
            open_calls = re.findall(r"\bopen\(", source)
            self.assertLessEqual(len(open_calls), 2, f"too many open() in {source!r}")

    def test_replay_delegates_through_multi_shot(self):
        self.assertIn("from .shots import create_and_render_shots", PROJECT_SOURCE)
        self.assertIn("create_and_render_shots(", PROJECT_SOURCE)

    def test_top_level_imports_minimal(self):
        for name, level in _ast_imports_top_level(PROJECT_SOURCE):
            if level > 0:
                # Relative import (e.g. from .project_migrations import ...).
                continue
            self.assertIn(
                name,
                {"json", "os", "dataclasses", "pathlib", "typing"},
                f"unexpected top-level import in project.py: {name}",
            )

    def test_project_module_exports_all_required_symbols(self):
        for name in (
            "Project", "ProjectInputError", "PROJECT_SCHEMA_VERSION",
            "project_to_dict", "project_from_dict",
            "project_to_json", "project_from_json",
            "save_project", "load_project", "replay_project",
        ):
            self.assertTrue(hasattr(project_mod, name), name)


if __name__ == "__main__":
    unittest.main()