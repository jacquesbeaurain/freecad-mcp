# In-Process AI Copilot Implementation Plan

## Overview
This document tracks the phased implementation of the In-Process AI Copilot DockWidget for FreeCAD within the `freecad-mcp` codebase.

---

## Phased Implementation Roadmap

### Phase 1: Documentation & Design Specifications
- Document the in-process architecture: `docs/EMBEDDED_AI_COPILOT_ARCHITECTURE.md`.
- Document implementation milestones: `docs/EMBEDDED_AI_COPILOT_PLAN.md`.
- Track upstream CAM recommendations: `CAM_RECOMMENDATIONS.md`.

### Phase 2: In-Memory Tool Bridge (`AICopilot/ui/tool_bridge.py`)
- Define `DirectToolBridge` class.
- Provide direct in-memory invocation of modular handlers:
  - PartDesign (`pad`, `pocket`, `hole`, `fillet`, `chamfer`, etc.)
  - CAM (`create_job`, `create_operation`, `create_tool`, `repair_cam_tree`, etc.)
  - Sketcher (`create_sketch`, `add_geometry`, `add_constraint`, etc.)
  - Spreadsheets (`create_sheet`, `set_cell`, `bind_property`, etc.)
  - Direct Python execution (`execute_python`) with stdout/stderr capture.
- Wire FreeCAD document transactions (`openTransaction`, `commitTransaction`, `abortTransaction`).
- Provide Gemini-compatible function declaration schemas for automatic tool calling.

### Phase 3: Background Agent Worker (`AICopilot/ui/agent_worker.py`)
- Implement `CopilotAgentWorker(QtCore.QThread)`.
- Integrate `google.genai` Client with API key resolution (env var, FreeCAD user preferences, UI dialog).
- Implement asynchronous streaming token consumption.
- Implement Gemini function calling loop:
  - Model requests tool call -> worker emits request to main thread -> main thread executes on `FreeCAD.ActiveDocument` -> result passed back to model.
- Provide cancellation and error handling hooks.

### Phase 4: Native PySide DockWidget UI (`AICopilot/ui/dock_widget.py`)
- Implement `AICopilotDockWidget(QtWidgets.QDockWidget)`.
- Build UI layout:
  - Header toolbar with Model dropdown, Settings dialog trigger, Clear button, and Undo button.
  - Live 3D Selection badge powered by `FreeCADGui.SelectionObserver`.
  - Rich chat message area with Markdown rendering, code snippet styling, and tool status chips.
  - Multi-line user prompt editor with Enter-to-send (Shift+Enter for newline) and Send/Stop button.
- Integrate selection context automatically into user prompts.

### Phase 5: FreeCAD GUI Startup Integration (`AICopilot/InitGui.py`)
- When `FreeCAD.GuiUp` is True, instantiate `AICopilotDockWidget` and register with `FreeCADGui.getMainWindow()`.
- Add menu toggle action under `View -> Panels -> AI Copilot`.
- Ensure coexistence with the existing socket service.
- Deploy to live FreeCAD addon configuration (`%APPDATA%\FreeCAD\v26-3\Mod\AICopilot`).

---

## Verification Strategy
1. **Module Import & Dependency Verification**:
   - Verify `google.genai`, `PySide6`, and `AICopilot.ui` import cleanly in FreeCAD Python without warnings.
2. **Headless & Unit Test Suite**:
   - Run `freecad-mcp` test suite (`tests/unit/test_cam_wrappers.py`, etc.).
3. **Live FreeCAD UI Testing**:
   - Start FreeCAD GUI.
   - Verify DockWidget appears docked on the right side.
   - Select 3D face; verify live selection badge updates.
   - Execute prompt (e.g. *"Create a parametric box 100x50x20mm"*); verify zero socket calls and immediate transaction history.
