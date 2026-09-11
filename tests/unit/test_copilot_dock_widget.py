import pytest

@pytest.fixture(scope="session", autouse=True)
def qapp():
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide import QtWidgets
    if hasattr(QtWidgets, "QApplication"):
        if QtWidgets.QApplication.instance() is None:
            app = QtWidgets.QApplication(["pytest", "-platform", "offscreen"])
            yield app
        else:
            yield QtWidgets.QApplication.instance()
    else:
        yield None
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
    worker.sig_turn_complete.connect(lambda res, *_: complete.append(res))

    worker._process_task({"prompt": "Hello test", "selection": None})

    # Should have emitted a fallback notice token and the final response
    assert any("experiencing high demand (503)" in t for t in tokens)
    assert any("Fallback success" in t for t in tokens)
    assert len(complete) == 1


def test_dock_widget_error_handling_and_prompt_retention():
    from AICopilot.ui.dock_widget import AICopilotDockWidget

    mock_widget = MagicMock(spec=AICopilotDockWidget)
    mock_widget.tool_bridge = MagicMock()
    mock_widget._last_submitted_prompt = "Create a parametric cylinder with r=10"
    mock_widget.input_edit = MagicMock()
    mock_widget.input_edit.toPlainText.return_value = ""
    mock_widget.error_frame = MagicMock()
    mock_widget.error_label = MagicMock()
    mock_widget.status_label = MagicMock()
    mock_widget.btn_send = MagicMock()
    mock_widget.btn_stop = MagicMock()
    mock_widget._append_html = MagicMock()
    mock_widget.chat_stream = MagicMock()

    AICopilotDockWidget._on_error(mock_widget, "503 UNAVAILABLE. {'error': {'message': 'High demand'}}")

    mock_widget.tool_bridge.abort_turn_transaction.assert_called_once()
    mock_widget.input_edit.setPlainText.assert_called_once_with("Create a parametric cylinder with r=10")
    mock_widget.error_frame.setVisible.assert_called_once_with(True)
    mock_widget.error_label.setText.assert_called_once()
    assert "High demand" in mock_widget.error_label.setText.call_args[0][0]
    assert "{'error':" not in mock_widget.error_label.setText.call_args[0][0]


def test_format_user_friendly_error_internal_quotes():
    from AICopilot.ui.dock_widget import format_user_friendly_error

    raw_400 = (
        "Agent Error: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': "
        "\"Role 'tool' is not supported. Please use a valid role: SYSTEM, USER, MODEL.\", 'status': 'INVALID_ARGUMENT'}}"
    )
    res_400 = format_user_friendly_error(raw_400)
    assert "API Error (400)" in res_400
    assert "Role 'tool' is not supported" in res_400
    assert res_400 != "Role"
    assert "{'error':" not in res_400


def test_copilot_agent_worker_function_response_role_user(monkeypatch):
    from AICopilot.ui.agent_worker import CopilotAgentWorker

    worker = CopilotAgentWorker(tool_bridge=MagicMock())
    worker.api_key = "fake-key"

    fake_client = MagicMock()
    call_count = 0

    def fake_generate_content(model, contents, config):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_cand = MagicMock()
        mock_part = MagicMock()

        if call_count == 1:
            mock_call = MagicMock()
            mock_call.name = "spatial_query"
            mock_call.args = {"query_type": "top_face", "object_name": "Body"}
            mock_part.text = None
            mock_part.function_call = mock_call
        else:
            mock_part.text = "The top face is Face6"
            mock_part.function_call = None

        mock_cand.content = MagicMock()
        mock_cand.content.parts = [mock_part]
        mock_resp.candidates = [mock_cand]
        return mock_resp

    fake_client.models.generate_content.side_effect = fake_generate_content

    fake_genai = MagicMock()
    fake_genai.Client.return_value = fake_client

    class FakeContent:
        def __init__(self, role, parts):
            self.role = role
            self.parts = parts

    class FakePart:
        @staticmethod
        def from_text(text):
            return text

        @staticmethod
        def from_function_response(name, response):
            return {"name": name, "response": response}

    fake_types = MagicMock()
    fake_types.Content = FakeContent
    fake_types.Part = FakePart
    fake_genai.types = fake_types

    import google

    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setattr(google, "genai", fake_genai, raising=False)

    # Wire signal to immediately fulfill main thread tool request
    worker.sig_request_main_thread_tool.connect(lambda req: req.set_result('{"face": "Face6"}'))

    worker._process_task({"prompt": "Find top face", "selection": None})

    # Verify history contains function response with role="user"
    assert len(worker.history) >= 3
    tool_resp_content = worker.history[2]
    assert getattr(tool_resp_content, "role", None) == "user"


def test_direct_tool_bridge_spatial_query_dispatch(mock_freecad):
    import AICopilot.ui.tool_bridge as tb

    doc = MagicMock()
    mock_freecad.ActiveDocument = doc
    tb.FreeCAD.ActiveDocument = doc

    fake_server = MagicMock()
    fake_server.spatial_ops.top_face.return_value = json.dumps({"top_face": "Face6"})

    bridge = tb.DirectToolBridge(server=fake_server)

    # 1. Dispatch via query_type
    res1 = bridge.execute_tool("spatial_query", {"query_type": "top_face", "object_name": "Body"})
    fake_server.spatial_ops.top_face.assert_called_once()
    assert json.loads(res1)["top_face"] == "Face6"

    # 2. Dispatch via operation
    fake_server.spatial_ops.top_face.reset_mock()
    res2 = bridge.execute_tool("spatial_query", {"operation": "top_face", "object_name": "Body"})
    fake_server.spatial_ops.top_face.assert_called_once()
    assert json.loads(res2)["top_face"] == "Face6"


