# Batch Dry-Run Mode

`TOONFLOW-PHASE-025` adds a deterministic, side-effect-free
preview of a batch execution. The dry-run layer reuses the
existing `workflow.batch.discover_projects` selection
semantics so the preview is exactly what a real execution
would attempt.

## What it adds

| Symbol | Purpose |
| --- | --- |
| `workflow.batch.BatchDryRunResult` | Frozen, immutable preview result. |
| `workflow.batch.dry_run_batch` | Pure preview function. |
| `workflow.batch.run_batch(..., dry_run=False)` | Existing entry point gains a dry-run keyword. |
| `workflow.manifest.dry_run_batch_manifest` | Manifest-driven preview. |
| `workflow.manifest.run_batch_manifest(..., dry_run=False)` | Existing manifest entry point gains a dry-run keyword. |
| `python -m workflow batch ... --dry-run` | CLI dry-run flag. |
| `python -m workflow manifest ... --dry-run` | CLI dry-run flag. |

## Dry-run semantics

A dry-run is a successful preview of the selection. It:

- validates `mode`, `recursive`, `include`, and `exclude`
  using the existing `BatchInputError` rules;
- runs the same `discover_projects` walk a real execution
  would run;
- returns an immutable `BatchDryRunResult` describing the
  selection;
- never calls `load_project` or `replay_project`;
- never invokes rendering, AI, Ollama, or any Blender code;
- never mutates project files;
- never writes a report;
- never mutates the manifest file (for manifest dry-run);
- never mutates the manifest instance.

## Normal batch vs dry-run

| Aspect | `run_batch` | `dry_run_batch` / `run_batch(dry_run=True)` |
| --- | --- | --- |
| Discovery | yes | yes (same call) |
| Filtering | yes | yes (same call) |
| Project loading | yes | **no** |
| Project replay | yes (run mode) | **no** |
| Rendering | yes (run mode) | **no** |
| AI / Ollama | yes (run mode) | **no** |
| Report writing | optional | **never** |
| Mutates files | yes (run mode) | **never** |
| Returns | `int` exit code | `int` (`0` always when `dry_run=True`) for `run_batch`; `BatchDryRunResult` for `dry_run_batch` |

## Discovery / filter parity

The dry-run path uses the same `discover_projects` selection
function as the real execution path. For any identical
configuration:

```text
dry_run selection  ==  real execution selection
```

The test `ParityTests.test_dry_run_matches_real_execution_selection`
verifies this end-to-end: it captures every path a real
`run_batch` would have loaded and asserts it equals the
`BatchDryRunResult.projects` tuple.

## Manifest interaction

`workflow.manifest.dry_run_batch_manifest(manifest)` returns
a `BatchDryRunResult` derived from the manifest's already
resolved configuration. The manifest instance is never
mutated; the manifest file on disk is never modified.

For CLI usage:

```text
python -m workflow manifest configs/nightly.json --dry-run
```

The CLI applies the PHASE-024 overrides first, then calls
`dry_run_batch_manifest` with the effective manifest. The
manifest file is never modified by the override layer or by
the dry-run layer.

Dry-run does **not** participate in the PHASE-024
configuration precedence. The `BatchManifest` schema is
intentionally not extended with a `dry_run` field. `--dry-run`
is an execution-time concern only.

## CLI usage

```text
python -m workflow batch ./projects validate --dry-run
python -m workflow batch ./projects run --recursive --include "*.json" --dry-run
python -m workflow manifest configs/nightly.json --dry-run
python -m workflow manifest configs/nightly.json \
    --mode validate \
    --include "release/*.json" \
    --no-recursive \
    --dry-run
```

The CLI prints a deterministic, machine-friendly summary:

```text
Dry-run:
  Mode: validate
  Recursive: False
  Include: ['a.json']
  Exclude: []
  Projects: 1
  - C:\path\to\a.json
```

The trailing newline is exactly one.

## `--dry-run` is execution-time only

The flag:

- is not stored in `BatchManifest`;
- is not serialized into a manifest JSON file;
- is not part of `BATCH_MANIFEST_SCHEMA_VERSION`;
- does not participate in PHASE-024 precedence.

The dry-run decision lives on the entry-point call and on
the CLI flag.

## Exit codes

| Condition | Exit code |
| --- | --- |
| Successful dry-run (including empty selection) | `0` |
| Invalid mode / recursive / include / exclude | `2` |
| Invalid CLI argument | `2` |
| Manifest load failure with `--dry-run` | `1` |
| Manifest override validation failure with `--dry-run` | `1` |

Dry-run never returns failure merely because the selected
project list is empty. Empty selection in dry-run is a
successful preview (exit code `0`, `Projects: 0`).

## Report behavior

