"""Blender PropertyGroup that holds TOONFLOW AI UI state.

The data lives under ``bpy.types.Scene.toonflow`` so it is namespaced
and cannot collide with unrelated scene data.

Stored fields:

- ``concept``:   The user's multiline concept input.
- ``last_status``: Human-readable status from the most recent operator
  run. Used to drive the panel status label without recreating
  operator reports every redraw.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import PropertyGroup


class ToonflowSceneProperties(PropertyGroup):
    """Scene-scoped UI state for the TOONFLOW AI panel."""

    concept: StringProperty(
        name="Concept",
        description=(
            "Free-form description of the scene to generate. "
            "Sent to the local Ollama planner."
        ),
        default="",
        subtype="MULTILINE",
    )

    last_status: StringProperty(
        name="Last status",
        description="Outcome of the most recent Generate Scene run.",
        default="",
    )


_CLASSES = (ToonflowSceneProperties,)


def register() -> None:
    """Register the TOONFLOW AI scene PropertyGroup and attach it to Scene."""
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.toonflow = bpy.props.PointerProperty(
        type=ToonflowSceneProperties,
        name="TOONFLOW AI",
        description="TOONFLOW AI panel state.",
    )


def unregister() -> None:
    """Detach the property and unregister the PropertyGroup class."""
    if hasattr(bpy.types.Scene, "toonflow"):
        try:
            del bpy.types.Scene.toonflow
        except Exception:
            pass

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)