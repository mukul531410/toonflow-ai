"""Tests for TOONFLOW AI Blender Lip Sync Animation (PHASE-013)."""
import ast
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ADDON_PKG_PATH = ROOT / "addon" / "toonflow_ai"
if str(ADDON_PKG_PATH) not in sys.path:
    sys.path.insert(0, str(ADDON_PKG_PATH))


def _ensure_pkg(name, path):
    if name in sys.modules:
        return sys.modules[name]
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(path)]
    sys.modules[name] = pkg
    return pkg


_ensure_pkg("toonflow_ai", ADDON_PKG_PATH)


_LIP_SYNC_BPY_SAVED = {}


def _install_bpy_stub():
    for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils"):
        if name in sys.modules and name not in _LIP_SYNC_BPY_SAVED:
            _LIP_SYNC_BPY_SAVED[name] = sys.modules.pop(name)
    bpy_stub = types.ModuleType("bpy")
    bpy_stub.types = types.ModuleType("bpy.types")
    bpy_stub.props = types.ModuleType("bpy.props")
    bpy_stub.utils = types.ModuleType("bpy.utils")
    sys.modules["bpy"] = bpy_stub
    sys.modules["bpy.types"] = bpy_stub.types
    sys.modules["bpy.props"] = bpy_stub.props
    sys.modules["bpy.utils"] = bpy_stub.utils


def _uninstall_bpy_stub():
    for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils"):
        sys.modules.pop(name, None)
    for name, mod in _LIP_SYNC_BPY_SAVED.items():
        sys.modules[name] = mod
    _LIP_SYNC_BPY_SAVED.clear()


def _load_lip_sync_module(bpy_stub):
    for name in ("bpy", "bpy.types"):
        sys.modules.pop(name, None)
    sys.modules["bpy"] = bpy_stub
    sys.modules["bpy.types"] = bpy_stub.types
    for name in (
        "toonflow_ai.generation.lip_sync",
        "toonflow_ai.generation.lip_sync_data",
    ):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        "toonflow_ai.generation.lip_sync",
        ADDON_PKG_PATH / "generation" / "lip_sync.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["toonflow_ai.generation.lip_sync"] = module
    spec.loader.exec_module(module)
    return module


class _LipSyncBpyStubMixin:
    def setUp(self):
        _install_bpy_stub()

    def tearDown(self):
        _uninstall_bpy_stub()


_install_bpy_stub()
from toonflow_ai.generation import (  # noqa: E402
    DEFAULT_LIP_SYNC_SEQUENCE,
    GenerationError,
    InvalidStartFrameError,
    LIP_SYNC_FRAME_OFFSETS,
    MOUTH_LOCAL_OFFSET,
    MOUTH_MESH_SIZE,
    MOUTH_STATE_Z_SCALES,
    SUPPORTED_MOUTH_STATES,
    UnknownCharacterError,
    animate_lip_sync,
    character_mouth_object_name,
    character_object_name,
    character_part_object_name,
    character_part_names,
    is_supported_mouth_state,
    lip_sync_frames,
    lip_sync_sequence,
    mouth_state_describe,
    mouth_state_z_scale,
    supported_mouth_states,
    validate_lip_sync_start_frame,
)

import toonflow_ai.generation.lip_sync_data as lip_sync_data_mod  # noqa: E402
import toonflow_ai.generation.naming as naming_mod  # noqa: E402
import toonflow_ai.generation.lip_sync as lip_sync_mod  # noqa: E402

_uninstall_bpy_stub()


LIP_SYNC_DATA_SOURCE = (ADDON_PKG_PATH / "generation" / "lip_sync_data.py").read_text(
    encoding="utf-8"
)
LIP_SYNC_BLENDER_SOURCE = (ADDON_PKG_PATH / "generation" / "lip_sync.py").read_text(
    encoding="utf-8"
)
NAMING_SOURCE = (ADDON_PKG_PATH / "generation" / "naming.py").read_text(
    encoding="utf-8"
)


