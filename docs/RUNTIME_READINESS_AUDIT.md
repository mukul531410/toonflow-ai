# Runtime Readiness Audit

TOONFLOW-PHASE-033 adds a deterministic, read-only audit layer that evaluates
the TOONFLOW AI repository's implementation and readiness state without
executing Blender operations.

## Purpose

The purpose is to create a structured audit mechanism that clearly distinguishes:

- **IMPLEMENTED**: Code exists and compiles
- **TEST_COVERED**: Unit tests exist and pass
- **BLENDER_UNVERIFIED**: Blender runtime verification is absent. A unit test
  passing does NOT mean Blender runtime verification passed.
- **DOCUMENTED**: Documentation exists and appears accurate
- **BLOCKED**: A known blocker prevents progress
- **NOT_APPLICABLE**: Not relevant to this repository

This phase is an audit foundation only. It must NOT redesign existing features,
invent missing functionality, or silently mark functionality as verified when
Blender has not actually been run.

## Distinction from Blender Runtime Verification

**Critical**: This audit layer does NOT verify Blender runtime behavior.

- Static/unit-test evidence is NOT equivalent to Blender runtime verification
- A module existing does NOT automatically mean the feature is production-ready
- Documentation existing does NOT mean the documented behavior is accurate
- The audit explicitly represents Blender runtime verification status as
  ``BLENDER_UNVERIFIED`` unless actual Blender execution evidence exists

Examples of what this audit is NOT:

- Blender installation test
- Blender execution test
- CI service integration test
- ``py_compile`` test
- CLI smoke test without Blender
- ``bpy`` stubs test

## Audit Model

### Status Semantics

The audit uses only these statuses:

| Status | Meaning |
|---|---|
| ``IMPLEMENTED`` | Code exists and compiles; found via inspection |
| ``TEST_COVERED`` | Unit tests exist; passing tests indicate coverage |
| ``BLENDER_UNVERIFIED`` | Blender runtime not verified; default for generation layer |
| ``DOCUMENTED`` | Documentation exists for the feature |
| ``BLOCKED`` | A known blocker prevents progress |
| ``NOT_APPLICABLE`` | Not relevant to this repository |

### Categories

| Category | Areas Covered |
|---|---|
| ``REPOSITORY_STRUCTURE`` | Package existence, required directories |
| ``ADDON_PACKAGING`` | Add-on structure, bl_info, bpy import boundaries |
| ``AI_BOUNDARY`` | Planner, Ollama client, structured output, no Blender imports |
| ``BLENDER_GENERATION`` | Scene generation, character, camera, animation, lip-sync, pose, rendering |
| ``WORKFLOW_LAYER`` | Batch, manifest, report, project, shots |
| ``TESTING`` | Test coverage, architecture guards, Blender runtime test status |
| ``DOCUMENTATION`` | Architecture, roadmap, tasks, README consistency |
| ``RELEASE_BLOCKERS`` | Critical blockers that would prevent release |

### Findings

Each finding has:

- **identifier**: Unique within the audit (e.g. ``generation_blender_runtime``)
- **category**: One of the eight categories above
- **status**: One of the six statuses above
- **message**: Human-readable description
- **evidence**: Tuple of supporting file paths (relative to project root)
- **blocks_release**: ``True`` if this finding blocks release

### Top-Level Audit Result

``RuntimeReadinessAudit`` contains:

- **findings**: Tuple of ``AuditFinding``, sorted by ``(category, identifier)``
- **summary**: ``AuditSummary`` with counts ``total_findings``, ``implemented``,
  ``test_covered``, ``blender_unverified``, ``documented``, ``blocked``,
  ``not_applicable``, ``release_blocker_count``

## Usage

### Pure Python API

```python
from workflow.audit import collect_repository_audit

audit = collect_repository_audit()
for finding in audit.findings:
    print(f"{finding.identifier}: {finding.status} - {finding.message}")

summary = audit.summary
print(f"Total: {summary.total_findings}")
print(f"Blender unverified: {summary.blender_unverified}")
print(f"Release blockers: {summary.release_blocker_count}")
```

### Deterministic Dict Output

```python
from workflow.audit import runtime_readiness_audit_to_dict, runtime_readiness_audit_to_json

dict_repr = runtime_readiness_audit_to_dict(audit)
json_str = runtime_readiness_audit_to_json(audit)
```

### Determinism

Running ``collect_repository_audit()`` more than once, or calling
``runtime_readiness_audit_to_json()`` twice on the same audit, always
produces byte-identical JSON output (no timestamps, no UUIDs, no random values,
no environment-dependent data).

### CLI

```bash
python -m workflow.cli audit
```

Provides a deterministic JSON dump of the repository readiness state. The
``--dry-run`` flag has no effect on the audit CLI since the audit is always a
preview. The audit does NOT execute Blender, make network calls, or modify
source files.

