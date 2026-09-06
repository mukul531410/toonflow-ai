"""TOONFLOW AI Blender add-on package.

Layers in this package:

- ``properties``: Blender PropertyGroup definitions that store UI state
  under the scene (``bpy.types.Scene.toonflow``).
- ``operator``: Blender operators that bridge the UI to the existing
  pure-Python ``pipeline`` package.
- ``ui``: Blender UI panels that draw the concept input, the Generate
  Scene button, and a small status label.
- ``registration``: Lifecycle that registers/unregisters the property,
  operator, and panel.

Boundary discipline:

- Only modules in this package import ``bpy``.
- The ``pipeline``, ``ai``, ``scene_plan``, and ``asset_registry``
  packages remain ``bpy``-independent.
- This module does NOT duplicate planning, validation, asset-lookup,
  or scene-generation logic. It only invokes existing public APIs.

The submodules that import ``bpy`` are NOT imported at package load
time. ``register()`` and ``unregister()`` resolve them lazily so that
pure-Python environments (such as the project's test suite) can import
``toonflow_ai.generation`` without requiring Blender.
"""

bl_info = {
    "name": "TOONFLOW AI",
    "blender": (4, 2, 0),
    "category": "3D View",
    "version": (0, 5, 0),
    "author": "TOONFLOW AI",
    "description": "Turn concepts into 3D cartoon scenes through local Ollama.",
}


def register() -> None:
    """Register all TOONFLOW AI add-on classes."""
    from . import registration

    registration.register()


def unregister() -> None:
    """Unregister all TOONFLOW AI add-on classes in reverse-safe order."""
    from . import registration

    registration.unregister()