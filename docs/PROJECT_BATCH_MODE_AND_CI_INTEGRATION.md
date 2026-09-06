# Project Batch Mode & CI Integration Foundation

`TOONFLOW-PHASE-020` — a deterministic batch entry point on top of
the existing TOONFLOW project CLI. The batch command processes every
project JSON file in a directory, strictly sequentially, in
lexicographic filename order, and is suitable for direct use in CI
pipelines and batch render farms.

---

## 1. Purpose

PHASE-019 added a single-project CLI (`validate`, `show`, `run`).
PHASE-020 adds a single-directory batch entry point so that:

- A directory of project JSON files can be processed with one
  command.
- The processing order is fully deterministic (lexicographic
  filename order, not filesystem order).
- The batch is CI-friendly: it produces a complete report and
  continues past per-project failures.
- The existing single-project CLI commands remain unchanged.

The batch layer is intentionally minimal. It does not add
parallelism, a job queue, a database, a job history, a JSON
report file, or progress animations.

---

## 2. Architecture

The batch logic lives in a small dedicated module:

```
workflow/__main__.py        # thin entry point: sys.exit(main())
    |
    v
workflow/cli.py             # parse + dispatch (NEW: batch subcommand)
    |
    v
workflow/batch.py           # NEW: batch orchestration (NEW)
    |
    +--> workflow.load_project(path)       # validate, show, run
    |
    +--> workflow.replay_project(project)  # run only
```

Responsibilities:

- **`workflow/batch.py`** — owns `discover_projects`, the
  per-mode executors, the `BatchProjectResult` value, the
  summary helper, and the `run_batch` programmatic entry point.
  The module is pure-Python, bpy-free, AI-free, networking-free,
  and threading-free.
- **`workflow/cli.py`** — adds a `batch` subcommand with
  `directory` and `mode` positionals, and dispatches to
  `workflow.batch.run_batch`. No business logic is added to the
  CLI itself.
- **`workflow/__init__.py`** — unchanged. The batch layer is
  reached via `workflow.batch.run_batch` and
  `python -m workflow batch`, not via the top-level package.

---

## 3. CLI syntax

```
python -m workflow batch <directory> <mode>
```

Where:

- `<directory>` is a path to an existing directory of project
  JSON files (positional, required).
- `<mode>` is one of `validate`, `show`, `run` (positional,
  required, choices enforced by argparse).

Example invocations:

```
python -m workflow batch ./projects validate
python -m workflow batch ./projects show
python -m workflow batch ./projects run
```

---

## 4. Batch modes

The batch command supports three modes, each mirroring the
single-project CLI:

| Mode | Per-project behavior |
| --- | --- |
| `validate` | Calls `load_project(path)`, prints `<path>: OK` or `<path>: ERROR: <message>`. |
| `show` | Calls `load_project(path)`, prints the same per-project block as the single-project `show` command. |
| `run` | Calls `load_project(path)`, then `replay_project(project)`, prints `<path>: OK (N shot(s))` followed by the per-shot output paths. |

A mode argument that is not one of `validate`, `show`, or `run`
is rejected by argparse before any code runs and produces exit
code `2`.

---

## 5. File discovery rules

`discover_projects(directory)` returns a deterministically
ordered list of project files. The rules are:

- **Non-recursive.** Only direct children of `directory` are
  considered. Subdirectories are never entered.
- **`*.json` only.** Files whose name ends in `.json` are
  eligible. Other extensions are ignored.
- **Hidden files ignored.** Any name starting with `.` is
  skipped (e.g. `.DS_Store`, `.hidden.json`).
- **Directories ignored.** Even if a directory's name ends in
  `.json`, it is skipped — only regular files are considered.
- **Sorted.** Names are sorted using Python's default
  lexicographic string order, which is byte-deterministic
  across runs and platforms for ASCII filenames.
- **String paths.** The returned list contains string paths
  built with `os.path.join`, not `pathlib.Path` objects, for
  cross-platform determinism.

---

## 6. Deterministic ordering

The same directory contents and injected dependencies always
produce:

- The same file discovery order (lexicographic by filename).
- The same delegated call order (one project at a time, in
  discovery order).
- The same per-project output order.
- The same summary block.
- The same exit code.

No timestamps, UUIDs, random values, environment-dependent
metadata, terminal colors, or progress animations are emitted.

---

## 7. Validate behavior

For every discovered project, the batch layer calls
`workflow.load_project(path)`. The existing project layer
performs:

- File loading.
- JSON parsing.
- Schema migration.
- Schema validation.

