# FreeCAD AI Copilot Dock Widget
# Copyright (c) 2026
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Embedded PySide DockWidget providing direct conversational interaction,
# live 3D selection awareness, collapsible thought/work sections,
# multiline Python code execution controls, color-coded structured JSON results,
# and light/dark theme adaptive styling.

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
try:
    from ..settings import (
        append_command_history,
        clear_command_history,
        get_setting,
        get_settings_file_path,
        set_setting,
    )
except (ImportError, ValueError):
    try:
        from AICopilot.settings import (
            append_command_history,
            clear_command_history,
            get_setting,
            get_settings_file_path,
            set_setting,
        )
    except (ImportError, ValueError):
        from settings import (
            append_command_history,
            clear_command_history,
            get_setting,
            get_settings_file_path,
            set_setting,
        )

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


def is_dark_theme(widget: Optional[QtWidgets.QWidget] = None) -> bool:
    """Detect whether FreeCAD or the active widget is currently running in a dark theme."""
    try:
        if widget and hasattr(widget, "palette"):
            val = widget.palette().color(QtGui.QPalette.Window).lightness()
            if isinstance(val, (int, float)):
                return val < 128
        if FreeCADGui and FreeCAD.GuiUp and hasattr(FreeCADGui, "getMainWindow"):
            mw = FreeCADGui.getMainWindow()
            if mw and hasattr(mw, "palette"):
                val = mw.palette().color(QtGui.QPalette.Window).lightness()
                if isinstance(val, (int, float)):
                    return val < 128
        app = QtWidgets.QApplication.instance()
        if app and hasattr(app, "palette"):
            val = app.palette().color(QtGui.QPalette.Window).lightness()
            if isinstance(val, (int, float)):
                return val < 128
    except Exception:
        pass
    return False


def get_theme_palette(widget: Optional[QtWidgets.QWidget] = None) -> dict:
    """Return theme-adaptive color tokens matching Classic, Light, and Dark themes cleanly."""
    dark = is_dark_theme(widget)
    if dark:
        return {
            "dark": True,
            "badge_sel_bg": "rgba(41, 128, 185, 0.25)",
            "badge_sel_border": "#2980b9",
            "badge_sel_fg": "#8ec5fc",
            "badge_none_bg": "rgba(255, 255, 255, 0.05)",
            "badge_none_border": "rgba(255, 255, 255, 0.1)",
            "badge_none_fg": "#888888",
            "user_box_bg": "rgba(255, 255, 255, 0.05)",
            "user_box_border": "rgba(255, 255, 255, 0.08)",
            "user_box_fg": "#e2e8f0",
            "user_sel_fg": "#54a0ff",
            "btn_toggle_fg": "#a0aec0",
            "btn_toggle_bg": "rgba(255, 255, 255, 0.06)",
            "btn_toggle_hover": "#edf2f7",
            "code_bg": "#181a1f",
            "code_border": "#333842",
            "code_fg": "#dcdcdc",
            "thought_bg": "rgba(0, 0, 0, 0.25)",
            "thought_border": "rgba(255, 255, 255, 0.1)",
            "thought_fg": "#a4b0be",
            "res_success_bg": "rgba(46, 204, 113, 0.12)",
            "res_success_border": "rgba(46, 204, 113, 0.4)",
            "res_success_fg": "#2ecc71",
            "res_success_val": "#d1d8e0",
            "res_err_bg": "rgba(231, 76, 60, 0.14)",
            "res_err_border": "rgba(231, 76, 60, 0.45)",
            "res_err_fg": "#e74c3c",
            "res_err_val": "#ffb8b8",
        }
    else:
        return {
            "dark": False,
            "badge_sel_bg": "rgba(52, 152, 219, 0.12)",
            "badge_sel_border": "rgba(52, 152, 219, 0.4)",
            "badge_sel_fg": "#1b4f72",
            "badge_none_bg": "rgba(0, 0, 0, 0.04)",
            "badge_none_border": "rgba(0, 0, 0, 0.1)",
            "badge_none_fg": "#666666",
            "user_box_bg": "rgba(0, 0, 0, 0.04)",
            "user_box_border": "rgba(0, 0, 0, 0.08)",
            "user_box_fg": "#1f2937",
            "user_sel_fg": "#0984e3",
            "btn_toggle_fg": "#374151",
            "btn_toggle_bg": "rgba(0, 0, 0, 0.04)",
            "btn_toggle_hover": "#111827",
            "code_bg": "#f8f9fa",
            "code_border": "#dcdfe6",
            "code_fg": "#1f2937",
            "thought_bg": "rgba(0, 0, 0, 0.03)",
            "thought_border": "rgba(0, 0, 0, 0.12)",
            "thought_fg": "#374151",
            "res_success_bg": "rgba(39, 174, 96, 0.08)",
            "res_success_border": "rgba(39, 174, 96, 0.35)",
            "res_success_fg": "#1e8449",
            "res_success_val": "#1f2937",
            "res_err_bg": "rgba(231, 76, 60, 0.08)",
            "res_err_border": "rgba(231, 76, 60, 0.35)",
            "res_err_fg": "#c0392b",
            "res_err_val": "#78281f",
        }


