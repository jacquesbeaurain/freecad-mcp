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

### Live Python Fallback & 100mm Solid Cube Verification
When `part_operations` encountered the `create_box` mismatch, the Copilot gracefully fell back to `execute_python`, adhered to canonical solid modeling rules, verified geometry health, and successfully created a valid 6-faced solid `Part::Box` with 100x100x100mm dimensions and 1,000,000 mm³ volume:
![Live 100mm Cube Creation via Python Fallback](img/cube_fallback_verification.png)

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
| [`2cd57cb`](../../../commit/2cd57cb) | `feat(copilotui): add execute_python cad helpers, geometry health validation, and scripting rules` | [`../AICopilot/handlers/execute_python_ops.py`](../AICopilot/handlers/execute_python_ops.py), [`../AICopilot/ui/agent_worker.py`](../AICopilot/ui/agent_worker.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py), [`img/cube_fallback_verification.png`](img/cube_fallback_verification.png) |
| [`3b3e306`](../../../commit/3b3e306) | `fix(cam): support shape and cutting_edge_height parameter aliases in cam_tools` | [`../AICopilot/handlers/cam_tools.py`](../AICopilot/handlers/cam_tools.py), [`../tests/unit/test_cam_wrappers.py`](../tests/unit/test_cam_wrappers.py) |
| [`b3f4f00`](../../../commit/b3f4f00) | `feat(cam): implement face/mill_face operation via Path.Op.MillFace` | [`../AICopilot/handlers/cam_ops.py`](../AICopilot/handlers/cam_ops.py), [`../tests/unit/test_cam_wrappers.py`](../tests/unit/test_cam_wrappers.py) |
| [`bd5a317`](../../../commit/bd5a317) | `feat(cam): detect CAM environment at startup and pre-populate PathScripts compat bridge` | [`../AICopilot/compat_pathscripts.py`](../AICopilot/compat_pathscripts.py), [`../tests/unit/test_pathscripts_compat.py`](../tests/unit/test_pathscripts_compat.py) |
| [`beefcbe`](../../../commit/beefcbe) | `fix(cam): preserve native on-disk PathScripts submodules in compatibility bridge` | [`../AICopilot/compat_pathscripts.py`](../AICopilot/compat_pathscripts.py), [`../tests/unit/test_pathscripts_compat.py`](../tests/unit/test_pathscripts_compat.py) |
| [`0a4f81b`](../../../commit/0a4f81b) | `feat(cam): add startup redirects and aliases for Path.Op.Face, Path.Job, and related CAM modules` | [`../AICopilot/compat_pathscripts.py`](../AICopilot/compat_pathscripts.py), [`../tests/unit/test_pathscripts_compat.py`](../tests/unit/test_pathscripts_compat.py) |
| [`84ebc18`](../../../commit/84ebc18) | `feat(ui): add settings gear menu, auto-save toggle, model persistence, and command history stack` | [`../AICopilot/settings.py`](../AICopilot/settings.py), [`../AICopilot/ui/dock_widget.py`](../AICopilot/ui/dock_widget.py), [`../AICopilot/handlers/execute_python_ops.py`](../AICopilot/handlers/execute_python_ops.py), [`../AICopilot/handlers/base.py`](../AICopilot/handlers/base.py), [`../tests/unit/test_copilot_dock_widget.py`](../tests/unit/test_copilot_dock_widget.py) |

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


---

## 9. Python Fallback Hardening, CAD Helpers & Geometry Health Validation

### 1. Root Cause of the "Zero-Sided Cube"
When evaluating the prompt `"Make a 100mm cube"`, the previous implementation produced an empty PartDesign Body with an extruded Pad that had 0 faces and 0 volume:
1. **Mathematical Collapse**: The LLM script generated 4 coincident lines and attempted to center them using:
   ```python
   sketch.addConstraint(Sketcher.Constraint("Symmetric", 0, 1, 0, 2, -1, 1))
   sketch.addConstraint(Sketcher.Constraint("Symmetric", 1, 1, 1, 2, -1, 1))
   ```
   In FreeCAD Sketcher, axis `-1` is the horizontal X-axis ($y = 0$). Line 0 had endpoints at $y = -50$. Symmetrizing two points with identical negative $y$-coordinates across the horizontal axis mathematically forces $y = 0$. In combination with coincident corners and horizontal/vertical constraints, all 4 vertices collapsed into a single degenerate point $(3.55 	imes 10^{-15}, 1.77 	imes 10^{-15}, 0)$ of length $pprox 0$.
