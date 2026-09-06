"""Tests for TOONFLOW AI Rendering Pipeline (PHASE-014)."""
import ast
import importlib.util
import os
import sys
import tempfile
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


_RENDER_BPY_SAVED = {}


def _install_bpy_stub():
    for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils", "bpy.ops", "bpy.ops.render"):
        if name in sys.modules and name not in _RENDER_BPY_SAVED:
            _RENDER_BPY_SAVED[name] = sys.modules.pop(name)
    bpy_stub = types.ModuleType("bpy")
    bpy_stub.types = types.ModuleType("bpy.types")
    bpy_stub.props = types.ModuleType("bpy.props")
    bpy_stub.utils = types.ModuleType("bpy.utils")
    bpy_stub.ops = types.ModuleType("bpy.ops")
    bpy_stub.ops.render = types.ModuleType("bpy.ops.render")
    sys.modules["bpy"] = bpy_stub
    sys.modules["bpy.types"] = bpy_stub.types
    sys.modules["bpy.props"] = bpy_stub.props
    sys.modules["bpy.utils"] = bpy_stub.utils
    sys.modules["bpy.ops"] = bpy_stub.ops
    sys.modules["bpy.ops.render"] = bpy_stub.ops.render


def _uninstall_bpy_stub():
    for name in (
        "bpy",
        "bpy.types",
        "bpy.props",
        "bpy.utils",
        "bpy.ops",
        "bpy.ops.render",
    ):
        sys.modules.pop(name, None)
    for name, mod in _RENDER_BPY_SAVED.items():
        sys.modules[name] = mod
    _RENDER_BPY_SAVED.clear()


def _load_rendering_module(bpy_stub):
    for name in (
        "bpy",
        "bpy.types",
        "bpy.ops",
        "bpy.ops.render",
    ):
        sys.modules.pop(name, None)
    sys.modules["bpy"] = bpy_stub
    sys.modules["bpy.types"] = bpy_stub.types
    if hasattr(bpy_stub, "ops"):
        sys.modules["bpy.ops"] = bpy_stub.ops
        sys.modules["bpy.ops.render"] = bpy_stub.ops.render
    for name in (
        "toonflow_ai.generation.rendering",
        "toonflow_ai.generation.render_data",
    ):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        "toonflow_ai.generation.rendering",
        ADDON_PKG_PATH / "generation" / "rendering.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["toonflow_ai.generation.rendering"] = module
    spec.loader.exec_module(module)
    return module


class _RenderBpyStubMixin:
    def setUp(self):
        _install_bpy_stub()

    def tearDown(self):
        _uninstall_bpy_stub()


_install_bpy_stub()
from toonflow_ai.generation import (  # noqa: E402
    RENDER_ENGINE,
    RENDER_FILE_FORMAT,
    RENDER_OUTPUT_FILENAME,
    RENDER_RESOLUTION_PERCENTAGE,
    RENDER_RESOLUTION_X,
    RENDER_RESOLUTION_Y,
    SUPPORTED_FILE_FORMATS,
    SUPPORTED_RENDER_ENGINES,
    BlenderUnavailableError,
    GenerationError,
    InvalidCameraTypeError,
    InvalidOutputPathError,
    MissingCameraError,
    RenderError,
    TOONFLOW_CAMERA_NAME,
    default_output_path,
    is_supported_file_format,
    is_supported_render_engine,
    render_describe,
    render_scene,
    render_settings_describe,
    validate_output_path,
)

import toonflow_ai.generation.render_data as render_data_mod  # noqa: E402
import toonflow_ai.generation.rendering as rendering_mod  # noqa: E402

_uninstall_bpy_stub()


RENDER_DATA_SOURCE = (ADDON_PKG_PATH / "generation" / "render_data.py").read_text(
    encoding="utf-8"
)
RENDERING_SOURCE = (ADDON_PKG_PATH / "generation" / "rendering.py").read_text(
    encoding="utf-8"
)


