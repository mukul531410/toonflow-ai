# AI Concept-to-Scene Pipeline

TOONFLOW-PHASE-007 connects the existing local AI planner to the existing
scene generation API. It adds orchestration only; planning, validation, asset
checks, and scene creation remain owned by their existing packages.

## End-to-end flow

```text
User concept
    -> ai.plan_scene(...)
    -> validated Scene Plan
    -> toonflow_ai.generation.generate_scene(...)
    -> SceneCreationResult
```

## Public API

```python
from pipeline import create_scene_from_concept

result = create_scene_from_concept(
    "A husband and wife at home",
    model="llama3.2",
    timeout=30,
)
```

`create_scene_from_concept` accepts the same local planner configuration as
`ai.plan_scene`: `base_url`, `model`, and `timeout`. An existing planner or a
generation callable can be supplied for controlled integration and testing.

## Result and errors

The function returns an immutable `SceneCreationResult` with:

- `scene_plan` — the validated dictionary returned by the planner.
- `generation_result` — the result returned by scene generation.

It does not catch or translate errors. AI planning errors and generation
errors therefore remain available to callers with their original types and
context.

## Dependency boundary and limitations

The `pipeline` package contains no transport, prompt-building, JSON parsing,
schema validation, Asset Registry, or Blender object-creation logic. It does
not add UI, operators, asset loading, or cloud providers.

Successful real-world execution still requires both a running local Ollama
service/model and a Blender-capable runtime for the generation layer.
