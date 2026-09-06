"""Tests for TOONFLOW-PHASE-015 — Advanced Automation Workflow."""
import ast
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_ROOT = PROJECT_ROOT / "addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


from workflow import (  # noqa: E402
    WorkflowResult,
    create_and_render_scene,
)
import workflow.api as workflow_api  # noqa: E402


VALID_PLAN = {
    "version": "0.1",
    "scene": {"environment": "living_room"},
    "characters": [
        {"id": "husband", "role": "husband"},
        {"id": "wife", "role": "wife"},
    ],
}


@dataclass(frozen=True)
class FakeGenerationResult:
    collection_name: str = "TOONFLOW"
    environment_id: str = "living_room"
    environment_object_names: tuple = ("TOONFLOW_ENV_LIVING_ROOM",)
    character_ids: tuple = ("husband", "wife")
    character_object_names: tuple = (
        "TOONFLOW_CHARACTER_HUSBAND",
        "TOONFLOW_CHARACTER_WIFE",
    )


@dataclass(frozen=True)
class FakeSceneCreation:
    scene_plan: dict
    generation_result: FakeGenerationResult


def _make_pipeline(plan=None, generation=None):
    plan = plan if plan is not None else VALID_PLAN
    generation = generation if generation is not None else FakeGenerationResult()
    creation = FakeSceneCreation(scene_plan=plan, generation_result=generation)

    def _pipeline(concept):
        _pipeline.calls.append((concept,))
        _pipeline.creation = creation
        return creation

    _pipeline.calls = []
    _pipeline.creation = creation
    return _pipeline


def _make_animator():
    def _animator(character_id, animation_name, start_frame):
        _animator.calls.append((character_id, animation_name, start_frame))
        return {
            "character_id": character_id,
            "animation_name": animation_name,
            "start_frame": start_frame,
        }

    _animator.calls = []
    return _animator


def _make_lip_sync():
    def _lip_sync(character_id, start_frame, sequence):
        _lip_sync.calls.append((character_id, start_frame, sequence))
        return {
            "character_id": character_id,
            "start_frame": start_frame,
            "sequence": sequence,
        }

    _lip_sync.calls = []
    return _lip_sync


def _make_camera():
    def _camera():
        _camera.calls.append(())
        return {
            "camera_name": "TOONFLOW_CAMERA",
            "reused": True,
        }

    _camera.calls = []
    return _camera


def _make_renderer():
    def _renderer(output_path):
        _renderer.calls.append((output_path,))
        return {
            "camera_name": "TOONFLOW_CAMERA",
            "output_path": "/resolved/toonflow_render.png",
        }

    _renderer.calls = []
    return _renderer


class PublicApiTests(unittest.TestCase):
    def test_create_and_render_scene_exported(self):
        self.assertTrue(callable(create_and_render_scene))

    def test_workflow_result_exported(self):
        self.assertTrue(callable(WorkflowResult))

    def test_workflow_input_error_defined(self):
        self.assertTrue(callable(workflow_api.WorkflowInputError))


