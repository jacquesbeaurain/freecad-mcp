# FreeCAD AI Copilot Dock Widget
# Copyright (c) 2026
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Embedded PySide DockWidget providing direct conversational interaction,
# live 3D selection awareness, and in-memory CAD tool execution.

import ast
import html
import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide import QtCore, QtGui, QtWidgets

import FreeCAD

if FreeCAD.GuiUp:
    import FreeCADGui
else:
    FreeCADGui = None

from .agent_worker import CopilotAgentWorker, ToolCallRequest
from .tool_bridge import DirectToolBridge

logger = logging.getLogger("AICopilot.DockWidget")

DEFAULT_GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",
    "gemini-pro-latest",
]


def format_user_friendly_error(error_input: Any) -> str:
    """Extract a clean, human-readable error message, stripping raw JSON and dicts."""
    raw = str(error_input).strip()

    code = None
    if "503" in raw or "UNAVAILABLE" in raw:
        code = 503
    elif "404" in raw or "NOT_FOUND" in raw:
        code = 404
    elif "429" in raw or "RESOURCE_EXHAUSTED" in raw:
        code = 429
    elif "400" in raw or "INVALID_ARGUMENT" in raw:
        code = 400
    elif "403" in raw or "PERMISSION_DENIED" in raw:
        code = 403

    if "API Key is missing" in raw:
        return "Gemini API Key is missing. Please configure your key via the ⚙ Key button."

    # First attempt: parse python/JSON dict if present
    dict_match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if dict_match:
        dict_str = dict_match.group(1).strip()
        parsed_dict = None
        try:
            parsed_dict = json.loads(dict_str)
        except Exception:
            try:
                parsed_dict = ast.literal_eval(dict_str)
            except Exception:
                pass

        if isinstance(parsed_dict, dict):
            err_obj = parsed_dict.get("error", parsed_dict)
            if isinstance(err_obj, dict) and "message" in err_obj:
                msg = str(err_obj["message"]).strip()
                err_code = err_obj.get("code", code)
                if err_code == 503:
                    return f"Model Busy (503): {msg}"
                elif err_code == 404:
                    return f"Model Unavailable (404): {msg}"
                elif err_code == 429:
                    return f"Rate Limit Exceeded (429): {msg}"
                elif err_code:
                    return f"API Error ({err_code}): {msg}"
                return msg

    # Second attempt: Regex matching either double-quoted or single-quoted string
    msg_match = re.search(r"""['"]message['"]\s*:\s*(?:"((?:\\"|[^"])*)"|'((?:\\'|[^'])*)')""", raw)
    if msg_match:
        extracted = (msg_match.group(1) or msg_match.group(2) or "").strip()
        if extracted:
            if code == 503:
                return f"Model Busy (503): {extracted}"
            elif code == 404:
                return f"Model Unavailable (404): {extracted}"
            elif code == 429:
                return f"Rate Limit Exceeded (429): {extracted}"
            elif code:
                return f"API Error ({code}): {extracted}"
            return extracted

    # Strip prefixes like google.genai.errors.ServerError: or Agent Error:
    cleaned = re.sub(r"^(google\.genai\.errors\.\w+:\s*|Agent Error:\s*)+", "", raw)
    # Strip any trailing JSON / dict dictionary blob starting with {'error' or {"error"
    cleaned = re.split(r"\s*[\{\[]\s*['\"]error", cleaned)[0].strip()
    cleaned = cleaned.rstrip(".:, ")
    if cleaned:
        if code and str(code) not in cleaned:
            return f"API Error ({code}): {cleaned}"
        return cleaned

    return raw


class ChatInputTextEdit(QtWidgets.QPlainTextEdit):
    """Custom multi-line text edit that sends on Enter and allows Shift+Enter for newlines."""

    sig_submit = QtCore.Signal()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.sig_submit.emit()
                event.accept()
        else:
            super().keyPressEvent(event)


class SelectionObserver:
    """Listens to FreeCAD 3D viewport selections and notifies the UI."""

    def __init__(self, callback):
        self.callback = callback

    def addSelection(self, doc, obj, sub, pnt):
        self.callback()

    def removeSelection(self, doc, obj, sub):
        self.callback()

    def setSelection(self, doc):
        self.callback()

    def clearSelection(self, doc):
        self.callback()


