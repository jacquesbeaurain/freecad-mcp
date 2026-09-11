# execute_python sandbox — the documented escape hatch for anything not
# covered by a dedicated tool. Owns the persistent namespace variables
# survive across calls in (unlike macro_ops.py's per-call namespace).

import ast
import io
import json
import os
import sys
import threading
import traceback as tb_module
from typing import Any, Dict

import FreeCAD

if FreeCAD.GuiUp:
    import FreeCADGui
else:
    FreeCADGui = None

from .base import BaseHandler



# ---------------------------------------------------------------------------
# CAD Helper Utilities for execute_python
# ---------------------------------------------------------------------------

def _cad_create_box(length=100.0, width=None, height=None, body=None, name="Box"):
    """Create a parametric box/cube. If a PartDesign Body is present/specified,
    creates a PartDesign::AdditiveBox; otherwise creates a Part::Box."""
    doc = FreeCAD.ActiveDocument
    if not doc:
        doc = FreeCAD.newDocument("Model")
    if width is None:
        width = length
    if height is None:
        height = length

    target_body = None
    if body:
        target_body = doc.getObject(body) if isinstance(body, str) else body
    if not target_body:
        for obj in doc.Objects:
            if obj.TypeId == "PartDesign::Body":
                target_body = obj
                break

    if target_body:
        box = target_body.newObject("PartDesign::AdditiveBox", name)
        box.Length = float(length)
        box.Width = float(width)
        box.Height = float(height)
    else:
        box = doc.addObject("Part::Box", name)
        box.Length = float(length)
        box.Width = float(width)
        box.Height = float(height)

    doc.recompute()
    return box


def _cad_create_cylinder(radius=10.0, height=20.0, body=None, name="Cylinder"):
    """Create a cylinder. If a PartDesign Body is present, creates an AdditiveCylinder;
    otherwise creates a Part::Cylinder."""
    doc = FreeCAD.ActiveDocument
    if not doc:
        doc = FreeCAD.newDocument("Model")
    target_body = None
    if body:
        target_body = doc.getObject(body) if isinstance(body, str) else body
    if not target_body:
        for obj in doc.Objects:
            if obj.TypeId == "PartDesign::Body":
                target_body = obj
                break

    if target_body:
        cyl = target_body.newObject("PartDesign::AdditiveCylinder", name)
        cyl.Radius = float(radius)
        cyl.Height = float(height)
    else:
        cyl = doc.addObject("Part::Cylinder", name)
        cyl.Radius = float(radius)
        cyl.Height = float(height)

    doc.recompute()
    return cyl


def _cad_create_sketch(plane="XY", body=None, name="Sketch"):
    """Create a new Sketch attached to the XY, XZ, or YZ plane of a Body or document."""
    doc = FreeCAD.ActiveDocument
    if not doc:
        doc = FreeCAD.newDocument("Model")
    target_body = None
    if body:
        target_body = doc.getObject(body) if isinstance(body, str) else body
    if not target_body:
        for obj in doc.Objects:
            if obj.TypeId == "PartDesign::Body":
                target_body = obj
                break

    clean_plane = plane.upper().replace("_PLANE", "").replace("-PLANE", "").replace("PLANE", "").strip()
    if target_body:
        sketch = target_body.newObject("Sketcher::SketchObject", name)
        origin_plane = None
        for f in getattr(target_body.Origin, "OriginFeatures", []):
            if f.Name.startswith(f"{clean_plane}_Plane") or clean_plane in f.Name:
                origin_plane = f
                break
        if origin_plane:
            sketch.AttachmentSupport = [(origin_plane, "")]
            sketch.MapMode = "FlatFace"
    else:
        sketch = doc.addObject("Sketcher::SketchObject", name)
        plane_rotations = {
            'XY': (0, 0, 0, 1),
            'XZ': (1, 0, 0, 1),
            'YZ': (0, 1, 0, 1),
        }
        rot = plane_rotations.get(clean_plane, (0, 0, 0, 1))
        sketch.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), FreeCAD.Rotation(*rot))

    doc.recompute()
    return sketch


