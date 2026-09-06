# Conceptual Architecture

TOONFLOW AI will keep planning separate from Blender execution.

```text
User Input
    ↓
AI Planner
    ↓
Structured Scene Plan
    ↓
Validation
    ↓
Blender Automation Layer
    ↓
Blender bpy
    ↓
Assets / Scene
```

## Planned responsibilities

| Layer | Conceptual responsibility |
| --- | --- |
| User Input | Accept a concept or script from the creator. |
| AI Planner | Analyze input and propose a structured scene plan through a replaceable provider. Ollama is the initial provider. |
| Structured Scene Plan | Represent approved scene instructions as JSON-compatible data, never executable code. |
| Validation | Check plan shape, permitted values, and asset references before any Blender action. |
| Blender Automation Layer | Map validated plan data to controlled operators and services. |
| Blender bpy | Perform the permitted Blender actions through the Blender Python API. |
| Assets / Scene | Provide predefined assets and receive the generated Blender scene state. |

## Safety boundary

The AI planner must never generate Python that is executed directly in Blender. It may only provide structured data. The validation and automation layers are the sole route from an AI plan to Blender operations.

## Current scope

This remains a conceptual design. Phase 001 supplies only the add-on package metadata and registration entry points; no architecture layers, schemas, bpy calls, operators, providers, or asset-loading logic are implemented.
