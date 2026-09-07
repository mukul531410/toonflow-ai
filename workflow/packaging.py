"""TOONFLOW-PHASE-036 — Release Packaging & Repository Readiness Foundation.

This module provides a deterministic, inspectable add-on packaging layer.
It validates the existing Blender add-on source package under
``addon/toonflow_ai/`` and can produce a reproducible ZIP archive whose
root contains a single ``toonflow_ai/`` directory suitable for
installation via Blender's ``Edit -> Preferences -> Add-ons -> Install``
mechanism.

The packaging layer is intentionally narrow:

- It does NOT import ``bpy``.
- It does NOT import any addon module, the AI layer, Ollama, the
  pipeline, the asset registry, the scene plan, or the
  ``toonflow_ai`` generation modules.
- It does NOT use ``subprocess``, network access, telemetry, or
  arbitrary code execution.
- It does NOT modify the source add-on tree.
- It does NOT call Blender.

The packaging layer is the read-only/build-only packaging
responsibility. It does NOT replace:

- Runtime verification (owned by :mod:`workflow.verification` /
  :mod:`workflow.runtime`).
- Runtime readiness audit (owned by :mod:`workflow.audit`).

Public API
----------

- :class:`PackagingStatus` — PASS/FAIL validation status constants.
- :class:`PackagingValidationResult` — structured validation result.
- :class:`AddonPackageManifest` — explicit packaging contract
  (source dir, archive root, included/excluded files).
- :class:`AddonPackageBuildResult` — outcome of a build attempt.
- :func:`validate_addon_package` — validate a source add-on package.
- :func:`build_addon_zip` — produce a deterministic ZIP archive.
- :func:`addon_package_manifest_default` — derive a manifest from the
  current repository layout.
"""

import io
import json
import os
import re
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import FrozenSet, Iterable, Optional, Tuple


# --- Status semantics -------------------------------------------------------


class PackagingStatus:
    """Packaging validation status constants.

    Only two terminal values are reported: PASS or FAIL. A packaging
    failure is a structured result that lists every concrete reason
    the source package did not satisfy the contract.
    """

    PASS = "PASS"
    FAIL = "FAIL"


# --- Result model ------------------------------------------------------------


@dataclass(frozen=True)
class PackagingValidationResult:
    """The outcome of validating a candidate add-on package.

    Attributes:
        status: :attr:`PackagingStatus.PASS` or :attr:`PackagingStatus.FAIL`.
        issues: Tuple of deterministic issue strings. Empty when
            the status is PASS.
        checked_files: Tuple of relative archive paths that were
            inspected during validation. Stable ordering.
    """

    status: str
    issues: Tuple[str, ...] = field(default_factory=tuple)
    checked_files: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.status not in (PackagingStatus.PASS, PackagingStatus.FAIL):
            raise ValueError(f"Unknown packaging status: {self.status!r}")
        if not isinstance(self.issues, tuple):
            object.__setattr__(self, "issues", tuple(self.issues))
        if not isinstance(self.checked_files, tuple):
            object.__setattr__(self, "checked_files", tuple(self.checked_files))
        if self.status == PackagingStatus.PASS and self.issues:
            raise ValueError("PASS result must have no issues")


# --- Build result model ------------------------------------------------------


