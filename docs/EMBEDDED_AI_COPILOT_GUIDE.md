# Embedded FreeCAD AI Copilot User & Developer Guide

## Overview

The **Embedded AI Copilot** is a native FreeCAD dock panel that integrates Google Gemini directly into the FreeCAD modeling environment. It allows conversational parametric CAD design, automated CAM toolpath generation, spreadsheet manipulation, and geometric inspection **without requiring external socket servers, IPC serialization, or temporary Python script files on disk**.

---

## Key Features

1. **Native Dockable UI (`AICopilotDockWidget`)**:
   - Resides directly inside FreeCAD's main window dock areas (dockable left, right, floating, or tabbed alongside the Tree View and Property View).
   - Toggled via `View -> Panels -> AI Copilot` or keyboard shortcut `Ctrl+Shift+A`.
   - Remembers its docking location and geometry across FreeCAD sessions.

2. **In-Memory Tool Dispatch (`DirectToolBridge`)**:
   - Zero socket overhead and zero disk script-dumping.
   - Executes CAD actions directly against FreeCAD's C++/Python core on the GUI thread.
   - Automatic document transaction management: wraps every mutating CAD action in `doc.openTransaction()` / `doc.commitTransaction()`, allowing full `Ctrl+Z` undo functionality.

3. **Live 3D Viewport Selection Awareness**:
   - Integrated `FreeCADGui.SelectionObserver` tracks the user's active selections in the 3D viewport in real time.
   - Displays a dynamic selection badge (e.g., `🎯 Selected: Wood_Plank (Face1)`) in the chat header.
   - Automatically provides active face, edge, and vertex context to the AI model for localized operations (e.g., pad, pocket, fillet, chamfer, or toolpath bounding).

4. **Multi-turn Streaming & Function Calling (`CopilotAgentWorker`)**:
   - Runs the Google Gemini agent loop asynchronously in a secondary `QThread` without blocking the FreeCAD GUI.
   - Streams conversational tokens in real time.
   - Safely marshals tool execution requests to FreeCAD's main thread via Qt signals/slots with thread-safe event synchronization.

5. **Integrated Preferences & Security**:
   - Store your Gemini API key via the `⚙ Key` button in the panel toolbar.
   - Securely persisted in FreeCAD User Parameters (`BaseApp/Preferences/AICopilot/GeminiApiKey`).
   - Supports Gemini 3.x models (`gemini-3.6-flash`, `gemini-3.7-flash`, `gemini-3.8-flash`, `gemini-3.1-pro-preview`, `gemini-flash-latest`, `gemini-pro-latest`).
   - Editable model selector allows typing or pasting any custom/preview model ID.
   - Automatic dynamic model discovery queries available models from your API key upon startup and key update.

6. **Smart Error Handling & Prompt Retention**:
   - **Dismissible Error Banner**: Displays clean, formatted error messages above the input box (stripping ugly JSON and nested dictionaries). Dismisses automatically on model change, dropdown selection, typing, or clicking `✕`.
   - **Zero-Retype Prompt Retention**: On any API error (such as 404 model not found or quota limits), the prompt is preserved in the input box so you can change the model and immediately retry.
   - **Automatic 503 Fallback**: If a selected preview model (e.g. `gemini-3.8-flash`) experiences peak-demand shedding (HTTP 503), the worker automatically completes the request using `gemini-3.6-flash` and reports an inline note.

---

## User Interface Walkthrough

```
┌────────────────────────────────────────────────────────┐
│  AI Copilot                                      🗖 🗙  │
├────────────────────────────────────────────────────────┤
│ [gemini-3.6-flash ▼]  [↩ Undo]  [⚙ Key]  [🗑 Clear]     │
├────────────────────────────────────────────────────────┤
│ 🎯 Selected: Wood_Plank (Face1)                        │
├────────────────────────────────────────────────────────┤
│                                                        │
│  ℹ FreeCAD AI Copilot ready.                           │
│                                                        │
│  You: Add a 5mm fillet to the selected edges.          │
│                                                        │
│  ⚡ Executing: partdesign_operations(operation=fillet) │
│  ✔ Result: {"success": true, "feature": "Fillet001"}   │
│                                                        │
│  Assistant: I've added a 5mm fillet to the selected    │
│  edges on Wood_Plank. You can undo if needed.          │
│                                                        │
├────────────────────────────────────────────────────────┤
│ Ready                                                  │
├────────────────────────────────────────────────────────┤
│ ⚠️ [Model Busy (503): High demand...]              [✕] │
├────────────────────────────────────────────────────────┤
│ [ Type CAD request or question (Enter to send)...    ] │
│                                          [➤ Send] [⏹]  │
└────────────────────────────────────────────────────────┘
```

---

## Quickstart

### 1. Configuration
1. Open FreeCAD.
2. In the AI Copilot panel toolbar, click `⚙ Key`.
3. Paste your Google Gemini API Key. (Alternatively, export `GEMINI_API_KEY="your-key"` in your shell environment before launching FreeCAD).

### 2. Basic Modeling
- **Create Geometry**: Type `Create a parametric wooden plank 100mm wide, 300mm long, and 20mm thick with a spreadsheet for parameters.`
- **Inspect Geometry**: Type `What are the bounding box dimensions of Wood_Plank?`
- **Modify Geometry**: Select a face in the 3D view, then type `Pocket this face by 5mm.`

### 3. Undo / Revert
- If an AI operation produces unexpected results, click `↩ Undo` in the toolbar or press `Ctrl+Z` to immediately roll back the document to its prior state.

---

## Architecture

For in-depth architectural details, threading diagrams, and security specifications, see:
- [`EMBEDDED_AI_COPILOT_ARCHITECTURE.md`](file:///D:/repos/oth/FreeCADOther/freecad-mcp/docs/EMBEDDED_AI_COPILOT_ARCHITECTURE.md)
- [`EMBEDDED_AI_COPILOT_PLAN.md`](file:///D:/repos/oth/FreeCADOther/freecad-mcp/docs/EMBEDDED_AI_COPILOT_PLAN.md)