def _cad_add_rectangle(sketch, width=100.0, height=None, center=True, x=0.0, y=0.0):
    """Add a fully constrained rectangle to a sketch. If center=True, centers on (x, y).
    Uses rock-solid corner offset constraints (DistanceX/DistanceY) that never collapse."""
    import Part
    import Sketcher

    if height is None:
        height = width
    w, h = float(width), float(height)
    if center:
        x0 = float(x) - w / 2.0
        y0 = float(y) - h / 2.0
    else:
        x0 = float(x)
        y0 = float(y)

    p1 = FreeCAD.Vector(x0, y0, 0)
    p2 = FreeCAD.Vector(x0 + w, y0, 0)
    p3 = FreeCAD.Vector(x0 + w, y0 + h, 0)
    p4 = FreeCAD.Vector(x0, y0 + h, 0)

    g0 = sketch.addGeometry(Part.LineSegment(p1, p2))
    g1 = sketch.addGeometry(Part.LineSegment(p2, p3))
    g2 = sketch.addGeometry(Part.LineSegment(p3, p4))
    g3 = sketch.addGeometry(Part.LineSegment(p4, p1))

    # Coincident corners
    sketch.addConstraint(Sketcher.Constraint('Coincident', g0, 2, g1, 1))
    sketch.addConstraint(Sketcher.Constraint('Coincident', g1, 2, g2, 1))
    sketch.addConstraint(Sketcher.Constraint('Coincident', g2, 2, g3, 1))
    sketch.addConstraint(Sketcher.Constraint('Coincident', g3, 2, g0, 1))

    # Horizontal / Vertical
    sketch.addConstraint(Sketcher.Constraint('Horizontal', g0))
    sketch.addConstraint(Sketcher.Constraint('Horizontal', g2))
    sketch.addConstraint(Sketcher.Constraint('Vertical', g1))
    sketch.addConstraint(Sketcher.Constraint('Vertical', g3))

    # Corner position relative to sketch origin (DistanceX, DistanceY)
    sketch.addConstraint(Sketcher.Constraint('DistanceX', -1, 1, g0, 1, x0))
    sketch.addConstraint(Sketcher.Constraint('DistanceY', -1, 1, g0, 1, y0))

    # Dimensions
    sketch.addConstraint(Sketcher.Constraint('DistanceX', g0, 1, g0, 2, w))
    sketch.addConstraint(Sketcher.Constraint('DistanceY', g1, 1, g1, 2, h))

    doc = getattr(sketch, "Document", None)
    if doc:
        doc.recompute()
    return (g0, g1, g2, g3)


def _cad_pad_sketch(sketch, length=10.0, name="Pad", reversed=False):
    """Pad a sketch within its PartDesign Body."""
    doc = getattr(sketch, "Document", None) or FreeCAD.ActiveDocument
    body = None
    for obj in getattr(doc, "Objects", []):
        if obj.TypeId == "PartDesign::Body":
            if sketch in getattr(obj, "Group", []) or getattr(sketch, "Parent", None) == obj:
                body = obj
                break
    if not body:
        for obj in getattr(doc, "Objects", []):
            if obj.TypeId == "PartDesign::Body":
                body = obj
                break
    if not body:
        body = doc.addObject("PartDesign::Body", "Body")
        body.addObject(sketch)

    pad = body.newObject("PartDesign::Pad", name)
    pad.Profile = sketch
    pad.Length = float(length)
    if reversed:
        pad.Reversed = True
    doc.recompute()
    return pad


