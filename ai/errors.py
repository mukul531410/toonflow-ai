"""Public error types for local TOONFLOW AI planning."""


class PlannerError(Exception):
    """Base class for all TOONFLOW AI planning errors."""


class InvalidConceptError(PlannerError):
    """The supplied user concept was not a non-empty string."""


class OllamaUnavailableError(PlannerError):
    """The local Ollama service could not be reached."""


class OllamaTimeoutError(PlannerError):
    """The local Ollama service did not respond before the timeout."""


class OllamaHTTPError(PlannerError):
    """Ollama returned a non-success HTTP response."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        message = f"Ollama returned HTTP {status_code}."
        if detail:
            message = f"{message} {detail}"
        super().__init__(message)


class OllamaResponseError(PlannerError):
    """Ollama returned a success response without usable model text."""


class InvalidModelJSONError(PlannerError):
    """The model response was not valid JSON."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Model response is not valid JSON: {message}")


class InvalidScenePlanError(PlannerError):
    """The model returned JSON that failed Scene Plan validation."""

    def __init__(self, errors) -> None:
        self.errors = tuple(errors)
        super().__init__(
            "Model response failed Scene Plan validation; "
            f"{len(self.errors)} error(s) found."
        )