def test_dock_widget_turn_transaction_lifecycle():
    from AICopilot.ui.dock_widget import AICopilotDockWidget

    mock_widget = MagicMock(spec=AICopilotDockWidget)
    mock_widget.tool_bridge = MagicMock()
    mock_widget.worker = MagicMock()
    mock_widget.input_edit = MagicMock()
    mock_widget.input_edit.toPlainText.return_value = "Create a 20mm pocket"
    mock_widget.error_frame = MagicMock()
    mock_widget.error_frame.isVisible.return_value = False
    mock_widget.status_label = MagicMock()
    mock_widget.btn_send = MagicMock()
    mock_widget.btn_stop = MagicMock()
    mock_widget._get_selection_summary = MagicMock(return_value=None)
    mock_widget._append_user_message = MagicMock()
    mock_widget._append_html = MagicMock()
    mock_widget.chat_stream = MagicMock()

    # 1. Send starts turn transaction
    AICopilotDockWidget._on_send_clicked(mock_widget)
    mock_widget.tool_bridge.begin_turn_transaction.assert_called_once_with("Create a 20mm pocket")
    mock_widget.worker.submit_prompt.assert_called_once()

    # 2. Complete commits turn transaction
    AICopilotDockWidget._on_turn_complete(mock_widget, "Pocket created.")
    mock_widget.tool_bridge.commit_turn_transaction.assert_called_once()

    # 3. Stop aborts turn transaction
    AICopilotDockWidget._on_stop_clicked(mock_widget)
    mock_widget.worker.stop.assert_called_once()
    mock_widget.tool_bridge.abort_turn_transaction.assert_called_once()


def test_direct_tool_bridge_atomic_turn_transaction(mock_freecad):
    import AICopilot.ui.tool_bridge as tb

    doc = MagicMock()
    mock_freecad.ActiveDocument = doc
    tb.FreeCAD.ActiveDocument = doc

    fake_server = MagicMock()
    fake_server.partdesign_ops.pocket.return_value = {"status": "ok"}

    bridge = tb.DirectToolBridge(server=fake_server)

    # Begin atomic turn transaction
    bridge.begin_turn_transaction("Create pocket")
    assert bridge._in_turn_transaction is True
    doc.openTransaction.assert_called_once_with("AI: Create pocket")

    # Mutating tool executed during turn does NOT open/commit micro-transactions
    doc.openTransaction.reset_mock()
    doc.commitTransaction.reset_mock()
    doc.abortTransaction.reset_mock()

    res = bridge.execute_tool("partdesign_operations", {"operation": "pocket", "depth": 20})
    fake_server.partdesign_ops.pocket.assert_called_once()
    # Micro-transactions skipped:
    doc.openTransaction.assert_not_called()
    doc.commitTransaction.assert_not_called()
    doc.abortTransaction.assert_not_called()
    # Recompute called for live update
    doc.recompute.assert_called()

    # Commit turn transaction
    bridge.commit_turn_transaction()
    assert bridge._in_turn_transaction is False
    doc.commitTransaction.assert_called_once()

    # Now test abort turn transaction
    doc.openTransaction.reset_mock()
    doc.commitTransaction.reset_mock()
    doc.abortTransaction.reset_mock()

    bridge.begin_turn_transaction("Failing turn")
    assert bridge._in_turn_transaction is True
    bridge.abort_turn_transaction()
    assert bridge._in_turn_transaction is False
    doc.abortTransaction.assert_called_once()


def test_copilot_agent_worker_429_retry(monkeypatch):
    import time
    from AICopilot.ui.agent_worker import CopilotAgentWorker

    worker = CopilotAgentWorker(tool_bridge=MagicMock())
    worker.api_key = "fake-key"

    fake_client = MagicMock()
    first_call = True

    def fake_generate_content(model, contents, config):
        nonlocal first_call
        if first_call:
            first_call = False
            raise RuntimeError(
                "429 RESOURCE_EXHAUSTED: Quota exceeded for metric: Please retry in 0.1s"
            )
        mock_resp = MagicMock()
        mock_cand = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "Success after 429 backoff"
        mock_part.function_call = None
        mock_cand.content.parts = [mock_part]
        mock_resp.candidates = [mock_cand]
        return mock_resp

    fake_client.models.generate_content.side_effect = fake_generate_content

    fake_genai = MagicMock()
    fake_genai.Client.return_value = fake_client
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", MagicMock())
    monkeypatch.setattr(time, "sleep", lambda s: None)

    tokens = []
    worker.sig_token.connect(tokens.append)
    complete = []
    worker.sig_turn_complete.connect(lambda res, *_: complete.append(res))

    worker._process_task({"prompt": "Make pocket", "selection": None})

    assert any("Rate limit reached" in t for t in tokens)
    assert any("Success after 429 backoff" in t for t in tokens)
    assert len(complete) == 1
    assert complete[0] == "Success after 429 backoff"








