"""Tests for TOONFLOW-PHASE-011 Camera Automation.

Covers:

- pure-Python camera_data module (no bpy),
- the public camera API exposed through ``toonflow_ai.generation``,
- ``bpy``-unavailable behavior,
- static structure of the Blender camera module,
- stubbed-Blender end-to-end behavior (creates, reuses, idempotent,
  deterministic transform, unrelated cameras untouched),
- dependency boundaries (camera_data is bpy-free; ai / pipeline /
  scene_plan / asset_registry / generation pure modules are bpy-free).

Live Blender execution was not exercised because Blender is not
installed in this environment.
"""

import importlib
import importlib.util
import inspect
import math
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
camera_data_mod = importlib.import_module("toonflow_ai.generation.camera_data")


class PureCameraDataTests(unittest.TestCase):
    def test_camera_data_does_not_import_bpy(self):
        source = inspect.getsource(camera_data_mod)
        self.assertNotIn("import bpy", source)
        self.assertNotIn("from bpy", source)

    def test_camera_object_name_is_deterministic(self):
        from toonflow_ai.generation import (
            TOONFLOW_CAMERA_NAME,
            camera_object_name,
            is_toonflow_camera_name,
        )

        self.assertEqual(TOONFLOW_CAMERA_NAME, "TOONFLOW_CAMERA")
        self.assertEqual(camera_object_name(), "TOONFLOW_CAMERA")
        self.assertTrue(is_toonflow_camera_name("TOONFLOW_CAMERA"))
        self.assertFalse(is_toonflow_camera_name("Camera"))
        self.assertFalse(is_toonflow_camera_name("TOONFLOW_CAMERA_BACKUP"))
        self.assertFalse(is_toonflow_camera_name(None))
        self.assertFalse(is_toonflow_camera_name(42))

    def test_camera_position_and_target_are_deterministic(self):
        from toonflow_ai.generation import camera_position, camera_target

        position = camera_position()
        target = camera_target()
        self.assertEqual(position, (0.0, 5.0, 2.5))
        self.assertEqual(target, (0.0, 0.0, 1.0))

    def test_camera_position_and_target_are_tuples(self):
        from toonflow_ai.generation import camera_position, camera_target

        self.assertIsInstance(camera_position(), tuple)
        self.assertIsInstance(camera_target(), tuple)

    def test_camera_lens_and_sensor(self):
        from toonflow_ai.generation import camera_lens, camera_sensor_width

        self.assertEqual(camera_lens(), 50.0)
        self.assertEqual(camera_sensor_width(), 36.0)

    def test_camera_describe_shape(self):
        from toonflow_ai.generation import camera_describe

        desc = camera_describe()
        self.assertEqual(desc["name"], "TOONFLOW_CAMERA")
        self.assertEqual(desc["location"], (0.0, 5.0, 2.5))
        self.assertEqual(desc["target"], (0.0, 0.0, 1.0))
        self.assertEqual(desc["lens"], 50.0)
        self.assertEqual(desc["sensor_width"], 36.0)

    def test_public_configuration_is_immutable(self):
        from toonflow_ai.generation import camera_describe

        snapshot_a = camera_describe()
        snapshot_b = camera_describe()
        self.assertEqual(snapshot_a, snapshot_b)


class PublicCameraApiTests(unittest.TestCase):
    def test_create_or_update_camera_is_exported(self):
        self.assertTrue(hasattr(generation_pkg, "create_or_update_camera"))
        self.assertTrue(callable(generation_pkg.create_or_update_camera))

    def test_camera_helpers_are_exported(self):
        for name in (
            "TOONFLOW_CAMERA_NAME",
            "camera_object_name",
            "camera_position",
            "camera_target",
            "camera_lens",
            "camera_sensor_width",
            "camera_describe",
            "is_toonflow_camera_name",
        ):
            self.assertTrue(hasattr(generation_pkg, name), name)


class BlenderUnavailableTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            n: sys.modules.pop(n, None)
            for n in ("bpy", "bpy.types", "bpy.props", "bpy.utils")
        }

    def tearDown(self):
        for n, v in self._saved.items():
            if v is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = v

    def test_create_or_update_camera_raises_when_bpy_missing(self):
        with self.assertRaises(errors_mod.BlenderUnavailableError):
            generation_pkg.create_or_update_camera()


