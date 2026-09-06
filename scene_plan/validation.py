"""Validation layer for TOONFLOW AI Scene Plans.

Public API:
    validate_scene_plan(data) -> ValidationResult

Design notes:
- Validation is deterministic and side-effect free.
- The input dictionary is never mutated.
- Validation does not print.
- Validation has no dependency on Blender or any AI provider.
- Invalid input is reported clearly; nothing is silently repaired.
"""

from .schema import (
    KEY_CHARACTERS,
    KEY_ENVIRONMENT,
    KEY_ID,
    KEY_ROLE,
    KEY_SCENE,
    KEY_VERSION,
    SUPPORTED_VERSIONS,
)


class ValidationError:
    """A single validation error.

    Attributes:
        path: Dotted JSON-pointer-like path to the offending value
              (e.g. "characters[2].id").
        message: Human-readable description of the problem.
    """

    __slots__ = ("path", "message")

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message

    def __repr__(self) -> str:
        return f"ValidationError({self.path!r}, {self.message!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ValidationError):
            return NotImplemented
        return self.path == other.path and self.message == other.message


class ValidationResult:
    """Outcome of validating a Scene Plan.

    Use ``is_valid`` for the boolean verdict and ``errors`` for a list of
    :class:`ValidationError` instances (empty when valid).
    """

    __slots__ = ("is_valid", "errors")

    def __init__(self, is_valid: bool, errors) -> None:
        self.is_valid = bool(is_valid)
        self.errors = list(errors)

    def __bool__(self) -> bool:
        return self.is_valid

    def __repr__(self) -> str:
        return f"ValidationResult(is_valid={self.is_valid!r}, errors={self.errors!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ValidationResult):
            return NotImplemented
        return self.is_valid == other.is_valid and self.errors == other.errors


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and value != ""


def validate_scene_plan(data: object) -> ValidationResult:
    """Validate a Scene Plan dictionary.

    Args:
        data: A Python value to validate. Typically a plain dict produced
              by a future AI planner.

    Returns:
        A :class:`ValidationResult`. When ``result.is_valid`` is True,
        ``result.errors`` is empty. When False, ``result.errors`` lists
        every problem found (validation is non-short-circuiting so the
        caller sees the full picture).

    The input is never mutated.
    """
    errors = []

    if not isinstance(data, dict):
        errors.append(ValidationError("", "Scene Plan must be a dictionary."))
        return ValidationResult(False, errors)

    if KEY_VERSION not in data:
        errors.append(
            ValidationError(KEY_VERSION, f"Missing required field '{KEY_VERSION}'.")
        )
    else:
        version = data[KEY_VERSION]
        if not isinstance(version, str):
            errors.append(
                ValidationError(
                    KEY_VERSION,
                    f"Field '{KEY_VERSION}' must be a string.",
                )
            )
        elif version not in SUPPORTED_VERSIONS:
            errors.append(
                ValidationError(
                    KEY_VERSION,
                    f"Unsupported version {version!r}. "
                    f"Supported versions: {list(SUPPORTED_VERSIONS)}.",
                )
            )

    if KEY_SCENE not in data:
        errors.append(
            ValidationError(KEY_SCENE, f"Missing required field '{KEY_SCENE}'.")
        )
    else:
        scene = data[KEY_SCENE]
        if not isinstance(scene, dict):
            errors.append(
                ValidationError(
                    KEY_SCENE,
                    f"Field '{KEY_SCENE}' must be a dictionary.",
                )
            )
        else:
            if KEY_ENVIRONMENT not in scene:
                errors.append(
                    ValidationError(
                        f"{KEY_SCENE}.{KEY_ENVIRONMENT}",
                        f"Missing required field '{KEY_ENVIRONMENT}' in '{KEY_SCENE}'.",
                    )
                )
            else:
                environment = scene[KEY_ENVIRONMENT]
                if not _is_non_empty_string(environment):
                    errors.append(
                        ValidationError(
                            f"{KEY_SCENE}.{KEY_ENVIRONMENT}",
                            f"Field '{KEY_SCENE}.{KEY_ENVIRONMENT}' must be a non-empty string.",
                        )
                    )

    if KEY_CHARACTERS not in data:
        errors.append(
            ValidationError(
                KEY_CHARACTERS,
                f"Missing required field '{KEY_CHARACTERS}'.",
            )
        )
    else:
        characters = data[KEY_CHARACTERS]
        if not isinstance(characters, list):
            errors.append(
                ValidationError(
                    KEY_CHARACTERS,
                    f"Field '{KEY_CHARACTERS}' must be a list.",
                )
            )
        else:
            seen_ids = set()
            for index, character in enumerate(characters):
                base_path = f"{KEY_CHARACTERS}[{index}]"
                if not isinstance(character, dict):
                    errors.append(
                        ValidationError(
                            base_path,
                            f"{base_path} must be a dictionary.",
                        )
                    )
                    continue

                if KEY_ID not in character:
                    errors.append(
                        ValidationError(
                            f"{base_path}.{KEY_ID}",
                            f"Missing required field '{KEY_ID}' in {base_path}.",
                        )
                    )
                else:
                    cid = character[KEY_ID]
                    if not _is_non_empty_string(cid):
                        errors.append(
                            ValidationError(
                                f"{base_path}.{KEY_ID}",
                                f"Field '{base_path}.{KEY_ID}' must be a non-empty string.",
                            )
                        )

                if KEY_ROLE not in character:
                    errors.append(
                        ValidationError(
                            f"{base_path}.{KEY_ROLE}",
                            f"Missing required field '{KEY_ROLE}' in {base_path}.",
                        )
                    )
                else:
                    role = character[KEY_ROLE]
                    if not _is_non_empty_string(role):
                        errors.append(
                            ValidationError(
                                f"{base_path}.{KEY_ROLE}",
                                f"Field '{base_path}.{KEY_ROLE}' must be a non-empty string.",
                            )
                        )

                if KEY_ID in character and _is_non_empty_string(character[KEY_ID]):
                    cid = character[KEY_ID]
                    if cid in seen_ids:
                        errors.append(
                            ValidationError(
                                f"{base_path}.{KEY_ID}",
                                f"Duplicate character id {cid!r}.",
                            )
                        )
                    else:
                        seen_ids.add(cid)

    return ValidationResult(not errors, errors)