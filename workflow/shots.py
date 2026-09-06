"""TOONFLOW-PHASE-016 — Multi-Shot Workflow Foundation.

This module is a thin orchestration layer that runs multiple
independent shots through the existing
:func:`workflow.create_and_render_scene` entry point in a fixed,
deterministic order.

The multi-shot orchestrator contains no business logic of its own. It
does not import ``bpy``, does not call AI or Ollama, does not perform
HTTP, does not perform Scene Plan validation, does not manipulate the
Asset Registry, does not create or delete Blender objects, and does
not resolve output paths. Every such responsibility is delegated to
the existing single-shot :func:`workflow.create_and_render_scene` API.

Errors from the delegated single-shot workflow propagate unchanged.
The only new error class is :class:`MultiShotInputError`, raised for
invalid top-level multi-shot inputs.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple


# --- Errors ----------------------------------------------------------------


class MultiShotInputError(ValueError):
    """The top-level multi-shot workflow inputs are invalid.

    The multi-shot layer is the only layer that needs a *new* error
    class for its own arguments. All delegated errors
    (``WorkflowInputError``, ``InvalidConceptError``,
    ``InvalidScenePlanError``, ``MissingCameraError``,
    ``RenderError``, etc.) propagate unchanged.
    """

    def __init__(self, parameter, value):
        self.parameter = parameter
        self.value = value
        super().__init__(
            f"Multi-shot input {parameter!r} is invalid: got {value!r}."
        )


# --- Shot model ------------------------------------------------------------


@dataclass(frozen=True)
class Shot:
    """One independent invocation of ``create_and_render_scene``.

    Attributes:
        concept: A non-empty text concept for the AI planner.
        animation: Optional animation name. When ``None`` or empty,
            characters are not animated.
        animation_start_frame: Integer >= 1, the first keyframe of
            the optional animation. Ignored when *animation* is
            falsy.
        lip_sync: When ``True``, apply the deterministic default
            lip-sync animation to every generated character.
        lip_sync_start_frame: Integer >= 1, the first keyframe of
            the optional lip-sync animation. Ignored when *lip_sync*
            is ``False``.
        output_path: Optional path for the rendered image. When
            ``None``, the deterministic default path is used
            (resolved inside ``render_scene``).
    """

    concept: str
    animation: Optional[str] = None
    animation_start_frame: int = 1
    lip_sync: bool = False
    lip_sync_start_frame: int = 1
    output_path: Optional[str] = None


# --- Result model ----------------------------------------------------------


@dataclass(frozen=True)
class MultiShotResult:
    """The combined outcome of one ``create_and_render_shots`` execution.

    Attributes:
        shot_results: Tuple of per-shot results returned by the
            delegated single-shot workflow, in execution order.
        output_paths: Tuple of resolved absolute output paths, in
            execution order.
        shot_count: The number of shots that were executed
            successfully. Equal to ``len(shot_results)``.
    """

    shot_results: Tuple[Any, ...]
    output_paths: Tuple[str, ...]
    shot_count: int


# --- Default delegation target --------------------------------------------


def _default_workflow_callable(
    *,
    concept,
    animation,
    animation_start_frame,
    lip_sync,
    lip_sync_start_frame,
    output_path,
):
    """Delegate to :func:`workflow.create_and_render_scene`."""
    from .api import create_and_render_scene

    return create_and_render_scene(
        concept,
        animation=animation,
        animation_start_frame=animation_start_frame,
        lip_sync=lip_sync,
        lip_sync_start_frame=lip_sync_start_frame,
        output_path=output_path,
    )


# --- Validation helpers ----------------------------------------------------


def _is_shot_like(value):
    """Return True if *value* looks like a :class:`Shot` instance."""
    return (
        isinstance(value, Shot)
        or (
            isinstance(value, tuple)
            and len(value) >= 1
            and isinstance(value[0], str)
        )
        or (
            hasattr(value, "concept")
            and isinstance(getattr(value, "concept", None), str)
        )
    )


def _extract_shot_fields(shot):
    """Return a dict of fields for *shot*.

    Accepts a :class:`Shot` instance or any object that exposes the
    same field names (``concept``, ``animation``,
    ``animation_start_frame``, ``lip_sync``, ``lip_sync_start_frame``,
    ``output_path``). Strings (which are iterable) and other
    non-shot values are rejected by the caller.
    """
    if isinstance(shot, Shot):
        return {
            "concept": shot.concept,
            "animation": shot.animation,
            "animation_start_frame": shot.animation_start_frame,
            "lip_sync": shot.lip_sync,
            "lip_sync_start_frame": shot.lip_sync_start_frame,
            "output_path": shot.output_path,
        }
    # duck-typed fallback
    return {
        "concept": getattr(shot, "concept"),
        "animation": getattr(shot, "animation"),
        "animation_start_frame": getattr(shot, "animation_start_frame"),
        "lip_sync": getattr(shot, "lip_sync"),
        "lip_sync_start_frame": getattr(shot, "lip_sync_start_frame"),
        "output_path": getattr(shot, "output_path"),
    }


def _validate_shots(shots):
    if not isinstance(shots, (list, tuple)):
        raise MultiShotInputError("shots", shots)
    if len(shots) == 0:
        raise MultiShotInputError("shots", shots)
    for index, shot in enumerate(shots):
        if not _is_shot_like(shot):
            raise MultiShotInputError(f"shots[{index}]", shot)


def _validate_workflow_callable(workflow_callable):
    if not callable(workflow_callable):
        raise MultiShotInputError("workflow_callable", workflow_callable)


# --- Public entry point ----------------------------------------------------


def create_and_render_shots(
    shots: Sequence[Shot],
    *,
    workflow_callable: Callable = _default_workflow_callable,
) -> MultiShotResult:
    """Run multiple shots through the existing single-shot workflow.

    Args:
        shots: A non-empty sequence of :class:`Shot` instances (or
            duck-typed equivalents). Shots execute strictly in input
            order.
        workflow_callable: Optional injection point replacing
            :func:`workflow.create_and_render_scene`. The default
            delegates to the existing single-shot workflow.

    Returns:
        A :class:`MultiShotResult` aggregating the per-shot results
        and the resolved output paths in execution order.

    Raises:
        MultiShotInputError: when *shots* is not a non-empty sequence
            of shot-like values, or when *workflow_callable* is not
            callable.
        Any error from a delegated single-shot workflow, propagated
            unchanged. Execution stops at the first failing shot.
    """
    _validate_shots(shots)
    _validate_workflow_callable(workflow_callable)

    results = []
    output_paths = []
    for index, shot in enumerate(shots):
        fields = _extract_shot_fields(shot)
        result = workflow_callable(**fields)
        results.append(result)
        output_paths.append(str(getattr(result, "output_path", "") or ""))

    return MultiShotResult(
        shot_results=tuple(results),
        output_paths=tuple(output_paths),
        shot_count=len(results),
    )


__all__ = (
    "Shot",
    "MultiShotResult",
    "MultiShotInputError",
    "create_and_render_shots",
)