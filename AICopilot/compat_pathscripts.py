"""PathScripts compatibility redirector for FreeCAD 1.0+ and development builds.

In FreeCAD 1.0+, the CAM (formerly Path) workbench underwent a major namespace
refactor: legacy modules under PathScripts (e.g. PathScripts.PathJob,
PathScripts.PathProfile, PathScripts.PathPocket, PathScripts.PathToolBit)
were relocated to Path.Main.Job, Path.Op.Profile, Path.Op.Pocket, Path.Tool.Bit, etc.

Older scripts, macros, and LLM-generated code often still attempt:
    import PathScripts.PathJob as PathJob
    from PathScripts import PathProfile

This module installs a sys.meta_path finder and a virtual PathScripts module
so that legacy imports resolve transparently to their modern FreeCAD equivalents.
"""

import importlib
import importlib.util
import logging
import sys
import types
from typing import Optional

logger = logging.getLogger(__name__)

# Map legacy PathScripts module name to modern FreeCAD module path
_PATHSCRIPTS_REDIRECTS = {
    "PathJob": "Path.Main.Job",
    "PathJobGui": "Path.Main.Gui.Job",
    "PathStock": "Path.Main.Stock",
    "PathProfile": "Path.Op.Profile",
    "PathPocket": "Path.Op.Pocket",
    "PathPocketShape": "Path.Op.PocketShape",
    "PathDrilling": "Path.Op.Drilling",
    "PathAdaptive": "Path.Op.Adaptive",
    "PathSurface": "Path.Op.Surface",
    "PathHelix": "Path.Op.Helix",
    "PathMillFace": "Path.Op.MillFace",
    "PathMillFacing": "Path.Op.MillFacing",
    "PathSlot": "Path.Op.Slot",
    "PathEngrave": "Path.Op.Engrave",
    "PathVcarve": "Path.Op.Vcarve",
    "PathDeburr": "Path.Op.Deburr",
    "PathWaterline": "Path.Op.Waterline",
    "PathToolBit": "Path.Tool.Bit",
    "PathToolController": "Path.Tool.Controller",
    "PathPost": "Path.Post.Command",
    "PathPreferences": "Path.Preferences",
    "PathLog": "Path.Log",
    "PathGeom": "Path.Geom",
    "PathUtils": "PathScripts.PathUtils",
    "PathPropertyBag": "PathScripts.PathPropertyBag",
}


class PathScriptsCompatFinder:
    """PEP 302/451 meta-path finder that intercepts PathScripts.<submodule> imports."""

    @classmethod
    def find_spec(cls, fullname: str, path=None, target=None):
        if fullname.startswith("PathScripts."):
            sub = fullname.split(".", 1)[1]
            target_mod = _PATHSCRIPTS_REDIRECTS.get(sub)
            if target_mod:
                try:
                    spec = importlib.util.find_spec(target_mod)
                    if spec:
                        return spec
                except Exception as e:
                    logger.debug("Failed to find spec for redirect %s -> %s: %s", fullname, target_mod, e)
        return None


class _VirtualPathScriptsPackage(types.ModuleType):
    """Virtual package module for PathScripts allowing attribute access like
    `from PathScripts import PathJob`."""

    def __getattr__(self, name: str):
        target = _PATHSCRIPTS_REDIRECTS.get(name)
        if target:
            try:
                mod = importlib.import_module(target)
                setattr(self, name, mod)
                sys.modules[f"PathScripts.{name}"] = mod
                return mod
            except Exception as e:
                logger.warning("Failed to import redirected module %s: %s", target, e)
        raise AttributeError(f"module 'PathScripts' has no attribute '{name}'")


_installed = False


def install_pathscripts_compat():
    """Install the PathScripts backward compatibility import hooks."""
    global _installed
    if _installed:
        return

    # 1. Register meta-path finder if not already present
    if not any(isinstance(finder, type) and finder.__name__ == "PathScriptsCompatFinder" for finder in sys.meta_path):
        sys.meta_path.insert(0, PathScriptsCompatFinder)

    # 2. Ensure PathScripts exists as a package in sys.modules
    existing_mod = sys.modules.get("PathScripts")
    if existing_mod is None or not isinstance(existing_mod, _VirtualPathScriptsPackage):
        virtual_mod = _VirtualPathScriptsPackage("PathScripts")
        virtual_mod.__doc__ = "Compatibility bridge for legacy FreeCAD PathScripts imports"
        # __path__ is required for Python to recognize it as a package
        virtual_mod.__path__ = getattr(existing_mod, "__path__", [])
        # Preserve any attributes from already-loaded PathScripts
        if existing_mod:
            for k, v in existing_mod.__dict__.items():
                if not k.startswith("__"):
                    setattr(virtual_mod, k, v)
        sys.modules["PathScripts"] = virtual_mod

    _installed = True
    logger.info("PathScripts backward-compatibility import bridge installed")
