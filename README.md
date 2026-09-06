# TOONFLOW AI

> Turn Scripts into 3D Cartoon Videos — Directly Inside Blender.

TOONFLOW AI is a planned Blender add-on that will help creators transform a text concept or script into a structured, automated 3D cartoon production workflow. Its core principle is simple: **AI plans. Blender executes.**

This repository currently contains **Phase 017 — Persistent Project Model & Deterministic Replay**. It adds a pure-Python persistent project definition layer (immutable `Project` dataclass, deterministic JSON serialization, strict deserialization, `save_project` / `load_project` file persistence, and `replay_project` delegation to the existing multi-shot workflow). The project layer is bpy-free, AI-free, and must not import pipeline / asset_registry / scene_plan / toonflow_ai.generation directly.

## Documentation

The shared documentation in `docs/` is the project’s primary source of truth for Codex, Kilo Code, and human contributors.

- [Project definition](docs/PROJECT.md)
- [Conceptual architecture](docs/ARCHITECTURE.md)
- [Development rules](docs/DEVELOPMENT_RULES.md)
- [Roadmap](docs/ROADMAP.md)
- [Task register](docs/TASKS.md)
- [Scene Plan contract](docs/SCENE_PLAN.md)
- [Asset Registry](docs/ASSET_REGISTRY.md)
- [Basic Scene Generation](docs/BASIC_SCENE_GENERATION.md)
- [Local Ollama Integration](docs/LOCAL_OLLAMA_INTEGRATION.md)
- [AI Concept-to-Scene Pipeline](docs/AI_CONCEPT_TO_SCENE_PIPELINE.md)
- [Blender UI & Pipeline Integration](docs/BLENDER_UI_PIPELINE_INTEGRATION.md)
- [Character Representation & Pose Foundation](docs/CHARACTER_REPRESENTATION_AND_POSE_FOUNDATION.md)
- [Timeline Animation Foundation](docs/TIMELINE_ANIMATION_FOUNDATION.md)
- [Camera Automation](docs/CAMERA_AUTOMATION.md)
- [Voice and Lip Sync Foundation](docs/VOICE_AND_LIP_SYNC_FOUNDATION.md)
- [Blender Lip Sync Animation Application](docs/BLENDER_LIP_SYNC_ANIMATION.md)
- [Rendering Pipeline](docs/RENDERING_PIPELINE.md)
- [Advanced Automation Workflow](docs/ADVANCED_AUTOMATION_WORKFLOW.md)
- [Multi-Shot Workflow Foundation](docs/MULTI_SHOT_WORKFLOW_FOUNDATION.md)
- [Persistent Project Model & Deterministic Replay](docs/PERSISTENT_PROJECT_MODEL.md)
- [Project Schema Versioning & Migration Foundation](docs/PROJECT_SCHEMA_VERSIONING_AND_MIGRATIONS.md)
- [Project CLI & Batch Runner Foundation](docs/PROJECT_CLI_AND_BATCH_RUNNER.md)
- [Project Batch Mode & CI Integration Foundation](docs/PROJECT_BATCH_MODE_AND_CI_INTEGRATION.md)
- [Project Report & CI Artifacts](docs/PROJECT_REPORTS_AND_CI_ARTIFACTS.md)
- [Batch Filtering & Selective Execution](docs/BATCH_FILTERING_AND_SELECTIVE_EXECUTION.md)
- [Project Manifest & Batch Configuration Foundation](docs/PROJECT_MANIFEST_AND_BATCH_CONFIGURATION.md)
- [Manifest CLI Overrides & Configuration Precedence Foundation](docs/MANIFEST_CLI_OVERRIDES_AND_CONFIGURATION_PRECEDENCE.md)
- [Batch Dry-Run Mode](docs/BATCH_DRY_RUN_MODE.md)
- [Machine-Readable Dry-Run JSON Output](docs/BATCH_DRY_RUN_JSON_OUTPUT.md)
- [Batch Resume and Continuation](docs/BATCH_RESUME_AND_CONTINUATION.md)
- [Batch Retry and Failure Recovery](docs/BATCH_RETRY_AND_FAILURE_RECOVERY.md)
- [Retry Observability and Attempt-Level Reporting](docs/RETRY_OBSERVABILITY_AND_ATTEMPT_REPORTING.md)
- [Batch Operational Summary](docs/BATCH_OPERATIONAL_SUMMARY.md)
- [Batch Result Export](docs/BATCH_RESULT_EXPORT.md)
- [Batch Result Validation](docs/BATCH_RESULT_VALIDATION.md)

## Current status

`TOONFLOW-PHASE-032 — Batch Result Consistency Validation Foundation` is complete.
`TOONFLOW-PHASE-033 — Release / Runtime Readiness Audit Foundation` is complete.
`TOONFLOW-PHASE-034` is reserved as a placeholder. Future phases will be defined by the project owner.

## Initial layout

```text
addon/toonflow_ai/     Blender add-on package
assets/                Reserved for predefined production assets
docs/                  Shared project source of truth
tests/                 Reserved for future automated tests
.codex/                Codex-specific instructions
.kilocode/             Kilo Code-specific rules
```

## Minimal Blender installation test

1. Create a ZIP archive containing the `toonflow_ai` directory from `addon/` at the archive root.
2. In Blender, open **Edit → Preferences → Add-ons**, select **Install**, and choose the ZIP archive.
3. Enable **TOONFLOW AI** and then disable it again.

The package currently registers and unregisters only; it adds no UI or Blender functionality.
