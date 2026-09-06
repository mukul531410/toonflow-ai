"""Tests for TOONFLOW AI's Blender UI & Pipeline Integration.

Strategy:

- Pure-Python helper ``message_for_error`` is exercised directly.
- The operator module is loaded with a ``bpy`` stub so we can confirm
  it imports without Blender installed, references the right public
  pipeline API, and does not duplicate AI / generation logic.
- Static checks confirm that ``ai``, ``pipeline``, ``scene_plan``, and
  ``asset_registry`` remain ``bpy``-free after this phase.

Live panel/operator behaviour inside Blender cannot be tested without
Blender installed; that limitation is reported explicitly.
"""

import importlib.util
import inspect
import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ADDON_ROOT = PROJECT_ROOT / "addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


class _StubOperator:
    def __init__(self):
        self.messages = []
        self.context = types.SimpleNamespace(scene=types.SimpleNamespace())

    def report(self, setlevel, message):
        self.messages.append(message)


def _bpy_stub():
    """Build a minimal ``bpy`` stub that lets the operator module import."""

    class _PropertyGroup:
        pass

    class _Operator:
        pass

    class _Panel:
        pass

    class _StringProperty:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _PointerProperty:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    bpy_types = types.ModuleType("bpy.types")
    bpy_types.PropertyGroup = _PropertyGroup
    bpy_types.Operator = _Operator
    bpy_types.Panel = _Panel

    bpy_props = types.ModuleType("bpy.props")
    bpy_props.StringProperty = _StringProperty
    bpy_props.PointerProperty = _PointerProperty

    bpy_utils = types.ModuleType("bpy.utils")
    bpy_utils.register_class = lambda cls: None
    bpy_utils.unregister_class = lambda cls: None

    bpy = types.ModuleType("bpy")
    bpy.props = bpy_props
    bpy.types = bpy_types
    bpy.utils = bpy_utils
    return bpy


