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
    fake_server._execute_tool.return_value = json.dumps({"status": "ok"})

    bridge = tb.DirectToolBridge(server=fake_server)
    result = bridge.execute_tool("spreadsheet_operations", {"operation": "get", "alias": "width"})
    fake_server._execute_tool.assert_called_once_with("spreadsheet_operations", {"operation": "get", "alias": "width"})
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
