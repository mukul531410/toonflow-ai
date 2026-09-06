"""Tests for TOONFLOW AI's local Ollama planning layer.

No test makes a real HTTP request or requires an Ollama server.
"""

import inspect
import io
import json
import socket
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import ai  # noqa: E402
import ai.errors as ai_errors  # noqa: E402
import ai.ollama_client as ollama_client  # noqa: E402
import ai.planner as planner_module  # noqa: E402
from ai.planner import build_planning_prompt  # noqa: E402


VALID_PLAN = {
    "version": "0.1",
    "scene": {"environment": "living_room"},
    "characters": [{"id": "husband", "role": "husband"}],
}


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class OllamaClientTests(unittest.TestCase):
    def test_successful_text_response(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(200, '{"response": "model text"}')

        client = ai.OllamaClient(
            base_url="http://localhost:1234/", model="test-model", timeout=5, opener=opener
        )
        self.assertEqual(client.generate("plan this"), "model text")
        self.assertEqual(captured["url"], "http://localhost:1234/api/generate")
        self.assertEqual(captured["timeout"], 5)
        self.assertEqual(
            captured["payload"],
            {"model": "test-model", "prompt": "plan this", "stream": False},
        )

    def test_network_failure_mapping(self):
        client = ai.OllamaClient(opener=lambda request, timeout: (_ for _ in ()).throw(URLError("offline")))
        with self.assertRaises(ai.OllamaUnavailableError):
            client.generate("prompt")

    def test_timeout_mapping(self):
        client = ai.OllamaClient(opener=lambda request, timeout: (_ for _ in ()).throw(socket.timeout()))
        with self.assertRaises(ai.OllamaTimeoutError):
            client.generate("prompt")

    def test_http_error_mapping(self):
        error = HTTPError("http://localhost", 503, "Unavailable", {}, io.BytesIO(b"service down"))
        client = ai.OllamaClient(opener=lambda request, timeout: (_ for _ in ()).throw(error))
        with self.assertRaises(ai.OllamaHTTPError) as context:
            client.generate("prompt")
        self.assertEqual(context.exception.status_code, 503)


class PlannerTests(unittest.TestCase):
    def planner_for(self, response):
        return ai.ScenePlanner(FakeClient(response))

    def test_valid_concept_returns_validated_dictionary(self):
        result = self.planner_for(json.dumps(VALID_PLAN)).plan_scene("A family at home")
        self.assertEqual(result, VALID_PLAN)

    def test_empty_concept_is_rejected(self):
        with self.assertRaises(ai.InvalidConceptError):
            self.planner_for(json.dumps(VALID_PLAN)).plan_scene("")

    def test_whitespace_concept_is_rejected(self):
        with self.assertRaises(ai.InvalidConceptError):
            self.planner_for(json.dumps(VALID_PLAN)).plan_scene("   ")

    def test_non_string_concept_is_rejected(self):
        with self.assertRaises(ai.InvalidConceptError):
            self.planner_for(json.dumps(VALID_PLAN)).plan_scene(None)

    def test_malformed_model_json_is_rejected(self):
        with self.assertRaises(ai.InvalidModelJSONError):
            self.planner_for("not json").plan_scene("A home")

    def test_json_list_is_rejected(self):
        with self.assertRaises(ai.InvalidScenePlanError) as context:
            self.planner_for("[]").plan_scene("A home")
        self.assertTrue(context.exception.errors)

    def test_structurally_invalid_scene_plan_is_rejected(self):
        with self.assertRaises(ai.InvalidScenePlanError) as context:
            self.planner_for('{"version": "0.1"}').plan_scene("A home")
        self.assertTrue(context.exception.errors)

    def test_planner_does_not_mutate_parsed_output(self):
        raw_response = json.dumps(VALID_PLAN)
        result = self.planner_for(raw_response).plan_scene("A home")
        expected = json.loads(raw_response)
        self.assertEqual(result, expected)


class PromptAndDependencyTests(unittest.TestCase):
    def test_prompt_declares_the_complete_contract(self):
        prompt = build_planning_prompt("A home")
        for required_text in ("0.1", "living_room", "husband", "wife", "ONLY valid JSON"):
            self.assertIn(required_text, prompt)

    def test_ai_package_has_no_bpy_dependency(self):
        for module in (ai, ai_errors, ollama_client, planner_module):
            self.assertNotIn("bpy", inspect.getsource(module))


if __name__ == "__main__":
    unittest.main()
