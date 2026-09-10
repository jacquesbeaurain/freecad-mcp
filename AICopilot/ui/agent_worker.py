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
import threading
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
5. Direct Execution: If an operation isn't covered by a high-level tool, use `execute_python` to run direct FreeCAD Python code.
6. Conciseness: Keep explanations clear, practical, and focused on CAD geometry.
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
    sig_token = QtCore.Signal(str)
    sig_status = QtCore.Signal(str)
    sig_tool_started = QtCore.Signal(str, dict)
    sig_tool_finished = QtCore.Signal(str, str)
    sig_turn_complete = QtCore.Signal(str)
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

    def submit_prompt(self, user_prompt: str, selection_context: Optional[str] = None):
        """Enqueue a user prompt to be processed by the background thread."""
        with self._queue_lock:
            self._prompt_queue.append({
                "prompt": user_prompt,
                "selection": selection_context,
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

            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                tools=gemini_tools,
            )

            # Append user message to history
            self.history.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=full_user_text)]
                )
            )

            # Function calling loop
            turn_done = False
            accumulated_response = ""
            max_turns = 10  # Guard against infinite tool recursion
            active_model = self.model_name

            while not turn_done and max_turns > 0 and not self._stop_requested:
                max_turns -= 1

                # Generate content from model with automatic 503 fallback
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
                        response = client.models.generate_content(
                            model=active_model,
                            contents=self.history,
                            config=config,
                        )
                    else:
                        raise

                candidate = response.candidates[0] if response.candidates else None
                if not candidate:
                    break

                model_content = candidate.content
                self.history.append(model_content)

                # Check for function calls
                function_calls = []
                for part in model_content.parts:
                    if part.text:
                        self.sig_token.emit(part.text)
                        accumulated_response += part.text
                    if part.function_call:
                        function_calls.append(part.function_call)

                if function_calls:
                    response_parts = []
                    for call in function_calls:
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

                    # Append tool responses to conversational history
                    self.history.append(
                        types.Content(
                            role="tool",
                            parts=response_parts,
                        )
                    )
                    self.sig_status.emit("Evaluating result...")
                else:
                    # Model produced a final textual response without further tool calls
                    turn_done = True

            self.sig_status.emit("Idle")
            self.sig_turn_complete.emit(accumulated_response)

        except Exception as exc:
            logger.exception(f"Error in Gemini agent turn: {exc}")
            # If the turn failed, remove the dangling user turn so conversational history stays clean
            if self.history and getattr(self.history[-1], "role", None) == "user":
                self.history.pop()
            self.sig_error.emit(str(exc))
            self.sig_status.emit("Error")
            self.sig_turn_complete.emit("")
