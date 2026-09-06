"""Pure-Python tests for the TOONFLOW AI Concept-to-Scene Pipeline."""

import inspect
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_ROOT = PROJECT_ROOT / "addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from pipeline import SceneCreationResult, create_scene_from_concept  # noqa: E402
import pipeline.api as pipeline_api  # noqa: E402


VALID_PLAN = {
    "version": "0.1",
    "scene": {"environment": "living_room"},
    "characters": [{"id": "husband", "role": "husband"}],
}


class PlannerFailure(Exception):
    pass


class GenerationFailure(Exception):
    pass


class ConceptPipelineTests(unittest.TestCase):
    def test_valid_concept_invokes_planner_and_generation_in_order(self):
        calls = []
        generation_result = object()

        def planner(concept):
            calls.append(("planner", concept))
            return VALID_PLAN

        def generator(scene_plan):
            calls.append(("generator", scene_plan))
            return generation_result

        result = create_scene_from_concept(
            "A family in their living room",
            planner=planner,
            generator=generator,
        )

        self.assertEqual(
            calls,
            [
                ("planner", "A family in their living room"),
                ("generator", VALID_PLAN),
            ],
        )
        self.assertIsInstance(result, SceneCreationResult)
        self.assertIs(result.scene_plan, VALID_PLAN)
        self.assertIs(result.generation_result, generation_result)

    def test_existing_planner_instance_is_supported(self):
        class Planner:
            def __init__(self):
                self.received = None

            def plan_scene(self, concept):
                self.received = concept
                return VALID_PLAN

        planner = Planner()
        create_scene_from_concept("At home", planner=planner, generator=lambda plan: None)
        self.assertEqual(planner.received, "At home")

    def test_planner_error_propagates_unchanged(self):
        error = PlannerFailure("planning failed")

        def planner(concept):
            raise error

        with self.assertRaises(PlannerFailure) as context:
            create_scene_from_concept("At home", planner=planner, generator=lambda plan: None)
        self.assertIs(context.exception, error)

    def test_generation_error_propagates_unchanged(self):
        error = GenerationFailure("generation failed")

        def generator(scene_plan):
            raise error

        with self.assertRaises(GenerationFailure) as context:
            create_scene_from_concept(
                "At home", planner=lambda concept: VALID_PLAN, generator=generator
            )
        self.assertIs(context.exception, error)

    def test_orchestration_has_no_direct_execution_or_network_dependency(self):
        source = inspect.getsource(pipeline_api)
        for forbidden in ("bpy", "urllib", "http.client", "socket", "Request("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