2. **OpenCASCADE Null Shape**: FreeCAD's Sketcher solver reported status `-4` (conflicting constraints) with `State=['Touched', 'Invalid']`. Extruding this degenerate sketch via `PartDesign::Pad` produced `Standard_NullObject BRepCheck_Analyzer::Init() - NULL shape`.
3. **Silent Success False Positive**: Because Python did not raise an unhandled exception, `execute_python` previously returned `{"success": True}` with silence, blinding the agent to the failure.

### 2. Built-in CAD Helpers in `execute_python`
To guarantee the Python fallback generates valid geometry every time, `execute_python_ops.py` now injects pre-tested CAD helper functions into its persistent namespace:
- `create_box(length=100, width=None, height=None, body=None, name="Box")`: Creates a valid solid box/cube inside a PartDesign Body if present, or a `Part::Box` otherwise.
- `create_cylinder(radius=10, height=20, body=None, name="Cylinder")`: Creates an `AdditiveCylinder` or `Part::Cylinder`.
- `create_sketch(plane="XY", body=None, name="Sketch")`: Properly attaches a sketch to a Body Origin plane or document coordinates.
- `add_rectangle(sketch, width=100, height=None, center=True, x=0, y=0)`: Adds 4 lines with robust corner offset constraints (`DistanceX`, `DistanceY`) that never mathematically collapse.
- `pad_sketch(sketch, length=10, name="Pad", reversed=False)`: Extrudes a sketch into a solid Pad within its Body.

### 3. Post-Execution Geometry Health Inspection
After executing code in `execute_python_ops.py`:
- Triggers `doc.recompute()`.
- Inspects all document objects:
  - Detects if any object has `State` with `'Invalid'` or `'Error'`.
  - Detects if any sketch has `sketch.solve() < 0` (e.g. `-4` over-constrained, `-2` conflicting).
  - Detects if any 3D solid feature produced a NULL shape (`shape.isNull()`) or zero faces (`len(shape.Faces) == 0`).
- If any geometry error is detected, returns `{"success": False, "error": "Geometry validation failed: ..."}` with actionable diagnostic feedback. This alerts Gemini's function-calling loop immediately so the model can self-correct instead of falsely reporting completion.

### 4. Canonical Scripting Rules in System Instruction
The Copilot's `SYSTEM_INSTRUCTION` was updated with explicit rules:
- Prefer 1-step solids (`body.newObject("PartDesign::AdditiveBox", "Box")` or `create_box()`).
- Explicitly forbids applying axis symmetry across the same axis on horizontal or vertical lines.


---

## 10. Direct Tool Bridge Operations & Measurement Handling

### 1. Root Cause of Measurement & Creation Errors
During manual testing of "Make a 100mm cube", Gemini attempted post-creation verification using the `measurement_operations` tool and primitive creation via `part_operations`:
1. **Unknown Operation Error**:
   - `tool_bridge.py` declared `"enum": ["bounding_box", "volume", ...]` to Gemini.
   - However, `MeasurementOpsHandler` implemented `get_bounding_box`, `get_volume`, `get_surface_area` and registered only those in `_ALLOWED_OPERATIONS`.
   - In `DirectToolBridge._dispatch_direct`, it evaluated `getattr(server.measurement_ops, op, None)` with `op="bounding_box"`, which returned `None`, triggering `ValueError: Unknown Measurement operation: bounding_box`.
2. **`create_box` vs `box` Mismatch**:
   - Gemini invoked `part_operations` with `operation="create_box"`.
   - `PrimitivesHandler` implements `box()`, causing dispatch failures when using the prefixed name.

### 2. Implementation Details
1. **Measurement Operations Harmonization (`AICopilot/handlers/measurement_ops.py`)**:
   - Added canonical operations (`bounding_box`, `volume`, `surface_area`, `mass_properties`, `center_of_mass`) to `_ALLOWED_OPERATIONS`.
   - Added aliases: `bounding_box = get_bounding_box`, `volume = get_volume`, `surface_area = get_surface_area`.
   - Added robust target object resolution: automatically accepts `object_name`, `name`, `target`, or `obj`, and verifies that PartDesign Bodies and Part primitives have valid shapes before bounding box calculations.
