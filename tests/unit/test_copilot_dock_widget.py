"""Unit tests for FreeCAD AI Copilot embedded in-process UI and tool bridge."""

import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def test_tool_call_request_sync():
    from AICopilot.ui.agent_worker import ToolCallRequest

    req = ToolCallRequest("part_operations", {"operation": "box"})
    assert req.tool_name == "part_operations"
    assert req.args == {"operation": "box"}
    assert req.result is None

    # Simulate worker signaling main thread and resolving
    req.set_result(json.dumps({"success": True}))
    assert req.wait(timeout=1.0) is True
    assert req.result == '{"success": true}'


def test_tool_call_request_exception():
    from AICopilot.ui.agent_worker import ToolCallRequest

    req = ToolCallRequest("test_tool", {})
    req.set_exception(RuntimeError("CAD error"))
    assert req.wait(timeout=1.0) is True
    assert isinstance(req.exception, RuntimeError)


def test_direct_tool_bridge_discovery():
    from AICopilot.ui.tool_bridge import DirectToolBridge

    bridge = DirectToolBridge()
    declarations = bridge.get_tool_declarations()
    assert len(declarations) >= 9
    names = [s["name"] for s in declarations]
    assert "partdesign_operations" in names
    assert "cam_operations" in names
    assert "spreadsheet_operations" in names
    assert "execute_python" in names


def test_direct_tool_bridge_execution(mock_freecad):
    import AICopilot.ui.tool_bridge as tb

    doc = MagicMock()
    mock_freecad.ActiveDocument = doc
    tb.FreeCAD.ActiveDocument = doc

    fake_server = MagicMock()
    fake_server.spreadsheet_ops.get.return_value = {"status": "ok"}

    bridge = tb.DirectToolBridge(server=fake_server)
    result = bridge.execute_tool("spreadsheet_operations", {"operation": "get", "alias": "width"})
    fake_server.spreadsheet_ops.get.assert_called_once_with({"operation": "get", "alias": "width"})
    parsed = json.loads(result)
    assert parsed["status"] == "ok"
    doc.openTransaction.assert_called_once()
    doc.commitTransaction.assert_called_once()


