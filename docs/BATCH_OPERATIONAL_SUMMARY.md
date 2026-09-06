# Batch Operational Summary

TOONFLOW-PHASE-030 adds a deterministic analytical view over existing batch results. It introduces no database, telemetry store, event log, or second execution-history system.

## Summary Fields

`BatchOperationalSummary` contains `selected`, `skipped`, `executed`, `succeeded`, `failed`, `retried`, `total_attempts`, and `pending`.

For completed execution, `selected` is the post-filter selection, `skipped` is the resume-skipped count, and `executed` is the number of projects attempted at least once. `succeeded` and `failed` describe final current outcomes. `retried` counts projects with more than one actual attempt, and `total_attempts` sums actual attempts. `pending` is zero for normal completed execution.

The normal invariants are:

```text
selected = skipped + executed
executed = succeeded + failed
```

## Resume and Retry

Resume planning precedes execution. Skipped historical successes are not current successes and are not counted as executed. Retry metadata comes from each final `BatchProjectResult`; configured maximum attempts are never substituted for actual attempts.

## Dry Run

Dry-run summaries use `selected`, `skipped`, and `pending` from the current selection and always report `executed=0`, `succeeded=0`, `failed=0`, `retried=0`, and `total_attempts=0`. When retry configuration is present, `retries` and `max_attempts` describe capacity only; no actual `attempts` value is fabricated.

Plain text reports these counters without colors, progress indicators, timestamps, or logging. Dry-run JSON adds the summary counters to generated previews while retaining deterministic ordering and JSON-only output. Manually constructed legacy dry-run result objects retain their prior serialization shape.

## Manifest and Compatibility

The manifest schema and configuration precedence are unchanged. Manifest execution and direct batch execution use the same summary derivation for equivalent effective selections. Existing callers still receive the batch exit code, and existing `BatchReport` entries remain authoritative for final outcomes. No project schema or report-history schema redesign is introduced.

## API and Limitations

Use `build_batch_operational_summary` or its alias `summarize_batch` with final project results and optional selection counts. The function is pure and accepts synthetic results for tests. It performs no discovery, project loading, file writes, Blender work, network access, or report reloads.

This phase does not add persistent analytics, telemetry, dashboards, monitoring, event sourcing, per-attempt persistent logs, retry policies, scheduling, concurrency, queues, plugins, environment substitution, or general execution JSON mode.