# --- Stub bpy for behavior tests -------------------------------------------

class _ImageSettings:
    def __init__(self):
        self.file_format = "PNG"


class _Render:
    def __init__(self):
        self.resolution_x = 1920
        self.resolution_y = 1080
        self.resolution_percentage = 100
        self.engine = "BLENDER_EEVEE_NEXT"
        self.filepath = ""
        self.film_transparent = False
        self.image_settings = _ImageSettings()


class _Scene:
    def __init__(self, name="Scene"):
        self.name = name
        self.render = _Render()
        self.camera = None


class _Object:
    def __init__(self, name, obj_type="MESH"):
        self.name = name
        self.type = obj_type


class _Objects:
    def __init__(self):
        self._store = []

    def get(self, name):
        for o in self._store:
            if o.name == name:
                return o
        return None

    def append(self, obj):
        self._store.append(obj)

    def __iter__(self):
        return iter(self._store)

    def __len__(self):
        return len(self._store)


def _make_bpy_stub(initial_objects=None, scene_name="Scene", blend_filepath=""):
    objects = _Objects()
    if initial_objects:
        for o in initial_objects:
            objects.append(o)
    scene = _Scene(scene_name)
    render_calls = []

    def _render(write_still=False):
        render_calls.append({"write_still": bool(write_still)})
        # Simulate a successful render by writing a tiny file.
        try:
            target = scene.render.filepath
            if target:
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                Path(target).write_bytes(b"PNG")
        except Exception:
            pass
        return {"FINISHED"}

    bpy_data = types.SimpleNamespace(objects=objects, filepath=blend_filepath)
    bpy_types = types.ModuleType("bpy.types")
    bpy_types.PropertyGroup = type("PropertyGroup", (), {})
    bpy_ops = types.ModuleType("bpy.ops")
    bpy_ops_render = types.ModuleType("bpy.ops.render")
    bpy_ops_render.render = _render

    bpy = types.ModuleType("bpy")
    bpy.data = bpy_data
    bpy.types = bpy_types
    bpy.ops = bpy_ops
    bpy.ops.render = bpy_ops_render
    bpy.context = types.SimpleNamespace(scene=scene)
    bpy._render_calls = render_calls
    bpy._scene = scene
    return bpy


# --- A. Public API exposure ------------------------------------------------

class PublicApiTests(_RenderBpyStubMixin, unittest.TestCase):
    def test_render_scene_exported(self):
        self.assertTrue(callable(render_scene))

    def test_render_describe_exported(self):
        self.assertTrue(callable(render_describe))

    def test_render_data_constants_exported(self):
        self.assertEqual(RENDER_RESOLUTION_X, 512)
        self.assertEqual(RENDER_RESOLUTION_Y, 512)
        self.assertEqual(RENDER_RESOLUTION_PERCENTAGE, 100)
        self.assertEqual(RENDER_FILE_FORMAT, "PNG")
        self.assertEqual(RENDER_ENGINE, "BLENDER_EEVEE_NEXT")
        self.assertEqual(RENDER_OUTPUT_FILENAME, "toonflow_render.png")
        self.assertEqual(SUPPORTED_FILE_FORMATS, ("PNG",))
        self.assertIn("BLENDER_EEVEE_NEXT", SUPPORTED_RENDER_ENGINES)
        self.assertIn("CYCLES", SUPPORTED_RENDER_ENGINES)

    def test_errors_exported(self):
        for name in (
            "BlenderUnavailableError",
            "MissingCameraError",
            "InvalidCameraTypeError",
            "InvalidOutputPathError",
            "RenderError",
        ):
            self.assertTrue(hasattr(__import__("toonflow_ai.generation", fromlist=[name]), name), name)

    def test_render_describe_does_not_import_bpy(self):
        # Pure-Python describe must not need bpy.
        bpy_stub = _make_bpy_stub()
        _install_bpy_stub()
        try:
            d = render_describe()
        finally:
            _uninstall_bpy_stub()
        self.assertEqual(d["camera_name"], TOONFLOW_CAMERA_NAME)
        self.assertEqual(d["default_output_filename"], RENDER_OUTPUT_FILENAME)
        self.assertEqual(d["config"]["resolution_x"], 512)
        self.assertEqual(d["config"]["resolution_y"], 512)
        self.assertEqual(d["config"]["file_format"], "PNG")


