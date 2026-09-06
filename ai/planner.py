"""Concept-to-Scene-Plan planner backed by a local Ollama client."""

import json

from scene_plan import validate_scene_plan

from .errors import InvalidConceptError, InvalidModelJSONError, InvalidScenePlanError
from .ollama_client import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_TIMEOUT, OllamaClient


def build_planning_prompt(concept: str) -> str:
    """Build the deterministic instruction sent to the local model."""
    return f'''Create a Scene Plan for this user concept:
{concept}

Return ONLY valid JSON. Do not return Markdown, explanations, or additional text.

The only supported Scene Plan version is "0.1".
The only supported environment identifier is "living_room".
The only supported character identifiers are "husband" and "wife".

Return exactly this structure, using only supported identifiers:
{{
  "version": "0.1",
  "scene": {{
    "environment": "living_room"
  }},
  "characters": [
    {{
      "id": "husband",
      "role": "husband"
    }}
  ]
}}'''


class ScenePlanner:
    """Produce validated Scene Plans through an injected Ollama client."""

    def __init__(self, client) -> None:
        self._client = client

    def plan_scene(self, concept: str) -> dict:
        """Convert a non-empty concept into a validated Scene Plan dictionary."""
        if not isinstance(concept, str) or not concept.strip():
            raise InvalidConceptError("concept must be a non-empty string.")

        raw_model_text = self._client.generate(build_planning_prompt(concept))
        try:
            scene_plan_data = json.loads(raw_model_text)
        except json.JSONDecodeError as error:
            raise InvalidModelJSONError(error.msg) from error

        validation_result = validate_scene_plan(scene_plan_data)
        if not isinstance(scene_plan_data, dict):
            raise InvalidScenePlanError(validation_result.errors)
        if not validation_result.is_valid:
            raise InvalidScenePlanError(validation_result.errors)
        return scene_plan_data


def plan_scene(
    concept: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Plan a Scene Plan through a configured local Ollama service."""
    client = OllamaClient(base_url=base_url, model=model, timeout=timeout)
    return ScenePlanner(client).plan_scene(concept)
