"""Tests for TOONFLOW AI Voice and Lip Sync Foundation (PHASE-012)."""
import importlib.util
import os
import sys
import types
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADDON_PKG_PATH = os.path.join(ROOT, "addon", "toonflow_ai")
if ADDON_PKG_PATH not in sys.path:
    sys.path.insert(0, ADDON_PKG_PATH)


def _import_fresh(name, path):
    """Load a module from a file path into a fresh module slot."""
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_pkg(name, path):
    if name in sys.modules:
        return sys.modules[name]
    pkg = types.ModuleType(name)
    pkg.__path__ = [path]
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


class _LipSyncBpyStubMixin:
    """Mixin: ensure a minimal ``bpy`` stub is present for each test,
    and remove it again immediately afterwards so other test modules are
    not affected by side effects."""

    def setUp(self):
        _install_bpy_stub()

    def tearDown(self):
        _uninstall_bpy_stub()


_install_bpy_stub()
from toonflow_ai.generation import (  # noqa: E402
    DEFAULT_LIP_SYNC_FRAME_OFFSETS,
    DEFAULT_LIP_SYNC_SEQUENCE,
    LIP_SYNC_FRAME_OFFSETS,
    SUPPORTED_MOUTH_STATES,
    GenerationError,
    InvalidStartFrameError,
    UnknownMouthStateError,
    is_supported_mouth_state,
    lip_sync_describe,
    lip_sync_frame_offsets,
    lip_sync_frames,
    lip_sync_sequence,
    lip_sync_state_at,
    validate_lip_sync_start_frame,
)
from toonflow_ai.generation import lip_sync_data  # noqa: E402

_LIP_SYNC_DATA_FILE = lip_sync_data.__file__
with open(_LIP_SYNC_DATA_FILE, "r", encoding="utf-8") as f:
    _LIP_SYNC_DATA_SOURCE = f.read()