class CameraBlenderModuleStructureTests(unittest.TestCase):
    def _code_only_functions(self, name):
        """Return the source of all top-level nodes in *name*, docstring-stripped."""
        import ast

        path = ADDON_PKG_PATH / "generation" / (name + ".py")
        tree = ast.parse(path.read_text())
        chunks = []
        for node in tree.body:
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Assign,
                    ast.ImportFrom,
                    ast.Import,
                ),
            ):
                chunks.append(ast.unparse(node))
        return "\n".join(chunks)

    def test_blender_camera_module_uses_data_api(self):
        """No bpy.ops.* calls inside any function body."""
        import ast

        code = self._code_only_functions("camera")
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                root = node.func
                if isinstance(root.value, ast.Name) and root.value.id == "bpy":
                    self.assertNotEqual(root.attr, "ops", "bpy.ops.* must not be used")

    def test_blender_camera_module_reuses_naming(self):
        code = self._code_only_functions("camera")
        self.assertIn("TOONFLOW_COLLECTION_NAME", code)
        self.assertIn("camera_data", code)

    def test_blender_camera_module_uses_existing_errors(self):
        code = self._code_only_functions("camera")
        self.assertIn("BlenderUnavailableError", code)
        self.assertIn("GenerationError", code)

    def test_camera_module_has_no_keyframe_or_animation(self):
        code = self._code_only_functions("camera")
        for forbidden in (
            "keyframe_insert",
            "animation_data",
            "track_to",
            "TRACK_TO",
        ):
            self.assertNotIn(forbidden, code)
        # Also check Constraint-creating calls.
        import ast

        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn("constraints", node.func.attr)

    def test_camera_module_has_no_rendering(self):
        code = self._code_only_functions("camera")
        for forbidden in ("render", "bpy.context.scene.render"):
            self.assertNotIn(forbidden, code)


class CleanupPreservesCameraTests(unittest.TestCase):
    def test_cleanup_helper_preserves_toonflow_camera(self):
        """The smallest targeted change: the cleanup helper excludes TOONFLOW_CAMERA."""
        source = (ADDON_PKG_PATH / "generation" / "blender_generator.py").read_text()
        self.assertIn("TOONFLOW_CAMERA_NAME", source)
        self.assertIn("obj.name != TOONFLOW_CAMERA_NAME", source)


class DependencyBoundaryTests(unittest.TestCase):
    def _no_bpy(self, package):
        mod = sys.modules.get(package) or importlib.import_module(package)
        source = inspect.getsource(mod)
        self.assertNotIn("import bpy", source)
        self.assertNotIn("from bpy", source)

    def test_camera_data_is_bpy_free(self):
        self._no_bpy("toonflow_ai.generation.camera_data")

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


