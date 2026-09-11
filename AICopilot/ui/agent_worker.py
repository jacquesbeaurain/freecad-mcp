# Background AI Agent Worker for FreeCAD
# Copyright (c) 2026
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Runs Google Gemini agent loops asynchronously in a secondary QThread,
# streaming tokens to the UI and safely marshaling CAD tool executions
# to FreeCAD's main GUI thread.

import html
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

try:
    from PySide6 import QtCore
except ImportError:
    from PySide import QtCore

import FreeCAD

from .tool_bridge import DirectToolBridge

logger = logging.getLogger("AICopilot.AgentWorker")

FALLBACK_MODEL = "gemini-3.6-flash"

SYSTEM_INSTRUCTION = """You are FreeCAD AI Copilot, an embedded assistant inside FreeCAD.
Your role is to assist the user with 3D mechanical CAD modeling, parametric design, 2D sketching, CAM (Path) CNC toolpaths, Draft, and Spreadsheets.

GUIDELINES:
1. Parametric Design: Use parametric features whenever possible. For dimensions, favor referencing expressions, named constraints, or Spreadsheets.
2. 3D Selection Context: The user may select faces, edges, vertices, or bodies in FreeCAD's 3D viewport. When a selection context is provided (e.g. [Selected: Box.Face1]), use that exact geometry for pads, pockets, fillets, chamfers, or toolpath boundaries.
3. Clean Document Trees: Avoid creating orphaned features. For PartDesign features (pads, pockets, holes), ensure they reside inside the appropriate PartDesign::Body.
4. Tool Calling: You have access to native FreeCAD tools (partdesign_operations, sketch_operations, cam_operations, cam_tools, spreadsheet_operations, part_operations, measurement_operations, spatial_query, and execute_python). Invoke these tools to inspect and modify the model directly.
   - For PartDesign primitives: Use `partdesign_operations(operation="additive_box", length=100, width=100, height=100)` or `additive_cylinder`, `additive_sphere`.
   - For Part CSG primitives: Use `part_operations(operation="create_box", length=100, width=100, height=100)` or `create_cylinder`, `create_sphere`.
   - For Parametric Spreadsheets: ALWAYS prefer `spreadsheet_operations` over raw scripting!
     • Inspect all cells, aliases, formulas, and values in 1 step: `spreadsheet_operations(operation="inspect_sheet")`.
     • Set cell: `spreadsheet_operations(operation="set_cell", cell="B4", value="12.7 mm")`.
     • Set alias: `spreadsheet_operations(operation="set_alias", cell="B4", alias="BitDiameter")`.
     • Object Expressions: In FreeCAD Python, parametric expressions on document objects reside in `obj.ExpressionEngine` (a list of `(property_name, expression_string)` tuples), NOT `obj.Expressions`.
   - For CAM (CNC) Operations: ALWAYS prefer `cam_operations` and `cam_tools` over raw scripting!
     • Create Job: `cam_operations(operation="create_job", base_object="<model_name>")` (e.g. base_object="Wood").
     • Facing / Jointing: `cam_operations(operation="face", job_name="Job", base_object="<model_name>", faces=["<top_face>"], cut_mode="Climb", step_over=50, step_down=0.5, clear_edges=True)`.
       Note: For facing/jointing narrow stock, `clear_edges=True` is vital so the cutter clears the stock boundary.
     • Add Operations: `cam_operations(operation="surface", job_name="Job")` for 3D surfacing, `operation="profile"` for contours, `operation="pocket"` for pockets, `operation="drilling"` for holes.
     • Tool Library: `cam_tools(operation="create_tool", name="<tool_name>", tool_type="endmill", diameter=12.7, cutting_edge_height=25.0)`.
     • In FreeCAD 1.0+, CAM modules live under `Path.Main.Job` and `Path.Op.*` (do not import legacy `PathScripts`).
5. Python Scripting Rules (execute_python):
   - Built-in CAD Helpers: execute_python includes pre-loaded namespace helpers for clean 1-step geometry:
     • `create_box(length, width=None, height=None, body=None, name="Box")`: Creates a valid solid box/cube inside a PartDesign Body if present, or a Part::Box.
     • `create_cylinder(radius, height, body=None, name="Cylinder")`: Creates an AdditiveCylinder inside a Body or Part::Cylinder.
     • `create_sketch(plane="XY", body=None)`: Creates a properly attached sketch on the specified plane.
     • `add_rectangle(sketch, width, height, center=True)`: Adds a fully constrained, non-collapsing rectangle.
     • `pad_sketch(sketch, length)`: Extrudes a sketch into a solid Pad inside its Body.
   - PartDesign Additive Primitives: Inside a PartDesign Body, prefer 1-step additive primitives:
     `box = body.newObject("PartDesign::AdditiveBox", "Box"); box.Length = 100; box.Width = 100; box.Height = 100; doc.recompute()`.
   - Part CSG Primitives: In Part workbench, use:
     `box = doc.addObject("Part::Box", "Box"); box.Length = 100; box.Width = 100; box.Height = 100; doc.recompute()`.
   - CRITICAL SKETCHER SYMMETRY RULE: NEVER place a `Symmetric` constraint on endpoints of a horizontal line across the horizontal axis (axis -1), or a vertical line across the vertical axis (axis -2). Doing so mathematically forces the coordinate to 0 and collapses all sketch lines to a degenerate 0-length point at the origin, producing a broken NULL shape! Instead, constrain position using corner offsets (`DistanceX`, `DistanceY` to origin) or use `add_rectangle(sketch, width, height, center=True)`.
6. Conciseness: Keep explanations clear, practical, and focused on CAD geometry.
7. Efficiency & Decisiveness: When creating features from scratch, execute decisively. Always verify that features recompute into valid solids (Shape.isValid() and not Shape.isNull()).
8. Plain Markdown Formatting: NEVER output LaTeX math markup (such as `$X$`, `$$...$$`, `\text{...}`, or `\times`). FreeCAD's chat interface displays standard CommonMark Markdown without LaTeX rendering. Always format coordinates, bounding boxes, dimensions, and units in clean plain text or standard Markdown (e.g. `X: 0.00 mm to 100.00 mm (length: 100.00 mm)`).
"""