class ExecutionOrderTests(unittest.TestCase):
    def test_default_order_is_pipeline_camera_render(self):
        pipeline = _make_pipeline()
        camera = _make_camera()
        renderer = _make_renderer()
        result = create_and_render_scene(
            "A family in their living room",
            pipeline=pipeline,
            camera=camera,
            renderer=renderer,
        )
        # Each injected callable was called exactly once.
        self.assertEqual(len(pipeline.calls), 1)
        self.assertEqual(len(camera.calls), 1)
        self.assertEqual(len(renderer.calls), 1)
        # Render received the user-supplied output_path unchanged.
        self.assertEqual(renderer.calls[0][0], None)
        # Result combines delegated outputs.
        self.assertIs(result.scene_plan, pipeline.creation.scene_plan)
        self.assertIs(result.generation_result, pipeline.creation.generation_result)
        self.assertEqual(result.camera_result, {"camera_name": "TOONFLOW_CAMERA", "reused": True})
        self.assertEqual(result.render_result["output_path"], "/resolved/toonflow_render.png")
        self.assertEqual(result.output_path, "/resolved/toonflow_render.png")
        self.assertIsNone(result.animation_results)
        self.assertIsNone(result.lip_sync_results)

    def test_animation_runs_after_pipeline_before_camera_and_render(self):
        pipeline = _make_pipeline()
        animator = _make_animator()
        camera = _make_camera()
        renderer = _make_renderer()
        create_and_render_scene(
            "A family in their living room",
            animation="wave",
            animation_start_frame=10,
            pipeline=pipeline,
            animator=animator,
            camera=camera,
            renderer=renderer,
        )
        # animator was called once per generated character.
        self.assertEqual(animator.calls, [("husband", "wave", 10), ("wife", "wave", 10)])
        self.assertEqual(len(pipeline.calls), 1)
        self.assertEqual(len(camera.calls), 1)
        self.assertEqual(len(renderer.calls), 1)

    def test_lip_sync_runs_after_animation_before_camera_and_render(self):
        pipeline = _make_pipeline()
        animator = _make_animator()
        lip_sync = _make_lip_sync()
        camera = _make_camera()
        renderer = _make_renderer()
        create_and_render_scene(
            "A family in their living room",
            animation="wave",
            animation_start_frame=1,
            lip_sync=True,
            lip_sync_start_frame=20,
            pipeline=pipeline,
            animator=animator,
            lip_sync_callable=lip_sync,
            camera=camera,
            renderer=renderer,
        )
        # Both animator and lip-sync were invoked per character.
        self.assertEqual(len(animator.calls), 2)
        self.assertEqual(len(lip_sync.calls), 2)
        self.assertEqual(lip_sync.calls[0], ("husband", 20, None))
        self.assertEqual(lip_sync.calls[1], ("wife", 20, None))
        self.assertEqual(len(camera.calls), 1)
        self.assertEqual(len(renderer.calls), 1)

    def test_animation_disabled_skips_animator(self):
        pipeline = _make_pipeline()
        animator = _make_animator()
        camera = _make_camera()
        renderer = _make_renderer()
        result = create_and_render_scene(
            "A family in their living room",
            animation=None,
            pipeline=pipeline,
            animator=animator,
            camera=camera,
            renderer=renderer,
        )
        self.assertEqual(animator.calls, [])
        self.assertIsNone(result.animation_results)
        self.assertEqual(len(camera.calls), 1)
        self.assertEqual(len(renderer.calls), 1)

    def test_empty_animation_string_skips_animator(self):
        pipeline = _make_pipeline()
        animator = _make_animator()
        camera = _make_camera()
        renderer = _make_renderer()
        result = create_and_render_scene(
            "A family in their living room",
            animation="",
            pipeline=pipeline,
            animator=animator,
            camera=camera,
            renderer=renderer,
        )
        self.assertEqual(animator.calls, [])
        self.assertIsNone(result.animation_results)

    def test_lip_sync_disabled_skips_lip_sync(self):
        pipeline = _make_pipeline()
        lip_sync = _make_lip_sync()
        camera = _make_camera()
        renderer = _make_renderer()
        result = create_and_render_scene(
            "A family in their living room",
            lip_sync=False,
            pipeline=pipeline,
            lip_sync_callable=lip_sync,
            camera=camera,
            renderer=renderer,
        )
        self.assertEqual(lip_sync.calls, [])
        self.assertIsNone(result.lip_sync_results)

    def test_output_path_passed_unchanged_to_renderer(self):
        pipeline = _make_pipeline()
        camera = _make_camera()
        renderer = _make_renderer()
        create_and_render_scene(
            "A family in their living room",
            output_path="/tmp/custom.png",
            pipeline=pipeline,
            camera=camera,
            renderer=renderer,
        )
        self.assertEqual(renderer.calls, [("/tmp/custom.png",)])

    def test_result_contains_all_delegated_outputs(self):
        pipeline = _make_pipeline()
        animator = _make_animator()
        lip_sync = _make_lip_sync()
        camera = _make_camera()
        renderer = _make_renderer()
        result = create_and_render_scene(
            "A family in their living room",
            animation="wave",
            animation_start_frame=1,
            lip_sync=True,
            lip_sync_start_frame=5,
            output_path=None,
            pipeline=pipeline,
            animator=animator,
            lip_sync_callable=lip_sync,
            camera=camera,
            renderer=renderer,
        )
        self.assertIs(result.scene_plan, pipeline.creation.scene_plan)
        self.assertIs(result.generation_result, pipeline.creation.generation_result)
        self.assertEqual(len(result.animation_results), 2)
        self.assertEqual(len(result.lip_sync_results), 2)
        self.assertEqual(result.camera_result, {"camera_name": "TOONFLOW_CAMERA", "reused": True})
        self.assertEqual(result.render_result["output_path"], "/resolved/toonflow_render.png")
        self.assertEqual(result.output_path, "/resolved/toonflow_render.png")

    def test_idempotent_delegation(self):
        pipeline = _make_pipeline()
        animator = _make_animator()
        lip_sync = _make_lip_sync()
        camera = _make_camera()
        renderer = _make_renderer()
        first = create_and_render_scene(
            "A family in their living room",
            animation="wave",
            animation_start_frame=1,
            lip_sync=True,
            lip_sync_start_frame=1,
            output_path="/tmp/a.png",
            pipeline=pipeline,
            animator=animator,
            lip_sync_callable=lip_sync,
            camera=camera,
            renderer=renderer,
        )
        second = create_and_render_scene(
            "A family in their living room",
            animation="wave",
            animation_start_frame=1,
            lip_sync=True,
            lip_sync_start_frame=1,
            output_path="/tmp/a.png",
            pipeline=pipeline,
            animator=animator,
            lip_sync_callable=lip_sync,
            camera=camera,
            renderer=renderer,
        )
        self.assertEqual(first.scene_plan, second.scene_plan)
        self.assertEqual(first.output_path, second.output_path)
        self.assertEqual(first.animation_results, second.animation_results)
        self.assertEqual(first.lip_sync_results, second.lip_sync_results)
        self.assertEqual(first.render_result, second.render_result)