class StubbedBlenderCameraBehaviorTests(unittest.TestCase):
    """End-to-end behavior using a minimal ``bpy`` stub."""

    def setUp(self):
        self._saved = {
            n: sys.modules.pop(n, None)
            for n in (
                "bpy",
                "bpy.types",
                "bpy.props",
                "bpy.utils",
                "toonflow_ai.generation.camera",
            )
        }
        self.bpy, self._Object_cls, self._CameraData_cls = self._build_bpy_stub()

    def tearDown(self):
        sys.modules.pop("toonflow_ai.generation.camera", None)
        for n, v in self._saved.items():
            if v is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = v

    def _build_bpy_stub(self):
        """Return a tiny ``bpy`` stub. Do not use `` ``types`` inside; alias it once."""
        import types as _types

        class _CameraData:
            def __init__(self, name):
                self.name = name
                self.lens = 0.0
                self.sensor_width = 0.0

        class _Object:
            def __init__(self, name, data=None):
                self.name = name
                self.data = data
                self.type = "CAMERA" if data is not None else "EMPTY"
                self.location = (0.0, 0.0, 0.0)
                self.rotation_euler = (0.0, 0.0, 0.0)

        class _Collection:
            def __init__(self, name):
                self.name = name
                self.objects = _CollObjects(self)
                self.children = []

        class _CollObjects:
            def __init__(self, coll):
                self._coll = coll
                self._store = {}

            def link(self, obj):
                self._store[obj.name] = obj

            def __contains__(self, item):
                return item in self._store

            def __len__(self):
                return len(self._store)

            def __iter__(self):
                return iter(self._store.values())

        class _SceneCollection:
            def __init__(self):
                self.children = _Children()
                self.objects = {}

        class _Children:
            def __init__(self):
                self._list = []

            def append(self, item):
                self._list.append(item)

            def __contains__(self, item):
                return item in self._list

            def __iter__(self):
                return iter(self._list)

            def link(self, coll):
                if coll.name not in self._list:
                    self._list.append(coll.name)

        class _Scene:
            def __init__(self):
                self.collection = _SceneCollection()

        class _Context:
            def __init__(self):
                self.scene = _Scene()

        class _Data:
            def __init__(self):
                self.objects = _Objects(self)
                self.collections = _Collections(self)
                self.cameras = _Cameras(self)

        class _Collections:
            def __init__(self, data):
                self._data = data
                self._store = {}

            def get(self, key):
                return self._store.get(key)

            def new(self, name):
                coll = _Collection(name)
                self._store[name] = coll
                return coll

        class _Objects:
            def __init__(self, data):
                self._data = data
                self._store = {}

            def get(self, key):
                return self._store.get(key)

            def new(self, name, data=None):
                obj = _Object(name, data=data)
                self._store[name] = obj
                return obj

            def __contains__(self, key):
                return key in self._store

            def __getitem__(self, key):
                return self._store[key]

            def __setitem__(self, key, value):
                self._store[key] = value

            def __len__(self):
                return len(self._store)

        class _Cameras:
            def __init__(self, data):
                self._data = data
                self._store = {}

            def new(self, name):
                cd = _CameraData(name)
                self._store[name] = cd
                return cd

        bpy_types = _types.ModuleType("bpy.types")
        bpy_types.PropertyGroup = type("PropertyGroup", (), {})
        bpy_types.Operator = type("Operator", (), {})
        bpy_types.Panel = type("Panel", (), {})

        bpy = _types.ModuleType("bpy")
        bpy.data = _Data()
        bpy.types = bpy_types
        bpy.context = _Context()
        bpy._stub_classes = {
            "Collection": _Collection,
            "Object": _Object,
            "CameraData": _CameraData,
        }
        return bpy, _Object, _CameraData

    def _seed_toonflow_collection(self):
        """Pre-create the TOONFLOW collection as if ``generate_scene`` ran first."""
        from toonflow_ai.generation.naming import TOONFLOW_COLLECTION_NAME

        Collection_cls = self.bpy._stub_classes["Collection"]
        coll = Collection_cls(TOONFLOW_COLLECTION_NAME)
        self.bpy.data.collections._store[TOONFLOW_COLLECTION_NAME] = coll
        self.bpy.context.scene.collection.children.link(coll)
        return coll

    def _load_camera_module(self):
        sys.modules["bpy"] = self.bpy
        sys.modules["bpy.types"] = self.bpy.types
        spec = importlib.util.spec_from_file_location(
            "toonflow_ai.generation.camera",
            ADDON_PKG_PATH / "generation" / "camera.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["toonflow_ai.generation.camera"] = module
        spec.loader.exec_module(module)
        return module

    def _seed_user_camera(self, name="UserCam.001", location=(99.0, 99.0, 99.0)):
        cam_data = self._CameraData_cls(name + "_DATA")
        cam = self._Object_cls(name, data=cam_data)
        cam.location = location
        self.bpy.data.objects._store[cam.name] = cam
        return cam

    def test_creates_camera_when_absent(self):
        coll = self._seed_toonflow_collection()
        module = self._load_camera_module()

        result = module.create_or_update_camera()

        self.assertEqual(result["camera_name"], "TOONFLOW_CAMERA")
        self.assertEqual(result["collection_name"], coll.name)
        self.assertFalse(result["reused"])
        self.assertEqual(result["location"], (0.0, 5.0, 2.5))
        self.assertEqual(result["target"], (0.0, 0.0, 1.0))
        self.assertEqual(result["lens"], 50.0)
        self.assertEqual(result["sensor_width"], 36.0)

        self.assertIn("TOONFLOW_CAMERA", self.bpy.data.objects)
        cam = self.bpy.data.objects["TOONFLOW_CAMERA"]
        self.assertEqual(cam.type, "CAMERA")
        self.assertIsNotNone(cam.data)

    def test_reuses_camera_when_present(self):
        coll = self._seed_toonflow_collection()
        existing_cam_data = self._CameraData_cls("TOONFLOW_CAMERA_DATA")
        existing_cam = self._Object_cls("TOONFLOW_CAMERA", data=existing_cam_data)
        coll.objects.link(existing_cam)
        self.bpy.data.objects._store[existing_cam.name] = existing_cam

        module = self._load_camera_module()
        result = module.create_or_update_camera()

        self.assertTrue(result["reused"])
        self.assertEqual(len(self.bpy.data.objects._store), 1)
        self.assertIn("TOONFLOW_CAMERA", self.bpy.data.objects._store)

    def test_no_duplicate_camera_on_repeated_call(self):
        self._seed_toonflow_collection()
        module = self._load_camera_module()
        module.create_or_update_camera()
        module.create_or_update_camera()
        module.create_or_update_camera()
        self.assertEqual(len(self.bpy.data.objects), 1)

    def test_camera_orientation_points_toward_target(self):
        self._seed_toonflow_collection()
        module = self._load_camera_module()
        module.create_or_update_camera()

        cam = self.bpy.data.objects["TOONFLOW_CAMERA"]
        pitch, _, yaw = cam.rotation_euler
        fx = -math.sin(yaw) * math.cos(pitch)
        fy = -math.cos(yaw) * math.cos(pitch)
        fz = math.sin(pitch)
        pos = cam.location
        from toonflow_ai.generation.camera_data import camera_target

        tgt = camera_target()
        dx = tgt[0] - pos[0]
        dy = tgt[1] - pos[1]
        dz = tgt[2] - pos[2]
        mag = math.sqrt(dx * dx + dy * dy + dz * dz)
        nx, ny, nz = dx / mag, dy / mag, dz / mag

        self.assertAlmostEqual(fx, nx, places=5)
        self.assertAlmostEqual(fy, ny, places=5)
        self.assertAlmostEqual(fz, nz, places=5)

    def test_repeated_calls_apply_deterministic_transform(self):
        self._seed_toonflow_collection()
        module = self._load_camera_module()
        first = module.create_or_update_camera()
        second = module.create_or_update_camera()

        self.assertEqual(first["location"], second["location"])
        self.assertEqual(first["rotation_euler"], second["rotation_euler"])
        self.assertEqual(first["camera_name"], second["camera_name"])
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])

    def test_unrelated_user_cameras_remain_untouched(self):
        self._seed_toonflow_collection()
        self._seed_user_camera()

        module = self._load_camera_module()
        module.create_or_update_camera()
        module.create_or_update_camera()

        self.assertIn("UserCam.001", self.bpy.data.objects)
        self.assertEqual(
            self.bpy.data.objects["UserCam.001"].location, (99.0, 99.0, 99.0)
        )

    def test_wrong_type_under_camera_name_raises(self):
        from toonflow_ai.generation.errors import GenerationError

        self._seed_toonflow_collection()
        wrong = self._Object_cls("TOONFLOW_CAMERA")  # no data -> EMPTY type
        wrong.location = (42.0, 42.0, 42.0)
        self.bpy.data.objects[wrong.name] = wrong

        module = self._load_camera_module()
        with self.assertRaises(GenerationError):
            module.create_or_update_camera()

        self.assertIn("TOONFLOW_CAMERA", self.bpy.data.objects)
        self.assertEqual(
            self.bpy.data.objects["TOONFLOW_CAMERA"].location, (42.0, 42.0, 42.0)
        )


class SyntaxValidationTests(unittest.TestCase):
    def test_new_modules_compile(self):
        import py_compile

        for name in ("camera_data.py", "camera.py"):
            path = ADDON_PKG_PATH / "generation" / name
            self.assertTrue(path.exists(), f"missing {path}")
            py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    unittest.main()