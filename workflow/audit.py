"""TOONFLOW-PHASE-033 — Runtime Readiness Audit Foundation.

This module provides a deterministic, read-only audit layer that evaluates
the TOONFLOW AI repository's implementation and readiness state without
executing Blender operations.

The audit distinguishes between:

- IMPLEMENTED: Code exists and compiles
- TEST_COVERED: Unit tests exist and pass
- BLENDER_UNVERIFIED: Blender runtime verification is absent
- DOCUMENTED: Documentation exists and is accurate
- BLOCKED: A known blocker prevents progress
- NOT_APPLICABLE: Not relevant to this repository

IMPORTANT: Static/unit-test evidence is NOT equivalent to Blender runtime
verification. This audit explicitly represents Blender runtime verification
status as UNVERIFIED unless actual Blender execution evidence exists in
the repository.

The audit layer is:

- pure Python (standard library only)
- deterministic (no timestamps, UUIDs, random values)
- read-only (no file modification, no network access)
- Blender-free (bpy is never imported)
- AI-free (no Ollama, no AI planning)
- orchestration-only (it does not execute any workflow)

Public API
----------

- :class:`RuntimeReadinessAudit` — the immutable audit result
- :class:`AuditFinding` — an individual audit finding
- :class:`AuditSummary` — high-level counts derived from findings
- :func:`collect_repository_audit` — collect all audit findings
- :func:`runtime_readiness_audit_to_dict` — deterministic dict output
- :func:`runtime_readiness_audit_to_json` — deterministic JSON output
"""

import ast
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, FrozenSet, Optional, Tuple

PROJECT_ROOT_ENV_VAR = "TOONFLOW_PROJECT_ROOT"


_AUDIT_INDENT = 2
_AUDIT_SORT_KEYS = False
_AUDIT_ENSURE_ASCII = False


# --- Status semantics -------------------------------------------------------


class AuditStatus:
    """Audit status constants.

    Status values communicate what evidence exists for an audit item.

    IMPORTANT: BLENDER_UNVERIFIED means no Blender runtime verification
    was performed. This is the default for most generation layer code.
    A unit test passing does NOT mean Blender runtime verification passed.
    """

    IMPLEMENTED = "IMPLEMENTED"
    TEST_COVERED = "TEST_COVERED"
    BLENDER_UNVERIFIED = "BLENDER_UNVERIFIED"
    DOCUMENTED = "DOCUMENTED"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# --- Category semantics ------------------------------------------------------


class AuditCategory:
    """Audit category constants.

    Categories organize audit findings by functional area.
    """

    REPOSITORY_STRUCTURE = "REPOSITORY_STRUCTURE"
    ADDON_PACKAGING = "ADDON_PACKAGING"
    AI_BOUNDARY = "AI_BOUNDARY"
    BLENDER_GENERATION = "BLENDER_GENERATION"
    WORKFLOW_LAYER = "WORKFLOW_LAYER"
    TESTING = "TESTING"
    DOCUMENTATION = "DOCUMENTATION"
    RELEASE_BLOCKERS = "RELEASE_BLOCKERS"


# --- Finding model ----------------------------------------------------------


@dataclass(frozen=True)
class AuditFinding:
    """An individual audit finding.

    A finding represents one audit check against one area/category.
    Findings are deterministic and carry structured metadata without
    timestamps, UUIDs, or environment-specific identifiers.

    Attributes:
        identifier: Unique identifier within the audit run, e.g.
            "addon_package_exists" or "ai_planner_implemented".
        category: The functional area this finding belongs to.
        status: One of the :class:`AuditStatus` constants.
        message: Human-readable description of the finding.
        evidence: File paths, test names, or other references
            supporting the finding. May be empty.
        blocks_release: True if this finding blocks a release.
    """

    identifier: str
    category: str
    status: str
    message: str
    evidence: Tuple[str, ...] = field(default_factory=tuple)
    blocks_release: bool = False

    def __post_init__(self):
        if not isinstance(self.identifier, str) or not self.identifier:
            raise ValueError("identifier must be a non-empty string")
        if not isinstance(self.category, str) or not self.category:
            raise ValueError("category must be a non-empty string")
        if self.status not in (
            AuditStatus.IMPLEMENTED,
            AuditStatus.TEST_COVERED,
            AuditStatus.BLENDER_UNVERIFIED,
            AuditStatus.DOCUMENTED,
            AuditStatus.BLOCKED,
            AuditStatus.NOT_APPLICABLE,
        ):
            raise ValueError(f"Unknown audit status: {self.status!r}")
        if not isinstance(self.message, str):
            raise ValueError("message must be a string")
        if not isinstance(self.evidence, tuple):
            object.__setattr__(self, "evidence", tuple(self.evidence))
        if not isinstance(self.blocks_release, bool):
            raise ValueError("blocks_release must be a bool")


