"""Tests for TOONFLOW-PHASE-009 Character Representation & Pose Foundation.

Pure-Python tests covering:

- deterministic naming for the new character parts,
- the static pose data module (offsets/rotations),
- the pose API input validation (without Blender),
- the pose Blender module's input-validation path (with a stubbed bpy),
- the static structure of the Blender character generator,
- the static structure of the Blender pose module,
- that no ``bpy`` dependency leaks into the pure-Python packages.

Live visual hierarchy and pose behavior inside Blender could not be
exercised without Blender installed; that limitation is reported.
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
naming_mod = importlib.import_module("toonflow_ai.generation.naming")
poses_mod = importlib.import_module("toonflow_ai.generation.poses")
errors_mod = importlib.import_module("toonflow_ai.generation.errors")


class CharacterPartsExposedTests(unittest.TestCase):
    def test_character_parts_constant_is_complete(self):
        from toonflow_ai.generation import CHARACTER_PARTS

        self.assertEqual(
            CHARACTER_PARTS,
            ("BODY", "HEAD", "LEFT_ARM", "RIGHT_ARM", "LEFT_LEG", "RIGHT_LEG"),
        )

    def test_part_naming_is_deterministic(self):
        from toonflow_ai.generation import character_part_object_name

        cases = {
            ("husband", "BODY"): "TOONFLOW_CHARACTER_HUSBAND_BODY",
            ("husband", "HEAD"): "TOONFLOW_CHARACTER_HUSBAND_HEAD",
            ("husband", "LEFT_ARM"): "TOONFLOW_CHARACTER_HUSBAND_LEFT_ARM",
            ("husband", "RIGHT_ARM"): "TOONFLOW_CHARACTER_HUSBAND_RIGHT_ARM",
            ("husband", "LEFT_LEG"): "TOONFLOW_CHARACTER_HUSBAND_LEFT_LEG",
            ("husband", "RIGHT_LEG"): "TOONFLOW_CHARACTER_HUSBAND_RIGHT_LEG",
            ("wife", "HEAD"): "TOONFLOW_CHARACTER_WIFE_HEAD",
        }
        for (cid, part), expected in cases.items():
            self.assertEqual(
                character_part_object_name(cid, part), expected, (cid, part)
            )

    def test_part_names_returns_full_set(self):
        from toonflow_ai.generation import character_part_names

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

    def test_unknown_part_raises_value_error(self):
        from toonflow_ai.generation import character_part_object_name

        with self.assertRaises(ValueError):
            character_part_object_name("husband", "WINGS")

    def test_part_names_use_same_prefix_as_root(self):
        from toonflow_ai.generation import character_part_object_name

        for part in ("BODY", "HEAD", "LEFT_ARM", "RIGHT_ARM", "LEFT_LEG", "RIGHT_LEG"):
            name = character_part_object_name("wife", part)
            self.assertTrue(name.startswith("TOONFLOW_CHARACTER_WIFE"))
            self.assertTrue(naming_mod.is_toonflow_name(name))


class CharacterRootBackwardCompatibilityTests(unittest.TestCase):
    def test_root_name_is_unchanged(self):
        from toonflow_ai.generation import character_object_name

        self.assertEqual(character_object_name("husband"), "TOONFLOW_CHARACTER_HUSBAND")
        self.assertEqual(character_object_name("wife"), "TOONFLOW_CHARACTER_WIFE")

    def test_is_toonflow_name_accepts_part_names(self):
        self.assertTrue(naming_mod.is_toonflow_name("TOONFLOW_CHARACTER_HUSBAND_BODY"))
        self.assertTrue(naming_mod.is_toonflow_name("TOONFLOW_CHARACTER_HUSBAND_LEFT_ARM"))
        self.assertFalse(naming_mod.is_toonflow_name("Cube"))


class PoseDataTests(unittest.TestCase):
    def test_supported_poses_constant(self):
        from toonflow_ai.generation import SUPPORTED_POSES

        self.assertEqual(SUPPORTED_POSES, ("neutral", "wave"))
        self.assertTrue(all(isinstance(p, str) for p in SUPPORTED_POSES))

    def test_is_supported_pose(self):
        from toonflow_ai.generation import is_supported_pose

        self.assertTrue(is_supported_pose("neutral"))
        self.assertTrue(is_supported_pose("wave"))
        self.assertFalse(is_supported_pose("dance"))
        self.assertFalse(is_supported_pose(""))
        self.assertFalse(is_supported_pose(None))

    def test_neutral_pose_has_zero_offsets(self):
        from toonflow_ai.generation import pose_offset, pose_rotation_euler

        for part in ("BODY", "HEAD", "LEFT_ARM", "RIGHT_ARM", "LEFT_LEG", "RIGHT_LEG"):
            self.assertEqual(pose_offset("neutral", part), (0.0, 0.0, 0.0))
            self.assertEqual(pose_rotation_euler("neutral", part), (0.0, 0.0, 0.0))

    def test_wave_pose_rotates_right_arm(self):
        from toonflow_ai.generation import pose_rotation_euler

        rx, ry, rz = pose_rotation_euler("wave", "RIGHT_ARM")
        self.assertAlmostEqual(rz, -1.5707963267948966)
        self.assertEqual((rx, ry), (0.0, 0.0))

    def test_wave_pose_leaves_other_parts_unrotated(self):
        from toonflow_ai.generation import pose_rotation_euler

        for part in ("BODY", "HEAD", "LEFT_ARM", "LEFT_LEG", "RIGHT_LEG"):
            self.assertEqual(
                pose_rotation_euler("wave", part),
                (0.0, 0.0, 0.0),
                part,
            )

    def test_wave_pose_is_visually_distinct_from_neutral(self):
        from toonflow_ai.generation import pose_rotation_euler

        neutral = pose_rotation_euler("neutral", "RIGHT_ARM")
        wave = pose_rotation_euler("wave", "RIGHT_ARM")
        self.assertNotEqual(neutral, wave)

    def test_pose_describe_includes_all_parts(self):
        from toonflow_ai.generation import pose_describe

        description = pose_describe("neutral")
        self.assertEqual(description["name"], "neutral")
        self.assertEqual(
            tuple(p["part"] for p in description["parts"]),
            ("BODY", "HEAD", "LEFT_ARM", "RIGHT_ARM", "LEFT_LEG", "RIGHT_LEG"),
        )


class PoseApiReexportTests(unittest.TestCase):
    def test_pose_api_is_exported(self):
        self.assertTrue(hasattr(generation_pkg, "set_character_pose"))
        self.assertTrue(callable(generation_pkg.set_character_pose))
        self.assertTrue(hasattr(generation_pkg, "supported_poses"))

    def test_pose_errors_are_exported(self):
        for name in (
            "UnknownCharacterError",
            "MissingCharacterError",
            "UnknownPoseError",
        ):
            self.assertTrue(hasattr(generation_pkg, name), name)


class PoseModuleInputValidationTests(unittest.TestCase):
    """Exercise ``set_character_pose`` validation without touching Blender."""

    def _fresh_pose_module(self):
        if "toonflow_ai.generation.pose" in sys.modules:
            del sys.modules["toonflow_ai.generation.pose"]
        spec = importlib.util.spec_from_file_location(
            "toonflow_ai.generation.pose",
            ADDON_PKG_PATH / "generation" / "pose.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["toonflow_ai.generation.pose"] = module
        spec.loader.exec_module(module)
        return module

    def test_unknown_character_id_raises_before_blender(self):
        module = self._fresh_pose_module()
        with self.assertRaises(errors_mod.UnknownCharacterError) as ctx:
            module.set_character_pose("stranger", "neutral")
        self.assertEqual(ctx.exception.character_id, "stranger")

    def test_empty_character_id_is_rejected(self):
        module = self._fresh_pose_module()
        with self.assertRaises(errors_mod.UnknownCharacterError):
            module.set_character_pose("", "neutral")

    def test_non_string_character_id_is_rejected(self):
        module = self._fresh_pose_module()
        with self.assertRaises(errors_mod.UnknownCharacterError):
            module.set_character_pose(None, "neutral")

    def test_unknown_pose_is_rejected(self):
        module = self._fresh_pose_module()
        with self.assertRaises(errors_mod.UnknownPoseError) as ctx:
            module.set_character_pose("husband", "dance")
        self.assertEqual(ctx.exception.pose_name, "dance")
        self.assertIn("neutral", ctx.exception.supported)
        self.assertIn("wave", ctx.exception.supported)

    def test_non_string_pose_is_rejected(self):
        module = self._fresh_pose_module()
        with self.assertRaises(errors_mod.UnknownPoseError):
            module.set_character_pose("husband", None)

    def test_known_inputs_reach_blender_branch(self):
        module = self._fresh_pose_module()
        with self.assertRaises(errors_mod.BlenderUnavailableError):
            module.set_character_pose("husband", "neutral")


class BlenderGenerationStaticTests(unittest.TestCase):
    def test_generator_uses_new_naming_helpers(self):
        source = (ADDON_PKG_PATH / "generation" / "blender_generator.py").read_text()
        self.assertIn("CHARACTER_PARTS", source)
        self.assertIn("character_part_object_name", source)
        self.assertIn("_create_character_root", source)
        self.assertIn("_create_character_part", source)

    def test_generator_parents_parts_to_root(self):
        source = (ADDON_PKG_PATH / "generation" / "blender_generator.py").read_text()
        self.assertIn("parent.children.link(obj)", source)

    def test_generator_uses_existing_ownership_cleanup(self):
        source = (ADDON_PKG_PATH / "generation" / "blender_generator.py").read_text()
        self.assertIn("_remove_existing_toonflow_objects", source)
        self.assertIn('startswith("TOONFLOW_")', source)


class PoseModuleStaticTests(unittest.TestCase):
    def test_pose_module_defines_set_character_pose(self):
        source = (ADDON_PKG_PATH / "generation" / "pose.py").read_text()
        self.assertIn("def set_character_pose", source)
        self.assertIn("def supported_poses", source)

    def test_pose_module_uses_pure_pose_data(self):
        source = (ADDON_PKG_PATH / "generation" / "pose.py").read_text()
        self.assertIn("from .poses import", source)
        self.assertIn("is_supported_pose", source)
        self.assertIn("pose_offset", source)
        self.assertIn("pose_rotation_euler", source)

    def test_pose_module_uses_pose_errors(self):
        source = (ADDON_PKG_PATH / "generation" / "pose.py").read_text()
        for cls in (
            "UnknownCharacterError",
            "MissingCharacterError",
            "UnknownPoseError",
            "BlenderUnavailableError",
        ):
            self.assertIn(cls, source, f"missing {cls}")

    def test_pose_module_does_not_define_animation_data(self):
        source = (ADDON_PKG_PATH / "generation" / "pose.py").read_text()
        for forbidden in (
            "keyframe_insert",
            "action_fcurve",
            "bpy.types.Action",
            "animation_data",
            "F-Curve",
            "FCurve",
        ):
            self.assertNotIn(forbidden, source)


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

    def test_pose_data_module_is_bpy_free(self):
        self._no_bpy("toonflow_ai.generation.poses")
        self._no_bpy("toonflow_ai.generation.naming")
        self._no_bpy("toonflow_ai.generation.errors")


class SyntaxValidationTests(unittest.TestCase):
    def test_new_modules_compile(self):
        import py_compile

        for name in ("poses.py", "pose.py"):
            path = ADDON_PKG_PATH / "generation" / name
            self.assertTrue(path.exists(), f"missing {path}")
            py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    unittest.main()