def test_collapsible_section_toggle():
    from AICopilot.ui.dock_widget import CollapsibleSection

    sec = CollapsibleSection("Test Section")
    sec.show()
    assert sec._is_expanded is True
    assert "▼" in sec.toggle_btn.text()
    assert sec.content_frame.isVisible() is True

    # Collapse
    sec.set_collapsed(True)
    assert sec._is_expanded is False
    assert "▶" in sec.toggle_btn.text()
    assert sec.content_frame.isVisible() is False

    # Expand
    sec.set_collapsed(False)
    assert sec._is_expanded is True
    assert "▼" in sec.toggle_btn.text()
    assert sec.content_frame.isVisible() is True


def test_thought_section_lifecycle():
    from AICopilot.ui.dock_widget import ThoughtSection

    ts = ThoughtSection()
    assert "Thinking..." in ts.toggle_btn.text()
    assert ts._is_expanded is True

    ts.append_thought("Analyzing requirements...")
    assert "Analyzing requirements..." in ts.thought_edit.toPlainText()

    ts.finish(duration=1.4)
    assert "Thought (1.4s)" in ts.toggle_btn.text()
    assert ts._is_expanded is False
    assert ts.content_frame.isVisible() is False


def test_work_section_lifecycle():
    from AICopilot.ui.dock_widget import WorkSection

    ws = WorkSection()
    assert "Working..." in ws.toggle_btn.text()
    assert ws._is_expanded is True

    ws.add_tool_call("spatial_query", {"object_name": "Body", "query_type": "top_face"})
    assert ws._tool_count == 1
    assert "Working (1 command)..." in ws.toggle_btn.text()

    ws.add_tool_result("spatial_query", '{"top_face": "Face6"}')

    ws.add_notice("Model busy notice")

    ws.finish(duration=3.8, count=1)
    assert "Worked for 3.8s (Ran 1 command)" in ws.toggle_btn.text()
    assert ws._is_expanded is False
    assert ws.content_frame.isVisible() is False


def test_turn_card_widget_flow():
    from AICopilot.ui.dock_widget import TurnCardWidget

    card = TurnCardWidget("Create a 20mm pocket", "Body (Face6)")
    card.show()
    assert card.thought_section is None
    assert card.work_section is None

    # Lazy thought creation
    t = card.ensure_thought_section()
    assert card.thought_section is t
    t.append_thought("Thinking step")

    # Lazy work creation
    w = card.ensure_work_section()
    assert card.work_section is w
    w.add_tool_call("partdesign_operations", {"operation": "pocket", "depth": 20})

    # Assistant response streaming
    card.append_response_token("Pocket created ")
    card.append_response_token("successfully.")
    assert card.response_label.isVisible() is True

    # Finish turn
    card.finish_turn(
        "Pocket created successfully.",
        {"thought_duration": 1.2, "work_duration": 2.5, "tool_count": 1},
    )
    assert t._is_expanded is False
    assert w._is_expanded is False
    assert "Thought (1.2s)" in t.toggle_btn.text()
    assert "Worked for 2.5s (Ran 1 command)" in w.toggle_btn.text()


def test_chat_stream_widget():
    from AICopilot.ui.dock_widget import ChatStreamWidget, TurnCardWidget

    stream = ChatStreamWidget()
    assert stream.layout.count() == 1  # stretch item

    card = TurnCardWidget("Hello")
    stream.add_turn_card(card)
    assert stream.layout.count() == 2

    stream.add_system_message("History cleared")
    assert stream.layout.count() == 3

    stream.clear()
    assert stream.layout.count() == 1  # only stretch remains


def test_formatted_code_box():
    from AICopilot.ui.dock_widget import FormattedCodeBox

    code = "import FreeCAD\ndoc = FreeCAD.newDocument()\ndoc.recompute()"
    box = FormattedCodeBox(code)
    box.show()
    assert "import FreeCAD" in box.code_edit.toPlainText()
    assert box.code_edit.isReadOnly() is True
    assert box.code_edit.height() >= 50


def test_formatted_result_card_success():
    from PySide6 import QtWidgets
    from AICopilot.ui.dock_widget import FormattedResultCard

    raw_json = '{"top_face": "Face6", "normal": [0.0, 0.0, 1.0], "area": 1600.0}'
    card = FormattedResultCard("spatial_query", raw_json)
    card.show()
    # Check that Result is rendered and not Error
    labels = card.findChildren(QtWidgets.QLabel)
    assert any("Result" in l.text() for l in labels)


def test_formatted_result_card_error():
    from PySide6 import QtWidgets
    from AICopilot.ui.dock_widget import FormattedResultCard

    raw_err = '{"error": "Sketch not on face", "status": "error", "code": 400}'
    card = FormattedResultCard("sketch_operations", raw_err)
    card.show()
    labels = card.findChildren(QtWidgets.QLabel)
    assert any("Error" in l.text() for l in labels)


def test_work_section_execute_python_multiline():
    from AICopilot.ui.dock_widget import WorkSection, FormattedCodeBox

    ws = WorkSection()
    ws.show()
    py_code = "box = Part.makeBox(10, 10, 10)\nPart.show(box)"
    ws.add_tool_call("execute_python", {"code": py_code})
    assert ws._tool_count == 1

    # Should have instantiated FormattedCodeBox inside content_layout
    boxes = ws.content_frame.findChildren(FormattedCodeBox)
    assert len(boxes) == 1
    assert "makeBox" in boxes[0].code_edit.toPlainText()


