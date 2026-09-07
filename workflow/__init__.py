"""TOONFLOW-PHASE-015 — Advanced Automation Workflow.

This package is a thin orchestration layer that composes the existing
TOONFLOW AI public APIs into one controlled end-to-end workflow.

The workflow itself contains no business logic. It delegates to:

- :func:`pipeline.create_scene_from_concept` for the concept-to-scene
  step (AI planning + Blender scene generation);
- :func:`toonflow_ai.generation.animate_character` for optional
  character animation (delegating to the existing animation API);
- :func:`toonflow_ai.generation.animate_lip_sync` for optional
  lip-sync animation (delegating to the existing lip-sync API);
- :func:`toonflow_ai.generation.create_or_update_camera` for the
  deterministic TOONFLOW camera;
- :func:`toonflow_ai.generation.render_scene` for the final render.

The workflow must remain bpy-free. All Blender side effects happen
inside the delegated modules.

TOONFLOW-PHASE-016 — Multi-Shot Workflow Foundation
---------------------------------------------------

:mod:`workflow.shots` adds a higher-level orchestrator that runs
multiple independent shots through
:func:`workflow.create_and_render_scene` in a fixed, deterministic
order. The multi-shot layer is a pure-Python, bpy-free, AI-free
orchestrator on top of the single-shot workflow.

TOONFLOW-PHASE-017 — Persistent Project Model & Deterministic Replay
--------------------------------------------------------------------

:mod:`workflow.project` adds a pure-Python, bpy-free persistent
project definition layer (the :class:`Project` dataclass plus
deterministic JSON serialization, safe deserialization, file
persistence, and :func:`replay_project` delegation to the
multi-shot workflow).

TOONFLOW-PHASE-023 — Project Manifest & Batch Configuration Foundation
----------------------------------------------------------------------

:mod:`workflow.manifest` adds a deterministic, immutable JSON
configuration layer on top of the existing batch layer. A
:class:`BatchManifest` names a directory, a batch mode, and the
batch filter / report options that should be applied to a single
batch execution. The manifest layer is configuration and
orchestration only; it delegates execution to
:func:`workflow.batch.run_batch`.

TOONFLOW-PHASE-024 — Manifest CLI Overrides & Configuration Precedence
----------------------------------------------------------------------

:mod:`workflow.manifest` adds
:func:`apply_manifest_overrides`, a pure configuration helper
that returns a new :class:`BatchManifest` with selected fields
replaced by CLI-supplied values. The override layer never
mutates the original manifest and never touches the manifest
file on disk. The CLI ``manifest`` subcommand grows matching
optional flags.

TOONFLOW-PHASE-025 — Batch Dry-Run Mode
---------------------------------------

:mod:`workflow.batch` adds :class:`BatchDryRunResult` and
:func:`dry_run_batch`, a deterministic preview of what a real
batch execution *would* do. The CLI ``batch`` and ``manifest``
subcommands gain a ``--dry-run`` flag. :mod:`workflow.manifest`
adds :func:`dry_run_batch_manifest` for manifest-driven
previews. Dry-run is an execution-time concern; the manifest
schema is not extended.

TOONFLOW-PHASE-033 — Runtime Readiness Audit Foundation
-------------------------------------------------------

:mod:`workflow.audit` adds a deterministic, read-only audit layer
that evaluates the repository's implementation and readiness state
without executing Blender. It distinguishes IMPLEMENTED, TEST_COVERED,
BLENDER_UNVERIFIED, DOCUMENTED, BLOCKED, and NOT_APPLICABLE findings.
Static/unit-test evidence is NOT equivalent to Blender runtime
verification.
"""

from .api import WorkflowResult, create_and_render_scene
from .audit import (
    AuditCategory,
    AuditFinding,
    AuditStatus,
    AuditSummary,
    RuntimeReadinessAudit,
    audit_finding_to_dict,
    audit_summary_to_dict,
    collect_repository_audit,
    runtime_readiness_audit_to_dict,
    runtime_readiness_audit_to_json,
)
from .packaging import (
    DEFAULT_EXCLUDED_PATHS,
    DEFAULT_INCLUDED_PATHS,
    DEFAULT_REQUIRED_PATHS,
    AddonPackageBuildResult,
    AddonPackageManifest,
    PackagingStatus,
    PackagingValidationResult,
    addon_package_manifest_default,
    build_addon_zip,
    build_result_to_dict,
    build_result_to_json,
    packaging_validation_to_dict,
    packaging_validation_to_json,
    read_archive_manifest,
    validate_addon_package,
)
from .manifest import (
    BATCH_MANIFEST_SCHEMA_VERSION,
    BatchManifest,
    ManifestInputError,
    apply_manifest_overrides,
    batch_manifest_from_dict,
    batch_manifest_from_json,
    batch_manifest_to_dict,
    batch_manifest_to_json,
    dry_run_batch_manifest,
    load_batch_manifest,
    run_batch_manifest,
    save_batch_manifest,
)
from .project import (
    PROJECT_SCHEMA_VERSION,
    Project,
    ProjectInputError,
    load_project,
    project_from_dict,
    project_from_json,
    project_to_dict,
    project_to_json,
    replay_project,
    save_project,
)
from .project_migrations import (
    SUPPORTED_PROJECT_SCHEMA_VERSIONS,
    UnsupportedProjectSchemaError,
    migrate_project_dict,
    migrate_project_dict_to_version,
)
from .shots import (
    MultiShotInputError,
    MultiShotResult,
    Shot,
    create_and_render_shots,
)
from .verification import (
    BlenderRuntimeVerificationResult,
    BlenderVerificationContract,
    VerificationBoundary,
    VerificationStatus,
    blender_verification_to_dict,
    blender_verification_to_json,
    verify_blender_runtime,
)

__all__ = (
    "create_and_render_scene",
    "WorkflowResult",
    "create_and_render_shots",
    "Shot",
    "MultiShotResult",
    "MultiShotInputError",
    "Project",
    "ProjectInputError",
    "PROJECT_SCHEMA_VERSION",
    "project_to_dict",
    "project_from_dict",
    "project_to_json",
    "project_from_json",
    "save_project",
    "load_project",
    "replay_project",
    "SUPPORTED_PROJECT_SCHEMA_VERSIONS",
    "UnsupportedProjectSchemaError",
    "migrate_project_dict",
    "migrate_project_dict_to_version",
    "BATCH_MANIFEST_SCHEMA_VERSION",
    "BatchManifest",
    "ManifestInputError",
    "apply_manifest_overrides",
    "batch_manifest_to_dict",
    "batch_manifest_from_dict",
    "batch_manifest_to_json",
    "batch_manifest_from_json",
    "save_batch_manifest",
    "load_batch_manifest",
    "run_batch_manifest",
    "dry_run_batch_manifest",
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
    "BlenderRuntimeVerificationResult",
    "BlenderVerificationContract",
    "VerificationBoundary",
    "VerificationStatus",
    "blender_verification_to_dict",
    "blender_verification_to_json",
    "verify_blender_runtime",
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
)