def _load_operator_module():
    """Import ``toonflow_ai.operator`` with a stubbed ``bpy`` module."""
    saved = {name: sys.modules.pop(name, None) for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils")}
    bpy_stub = _bpy_stub()
    sys.modules["bpy"] = bpy_stub
    sys.modules["bpy.types"] = bpy_stub.types
    sys.modules["bpy.props"] = bpy_stub.props
    sys.modules["bpy.utils"] = bpy_stub.utils
    try:
        if "toonflow_ai" not in sys.modules:
            toonflow_pkg = types.ModuleType("toonflow_ai")
            toonflow_pkg.__path__ = [str(ADDON_ROOT / "toonflow_ai")]
            sys.modules["toonflow_ai"] = toonflow_pkg
        if "toonflow_ai.operator" in sys.modules:
            del sys.modules["toonflow_ai.operator"]
        spec = importlib.util.spec_from_file_location(
            "toonflow_ai.operator",
            ADDON_ROOT / "toonflow_ai" / "operator.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["toonflow_ai.operator"] = module
        spec.loader.exec_module(module)
        return module, bpy_stub
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


operator_module, _ = _load_operator_module()


class OperatorErrorMappingTests(unittest.TestCase):
    def test_invalid_concept_message(self):
        from ai.errors import InvalidConceptError

        msg = operator_module.message_for_error(InvalidConceptError("x"))
        self.assertIn("Concept", msg)

    def test_ollama_unavailable_message(self):
        from ai.errors import OllamaUnavailableError

        msg = operator_module.message_for_error(OllamaUnavailableError("down"))
        self.assertIn("Ollama", msg)

    def test_ollama_timeout_message(self):
        from ai.errors import OllamaTimeoutError

        msg = operator_module.message_for_error(OllamaTimeoutError("slow"))
        self.assertIn("timeout", msg.lower())

    def test_ollama_http_message(self):
        from ai.errors import OllamaHTTPError

        err = OllamaHTTPError(503, "service down")
        msg = operator_module.message_for_error(err)
        self.assertIn("503", msg)
        self.assertIn("service down", msg)

    def test_ollama_response_message(self):
        from ai.errors import OllamaResponseError

        msg = operator_module.message_for_error(OllamaResponseError("no text"))
        self.assertIn("unusable", msg.lower())

    def test_invalid_model_json_message(self):
        from ai.errors import InvalidModelJSONError

        msg = operator_module.message_for_error(InvalidModelJSONError("bad"))
        self.assertIn("JSON", msg)

    def test_invalid_scene_plan_from_ai_message(self):
        from ai.errors import InvalidScenePlanError as AIErr

        err = AIErr([types.SimpleNamespace(path="version", message="bad")])
        msg = operator_module.message_for_error(err)
        self.assertIn("validation", msg.lower())
        self.assertIn("1", msg)

    def test_invalid_scene_plan_from_generation_message(self):
        from toonflow_ai.generation.errors import InvalidScenePlanError

        err = InvalidScenePlanError(
            [types.SimpleNamespace(path="version", message="bad")]
        )
        msg = operator_module.message_for_error(err)
        self.assertIn("validation", msg.lower())

    def test_unknown_asset_message_includes_asset_id(self):
        from toonflow_ai.generation.errors import UnknownAssetError

        err = UnknownAssetError("castle", "environment")
        msg = operator_module.message_for_error(err)
        self.assertIn("castle", msg)
        self.assertIn("environment", msg.lower())

    def test_blender_unavailable_message(self):
        from toonflow_ai.generation.errors import BlenderUnavailableError

        msg = operator_module.message_for_error(BlenderUnavailableError("nope"))
        self.assertIn("bpy", msg)

    def test_unknown_error_passthrough(self):
        class _Weird(ValueError):
            pass

        msg = operator_module.message_for_error(_Weird("oops"))
        self.assertIn("_Weird", msg)
        self.assertIn("oops", msg)


def _import_lines(module):
    """Return only real ``import`` / ``from ... import`` lines for *module*."""
    import ast

    try:
        tree = ast.parse(inspect.getsource(module))
    except SyntaxError:
        return []
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.append(ast.unparse(node))
    return lines


class OperatorStaticStructureTests(unittest.TestCase):
    def test_operator_class_exists(self):
        self.assertTrue(hasattr(operator_module, "TOONFLOW_OT_generate_scene"))

    def test_operator_bl_idname(self):
        cls = operator_module.TOONFLOW_OT_generate_scene
        self.assertEqual(cls.bl_idname, "toonflow.generate_scene")
        self.assertTrue(cls.bl_label)

    def test_operator_module_imports_pipeline(self):
        imports = _import_lines(operator_module)
        self.assertTrue(
            any("from pipeline import create_scene_from_concept" in line for line in imports),
            imports,
        )

    def test_operator_does_not_import_urllib(self):
        imports = _import_lines(operator_module)
        self.assertFalse(
            any("urllib" in line for line in imports),
            imports,
        )

    def test_operator_does_not_import_ollama_client(self):
        imports = _import_lines(operator_module)
        self.assertFalse(
            any("ollama_client" in line for line in imports),
            imports,
        )

    def test_operator_does_not_import_scene_plan_or_asset_registry(self):
        imports = _import_lines(operator_module)
        self.assertFalse(
            any("scene_plan" in line or "asset_registry" in line for line in imports),
            imports,
        )

    def test_operator_does_not_import_bpy_objects_module(self):
        imports = _import_lines(operator_module)
        self.assertFalse(
            any("bpy.data" in line or "bpy.ops" in line for line in imports),
            imports,
        )


def _make_context(concept):
    properties = types.SimpleNamespace(concept=concept, last_status="")
    scene = types.SimpleNamespace(toonflow=properties)
    context = types.SimpleNamespace(scene=scene)
    return context


def _make_operator_stub():
    op = operator_module.TOONFLOW_OT_generate_scene()
    op.messages = []

    def report(setlevel, message):
        op.messages.append(message)

    op.report = report
    return op


class OperatorExecuteLogicTests(unittest.TestCase):
    def test_empty_concept_is_rejected(self):
        op = _make_operator_stub()
        op.context = _make_context("")
        result = op.execute(op.context)
        self.assertEqual(result, {"CANCELLED"})
        self.assertTrue(any("Concept" in m for m in op.messages))
        self.assertEqual(op.context.scene.toonflow.last_status, op.messages[-1])

    def test_whitespace_concept_is_rejected(self):
        op = _make_operator_stub()
        op.context = _make_context("   \n\t  ")
        result = op.execute(op.context)
        self.assertEqual(result, {"CANCELLED"})
        self.assertTrue(any("Concept" in m for m in op.messages))

    def test_success_runs_pipeline_and_reports(self):
        from dataclasses import dataclass

        @dataclass
        class FakeGenerationResult:
            environment_object_names: list
            character_object_names: list

        @dataclass
        class FakeSceneCreationResult:
            scene_plan: dict
            generation_result: FakeGenerationResult

        captured = {}

        def fake_create(concept, **kwargs):
            captured["concept"] = concept
            return FakeSceneCreationResult(
                scene_plan={"version": "0.1"},
                generation_result=FakeGenerationResult(
                    environment_object_names=["TOONFLOW_ENV_LIVING_ROOM"],
                    character_object_names=[
                        "TOONFLOW_CHARACTER_HUSBAND_BODY",
                        "TOONFLOW_CHARACTER_HUSBAND_HEAD",
                    ],
                ),
            )

        original = operator_module.create_scene_from_concept
        operator_module.create_scene_from_concept = fake_create
        try:
            op = _make_operator_stub()
            op.context = _make_context("A family at home")
            result = op.execute(op.context)
        finally:
            operator_module.create_scene_from_concept = original

        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(captured["concept"], "A family at home")
        joined = " ".join(op.messages)
        self.assertIn("TOONFLOW_ENV_LIVING_ROOM", joined)
        self.assertIn("TOONFLOW_CHARACTER_HUSBAND_BODY", joined)

    def test_pipeline_invalid_concept_is_surfaced(self):
        from ai.errors import InvalidConceptError

        def fake_create(concept, **kwargs):
            raise InvalidConceptError("concept must be a non-empty string.")

        original = operator_module.create_scene_from_concept
        operator_module.create_scene_from_concept = fake_create
        try:
            op = _make_operator_stub()
            op.context = _make_context("x")
            result = op.execute(op.context)
        finally:
            operator_module.create_scene_from_concept = original

        self.assertEqual(result, {"CANCELLED"})
        joined = " ".join(op.messages)
        self.assertIn("Concept", joined)

    def test_pipeline_unknown_asset_is_surfaced(self):
        from toonflow_ai.generation.errors import UnknownAssetError

        def fake_create(concept, **kwargs):
            raise UnknownAssetError("castle", "environment")

        original = operator_module.create_scene_from_concept
        operator_module.create_scene_from_concept = fake_create
        try:
            op = _make_operator_stub()
            op.context = _make_context("x")
            result = op.execute(op.context)
        finally:
            operator_module.create_scene_from_concept = original

        self.assertEqual(result, {"CANCELLED"})
        joined = " ".join(op.messages)
        self.assertIn("castle", joined)


class PropertyModuleStaticTests(unittest.TestCase):
    def test_toonflow_scene_properties_uses_string_property(self):
        source = (ADDON_ROOT / "toonflow_ai" / "properties.py").read_text()
        self.assertIn("StringProperty", source)
        self.assertIn('subtype="MULTILINE"', source)
        self.assertIn("PointerProperty", source)
        self.assertIn("Scene.toonflow", source)


class UIPanelStaticTests(unittest.TestCase):
    def test_panel_uses_existing_class_naming(self):
        source = (ADDON_ROOT / "toonflow_ai" / "ui.py").read_text()
        self.assertIn("TOONFLOW_PT_panel", source)
        self.assertIn('bl_space_type = "VIEW_3D"', source)
        self.assertIn('bl_category = "TOONFLOW"', source)
        self.assertIn("toonflow.generate_scene", source)

    def test_panel_does_not_expose_unwanted_controls(self):
        import ast

        source = (ADDON_ROOT / "toonflow_ai" / "ui.py").read_text()
        forbidden_property_types = (
            "EnumProperty",
            "IntProperty",
            "BoolProperty",
            "FloatProperty",
        )
        try:
            tree = ast.parse(source)
        except SyntaxError:
            self.fail("ui.py is not parseable")

        for node in ast.walk(tree):
            label = ""
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                label = node.func.id
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                label = node.func.attr
            self.assertNotIn(label, forbidden_property_types, f"unexpected call: {label}")

        forbidden_draw_terms = ("camera", "render", "animation", "asset selector")
        draw_fn = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "draw"
            ),
            None,
        )
        self.assertIsNotNone(draw_fn)
        for term in forbidden_draw_terms:
            self.assertNotIn(term, ast.unparse(draw_fn).lower())