def clean_markdown_text(text: str) -> str:
    """Strip LaTeX math formatting that Qt's CommonMark Markdown renderer cannot display.

    Converts expressions like '$X$: $0.00 \\text{ mm}$ to $900.00 \\text{ mm}$' into
    'X: 0.00 mm to 900.00 mm'.
    """
    if not text:
        return text
    s = text
    s = s.replace(r"\times", "x")
    s = s.replace(r"\approx", "~")
    s = s.replace(r"\pm", "+/-")
    s = s.replace(r"\leq", "<=").replace(r"\le", "<=")
    s = s.replace(r"\geq", ">=").replace(r"\ge", ">=")
    s = s.replace(r"^\circ", " deg").replace(r"\degree", " deg")
    s = re.sub(r"\\(?:text|mathrm|mathbf|mathit)\{\s*([^}]+?)\s*\}", r"\1", s)
    s = re.sub(r"(?<!\\)\$([^\$\n]+?)\$", r"\1", s)
    s = re.sub(r"(?<!\\)\$\$([^\$]+?)\$\$", r"\1", s)
    s = re.sub(r"([0-9])\s{2,}([a-zA-Z])", r"\1 \2", s)
    return s


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
    cleaned = re.split(r"\s*[\{\[]\s*['\"]error", cleaned)[0].strip()
    cleaned = cleaned.rstrip(".:, ")
    if cleaned:
        if code and str(code) not in cleaned:
            return f"API Error ({code}): {cleaned}"
        return cleaned

    return raw


class ChatInputTextEdit(QtWidgets.QPlainTextEdit):
    """Custom multi-line text edit supporting Enter-to-send, Shift+Enter newlines,
    and command history navigation via Ctrl+Alt+Up / Ctrl+Alt+Down.
    """

    sig_submit = QtCore.Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._history: List[str] = []
        self._history_index: int = 0
        self._draft: str = ""

    def set_history(self, history: List[str]):
        self._history = list(history)
        self._history_index = len(self._history)
        self._draft = ""

    def get_history(self) -> List[str]:
        return list(self._history)

    def append_history(self, prompt: str):
        p = prompt.strip()
        if not p:
            return
        if not self._history or self._history[-1] != p:
            self._history.append(p)
            if len(self._history) > 100:
                self._history = self._history[-100:]
        self._history_index = len(self._history)
        self._draft = ""

    def clear_history(self):
        self._history.clear()
        self._history_index = 0
        self._draft = ""

    def navigate_history_prev(self):
        """Navigate to earlier command in history (Up / older)."""
        if not self._history:
            return
        if self._history_index >= len(self._history):
            self._draft = self.toPlainText()
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        else:
            return

        self._show_history_entry(self._history[self._history_index])

    def navigate_history_next(self):
        """Navigate to newer command in history or back to draft (Down / newer)."""
        if not self._history:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._show_history_entry(self._history[self._history_index])
        elif self._history_index == len(self._history) - 1:
            self._history_index = len(self._history)
            self._show_history_entry(self._draft)

    def _show_history_entry(self, entry_text: str):
        self.blockSignals(True)
        try:
            self.setPlainText(entry_text)
            cursor = self.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End)
            self.setTextCursor(cursor)
        finally:
            self.blockSignals(False)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        key = event.key()
        mods = event.modifiers()

        # Ctrl+Alt+Up / Down: command history navigation (does not interfere with text editing)
        is_ctrl = bool(mods & QtCore.Qt.ControlModifier)
        is_alt = bool(mods & QtCore.Qt.AltModifier)
        is_shift = bool(mods & QtCore.Qt.ShiftModifier)

        if is_ctrl and is_alt:
            if key == QtCore.Qt.Key_Up:
                self.navigate_history_prev()
                event.accept()
                return
            elif key == QtCore.Qt.Key_Down:
                self.navigate_history_next()
                event.accept()
                return

        # Return / Enter: send prompt (Shift+Enter inserts newline)
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if is_shift:
                super().keyPressEvent(event)
            else:
                self.sig_submit.emit()
                event.accept()
            return

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


# ── Formatted Tool Controls ──────────────────────────────────────────

