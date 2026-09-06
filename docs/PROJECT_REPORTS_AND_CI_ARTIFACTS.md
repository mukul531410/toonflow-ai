# Project Report & CI Artifacts

`TOONFLOW-PHASE-021` — a deterministic machine-readable JSON report
for batch execution, designed for direct consumption by CI systems.

---

## 1. Purpose

PHASE-020 added a deterministic batch entry point. The batch
prints a human-readable summary to stdout and returns an exit
code. CI systems benefit from a machine-readable artifact as well,
so that dashboards can graph per-project pass/fail counts and so
that downstream tools can inspect the run without parsing free-form
text.

This phase adds:

- A `BatchReport` model (frozen dataclass) representing the
  outcome of a batch run.
- Deterministic JSON serialization of the report.
- An optional `--report PATH` flag on the batch CLI.
- A `save_report` programmatic API.
- A new `ReportInputError` for report-specific validation.

The report is opt-in. Without `--report`, the existing batch
behavior is byte-for-byte unchanged.

---

## 2. Architecture

```
python -m workflow batch <dir> <mode> [--report <path>]
        |
        v
workflow.cli._dispatch
        |
        v
workflow.batch.run_batch(..., report_path=..., report_writer=...)
        |
        +--> workflow.load_project(path)        # existing
        |
        +--> workflow.replay_project(project)   # existing (run mode)
        |
        +--> workflow.report.batch_result_to_report(...)
        |
        +--> workflow.report.save_report(...)
                  |
                  v
                report.json
```

Responsibilities:

- **`workflow/report.py`** — owns the `BatchReport` and
  `BatchProjectReportEntry` models, `ReportInputError`,
  `batch_result_to_report`, `report_to_dict`, `report_to_json`,
  and `save_report`. It is pure-Python, bpy-free, AI-free,
  network-free, and orchestration-only. It does not discover,
  load, replay, or render anything.
- **`workflow/batch.py`** — collects `BatchProjectResult`
  values as before, then optionally delegates to
  `batch_result_to_report` and `save_report` when a report
  path is provided. The report is only written when at least
  one project was actually executed; early-exit cases
  (unknown mode, missing directory, empty directory) do not
  produce a report and keep the existing exit-code behavior.
- **`workflow/cli.py`** — adds a `--report` option to the
  batch subcommand and forwards its value to `run_batch`. The
  CLI does not serialize JSON or write report files.

---

## 3. Batch report model

```python
@dataclass(frozen=True)
class BatchProjectReportEntry:
    path: str
    success: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    output_paths: Tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchReport:
    mode: str
    project_count: int
    success_count: int
    failure_count: int
    projects: Tuple[BatchProjectReportEntry, ...] = ()
```

Both types are frozen. The `output_paths` field is populated only
for successful `run` mode entries; it is an empty tuple for
`validate` / `show` modes and for failures.

---

## 4. JSON format

```json
{
  "mode": "validate",
  "project_count": 3,
  "success_count": 2,
  "failure_count": 1,
  "projects": [
    {
      "path": "/abs/path/alpha.json",
      "success": true,
      "error_type": null,
      "error_message": null,
      "output_paths": []
    },
    {
      "path": "/abs/path/beta.json",
      "success": true,
      "error_type": null,
      "error_message": null,
      "output_paths": []
    },
    {
      "path": "/abs/path/gamma.json",
      "success": false,
      "error_type": "ProjectInputError",
      "error_message": "project.schema_version 99 is unsupported",
      "output_paths": []
    }
  ]
}
```

For `run` mode, successful entries include `output_paths`:

```json
{
  "path": "/abs/path/alpha.json",
  "success": true,
  "error_type": null,
  "error_message": null,
  "output_paths": [
    "/renders/alpha_0.png",
    "/renders/alpha_1.png"
  ]
}
```

The JSON contains no timestamps, UUIDs, environment metadata, host
metadata, Python version metadata, or nondeterministic traceback
data. The `path` field is the path exactly as supplied to the
batch layer; it is not resolved or rewritten. The `output_paths`
are copied from the multi-shot result in execution order.

---

## 5. Deterministic serialization

JSON output is byte-deterministic for the same report:

- `indent=2`
- `sort_keys=False`
- `ensure_ascii=False`
- Top-level key order: `mode`, `project_count`, `success_count`,
  `failure_count`, `projects`.