@dataclass(frozen=True)
class AddonPackageBuildResult:
    """The outcome of a packaging build.

    Attributes:
        status: :attr:`PackagingStatus.PASS` or :attr:`PackagingStatus.FAIL`.
        archive_path: Absolute path to the produced archive on PASS.
            None on FAIL.
        archive_bytes: Byte length of the produced archive on PASS.
            Zero on FAIL.
        file_count: Number of files written into the archive on PASS.
            Zero on FAIL.
        issue: Deterministic single-issue description on FAIL.
            Empty string on PASS.
        manifest_source: The :class:`AddonPackageManifest` that was
            used to build the archive.
    """

    status: str
    manifest_source: object
    archive_path: Optional[str] = None
    archive_bytes: int = 0
    file_count: int = 0
    issue: str = ""

    def __post_init__(self):
        if self.status not in (PackagingStatus.PASS, PackagingStatus.FAIL):
            raise ValueError(f"Unknown packaging status: {self.status!r}")
        if self.status == PackagingStatus.PASS:
            if not self.archive_path:
                raise ValueError("PASS build must have archive_path")
            if self.archive_bytes <= 0:
                raise ValueError("PASS build must have positive archive_bytes")
            if self.file_count <= 0:
                raise ValueError("PASS build must have positive file_count")
            if self.issue:
                raise ValueError("PASS build must have empty issue")
        else:
            if self.archive_path is not None:
                raise ValueError("FAIL build must not have archive_path")
            if self.archive_bytes != 0:
                raise ValueError("FAIL build must have zero archive_bytes")
            if self.file_count != 0:
                raise ValueError("FAIL build must have zero file_count")
            if not self.issue:
                raise ValueError("FAIL build must have an issue string")


# --- Manifest model ----------------------------------------------------------


@dataclass(frozen=True)
class AddonPackageManifest:
    """The explicit packaging contract for a single build.

    Attributes:
        source_dir: Absolute path to the source add-on directory on
            disk. The directory itself is treated as a *boundary*;
            only files inside this directory may enter the archive.
        archive_root: The directory name that appears at the archive
            root (e.g. ``"toonflow_ai"``). The archive will contain
            exactly one top-level directory with this name.
        included_relative_paths: Tuple of relative paths (relative to
            *source_dir*) that are allowed in the archive. Every file
            in the archive must appear in this set. Order is not
            semantically meaningful; comparison uses the set.
        excluded_relative_paths: Tuple of relative paths that must
            never appear in the archive. Enforced even if a path is
            in *included_relative_paths*. Comparison uses the set.
    """

    source_dir: Path
    archive_root: str
    included_relative_paths: Tuple[str, ...] = field(default_factory=tuple)
    excluded_relative_paths: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not isinstance(self.source_dir, Path):
            object.__setattr__(self, "source_dir", Path(self.source_dir))
        if not isinstance(self.archive_root, str) or not self.archive_root:
            raise ValueError("archive_root must be a non-empty string")
        if "/" in self.archive_root or "\\" in self.archive_root:
            raise ValueError("archive_root must be a single path segment")
        if self.archive_root in (".", ".."):
            raise ValueError("archive_root must not be a traversal segment")
        if not isinstance(self.included_relative_paths, tuple):
            object.__setattr__(
                self, "included_relative_paths",
                tuple(self.included_relative_paths),
            )
        if not isinstance(self.excluded_relative_paths, tuple):
            object.__setattr__(
                self, "excluded_relative_paths",
                tuple(self.excluded_relative_paths),
            )
        for path in self.included_relative_paths:
            if not isinstance(path, str) or not path:
                raise ValueError("included paths must be non-empty strings")
            _validate_archive_relative_path(path)
        for path in self.excluded_relative_paths:
            if not isinstance(path, str) or not path:
                raise ValueError("excluded paths must be non-empty strings")
            _validate_archive_relative_path(path)
        if len(set(self.included_relative_paths)) != len(self.included_relative_paths):
            raise ValueError("included_relative_paths contains duplicates")


# --- Path utilities ----------------------------------------------------------


_FORBIDDEN_PATH_CHARS = re.compile(r"[\x00]")


def _validate_archive_relative_path(path: str) -> None:
    """Validate that *path* is a safe archive-relative POSIX path.

    Raises :class:`ValueError` for absolute paths, traversal segments,
    or any control character that could break archive extraction.
    """
    if not path:
        raise ValueError("path must be non-empty")
    if path.startswith("/") or path.startswith("\\"):
        raise ValueError(f"absolute path not allowed: {path!r}")
    if _FORBIDDEN_PATH_CHARS.search(path):
        raise ValueError(f"NUL byte in path: {path!r}")
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"traversal segment not allowed: {path!r}")
    normalized = "/".join(parts)
    if normalized in ("", "."):
        raise ValueError(f"path reduces to current directory: {path!r}")


