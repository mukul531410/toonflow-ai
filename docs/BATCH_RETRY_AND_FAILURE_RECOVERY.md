# Batch Retry and Failure Recovery

TOONFLOW-PHASE-028 adds bounded, deterministic retries for individual batch projects.

## Attempts

`retries` is the number of additional attempts after the first attempt. The default is `0`, so a project receives exactly one attempt. `retries=2` permits at most three sequential attempts. Retrying stops immediately after the first success, with no delay, randomness, or concurrency.

## Execution and Reports

Retries wrap the existing per-project batch execution path. A failed project does not prevent later selected projects from running. The current `BatchReport` contains one entry per project and records only the final outcome: success after a retry is successful, and exhausted retries retain the final failure's existing error representation. No per-attempt history is persisted.

## Resume Interaction

Discovery and filtering happen first, then PHASE-027 resume planning. Previously successful projects are skipped and never retried. Previously failed and new projects are pending and receive the configured retry budget. The historical report remains read-only, and the existing `resume_from == report_path` collision protection remains active.

## CLI

```text
python -m workflow batch ./projects run --retries 2
python -m workflow batch ./projects run --resume-from previous.json --retries 2
python -m workflow batch ./projects run --retries 3 --dry-run
python -m workflow batch ./projects run --retries 3 --dry-run --json
python -m workflow manifest manifest.json --resume-from previous.json --retries 2
```

Negative or malformed retry values are invalid CLI arguments and return exit code `2`. Valid execution failures return exit code `1`; successful execution and dry-run return `0`.

## Dry Run and JSON

Dry-run validates the retry count, applies discovery, filters, and resume, and never loads or executes a project. The effective retry count is visible in plain output when nonzero and appears as the deterministic `retries` JSON field when explicitly nonzero. Legacy zero-retry JSON remains unchanged.

## Manifest and DI

Retry is execution-time input only. It is not stored in `BatchManifest`, does not change schema version `1`, and does not participate in manifest configuration precedence. Existing project loaders, executors, report writers, report loaders, and dry-run injection points remain available.

## Non-Features

This phase does not add delays, exponential backoff, jitter, scheduling, asynchronous or parallel execution, queues, distributed workers, persistent retry state, databases, cloud state, automatic error policies, manifest retry fields, or per-attempt reports.