2. **Tool Bridge Normalization (`AICopilot/ui/tool_bridge.py`)**:
   - In `part_operations` dispatch: dynamically strips `create_` prefixes (mapping `create_box` -> `box`, `create_cylinder` -> `cylinder`, `create_sphere` -> `sphere`).
   - In `measurement_operations` dispatch: maps `bounding_box` -> `get_bounding_box`, `volume` -> `get_volume`, `surface_area` -> `get_surface_area`.
   - Aligned Gemini tool declarations schema with valid operations.
3. **Automated Unit Verification (`tests/unit/test_copilot_dock_widget.py`)**:
   - Added unit tests: `test_direct_tool_bridge_measurement_bounding_box` and `test_direct_tool_bridge_part_operations_create_box`.
   - All 31 unit tests pass.

### 3. Verification & Live Inspection
Verified live in FreeCAD on both Part primitives and PartDesign Bodies:
- Direct tool bridge execution of `measurement_operations` with `operation="bounding_box"` accurately reports bounding box coordinates:
  `Bounding box for Body: X: 0.00 to 100.00 mm (length: 100.00), Y: 0.00 to 100.00 mm (length: 100.00), Z: 0.00 to 100.00 mm (length: 100.00)`.


---

## 11. PartDesign Additive Primitives & Intelligent Dimension Defaulting

### 1. Overview
To deliver instantaneous 1-step solid creation and eliminate fragile sketch extrusions for basic geometry (such as "Make a 100mm cube"), native support for PartDesign additive primitives was integrated directly into `PartDesignOpsHandler` and `DirectToolBridge`.

### 2. Implementation Details
1. **PartDesign Additive Primitives (`AICopilot/handlers/partdesign_ops.py`)**:
   - `create_body`: Creates and registers a `PartDesign::Body` in the active document.
   - `additive_box`: Creates a `PartDesign::AdditiveBox` inside the active or specified Body. Automatically populates `width` and `height` from `length` (or `size`) for uniform cube requests.
   - `additive_cylinder`: Creates a `PartDesign::AdditiveCylinder` with `radius` and `height`.
   - `additive_sphere`: Creates a `PartDesign::AdditiveSphere` with `radius`.
   - Automatic Body resolution via `_resolve_target_body`: uses existing body or auto-creates one if absent.
2. **Part Primitives Dimension Defaulting (`AICopilot/handlers/primitives.py`)**:
   - `create_box`: Supports `size` parameter and defaults `width` and `height` to `length` when omitted.
3. **Tool Bridge & Schema Alignment (`AICopilot/ui/tool_bridge.py`)**:
   - Exposed `create_body`, `additive_box`, `additive_cylinder`, `additive_sphere` with aliases (`box`, `cylinder`, `sphere`) in `DirectToolBridge`.
   - Updated tool declaration schemas for Gemini function calling.
4. **System Instruction Guidance (`AICopilot/ui/agent_worker.py`)**:
   - Directs Gemini to invoke `partdesign_operations(operation="additive_box", length=100, width=100, height=100)` for PartDesign solids and `part_operations(operation="create_box", ...)` for Part CSG.

### 3. Verification
- **Automated Tests**: All 37 unit tests in `tests/unit/test_copilot_dock_widget.py`, all 39 tests in `test_primitives.py`, and all 92 tests in `test_partdesign_ops.py` pass.
- **Live Verification**: Direct execution verified live in FreeCAD:
  `Created AdditiveBox: Box (100.00x100.00x100.00mm) in Body: Body`
  `Bounding box of Body: X: 0.00 to 100.00 mm, Y: 0.00 to 100.00 mm, Z: 0.00 to 100.00 mm`


---

## 12. History Text Selection & LaTeX Markdown Sanitization

### 1. Overview
Two developer experience refinements were implemented in the conversation history cards:
1. **Full Text Selection & Copy Support**: All text elements inside the conversational stream—including tool execution badges (`⚡ Executing: ...`), structured JSON result cards (`✔ Result`, `❌ Error`, key-value lines), Python code boxes, selection badges, and error banners—now have mouse text selection flags enabled (`TextSelectableByMouse`), allowing developers to highlight and copy details directly with `Ctrl+C`.
2. **LaTeX Math Sanitization**: Qt's CommonMark Markdown engine does not render LaTeX math syntax (e.g. `$X$: $0.00 \text{ mm}$ to $900.00 \text{ mm}$`). The Copilot now combines prompt-level guidelines forbidding LaTeX output with an automated text sanitizer (`clean_markdown_text`) that transforms LaTeX variables and units into clean, human-readable plain text (`X: 0.00 mm to 900.00 mm`).

