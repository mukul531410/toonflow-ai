# Project Manifest & Batch Configuration Foundation

`TOONFLOW-PHASE-023` adds a deterministic, immutable JSON
*batch manifest* layer on top of the existing batch execution
surface. A manifest names a directory, a batch mode, and the
batch filter / report options that should be applied to a
single batch execution. The manifest layer is configuration and
orchestration only; it delegates execution to
`workflow.batch.run_batch` exactly once.

## What it adds

A new module `workflow.manifest` with the public API:

| Symbol | Purpose |
| --- | --- |
| `BATCH_MANIFEST_SCHEMA_VERSION` | The current manifest schema version (`1`). |
| `BatchManifest` | Frozen dataclass holding one batch configuration. |
| `ManifestInputError` | Structured error raised for invalid manifest-layer inputs. |
| `batch_manifest_to_dict` | Deterministic dict serialization. |
| `batch_manifest_from_dict` | Strict dict deserialization. |
| `batch_manifest_to_json` | Deterministic JSON serialization. |
| `batch_manifest_from_json` | Strict JSON deserialization. |
| `save_batch_manifest` | Write a manifest to disk. |
| `load_batch_manifest` | Read and validate a manifest from disk. |
| `run_batch_manifest` | Delegate one batch execution to the batch layer. |

The CLI gains a new subcommand:

```text
python -m workflow manifest <path>
```

## Architecture

```text
BatchManifest
      │
      ▼
workflow.manifest
      │
      ▼
workflow.batch.run_batch
      │
      ├── discover_projects
      ├── include / exclude filters
      ├── recursive discovery
      ├── validate / show / run
      └── optional report generation
```

The manifest layer contains configuration and orchestration
only. It must not duplicate:

- project discovery (owned by `workflow.batch.discover_projects`);
- include / exclude filtering (owned by `workflow.batch.run_batch`);
- recursive discovery (owned by `workflow.batch.run_batch`);
- project validation (owned by `workflow.load_project`);
- project loading (owned by `workflow.load_project`);
- schema migration (owned by `workflow.project_migrations`);
- project replay (owned by `workflow.replay_project`);
- report generation (owned by `workflow.report`);
- rendering logic (owned by `toonflow_ai.generation.*`);
- Blender logic (owned by `toonflow_ai.generation.*`);
- AI logic (owned by `ai.planner` and `ai.ollama_client`).

## Schema

The manifest schema has its own version, separate from the
project schema. The current manifest schema version is
`BATCH_MANIFEST_SCHEMA_VERSION = 1`. The supported set is
`(1,)`. Unsupported versions are rejected with
`ManifestInputError("schema_version", value)`.

The project schema version and the batch manifest schema
version evolve independently; this phase deliberately does
not share the project version's numbering.

## BatchManifest model

`BatchManifest` is a `@dataclass(frozen=True)` with the
following fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `directory` | `str` or `os.PathLike` | Directory containing project JSON files. |
| `mode` | `str` | One of `"validate"`, `"show"`, `"run"`. |
| `include` | `tuple[str, ...]` | Include glob patterns. Default `()`. |
| `exclude` | `tuple[str, ...]` | Exclude glob patterns. Default `()`. |
| `recursive` | `bool` | Walk subdirectories. Default `False`. |
| `report_path` | `str`, `os.PathLike`, or `None` | Optional report output path. |
| `schema_version` | `int` | Manifest schema version. Default `1`. |

The model is immutable. Collection fields are normalized to
tuples in `__post_init__`; the manifest never aliases a
caller-provided list. The directory and report path are
stored exactly as configured — the manifest layer never
resolves them against the current working directory.

## Validation

`BatchManifest.__post_init__` validates every field:

- `directory` — non-empty, non-whitespace, non-`bool`, non-numeric string-or-path-like.
- `mode` — exactly one of `validate`, `show`, `run`.
- `include` / `exclude` — `None`, a non-empty string, or a sequence of non-empty strings. `bool` and mixed types are rejected.
- `recursive` — real `bool`; `1`, `0`, `"true"`, `None` are rejected.
- `report_path` — `None` or a non-empty, non-whitespace path-like value.
- `schema_version` — integer in the supported set; `bool` is rejected.

Each violation raises `ManifestInputError(ValueError)` exposing
`parameter` and `value` attributes.

## Serialization

`batch_manifest_to_json` uses `indent=2`, `sort_keys=False`,
and `ensure_ascii=False`, and appends exactly one trailing
newline. The canonical top-level key order is:

```text
schema_version
directory
mode
include
exclude
recursive
report_path
```

The output never contains timestamps, UUIDs, environment
metadata, or machine-specific data. Repeated serialization of
the same `BatchManifest` produces byte-identical output.

Example:

```json
{
  "schema_version": 1,
  "directory": "./projects",
  "mode": "run",
  "include": [
    "production/*.json"
  ],
  "exclude": [
    "**/draft_*.json"
  ],
  "recursive": true,
  "report_path": "./artifacts/report.json"
}
```

## Deserialization

`batch_manifest_from_dict` strictly rejects:

- non-mapping input;
- missing required keys;
- unknown top-level keys;
- wrong field types;
- unsupported schema versions;
- non-integer or `bool` `schema_version`.

Malformed JSON continues to raise the standard
`json.JSONDecodeError` unchanged.

## Save and load

