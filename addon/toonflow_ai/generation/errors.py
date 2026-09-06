"""Error types raised by TOONFLOW AI scene generation.

These errors are part of the public API. They are designed to be useful to
future UI / operator layers and to be testable without Blender.

The generation layer never prints. Callers are responsible for surfacing
these errors to the user.
"""


class GenerationError(Exception):
    """Base class for all TOONFLOW AI scene generation errors."""


class InvalidScenePlanError(GenerationError):
    """The Scene Plan failed schema validation before generation started.

    Attributes:
        errors: Tuple of :class:`scene_plan.ValidationError` instances.
    """

    def __init__(self, errors):
        self.errors = tuple(errors)
        message = (
            "Scene Plan failed validation; generation was not started. "
            f"{len(self.errors)} error(s) found."
        )
        super().__init__(message)


class UnknownAssetError(GenerationError):
    """A Scene Plan referenced an asset that is not in the Asset Registry.

    Attributes:
        asset_id: The unknown asset identifier from the Scene Plan.
        asset_type: Either ``"environment"`` or ``"character"``.
    """

    def __init__(self, asset_id, asset_type):
        self.asset_id = asset_id
        self.asset_type = asset_type
        super().__init__(
            f"Unknown {asset_type} asset id {asset_id!r}; "
            "the Asset Registry does not contain this identifier."
        )


class BlenderUnavailableError(GenerationError):
    """The Blender ``bpy`` module is not importable in the current process."""


class UnknownCharacterError(GenerationError):
    """A pose request referenced an unknown character id.

    Attributes:
        character_id: The unknown character identifier.
    """

    def __init__(self, character_id):
        self.character_id = character_id
        super().__init__(
            f"Unknown character id {character_id!r}; "
            "the Asset Registry does not contain this identifier."
        )


class MissingCharacterError(GenerationError):
    """No generated TOONFLOW character root exists for the given id.

    Attributes:
        character_id: The requested character identifier.
    """

    def __init__(self, character_id):
        self.character_id = character_id
        super().__init__(
            f"No generated TOONFLOW character root for {character_id!r}; "
            "call generate_scene() before requesting a pose."
        )


class UnknownPoseError(GenerationError):
    """The pose name is not part of the supported pose set.

    Attributes:
        pose_name: The unknown pose identifier.
        supported: Tuple of supported pose names.
    """

    def __init__(self, pose_name, supported):
        self.pose_name = pose_name
        self.supported = tuple(supported)
        super().__init__(
            f"Unknown pose name {pose_name!r}; "
            f"supported poses: {list(self.supported)}."
        )


class UnknownAnimationError(GenerationError):
    """The animation name is not part of the supported animation set.

    Attributes:
        animation_name: The unknown animation identifier.
        supported: Tuple of supported animation names.
    """

    def __init__(self, animation_name, supported):
        self.animation_name = animation_name
        self.supported = tuple(supported)
        super().__init__(
            f"Unknown animation name {animation_name!r}; "
            f"supported animations: {list(self.supported)}."
        )


class InvalidStartFrameError(GenerationError):
    """The start_frame argument is not a positive integer.

    Attributes:
        start_frame: The offending value (preserved as-given).
    """

    def __init__(self, start_frame):
        self.start_frame = start_frame
        super().__init__(
            "start_frame must be an integer >= 1 (bool is rejected); "
            f"got {start_frame!r}."
        )


class UnknownMouthStateError(GenerationError):
    """The mouth state is not part of the supported mouth-state set.

    Attributes:
        mouth_state: The unknown mouth-state identifier.
        supported: Tuple of supported mouth-state identifiers.
    """

    def __init__(self, mouth_state, supported):
        self.mouth_state = mouth_state
        self.supported = tuple(supported)
        super().__init__(
            f"Unknown mouth state {mouth_state!r}; "
            f"supported mouth states: {list(self.supported)}."
        )


class MissingCameraError(GenerationError):
    """No TOONFLOW camera object exists in the current Blender scene.

    Attributes:
        camera_name: The expected TOONFLOW camera name.
    """

    def __init__(self, camera_name):
        self.camera_name = camera_name
        super().__init__(
            f"No TOONFLOW camera named {camera_name!r} exists in the "
            "current Blender scene; call create_or_update_camera() before "
            "render_scene()."
        )


class InvalidCameraTypeError(GenerationError):
    """An object with the TOONFLOW camera name exists but is not a camera.

    Attributes:
        camera_name: The expected TOONFLOW camera name.
        actual_type: The actual ``bpy`` object type string.
    """

    def __init__(self, camera_name, actual_type):
        self.camera_name = camera_name
        self.actual_type = actual_type
        super().__init__(
            f"Object named {camera_name!r} exists but is of type "
            f"{actual_type!r}; refusing to modify unrelated scene state."
        )


class InvalidOutputPathError(GenerationError):
    """The supplied output path is not acceptable for rendering.

    Attributes:
        value: The offending value (preserved as-given).
    """

    def __init__(self, value):
        self.value = value
        super().__init__(
            "output_path must be a non-empty string or os.PathLike, "
            f"or None; got {value!r}."
        )


class RenderError(GenerationError):
    """The Blender render operation failed.

    Attributes:
        output_path: The output path the renderer was writing to.
        cause: The underlying exception message, when available.
    """

    def __init__(self, output_path, cause=None):
        self.output_path = output_path
        self.cause = str(cause) if cause is not None else None
        message = (
            f"Blender render to {output_path!r} failed."
            if self.cause is None
            else f"Blender render to {output_path!r} failed: {self.cause}"
        )
        super().__init__(message)