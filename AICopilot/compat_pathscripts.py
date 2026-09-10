"""CAM module compatibility redirector for FreeCAD 1.0+ and development builds.

In FreeCAD 1.0+, the CAM (formerly Path) workbench underwent a major namespace
refactor: legacy modules under PathScripts (e.g. PathScripts.PathJob,
PathScripts.PathProfile, PathScripts.PathPocket, PathScripts.PathToolBit)
were relocated to Path.Main.Job, Path.Op.Profile, Path.Op.Pocket, Path.Tool.Bit, etc.

Additionally, intuitive operation names (e.g. `Path.Op.Face` instead of `MillFace`,
`Path.Op.Drill` instead of `Drilling`, `Path.Job` instead of `Path.Main.Job`)
frequently occur in LLM-generated code, macros, and user scripts.

This module installs a sys.meta_path finder, pre-populates sys.modules,
and binds attribute fallbacks on Path, Path.Op, and PathScripts so that
legacy imports and intuitive aliases resolve transparently and instantly
in O(1) time without exceptions or disk lookups, while preserving any
native on-disk modules (like PathScripts.PathUtils).
"""

import importlib
import importlib.machinery
import importlib.util
import logging
import sys
import types
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

# Complete mapping of CAM module redirects (source full module path -> target full module path)
_CAM_MODULE_REDIRECTS = {
    # --- Path.Op aliases and intuitive operation names ---
    "Path.Op.Face": "Path.Op.MillFace",
    "Path.Op.Facing": "Path.Op.MillFace",
    "Path.Op.Drill": "Path.Op.Drilling",
    "Path.Op.DrillHoles": "Path.Op.Drilling",
    "Path.Op.Pocketing": "Path.Op.Pocket",
    "Path.Op.Profiling": "Path.Op.Profile",
    "Path.Op.Contour": "Path.Op.Profile",
    "Path.Op.Contouring": "Path.Op.Profile",
    "Path.Op.SurfaceMilling": "Path.Op.Surface",
    "Path.Op.Surface3D": "Path.Op.Surface",
    "Path.Op.Pocket3D": "Path.Op.Surface",
    "Path.Op.Thread": "Path.Op.ThreadMilling",
    "Path.Op.Threading": "Path.Op.ThreadMilling",
    "Path.Op.Helical": "Path.Op.Helix",
    "Path.Op.Slotting": "Path.Op.Slot",
    "Path.Op.Engraving": "Path.Op.Engrave",
    "Path.Op.Deburring": "Path.Op.Deburr",

    # --- Path root shortcuts ---
    "Path.Job": "Path.Main.Job",
    "Path.JobGui": "Path.Main.Gui.Job",
    "Path.Stock": "Path.Main.Stock",
    "Path.ToolBit": "Path.Tool.Bit",
    "Path.ToolController": "Path.Tool.Controller",
    "Path.Controller": "Path.Tool.Controller",
    "Path.PostProcessor": "Path.Post.Processor",
    "Path.Profile": "Path.Op.Profile",
    "Path.Pocket": "Path.Op.Pocket",
    "Path.Drilling": "Path.Op.Drilling",
    "Path.Drill": "Path.Op.Drilling",
    "Path.MillFace": "Path.Op.MillFace",
    "Path.Face": "Path.Op.MillFace",
    "Path.Facing": "Path.Op.MillFace",
    "Path.Surface": "Path.Op.Surface",
    "Path.Adaptive": "Path.Op.Adaptive",
    "Path.Helix": "Path.Op.Helix",
    "Path.Slot": "Path.Op.Slot",
    "Path.Engrave": "Path.Op.Engrave",
    "Path.Deburr": "Path.Op.Deburr",
    "Path.Vcarve": "Path.Op.Vcarve",
    "Path.Waterline": "Path.Op.Waterline",

    # --- Legacy PathScripts redirects ---
    "PathScripts.PathJob": "Path.Main.Job",
    "PathScripts.PathJobGui": "Path.Main.Gui.Job",
    "PathScripts.PathStock": "Path.Main.Stock",
    "PathScripts.PathProfile": "Path.Op.Profile",
    "PathScripts.PathPocket": "Path.Op.Pocket",
    "PathScripts.PathPocketShape": "Path.Op.PocketShape",
    "PathScripts.PathDrilling": "Path.Op.Drilling",
    "PathScripts.PathDrill": "Path.Op.Drilling",
    "PathScripts.PathAdaptive": "Path.Op.Adaptive",
    "PathScripts.PathSurface": "Path.Op.Surface",
    "PathScripts.PathSurfaceMilling": "Path.Op.Surface",
    "PathScripts.PathHelix": "Path.Op.Helix",
    "PathScripts.PathMillFace": "Path.Op.MillFace",
    "PathScripts.PathMillFacing": "Path.Op.MillFacing",
    "PathScripts.PathFace": "Path.Op.MillFace",
    "PathScripts.PathFacing": "Path.Op.MillFace",
    "PathScripts.PathSlot": "Path.Op.Slot",
    "PathScripts.PathEngrave": "Path.Op.Engrave",
    "PathScripts.PathVcarve": "Path.Op.Vcarve",
    "PathScripts.PathDeburr": "Path.Op.Deburr",
    "PathScripts.PathWaterline": "Path.Op.Waterline",
    "PathScripts.PathToolBit": "Path.Tool.Bit",
    "PathScripts.PathToolController": "Path.Tool.Controller",
    "PathScripts.PathPost": "Path.Post.Command",
    "PathScripts.PathPreferences": "Path.Preferences",
    "PathScripts.PathLog": "Path.Log",
    "PathScripts.PathGeom": "Path.Geom",
}

