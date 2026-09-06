"""Blender-dependent scene generation for TOONFLOW AI.

This module is the only place in TOONFLOW AI that imports ``bpy``.
``bpy`` is imported lazily so the package can be imported in test
environments where Blender is not available; calling ``generate_scene``
without Blender still raises a clear ``BlenderUnavailableError``.

Ownership and idempotency strategy
----------------------------------

TOONFLOW objects are kept in a single collection named ``"TOONFLOW"`` and
follow deterministic names:

- ``TOONFLOW_ENV_<ENV_ID>`` for the environment placeholder
- ``TOONFLOW_CHARACTER_<CHARACTER_ID>`` for each character root (Empty)
- ``TOONFLOW_CHARACTER_<CHARACTER_ID>_<PART>`` for each character part

Before generating, the generator removes only those objects (and the
``TOONFLOW`` collection if it becomes empty). It never inspects,
mutates, or removes unrelated user objects.

Character hierarchy
-------------------

Each character is a deterministic parent/child hierarchy:

    TOONFLOW_CHARACTER_<ID>          (Empty, root)
    ├── TOONFLOW_CHARACTER_<ID>_BODY
    ├── TOONFLOW_CHARACTER_<ID>_HEAD
    ├── TOONFLOW_CHARACTER_<ID>_LEFT_ARM
    ├── TOONFLOW_CHARACTER_<ID>_RIGHT_ARM
    ├── TOONFLOW_CHARACTER_<ID>_LEFT_LEG
    └── TOONFLOW_CHARACTER_<ID>_RIGHT_LEG

Placeholders
------------

Only simple Blender primitive meshes are created. There are no
materials, textures, rigs, animations, lights, cameras, or external
files.
"""


def _require_bpy():
    """Import ``bpy`` lazily and raise a clear error if unavailable."""
    try:
        import bpy  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only outside Blender
        raise BlenderUnavailableError(
            "The Blender 'bpy' module is not available in this Python "
            "process. generate_scene() must be called from inside Blender."
        ) from exc
    return bpy


from .errors import BlenderUnavailableError
from .naming import (
    CHARACTER_PARTS,
    TOONFLOW_COLLECTION_NAME,
    character_object_name,
    character_part_object_name,
    env_object_name,
)


CHARACTER_BODY_HEIGHT = 1.8
CHARACTER_BODY_RADIUS = 0.35
CHARACTER_HEAD_RADIUS = 0.22
CHARACTER_ARM_LENGTH = 0.8
CHARACTER_ARM_RADIUS = 0.12
CHARACTER_LEG_LENGTH = 0.9
CHARACTER_LEG_RADIUS = 0.14
FLOOR_SIZE = 6.0
CHARACTER_SPREAD = 1.5


