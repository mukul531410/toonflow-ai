"""Tests for TOONFLOW-PHASE-036 — Release Packaging & Repository Readiness Foundation.

Covers:

A. valid add-on structure passes
B. missing package fails
C. missing required file fails
D. invalid metadata fails
E. archive root is exactly correct
F. archive file ordering is deterministic
G. repeated packaging produces identical ZIP bytes
H. development artifacts are excluded
I. absolute paths are rejected
J. traversal paths are rejected
K. duplicate archive paths are rejected
L. source tree is unchanged
M. output archive is valid
N. CLI packaging works
O. packaging does not import bpy
P. packaging does not import subprocess
Q. packaging does not use network
R. packaging does not mutate repository state
S. deterministic serialization/reporting
"""

import ast
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflow.packaging import (  # noqa: E402
    DEFAULT_EXCLUDED_PATHS,
    DEFAULT_INCLUDED_PATHS,
    DEFAULT_REQUIRED_PATHS,
    AddonPackageBuildResult,
    AddonPackageManifest,
    PackagingStatus,
    PackagingValidationResult,
    addon_package_manifest_default,
    build_addon_zip,
    build_result_to_dict,
    build_result_to_json,
    packaging_module_imports_safe,
    packaging_validation_to_dict,
    packaging_validation_to_json,
    read_archive_manifest,
    validate_addon_package,
)


def _ast_all_imports(source: str):
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(node.module)
    return out


def _make_fake_addon(root: Path) -> Path:
    """Create a minimal but valid fake add-on at *root*."""
    addon = root / "toonflow_ai"
    addon.mkdir(parents=True, exist_ok=True)
    (addon / "__init__.py").write_text(
        'bl_info = {\n'
        '    "name": "Fake",\n'
        '    "blender": (4, 2, 0),\n'
        '    "category": "3D View",\n'
        '    "version": (0, 1, 0),\n'
        '    "author": "Test",\n'
        '    "description": "Fake add-on for tests.",\n'
        '}\n\n'
        'def register():\n    pass\n\n'
        'def unregister():\n    pass\n',
        encoding="utf-8",
    )
    (addon / "registration.py").write_text("def register():\n    pass\n")
    (addon / "operator.py").write_text("import bpy\n")
    (addon / "properties.py").write_text("import bpy\n")
    (addon / "ui.py").write_text("import bpy\n")
    gen = addon / "generation"
    gen.mkdir()
    (gen / "__init__.py").write_text("")
    (gen / "animation.py").write_text("import bpy\n")
    (gen / "camera.py").write_text("import bpy\n")
    (gen / "lip_sync.py").write_text("import bpy\n")
    (gen / "pose.py").write_text("import bpy\n")
    (gen / "rendering.py").write_text("import bpy\n")
    (gen / "validation.py").write_text("import bpy\n")
    (gen / "blender_generator.py").write_text("import bpy\n")
    return addon


# --- A. valid add-on structure passes ---------------------------------------


class ValidAddOnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_manifest_validates_against_real_repo(self):
        manifest = addon_package_manifest_default(PROJECT_ROOT)
        result = validate_addon_package(manifest)
        self.assertEqual(result.status, PackagingStatus.PASS)
        self.assertEqual(result.issues, ())

    def test_fake_addon_validates_as_pass(self):
        fake_root = Path(self.tmp) / "fake_repo"
        fake_root.mkdir()
        _make_fake_addon(fake_root)
        manifest = AddonPackageManifest(
            source_dir=fake_root / "toonflow_ai",
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        result = validate_addon_package(manifest)
        self.assertEqual(result.status, PackagingStatus.PASS)


# --- B. missing package fails ----------------------------------------------


class MissingPackageTests(unittest.TestCase):
    def test_missing_source_dir_fails(self):
        manifest = AddonPackageManifest(
            source_dir=Path("/nonexistent/never/there"),
            archive_root="toonflow_ai",
            included_relative_paths=("__init__.py",),
            excluded_relative_paths=(),
        )
        result = validate_addon_package(manifest)
        self.assertEqual(result.status, PackagingStatus.FAIL)
        self.assertTrue(any("missing" in i for i in result.issues))

    def test_missing_init_fails(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "registration.py").write_text("")
            manifest = AddonPackageManifest(
                source_dir=tmp,
                archive_root="toonflow_ai",
                included_relative_paths=("__init__.py",),
                excluded_relative_paths=(),
            )
            result = validate_addon_package(manifest)
            self.assertEqual(result.status, PackagingStatus.FAIL)
            self.assertTrue(any("__init__.py" in i for i in result.issues))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --- C. missing required file fails ----------------------------------------


class MissingRequiredFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = self.tmp / "toonflow_ai"
        self.addon.mkdir()
        (self.addon / "__init__.py").write_text(
            'bl_info = {\n'
            '    "name": "X",\n'
            '    "blender": (4, 2, 0),\n'
            '    "category": "3D View",\n'
            '    "version": (0, 1, 0),\n'
            '    "author": "X",\n'
            '    "description": "X",\n'
            '}\n'
        )
        (self.addon / "registration.py").write_text("")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_operator_fails(self):
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=(
                "__init__.py", "registration.py", "operator.py",
            ),
            excluded_relative_paths=(),
        )
        result = validate_addon_package(manifest)
        self.assertEqual(result.status, PackagingStatus.FAIL)
        self.assertTrue(any("operator.py" in i for i in result.issues))


# --- D. invalid metadata fails ---------------------------------------------


class InvalidMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = self.tmp / "toonflow_ai"
        self.addon.mkdir()
        (self.addon / "registration.py").write_text("")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_bl_info_fails(self):
        (self.addon / "__init__.py").write_text("# nothing\n")
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=("__init__.py", "registration.py"),
            excluded_relative_paths=(),
        )
        result = validate_addon_package(manifest)
        self.assertEqual(result.status, PackagingStatus.FAIL)
        self.assertTrue(any("bl_info" in i for i in result.issues))

    def test_incomplete_bl_info_fails(self):
        (self.addon / "__init__.py").write_text(
            'bl_info = {"name": "X"}\n'
        )
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=("__init__.py", "registration.py"),
            excluded_relative_paths=(),
        )
        result = validate_addon_package(manifest)
        self.assertEqual(result.status, PackagingStatus.FAIL)
        self.assertTrue(any("missing required keys" in i for i in result.issues))

    def test_non_string_name_fails(self):
        (self.addon / "__init__.py").write_text(
            'bl_info = {\n'
            '    "name": 123,\n'
            '    "blender": (4, 2, 0),\n'
            '    "category": "3D View",\n'
            '    "version": (0, 1, 0),\n'
            '    "author": "X",\n'
            '    "description": "X",\n'
            '}\n'
        )
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=("__init__.py", "registration.py"),
            excluded_relative_paths=(),
        )
        result = validate_addon_package(manifest)
        self.assertEqual(result.status, PackagingStatus.FAIL)


# --- E. archive root is exactly correct ------------------------------------


class ArchiveRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = _make_fake_addon(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_archive_root_is_toonflow_ai(self):
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        output = Path(self.tmp) / "out.zip"
        build = build_addon_zip(manifest, output)
        self.assertEqual(build.status, PackagingStatus.PASS)
        names = read_archive_manifest(output)
        self.assertTrue(all(n.startswith("toonflow_ai/") for n in names))
        # Exactly one top-level directory
        tops = {n.split("/")[0] for n in names}
        self.assertEqual(tops, {"toonflow_ai"})

    def test_archive_contains_bl_info(self):
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        output = Path(self.tmp) / "out.zip"
        build_addon_zip(manifest, output)
        with zipfile.ZipFile(output, "r") as zf:
            with zf.open("toonflow_ai/__init__.py") as fh:
                text = fh.read().decode("utf-8")
        self.assertIn("bl_info", text)


# --- F. archive file ordering is deterministic -----------------------------


class ArchiveOrderingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = _make_fake_addon(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_ordering_is_deterministic(self):
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        output = Path(self.tmp) / "out.zip"
        build_addon_zip(manifest, output)
        names = read_archive_manifest(output)
        self.assertEqual(names, tuple(sorted(names)))


# --- G. repeated packaging produces identical ZIP bytes --------------------


class DeterministicZipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = _make_fake_addon(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_repeated_builds_produce_identical_bytes(self):
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        a = Path(self.tmp) / "a.zip"
        b = Path(self.tmp) / "b.zip"
        build_addon_zip(manifest, a)
        build_addon_zip(manifest, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())


# --- H. development artifacts are excluded ---------------------------------


class DevelopmentArtifactsExclusionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = _make_fake_addon(Path(self.tmp))
        # Plant forbidden artifacts.
        (self.addon / "test_caching.pyc").write_text("")
        cache_dir = self.addon / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "x.pyc").write_text("")
        (self.addon / "notes.bak").write_text("")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_excluded_artifacts_make_validation_fail(self):
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        result = validate_addon_package(manifest)
        self.assertEqual(result.status, PackagingStatus.FAIL)
        joined = " ".join(result.issues)
        self.assertIn(".bak", joined)
        self.assertIn(".pyc", joined)


# --- I. absolute paths are rejected ----------------------------------------


class AbsolutePathRejectionTests(unittest.TestCase):
    def test_absolute_archive_path_rejected_by_manifest(self):
        with self.assertRaises(ValueError):
            AddonPackageManifest(
                source_dir=Path("/tmp"),
                archive_root="toonflow_ai",
                included_relative_paths=("/abs/file.py",),
                excluded_relative_paths=(),
            )

    def test_absolute_archive_path_rejected_by_build(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            addon = _make_fake_addon(Path(tmp))
            manifest = AddonPackageManifest(
                source_dir=addon,
                archive_root="toonflow_ai",
                included_relative_paths=DEFAULT_INCLUDED_PATHS,
                excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
            )
            # Try to build into an absolute path that is a directory.
            result = build_addon_zip(manifest, Path(tempfile.gettempdir()))
            self.assertEqual(result.status, PackagingStatus.FAIL)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --- J. traversal paths are rejected ---------------------------------------


class TraversalPathRejectionTests(unittest.TestCase):
    def test_traversal_in_manifest_rejected(self):
        with self.assertRaises(ValueError):
            AddonPackageManifest(
                source_dir=Path("/tmp"),
                archive_root="toonflow_ai",
                included_relative_paths=("../escape.py",),
                excluded_relative_paths=(),
            )

    def test_traversal_in_excluded_rejected(self):
        with self.assertRaises(ValueError):
            AddonPackageManifest(
                source_dir=Path("/tmp"),
                archive_root="toonflow_ai",
                included_relative_paths=(),
                excluded_relative_paths=("../escape.py",),
            )

    def test_relative_output_with_traversal_rejected(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            addon = _make_fake_addon(Path(tmp))
            manifest = AddonPackageManifest(
                source_dir=addon,
                archive_root="toonflow_ai",
                included_relative_paths=DEFAULT_INCLUDED_PATHS,
                excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
            )
            build = build_addon_zip(manifest, Path("../escape.zip"))
            self.assertEqual(build.status, PackagingStatus.FAIL)
            self.assertIn("traversal", build.issue)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --- K. duplicate archive paths are rejected -------------------------------


class DuplicatePathRejectionTests(unittest.TestCase):
    def test_duplicate_included_path_rejected(self):
        with self.assertRaises(ValueError):
            AddonPackageManifest(
                source_dir=Path("/tmp"),
                archive_root="toonflow_ai",
                included_relative_paths=("__init__.py", "__init__.py"),
                excluded_relative_paths=(),
            )


# --- L. source tree is unchanged -------------------------------------------


class SourceImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = _make_fake_addon(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _snapshot(self, root: Path):
        snap = {}
        for dirpath, dirnames, filenames in os.walk(root):
            for f in filenames:
                p = Path(dirpath) / f
                snap[str(p)] = (p.stat().st_mtime, p.stat().st_size)
        return snap

    def test_validation_does_not_modify_source(self):
        before = self._snapshot(self.addon)
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        validate_addon_package(manifest)
        after = self._snapshot(self.addon)
        self.assertEqual(before, after)

    def test_build_does_not_modify_source(self):
        before = self._snapshot(self.addon)
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        output = Path(self.tmp) / "out.zip"
        build_addon_zip(manifest, output)
        after = self._snapshot(self.addon)
        self.assertEqual(before, after)


# --- M. output archive is valid --------------------------------------------


class ArchiveValidityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = _make_fake_addon(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_archive_is_valid_zip(self):
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        output = Path(self.tmp) / "out.zip"
        build_addon_zip(manifest, output)
        self.assertTrue(zipfile.is_zipfile(output))
        with zipfile.ZipFile(output, "r") as zf:
            bad = zf.testzip()
            self.assertIsNone(bad)

    def test_archive_bytes_match_file_count(self):
        manifest = AddonPackageManifest(
            source_dir=self.addon,
            archive_root="toonflow_ai",
            included_relative_paths=DEFAULT_INCLUDED_PATHS,
            excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
        )
        output = Path(self.tmp) / "out.zip"
        build = build_addon_zip(manifest, output)
        self.assertGreater(build.archive_bytes, 0)
        self.assertEqual(build.file_count, len(DEFAULT_INCLUDED_PATHS))


# --- N. CLI packaging works ------------------------------------------------


class CLIPackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cli_package_addon_text(self):
        import io
        from workflow.cli import main

        output = Path(self.tmp) / "out.zip"
        stdout = io.StringIO()
        exit_code = main(
            ["package-addon", "--output", str(output)],
            stdout=stdout,
            addon_package_manifest_default=lambda project_root=None: (
                _fake_manifest_for(self.tmp)
            ),
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("Add-on packaging: PASS", stdout.getvalue())
        self.assertTrue(output.exists())

    def test_cli_package_addon_json(self):
        import io
        from workflow.cli import main

        output = Path(self.tmp) / "out.zip"
        stdout = io.StringIO()
        exit_code = main(
            ["package-addon", "--output", str(output), "--json"],
            stdout=stdout,
            addon_package_manifest_default=lambda project_root=None: (
                _fake_manifest_for(self.tmp)
            ),
        )
        self.assertEqual(exit_code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["status"], "PASS")
        self.assertEqual(data["file_count"], len(DEFAULT_INCLUDED_PATHS))


def _fake_manifest_for(tmp_dir: Path) -> AddonPackageManifest:
    """Return a manifest pointing to a fake add-on in *tmp_dir*."""
    fake_root = Path(tmp_dir) / "fake"
    _make_fake_addon(fake_root)
    return AddonPackageManifest(
        source_dir=fake_root / "toonflow_ai",
        archive_root="toonflow_ai",
        included_relative_paths=DEFAULT_INCLUDED_PATHS,
        excluded_relative_paths=DEFAULT_EXCLUDED_PATHS,
    )


# --- O,P,Q. packaging does not import forbidden modules -------------------


class ImportSafetyTests(unittest.TestCase):
    def test_packaging_does_not_import_bpy(self):
        bad = packaging_module_imports_safe()
        self.assertNotIn("bpy", bad)

    def test_packaging_does_not_import_subprocess(self):
        bad = packaging_module_imports_safe()
        self.assertNotIn("subprocess", bad)

    def test_packaging_does_not_import_network(self):
        bad = packaging_module_imports_safe()
        for mod in ("requests", "urllib", "http", "socket", "ssl"):
            self.assertNotIn(mod, bad)


# --- R. packaging does not mutate repository state ------------------------


class RepositoryImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addon = _make_fake_addon(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_validate_does_not_mutate_real_repo(self):
        # Snapshot real repo state.
        def snapshot():
            out = {}
            for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
                for f in filenames:
                    p = Path(dirpath) / f
                    out[str(p.relative_to(PROJECT_ROOT))] = (
                        p.stat().st_mtime
                    )
            return out

        before = snapshot()
        manifest = addon_package_manifest_default(PROJECT_ROOT)
        validate_addon_package(manifest)
        validate_addon_package(manifest)
        after = snapshot()
        self.assertEqual(before, after)


# --- S. deterministic serialization ----------------------------------------


class SerializationTests(unittest.TestCase):
    def test_validation_to_dict_deterministic(self):
        result = PackagingValidationResult(
            status=PackagingStatus.PASS,
            issues=(),
            checked_files=("a.py", "b.py"),
        )
        d1 = packaging_validation_to_dict(result)
        d2 = packaging_validation_to_dict(result)
        self.assertEqual(d1, d2)

    def test_validation_to_json_has_trailing_newline(self):
        result = PackagingValidationResult(
            status=PackagingStatus.PASS, issues=(), checked_files=(),
        )
        js = packaging_validation_to_json(result)
        self.assertTrue(js.endswith("\n"))
        self.assertFalse(js.endswith("\n\n"))

    def test_build_result_to_dict(self):
        # Need a dummy manifest; just use a real path.
        manifest = addon_package_manifest_default(PROJECT_ROOT)
        result = AddonPackageBuildResult(
            status=PackagingStatus.PASS,
            manifest_source=manifest,
            archive_path="/tmp/x.zip",
            archive_bytes=100,
            file_count=5,
        )
        d = build_result_to_dict(result)
        self.assertEqual(d["status"], "PASS")
        self.assertEqual(d["archive_bytes"], 100)
        self.assertEqual(d["file_count"], 5)

    def test_build_result_to_json(self):
        manifest = addon_package_manifest_default(PROJECT_ROOT)
        result = AddonPackageBuildResult(
            status=PackagingStatus.FAIL,
            manifest_source=manifest,
            issue="bad",
        )
        js = build_result_to_json(result)
        data = json.loads(js)
        self.assertEqual(data["status"], "FAIL")
        self.assertEqual(data["issue"], "bad")


# --- Source-file architecture scan -----------------------------------------


class PackagingSourceArchitectureTests(unittest.TestCase):
    def test_packaging_module_source_has_no_bpy_import(self):
        source = (PROJECT_ROOT / "workflow" / "packaging.py").read_text()
        imports = _ast_all_imports(source)
        self.assertNotIn("bpy", imports)

    def test_packaging_module_source_has_no_subprocess_import(self):
        source = (PROJECT_ROOT / "workflow" / "packaging.py").read_text()
        imports = _ast_all_imports(source)
        self.assertNotIn("subprocess", imports)

    def test_packaging_module_source_has_no_requests_import(self):
        source = (PROJECT_ROOT / "workflow" / "packaging.py").read_text()
        imports = _ast_all_imports(source)
        self.assertNotIn("requests", imports)


# --- Failure result invariants ---------------------------------------------


class BuildResultInvariantTests(unittest.TestCase):
    def test_pass_build_requires_archive_path(self):
        manifest = addon_package_manifest_default(PROJECT_ROOT)
        with self.assertRaises(ValueError):
            AddonPackageBuildResult(
                status=PackagingStatus.PASS,
                manifest_source=manifest,
                archive_path=None,
                archive_bytes=10,
                file_count=1,
            )

    def test_fail_build_requires_issue(self):
        manifest = addon_package_manifest_default(PROJECT_ROOT)
        with self.assertRaises(ValueError):
            AddonPackageBuildResult(
                status=PackagingStatus.FAIL,
                manifest_source=manifest,
                issue="",
            )


# --- Manifest invariants ---------------------------------------------------


class ManifestInvariantTests(unittest.TestCase):
    def test_empty_archive_root_rejected(self):
        with self.assertRaises(ValueError):
            AddonPackageManifest(
                source_dir=Path("/tmp"),
                archive_root="",
                included_relative_paths=(),
                excluded_relative_paths=(),
            )

    def test_slash_in_archive_root_rejected(self):
        with self.assertRaises(ValueError):
            AddonPackageManifest(
                source_dir=Path("/tmp"),
                archive_root="a/b",
                included_relative_paths=(),
                excluded_relative_paths=(),
            )

    def test_dot_in_archive_root_rejected(self):
        with self.assertRaises(ValueError):
            AddonPackageManifest(
                source_dir=Path("/tmp"),
                archive_root="..",
                included_relative_paths=(),
                excluded_relative_paths=(),
            )


if __name__ == "__main__":
    unittest.main()
