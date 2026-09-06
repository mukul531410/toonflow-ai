"""Blender UI panel for the TOONFLOW AI add-on.

The panel is intentionally minimal:

- a multiline text input for the concept,
- a Generate Scene button,
- a single status label driven by ``Scene.toonflow.last_status``.

No model selection, no API key fields, no asset selectors, no
animation, camera, or rendering controls are exposed.
"""

import bpy
from bpy.types import Panel

from .properties import ToonflowSceneProperties


class TOONFLOW_PT_panel(Panel):
    """Main TOONFLOW AI panel in the 3D View sidebar."""

    bl_idname = "TOONFLOW_PT_panel"
    bl_label = "TOONFLOW AI"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TOONFLOW"

    def draw(self, context):
        layout = self.layout
        properties = getattr(context.scene, "toonflow", None)
        if not isinstance(properties, ToonflowSceneProperties):
            layout.label(text="TOONFLOW AI not registered.")
            return

        col = layout.column(align=True)
        col.label(text="Concept:")
        col.prop(properties, "concept", text="")

        layout.separator()
        layout.operator("toonflow.generate_scene", icon="PLAY")

        if properties.last_status:
            layout.separator()
            box = layout.box()
            for line in properties.last_status.splitlines() or [""]:
                box.label(text=line)


_CLASSES = (TOONFLOW_PT_panel,)


def register() -> None:
    """Register the TOONFLOW AI panel."""
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    """Unregister the TOONFLOW AI panel."""
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)