class TestSupportedMouthStates(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_tuple(self):
        self.assertEqual(SUPPORTED_MOUTH_STATES, ("REST", "OPEN", "CLOSED"))

    def test_defaults(self):
        self.assertEqual(DEFAULT_LIP_SYNC_SEQUENCE, ("REST", "OPEN", "CLOSED", "REST"))
        self.assertEqual(LIP_SYNC_FRAME_OFFSETS, DEFAULT_LIP_SYNC_FRAME_OFFSETS)

    def test_is_supported(self):
        for s in SUPPORTED_MOUTH_STATES:
            self.assertTrue(is_supported_mouth_state(s))
        for bad in [None, 1, 1.5, [], {}, "rest", "X", ""]:
            self.assertFalse(is_supported_mouth_state(bad))


class TestSequence(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_default(self):
        self.assertEqual(lip_sync_sequence(), DEFAULT_LIP_SYNC_SEQUENCE)

    def test_none_uses_default(self):
        self.assertEqual(lip_sync_sequence(None), DEFAULT_LIP_SYNC_SEQUENCE)

    def test_custom(self):
        self.assertEqual(lip_sync_sequence(["OPEN", "CLOSED"]), ("OPEN", "CLOSED"))

    def test_custom_returns_tuple(self):
        self.assertIsInstance(lip_sync_sequence(["REST"]), tuple)

    def test_string_rejected(self):
        with self.assertRaises(TypeError):
            lip_sync_sequence("OPEN")

    def test_custom_elements_must_be_strings(self):
        with self.assertRaises(TypeError):
            lip_sync_sequence([1, 2])
        with self.assertRaises(TypeError):
            lip_sync_sequence(["OPEN", 3])

    def test_custom_unknown_state(self):
        with self.assertRaises(UnknownMouthStateError):
            lip_sync_sequence(["SMILE"])

    def test_custom_empty(self):
        with self.assertRaises(ValueError):
            lip_sync_sequence([])


class TestStartFrameValidation(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_int_valid(self):
        self.assertEqual(validate_lip_sync_start_frame(1), 1)
        self.assertEqual(validate_lip_sync_start_frame(250), 250)

    def test_bool_rejected(self):
        for bad in [True, False]:
            with self.assertRaises(InvalidStartFrameError):
                validate_lip_sync_start_frame(bad)

    def test_non_int_rejected(self):
        for bad in [1.0, "10", None, [], 0, -1, -100]:
            with self.assertRaises(InvalidStartFrameError):
                validate_lip_sync_start_frame(bad)

    def test_error_hierarchy(self):
        with self.assertRaises(InvalidStartFrameError):
            validate_lip_sync_start_frame(0)
        try:
            validate_lip_sync_start_frame(0)
        except InvalidStartFrameError as exc:
            self.assertEqual(exc.start_frame, 0)
            self.assertIsInstance(exc, GenerationError)


class TestFrames(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_offsets_return_tuple_copy(self):
        a = lip_sync_frame_offsets()
        b = lip_sync_frame_offsets()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsInstance(a, tuple)

    def test_frames_default_sequence(self):
        frames = lip_sync_frames(1)
        self.assertEqual(frames, (1, 5, 9, 13))

    def test_frames_custom_sequence_short(self):
        frames = lip_sync_frames(10, sequence=["REST", "OPEN"])
        self.assertEqual(frames, (10, 14))

    def test_frames_custom_sequence_longer_than_offsets(self):
        frames = lip_sync_frames(
            1,
            sequence=["REST", "OPEN", "CLOSED", "REST", "OPEN"],
        )
        self.assertEqual(frames, (1, 5, 9, 13, 17))

    def test_frames_invalid_start(self):
        with self.assertRaises(InvalidStartFrameError):
            lip_sync_frames(0)
        with self.assertRaises(InvalidStartFrameError):
            lip_sync_frames(1.5)
        with self.assertRaises(InvalidStartFrameError):
            lip_sync_frames("1")

    def test_frames_rejects_invalid_sequence(self):
        with self.assertRaises(UnknownMouthStateError):
            lip_sync_frames(1, sequence=["X"])
        with self.assertRaises(ValueError):
            lip_sync_frames(1, sequence=[])


class TestStateAt(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_index(self):
        self.assertEqual(lip_sync_state_at(1, index=0), "REST")
        self.assertEqual(lip_sync_state_at(1, index=1), "OPEN")
        self.assertEqual(lip_sync_state_at(1, index=2), "CLOSED")
        self.assertEqual(lip_sync_state_at(1, index=3), "REST")

    def test_index_clamps_to_end(self):
        self.assertEqual(lip_sync_state_at(1, index=999), "REST")

    def test_index_negative_raises(self):
        with self.assertRaises(ValueError):
            lip_sync_state_at(1, index=-1)

    def test_frame_before_start_returns_first(self):
        self.assertEqual(lip_sync_state_at(10, frame=1), "REST")
        self.assertEqual(lip_sync_state_at(10, frame=9), "REST")

    def test_frame_exact(self):
        self.assertEqual(lip_sync_state_at(1, frame=1), "REST")
        self.assertEqual(lip_sync_state_at(1, frame=5), "OPEN")
        self.assertEqual(lip_sync_state_at(1, frame=9), "CLOSED")
        self.assertEqual(lip_sync_state_at(1, frame=13), "REST")

    def test_frame_between(self):
        self.assertEqual(lip_sync_state_at(1, frame=6), "OPEN")
        self.assertEqual(lip_sync_state_at(1, frame=12), "CLOSED")

    def test_frame_past_end_returns_last(self):
        self.assertEqual(lip_sync_state_at(1, frame=1000), "REST")

    def test_both_or_neither_raises(self):
        with self.assertRaises(ValueError):
            lip_sync_state_at(1)
        with self.assertRaises(ValueError):
            lip_sync_state_at(1, index=0, frame=10)

    def test_custom_sequence_index(self):
        self.assertEqual(
            lip_sync_state_at(1, sequence=["OPEN", "CLOSED", "REST"], index=1),
            "CLOSED",
        )


class TestDescribe(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_describe_default(self):
        d = lip_sync_describe(1)
        self.assertEqual(d["start_frame"], 1)
        self.assertEqual(d["states"], DEFAULT_LIP_SYNC_SEQUENCE)
        self.assertEqual(d["frame_offsets"], (0, 4, 8, 12))
        self.assertEqual(d["frames"], (1, 5, 9, 13))
        self.assertEqual(d["duration_frames"], 12)

    def test_describe_custom(self):
        d = lip_sync_describe(10, sequence=["OPEN", "REST", "CLOSED"])
        self.assertEqual(d["start_frame"], 10)
        self.assertEqual(d["states"], ("OPEN", "REST", "CLOSED"))
        self.assertEqual(d["frame_offsets"], (0, 4, 8))
        self.assertEqual(d["frames"], (10, 14, 18))
        self.assertEqual(d["duration_frames"], 8)


class TestArchitecture(_LipSyncBpyStubMixin, unittest.TestCase):
    def test_no_bpy_import_in_lip_sync_data(self):
        for forbidden in (
            "import bpy",
            "from bpy",
            "bpy.types",
            "bpy.props",
            "bpy.utils",
            "keyframe_insert",
            "shape_key",
            "armature",
        ):
            self.assertNotIn(forbidden, _LIP_SYNC_DATA_SOURCE, forbidden)

    def test_no_ai_or_network_imports(self):
        for forbidden in (
            "import ai\n",
            "from ai",
            "import ollama",
            "from ollama",
            "import urllib",
            "from urllib",
            "import requests",
            "from requests",
            "import audio",
            "from audio",
            "import wave",
            "from wave",
            "import soundfile",
            "from soundfile",
            "import librosa",
            "from librosa",
            "import speech_recognition",
        ):
            self.assertNotIn(forbidden, _LIP_SYNC_DATA_SOURCE, forbidden)

    def test_no_print(self):
        self.assertNotIn("print(", _LIP_SYNC_DATA_SOURCE)

    def test_exports_complete(self):
        for name in (
            "SUPPORTED_MOUTH_STATES",
            "DEFAULT_LIP_SYNC_SEQUENCE",
            "LIP_SYNC_FRAME_OFFSETS",
            "DEFAULT_LIP_SYNC_FRAME_OFFSETS",
            "is_supported_mouth_state",
            "lip_sync_sequence",
            "lip_sync_frame_offsets",
            "validate_start_frame",
            "lip_sync_frames",
            "lip_sync_state_at",
            "lip_sync_describe",
        ):
            self.assertTrue(hasattr(lip_sync_data, name), name)


_uninstall_bpy_stub()


if __name__ == "__main__":
    unittest.main()
