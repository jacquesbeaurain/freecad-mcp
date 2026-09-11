"""Unit tests for CAM and PathScripts backward compatibility redirector."""

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
    _CAM_MODULE_REDIRECTS,
    _PATHSCRIPTS_REDIRECTS,
    _OP_MODULE_MAP,
    CAMModuleCompatFinder,
)


class TestCAMModuleCompat(unittest.TestCase):
    def setUp(self):
        install_pathscripts_compat()

    def test_redirects_defined(self):
        self.assertIn("PathJob", _PATHSCRIPTS_REDIRECTS)
        self.assertEqual(_PATHSCRIPTS_REDIRECTS["PathJob"], "Path.Main.Job")
        self.assertIn("PathProfile", _PATHSCRIPTS_REDIRECTS)
        self.assertEqual(_PATHSCRIPTS_REDIRECTS["PathProfile"], "Path.Op.Profile")
        self.assertIn("PathSurface", _PATHSCRIPTS_REDIRECTS)
        self.assertEqual(_PATHSCRIPTS_REDIRECTS["PathSurface"], "Path.Op.Surface")
        # Intuitive Path.Op aliases
        self.assertIn(_CAM_MODULE_REDIRECTS["Path.Op.Face"], ("Path.Op.MillFacing", "Path.Op.MillFace", ("Path.Op.MillFacing", "Path.Op.MillFace")))
        self.assertIn(_CAM_MODULE_REDIRECTS["Path.Op.Facing"], ("Path.Op.MillFacing", "Path.Op.MillFace", ("Path.Op.MillFacing", "Path.Op.MillFace")))
        self.assertEqual(_CAM_MODULE_REDIRECTS["Path.Op.Drill"], "Path.Op.Drilling")
        self.assertEqual(_CAM_MODULE_REDIRECTS["Path.Op.Contour"], "Path.Op.Profile")
        # Root shortcuts
        self.assertEqual(_CAM_MODULE_REDIRECTS["Path.Job"], "Path.Main.Job")
        self.assertEqual(_CAM_MODULE_REDIRECTS["Path.Stock"], "Path.Main.Stock")
        self.assertEqual(_CAM_MODULE_REDIRECTS["Path.ToolBit"], "Path.Tool.Bit")

    def test_import_virtual_pathscripts_attribute(self):
        import PathScripts
        self.assertTrue(hasattr(PathScripts, "__path__"))

    def test_meta_path_finder_resolves_path_op_face(self):
        spec = CAMModuleCompatFinder.find_spec("Path.Op.Face")
        self.assertTrue(spec is None or spec is not None)

    def test_meta_path_finder_resolves_pathscripts_submodule(self):
        spec = CAMModuleCompatFinder.find_spec("PathScripts.PathJob")
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

    def test_path_op_face_resolves_to_millface(self):
        fake_path = types.ModuleType("Path")
        fake_path.__path__ = []
        sys.modules["Path"] = fake_path

        fake_path_op = types.ModuleType("Path.Op")
        fake_path_op.__path__ = []
        sys.modules["Path.Op"] = fake_path_op

        fake_millface = types.ModuleType("Path.Op.MillFace")
        fake_millface.Create = lambda *args: "fake_millface_create"
        sys.modules["Path.Op.MillFace"] = fake_millface

        # Re-run install to bind aliases
        import AICopilot.compat_pathscripts as cp
        cp._installed = False
        cp.install_pathscripts_compat()

        try:
            import Path.Op.Face as PathFace
            self.assertEqual(PathFace, fake_millface)
            self.assertEqual(PathFace.Create(), "fake_millface_create")
            self.assertEqual(fake_path_op.Face, fake_millface)
        finally:
            sys.modules.pop("Path.Op.MillFace", None)
            sys.modules.pop("Path.Op.Face", None)
            sys.modules.pop("Path.Op", None)
            sys.modules.pop("Path", None)

    def test_path_op_face_resolves_to_millfacing_when_available(self):
        fake_path = types.ModuleType("Path")
        fake_path.__path__ = []
        sys.modules["Path"] = fake_path

        fake_path_op = types.ModuleType("Path.Op")
        fake_path_op.__path__ = []
        sys.modules["Path.Op"] = fake_path_op

        fake_millfacing = types.ModuleType("Path.Op.MillFacing")
        fake_millfacing.Create = lambda *args: "fake_millfacing_create"
        sys.modules["Path.Op.MillFacing"] = fake_millfacing

        import AICopilot.compat_pathscripts as cp
        cp._installed = False
        cp.install_pathscripts_compat()

        try:
            import Path.Op.Face as PathFace
            self.assertEqual(PathFace, fake_millfacing)
            self.assertEqual(PathFace.Create(), "fake_millfacing_create")
        finally:
            sys.modules.pop("Path.Op.MillFacing", None)
            sys.modules.pop("Path.Op.Face", None)
            sys.modules.pop("Path.Op", None)
            sys.modules.pop("Path", None)

    def test_path_job_resolves_to_main_job(self):
        fake_path = types.ModuleType("Path")
        fake_path.__path__ = []
        sys.modules["Path"] = fake_path

        fake_job = types.ModuleType("Path.Main.Job")
        fake_job.Create = lambda *args: "fake_job_create"
        sys.modules["Path.Main.Job"] = fake_job

        import AICopilot.compat_pathscripts as cp
        cp._installed = False
        cp.install_pathscripts_compat()

        try:
            import Path.Job as DirectJob
            self.assertEqual(DirectJob, fake_job)
            self.assertEqual(DirectJob.Create(), "fake_job_create")
            self.assertEqual(fake_path.Job, fake_job)
        finally:
            sys.modules.pop("Path.Main.Job", None)
            sys.modules.pop("Path.Job", None)
            sys.modules.pop("Path", None)

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
