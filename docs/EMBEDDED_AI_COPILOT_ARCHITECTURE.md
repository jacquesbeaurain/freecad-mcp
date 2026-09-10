# Embedded In-Process AI Copilot Architecture for FreeCAD

## 1. Executive Summary

This document specifies the architecture of the **In-Process AI Copilot** embedded directly within FreeCAD's Qt application shell as a native `QDockWidget`.

Historically, `freecad-mcp` operated as an external process communicating with FreeCAD over a local TCP socket using length-prefixed JSON-RPC framing, frequently writing temporary `.py` script files to disk to execute complex CAD operations. While functional for external CLI or desktop clients, this bridge architecture introduced IPC latency, port collisions, socket disconnects, disk churn, lack of viewport selection awareness, and jarring window-switching for end users.

The **In-Process AI Copilot** eliminates the socket, the bridge process, and temporary disk files completely by running the agent engine and its user interface inside FreeCAD's native Python and Qt runtime.

---

## 2. Architecture Comparison

### A. Legacy Socket Bridge Architecture

```
┌───────────────────────────┐           ┌─────────────────────────────────────────┐
│     External Client       │           │          FreeCAD GUI Process            │
│ (Claude / Antigravity CLI)│           │                                         │
│             │             │           │  ┌───────────────────────────────────┐  │
│             │ stdio       │           │  │          AICopilot Addon          │  │
│             ▼             │           │  │       (FreeCADSocketServer)       │  │
│ ┌───────────────────────┐ │   TCP     │  │  ┌──────────────┐                 │  │
│ │ freecad_mcp_server.py ├─┼───────────┼─►│  │ Socket Poll  │                 │  │
│ └───────────────────────┘ │ localhost │  │  └──────┬───────┘                 │  │
│                           │   :23456  │  │         │ JSON-RPC parse          │  │
│                           │           │  │         ▼                         │  │
│                           │           │  │  ┌──────────────┐   Disk Files    │  │
│                           │           │  │  │ Write Temp   ├──────────────┐  │  │
│                           │           │  │  │ .py Scripts  │◄─────────────┘  │  │
│                           │           │  │  └──────┬───────┘                 │  │
│                           │           │  │         ▼                         │  │
│                           │           │  │  FreeCAD.ActiveDocument           │  │
│                           │           │  └───────────────────────────────────┘  │
│                           │           └─────────────────────────────────────────┘
```

**Pain points**:
- Multi-process coordination required (FreeCAD running + MCP server running).
- High IPC serialization overhead for complex CAD geometry.
- No awareness of the active 3D viewport or user object selection.
- Fragile temporary script writing to `/tmp` with filesystem permission and pathing quirks on Windows.
- Disconnected undo/redo stack.

---

### B. In-Process Native AI Copilot Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FreeCAD GUI Process                              │
│                                                                             │
│  ┌─────────────────────────┐      Qt Signals       ┌─────────────────────┐  │
│  │     3D View / Tree      │◄─────────────────────►│ AICopilotDockWidget │  │
│  │    (ActiveDocument)     │   (SelectionObserver) │    (PySide6 / Qt)   │  │
│  │                         │                       │                     │  │
│  │   [Model Viewport]      │                       │ [Selection Badge]   │  │
│  │   [Selection Context]   │                       │ [Chat Stream]       │  │
│  │   [Direct Coin3D View]  │                       │ [Model Selector]    │  │
│  └────────────▲────────────┘                       │ [Undo / Clear Btns] │  │
│               │                                    └──────────▲──────────┘  │
│               │ Main Thread Dispatch                          │ Qt Signals  │
│               │ (BlockingQueuedConnection)                    │ (tokens,    │
│               │                                               │  status)    │
│  ┌────────────┴───────────────────────────────────────────────┴──────────┐  │
│  │                      DirectToolBridge                                 │  │
│  │  - FreeCAD.ActiveDocument.openTransaction("AI: <Op>")                 │  │
│  │  - Direct in-memory dispatch to handlers (cam_ops, partdesign, etc.)  │  │
│  │  - FreeCAD.ActiveDocument.commitTransaction()                         │  │
│  │  - Zero sockets, zero IPC, zero temporary script files                │  │
│  └────────────────────────────▲──────────────────────────────────────────┘  │
│                               │ Tool Call Request / Response                │
│  ┌────────────────────────────┴──────────────────────────────────────────┐  │
│  │                    CopilotAgentWorker (QThread)                       │  │
│  │                    (google-genai / Gemini API)                        │  │
│  │  - Background execution (never blocks 60 FPS GUI rendering)           │  │
│  │  - Multi-turn conversation state and streaming token consumer         │  │
│  │  - Automated function calling loop                                    │  │
│  └────────────────────────────▲──────────────────────────────────────────┘  │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │ HTTPS REST / Streaming
                                ▼
                   Google Gemini API Gateway