# --- Helpers ----------------------------------------------------------------

class _Action:
    def __init__(self, name):
        self.name = name
        self.fcurves = []


class _Keyframe:
    def __init__(self, frame, value=0.0):
        self.co = types.SimpleNamespace(x=frame, y=value)


class _FCurve:
    def __init__(self, data_path, array_index):
        self.data_path = data_path
        self.array_index = array_index
        self.keyframe_points = []


class _AnimData:
    def __init__(self):
        self.action = None


class _ChildrenLink:
    def __init__(self):
        self.objects = []

    def link(self, obj):
        self.objects.append(obj)


class _Object:
    def __init__(self, name):
        self.name = name
        self.type = "MESH"
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.children = _ChildrenLink()
        self.animation_data = _AnimData()

    def animation_data_create(self):
        if self.animation_data is None:
            self.animation_data = _AnimData()

    def keyframe_insert(self, data_path, frame):
        if self.animation_data is None:
            self.animation_data = _AnimData()
        action = self.animation_data.action
        if action is None:
            raise AssertionError(
                "keyframe_insert called without an assigned Action"
            )
        # Mirror Blender: F-Curves are per-index for vector data paths.
        if data_path == "scale":
            size = 3
        elif data_path in ("location", "rotation_euler"):
            size = 3
        else:
            size = 1
        for axis in range(size):
            fcurve = next(
                (
                    fc for fc in action.fcurves
                    if fc.data_path == data_path and fc.array_index == axis
                ),
                None,
            )
            if fcurve is None:
                fcurve = _FCurve(data_path, axis)
                action.fcurves.append(fcurve)
            fcurve.keyframe_points.append(_Keyframe(frame, 0.0))


class _Meshes:
    def __init__(self):
        self._store = {}

    def new(self, name):
        if name in self._store:
            return self._store[name]
        m = types.SimpleNamespace(name=name)
        m.from_pydata = lambda *a, **k: None
        m.update = lambda: None
        self._store[name] = m
        return m

    def get(self, name):
        return self._store.get(name)


class _Objects:
    """Minimal ``bpy.data.objects`` surrogate.

    Supports ``.new(name, mesh)`` and iteration over the registered
    objects. Used by the stubbed lip-sync tests.
    """

    def __init__(self):
        self._store = []

    def new(self, name, mesh=None):
        obj = _Object(name)
        self._store.append(obj)
        return obj

    def append(self, obj):
        self._store.append(obj)

    def __iter__(self):
        return iter(self._store)

    def __len__(self):
        return len(self._store)

    def __contains__(self, name):
        return any(getattr(o, "name", None) == name for o in self._store)


def _make_bpy_stub():
    actions_store = {}

    def _new_action(name):
        if name in actions_store:
            return actions_store[name]
        action = _Action(name)
        actions_store[name] = action
        return action

    actions_ns = types.SimpleNamespace(
        new=_new_action, get=lambda n: actions_store.get(n)
    )

    bpy_data = types.SimpleNamespace(
        actions=actions_ns,
        objects=_Objects(),
        meshes=_Meshes(),
    )

    bpy_types = types.ModuleType("bpy.types")
    bpy_types.PropertyGroup = type("PropertyGroup", (), {})

    bpy = types.ModuleType("bpy")
    bpy.data = bpy_data
    bpy.types = bpy_types
    bpy.context = types.SimpleNamespace(
        scene=types.SimpleNamespace(collection=types.SimpleNamespace(children=[])),
        view_layer=types.SimpleNamespace(update=lambda: None),
    )
    return bpy, _Object, actions_store


def _make_root_and_parts(bpy_stub, character_id):
    root = _Object(character_object_name(character_id))
    bpy_stub.data.objects.append(root)
    parts = {}
    for part in ("BODY", "HEAD", "LEFT_ARM", "RIGHT_ARM", "LEFT_LEG", "RIGHT_LEG"):
        obj = _Object(character_part_object_name(character_id, part))
        bpy_stub.data.objects.append(obj)
        parts[part] = obj
    return root, parts


