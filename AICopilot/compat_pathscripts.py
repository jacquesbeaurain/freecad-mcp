"""PathScripts compatibility redirector for FreeCAD 1.0+ and development builds.

In FreeCAD 1.0+, the CAM (formerly Path) workbench underwent a major namespace
refactor: legacy modules under PathScripts (e.g. PathScripts.PathJob,
PathScripts.PathProfile, PathScripts.PathPocket, PathScripts.PathToolBit)
were relocated to Path.Main.Job, Path.Op.Profile, Path.Op.Pocket, Path.Tool.Bit, etc.

Older scripts, macros, and LLM-generated code often still attempt:
    import PathScripts.PathJob as PathJob
    from PathScripts import PathProfile

This module installs a sys.meta_path finder, pre-populates sys.modules,
and provides a virtual PathScripts module so that legacy imports resolve
transparently and instantly to their modern FreeCAD equivalents.
"""

import importlib
import importlib.util
import logging
import sys
import types
from typing import Optional, Tuple, Any

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

# Mapping of CAM operation names to candidate module paths (modern, fallbacks, legacy)
_OP_MODULE_MAP = {
    "profile": ("Path.Op.Profile", "PathScripts.PathProfile"),
    "pocket": ("Path.Op.Pocket", "PathScripts.PathPocket"),
    "pocket_shape": ("Path.Op.PocketShape", "PathScripts.PathPocketShape"),
    "drilling": ("Path.Op.Drilling", "PathScripts.PathDrilling"),
    "drill": ("Path.Op.Drilling", "PathScripts.PathDrilling"),
    "adaptive": ("Path.Op.Adaptive", "PathScripts.PathAdaptive"),
    "face": ("Path.Op.MillFace", "Path.Op.MillFacing", "PathScripts.PathMillFace", "PathScripts.PathMillFacing"),
    "mill_face": ("Path.Op.MillFace", "Path.Op.MillFacing", "PathScripts.PathMillFace", "PathScripts.PathMillFacing"),
    "surface": ("Path.Op.Surface", "PathScripts.PathSurface"),
    "surface_milling": ("Path.Op.Surface", "PathScripts.PathSurface"),
    "helix": ("Path.Op.Helix", "PathScripts.PathHelix"),
    "slot": ("Path.Op.Slot", "PathScripts.PathSlot"),
    "engrave": ("Path.Op.Engrave", "PathScripts.PathEngrave"),
    "vcarve": ("Path.Op.Vcarve", "PathScripts.PathVcarve"),
    "deburr": ("Path.Op.Deburr", "PathScripts.PathDeburr"),
    "waterline": ("Path.Op.Waterline", "PathScripts.PathWaterline"),
}

CAM_MODE: Optional[str] = None  # "modern" | "legacy" | "none"
_installed = False
_RESOLVED_OP_FACTORIES = {}


def detect_cam_environment() -> str:
    """Detect whether FreeCAD has modern Path (1.0+), legacy PathScripts (<1.0), or neither.

    Caches and returns CAM_MODE.
    """
    global CAM_MODE
    if CAM_MODE is not None:
        return CAM_MODE

    # 1. Check if modern Path is already loaded in sys.modules (e.g. tests or early imports)
    if "Path.Main.Job" in sys.modules or "Path.Op" in sys.modules:
        CAM_MODE = "modern"
        return CAM_MODE

    # 2. Check for modern FreeCAD 1.0+ CAM via spec inspection
    try:
        spec = importlib.util.find_spec("Path.Main.Job")
        if spec is not None:
            CAM_MODE = "modern"
            return CAM_MODE
    except Exception:
        pass

    # 3. Check for native legacy PathScripts on disk (<1.0)
    if "PathScripts" in sys.modules and not isinstance(sys.modules["PathScripts"], _VirtualPathScriptsPackage):
        CAM_MODE = "legacy"
        return CAM_MODE

    try:
        spec = importlib.util.find_spec("PathScripts.PathJob")
        if spec is not None and not (spec.loader and "compat_pathscripts" in getattr(spec.loader, "__module__", "")):
            CAM_MODE = "legacy"
            return CAM_MODE
    except Exception:
        pass

    # 4. Fallback import probes
    try:
        importlib.import_module("Path.Main.Job")
        CAM_MODE = "modern"
        return CAM_MODE
    except Exception:
        pass

    try:
        importlib.import_module("PathScripts.PathJob")
        CAM_MODE = "legacy"
        return CAM_MODE
    except Exception:
        pass

    CAM_MODE = "none"
    return CAM_MODE


