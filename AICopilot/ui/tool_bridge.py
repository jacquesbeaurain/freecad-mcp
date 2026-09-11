# Direct In-Memory Tool Bridge for FreeCAD
# Copyright (c) 2026
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Executes CAD tools directly within FreeCAD's Python runtime without sockets,
# IPC serialization, or writing temporary script files to disk.

import json
import logging
from typing import Any, Dict, List, Optional

import FreeCAD

if FreeCAD.GuiUp:
    import FreeCADGui
else:
    FreeCADGui = None

logger = logging.getLogger("AICopilot.ToolBridge")

# Tools that modify document geometry and should be wrapped in an undo transaction
MUTATING_TOOLS = {
    "partdesign_operations",
    "sketch_operations",
    "part_operations",
    "cam_operations",
    "cam_tools",
    "cam_tool_controllers",
    "spreadsheet_operations",
    "varset_operations",
    "draft_operations",
    "mesh_operations",
    "assembly_operations",
    "fixture_operations",
    "build_sketch",
    "execute_python",
}


class DirectToolBridge:
    """Dispatches tool calls directly to AICopilot handlers in memory."""

    def __init__(self, server=None):
        self._server = server
        self._turn_active = False
        self._turn_label = ""
        self._in_turn_transaction = False
        self._turn_doc = None

    def begin_turn_transaction(self, label: str = "AI Copilot Turn"):
        """Opens a single atomic undo transaction for the entire user request."""
        self._turn_active = True
        self._turn_label = label
        doc = FreeCAD.ActiveDocument
        if doc and not self._in_turn_transaction:
            try:
                doc.openTransaction(f"AI: {label[:40]}")
                self._in_turn_transaction = True
                self._turn_doc = doc
            except Exception as e:
                logger.debug(f"Could not open turn transaction: {e}")

    def commit_turn_transaction(self):
        """Commits the atomic turn transaction and recomputes the document."""
        self._turn_active = False
        if self._in_turn_transaction and self._turn_doc:
            try:
                self._turn_doc.commitTransaction()
                self._turn_doc.recompute()
                if FreeCADGui and FreeCAD.GuiUp:
                    try:
                        FreeCADGui.updateGui()
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Could not commit turn transaction: {e}")
            finally:
                self._in_turn_transaction = False
                self._turn_doc = None

    def abort_turn_transaction(self):
        """Aborts the turn transaction, cleanly restoring the document to its pre-turn state."""
        self._turn_active = False
        if self._in_turn_transaction and self._turn_doc:
            try:
                self._turn_doc.abortTransaction()
                self._turn_doc.recompute()
                if FreeCADGui and FreeCAD.GuiUp:
                    try:
                        FreeCADGui.updateGui()
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Could not abort turn transaction: {e}")
            finally:
                self._in_turn_transaction = False
                self._turn_doc = None

    def _get_server(self):
        if self._server:
            return self._server
        if hasattr(FreeCAD, "__ai_socket_server") and FreeCAD.__ai_socket_server:
            return FreeCAD.__ai_socket_server

        # Standalone initialization if socket server is not active
        try:
            from freecad_mcp_handler import FreeCADSocketServer
            self._server = FreeCADSocketServer()
            return self._server
        except Exception as e:
            logger.warning(f"Could not initialize standalone FreeCADSocketServer: {e}")
            return None

    def execute_tool(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> str:
        """Executes a tool call directly in memory on FreeCAD.ActiveDocument.

        Must be called on the FreeCAD main/GUI thread.
        """
        if args is None:
            args = {}

        server = self._get_server()
        if not server:
            return json.dumps({"error": "No active FreeCAD handler server available"})

        doc = FreeCAD.ActiveDocument
        if doc and self._turn_active and not self._in_turn_transaction:
            try:
                doc.openTransaction(f"AI: {self._turn_label[:40]}")
                self._in_turn_transaction = True
                self._turn_doc = doc
            except Exception as e:
                logger.debug(f"Could not open turn transaction: {e}")

        has_transaction = False

        # Open undo transaction if this operation mutates the document and we're not inside a turn transaction
        if doc and tool_name in MUTATING_TOOLS and not self._in_turn_transaction:
            try:
                op_label = args.get("operation") or tool_name
                doc.openTransaction(f"AI: {op_label}")
                has_transaction = True
            except Exception as e:
                logger.debug(f"Could not open transaction: {e}")

        try:
            # Direct synchronous in-memory dispatch to handler
            result_str = self._dispatch_direct(server, tool_name, args)

            # Check if result indicates an error string before committing
            is_error = False
            try:
                parsed = json.loads(result_str)
                if isinstance(parsed, dict) and "error" in parsed:
                    is_error = True
            except Exception:
                if str(result_str).startswith("Error"):
                    is_error = True

            if has_transaction and doc:
                if is_error:
                    doc.abortTransaction()
                else:
                    doc.commitTransaction()
                    doc.recompute()
                    if FreeCADGui and FreeCAD.GuiUp:
                        try:
                            FreeCADGui.updateGui()
                        except Exception:
                            pass
            elif self._in_turn_transaction and doc:
                doc.recompute()
                if FreeCADGui and FreeCAD.GuiUp:
                    try:
                        FreeCADGui.updateGui()
                    except Exception:
                        pass

            return result_str

        except Exception as exc:
            if has_transaction and doc:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
            logger.exception(f"Tool execution error in {tool_name}: {exc}")
            return json.dumps({"error": f"Tool execution failed: {exc}"})

    def _dispatch_direct(self, server, tool_name: str, args: Dict[str, Any]) -> str:
        """Invokes modular CAD handlers directly and synchronously on FreeCAD's GUI thread."""
        op = args.get("operation", "")
        if tool_name == "spatial_query":
            if not op:
                op = args.get("query_type", "")
            if not op and "normal" in args:
                op = "faces_by_normal"

        try:
            if tool_name == "partdesign_operations":
                mapping = {
                    "create_body": getattr(server.partdesign_ops, "create_body", None),
                    "additive_box": getattr(server.partdesign_ops, "additive_box", None),
                    "box": getattr(server.partdesign_ops, "additive_box", None),
                    "create_box": getattr(server.partdesign_ops, "additive_box", None),
                    "additive_cylinder": getattr(server.partdesign_ops, "additive_cylinder", None),
                    "cylinder": getattr(server.partdesign_ops, "additive_cylinder", None),
                    "create_cylinder": getattr(server.partdesign_ops, "additive_cylinder", None),
                    "additive_sphere": getattr(server.partdesign_ops, "additive_sphere", None),
                    "sphere": getattr(server.partdesign_ops, "additive_sphere", None),
                    "create_sphere": getattr(server.partdesign_ops, "additive_sphere", None),
                    "pad": getattr(server.partdesign_ops, "pad_sketch", None),
                    "revolution": getattr(server.partdesign_ops, "revolution", None),
                    "loft": getattr(server.partdesign_ops, "loft_profiles", None),
                    "sweep": getattr(server.partdesign_ops, "sweep_path", None),
                    "additive_pipe": getattr(server.partdesign_ops, "additive_pipe", None),
                    "pocket": getattr(server.partdesign_ops, "pocket", None),
                    "groove": getattr(server.partdesign_ops, "groove", None),
                    "subtractive_loft": getattr(server.partdesign_ops, "subtractive_loft", None),
                    "subtractive_sweep": getattr(server.partdesign_ops, "subtractive_sweep", None),
                    "fillet": getattr(server.partdesign_ops, "fillet_edges", None),
                    "chamfer": getattr(server.partdesign_ops, "chamfer_edges", None),
                    "draft": getattr(server.partdesign_ops, "draft_faces", None),
                    "shell": getattr(server.partdesign_ops, "shell_solid", None),
                    "thickness": getattr(server.partdesign_ops, "add_thickness", None),
                    "hole": getattr(server.partdesign_ops, "hole_wizard", None),
                    "linear_pattern": getattr(server.partdesign_ops, "linear_pattern", None),
                    "polar_pattern": getattr(server.partdesign_ops, "polar_pattern", None),
                    "mirror": getattr(server.partdesign_ops, "mirror_feature", None),
                }
                fn = mapping.get(op) or getattr(server.partdesign_ops, op, None)
                if not fn:
                    raise ValueError(f"Unknown PartDesign operation: {op}")
                res = fn(args)

            elif tool_name == "sketch_operations":
                mapping = {
                    "create_sketch": getattr(server.sketch_ops, "create_sketch", None),
                    "close_sketch": getattr(server.sketch_ops, "close_sketch", None),
                    "verify_sketch": getattr(server.sketch_ops, "verify_sketch", None),
                    "add_line": getattr(server.sketch_ops, "add_line", None),
                    "add_circle": getattr(server.sketch_ops, "add_circle", None),
                    "add_rectangle": getattr(server.sketch_ops, "add_rectangle", None),
                    "add_arc": getattr(server.sketch_ops, "add_arc", None),
                    "add_polygon": getattr(server.sketch_ops, "add_polygon", None),
                    "add_slot": getattr(server.sketch_ops, "add_slot", None),
                    "add_geometry": getattr(server.sketch_ops, "add_geometry", None),
                    "add_constraint": getattr(server.sketch_ops, "add_constraint", None),
                    "get_sketch": getattr(server.sketch_ops, "get_sketch", None),
                    "solve_sketch": getattr(server.sketch_ops, "solve_sketch", None),
                }
                fn = mapping.get(op) or getattr(server.sketch_ops, op, None)
                if not fn:
                    raise ValueError(f"Unknown Sketch operation: {op}")
                res = fn(args)

            elif tool_name == "part_operations":
                norm_op = op[7:] if op.startswith("create_") else op
                if norm_op in ("box", "cylinder", "sphere", "cone", "torus", "wedge"):
                    fn = getattr(server.primitives, f"create_{norm_op}", None)
                elif op in ("fuse", "cut", "common"):
                    fn = getattr(server.boolean_ops, f"{op}_objects", None)
                elif op in ("move", "rotate", "copy", "array"):
                    fn = getattr(server.transforms, f"{op}_object", None)
                elif op in ("extrude", "revolve", "loft", "sweep"):
                    fn = getattr(server.part_ops, op, None)
                elif op in ("mirror", "scale"):
                    fn = getattr(server.part_ops, f"{op}_object", None)
                else:
                    fn = getattr(server.part_ops, op, None)
                if not fn:
                    raise ValueError(f"Unknown Part operation: {op}")
                res = fn(args)

            elif tool_name == "spreadsheet_operations":
                sheet_op_map = {
                    "create_sheet": "create_spreadsheet",
                    "inspect_sheet": "inspect_sheet",
                    "list_cells": "inspect_sheet",
                }
                mapped_op = sheet_op_map.get(op, op)
                fn = getattr(server.spreadsheet_ops, mapped_op, None)
                if not fn:
                    raise ValueError(f"Unknown Spreadsheet operation: {op}")
                res = fn(args)

            elif tool_name in ("cam_operations", "cam_tools", "cam_tool_controllers"):
                handler = server.cam_ops if tool_name == "cam_operations" else getattr(server, tool_name)
                cam_op_map = {
                    "pocket_shape": "pocket",
                    "mill_face": "face",
                    "drill": "drilling",
                    "surface_milling": "surface",
                    "post_process": "export_gcode",
                }
                mapped_op = cam_op_map.get(op, op) if tool_name == "cam_operations" else op
                fn = getattr(handler, mapped_op, None)
                if not fn:
                    raise ValueError(f"Unknown {tool_name} operation: {op}")
                res = fn(args)

            elif tool_name == "measurement_operations":
                op_map = {
                    "bounding_box": getattr(server.measurement_ops, "get_bounding_box", None),
                    "volume": getattr(server.measurement_ops, "get_volume", None),
                    "surface_area": getattr(server.measurement_ops, "get_surface_area", None),
                    "mass_properties": getattr(server.measurement_ops, "get_mass_properties", None),
                    "center_of_mass": getattr(server.measurement_ops, "get_center_of_mass", None),
                }
                fn = op_map.get(op) or getattr(server.measurement_ops, op, None) or getattr(server.measurement_ops, f"get_{op}", None)
                if not fn:
                    raise ValueError(f"Unknown Measurement operation: {op}")
                res = fn(args)

            elif tool_name == "spatial_query":
                fn = getattr(server.spatial_ops, op, None)
                if not fn:
                    raise ValueError(f"Unknown Spatial operation: {op}")
                res = fn(args)

            elif tool_name == "assembly_operations":
                fn = getattr(server.assembly_ops, op, None)
                if not fn:
                    raise ValueError(f"Unknown Assembly operation: {op}")
                res = fn(args)

            elif tool_name == "varset_operations":
                fn = getattr(server.varset_ops, op, None)
                if not fn:
                    raise ValueError(f"Unknown VarSet operation: {op}")
                res = fn(args)

            elif tool_name == "execute_python":
                code = args.get("code", "")
                if hasattr(server.execute_python_ops, "run_code"):
                    res = server.execute_python_ops.run_code(code)
                else:
                    res = server.execute_python_ops.execute(args)

            elif tool_name == "build_sketch":
                res = server.sketch_builder_ops.build_sketch(args)

            elif tool_name == "run_inspector":
                res = server.inspector_ops.run(args)

            else:
                # Fallback to server._execute_tool
                res = server._execute_tool(tool_name, args)

            if isinstance(res, (dict, list, bool, int, float)):
                return json.dumps(res)
            return str(res)

        except Exception as e:
            logger.exception(f"Direct handler dispatch error for {tool_name}: {e}")
            return json.dumps({"error": str(e)})

    def get_tool_declarations(self) -> List[Dict[str, Any]]:
        """Returns standard FunctionDeclaration dictionaries for Gemini function calling."""
        return [
            {
                "name": "partdesign_operations",
                "description": "Create and edit PartDesign features: create_body, additive_box, additive_cylinder, additive_sphere, pad, pocket, hole, fillet, chamfer, revolution, groove, mirror, linear_pattern, polar_pattern.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_body", "additive_box", "additive_cylinder", "additive_sphere", "pad", "pocket", "hole", "fillet", "chamfer", "revolution", "groove", "mirror", "linear_pattern", "polar_pattern"],
                            "description": "PartDesign operation to perform"
                        },
                        "body_name": {"type": "string", "description": "Target PartDesign::Body object name"},
                        "name": {"type": "string", "description": "Name for the feature or body"},
                        "sketch_name": {"type": "string", "description": "Sketch to use for pad/pocket/revolution"},
                        "length": {"type": "number", "description": "Length (X) in mm for box, or extrusion length / depth for pad/pocket"},
                        "width": {"type": "number", "description": "Width (Y) in mm for box"},
                        "height": {"type": "number", "description": "Height (Z) in mm for box or cylinder"},
                        "radius": {"type": "number", "description": "Radius for cylinder, sphere, fillet or hole"},
                        "size": {"type": "number", "description": "Uniform size for cube (sets length, width, and height)"},
                        "angle": {"type": "number", "description": "Angle in degrees for revolution/groove"},
                        "reversed": {"type": "boolean", "description": "Reverse direction flag"},
                        "sub_elements": {"type": "array", "items": {"type": "string"}, "description": "Faces/edges for fillet/chamfer (e.g. ['Edge1', 'Face2'])"}
                    },
                    "required": ["operation"]
                }
            },
            {
                "name": "sketch_operations",
                "description": "Create and edit 2D parametric Sketches: create_sketch, add_geometry, add_constraint, get_sketch, solve_sketch.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_sketch", "add_geometry", "add_line", "add_circle", "add_rectangle", "add_arc", "add_polygon", "add_slot", "add_constraint", "get_sketch", "solve_sketch"],
                            "description": "Sketch operation to perform"
                        },
                        "sketch_name": {"type": "string", "description": "Name of sketch"},
                        "plane": {"type": "string", "description": "Attachment plane: 'XY', 'XZ', or 'YZ' (or 'XY_Plane', 'XZ_Plane', 'YZ_Plane')"},
                        "body_name": {"type": "string", "description": "Parent PartDesign body to attach sketch to"},
                        "geometry_type": {"type": "string", "enum": ["Line", "Circle", "Arc", "Rectangle"], "description": "Geometry type to add"},
                        "parameters": {"type": "object", "description": "Geometry parameters (e.g. start/end points, radius)"},
                        "constraint_type": {"type": "string", "description": "Constraint: Distance, DistanceX, DistanceY, Radius, Coincident, Horizontal, Vertical"},
                        "value": {"type": "number", "description": "Numerical dimension value for constraint in mm"}
                    },
                    "required": ["operation"]
                }
            },
            {
                "name": "cam_operations",
                "description": "Manage CAM (Path) jobs and CNC machining operations: create_job, profile, pocket, surface, adaptive, drilling, face, helix, export_gcode, inspect_job.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_job", "profile", "pocket", "pocket_shape", "surface", "surface_milling", "adaptive", "drilling", "drill", "face", "mill_face", "helix", "export_gcode", "inspect_job"],
                            "description": "CAM operation to perform"
                        },
                        "job_name": {"type": "string", "description": "Name of CAM Job (defaults to 'Job')"},
                        "base_object": {"type": "string", "description": "Base solid/model to machine (e.g. 'Wood', 'Body')"},
                        "model_name": {"type": "string", "description": "Alias for base_object"},
                        "tool_controller": {"type": "string", "description": "Tool controller name"},
                        "name": {"type": "string", "description": "Name for the operation"},
                        "faces": {"type": "array", "items": {"type": "string"}, "description": "List of face names (e.g. ['Face1']) to machine"},
                        "edges": {"type": "array", "items": {"type": "string"}, "description": "List of edge names to trace"},
                        "step_down": {"type": "number", "description": "Step down depth per pass in mm"},
                        "cut_mode": {"type": "string", "enum": ["Climb", "Conventional"], "description": "Milling cut direction"},
                        "step_over": {"type": "number", "description": "Step over percentage (e.g. 50)"},
                        "output_path": {"type": "string", "description": "File path for exported G-code"}
                    },
                    "required": ["operation"]
                }
            },
            {
                "name": "cam_tools",
                "description": "Manage cutting tools in FreeCAD CAM tool library: create_tool, update_tool, delete_tool, list_tools.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_tool", "update_tool", "delete_tool", "list_tools"],
                            "description": "CAM tool operation to perform"
                        },
                        "name": {"type": "string", "description": "Tool name"},
                        "shape": {"type": "string", "description": "Tool shape file (e.g. 'endmill', 'ballend', 'vbit')"},
                        "diameter": {"type": "number", "description": "Tool cutting diameter in mm"},
                        "cutting_edge_height": {"type": "number", "description": "Flute length in mm"},
                        "tool_name": {"type": "string", "description": "Name of tool to update or delete"}
                    },
                    "required": ["operation"]
                }
            },
            {
                "name": "spreadsheet_operations",
                "description": "Create and edit parametric Spreadsheets: inspect_sheet, create_sheet, set_cell, get_cell, set_alias, bind_property.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["inspect_sheet", "create_sheet", "create_spreadsheet", "set_cell", "get_cell", "set_alias", "bind_property"],
                            "description": "Spreadsheet operation to perform"
                        },
                        "sheet_name": {"type": "string", "description": "Spreadsheet object name"},
                        "cell": {"type": "string", "description": "Cell coordinate, e.g. 'A1', 'B2'"},
                        "value": {"type": "string", "description": "Value or expression to put into cell"},
                        "alias": {"type": "string", "description": "Named alias for the cell"},
                        "object_name": {"type": "string", "description": "DocumentObject name to bind property to"},
                        "property_name": {"type": "string", "description": "Property name to bind expression to"}
                    },
                    "required": ["operation"]
                }
            },
            {
                "name": "part_operations",
                "description": "CSG primitives and boolean operations: create_box, create_cylinder, create_sphere, fuse, cut, common.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_box", "create_cylinder", "create_sphere", "fuse", "cut", "common"],
                            "description": "Part operation to perform"
                        },
                        "name": {"type": "string", "description": "Name for the primitive"},
                        "length": {"type": "number", "description": "Length (X) in mm"},
                        "width": {"type": "number", "description": "Width (Y) in mm"},
                        "height": {"type": "number", "description": "Height (Z) in mm"},
                        "radius": {"type": "number", "description": "Radius in mm for cylinder or sphere"},
                        "base": {"type": "string", "description": "Base object for boolean operation"},
                        "tool": {"type": "string", "description": "Tool object to cut/fuse with base"}
                    },
                    "required": ["operation"]
                }
            },
            {
                "name": "measurement_operations",
                "description": "Measure distances, bounding boxes, areas, and volumes of geometry in the active document.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["bounding_box", "get_bounding_box", "volume", "get_volume", "surface_area", "get_surface_area", "measure_distance", "mass_properties", "center_of_mass", "count_elements", "check_solid"],
                            "description": "Measurement to perform"
                        },
                        "object_name": {"type": "string", "description": "DocumentObject name to measure"},
                        "sub_element": {"type": "string", "description": "Optional sub-element like 'Face1' or 'Edge2'"}
                    },
                    "required": ["operation"]
                }
            },
            {
                "name": "spatial_query",
                "description": "Analyze spatial relationships or query geometry elements: find top/bottom face, find faces by normal vector, list faces, interference/clearance/containment check.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "top_face", "bottom_face", "faces_by_normal", "horizontal_faces", "vertical_faces", "list_faces",
                                "interference_check", "clearance", "containment", "contains_point", "face_relationship", "batch_interference", "alignment_check"
                            ],
                            "description": "Spatial operation or face query to perform"
                        },
                        "query_type": {
                            "type": "string",
                            "enum": ["top_face", "bottom_face", "faces_by_normal", "horizontal_faces", "vertical_faces", "list_faces"],
                            "description": "Alias for operation (e.g. top_face, bottom_face, horizontal_faces)"
                        },
                        "object_name": {"type": "string", "description": "Target object name (e.g. 'Body' or 'Box')"},
                        "normal": {"type": "array", "items": {"type": "number"}, "description": "Normal vector [x, y, z] to match (for faces_by_normal)"},
                        "object1": {"type": "string", "description": "First object for interference/clearance"},
                        "object2": {"type": "string", "description": "Second object for interference/clearance"}
                    },
                    "required": ["object_name"]
                }
            },
            {
                "name": "execute_python",
                "description": "Direct Python execution escape hatch in FreeCAD's runtime environment. Captures stdout/stderr and evaluates expressions in persistent namespace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code string to execute"}
                    },
                    "required": ["code"]
                }
            }
        ]