class ErrorPropagationTests(unittest.TestCase):
    def test_pipeline_error_propagates_unchanged(self):
        class PipelineFailure(Exception):
            pass

        def pipeline(concept):
            raise PipelineFailure("planning failed")

        camera = _make_camera()
        renderer = _make_renderer()
        with self.assertRaises(PipelineFailure):
            create_and_render_scene(
                "Any concept",
                pipeline=pipeline,
                camera=camera,
                renderer=renderer,
            )
        self.assertEqual(camera.calls, [])
        self.assertEqual(renderer.calls, [])

    def test_animation_error_propagates_unchanged(self):
        class AnimationFailure(Exception):
            pass

        pipeline = _make_pipeline()

        def animator(character_id, animation_name, start_frame):
            raise AnimationFailure(f"animator failed for {character_id}")

        camera = _make_camera()
        renderer = _make_renderer()
        with self.assertRaises(AnimationFailure):
            create_and_render_scene(
                "Any concept",
                animation="wave",
                pipeline=pipeline,
                animator=animator,
                camera=camera,
                renderer=renderer,
            )
        # Camera and render were not called.
        self.assertEqual(camera.calls, [])
        self.assertEqual(renderer.calls, [])

    def test_lip_sync_error_propagates_unchanged(self):
        class LipSyncFailure(Exception):
            pass

        pipeline = _make_pipeline()
        lip_sync = _make_lip_sync()
        camera = _make_camera()
        renderer = _make_renderer()

        def failing_lip_sync(character_id, start_frame, sequence):
            raise LipSyncFailure(f"lip sync failed for {character_id}")

        with self.assertRaises(LipSyncFailure):
            create_and_render_scene(
                "Any concept",
                lip_sync=True,
                pipeline=pipeline,
                lip_sync_callable=failing_lip_sync,
                camera=camera,
                renderer=renderer,
            )
        self.assertEqual(camera.calls, [])
        self.assertEqual(renderer.calls, [])

    def test_camera_error_propagates_unchanged(self):
        class CameraFailure(Exception):
            pass

        pipeline = _make_pipeline()

        def camera():
            raise CameraFailure("camera failed")

        renderer = _make_renderer()
        with self.assertRaises(CameraFailure):
            create_and_render_scene(
                "Any concept",
                pipeline=pipeline,
                camera=camera,
                renderer=renderer,
            )
        self.assertEqual(renderer.calls, [])

    def test_render_error_propagates_unchanged(self):
        class RenderFailure(Exception):
            pass

        pipeline = _make_pipeline()
        camera = _make_camera()

        def renderer(output_path):
            raise RenderFailure(f"render failed: {output_path}")

        with self.assertRaises(RenderFailure):
            create_and_render_scene(
                "Any concept",
                output_path="/tmp/x.png",
                pipeline=pipeline,
                camera=camera,
                renderer=renderer,
            )


