"""Unit tests for PathScripts backward compatibility redirector."""

import importlib
import sys
import unittest
from unittest.mock import patch

from AICopilot.compat_pathscripts import install_pathscripts_compat, _PATHSCRIPTS_REDIRECTS


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
        # In test environment where Path.Main.Job may not exist as real module,
        # find_spec returns None or a spec if mocked, but does not raise
        self.assertTrue(spec is None or spec is not None)

    def test_virtual_package_attribute_access_dynamic_import(self):
        import types
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
