"""TOONFLOW-PHASE-018 — Project Schema Versioning & Migration Foundation.

This module is the single source of truth for the project schema
versioning and migration policy. It is pure-Python, ``bpy``-free,
AI-free, and dependency-free.

It owns:

- the canonical current schema version (:data:`PROJECT_SCHEMA_VERSION`);
- the ordered tuple of supported schema versions
  (:data:`SUPPORTED_PROJECT_SCHEMA_VERSIONS`);
- the structured :class:`UnsupportedProjectSchemaError`;
- the deterministic :func:`migrate_project_dict` and
  :func:`migrate_project_dict_to_version` migration functions.

It does NOT own:

- JSON file persistence (that is owned by :mod:`workflow.project`);
- the :class:`Project` model itself (that is owned by
  :mod:`workflow.project`);
- any Blender, AI, Ollama, or HTTP code.

Schema versions
---------------

- Version 1 (PHASE-017): the original deterministic project format.
- Version 2 (PHASE-018): adds an optional ``description`` field at
  the project level. The field defaults to the empty string. No
  other fields change.

Migration policy
----------------

Migrations are deterministic, explicit, and minimal. They never
mutate the input dictionary; they always produce a new dictionary.
They run step-by-step in ascending version order. Intermediate
versions are never skipped.

The only currently registered migration is ``_migrate_v1_to_v2``,
which copies the input and adds ``description=""`` at the top
level.
"""

from typing import Any, Dict, Tuple


# --- Constants -------------------------------------------------------------


PROJECT_SCHEMA_VERSION = 2


SUPPORTED_PROJECT_SCHEMA_VERSIONS: Tuple[int, ...] = (1, 2)


# Field name introduced in schema version 2.
DESCRIPTION_FIELD = "description"


# --- Errors ----------------------------------------------------------------


class UnsupportedProjectSchemaError(ValueError):
    """The provided project schema version is not supported.

    Attributes:
        provided_version: The offending version (preserved as-given).
        supported_versions: Tuple of supported version integers.
        current_version: The canonical current schema version.
    """

    def __init__(self, provided_version, supported_versions, current_version):
        self.provided_version = provided_version
        self.supported_versions = tuple(supported_versions)
        self.current_version = int(current_version)
        super().__init__(
            f"Unsupported project schema version {provided_version!r}; "
            f"supported versions: {list(self.supported_versions)}; "
            f"current version: {self.current_version}."
        )


# --- Version validation ----------------------------------------------------


def _validate_schema_version_value(value, *, parameter):
    """Validate that *value* is a usable, positive, non-bool integer.

    Raises:
        TypeError: when *value* is ``None``, a ``bool``, or not an
            ``int``.
        ValueError: when *value* is not a positive integer.
    """
    if value is None:
        raise TypeError(
            f"schema version {parameter!r} must not be None."
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"schema version {parameter!r} must be an int (bool is rejected); "
            f"got {type(value).__name__}."
        )
    if int(value) < 1:
        raise ValueError(
            f"schema version {parameter!r} must be >= 1; got {value!r}."
        )
    return int(value)


# --- Migration helpers -----------------------------------------------------


def _deep_copy(data):
    """Return a deterministic, deep copy of * ``data* for JSON-compatible values.

    Uses ``json`` round-trip to guarantee no shared references and no
    Python-specific objects survive. ``ensure_ascii=False`` is used
    so non-ASCII strings survive verbatim.
    """
    import json

    return json.loads(
        json.dumps(data, ensure_ascii=False, sort_keys=False, separators=(",", ": ")),
        object_hook=None,
    )


def _copy_shots(data):
    """Return a deterministic, independent copy of the * ``shots* list."""
    shots = data.get("shots", [])
    if not isinstance(shots, list):
        shots = list(shots)
    new_shots = []
    for shot in shots:
        new_shots.append(_deep_copy(shot))
    return new_shots


# --- Individual migrations -------------------------------------------------


def _migrate_v1_to_v2(data):
    """Migrate a v1 project dict to a v2 project dict.

    The v1 -> v2 migration adds the optional ``description`` field at
    the project level. The field defaults to the empty string. The
    input is not mutated; a new independent dict is returned.
    """
    migrated = _deep_copy(data)
    migrated["schema_version"] = 2
    if DESCRIPTION_FIELD not in migrated:
        migrated[DESCRIPTION_FIELD] = ""
    return migrated