class FormattedCodeBox(QtWidgets.QWidget):
    """Multiline formatted code control for execute_python invocations."""

    def __init__(self, code_text: str, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        palette = get_theme_palette(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(3)

        # Header Bar
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(2, 0, 2, 0)
        lbl_title = QtWidgets.QLabel("⚡ <b>Execute Python:</b>", self)
        lbl_title.setTextFormat(QtCore.Qt.RichText)
        lbl_title.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lbl_title.setStyleSheet(f"font-size: 11px; color: {palette['user_sel_fg']};")
        header_layout.addWidget(lbl_title)
        header_layout.addStretch(1)

        badge = QtWidgets.QLabel("Python", self)
        badge.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        badge.setStyleSheet(
            f"font-size: 9px; font-weight: bold; background: {palette['badge_none_bg']}; "
            f"border: 1px solid {palette['badge_none_border']}; border-radius: 3px; padding: 1px 4px; color: {palette['badge_none_fg']};"
        )
        header_layout.addWidget(badge)
        layout.addLayout(header_layout)

        # Monospace Code View
        self.code_edit = QtWidgets.QPlainTextEdit(self)
        self.code_edit.setReadOnly(True)
        self.code_edit.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
        self.code_edit.setPlainText(code_text.strip())
        self.code_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)

        lines = max(code_text.count("\n") + 1, 1)
        calc_height = min(max(lines * 17 + 14, 50), 200)
        self.code_edit.setFixedHeight(calc_height)

        self.code_edit.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {palette['code_bg']};
                border: 1px solid {palette['code_border']};
                border-radius: 4px;
                color: {palette['code_fg']};
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
                padding: 4px 6px;
            }}
            """
        )
        layout.addWidget(self.code_edit)


class FormattedResultCard(QtWidgets.QFrame):
    """Color-coded card for unparsed and structured JSON tool results."""

    def __init__(self, tool_name: str, result_str: str, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        palette = get_theme_palette(self)

        # Parse JSON
        parsed: Optional[Any] = None
        is_error = False
        try:
            parsed = json.loads(result_str)
            if isinstance(parsed, dict):
                if "error" in parsed or parsed.get("status") == "error" or parsed.get("success") is False:
                    is_error = True
        except Exception:
            if "error" in result_str.lower() or "exception" in result_str.lower():
                is_error = True

        bg = palette["res_err_bg"] if is_error else palette["res_success_bg"]
        border = palette["res_err_border"] if is_error else palette["res_success_border"]
        accent = palette["res_err_fg"] if is_error else palette["res_success_fg"]
        val_color = palette["res_err_val"] if is_error else palette["res_success_val"]

        self.setStyleSheet(
            f"""
            FormattedResultCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 4px;
                margin: 2px 0 4px 4px;
            }}
            """
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Header Row
        header_layout = QtWidgets.QHBoxLayout()
        icon = "❌" if is_error else "✔"
        title_text = "Error" if is_error else "Result"
        lbl_head = QtWidgets.QLabel(f"{icon} <b>{title_text}</b>", self)
        lbl_head.setTextFormat(QtCore.Qt.RichText)
        lbl_head.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lbl_head.setStyleSheet(f"font-size: 11px; color: {accent}; font-weight: bold;")
        header_layout.addWidget(lbl_head)
        header_layout.addStretch(1)

        tool_badge = QtWidgets.QLabel(tool_name, self)
        tool_badge.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        tool_badge.setStyleSheet(
            f"font-size: 9px; font-family: monospace; color: {palette['badge_none_fg']}; "
            f"background: {palette['badge_none_bg']}; border-radius: 2px; padding: 1px 3px;"
        )
        header_layout.addWidget(tool_badge)
        layout.addLayout(header_layout)

        # Content Rendering
        if isinstance(parsed, dict):
            for k, v in list(parsed.items())[:6]:
                row = QtWidgets.QHBoxLayout()
                row.setContentsMargins(4, 0, 4, 0)
                row.setSpacing(4)

                lbl_k = QtWidgets.QLabel(f"• <b>{html.escape(str(k))}:</b>", self)
                lbl_k.setTextFormat(QtCore.Qt.RichText)
                lbl_k.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                lbl_k.setStyleSheet(f"font-size: 11px; color: {accent}; font-family: monospace;")
                row.addWidget(lbl_k)

                val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                lbl_v = QtWidgets.QLabel(html.escape(val_str), self)
                lbl_v.setWordWrap(True)
                lbl_v.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                lbl_v.setStyleSheet(f"font-size: 11px; color: {val_color}; font-family: monospace;")
                row.addWidget(lbl_v, stretch=1)
                layout.addLayout(row)

            if len(parsed) > 6:
                more_lbl = QtWidgets.QLabel(f"... and {len(parsed) - 6} more fields", self)
                more_lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                more_lbl.setStyleSheet(f"font-size: 10px; color: {palette['badge_none_fg']}; font-style: italic; margin-left: 12px;")
                layout.addWidget(more_lbl)
        else:
            lbl = QtWidgets.QLabel(html.escape(result_str[:300] + ("..." if len(result_str) > 300 else "")), self)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            lbl.setStyleSheet(f"font-size: 11px; color: {val_color}; font-family: monospace; padding-left: 4px;")
            layout.addWidget(lbl)


# ── Collapsible History Sections ─────────────────────────────────────

class CollapsibleSection(QtWidgets.QWidget):
    """Collapsible container with a clickable header button and expandable frame."""

    def __init__(self, title: str, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.title_text = title
        self._is_expanded = True
        palette = get_theme_palette(self)

        self._main_layout = QtWidgets.QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 2, 0, 2)
        self._main_layout.setSpacing(2)

        self.toggle_btn = QtWidgets.QToolButton(self)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet(
            f"""
            QToolButton {{
                border: 1px solid {palette['user_box_border']};
                font-size: 11px;
                font-weight: 600;
                color: {palette['btn_toggle_fg']};
                background: {palette['btn_toggle_bg']};
                border-radius: 4px;
                text-align: left;
                padding: 4px 8px;
            }}
            QToolButton:hover {{
                color: {palette['btn_toggle_hover']};
            }}
            """
        )
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        self._main_layout.addWidget(self.toggle_btn)

        self.content_frame = QtWidgets.QFrame(self)
        self.content_frame.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.content_layout = QtWidgets.QVBoxLayout(self.content_frame)
        self.content_layout.setContentsMargins(10, 4, 4, 4)
        self.content_layout.setSpacing(4)
        self._main_layout.addWidget(self.content_frame)

        self._update_arrow()

    def _update_arrow(self):
        arrow = "▼" if self._is_expanded else "▶"
        self.toggle_btn.setText(f"{arrow}  {self.title_text}")

    def _on_toggle_clicked(self):
        self.set_collapsed(self._is_expanded)

    def set_collapsed(self, collapsed: bool):
        self._is_expanded = not collapsed
        self.content_frame.setVisible(self._is_expanded)
        self.toggle_btn.setChecked(self._is_expanded)
        self._update_arrow()

    def set_title(self, title: str):
        self.title_text = title
        self._update_arrow()


class ThoughtSection(CollapsibleSection):
    """Collapsible section displaying model reasoning/thinking tokens."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__("Thinking...", parent)
        palette = get_theme_palette(self)
        self.thought_edit = QtWidgets.QPlainTextEdit(self.content_frame)
        self.thought_edit.setReadOnly(True)
        self.thought_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.thought_edit.setMaximumHeight(140)
        self.thought_edit.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {palette['thought_bg']};
                border: 1px solid {palette['thought_border']};
                border-radius: 4px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
                color: {palette['thought_fg']};
                padding: 4px;
            }}
            """
        )
        self.content_layout.addWidget(self.thought_edit)

    def append_thought(self, text: str):
        cursor = self.thought_edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.thought_edit.setTextCursor(cursor)
        self.thought_edit.insertPlainText(text)
        cursor.movePosition(QtGui.QTextCursor.End)
        self.thought_edit.setTextCursor(cursor)
        self.thought_edit.ensureCursorVisible()

    def finish(self, duration: float):
        dur_str = f"{max(duration, 0.1):.1f}s"
        self.set_title(f"Thought ({dur_str})")
        self.set_collapsed(True)


class WorkSection(CollapsibleSection):
    """Collapsible section displaying executed tools, multiline python code, and colored JSON results."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__("Working...", parent)
        self._tool_count = 0

    def add_tool_call(self, tool_name: str, args: dict):
        self._tool_count += 1
        palette = get_theme_palette(self)

        # If execute_python, render multiline formatted code control
        if tool_name == "execute_python":
            code_str = str(args.get("code") or args.get("script") or "")
            if code_str:
                code_box = FormattedCodeBox(code_str, self.content_frame)
                self.content_layout.addWidget(code_box)
            else:
                lbl = QtWidgets.QLabel("⚡ <b>Execute Python:</b> (empty)", self.content_frame)
                lbl.setTextFormat(QtCore.Qt.RichText)
                lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                lbl.setStyleSheet(f"font-family: Consolas, monospace; font-size: 11px; color: {palette['user_sel_fg']};")
                self.content_layout.addWidget(lbl)
        else:
            args_summary = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
            if len(args) > 3:
                args_summary += ", ..."
            lbl = QtWidgets.QLabel(self.content_frame)
            lbl.setWordWrap(True)
            lbl.setTextFormat(QtCore.Qt.RichText)
            lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            lbl.setStyleSheet(f"font-family: Consolas, monospace; font-size: 11px; color: {palette['user_sel_fg']}; margin: 1px 0;")
            lbl.setText(f"⚡ <b>Executing:</b> {html.escape(tool_name)}({html.escape(args_summary)})")
            self.content_layout.addWidget(lbl)

        cmd_word = "command" if self._tool_count == 1 else "commands"
        self.set_title(f"Working ({self._tool_count} {cmd_word})...")

    def add_tool_result(self, tool_name: str, result_str: str):
        card = FormattedResultCard(tool_name, result_str, self.content_frame)
        self.content_layout.addWidget(card)

    def add_notice(self, notice_text: str):
        lbl = QtWidgets.QLabel(self.content_frame)
        lbl.setWordWrap(True)
        lbl.setTextFormat(QtCore.Qt.RichText)
        lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lbl.setText(f"<div style='color: #e67e22; font-size: 11px; margin: 2px 0;'>{notice_text}</div>")
        self.content_layout.addWidget(lbl)

    def finish(self, duration: float, count: int):
        cmd_word = "command" if count == 1 else "commands"
        dur_str = f"{max(duration, 0.1):.1f}s"
        if count > 0:
            self.set_title(f"Worked for {dur_str} (Ran {count} {cmd_word})")
        else:
            self.set_title(f"Worked for {dur_str}")
        self.set_collapsed(True)


