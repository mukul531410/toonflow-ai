# Retry Observability and Attempt-Level Reporting

TOONFLOW-PHASE-029 adds deterministic observability for PHASE-028 retries without turning `BatchReport` into an event log or second history database.

## Attempt Semantics

`BatchAttemptResult` is an immutable in-memory value with a 1-based `attempt`, final `success`, and normalized error string. `BatchProjectResult.attempt_history` contains the attempts made in the current invocation. Its aggregate `attempts`, `attempt_count`, `final_attempt`, and `retried` values answer how much retry capacity was consumed.

A first-attempt success is `attempts=1`, `retried=false`. A failure followed by success records the final success with the actual number of attempts. Exhausted retries record the final failure and the same aggregate count. The retry loop stops immediately after success and remains sequential.

## BatchReport and Compatibility

The final project outcome remains authoritative. Reports continue to contain one project entry per current invocation. When a project used more than one attempt, its entry additively includes `attempts` and `retried` after the existing fields. One-attempt reports retain the legacy JSON shape. Historical reports without metadata load as `attempts=1`, `retried=false`; zero, negative, boolean, non-integer, or inconsistent metadata is rejected.

No per-attempt errors, timestamps, tracebacks, UUIDs, or persistent attempt history are stored.

## Resume

Resume still skips only historical entries whose final `success` is explicitly true. Attempt count and retry metadata do not affect skip eligibility. Historical success after retries is skipped; historical failure remains eligible for current execution and its configured retries.

## Dry Run and JSON

Dry-run performs no attempts and never loads a project. With retry configuration, it reports capacity using `retries` and `max_attempts`; it never emits an actual `attempts` count. JSON remains deterministic, JSON-only, and newline-terminated. The legacy zero-retry shape is preserved.

## Manifest and CLI

`--retries N` remains execution-time input for both `batch` and `manifest`. It is not a `BatchManifest` field, does not change manifest schema version 1, and is not persisted. Negative or malformed CLI values return exit code `2`. Valid execution failure returns `1`; successful execution and dry-run return `0`.

## Determinism and Non-Features

There are no delays, backoff, jitter, scheduling, concurrency, queues, distributed workers, retry policies, error-type decisions, project schema changes, per-attempt persistent event logs, plugins, environment substitution, progress bars, or terminal colors.
