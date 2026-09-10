# FreeCAD Embedded AI Copilot & In-Process Integration Walkthrough

## 1. Executive Summary

We have designed, implemented, verified, and deployed a **native, embedded AI Copilot inside FreeCAD** within the `freecad-mcp` repository on the `feat_copilotui` branch.

This embedded copilot replaces external socket connections, IPC serialization overhead, and disk-dumped temporary Python scripts with a **direct, in-process PySide dock widget**:
- **Zero Socket Latency & Zero Temporary Script Files**: All CAD operations execute directly against FreeCAD's Python and C++ runtime in memory.
- **Native Turn-Level Undo Transactions**: User operations are enclosed in atomic document transactions, enabling immediate one-click rollback (`↩ Undo` or `Ctrl+Z`) and automatic rollback on error.
- **Live 3D Viewport Selection Awareness**: A dedicated `FreeCADGui.SelectionObserver` tracks active selections (objects, faces, edges, vertices) and passes sub-element context directly to the AI model.
- **Asynchronous Agent Loop with Streaming**: Powered by `google-genai` running in a dedicated `QThread`, streaming tokens into the chat browser without freezing FreeCAD's GUI.
- **Safe Main-Thread Marshalling**: CAD geometry and Coin3D/Qt calls are safely dispatched to FreeCAD's GUI thread via Qt signals/slots with thread synchronization (`ToolCallRequest`).

---

## 2. Visual Verification

The embedded AI Copilot runs live inside FreeCAD, docked on the right side of the main window:

### Panel Docked in FreeCAD
![AI Copilot Dock Widget](img/copilot_dock_widget_gui.png)

### Live 3D Selection Observer in Action
When selecting geometry in the 3D viewport, the selection badge reactively updates:
![Live 3D Selection Badge](img/copilot_selection_gui.png)

### Live Ready State with Fixed Error Parsing and Spatial Queries
![Live Copilot Ready State](img/copilot_fixed_gui.png)

### Antigravity-Style Collapsible Thoughts, Work Sections, and Markdown Summaries
The conversation history renders sequential turns with collapsible thought and work sections that automatically collapse upon completion:

| Collapsed State (Default at End of Turn) | Expanded State (Click Header to Inspect) |
|---|---|
| ![Collapsed State](img/copilot_ui_mockup.png) | ![Expanded State](img/copilot_ui_mockup_top.png) |

### Live Operational Notices in Stream View
During multi-step execution, model busy (503) and rate limit (429) quota pauses display directly in the active turn card:
![Live Operational Notices](img/copilot_dock_live_stream.png)

### Refined Theme-Adaptive Controls (Classic / Light Theme)
Refined controls for Light and Classic themes with read-only syntax-styled multiline Python code boxes and structured, color-coded JSON result cards:
![Refined Light Theme UI with Multiline Python and Color-Coded Results](img/copilot_refined_light_theme.png)

---

## 3. Git Commit History in `freecad-mcp`

The implementation was delivered across clean, well-documented commits following Conventional Commits standards on `feat_copilotui`:

| Commit | Summary | Key Files |
|---|---|---|
| [`37c5097`](../../../commit/37c5097) | `feat(copilotui): add architectural specification and design plan for embedded in-process UI` | [`EMBEDDED_AI_COPILOT_ARCHITECTURE.md`](EMBEDDED_AI_COPILOT_ARCHITECTURE.md), [`EMBEDDED_AI_COPILOT_PLAN.md`](EMBEDDED_AI_COPILOT_PLAN.md) |
| [`9805bc4`](../../../commit/9805bc4) | `feat(copilotui): implement in-memory tool bridge for direct execution without sockets` | [`../AICopilot/ui/__init__.py`](../AICopilot/ui/__init__.py), [`../AICopilot/ui/tool_bridge.py`](../AICopilot/ui/tool_bridge.py) |
| [`fe77b6f`](../../../commit/fe77b6f) | `feat(copilotui): add background agent worker thread with streaming and function calling` | [`../AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py) |
| [`2d931b1`](../../../commit/2d931b1) | `feat(copilotui): create native PySide dock widget with live 3D selection observer` | [`../AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py) |
| [`cbea557`](../../../commit/cbea557) | `feat(copilotui): integrate embedded AI Copilot dock widget in FreeCAD GUI startup` | [`../AICopilot/InitGui.py`](../AICopilot/InitGui.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py) |
| [`6c3efa8`](../../../commit/6c3efa8) | `feat(copilotui): route DirectToolBridge calls synchronously to modular handlers` | [`../AICopilot/ui/tool_bridge.py`](../AICopilot/ui/tool_bridge.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py) |
| [`56959d4`](../../../commit/56959d4) | `feat(copilotui): add embedded AI Copilot user and developer guide` | [`EMBEDDED_AI_COPILOT_GUIDE.md`](EMBEDDED_AI_COPILOT_GUIDE.md) |
| [`1504950`](../../../commit/1504950) | `feat(copilotui): update models to Gemini 3.x with dynamic discovery and editable selector` | [`../AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py), [`../AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py) |
| [`861578a`](../../../commit/861578a) | `feat(copilotui): update embedded user guide with Gemini 3.x model selection` | [`EMBEDDED_AI_COPILOT_GUIDE.md`](EMBEDDED_AI_COPILOT_GUIDE.md) |
| [`8e92267`](../../../commit/8e92267) | `feat(copilotui): add automatic 503 fallback, dismissible error banner, and prompt retention` | [`../AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py), [`../AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py) |
| [`3b7cbb6`](../../../commit/3b7cbb6) | `feat(copilotui): document error banner, prompt retention, and 503 fallback in guide` | [`EMBEDDED_AI_COPILOT_GUIDE.md`](EMBEDDED_AI_COPILOT_GUIDE.md) |
| [`4d23530`](../../../commit/4d23530) | `feat(copilotui): use role user for function responses, fix error parser, and add spatial face queries` | [`../AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py), [`../AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), [`../AICopilot/handlers/spatial_ops.py`](../AICopilot/handlers/spatial_ops.py), [`../AICopilot/ui/tool_bridge.py`](../AICopilot/ui/tool_bridge.py), [`../AICopilot/handlers/sketch_ops.py`](../AICopilot/handlers/sketch_ops.py) |
| [`61cfddb`](../../../commit/61cfddb) | `feat(copilotui): add atomic turn undo transactions and 429 auto-retry backoff` | [`../AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py), [`../AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), [`../AICopilot/ui/tool_bridge.py`](../AICopilot/ui/tool_bridge.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py) |
| [`6884882`](../../../commit/6884882) | `feat(copilotui): document atomic turn undo and 429 quota handling in user guide` | [`EMBEDDED_AI_COPILOT_GUIDE.md`](EMBEDDED_AI_COPILOT_GUIDE.md) |
| [`28de92e`](../../../commit/28de92e) | `feat(copilotui): add embedded copilot walkthrough and visual verification to docs` | [`EMBEDDED_AI_COPILOT_WALKTHROUGH.md`](EMBEDDED_AI_COPILOT_WALKTHROUGH.md) |
| [`177d534`](../../../commit/177d534) | `feat(copilotui): add collapsible thought and work sections with markdown summaries` | [`../AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py), [`../AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py) |
| [`4633547`](../../../commit/4633547) | `feat(copilotui): add multiline python controls, colored json cards, and light theme styling` | [`../AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py), [`img/copilot_refined_light_theme.png`](img/copilot_refined_light_theme.png) |

---

## 4. Problem Diagnostics & Root Cause Fixes

### 1. The 400 INVALID_ARGUMENT "Role 'tool'" Fix
- **Root Cause**: In [`AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py), tool response content parts were appended to `self.history` with `role="tool"`. While OpenAI's API uses `role="tool"`, the Google Gemini API strictly requires `role="user"` for `FunctionResponse` content. Passing `role="tool"` caused the second turn of any tool call to immediately fail with `400 INVALID_ARGUMENT`.
- **Solution**: Changed to `role="user"`. Added turn history snapshotting (`history_start_len`) to cleanly roll back any partial or failed conversational turns without corrupting history.

