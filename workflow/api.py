"""End-to-end orchestration for TOONFLOW AI.

This module is the only place in the :mod:`workflow` package that
contains executable code. It composes the existing TOONFLOW public
APIs in a fixed, deterministic order:

    1. Validate the high-level workflow inputs.
    2. Concept -> Scene pipeline (AI planning + scene generation).
    3. Optional character animation.
    4. Optional lip-sync animation.
    5. Camera update / create.
    6. Render.

The workflow contains no business logic of its own. It does not
import ``bpy``; it does not call AI directly; it does not perform
Scene Plan validation; it does not manipulate the Asset Registry; it
does not create or delete Blender objects; it does not insert
keyframes; it does not configure render settings. Every such side
effect is delegated to the dedicated TOONFLOW modules.

Errors from the delegated layers propagate unchanged. The workflow
only adds a single, small domain error for the top-level inputs.
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional


# --- Errors ----------------------------------------------------------------


class WorkflowInputError(ValueError):
    """The high-level workflow inputs are invalid.

    The workflow is the only layer that needs a *new* error class for
    its own arguments. All delegated layers raise their own existing
    errors (for example, ``InvalidConceptError``,
    ``UnknownAnimationError``, ``MissingCameraError``,
    ``RenderError``); those propagate unchanged.
    """

    def __init__(self, parameter, value):
        self.parameter = parameter
        self.value = value
        super().__init__(
            f"Workflow input {parameter!r} is invalid: got {value!r}."
        )


# --- Result -----------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowResult:
    """The combined outcome of one ``create_and_render_scene`` execution.

    Attributes:
        scene_plan: The validated Scene Plan returned by the concept
            pipeline.
        generation_result: The :class:`toonflow_ai.generation.GenerationResult`
            returned by the scene generation step.
        animation_results: Tuple of per-character animation results, or
            ``None`` when animation was not requested.
        lip_sync_results: Tuple of per-character lip-sync results, or
            ``None`` when lip sync was not requested.
        camera_result: The deterministic camera description returned
            by :func:`create_or_update_camera`.
        render_result: The deterministic render description returned
            by :func:`render_scene`.
        output_path: The resolved absolute output path used by the
            render step.
    """

    scene_plan: Any
    generation_result: Any
    animation_results: Optional[tuple]
    lip_sync_results: Optional[tuple]
    camera_result: Any
    render_result: Any
    output_path: str


# --- Default delegation targets --------------------------------------------


def _default_pipeline(concept):
    """Delegate to :func:`pipeline.create_scene_from_concept`."""
    from pipeline import create_scene_from_concept

    return create_scene_from_concept(concept)


def _default_animator(character_id, animation_name, start_frame):
    """Delegate to :func:`toonflow_ai.generation.animate_character`."""
    from toonflow_ai.generation import animate_character

    return animate_character(character_id, animation_name, start_frame)


def _default_lip_sync(character_id, start_frame, sequence):
    """Delegate to :func:`toonflow_ai.generation.animate_lip_sync`."""
    from toonflow_ai.generation import animate_lip_sync

    return animate_lip_sync(character_id, start_frame, sequence)


def _default_camera():
    """Delegate to :func:`toonflow_ai.generation.create_or_update_camera`."""
    from toonflow_ai.generation import create_or_update_camera

    return create_or_update_camera()


def _default_renderer(output_path):
    """Delegate to :func:`toonflow_ai.generation.render_scene`."""
    from toonflow_ai.generation import render_scene

    return render_scene(output_path)


# --- Workflow entry point --------------------------------------------------


def _validate_concept(concept):
    if not isinstance(concept, str) or not concept.strip():
        raise WorkflowInputError("concept", concept)


def _validate_animation_args(animation, animation_start_frame):
    if animation is not None and not isinstance(animation, str):
        raise WorkflowInputError("animation", animation)
    if (
        isinstance(animation_start_frame, bool)
        or not isinstance(animation_start_frame, int)
    ):
        raise WorkflowInputError("animation_start_frame", animation_start_frame)


def _validate_lip_sync_args(lip_sync, lip_sync_start_frame):
    if not isinstance(lip_sync, bool):
        raise WorkflowInputError("lip_sync", lip_sync)
    if (
        isinstance(lip_sync_start_frame, bool)
        or not isinstance(lip_sync_start_frame, int)
    ):
        raise WorkflowInputError("lip_sync_start_frame", lip_sync_start_frame)


def _apply_animation(
    character_ids,
    animation,
    animation_start_frame,
    animator: Callable,
):
    """Apply the optional animation to every generated character.

    Errors from the delegated animation layer propagate unchanged
    (``UnknownCharacterError``, ``UnknownAnimationError``,
    ``InvalidStartFrameError``, ``MissingCharacterError``,
    ``BlenderUnavailableError``).
    """
    if not animation:
        return None
    if not character_ids:
        return tuple()
    results = []
    for character_id in character_ids:
        result = animator(character_id, animation, animation_start_frame)
        results.append(result)
    return tuple(results)


def _apply_lip_sync(character_ids, lip_sync_start_frame, lip_sync_callable: Callable):
    """Apply the optional lip-sync animation to every generated character.

    Errors from the delegated lip-sync layer propagate unchanged
    (``UnknownCharacterError``, ``InvalidStartFrameError``,
    ``MissingCharacterError``, ``BlenderUnavailableError``,
    ``UnknownMouthStateError``).
    """
    if not character_ids:
        return tuple()
    results = []
    for character_id in character_ids:
        result = lip_sync_callable(character_id, lip_sync_start_frame, None)
        results.append(result)
    return tuple(results)


def create_and_render_scene(
    concept: str,
    animation: Optional[str] = None,
    animation_start_frame: int = 1,
    lip_sync: bool = False,
    lip_sync_start_frame: int = 1,
    output_path: Optional[str] = None,
    *,
    pipeline: Callable = _default_pipeline,
    animator: Callable = _default_animator,
    lip_sync_callable: Callable = _default_lip_sync,
    camera: Callable = _default_camera,
    renderer: Callable = _default_renderer,
) -> WorkflowResult:
    """Plan, generate, optionally animate / lip-sync, frame, and render a scene.

    Args:
        concept: A non-empty text concept for the AI planner.
        animation: Optional animation name (e.g. ``"wave"``). When
            ``None`` or empty, characters are not animated.
        animation_start_frame: Integer >= 1, the first keyframe of the
            optional animation. Ignored when *animation* is falsy.
        lip_sync: When ``True``, apply the deterministic default
            lip-sync animation to every generated character.
        lip_sync_start_frame: Integer >= 1, the first keyframe of the
            optional lip-sync animation. Ignored when *lip_sync* is
            ``False``.
        output_path: Optional path for the rendered image. When
            ``None``, the deterministic default path is used (resolved
            inside :func:`render_scene`).
        pipeline: Optional injection point replacing
            :func:`pipeline.create_scene_from_concept`. Receives the
            concept and returns an object with ``scene_plan`` and
            ``generation_result`` attributes.
        animator: Optional injection point replacing the per-character
            animation call.
        lip_sync_callable: Optional injection point replacing the
            per-character lip-sync call.
        camera: Optional injection point replacing
            :func:`create_or_update_camera`.
        renderer: Optional injection point replacing
            :func:`render_scene`.

    Returns:
        A :class:`WorkflowResult` aggregating the delegated results.

    Raises:
        WorkflowInputError: when a top-level workflow input is invalid.
        Any error from a delegated layer, propagated unchanged
        (``InvalidConceptError``, ``InvalidScenePlanError``,
        ``UnknownAssetError``, ``UnknownAnimationError``,
        ``InvalidStartFrameError``, ``UnknownCharacterError``,
        ``MissingCharacterError``, ``MissingCameraError``,
        ``InvalidCameraTypeError``, ``InvalidOutputPathError``,
        ``RenderError``, ``BlenderUnavailableError``, etc.).
    """
    _validate_concept(concept)
    _validate_animation_args(animation, animation_start_frame)
    _validate_lip_sync_args(lip_sync, lip_sync_start_frame)

    # 1. Concept -> Scene pipeline.
    scene_creation = pipeline(concept)
    scene_plan = scene_creation.scene_plan
    generation_result = scene_creation.generation_result
    character_ids = tuple(getattr(generation_result, "character_ids", []) or ())

    # 2. Optional character animation.
    animation_results = _apply_animation(
        character_ids, animation, animation_start_frame, animator,
    )

    # 3. Optional lip-sync animation.
    if lip_sync:
        lip_sync_results = _apply_lip_sync(
            character_ids, lip_sync_start_frame, lip_sync_callable,
        )
    else:
        lip_sync_results = None

    # 4. Camera update / create.
    camera_result = camera()

    # 5. Render.
    render_result = renderer(output_path)
    resolved_output_path = _extract_output_path(render_result)

    return WorkflowResult(
        scene_plan=scene_plan,
        generation_result=generation_result,
        animation_results=animation_results,
        lip_sync_results=lip_sync_results,
        camera_result=camera_result,
        render_result=render_result,
        output_path=resolved_output_path,
    )


def _extract_output_path(render_result):
    """Return the resolved output path from *render_result*.

    Supports both attribute access (objects) and mapping access
    (dicts, which is what :func:`render_scene` returns).
    """
    if render_result is None:
        return ""
    value = getattr(render_result, "output_path", None)
    if value is None and isinstance(render_result, dict):
        value = render_result.get("output_path")
    return str(value or "")


__all__ = (
    "create_and_render_scene",
    "WorkflowResult",
    "WorkflowInputError",
)