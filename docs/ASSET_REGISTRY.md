# Asset Registry

TOONFLOW AI's Asset Registry provides a controlled, read-only mapping from
asset identifiers in a Scene Plan to minimal known asset definitions. It is
separate from Scene Plan validation: a plan may be structurally valid while
referring to an unregistered identifier.

## Supported asset types

Only these types are supported in TOONFLOW-PHASE-004:

- Environments
- Characters

## Initial registered assets

| Asset type | Identifier | Display name |
| --- | --- | --- |
| Environment | `living_room` | Living Room |
| Character | `husband` | Husband |
| Character | `wife` | Wife |

Every definition contains exactly `id`, `asset_type`, and `display_name`.

## Public API

```python
from asset_registry import (
    character_exists,
    environment_exists,
    get_character,
    get_environment,
)
```

- `get_environment(asset_id)` and `get_character(asset_id)` return a fresh
  dictionary containing the matching definition, or `None` when unknown.
- `environment_exists(asset_id)` and `character_exists(asset_id)` return a
  boolean.

Returned dictionaries are copies, so changing one cannot alter the internal
registry.

## Current limitations

The registry does not load Blender assets and contains no `.blend` file paths,
object names, collections, rigs, materials, animations, or download metadata.
It supports no props, cameras, lighting, audio, effects, or animation assets.
Cross-validating Scene Plans against this registry is intentionally deferred.
