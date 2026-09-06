# TOONFLOW-PHASE-017 — Persistent Project Model & Deterministic Replay

## Purpose

This phase adds a **pure-Python, `bpy`-free persistent project
definition layer** on top of the existing
[Multi-Shot Workflow Foundation](MULTI_SHOT_WORKFLOW_FOUNDATION.md)
API. The project layer can:

- represent a multi-shot TOONFLOW project as a single immutable
  `Project` value;
- serialize a project deterministically to plain Python data or
  JSON;
- deserialize a project strictly and safely;
- save a project to a JSON file on disk and load it back;
- replay a project through the existing
  `workflow.create_and_render_shots` orchestrator.

The project layer contains **no business logic of its own**. It does
not import `bpy`, does not call AI or Ollama, does not make HTTP
calls, does not perform Scene Plan validation, does not manipulate
the Asset Registry, does not create or delete Blender objects, and
does not resolve output paths. Every such responsibility remains
owned by the existing single-shot, multi-shot, generation,
animation, lip-sync, camera, and rendering layers.

## Architecture

```
Persistent project layer  (this phase, bpy-free)
    |
    v
workflow.create_and_render_shots  (PHASE-016)
    |
    v
workflow.create_and_render_scene  (PHASE-015)
    |
    v
existing TOONFLOW pipeline
    (AI planning -> scene generation ->
     optional animation -> optional lip sync ->
     camera -> render)
```

The project layer sits one level above the multi-shot workflow. It
does not know about `bpy`, AI, Ollama, HTTP, the Asset Registry, the
Scene Plan, or any generation API. It only knows about the
`workflow.create_and_render_shots` contract and the `Shot` and
`Project` models.

## Public API

```python
from workflow import (
    Project,
    ProjectInputError,
    project_to_dict,
    project_from_dict,
    project_to_json,
    project_from_json,
    save_project,
    load_project,
    replay_project,
)
```

Example end-to-end usage:

```python
from workflow import (
    Project,
    Shot,
    save_project,
    load_project,
    replay_project,
)

project = Project(
    name="demo_project",
    shots=(
        Shot(concept="A husband waves"),
        Shot(
            concept="A wife smiles",
            animation="wave",
        ),
    ),
)

save_project(project, "demo_project.json")

loaded = load_project("demo_project.json")

result = replay_project(loaded)
```

`replay_project` accepts an optional `workflow_callable` injection
hook that is forwarded to
`workflow.create_and_render_shots(workflow_callable=...)`. The
default delegates to the existing multi-shot workflow, which in turn
uses the existing single-shot workflow.

## Project model

```python
@dataclass(frozen=True)
class Project:
    name: str
    shots: Tuple[Shot, ...]
    schema_version: int = PROJECT_SCHEMA_VERSION
```

| Field | Type | Default | Meaning |
| ----- | ---- | ------- | ------- |
| `name` | `str` | (required) | Non-empty project name. |
| `shots` | `tuple[Shot, ...]` | (required) | Non-empty tuple of shots in execution order. |
| `schema_version` | `int` | `1` | On-disk schema version. |

Validation rules:

- `name` must be a non-empty string; whitespace-only names are
  rejected; `bool` and non-strings are rejected.
- `shots` must be a non-empty sequence of `Shot` instances.
- `schema_version` must be a non-`bool` `int` in the set of
  supported versions.
- `Project` is a frozen dataclass; mutation after construction is
  rejected.
- The `shots` field is normalized to a tuple on construction.

The only project-layer error is `ProjectInputError(parameter,
value)`, a `ValueError` subclass that carries the offending
parameter name and value.

## Serialization format

`project_to_dict(project)` returns a JSON-compatible dict with a
fixed canonical structure:

```python
{
    "schema_version": 1,
    "name": "demo_project",
    "shots": [
        {
            "concept": "A husband waves",
            "animation": None,
            "animation_start_frame": 1,
            "lip_sync": False,
            "lip_sync_start_frame": 1,
            "output_path": None,
        },
        ...
    ],
}
```

The top-level key order is fixed: `schema_version`, `name`, `shots`.
Each shot dict uses the canonical `Shot` field names in the
documented order. No additional metadata, no timestamps, no random
IDs, no environment-specific data.

## Deterministic JSON

`project_to_json(project)` returns a deterministic UTF-8 JSON string
with the following properties:

- `indent=2` for stable indentation;
- `sort_keys=False` because the dicts are already constructed in
  the canonical order described above;
- `ensure_ascii=False` so non-ASCII characters survive verbatim
  (the project can still be round-tripped through
  `project_from_json`);
- a single trailing newline at the end of the document;
- no timestamps, no random values, no environment data.

Repeated serialization of the same `Project` produces
**byte-identical** output.

## Save / load behavior

```python
save_project(project, "demo_project.json")
loaded = load_project("demo_project.json")
```

- `save_project` accepts a `Project` and a non-empty `str` or
  `os.PathLike`. It validates the path, creates parent directories
  as needed, writes UTF-8 JSON with a trailing newline, and returns
  the absolute `pathlib.Path` of the written file.
- `load_project` accepts a non-empty `str` or `os.PathLike`,
  rejects directory paths, reads UTF-8 JSON, and reconstructs a
  `Project` through `project_from_json`.
- Both functions raise `ProjectInputError` for invalid paths and
  propagate `json.JSONDecodeError` for malformed JSON files.

## Deserialization

`project_from_dict(data)` and `project_from_json(text)` strictly
reject:

- non-mapping top-level data;
- missing `schema_version`, `name`, or `shots` keys;
- empty `shots`;
- invalid `name` (empty, whitespace-only, non-string, `bool`);
- invalid `schema_version` (non-`int`, `bool`, unsupported value);
- malformed shot entries (non-dict, missing fields, unknown fields);
- unknown top-level keys.

