# Machine-Readable Dry-Run JSON Output

`TOONFLOW-PHASE-026` adds a deterministic JSON representation
for batch dry-run. The plain-text PHASE-025 output remains
the default; the new `--json` flag switches the dry-run path
to JSON-only stdout for CI scripts, automation, and future
tooling.

## Why machine-readable output exists

PHASE-025 introduced a deterministic plain-text dry-run
summary. That format is human-friendly but awkward to parse
from CI scripts. PHASE-026 adds a JSON representation so:

- `jq` and other shell tools can consume the dry-run output
  directly;
- CI pipelines can gate builds on the exact selection;
- future orchestration tools (e.g. an MCP server) can read
  the same canonical model.

The JSON layer is **output representation only**. The
canonical model is still `BatchDryRunResult`; the JSON is
derived from it.

## BatchDryRunResult as canonical model

```text
batch configuration
      ↓
dry_run_batch()
      ↓
BatchDryRunResult
      ↓
batch_dry_run_to_dict() / batch_dry_run_to_json()
      ↓
CLI output
```

No second data model is introduced. The serializer only
reads from `BatchDryRunResult`. The result itself is never
mutated, and the serializer never touches the file system,
network, or any execution layer.

## JSON schema

The canonical top-level key order is:

```text
directory
mode
recursive
include
exclude
projects
```

Field types:

| Field | JSON type | Notes |
| --- | --- | --- |
| `directory` | string | The scanned directory, normalized with forward slashes. |
| `mode` | string | One of `"validate"`, `"show"`, `"run"`. |
| `recursive` | boolean | Effective recursive flag. |
| `include` | array of string | Effective include patterns. |
| `exclude` | array of string | Effective exclude patterns. |
| `projects` | array of string | Effective would-be-executed paths, in deterministic lexicographic order, normalized with forward slashes. May be empty. |

Example output:

```json
{
  "directory": "./projects",
  "mode": "run",
  "recursive": true,
  "include": [
    "production/*.json"
  ],
  "exclude": [
    "**/draft_*.json"
  ],
  "projects": [
    "./projects/a.json",
    "./projects/sub/b.json"
  ]
}
```

## Deterministic serialization

The JSON output is byte-for-byte deterministic for identical
input. Specifically:

- `indent=2`, `sort_keys=False`, `ensure_ascii=False` (the
  same convention used by PHASE-021 reports and PHASE-023
  manifests);
- exactly one trailing newline;
- canonical key order (no hash-based ordering);
- path values use forward slashes regardless of platform;
- no timestamps, UUIDs, environment metadata, hostname, PID,
  memory address, or Python `repr()` output;
- repeated serialization of the same `BatchDryRunResult`
  produces identical bytes.

## CLI usage

```text
# Plain-text dry-run (PHASE-025 behavior, unchanged)
python -m workflow batch ./projects validate --dry-run

# Machine-readable dry-run (PHASE-026)
python -m workflow batch ./projects run --dry-run --json

# Manifest dry-run with overrides, JSON output
python -m workflow manifest configs/nightly.json \
    --dry-run --json \
    --include "release/*.json" \
    --exclude "**/draft_*.json"
```

The output goes to stdout only. There is no banner, no
logging, no explanatory prefix, and no plain-text summary
when `--json` is supplied. The JSON document is the only
content.

## `--json` requires `--dry-run`

The flag is **only** valid with `--dry-run`. Invalid
combinations return the standard CLI exit code `2` with a
deterministic error message:

```text
python -m workflow batch ./projects validate --json
# error: --json requires --dry-run
# exit code: 2

python -m workflow manifest configs/nightly.json --json
# error: --json requires --dry-run
# exit code: 2
```

`--json` is **not** a general batch output mode. There is
no execution-result JSON format; PHASE-021's `BatchReport`
remains the dedicated report representation.

## Manifest override interaction

The JSON describes the **effective** configuration after
PHASE-024 overrides are applied. For example:

| Manifest value | CLI override | JSON field |
| --- | --- | --- |
| `recursive = true` | `--no-recursive` | `"recursive": false` |
| `recursive = false` | `--recursive` | `"recursive": true` |
| `include = ["a.json", "b.json"]` | `--include c.json` | `"include": ["c.json"]` |
| `exclude = ["a.json"]` | `--exclude b.json` | `"exclude": ["b.json"]` |

Include and exclude are always complete replacements
(PHASE-024 semantics); the JSON never merges manifest and
CLI values.

## Manifest immutability

For:

```text
python -m workflow manifest configs/nightly.json --dry-run --json
```

the manifest file is byte-for-byte unchanged before and
after the command. The JSON output is generated in memory
only. The CLI never calls `save_batch_manifest` during
dry-run. The manifest instance is never mutated; only a
new `BatchManifest` (the effective one) is constructed by
`apply_manifest_overrides`.

## Empty selection behavior

PHASE-025 semantics are preserved: an empty selection is a
valid dry-run result. The JSON output for an empty
selection is:

```json
{
  "directory": "./empty",
  "mode": "validate",
  "recursive": false,
  "include": [],
  "exclude": [],
  "projects": []
}
```

Empty selection never raises a JSON serialization error,
never produces a different empty-selection contract, and
returns exit code `0`.

## Exit codes

| Condition | Exit code |
| --- | --- |
| Successful dry-run (including empty selection) | `0` |
| Invalid mode / recursive / include / exclude | `2` |
| Invalid CLI argument (e.g. `--json` without `--dry-run`) | `2` |
| Manifest load failure with `--dry-run --json` | `1` |
| Manifest override validation failure with `--dry-run --json` | `1` |