def test_theme_palette_keys():
    from AICopilot.ui.dock_widget import get_theme_palette

    pal = get_theme_palette()
    assert "badge_sel_bg" in pal
    assert "badge_none_bg" in pal
    assert "user_box_bg" in pal
    assert "code_bg" in pal
    assert "res_success_bg" in pal
    assert "res_err_bg" in pal



def test_system_instruction_scripting_guidelines():
    from AICopilot.ui.agent_worker import SYSTEM_INSTRUCTION

    assert "PartDesign::AdditiveBox" in SYSTEM_INSTRUCTION
    assert "CRITICAL SKETCHER SYMMETRY RULE" in SYSTEM_INSTRUCTION
    assert "create_box" in SYSTEM_INSTRUCTION


def test_execute_python_cad_helpers(mock_freecad):
    from AICopilot.handlers.execute_python_ops import ExecutePythonOpsHandler

    handler = ExecutePythonOpsHandler()
    assert "create_box" in handler._python_namespace or hasattr(handler, "run_code")

    # Run code with create_box
    res = handler.run_code("box = create_box(100, 100, 100)")
    assert res.get("success") is True


def test_execute_python_geometry_health_validation(mock_freecad):
    from AICopilot.handlers.execute_python_ops import ExecutePythonOpsHandler

    doc = MagicMock()
    bad_obj = MagicMock()
    bad_obj.Name = "BadSketch"
    bad_obj.TypeId = "Sketcher::SketchObject"
    bad_obj.State = ["Touched", "Invalid"]
    bad_obj.isDerivedFrom.return_value = True
    bad_obj.solve.return_value = -4

    doc.Objects = [bad_obj]
    mock_freecad.ActiveDocument = doc

    handler = ExecutePythonOpsHandler()
    res = handler.run_code("x = 42")
    assert res.get("success") is False
    assert "Geometry validation failed" in res.get("error", "")
    assert "invalid constraints" in res.get("error", "")



def test_direct_tool_bridge_measurement_bounding_box(mock_freecad):
    import AICopilot.ui.tool_bridge as tb

    doc = MagicMock()
    mock_freecad.ActiveDocument = doc
    tb.FreeCAD.ActiveDocument = doc

    fake_server = MagicMock()
    fake_server.measurement_ops.get_bounding_box.return_value = "Bounding box of Cube: X: 0 to 100"

    bridge = tb.DirectToolBridge(server=fake_server)
    res = bridge.execute_tool("measurement_operations", {"operation": "bounding_box", "object_name": "Cube"})
    fake_server.measurement_ops.get_bounding_box.assert_called_once_with({"operation": "bounding_box", "object_name": "Cube"})
    assert "Bounding box of Cube" in res


def test_direct_tool_bridge_part_operations_create_box(mock_freecad):
    import AICopilot.ui.tool_bridge as tb

    doc = MagicMock()
    mock_freecad.ActiveDocument = doc
    tb.FreeCAD.ActiveDocument = doc

    fake_server = MagicMock()
    fake_server.primitives.create_box.return_value = "Created box: Box (100x100x100mm)"

    bridge = tb.DirectToolBridge(server=fake_server)
    res = bridge.execute_tool("part_operations", {"operation": "create_box", "length": 100, "width": 100, "height": 100})
    fake_server.primitives.create_box.assert_called_once_with({"operation": "create_box", "length": 100, "width": 100, "height": 100})
    assert "Created box" in res


def test_partdesign_create_body(mock_freecad):
    import AICopilot.handlers.base as b
    from AICopilot.handlers.partdesign_ops import PartDesignOpsHandler

    doc = MagicMock()
    body = MagicMock()
    body.Name = "Body"
    doc.addObject.return_value = body
    b.FreeCAD.ActiveDocument = doc
    mock_freecad.ActiveDocument = doc

    handler = PartDesignOpsHandler()
    res = handler.create_body({"name": "CustomBody"})
    assert "Created PartDesign Body: Body" in res
    doc.addObject.assert_called_once_with("PartDesign::Body", "CustomBody")


def test_partdesign_additive_box(mock_freecad):
    import AICopilot.handlers.base as b
    from AICopilot.handlers.partdesign_ops import PartDesignOpsHandler

    doc = MagicMock()
    body = MagicMock()
    body.Name = "Body"
    body.TypeId = "PartDesign::Body"
    doc.Objects = [body]
    box = MagicMock()
    box.Name = "Box"
    box.State = []
    body.newObject.return_value = box
    b.FreeCAD.ActiveDocument = doc
    mock_freecad.ActiveDocument = doc

    handler = PartDesignOpsHandler()
    res = handler.additive_box({"length": 100})
    assert "Created AdditiveBox: Box (100.00x100.00x100.00mm)" in res
    assert box.Length == 100.0
    assert box.Width == 100.0
    assert box.Height == 100.0


def test_partdesign_additive_cylinder(mock_freecad):
    import AICopilot.handlers.base as b
    from AICopilot.handlers.partdesign_ops import PartDesignOpsHandler

    doc = MagicMock()
    body = MagicMock()
    body.Name = "Body"
    body.TypeId = "PartDesign::Body"
    doc.Objects = [body]
    cyl = MagicMock()
    cyl.Name = "Cylinder"
    cyl.State = []
    body.newObject.return_value = cyl
    b.FreeCAD.ActiveDocument = doc
    mock_freecad.ActiveDocument = doc

    handler = PartDesignOpsHandler()
    res = handler.additive_cylinder({"radius": 20, "height": 40})
    assert "Created AdditiveCylinder: Cylinder" in res
    assert cyl.Radius == 20.0
    assert cyl.Height == 40.0