# --- Migration registry ----------------------------------------------------


# Each entry maps a source version to a callable that returns a dict
# at source_version + 1. The registry is ordered and must be kept in
# ascending version order.
_MIGRATION_STEPS = (
    (1, _migrate_v1_to_v2),
)


def _build_migration_path(source_version, target_version):
    """Return the ordered list of migrations from * ``source_version* to * ``target_version*.

    Raises:
        UnsupportedProjectSchemaError: when the path is impossible.
    """
    path = []
    current = int(source_version)
    target = int(target_version)
    while current < target:
        step = next(
            ((src, fn) for src, fn in _MIGRATION_STEPS if src == current),
            None,
        )
        if step is None:
            raise UnsupportedProjectSchemaError(
                current,
                SUPPORTED_PROJECT_SCHEMA_VERSIONS,
                PROJECT_SCHEMA_VERSION,
            )
        path.append(step)
        current += 1
    if current != target:
        # The source is greater than the target: reverse migration is
        # not supported.
        raise UnsupportedProjectSchemaError(
            source_version,
            SUPPORTED_PROJECT_SCHEMA_VERSIONS,
            PROJECT_SCHEMA_VERSION,
        )
    return path


# --- Public migration API --------------------------------------------------


def _normalize_data(data):
    """Validate that * ``data* is a mapping. Return * ``data* unchanged."""
    if not isinstance(data, dict):
        raise TypeError(
            f"project data must be a dict; got {type(data).__name__}."
        )
    return data


def _extract_input_version(data, *, parameter):
    """Read and validate the ``schema_version`` field from * ``data*."""
    if "schema_version" not in data:
        raise UnsupportedProjectSchemaError(
            None,
            SUPPORTED_PROJECT_SCHEMA_VERSIONS,
            PROJECT_SCHEMA_VERSION,
        )
    return _validate_schema_version_value(
        data["schema_version"], parameter=parameter
    )


def migrate_project_dict_to_version(data, target_version):
    """Migrate * ``data* to * ``target_version* and return the migrated dict.

    The input is not mutated. The returned dict is independent of the
    input. Migration runs step-by-step in ascending version order.

    Args:
        data: A JSON-compatible dict representing a project document.
        target_version: The desired target schema version (positive
            ``int``, non-``bool``).

    Returns:
        A new dict at * ``target_version*. When
        ``target_version`` equals the source version, the returned
        dict is a deep copy of the input with no semantic changes.

    Raises:
        TypeError: when * ``data* is not a dict or * ``target_version*
            is not a positive int.
        UnsupportedProjectSchemaError: when the source version is
            unsupported, the target version is unsupported, or no
            migration path exists between them.
    """
    _normalize_data(data)
    target = _validate_schema_version_value(
        target_version, parameter="target_version",
    )
    if target not in SUPPORTED_PROJECT_SCHEMA_VERSIONS:
        raise UnsupportedProjectSchemaError(
            target,
            SUPPORTED_PROJECT_SCHEMA_VERSIONS,
            PROJECT_SCHEMA_VERSION,
        )
    source = _extract_input_version(data, parameter="schema_version")
    if source not in SUPPORTED_PROJECT_SCHEMA_VERSIONS:
        raise UnsupportedProjectSchemaError(
            source,
            SUPPORTED_PROJECT_SCHEMA_VERSIONS,
            PROJECT_SCHEMA_VERSION,
        )
    path = _build_migration_path(source, target)
    current = _deep_copy(data)
    for _, step in path:
        current = step(current)
    return current


def migrate_project_dict(data):
    """Migrate * ``data* to the current schema version.

    This is a convenience wrapper around
    :func:`migrate_project_dict_to_version` that uses
    :data:`PROJECT_SCHEMA_VERSION` as the target. It is the function
    the project persistence layer calls before constructing a
    :class:`Project` from a deserialized dict.
    """
    return migrate_project_dict_to_version(data, PROJECT_SCHEMA_VERSION)


__all__ = (
    "PROJECT_SCHEMA_VERSION",
    "SUPPORTED_PROJECT_SCHEMA_VERSIONS",
    "UnsupportedProjectSchemaError",
    "migrate_project_dict",
    "migrate_project_dict_to_version",
)