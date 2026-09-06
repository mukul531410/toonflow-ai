"""TOONFLOW-PHASE-017 — Persistent Project Model & Deterministic Replay.

This module adds a pure-Python, ``bpy``-free persistent project
definition layer on top of the existing
:func:`workflow.create_and_render_shots` multi-shot API.

The project layer owns:

- the :class:`Project` model (immutable);
- deterministic :func:`project_to_dict` / :func:`project_to_json`
  serialization;
- strict :func:`project_from_dict` / :func:`project_from_json`
  deserialization;
- :func:`save_project` / :func:`load_project` file persistence;
- :func:`replay_project` delegation to the multi-shot workflow.

The project layer does **not** own:

- scene generation;
- character animation or lip-sync;
- camera automation;
- rendering;
- output-path resolution;
- Scene Plan validation;
- Asset Registry logic;
- AI / Ollama / HTTP.

Everything that requires Blender is delegated to the existing
single-shot and multi-shot workflow APIs.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Tuple


# --- Errors ----------------------------------------------------------------


class ProjectInputError(ValueError):
    """A project-layer input is invalid.

    The project layer is the only layer that needs a *new* error class
    for its own arguments. All delegated errors propagate unchanged
    (``MultiShotInputError``, ``WorkflowInputError``,
    ``InvalidConceptError``, ``InvalidScenePlanError``,
    ``MissingCameraError``, ``RenderError``, etc.).
    """

    def __init__(self, parameter, value):
        self.parameter = parameter
        self.value = value
        super().__init__(
            f"Project input {parameter!r} is invalid: got {value!r}."
        )


# --- Constants -------------------------------------------------------------


from .project_migrations import PROJECT_SCHEMA_VERSION as _MIGRATION_SCHEMA_VERSION


PROJECT_SCHEMA_VERSION = _MIGRATION_SCHEMA_VERSION


_SUPPORTED_SCHEMA_VERSIONS = (1, 2)


_INDENT = 2
_SORT_KEYS = False
_ENSURE_ASCII = False


# --- Project model ---------------------------------------------------------


def _validate_name(name):
    if isinstance(name, bool) or not isinstance(name, str):
        raise ProjectInputError("name", name)
    if not name or not name.strip():
        raise ProjectInputError("name", name)


def _validate_shots(shots):
    if not isinstance(shots, (list, tuple)):
        raise ProjectInputError("shots", shots)
    if len(shots) == 0:
        raise ProjectInputError("shots", shots)
    from .shots import Shot
    for index, shot in enumerate(shots):
        if not isinstance(shot, Shot):
            raise ProjectInputError(f"shots[{index}]", shot)
    return tuple(shots)


@dataclass(frozen=True)
class Project:
    """A deterministic, immutable multi-shot project definition.

    Attributes:
        name: Non-empty project name. Used purely as a deterministic
            identifier for the project itself; it is not a path.
        shots: Non-empty tuple of :class:`Shot` instances in execution
            order.
        schema_version: The on-disk schema version. Defaults to
            :data:`PROJECT_SCHEMA_VERSION`. Only used by
            :func:`project_to_dict` and :func:`project_from_dict` to
            gate future-compatible changes.
        description: Optional human-readable description. Defaults to
            the empty string. Introduced in schema version 2.
    """

    name: str
    shots: Tuple
    schema_version: int = PROJECT_SCHEMA_VERSION
    description: str = ""

    def __post_init__(self):
        _validate_name(self.name)
        # Re-validate and normalize shots so the field is always a tuple.
        normalized = _validate_shots(self.shots)
        if normalized is not self.shots:
            object.__setattr__(self, "shots", normalized)
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
        ):
            raise ProjectInputError("schema_version", self.schema_version)
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise ProjectInputError("schema_version", self.schema_version)
        if isinstance(self.description, bool) or not isinstance(self.description, str):
            raise ProjectInputError("description", self.description)


# --- Serialization ---------------------------------------------------------


_SHOT_FIELDS_ORDER = (
    "concept",
    "animation",
    "animation_start_frame",
    "lip_sync",
    "lip_sync_start_frame",
    "output_path",
)


def _shot_to_dict(shot):
    return {field: getattr(shot, field) for field in _SHOT_FIELDS_ORDER}


def _shot_from_dict(data):
    if not isinstance(data, dict):
        raise ProjectInputError("shot", data)
    missing = [f for f in _SHOT_FIELDS_ORDER if f not in data]
    if missing:
        raise ProjectInputError(f"shot.missing[{missing[0]}]", data)
    unknown = sorted(set(data) - set(_SHOT_FIELDS_ORDER))
    if unknown:
        raise ProjectInputError("shot.unknown", tuple(unknown))
    from .shots import Shot

    return Shot(
        concept=data["concept"],
        animation=data["animation"],
        animation_start_frame=data["animation_start_frame"],
        lip_sync=data["lip_sync"],
        lip_sync_start_frame=data["lip_sync_start_frame"],
        output_path=data["output_path"],
    )


def project_to_dict(project):
    """Return a JSON-compatible dict representation of * ``project*.

    The returned dict contains only built-in Python types and uses the
    canonical field names. The top-level key order is fixed.
    """
    if not isinstance(project, Project):
        raise ProjectInputError("project", project)
    return {
        "schema_version": int(project.schema_version),
        "name": project.name,
        "description": project.description,
        "shots": [_shot_to_dict(s) for s in project.shots],
    }


def project_from_dict(data):
    """Reconstruct a :class:`Project` from a dict.

    Strictly rejects malformed input. The dict must already be
    JSON-decoded; this function does not parse JSON. Supported older
    schema versions are transparently migrated to the current schema
    via :func:`migrate_project_dict`; callers do not need to migrate
    before calling this function.
    """
    if not isinstance(data, dict):
        raise ProjectInputError("project", data)

    from .project_migrations import migrate_project_dict

    try:
        migrated = migrate_project_dict(data)
    except TypeError as exc:
        # The migration layer raised because the input was not a
        # JSON-compatible mapping. Surface that as a project input
        # error for backward compatibility with PHASE-017 callers.
        raise ProjectInputError("project", data) from exc
    except ValueError as exc:
        # UnsupportedProjectSchemaError is a ValueError subclass.
        # Re-raise as a project input error so existing callers that
        # expect ProjectInputError continue to work.
        raise ProjectInputError("project.schema_version", data.get("schema_version")) from exc

    # After migration, the dict is at the current schema and contains
    # at least: schema_version, name, description, shots.
    if "name" not in migrated:
        raise ProjectInputError("project.name", None)
    name = migrated["name"]
    if isinstance(name, bool) or not isinstance(name, str) or not name.strip():
        raise ProjectInputError("project.name", name)

    if "description" not in migrated:
        # Defensive: migration should always add this for current schema.
        migrated["description"] = ""
    description = migrated["description"]
    if isinstance(description, bool) or not isinstance(description, str):
        raise ProjectInputError("project.description", description)

    if "shots" not in migrated:
        raise ProjectInputError("project.shots", None)
    shots_raw = migrated["shots"]
    if not isinstance(shots_raw, (list, tuple)):
        raise ProjectInputError("project.shots", shots_raw)
    if len(shots_raw) == 0:
        raise ProjectInputError("project.shots", shots_raw)
    shots = tuple(_shot_from_dict(item) for item in shots_raw)

    unknown = sorted(
        set(migrated) - {"schema_version", "name", "description", "shots"}
    )
    if unknown:
        raise ProjectInputError("project.unknown", tuple(unknown))

    # `schema_version` was already validated by the migration layer.
    schema_version = int(migrated["schema_version"])

    return Project(
        name=name,
        shots=shots,
        schema_version=schema_version,
        description=description,
    )


# --- JSON helpers ---------------------------------------------------------


def project_to_json(project):
    """Return a deterministic JSON string for * ``project*.

    Determinism properties:

    - stable key ordering (the dicts in :func:`project_to_dict` are
      constructed in a fixed canonical order, and ``sort_keys=False``
      is used so the JSON preserves that order);
    - consistent indentation (``indent=2``) and stable trailing
      newline;
    - ``ensure_ascii=False`` so non-ASCII characters survive
      verbatim (re-decoding always yields the same Project);
    - no timestamps, no environment data, no random IDs.
    """
    return json.dumps(
        project_to_dict(project),
        indent=_INDENT,
        sort_keys=_SORT_KEYS,
        ensure_ascii=_ENSURE_ASCII,
        separators=(",", ": "),
    ) + "\n"


def project_from_json(text):
    """Reconstruct a :class:`Project` from a JSON string.

    Raises:
        ProjectInputError: when * ``text* is not a string, is empty,
            or contains invalid JSON.
        json.JSONDecodeError: when * ``text* is a string but is not
            valid JSON.
    """
    if not isinstance(text, str):
        raise ProjectInputError("json", text)
    if not text.strip():
        raise ProjectInputError("json", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise
    return project_from_dict(data)


# --- Path validation ------------------------------------------------------


def _validate_path(value):
    if value is None:
        raise ProjectInputError("path", value)
    if not isinstance(value, (str, os.PathLike)):
        raise ProjectInputError("path", value)
    try:
        text = os.fspath(value)
    except (TypeError, ValueError):
        raise ProjectInputError("path", value)
    if not isinstance(text, str) or not text.strip():
        raise ProjectInputError("path", value)
    try:
        path = Path(text)
    except (TypeError, ValueError):
        raise ProjectInputError("path", value)
    if not path.name:
        raise ProjectInputError("path", value)
    return path


# --- File persistence -----------------------------------------------------


def save_project(project, path):
    """Serialize * ``project* to * ``path* as deterministic JSON.

    Args:
        project: A :class:`Project` instance.
        path: A non-empty string or :class:`os.PathLike` whose parent
            directory may be created.

    Returns:
        The absolute :class:`pathlib.Path` of the written file.

    Raises:
        ProjectInputError: when * ``project* or * ``path* is invalid.
        OSError: when the file cannot be written.
    """
    if not isinstance(project, Project):
        raise ProjectInputError("project", project)
    path = _validate_path(path)
    parent = path.parent
    if str(parent) and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    payload = project_to_json(project)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)
    return path.resolve()


def load_project(path):
    """Load and validate a :class:`Project` from the JSON file at * ``path*."""
    path = _validate_path(path)
    if path.exists() and path.is_dir():
        raise ProjectInputError("path", str(path))
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return project_from_json(text)


# --- Replay ---------------------------------------------------------------


def _default_workflow_callable(shots, *, workflow_callable=None):
    """Delegate to :func:`workflow.create_and_render_shots`."""
    from .shots import create_and_render_shots

    if workflow_callable is None:
        return create_and_render_shots(shots)
    return create_and_render_shots(shots, workflow_callable=workflow_callable)


def replay_project(project, *, workflow_callable=None):
    """Replay * ``project* through the existing multi-shot workflow.

    Args:
        project: A :class:`Project` instance.
        workflow_callable: Optional per-shot injection point that is
            forwarded to :func:`workflow.create_and_render_shots` as
            its ``workflow_callable`` keyword. The default is
            ``None``, meaning the multi-shot workflow uses its own
            default per-shot callable
            (:func:`workflow.create_and_render_scene`).

    Returns:
        The :class:`MultiShotResult` returned by the multi-shot
        workflow.

    Raises:
        ProjectInputError: when * ``project* is not a Project.
        Any error from the delegated multi-shot workflow, propagated
        unchanged.
    """
    if not isinstance(project, Project):
        raise ProjectInputError("project", project)
    return _default_workflow_callable(
        project.shots,
        workflow_callable=workflow_callable,
    )


__all__ = (
    "Project",
    "ProjectInputError",
    "PROJECT_SCHEMA_VERSION",
    "project_to_dict",
    "project_from_dict",
    "project_to_json",
    "project_from_json",
    "save_project",
    "load_project",
    "replay_project",
)