def test_partdesign_additive_sphere(mock_freecad):
    import AICopilot.handlers.base as b
    from AICopilot.handlers.partdesign_ops import PartDesignOpsHandler

    doc = MagicMock()
    body = MagicMock()
    body.Name = "Body"
    body.TypeId = "PartDesign::Body"
    doc.Objects = [body]
    sph = MagicMock()
    sph.Name = "Sphere"
    sph.State = []
    body.newObject.return_value = sph
    b.FreeCAD.ActiveDocument = doc
    mock_freecad.ActiveDocument = doc

    handler = PartDesignOpsHandler()
    res = handler.additive_sphere({"radius": 15})
    assert "Created AdditiveSphere: Sphere" in res
    assert sph.Radius == 15.0


def test_direct_tool_bridge_partdesign_additive_box(mock_freecad):
    import AICopilot.ui.tool_bridge as tb

    doc = MagicMock()
    mock_freecad.ActiveDocument = doc
    tb.FreeCAD.ActiveDocument = doc

    fake_server = MagicMock()
    fake_server.partdesign_ops.additive_box.return_value = "Created AdditiveBox: Box (100x100x100mm) in Body: Body"

    bridge = tb.DirectToolBridge(server=fake_server)
    res = bridge.execute_tool("partdesign_operations", {"operation": "additive_box", "length": 100})
    fake_server.partdesign_ops.additive_box.assert_called_once_with({"operation": "additive_box", "length": 100})
    assert "Created AdditiveBox" in res


def test_primitives_create_box_defaults(mock_freecad):
    import AICopilot.handlers.base as b
    import AICopilot.handlers.primitives as prim
    from AICopilot.handlers.primitives import PrimitivesHandler

    doc = MagicMock()
    box = MagicMock()
    box.Name = "Box"
    doc.addObject.return_value = box
    b.FreeCAD.ActiveDocument = doc
    mock_freecad.ActiveDocument = doc
    mock_freecad.Vector = MagicMock()
    prim.FreeCAD.Vector = MagicMock()

    handler = PrimitivesHandler()
    res = handler.create_box({"length": 100})
    assert "Created box: Box" in res
    assert box.Length == 100
    assert box.Width == 100
    assert box.Height == 100


def test_clean_markdown_text():
    from AICopilot.ui.dock_widget import clean_markdown_text

    raw = "$X$: $0.00 \\text{ mm}$ to $900.00 \\text{ mm}$"
    cleaned = clean_markdown_text(raw)
    assert cleaned == "X: 0.00 mm to 900.00 mm"

    raw2 = "Bounding box: $100 \\times 100 \\times 100 \\text{ mm}$"
    cleaned2 = clean_markdown_text(raw2)
    assert cleaned2 == "Bounding box: 100 x 100 x 100 mm"

    raw3 = "**$Z$**: $0.00 \\text{ mm}$"
    cleaned3 = clean_markdown_text(raw3)
    assert cleaned3 == "**Z**: 0.00 mm"


def test_system_instruction_plain_markdown():
    from AICopilot.ui.agent_worker import SYSTEM_INSTRUCTION
    assert "Plain Markdown Formatting" in SYSTEM_INSTRUCTION
    assert "NEVER output LaTeX math" in SYSTEM_INSTRUCTION


def test_history_widgets_text_selectable(qapp):
    from AICopilot.ui.dock_widget import (
        FormattedResultCard,
        FormattedCodeBox,
        WorkSection,
        TurnCardWidget,
        QtWidgets,
        QtCore,
    )

    # 1. FormattedResultCard labels
    card = FormattedResultCard("measurement_operations", '{"X": "0.00 to 100.00 mm", "Y": "0.00 to 100.00 mm"}')
    for lbl in card.findChildren(QtWidgets.QLabel):
        flags = lbl.textInteractionFlags()
        assert flags & QtCore.Qt.TextSelectableByMouse, f"Label {lbl.text()} is not selectable"

    # 2. FormattedCodeBox
    code_box = FormattedCodeBox("print('hello world')")
    code_flags = code_box.code_edit.textInteractionFlags()
    assert code_flags & QtCore.Qt.TextSelectableByMouse

    # 3. WorkSection
    work = WorkSection()
    work.add_tool_call("partdesign_operations", {"operation": "additive_box", "length": 100})
    for lbl in work.content_frame.findChildren(QtWidgets.QLabel):
        flags = lbl.textInteractionFlags()
        assert flags & QtCore.Qt.TextSelectableByMouse

    # 4. TurnCardWidget
    turn = TurnCardWidget("Create a 100mm cube", selection_badge="Box.Face1")
    turn.finish_turn("Finished: $X$: $0.00 \\text{ mm}$ to $100.00 \\text{ mm}$")
    assert "X: 0.00 mm to 100.00 mm" in turn.response_label.text()
    assert "$" not in turn.response_label.text()
    assert turn.response_label.textInteractionFlags() & QtCore.Qt.TextSelectableByMouse