```

---

## 3. Key Subsystems & Design Principles

### 1. In-Memory Tool Dispatch (`DirectToolBridge`)
- Reuses the existing modular handlers (`CAMOpsHandler`, `PartDesignOpsHandler`, `SketchOpsHandler`, `SpreadsheetOpsHandler`, `ExecutePythonOpsHandler`, etc.).
- When the LLM calls a tool:
  1. The call is routed to `DirectToolBridge.execute_tool(name, args)`.
  2. The bridge ensures execution runs on FreeCAD's main thread via `QtCore.QMetaObject.invokeMethod` or `BlockingQueuedConnection` (ensuring OpenCASCADE and Qt GUI safety).
  3. The operation is wrapped in a native transaction:
     ```python
     doc.openTransaction(f"AI: {tool_name}")
     try:
         result = handler_method(args)
         doc.commitTransaction()
         doc.recompute()
     except Exception as e:
         doc.abortTransaction()
         raise e
     ```
  4. Returns the result directly in memory without writing any files or encoding JSON frames across sockets.

### 2. Multi-Threaded Execution Engine (`CopilotAgentWorker`)
- Inherits from `QtCore.QThread`.
- Maintains the model conversation session using `google.genai`.
- Emits Qt signals back to the UI:
  - `token_received(str)`: Real-time streamed text tokens.
  - `status_changed(str)`: Status updates (e.g. *"Reasoning..."*, *"Executing CAM toolpath..."*, *"Idle"*).
  - `tool_call_started(str, dict)`: Notifies UI that a tool invocation has begun.
  - `tool_call_finished(str, str)`: Reports tool completion and result.
  - `finished(str)`: Turn completion.
  - `error_occurred(str)`: Graceful error handling.
- Implements `stop()` to cancel active requests without killing FreeCAD.

### 3. Live Selection Awareness (`FreeCADGui.SelectionObserver`)
- FreeCAD's native `SelectionObserver` is attached when the dock widget initializes.
- Real-time events (`addSelection`, `clearSelection`, `removeSelection`) update the UI badge with the active object name, sub-element (e.g. `Face4`, `Edge12`), and parent body.
- When the user submits a message, the active selection is injected as context:
  `[Active Selection: Box.Face4 (Plane at Z=50mm, Area=4500mm²)]`
  This enables natural commands such as *"Pocket this face 5mm deep"* or *"Fillet these edges 2mm"* without requiring manual object name lookups.

### 4. Native Undo/Redo Harmony
- Because every tool execution is wrapped in FreeCAD's `openTransaction` / `commitTransaction`, FreeCAD's native **Ctrl+Z** (Undo) and **Ctrl+Y** (Redo) immediately roll back or reapply the AI's changes.
- The Copilot UI also exposes an **Undo Last Action** button that directly triggers `FreeCAD.ActiveDocument.undo()`.

---

## 4. Security & Configuration

- **API Key Resolution**:
  1. Environment variable: `GEMINI_API_KEY`.
  2. FreeCAD user configuration: `App.ParamGet("User parameter:BaseApp/Preferences/AICopilot").GetString("GeminiApiKey")`.
  3. User interface dialog: Accessible via the Settings button on the dock widget toolbar.
- **Model Selection**: Defaults to `gemini-2.5-flash` for high-speed CAD iterations, with options for `gemini-2.5-pro` for complex parametric reasoning.
- **Backwards Compatibility**: The external TCP socket server remains available as an optional service for external MCP tools while the in-app Copilot provides the primary interface.
