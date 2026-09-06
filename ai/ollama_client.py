"""Small standard-library client for Ollama's local generate endpoint."""

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import (
    OllamaHTTPError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2"
DEFAULT_TIMEOUT = 30.0


class OllamaClient:
    """Send prompts to a local Ollama service and return model text only."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        opener=None,
    ) -> None:
        if not isinstance(base_url, str) or not base_url:
            raise ValueError("base_url must be a non-empty string.")
        if not isinstance(model, str) or not model:
            raise ValueError("model must be a non-empty string.")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number.")

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._opener = urlopen if opener is None else opener

    def generate(self, prompt: str) -> str:
        """Return generated model text for *prompt*.

        Transport failures are converted to the public planning error types.
        """
        payload = json.dumps(
            {"model": self.model, "prompt": prompt, "stream": False}
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with self._opener(request, timeout=self.timeout) as response:
                status_code = getattr(response, "status", None)
                if status_code is None:
                    status_code = response.getcode()
                body = response.read().decode("utf-8")
        except HTTPError as error:
            detail = _read_error_detail(error)
            raise OllamaHTTPError(error.code, detail) from error
        except (socket.timeout, TimeoutError) as error:
            raise OllamaTimeoutError("Ollama request timed out.") from error
        except (URLError, OSError) as error:
            raise OllamaUnavailableError("Ollama service is unavailable.") from error

        if not isinstance(status_code, int) or not 200 <= status_code < 300:
            raise OllamaHTTPError(status_code, body)

        try:
            response_data = json.loads(body)
        except json.JSONDecodeError as error:
            raise OllamaResponseError("Ollama returned invalid response JSON.") from error

        model_text = response_data.get("response") if isinstance(response_data, dict) else None
        if not isinstance(model_text, str):
            raise OllamaResponseError("Ollama response did not contain text.")
        return model_text


def _read_error_detail(error: HTTPError) -> str:
    """Read a concise error response body without masking the HTTP error."""
    try:
        return error.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
