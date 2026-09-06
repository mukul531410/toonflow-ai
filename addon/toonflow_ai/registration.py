"""Add-on registration lifecycle for TOONFLOW AI.

Registration order (reverse-safe unregistration):

1. UI panel (``ui.TOONFLOW_PT_panel``)
2. Operator (``operator.TOONFLOW_OT_generate_scene``)
3. Scene PropertyGroup + ``Scene.toonflow`` pointer
   (``properties.ToonflowSceneProperties``)

Unregistration happens in the opposite order.
"""

from . import operator, properties, ui


def register() -> None:
    """Register every Blender-side TOONFLOW AI class."""
    ui.register()
    operator.register()
    properties.register()


def unregister() -> None:
    """Unregister every Blender-side TOONFLOW AI class in reverse order."""
    properties.unregister()
    operator.unregister()
    ui.unregister()