def test_copilot_settings_manager(tmp_path, monkeypatch):
    import AICopilot.settings as s
    test_file = str(tmp_path / "test_settings.json")
    monkeypatch.setenv("AICOPILOT_SETTINGS_PATH", test_file)

    # Defaults
    assert s.get_setting("auto_save_on_execute") is False
    assert s.get_setting("selected_model") == "gemini-3.6-flash"
    assert s.get_setting("command_history") == []

    # Set and persist
    assert s.set_setting("auto_save_on_execute", True)
    assert s.get_setting("auto_save_on_execute") is True

    assert s.set_setting("selected_model", "gemini-3.7-flash")
    assert s.get_setting("selected_model") == "gemini-3.7-flash"

    # Command history
    s.append_command_history("box 10 20 30")
    s.append_command_history("cylinder 5 10")
    s.append_command_history("cylinder 5 10")  # duplicate should be skipped
    h = s.get_setting("command_history")
    assert h == ["box 10 20 30", "cylinder 5 10"]

    s.clear_command_history()
    assert s.get_setting("command_history") == []

    # Verify LF on disk
    with open(test_file, "rb") as f:
        raw_bytes = f.read()
    assert b"\r" not in raw_bytes


def test_auto_save_disabled_by_default_in_execute_python(mock_freecad, tmp_path, monkeypatch):
    import AICopilot.settings as s
    import AICopilot.handlers.execute_python_ops as ep
    monkeypatch.setenv("AICOPILOT_SETTINGS_PATH", str(tmp_path / "settings.json"))

    doc = MagicMock()
    doc.FileName = "test.FCStd"
    mock_freecad.ActiveDocument = doc
    ep.FreeCAD = mock_freecad

    ops = ep.ExecutePythonOpsHandler()
    res = ops.execute({"code": "x = 42"})
    assert "error" not in str(res).lower()
    # By default, doc.save() should NOT be called
    doc.save.assert_not_called()


def test_auto_save_enabled_in_execute_python(mock_freecad, tmp_path, monkeypatch):
    import AICopilot.settings as s
    import AICopilot.handlers.execute_python_ops as ep
    monkeypatch.setenv("AICOPILOT_SETTINGS_PATH", str(tmp_path / "settings.json"))
    s.set_setting("auto_save_on_execute", True)

    doc = MagicMock()
    doc.FileName = "test.FCStd"
    mock_freecad.ActiveDocument = doc
    ep.FreeCAD = mock_freecad

    ops = ep.ExecutePythonOpsHandler()
    res = ops.execute({"code": "x = 42"})
    assert "error" not in str(res).lower()
    # With setting enabled, doc.save() SHOULD be called
    doc.save.assert_called_once()


def test_auto_save_disabled_by_default_in_save_before_risky_op(mock_freecad, tmp_path, monkeypatch):
    import AICopilot.settings as s
    from AICopilot.handlers.base import BaseHandler
    monkeypatch.setenv("AICOPILOT_SETTINGS_PATH", str(tmp_path / "settings.json"))

    doc = MagicMock()
    doc.FileName = "test.FCStd"
    mock_freecad.ActiveDocument = doc

    handler = BaseHandler()
    handler.save_before_risky_op(doc)
    doc.save.assert_not_called()

    # When enabled:
    s.set_setting("auto_save_on_execute", True)
    handler.save_before_risky_op(doc)
    doc.save.assert_called_once()


def test_chat_input_text_edit_command_history(qapp):
    from AICopilot.ui.dock_widget import ChatInputTextEdit

    edit = ChatInputTextEdit()
    edit.set_history(["cmd 1", "cmd 2", "cmd 3"])

    # User types a draft
    edit.setPlainText("my draft")

    # Navigate up (prev)
    edit.navigate_history_prev()
    assert edit.toPlainText() == "cmd 3"

    edit.navigate_history_prev()
    assert edit.toPlainText() == "cmd 2"

    edit.navigate_history_prev()
    assert edit.toPlainText() == "cmd 1"

    # Stop at top
    edit.navigate_history_prev()
    assert edit.toPlainText() == "cmd 1"

    # Navigate down (next)
    edit.navigate_history_next()
    assert edit.toPlainText() == "cmd 2"

    edit.navigate_history_next()
    assert edit.toPlainText() == "cmd 3"

    # Restores draft
    edit.navigate_history_next()
    assert edit.toPlainText() == "my draft"


def test_chat_input_text_edit_hotkeys(qapp):
    from AICopilot.ui.dock_widget import ChatInputTextEdit, QtGui, QtCore

    edit = ChatInputTextEdit()
    edit.set_history(["box", "cylinder"])
    edit.setPlainText("draft")

    # Ctrl+Alt+Up -> triggers navigate_history_prev
    event_up = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Up,
        QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier,
    )
    edit.keyPressEvent(event_up)
    assert edit.toPlainText() == "cylinder"

    # Ctrl+Alt+Down -> triggers navigate_history_next (back to draft)
    event_down = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Down,
        QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier,
    )
    edit.keyPressEvent(event_down)
    assert edit.toPlainText() == "draft"

    # Regular Up and Down arrow keys do NOT navigate command history
    event_regular_up = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Up,
        QtCore.Qt.NoModifier,
    )
    edit.keyPressEvent(event_regular_up)
    assert edit.toPlainText() == "draft"