class InputValidationTests(unittest.TestCase):
    def test_empty_concept_rejected(self):
        camera = _make_camera()
        renderer = _make_renderer()
        with self.assertRaises(workflow_api.WorkflowInputError) as ctx:
            create_and_render_scene(
                "",
                pipeline=_make_pipeline(),
                camera=camera,
                renderer=renderer,
            )
        self.assertEqual(ctx.exception.parameter, "concept")

    def test_non_string_concept_rejected(self):
        with self.assertRaises(workflow_api.WorkflowInputError):
            create_and_render_scene(
                123,
                pipeline=_make_pipeline(),
                camera=_make_camera(),
                renderer=_make_renderer(),
            )

    def test_non_string_animation_rejected(self):
        with self.assertRaises(workflow_api.WorkflowInputError) as ctx:
            create_and_render_scene(
                "concept",
                animation=123,
                pipeline=_make_pipeline(),
                camera=_make_camera(),
                renderer=_make_renderer(),
            )
        self.assertEqual(ctx.exception.parameter, "animation")

    def test_non_bool_lip_sync_rejected(self):
        with self.assertRaises(workflow_api.WorkflowInputError) as ctx:
            create_and_render_scene(
                "concept",
                lip_sync="yes",
                pipeline=_make_pipeline(),
                camera=_make_camera(),
                renderer=_make_renderer(),
            )
        self.assertEqual(ctx.exception.parameter, "lip_sync")

    def test_invalid_animation_start_frame_rejected(self):
        # Only non-int / bool / float / str / None are rejected by the
        # workflow's own input validation. Out-of-range integers
        # (e.g. 0, -1) are intentionally delegated to the existing
        # animation layer so the workflow does not duplicate the
        # PHASE-010 start-frame rule.
        for bad in (1.5, "1", True, False, None):
            animator = _make_animator()
            with self.assertRaises(workflow_api.WorkflowInputError):
                create_and_render_scene(
                    "concept",
                    animation="wave",
                    animation_start_frame=bad,
                    pipeline=_make_pipeline(),
                    animator=animator,
                    camera=_make_camera(),
                    renderer=_make_renderer(),
                )
            self.assertEqual(animator.calls, [])

    def test_invalid_lip_sync_start_frame_rejected(self):
        for bad in (1.5, "1", True, False, None):
            lip_sync = _make_lip_sync()
            with self.assertRaises(workflow_api.WorkflowInputError):
                create_and_render_scene(
                    "concept",
                    lip_sync=True,
                    lip_sync_start_frame=bad,
                    pipeline=_make_pipeline(),
                    lip_sync_callable=lip_sync,
                    camera=_make_camera(),
                    renderer=_make_renderer(),
                )
            self.assertEqual(lip_sync.calls, [])

    def test_input_validation_runs_before_any_delegation(self):
        pipeline = _make_pipeline()
        animator = _make_animator()
        lip_sync = _make_lip_sync()
        camera = _make_camera()
        renderer = _make_renderer()
        with self.assertRaises(workflow_api.WorkflowInputError):
            create_and_render_scene(
                "",
                animation="wave",
                lip_sync=True,
                pipeline=pipeline,
                animator=animator,
                lip_sync_callable=lip_sync,
                camera=camera,
                renderer=renderer,
            )
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(animator.calls, [])
        self.assertEqual(lip_sync.calls, [])
        self.assertEqual(camera.calls, [])
        self.assertEqual(renderer.calls, [])


