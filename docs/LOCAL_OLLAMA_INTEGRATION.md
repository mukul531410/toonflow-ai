# Local Ollama Integration

TOONFLOW-PHASE-006 adds a planning-only layer that turns a user concept into
a validated Scene Plan. It does not invoke Blender generation.

## Architecture

```text
User concept
    -> deterministic planner prompt
    -> local Ollama HTTP API
    -> raw model text
    -> JSON parsing
    -> Scene Plan validation
    -> validated Scene Plan dictionary
```

The top-level `ai` package is independent from Blender UI, operators, and
scene generation. It uses only Python's standard library `urllib` client.

## Local-only configuration

`plan_scene` defaults to local Ollama at `http://127.0.0.1:11434`, model
`llama3.2`, and a 30-second timeout. Callers can configure all three:

```python
from ai import plan_scene

scene_plan = plan_scene(
    "A husband and wife at home",
    base_url="http://127.0.0.1:11434",
    model="llama3.2",
    timeout=30,
)
```

No API key, cloud service, telemetry, or third-party Python package is used.

## Public API and output contract

`plan_scene(concept, *, base_url, model, timeout) -> dict` accepts a non-empty
string and returns only a Scene Plan accepted by `scene_plan.validate_scene_plan`.

The model prompt requires JSON only, with no Markdown or explanatory text. It
supports version `"0.1"`, environment `living_room`, and characters `husband`
and `wife`. The output must have the existing Scene Plan shape:

```json
{
  "version": "0.1",
  "scene": {"environment": "living_room"},
  "characters": [{"id": "husband", "role": "husband"}]
}
```

## Errors

The package raises clear domain errors rather than raw `urllib` exceptions:

- `InvalidConceptError`
- `OllamaUnavailableError`
- `OllamaTimeoutError`
- `OllamaHTTPError`
- `OllamaResponseError`
- `InvalidModelJSONError`
- `InvalidScenePlanError` (with `.errors` from schema validation)

## Required local setup

Install and run Ollama locally, then ensure the configured model is available.
The default service endpoint is `http://127.0.0.1:11434/api/generate`.

## Current limitations

This phase supports only one Scene Plan schema and the current three Asset
Registry identifiers. It does not cross-check the registry itself, call
`generate_scene`, load assets, or provide a Blender UI. A local Ollama service
and downloaded model are required for a real request.