# Legacy dictionary alias for backward compatibility
_PATHSCRIPTS_REDIRECTS = {
    k.split(".", 1)[1]: v for k, v in _CAM_MODULE_REDIRECTS.items() if k.startswith("PathScripts.")
}

# Mapping of CAM operation names to candidate module paths (modern, fallbacks, legacy)
_OP_MODULE_MAP = {
    "profile": ("Path.Op.Profile", "PathScripts.PathProfile"),
    "pocket": ("Path.Op.Pocket", "PathScripts.PathPocket"),
    "pocket_shape": ("Path.Op.PocketShape", "PathScripts.PathPocketShape"),
    "drilling": ("Path.Op.Drilling", "Path.Op.Drill", "PathScripts.PathDrilling"),
    "drill": ("Path.Op.Drilling", "Path.Op.Drill", "PathScripts.PathDrilling"),
    "adaptive": ("Path.Op.Adaptive", "PathScripts.PathAdaptive"),
    "face": ("Path.Op.MillFace", "Path.Op.Face", "Path.Op.MillFacing", "PathScripts.PathMillFace"),
    "mill_face": ("Path.Op.MillFace", "Path.Op.Face", "Path.Op.MillFacing", "PathScripts.PathMillFace"),
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
        if hasattr(sys.modules["PathScripts"], "PathJob"):
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


class _RedirectLoader:
    def __init__(self, target_name):
        self.target_name = target_name

    def create_module(self, spec):
        return sys.modules.get(self.target_name) or importlib.import_module(self.target_name)

    def exec_module(self, module):
        pass


class CAMModuleCompatFinder:
    """PEP 302/451 meta-path finder that intercepts CAM module imports across
    Path.Op.*, Path.*, and PathScripts.* to resolve aliases and legacy namespaces."""

    @classmethod
    def find_spec(cls, fullname: str, path=None, target=None):
        target_mod = _CAM_MODULE_REDIRECTS.get(fullname)
        if target_mod:
            # If target module is already loaded in sys.modules, return spec immediately
            if target_mod in sys.modules:
                from importlib.machinery import ModuleSpec
                return ModuleSpec(fullname, _RedirectLoader(target_mod), origin=target_mod)
            try:
                spec = importlib.util.find_spec(target_mod)
                if spec:
                    return spec
            except Exception as e:
                logger.debug("Failed to find spec for redirect %s -> %s: %s", fullname, target_mod, e)
        return None


# Backward-compatible alias for finder class
PathScriptsCompatFinder = CAMModuleCompatFinder


class _VirtualPathScriptsPackage(types.ModuleType):
    """Virtual package module for PathScripts allowing attribute access like
    `from PathScripts import PathJob` while permitting resolution of native files."""

    def __getattr__(self, name: str):
        target = _CAM_MODULE_REDIRECTS.get(f"PathScripts.{name}")
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

        # Fall back to trying to load real submodules from disk (e.g. PathUtils, PathPropertyBag)
        try:
            mod = importlib.import_module(f"PathScripts.{name}")
            setattr(self, name, mod)
            return mod
        except Exception:
            pass

        raise AttributeError(f"module 'PathScripts' has no attribute '{name}'")


class _AliasedPackageModule(types.ModuleType):
    """Package wrapper that resolves aliased submodules on attribute access
    (e.g. `Path.Op.Face` or `Path.Job`)."""

    def __getattr__(self, name: str):
        fullname = f"{self.__name__}.{name}"
        target = _CAM_MODULE_REDIRECTS.get(fullname)
        if target:
            try:
                mod = sys.modules.get(target)
                if mod is None:
                    mod = importlib.import_module(target)
                setattr(self, name, mod)
                sys.modules[fullname] = mod
                return mod
            except Exception as e:
                logger.warning("Failed to import redirected alias %s -> %s: %s", fullname, target, e)
        raise AttributeError(f"module '{self.__name__}' has no attribute '{name}'")


def _wrap_package_with_alias_support(package_name: str):
    """Attach alias support to an already-imported package module (e.g. Path or Path.Op)."""
    pkg = sys.modules.get(package_name)
    if pkg is not None and not isinstance(pkg, _AliasedPackageModule):
        try:
            pkg.__class__ = _AliasedPackageModule
        except Exception:
            pass


def install_pathscripts_compat() -> str:
    """Install the CAM and PathScripts backward compatibility import hooks and pre-populate sys.modules."""
    global _installed
    mode = detect_cam_environment()
    if _installed:
        return mode

    # 1. Register meta-path finder if not already present
    if not any(isinstance(finder, type) and finder.__name__ in ("CAMModuleCompatFinder", "PathScriptsCompatFinder") for finder in sys.meta_path):
        sys.meta_path.insert(0, CAMModuleCompatFinder)

    # 2. Get or import real PathScripts module if present on disk
    real_mod = sys.modules.get("PathScripts")
    if real_mod is None:
        try:
            real_mod = importlib.import_module("PathScripts")
        except Exception:
            pass

    real_paths = []
    if real_mod and hasattr(real_mod, "__path__"):
        real_paths = list(real_mod.__path__)
    else:
        try:
            spec = importlib.machinery.PathFinder.find_spec("PathScripts")
            if spec and spec.submodule_search_locations:
                real_paths = list(spec.submodule_search_locations)
        except Exception:
            pass

    if real_mod is not None:
        real_mod.__class__ = _VirtualPathScriptsPackage
        virtual_mod = real_mod
    else:
        virtual_mod = _VirtualPathScriptsPackage("PathScripts")
        virtual_mod.__doc__ = "Compatibility bridge for legacy FreeCAD PathScripts imports"
        virtual_mod.__path__ = real_paths
        sys.modules["PathScripts"] = virtual_mod

    if not getattr(virtual_mod, "__path__", None) and real_paths:
        virtual_mod.__path__ = real_paths

    # 3. If modern CAM is available, pre-populate sys.modules with all redirected modules
    # across Path.Op.*, Path.*, and PathScripts.* so subsequent imports resolve in O(1) time
    if mode == "modern":
        # Wrap Path and Path.Op with alias support if loaded
        _wrap_package_with_alias_support("Path")
        _wrap_package_with_alias_support("Path.Op")

        for source_alias, modern_target in _CAM_MODULE_REDIRECTS.items():
            if source_alias not in sys.modules:
                try:
                    mod = sys.modules.get(modern_target)
                    if mod is None:
                        mod = importlib.import_module(modern_target)
                    sys.modules[source_alias] = mod
                    # Bind attribute to parent package if available
                    if "." in source_alias:
                        parent_name, attr_name = source_alias.rsplit(".", 1)
                        parent_mod = sys.modules.get(parent_name)
                        if parent_mod is not None:
                            setattr(parent_mod, attr_name, mod)
                except Exception:
                    pass

    _installed = True
    logger.info("CAM module compatibility & alias bridge installed (mode=%s)", mode)
    return mode


# General alias for install function
install_cam_compat = install_pathscripts_compat


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
    candidates = ("Path.Main.Job", "Path.Job", "PathScripts.PathJob")
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
    candidates = ("Path.Main.Gui.Job", "Path.JobGui", "PathScripts.PathJobGui")
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
    candidates = ("Path.Main.Stock", "Path.Stock", "PathScripts.PathStock")
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