def test_dock_widget_settings_menu_and_history_buttons(mock_freecad, qapp, tmp_path, monkeypatch):
    import AICopilot.settings as s
    from AICopilot.ui.dock_widget import AICopilotDockWidget, QtCore

    monkeypatch.setenv("AICOPILOT_SETTINGS_PATH", str(tmp_path / "settings.json"))

    widget = AICopilotDockWidget()
    try:
        # Check settings gear button
        assert widget.btn_settings.text() == "⚙"
        assert widget.btn_settings.toolTip() == "Settings"
        assert hasattr(widget, "settings_menu")
        assert hasattr(widget, "act_auto_save")
        assert widget.act_auto_save.isCheckable()
        assert widget.act_auto_save.isChecked() is False

        # Toggle auto-save via menu action
        widget.act_auto_save.setChecked(True)
        assert s.get_setting("auto_save_on_execute") is True

        # Check Up/Down history buttons
        assert widget.btn_hist_prev.text() == "▲"
        assert widget.btn_hist_next.text() == "▼"
        assert "Ctrl+Alt+Up" in widget.btn_hist_prev.toolTip()
        assert "Ctrl+Alt+Down" in widget.btn_hist_next.toolTip()

        # Setup Selection mock if needed
        import sys
        if "FreeCADGui" in sys.modules:
            fc_gui = sys.modules["FreeCADGui"]
            if not hasattr(fc_gui, "Selection"):
                fc_gui.Selection = MagicMock()
                fc_gui.Selection.getSelectionEx.return_value = []

        # Submit prompts and test button navigation
        widget.input_edit.setPlainText("make a cylinder")
        widget.btn_send.click()
        assert "make a cylinder" in s.get_setting("command_history")
        widget._on_turn_complete("Done cylinder")

        widget.input_edit.setPlainText("make a sphere")
        widget.btn_send.click()
        assert "make a sphere" in s.get_setting("command_history")
        widget._on_turn_complete("Done sphere")

        # Now click ▲
        widget.btn_hist_prev.click()
        assert widget.input_edit.toPlainText() == "make a sphere"
        widget.btn_hist_prev.click()
        assert widget.input_edit.toPlainText() == "make a cylinder"
        widget.btn_hist_next.click()
        assert widget.input_edit.toPlainText() == "make a sphere"
        widget.btn_hist_next.click()
        assert widget.input_edit.toPlainText() == ""

        # Test model selection persistence
        widget.model_combo.setCurrentText("gemini-3.7-flash")
        assert s.get_setting("selected_model") == "gemini-3.7-flash"
    finally:
        widget.close()


def test_default_feeds_and_speeds_heuristic():
    from AICopilot.handlers.base import get_default_feeds_and_speeds

    # Wood with 12.7mm (1/2 in) endmill
    wood = get_default_feeds_and_speeds(tool_type="endmill", diameter=12.7, material="Wood", flutes=2)
    assert 4000.0 <= wood["spindle_speed"] <= 18000.0
    assert wood["horiz_feed_min"] > 0.0
    assert wood["vert_feed_min"] > 0.0
    # In mm/s for PropertySpeed
    assert abs(wood["horiz_feed"] - round(wood["horiz_feed_min"] / 60.0, 3)) < 1e-4
    assert abs(wood["vert_feed"] - round(wood["vert_feed_min"] / 60.0, 3)) < 0.005

    # Aluminum with 6mm endmill (slower Vc than wood)
    alu = get_default_feeds_and_speeds(tool_type="endmill", diameter=6.0, material="Aluminum", flutes=2)
    assert alu["spindle_speed"] <= 10000.0
    assert alu["horiz_feed_min"] < wood["horiz_feed_min"]

    # Steel with 6mm endmill (slower than aluminum)
    steel = get_default_feeds_and_speeds(tool_type="endmill", diameter=6.0, material="Steel", flutes=4)
    assert steel["spindle_speed"] <= alu["spindle_speed"]

    # Fallback with invalid / 0 diameter
    fallback = get_default_feeds_and_speeds(diameter=0, material="")
    assert fallback["spindle_speed"] > 0
    assert fallback["horiz_feed"] > 0


def test_settings_max_turns_persistence(tmp_path, monkeypatch):
    import AICopilot.settings as s
    monkeypatch.setenv("AICOPILOT_SETTINGS_PATH", str(tmp_path / "settings.json"))

    # Default max_turns should be 30
    assert s.get_setting("max_turns") == 30

    # Custom value persisted
    s.set_setting("max_turns", 45)
    assert s.get_setting("max_turns") == 45