# --- A. Naming tests --------------------------------------------------------

class MouthNamingTests(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_deterministic_naming(self):
        self.assertEqual(
            character_mouth_object_name("husband"),
            "TOONFLOW_CHARACTER_HUSBAND_MOUTH",
        )
        self.assertEqual(
            character_mouth_object_name("wife"),
            "TOONFLOW_CHARACTER_WIFE_MOUTH",
        )

    def test_naming_helper_lives_in_naming_module(self):
        self.assertTrue(hasattr(naming_mod, "character_mouth_object_name"))
        self.assertEqual(
            naming_mod.character_mouth_object_name("Husband"),
            "TOONFLOW_CHARACTER_HUSBAND_MOUTH",
        )

    def test_existing_character_naming_unchanged(self):
        self.assertEqual(character_object_name("husband"), "TOONFLOW_CHARACTER_HUSBAND")
        self.assertEqual(
            character_part_object_name("husband", "HEAD"),
            "TOONFLOW_CHARACTER_HUSBAND_HEAD",
        )
        self.assertEqual(
            character_part_names("husband"),
            (
                "TOONFLOW_CHARACTER_HUSBAND_BODY",
                "TOONFLOW_CHARACTER_HUSBAND_HEAD",
                "TOONFLOW_CHARACTER_HUSBAND_LEFT_ARM",
                "TOONFLOW_CHARACTER_HUSBAND_RIGHT_ARM",
                "TOONFLOW_CHARACTER_HUSBAND_LEFT_LEG",
                "TOONFLOW_CHARACTER_HUSBAND_RIGHT_LEG",
            ),
        )


# --- B. Validation tests ----------------------------------------------------

class LipSyncInputValidationTests(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_unknown_character_raises(self):
        with self.assertRaises(UnknownCharacterError):
            animate_lip_sync("stranger", start_frame=1)

    def test_empty_character_raises(self):
        with self.assertRaises(UnknownCharacterError):
            animate_lip_sync("", start_frame=1)

    def test_non_string_character_raises(self):
        for bad in (None, 1, [], {}):
            with self.assertRaises(UnknownCharacterError):
                animate_lip_sync(bad, start_frame=1)

    def test_valid_character_accepted(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")
        # Should reach the bpy branch and succeed; if bpy is missing, this
        # would raise BlenderUnavailableError instead.
        result = module.animate_lip_sync("husband", start_frame=1)
        self.assertEqual(result["character_id"], "husband")

    def test_start_frame_validation(self):
        # Valid
        self.assertEqual(validate_lip_sync_start_frame(1), 1)
        self.assertEqual(validate_lip_sync_start_frame(250), 250)
        # Invalid
        for bad in (True, False, 1.0, "10", None, [], 0, -1, -100):
            with self.assertRaises(InvalidStartFrameError):
                validate_lip_sync_start_frame(bad)

    def test_start_frame_hierarchy(self):
        try:
            validate_lip_sync_start_frame(0)
        except InvalidStartFrameError as exc:
            self.assertEqual(exc.start_frame, 0)
            self.assertIsInstance(exc, GenerationError)
        else:
            self.fail("Expected InvalidStartFrameError")


# --- C. Blender unavailable -------------------------------------------------

class LipSyncBlenderUnavailableTests(_LipSyncBpyStubMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        # Ensure bpy is not importable.
        for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils"):
            if name in sys.modules:
                del sys.modules[name]
        import builtins
        self._orig_import = builtins.__import__
        def _blocked(name, *a, **k):
            if name == "bpy" or name.startswith("bpy."):
                raise ImportError("bpy is intentionally unavailable for this test.")
            return self._orig_import(name, *a, **k)
        builtins.__import__ = _blocked

    def tearDown(self):
        import builtins
        builtins.__import__ = self._orig_import
        super().tearDown()

    def test_valid_inputs_raise_blender_unavailable(self):
        from toonflow_ai.generation.errors import BlenderUnavailableError
        bpy_stub = types.ModuleType("bpy")
        bpy_stub.types = types.ModuleType("bpy.types")
        # The freshly loaded module has a fresh reference to ``bpy`` already
        # attempted; instead of relying on import, call the validator
        # functions to make sure they reach the bpy branch.
        module = _load_lip_sync_module(bpy_stub)
        for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils"):
            sys.modules.pop(name, None)
        with self.assertRaises(BlenderUnavailableError):
            module.animate_lip_sync("husband", start_frame=1)


# --- D. Stubbed Blender behavior -------------------------------------------

class LipSyncBlenderBehaviorTests(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_creates_mouth_when_absent(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")

        result = module.animate_lip_sync("husband", start_frame=1)

        self.assertEqual(
            result["mouth_object_name"],
            "TOONFLOW_CHARACTER_HUSBAND_MOUTH",
        )
        # Mouth must exist exactly once in bpy.data.objects.
        mouths = [
            o for o in bpy_stub.data.objects
            if o.name == "TOONFLOW_CHARACTER_HUSBAND_MOUTH"
        ]
        self.assertEqual(len(mouths), 1)

    def test_mouth_is_parented_to_head(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        root, parts = _make_root_and_parts(bpy_stub, "husband")

        module.animate_lip_sync("husband", start_frame=1)

        head = parts["HEAD"]
        mouth = next(
            o for o in bpy_stub.data.objects
            if o.name == "TOONFLOW_CHARACTER_HUSBAND_MOUTH"
        )
        self.assertIn(mouth, head.children.objects)

    def test_existing_mouth_reused(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")
        # Pre-create a mouth object that should be reused.
        pre = _Object("TOONFLOW_CHARACTER_HUSBAND_MOUTH")
        bpy_stub.data.objects.append(pre)

        module.animate_lip_sync("husband", start_frame=1)

        mouths = [
            o for o in bpy_stub.data.objects
            if o.name == "TOONFLOW_CHARACTER_HUSBAND_MOUTH"
        ]
        self.assertEqual(len(mouths), 1)
        # The reused object must be the pre-existing one (same identity).
        self.assertIs(mouths[0], pre)

    def test_rest_open_closed_scales(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")

        result = module.animate_lip_sync("husband", start_frame=1)

        z_by_state = {kf["state"]: kf["scale"][2] for kf in result["keyframes"]}
        self.assertEqual(z_by_state["REST"], MOUTH_STATE_Z_SCALES["REST"])
        self.assertEqual(z_by_state["OPEN"], MOUTH_STATE_Z_SCALES["OPEN"])
        self.assertEqual(z_by_state["CLOSED"], MOUTH_STATE_Z_SCALES["CLOSED"])
        # Visibly distinct.
        self.assertNotEqual(z_by_state["OPEN"], z_by_state["REST"])
        self.assertNotEqual(z_by_state["CLOSED"], z_by_state["REST"])
        self.assertNotEqual(z_by_state["CLOSED"], z_by_state["OPEN"])

    def test_keyframes_at_expected_frames(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")

        result = module.animate_lip_sync("husband", start_frame=1)

        self.assertEqual(result["frames"], (1, 5, 9, 13))
        self.assertEqual(
            [kf["frame"] for kf in result["keyframes"]],
            [1, 5, 9, 13],
        )

        # Verify keyframes were inserted into the mouth's action.
        mouth = next(
            o for o in bpy_stub.data.objects
            if o.name == "TOONFLOW_CHARACTER_HUSBAND_MOUTH"
        )
        action = mouth.animation_data.action
        self.assertIsNotNone(action)
        scale_frames = sorted(
            int(round(kp.co.x))
            for fc in action.fcurves if fc.data_path == "scale"
            for kp in fc.keyframe_points
        )
        # 3 fcurves (x,y,z) x 4 keyframes each = 12 entries total, all at
        # 1, 5, 9, 13.
        self.assertEqual(scale_frames, [1, 1, 1, 5, 5, 5, 9, 9, 9, 13, 13, 13])

    def test_default_sequence_applied(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")

        result = module.animate_lip_sync("husband", start_frame=1)
        self.assertEqual(result["states"], DEFAULT_LIP_SYNC_SEQUENCE)

    def test_repeated_call_is_deterministic(self):
        bpy_stub, _Object, actions_store = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")

        module.animate_lip_sync("husband", start_frame=1)
        module.animate_lip_sync("husband", start_frame=1)

        # One mouth object.
        mouths = [
            o for o in bpy_stub.data.objects
            if o.name == "TOONFLOW_CHARACTER_HUSBAND_MOUTH"
        ]
        self.assertEqual(len(mouths), 1)
        # One action.
        self.assertEqual(
            sum(1 for n in actions_store if n.startswith("TOONFLOW_LIP_SYNC_")),
            1,
        )
        # Scale fcurves still have exactly 4 distinct frames x 3 axes.
        mouth = mouths[0]
        scale_frames = sorted(set(
            int(round(kp.co.x))
            for fc in mouth.animation_data.action.fcurves
            if fc.data_path == "scale"
            for kp in fc.keyframe_points
        ))
        self.assertEqual(scale_frames, [1, 5, 9, 13])

    def test_only_lip_sync_frames_replaced(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "wife")

        # First call.
        module.animate_lip_sync("wife", start_frame=1)
        wife_mouth = next(
            o for o in bpy_stub.data.objects
            if o.name == "TOONFLOW_CHARACTER_WIFE_MOUTH"
        )
        action = wife_mouth.animation_data.action
        # Inject an unrelated keyframe at frame 99 on every scale fcurve.
        for fc in action.fcurves:
            if fc.data_path == "scale":
                fc.keyframe_points.append(_Keyframe(99.0, 0.0))

        # Second call.
        module.animate_lip_sync("wife", start_frame=1)

        scale_frames = sorted(set(
            int(round(kp.co.x))
            for fc in action.fcurves if fc.data_path == "scale"
            for kp in fc.keyframe_points
        ))
        self.assertIn(99, scale_frames)
        # The targeted frames remain; the unrelated 99 also remains.
        self.assertEqual(scale_frames, [1, 5, 9, 13, 99])

    def test_unrelated_objects_untouched(self):
        bpy_stub, _Object, actions_store = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")
        # Add a user object that must never be touched.
        user_obj = _Object("UserCube")
        bpy_stub.data.objects.append(user_obj)

        module.animate_lip_sync("husband", start_frame=1)

        # User object has no action assigned.
        self.assertIsNone(user_obj.animation_data.action)
        # No LIP_SYNC action was created for the user object.
        self.assertFalse(
            any(getattr(a, "name", "").startswith("TOONFLOW_LIP_SYNC_")
                for a in [user_obj.animation_data.action] if a is not None)
        )

    def test_another_character_untouched(self):
        bpy_stub, _Object, actions_store = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")
        _make_root_and_parts(bpy_stub, "wife")

        module.animate_lip_sync("husband", start_frame=1)

        wife_mouth = next(
            (o for o in bpy_stub.data.objects
             if o.name == "TOONFLOW_CHARACTER_WIFE_MOUTH"),
            None,
        )
        self.assertIsNone(wife_mouth)
        # No LIP_SYNC_WIFE action was created.
        self.assertNotIn("TOONFLOW_LIP_SYNC_WIFE", actions_store)

    def test_missing_character_raises(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        # No root/parts created.
        from toonflow_ai.generation.errors import MissingCharacterError
        with self.assertRaises(MissingCharacterError):
            module.animate_lip_sync("husband", start_frame=1)

    def test_keyframe_insert_uses_scale_only(self):
        bpy_stub, _Object, _ = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")

        module.animate_lip_sync("husband", start_frame=1)

        mouth = next(
            o for o in bpy_stub.data.objects
            if o.name == "TOONFLOW_CHARACTER_HUSBAND_MOUTH"
        )
        action = mouth.animation_data.action
        paths = sorted({fc.data_path for fc in action.fcurves})
        self.assertEqual(paths, ["scale"])

    def test_action_name_deterministic(self):
        bpy_stub, _Object, actions_store = _make_bpy_stub()
        module = _load_lip_sync_module(bpy_stub)
        _make_root_and_parts(bpy_stub, "husband")

        result = module.animate_lip_sync("husband", start_frame=1)
        self.assertEqual(result["action_name"], "TOONFLOW_LIP_SYNC_HUSBAND")
        self.assertIn("TOONFLOW_LIP_SYNC_HUSBAND", actions_store)


# --- E. Architecture tests --------------------------------------------------

class LipSyncArchitectureTests(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_lip_sync_data_remains_bpy_free(self):
        tree = ast.parse(LIP_SYNC_DATA_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(
                        alias.name == "bpy" or alias.name.startswith("bpy."),
                        f"bpy import in lip_sync_data: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    (node.module or "").startswith("bpy"),
                    f"bpy 'from' import in lip_sync_data: {node.module}",
                )

    def test_blender_lip_sync_uses_existing_helpers(self):
        # Must reuse lip_sync_data constants and helpers, not duplicate.
        for needle in (
            "from .lip_sync_data import",
            "lip_sync_sequence",
            "lip_sync_frames",
            "mouth_state_z_scale",
            "validate_start_frame",
        ):
            self.assertIn(needle, LIP_SYNC_BLENDER_SOURCE, needle)

    def test_no_state_constant_duplication(self):
        # The Blender module must not redefine REST/OPEN/CLOSED as a tuple.
        for forbidden in (
            '("REST", "OPEN", "CLOSED")',
            '("OPEN", "CLOSED", "REST")',
            '("REST", "OPEN", "CLOSED", "REST")',
        ):
            self.assertNotIn(forbidden, LIP_SYNC_BLENDER_SOURCE, forbidden)

    def test_no_frame_offset_duplication(self):
        for forbidden in (
            "(0, 4, 8, 12)",
            "= (0, 4, 8, 12)",
        ):
            self.assertNotIn(forbidden, LIP_SYNC_BLENDER_SOURCE, forbidden)

    def test_no_ai_ollama_http_urllib(self):
        for forbidden in (
            "import ai", "from ai",
            "import ollama", "from ollama",
            "import urllib", "from urllib",
            "import requests", "from requests",
        ):
            self.assertNotIn(forbidden, LIP_SYNC_BLENDER_SOURCE, forbidden)

    def test_no_audio_dependencies(self):
        for forbidden in (
            "import wave", "from wave",
            "import soundfile", "from soundfile",
            "import librosa", "from librosa",
            "import speech_recognition", "from speech_recognition",
            "import audio", "from audio",
        ):
            self.assertNotIn(forbidden, LIP_SYNC_BLENDER_SOURCE, forbidden)

    def test_no_tts_or_speech(self):
        for forbidden in (
            "tts", "text_to_speech", "speech", "phoneme",
            "say_", "synth", "pronunciation",
        ):
            self.assertNotIn(forbidden, LIP_SYNC_BLENDER_SOURCE.lower(), forbidden)

    def test_no_armatures_bones_shape_keys_constraints(self):
        # Use AST-based checks so docstrings/comments don't cause false
        # positives. The phase explicitly forbids rigging, shape keys,
        # constraints, and drivers.
        tree = ast.parse(LIP_SYNC_BLENDER_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in {"armature", "bone", "shape_key", "constraint", "driver"}:
                    self.fail(
                        f"Forbidden attribute access '.{node.attr}' in lip_sync.py"
                    )
            if isinstance(node, ast.Name):
                if node.id in {"armature", "bone", "shape_key", "constraint", "driver"}:
                    self.fail(
                        f"Forbidden name '{node.id}' in lip_sync.py"
                    )

    def test_uses_data_api_not_bpy_ops(self):
        # The Blender lip-sync module must not depend on bpy.ops.
        for forbidden in ("bpy.ops", "from bpy import ops"):
            self.assertNotIn(forbidden, LIP_SYNC_BLENDER_SOURCE, forbidden)

    def test_uses_keyframe_insert(self):
        self.assertIn("keyframe_insert", LIP_SYNC_BLENDER_SOURCE)
        self.assertIn("data_path=\"scale\"", LIP_SYNC_BLENDER_SOURCE)

    def test_uses_existing_naming_helpers(self):
        for needle in (
            "character_object_name",
            "character_mouth_object_name",
            "character_part_object_name",
            "is_toonflow_name",
        ):
            self.assertIn(needle, LIP_SYNC_BLENDER_SOURCE, needle)

    def test_uses_existing_error_classes(self):
        for needle in (
            "BlenderUnavailableError",
            "InvalidStartFrameError",
            "MissingCharacterError",
            "UnknownCharacterError",
        ):
            self.assertIn(needle, LIP_SYNC_BLENDER_SOURCE, needle)

    def test_no_print_or_io_side_effects(self):
        self.assertNotIn("print(", LIP_SYNC_BLENDER_SOURCE)
        self.assertNotIn("input(", LIP_SYNC_BLENDER_SOURCE)


# --- F. Data layer integration (no bpy) -------------------------------------

class LipSyncDataIntegrationTests(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_supported_states(self):
        self.assertEqual(SUPPORTED_MOUTH_STATES, ("REST", "OPEN", "CLOSED"))
        self.assertEqual(
            supported_mouth_states(), ("REST", "OPEN", "CLOSED")
        )

    def test_mouth_state_z_scales_distinct(self):
        scales = MOUTH_STATE_Z_SCALES
        self.assertEqual(scales["REST"], 1.0)
        self.assertEqual(scales["OPEN"], 2.0)
        self.assertEqual(scales["CLOSED"], 0.5)
        self.assertEqual(len(set(scales.values())), 3)

    def test_mouth_state_z_scale_helper(self):
        self.assertEqual(mouth_state_z_scale("REST"), 1.0)
        self.assertEqual(mouth_state_z_scale("OPEN"), 2.0)
        self.assertEqual(mouth_state_z_scale("CLOSED"), 0.5)

    def test_mouth_state_z_scale_rejects_unknown(self):
        from toonflow_ai.generation import UnknownMouthStateError
        with self.assertRaises(UnknownMouthStateError):
            mouth_state_z_scale("SMILE")

    def test_mouth_state_describe(self):
        d = mouth_state_describe("OPEN")
        self.assertEqual(d["state"], "OPEN")
        self.assertEqual(d["z_scale"], 2.0)

    def test_lip_sync_sequence_default(self):
        self.assertEqual(
            lip_sync_sequence(), DEFAULT_LIP_SYNC_SEQUENCE
        )

    def test_lip_sync_frames_default(self):
        self.assertEqual(lip_sync_frames(1), (1, 5, 9, 13))
        self.assertEqual(lip_sync_frames(1), tuple(1 + o for o in LIP_SYNC_FRAME_OFFSETS))

    def test_mouth_size_offset_defined(self):
        self.assertEqual(len(MOUTH_MESH_SIZE), 3)
        self.assertEqual(len(MOUTH_LOCAL_OFFSET), 3)
        # Reasonable, positive dimensions.
        for v in MOUTH_MESH_SIZE:
            self.assertGreater(v, 0.0)


if __name__ == "__main__":
    unittest.main()