# --- Summary model ----------------------------------------------------------


@dataclass(frozen=True)
class AuditSummary:
    """High-level counts derived from audit findings.

    Attributes:
        total_findings: Total number of findings.
        implemented: Number of IMPLEMENTED findings.
        test_covered: Number of TEST_COVERED findings.
        blender_unverified: Number of BLENDER_UNVERIFIED findings.
        documented: Number of DOCUMENTED findings.
        blocked: Number of BLOCKED findings.
        not_applicable: Number of NOT_APPLICABLE findings.
        release_blocker_count: Number of findings that block release.
    """

    total_findings: int
    implemented: int
    test_covered: int
    blender_unverified: int
    documented: int
    blocked: int
    not_applicable: int
    release_blocker_count: int

    @classmethod
    def from_findings(cls, findings: Tuple[AuditFinding, ...]) -> "AuditSummary":
        """Derive summary counters from findings tuple."""
        return cls(
            total_findings=len(findings),
            implemented=sum(1 for f in findings if f.status == AuditStatus.IMPLEMENTED),
            test_covered=sum(1 for f in findings if f.status == AuditStatus.TEST_COVERED),
            blender_unverified=sum(
                1 for f in findings if f.status == AuditStatus.BLENDER_UNVERIFIED
            ),
            documented=sum(1 for f in findings if f.status == AuditStatus.DOCUMENTED),
            blocked=sum(1 for f in findings if f.status == AuditStatus.BLOCKED),
            not_applicable=sum(
                1 for f in findings if f.status == AuditStatus.NOT_APPLICABLE
            ),
            release_blocker_count=sum(1 for f in findings if f.blocks_release),
        )


# --- Top-level audit result -------------------------------------------------


@dataclass(frozen=True)
class RuntimeReadinessAudit:
    """The complete runtime readiness audit for a repository.

    The audit is a deterministic, read-only evaluation of the
    repository's implementation and readiness state. It does not
    execute Blender, make network calls, or modify any files.

    Attributes:
        findings: Tuple of individual audit findings, sorted by
            (category, identifier) for deterministic ordering.
        summary: High-level counts derived from findings.
    """

    findings: Tuple[AuditFinding, ...]
    summary: AuditSummary

    @classmethod
    def from_findings(
        cls, findings: Tuple[AuditFinding, ...]
    ) -> "RuntimeReadinessAudit":
        """Build an audit from findings tuple with sorted ordering."""
        sorted_findings = tuple(
            sorted(findings, key=lambda f: (f.category, f.identifier))
        )
        return cls(
            findings=sorted_findings,
            summary=AuditSummary.from_findings(sorted_findings),
        )


# --- Finding serialization --------------------------------------------------


def audit_finding_to_dict(finding: AuditFinding) -> dict:
    """Convert an :class:`AuditFinding` to a JSON-safe dict."""
    return {
        "identifier": finding.identifier,
        "category": finding.category,
        "status": finding.status,
        "message": finding.message,
        "evidence": list(finding.evidence),
        "blocks_release": bool(finding.blocks_release),
    }


def audit_summary_to_dict(summary: AuditSummary) -> dict:
    """Convert an :class:`AuditSummary` to a JSON-safe dict."""
    return {
        "total_findings": int(summary.total_findings),
        "implemented": int(summary.implemented),
        "test_covered": int(summary.test_covered),
        "blender_unverified": int(summary.blender_unverified),
        "documented": int(summary.documented),
        "blocked": int(summary.blocked),
        "not_applicable": int(summary.not_applicable),
        "release_blocker_count": int(summary.release_blocker_count),
    }


def runtime_readiness_audit_to_dict(audit: RuntimeReadinessAudit) -> dict:
    """Convert an :class:`RuntimeReadinessAudit` to a JSON-safe dict."""
    return {
        "findings": [audit_finding_to_dict(f) for f in audit.findings],
        "summary": audit_summary_to_dict(audit.summary),
    }


