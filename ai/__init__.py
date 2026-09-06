"""Local AI planning for TOONFLOW AI.

This package converts a user concept into a validated Scene Plan. It is
independent from Blender execution and communicates only with local Ollama.
"""

from .errors import (
    InvalidConceptError,
    InvalidModelJSONError,
    InvalidScenePlanError,
    OllamaHTTPError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
    PlannerError,
)
from .ollama_client import OllamaClient
from .planner import ScenePlanner, plan_scene

__all__ = (
    "plan_scene",
    "ScenePlanner",
    "OllamaClient",
    "PlannerError",
    "InvalidConceptError",
    "OllamaUnavailableError",
    "OllamaTimeoutError",
    "OllamaHTTPError",
    "OllamaResponseError",
    "InvalidModelJSONError",
    "InvalidScenePlanError",
)