class AICopilotDockWidget(QtWidgets.QDockWidget):
    """Native FreeCAD dock widget hosting the embedded AI Copilot assistant."""

    sig_models_discovered = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__("AI Copilot", parent)
        self.setObjectName("AICopilotDockWidget")
        self.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)

        self.tool_bridge = DirectToolBridge()
        self.worker = CopilotAgentWorker(self.tool_bridge, parent=self)
        self._current_assistant_buffer = ""
        self._selection_observer = None
        self._last_submitted_prompt: Optional[str] = None

        self._init_ui()
        self._wire_signals()
        self._attach_selection_observer()
        self._refresh_models_from_api()

        # Start the background worker thread
        self.worker.start()

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Clean up observer and stop worker on widget close."""
        self._detach_selection_observer()
        if self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1000)
        super().closeEvent(event)

    def _init_ui(self):
        container = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── Toolbar Row ──────────────────────────────────────────────
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(4)

        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(DEFAULT_GEMINI_MODELS)
        self.model_combo.setCurrentText(self.worker.model_name)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.model_combo.activated.connect(lambda _: self._dismiss_error_banner())
        toolbar.addWidget(self.model_combo, stretch=1)

        self.btn_undo = QtWidgets.QPushButton("↩ Undo")
        self.btn_undo.setToolTip("Roll back the last document transaction (Ctrl+Z)")
        self.btn_undo.clicked.connect(self._on_undo_clicked)
        toolbar.addWidget(self.btn_undo)

        self.btn_settings = QtWidgets.QPushButton("⚙ Key")
        self.btn_settings.setToolTip("Configure Gemini API Key")
        self.btn_settings.clicked.connect(self._on_settings_clicked)
        toolbar.addWidget(self.btn_settings)

        self.btn_clear = QtWidgets.QPushButton("🗑 Clear")
        self.btn_clear.setToolTip("Clear conversation history")
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        toolbar.addWidget(self.btn_clear)

        layout.addLayout(toolbar)

        # ── Live Selection Badge ─────────────────────────────────────
        self.selection_label = QtWidgets.QLabel("🎯 Selection: None")
        self.selection_label.setStyleSheet(
            "background: palette(alternate-base); border-radius: 4px; padding: 4px 6px; font-size: 11px;"
        )
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)

        # ── Chat History Display ─────────────────────────────────────
        self.chat_browser = QtWidgets.QTextBrowser()
        self.chat_browser.setOpenExternalLinks(True)
        self.chat_browser.setStyleSheet(
            "QTextBrowser { font-family: sans-serif; font-size: 12px; line-height: 1.4; }"
        )
        layout.addWidget(self.chat_browser, stretch=1)

        # ── Status Bar ───────────────────────────────────────────────
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("color: gray; font-size: 11px; padding: 2px 4px;")
        layout.addWidget(self.status_label)

        # ── Error Banner (Dismissible) ──────────────────────────────
        self.error_frame = QtWidgets.QFrame()
        self.error_frame.setObjectName("ErrorBanner")
        self.error_frame.setStyleSheet(
            "#ErrorBanner { background: rgba(231, 76, 60, 0.12); border: 1px solid #e74c3c; "
            "border-radius: 4px; padding: 2px 4px; }"
        )
        error_layout = QtWidgets.QHBoxLayout(self.error_frame)
        error_layout.setContentsMargins(6, 4, 6, 4)
        error_layout.setSpacing(6)

        self.error_icon = QtWidgets.QLabel("⚠️")
        self.error_icon.setStyleSheet("font-size: 13px;")
        error_layout.addWidget(self.error_icon)

        self.error_label = QtWidgets.QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #e74c3c; font-size: 11px; font-weight: 500;")
        error_layout.addWidget(self.error_label, stretch=1)

        self.btn_dismiss_error = QtWidgets.QPushButton("✕")
        self.btn_dismiss_error.setToolTip("Dismiss error")
        self.btn_dismiss_error.setFixedSize(18, 18)
        self.btn_dismiss_error.setStyleSheet(
            "QPushButton { border: none; font-size: 11px; font-weight: bold; color: #888; background: transparent; } "
            "QPushButton:hover { color: #e74c3c; background: rgba(231, 76, 60, 0.2); border-radius: 9px; }"
        )
        self.btn_dismiss_error.clicked.connect(self._dismiss_error_banner)
        error_layout.addWidget(self.btn_dismiss_error)

        self.error_frame.setVisible(False)
        layout.addWidget(self.error_frame)

        # ── Input Area ───────────────────────────────────────────────
        input_layout = QtWidgets.QHBoxLayout()
        input_layout.setSpacing(4)

        self.input_edit = ChatInputTextEdit()
        self.input_edit.setPlaceholderText("Ask AI Copilot or request CAD action (Enter to send, Shift+Enter for newline)...")
        self.input_edit.setFixedHeight(65)
        self.input_edit.sig_submit.connect(self._on_send_clicked)
        self.input_edit.textChanged.connect(self._on_input_text_changed)
        input_layout.addWidget(self.input_edit, stretch=1)

        btn_column = QtWidgets.QVBoxLayout()
        btn_column.setSpacing(2)

        self.btn_send = QtWidgets.QPushButton("➤ Send")
        self.btn_send.setStyleSheet("font-weight: bold;")
        self.btn_send.clicked.connect(self._on_send_clicked)
        btn_column.addWidget(self.btn_send)

        self.btn_stop = QtWidgets.QPushButton("⏹ Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        btn_column.addWidget(self.btn_stop)

        input_layout.addLayout(btn_column)
        layout.addLayout(input_layout)

        self.setWidget(container)
        self._append_system_message("<b>FreeCAD AI Copilot ready.</b> Type a prompt or select geometry in the 3D view.")

    def _wire_signals(self):
        self.sig_models_discovered.connect(self._apply_model_list)
        self.worker.sig_token.connect(self._on_token_received)
        self.worker.sig_status.connect(self._on_status_changed)
        self.worker.sig_tool_started.connect(self._on_tool_started)
        self.worker.sig_tool_finished.connect(self._on_tool_finished)
        self.worker.sig_turn_complete.connect(self._on_turn_complete)
        self.worker.sig_error.connect(self._on_error)
        self.worker.sig_request_main_thread_tool.connect(self._on_main_thread_tool_request)

    # ── Selection Observer ───────────────────────────────────────────

    def _attach_selection_observer(self):
        if FreeCADGui and FreeCAD.GuiUp:
            try:
                self._selection_observer = SelectionObserver(self._update_selection_badge)
                FreeCADGui.Selection.addObserver(self._selection_observer)
                self._update_selection_badge()
            except Exception as e:
                logger.warning(f"Could not attach SelectionObserver: {e}")

    def _detach_selection_observer(self):
        if FreeCADGui and FreeCAD.GuiUp and self._selection_observer:
            try:
                FreeCADGui.Selection.removeObserver(self._selection_observer)
                self._selection_observer = None
            except Exception:
                pass

    def _get_selection_summary(self) -> Optional[str]:
        if not FreeCADGui or not FreeCAD.GuiUp:
            return None
        sel_list = FreeCADGui.Selection.getSelectionEx()
        if not sel_list:
            return None

        items = []
        for sel in sel_list:
            obj_name = sel.ObjectName
            if sel.SubElementNames:
                sub_names = ", ".join(sel.SubElementNames)
                items.append(f"{obj_name} ({sub_names})")
            else:
                items.append(f"{obj_name}")
        return "; ".join(items)

    def _update_selection_badge(self):
        summary = self._get_selection_summary()
        if summary:
            self.selection_label.setText(f"🎯 <b>Selected:</b> {html.escape(summary)}")
            self.selection_label.setStyleSheet(
                "background: #2a3a4a; color: #8ec5fc; border-radius: 4px; padding: 4px 6px; font-size: 11px;"
            )
        else:
            self.selection_label.setText("🎯 Selection: None")
            self.selection_label.setStyleSheet(
                "background: palette(alternate-base); border-radius: 4px; padding: 4px 6px; font-size: 11px;"
            )

    # ── Chat Actions & Formatting ────────────────────────────────────

    def _on_model_changed(self, model_name: str):
        self._dismiss_error_banner()
        self.worker.set_model_name(model_name)

    def _dismiss_error_banner(self):
        self.error_frame.setVisible(False)
        self.error_label.setText("")

    def _on_input_text_changed(self):
        if self.error_frame.isVisible():
            self._dismiss_error_banner()

    def _on_send_clicked(self):
        prompt = self.input_edit.toPlainText().strip()
        if not prompt:
            return

        self._last_submitted_prompt = prompt
        self._dismiss_error_banner()
        self.input_edit.clear()
        self.btn_send.setEnabled(False)
        self.btn_stop.setEnabled(True)

        selection_summary = self._get_selection_summary()
        selection_ctx = f"[3D View Selection: {selection_summary}]" if selection_summary else None

        self._append_user_message(prompt, selection_summary)
        self._current_assistant_buffer = ""

        # Enqueue prompt to background worker
        self.worker.submit_prompt(prompt, selection_ctx)

    def _on_stop_clicked(self):
        self.worker.stop()
        self.status_label.setText("Stopping...")
        self.btn_stop.setEnabled(False)
        self.btn_send.setEnabled(True)

    def _on_clear_clicked(self):
        self.worker.clear_history()
        self.chat_browser.clear()
        self._append_system_message("Conversation history cleared.")

    def _on_undo_clicked(self):
        doc = FreeCAD.ActiveDocument
        if doc:
            try:
                doc.undo()
                doc.recompute()
                if FreeCADGui and FreeCAD.GuiUp:
                    FreeCADGui.updateGui()
                self._append_system_message("Undid last document action.")
            except Exception as e:
                self._append_system_message(f"Could not undo: {e}")
        else:
            self._append_system_message("No active document to undo.")

    def _on_settings_clicked(self):
        curr_key = os.environ.get("GEMINI_API_KEY", "")
        try:
            param = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/AICopilot")
            stored = param.GetString("GeminiApiKey", "")
            if stored:
                curr_key = stored
        except Exception:
            pass

        key, ok = QtWidgets.QInputDialog.getText(
            self,
            "Gemini API Key",
            "Enter your Google Gemini API Key:",
            QtWidgets.QLineEdit.Password,
            curr_key,
        )
        if ok and key:
            try:
                param = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/AICopilot")
                param.SetString("GeminiApiKey", key.strip())
                self.worker.set_api_key(key.strip())
                self._append_system_message("Gemini API key updated successfully.")
                self._refresh_models_from_api()
            except Exception as e:
                self._append_system_message(f"Failed to save API key: {e}")

    # ── Dynamic Model Discovery ──────────────────────────────────────

    def _refresh_models_from_api(self):
        """Asynchronously query Gemini API for available models and update combobox."""
        api_key = self.worker._resolve_api_key()
        if not api_key:
            return

        def fetch_models():
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                fetched = []
                for m in client.models.list():
                    name = m.name or ""
                    if name.startswith("models/"):
                        name = name[len("models/"):]
                    # Skip deprecated 2.5 and 1.x models for new users
                    if name.startswith("gemini-2.5-") or name.startswith("gemini-1.") or name.startswith("gemini-2.0"):
                        continue
                    actions = m.supported_actions or []
                    if "generateContent" in actions:
                        if any(skip in name for skip in ["-image", "-tts", "transcribe", "clip", "robotics", "embedding"]):
                            continue
                        fetched.append(name)

                if fetched:
                    priority = [
                        "gemini-3.6-flash",
                        "gemini-3.7-flash",
                        "gemini-3.8-flash",
                        "gemini-3.1-pro-preview",
                        "gemini-3.5-flash",
                        "gemini-3.5-flash-lite",
                        "gemini-flash-latest",
                        "gemini-pro-latest",
                    ]
                    def sort_key(item):
                        if item in priority:
                            return (0, priority.index(item))
                        return (1, item)
                    fetched.sort(key=sort_key)

                    self.sig_models_discovered.emit(fetched)
            except Exception as e:
                logger.debug(f"Could not dynamically refresh models: {e}")

        t = threading.Thread(target=fetch_models, daemon=True)
        t.start()

    @QtCore.Slot(list)
    def _apply_model_list(self, models: List[str]):
        """Update the model combobox with fetched models preserving current selection."""
        current = self.model_combo.currentText().strip()
        self.model_combo.blockSignals(True)
        try:
            self.model_combo.clear()
            self.model_combo.addItems(models)
            if current and current in models:
                self.model_combo.setCurrentText(current)
            elif current:
                self.model_combo.setEditText(current)
            elif models:
                self.model_combo.setCurrentIndex(0)
        finally:
            self.model_combo.blockSignals(False)

    # ── Worker Signal Handlers ───────────────────────────────────────

    def _on_token_received(self, token: str):
        self._current_assistant_buffer += token
        # Live refresh of current assistant message
        cursor = self.chat_browser.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.chat_browser.setTextCursor(cursor)
        self.chat_browser.insertPlainText(token)
        self.chat_browser.ensureCursorVisible()

    def _on_status_changed(self, status: str):
        self.status_label.setText(status)

    def _on_tool_started(self, tool_name: str, args: dict):
        args_summary = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
        if len(args) > 3:
            args_summary += ", ..."
        chip = f"<div style='color: #4a90e2; font-family: monospace; font-size: 11px; margin: 4px 0;'>" \
               f"⚡ <b>Executing:</b> {html.escape(tool_name)}({html.escape(args_summary)})</div>"
        self._append_html(chip)

    def _on_tool_finished(self, tool_name: str, result_str: str):
        # Truncate output for chat preview
        preview = result_str[:250] + ("..." if len(result_str) > 250 else "")
        chip = f"<div style='color: #50b37b; font-family: monospace; font-size: 11px; margin: 2px 0 6px 12px;'>" \
               f"✔ <b>Result:</b> {html.escape(preview)}</div>"
        self._append_html(chip)

    def _on_turn_complete(self, full_response: str):
        self._last_submitted_prompt = None
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if not self.error_frame.isVisible():
            self.status_label.setText("Ready")
        self._current_assistant_buffer = ""
        self._append_html("<hr style='border: none; border-top: 1px solid palette(mid); margin: 8px 0;'>")

    def _on_error(self, error_msg: str):
        cleaned_msg = format_user_friendly_error(error_msg)
        self.error_label.setText(cleaned_msg)
        self.error_frame.setVisible(True)
        self._append_html(
            f"<div style='color: #e74c3c; font-size: 11px; padding: 4px 0;'>"
            f"⚠️ <b>Error:</b> {html.escape(cleaned_msg)}</div>"
        )
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("Error")

        # Do not clear prompt on error: restore so user can easily retry or fix model
        if self._last_submitted_prompt and not self.input_edit.toPlainText().strip():
            self.input_edit.blockSignals(True)
            try:
                self.input_edit.setPlainText(self._last_submitted_prompt)
                cursor = self.input_edit.textCursor()
                cursor.movePosition(QtGui.QTextCursor.End)
                self.input_edit.setTextCursor(cursor)
            finally:
                self.input_edit.blockSignals(False)

    @QtCore.Slot(object)
    def _on_main_thread_tool_request(self, req: ToolCallRequest):
        """Executed on the main GUI thread when the background worker requests a CAD tool."""
        try:
            result = self.tool_bridge.execute_tool(req.tool_name, req.args)
            req.set_result(result)
        except Exception as exc:
            logger.exception(f"Main thread tool dispatch error: {exc}")
            req.set_exception(exc)

    # ── Formatting Helpers ───────────────────────────────────────────

    def _append_user_message(self, text: str, selection_badge: Optional[str] = None):
        badge_html = ""
        if selection_badge:
            badge_html = f"<div style='font-size: 10px; color: #8ec5fc; margin-bottom: 2px;'>" \
                         f"🎯 {html.escape(selection_badge)}</div>"
        content_html = f"<div style='background: palette(midlight); border-radius: 6px; padding: 6px 10px; margin: 6px 0;'>" \
                       f"{badge_html}<b>You:</b> {html.escape(text)}</div>"
        self._append_html(content_html)

    def _append_system_message(self, msg_html: str):
        formatted = f"<div style='color: gray; font-size: 11px; margin: 4px 0;'>ℹ {msg_html}</div>"
        self._append_html(formatted)

    def _append_html(self, html_content: str):
        cursor = self.chat_browser.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.chat_browser.setTextCursor(cursor)
        self.chat_browser.insertHtml(html_content)
        cursor.movePosition(QtGui.QTextCursor.End)
        self.chat_browser.setTextCursor(cursor)
        self.chat_browser.ensureCursorVisible()