# --- B. Pure render data module --------------------------------------------

class RenderDataTests(_RenderBpyStubMixin, unittest.TestCase):
    def test_render_data_is_bpy_free(self):
        tree = ast.parse(RENDER_DATA_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(
                        alias.name == "bpy" or alias.name.startswith("bpy."),
                        f"bpy import in render_data: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("bpy"):
                    self.fail(f"bpy 'from' import in render_data: {node.module}")

    def test_is_supported_file_format(self):
        self.assertTrue(is_supported_file_format("PNG"))
        for bad in (None, 1, "jpg", "JPEG", ""):
            self.assertFalse(is_supported_file_format(bad))

    def test_is_supported_render_engine(self):
        for good in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
            self.assertTrue(is_supported_render_engine(good))
        for bad in (None, 1, "OCTANE", ""):
            self.assertFalse(is_supported_render_engine(bad))

    def test_settings_describe(self):
        d = render_settings_describe()
        self.assertEqual(d["resolution_x"], 512)
        self.assertEqual(d["resolution_y"], 512)
        self.assertEqual(d["resolution_percentage"], 100)
        self.assertEqual(d["file_format"], "PNG")
        self.assertEqual(d["engine"], "BLENDER_EEVEE_NEXT")
        self.assertEqual(d["output_filename"], "toonflow_render.png")

    def test_default_output_path_uses_blend_parent(self):
        with tempfile.TemporaryDirectory() as d:
            blend = Path(d) / "scene.blend"
            blend.write_text("")
            p = default_output_path(str(blend))
            self.assertEqual(p.name, "toonflow_render.png")
            self.assertEqual(p.parent.resolve(), Path(d).resolve())

    def test_default_output_path_falls_back_to_cwd(self):
        old_cwd = os.getcwd()
        try:
            os.chdir(tempfile.mkdtemp())
            p = default_output_path(None)
            self.assertEqual(p.name, "toonflow_render.png")
            self.assertTrue(p.is_absolute())
        finally:
            os.chdir(old_cwd)

    def test_validate_output_path_accepts_str(self):
        with tempfile.TemporaryDirectory() as d:
            p = validate_output_path(str(Path(d) / "out.png"))
            self.assertEqual(p.name, "out.png")

    def test_validate_output_path_accepts_pathlike(self):
        with tempfile.TemporaryDirectory() as d:
            p = validate_output_path(Path(d) / "out.png")
            self.assertEqual(p.name, "out.png")

    def test_validate_output_path_none_returns_none(self):
        self.assertIsNone(validate_output_path(None))

    def test_validate_output_path_rejects_empty(self):
        with self.assertRaises(InvalidOutputPathError):
            validate_output_path("")
        with self.assertRaises(InvalidOutputPathError):
            validate_output_path("   ")
        with self.assertRaises(InvalidOutputPathError):
            validate_output_path("/")

    def test_validate_output_path_rejects_non_str(self):
        for bad in (1, 1.5, [], {}, object()):
            with self.assertRaises(InvalidOutputPathError):
                validate_output_path(bad)


# --- C. Blender-dependent rendering module behavior ------------------------

class RenderingBehaviorTests(_RenderBpyStubMixin, unittest.TestCase):
    def test_missing_camera_raises(self):
        bpy_stub = _make_bpy_stub(initial_objects=[])
        module = _load_rendering_module(bpy_stub)
        with self.assertRaises(MissingCameraError) as ctx:
            module.render_scene()
        self.assertEqual(ctx.exception.camera_name, TOONFLOW_CAMERA_NAME)
        self.assertIsInstance(ctx.exception, GenerationError)

    def test_wrong_type_under_camera_name_raises(self):
        bpy_stub = _make_bpy_stub(
            initial_objects=[_Object(TOONFLOW_CAMERA_NAME, obj_type="MESH")]
        )
        module = _load_rendering_module(bpy_stub)
        with self.assertRaises(InvalidCameraTypeError) as ctx:
            module.render_scene()
        self.assertEqual(ctx.exception.camera_name, TOONFLOW_CAMERA_NAME)
        self.assertEqual(ctx.exception.actual_type, "MESH")
        # The wrong-type object must NOT be modified or removed.
        self.assertIsNotNone(
            bpy_stub.data.objects.get(TOONFLOW_CAMERA_NAME)
        )

    def test_does_not_fall_back_to_user_camera(self):
        # Add an unrelated user camera. The renderer must NOT use it.
        user_cam = _Object("UserCamera", obj_type="CAMERA")
        bpy_stub = _make_bpy_stub(initial_objects=[user_cam])
        module = _load_rendering_module(bpy_stub)
        with self.assertRaises(MissingCameraError):
            module.render_scene()
        # The user camera must remain untouched.
        self.assertIs(bpy_stub.data.objects.get("UserCamera"), user_cam)

    def test_renders_with_deterministic_settings(self):
        with tempfile.TemporaryDirectory() as d:
            cam = _Object(TOONFLOW_CAMERA_NAME, obj_type="CAMERA")
            bpy_stub = _make_bpy_stub(initial_objects=[cam])
            module = _load_rendering_module(bpy_stub)
            out = Path(d) / "out.png"

            result = module.render_scene(output_path=str(out))

            scene = bpy_stub._scene
            self.assertEqual(scene.render.resolution_x, 512)
            self.assertEqual(scene.render.resolution_y, 512)
            self.assertEqual(scene.render.resolution_percentage, 100)
            self.assertEqual(scene.render.image_settings.file_format, "PNG")
            self.assertEqual(scene.render.filepath, str(out.resolve()))
            self.assertEqual(scene.camera, cam)
            self.assertEqual(result["output_path"], str(out.resolve()))
            self.assertEqual(result["camera_name"], TOONFLOW_CAMERA_NAME)
            # bpy.ops.render.render was called once.
            self.assertEqual(len(bpy_stub._render_calls), 1)
            self.assertTrue(bpy_stub._render_calls[0]["write_still"])

    def test_default_output_path_used_when_none(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "scene.blend").write_text("")
            cam = _Object(TOONFLOW_CAMERA_NAME, obj_type="CAMERA")
            bpy_stub = _make_bpy_stub(
                initial_objects=[cam],
                blend_filepath=str(Path(d) / "scene.blend"),
            )
            module = _load_rendering_module(bpy_stub)

            result = module.render_scene()

            self.assertEqual(
                Path(result["output_path"]).name, "toonflow_render.png"
            )
            self.assertEqual(
                Path(result["output_path"]).parent.resolve(),
                Path(d).resolve(),
            )

    def test_invalid_output_path_raises(self):
        cam = _Object(TOONFLOW_CAMERA_NAME, obj_type="CAMERA")
        bpy_stub = _make_bpy_stub(initial_objects=[cam])
        module = _load_rendering_module(bpy_stub)
        with self.assertRaises(InvalidOutputPathError):
            module.render_scene(output_path=123)
        with self.assertRaises(InvalidOutputPathError):
            module.render_scene(output_path="")

    def test_repeated_calls_do_not_create_objects(self):
        cam = _Object(TOONFLOW_CAMERA_NAME, obj_type="CAMERA")
        bpy_stub = _make_bpy_stub(initial_objects=[cam])
        module = _load_rendering_module(bpy_stub)
        with tempfile.TemporaryDirectory() as d:
            out1 = str(Path(d) / "a.png")
            out2 = str(Path(d) / "b.png")
            module.render_scene(output_path=out1)
            module.render_scene(output_path=out2)
        # Still exactly one object (the camera).
        self.assertEqual(len(list(bpy_stub.data.objects)), 1)
        self.assertEqual(len(bpy_stub._render_calls), 2)

    def test_repeated_calls_do_not_modify_unrelated_objects(self):
        cam = _Object(TOONFLOW_CAMERA_NAME, obj_type="CAMERA")
        user = _Object("UserCube", obj_type="MESH")
        bpy_stub = _make_bpy_stub(initial_objects=[cam, user])
        module = _load_rendering_module(bpy_stub)
        with tempfile.TemporaryDirectory() as d:
            module.render_scene(output_path=str(Path(d) / "a.png"))
        # User object untouched (no name change, no removal, no type change).
        self.assertIs(bpy_stub.data.objects.get("UserCube"), user)
        self.assertEqual(user.type, "MESH")
        # Object count unchanged.
        self.assertEqual(len(list(bpy_stub.data.objects)), 2)

    def test_render_failure_raises_render_error(self):
        cam = _Object(TOONFLOW_CAMERA_NAME, obj_type="CAMERA")
        bpy_stub = _make_bpy_stub(initial_objects=[cam])

        def _boom(write_still=False):
            raise RuntimeError("simulated Blender failure")

        bpy_stub.ops.render.render = _boom
        module = _load_rendering_module(bpy_stub)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RenderError) as ctx:
                module.render_scene(output_path=str(Path(d) / "a.png"))
        self.assertIsInstance(ctx.exception, GenerationError)
        self.assertIn("simulated Blender failure", ctx.exception.cause)


# --- D. Architecture / static checks ---------------------------------------

class RenderingArchitectureTests(_RenderBpyStubMixin, unittest.TestCase):
    def test_render_data_is_bpy_free(self):
        tree = ast.parse(RENDER_DATA_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(
                        alias.name == "bpy" or alias.name.startswith("bpy."),
                        f"bpy import in render_data: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("bpy"):
                    self.fail(f"bpy 'from' import in render_data: {node.module}")

    def test_rendering_uses_bpy_only_via_require(self):
        # The only ``import bpy`` statement in the module must live
        # inside the function ``_require_bpy``.
        tree = ast.parse(RENDERING_SOURCE)
        allowed_function = "_require_bpy"

        parent_map = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parent_map[id(child)] = parent

        for node in ast.walk(tree):
            is_bpy_import = (
                (isinstance(node, ast.Import)
                 and any(a.name == "bpy" or a.name.startswith("bpy.")
                         for a in node.names))
                or (isinstance(node, ast.ImportFrom)
                    and (node.module or "").startswith("bpy"))
            )
            if not is_bpy_import:
                continue
            ancestor = parent_map.get(id(node))
            while ancestor is not None and not isinstance(ancestor, ast.FunctionDef):
                ancestor = parent_map.get(id(ancestor))
            self.assertIsNotNone(ancestor, "bpy import is not inside any function")
            self.assertEqual(
                ancestor.name, allowed_function,
                f"bpy import must live inside {allowed_function}(); "
                f"found inside {ancestor.name}()",
            )

    def test_no_ai_ollama_http_urllib(self):
        for source in (RENDERING_SOURCE, RENDER_DATA_SOURCE):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name in (
                                "ai", "ollama", "urllib", "urllib.request",
                                "requests", "http",
                            ),
                            f"forbidden import: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(
                        (node.module or "").split(".")[0],
                        {
                            "ai", "ollama", "urllib", "requests", "http",
                        },
                        f"forbidden from-import: {node.module}",
                    )

    def test_no_audio_or_speech(self):
        for source in (RENDERING_SOURCE, RENDER_DATA_SOURCE):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name in (
                                "wave", "soundfile", "librosa",
                                "speech_recognition", "audio",
                            ),
                            f"forbidden import: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(
                        (node.module or "").split(".")[0],
                        {
                            "wave", "soundfile", "librosa",
                            "speech_recognition", "audio",
                        },
                        f"forbidden from-import: {node.module}",
                    )

    def test_rendering_does_not_duplicate_camera_naming(self):
        # AST-based: no string literal equal to the deterministic camera
        # name; the constant must be imported from .camera_data.
        tree = ast.parse(RENDERING_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "TOONFLOW_CAMERA":
                self.fail("rendering.py must not hardcode the TOONFLOW_CAMERA name")
        imports_camera_data = False
        uses_constant = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("camera_data"):
                imports_camera_data = True
            if isinstance(node, ast.Name) and node.id == "TOONFLOW_CAMERA_NAME":
                uses_constant = True
        self.assertTrue(imports_camera_data, "rendering.py must import from .camera_data")
        self.assertTrue(uses_constant, "rendering.py must reference TOONFLOW_CAMERA_NAME")

    def test_rendering_uses_bpy_ops_render_only_for_render(self):
        # bpy.ops must only appear as bpy.ops.render.render(...).
        tree = ast.parse(RENDERING_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                # Allow bpy.ops.render.render(...) but no other bpy.ops.X use.
                if node.attr == "ops":
                    # The value should be the ``bpy`` local returned by _require_bpy.
                    self.assertIsInstance(node.value, ast.Name)
                    self.assertEqual(node.value.id, "bpy")
            # No calls like bpy.ops.foo.bar() other than the documented render call.
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if func.attr != "render":
                        # Not a render call. Disallow bpy.ops.X.
                        root = func
                        while isinstance(root, ast.Attribute):
                            root = root.value
                        if isinstance(root, ast.Name) and root.id == "bpy":
                            if (isinstance(func.value, ast.Attribute)
                                    and func.value.attr == "ops"):
                                self.fail(
                                    f"Disallowed bpy.ops call: {ast.unparse(func)}"
                                )

    def test_rendering_does_not_call_scene_generation(self):
        # AST-based: no Call to generate_scene, set_character_pose,
        # animate_character, animate_lip_sync, or create_or_update_camera.
        tree = ast.parse(RENDERING_SOURCE)
        forbidden = {
            "generate_scene", "set_character_pose", "animate_character",
            "animate_lip_sync", "create_or_update_camera",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in forbidden:
                    self.fail(f"forbidden call: {func.id}()")
                if isinstance(func, ast.Attribute) and func.attr in forbidden:
                    # Disallow Attribute-form calls to the forbidden entry points.
                    # We still need to allow "scene.render.engine" etc., so
                    # we only fail if the attribute is followed by a Call and
                    # the attribute name matches.
                    self.fail(f"forbidden call: {func.attr}()")

    def test_rendering_does_not_print(self):
        self.assertNotIn("print(", RENDERING_SOURCE)
        self.assertNotIn("input(", RENDERING_SOURCE)

    def test_rendering_uses_existing_errors(self):
        for needle in (
            "BlenderUnavailableError",
            "InvalidCameraTypeError",
            "InvalidOutputPathError",
            "MissingCameraError",
            "RenderError",
        ):
            self.assertIn(needle, RENDERING_SOURCE, needle)

    def test_rendering_does_not_mutate_assets_or_pipeline(self):
        # AST-based check so docstrings/comments don't trip the test.
        for source in (RENDERING_SOURCE, RENDER_DATA_SOURCE):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name in (
                                "asset_registry", "scene_plan", "pipeline",
                                "ai", "ai.planner", "ai.ollama_client",
                            ),
                            f"forbidden import: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(
                        (node.module or "").split(".")[0],
                        {
                            "asset_registry", "scene_plan", "pipeline", "ai",
                        },
                        f"forbidden from-import: {node.module}",
                    )


if __name__ == "__main__":
    unittest.main()