`--report PATH` is supported on the `batch` subcommand.
When `--dry-run` is supplied:

- no report is written;
- the report file is not even created;
- no `BatchReport` is constructed;
- `report_writer` (the PHASE-021 injection point) is never
  invoked.

This avoids fabricating an execution report that would
falsely claim projects were loaded, replayed, or rendered.

## Immutability

`BatchDryRunResult` is `@dataclass(frozen=True)`. `__post_init__`
defensively normalizes the `include`, `exclude`, and
`projects` collections to tuples so the result never aliases
a caller-provided list. The manifest instance is never
mutated; the manifest file is never modified.

## Safety guarantees

The dry-run layer is guaranteed to:

- never call `load_project` (verified by tests that count
  calls to a stubbed loader);
- never call `replay_project`;
- never call `render_scene`, `create_and_render_scene`, or
  `create_and_render_shots`;
- never import `bpy`, `ai`, `ollama`, `urllib`, `requests`,
  `pipeline`, `asset_registry`, `scene_plan`, `toonflow_ai`,
  or `audio`;
- never call `print` or `input`;
- never use `threading`, `multiprocessing`, `asyncio`, or
  `subprocess`;
- never read environment variables or YAML/TOML/`.env`;
- never fabricate execution results in the report layer.

## Dependency boundaries

Dry-run code is allowed to import only the standard library
plus the existing TOONFLOW modules it orchestrates. The
dependency guard rails in `tests/test_batch_dry_run.py`
enforce the forbidden-import list at the AST level.

## Dependency injection

`dry_run_batch` has no injected dependencies — it is pure
orchestration. `dry_run_batch_manifest(manifest, *,
dry_run_batch=...)` accepts an injection point for tests.
The CLI's `main` function accepts `dry_run_batch_manifest`
in addition to the PHASE-023/PHASE-024 hooks.

## Determinism

Repeated dry-run calls with the same configuration produce
equal `BatchDryRunResult` values. Project ordering is
deterministic (sorted by relative POSIX path). No
timestamps, UUIDs, environment metadata, or random values
are introduced.

## Testing strategy

`tests/test_batch_dry_run.py` covers:

- **Result model**: immutability, tuple normalization,
  no-list-aliasing, all fields.
- **Discovery**: non-recursive, recursive, deterministic
  ordering, empty selection.
- **Filters**: include, exclude, exclude-wins, multiple
  patterns, parity with `discover_projects`, validation.
- **Dry-run safety**: `load_project` and `replay_project`
  are never called; project files are not modified.
- **Parity**: dry-run selection matches real execution
  selection for identical configuration.
- **Manifest integration**: dry-run returns the right
  result, manifest object is not mutated, manifest file is
  not modified, recursive flag is honored.
- **CLI integration**: `batch --dry-run`, `manifest
  --dry-run`, dry-run output is deterministic, empty
  selection returns `0`, invalid mode returns `2`, help
  returns `0`, manifest file is unchanged after dry-run.
- **PHASE-024 interaction**: overrides applied before
  dry-run, `--no-recursive` wins, dry-run does not
  participate in precedence, CLI override + dry-run
  works end-to-end.
- **Reports**: no report is written during dry-run, no
  project is falsely marked successful.
- **Architecture**: forbidden imports, no threading /
  subprocess / asyncio, no `print` / `input`, required
  functions and classes exist.

## Known limitations

- Dry-run reports discovery and filtering only; it does
  not introspect the contents of each project file. A
  project that *would* fail to load is still listed in
  the dry-run preview.
- Dry-run does not predict execution duration, memory
  usage, or render output.
- The CLI dry-run output is plain text. There is no
  machine-readable JSON dry-run output in this phase.

## Explicit non-features

This phase does NOT introduce:

- YAML / TOML / `.env`;
- environment-variable substitution;
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
- Scene Plan changes;
- a persisted `dry_run` field in the manifest schema.

## Ownership boundaries

| Concern | Owner |
| --- | --- |
| Dry-run result model | `workflow.batch.BatchDryRunResult` |
| Pure dry-run selection | `workflow.batch.dry_run_batch` |
| Batch entry-point `dry_run` keyword | `workflow.batch.run_batch` |
| Manifest dry-run selection | `workflow.manifest.dry_run_batch_manifest` |
| Manifest entry-point `dry_run` keyword | `workflow.manifest.run_batch_manifest` |
| CLI `--dry-run` parsing and dispatch | `workflow.cli` |
| Discovery + filtering (reused) | `workflow.batch.discover_projects` |
| Project loading, schema migration, replay | `workflow.project`, `workflow.project_migrations` |
| Report generation | `workflow.report` |
| Rendering, Blender, AI | `toonflow_ai.generation.*`, `ai.*` |