## CI / scripting usage

```bash
# Pipe to jq and count selected projects
python -m workflow batch ./projects validate --dry-run --json \
    | jq '.projects | length'

# Verify a manifest's effective selection matches expectations
python -m workflow manifest configs/nightly.json --dry-run --json \
    | jq -e '.recursive == false and (.include | length) == 1'
```

The output is suitable for direct piping to `jq`, `yq`, or
any JSON consumer. The trailing newline does not break
streaming JSON consumers.

## Safety guarantees

The JSON layer is **output representation only**. It
inherits all PHASE-025 dry-run safety guarantees:

- never calls `load_project()`;
- never calls `replay_project()`;
- never executes project workflows;
- never invokes Blender, AI, Ollama, or rendering;
- never accesses the network;
- never modifies project files;
- never creates execution reports;
- never rewrites the manifest file.

The serializer only reads from `BatchDryRunResult`. It
never mutates the result, never touches the file system,
and never invokes any execution layer.

## API

| Symbol | Purpose |
| --- | --- |
| `workflow.batch.batch_dry_run_to_dict(result)` | JSON-compatible dict in canonical key order. |
| `workflow.batch.batch_dry_run_to_json(result)` | Deterministic JSON string ending with one trailing newline. |
| `workflow.cli.main(..., dry_run_to_json=...)` | DI hook for the JSON formatter. |

## Dependency injection

The CLI accepts a `dry_run_to_json` keyword argument that
defaults to `_default_dry_run_to_json` (which delegates to
`workflow.batch.batch_dry_run_to_json`). Tests may inject
their own formatter to observe the exact forwarded value
without parsing JSON.

## Architecture rules

The new code is verified AST-clean against the forbidden
imports: `bpy`, `ollama`, `requests`, `urllib`, `pipeline`,
`asset_registry`, `scene_plan`, `toonflow_ai`, `audio`,
`threading`, `multiprocessing`, `asyncio`, `subprocess`,
`print`, `input`. The batch layer's top-level imports
remains `{os, typing, fnmatch, dataclasses, pathlib, json}`
(`json` was added in PHASE-026 for the dedicated dry-run
serializer).

## Testing strategy

`tests/test_batch_dry_run_json.py` covers:

- **Serialization**: correct structure, canonical key order,
  Path-to-string conversion, tuple-to-list conversion, bool
  conversion, indent=2, trailing newline, ensure_ascii=False
  preserves unicode, no timestamps/random fields, invalid
  result rejected.
- **Determinism**: same result → identical JSON; repeated
  serialization byte-identical; to_dict reproducible;
  project ordering stable; include/exclude ordering
  preserved.
- **CLI integration**: `batch --dry-run --json` returns 0;
  output is JSON only; no banner; exactly one trailing
  newline; exactly one JSON document; `manifest --dry-run
  --json` returns 0; manifest CLI overrides reflected in
  JSON; plain-text dry-run output unchanged without
  `--json`.
- **Invalid combinations**: `batch --json` without
  `--dry-run` returns 2; `manifest --json` without
  `--dry-run` returns 2; deterministic error message.
- **PHASE-024 interaction**: `--no-recursive` wins over
  manifest `True`; `--recursive` wins over manifest
  `False`; CLI `--include` replaces manifest include; CLI
  `--exclude` replaces manifest exclude.
- **Manifest immutability**: manifest file bytes unchanged
  before and after CLI execution; manifest object not
  mutated by serializer.
- **Dry-run safety**: `load_project` never called; no
  report written; project files not modified; manifest not
  modified.
- **Empty selection**: `projects: []` is valid JSON; CLI
  returns 0; manifest dry-run with empty selection
  returns 0.
- **Backward compatibility**: normal `batch` execution
  unchanged; normal `manifest` execution unchanged;
  `dry_run_batch()` still returns `BatchDryRunResult`;
  `dry_run_batch_manifest()` still returns
  `BatchDryRunResult`; `run_batch(dry_run=True)` still
  returns `0`.
- **Architecture**: no `bpy`, no AI / network / threading /
  subprocess imports; required functions and CLI
  validation message exist; CLI delegates to the dedicated
  JSON serializer.

## Known limitations

- The JSON output is always pretty-printed with `indent=2`;
  there is no compact mode in this phase.
- The JSON is emitted to stdout only. There is no
  `--output-file` option in this phase; consumers redirect
  shell-side.
- The CLI does not yet expose a separate
  `--machine-output` mode for other future JSON needs; the
  JSON flag is dry-run-only by design.

## Explicit non-features

This phase does NOT introduce:

- execution-result JSON output (PHASE-021 report format is
  unchanged);
- `--json` for normal batch / manifest execution;
- a new persisted JSON configuration format;
- a new manifest schema version;
- YAML / TOML / `.env` support;
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
- a compact JSON mode.

## Ownership boundaries

| Concern | Owner |
| --- | --- |
| Canonical dry-run result | `workflow.batch.BatchDryRunResult` |
| Dry-run selection | `workflow.batch.dry_run_batch` |
| Dry-run JSON serialization | `workflow.batch.batch_dry_run_to_dict` / `batch_dry_run_to_json` |
| CLI `--json` parsing and validation | `workflow.cli` |
| Manifest dry-run | `workflow.manifest.dry_run_batch_manifest` |
| Execution report JSON | `workflow.report` (unchanged) |
| Project loading, schema migration, replay | `workflow.project`, `workflow.project_migrations` |
| Rendering, Blender, AI | `toonflow_ai.generation.*`, `ai.*` |