- Per-project key order: `path`, `success`, `error_type`,
  `error_message`, `output_paths`.
- The file ends with exactly one trailing newline.

Non-ASCII strings (project names, descriptions, file paths) are
emitted verbatim. They are not escaped to `\uXXXX`.

---

## 6. CLI usage

```
python -m workflow batch ./projects validate --report reports/validate.json
python -m workflow batch ./projects show     --report reports/show.json
python -m workflow batch ./projects run      --report reports/run.json
```

Without `--report`, the command behaves exactly as in PHASE-020:

```
python -m workflow batch ./projects validate
```

The `--report` option is available for all three batch modes.

---

## 7. Programmatic API

```python
from workflow.batch import run_batch
from workflow.report import (
    BatchReport,
    BatchProjectReportEntry,
    ReportInputError,
    batch_result_to_report,
    report_to_dict,
    report_to_json,
    save_report,
)

# Option 1: end-to-end via the batch layer.
rc = run_batch(
    "./projects", "run",
    report_path="./reports/run.json",
)

# Option 2: build a report manually.
entries = (
    BatchProjectReportEntry(path="/a.json", success=True,
                            output_paths=("/o/1.png",)),
)
report = BatchReport(
    mode="run", project_count=1,
    success_count=1, failure_count=0,
    projects=entries,
)
save_report(report, "/tmp/r.json")
```

`save_report` returns the absolute, resolved `pathlib.Path` of
the written file.

---

## 8. Report path behavior

- **Non-empty strings and `os.PathLike` objects** are accepted.
  Whitespace-only strings and `None` are rejected with
  `ReportInputError("path", value)`.
- **Parent directories are created** when missing.
- **Existing files are overwritten** deterministically.
- **The returned path is absolute** (`Path.resolve()`).
- **Filesystem errors propagate** as `OSError` (or `ValueError`
  for paths the OS rejects, such as embedded nulls). The report
  layer does not swallow them.

---

## 9. Batch integration

`workflow.batch.run_batch` gained two new optional keyword
arguments:

- `report_path` — when `None` (the default), no report is
  written. When provided, a `BatchReport` is built from the
  executed project results and written via the report layer.
- `report_writer` — optional dependency-injection point. The
  default writer is `workflow.report.save_report`.

The report is only written when at least one project was
actually executed. The early-exit cases (unknown mode,
`OSError` on directory, empty directory) do not produce a
report and keep the existing exit-code behavior. This is the
documented, tested behavior.

Existing batch behavior is preserved:

- Continue-on-error: every discovered project is processed
  exactly once, in lexicographic order.
- Exit code: `0` only if all projects succeeded; `1`
  otherwise.
- No report is written unless `report_path` is explicitly
  provided.

---

## 10. Success/failure representation

Per-project entries in the report represent the structured
outcome of the batch layer's `BatchProjectResult`:

- On success: `success=true`, `error_type=null`,
  `error_message=null`. For `run` mode, `output_paths` contains
  the resolved output paths in execution order.
- On failure: `success=false`, `error_type` is the exception
  class name (e.g. `"ProjectInputError"`, `"OSError"`),
  `error_message` is the exception's `str()` representation.
  `output_paths` is an empty list.

The `error_type` / `error_message` split is derived from the
batch layer's `"<TypeName>: <message>"` error string by
splitting on the first `": "`. The split is deterministic and
preserves the exception class name and message exactly.

---

## 11. CI usage examples

A typical CI pipeline step that validates every project and
writes a JSON report:

```yaml
- name: Validate TOONFLOW projects
  run: python -m workflow batch ./projects validate --report ./reports/validate.json
- name: Upload report
  uses: actions/upload-artifact@v4
  with:
    name: toonflow-validate-report
    path: ./reports/validate.json
```

A consumer script that inspects the report:

```python
import json
with open("./reports/validate.json", encoding="utf-8") as fh:
    report = json.load(fh)
print(f"mode={report['mode']} "
      f"success={report['success_count']} "
      f"failed={report['failure_count']}")
for entry in report["projects"]:
    if not entry["success"]:
        print(f"FAIL: {entry['path']} "
              f"({entry['error_type']}: {entry['error_message']})")
```

A CI step that fails the build on any project failure uses the
batch command's exit code (unchanged from PHASE-020):