The project layer does not silently coerce or ignore invalid
values.

## Replay behavior

`replay_project(project, *, workflow_callable=None)` delegates to
`workflow.create_and_render_shots(project.shots, workflow_callable=workflow_callable)`.

- Execution order is preserved.
- Project shots are forwarded unchanged.
- Delegated errors propagate unchanged.
- The project layer does not mutate the `Project` and does not add
  project-layer mutable state.
- The optional `workflow_callable` injection hook makes replay
  testable without Blender or Ollama.

## Dependency injection

The project layer exposes a single dependency-injection point:
`replay_project(..., workflow_callable=...)`. The default delegates
to `workflow.create_and_render_shots`. All other functions
(`project_to_dict`, `project_to_json`, `save_project`,
`project_from_dict`, `project_from_json`, `load_project`) are
pure-Python and require no injection.

## Error behavior

The project layer adds exactly one new error class:
`ProjectInputError(parameter, value)`, a `ValueError` subclass.

| Input | Raised |
| ----- | ------ |
| Invalid project name | `ProjectInputError("name", value)` |
| Empty / non-Shot shots | `ProjectInputError("shots", value)` |
| Invalid schema version | `ProjectInputError("schema_version", value)` |
| Invalid path | `ProjectInputError("path", value)` |
| Invalid top-level dict | `ProjectInputError("project", value)` |
| Missing top-level field | `ProjectInputError("project.<field>", value)` |
| Unknown top-level key | `ProjectInputError("project.unknown", tuple(keys))` |
| Missing shot field | `ProjectInputError("shot.missing[<field>]", data)` |
| Unknown shot field | `ProjectInputError("shot.unknown", tuple(keys))` |

All other errors (workflow errors, rendering errors, AI errors,
etc.) propagate unchanged from the delegated layers.

## Ownership and dependency boundaries

The project module is AST-verifiably free of:

- `bpy` imports and `bpy.data` / `bpy.ops` references;
- `keyframe_insert` and `from_pydata` calls;
- AI / Ollama / HTTP / urllib / requests / audio imports;
- `toonflow_ai.generation`, `pipeline`, `asset_registry`, and
  `scene_plan` imports;
- `print(` and `input(` calls.

The only `open(` calls are inside `save_project` and `load_project`
(file persistence) — there are at most two.

The project layer does not create cameras, create objects, render
directly, invoke AI directly, invoke scene generation directly, or
maintain mutable global state.

## Idempotency

The project layer is idempotent:

- `save_project(project, path)` overwrites the same file with
  byte-identical content for the same `project`.
- `load_project(path)` returns equal `Project` values for the same
  file.
- `replay_project(project)` does not mutate the `Project` and does
  not add project-layer mutable state.
- Repeated replay produces equivalent delegation to the
  multi-shot workflow.

The project layer does not add any cleanup or mutation behavior.
Lower-level idempotency guarantees (scene generation, animation,
lip-sync, camera, rendering) are owned by the existing TOONFLOW
modules.

## Testing strategy

Tests live in `tests/test_project_persistence.py` and cover:

- **Public API exposure** — all new symbols are exported; existing
  public APIs from PHASE-015/016 remain available; `Project` is
  frozen; `ProjectInputError` is a `ValueError` subclass.
- **Project model** — valid creation, default and explicit
  `schema_version`, tuple normalization, invalid name, empty
  shots, non-Shot elements, invalid `schema_version`.
- **Serialization** — `project_to_dict` structure, JSON-compatibility,
  deterministic repeated serialization, stable key ordering,
  non-ASCII round-trip, no timestamps or random data.
- **Deserialization** — valid round-trip (dict and JSON), rejection
  of non-mapping, missing fields, empty shots, invalid name,
  invalid `schema_version`, unknown top-level keys, malformed
  shots, unknown shot fields, malformed JSON, empty/non-string
  JSON input.
- **File persistence** — `tempfile`-backed round-trip, parent
  directory creation, PathLike support, invalid path rejection,
  invalid `Project` rejection, directory path rejection, repeated
  save determinism, repeated load equivalence, malformed JSON file
  rejection.
- **Replay** — shots forwarded in order, delegated errors propagate
  unchanged, no project mutation, repeated equivalent delegation,
  default delegation through `create_and_render_shots`, non-
  `Project` input rejection.
- **Architecture** — AST-based proof that the project module is
  `bpy`-free, has no `bpy.data` / `bpy.ops`, no
  `keyframe_insert`, no `from_pydata`, no AI / Ollama / HTTP /
  urllib / audio / `toonflow_ai.generation` / `pipeline` /
  `asset_registry` / `scene_plan` imports, no `print(` / `input(`,
  that the replay helper routes through `create_and_render_shots`,
  and that the top-level imports are limited to the standard
  library plus the local relative `.shots` import.

All tests run without Blender, without `bpy`, without Ollama, and
without a real render engine.

## Known limitations

- The project layer uses a fixed `schema_version = 1`. Future
  versions may extend the schema; the version gate is already in
  place.
- Only JSON is supported. There is no YAML, no SQLite, no cloud
  storage.
- The project layer does not implement a job history, persistent
  project storage beyond the JSON file, or concurrent project
  editing.
- The project layer does not implement retries, async, or threading.

## Explicit non-features

This phase does NOT implement:

- Blender persistence or `.blend` file manipulation;
- databases (SQLite, etc.);
- cloud storage;
- YAML;
- project UI;
- Blender operators;
- job history;
- timestamps or UUIDs;
- async, threading, queues, or retries;
- video rendering or FFmpeg;
- AI planning;
- camera orchestration or cross-shot camera switching;
- new animation or lip-sync logic;
- Scene Plan schema changes.