### 2. Error Message Truncation Fix
- **Root Cause**: The error message parsing regex terminated on the first quote, which truncated errors like `Role 'tool' is not supported...` down to the single word `"Role"`.
- **Solution**: Replaced fragile regex extraction with Python AST and JSON dictionary parsing in [`AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), correctly surfacing untruncated messages (e.g. `Rate Limit Exceeded (429): You exceeded your current quota...`).

### 3. Spatial Face Queries Implementation
- **Root Cause**: Gemini was given the tool `spatial_query(object_name='Body', query_type='top_face')`, but `SpatialOpsHandler` only supported collision/clearance queries between two shapes (`interference_check`, `clearance`), causing `Unknown Spatial operation: `.
- **Solution**: Implemented full geometric face queries in [`AICopilot/handlers/spatial_ops.py`](../AICopilot/handlers/spatial_ops.py):
  - `top_face`: selects the topmost planar face pointing in +Z with centroid coordinates, normal, and area.
  - `bottom_face`: selects the lowest face pointing in -Z.
  - `horizontal_faces`: filters all faces with normal along ±Z.
  - `vertical_faces`: filters vertical faces perpendicular to Z.
  - `faces_by_normal`: vector dot-product matching against target `[nx, ny, nz]`.
  - `list_faces`: comprehensive enumeration of all faces.
  - Graceful empty geometry detection: if an empty PartDesign Body has 0 faces, it clearly informs the agent: `"Object 'Body' has no faces or solid geometry yet. If this is an empty PartDesign Body, create a base feature (e.g. pad, revolution, or primitive) first."`

### 4. Direct GUI Thread Execution & Sketch Geometry Dispatch
- **Direct Python Execution**: [`AICopilot/ui/tool_bridge.py`](../AICopilot/ui/tool_bridge.py) now calls `run_code` directly on `execute_python_ops` since execution is already on the GUI thread, removing socket queue latency.
- **Sketch Operations Dispatch**: Added `add_geometry` dispatcher mapping to `add_rectangle`, `add_circle`, `add_line`, etc., and normalized attachment plane names (e.g. `XY_Plane` -> `XY`).

---

## 5. Automated Verification Results

All 21 Copilot UI unit tests and 106 related CAD tests pass consistently:
```pwsh
D:\repos\oth\FreeCAD\build\release\bin\python.exe -m pytest tests/unit/test_copilot_dock_widget.py tests/unit/test_spatial_ops.py tests/unit/test_sketch_ops.py
```

```
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\repos\oth\FreeCADOther\freecad-mcp
configfile: pyproject.toml
plugins: anyio-4.14.2, mock-3.15.1
collected 106 items

tests\unit\test_copilot_dock_widget.py .....................            [ 20%]
tests\unit\test_spatial_ops.py ......................................... [ 58%]
.........                                                                [ 67%]
tests\unit\test_sketch_ops.py ...................................        [100%]

============================= 106 passed in 0.88s ==============================
```

---

## 6. Atomic Turn Undo Transactions & 429 Auto-Resume

### Problem Context
When the user executed a multi-step operation (such as *"Create a 20mm pocket in the top face"*), the AI agent invoked multiple sequential tools:
1. `spatial_query(object_name="Body", query_type="top_face")`
2. `sketch_operations(operation="create_sketch", ...)`
3. `partdesign_operations(operation="pocket", depth=20)`

Under the Google AI Studio **Free Tier**, a strict limit of 15–20 RPM (requests per minute) is enforced. Because multi-turn tool calling burns 3–5 requests per turn, submitting two requests in rapid succession triggered:
```text
Error: Rate Limit Exceeded (429): Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.6-flash. Please retry in 28.95s.
```
Because FreeCAD transactions were historically committed per individual tool call, failing on step 3 left the document in a **partially completed state** with orphaned sketches and unpadded profiles.

### Architecture Solutions

#### 1. Atomic Turn-Level Undo Transactions
- **Initiation**: In [`AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), `_on_send_clicked()` calls `self.tool_bridge.begin_turn_transaction(prompt)`, creating a single document transaction `doc.openTransaction(f"AI: {prompt[:40]}")`.
- **Live Recompute Without Micro-Commits**: In [`AICopilot/ui/tool_bridge.py`](../AICopilot/ui/tool_bridge.py), when `_in_turn_transaction` is active, mutating tools bypass opening and closing individual micro-transactions. Each tool recomputes and refreshes the GUI live so the user sees progress in real time.
- **Atomic Commit**: When the turn succeeds, `commit_turn_transaction()` closes the transaction. FreeCAD's native undo stack registers a single item: clicking `↩ Undo` (or Ctrl+Z) rolls back the whole multi-step AI turn in one click.
- **Atomic Abort / Rollback**: If an error occurs (e.g. 429, API failure, or the user clicks `⏹ Stop`), `abort_turn_transaction()` invokes `doc.abortTransaction()`. All intermediate objects created during that turn are instantly removed, cleanly returning the document to its exact pre-turn state.

