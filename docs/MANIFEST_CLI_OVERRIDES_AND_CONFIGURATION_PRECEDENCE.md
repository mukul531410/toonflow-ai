# Manifest CLI Overrides & Configuration Precedence Foundation

`TOONFLOW-PHASE-024` extends the `manifest` subcommand with
optional CLI flags that override selected fields of the loaded
`BatchManifest` without modifying the manifest file.

## Why CLI overrides exist

A manifest captures the *default* configuration for a batch
run. Different environments (CI vs. local, nightly vs. release)
often need to vary one or two fields without rewriting the
manifest. CLI overrides provide a deterministic, explicit
override mechanism that:

- leaves the manifest file byte-for-byte unchanged;
- leaves the loaded manifest instance unchanged (a new
  immutable `BatchManifest` is produced);
- composes with PHASE-023 and earlier phases without
  duplicating any batch, project, schema, report, rendering,
  AI, or Blender logic.

## Precedence

For every overridable field:

```text
CLI override
    ↓
manifest value
    ↓
BatchManifest model default
```

`None` for any CLI override means "no override supplied". The
override layer uses **identity** (`is None`) rather than
truthiness to detect the absence of an override so that
`--no-recursive` is honored as a real override.

## Supported override fields

| Field | Override flag | Notes |
| --- | --- | --- |
| `directory` | `--directory <path>` | Replaces the manifest's batch directory. The positional `<manifest-path>` still identifies the manifest file. |
| `mode` | `--mode {validate,show,run}` | Replaces the manifest's mode. |
| `include` | `--include <pattern>` (repeatable) | Complete replacement, not merge. |
| `exclude` | `--exclude <pattern>` (repeatable) | Complete replacement, not merge. |
| `recursive` | `--recursive` / `--no-recursive` | Tri-state: `None`, `True`, `False`. |
| `report_path` | `--report <path>` | Replaces the manifest's report path. |

`schema_version` is **not** overridable from the CLI. The
manifest schema version is part of the file's contract.

## Tri-state recursive behavior

The `--recursive` flag uses a tri-state representation:

| CLI input | Effective value | Stored on `manifest.recursive` |
| --- | --- | --- |
| (no flag) | `None` | unchanged |
| `--recursive` | `True` | replaced with `True` |
| `--no-recursive` | `False` | replaced with `False` |

The override layer uses `is None` to detect absence; it does
**not** use truthiness. This guarantees that an explicit
`--no-recursive` correctly overrides a manifest `True`.

## Include / exclude replacement behavior

CLI include / exclude values are **complete replacements** for
the manifest's include / exclude configuration. They are
**not** merged with the manifest's values.

Example:

```text
manifest.include = ("production/*.json", "release/*.json")
CLI:             --include "staging/*.json"
Result:          include = ("staging/*.json",)
```

Multiple CLI values preserve their CLI order:

```text
CLI:             --include a --include b --include c
Result:          include = ("a", "b", "c")
```

Empty override values are rejected as ambiguous with "no
override supplied".

## Directory override

The positional `<manifest-path>` is the manifest file. The
optional `--directory` overrides the *batch* directory inside
the manifest. The two paths must not be confused:

```text
python -m workflow manifest configs/nightly.json \
    --directory projects/production
```

loads `configs/nightly.json` and executes the batch against
`projects/production`. The manifest JSON file is never
modified.

## Mode override

Allowed values remain exactly `validate`, `show`, and `run`.
Invalid values are rejected by argparse with exit code `2`
before the manifest is even loaded.

## Report override

`--report <path>` replaces the manifest's `report_path`. When
the override is supplied, the existing no-report behavior
(when neither the manifest nor the CLI supplies a path)
remains unchanged.

## Manifest immutability

```python
original = BatchManifest(...)
overridden = apply_manifest_overrides(original, mode="validate")

assert overridden is not original
assert original.mode == "run"
assert overridden.mode == "validate"
```

`apply_manifest_overrides` always returns a new
`BatchManifest`. The original instance is never mutated, and
the override layer never aliases caller-provided lists.

## Manifest file preservation

Running:

```text
python -m workflow manifest project.json --mode validate
```

must not rewrite `project.json`. The manifest file is
byte-for-byte identical before and after execution. The
override layer never calls `save_batch_manifest`; the CLI
never writes to the manifest path. A dedicated test reads
the file before and after execution and asserts equality.

## Execution flow

```text
CLI
  |
  v
load_batch_manifest()
  |
  v
apply_manifest_overrides()
  |
  v
run_batch_manifest()
  |
  v
workflow.batch.run_batch()
  |
  v
existing batch execution
```

The CLI:

1. parses the manifest path and the optional override flags;
2. loads the manifest (errors → exit code `1`);
3. applies the overrides via `apply_manifest_overrides`
   (validation errors → exit code `1`);
4. delegates to `run_batch_manifest` with the **effective**
   manifest (the batch layer never sees the raw manifest);
5. returns the batch layer's exit code.

The CLI does **not** call `discover_projects`, `load_project`,
`replay_project`, or `save_batch_manifest` directly. All
those responsibilities remain in the existing layers.

## Dependency injection