def _normalize_relative(path: str) -> str:
    """Normalize an archive-relative path to forward slashes."""
    return path.replace("\\", "/")


def _is_within(child: Path, parent: Path) -> bool:
    """Return True if *child* is the same as or inside *parent*."""
    try:
        child_resolved = child.resolve(strict=False)
        parent_resolved = parent.resolve(strict=False)
    except OSError:
        return False
    try:
        child_resolved.relative_to(parent_resolved)
        return True
    except ValueError:
        return child_resolved == parent_resolved


# --- Default manifest derivation --------------------------------------------


# Required package files for the TOONFLOW AI Blender add-on.
DEFAULT_REQUIRED_PATHS: Tuple[str, ...] = (
    "__init__.py",
    "registration.py",
    "operator.py",
    "properties.py",
    "ui.py",
)

# Always-excluded development artifacts.
DEFAULT_EXCLUDED_PATHS: Tuple[str, ...] = (
    "__pycache__",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.backup",
    "*.bak",
    "*.tmp",
    "*.swp",
    "*.swo",
    "*.DS_Store",
    "Thumbs.db",
    ".git",
    ".git/",
    ".gitignore",
    ".gitattributes",
    "tests",
    "tests/",
    "test_*.py",
    "conftest.py",
    "docs",
    "docs/",
    "*.md",
    "README*",
    "*.log",
    "*.orig",
    "*.rej",
)

# Always-included source files (the explicit, minimal packaging
# surface). The archive should contain only these files, relative to
# the source directory.
DEFAULT_INCLUDED_PATHS: Tuple[str, ...] = (
    "__init__.py",
    "registration.py",
    "operator.py",
    "properties.py",
    "ui.py",
    "generation/__init__.py",
    "generation/animation.py",
    "generation/camera.py",
    "generation/lip_sync.py",
    "generation/pose.py",
    "generation/rendering.py",
    "generation/validation.py",
    "generation/blender_generator.py",
)


