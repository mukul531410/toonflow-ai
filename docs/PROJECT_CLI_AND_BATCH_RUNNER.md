# Project CLI & Batch Runner Foundation

`TOONFLOW-PHASE-019` — a thin command-line interface for working with
persistent TOONFLOW project JSON files. The CLI is an orchestration
layer; it does not duplicate any existing project, schema, JSON,
multi-shot, or rendering logic.

---

## 1. Purpose

Provide a deterministic, testable, dependency-injectable command-line
entry point for the three most common operations on a TOONFLOW
project file:

1. **Validate** a project file (load + schema-migrate + check).
2. **Show** a deterministic project summary.
3. **Run** (replay) a project through the existing multi-shot
   workflow.

The CLI is intentionally minimal. It does not add a queue, a job
history, retry logic, progress animations, terminal colors, or
parallelism. Those are out of scope for this phase.

---

## 2. Architecture

The CLI is implemented as two small modules inside the existing
`workflow` package:

```
workflow/__main__.py        # thin entry point: sys.exit(main())
    |
    v
workflow/cli.py             # parse + dispatch + format
    |
    +--> workflow.load_project(path)       # validate, show, run
    |
    +--> workflow.replay_project(project)  # run only
```

Responsibilities:

- **`workflow/__main__.py`** — calls `cli.main()` and forwards the
  return code to `sys.exit()`. The file is intentionally tiny (under
  20 lines).
- **`workflow/cli.py`** — owns the `argparse` parser, the three
  command handlers, the output formatters, and the `main()`
  programmatic entry point.

The CLI is bpy-free, AI-free, and networking-free. It does not
import `bpy`, `ai`, `ollama`, `urllib`, `requests`, `pipeline`,
`asset_registry`, `scene_plan`, or any submodule of
`toonflow_ai.generation`.

---

## 3. CLI commands

The CLI exposes three subcommands. Each takes a single positional
`path` argument pointing to a project JSON file.

```
python -m workflow validate <project.json>
python -m workflow show     <project.json>
python -m workflow run      <project.json>
```

All three commands can also be invoked programmatically through
`workflow.cli.main(argv=[...])` and return an integer exit code.

---

## 4. `validate` command

Loads the project file via `workflow.load_project`, which performs
schema migration and validation automatically. On success, prints a
deterministic four-line summary to stdout:

```
Project is valid
Name: <name>
Schema version: <version>
Shots: <count>
```

Exit code:

- `0` — the project loaded and validated successfully.
- `1` — the project file could not be loaded, parsed, migrated, or
  validated.
- `2` — invalid CLI arguments (missing command, missing path, unknown
  command, extra positional arguments).

The command does not modify the file on disk. It does not call
`replay_project`.

---

## 5. `show` command

Loads the project file via `workflow.load_project` and prints a
deterministic, human-readable summary including every shot:

```
Name: <name>
Schema version: <version>
Description: <description>
Shots: <count>
Shot 0: concept='...' animation='...' lip_sync=False output_path='...'
Shot 1: ...
```

Shot ordering is preserved from the input. The summary is fully
deterministic: repeated invocations on the same file produce
byte-identical output.

The command does not modify the file on disk. It does not call
`replay_project`.

Exit codes: same as `validate`.

---

## 6. `run` command

Loads the project file via `workflow.load_project` and replays it
through the existing multi-shot workflow by calling
`workflow.replay_project` exactly once. The CLI does not invoke the
single-shot workflow, the multi-shot orchestrator, or any
generation / animation / camera / render function directly.

The output is a deterministic summary in execution order:

```
Project: <name>
Shots: <count>
Shot 0: output_path='...'
Shot 1: output_path='...'
```

Output paths come from the `MultiShotResult.output_paths` tuple in
the order they were produced.

Exit codes:

- `0` — the project loaded and the workflow completed successfully.
- `1` — the project could not be loaded, or the workflow raised an
  expected error (`OSError`, `ValueError`, `TypeError`, or any
  unexpected `Exception` from the delegated workflow). The exception
  message is printed to stdout; the stack trace is elided.
- `2` — invalid CLI arguments.

A replay error does not cause a loading error to be reported, and
vice versa. If loading fails, the workflow is not invoked.

---

## 7. Project loading and schema migration

The CLI does not perform JSON parsing or schema migration. It calls
`workflow.load_project(path)`, which in turn:

1. Validates the path (string / path-like, non-empty).
2. Opens and reads the file.
3. Calls `project_from_json` to JSON-decode the document.
4. Calls `project_from_dict` which:
   - calls `migrate_project_dict` (PHASE-018) to upgrade the
     document to the current schema version,
   - validates the migrated document,
   - constructs a `Project`.
5. Returns the `Project`.

Older project documents (schema v1) are silently and deterministically
migrated forward to schema v2 during loading. Unsupported future
schema versions (e.g. v99) are rejected by `load_project` and surface
in the CLI as a non-zero exit code.

---

## 8. Execution delegation

The `run` command is a two-step delegation:

```
workflow.cli._cmd_run
    |
    v
workflow.load_project(path)           # from workflow.project
    |
    v
workflow.replay_project(project)      # from workflow.project
    |
    v
workflow.create_and_render_shots      # from workflow.shots (PHASE-016)
    |
    v
workflow.create_and_render_scene      # from workflow.api (PHASE-015)
    |
    v
toonflow_ai.generation.*              # Blender side
```

The CLI touches only the first two arrows. The remaining arrows are
owned by the existing workflow layers and are not duplicated,
reimplemented, or shadowed by the CLI.

---

## 9. Exit code behavior

| Situation | Exit code |
| --- | --- |
| Successful command | `0` |
| Invalid CLI arguments (missing command, missing path, unknown command, extra positionals) | `2` |
| Project loading error (missing file, malformed JSON, unsupported schema, invalid project shape) | `1` |
| Replay error (any exception from `replay_project`) | `1` |
| `--help` | `0` (prints help text to stdout) |

`main()` never calls `sys.exit` directly, so unit tests can observe
the return code without process-level side effects.

---

## 10. Error behavior

Expected errors are converted to a deterministic, human-readable
message on stdout and a non-zero exit code:

- `OSError` (e.g. missing file) → `error: <message>` + exit `1`.
- `ValueError` (e.g. unsupported schema version) → `error: <message>`
  + exit `1`.
- `TypeError` (e.g. malformed JSON shape) → `error: <message>` + exit
  `1`.
- Any other exception from the delegated workflow → `error:
  <ExceptionType>: <message>` + exit `1` (no traceback).

The CLI does not wrap or re-raise exceptions. The original exception
type and message are preserved in the output. Argparse-level errors
(invalid command, missing path, extra positionals) produce a
deterministic error on the program's stdout/stderr and exit `2`.

---

## 11. Deterministic output guarantees

All CLI output is deterministic:

- No timestamps.
- No UUIDs.
- No random values.
- No environment-dependent metadata.
- No progress animations or terminal colors.
- No third-party formatting libraries.

The output uses the standard library only. Repeated invocations on
the same input produce byte-identical output.

---

## 12. Dependency boundaries

The CLI must not import or use:

- `bpy`, `bpy.data`, `bpy.ops`
- `ai`, `ollama`, `ollama_client`
- `urllib`, `urllib.request`, `requests`, `http`
- `pipeline`
- `asset_registry`
- `scene_plan`
- any submodule of `toonflow_ai`
- `keyframe_insert`, `from_pydata`, `render_scene(`, direct
  rendering APIs

The CLI must not:

- Create or manipulate Blender objects.
- Insert keyframes.
- Configure render settings.
- Render anything directly.
- Perform schema migration itself.
- Parse project JSON itself (owned by `load_project`).
- Duplicate project validation.
- Duplicate replay orchestration.