## Documentation Consistency

If inspection reveals stale README or documentation statements, do NOT perform
a broad documentation rewrite in this phase. Only make the minimal changes
required to accurately identify the current phase and describe the audit
foundation. Record other documentation inconsistencies as audit findings.

## Limitations

This phase is an audit foundation only. It does NOT implement:

- Blender installation automation
- Blender downloading
- Blender execution from the audit
- CI service integration
- GitHub Actions redesign
- Release publishing
- Blender Extension submission
- Telemetry, monitoring, or dashboards
- Analytics database, persistent audit history
- Network checks or cloud services
- Automatic fixes or code modification
- AI-based code review or semantic quality scoring
- Arbitrary percentage scoring
- New project schema, manifest schema, or report schema
- New persistence layer

## Report Semantics

- Static/unit-test evidence is not equivalent to Blender runtime verification.
- ``BLENDER_UNVERIFIED`` is the default status for any generation-layer code
  unless actual Blender execution evidence exists.
- ``IMPLEMENTED`` means code was found via inspection; it does NOT guarantee
  production readiness.
- ``BLOCKED`` findings with ``blocks_release=True`` are the only items that
  should block a release decision; others are informational.
- The ``release_blocker_count`` in the summary counts only findings where
  ``blocks_release=True``.

## Example Output

````json
{
  "findings": [
    {
      "identifier": "addon_package_exists",
      "category": "REPOSITORY_STRUCTURE",
      "status": "IMPLEMENTED",
      "message": "Package exists",
      "evidence": ["addon/toonflow_ai/__init__.py"],
      "blocks_release": false
    },
    {
      "identifier": "generation_blender_runtime",
      "category": "BLENDER_GENERATION",
      "status": "BLENDER_UNVERIFIED",
      "message": "Blender runtime verification: UNVERIFIED. Unit tests stub bpy; actual Blender execution not tested.",
      "evidence": [],
      "blocks_release": false
    },
    {
      "identifier": "blocker_blender_runtime",
      "category": "RELEASE_BLOCKERS",
      "status": "BLOCKED",
      "message": "Blender runtime verification not performed. Blender is not installed in the development environment.",
      "evidence": [],
      "blocks_release": true
    }
  ],
  "summary": {
    "total_findings": 73,
    "implemented": 51,
    "test_covered": 16,
    "blender_unverified": 5,
    "documented": 60,
    "blocked": 5,
    "not_applicable": 2,
    "release_blocker_count": 3
  }
}
````

## Relationship to Prior Phases

- PHASE-021 (Project Report & CI Artifacts): Provides deterministic JSON
  serialization patterns followed by this audit.
- PHASE-023 (Project Manifest & Batch Configuration Foundation): Provides
  ``BatchManifest`` model conventions for deterministic structure.
- PHASE-025 (Batch Dry-Run Mode): Provides ``BatchDryRunResult`` patterns.
- PHASE-026 (Machine-Readable Dry-Run JSON Output): Provides JSON
  serialization conventions (indent=2, sort_keys=False, ensure_ascii=False,
  single trailing newline).
- PHASE-027 (Batch Resume & Continuation Foundation): Provides ``BatchResumeResult``
  and ``plan_batch_resume`` patterns.

The audit intentionally reuses the project's existing serialization conventions
rather than creating a new framework.

## Files Created

- ``workflow/audit.py`` — audit model, collector functions, serialization
- ``tests/test_runtime_readiness_audit.py`` — comprehensive test suite
- ``docs/RUNTIME_READINESS_AUDIT.md`` — this documentation

## Files Modified

- ``workflow/__init__.py`` — added audit exports and docstring update
- ``docs/TASKS.md`` — added PHASE-033 entry
- ``docs/ROADMAP.md`` — marked PHASE-033 complete, added PHASE-034 placeholder
- ``README.md`` — marked PHASE-033 complete

## Verification

After implementation, run:

1. ``python -m unittest discover -s tests`` — all existing tests must pass
2. ``python -m py_compile workflow/audit.py`` — no compilation errors
3. ``python -m py_compile tests/test_runtime_readiness_audit.py`` — no errors
4. ``python -c "from workflow.audit import collect_repository_audit; audit = collect_repository_audit(); print(audit.summary)`` — functional test
5. ``python -c "from workflow.audit import runtime_readiness_audit_to_json; audit = collect_repository_audit(); json_str = runtime_readiness_audit_to_json(audit); data = json.loads(json_str); assert 'summary' in data`` — JSON determinism test
6. ``python -m unittest discover -s tests tests.test_runtime_readiness_audit`` — focused audit tests

If Blender is unavailable, explicitly state that Blender live integration was
not tested. The audit explicitly represents Blender runtime verification status
as ``BLENDER_UNVERIFIED`` unless actual Blender evidence exists.