class ExecutePythonOpsHandler(BaseHandler):
    """Handler for execute_python: parses/execs/evals user code in a
    persistent namespace, capturing stdout and the last expression's
    value (Jupyter-like semantics)."""

    def __init__(self, server=None, log_operation=None, capture_state=None):
        super().__init__(server, log_operation, capture_state)
        # Persistent namespace for execute_python calls.
        # Variables created in one call survive to the next.
        self._python_namespace: Dict[str, Any] = {}

    def _capture_console_stderr_start(self):
        """Redirect the real OS-level stderr fd to a pipe with a background
        drain thread, so FreeCAD's own C++ Console output (PrintWarning,
        PrintError, PrintLog, PrintCritical -- and warnings FreeCAD emits
        internally as a side effect of property sets/recomputes, e.g.
        deprecation notices) gets captured instead of vanishing silently.

        Confirmed via FreeCAD's own source (FC-clone/src/Base/
        ConsoleObserver.cpp): ConsoleObserverStd::Warning/Error/Log/Critical
        write via raw fprintf(stderr, ...) at the C level, below Python's
        sys.stdout/sys.stderr -- redirecting those (as run_code already does
        for stdout) never sees it. ConsoleObserverStd is unconditionally
        attached with LoggingConsole="1" in both MainCmd.cpp (headless) and
        MainGui.cpp (GUI), confirmed in the same source tree, so this works
        in both modes. (Console.Message()/plain Msg-level output goes to
        stdout instead, along with FreeCAD's recompute() progress-bar spam
        -- deliberately NOT captured here, to avoid returning tick-spam
        noise in the response; only stderr, i.e. actually-actionable
        Warning/Error/Log/Critical output, is worth surfacing.)

        A background drain thread (not a one-shot read at the end) avoids
        the exact pipe-full deadlock class fixed in tests/integration/
        conftest.py's _PipeDrain for the same underlying reason (an
        unbounded fprintf into an unread OS pipe blocks forever once the
        64KB buffer fills) -- unlikely here since stderr should be low-
        volume, but the mechanism is identical so the same guard applies.

        Returns a state dict for _capture_console_stderr_stop, or None if
        redirection failed for any reason -- must never block or break
        code execution just because this diagnostic capture couldn't be
        set up.
        """
        try:
            read_fd, write_fd = os.pipe()
            saved_fd = os.dup(2)
            os.dup2(write_fd, 2)
            os.close(write_fd)
        except OSError:
            return None
        buf = bytearray()
        lock = threading.Lock()

        def _drain():
            try:
                while True:
                    chunk = os.read(read_fd, 4096)
                    if not chunk:
                        break
                    with lock:
                        buf.extend(chunk)
            except OSError:
                pass

        thread = threading.Thread(target=_drain, daemon=True)
        thread.start()
        return {"read_fd": read_fd, "saved_fd": saved_fd, "buf": buf, "lock": lock, "thread": thread}

    def _capture_console_stderr_stop(self, state) -> str:
        """Restore the real stderr fd and return whatever was captured."""
        if state is None:
            return ""
        try:
            # Closes the pipe's write end (fd 2 was its only remaining
            # reference -- the original write_fd number was already closed
            # in _capture_console_stderr_start), which lets the drain
            # thread's os.read() see EOF and exit.
            os.dup2(state["saved_fd"], 2)
            os.close(state["saved_fd"])
        except OSError:
            pass
        state["thread"].join(timeout=1.0)
        try:
            os.close(state["read_fd"])
        except OSError:
            pass
        with state["lock"]:
            return bytes(state["buf"]).decode("utf-8", errors="replace").strip()

    def run_code(self, code: str) -> dict:
        """Core Python execution: runs code on the GUI thread, captures stdout.

        Returns a result dict suitable for _run_on_gui_thread / _run_on_gui_thread_async.

        Uses a persistent namespace so variables survive across calls.

        Output priority:
          - stdout lines (from print() calls) are always included when present
          - the last-expression value (or `result` variable) is appended when present
          - if neither, returns "Code executed successfully"
        """
        # Ensure base modules are always available (even if user overwrites them)
        self._python_namespace["FreeCAD"] = FreeCAD
        self._python_namespace["FreeCADGui"] = FreeCADGui
        self._python_namespace["App"] = FreeCAD
        self._python_namespace["Gui"] = FreeCADGui
        try:
            import Part
            self._python_namespace["Part"] = Part
        except ImportError:
            pass
        try:
            from FreeCAD import Vector
            self._python_namespace["Vector"] = Vector
        except ImportError:
            pass
        try:
            import Sketcher
            self._python_namespace["Sketcher"] = Sketcher
        except ImportError:
            pass
        try:
            import PartDesign
            self._python_namespace["PartDesign"] = PartDesign
        except ImportError:
            pass

        # PathScripts backward compatibility & CAM namespace helpers
        try:
            import Path
            self._python_namespace["Path"] = Path
        except ImportError:
            pass
        try:
            from ..compat_pathscripts import get_job_create
        except Exception:
            try:
                from compat_pathscripts import get_job_create
            except Exception:
                get_job_create = None

        if get_job_create is not None:
            try:
                self._python_namespace["CreateJob"] = get_job_create()
            except Exception:
                pass
        self._python_namespace["PathJob"] = sys.modules.get("Path.Main.Job") or sys.modules.get("PathScripts.PathJob")

        # Ensure doc is readily available
        if FreeCAD.ActiveDocument:
            self._python_namespace["doc"] = FreeCAD.ActiveDocument

        # Pre-loaded CAD helper functions
        self._python_namespace["create_box"] = _cad_create_box
        self._python_namespace["create_cylinder"] = _cad_create_cylinder
        self._python_namespace["create_sketch"] = _cad_create_sketch
        self._python_namespace["add_rectangle"] = _cad_add_rectangle
        self._python_namespace["pad_sketch"] = _cad_pad_sketch
        self._python_namespace["recompute"] = lambda: FreeCAD.ActiveDocument.recompute() if FreeCAD.ActiveDocument else None

        namespace = self._python_namespace

        # Auto-save active document before executing user code (if enabled in settings).
        # Default is False to prevent unwanted overwrites of user project files.
        try:
            try:
                from ..settings import get_setting
            except (ImportError, ValueError):
                try:
                    from AICopilot.settings import get_setting
                except (ImportError, ValueError):
                    from settings import get_setting
            if get_setting('auto_save_on_execute', False):
                doc = FreeCAD.ActiveDocument
                if doc and getattr(doc, 'FileName', ''):
                    doc.save()
        except Exception:
            pass  # non-fatal; proceed with execution

        result_value = None
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        console_stderr_state = self._capture_console_stderr_start()
        try:
            try:
                tree = ast.parse(code)
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    # Execute all statements except the last
                    if len(tree.body) > 1:
                        exec_module = ast.Module(body=tree.body[:-1], type_ignores=[])
                        ast.fix_missing_locations(exec_module)
                        exec(compile(exec_module, "<string>", "exec"), namespace)
                    # Evaluate the last expression
                    expr_ast = ast.Expression(body=tree.body[-1].value)
                    ast.fix_missing_locations(expr_ast)
                    result_value = eval(compile(expr_ast, "<string>", "eval"), namespace)
                else:
                    exec(code, namespace)
                    if "result" in namespace:
                        result_value = namespace["result"]
            except SyntaxError as e:
                err_id = self.server.diagnostics_ops.store_traceback(tb_module.format_exc()) if self.server and hasattr(self.server, "diagnostics_ops") else None
                return {"success": False, "error": f"SyntaxError: {e}", "error_id": err_id}
        except Exception as e:
            err_id = self.server.diagnostics_ops.store_traceback(tb_module.format_exc()) if self.server and hasattr(self.server, "diagnostics_ops") else None
            return {"success": False, "error": f"Python execution error: {e}", "error_id": err_id}
        finally:
            sys.stdout = old_stdout
            console_stderr = self._capture_console_stderr_stop(console_stderr_state)

        stdout_output = captured.getvalue().rstrip("\n")
        parts = []
        if stdout_output:
            parts.append(stdout_output)
        if console_stderr:
            parts.append(f"[FreeCAD Console]\n{console_stderr}")
        if result_value is not None:
            parts.append(repr(result_value))

        # Validate geometry health post-execution
        fc = sys.modules.get("FreeCAD", FreeCAD)
        doc = getattr(fc, "ActiveDocument", None)
        geom_errors = []
        if doc and hasattr(doc, "Objects"):
            try:
                doc.recompute()
            except Exception as e:
                geom_errors.append(f"Document recompute failed: {e}")

            for obj in doc.Objects:
                try:
                    # 1. Check object state
                    states = getattr(obj, "State", [])
                    if "Invalid" in states or "Error" in states:
                        geom_errors.append(f"Object '{obj.Name}' ({obj.TypeId}) is in error state: {states}")

                    # 2. Check sketch solve status
                    if hasattr(obj, "isDerivedFrom") and obj.isDerivedFrom("Sketcher::SketchObject"):
                        solve_status = obj.solve()
                        if solve_status < 0:
                            status_desc = {
                                -1: "Empty sketch",
                                -2: "Conflicting / inconsistent constraints",
                                -3: "Redundant constraints",
                                -4: "Over-constrained or mathematically degenerate",
                            }.get(solve_status, f"Solve error code {solve_status}")
                            geom_errors.append(
                                f"Sketch '{obj.Name}' has invalid constraints ({status_desc}). "
                                f"Check coincident, horizontal/vertical, or symmetric constraints."
                            )

                    # 3. Check for NULL shapes on 3D features
                    if hasattr(obj, "Shape"):
                        type_id = getattr(obj, "TypeId", "")
                        is_feature = any(t in type_id for t in ("PartDesign::", "Part::Box", "Part::Cylinder", "Part::Sphere", "Part::Feature"))
                        if is_feature and not (hasattr(obj, "isDerivedFrom") and obj.isDerivedFrom("Sketcher::SketchObject")):
                            try:
                                shape = obj.Shape
                                if shape.isNull():
                                    geom_errors.append(f"Object '{obj.Name}' ({type_id}) produced a NULL shape (0 faces).")
                                elif hasattr(shape, "Faces") and len(shape.Faces) == 0:
                                    geom_errors.append(f"Object '{obj.Name}' ({type_id}) produced a zero-faced shape.")
                            except Exception as e:
                                geom_errors.append(f"Object '{obj.Name}' shape error: {e}")
                except Exception:
                    pass

        if geom_errors:
            err_msg = "Geometry validation failed:\n" + "\n".join(f"• {e}" for e in geom_errors)
            err_msg += (
                "\n\nRecommendation: Ensure sketch profiles are closed and not over-constrained. "
                "For a solid cube/box in PartDesign, use body.newObject('PartDesign::AdditiveBox', 'Box') "
                "or the built-in create_box() helper."
            )
            if parts:
                err_msg = f"{parts[0]}\n\n{err_msg}"
            return {"success": False, "error": err_msg}

        if parts:
            return {"success": True, "result": "\n".join(parts)}
        return {"success": True, "result": "Code executed successfully"}

    def execute(self, args: Dict[str, Any]) -> str:
        """Execute Python code in FreeCAD context with expression value capture (GUI-safe).

        Handles both statements and expressions, returning the value
        of the last expression if present (similar to IPython/Jupyter behavior).

        Examples:
            "1 + 1"                    -> "2"
            "x = 5"                    -> "Code executed successfully"
            "x = 5\\nx * 2"            -> "10"
            "FreeCAD.ActiveDocument"   -> "<Document object>"
            "result = 42"              -> "42" (explicit result variable)
        """
        code = args.get("code", "")
        if not code:
            return json.dumps({"error": "No code provided"})

        timeout = args.get("timeout", 30.0)
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            timeout = 30.0

        return self.run_on_gui_thread(lambda: self.run_code(code), timeout=timeout)