class TurnCardWidget(QtWidgets.QFrame):
    """Encapsulates a single conversational exchange (User prompt -> Thoughts -> Work -> Response)."""

    def __init__(self, prompt: str, selection_badge: Optional[str] = None, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        palette = get_theme_palette(self)
        self.setObjectName("TurnCard")
        self.setStyleSheet(
            "#TurnCard { background: transparent; border-bottom: 1px solid palette(mid); margin-bottom: 10px; }"
        )
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(2, 4, 2, 8)
        self._layout.setSpacing(6)

        # 1. User Message Box
        self.user_box = QtWidgets.QFrame(self)
        self.user_box.setObjectName("UserBox")
        self.user_box.setStyleSheet(
            f"#UserBox {{ background: {palette['user_box_bg']}; border: 1px solid {palette['user_box_border']}; border-radius: 6px; padding: 6px 10px; }}"
        )
        user_layout = QtWidgets.QVBoxLayout(self.user_box)
        user_layout.setContentsMargins(6, 6, 6, 6)
        user_layout.setSpacing(2)

        if selection_badge:
            sel_lbl = QtWidgets.QLabel(f"🎯 {selection_badge}", self.user_box)
            sel_lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            sel_lbl.setStyleSheet(f"font-size: 10px; color: {palette['user_sel_fg']}; font-weight: 600;")
            user_layout.addWidget(sel_lbl)

        prompt_lbl = QtWidgets.QLabel(self.user_box)
        prompt_lbl.setWordWrap(True)
        prompt_lbl.setTextFormat(QtCore.Qt.RichText)
        prompt_lbl.setText(f"<b>You:</b> {html.escape(prompt)}")
        prompt_lbl.setStyleSheet(f"color: {palette['user_box_fg']}; font-size: 12px;")
        prompt_lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        user_layout.addWidget(prompt_lbl)
        self._layout.addWidget(self.user_box)

        # 2. Sections (created on demand)
        self.thought_section: Optional[ThoughtSection] = None
        self.work_section: Optional[WorkSection] = None

        # 3. Assistant Response Container
        self.response_label = QtWidgets.QLabel(self)
        self.response_label.setWordWrap(True)
        self.response_label.setTextFormat(QtCore.Qt.MarkdownText)
        self.response_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse
        )
        self.response_label.setOpenExternalLinks(True)
        self.response_label.setStyleSheet(
            f"QLabel {{ font-family: sans-serif; font-size: 12px; line-height: 1.4; padding: 4px; color: {palette['user_box_fg']}; }}"
        )
        self.response_label.setVisible(False)
        self._layout.addWidget(self.response_label)

        # 4. Turn Error Box
        self.turn_error_box = QtWidgets.QFrame(self)
        self.turn_error_box.setStyleSheet(
            f"background: {palette['res_err_bg']}; border: 1px solid {palette['res_err_border']}; border-radius: 4px; padding: 4px;"
        )
        err_layout = QtWidgets.QHBoxLayout(self.turn_error_box)
        err_layout.setContentsMargins(6, 4, 6, 4)
        err_layout.setSpacing(6)
        self.err_icon = QtWidgets.QLabel("⚠️")
        err_layout.addWidget(self.err_icon)
        self.err_label = QtWidgets.QLabel()
        self.err_label.setWordWrap(True)
        self.err_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.err_label.setStyleSheet(f"color: {palette['res_err_fg']}; font-size: 11px; font-weight: 500;")
        err_layout.addWidget(self.err_label, stretch=1)
        self.turn_error_box.setVisible(False)
        self._layout.addWidget(self.turn_error_box)

        self._assistant_raw_text = ""

    def ensure_thought_section(self) -> ThoughtSection:
        if self.thought_section is None:
            self.thought_section = ThoughtSection(self)
            idx = self._layout.indexOf(self.response_label)
            self._layout.insertWidget(idx, self.thought_section)
        return self.thought_section

    def ensure_work_section(self) -> WorkSection:
        if self.work_section is None:
            self.work_section = WorkSection(self)
            idx = self._layout.indexOf(self.response_label)
            self._layout.insertWidget(idx, self.work_section)
        return self.work_section

    def append_response_token(self, token: str):
        self._assistant_raw_text += token
        self.response_label.setText(clean_markdown_text(self._assistant_raw_text))
        if not self.response_label.isVisible():
            self.response_label.setVisible(True)

    def finish_turn(self, final_text: str, metrics: Optional[dict] = None):
        metrics = metrics or {}
        if self.thought_section:
            dur = metrics.get("thought_duration", 0.0)
            self.thought_section.finish(dur)

        if self.work_section:
            dur = metrics.get("work_duration", 0.0)
            cnt = metrics.get("tool_count", self.work_section._tool_count)
            self.work_section.finish(dur, cnt)

        if final_text:
            self._assistant_raw_text = final_text
            self.response_label.setText(clean_markdown_text(self._assistant_raw_text))
            self.response_label.setVisible(True)

    def show_error(self, message: str):
        self.err_label.setText(message)
        self.turn_error_box.setVisible(True)


