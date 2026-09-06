# Batch Result Validation

TOONFLOW-PHASE-032 adds a pure consistency-validation layer for existing batch results, operational summaries, and `BatchResultExport` values. It performs analysis only and introduces no persistence, repair, telemetry, or execution history.

## APIs

`validate_batch_operational_summary(value, dry_run=False)`, `validate_batch_results(values)`, and `validate_batch_result_export(value)` return immutable `BatchResultValidation` values with deterministic `valid` and `findings` fields. `validate_batch_result_export_or_raise(value)` raises `BatchInputError` when an export is invalid and returns the original export when valid.

## Invariants

Normal summaries require nonnegative counters, `selected = skipped + executed`, `executed = succeeded + failed`, `retried <= executed`, and `total_attempts >= executed` and `total_attempts >= retried`. Project validation checks final success state, positive actual attempt counts, retry agreement, and sequential attempt history when present.

Dry-run summaries require `selected = skipped + pending`, zero executed/succeeded/failed/retried/total attempts, and no project execution records in the export. Retry capacity is never treated as actual execution.

Export validation checks configuration types, selected/skipped/pending partition membership, summary derivation, final project results, and dry-run truthfulness. Resume-skipped projects remain counts and path partitions only; they are not current successes or attempts.

## Determinism and Scope

Validation never discovers files, reloads reports, executes projects, mutates inputs, writes files, imports Blender, or accesses networks. Findings are stable and contain no timestamps, object representations, or environment data. `BatchReport` and `BatchManifest` remain unchanged. This phase does not add automatic repair, retry policy, persistence, dashboards, alternate formats, or scene/geometry/AI validation.
