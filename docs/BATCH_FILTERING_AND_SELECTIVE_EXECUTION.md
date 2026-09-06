# Batch Filtering & Selective Execution

`TOONFLOW-PHASE-022` extends the `batch` subcommand with glob-based filtering so CI pipelines and local operators can run a subset of the projects under a directory without re-shuffling files.

## What it adds

Three new options on `batch`:

| Option | Meaning |
| --- | --- |
| `--include PATTERN` | Restrict execution to projects whose relative path matches the pattern. Repeatable, and may also be a comma-separated list. |
| `--exclude PATTERN` | Drop projects whose relative path matches the pattern. Repeatable, and may also be a comma-separated list. |
| `--recursive` | Walk subdirectories; without it, only files directly in the search directory are considered. |

Patterns use `fnmatch.fnmatchcase` (case-sensitive). The matched string is the **relative path** of the project file with the platform separator normalized to `/`.

## Behavior

- Without any filter or `--recursive`, the previous behavior is preserved: only top-level `.json` files are discovered and run.
- `--include` is a whitelist applied first. If the resulting list is empty, batch exits with code `1` and prints a clear message to `stdout`. No project is loaded, no report is written.
- `--exclude` is applied after `--include`. Exclude always wins.
- `--recursive` enables subdirectory discovery. The order is the sorted relative path of every eligible file.
- Filters are applied before any project is loaded. No Blender call, no schema migration, no AI invocation, no network call happens for filtered-out files.
- Empty filter values are rejected as a validation error (`BatchInputError`).
- Mixing `bool` or `int` with `str` values inside the same `--include` / `--exclude` value is rejected.
- Non-`bool` `--recursive` values are rejected.

## CLI examples

```text
# Only files whose name starts with "scene_"
toonflow batch ./projects run --include "scene_*.json"

# Drop drafts and tutorials
toonflow batch ./projects validate --exclude "draft_*" --exclude "tutorial_*"

# Walk subdirectories but keep only finals
toonflow batch ./projects run --recursive --include "**/final_*.json"

# Combine include + exclude
toonflow batch ./projects validate \
    --recursive \
    --include "ep*.json" \
    --exclude "*_draft.json"
```

Each option can also be repeated or comma-separated:

```text
toonflow batch ./projects run --include "a.json,b.json"
toonflow batch ./projects run --include "a.json" --include "b.json"
toonflow batch ./projects run --exclude "draft_*.json,*_tmp.json"
```

## Python API

```python
from workflow.batch import (
    discover_projects,
    run_batch,
    BatchInputError,
)

paths = discover_projects(
    "./projects",
    recursive=True,
    include=("ep*.json",),
    exclude=("*_draft.json",),
)
```

`run_batch` accepts the same keyword arguments and forwards them to `discover_projects` internally:

```python
run_batch(
    "./projects",
    "validate",
    recursive=True,
    include=("ep*.json",),
    exclude=("*_draft.json",),
    report_path="./build/batch_report.json",
    stdout=sys.stdout,
)
```

## Pattern semantics

- `*` matches any run of characters (including `/`).
- `?` matches a single character.
- `[seq]` matches one of the listed characters.
- `**` matches any run of characters, including empty.
- Pattern matching is case-sensitive; `Scene_*.json` does not match `scene_01.json`.
- A pattern without a path separator matches the relative path as a whole; `ep*.json` does not match `season1/ep01.json` because the relative path begins with `season1/`. Use `**/ep*.json` to allow nested matches.

## Errors

`BatchInputError(ValueError)` is raised when filter arguments cannot be safely interpreted. It exposes:

| Attribute | Meaning |
| --- | --- |
| `parameter` | The name of the offending option (`"include"`, `"exclude"`, or `"recursive"`). |
| `value` | The value that failed validation. |

The CLI surfaces these as a non-zero exit code with a human-readable message and does not write a report.

## Integration with reports

Filtering interacts with `--report` only at the entry-exit boundary:

- Filters that resolve to an empty set exit with code `1` and write no report.
- A non-empty filtered run produces the same JSON report as an unfiltered run, with only the surviving project entries.

## Architectural rules

- The filter layer lives in `workflow.batch`; no new module is added.
- Pattern matching uses only `fnmatch` from the standard library.
- The filter layer does not import `bpy`, `ai`, `ollama`, `urllib`, `pipeline`, audio libraries, or third-party dependencies.
- The filter layer does not perform project loading, schema migration, rendering, or AI calls.
- The existing batch behavior without these options is unchanged.
