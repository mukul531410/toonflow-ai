"""Tests for TOONFLOW-PHASE-016 — Multi-Shot Workflow Foundation."""
import ast
import dataclasses
import sys
import unittest
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_ROOT = PROJECT_ROOT / "addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


from workflow import (  # noqa: E402
    MultiShotInputError,
    MultiShotResult,
    Shot,
    create_and_render_shots,
)
import workflow.shots as shots_mod  # noqa: E402


SHOTS_SOURCE = (PROJECT_ROOT / "workflow" / "shots.py").read_text(
    encoding="utf-8"
)
WORKFLOW_INIT_SOURCE = (PROJECT_ROOT / "workflow" / "__init__.py").read_text(
    encoding="utf-8"
)


# --- Helpers ----------------------------------------------------------------

def _make_workflow_callable(per_shot_outputs=None, raise_on=None):
    """Return a fake workflow_callable that records calls and returns per-shot results.

    Args:
        per_shot_outputs: dict mapping call index (int) to the
            ``output_path`` value the fake should put on its result.
        raise_on: index (int) of the call after which the fake should
            raise. ``None`` means never raise.
    """
    per_shot_outputs = per_shot_outputs or {}
    raise_on = raise_on if raise_on is not None else -1
    state = {"calls": []}

    def _callable(
        *,
        concept,
        animation,
        animation_start_frame,
        lip_sync,
        lip_sync_start_frame,
        output_path,
    ):
        index = len(state["calls"])
        state["calls"].append(
            {
                "concept": concept,
                "animation": animation,
                "animation_start_frame": animation_start_frame,
                "lip_sync": lip_sync,
                "lip_sync_start_frame": lip_sync_start_frame,
                "output_path": output_path,
            }
        )
        if index == raise_on:
            raise RuntimeError(f"simulated failure at shot {index}")
        out = per_shot_outputs.get(index, f"/resolved/shot_{index}.png")
        return _FakeWorkflowResult(output_path=out)

    state["callable"] = _callable
    return _callable, state


@dataclasses.dataclass(frozen=True)
class _FakeWorkflowResult:
    output_path: str = ""


# --- A. Public API exposure ------------------------------------------------

