# Project Schema Versioning & Migration Foundation

`TOONFLOW-PHASE-018` — a pure-Python, dependency-free migration layer on
top of the persistent project model introduced in
`TOONFLOW-PHASE-017`.

This document describes the on-disk project schema, the supported schema
versions, the migration policy, the public migration API, and the
guarantees the migration layer provides. It is the canonical reference
for any future schema change.

---

## 1. Purpose

`workflow.project` (PHASE-017) defines a deterministic in-memory
project model and JSON file persistence. The migration layer adds a
versioned schema and an explicit, testable path from older project
documents to the current one. With it:

- `project_from_dict` and `load_project` transparently migrate older
  documents to the current schema version before constructing a
  `Project`.
- The schema version is stored in the JSON document itself
  (``schema_version``) and is validated on load.
- Unsupported versions are rejected with a structured
  `UnsupportedProjectSchemaError` carrying the provided version, the
  supported versions, and the current version.
- Future schema changes (e.g. PHASE-019) are added by writing a new
  step in the migration registry and bumping
  `PROJECT_SCHEMA_VERSION` — no caller code changes are required.

---

## 2. Supported schema versions

The migration layer owns a single ordered tuple of supported schema
versions and a single integer for the canonical current version:

```python
from workflow.project_migrations import (
    PROJECT_SCHEMA_VERSION,           # 2
    SUPPORTED_PROJECT_SCHEMA_VERSIONS,  # (1, 2)
)
```

| Version | Origin | Description |
| --- | --- | --- |
| **1** | PHASE-017 | Original deterministic project format. Top-level keys: `schema_version`, `name`, `shots`. |
| **2** | PHASE-018 | Adds an optional top-level `description` field (defaults to `""`). All other fields unchanged. |

The current version (`PROJECT_SCHEMA_VERSION = 2`) is part of
`SUPPORTED_PROJECT_SCHEMA_VERSIONS`. The tuple is strictly ascending
and free of duplicates.

---

## 3. The v1 -> v2 migration

The only registered migration step is `_migrate_v1_to_v2` (in
`workflow.project_migrations`). It:

1. Performs a deterministic deep copy of the input dict (via a JSON
   round-trip with `ensure_ascii=False`), so the input is never
   mutated and the output is fully independent.
2. Sets `schema_version` to `2`.
3. Adds a top-level `description` key with the value `""` if and only
   if the key is missing. If the input already carries a
   `description` (e.g. a partially migrated document), the existing
   value is preserved.

No other fields change in v1 -> v2. Shot shape, field names, and
ordering are identical to PHASE-017.

---

## 4. Public API

The migration layer exposes a small, stable surface. Everything else
in `workflow.project_migrations` is an implementation detail.

```python
from workflow.project_migrations import (
    PROJECT_SCHEMA_VERSION,
    SUPPORTED_PROJECT_SCHEMA_VERSIONS,
    UnsupportedProjectSchemaError,
    migrate_project_dict,
    migrate_project_dict_to_version,
)
```

### `migrate_project_dict(data) -> dict`

Migrate *data* to the current schema version. The input is not
mutated; the returned dict is fully independent. Equivalent to
`migrate_project_dict_to_version(data, PROJECT_SCHEMA_VERSION)`.

This is the function `project_from_dict` calls before constructing the
in-memory `Project`.

### `migrate_project_dict_to_version(data, target_version) -> dict`

Migrate *data* to *target_version*. Raises:

- `TypeError` when *data* is not a dict or *target_version* is not a
  positive, non-bool `int`.
- `UnsupportedProjectSchemaError` (`ValueError` subclass) when the
  source version, the target version, or any intermediate version is
  not in `SUPPORTED_PROJECT_SCHEMA_VERSIONS`, or when no migration
  path exists between them.

Reverse migrations (target < source) are not supported. Skipping
intermediate versions is not supported. Migrations always run
step-by-step in ascending version order.

### `UnsupportedProjectSchemaError`

```python
class UnsupportedProjectSchemaError(ValueError):
    provided_version     # the offending version, preserved as-given
    supported_versions   # tuple of supported integers
    current_version      # the canonical current version (int)
```

The error message includes the provided version, the supported
versions, and the current version. `project_from_dict` catches this
error and re-raises it as `ProjectInputError("project.schema_version",
provided_version)` for backward compatibility with PHASE-017 callers.

### `PROJECT_SCHEMA_VERSION` and `SUPPORTED_PROJECT_SCHEMA_VERSIONS`

The canonical current schema version and the ordered tuple of
supported versions. Both are module-level constants.

---

## 5. Integration with `project_from_dict`

`workflow.project.project_from_dict` calls `migrate_project_dict` as
its very first step. The error mapping is:

| Migration-layer exception | `ProjectInputError` parameter |
| --- | --- |
| `TypeError` (data is not a dict, or `schema_version` is not a positive non-bool int) | `"project"` |
| `UnsupportedProjectSchemaError` (unsupported source, unsupported target, missing path, reverse migration, missing field) | `"project.schema_version"` |
| other `ValueError` from the migration layer (e.g. negative or zero `schema_version`) | `"project.schema_version"` |

`Project.schema_version` is also validated by the dataclass
`__post_init__`; valid values are exactly the integers in
`SUPPORTED_PROJECT_SCHEMA_VERSIONS` (currently `(1, 2)`), and the
field is rejected for non-int, `bool`, `None`, or out-of-range values.

After migration, the deserialized dict at the current schema is
validated for unknown top-level keys (the allowed set is
`{"schema_version", "name", "description", "shots"}`).

---

## 6. Migration policy — guarantees

- **Deterministic.** A given input always produces the same output
  for the same target version. No timestamps, no environment lookups,
  no randomness.
- **Pure.** Inputs are never mutated. Every migration returns a
  brand-new, fully independent dict.
- **Minimal.** Each migration step does the smallest possible
  structural change needed to advance the schema by one version.
- **Step-by-step.** Intermediate versions are never skipped.
  `_build_migration_path` walks the registry one step at a time.
- **Unicode-safe.** `_deep_copy` round-trips through JSON with
  `ensure_ascii=False`, so non-ASCII strings, emojis, and locale text
  survive verbatim with key order preserved.
- **Reverse-migration unsupported.** A document at version N cannot
  be migrated to a version M < N. The migration registry is
  one-directional.
- **No file I/O.** The migration layer never opens files. File
  persistence is owned by `workflow.project`.
- **No `bpy`, no AI, no networking, no audio.** The module imports
  only the Python standard library (`typing`, `json`).

---

## 7. Adding a new schema version

A future phase that introduces schema v3 would:

1. Bump `PROJECT_SCHEMA_VERSION` to `3` in
   `workflow.project_migrations`.
2. Add `3` to `SUPPORTED_PROJECT_SCHEMA_VERSIONS`.
3. Write a `_migrate_v2_to_v3(data) -> dict` function that returns a
   new dict at version 3.
4. Add `(2, _migrate_v2_to_v3)` to `_MIGRATION_STEPS` (the registry
   must remain strictly ascending by source version).
5. Update `Project` and `_PROJECT_TOP_LEVEL_KEYS` in
   `workflow.project` to accept the new fields.
6. Add tests to `tests/test_project_migrations.py` covering the new
   step, the new combined path, and the new error cases.

`project_from_dict` and `load_project` automatically pick up the new
migration — no caller code changes are required.

---

## 8. Non-features (intentionally out of scope)

- **Schema introspection.** The module does not parse the JSON file
  itself; that is the job of `project_from_json`.
- **Schema downgrade.** A document at v2 cannot be migrated to v1.
  Downgrades would silently lose data and are explicitly forbidden.
- **Automatic schema repair.** Missing required fields are not
  auto-filled by the migration layer. The migration layer only
  handles version-specific structural changes; field-level validation
  remains the responsibility of `Project` and `Shot`.
- **Custom migration hooks.** There is no plugin or callback
  registry. All migrations are written as plain Python functions in
  the migration module.
- **File format migration.** The migration layer operates on
  in-memory dicts only. The on-disk JSON format is owned by
  `workflow.project`.

---

## 9. Testing

The migration layer is exercised by `tests/test_project_migrations.py`
(81 tests). Coverage includes:

- Constants and their invariants.
- `UnsupportedProjectSchemaError` attribute round-trip, message
  content, and `ValueError` inheritance.
- `_validate_schema_version_value` for every accepted and rejected
  input class.
- `_build_migration_path` for identity, single-step, multi-step,
  unknown-source, unknown-target, and reverse-migration cases.
- `migrate_project_dict_to_version` for v1 -> v2, v2 -> v2
  (passthrough deep-copy), non-dict input, missing
  `schema_version`, unsupported source/target, reverse migration,
  non-int target, and zero/negative target.
- `migrate_project_dict` for default-target, v1 -> current, v2 ->
  current, input non-mutation, and error propagation.
- `_migrate_v1_to_v2` for description defaulting, description
  preservation, and input non-mutation.
- `_deep_copy` for non-ASCII, emoji, unicode key order, falsy
  values, and nested independence.
- Integration with `project_from_dict` for v1 round-trip, v2
  round-trip, caller-dict non-mutation, unsupported-version
  rejection, and full v1 -> v2 -> Project -> v2 round-trip.
- Architecture guard rails: no `bpy`, no AI / Ollama / HTTP, no
  audio, no pipeline / generation imports, no `print` / `input` /
  `open` calls, and minimal top-level imports.

The full test suite (`python -m unittest discover -s tests`) runs
539 tests and passes.
