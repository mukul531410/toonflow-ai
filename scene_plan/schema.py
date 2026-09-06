"""Scene Plan schema constants.

The schema is intentionally small and explicit. It does NOT use dataclasses,
pydantic, jsonschema, or any third-party dependency. The contract is a plain
Python dictionary shape, documented here as constants and keys.
"""

SCHEMA_VERSION = "0.1"

SUPPORTED_VERSIONS = (SCHEMA_VERSION,)

KEY_VERSION = "version"
KEY_SCENE = "scene"
KEY_ENVIRONMENT = "environment"
KEY_CHARACTERS = "characters"
KEY_ID = "id"
KEY_ROLE = "role"