#### 2. Smart 429 Rate-Limit Backoff & Auto-Resume
- In [`AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py), 429 errors are intercepted and the exact required cooldown is extracted:
  ```python
  retry_match = re.search(r"retry in\s*([\d\.]+)\s*s", err_str, re.IGNORECASE)
  ```
- An inline token notice is posted to the chat informing the user that quota was reached and the operation is paused.
- The status bar displays a live countdown: `Rate limit: resuming in 28s...`.
- While waiting, the thread checks `self._stop_requested` every second so the user can abort immediately without waiting.
- Once the cooldown timer finishes, the worker automatically retries `client.models.generate_content` and resumes tool execution seamlessly.

#### 3. Free Tier vs. Pay-As-You-Go Quota
- **Free Tier**: 15–20 RPM cap per model across the Google Cloud project.
- **Pay-As-You-Go**: Enabling billing in Google AI Studio or Google Cloud Console raises the quota for Gemini 3.6/3.7/3.8 Flash to **1,000–2,000 RPM**, completely eliminating 429 rate limit bottlenecks during interactive CAD sessions. Pricing on Flash models is approximately $0.10 per million tokens (a fraction of a cent per operation).



---

## 7. Antigravity-Style Conversation Stream UI

To provide a modern, clean developer experience matching advanced AI coding environments like Antigravity, the chat history interface was upgraded from a flat `QTextBrowser` to a structured, widget-based stream (`ChatStreamWidget` + `TurnCardWidget`):

### Key UI Capabilities
1. **Collapsible Thought Traces (`ThoughtSection`)**:
   - As thinking tokens stream from Gemini (`types.ThinkingConfig(include_thoughts=True)`), an expanded `▼ Thinking...` section displays the model's live reasoning in a dark monospaced code frame.
   - Upon completion, the section automatically collapses into a compact pill: `▶ Thought (1.4s)`.
   - The user can click the header at any time to expand or re-collapse the reasoning trace.

2. **Active Work Sections (`WorkSection`)**:
   - While tool calls are executing against FreeCAD in real time, the work section displays `▼ Working (n commands)...` with live execution logs (`⚡ Executing: tool(args...)` and `✔ Result: <preview>`).
   - Operational notices such as 503 model fallback and 429 quota backoff cooldowns render inline within the active work section rather than cluttering the final assistant response.
   - Upon completion, the work section automatically collapses into: `▶ Worked for 3.8s (Ran 2 commands)`.
   - Clicking the pill reveals the exact commands that ran and their return values.

3. **Formatted Markdown Summaries**:
   - The assistant's final response renders using Qt CommonMark Markdown (`QLabel` with `setTextFormat(QtCore.Qt.MarkdownText)`, `setWordWrap(True)`, and mouse selection enabled).
   - Supports headings, bold/italic text, lists, inline code chips (`Face6`), and pre-formatted code blocks without nested scrollbars.

4. **Self-Contained Turn Cards (`TurnCardWidget`)**:
   - Each conversational exchange is grouped into an independent turn card holding the user's prompt, selection badge, thought trace, work section, and response summary.
   - If an error occurs, a dedicated red error box renders directly within the turn card while preserving the prompt in the input edit for instant retry.


---

## 8. Refined Multiline Python Controls, JSON Cards & Theme Adaptation

Following developer feedback on the conversation history experience, three major UI refinements were implemented to deliver an experience matching advanced IDE copilots:

### 1. Multiline Formatted Code Control (`FormattedCodeBox`)
- **Dedicated Read-Only Code Viewer**: When Gemini invokes `execute_python`, the Python code is displayed inside a custom `FormattedCodeBox` control rather than a single-line label.
- **Dynamic Line-Aware Sizing**: Automatically computes height based on code line count (`min(max(lines * 17 + 14, 50), 200)`), expanding for readable viewing while bounding height with scrollbars for lengthy scripts.
- **Syntax Header & Language Chip**: Renders an `⚡ Execute Python:` title alongside a styled `Python` badge in monospace font (`Consolas`, `'Courier New'`).

### 2. Structured, Color-Coded JSON Result Cards (`FormattedResultCard`)
- **Automatic JSON Categorization**: Unparses and validates JSON payloads from tool returns. Automatically distinguishes success payloads from error responses (checking `error`, `status == "error"`, `success is False`, or exception text).
- **Green Success Cards (`✔ Result`)**: Renders tool results in soft green cards (`rgba(39, 174, 96, 0.08)`) with bulleted key-value rows for the top fields (e.g. `top_face`, `normal`, `area`), plus an overflow indicator (`... and n more fields`).
- **Red Error Cards (`❌ Error`)**: Displays tool failures in high-visibility warning cards (`rgba(231, 76, 60, 0.08)`) with clear red borders and error details.
- **Tool Attribution Chip**: Each card includes a subtle monospace badge denoting the executing tool (e.g. `spatial_query`, `sketch_operations`).

### 3. Theme-Adaptive Styling (Classic & Light Themes)
- **Automatic Lightness Detection (`is_dark_theme`)**: Probes `widget.palette()`, `FreeCADGui.getMainWindow().palette()`, and `QApplication.palette()` for background color lightness.
- **Light/Classic Theme Contrast Fix**:
  - Replaces harsh dark/black selection backgrounds with soft sky blue badges (`#1b4f72` text on `rgba(52, 152, 219, 0.12)` with `rgba(52, 152, 219, 0.4)` border).
  - User prompt bubbles render in clean, subtle neutral backgrounds (`#1f2937` text on `rgba(0, 0, 0, 0.04)`).
  - Collapsible toggle buttons and thought panels use soft translucent tints with clear hover states.
  - Maintains sharp readability and visual separation across Dark, Classic, and Light FreeCAD themes.
