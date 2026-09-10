# FreeCAD CAM Workbench Architecture & Programmatic Best Practices

This document details critical architectural insights, root-cause analyses, and recommended practices for programmatic CAM operations in FreeCAD (including the `freecad-mcp` server, headless scripts, and Python plugins).

---

## Table of Contents
1. [Overview](#overview)
2. [Issue 1: Tree View Hierarchy Flattening](#issue-1-tree-view-hierarchy-flattening)
   - [Root Cause in FreeCAD C++ DocumentModel](#root-cause-in-freecad-c-documentmodel)
   - [The Complete Fix](#the-complete-fix)
3. [Issue 2: Operation Toolpath Invisibility & Missing ViewProviders](#issue-2-operation-toolpath-invisibility--missing-viewproviders)
   - [Root Cause](#root-cause)
   - [The Solution](#the-solution)
4. [Issue 3: Phantom ToolBit Meshes & Orphan Accumulation](#issue-3-phantom-toolbit-meshes--orphan-accumulation)
   - [Root Cause in ToolBit Visual Representation](#root-cause-in-toolbit-visual-representation)
   - [Deep Visibility Suppression](#deep-visibility-suppression)
   - [Cascading Tool Deletion](#cascading-tool-deletion)
5. [Summary of Implemented Fixes in `freecad-mcp`](#summary-of-implemented-fixes-in-freecad-mcp)
6. [Recommendations for Upstream FreeCAD (`FreeCAD/FreeCAD`)](#recommendations-for-upstream-freecad-freecadfreecad)

---

## Overview

When interacting with FreeCAD's CAM (Path) Workbench via Python APIs (such as through RPC or MCP), operations often bypass the GUI command dispatchers (`Gui::Command`). While this is necessary for headless execution, it uncovers several synchronization gaps between FreeCAD's App document graph and its Qt GUI model (`Gui::DocumentModel` and `ViewProvider`).

Without specific accommodations, users encounter:
1. **Flattened Tree Views**: Sub-containers (`Operations`, `Model`, `Stock`, `SetupSheet`, `Tools`) appear loose at the root of the document rather than nested under `Job`.
2. **Invisible Toolpaths**: Operations appear calculated in the data model, but 3D toolpath lines (G-code paths) fail to render in the viewport.
3. **Phantom Cutter Meshes**: Cutter geometry appears locked at `(0, 0, 0)` in 3D, cannot be selected or hidden via the tree view, and persists even after deleting the tool.

---

## Issue 1: Tree View Hierarchy Flattening

### Root Cause in FreeCAD C++ DocumentModel

In standard GUI usage, creating a CAM Job invokes `PathScripts.PathJobGui.CommandJobCreate()`, which sets up the GUI ViewProvider before sub-objects are linked.

When created programmatically via `PathScripts.PathJob.Create(job_name, model_list, None)`:
1. The C++ `App::DocumentObject` is created with its link properties: `job.Operations`, `job.Model`, `job.Stock`, `job.SetupSheet`, and `job.Tools`.
2. Later, when the GUI ViewProvider is attached:
   ```python
   job.ViewObject.Proxy = Path.Main.Gui.Job.ViewProvider(job.ViewObject)
   job.ViewObject.addExtension("Gui::ViewProviderGroupExtensionPython")
   ```
   the C++ Qt Tree Model (`Gui::DocumentModel`, specifically `src/Gui/DocumentModel.cpp`, line 549) has **already registered the objects**.
3. In `DocumentModel::slotChangeObject()`, `claimChildren()` is **only** triggered when a `PropertyLink` change notification is fired:
   ```cpp
   if (isPropertyLink(Prop)) {
       // calls claimChildren() to rearrange Qt tree items
   }
   ```
   Merely attaching `job.ViewObject.Proxy` or `Gui::ViewProviderGroupExtensionPython` does **not** fire a `PropertyLink` change event. Consequently, `DocumentModel` never claims the child containers under `Job`, leaving all 5 containers floating at the root level of the tree.

### The Complete Fix

To force `DocumentModel` to execute `claimChildren()` and re-parent the items into the GUI tree under `Job`, re-trigger the link property assignments immediately after attaching the ViewProvider and group extension:

```python
if FreeCAD.GuiUp and hasattr(job, 'ViewObject') and job.ViewObject:
    from Path.Main.Gui.Job import ViewProvider as JobViewProvider
    if not job.ViewObject.Proxy:
        job.ViewObject.Proxy = JobViewProvider(job.ViewObject)
    if hasattr(job.ViewObject, "extensions") and "Gui::ViewProviderGroupExtensionPython" not in job.ViewObject.extensions():
        job.ViewObject.addExtension("Gui::ViewProviderGroupExtensionPython")

    # Re-trigger PropertyLink notifications to force DocumentModel::slotChangeObject()
    # to invoke claimChildren()
    for prop in ("Operations", "Model", "Stock", "SetupSheet", "Tools"):
        if hasattr(job, prop):
            val = getattr(job, prop)
            if val:
                setattr(job, prop, val)

    job.ViewObject.Visibility = True
    if hasattr(job, 'Operations') and job.Operations and hasattr(job.Operations, 'ViewObject') and job.Operations.ViewObject:
        job.Operations.ViewObject.Visibility = True

    import FreeCADGui
    FreeCADGui.updateGui()
```

---

## Issue 2: Operation Toolpath Invisibility & Missing ViewProviders

### Root Cause

When operations (e.g. `PocketShape`, `Profile`, `MillFace`) are added via `PathScripts.<Op>.Create(job)`:
1. The underlying `Path::FeaturePython` data object is created and appended to `job.Operations.Group`.
2. However, the operation's GUI ViewProvider is **not** assigned. In FreeCAD CAM, toolpath rendering and task panel integration are handled by `Path.Op.Gui.Base.ViewProvider`, initialized with the operation's specific command resource dictionary (`Command.res`).
3. Furthermore, `job.Operations`'s own `ViewObject.Visibility` is often initialized to `False` or defaults to hidden when created headlessly. If the parent group is hidden, Qt and Coin3D hide all child toolpath line nodes.

### The Solution

In `_create_path_op()`:
1. Ensure the parent `job.Operations` group is explicitly visible.
2. Dynamically import and attach the corresponding GUI ViewProvider with `Command.res`:

```python
# Ensure parent Operations container is visible
if hasattr(job, 'Operations') and job.Operations and hasattr(job.Operations, 'ViewObject') and job.Operations.ViewObject:
    job.Operations.ViewObject.Visibility = True

# Wire GUI ViewProvider for 3D toolpath visualization & task panel interaction
if FreeCAD.GuiUp and hasattr(op, 'ViewObject') and op.ViewObject:
    op.ViewObject.Visibility = True
    try:
        from Path.Op.Gui.Base import ViewProvider as OpViewProvider
        import importlib
        mod_name = create_fn.__module__.replace('Path.Op.', 'Path.Op.Gui.')
        gui_mod = importlib.import_module(mod_name)
        if hasattr(gui_mod, 'Command') and hasattr(gui_mod.Command, 'res'):
            op.ViewObject.Proxy = OpViewProvider(op.ViewObject, gui_mod.Command.res)
    except Exception:
        pass
```

---

## Issue 3: Phantom ToolBit Meshes & Orphan Accumulation

### Root Cause in ToolBit Visual Representation

FreeCAD's `ToolBit` system represents cutting tools using parametric PartDesign shapes (`PartDesign::Body` + `PartDesign::Revolution`):
1. When `tool_bit.attach_to_doc(doc)` is called, `ToolBit._update_visual_representation()` sets:
   ```python
   BitBody.ViewObject.ShowInTree = False
   BitBody.ViewObject.Visibility = False
   ```
2. However, it leaves:
   - The inner `Revolution` feature with `Visibility = True`
   - The outer `tool_obj.Shape` with `Visibility = True`
3. Because `ShowInTree = False`, the body does **not** appear in the tree view. But because the inner Coin3D scene node is visible, a yellow/grey cutter mesh is rendered at `(0, 0, 0)`. The user cannot click it, select it in the tree, or toggle its visibility with the Spacebar.
4. When `doc.removeObject(tool.Name)` was called to delete the tool, FreeCAD deleted only the `Path::ToolBit` object, leaving the underlying `PartDesign::Body` behind as an orphaned, unlisted object that still rendered in 3D.

### Deep Visibility Suppression

In `create_tool` and `update_tool`, recursively suppress visibility on all layers of the tool hierarchy:

```python
if hasattr(tool_obj, 'ViewObject') and tool_obj.ViewObject:
    tool_obj.ViewObject.Visibility = False

if hasattr(tool_obj, 'BitBody') and tool_obj.BitBody:
    bit_body = tool_obj.BitBody
    if hasattr(bit_body, 'ViewObject') and bit_body.ViewObject:
        bit_body.ViewObject.Visibility = False
        bit_body.ViewObject.ShowInTree = False
    if hasattr(bit_body, 'Group'):
        for child in bit_body.Group:
            if hasattr(child, 'ViewObject') and child.ViewObject:
                child.ViewObject.Visibility = False
    if hasattr(bit_body, 'Tip') and bit_body.Tip:
        if hasattr(bit_body.Tip, 'ViewObject') and bit_body.Tip.ViewObject:
            bit_body.Tip.ViewObject.Visibility = False
```

### Cascading Tool Deletion

In `delete_tool`, explicitly delete `tool.BitBody` before deleting `tool.Name`:

```python
# Cascade deletion to underlying BitBody so hidden PartDesign features don't orphan
if hasattr(tool, 'BitBody') and tool.BitBody:
    try:
        doc.removeObject(tool.BitBody.Name)
    except Exception:
        pass

doc.removeObject(tool.Name)
```

---

## Summary of Implemented Fixes in `freecad-mcp`

| Component | File | Fix Implemented |
|---|---|---|
| **Job Hierarchy** | `AICopilot/handlers/cam_ops.py` | Attach `Job.ViewProvider` and `Gui::ViewProviderGroupExtensionPython`; re-assign link properties to trigger `DocumentModel::slotChangeObject()` claimChildren. |
| **Toolpaths** | `AICopilot/handlers/cam_ops.py` | Auto-attach `OpViewProvider` using `Path.Op.Gui.<OpName>.Command.res`; enforce `job.Operations.ViewObject.Visibility = True`. |
| **Tool Cleanup** | `AICopilot/handlers/cam_tools.py` | Cascade deletion to `tool.BitBody.Name` before removing tool object. |
| **Mesh Suppression** | `AICopilot/handlers/cam_tools.py` | Deeply suppress `Visibility` on `tool_obj`, `BitBody`, `BitBody.Group`, and `BitBody.Tip` on creation and recompute. |
| **Diagnostic Repair** | `AICopilot/handlers/cam_ops.py` | Added `repair_cam_tree` operation to fix broken documents and purge orphaned cutter bodies. |

---

## Recommendations for Upstream FreeCAD (`FreeCAD/FreeCAD`)

For contributors working directly on FreeCAD core C++ or the CAM Workbench:

1. **`src/Mod/CAM/App/PathJob.cpp` & `PathJobGui.cpp`**:
   - `Job` creation in Python (`PathJob.Create()`) should automatically associate its default ViewProvider when `GuiUp` is true, or expose an explicit `job.rebuildTree()` method in `PathJobGui`.
   - `DocumentModel` should listen to `ViewObject.addExtension()` or provide a Python binding to `rebuildChildren()` / `claimChildren()` without requiring artificial `PropertyLink` reassignment.

2. **`src/Mod/CAM/PathScripts/PathToolBit.py`**:
   - In `_update_visual_representation()`, visibility should be recursively set to `False` on the inner `Revolution` and `BitBody.Tip` when `ShowInTree` is set to `False`.
   - `ToolBit` should register an `onDocumentDeleted` / `removeObject` callback to automatically remove its companion `BitBody`.