def get_cam_mode() -> str:
    """Return the cached or detected CAM environment mode."""
    return detect_cam_environment()


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
                mod = sys.modules.get(target)
                if mod is None:
                    mod = importlib.import_module(target)
                setattr(self, name, mod)
                sys.modules[f"PathScripts.{name}"] = mod
                return mod
            except Exception as e:
                logger.warning("Failed to import redirected module %s: %s", target, e)
        raise AttributeError(f"module 'PathScripts' has no attribute '{name}'")


def install_pathscripts_compat() -> str:
    """Install the PathScripts backward compatibility import hooks and pre-populate sys.modules."""
    global _installed
    mode = detect_cam_environment()
    if _installed:
        return mode

    # 1. Register meta-path finder if not already present
    if not any(isinstance(finder, type) and finder.__name__ == "PathScriptsCompatFinder" for finder in sys.meta_path):
        sys.meta_path.insert(0, PathScriptsCompatFinder)

    # 2. Ensure PathScripts exists as a package in sys.modules
    existing_mod = sys.modules.get("PathScripts")
    if existing_mod is None or not isinstance(existing_mod, _VirtualPathScriptsPackage):
        virtual_mod = _VirtualPathScriptsPackage("PathScripts")
        virtual_mod.__doc__ = "Compatibility bridge for legacy FreeCAD PathScripts imports"
        virtual_mod.__path__ = getattr(existing_mod, "__path__", [])
        if existing_mod:
            for k, v in existing_mod.__dict__.items():
                if not k.startswith("__"):
                    setattr(virtual_mod, k, v)
        sys.modules["PathScripts"] = virtual_mod
    else:
        virtual_mod = existing_mod

    # 3. If modern CAM is available, pre-populate sys.modules with redirected modules
    # so subsequent imports resolve in O(1) time without finders or exception overhead
    if mode == "modern":
        for legacy_name, modern_target in _PATHSCRIPTS_REDIRECTS.items():
            full_legacy_name = f"PathScripts.{legacy_name}"
            if full_legacy_name not in sys.modules:
                try:
                    mod = sys.modules.get(modern_target)
                    if mod is None:
                        mod = importlib.import_module(modern_target)
                    sys.modules[full_legacy_name] = mod
                    setattr(virtual_mod, legacy_name, mod)
                except Exception:
                    pass

    _installed = True
    logger.info("PathScripts backward-compatibility import bridge installed (mode=%s)", mode)
    return mode


def get_op_create(op_name: str):
    """Return the Create callable for the given CAM operation.

    Checks active sys.modules first (respecting unit test mocks), then cached
    factories, and falls back to importing candidate modules.
    """
    op_key = op_name.lower()
    candidates = _OP_MODULE_MAP.get(
        op_key,
        (f"Path.Op.{op_name.capitalize()}", f"PathScripts.Path{op_name.capitalize()}")
    )

    # 1. Check sys.modules first (picks up active modules and unit test mocks)
    for mod_name in candidates:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "Create"):
            return getattr(mod, "Create")

    # 2. Check cached factory
    if op_key in _RESOLVED_OP_FACTORIES:
        return _RESOLVED_OP_FACTORIES[op_key]

    # 3. Import candidate modules
    for mod_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, "Create", None)
            if fn is not None:
                _RESOLVED_OP_FACTORIES[op_key] = fn
                return fn
        except Exception:
            continue

    raise ImportError(f"Path (CAM) operation module for '{op_name}' not available")


def get_job_create():
    """Return the Create callable for CAM Job."""
    candidates = ("Path.Main.Job", "PathScripts.PathJob")
    for mod_name in candidates:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "Create"):
            return getattr(mod, "Create")
    for mod_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, "Create", None)
            if fn is not None:
                return fn
        except Exception:
            continue
    raise ImportError("Path (CAM) module not available. Please install FreeCAD with CAM workbench support.")


def get_job_viewprovider():
    """Return the Job ViewProvider class if available in GUI mode."""
    candidates = ("Path.Main.Gui.Job", "PathScripts.PathJobGui")
    for mod_name in candidates:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "ViewProvider"):
            return getattr(mod, "ViewProvider")
    for mod_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
            vp = getattr(mod, "ViewProvider", None)
            if vp is not None:
                return vp
        except Exception:
            continue
    return None


def get_stock_factories() -> Tuple[Any, Any, Any]:
    """Return (CreateBox, CreateCylinder, CreateFromBase) for CAM Stock."""
    candidates = ("Path.Main.Stock", "PathScripts.PathStock")
    for mod_name in candidates:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "CreateBox"):
            return getattr(mod, "CreateBox"), getattr(mod, "CreateCylinder", None), getattr(mod, "CreateFromBase", None)
    for mod_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "CreateBox"):
                return getattr(mod, "CreateBox"), getattr(mod, "CreateCylinder", None), getattr(mod, "CreateFromBase", None)
        except Exception:
            continue
    raise ImportError("Path (CAM) Stock module not available")