class SystemMessageWidget(QtWidgets.QWidget):
    """Muted inline banner for system actions (clear, undo, initial greetings)."""

    def __init__(self, text: str, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        lbl = QtWidgets.QLabel(f"ℹ {text}", self)
        lbl.setWordWrap(True)
        lbl.setTextFormat(QtCore.Qt.RichText)
        lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lbl.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(lbl)


class ChatStreamWidget(QtWidgets.QScrollArea):
    """Scroll area containing sequential turn cards and system messages."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.container = QtWidgets.QWidget()
        self.container.setStyleSheet("QWidget { background: transparent; }")
        self.layout = QtWidgets.QVBoxLayout(self.container)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(6)
        self.layout.addStretch(1)

        self.setWidget(self.container)

    def add_turn_card(self, card: TurnCardWidget):
        self.layout.insertWidget(self.layout.count() - 1, card)
        self.scroll_to_bottom()

    def add_system_message(self, text: str):
        msg = SystemMessageWidget(text, self.container)
        self.layout.insertWidget(self.layout.count() - 1, msg)
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        QtCore.QTimer.singleShot(10, self._do_scroll_bottom)

    def _do_scroll_bottom(self):
        vsb = self.verticalScrollBar()
        vsb.setValue(vsb.maximum())

    def clear(self):
        while self.layout.count() > 1:
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()


# ── Copilot Settings Dialog ─────────────────────────────────────────

class CopilotSettingsDialog(QtWidgets.QDialog):
    """Preferences dialog for AI Copilot auto-save, model, and history options."""

    def __init__(self, dock_widget: "AICopilotDockWidget", parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent or dock_widget)
        self.dock_widget = dock_widget
        self.setWindowTitle("AI Copilot Settings")
        self.setMinimumWidth(440)
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        # 1. Execution & Auto-Save
        group_exec = QtWidgets.QGroupBox("Execution and Safety", self)
        layout_exec = QtWidgets.QVBoxLayout(group_exec)
        layout_exec.setSpacing(6)

        self.chk_auto_save = QtWidgets.QCheckBox("Auto-save active document before code execution", group_exec)
        self.chk_auto_save.setChecked(get_setting("auto_save_on_execute", False))
        layout_exec.addWidget(self.chk_auto_save)

        lbl_note = QtWidgets.QLabel(
            "<span style='color: gray; font-size: 10px;'>"
            "When enabled, saves the active FreeCAD document before executing Python code or complex boolean operations. "
            "Disabled by default to avoid unintended changes to saved files."
            "</span>",
            group_exec,
        )
        lbl_note.setWordWrap(True)
        lbl_note.setTextFormat(QtCore.Qt.RichText)
        layout_exec.addWidget(lbl_note)

        layout_turns = QtWidgets.QHBoxLayout()
        lbl_turns = QtWidgets.QLabel("Max Tool Execution Steps (Turns):", group_exec)
        self.spin_max_turns = QtWidgets.QSpinBox(group_exec)
        self.spin_max_turns.setRange(5, 100)
        self.spin_max_turns.setValue(int(get_setting("max_turns", 30)))
        layout_turns.addWidget(lbl_turns)
        layout_turns.addWidget(self.spin_max_turns)
        layout_turns.addStretch()
        layout_exec.addLayout(layout_turns)

        layout.addWidget(group_exec)

        # 2. Model & API Key
        group_api = QtWidgets.QGroupBox("Gemini Model and API Key", self)
        layout_api = QtWidgets.QFormLayout(group_api)
        layout_api.setSpacing(6)

        self.combo_model = QtWidgets.QComboBox(group_api)
        self.combo_model.addItems(DEFAULT_GEMINI_MODELS)
        curr_model = get_setting("selected_model", dock_widget.worker.model_name)
        if curr_model and curr_model not in DEFAULT_GEMINI_MODELS:
            self.combo_model.addItem(curr_model)
        self.combo_model.setCurrentText(curr_model)
        layout_api.addRow("Default Model:", self.combo_model)

        self.txt_key = QtWidgets.QLineEdit(group_api)
        self.txt_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.txt_key.setPlaceholderText("Enter Gemini API Key...")
        curr_key = os.environ.get("GEMINI_API_KEY", "")
        try:
            param = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/AICopilot")
            stored = param.GetString("GeminiApiKey", "")
            if stored:
                curr_key = stored
        except Exception:
            pass
        if curr_key:
            self.txt_key.setText(curr_key)
        layout_api.addRow("API Key:", self.txt_key)
        layout.addWidget(group_api)

        # 3. Storage & History
        group_store = QtWidgets.QGroupBox("Storage and Command History", self)
        layout_store = QtWidgets.QVBoxLayout(group_store)
        layout_store.setSpacing(6)

        settings_path = get_settings_file_path()
        lbl_path = QtWidgets.QLabel(f"<span style='font-size: 10px; color: gray;'>Settings file: {settings_path}</span>", group_store)
        lbl_path.setWordWrap(True)
        lbl_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout_store.addWidget(lbl_path)

        hist = get_setting("command_history", [])
        self.lbl_hist_count = QtWidgets.QLabel(f"Command history: {len(hist)} saved prompts", group_store)
        layout_store.addWidget(self.lbl_hist_count)

        btn_clear_hist = QtWidgets.QPushButton("Clear Command History", group_store)
        btn_clear_hist.clicked.connect(self._on_clear_hist_clicked)
        layout_store.addWidget(btn_clear_hist)
        layout.addWidget(group_store)

        # Dialog Buttons
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel,
            self,
        )
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_clear_hist_clicked(self):
        clear_command_history()
        self.dock_widget.input_edit.clear_history()
        self.lbl_hist_count.setText("Command history: 0 saved prompts")
        QtWidgets.QMessageBox.information(self, "History Cleared", "Command history has been cleared.")

    def _on_save(self):
        # Save max turns setting
        max_turns = int(self.spin_max_turns.value())
        set_setting("max_turns", max_turns)
        if hasattr(self.dock_widget, "worker") and self.dock_widget.worker:
            self.dock_widget.worker.max_turns = max_turns

        # Save auto-save setting
        auto_save = self.chk_auto_save.isChecked()
        set_setting("auto_save_on_execute", auto_save)
        if hasattr(self.dock_widget, "act_auto_save"):
            self.dock_widget.act_auto_save.blockSignals(True)
            self.dock_widget.act_auto_save.setChecked(auto_save)
            self.dock_widget.act_auto_save.blockSignals(False)

        # Save model setting
        model_name = self.combo_model.currentText().strip()
        if model_name:
            set_setting("selected_model", model_name)
            self.dock_widget.model_combo.setCurrentText(model_name)

        # Save API key if provided
        key_text = self.txt_key.text().strip()
        if key_text:
            try:
                param = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/AICopilot")
                param.SetString("GeminiApiKey", key_text)
                self.dock_widget.worker.set_api_key(key_text)
                self.dock_widget._refresh_models_from_api()
            except Exception as e:
                logger.warning(f"Could not save Gemini API key: {e}")

        self.accept()


# ── AI Copilot Dock Widget ───────────────────────────────────────────

class AICopilotDockWidget(QtWidgets.QDockWidget):
    """Native FreeCAD dock widget hosting the embedded AI Copilot assistant."""

    sig_models_discovered = QtCore.Signal(list)
    _active_turn_card: Optional[Any] = None
    chat_stream: Optional[Any] = None

    def __init__(self, parent=None):
        super().__init__("AI Copilot", parent)
        self.setObjectName("AICopilotDockWidget")
        self.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)

        self.tool_bridge = DirectToolBridge()
        self.worker = CopilotAgentWorker(self.tool_bridge, parent=self)
        self._current_assistant_buffer = ""
        self._active_turn_card: Optional[TurnCardWidget] = None
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
        saved_model = get_setting("selected_model", self.worker.model_name)
        if saved_model and saved_model not in DEFAULT_GEMINI_MODELS:
            self.model_combo.addItem(saved_model)
        self.model_combo.setCurrentText(saved_model)
        self.worker.set_model_name(saved_model)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.model_combo.activated.connect(lambda _: self._dismiss_error_banner())
        toolbar.addWidget(self.model_combo, stretch=1)

        self.btn_undo = QtWidgets.QPushButton("↩ Undo")
        self.btn_undo.setToolTip("Roll back the last document transaction (Ctrl+Z)")
        self.btn_undo.clicked.connect(self._on_undo_clicked)
        toolbar.addWidget(self.btn_undo)

        self.btn_clear = QtWidgets.QPushButton("🗑 Clear")
        self.btn_clear.setToolTip("Clear conversation history")
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        toolbar.addWidget(self.btn_clear)

        # Settings Gear Button with popup menu
        self.btn_settings = QtWidgets.QToolButton()
        self.btn_settings.setText("⚙")
        self.btn_settings.setToolTip("Settings")
        self.btn_settings.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btn_settings.setStyleSheet("font-size: 13px; font-weight: bold; padding: 2px 6px;")

        self.settings_menu = QtWidgets.QMenu(self.btn_settings)

        self.act_auto_save = QtGui.QAction("Auto-Save Before Execution", self)
        self.act_auto_save.setCheckable(True)
        self.act_auto_save.setChecked(get_setting("auto_save_on_execute", False))
        self.act_auto_save.setToolTip("Automatically save active document before executing code or risky operations")
        self.act_auto_save.toggled.connect(self._on_auto_save_toggled)
        self.settings_menu.addAction(self.act_auto_save)

        self.settings_menu.addSeparator()

        self.act_api_key = self.settings_menu.addAction("Gemini API Key...")
        self.act_api_key.triggered.connect(self._on_settings_clicked)

        self.act_clear_hist = self.settings_menu.addAction("Clear Command History")
        self.act_clear_hist.triggered.connect(self._on_clear_command_history)

        self.act_clear_conv = self.settings_menu.addAction("Clear Conversation")
        self.act_clear_conv.triggered.connect(self._on_clear_clicked)

        self.settings_menu.addSeparator()

        self.act_open_dialog = self.settings_menu.addAction("Settings Dialog...")
        self.act_open_dialog.triggered.connect(self._on_open_settings_dialog)

        self.btn_settings.setMenu(self.settings_menu)
        toolbar.addWidget(self.btn_settings)

        layout.addLayout(toolbar)

        # ── Live Selection Badge ─────────────────────────────────────
        palette = get_theme_palette(self)
        self.selection_label = QtWidgets.QLabel("🎯 Selection: None")
        self.selection_label.setStyleSheet(
            f"background: {palette['badge_none_bg']}; color: {palette['badge_none_fg']}; "
            f"border: 1px solid {palette['badge_none_border']}; border-radius: 4px; padding: 4px 6px; font-size: 11px;"
        )
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)

        # ── Stream Viewport (Sequential Turn Cards) ──────────────────
        self.chat_stream = ChatStreamWidget()
        layout.addWidget(self.chat_stream, stretch=1)

        # ── Status Bar ───────────────────────────────────────────────
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("color: gray; font-size: 11px; padding: 2px 4px;")
        layout.addWidget(self.status_label)

        # ── Error Banner (Dismissible) ──────────────────────────────
        self.error_frame = QtWidgets.QFrame()
        self.error_frame.setObjectName("ErrorBanner")
        self.error_frame.setStyleSheet(
            f"#ErrorBanner {{ background: {palette['res_err_bg']}; border: 1px solid {palette['res_err_border']}; "
            f"border-radius: 4px; padding: 2px 4px; }}"
        )
        error_layout = QtWidgets.QHBoxLayout(self.error_frame)
        error_layout.setContentsMargins(6, 4, 6, 4)
        error_layout.setSpacing(6)

        self.error_icon = QtWidgets.QLabel("⚠️")
        self.error_icon.setStyleSheet("font-size: 13px;")
        error_layout.addWidget(self.error_icon)

        self.error_label = QtWidgets.QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {palette['res_err_fg']}; font-size: 11px; font-weight: 500;")
        error_layout.addWidget(self.error_label, stretch=1)

        self.btn_dismiss_error = QtWidgets.QPushButton("✕")
        self.btn_dismiss_error.setToolTip("Dismiss error")
        self.btn_dismiss_error.setFixedSize(18, 18)
        self.btn_dismiss_error.setStyleSheet(
            f"QPushButton {{ border: none; font-size: 11px; font-weight: bold; color: {palette['badge_none_fg']}; background: transparent; }} "
            f"QPushButton:hover {{ color: {palette['res_err_fg']}; background: {palette['res_err_bg']}; border-radius: 9px; }}"
        )
        self.btn_dismiss_error.clicked.connect(self._dismiss_error_banner)
        error_layout.addWidget(self.btn_dismiss_error)

        self.error_frame.setVisible(False)
        layout.addWidget(self.error_frame)

        # ── Input Area ───────────────────────────────────────────────
        input_layout = QtWidgets.QHBoxLayout()
        input_layout.setSpacing(4)

        self.input_edit = ChatInputTextEdit()
        self.input_edit.setPlaceholderText("Ask AI Copilot or request CAD action (Enter to send, Ctrl+Alt+Up/Down for history)...")
        self.input_edit.setFixedHeight(65)
        self.input_edit.sig_submit.connect(self._on_send_clicked)
        self.input_edit.textChanged.connect(self._on_input_text_changed)
        self.input_edit.set_history(get_setting("command_history", []))
        input_layout.addWidget(self.input_edit, stretch=1)

        # Up/Down history navigation buttons (mouse users)
        hist_btn_col = QtWidgets.QVBoxLayout()
        hist_btn_col.setSpacing(2)

        self.btn_hist_prev = QtWidgets.QToolButton()
        self.btn_hist_prev.setText("▲")
        self.btn_hist_prev.setToolTip("Previous prompt (Ctrl+Alt+Up)")
        self.btn_hist_prev.setFixedSize(24, 28)
        self.btn_hist_prev.clicked.connect(self.input_edit.navigate_history_prev)
        hist_btn_col.addWidget(self.btn_hist_prev)

        self.btn_hist_next = QtWidgets.QToolButton()
        self.btn_hist_next.setText("▼")
        self.btn_hist_next.setToolTip("Next prompt (Ctrl+Alt+Down)")
        self.btn_hist_next.setFixedSize(24, 28)
        self.btn_hist_next.clicked.connect(self.input_edit.navigate_history_next)
        hist_btn_col.addWidget(self.btn_hist_next)

        input_layout.addLayout(hist_btn_col)

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
        if hasattr(self.worker, "sig_thought"):
            self.worker.sig_thought.connect(self._on_thought_received)
        self.worker.sig_token.connect(self._on_token_received)
        if hasattr(self.worker, "sig_notice"):
            self.worker.sig_notice.connect(self._on_notice_received)
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
        palette = get_theme_palette(self)
        summary = self._get_selection_summary()
        if summary:
            self.selection_label.setText(f"🎯 <b>Selected:</b> {html.escape(summary)}")
            self.selection_label.setStyleSheet(
                f"background: {palette['badge_sel_bg']}; color: {palette['badge_sel_fg']}; "
                f"border: 1px solid {palette['badge_sel_border']}; border-radius: 4px; padding: 4px 6px; font-size: 11px;"
            )
        else:
            self.selection_label.setText("🎯 Selection: None")
            self.selection_label.setStyleSheet(
                f"background: {palette['badge_none_bg']}; color: {palette['badge_none_fg']}; "
                f"border: 1px solid {palette['badge_none_border']}; border-radius: 4px; padding: 4px 6px; font-size: 11px;"
            )

    # ── Chat Actions & Formatting ────────────────────────────────────

    def _on_model_changed(self, model_name: str):
        self._dismiss_error_banner()
        self.worker.set_model_name(model_name)
        set_setting("selected_model", model_name)

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
        self.input_edit.append_history(prompt)
        append_command_history(prompt)
        self.input_edit.clear()
        self.btn_send.setEnabled(False)
        self.btn_stop.setEnabled(True)

        selection_summary = self._get_selection_summary()
        selection_ctx = f"[3D View Selection: {selection_summary}]" if selection_summary else None

        self._active_turn_card = TurnCardWidget(prompt, selection_summary)
        self.chat_stream.add_turn_card(self._active_turn_card)
        self._current_assistant_buffer = ""

        # Open atomic undo transaction for this user turn
        self.tool_bridge.begin_turn_transaction(prompt)

        # Enqueue prompt to background worker with configured max_turns
        max_turns = int(get_setting("max_turns", 30))
        self.worker.submit_prompt(prompt, selection_ctx, max_turns=max_turns)

    def _on_stop_clicked(self):
        self.worker.stop()
        self.tool_bridge.abort_turn_transaction()
        self.status_label.setText("Stopping...")
        if self._active_turn_card:
            stop_msg = (self._current_assistant_buffer + "\n\n*(Operation stopped by user)*").strip()
            self._active_turn_card.finish_turn(stop_msg, {})
            self._active_turn_card = None
        self.btn_stop.setEnabled(False)
        self.btn_send.setEnabled(True)

    def _on_clear_clicked(self):
        self.worker.clear_history()
        self.chat_stream.clear()
        self._active_turn_card = None
        self._current_assistant_buffer = ""
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

    def _on_auto_save_toggled(self, checked: bool):
        set_setting("auto_save_on_execute", checked)
        state_str = "enabled" if checked else "disabled"
        self._append_system_message(f"Auto-save before execution {state_str}.")

    def _on_clear_command_history(self):
        clear_command_history()
        self.input_edit.clear_history()
        self._append_system_message("Command history cleared.")

    def _on_open_settings_dialog(self):
        dialog = CopilotSettingsDialog(self, parent=self)
        dialog.exec()

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

    def _on_thought_received(self, token: str):
        if self._active_turn_card:
            self._active_turn_card.ensure_thought_section().append_thought(token)

    def _on_token_received(self, token: str):
        if token.startswith("<div style="):
            self._on_notice_received(token)
            return

        if self._active_turn_card:
            if self._active_turn_card.work_section and not self._current_assistant_buffer:
                self._active_turn_card.work_section.set_collapsed(True)
            self._active_turn_card.append_response_token(token)

        self._current_assistant_buffer += token

    def _on_notice_received(self, notice: str):
        if self._active_turn_card:
            self._active_turn_card.ensure_work_section().add_notice(notice)

    def _on_status_changed(self, status: str):
        self.status_label.setText(status)

    def _on_tool_started(self, tool_name: str, args: dict):
        if self._active_turn_card:
            if self._active_turn_card.thought_section:
                self._active_turn_card.thought_section.set_collapsed(True)
            self._active_turn_card.ensure_work_section().add_tool_call(tool_name, args)

    def _on_tool_finished(self, tool_name: str, result_str: str):
        if self._active_turn_card:
            self._active_turn_card.ensure_work_section().add_tool_result(tool_name, result_str)

    def _on_turn_complete(self, full_response: str, metrics: Optional[dict] = None):
        self._last_submitted_prompt = None
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.tool_bridge.commit_turn_transaction()
        if not self.error_frame.isVisible():
            self.status_label.setText("Ready")

        if self._active_turn_card:
            self._active_turn_card.finish_turn(full_response, metrics or {})
            self._active_turn_card = None

        self._current_assistant_buffer = ""

    def _on_error(self, error_msg: str):
        self.tool_bridge.abort_turn_transaction()
        cleaned_msg = format_user_friendly_error(error_msg)
        self.error_label.setText(cleaned_msg)
        self.error_frame.setVisible(True)

        if self._active_turn_card:
            self._active_turn_card.show_error(cleaned_msg)
            self._active_turn_card = None

        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("Error")

        # Restore prompt on error so user can retry
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
        card = TurnCardWidget(text, selection_badge)
        self.chat_stream.add_turn_card(card)
        self._active_turn_card = card

    def _append_system_message(self, msg_html: str):
        self.chat_stream.add_system_message(msg_html)

    def _append_html(self, html_content: str):
        self.chat_stream.add_system_message(html_content)