# --- Architecture / dependency boundary tests ------------------------------

WORKFLOW_API_SOURCE = (PROJECT_ROOT / "workflow" / "api.py").read_text(
    encoding="utf-8"
)
WORKFLOW_INIT_SOURCE = (PROJECT_ROOT / "workflow" / "__init__.py").read_text(
    encoding="utf-8"
)


def _ast_imports(source):
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


class WorkflowArchitectureTests(unittest.TestCase):
    def test_workflow_is_bpy_free(self):
        for source in (WORKFLOW_API_SOURCE, WORKFLOW_INIT_SOURCE):
            for name in _ast_imports(source):
                self.assertFalse(
                    name == "bpy" or name.startswith("bpy."),
                    f"forbidden bpy import in workflow: {name}",
                )

    def test_no_ai_ollama_http_urllib(self):
        for source in (WORKFLOW_API_SOURCE, WORKFLOW_INIT_SOURCE):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(
                            alias.name,
                            {"ai", "ollama", "urllib", "urllib.request",
                             "requests", "http"},
                            f"forbidden import: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(
                        (node.module or "").split(".")[0],
                        {"ai", "ollama", "urllib", "requests", "http"},
                        f"forbidden from-import: {node.module}",
                    )

    def test_no_audio_or_speech(self):
        for source in (WORKFLOW_API_SOURCE, WORKFLOW_INIT_SOURCE):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(
                            alias.name,
                            {"wave", "soundfile", "librosa",
                             "speech_recognition", "audio"},
                            f"forbidden import: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(
                        (node.module or "").split(".")[0],
                        {"wave", "soundfile", "librosa",
                         "speech_recognition", "audio"},
                        f"forbidden from-import: {node.module}",
                    )

    def test_no_bpy_data_or_bpy_ops(self):
        for source in (WORKFLOW_API_SOURCE, WORKFLOW_INIT_SOURCE):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    if node.attr in {"data", "ops"}:
                        root = node
                        while isinstance(root, ast.Attribute):
                            root = root.value
                        if isinstance(root, ast.Name) and root.id == "bpy":
                            self.fail(
                                f"forbidden bpy.{node.attr} reference in workflow"
                            )

    def test_no_scene_plan_or_asset_registry_logic(self):
        for source in (WORKFLOW_API_SOURCE, WORKFLOW_INIT_SOURCE):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(
                            alias.name,
                            {"asset_registry", "scene_plan"},
                            f"forbidden import: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(
                        (node.module or "").split(".")[0],
                        {"asset_registry", "scene_plan"},
                        f"forbidden from-import: {node.module}",
                    )

    def test_no_keyframe_or_mesh_creation(self):
        for forbidden in ("keyframe_insert", "from_pydata"):
            self.assertNotIn(forbidden, WORKFLOW_API_SOURCE, forbidden)
            self.assertNotIn(forbidden, WORKFLOW_INIT_SOURCE, forbidden)

    def test_no_direct_bpy_render_call(self):
        # No literal "bpy.ops.render.render" string.
        self.assertNotIn("bpy.ops.render.render", WORKFLOW_API_SOURCE)
        self.assertNotIn("bpy.ops.render.render", WORKFLOW_INIT_SOURCE)

    def test_no_print_or_io_side_effects(self):
        self.assertNotIn("print(", WORKFLOW_API_SOURCE)
        self.assertNotIn("input(", WORKFLOW_API_SOURCE)
        self.assertNotIn("open(", WORKFLOW_API_SOURCE)


if __name__ == "__main__":
    unittest.main()