These constraints are enforced by AST-based tests in
`tests/test_project_cli.py`.

---

## 13. Testing strategy

The CLI is tested by `tests/test_project_cli.py` (70 tests). The
tests use dependency injection to avoid Blender, bpy, Ollama, a real
renderer, and a real AI server:

- **`PublicAPITests`** — `cli.main` is callable, the module entry
  point exists, and the existing workflow public surface is
  unchanged.
- **`ArgumentHandlingTests`** — missing command, unknown command,
  missing path, extra invalid arguments, and `--help`.
- **`ValidateCommandTests`** — success, current schema, migrated v1,
  output contents (name, version, shot count, validity message),
  invalid project, schema error, missing file, and that
  `replay_project` is never called.
- **`ShowCommandTests`** — success, output contents (name, version,
  description, shot count), shot ordering, deterministic shot
  details, no project mutation, no file modification, and that
  `replay_project` is never called.
- **`RunCommandTests`** — loads the project, delegates exactly once
  to `replay_project`, does not call lower-level workflow
  functions, output includes project name and shot count, output
  paths preserve result order, replay error returns non-zero,
  loading failure prevents replay, repeated equivalent runs
  delegate equivalently, the loaded project is forwarded to
  replay, and the default `replay_project` routes through the
  real workflow chain.
- **`DependencyInjectionTests`** — fake `load_project` can be
  injected, fake `replay_project` can be injected, validate and
  show do not require `replay_project`, the default
  `load_project` loads a real file, and the CLI has no bpy /
  Ollama / networking dependency.
- **`ArchitectureTests`** — AST-based guard rails for the
  dependency boundaries listed above.

---

## 14. Known limitations

- The CLI does not stream progress or partial results. A long
  replay prints nothing until completion.
- The CLI does not support batch mode (multiple project files in
  one invocation). A future phase may add it.
- The CLI does not support a `--quiet` flag. Use shell redirection
  (`> /dev/null`) to silence stdout.
- The CLI does not support a `--json` output mode. A future phase
  may add it for machine consumption.
- The CLI does not validate the existence of the project file
  before calling `load_project`; semantic path validation is owned
  by `load_project`.

---

## 15. Non-features (intentionally NOT implemented)

- Job queue or batch history.
- Parallel or concurrent project execution.
- Retry logic on transient failures.
- Progress bars or spinners.
- Terminal colors or rich formatting.
- JSON output mode.
- Config files (e.g. `.toonflow.toml`).
- Environment variable overrides.
- Plugin / hook system.
- Interactive prompts.
- File watching or hot-reload.
- Network access (no Ollama, no HTTP, no remote project fetching).
- Direct Blender manipulation.

---

## 16. Example commands

Validate a project file:

```
python -m workflow validate project.json
```

Output:

```
Project is valid
Name: demo_project
Schema version: 2
Shots: 3
```

Show a project summary:

```
python -m workflow show project.json
```

Output:

```
Name: demo_project
Schema version: 2
Description: A short story in three shots
Shots: 3
Shot 0: concept='A husband waves in a living room' animation=None lip_sync=False output_path=None
Shot 1: concept='A wife smiles in the same room' animation='wave' lip_sync=False output_path='/tmp/shot_1.png'
Shot 2: concept='They share a quiet moment' animation=None lip_sync=True output_path=None
```

Run (replay) a project:

```
python -m workflow run project.json
```

Output:

```
Project: demo_project
Shots: 3
Shot 0: output_path='/renders/shot_0.png'
Shot 1: output_path='/renders/shot_1.png'
Shot 2: output_path='/renders/shot_2.png'
```

Programmatic use (for tests and embedding):

```python
from workflow.cli import main

rc = main(["validate", "project.json"])
assert rc == 0

rc = main(["run", "project.json"], stdout=my_buffer)
assert rc == 0
```