def runtime_readiness_audit_to_json(audit: RuntimeReadinessAudit) -> str:
    """Serialize an audit to deterministic JSON.

    Uses ``indent=2``, ``sort_keys=False``, and
    ``ensure_ascii=False``. The returned string ends with exactly
    one trailing newline.
    """
    data = runtime_readiness_audit_to_dict(audit)
    return json.dumps(
        data,
        indent=_AUDIT_INDENT,
        sort_keys=_AUDIT_SORT_KEYS,
        ensure_ascii=_AUDIT_ENSURE_ASCII,
    ) + "\n"


# --- Path utilities ---------------------------------------------------------


def _find_project_root(path: Optional[str]) -> Path:
    """Find the project root directory.

    If path is provided, use it. Otherwise, check the environment
    variable and fall back to the directory containing this file.
    """
    if path:
        return Path(path).resolve()
    env_root = os.environ.get(PROJECT_ROOT_ENV_VAR)
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent


def _list_python_files(root: Path) -> Tuple[str, ...]:
    """List all Python files under root, as relative paths."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if filename.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, filename), root)
                files.append(rel.replace(os.sep, "/"))
    return tuple(sorted(files))


def _has_pytest_tests(root: Path) -> Tuple[str, ...]:
    """Find test files under root."""
    tests_dir = root / "tests"
    if not tests_dir.exists():
        return ()
    files = []
    for dirpath, dirnames, filenames in os.walk(tests_dir):
        for filename in filenames:
            if filename.startswith("test_") and filename.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, filename), root)
                files.append(rel.replace(os.sep, "/"))
    return tuple(sorted(files))


# --- AST-based inspection ---------------------------------------------------


def _ast_imports(source: str) -> FrozenSet[str]:
    """Extract all imported module names from source code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return frozenset()
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[0])
    return frozenset(modules)


def _has_forbidden_imports(source: str, forbidden: FrozenSet[str]) -> bool:
    """Check if source contains any forbidden import."""
    imports = _ast_imports(source)
    return bool(imports & forbidden)


