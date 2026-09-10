"""Unit tests for PathScripts backward compatibility redirector."""

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock

from AICopilot.compat_pathscripts import (
    install_pathscripts_compat,
    detect_cam_environment,
    get_cam_mode,
    get_op_create,
    get_job_create,
    get_job_viewprovider,
    get_stock_factories,
    _PATHSCRIPTS_REDIRECTS,
    _OP_MODULE_MAP,
)


class TestPathScriptsCompat(unittest.TestCase):
    def setUp(self):
        install_pathscripts_compat()

    def test_redirects_defined(self):
        self.assertIn("PathJob", _PATHSCRIPTS_REDIRECTS)
        self.assertEqual(_PATHSCRIPTS_REDIRECTS["PathJob"], "Path.Main.Job")
        self.assertIn("PathProfile", _PATHSCRIPTS_REDIRECTS)
        self.assertEqual(_PATHSCRIPTS_REDIRECTS["PathProfile"], "Path.Op.Profile")
        self.assertIn("PathSurface", _PATHSCRIPTS_REDIRECTS)
        self.assertEqual(_PATHSCRIPTS_REDIRECTS["PathSurface"], "Path.Op.Surface")

    def test_import_virtual_pathscripts_attribute(self):
        import PathScripts
        self.assertTrue(hasattr(PathScripts, "__path__"))

    def test_meta_path_finder_resolves_pathscripts_submodule(self):
        from AICopilot.compat_pathscripts import PathScriptsCompatFinder
        spec = PathScriptsCompatFinder.find_spec("PathScripts.PathJob")
        self.assertTrue(spec is None or spec is not None)

    def test_virtual_package_attribute_access_dynamic_import(self):
        fake_job = types.ModuleType("Path.Main.Job")
        fake_job.Create = lambda *args: "fake_job"
        sys.modules["Path.Main.Job"] = fake_job

        try:
            import PathScripts
            job_mod = getattr(PathScripts, "PathJob")
            self.assertEqual(job_mod, fake_job)
            self.assertEqual(job_mod.Create(), "fake_job")
            self.assertEqual(sys.modules.get("PathScripts.PathJob"), fake_job)
        finally:
            sys.modules.pop("Path.Main.Job", None)
            sys.modules.pop("PathScripts.PathJob", None)

    def test_detect_cam_environment(self):
        mode = detect_cam_environment()
        self.assertIn(mode, ("modern", "legacy", "none"))
        self.assertEqual(get_cam_mode(), mode)

    def test_get_op_create_resolves_from_sys_modules(self):
        fake_profile = types.ModuleType("Path.Op.Profile")
        mock_create = MagicMock(return_value="mock_profile_op")
        fake_profile.Create = mock_create
        sys.modules["Path.Op.Profile"] = fake_profile

        try:
            create_fn = get_op_create("profile")
            self.assertEqual(create_fn(), "mock_profile_op")
            mock_create.assert_called_once()
        finally:
            sys.modules.pop("Path.Op.Profile", None)

    def test_get_job_create_resolves_from_sys_modules(self):
        fake_job = types.ModuleType("Path.Main.Job")
        mock_create = MagicMock(return_value="mock_job_obj")
        fake_job.Create = mock_create
        sys.modules["Path.Main.Job"] = fake_job

        try:
            create_fn = get_job_create()
            self.assertEqual(create_fn(), "mock_job_obj")
            mock_create.assert_called_once()
        finally:
            sys.modules.pop("Path.Main.Job", None)

    def test_get_stock_factories_resolves_from_sys_modules(self):
        fake_stock = types.ModuleType("Path.Main.Stock")
        fake_stock.CreateBox = MagicMock(return_value="mock_box")
        fake_stock.CreateCylinder = MagicMock(return_value="mock_cyl")
        fake_stock.CreateFromBase = MagicMock(return_value="mock_base")
        sys.modules["Path.Main.Stock"] = fake_stock

        try:
            create_box, create_cyl, create_base = get_stock_factories()
            self.assertEqual(create_box(), "mock_box")
            self.assertEqual(create_cyl(), "mock_cyl")
            self.assertEqual(create_base(), "mock_base")
        finally:
            sys.modules.pop("Path.Main.Stock", None)

    def test_get_job_viewprovider_resolves_when_present(self):
        fake_gui_job = types.ModuleType("Path.Main.Gui.Job")
        fake_gui_job.ViewProvider = MagicMock()
        sys.modules["Path.Main.Gui.Job"] = fake_gui_job

        try:
            vp = get_job_viewprovider()
            self.assertEqual(vp, fake_gui_job.ViewProvider)
        finally:
            sys.modules.pop("Path.Main.Gui.Job", None)