class RegistrationStaticTests(unittest.TestCase):
    def test_registration_calls_each_submodule(self):
        source = (ADDON_ROOT / "toonflow_ai" / "registration.py").read_text()
        self.assertIn("ui.register()", source)
        self.assertIn("operator.register()", source)
        self.assertIn("properties.register()", source)
        self.assertIn("ui.unregister()", source)
        self.assertIn("operator.unregister()", source)
        self.assertIn("properties.unregister()", source)


class DependencyBoundaryTests(unittest.TestCase):
    def _no_bpy(self, package):
        if package in sys.modules:
            mod = sys.modules[package]
        else:
            mod = importlib.import_module(package)
        source = inspect.getsource(mod)
        self.assertNotIn("import bpy", source)
        self.assertNotIn("from bpy", source)

    def test_ai_is_bpy_free(self):
        for pkg in (
            "ai",
            "ai.errors",
            "ai.ollama_client",
            "ai.planner",
        ):
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

    def test_generation_validation_is_bpy_free(self):
        self._no_bpy("toonflow_ai.generation.validation")
        self._no_bpy("toonflow_ai.generation.errors")


class SyntaxValidationTests(unittest.TestCase):
    def test_all_new_addon_modules_compile(self):
        import py_compile

        for name in (
            "__init__.py",
            "properties.py",
            "operator.py",
            "ui.py",
            "registration.py",
        ):
            path = ADDON_ROOT / "toonflow_ai" / name
            self.assertTrue(path.exists(), f"missing {path}")
            py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    unittest.main()