- `save_batch_manifest(manifest, path)` validates the
  manifest, validates the target path, creates parent
  directories when missing, writes UTF-8 JSON with exactly
  one trailing newline, overwrites any existing file
  deterministically, and returns the absolute resolved
  `pathlib.Path`.
- `load_batch_manifest(path)` validates the path, rejects
  directories, reads UTF-8, and delegates to
  `batch_manifest_from_json`.

## Execution delegation

`run_batch_manifest(manifest, *, run_batch=..., load_project=..., replay_project=..., stdout=..., report_writer=...)`:

1. validates the manifest is a `BatchManifest`;
2. resolves `stdout` to `sys.stdout` when `None`;
3. forwards `manifest.directory`, `manifest.mode`,
   `manifest.include`, `manifest.exclude`,
   `manifest.recursive`, and `manifest.report_path` to
   `run_batch` along with the injected hooks;
4. returns the integer exit code produced by the delegated
   call.

The manifest layer does not call `discover_projects`
directly, does not call `load_project` or `replay_project`
directly, and does not generate reports. All those
responsibilities remain below the manifest layer.

## Path portability policy

The manifest layer stores `directory` and `report_path`
exactly as configured. It does not resolve them against the
current working directory and does not rewrite them during
serialization. Actual path interpretation belongs to
`workflow.batch.run_batch` and the report layer. This keeps
manifest files portable across machines and CI runs.

## CLI usage

```text
# Validate a manifest file
python -m workflow manifest ./configs/nightly_batch.json

# The command prints the batch layer's stdout output to the
# CLI's stdout and returns the batch layer's exit code.
```

Manifest loading failures (missing file, malformed JSON,
malformed structure) are reported on `stdout` as
`error: <message>` and return exit code `1`. Invalid CLI
arguments continue to use the conventional argparse exit
code `2`. `--help` returns `0`.

The existing `validate`, `show`, `run`, and `batch`
subcommands are unchanged.

## Dependency injection

The CLI and the manifest layer support dependency injection
so that tests can exercise the full pipeline without Blender
or the network:

- `run_batch_manifest` accepts `run_batch`, `load_project`,
  `replay_project`, `stdout`, and `report_writer`.
- `cli_main` accepts the same hooks plus `load_batch_manifest`
  and `run_batch_manifest`.

When `load_project` or `replay_project` is omitted at the
`run_batch_manifest` boundary, a placeholder callable is
forwarded so the batch layer can still type-check its
arguments; the batch layer's defaults take effect for actual
execution.

## Error propagation

Delegated errors propagate unchanged unless the CLI process
boundary already has established error handling. The only
new manifest-specific validation error is
`ManifestInputError`.

## Idempotency

The manifest layer:

- does not modify project files;
- does not create or modify directories (except when
  `save_batch_manifest` explicitly creates parents of the
  requested path);
- does not mutate the manifest instance;
- does not mutate the caller's `include` / `exclude`
  sequences;
- does not create Blender objects;
- does not maintain mutable global state.

Saving the same manifest twice produces byte-identical file
content. Repeated `run_batch_manifest` calls with the same
manifest and injected dependencies result in equivalent
delegation.

## Testing strategy

`tests/test_batch_manifest.py` covers:

- public API and package exports;
- model validation (every field's success and failure
  modes, tuple normalization, frozen behavior);
- serialization (canonical key order, deterministic JSON,
  trailing newline, non-ASCII preservation, no timestamps);
- deserialization (every rejection path, malformed JSON
  propagation);
- file persistence (parent creation, absolute path,
  overwrite, round-trip, directory-path rejection, missing
  file);
- execution delegation (every forwarded argument, return
  code preservation, error propagation, exactly-once
  delegation, no manifest mutation);
- CLI integration (success, delegated failure, missing
  file, invalid JSON, invalid structure, `--help`, missing
  path, deterministic output, DI forwarding, existing
  commands unchanged);
- idempotency (byte-identical save, equivalent delegation,
  no side-effect directory creation);
- architecture (no forbidden imports, no Blender
  references, no direct `discover_projects` call, no
  `load_project` / `replay_project` import, no threading or
  asyncio, no network, no `print` / `input`, no env
  variable or YAML access, exactly one
  `run_batch_manifest` definition).

## Known limitations

- The manifest is loaded and executed once per CLI
  invocation. Multi-manifest execution is intentionally not
  supported.
- The manifest does not support YAML, TOML, or environment
  variable substitution.
- The manifest does not include a CLI flag override; all
  configuration flows through the JSON document. A future
  phase may add CLI overrides if needed.

## Explicit non-features

This phase does NOT introduce:

- YAML or TOML manifests;
- environment-variable substitution or `.env` files;
- variable interpolation;
- multiple manifests in one invocation;
- manifest inheritance, includes, or imports;
- plugin systems or hooks;
- databases;
- project schema changes;
- parallel execution, threading, multiprocessing, or
  asyncio;
- retries, queues, or progress bars;
- terminal colors or file watching;
- network access;
- Blender manipulation or AI planning.

## Ownership boundaries

| Concern | Owner |
| --- | --- |
| Manifest schema, model, validation, JSON, save / load | `workflow.manifest` |
| Delegation of execution | `workflow.manifest.run_batch_manifest` |
| Project discovery, filtering, recursive walk | `workflow.batch` |
| Project validation, loading, schema migration, replay | `workflow.project`, `workflow.project_migrations` |
| Report generation | `workflow.report` |
| Rendering, Blender, AI | `toonflow_ai.generation.*`, `ai.*` |