```yaml
- name: Validate TOONFLOW projects
  run: python -m workflow batch ./projects validate --report ./reports/validate.json
  # Exit code 0 = all OK, exit code 1 = one or more failures.
```

---

## 12. Exit-code behavior

The report layer does not change exit codes. The exit code of
`run_batch` (and the CLI) is determined entirely by the batch
execution:

| Situation | Exit code |
| --- | --- |
| All discovered projects succeeded | `0` |
| One or more projects failed | `1` |
| No eligible project JSON files in the directory | `1` |
| Directory does not exist or is not a directory | `1` |
| Invalid CLI arguments (missing args, unknown mode) | `2` |

When `save_report` itself fails (e.g. invalid path), the
underlying `ReportInputError` or `OSError` propagates to the
caller. The batch exit code is not affected by report-writing
errors: the batch has already produced its result before the
report is written.

---

## 13. Error behavior

| Error | Source | Where it surfaces |
| --- | --- | --- |
| Invalid `BatchReport` (wrong type) | `report_to_dict` / `report_to_json` / `save_report` | `ReportInputError("report", value)` |
| Invalid mode in `batch_result_to_report` | report layer | `ReportInputError("mode", value)` |
| Invalid project count | report layer | `ReportInputError("project_count", value)` |
| Invalid entry path | report layer | `ReportInputError("project_result.path", value)` |
| Invalid report path | report layer | `ReportInputError("path", value)` |
| Filesystem write failure | report layer | `OSError` (propagates) |

The CLI does not catch these. They propagate to the caller.

---

## 14. Dependency injection

`save_report` accepts an optional `report_writer` callable:

```python
def save_report(report, path, *, report_writer=None):
    ...
```

The default writer is `_default_report_writer`, which creates
parent directories and writes UTF-8 JSON. Tests inject a custom
writer to capture the payload without touching the file system.

`run_batch` accepts the same `report_writer` keyword and
forwards it to `save_report`. This lets tests exercise the
full batch-plus-report chain without writing to disk.

The CLI does not expose a `report_writer` hook (the CLI is a
process boundary; tests drive the CLI through the existing
`load_project` and `replay_project` hooks or through real
files).

---

## 15. Determinism guarantees

The report layer is deterministic by construction:

- Dicts are built in canonical key order.
- JSON uses `indent=2`, `sort_keys=False`, `ensure_ascii=False`.
- The file ends with exactly one trailing newline.
- No timestamps, UUIDs, random values, or environment lookups.
- Non-ASCII strings are preserved verbatim.
- The same `BatchReport` always serializes to the same bytes.

The batch layer's existing determinism guarantees
(lexicographic discovery order, continue-on-error, strict
sequential execution) are preserved by the report integration.

---

## 16. Ownership boundaries

**`workflow.report`** owns:

- The `BatchReport` and `BatchProjectReportEntry` models.
- `ReportInputError`.
- `batch_result_to_report`.
- `report_to_dict`, `report_to_json`.
- `save_report` and the default report writer.
- JSON serialization details.
- Report path validation.
- Report file persistence.

**`workflow.report`** does NOT own:

- Project discovery.
- Project loading.
- Schema migration.
- Batch execution.
- Rendering.
- Workflow execution.

**`workflow.batch`** owns:

- Project file discovery.
- Deterministic execution order.
- Per-project execution.
- Success/failure collection.
- Batch exit-code decision.
- Optional delegation to report writing (via `report_path`).

**`workflow.batch`** does NOT own:

- JSON formatting details.
- Report file serialization.

**`workflow.cli`** owns:

- Argparse parsing.
- Forwarding `--report` to `run_batch`.

**`workflow.cli`** does NOT own:

- Report serialization.
- Report persistence.
- Batch execution internals.

These constraints are enforced by AST-based tests in
`tests/test_project_reports.py`.

---

## 17. Testing strategy

The report layer is tested by 76 tests in
`tests/test_project_reports.py`. The tests are grouped as:

- **`PublicAPITests`** (6) — module imports; public surface
  available; package `__init__` stable; CLI callable; existing
  workflow / batch APIs unchanged.
- **`ReportModelTests`** (12) — valid report; frozen
  immutability; invalid mode; invalid project count; invalid
  entry path; success / failure / run-mode construction.
