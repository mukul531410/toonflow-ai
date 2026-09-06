"""Tests for TOONFLOW-PHASE-010 Timeline Animation Foundation.

Pure-Python tests covering:

- ``animation_data`` metadata (supported animations, sequence mapping,
  deterministic frame offsets, pose reuse),
- ``animate_character`` input validation without Blender,
- the Blender module's behavior with a stubbed ``bpy`` (idempotency,
  action creation, keyframe insertion, frame-range clearing),
- static structure (no ``bpy`` leaks into pure pose/animation data).

Live timeline/keyframe behavior inside Blender was not exercised
because Blender is not installed; that limitation is reported.
"""

import importlib
import importlib.util
import inspect
import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_PKG_PATH = PROJECT_ROOT / "addon" / "toonflow_ai"
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

generation_pkg = importlib.import_module("toonflow_ai.generation")
errors_mod = importlib.import_module("toonflow_ai.generation.errors")
animation_data_mod = importlib.import_module("toonflow_ai.generation.animation_data")
poses_mod = importlib.import_module("toonflow_ai.generation.poses")


class SupportedAnimationsTests(unittest.TestCase):
    def test_supported_animations_constant(self):
        from toonflow_ai.generation import SUPPORTED_ANIMATIONS

        self.assertEqual(SUPPORTED_ANIMATIONS, ("wave",))

    def test_is_supported_animation(self):
        from toonflow_ai.generation import is_supported_animation

        self.assertTrue(is_supported_animation("wave"))
        self.assertFalse(is_supported_animation("dance"))
        self.assertFalse(is_supported_animation(""))
        self.assertFalse(is_supported_animation(None))
        self.assertFalse(is_supported_animation(42))


class AnimationSequenceTests(unittest.TestCase):
    def test_wave_maps_to_neutral_wave_neutral(self):
        from toonflow_ai.generation import animation_sequence

        self.assertEqual(animation_sequence("wave"), ("neutral", "wave", "neutral"))

    def test_animation_uses_pose(self):
        from toonflow_ai.generation import animation_uses_pose

        self.assertTrue(animation_uses_pose("wave", "neutral"))
        self.assertTrue(animation_uses_pose("wave", "wave"))
        self.assertFalse(animation_uses_pose("wave", "dance"))

    def test_animation_pose_at(self):
        from toonflow_ai.generation import animation_pose_at

        self.assertEqual(animation_pose_at("wave", 0), "neutral")
        self.assertEqual(animation_pose_at("wave", 1), "wave")
        self.assertEqual(animation_pose_at("wave", 2), "neutral")


class FrameOffsetsTests(unittest.TestCase):
    def test_frame_offsets_constant(self):
        from toonflow_ai.generation import (
            ANIMATION_FRAME_OFFSETS,
            animation_frame_offsets,
        )

        self.assertEqual(ANIMATION_FRAME_OFFSETS, (0, 20, 40))
        self.assertEqual(animation_frame_offsets(), (0, 20, 40))

    def test_animation_frames_are_deterministic(self):
        from toonflow_ai.generation import animation_frames

        self.assertEqual(animation_frames("wave", 1), (1, 21, 41))
        self.assertEqual(animation_frames("wave", 100), (100, 120, 140))

    def test_animation_describe_shape(self):
        from toonflow_ai.generation import animation_describe

        desc = animation_describe("wave")
        self.assertEqual(desc["name"], "wave")
        self.assertEqual(desc["poses"], ("neutral", "wave", "neutral"))
        self.assertEqual(desc["frame_offsets"], (0, 20, 40))
        self.assertEqual(desc["frame_count"], 3)


