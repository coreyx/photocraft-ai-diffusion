---
status: approved
---

# Keep a long drop-down choice from pushing the Upscale workspace past the panel

With the default upscaler selected, `Default (4x_NMKD-Superscale-SP_178000_G)`, the Upscale workspace ran past the panel's right edge. The Scale field, the Tile Overlap field, the Use Prompt switch and the queue button were cut off. There were two causes. The fork's drop-down grew to its selected text, and egui widened the panel's layout to fit it. And Qt's minimum for the workspace followed the drop-down's longest item, so the plug-in drew the Upscale button for 355 px. The fork will cut a drop-down's selected text to fit. For a panel, the mirror will give Qt drop-downs a short minimum instead of their longest item.

**Related documents**
- [Investigation findings](../../investigations/upscale-panel-rows-overflow/findings.md)

## User Review Required

> [!IMPORTANT]
> **This changes the PhotoCraft fork** (`coreyx/photocraft`, `feat/process-plugins`) as well as the plug-in. Every plug-in drop-down, in panels and dialogs, now cuts its selected text with an ellipsis when it's wider than the drop-down. The full text shows as a tooltip when the plug-in gives the drop-down none of its own, and every item still shows in full in the list.

> [!NOTE]
> **Only panels change on the plug-in side**, as you chose. In a mirrored panel, a `QComboBox` that has Qt's default size policy (`AdjustToContentsOnFirstShow`) gets `AdjustToMinimumContentsLengthWithIcon` with a minimum of 8 characters. A drop-down whose code chose its own size policy keeps it. This changes only the layout the plug-in computes, which sets the size of the widgets it draws as images. PhotoCraft draws drop-downs itself. Dialogs keep their current sizes.

## Open Questions

None at this time.

## Proposed Changes

### PhotoCraft fork

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/render.rs`
- [x] **TASK-1:** In `combo()`, build craft-ui's `ComboBox` with `.truncate()`, so the selected text is cut with an ellipsis to the width it's given rather than widening the drop-down. When the node has no `tooltip` prop, the drop-down's response shows the full selected text on hover. A comment explains why: craft-ui's `width` is a minimum, and a drop-down wider than the panel widens egui's layout region, which pushes every right-aligned item in the rows after it past the edge.

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/tests.rs`
- [ ] **TASK-2:** Add `a_long_combo_choice_stays_inside_the_panel`, in a harness 300 points wide that draws the tree inside a vertical scroll area, like a panel's body:
  1. A column holds a combo whose selected item is a 45-character name.
  2. After it, a row: a `grow` label, then a spin box.
  3. Check that the combo and the spin box end inside 300 points.
  4. Check that the combo's accessible value is still the full name.

  Before TASK-1, the combo ends at about 357 points and the spin box with it.

### Plug-in

#### [MODIFY] `photocraft_host/qt_mirror/mirror.py`
- [ ] **TASK-3:** In `Mirror.build`, when a panel's mirror first tracks a `QComboBox` that has Qt's default `sizeAdjustPolicy`, set `AdjustToMinimumContentsLengthWithIcon` with `setMinimumContentsLength(PANEL_COMBO_CHARS)`, a new constant of 8. A comment explains why:
  - with the default policy, Qt's minimum is the longest item;
  - the mirror lays a panel out at that minimum when it's wider than PhotoCraft's width, so self-drawn widgets are drawn too wide;
  - PhotoCraft draws drop-downs at its own width, cutting long text.

  A dialog's mirror leaves its drop-downs alone.

#### [MODIFY] `tests/photocraft/test_qt_mirror_rich.py`
- [ ] **TASK-4:** Add `test_a_long_drop_down_choice_doesnt_widen_the_panel`:
  1. Set up a panel with a `QComboBox` holding a 45-character item, then a row with a self-drawn widget (the test file's existing painted widget) beside a tool button.
  2. Send `panel.resized` with 280 points. The root lays out at 280, not at the combo's full width, and the self-drawn widget's image fits within it.
  3. Mirror the same combo in a dialog: it keeps `AdjustToContentsOnFirstShow`.
  4. Mirror a combo whose code set its own policy, in a panel: it keeps that policy.

  Before TASK-3, step 2 fails.

## Verification Plan

### Automated Tests
1. **Fork:** `cargo test -p photocraft-ui-egui --lib process_plugin_ui`, with TASK-2's test. It's run once before TASK-1 to confirm it fails.
2. **Plug-in:** `pytest tests/photocraft/test_qt_mirror_rich.py`, with TASK-4's test. It's run once before TASK-3 to confirm it fails.
3. **Regression:**
   - **Fork:** `cargo fmt --check` and `cargo clippy -p photocraft-ui-egui --tests`. `cargo test -p photocraft-ui-egui --lib`, where only the 24 known debug-build glyph failures may fail.
   - **Plug-in:** the CI-equivalent pass, including the workspace snapshot tests (`tests/photocraft/fixtures/mirror/*.json`). If their recorded sizes change, they're updated in TASK-4's commit, with what changed.

### Manual Verification
In the fork's PhotoCraft release build, with the rebuilt package and your local ComfyUI, at the dock's default width:
1. Switch the panel to Upscale, with the default upscaler selected. The upscaler drop-down ends inside the panel, its name cut with "…", and hovering it shows the full name.
2. The Scale field, the Tile Overlap field, the Use Prompt switch and the queue button are all inside the panel.
3. Open the upscaler drop-down. Every name shows in full.
4. Switch to Generate. Its rows still fit, and the style drop-down works.
5. Open the plug-in's settings. The dialog opens at the same size as before, and its drop-downs work.

## Visual design application

No new visual language. A drop-down whose selected text doesn't fit now ends it with "…", as text that doesn't fit is cut elsewhere in PhotoCraft.