class PublicApiTests(unittest.TestCase):
    def test_create_and_render_shots_exported(self):
        self.assertTrue(callable(create_and_render_shots))

    def test_shot_exported(self):
        self.assertTrue(callable(Shot))

    def test_multi_shot_result_exported(self):
        self.assertTrue(callable(MultiShotResult))

    def test_multi_shot_input_error_exported(self):
        self.assertTrue(callable(MultiShotInputError))

    def test_shot_is_immutable(self):
        shot = Shot(concept="A family in their living room")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            shot.concept = "other"  # type: ignore[misc]

    def test_multi_shot_result_is_immutable(self):
        result = MultiShotResult(shot_results=(), output_paths=(), shot_count=0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.shot_count = 1  # type: ignore[misc]

    def test_shot_defaults(self):
        shot = Shot(concept="x")
        self.assertEqual(shot.concept, "x")
        self.assertIsNone(shot.animation)
        self.assertEqual(shot.animation_start_frame, 1)
        self.assertFalse(shot.lip_sync)
        self.assertEqual(shot.lip_sync_start_frame, 1)
        self.assertIsNone(shot.output_path)


# --- B. Execution order ----------------------------------------------------

class ExecutionOrderTests(unittest.TestCase):
    def test_shots_execute_in_input_order(self):
        shots = (
            Shot(concept="shot 1 concept", output_path="shot_01.png"),
            Shot(concept="shot 2 concept", output_path="shot_02.png"),
            Shot(concept="shot 3 concept", output_path="shot_03.png"),
        )
        callable_, state = _make_workflow_callable(
            per_shot_outputs={
                0: "/r/shot_01.png",
                1: "/r/shot_02.png",
                2: "/r/shot_03.png",
            }
        )
        result = create_and_render_shots(shots, workflow_callable=callable_)

        self.assertEqual([c["concept"] for c in state["calls"]],
                         ["shot 1 concept", "shot 2 concept", "shot 3 concept"])
        self.assertEqual([c["output_path"] for c in state["calls"]],
                         ["shot_01.png", "shot_02.png", "shot_03.png"])
        self.assertEqual(result.output_paths,
                         ("/r/shot_01.png", "/r/shot_02.png", "/r/shot_03.png"))
        self.assertEqual(result.shot_count, 3)
        self.assertEqual(len(result.shot_results), 3)


# --- C. Delegation ---------------------------------------------------------

class DelegationTests(unittest.TestCase):
    def test_all_shot_fields_forwarded(self):
        shot = Shot(
            concept="A husband waves in a living room",
            animation="wave",
            animation_start_frame=10,
            lip_sync=True,
            lip_sync_start_frame=20,
            output_path="shot.png",
        )
        callable_, state = _make_workflow_callable(
            per_shot_outputs={0: "/r/shot.png"}
        )
        create_and_render_shots((shot,), workflow_callable=callable_)
        self.assertEqual(len(state["calls"]), 1)
        call = state["calls"][0]
        self.assertEqual(call["concept"], "A husband waves in a living room")
        self.assertEqual(call["animation"], "wave")
        self.assertEqual(call["animation_start_frame"], 10)
        self.assertTrue(call["lip_sync"])
        self.assertEqual(call["lip_sync_start_frame"], 20)
        self.assertEqual(call["output_path"], "shot.png")

    def test_default_shot_values_forwarded(self):
        shot = Shot(concept="minimal")
        callable_, state = _make_workflow_callable()
        create_and_render_shots((shot,), workflow_callable=callable_)
        call = state["calls"][0]
        self.assertIsNone(call["animation"])
        self.assertEqual(call["animation_start_frame"], 1)
        self.assertFalse(call["lip_sync"])
        self.assertEqual(call["lip_sync_start_frame"], 1)
        self.assertIsNone(call["output_path"])

    def test_output_path_passed_through_unchanged(self):
        shots = (
            Shot(concept="a", output_path="/tmp/a.png"),
            Shot(concept="b", output_path=None),
            Shot(concept="c", output_path="/tmp/c.png"),
        )
        callable_, state = _make_workflow_callable(
            per_shot_outputs={
                0: "/r/a.png", 1: "/r/b.png", 2: "/r/c.png",
            }
        )
        create_and_render_shots(shots, workflow_callable=callable_)
        self.assertEqual(
            [c["output_path"] for c in state["calls"]],
            ["/tmp/a.png", None, "/tmp/c.png"],
        )
        # The multi-shot layer must NOT modify the output paths.
        self.assertEqual(
            result_shot_output_paths := [c["output_path"] for c in state["calls"]],
            ["/tmp/a.png", None, "/tmp/c.png"],
        )

    def test_duck_typed_shot_is_supported(self):
        @dataclasses.dataclass(frozen=True)
        class CustomShot:
            concept: str
            animation: Optional[str] = None
            animation_start_frame: int = 1
            lip_sync: bool = False
            lip_sync_start_frame: int = 1
            output_path: Optional[str] = None

        shot = CustomShot(concept="duck typed", animation="wave")
        callable_, state = _make_workflow_callable()
        create_and_render_shots((shot,), workflow_callable=callable_)
        self.assertEqual(state["calls"][0]["concept"], "duck typed")
        self.assertEqual(state["calls"][0]["animation"], "wave")


# --- D. Error propagation --------------------------------------------------

class ErrorPropagationTests(unittest.TestCase):
    def test_delegated_error_propagates_unchanged(self):
        class CustomFailure(Exception):
            pass

        def failing_callable(**kwargs):
            raise CustomFailure("boom")

        shots = (Shot(concept="a"), Shot(concept="b"))
        with self.assertRaises(CustomFailure) as ctx:
            create_and_render_shots(shots, workflow_callable=failing_callable)
        self.assertEqual(str(ctx.exception), "boom")

    def test_execution_stops_after_failing_shot(self):
        shots = (
            Shot(concept="ok 1"),
            Shot(concept="ok 2"),
            Shot(concept="fails"),
            Shot(concept="never executed"),
        )
        callable_, state = _make_workflow_callable(raise_on=2)
        with self.assertRaises(RuntimeError):
            create_and_render_shots(shots, workflow_callable=callable_)
        # Only the first three shots were attempted.
        self.assertEqual(len(state["calls"]), 3)
        self.assertEqual(
            [c["concept"] for c in state["calls"]],
            ["ok 1", "ok 2", "fails"],
        )

    def test_later_shots_not_executed(self):
        shots = (
            Shot(concept="ok"),
            Shot(concept="fails"),
            Shot(concept="never"),
            Shot(concept="never 2"),
        )
        callable_, state = _make_workflow_callable(raise_on=1)
        with self.assertRaises(RuntimeError):
            create_and_render_shots(shots, workflow_callable=callable_)
        self.assertEqual(len(state["calls"]), 2)

    def test_first_shot_failure_short_circuits(self):
        def failing(**kwargs):
            raise ValueError("first shot failed")

        with self.assertRaises(ValueError):
            create_and_render_shots(
                (Shot(concept="fails"), Shot(concept="never")),
                workflow_callable=failing,
            )


# --- E. Input validation ---------------------------------------------------

class InputValidationTests(unittest.TestCase):
    def test_non_sequence_input_rejected(self):
        for bad in (None, 42, "not a sequence", 3.14, {"a": 1}):
            with self.assertRaises(MultiShotInputError) as ctx:
                create_and_render_shots(bad)
            self.assertEqual(ctx.exception.parameter, "shots")

    def test_empty_sequence_rejected(self):
        for bad in ([], tuple()):
            with self.assertRaises(MultiShotInputError) as ctx:
                create_and_render_shots(bad)
            self.assertEqual(ctx.exception.parameter, "shots")

    def test_non_callable_workflow_rejected(self):
        for bad in (None, 42, "callable", object()):
            with self.assertRaises(MultiShotInputError) as ctx:
                create_and_render_shots(
                    (Shot(concept="a"),), workflow_callable=bad
                )
            self.assertEqual(ctx.exception.parameter, "workflow_callable")

    def test_invalid_shot_value_rejected(self):
        for bad in (42, "string", object()):
            with self.assertRaises(MultiShotInputError) as ctx:
                create_and_render_shots((Shot(concept="a"), bad))
            self.assertEqual(ctx.exception.parameter, "shots[1]")

    def test_validation_runs_before_any_delegation(self):
        def would_call(**kwargs):
            would_call.called = True
            return _FakeWorkflowResult()
        would_call.called = False
        with self.assertRaises(MultiShotInputError):
            create_and_render_shots(
                (),
                workflow_callable=would_call,
            )
        self.assertFalse(would_call.called)

    def test_multi_shot_input_error_is_value_error(self):
        self.assertTrue(issubclass(MultiShotInputError, ValueError))


# --- F. Result model -------------------------------------------------------

class ResultTests(unittest.TestCase):
    def test_result_preserves_order(self):
        shots = tuple(Shot(concept=f"shot {i}") for i in range(5))
        callable_, _ = _make_workflow_callable(
            per_shot_outputs={i: f"/r/{i}.png" for i in range(5)}
        )
        result = create_and_render_shots(shots, workflow_callable=callable_)
        self.assertEqual(result.shot_count, 5)
        self.assertEqual(len(result.shot_results), 5)
        self.assertEqual(len(result.output_paths), 5)

    def test_output_paths_preserve_order(self):
        shots = tuple(Shot(concept=f"c{i}") for i in range(4))
        callable_, _ = _make_workflow_callable(
            per_shot_outputs={i: f"/resolved/shot_{i}.png" for i in range(4)}
        )
        result = create_and_render_shots(shots, workflow_callable=callable_)
        self.assertEqual(
            result.output_paths,
            tuple(f"/resolved/shot_{i}.png" for i in range(4)),
        )


# --- G. Idempotency / determinism ------------------------------------------

class IdempotencyTests(unittest.TestCase):
    def test_repeated_calls_produce_equivalent_delegation(self):
        shots = (
            Shot(concept="a", animation="wave", output_path="a.png"),
            Shot(concept="b", lip_sync=True, output_path="b.png"),
        )
        callable1, state1 = _make_workflow_callable(
            per_shot_outputs={0: "/r/a.png", 1: "/r/b.png"}
        )
        callable2, state2 = _make_workflow_callable(
            per_shot_outputs={0: "/r/a.png", 1: "/r/b.png"}
        )
        first = create_and_render_shots(shots, workflow_callable=callable1)
        second = create_and_render_shots(shots, workflow_callable=callable2)
        # Same concepts/animations/output_paths forwarded, in the same order.
        self.assertEqual(
            [c["concept"] for c in state1["calls"]],
            [c["concept"] for c in state2["calls"]],
        )
        self.assertEqual(
            [c["output_path"] for c in state1["calls"]],
            [c["output_path"] for c in state2["calls"]],
        )
        self.assertEqual(first.output_paths, second.output_paths)
        self.assertEqual(first.shot_count, second.shot_count)

    def test_shot_objects_not_mutated(self):
        original = Shot(concept="x", animation="wave", output_path="x.png")
        shots = (original,)
        callable_, _ = _make_workflow_callable(per_shot_outputs={0: "/r/x.png"})
        create_and_render_shots(shots, workflow_callable=callable_)
        # The original Shot instance is untouched.
        self.assertEqual(original.concept, "x")
        self.assertEqual(original.animation, "wave")
        self.assertEqual(original.output_path, "x.png")


# --- H. Architecture / dependency boundary tests ---------------------------

def _ast_imports_top_level(source):
    tree = ast.parse(source)
    out = []
    for node in tree.body:  # top-level only
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(node.module)
    return out


class MultiShotArchitectureTests(unittest.TestCase):
    def test_shots_module_is_bpy_free(self):
        for source in (SHOTS_SOURCE, WORKFLOW_INIT_SOURCE):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name == "bpy" or alias.name.startswith("bpy."),
                            f"forbidden bpy import: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertFalse(
                        (node.module or "").startswith("bpy"),
                        f"forbidden from bpy import: {node.module}",
                    )

    def test_shots_module_has_no_bpy_data_or_bpy_ops(self):
        tree = ast.parse(SHOTS_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in {"data", "ops"}:
                    root = node
                    while isinstance(root, ast.Attribute):
                        root = root.value
                    if isinstance(root, ast.Name) and root.id == "bpy":
                        self.fail(f"forbidden bpy.{node.attr} reference")

    def test_no_keyframe_insert_or_from_pydata(self):
        self.assertNotIn("keyframe_insert", SHOTS_SOURCE)
        self.assertNotIn("from_pydata", SHOTS_SOURCE)

    def test_no_ai_ollama_http_urllib_audio(self):
        forbidden_top_level = {
            "ai", "ollama", "ollama_client", "urllib", "urllib.request",
            "requests", "http", "wave", "soundfile", "librosa",
            "speech_recognition", "audio",
        }
        for source in (SHOTS_SOURCE, WORKFLOW_INIT_SOURCE):
            for name in _ast_imports_top_level(source):
                self.assertNotIn(
                    name.split(".")[0],
                    forbidden_top_level,
                    f"forbidden top-level import: {name}",
                )

    def test_does_not_import_pipeline_asset_registry_or_scene_plan(self):
        forbidden = {"pipeline", "asset_registry", "scene_plan"}
        for source in (SHOTS_SOURCE, WORKFLOW_INIT_SOURCE):
            for name in _ast_imports_top_level(source):
                self.assertNotIn(
                    name.split(".")[0],
                    forbidden,
                    f"forbidden top-level import: {name}",
                )

    def test_does_not_import_toonflow_ai_generation(self):
        # The multi-shot layer must delegate only through workflow.api.
        for name in _ast_imports_top_level(SHOTS_SOURCE):
            self.assertFalse(
                name.startswith("toonflow_ai"),
                f"forbidden import: {name}",
            )

    def test_delegates_through_workflow_api_only(self):
        # The only top-level non-typing import must be the local
        # workflow package (for Shot-like duck-typing) and stdlib.
        for name in _ast_imports_top_level(SHOTS_SOURCE):
            if name.startswith("."):
                # Relative import to local workflow package — allowed.
                continue
            if name in {"dataclasses", "typing"}:
                continue
            self.assertTrue(
                name == "workflow" or name.startswith("workflow."),
                f"unexpected top-level import in shots.py: {name}",
            )

    def test_no_print_or_io_side_effects(self):
        for source in (SHOTS_SOURCE, WORKFLOW_INIT_SOURCE):
            self.assertNotIn("print(", source)
            self.assertNotIn("input(", source)
            self.assertNotIn("open(", source)

    def test_default_workflow_callable_delegates_to_workflow_api(self):
        # Inspect the source to ensure the default callable routes
        # through the existing single-shot workflow.
        self.assertIn("from .api import create_and_render_scene", SHOTS_SOURCE)
        self.assertIn("create_and_render_scene(", SHOTS_SOURCE)

    def test_shots_module_uses_only_public_api_names(self):
        # The public API names that must be exported.
        for name in (
            "Shot", "MultiShotResult", "MultiShotInputError",
            "create_and_render_shots",
        ):
            self.assertTrue(hasattr(shots_mod, name), name)


if __name__ == "__main__":
    unittest.main()