def _ensure_toonflow_collection(bpy):
    """Return the TOONFLOW collection, creating it if necessary."""
    coll = bpy.data.collections.get(TOONFLOW_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(TOONFLOW_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(coll)
    else:
        if coll.name not in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.link(coll)
    return coll


def _remove_existing_toonflow_objects(bpy):
    """Remove only objects previously created by TOONFLOW.

    This includes character roots, character parts, and the
    environment. Unrelated user objects are never touched.

    The deterministic TOONFLOW camera (``TOONFLOW_CAMERA``) is
    preserved across regeneration so callers can re-run
    ``generate_scene`` without losing the camera setup.
    """
    from .camera_data import TOONFLOW_CAMERA_NAME

    to_delete = [
        obj for obj in bpy.data.objects
        if (
            obj.name.startswith("TOONFLOW_")
            or obj.name == TOONFLOW_COLLECTION_NAME
        )
        and obj.name != TOONFLOW_CAMERA_NAME
    ]
    for obj in to_delete:
        if obj.type != "COLLECTION":
            bpy.data.objects.remove(obj, do_unlink=True)

    coll = bpy.data.collections.get(TOONFLOW_COLLECTION_NAME)
    if coll is not None and not coll.all_objects:
        try:
            bpy.data.collections.remove(coll)
        except RuntimeError:
            pass


def _create_floor(bpy, collection, env_id):
    """Create a simple floor plane for the given environment id."""
    mesh = bpy.data.meshes.new(env_object_name(env_id) + "_MESH")
    mesh.from_pydata(
        _floor_vertices(),
        [],
        _floor_faces(),
    )
    mesh.update()

    obj = bpy.data.objects.new(env_object_name(env_id), mesh)
    collection.objects.link(obj)
    return obj


def _floor_vertices():
    half = FLOOR_SIZE / 2.0
    return [
        (-half, -half, 0.0),
        (half, -half, 0.0),
        (half, half, 0.0),
        (-half, half, 0.0),
    ]


def _floor_faces():
    return [(0, 1, 2, 3)]


def _create_character_root(bpy, collection, character_id, index):
    """Create the deterministic Empty root for *character_id*."""
    obj = bpy.data.objects.new(
        character_object_name(character_id),
        None,  # Empty: no mesh data
    )
    obj.location = (_character_x(index), 0.0, 0.0)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 0.4
    collection.objects.link(obj)
    return obj


def _create_character_part(bpy, collection, parent, character_id, part):
    """Create one primitive part and parent it to *parent*."""
    name = character_part_object_name(character_id, part)
    if part == "BODY":
        mesh = _make_cylinder_mesh(bpy, name, CHARACTER_BODY_RADIUS, CHARACTER_BODY_HEIGHT)
    elif part == "HEAD":
        mesh = _make_sphere_mesh(bpy, name, CHARACTER_HEAD_RADIUS)
    elif part in ("LEFT_ARM", "RIGHT_ARM"):
        mesh = _make_cylinder_mesh(bpy, name, CHARACTER_ARM_RADIUS, CHARACTER_ARM_LENGTH)
    elif part in ("LEFT_LEG", "RIGHT_LEG"):
        mesh = _make_cylinder_mesh(bpy, name, CHARACTER_LEG_RADIUS, CHARACTER_LEG_LENGTH)
    else:
        raise ValueError(f"Unknown character part {part!r}.")

    obj = bpy.data.objects.new(name, mesh)
    obj.location = _part_local_position(part)
    collection.objects.link(obj)
    parent.children.link(obj)
    return obj


def _make_cylinder_mesh(bpy, name, radius, height):
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(
        _cylinder_vertices(radius, height),
        [],
        _cylinder_faces(),
    )
    mesh.update()
    return mesh


def _make_sphere_mesh(bpy, name, radius):
    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(
        _sphere_vertices(radius),
        [],
        _sphere_faces(),
    )
    mesh.update()
    return mesh


def _part_local_position(part):
    """Deterministic local offset for a character part inside the root."""
    half_body = CHARACTER_BODY_HEIGHT / 2.0
    half_arm = CHARACTER_ARM_LENGTH / 2.0
    half_leg = CHARACTER_LEG_LENGTH / 2.0
    shoulder_offset = CHARACTER_BODY_RADIUS + CHARACTER_ARM_RADIUS
    hip_offset = CHARACTER_BODY_RADIUS

    if part == "BODY":
        return (0.0, 0.0, half_body)
    if part == "HEAD":
        return (0.0, 0.0, CHARACTER_BODY_HEIGHT + CHARACTER_HEAD_RADIUS)
    if part == "LEFT_ARM":
        return (shoulder_offset, 0.0, CHARACTER_BODY_HEIGHT - half_arm)
    if part == "RIGHT_ARM":
        return (-shoulder_offset, 0.0, CHARACTER_BODY_HEIGHT - half_arm)
    if part == "LEFT_LEG":
        return (hip_offset * 0.5, 0.0, -half_leg + 0.05)
    if part == "RIGHT_LEG":
        return (-hip_offset * 0.5, 0.0, -half_leg + 0.05)
    raise ValueError(f"Unknown character part {part!r}.")


def _character_x(index):
    """Deterministic X placement based on character index."""
    offsets = [-CHARACTER_SPREAD, 0.0, CHARACTER_SPREAD]
    return offsets[index % len(offsets)]


def _cylinder_vertices(radius, height):
    half = height / 2.0
    return [
        (radius, 0.0, -half),
        (0.0, radius, -half),
        (-radius, 0.0, -half),
        (0.0, -radius, -half),
        (radius, 0.0, half),
        (0.0, radius, half),
        (-radius, 0.0, half),
        (0.0, -radius, half),
    ]


def _cylinder_faces():
    sides = [
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    bottom = (0, 3, 2, 1)
    top = (4, 5, 6, 7)
    return sides + [bottom, top]


def _sphere_vertices(radius):
    return [
        (radius, 0.0, 0.0),
        (0.0, radius, 0.0),
        (-radius, 0.0, 0.0),
        (0.0, -radius, 0.0),
        (0.0, 0.0, radius),
        (0.0, 0.0, -radius),
    ]


def _sphere_faces():
    return [
        (0, 1, 4),
        (1, 2, 4),
        (2, 3, 4),
        (3, 0, 4),
        (0, 5, 1),
        (1, 5, 2),
        (2, 5, 3),
        (3, 5, 0),
    ]


def _generate_environment(bpy, collection, environment_id):
    """Create the placeholder environment objects."""
    return [_create_floor(bpy, collection, environment_id)]


def _generate_characters(bpy, collection, characters):
    """Create the multi-part placeholder character hierarchies."""
    created = []
    for index, character in enumerate(characters):
        root = _create_character_root(
            bpy, collection, character["id"], index
        )
        created.append(root)
        for part in CHARACTER_PARTS:
            obj = _create_character_part(
                bpy,
                collection,
                root,
                character["id"],
                part,
            )
            created.append(obj)
    return created


def generate_in_blender(scene_plan_data):
    """Execute the Blender-side scene generation.

    This function assumes validation has already passed. It must be
    called from within Blender; ``bpy`` is imported lazily.
    """
    bpy = _require_bpy()

    _remove_existing_toonflow_objects(bpy)
    collection = _ensure_toonflow_collection(bpy)

    environment_id = scene_plan_data["scene"]["environment"]
    environment_objects = _generate_environment(
        bpy, collection, environment_id
    )
    character_objects = _generate_characters(
        bpy, collection, scene_plan_data["characters"]
    )

    return {
        "collection_name": TOONFLOW_COLLECTION_NAME,
        "environment_id": environment_id,
        "environment_object_names": [obj.name for obj in environment_objects],
        "character_ids": [c["id"] for c in scene_plan_data["characters"]],
        "character_object_names": [obj.name for obj in character_objects],
    }