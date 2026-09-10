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
        has_transaction = False

        # Open undo transaction if this operation mutates the document
        if doc and tool_name in MUTATING_TOOLS:
            try:
                op_label = args.get("operation") or tool_name
                doc.openTransaction(f"AI: {op_label}")
                has_transaction = True
            except Exception as e:
                logger.debug(f"Could not open transaction: {e}")

        try:
            # Direct in-memory dispatch to handler
            result_str = server._execute_tool(tool_name, args)

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

            return result_str

        except Exception as exc:
            if has_transaction and doc:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
            logger.exception(f"Tool execution error in {tool_name}: {exc}")
            return json.dumps({"error": f"Tool execution failed: {exc}"})

    def get_tool_declarations(self) -> List[Dict[str, Any]]:
        """Returns standard FunctionDeclaration dictionaries for Gemini function calling."""
        return [
            {
                "name": "partdesign_operations",
                "description": "Create and edit PartDesign features: create_body, pad, pocket, hole, fillet, chamfer, revolution, groove, mirror, linear_pattern, polar_pattern.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_body", "pad", "pocket", "hole", "fillet", "chamfer", "revolution", "groove", "mirror", "linear_pattern", "polar_pattern"],
                            "description": "PartDesign operation to perform"
                        },
                        "body_name": {"type": "string", "description": "Target PartDesign::Body object name"},
                        "sketch_name": {"type": "string", "description": "Sketch to use for pad/pocket/revolution"},
                        "length": {"type": "number", "description": "Length / depth in mm for pad or pocket"},
                        "radius": {"type": "number", "description": "Radius for fillet or hole"},
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
                            "enum": ["create_sketch", "add_geometry", "add_constraint", "get_sketch", "solve_sketch"],
                            "description": "Sketch operation to perform"
                        },
                        "sketch_name": {"type": "string", "description": "Name of sketch"},
                        "plane": {"type": "string", "description": "Attachment plane: XY_Plane, XZ_Plane, YZ_Plane"},
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
                "description": "Manage CAM (Path) jobs and operations: create_job, profile, pocket_shape, mill_face, adaptive, drill, helix, export_gcode, repair_cam_tree.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_job", "profile", "pocket_shape", "mill_face", "adaptive", "drill", "helix", "export_gcode", "repair_cam_tree", "inspect_job"],
                            "description": "CAM operation to perform"
                        },
                        "job_name": {"type": "string", "description": "Name of CAM Job (defaults to 'Job')"},
                        "model_name": {"type": "string", "description": "Base solid/model to machine"},
                        "tool_controller": {"type": "string", "description": "Tool controller name"},
                        "name": {"type": "string", "description": "Name for the operation"},
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
                "description": "Create and edit parametric Spreadsheets: create_sheet, set_cell, get_cell, set_alias, bind_property.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_sheet", "set_cell", "get_cell", "set_alias", "bind_property"],
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
                            "enum": ["measure_distance", "bounding_box", "volume", "surface_area"],
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
                "description": "Query geometry elements by spatial attributes: find faces by normal vector, find highest/lowest faces, find edges by length.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "object_name": {"type": "string", "description": "Target object name"},
                        "query_type": {
                            "type": "string",
                            "enum": ["faces_by_normal", "top_face", "bottom_face", "horizontal_faces", "vertical_faces"],
                            "description": "Type of spatial query"
                        },
                        "normal": {"type": "array", "items": {"type": "number"}, "description": "Normal vector [x, y, z] to match"}
                    },
                    "required": ["object_name", "query_type"]
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