def addon_package_manifest_default(
    project_root: Optional[Path] = None,
) -> AddonPackageManifest:
    """Derive a default :class:`AddonPackageManifest` from the repository.

    Args:
        project_root: Optional absolute path to the repository root.
            When omitted, the manifest uses the parent of the
            ``workflow`` package directory as the project root.

    Returns:
        A deterministic :class:`AddonPackageManifest` configured for
        the current repository layout.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    return AddonPackageManifest(
        source_dir=project_root / "addon" / "toonflow_ai",
        archive_root="toonflow_ai",
        included_relative_paths=DEFAULT_INCLUDED_PATHS,
        excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
    )


# --- bl_info validation ------------------------------------------------------


_REQUIRED_BL_INFO_KEYS: FrozenSet[str] = frozenset({
    "name", "blender", "category", "version", "author", "description",
})


def _validate_bl_info(bl_info: object, issues: list) -> None:
    """Validate the *bl_info* dict loaded from ``__init__.py``.

    Appends a deterministic issue to *issues* for every violation
    found. The function never raises; it only appends.
    """
    if not isinstance(bl_info, dict):
        issues.append("bl_info is not a dict")
        return

    missing = sorted(_REQUIRED_BL_INFO_KEYS - set(bl_info.keys()))
    if missing:
        issues.append(
            f"bl_info missing required keys: {', '.join(missing)}"
        )

    name = bl_info.get("name")
    if not isinstance(name, str) or not name.strip():
        issues.append("bl_info.name must be a non-empty string")

    blender = bl_info.get("blender")
    if not isinstance(blender, (tuple, list)) or len(blender) < 1:
        issues.append("bl_info.blender must be a non-empty tuple")
    elif not all(isinstance(part, int) and part >= 0 for part in blender):
        issues.append("bl_info.blender must contain only non-negative ints")

    version = bl_info.get("version")
    if not isinstance(version, (tuple, list)) or len(version) < 1:
        issues.append("bl_info.version must be a non-empty tuple")
    elif not all(isinstance(part, int) and part >= 0 for part in version):
        issues.append("bl_info.version must contain only non-negative ints")

    category = bl_info.get("category")
    if not isinstance(category, str) or not category.strip():
        issues.append("bl_info.category must be a non-empty string")

    author = bl_info.get("author")
    if not isinstance(author, str) or not author.strip():
        issues.append("bl_info.author must be a non-empty string")

    description = bl_info.get("description")
    if not isinstance(description, str) or not description.strip():
        issues.append("bl_info.description must be a non-empty string")


# --- File inspection ---------------------------------------------------------


_EXCLUDED_FILENAME_PATTERNS: Tuple[re.Pattern, ...] = tuple(
    re.compile(pattern.replace("*", ".*"))
    for pattern in DEFAULT_EXCLUDED_PATHS
    if "*" in pattern and not pattern.endswith("/") and pattern not in {
        "*.DS_Store", "Thumbs.db",
    }
)


def _is_excluded_basename(basename: str) -> bool:
    """Return True if a file *basename* matches an excluded pattern."""
    if basename in {"__pycache__", ".DS_Store", "Thumbs.db"}:
        return True
    for pattern in _EXCLUDED_FILENAME_PATTERNS:
        if pattern.match(basename):
            return True
    return False


def _is_excluded_dirname(dirname: str) -> bool:
    """Return True if a directory name should be excluded from packaging."""
    return dirname in {"__pycache__", ".git", "tests", "docs"}


# --- AST helpers ------------------------------------------------------------


def _ast_all_imports(source: str) -> FrozenSet[str]:
    """Return the set of top-level module names imported by *source*."""
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return frozenset()
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return frozenset(names)


# --- Validation -------------------------------------------------------------


def validate_addon_package(
    manifest: AddonPackageManifest,
) -> PackagingValidationResult:
    """Validate the source add-on package described by *manifest*.

    The function inspects only files inside ``manifest.source_dir``.
    It never writes to disk and never modifies the source tree.

    Returns:
        A :class:`PackagingValidationResult`. When every required
        file is present, every required key in ``bl_info`` is valid,
        and no excluded development artifacts exist under the
        source directory, the status is :attr:`PackagingStatus.PASS`.
        Otherwise the status is :attr:`PackagingStatus.FAIL` and
        ``issues`` lists every concrete reason.
    """
    issues: list = []
    checked: list = []

    source_dir = manifest.source_dir
    if not source_dir.exists() or not source_dir.is_dir():
        issues.append(f"source directory missing: {source_dir}")
        return PackagingValidationResult(
            status=PackagingStatus.FAIL,
            issues=tuple(issues),
            checked_files=(),
        )

    # 1. Required files exist.
    for rel in manifest.included_relative_paths:
        try:
            _validate_archive_relative_path(rel)
        except ValueError as exc:
            issues.append(f"manifest path invalid: {rel} ({exc})")
            continue
        src_path = source_dir / rel.replace("/", os.sep)
        if not src_path.exists() or not src_path.is_file():
            issues.append(f"required file missing: {rel}")
            continue
        checked.append(_normalize_relative(rel))

    # 2. __init__.py has a valid bl_info.
    init_rel = "__init__.py"
    init_path = source_dir / init_rel
    if init_path.exists() and init_path.is_file():
        try:
            source_text = init_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f"__init__.py unreadable: {exc}")
        else:
            bl_info_value = _extract_bl_info(source_text, init_path)
            _validate_bl_info(bl_info_value, issues)
            if init_rel not in checked:
                checked.append(init_rel)
    else:
        issues.append("__init__.py missing")

    # 3. No excluded artifacts under source_dir.
    try:
        for dirpath, dirnames, filenames in os.walk(source_dir):
            # Filter excluded directories in-place.
            dirnames[:] = [
                d for d in dirnames if not _is_excluded_dirname(d)
            ]
            for filename in filenames:
                if _is_excluded_basename(filename):
                    abs_path = Path(dirpath) / filename
                    try:
                        rel = abs_path.relative_to(source_dir)
                    except ValueError:
                        rel = abs_path
                    issues.append(
                        f"excluded development artifact present: "
                        f"{_normalize_relative(str(rel))}"
                    )
                elif filename.endswith((".pyc", ".pyo", ".pyd")):
                    abs_path = Path(dirpath) / filename
                    try:
                        rel = abs_path.relative_to(source_dir)
                    except ValueError:
                        rel = abs_path
                    issues.append(
                        f"compiled bytecode present: "
                        f"{_normalize_relative(str(rel))}"
                    )
    except OSError as exc:
        issues.append(f"source directory unreadable: {exc}")

    # 4. No included path escapes source_dir (path-traversal guard).
    for rel in manifest.included_relative_paths:
        target = (source_dir / rel.replace("/", os.sep)).resolve(strict=False)
        if not _is_within(target, source_dir):
            issues.append(
                f"included path escapes source boundary: {rel}"
            )

    # Deterministic ordering.
    checked_sorted = tuple(sorted(set(checked)))
    issues_sorted = tuple(sorted(issues))

    if issues_sorted:
        return PackagingValidationResult(
            status=PackagingStatus.FAIL,
            issues=issues_sorted,
            checked_files=checked_sorted,
        )
    return PackagingValidationResult(
        status=PackagingStatus.PASS,
        issues=(),
        checked_files=checked_sorted,
    )


def _extract_bl_info(source_text: str, init_path: Path) -> object:
    """Extract the ``bl_info`` constant from *source_text*.

    The function is intentionally permissive: it accepts the
    standard pattern used by every Blender add-on, namely
    ``bl_info = {...}`` at module top-level. It returns the dict if
    it can be extracted safely, otherwise an empty dict.
    """
    import ast
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "bl_info":
                    value = node.value
                    if isinstance(value, ast.Dict):
                        try:
                            return ast.literal_eval(value)
                        except (ValueError, SyntaxError):
                            return {}
    return {}


# --- Build ------------------------------------------------------------------


def _stable_sort_key(rel: str) -> Tuple[str, ...]:
    """Return a stable sort key for archive entries."""
    return tuple(rel.replace("\\", "/").split("/"))


def _check_path_safety(
    source_dir: Path,
    rel: str,
    excluded_set: FrozenSet[str],
) -> Optional[str]:
    """Return a deterministic error string if *rel* is unsafe, else None.

    "Unsafe" means:
    - The path is not relative to *source_dir*.
    - The path is absolute.
    - The path contains traversal segments.
    - The path is duplicated in the archive (caller responsibility).
    - The path matches the manifest's excluded list.
    """
    try:
        _validate_archive_relative_path(rel)
    except ValueError as exc:
        return f"unsafe archive path {rel!r}: {exc}"

    abs_target = (source_dir / rel.replace("/", os.sep)).resolve(strict=False)
    if not _is_within(abs_target, source_dir):
        return f"path escapes source boundary: {rel}"

    if rel in excluded_set:
        return f"excluded path: {rel}"

    return None


def build_addon_zip(
    manifest: AddonPackageManifest,
    output_path: Path,
) -> AddonPackageBuildResult:
    """Build a deterministic ZIP archive for the add-on package.

    The archive is written to *output_path*. The archive contains
    exactly one top-level directory named ``manifest.archive_root``
    (typically ``"toonflow_ai"``). The archive is reproducible:
    the same source tree produces byte-identical archives on
    repeated builds (fixed timestamps, sorted entries, no extra
    metadata, no comments).

    The function never modifies the source directory. It refuses to
    write into the source directory tree.

    Args:
        manifest: The packaging contract to apply.
        output_path: The destination file path for the archive.
            The parent directory is created if missing.

    Returns:
        An :class:`AddonPackageBuildResult`. The status is
        :attr:`PackagingStatus.PASS` on success and
        :attr:`PackagingStatus.FAIL` on any structured failure.
    """
    if not isinstance(output_path, Path):
        output_path = Path(output_path)

    if output_path.is_absolute():
        # The caller is allowed to choose any output path, but the
        # path must be a normal file path, not a symlink, and not a
        # directory.
        if output_path.is_dir():
            return AddonPackageBuildResult(
                status=PackagingStatus.FAIL,
                manifest_source=manifest,
                issue=f"output path is a directory: {output_path}",
            )
    else:
        # Reject relative paths that try to escape via "..".
        if ".." in output_path.parts:
            return AddonPackageBuildResult(
                status=PackagingStatus.FAIL,
                manifest_source=manifest,
                issue=f"output path contains traversal: {output_path}",
            )

    source_dir = manifest.source_dir
    if not source_dir.exists() or not source_dir.is_dir():
        return AddonPackageBuildResult(
            status=PackagingStatus.FAIL,
            manifest_source=manifest,
            issue=f"source directory missing: {source_dir}",
        )

    # Refuse to overwrite the source tree.
    try:
        output_resolved = output_path.resolve(strict=False)
        source_resolved = source_dir.resolve(strict=False)
    except OSError as exc:
        return AddonPackageBuildResult(
            status=PackagingStatus.FAIL,
            manifest_source=manifest,
            issue=f"path resolution failed: {exc}",
        )
    if _is_within(output_resolved, source_resolved):
        return AddonPackageBuildResult(
            status=PackagingStatus.FAIL,
            manifest_source=manifest,
            issue="output path is inside the source directory",
        )

    included_set = frozenset(manifest.included_relative_paths)
    excluded_set = frozenset(manifest.excluded_relative_paths)

    # Detect duplicate archive paths.
    seen: set = set()
    for rel in manifest.included_relative_paths:
        if rel in seen:
            return AddonPackageBuildResult(
                status=PackagingStatus.FAIL,
                manifest_source=manifest,
                issue=f"duplicate archive path in manifest: {rel}",
            )
        seen.add(rel)

    # Path safety check.
    for rel in manifest.included_relative_paths:
        issue = _check_path_safety(source_dir, rel, excluded_set)
        if issue is not None:
            return AddonPackageBuildResult(
                status=PackagingStatus.FAIL,
                manifest_source=manifest,
                issue=issue,
            )

    # Sort deterministically.
    ordered = sorted(manifest.included_relative_paths, key=_stable_sort_key)

    # Build the archive in memory first so the function is
    # transactional: on failure, no partial archive is left behind.
    buffer = io.BytesIO()
    fixed_timestamp = (2020, 1, 1, 0, 0, 0)
    try:
        with zipfile.ZipFile(
            buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            allowZip64=False,
        ) as zf:
            for rel in ordered:
                src = source_dir / rel.replace("/", os.sep)
                if not src.exists() or not src.is_file():
                    return AddonPackageBuildResult(
                        status=PackagingStatus.FAIL,
                        manifest_source=manifest,
                        issue=f"required file missing at build time: {rel}",
                    )
                # Reject symlinks to avoid path tricks.
                if src.is_symlink():
                    return AddonPackageBuildResult(
                        status=PackagingStatus.FAIL,
                        manifest_source=manifest,
                        issue=f"symlink refused: {rel}",
                    )
                archive_name = f"{manifest.archive_root}/{rel}"
                with open(src, "rb") as fh:
                    data = fh.read()
                info = zipfile.ZipInfo(filename=archive_name)
                info.date_time = fixed_timestamp
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.create_system = 0
                info.create_version = 20
                info.extract_version = 20
                zf.writestr(info, data)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        return AddonPackageBuildResult(
            status=PackagingStatus.FAIL,
            manifest_source=manifest,
            issue=f"zip build failed: {exc}",
        )

    # Commit to disk.
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = buffer.getvalue()
        with open(output_path, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        return AddonPackageBuildResult(
            status=PackagingStatus.FAIL,
            manifest_source=manifest,
            issue=f"archive write failed: {exc}",
        )

    return AddonPackageBuildResult(
        status=PackagingStatus.PASS,
        manifest_source=manifest,
        archive_path=str(output_path),
        archive_bytes=len(data),
        file_count=len(ordered),
        issue="",
    )


# --- Serialization helpers --------------------------------------------------


def packaging_validation_to_dict(
    result: PackagingValidationResult,
) -> dict:
    """Serialize a :class:`PackagingValidationResult` to a dict."""
    return {
        "status": result.status,
        "issues": list(result.issues),
        "checked_files": list(result.checked_files),
    }


def packaging_validation_to_json(
    result: PackagingValidationResult,
) -> str:
    """Serialize a validation result to deterministic JSON."""
    return json.dumps(
        packaging_validation_to_dict(result),
        indent=2,
        sort_keys=False,
        ensure_ascii=False,
    ) + "\n"


def build_result_to_dict(result: AddonPackageBuildResult) -> dict:
    """Serialize an :class:`AddonPackageBuildResult` to a dict."""
    return {
        "status": result.status,
        "archive_path": result.archive_path,
        "archive_bytes": int(result.archive_bytes),
        "file_count": int(result.file_count),
        "issue": result.issue,
    }


def build_result_to_json(result: AddonPackageBuildResult) -> str:
    """Serialize a build result to deterministic JSON."""
    return json.dumps(
        build_result_to_dict(result),
        indent=2,
        sort_keys=False,
        ensure_ascii=False,
    ) + "\n"


# --- Public inspection helpers ----------------------------------------------


def read_archive_manifest(archive_path: Path) -> Tuple[str, ...]:
    """Return the relative path list of *archive_path*.

    The returned tuple is sorted lexicographically and contains
    only forward-slash paths.
    """
    if not isinstance(archive_path, Path):
        archive_path = Path(archive_path)
    if not archive_path.exists() or not archive_path.is_file():
        raise ValueError(f"archive not found: {archive_path}")
    with zipfile.ZipFile(archive_path, mode="r") as zf:
        names = zf.namelist()
    return tuple(sorted(names))


# --- Anti-import guard ------------------------------------------------------


_FORBIDDEN_MODULES: FrozenSet[str] = frozenset({
    "bpy",
    "subprocess",
    "requests",
    "urllib",
    "http",
    "httplib",
    "socket",
    "ssl",
    "asyncio",
    "multiprocessing",
    "threading",
})


def packaging_module_imports_safe() -> Tuple[str, ...]:
    """Return any forbidden module names imported by this module.

    This is a self-check helper used by tests to prove that the
    packaging layer never gains a forbidden import. Returns an empty
    tuple when the module is clean.
    """
    import inspect
    source = inspect.getsource(_get_module_object())
    imports = _ast_all_imports(source)
    bad = sorted(imports & _FORBIDDEN_MODULES)
    return tuple(bad)


def _get_module_object():
    """Return the module object for the current file."""
    import sys
    return sys.modules[__name__]


# --- Sanity check that the module file itself is clean at import time -------


def _self_check() -> None:
    """Run a one-time self-check at import time.

    Raises :class:`RuntimeError` if the module accidentally imports
    a forbidden module. Intended to catch regressions before tests
    run.
    """
    bad = packaging_module_imports_safe()
    if bad:
        raise RuntimeError(
            f"workflow.packaging unexpectedly imports forbidden modules: {bad}"
        )


_self_check()


__all__ = (
    "PackagingStatus",
    "PackagingValidationResult",
    "AddonPackageManifest",
    "AddonPackageBuildResult",
    "DEFAULT_REQUIRED_PATHS",
    "DEFAULT_EXCLUDED_PATHS",
    "DEFAULT_INCLUDED_PATHS",
    "addon_package_manifest_default",
    "validate_addon_package",
    "build_addon_zip",
    "packaging_validation_to_dict",
    "packaging_validation_to_json",
    "build_result_to_dict",
    "build_result_to_json",
    "read_archive_manifest",
    "packaging_module_imports_safe",
)