### 2. Implementation Details
1. **Selection Flags Across All History Widgets (`AICopilot/ui/dock_widget.py`)**:
   - `FormattedCodeBox`: Enabled `TextSelectableByMouse | TextSelectableByKeyboard` on code editor and header labels.
   - `FormattedResultCard`: Added `TextSelectableByMouse` to header, tool badge, key-value rows, and string fallbacks.
   - `WorkSection`: Added `TextSelectableByMouse` to live tool execution commands and notices.
   - `TurnCardWidget`: Added `TextSelectableByMouse` to selection badge, turn error box, and user prompt.
   - `SystemMessageWidget`: Added `TextSelectableByMouse` to info messages.
2. **Markdown LaTeX Sanitizer (`clean_markdown_text` in `dock_widget.py`)**:
   - Strips `\text{...}`, `\mathrm{...}`, `\mathbf{...}`.
   - Converts `\times` $\to$ `x`, `\approx` $\to$ `~`, `\pm` $\to$ `+/-`, `\leq`/`\geq` $\to$ `<=`/`>=`.
   - Unwraps inline `$ ... $` and block `$$ ... $$` math delimiters.
   - Collapses spacing before units (`0.00  mm` $\to$ `0.00 mm`).
   - Hooked into `TurnCardWidget.append_response_token` and `TurnCardWidget.finish_turn`.
3. **Agent System Instruction (`AICopilot/ui/agent_worker.py`)**:
   - Explicitly instructs Gemini in Guideline 8 to output clean plain text or standard Markdown and avoid LaTeX math markup.

### 3. Verification
- **Unit Tests**: All 40 unit tests in `tests/unit/test_copilot_dock_widget.py` pass (`0.35s`), verifying both `clean_markdown_text` behavior and `TextSelectableByMouse` flags across all history widgets.
- **Live FreeCAD Verification**: Verified live in running FreeCAD instance.

---

## 13. CAM Compatibility Bridge & Startup Detection

### 1. Overview
In FreeCAD 1.0+, CAM operations transitioned from legacy `PathScripts.*` modules to modern `Path.Main.*` and `Path.Op.*`. Calls in LLM-generated code or older macros such as `import PathScripts.PathJob as PathJob` or `from Path.Op.Face import Create` previously triggered `ModuleNotFoundError` or incurred repeated try/except import penalties on every operation.

### 2. Implementation Details
1. **Startup CAM Environment Detection (`AICopilot/compat_pathscripts.py`)**:
   - `detect_cam_environment()` probes once at startup (`"modern"`, `"legacy"`, or `"none"`).
   - Pre-populates Python's `sys.modules` at startup with all known mappings, allowing statements like `import PathScripts.PathJob as PathJob` to resolve in $O(1)$ time with zero finder overhead and zero `ImportError` exceptions.
2. **Submodule Aliasing & Redirects**:
   - Aliased `Path.Op.Face` and `Path.Op.Facing` $\to$ `Path.Op.MillFace`.
   - Aliased `Path.Op.Drill` $\to$ `Path.Op.Drilling`.
   - Aliased `Path.Job` $\to$ `Path.Main.Job`.
   - Preserved native on-disk `Mod/CAM/PathScripts` search path (`__path__`) so internal submodules (`PathUtils`, `PathPropertyBag`) load without collision.
3. **Operation Factory Caching (`AICopilot/handlers/cam_ops.py`)**:
   - Eliminated repeated per-call try/except imports in `profile()`, `pocket()`, `drilling()`, `adaptive()`, `face()`, and `surface()` using cached operation factory resolvers (`_get_op_create`, `_get_job_create`).
4. **Falsy Parameter Fix (`AICopilot/handlers/cam_tools.py`)**:
   - Fixed parameter fallback logic so legitimately supplied `0` values (e.g. `flute_length=0`) are not dropped by Python's `or` operator.

### 3. Verification
- All 12 unit tests in `tests/unit/test_pathscripts_compat.py` pass (`0.04s`).
- Live FreeCAD verification confirmed that `import PathScripts.PathJob as PathJob` and `from Path.Op.Face import Create` resolve instantly without exceptions.


---

## 14. Repository Line Ending Normalization & Hygiene

### 1. Line Ending Standardization
- Rewrote 33 commits on `feat_copilotui` to ensure 100% pure LF line endings across the entire branch history, completely eliminating CRLF noise in git diffs.
- Configured repository-level `.gitattributes`:
  ```gitattributes
  * text=auto eol=lf
  ```