def test_init_gui_dock_widget_lifecycle(mock_freecad, monkeypatch):
    import importlib.util

    mock_freecad.GuiUp = True
    main_win = MagicMock()
    main_win.findChild.return_value = None

    fc_gui = sys.modules["FreeCADGui"]
    fc_gui.getMainWindow = MagicMock(return_value=main_win)
    fc_gui.addCommand = MagicMock()

    init_gui_path = os.path.join(os.path.dirname(__file__), "..", "..", "AICopilot", "InitGui.py")
    spec = importlib.util.spec_from_file_location("InitGui_test_dock", init_gui_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    service = module.GlobalAIService()

    # Mock server to avoid network binding
    mock_server = MagicMock()
    mock_server.start_server.return_value = True
    mock_server.instance_uuid = "dock-test-uuid"
    mock_server.socket_path = "/tmp/dock_test.sock"
    monkeypatch.setattr("freecad_mcp_handler.FreeCADSocketServer", lambda: mock_server)
    monkeypatch.setattr("instance_registry.write_discovery", MagicMock())
    monkeypatch.setattr("instance_registry.sweep_stale_sockets", MagicMock(return_value=0))

    # Mock AICopilotDockWidget to avoid full Qt window creation in headless test
    fake_dock = MagicMock()
    with patch("AICopilot.ui.dock_widget.AICopilotDockWidget", return_value=fake_dock):
        service.start()
        assert service.is_running is True
        assert service.dock_widget == fake_dock
        main_win.addDockWidget.assert_called_once()

        # Stop service and check cleanup
        service.stop()
        assert service.is_running is False
        fake_dock.close.assert_called_once()
        fake_dock.deleteLater.assert_called_once()
        assert service.dock_widget is None


def test_copilot_agent_worker_model_default_and_setter():
    from AICopilot.ui.agent_worker import CopilotAgentWorker

    worker = CopilotAgentWorker(tool_bridge=MagicMock())
    assert worker.model_name == "gemini-3.6-flash"

    worker.set_model_name("models/gemini-3.8-flash")
    assert worker.model_name == "gemini-3.8-flash"

    worker.set_model_name("gemini-3.7-flash")
    assert worker.model_name == "gemini-3.7-flash"


def test_copilot_dock_widget_default_models():
    from AICopilot.ui.dock_widget import DEFAULT_GEMINI_MODELS

    assert "gemini-3.6-flash" in DEFAULT_GEMINI_MODELS
    assert "gemini-3.7-flash" in DEFAULT_GEMINI_MODELS
    assert "gemini-3.8-flash" in DEFAULT_GEMINI_MODELS
    assert "gemini-3.1-pro-preview" in DEFAULT_GEMINI_MODELS


def test_format_user_friendly_error():
    from AICopilot.ui.dock_widget import format_user_friendly_error

    # Test 404 with JSON dict
    raw_404 = (
        "Agent Error: 404 NOT_FOUND. {'error': {'code': 404, 'message': "
        "'This model models/gemini-2.5-flash is no longer available to new users. "
        "Please update your code to use models/gemini-3.6-flash.', 'status': 'NOT_FOUND'}}"
    )
    res_404 = format_user_friendly_error(raw_404)
    assert "Model Unavailable (404)" in res_404
    assert "gemini-3.6-flash" in res_404
    assert "{'error':" not in res_404

    # Test 503 with JSON dict
    raw_503 = (
        "503 UNAVAILABLE. {'error': {'code': 503, 'message': "
        "'This model is currently experiencing high demand. Spikes in demand are usually temporary.', 'status': 'UNAVAILABLE'}}"
    )
    res_503 = format_user_friendly_error(raw_503)
    assert "Model Busy (503)" in res_503
    assert "high demand" in res_503
    assert "{'error':" not in res_503

    # Test missing API key
    raw_key = "Gemini API Key is missing. Please set the GEMINI_API_KEY environment variable"
    res_key = format_user_friendly_error(raw_key)
    assert "⚙ Key" in res_key


def test_copilot_agent_worker_503_fallback(monkeypatch):
    from AICopilot.ui.agent_worker import CopilotAgentWorker

    worker = CopilotAgentWorker(tool_bridge=MagicMock(), model_name="gemini-3.8-flash")
    worker.api_key = "fake-key"

    fake_client = MagicMock()
    first_call = True

    def fake_generate_content(model, contents, config):
        nonlocal first_call
        if first_call and model == "gemini-3.8-flash":
            first_call = False
            raise RuntimeError("503 UNAVAILABLE: This model is currently experiencing high demand.")
        mock_resp = MagicMock()
        mock_cand = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "Fallback success"
        mock_part.function_call = None
        mock_cand.content.parts = [mock_part]
        mock_resp.candidates = [mock_cand]
        return mock_resp

    fake_client.models.generate_content.side_effect = fake_generate_content

    # Mock google.genai module
    fake_genai = MagicMock()
    fake_genai.Client.return_value = fake_client
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", MagicMock())

    tokens = []
    worker.sig_token.connect(tokens.append)
    complete = []
    worker.sig_turn_complete.connect(complete.append)

    worker._process_task({"prompt": "Hello test", "selection": None})

    # Should have emitted a fallback notice token and the final response
    assert any("experiencing high demand (503)" in t for t in tokens)
    assert any("Fallback success" in t for t in tokens)
    assert len(complete) == 1


def test_dock_widget_error_handling_and_prompt_retention():
    from AICopilot.ui.dock_widget import AICopilotDockWidget

    mock_widget = MagicMock(spec=AICopilotDockWidget)
    mock_widget._last_submitted_prompt = "Create a parametric cylinder with r=10"
    mock_widget.input_edit = MagicMock()
    mock_widget.input_edit.toPlainText.return_value = ""
    mock_widget.error_frame = MagicMock()
    mock_widget.error_label = MagicMock()
    mock_widget.status_label = MagicMock()
    mock_widget.btn_send = MagicMock()
    mock_widget.btn_stop = MagicMock()
    mock_widget._append_html = MagicMock()

    AICopilotDockWidget._on_error(mock_widget, "503 UNAVAILABLE. {'error': {'message': 'High demand'}}")

    mock_widget.input_edit.setPlainText.assert_called_once_with("Create a parametric cylinder with r=10")
    mock_widget.error_frame.setVisible.assert_called_once_with(True)
    mock_widget.error_label.setText.assert_called_once()
    assert "High demand" in mock_widget.error_label.setText.call_args[0][0]
    assert "{'error':" not in mock_widget.error_label.setText.call_args[0][0]