class ToolCallRequest:
    """Thread-safe synchronization container for main-thread tool execution."""

    def __init__(self, tool_name: str, args: Dict[str, Any]):
        self.tool_name = tool_name
        self.args = args
        self.result: Optional[str] = None
        self.exception: Optional[Exception] = None
        self.event = threading.Event()

    def wait(self, timeout: float = 60.0) -> bool:
        return self.event.wait(timeout)

    def set_result(self, result: str):
        self.result = result
        self.event.set()

    def set_exception(self, exc: Exception):
        self.exception = exc
        self.event.set()


class CopilotAgentWorker(QtCore.QThread):
    """Background QThread that drives Gemini conversational turns and function calling."""

    # Qt Signals for GUI updates
    sig_thought = QtCore.Signal(str)
    sig_token = QtCore.Signal(str)
    sig_status = QtCore.Signal(str)
    sig_tool_started = QtCore.Signal(str, dict)
    sig_tool_finished = QtCore.Signal(str, str)
    sig_turn_complete = QtCore.Signal(str, dict)
    sig_error = QtCore.Signal(str)
    sig_request_main_thread_tool = QtCore.Signal(object)

    def __init__(
        self,
        tool_bridge: DirectToolBridge,
        model_name: str = "gemini-3.6-flash",
        api_key: Optional[str] = None,
        parent: Optional[QtCore.QObject] = None,
    ):
        super().__init__(parent)
        self.tool_bridge = tool_bridge
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._stop_requested = False

        # Queue for incoming prompts: (user_prompt, selection_context)
        self._prompt_queue: List[Dict[str, Any]] = []
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()

        # Multi-turn conversational history: list of Content or dicts
        self.history: List[Any] = []

    def set_api_key(self, api_key: str):
        self.api_key = api_key

    def set_model_name(self, model_name: str):
        if model_name:
            clean = model_name.strip()
            if clean.startswith("models/"):
                clean = clean[len("models/"):]
            self.model_name = clean

    def clear_history(self):
        with self._queue_lock:
            self.history.clear()
        self.sig_status.emit("History cleared")

    def submit_prompt(self, user_prompt: str, selection_context: Optional[str] = None, max_turns: Optional[int] = None):
        """Enqueue a user prompt to be processed by the background thread."""
        with self._queue_lock:
            self._prompt_queue.append({
                "prompt": user_prompt,
                "selection": selection_context,
                "max_turns": max_turns,
            })
            self._queue_event.set()

    def stop(self):
        """Signals the worker thread to stop current execution."""
        self._stop_requested = True
        self._queue_event.set()

    def _resolve_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        # Check FreeCAD preferences
        try:
            param = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/AICopilot")
            stored = param.GetString("GeminiApiKey", "")
            if stored:
                return stored
        except Exception:
            pass
        return os.environ.get("GEMINI_API_KEY")

    def run(self):
        """Worker thread main loop."""
        while not self._stop_requested:
            # Wait for an enqueued prompt
            self._queue_event.wait(timeout=0.5)
            if self._stop_requested:
                break

            task = None
            with self._queue_lock:
                if self._prompt_queue:
                    task = self._prompt_queue.pop(0)
                if not self._prompt_queue:
                    self._queue_event.clear()

            if task:
                self._process_task(task)

    def _process_task(self, task: Dict[str, Any]):
        prompt_text = task["prompt"]
        selection = task.get("selection")

        api_key = self._resolve_api_key()
        if not api_key:
            self.sig_error.emit(
                "Gemini API Key is missing. Please set the GEMINI_API_KEY environment variable "
                "or enter your key in the AI Copilot settings."
            )
            self.sig_turn_complete.emit("")
            return

        self.sig_status.emit("Thinking...")

        # Construct full message content including selection context
        full_user_text = prompt_text
        if selection:
            full_user_text = f"{selection}\n\nUser Request: {prompt_text}"

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            # Prepare tool declarations
            raw_tools = self.tool_bridge.get_tool_declarations()
            gemini_tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t["name"],
                            description=t["description"],
                            parameters=t["parameters"],
                        )
                        for t in raw_tools
                    ]
                )
            ]

            thinking_cfg = None
            if hasattr(types, 'ThinkingConfig'):
                try:
                    thinking_cfg = types.ThinkingConfig(include_thoughts=True)
                except Exception:
                    pass

            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                tools=gemini_tools,
                thinking_config=thinking_cfg,
            )

            history_start_len = len(self.history)

            # Append user message to history
            self.history.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=full_user_text)]
                )
            )

            # Function calling loop
            turn_done = False
            turn_start_time = time.time()
            work_duration = 0.0
            tool_count = 0
            accumulated_response = ""
            accumulated_thought = ""
            task_max_turns = task.get("max_turns")
            if task_max_turns is None or task_max_turns <= 0:
                try:
                    from ..settings import get_setting
                except (ImportError, ValueError):
                    try:
                        from AICopilot.settings import get_setting
                    except (ImportError, ValueError):
                        from settings import get_setting
                task_max_turns = get_setting("max_turns", 30)
            max_turns = int(task_max_turns)
            initial_max_turns = max_turns
            active_model = self.model_name

            while not turn_done and max_turns > 0 and not self._stop_requested:
                max_turns -= 1

                # Generate content from model with automatic 503 fallback and 429 rate limit retry
                response = None
                max_429_retries = 2
                retry_429_count = 0

                while response is None and not self._stop_requested:
                    try:
                        response = client.models.generate_content(
                            model=active_model,
                            contents=self.history,
                            config=config,
                        )
                    except Exception as gen_err:
                        err_str = str(gen_err)
                        is_503 = (
                            "503" in err_str
                            or "UNAVAILABLE" in err_str
                            or "high demand" in err_str.lower()
                        )
                        is_429 = (
                            "429" in err_str
                            or "RESOURCE_EXHAUSTED" in err_str
                            or "quota" in err_str.lower()
                        )

                        if is_503 and active_model != FALLBACK_MODEL:
                            logger.warning(
                                f"Model {active_model} returned 503; falling back to {FALLBACK_MODEL}"
                            )
                            self.sig_status.emit(f"Model busy, falling back to {FALLBACK_MODEL}...")
                            fallback_notice = (
                                f"<div style='color: #e67e22; font-size: 11px; margin: 4px 0;'>"
                                f"⚡ <i>Notice: <b>{html.escape(active_model)}</b> is currently experiencing high demand (503). "
                                f"Automatically retrying via <b>{FALLBACK_MODEL}</b>...</i></div>"
                            )
                            self.sig_token.emit(fallback_notice)
                            active_model = FALLBACK_MODEL
                            continue

                        elif is_429 and retry_429_count < max_429_retries:
                            retry_429_count += 1
                            # Extract suggested retry delay from error if available (e.g. "Please retry in 28.95s")
                            retry_match = re.search(r"retry in\s*([\d\.]+)\s*s", err_str, re.IGNORECASE)
                            if retry_match:
                                wait_seconds = min(float(retry_match.group(1)) + 1.0, 45.0)
                            else:
                                wait_seconds = min(5.0 * (2 ** (retry_429_count - 1)), 30.0)

                            wait_int = max(int(wait_seconds), 1)
                            self.sig_token.emit(
                                f"<div style='color: #f39c12; font-size: 11px; margin: 4px 0;'>"
                                f"⏳ <i>Rate limit reached ({active_model} free tier quota). "
                                f"Pausing {wait_int}s for quota window to reset, then automatically resuming...</i></div>"
                            )

                            for sec in range(wait_int, 0, -1):
                                if self._stop_requested:
                                    break
                                self.sig_status.emit(f"Rate limit: resuming in {sec}s...")
                                time.sleep(1.0)

                            if self._stop_requested:
                                raise RuntimeError("Operation stopped by user")

                            self.sig_status.emit("Resuming operation...")
                            continue
                        else:
                            raise

                candidate = response.candidates[0] if response.candidates else None
                if not candidate:
                    break

                model_content = candidate.content
                self.history.append(model_content)

                # Check for function calls and thoughts
                function_calls = []
                for part in model_content.parts:
                    is_thought = getattr(part, 'thought', False) is True
                    if is_thought and part.text:
                        self.sig_thought.emit(part.text)
                        accumulated_thought += part.text
                    elif part.text:
                        self.sig_token.emit(part.text)
                        accumulated_response += part.text

                    if part.function_call:
                        function_calls.append(part.function_call)

                if function_calls:
                    t_work_start = time.time()
                    response_parts = []
                    for call in function_calls:
                        tool_count += 1
                        fn_name = call.name
                        fn_args = dict(call.args) if call.args else {}

                        self.sig_status.emit(f"Executing {fn_name}...")
                        self.sig_tool_started.emit(fn_name, fn_args)

                        # Request execution on the main GUI thread
                        req = ToolCallRequest(fn_name, fn_args)
                        self.sig_request_main_thread_tool.emit(req)

                        # Wait for main thread to complete execution
                        req.wait(timeout=120.0)

                        if req.exception:
                            tool_result_str = json.dumps({"error": str(req.exception)})
                        else:
                            tool_result_str = req.result or "{}"

                        self.sig_tool_finished.emit(fn_name, tool_result_str)

                        # Parse result to dict for Gemini function response
                        try:
                            parsed_res = json.loads(tool_result_str)
                        except Exception:
                            parsed_res = {"result": tool_result_str}

                        response_parts.append(
                            types.Part.from_function_response(
                                name=fn_name,
                                response={"output": parsed_res},
                            )
                        )

                    # Append tool responses to conversational history (Gemini API requires role="user")
                    self.history.append(
                        types.Content(
                            role="user",
                            parts=response_parts,
                        )
                    )
                    work_duration += (time.time() - t_work_start)
                    self.sig_status.emit("Evaluating result...")
                else:
                    # Model produced a final textual response without further tool calls
                    turn_done = True

            if not turn_done and not self._stop_requested and max_turns <= 0:
                logger.warning(f"Turn limit reached ({initial_max_turns}). Requesting summary from model.")
                self.sig_status.emit("Step limit reached, generating summary...")
                try:
                    summary_prompt = types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text=f"Note: You have reached the maximum allowed tool execution steps ({initial_max_turns}). "
                                 "Please provide a clear and concise summary for the user detailing: "
                                 "1) What has been completed so far, "
                                 "2) What operations or parameters were attempted and any errors encountered, and "
                                 "3) What remaining steps the user or Copilot should perform next."
                        )]
                    )
                    self.history.append(summary_prompt)
                    sum_resp = client.models.generate_content(
                        model=active_model,
                        contents=self.history,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.2,
                            thinking_config=thinking_cfg,
                        )
                    )
                    if sum_resp.candidates and sum_resp.candidates[0].content:
                        self.history.append(sum_resp.candidates[0].content)
                        for part in sum_resp.candidates[0].content.parts:
                            if part.text:
                                self.sig_token.emit(part.text)
                                accumulated_response += part.text
                except Exception as sum_err:
                    fallback_msg = (
                        f"\n\n*(Reached maximum tool execution steps limit: {initial_max_turns}. "
                        "Please check the executed steps above or submit a follow-up prompt.)*"
                    )
                    self.sig_token.emit(fallback_msg)
                    accumulated_response += fallback_msg

            total_duration = time.time() - turn_start_time
            metrics = {
                "total_duration": total_duration,
                "work_duration": work_duration if work_duration > 0 else (total_duration if tool_count > 0 else 0.0),
                "thought_duration": max(0.0, total_duration - work_duration) if accumulated_thought else 0.0,
                "tool_count": tool_count,
            }
            self.sig_status.emit("Idle")
            self.sig_turn_complete.emit(accumulated_response, metrics)

        except Exception as exc:
            logger.exception(f"Error in Gemini agent turn: {exc}")
            # If the turn failed, restore conversational history to before this turn started
            if len(self.history) > history_start_len:
                self.history = self.history[:history_start_len]
            self.sig_error.emit(str(exc))
            self.sig_status.emit("Error")