- Added strict global guidelines in `~/.gemini/config/AGENTS.md` enforcing binary mode or `newline='\n'` for all file writes and forbidding IDE file modification tools that spawn focus-stealing editor diff tabs.


---

## 15. AI Copilot Settings, Gear Menu & Command History Stack

### 1. Persistent JSON Settings Architecture (`AICopilot/settings.py`)
- Centralized configuration manager automatically locating `<FreeCAD UserAppDataDir>/AICopilot/settings.json` (e.g. `%APPDATA%\FreeCAD\v26-3\AICopilot\settings.json`, falling back to `~/.freecad-copilot/settings.json`).
- Supported settings keys:
  - `"auto_save_on_execute"`: `bool` (default: `False`).
  - `"selected_model"`: `str` (default: `"gemini-3.6-flash"`).
  - `"command_history"`: `List[str]` (capped at 100 entries, consecutive duplicates deduplicated).
- Strictly reads and writes with Unix LF line endings (`newline="\n"`).

### 2. Configurable Auto-Save Behavior (`AICopilot/handlers/execute_python_ops.py`, `AICopilot/handlers/base.py`)
- Replaced unconditional `doc.save()` calls before code execution with a check against `get_setting("auto_save_on_execute", False)`.
- When disabled (`False`, default), running Python code will not overwrite the active document file on disk, preventing unintended changes during exploratory sessions.

### 3. Settings Gear Button (`⚙`) & Popup Menu (`AICopilot/ui/dock_widget.py`)
- The top toolbar contains a dedicated `⚙` button (`QToolButton`) with tooltip `"Settings"`.
- Features an instant popup menu (`QMenu`):
  - **Auto-Save Before Execution**: Checkable toggle synced with `settings.json`.
  - **Gemini API Key...**: Opens the API key input dialog.
  - **Clear Command History**: Clears saved prompt stack.
  - **Clear Conversation**: Resets active chat stream.
  - **Settings Dialog...**: Opens the modal preferences dialog.

### 4. Copilot Preferences Dialog (`CopilotSettingsDialog`)
- Modal dialog providing full configuration of execution safety, default model selection, API key entry, and settings storage path inspection.

### 5. Command History Stack & Hotkeys
- Enhanced `ChatInputTextEdit` to maintain prompt history, history index, and in-progress text draft:
  - **`Ctrl+Alt+Up`**: Cycles to earlier prompts in the history stack. Preserves in-progress drafts.
  - **`Ctrl+Alt+Down`**: Cycles to newer prompts, restoring the uncommitted draft when returning to the bottom.
  - **Standard `Up` / `Down` Arrow Keys**: Completely untouched for normal multi-line cursor navigation and text editing.
  - **Mouse Navigation Buttons**: Compact `▲` and `▼` tool buttons beside the prompt box for mouse users.
- On prompt send, non-empty prompts are automatically pushed to the history stack and persisted to `settings.json`.

### 6. Visual Verification

| Panel Docked with Gear & History Buttons | Settings Gear Popup Menu | Modal Preferences Dialog |
|---|---|---|
| ![Dock Widget with Gear & History Buttons](img/copilot_settings_history_gui.png) | ![Settings Gear Popup Menu](img/copilot_gear_menu_popup.png) | ![Copilot Preferences Dialog](img/copilot_settings_dialog_gui.png) |

### 7. Verification Results
All 59 unit tests passed:
```powershell
& "D:\repos\oth\FreeCAD\build\release\bin\python.exe" -m pytest tests/unit/test_copilot_dock_widget.py tests/unit/test_pathscripts_compat.py
```
- `test_copilot_settings_manager`: Verified defaults, set/get, deduplication, and LF file writes.
- `test_auto_save_disabled_by_default_in_execute_python`: Verified `doc.save()` is NOT called when auto-save is False.
- `test_auto_save_enabled_in_execute_python`: Verified `doc.save()` IS called when auto-save is True.
- `test_auto_save_disabled_by_default_in_save_before_risky_op`: Verified `save_before_risky_op` respects setting.
- `test_chat_input_text_edit_command_history`: Verified navigation through history and draft restoration.
- `test_chat_input_text_edit_hotkeys`: Verified `Ctrl+Alt+Up` and `Ctrl+Alt+Down` trigger history navigation, while standard `Up`/`Down` arrow keys are unaffected.
- `test_dock_widget_settings_menu_and_history_buttons`: Verified gear button menu, auto-save action toggle, mouse buttons, and model persistence.

