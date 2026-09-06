# Batch Result Export

TOONFLOW-PHASE-031 adds a deterministic analytical export over existing batch results. It is a conversion layer, not a second execution-history or persistence system.

## Model and APIs

`BatchResultExport` is an immutable value containing `directory`, `mode`, `recursive`, `include`, `exclude`, final current `projects`, the existing `BatchOperationalSummary`, and selected/skipped/pending path partitions.

Use `export_batch_result(...)` with final `BatchProjectResult` values, or pass a `BatchDryRunResult` directly. Convert exports with `batch_result_to_dict(...)` or `batch_result_to_json(...)`.

```python
from workflow.batch import batch_result_to_json, export_batch_result

export = export_batch_result(
    directory="./projects",
    mode="validate",
    project_results=results,
    selected_projects=selected_paths,
    skipped_projects=skipped_paths,
)
payload = batch_result_to_json(export)
```

## Semantics

Normal exports contain only final current project results. Retry fields use actual attempts already recorded by `BatchProjectResult`; attempt history is not persisted. Resume-skipped projects remain path partitions and are not fabricated as current successes. The summary is derived from the same final results and selected/skipped counts used by batch execution.

Dry-run exports contain no project execution records. They preserve selected, skipped, and pending paths and report `executed=0`, `succeeded=0`, `failed=0`, `retried=0`, and `total_attempts=0`. Retry capacity remains configuration only.

## Determinism and Compatibility

Conversion uses JSON-safe primitives, stable insertion order, existing pretty-JSON formatting, and exactly one trailing newline. It performs no discovery, report reload, file write, Blender work, network access, timestamp generation, or mutation. `BatchReport` remains the final-outcome source of truth, and `BatchManifest` schema version 1 is unchanged.

The existing `--json` contract remains dry-run-only. Existing dry-run JSON behavior is preserved; the export APIs are available programmatically rather than introducing a competing general execution JSON format.

## Non-Features

This phase does not add persistent analytics, telemetry, dashboards, event sourcing, per-attempt databases, retry policies, scheduling, concurrency, queues, plugins, alternate formats, network/cloud export, project or manifest schema changes, or a new persistence layer.