Per-project output:

```
<path>: OK
```

On failure:

```
<path>: ERROR: <ExceptionType>: <message>
```

`replay_project` is never called in `validate` mode (verified
by test).

---

## 8. Show behavior

For every discovered project, the batch layer calls
`workflow.load_project(path)` and prints the same deterministic
per-project block as the single-project `show` command:

```
<path>:
  Name: <name>
  Schema version: <version>
  Description: <description>
  Shots: <count>
  Shot 0: concept='...' animation='...' lip_sync=... output_path='...'
  ...
```

Project files on disk are not modified. `replay_project` is
never called in `show` mode.

---

## 9. Run behavior

For every discovered project:

1. Call `load_project(path)`.
2. If loading fails, the project is recorded as failed and
   `replay_project` is NOT invoked for that project.
3. If loading succeeds, call `replay_project(project)` exactly
   once.
4. On replay failure, the project is recorded as failed and
   the next project is processed.
5. On success, print `<path>: OK (N shot(s))` followed by one
   `  Shot <i>: output_path='...'` line per output path, in the
   order returned by the multi-shot result.

Projects are processed strictly sequentially. No parallelism,
no concurrent execution, no background workers.

---

## 10. Continue-on-error policy

The batch command follows the **continue-on-error** failure
policy. For each project:

- If loading fails, record the failure, print a deterministic
  error line, and continue with the next project.
- If `replay_project` fails, record the failure, print a
  deterministic error line, and continue with the next project.

After every discovered file has been processed, a deterministic
summary block is printed:

```

Summary:
  Projects: 5
  Succeeded: 4
  Failed: 1

```

The exit code is then:

- `0` if and only if every project succeeded.
- `1` if one or more projects failed, or if no eligible
  project JSON files were found in the directory, or if the
  directory itself is missing or not a directory.

This gives CI systems a complete batch report instead of
failing on the first project.

---

## 11. Exit codes

| Situation | Exit code |
| --- | --- |
| All discovered projects succeeded | `0` |
| One or more projects failed | `1` |
| No eligible project JSON files in the directory | `1` |
| Directory does not exist or is not a directory | `1` |
| Invalid CLI arguments (missing args, unknown mode) | `2` |
| `--help` | `0` |

The existing single-project commands (`validate`, `show`,
`run`) keep their PHASE-019 exit codes. The batch command
adds a new layer on top without changing the underlying
behavior.

---

## 12. CI integration usage

A typical CI pipeline step that runs the batch `validate` mode
on every project JSON file under `./projects`:

```
python -m workflow batch ./projects validate
```

Or in a CI YAML step:

```yaml
- name: Validate TOONFLOW projects
  run: python -m workflow batch ./projects validate
- name: Show TOONFLOW projects
  run: python -m workflow batch ./projects show
- name: Run TOONFLOW projects
  run: python -m workflow batch ./projects run
```

Because the batch is deterministic and continues on error, the
CI log contains a complete per-project report, and the final
exit code reflects whether any project failed.

---

## 13. Dependency injection

The batch layer reuses the existing CLI DI pattern. The
programmatic entry point accepts:

- `load_project` — replaces `workflow.load_project`.
- `replay_project` — replaces `workflow.replay_project`. Only
  used in `run` mode.
- `stdout` — replaces `sys.stdout` for output capture.

Unit tests use these hooks to exercise the batch logic without
Blender, bpy, Ollama, a real renderer, or a real AI server.

The CLI entry point also accepts the same DI hooks and forwards
them to `run_batch`.

---

## 14. Determinism guarantees

The batch layer is deterministic by construction:

- File discovery uses `os.scandir` + `sorted`, with no
  filesystem-order dependency.
- All per-project work is a sequential `for` loop.
- No timestamps, UUIDs, random values, environment lookups,
  or timezone-aware formatting.
- No threading, multiprocessing, asyncio, or concurrent
  futures.
- The summary block is built from a single integer count, not
  from a duration or a wall-clock measurement.
- Output is written through the injected `stdout` stream, not
  through `print`, so test capture is exact.

---

## 15. Ownership and safety boundaries

The batch layer:

- Does **not** import or use `bpy`, `ai`, `ollama`, `urllib`,
  `requests`, `pipeline`, `asset_registry`, `scene_plan`, or any
  submodule of `toonflow_ai`.
- Does **not** call `keyframe_insert`, `from_pydata`,
  `render_scene`, `create_or_update_camera`, or any direct
  Blender / rendering API.
