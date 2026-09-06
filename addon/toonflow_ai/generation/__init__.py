"""Basic Scene Generation for TOONFLOW AI.

Public API:
    from toonflow_ai.generation import (
        generate_scene,
        set_character_pose,
        animate_character,
        animate_lip_sync,
        create_or_update_camera,
        render_scene,
        GenerationResult,
    )

Pipeline:
    Scene Plan dict
        -> Scene Plan validation
        -> Asset Registry lookup
        -> Basic Scene Generator (Blender bpy)
        -> Blender scene objects

Character hierarchy, static poses, keyframed animation, the
deterministic TOONFLOW-owned camera, the deterministic lip-sync
mouth animation, and the deterministic TOONFLOW rendering pipeline
are layered on top of the existing generation pipeline without
changing it. ``set_character_pose`` applies an immediate,
deterministic static transform to a previously generated TOONFLOW
character. ``animate_character`` layers a deterministic keyframed
animation on top of the same character parts.
``animate_lip_sync`` layers a deterministic keyframed mouth-scale
animation on a TOONFLOW-owned mouth object parented to the
character's head. ``create_or_update_camera`` finds or creates the
deterministic ``TOONFLOW_CAMERA`` and orients it toward the
configured target. ``render_scene`` consumes the existing scene and
camera and renders the current frame to a deterministic output
path.

This phase does NOT use AI and does NOT load real assets. It uses
only simple Blender primitives as placeholders.
"""

from .animation import animate_character, supported_animations
from .animation_data import (
    ANIMATION_FRAME_OFFSETS,
    SUPPORTED_ANIMATIONS,
    animation_describe,
    animation_frame_offsets,
    animation_frames,
    animation_pose_at,
    animation_sequence,
    animation_uses_pose,
    is_supported_animation,
)
from .api import (
    GenerationResult,
    generate_scene,
)
from .camera import create_or_update_camera
from .camera_data import (
    TOONFLOW_CAMERA_NAME,
    camera_describe,
    camera_lens,
    camera_object_name,
    camera_position,
    camera_sensor_width,
    camera_target,
    is_toonflow_camera_name,
)
from .errors import (
    BlenderUnavailableError,
    GenerationError,
    InvalidCameraTypeError,
    InvalidOutputPathError,
    InvalidScenePlanError,
    InvalidStartFrameError,
    MissingCameraError,
    MissingCharacterError,
    RenderError,
    UnknownAnimationError,
    UnknownAssetError,
    UnknownCharacterError,
    UnknownMouthStateError,
    UnknownPoseError,
)
from .naming import (
    CHARACTER_PARTS,
    character_mouth_object_name,
    character_object_name,
    character_part_object_name,
    character_part_names,
)
from .lip_sync_data import (
    DEFAULT_LIP_SYNC_FRAME_OFFSETS,
    DEFAULT_LIP_SYNC_SEQUENCE,
    LIP_SYNC_FRAME_OFFSETS,
    MOUTH_LOCAL_OFFSET,
    MOUTH_MESH_SIZE,
    MOUTH_STATE_Z_SCALES,
    SUPPORTED_MOUTH_STATES,
    is_supported_mouth_state,
    lip_sync_describe,
    lip_sync_frame_offsets,
    lip_sync_frames,
    lip_sync_sequence,
    lip_sync_state_at,
    mouth_state_describe,
    mouth_state_z_scale,
    validate_start_frame as validate_lip_sync_start_frame,
)
from .lip_sync import animate_lip_sync, supported_mouth_states
from .render_data import (
    RENDER_ENGINE,
    RENDER_FILE_FORMAT,
    RENDER_OUTPUT_FILENAME,
    RENDER_RESOLUTION_PERCENTAGE,
    RENDER_RESOLUTION_X,
    RENDER_RESOLUTION_Y,
    SUPPORTED_FILE_FORMATS,
    SUPPORTED_RENDER_ENGINES,
    default_output_path,
    is_supported_file_format,
    is_supported_render_engine,
    render_settings_describe,
    validate_output_path,
)
from .rendering import render_describe, render_scene
from .pose import set_character_pose, supported_poses
from .poses import (
    SUPPORTED_POSES,
    is_supported_pose,
    pose_describe,
    pose_offset,
    pose_rotation_euler,
)

__all__ = (
    "generate_scene",
    "set_character_pose",
    "animate_character",
    "animate_lip_sync",
    "create_or_update_camera",
    "render_scene",
    "render_describe",
    "supported_poses",
    "supported_animations",
    "supported_mouth_states",
    "GenerationResult",
    "GenerationError",
    "InvalidScenePlanError",
    "InvalidStartFrameError",
    "InvalidCameraTypeError",
    "InvalidOutputPathError",
    "MissingCameraError",
    "RenderError",
    "UnknownAssetError",
    "BlenderUnavailableError",
    "UnknownCharacterError",
    "MissingCharacterError",
    "UnknownPoseError",
    "UnknownAnimationError",
    "CHARACTER_PARTS",
    "SUPPORTED_POSES",
    "SUPPORTED_ANIMATIONS",
    "ANIMATION_FRAME_OFFSETS",
    "TOONFLOW_CAMERA_NAME",
    "is_supported_pose",
    "is_supported_animation",
    "pose_offset",
    "pose_rotation_euler",
    "pose_describe",
    "animation_sequence",
    "animation_pose_at",
    "animation_uses_pose",
    "animation_frame_offsets",
    "animation_frames",
    "animation_describe",
    "camera_object_name",
    "camera_position",
    "camera_target",
    "camera_lens",
    "camera_sensor_width",
    "camera_describe",
    "is_toonflow_camera_name",
    "character_object_name",
    "character_part_object_name",
    "character_part_names",
    "character_mouth_object_name",
    "SUPPORTED_MOUTH_STATES",
    "DEFAULT_LIP_SYNC_SEQUENCE",
    "LIP_SYNC_FRAME_OFFSETS",
    "DEFAULT_LIP_SYNC_FRAME_OFFSETS",
    "MOUTH_STATE_Z_SCALES",
    "MOUTH_LOCAL_OFFSET",
    "MOUTH_MESH_SIZE",
    "is_supported_mouth_state",
    "lip_sync_sequence",
    "lip_sync_frame_offsets",
    "lip_sync_frames",
    "lip_sync_state_at",
    "lip_sync_describe",
    "validate_lip_sync_start_frame",
    "mouth_state_z_scale",
    "mouth_state_describe",
    "UnknownMouthStateError",
    "RENDER_RESOLUTION_X",
    "RENDER_RESOLUTION_Y",
    "RENDER_RESOLUTION_PERCENTAGE",
    "RENDER_FILE_FORMAT",
    "RENDER_ENGINE",
    "RENDER_OUTPUT_FILENAME",
    "SUPPORTED_FILE_FORMATS",
    "SUPPORTED_RENDER_ENGINES",
    "is_supported_file_format",
    "is_supported_render_engine",
    "render_settings_describe",
    "default_output_path",
    "validate_output_path",
)