# Release Packaging & Repository Readiness Foundation

> TOONFLOW-PHASE-036 — Release Packaging & Repository Readiness Foundation

This document describes the deterministic, inspectable release-packaging
foundation for the TOONFLOW AI Blender add-on. The packaging layer turns
the existing source add-on package into a reproducible ZIP archive
whose root contains a single `toonflow_ai/` directory, suitable for
installation via Blender's **Edit → Preferences → Add-ons → Install**
mechanism.

This phase is NOT a public release/publishing system. It does not
upload archives anywhere, does not interact with the Blender
Extension platform, and does not perform any network operations.

## Package source directory

The packaging layer reads from:

```text
addon/toonflow_ai/
    __init__.py            # contains bl_info
    registration.py
    operator.py
    properties.py
    ui.py
    generation/
        __init__.py
        animation.py
        camera.py
        lip_sync.py
        pose.py
        rendering.py
        validation.py
        blender_generator.py
```

The source directory is treated as a hard boundary. The packaging
layer never reads or writes anything outside it.

## Archive root structure

Every produced archive has exactly one top-level directory named
`toonflow_ai/`. The archive contains a curated, minimal file set:

```text
toonflow_ai/
    __init__.py
    registration.py
    operator.py
    properties.py
    ui.py
    generation/
        __init__.py
        animation.py
        camera.py
        lip_sync.py
        pose.py
        rendering.py
        validation.py
        blender_generator.py
```

## Included and excluded files

### Included

The packaging contract explicitly includes the source files listed
above. Every other file under the source directory is excluded by
the default manifest.

### Excluded

The default manifest excludes every development artifact. The
exclusion list is applied both as a manifest contract and as a
validation scan:

- `__pycache__/` directories
- `*.pyc`, `*.pyo`, `*.pyd` compiled bytecode
- `*.backup`, `*.bak`, `*.tmp`, `*.swp`, `*.swo` backup/temp files
- `*.DS_Store`, `Thumbs.db` OS metadata
- `.git/`, `.gitignore`, `.gitattributes` git metadata
- `tests/`, `test_*.py`, `conftest.py` test suite
- `docs/`, `*.md`, `README*` documentation
- `*.log`, `*.orig`, `*.rej` patch artifacts

The validator reports every concrete excluded artifact it finds under
the source directory.

## Deterministic packaging behavior

The packaging layer is reproducible. Given the same source tree, the
build produces byte-identical archives across runs.

Determinism is enforced by:

- A fixed ZIP entry timestamp (2020-01-01 00:00:00).
- A fixed ZIP external attribute (`S_IFREG | 0o644`).
- No ZIP comments or extra metadata.
- Fixed ZIP version stamps (`create_version=20`, `extract_version=20`).
- A fixed `create_system=0` (FAT).
- Sorted archive entries (lexicographic by path).
- No random identifiers, UUIDs, or environment-dependent values.

## Validation behavior

`workflow.packaging.validate_addon_package(manifest)` returns a
structured `PackagingValidationResult` with status PASS or FAIL.

On PASS, the result lists every file that was inspected.

On FAIL, the result lists every concrete issue. Validation checks
include:

- The source directory exists.
- Every required file (per the manifest) exists.
- `__init__.py` is present and contains a valid `bl_info` dict.
- `bl_info` contains all required keys (`name`, `blender`,
  `category`, `version`, `author`, `description`).
- `bl_info` types are correct (e.g. `blender` and `version` are
  non-empty tuples of non-negative integers).
- No excluded development artifacts exist under the source
  directory.
- No included path escapes the source boundary.

The validator never silently repairs invalid source packages. It
only reports structured failures.

## Path / security rules

The packaging layer rejects or prevents:

- Absolute archive paths (paths starting with `/` or `\`).
- Traversal segments (`..`) in any archive path.
- Duplicate archive paths in the manifest.
- Included paths that resolve outside the source directory.
- Symlinks inside the source directory.
- Output paths inside the source directory tree.
- Relative output paths that contain traversal segments.
- Output paths that are existing directories.

## Source immutability

The packaging layer never modifies the source add-on tree. It:

- Never rewrites source files.
- Never creates `__pycache__` inside the source package.
- Never modifies metadata.
- Never deletes or renames files.
- Never modifies docs or any other project state.

Generated archives are written to a caller-supplied output path
outside the source tree. Tests use temporary directories for every
generated archive.

## Layer separation

The packaging layer is the build-only packaging responsibility. It
does NOT replace:

- **Runtime verification** (owned by `workflow.verification` and
  `workflow.runtime`). Runtime verification executes a controlled
  Blender process to confirm the add-on registers and unregisters
  inside a real Blender runtime.
- **Runtime readiness audit** (owned by `workflow.audit`). The audit
  is a read-only, deterministic evaluation of repository state and
  never executes Blender or builds archives.

These three layers remain independent. Packaging never
auto-runs Blender; verification never produces a ZIP; audit never
produces a ZIP and never runs Blender.

## CLI usage

The `workflow` CLI exposes a `package-addon` subcommand:

```text
python -m workflow package-addon [--output PATH] [--json]
```

- `--output PATH` — Optional destination for the produced ZIP.
  When omitted, the default is `dist/toonflow_ai.zip` in the
  project root.
- `--json` — Emit the build result as deterministic JSON on
  stdout. Plain-text output is suppressed.

The command:

1. Derives the default packaging manifest.
2. Validates the source add-on package.
3. Builds the deterministic ZIP archive.
4. Reports the result (text or JSON) and returns exit code 0 on
   success or 1 on failure.

The command does not install software, does not access the network,
does not invoke Blender, does not invoke subprocess, does not send
telemetry, and does not execute arbitrary Python.

## Blender installation step remains separate

After the archive is built, the user installs it manually:

1. In Blender, open **Edit → Preferences → Add-ons**.
2. Select **Install**.
3. Choose the produced ZIP.
4. Enable **TOONFLOW AI** and then disable it again.

This is identical to the pre-existing installation procedure. The
packaging layer does not automate this step.

## Runtime verification remains separate

`workflow package-addon` never invokes Blender. Blender runtime
verification is owned by `workflow verify-blender` and remains
explicitly opt-in. The two commands are independent and may be run
in either order.

## API summary

| Symbol | Purpose |
| --- | --- |
| `PackagingStatus` | PASS / FAIL constants |
| `PackagingValidationResult` | Structured validation outcome |
| `AddonPackageManifest` | Explicit packaging contract |
| `AddonPackageBuildResult` | Structured build outcome |
| `validate_addon_package` | Validate the source add-on package |
| `build_addon_zip` | Produce a deterministic ZIP archive |
| `addon_package_manifest_default` | Derive a manifest from the repo |
| `read_archive_manifest` | List the entries of a produced archive |
| `packaging_module_imports_safe` | Self-check for forbidden imports |
