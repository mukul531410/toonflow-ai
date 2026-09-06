# Batch Resume and Continuation

TOONFLOW-PHASE-027 adds deterministic continuation from an existing `BatchReport` JSON file. The historical report is the only execution-history source of truth.

## Workflow

The batch layer always performs discovery and current include/exclude filtering first. It then calls `plan_batch_resume` on that current selection. The result contains `selected_projects`, `skipped_projects`, and `pending_projects` in deterministic selection order.

Only an entry whose report `success` value is explicitly `true` can be skipped. Failed, missing, malformed, unknown, or ambiguous entries remain pending. Duplicate historical paths are treated as ambiguous and are not skipped.

Paths are matched after redundant components are normalized and separators are represented as `/`. Matching is case-sensitive; no arbitrary case folding or path-object identity is used.

## CLI

```text
python -m workflow batch ./projects run --resume-from previous-report.json
python -m workflow batch ./projects run --resume-from previous-report.json --dry-run
python -m workflow batch ./projects run --resume-from previous-report.json --dry-run --json
python -m workflow manifest manifest.json --resume-from previous-report.json
```

`--resume-from` is execution-time input. It is not a `BatchManifest` field and does not participate in manifest configuration precedence. Current directory, mode, filters, recursion, and report options remain authoritative.

## Dry Run and JSON

Dry-run never loads or executes projects and never writes an execution report. With resume enabled, plain text reports the skip decision and selected, skipped, and pending counts. JSON extends the existing dry-run document only when resume is active with `selected_projects`, `skipped_projects`, and `pending_projects`; the original six-field output remains unchanged without resume.

## Reports

A new execution report contains only projects actually attempted in the current invocation. Skipped projects are not fabricated as new successes and receive no duration, timestamp, output, or render data. The previous report is loaded read-only and is never overwritten. Setting `--resume-from` equal to `--report` is rejected before execution.

## Dependency Injection and Exit Codes

The batch and manifest APIs accept report-loader injection alongside their existing project, executor, writer, and dry-run hooks. Exit code `0` means successful execution or a valid dry-run, `1` means execution/input or report-loading failure, and `2` remains the CLI invalid-argument code.

## Limitations and Non-Features

Resume is sequential and deterministic. This phase does not add retries, retry counts, backoff, parallel or distributed execution, queues, databases, persistent state, cloud or remote execution, scheduling, manifest persistence, YAML/TOML/.env support, plugins, hooks, progress bars, or terminal colors.
