---
status: approved
---

# Deselect a history result by clicking the grid's empty space

In PhotoCraft, the Generate panel's selected result can only be deselected by selecting another. The fork's thumbnail grid never reads a click that lands between or after the thumbnails, so it never sends an empty selection. The fork will send `select []` for such a click, as Qt does in Krita for a list that allows several selected items. Once the selection is empty, upstream's own code takes the result's preview off the canvas.

**Related documents**
- [Investigation findings](../../investigations/history-deselect-and-preview/findings.md)

## User Review Required

> [!IMPORTANT]
> **This changes only the PhotoCraft fork** (`coreyx/photocraft`, `feat/process-plugins`): `thumb_grid` and `list` in `crates/ui-egui/src/process_plugin_ui/render.rs`. The plug-in gets a test, no code change. As before, the fork's commits stay local until you ask for a push.

> [!NOTE]
> **Which clicks deselect, and which don't:**
> - **Deselects:** a plain click on empty space inside the grid, between thumbnails, after the last one in a row, or below the last row within the grid.
> - **Doesn't deselect:** a click on a thumbnail or a batch header, which selects it as now. A click on anything outside the grid, such as the Apply / "…" row under it, the prompt or the Generate button.
> - **Clicking the selected result again keeps it selected,** as you chose. Ctrl+click (⌘ on macOS) and Space still deselect.

> [!NOTE]
> **Only grids and lists that allow several selected items** (`selectionMode: "multi"`, from Qt's Extended, Multi and Contiguous modes) deselect this way. That's the history. A single-selection list, such as the settings dialog's page list, keeps its selection, as it does in Qt.

## Open Questions

None at this time.

## Proposed Changes

### PhotoCraft fork

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/render.rs`
- [ ] **TASK-1:** Add `empty_click(ui, n, cx, area_id)` beside `item_interaction`, used by `thumb_grid` and `list`:
  - **Before the items are drawn,** it senses a click on the grid's area from the previous frame, kept in egui's temporary memory under `area_id`. Items are registered after it, so they sit above it and take the clicks that land on them. Only a click that misses every item reaches it.
  - **The area** is the grid's rect at the full width it was laid out in, so it includes the rest of a short row. It's updated after the items are laid out each frame. On the first frame there is none yet, and nothing is sensed.
  - **On a plain primary click** (no Shift, no Ctrl/⌘), in `multi` mode, with a non-empty selection, it sets the local `selected` to `[]` and emits `InputKind::Select` with `[]`, as `select` does. Otherwise it does nothing.

  A comment explains why: Qt clears an Extended-selection list's selection on a click that hits no item. Upstream's history relies on this to deselect and hide its preview, and the fork had no way to send it.
- [ ] **TASK-2:** Call `empty_click` from `thumb_grid` and `list`, then store each one's area after its items. Keys are still forwarded while the pointer is over the area. A secondary click on empty space still sends nothing.

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/tests.rs`
- [ ] **TASK-3:** Add `a_click_on_a_grids_empty_space_clears_its_selection`:
  1. Set up a `thumbGrid` in `multi` mode with two 48-pt thumbnails, `selected: ["r1"]`, in a 700-pt harness, so the row has empty space after `r2`.
  2. Run a few frames.
  3. Click a point inside the grid's area to the right of `r2`, and check one `Select` event with `[]`.
  4. In the same test:
     - with nothing selected, a click there sends nothing;
     - in a single-selection `list`, a click on empty space sends nothing;
     - a click on `r2` still sends `["r2"]`.

  Before TASK-1 and TASK-2, step 3 fails.

### Plug-in

#### [MODIFY] `tests/photocraft/test_qt_mirror_rich.py`
- [ ] **TASK-4:** In `test_history_list`, after selecting `red`, send `select []`. Check three things:
  - the grid's `selected` is `[]`;
  - the history has no selected item;
  - Apply is hidden again.

  This pins the plug-in's half of the deselect. The scratch check in the findings showed it already works.

## Verification Plan

### Automated Tests
1. **Fork:** `cargo test -p photocraft-ui-egui --lib process_plugin_ui`, with the new test (TASK-3). It's run once before TASK-1 to confirm it fails.
2. **Plug-in:** `pytest tests/photocraft/test_qt_mirror_rich.py` (TASK-4).
3. **Regression:**
   - **Fork:** `cargo clippy -p photocraft-ui-egui --tests` and `cargo fmt --check`.
   - **Fork tests:** `cargo test -p photocraft-ui-egui --lib`. The 24 debug-build glyph failures that predate this work are expected; nothing else may fail.
   - **Plug-in:** the CI-equivalent pass, meaning format, lint, `pyright`, the three suites under coverage and the coverage gate.

### Manual Verification
In the fork's PhotoCraft release build, with the plug-in package installed and your local ComfyUI:
1. Generate, then click a result. Its preview shows on the canvas, and Apply shows under the history.
2. Click empty space in the grid, to the right of the last result in its row. The result is deselected, the preview leaves the canvas, and Apply hides.
3. Select a result, then click the prompt, the Generate button and the Apply row's background. The result stays selected and its preview stays.
4. Click the selected result again. It stays selected.
5. Ctrl+click it, and it's deselected. Select it again, hover the grid and press Space: deselected.
6. Right-click empty space in the grid. Nothing changes.
7. Open the plug-in's settings and click empty space under the page list. The current page stays selected.

## Visual design application

No visual change: the grid and its selection highlight look as they do now. Only a click on the grid's empty space gains a meaning.