- **`SerializationTests`** (8) — canonical key order;
  deterministic output; trailing newline; non-ASCII
  preserved; indent of 2; success value as `true` / `false`;
  invalid report raises; `output_paths` in `run` mode.
- **`FilePersistenceTests`** (8) — absolute returned path;
  parent directories created; existing report overwritten;
  invalid path rejected; invalid report rejected; injected
  writer used; invalid path OS-rejected.
- **`BatchIntegrationTests`** (12) — no report without
  `report_path`; report written when requested; all projects
  included; counts correct; ordering preserved; run output
  paths included; failures represented; continue-on-error
  preserved; early-exit cases produce no report; injected
  report writer used.
- **`CLIIntegrationTests`** (5) — `--report` accepted;
  omitted behavior backward compatible; invalid CLI usage
  still `2`; report path forwarded; show-mode report.
- **`DeterminismTests`** (2) — repeated runs produce
  byte-identical reports; repeated serialization
  byte-identical.
- **`ErrorTests`** (3) — `ReportInputError` attributes and
  message; `OSError` propagates from invalid paths.
- **`ArchitectureTests`** (20) — AST-based guard rails: no
  `bpy` / `ollama` / `requests` / `urllib` / `http` /
  `pipeline` / `asset_registry` / `scene_plan` /
  `toonflow_ai.*`; no `bpy.data` / `bpy.ops` /
  `keyframe_insert` / direct rendering APIs; no
  `create_and_render_scene` / `create_and_render_shots`; no
  `print` / `input`; exactly one controlled `open()` call;
  minimal top-level imports; batch does not import `json`;
  CLI does not serialize JSON; CLI forwards `report_path`.

---

## 18. Known limitations

- **No JUnit XML report.** A future phase may add a JUnit XML
  writer behind an opt-in flag if CI dashboards need it. It is
  not implemented in PHASE-021 because it adds complexity
  without being required.
- **No HTML report.** A future phase may add a small HTML
  report writer.
- **No JSON Lines (JSONL) output.** The report is a single
  JSON object, not a stream of objects.
- **No `--report-format` flag.** The report format is
  always JSON.
- **No report compression / rotation.** A single file is
  written; the caller is responsible for archiving.
- **Report file location is caller-controlled.** The batch
  layer does not enforce that the report file lives outside
  the project directory. If the report path is inside the
  project directory, the second batch run would discover the
  report as a project file. Callers should place reports
  outside the project directory.
- **The CLI does not surface report-writing errors as a
  non-zero exit code.** A failed report write raises
  `OSError` / `ReportInputError` to the caller, which is
  the standard Python behavior.

---

## 19. Explicit non-features

The report layer does NOT implement:

- JUnit XML reports.
- HTML reports.
- JSON Lines.
- Timestamps, UUIDs, or random values.
- Compression, rotation, or archival.
- Network access (no upload to CI dashboards).
- GitHub API integration.
- Plugin / hook system.
- Custom serialization formats.
- Environment configuration (`.env` files, env-var overrides).
- Database persistence.
- File watching, hot-reload, or streaming.
- Terminal colors, progress bars, or rich formatting.

---

## 20. Example commands

Validate every project in a directory and write a JSON report:

```
python -m workflow batch ./projects validate --report ./reports/validate.json
```

Output:

```
...\projects\alpha.json: OK
...\projects\beta.json: OK
...\projects\gamma.json: ERROR: ProjectInputError: project.schema_version 99 is unsupported

Summary:
  Projects: 3
  Succeeded: 2
  Failed: 1

```

Report:

```json
{
  "mode": "validate",
  "project_count": 3,
  "success_count": 2,
  "failure_count": 1,
  "projects": [
    {"path": "C:\\projects\\alpha.json", "success": true,
     "error_type": null, "error_message": null, "output_paths": []},
    {"path": "C:\\projects\\beta.json", "success": true,
     "error_type": null, "error_message": null, "output_paths": []},
    {"path": "C:\\projects\\gamma.json", "success": false,
     "error_type": "ProjectInputError",
     "error_message": "project.schema_version 99 is unsupported",
     "output_paths": []}
  ]
}
```

Run every project and write a run report:

```
python -m workflow batch ./projects run --report ./reports/run.json
```

Programmatic use:

```python
from workflow.batch import run_batch

rc = run_batch(
    "./projects", "run",
    report_path="./reports/run.json",
)
```
