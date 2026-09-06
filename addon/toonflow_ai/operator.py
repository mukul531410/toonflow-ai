"""Blender operator that drives the TOONFLOW AI concept-to-scene pipeline.

Boundary contract:

- The operator reads the concept from the scene property, validates that
  it is non-empty, and calls the existing
  ``pipeline.create_scene_from_concept`` public API.
- The operator NEVER imports ``urllib``, never builds prompts, never
  validates Scene Plans, never looks up assets, and never creates
  Blender objects. All of those live in their existing packages.
- The operator only translates domain errors into Blender operator
  reports and updates the scene-scoped status label.
"""

import bpy
from bpy.types import Operator

# These imports are evaluated when the operator module is loaded inside
# Blender. ``pipeline`` itself depends on ``ai`` and
# ``toonflow_ai.generation``, neither of which import ``bpy`` at module
# load time (``bpy`` is imported lazily inside the generation module).
from pipeline import create_scene_from_concept


class TOONFLOW_OT_generate_scene(Operator):
    """Run the AI concept-to-scene pipeline and create Blender placeholders."""

    bl_idname = "toonflow.generate_scene"
    bl_label = "Generate Scene"
    bl_description = (
        "Send the concept to the local Ollama planner and generate the "
        "validated scene as Blender placeholder objects."
    )

    bl_options = {"REGISTER"}

    def execute(self, context):
        """Read the concept, invoke the pipeline, and report the result."""
        properties = getattr(context.scene, "toonflow", None)
        if properties is None or not _is_toonflow_properties(properties):
            self.report(
                {"ERROR"},
                "TOONFLOW AI scene properties are not registered.",
            )
            return {"CANCELLED"}

        concept = (properties.concept or "").strip()
        if not concept:
            self.report({"ERROR"}, "Concept must not be empty.")
            properties.last_status = "Concept must not be empty."
            return {"CANCELLED"}

        try:
            result = create_scene_from_concept(concept)
        except _KnownPipelineError as error:
            message = message_for_error(error)
            self.report({"ERROR"}, message)
            properties.last_status = message
            return {"CANCELLED"}
        except Exception as error:  # pragma: no cover - defensive
            report_unexpected(self, error)
            return {"CANCELLED"}

        env_names = ", ".join(result.generation_result.environment_object_names)
        char_names = ", ".join(result.generation_result.character_object_names)
        message = (
            "TOONFLOW AI generated scene: environment "
            f"[{env_names}]; characters [{char_names}]."
        )
        self.report({"INFO"}, message)
        properties.last_status = message
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Pure-Python error mapping helpers (no bpy).
# ---------------------------------------------------------------------------

try:
    from ai.errors import (
        InvalidConceptError,
        InvalidModelJSONError,
        InvalidScenePlanError as AIInvalidScenePlanError,
        OllamaHTTPError,
        OllamaResponseError,
        OllamaTimeoutError,
        OllamaUnavailableError,
        PlannerError,
    )
except ImportError:  # pragma: no cover - exercised only outside Blender
    PlannerError = Exception  # type: ignore[assignment]
    InvalidConceptError = Exception  # type: ignore[assignment]
    InvalidModelJSONError = Exception  # type: ignore[assignment]
    AIInvalidScenePlanError = Exception  # type: ignore[assignment]
    OllamaHTTPError = Exception  # type: ignore[assignment]
    OllamaResponseError = Exception  # type: ignore[assignment]
    OllamaTimeoutError = Exception  # type: ignore[assignment]
    OllamaUnavailableError = Exception  # type: ignore[assignment]


try:
    from toonflow_ai.generation.errors import (
        BlenderUnavailableError,
        InvalidScenePlanError as GenInvalidScenePlanError,
        UnknownAssetError,
    )
except ImportError:  # pragma: no cover - exercised only outside Blender
    BlenderUnavailableError = Exception  # type: ignore[assignment]
    GenInvalidScenePlanError = Exception  # type: ignore[assignment]
    UnknownAssetError = Exception  # type: ignore[assignment]


def _known_pipeline_errors():
    """Return the tuple of all known domain error classes."""
    return (
        InvalidConceptError,
        OllamaUnavailableError,
        OllamaTimeoutError,
        OllamaHTTPError,
        OllamaResponseError,
        InvalidModelJSONError,
        AIInvalidScenePlanError,
        GenInvalidScenePlanError,
        UnknownAssetError,
        BlenderUnavailableError,
    )


_KnownPipelineError = _known_pipeline_errors()


def _is_toonflow_properties(properties: object) -> bool:
    """Duck-typed guard for the TOONFLOW AI scene-scoped PropertyGroup."""
    return all(hasattr(properties, attr) for attr in ("concept", "last_status"))


def message_for_error(error: Exception) -> str:
    """Return a user-facing message for any known domain error.

    Exposed for testing and reuse; the operator delegates here.
    """
    if isinstance(error, InvalidConceptError):
        return "Concept is empty or not a valid string."
    if isinstance(error, OllamaUnavailableError):
        return (
            "Local Ollama service is unreachable. "
            "Start Ollama and ensure it listens on the configured URL."
        )
    if isinstance(error, OllamaTimeoutError):
        return (
            "Local Ollama did not respond before the timeout. "
            "Increase the timeout or check the model."
        )
    if isinstance(error, OllamaHTTPError):
        detail = getattr(error, "detail", "") or ""
        suffix = f" {detail}" if detail else ""
        return f"Local Ollama returned HTTP {error.status_code}.{suffix}"
    if isinstance(error, OllamaResponseError):
        return "Local Ollama returned an unusable response."
    if isinstance(error, InvalidModelJSONError):
        return "The model returned text that is not valid JSON."
    if isinstance(error, AIInvalidScenePlanError):
        return (
            "The model's JSON failed Scene Plan validation. "
            f"{len(error.errors)} error(s)."
        )
    if isinstance(error, GenInvalidScenePlanError):
        return (
            "Generated Scene Plan failed validation. "
            f"{len(error.errors)} error(s)."
        )
    if isinstance(error, UnknownAssetError):
        return (
            f"Scene Plan referenced unknown {error.asset_type} "
            f"{error.asset_id!r}; check the Asset Registry."
        )
    if isinstance(error, BlenderUnavailableError):
        return "Blender 'bpy' module is unavailable in this process."
    if isinstance(error, PlannerError):
        return f"Planner error: {error}"
    return f"{type(error).__name__}: {error}"


def report_unexpected(operator: Operator, error: Exception) -> None:
    """Report an unexpected error and print its traceback for debugging.

    Used by the operator's defensive catch-all. The traceback is printed
    to Blender's console for debugging context; the user-facing report
    contains only the error type and message — never the raw stack.
    """
    import traceback

    traceback.print_exc()
    operator.report(
        {"ERROR"},
        f"Unexpected TOONFLOW AI error: {type(error).__name__}: {error}",
    )
    properties = getattr(operator.context.scene, "toonflow", None)
    if _is_toonflow_properties(properties):
        properties.last_status = (
            f"Unexpected error: {type(error).__name__}: {error}"
        )


_CLASSES = (TOONFLOW_OT_generate_scene,)


def register() -> None:
    """Register the operator class with Blender."""
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    """Unregister the operator class."""
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)