- Does **not** perform JSON parsing, schema migration, project
  validation, or replay orchestration itself — it delegates
  these to the existing public APIs.
- Does **not** mutate project JSON files, loaded `Project`
  objects, or any unrelated file on disk.
- Does **not** create, delete, or rename files.
- Does **not** introduce a database, job history, or JSON
  report file.
- Does **not** run the workflow on more than one project at a
  time.

These constraints are enforced by AST-based tests in
`tests/test_project_batch_cli.py`.

---

## 16. Testing strategy

The batch layer is tested by 67 tests in
`tests/test_project_batch_cli.py`. The tests are grouped as:

- **`PublicAPITests`** (6) — the CLI `batch` subcommand is
  registered; the existing `validate` / `show` / `run`
  commands are unchanged; the `__main__` module is still thin;
  invalid batch arguments produce exit code 2; the
  `workflow.batch` module exposes the documented surface.
- **`DiscoveryTests`** (7) — only JSON files are discovered;
  directories and hidden files are ignored; ordering is
  lexicographic; empty directory returns an empty list;
  missing path raises `OSError`; non-directory raises
  `OSError`.
- **`ValidateModeTests`** (9) — every project is loaded;
  sorted order is respected; successes and failures are
  reported; processing continues after failure;
  `replay_project` is never called; summary counts are
  correct; exit codes are `0` / `1`; empty / missing
  directory returns `1`.
- **`ShowModeTests`** (5) — every project is loaded;
  ordering is deterministic; project information is shown;
  files are not modified; `replay_project` is never called;
  processing continues after failure; summary counts are
  correct.
- **`RunModeTests`** (8) — load-then-replay per project;
  strictly sequential execution; replay called only after
  successful load; loading failure prevents replay; replay
  failure does not prevent later projects; output paths
  preserve delegated order; summary counts are correct;
  processing continues after failure.
- **`DependencyInjectionTests`** (4) — fake `load_project`
  works; fake `replay_project` works; no Blender required;
  no Ollama required.
- **`DeterminismTests`** (3) — repeated runs produce
  equivalent delegation order; summary output is
  byte-identical; file order is deterministic.
- **`ArchitectureTests`** (25) — AST-based guard rails for
  the dependency boundaries listed above; the CLI's batch
  wiring routes through `workflow.batch.run_batch`; no
  threading / multiprocessing / asyncio.

The tests do not require Blender, bpy, Ollama, a real
renderer, or a real AI server.

---

## 17. Known limitations

- **No recursive directory walk.** A future phase may add a
  `--recursive` flag.
- **No JSON report file.** A future phase may add
  `--report out.json`.
- **No parallel execution.** Projects run strictly
  sequentially. A future phase may add a `--workers N` flag.
- **No progress indicators.** Long batches print nothing
  until completion.
- **No `--filter` glob.** A future phase may add a glob
  pattern to restrict the file set.
- **Empty directory is treated as failure.** This is
  deliberate (CI should notice the empty directory) but may
  be relaxed by a future phase with an `--allow-empty` flag.
- **No `os.walk` / `Path.rglob`.** Discovery uses
  `os.scandir` for cross-platform determinism and explicit
  non-recursive semantics.

---

## 18. Explicit non-features

The batch layer does **NOT** implement, and no tests are
written for, any of the following:

- Job queue, worker pool, or background scheduler.
- Database, SQLite, JSON report file, or other persistence.
- Parallel or concurrent execution.
- Retry logic on transient failures.
- Progress bars, spinners, or terminal colors.
- Recursive directory walk.
- Glob-based file filtering.
- File watching or hot-reload.
- Network access (no Ollama, no HTTP, no remote project
  fetching).
- Direct Blender manipulation.
- AI planning or prompt generation.
- Custom plugin / hook system.
- Interactive prompts.
- Environment variable overrides or config files.

---

## 19. Example commands

Validate every project in a directory:

```
python -m workflow batch ./projects validate
```

Output:

```
C:\projects\alpha.json: OK
C:\projects\beta.json: OK
C:\projects\gamma.json: ERROR: ProjectInputError: project.schema_version 99 is unsupported

Summary:
  Projects: 3
  Succeeded: 2
  Failed: 1

```

Exit code: `1` (one project failed).

Show every project in a directory:

```
python -m workflow batch ./projects show
```

Run every project in a directory:

```
python -m workflow batch ./projects run
```

Programmatic use (for tests and embedding):

```python
from workflow.batch import run_batch

rc = run_batch("./projects", "validate", stdout=my_buffer)
assert rc == 0
```
