"""Static pose data for TOONFLOW AI characters.

This module is pure Python and contains no ``bpy`` import. It defines
the supported pose identifiers and the deterministic, immediate
transform offsets that should be applied for each pose. The Blender-side
``pose.py`` module reads this data and applies the transforms.

A pose is **not** an animation. It is an immediate static transform of
the character parts:

- No keyframes are inserted.
- No Actions are created.
- No timeline or curve data is touched.
"""

CHARACTER_PART_LOCAL_OFFSETS = {
    "BODY": (0.0, 0.0, 0.0),
    "HEAD": (0.0, 0.0, 0.0),
    "LEFT_ARM": (0.0, 0.0, 0.0),
    "RIGHT_ARM": (0.0, 0.0, 0.0),
    "LEFT_LEG": (0.0, 0.0, 0.0),
    "RIGHT_LEG": (0.0, 0.0, 0.0),
}


CHARACTER_PART_LOCAL_ROTATIONS_EULER = {
    "BODY": (0.0, 0.0, 0.0),
    "HEAD": (0.0, 0.0, 0.0),
    "LEFT_ARM": (0.0, 0.0, 0.0),
    "RIGHT_ARM": (0.0, 0.0, 0.0),
    "LEFT_LEG": (0.0, 0.0, 0.0),
    "RIGHT_LEG": (0.0, 0.0, 0.0),
}


_POSE_DATA = {
    "neutral": {
        "offsets": CHARACTER_PART_LOCAL_OFFSETS,
        "rotations": CHARACTER_PART_LOCAL_ROTATIONS_EULER,
    },
    "wave": {
        "offsets": CHARACTER_PART_LOCAL_OFFSETS,
        "rotations": {
            "BODY": (0.0, 0.0, 0.0),
            "HEAD": (0.0, 0.0, 0.0),
            "LEFT_ARM": (0.0, 0.0, 0.0),
            "RIGHT_ARM": (0.0, 0.0, -1.5707963267948966),
            "LEFT_LEG": (0.0, 0.0, 0.0),
            "RIGHT_LEG": (0.0, 0.0, 0.0),
        },
    },
}


SUPPORTED_POSES = tuple(_POSE_DATA.keys())


def is_supported_pose(pose_name: object) -> bool:
    """Return True if *pose_name* is a supported pose identifier."""
    return isinstance(pose_name, str) and pose_name in _POSE_DATA


def pose_offset(pose_name: str, part: str):
    """Return the deterministic local offset tuple for *part* in *pose_name*."""
    return tuple(_POSE_DATA[pose_name]["offsets"][part])


def pose_rotation_euler(pose_name: str, part: str):
    """Return the deterministic local Euler rotation tuple for *part*."""
    return tuple(_POSE_DATA[pose_name]["rotations"][part])


def pose_describe(pose_name: str):
    """Return a deterministic, plain-Python description of *pose_name*."""
    data = _POSE_DATA[pose_name]
    return {
        "name": pose_name,
        "parts": tuple(
            {
                "part": part,
                "offset": tuple(data["offsets"][part]),
                "rotation_euler": tuple(data["rotations"][part]),
            }
            for part in CHARACTER_PART_LOCAL_OFFSETS
        ),
    }