def test_spreadsheet_inspect_sheet_and_safe_get(mock_freecad):
    from AICopilot.handlers.spreadsheet_ops import SpreadsheetOpsHandler
    from unittest.mock import MagicMock

    sheet = MagicMock()
    sheet.Name = "Spreadsheet"
    sheet.Label = "Spreadsheet"
    sheet.TypeId = "Spreadsheet::Sheet"

    # Mock non-empty cells
    def mock_get_contents(cell):
        if cell == "A1":
            return "=12.7 mm"
        elif cell == "A2":
            return "50"
        return ""

    def mock_get(cell):
        if cell == "A1":
            val = MagicMock()
            val.Value = 12.7
            val.Unit = "mm"
            val.__str__ = lambda self: "12.7 mm"
            return val
        elif cell == "A2":
            return 50
        raise ValueError(f"Invalid cell address or property: {cell}")

    sheet.getContents = MagicMock(side_effect=mock_get_contents)
    sheet.get = MagicMock(side_effect=mock_get)
    sheet.getAlias = MagicMock(side_effect=lambda cell: "ToolDia" if cell == "A1" else None)
    sheet.getNonEmptyCells = MagicMock(return_value=["A1", "A2"])

    doc = MagicMock()
    doc.getObject.return_value = sheet
    mock_freecad.ActiveDocument = doc
    import AICopilot.handlers.base as b
    b.FreeCAD = mock_freecad

    handler = SpreadsheetOpsHandler()

    # inspect_sheet
    res = handler.inspect_sheet({"sheet_name": "Spreadsheet", "max_rows": 5, "max_cols": 5})
    import json
    data = json.loads(res)
    assert data["spreadsheet_name"] == "Spreadsheet"
    assert "A1" in data["cells"]
    assert data["cells"]["A1"]["alias"] == "ToolDia"
    assert data["cells"]["A1"]["formula"] == "=12.7 mm"
    assert "12.7" in str(data["cells"]["A1"]["value"])

    # Safe get_cell on empty cell returns None, no exception
    res_empty = handler.get_cell({"sheet_name": "Spreadsheet", "cell": "C1"})
    data_empty = json.loads(res_empty)
    assert data_empty["value"] is None


def test_cam_millfacing_viewprovider_and_parameter_wiring(mock_freecad):
    """Verify CAMOpsHandler.face wires modern MillFacing parameters and attaches ViewProvider."""
    import AICopilot.handlers.cam_ops as co
    import AICopilot.handlers.base as b
    b.FreeCAD = mock_freecad
    co.FreeCAD = mock_freecad
    mock_freecad.GuiUp = True

    job = MagicMock()
    job.Name = "Job"
    job.Label = "Job"
    job.TypeId = "Path::FeaturePython"
    job_vo = MagicMock()
    job_vo.Proxy = None
    job.ViewObject = job_vo
    job.Model = MagicMock()
    clone_m = MagicMock()
    clone_m.Label = "Model-Wood"
    job.Model.Group = [clone_m]

    op = MagicMock()
    op.Name = "MillFacing"
    op.Label = "MillFacing"
    op.TypeId = "Path::FeaturePython"
    # MillFacing does NOT have Base attribute
    if hasattr(op, "Base"):
        delattr(op, "Base")
    op_vo = MagicMock()
    op_vo.Proxy = None
    op_vo.Visibility = False
    op.ViewObject = op_vo
    op.StepOver = 25
    op.CutMode = "Conventional"
    op.ClearingPattern = "ZigZag"

    doc = MagicMock()
    doc.getObject.side_effect = lambda n: job if n == "Job" else (clone_m if n == "Clone" else None)
    mock_freecad.ActiveDocument = doc

    handler = co.CAMOpsHandler()
    fake_create = MagicMock(return_value=op)

    # Mock get_op_create to return our fake factory
    fake_res = MagicMock()
    fake_res.name = "MillFacing"
    fake_res.pixmap = "CAM_Face"

    fake_vp_cls = MagicMock()
    mock_vp_inst = MagicMock()
    mock_vp_inst.setEdit = MagicMock(return_value=True)
    fake_vp_cls.return_value = mock_vp_inst

    mock_base = types.ModuleType("Path.Op.Gui.Base")
    mock_base.ViewProvider = fake_vp_cls

    with patch.dict(sys.modules, {
        "Path": types.ModuleType("Path"),
        "Path.Op": types.ModuleType("Path.Op"),
        "Path.Op.Gui": types.ModuleType("Path.Op.Gui"),
        "Path.Op.Gui.Base": mock_base,
    }):
        with patch.object(co, "get_op_create", return_value=fake_create):
            with patch.object(co, "get_op_viewprovider_resources", return_value=fake_res):
                res_str = handler.face({
                    "job_name": "Job",
                    "cut_mode": "Climb",
                    "clearing_pattern": "Directional",
                    "step_over": 50,
                    "step_down": 0.5,
                    "pass_extension": 3.0,
                    "stock_extension": 1.0,
                })

                assert "Created" in res_str
                # Verified parameter assignments
                assert op.CutMode == "Climb"
                assert op.ClearingPattern == "Directional"
                assert op.StepOver == 50
                assert op.StepDown == 0.5
                assert op.PassExtension == 3.0
                assert op.StockExtension == 1.0
                # Verified ViewProvider attachment and Visibility
                assert op_vo.Visibility is True
                assert op_vo.Proxy == mock_vp_inst
                assert op_vo.Proxy.setEdit(op_vo, 0) is True


def test_get_op_viewprovider_resources():
    """Verify get_op_viewprovider_resources resolves CommandResources from Gui module."""
    from AICopilot.compat_pathscripts import get_op_viewprovider_resources

    fake_gui_mod = types.ModuleType("Path.Op.Gui.MillFacing")
    fake_cmd = MagicMock()
    fake_res = MagicMock()
    fake_res.name = "MillFacing"
    fake_cmd.res = fake_res
    fake_gui_mod.Command = fake_cmd

    sys.modules["Path.Op.Gui.MillFacing"] = fake_gui_mod
    try:
        res = get_op_viewprovider_resources("facing")
        assert res == fake_res
        assert res.name == "MillFacing"

        res_face = get_op_viewprovider_resources("face")
        assert res_face == fake_res
    finally:
        sys.modules.pop("Path.Op.Gui.MillFacing", None)