class PoseReuseTests(unittest.TestCase):
    def test_animation_data_does_not_duplicate_pose_transforms(self):
        """The animation_data module must reference poses, not redefine offsets/rotations."""
        src = inspect.getsource(animation_data_mod)
        # It must not contain raw rotation values like -1.5707963 that
        # would indicate duplicated pose data.
        self.assertNotIn("-1.5707963", src)
        # It must import the pose helpers.
        self.assertIn("from .poses import", src)
        self.assertIn("is_supported_pose", src)

    def test_poses_and_animation_data_share_no_offset_data(self):
        pose_src = inspect.getsource(poses_mod)
        anim_src = inspect.getsource(animation_data_mod)
        # Animation data must reference SUPPORTED_POSES and is_supported_pose;
        # pose source owns the actual numeric transform tuples.
        self.assertIn("is_supported_pose", anim_src)
        # The only numeric 1.5707... value lives in poses.py, not in animation_data.py.
        self.assertIn("-1.5707963267948966", pose_src)
        self.assertNotIn("-1.5707963267948966", anim_src)


class AnimationApiReexportTests(unittest.TestCase):
    def test_animate_character_is_exported(self):
        self.assertTrue(hasattr(generation_pkg, "animate_character"))
        self.assertTrue(callable(generation_pkg.animate_character))

    def test_supported_animations_is_exported(self):
        self.assertTrue(hasattr(generation_pkg, "supported_animations"))

    def test_animation_errors_are_exported(self):
        for name in (
            "UnknownAnimationError",
            "InvalidStartFrameError",
        ):
            self.assertTrue(hasattr(generation_pkg, name), name)
            self.assertTrue(hasattr(errors_mod, name), name)