The CLI and the override layer support dependency injection
so that tests can exercise the full pipeline without Blender
or the network:

- `cli_main` accepts `apply_manifest_overrides` in addition to
  the PHASE-023 hooks (`load_batch_manifest`,
  `run_batch_manifest`, `run_batch`, `load_project`,
  `replay_project`, `stdout`).
- `apply_manifest_overrides` itself is a pure function with
  no injected dependencies.

## Validation

The override layer reuses the existing `BatchManifest`
validators. There are no duplicate validation rules. When an
override is invalid, `ManifestInputError(ValueError)` is
raised with `parameter` and `value` attributes, and the
original manifest is unchanged.

Invalid CLI flags (for example `--mode render`) are rejected
by argparse with exit code `2` before the manifest is loaded.

## Error behavior

- Manifest loading failure → `error:` line on `stdout`,
  exit code `1`.
- Override validation failure → `error:` line on `stdout`,
  exit code `1`. The original manifest instance is unchanged.
- Batch layer failure → the batch layer's exit code.
- `--help` → exit code `0`.
- Missing manifest path or invalid CLI flags → exit code `2`.

The override layer does not introduce new error classes.

## Determinism

Repeated calls to `apply_manifest_overrides` with the same
manifest and the same override values produce equal
`BatchManifest` instances. Serialization of the effective
manifest is byte-identical to repeated serialization of any
other `BatchManifest` produced by the same inputs. No
timestamps, UUIDs, environment data, or random values are
introduced.

## Examples

Validate a manifest without changing its file:

```text
python -m workflow manifest configs/nightly.json --mode validate
```

Override the mode and the report path:

```text
python -m workflow manifest configs/nightly.json \
    --mode run \
    --report artifacts/manual.json
```

Replace the include / exclude patterns and force recursion
on:

```text
python -m workflow manifest configs/nightly.json \
    --include "release/*.json" \
    --exclude "**/draft_*.json" \
    --recursive
```

Disable recursion that the manifest enabled:

```text
python -m workflow manifest configs/nightly.json --no-recursive
```

Override every supported field:

```text
python -m workflow manifest configs/nightly.json \
    --directory projects/production \
    --mode run \
    --include "release/*.json" \
    --exclude "**/draft_*.json" \
    --recursive \
    --report artifacts/release-report.json
```

## Testing strategy

`tests/test_manifest_overrides.py` covers:

- override model: every field, including `recursive=True`
  and `recursive=False`;
- precedence: manifest value preserved when no override;
  CLI value wins; explicit `False` wins over manifest
  `True`; explicit `True` wins over manifest `False`;
- include / exclude: complete replacement (not merge),
  order preservation across repeated flags, empty
  override rejection;
- validation: every invalid override (directory, mode,
  include, exclude, recursive, report path, wrong type);
- immutability: original manifest unchanged, new manifest
  is a different frozen object, input lists not aliased;
- serialization: deterministic, canonical key order, no
  timestamps;
- CLI integration: every override flag, combinations,
  manifest file byte-for-byte unchanged after run, invalid
  mode → exit code `2`, invalid include → exit code `1`,
  manifest loading failure → exit code `1`;
- execution delegation: effective values reach
  `run_batch`; exactly one delegation; return code
  preserved; DI hook for `apply_manifest_overrides`;
- existing behavior: `validate`, `show`, `run`, `batch`,
  and the unflagged `manifest` subcommand remain
  compatible; PHASE-023 public API remains available;
- architecture: AST-based guard rails verifying
  `workflow.manifest.py` and `workflow/cli.py` are free of
  `bpy`, `ollama`, `urllib`, `requests`, `pipeline`,
  `asset_registry`, `scene_plan`, `toonflow_ai`, `audio`,
  `print`, `input`, threading, asyncio, multiprocessing,
  network calls, env variables, and YAML.

## Known limitations

- CLI overrides are evaluated once per invocation; there is
  no interactive override UI.
- The override layer does not support multiple manifests in
  one invocation; each invocation loads one manifest.
- The override layer does not implement configuration
  profiles, manifest inheritance, or include / import
  mechanisms.

## Explicit non-features

This phase does NOT introduce:

- YAML, TOML, env-var substitution, `.env`;
- variable interpolation;
- manifest inheritance, includes, or imports;
- multiple manifest execution;
- configuration profiles;
- plugin systems or hooks;
- databases;
- project schema changes;
- parallel execution, threading, multiprocessing, asyncio;
- retries, queues, progress bars, terminal colors;
- network access;
- Blender UI or Blender manipulation;
- AI changes;
- Scene Plan changes.

## Ownership boundaries

| Concern | Owner |
| --- | --- |
| Override precedence rules | `workflow.manifest.apply_manifest_overrides` |
| CLI override flag parsing | `workflow.cli` |
| Manifest loading and validation | `workflow.manifest.load_batch_manifest` |
| Batch execution delegation | `workflow.manifest.run_batch_manifest` |
| Project discovery, filtering, recursive walk | `workflow.batch` |
| Project validation, loading, schema migration, replay | `workflow.project`, `workflow.project_migrations` |
| Report generation | `workflow.report` |
| Rendering, Blender, AI | `toonflow_ai.generation.*`, `ai.*` |
