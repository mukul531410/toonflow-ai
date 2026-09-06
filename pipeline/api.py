"""Thin orchestration layer between TOONFLOW AI planning and generation."""

from dataclasses import dataclass
from typing import Any, Callable

from ai import plan_scene
from ai.ollama_client import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_TIMEOUT
from toonflow_ai.generation import generate_scene


@dataclass(frozen=True)
class SceneCreationResult:
    """The validated plan and generation result from one pipeline execution."""

    scene_plan: dict
    generation_result: Any


def create_scene_from_concept(
    concept: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    planner=None,
    generator: Callable[[dict], Any] | None = None,
) -> SceneCreationResult:
    """Plan and generate a scene from *concept*.

    By default this delegates to the public ``ai.plan_scene`` and
    ``toonflow_ai.generation.generate_scene`` APIs. ``planner`` and
    ``generator`` are optional injection points for alternative callers and
    pure-Python tests; they receive the concept and validated Scene Plan,
    respectively. Errors from either layer propagate unchanged.
    """
    if planner is None:
        scene_plan = plan_scene(
            concept,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )
    elif callable(planner):
        scene_plan = planner(concept)
    else:
        scene_plan = planner.plan_scene(concept)

    generation_function = generate_scene if generator is None else generator
    generation_result = generation_function(scene_plan)
    return SceneCreationResult(
        scene_plan=scene_plan,
        generation_result=generation_result,
    )