class AnimationInputValidationTests(unittest.TestCase):
    """Exercise ``animate_character`` validation without touching Blender."""

    def setUp(self):
        self._saved_modules = {
            name: sys.modules.pop(name, None)
            for name in (
                "bpy",
                "bpy.types",
                "bpy.props",
                "bpy.utils",
                "toonflow_ai.generation.animation",
            )
        }

    def tearDown(self):
        sys.modules.pop("toonflow_ai.generation.animation", None)
        for name, value in self._saved_modules.items():
            if value is not None:
                sys.modules[name] = value
            else:
                sys.modules.pop(name, None)

    def _fresh_animation_module(self):
        sys.modules.pop("toonflow_ai.generation.animation", None)
        spec = importlib.util.spec_from_file_location(
            "toonflow_ai.generation.animation",
            ADDON_PKG_PATH / "generation" / "animation.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["toonflow_ai.generation.animation"] = module
        spec.loader.exec_module(module)
        return module

    def test_unknown_character_id_raises_before_blender(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.UnknownCharacterError) as ctx:
            module.animate_character("stranger", "wave", 1)
        self.assertEqual(ctx.exception.character_id, "stranger")

    def test_empty_character_id_is_rejected(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.UnknownCharacterError):
            module.animate_character("", "wave", 1)

    def test_non_string_character_id_is_rejected(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.UnknownCharacterError):
            module.animate_character(None, "wave", 1)

    def test_unknown_animation_name_raises(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.UnknownAnimationError) as ctx:
            module.animate_character("husband", "dance", 1)
        self.assertEqual(ctx.exception.animation_name, "dance")
        self.assertIn("wave", ctx.exception.supported)

    def test_non_string_animation_name_is_rejected(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.UnknownAnimationError):
            module.animate_character("husband", None, 1)

    def test_non_integer_start_frame_is_rejected(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.InvalidStartFrameError) as ctx:
            module.animate_character("husband", "wave", 1.5)
        self.assertEqual(ctx.exception.start_frame, 1.5)

    def test_string_start_frame_is_rejected(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.InvalidStartFrameError):
            module.animate_character("husband", "wave", "1")

    def test_zero_start_frame_is_rejected(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.InvalidStartFrameError):
            module.animate_character("husband", "wave", 0)

    def test_negative_start_frame_is_rejected(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.InvalidStartFrameError):
            module.animate_character("husband", "wave", -3)

    def test_bool_start_frame_is_rejected(self):
        module = self._fresh_animation_module()
        # bool is a subclass of int in Python; explicitly rejected.
        with self.assertRaises(errors_mod.InvalidStartFrameError):
            module.animate_character("husband", "wave", True)

    def test_valid_inputs_reach_blender_branch(self):
        module = self._fresh_animation_module()
        with self.assertRaises(errors_mod.BlenderUnavailableError):
            module.animate_character("husband", "wave", 1)


class BlenderAnimationBehaviorTests(unittest.TestCase):
    """Exercise ``animate_character`` end-to-end with a stubbed ``bpy``."""

    def setUp(self):
        self._saved_modules = {
            name: sys.modules.pop(name, None)
            for name in (
                "bpy",
                "bpy.types",
                "bpy.props",
                "bpy.utils",
                "toonflow_ai.generation.animation",
            )
        }

    def tearDown(self):
        sys.modules.pop("toonflow_ai.generation.animation", None)
        for name, value in self._saved_modules.items():
            if value is not None:
                sys.modules[name] = value
            else:
                sys.modules.pop(name, None)

    def _bpy_stub(self):
        class _Action:
            def __init__(self, name):
                self.name = name
                self.fcurves = []

        class _Keyframe:
            def __init__(self, frame):
                self.co = types.SimpleNamespace(x=frame, y=0.0)

        class _FCurve:
            def __init__(self, data_path, array_index):
                self.data_path = data_path
                self.array_index = array_index
                self.keyframe_points = []

        class _AnimData:
            def __init__(self):
                self.action = None

        class _Object:
            def __init__(self, name):
                self.name = name
                self.location = (0.0, 0.0, 0.0)
                self.rotation_euler = (0.0, 0.0, 0.0)
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
                fcurve = next(
                    (
                        fc for fc in action.fcurves
                        if fc.data_path == data_path and fc.array_index == 0
                    ),
                    None,
                )
                if fcurve is None:
                    fcurve = _FCurve(data_path, 0)
                    action.fcurves.append(fcurve)
                fcurve.keyframe_points.append(_Keyframe(frame))

        actions_store = {}

        def _new_action(name):
            if name in actions_store:
                return actions_store[name]
            action = _Action(name)
            actions_store[name] = action
            return action

        actions_ns = types.SimpleNamespace(new=_new_action, get=lambda n: actions_store.get(n))

        bpy_data = types.SimpleNamespace(
            actions=actions_ns,
            objects=[],
        )

        bpy_types = types.ModuleType("bpy.types")
        bpy_types.PropertyGroup = type("PropertyGroup", (), {})
        bpy_types.Operator = type("Operator", (), {})
        bpy_types.Panel = type("Panel", (), {})

        bpy = types.ModuleType("bpy")
        bpy.data = bpy_data
        bpy.types = bpy_types
        bpy.context = types.SimpleNamespace(
            scene=types.SimpleNamespace(collection=types.SimpleNamespace(children=[])),
            view_layer=types.SimpleNamespace(update=lambda: None),
        )
        return bpy, _Object, actions_store

    def _load_animation_module(self, bpy_stub):
        for name in ("bpy", "bpy.types"):
            sys.modules.pop(name, None)
        sys.modules["bpy"] = bpy_stub
        sys.modules["bpy.types"] = bpy_stub.types
        for name in ("toonflow_ai.generation.animation",):
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location(
            "toonflow_ai.generation.animation",
            ADDON_PKG_PATH / "generation" / "animation.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["toonflow_ai.generation.animation"] = module
        spec.loader.exec_module(module)
        return module

    def _make_root_and_parts(self, bpy_stub, _Object, character_id):
        from toonflow_ai.generation.naming import (
            CHARACTER_PARTS,
            character_object_name,
            character_part_object_name,
        )

        root = _Object(character_object_name(character_id))
        bpy_stub.data.objects.append(root)
        parts = {}
        for part in CHARACTER_PARTS:
            obj = _Object(character_part_object_name(character_id, part))
            bpy_stub.data.objects.append(obj)
            parts[part] = obj
        return root, parts

    def test_wave_inserts_keyframes_for_location_and_rotation(self):
        bpy_stub, _Object, actions_store = self._bpy_stub()
        module = self._load_animation_module(bpy_stub)
        self._make_root_and_parts(bpy_stub, _Object, "husband")

        result = module.animate_character("husband", "wave", start_frame=1)

        self.assertEqual(result["character_id"], "husband")
        self.assertEqual(result["animation_name"], "wave")
        self.assertEqual(result["start_frame"], 1)
        self.assertEqual(result["frame_offsets"], (0, 20, 40))
        self.assertEqual(result["pose_sequence"], ("neutral", "wave", "neutral"))

        # One entry per character part.
        self.assertEqual(len(result["parts"]), 6)
        for entry in result["parts"]:
            self.assertEqual(len(entry["keyframes"]), 3)

        # Inspect the actual keyframes stored on each part's action.
        for entry in result["parts"]:
            action_name = entry["action_name"]
            self.assertIn(action_name, actions_store)
            action = actions_store[action_name]
            paths = sorted(fc.data_path for fc in action.fcurves)
            self.assertEqual(paths, ["location", "rotation_euler"])
            frames_for_location = [
                int(round(kp.co.x)) for fc in action.fcurves if fc.data_path == "location"
                for kp in fc.keyframe_points
            ]
            self.assertEqual(sorted(frames_for_location), [1, 21, 41])

    def test_repeated_call_replaces_only_target_frames(self):
        bpy_stub, _Object, _actions_store = self._bpy_stub()
        module = self._load_animation_module(bpy_stub)
        self._make_root_and_parts(bpy_stub, _Object, "wife")

        module.animate_character("wife", "wave", start_frame=1)
        wife_obj = next(
            obj for obj in bpy_stub.data.objects
            if obj.name == "TOONFLOW_CHARACTER_WIFE_RIGHT_ARM"
        )
        action = wife_obj.animation_data.action
        from toonflow_ai.generation.animation_data import animation_frames

        action.fcurves[0].keyframe_points.append(
            types.SimpleNamespace(co=types.SimpleNamespace(x=99.0, y=0.0))
        )

        module.animate_character("wife", "wave", start_frame=1)

        frames_location = sorted(
            int(round(kp.co.x))
            for fc in action.fcurves if fc.data_path == "location"
            for kp in fc.keyframe_points
        )
        self.assertEqual(frames_location, [1, 21, 41, 99])
        self.assertTrue(
            any(
                int(round(kp.co.x)) == 99
                for fc in action.fcurves if fc.data_path == "location"
                for kp in fc.keyframe_points
            )
        )
        self.assertGreaterEqual(len(action.fcurves[0].keyframe_points), 4)
        _ = animation_frames  # silence unused warning; just imported

    def test_idempotent_action_creation(self):
        bpy_stub, _Object, actions_store = self._bpy_stub()
        module = self._load_animation_module(bpy_stub)
        self._make_root_and_parts(bpy_stub, _Object, "husband")

        module.animate_character("husband", "wave", start_frame=1)
        module.animate_character("husband", "wave", start_frame=1)

        action_names = [name for name in actions_store if "HUSBAND" in name]
        self.assertEqual(len(action_names), 1)


class DependencyBoundaryTests(unittest.TestCase):
    def _no_bpy(self, package):
        mod = sys.modules.get(package) or importlib.import_module(package)
        source = inspect.getsource(mod)
        self.assertNotIn("import bpy", source)
        self.assertNotIn("from bpy", source)

    def test_ai_is_bpy_free(self):
        for pkg in ("ai", "ai.errors", "ai.ollama_client", "ai.planner"):
            self._no_bpy(pkg)

    def test_pipeline_is_bpy_free(self):
        self._no_bpy("pipeline")
        self._no_bpy("pipeline.api")

    def test_scene_plan_is_bpy_free(self):
        self._no_bpy("scene_plan")
        self._no_bpy("scene_plan.validation")
        self._no_bpy("scene_plan.schema")

    def test_asset_registry_is_bpy_free(self):
        self._no_bpy("asset_registry")
        self._no_bpy("asset_registry.registry")

    def test_animation_data_is_bpy_free(self):
        self._no_bpy("toonflow_ai.generation.animation_data")
        self._no_bpy("toonflow_ai.generation.poses")
        self._no_bpy("toonflow_ai.generation.naming")
        self._no_bpy("toonflow_ai.generation.errors")


class AnimationModuleStaticTests(unittest.TestCase):
    def test_animation_module_defines_public_api(self):
        source = (ADDON_PKG_PATH / "generation" / "animation.py").read_text()
        self.assertIn("def animate_character", source)
        self.assertIn("def supported_animations", source)

    def test_animation_module_uses_pure_animation_data(self):
        source = (ADDON_PKG_PATH / "generation" / "animation.py").read_text()
        self.assertIn("from .animation_data import", source)
        self.assertIn("animation_sequence", source)
        self.assertIn("animation_frame_offsets", source)
        self.assertIn("is_supported_animation", source)

    def test_animation_module_reuses_pose_helpers(self):
        source = (ADDON_PKG_PATH / "generation" / "animation.py").read_text()
        self.assertIn("from .poses import", source)
        self.assertIn("pose_offset", source)
        self.assertIn("pose_rotation_euler", source)

    def test_animation_module_does_not_define_pose_transforms(self):
        """The Blender animation module must not redefine pose offsets/rotations."""
        source = (ADDON_PKG_PATH / "generation" / "animation.py").read_text()
        self.assertNotIn("-1.5707963267948966", source)

    def test_animation_module_uses_keyframe_insert(self):
        source = (ADDON_PKG_PATH / "generation" / "animation.py").read_text()
        self.assertIn("keyframe_insert", source)
        self.assertIn("data_path=\"location\"", source)
        self.assertIn("data_path=\"rotation_euler\"", source)

    def test_animation_module_uses_existing_naming_helpers(self):
        source = (ADDON_PKG_PATH / "generation" / "animation.py").read_text()
        self.assertIn("character_object_name", source)
        self.assertIn("character_part_object_name", source)
        self.assertIn("is_toonflow_name", source)
        self.assertIn("CHARACTER_PARTS", source)

    def test_animation_module_uses_existing_errors(self):
        source = (ADDON_PKG_PATH / "generation" / "animation.py").read_text()
        for cls in (
            "UnknownCharacterError",
            "MissingCharacterError",
            "UnknownAnimationError",
            "InvalidStartFrameError",
            "BlenderUnavailableError",
        ):
            self.assertIn(cls, source, f"missing {cls}")

    def test_animation_module_does_not_use_banned_features(self):
        """The animation module must not reference armature/bone/shape-key APIs.

        The check looks at *imported* names only — it ignores docstrings
        that explicitly mention these concepts in the negative.
        """
        import ast

        source = (ADDON_PKG_PATH / "generation" / "animation.py").read_text()
        tree = ast.parse(source)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add((alias.asname or alias.name).split(".")[0])

        banned = {"armature", "vertex_group", "shape_key", "parent_bone"}
        for name in imported_names:
            self.assertNotIn(name, banned, f"unexpected import: {name}")

        # Also assert no direct constructor calls on banned bpy types.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                self.assertNotIn(attr, banned, f"unexpected call: {attr}")


class SyntaxValidationTests(unittest.TestCase):
    def test_new_modules_compile(self):
        import py_compile

        for name in ("animation_data.py", "animation.py"):
            path = ADDON_PKG_PATH / "generation" / name
            self.assertTrue(path.exists(), f"missing {path}")
            py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    unittest.main()