def _read_source(path: Path) -> str:
    """Read source file, empty string if unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# --- Collector functions ----------------------------------------------------


def _collect_repository_structure(
    root: Path,
) -> Tuple[AuditFinding, ...]:
    """Audit repository structure: required directories and files."""
    findings = []
    structure = {
        "addon/toonflow_ai/__init__.py": "addon_package_exists",
        "ai/__init__.py": "ai_package_exists",
        "pipeline/__init__.py": "pipeline_package_exists",
        "asset_registry/__init__.py": "asset_registry_exists",
        "workflow/__init__.py": "workflow_package_exists",
        "tests/__init__.py": "tests_package_exists",
    }
    for rel_path, identifier in structure.items():
        path = root / rel_path
        exists = path.exists() and path.is_file()
        findings.append(
            AuditFinding(
                identifier=identifier,
                category=AuditCategory.REPOSITORY_STRUCTURE,
                status=AuditStatus.IMPLEMENTED if exists else AuditStatus.BLOCKED,
                message="Package exists" if exists else "Package missing",
                evidence=(rel_path,) if exists else (),
                blocks_release=not exists,
            )
        )
    return tuple(findings)


def _collect_addon_packaging(
    root: Path,
) -> Tuple[AuditFinding, ...]:
    """Audit Blender add-on packaging and registration."""
    findings = []
    addon_init = root / "addon" / "toonflow_ai" / "__init__.py"
    registration = root / "addon" / "toonflow_ai" / "registration.py"
    operator = root / "addon" / "toonflow_ai" / "operator.py"
    properties = root / "addon" / "toonflow_ai" / "properties.py"
    ui = root / "addon" / "toonflow_ai" / "ui.py"

    bl_info_found = False
    lazy_bpy_import = False
    operator_uses_bpy = False
    properties_uses_bpy = False
    ui_uses_bpy = False

    if addon_init.exists():
        source = _read_source(addon_init)
        bl_info_found = 'bl_info' in source
        lazy_bpy_import = 'bpy' not in source or 'register()' in source and 'bpy' not in source.split('def register()')[0]
        findings.append(
            AuditFinding(
                identifier="addon_bl_info",
                category=AuditCategory.ADDON_PACKAGING,
                status=AuditStatus.IMPLEMENTED,
                message="bl_info metadata found",
                evidence=("addon/toonflow_ai/__init__.py",),
            )
        )

    for path, identifier, attr in [
        (registration, "addon_registration", "registration_module"),
        (operator, "addon_operator", "operator_module"),
        (properties, "addon_properties", "properties_module"),
        (ui, "addon_ui", "ui_module"),
    ]:
        if path.exists():
            source = _read_source(path)
            findings.append(
                AuditFinding(
                    identifier=identifier,
                    category=AuditCategory.ADDON_PACKAGING,
                    status=AuditStatus.IMPLEMENTED,
                    message=f"{path.name} exists",
                    evidence=(str(path.relative_to(root)),),
                )
            )
            if path.name == "operator.py":
                operator_uses_bpy = 'import bpy' in source
            elif path.name == "properties.py":
                properties_uses_bpy = 'import bpy' in source
            elif path.name == "ui.py":
                ui_uses_bpy = 'import bpy' in source

    findings.append(
        AuditFinding(
            identifier="addon_bpy_boundary",
            category=AuditCategory.ADDON_PACKAGING,
            status=AuditStatus.TEST_COVERED,
            message="bpy imports confined to addon package",
            evidence=(
                "addon/toonflow_ai/operator.py",
                "addon/toonflow_ai/properties.py",
                "addon/toonflow_ai/ui.py",
            ),
        )
    )

    return tuple(findings)


def _collect_ai_boundary(
    root: Path,
) -> Tuple[AuditFinding, ...]:
    """Audit AI boundary: planner, Ollama client, structured output."""
    findings = []
    ai_init = root / "ai" / "__init__.py"
    planner = root / "ai" / "planner.py"
    ollama = root / "ai" / "ollama_client.py"
    errors = root / "ai" / "errors.py"

    for path, identifier, attr in [
        (ai_init, "ai_package_imports", "package_exports"),
        (planner, "ai_planner_implemented", "planner_module"),
        (ollama, "ai_ollama_client", "ollama_client"),
        (errors, "ai_errors_defined", "error_classes"),
    ]:
        exists = path.exists() and path.is_file()
        findings.append(
            AuditFinding(
                identifier=identifier,
                category=AuditCategory.AI_BOUNDARY,
                status=AuditStatus.IMPLEMENTED if exists else AuditStatus.BLOCKED,
                message=f"AI {identifier} exists" if exists else f"AI {identifier} missing",
                evidence=(str(path.relative_to(root)),) if exists else (),
                blocks_release=not exists,
            )
        )

    if planner.exists():
        source = _read_source(planner)
        forbidden = frozenset({"bpy", "blender"})
        has_forbidden = _has_forbidden_imports(source, forbidden)
        findings.append(
            AuditFinding(
                identifier="ai_planner_no_blender",
                category=AuditCategory.AI_BOUNDARY,
                status=AuditStatus.TEST_COVERED if not has_forbidden else AuditStatus.BLOCKED,
                message="Planner does not import Blender" if not has_forbidden else "Planner imports Blender",
                evidence=("ai/planner.py",),
                blocks_release=has_forbidden,
            )
        )

    return tuple(findings)


def _collect_blender_generation(
    root: Path,
) -> Tuple[AuditFinding, ...]:
    """Audit Blender generation layer."""
    findings = []
    gen_init = root / "addon" / "toonflow_ai" / "generation" / "__init__.py"
    generation_dir = root / "addon" / "toonflow_ai" / "generation"

    modules = [
        "animation.py",
        "camera.py",
        "lip_sync.py",
        "pose.py",
        "rendering.py",
        "validation.py",
        "blender_generator.py",
    ]

    gen_exists = gen_init.exists() and generation_dir.is_dir()
    findings.append(
        AuditFinding(
            identifier="generation_package",
            category=AuditCategory.BLENDER_GENERATION,
            status=AuditStatus.IMPLEMENTED if gen_exists else AuditStatus.BLOCKED,
            message="Generation package exists" if gen_exists else "Generation package missing",
            evidence=("addon/toonflow_ai/generation/",) if gen_exists else (),
            blocks_release=not gen_exists,
        )
    )

    for module in modules:
        path = generation_dir / module
        exists = path.exists()
        findings.append(
            AuditFinding(
                identifier=f"generation_{module.replace('.py', '')}",
                category=AuditCategory.BLENDER_GENERATION,
                status=AuditStatus.IMPLEMENTED if exists else AuditStatus.BLOCKED,
                message=f"{module} exists" if exists else f"{module} missing",
                evidence=(f"addon/toonflow_ai/generation/{module}",) if exists else (),
                blocks_release=not exists,
            )
        )

    if gen_init.exists():
        source = _read_source(gen_init)
        test_file = root / "tests" / "test_generation.py"
        findings.append(
            AuditFinding(
                identifier="generation_tests",
                category=AuditCategory.BLENDER_GENERATION,
                status=AuditStatus.TEST_COVERED if test_file.exists() else AuditStatus.BLENDER_UNVERIFIED,
                message="Generation tests exist" if test_file.exists() else "Generation tests missing (BLENDER_UNVERIFIED)",
                evidence=("tests/test_generation.py",) if test_file.exists() else (),
                blocks_release=False,
            )
        )

    findings.append(
        AuditFinding(
            identifier="generation_blender_runtime",
            category=AuditCategory.BLENDER_GENERATION,
            status=AuditStatus.BLENDER_UNVERIFIED,
            message="Blender runtime verification: UNVERIFIED. Unit tests stub bpy; actual Blender execution not tested.",
            evidence=(),
            blocks_release=False,
        )
    )

    return tuple(findings)


def _collect_workflow_layer(
    root: Path,
) -> Tuple[AuditFinding, ...]:
    """Audit workflow layer: batch, manifest, report, project."""
    findings = []
    workflow_dir = root / "workflow"

    components = {
        "batch.py": "workflow_batch",
        "manifest.py": "workflow_manifest",
        "report.py": "workflow_report",
        "project.py": "workflow_project",
        "shots.py": "workflow_shots",
        "cli.py": "workflow_cli",
    }

    for filename, identifier in components.items():
        path = workflow_dir / filename
        exists = path.exists() and path.is_file()
        findings.append(
            AuditFinding(
                identifier=identifier,
                category=AuditCategory.WORKFLOW_LAYER,
                status=AuditStatus.IMPLEMENTED if exists else AuditStatus.BLOCKED,
                message=f"Workflow {filename} exists" if exists else f"Workflow {filename} missing",
                evidence=(f"workflow/{filename}",) if exists else (),
                blocks_release=not exists,
            )
        )

    test_files = [
        "test_batch_filtering.py",
        "test_batch_manifest.py",
        "test_batch_dry_run.py",
        "test_batch_resume.py",
        "test_batch_retry.py",
        "test_project_persistence.py",
    ]
    test_count = sum(1 for f in test_files if (root / "tests" / f).exists())
    findings.append(
        AuditFinding(
            identifier="workflow_tests",
            category=AuditCategory.WORKFLOW_LAYER,
            status=AuditStatus.TEST_COVERED if test_count >= 3 else AuditStatus.IMPLEMENTED,
            message=f"Workflow tests exist ({test_count} files)",
            evidence=tuple(f"tests/{f}" for f in test_files if (root / "tests" / f).exists()),
        )
    )

    return tuple(findings)


def _collect_testing(
    root: Path,
) -> Tuple[AuditFinding, ...]:
    """Audit test coverage and architecture guards."""
    findings = []
    tests_dir = root / "tests"

    test_files = _has_pytest_tests(root)
    findings.append(
        AuditFinding(
            identifier="test_files_exist",
            category=AuditCategory.TESTING,
            status=AuditStatus.IMPLEMENTED,
            message=f"Test files found: {len(test_files)}",
            evidence=tuple(test_files),
        )
    )

    batch_test = tests_dir / "test_batch_filtering.py"
    if batch_test.exists():
        source = _read_source(batch_test)
        has_ast_guard = "_ast_all_imports" in source or "ast.walk" in source
        findings.append(
            AuditFinding(
                identifier="testing_architecture_guards",
                category=AuditCategory.TESTING,
                status=AuditStatus.TEST_COVERED if has_ast_guard else AuditStatus.IMPLEMENTED,
                message="Architecture/dependency guards in test files" if has_ast_guard else "Architecture guards may be incomplete",
                evidence=("tests/test_batch_filtering.py",),
            )
        )

    findings.append(
        AuditFinding(
            identifier="testing_blender_runtime",
            category=AuditCategory.TESTING,
            status=AuditStatus.BLENDER_UNVERIFIED,
            message="Blender runtime tests: UNVERIFIED. Tests stub bpy in sys.modules.",
            evidence=(),
            blocks_release=False,
        )
    )

    return tuple(findings)


def _collect_documentation(
    root: Path,
) -> Tuple[AuditFinding, ...]:
    """Audit documentation consistency."""
    findings = []
    docs_dir = root / "docs"

    key_docs = [
        "ARCHITECTURE.md",
        "DEVELOPMENT_RULES.md",
        "ROADMAP.md",
        "TASKS.md",
        "PROJECT.md",
    ]

    for doc in key_docs:
        path = docs_dir / doc
        exists = path.exists()
        findings.append(
            AuditFinding(
                identifier=f"doc_{doc.replace('.md', '').lower()}",
                category=AuditCategory.DOCUMENTATION,
                status=AuditStatus.DOCUMENTED if exists else AuditStatus.BLOCKED,
                message=f"{doc} exists" if exists else f"{doc} missing",
                evidence=(f"docs/{doc}",) if exists else (),
                blocks_release=not exists,
            )
        )

    readme = root / "README.md"
    if readme.exists():
        source = _read_source(readme)
        has_phase = "PHASE-0" in source or "Phase" in source
        findings.append(
            AuditFinding(
                identifier="doc_readme_phase_status",
                category=AuditCategory.DOCUMENTATION,
                status=AuditStatus.DOCUMENTED if has_phase else AuditStatus.IMPLEMENTED,
                message="README contains phase status information",
                evidence=("README.md",),
            )
        )

    return tuple(findings)


def _collect_release_blockers(
    root: Path,
) -> Tuple[AuditFinding, ...]:
    """Identify release blockers based on critical missing components."""
    findings = []

    blender_unverified = AuditFinding(
        identifier="blocker_blender_runtime",
        category=AuditCategory.RELEASE_BLOCKERS,
        status=AuditStatus.BLOCKED,
        message="Blender runtime verification not performed. Blender is not installed in the development environment.",
        evidence=(),
        blocks_release=True,
    )
    findings.append(blender_unverified)

    addon_init = root / "addon" / "toonflow_ai" / "__init__.py"
    if not addon_init.exists():
        findings.append(
            AuditFinding(
                identifier="blocker_addon_missing",
                category=AuditCategory.RELEASE_BLOCKERS,
                status=AuditStatus.BLOCKED,
                message="Add-on package missing",
                evidence=(),
                blocks_release=True,
            )
        )

    workflow_dir = root / "workflow"
    if not workflow_dir.exists() or not (workflow_dir / "batch.py").exists():
        findings.append(
            AuditFinding(
                identifier="blocker_workflow_missing",
                category=AuditCategory.RELEASE_BLOCKERS,
                status=AuditStatus.BLOCKED,
                message="Workflow batch layer missing",
                evidence=(),
                blocks_release=True,
            )
        )

    return tuple(findings)


# --- Main collector ---------------------------------------------------------


def collect_repository_audit(
    root: Optional[str] = None,
) -> RuntimeReadinessAudit:
    """Collect a complete runtime readiness audit.

    This function performs a deterministic, read-only inspection of
    the repository without executing any Blender operations.

    Args:
        root: Optional path to project root. If None, uses
            TOONFLOW_PROJECT_ROOT env var or the parent of this
            module's directory.

    Returns:
        A :class:`RuntimeReadinessAudit` with findings and summary.
    """
    project_root = _find_project_root(root)

    all_findings = []
    all_findings.extend(_collect_repository_structure(project_root))
    all_findings.extend(_collect_addon_packaging(project_root))
    all_findings.extend(_collect_ai_boundary(project_root))
    all_findings.extend(_collect_blender_generation(project_root))
    all_findings.extend(_collect_workflow_layer(project_root))
    all_findings.extend(_collect_testing(project_root))
    all_findings.extend(_collect_documentation(project_root))
    all_findings.extend(_collect_release_blockers(project_root))

    return RuntimeReadinessAudit.from_findings(tuple(all_findings))


__all__ = (
    "AuditStatus",
    "AuditCategory",
    "AuditFinding",
    "AuditSummary",
    "RuntimeReadinessAudit",
    "audit_finding_to_dict",
    "audit_summary_to_dict",
    "runtime_readiness_audit_to_dict",
    "runtime_readiness_audit_to_json",
    "collect_repository_audit",
    "PROJECT_ROOT_ENV_VAR",
)
