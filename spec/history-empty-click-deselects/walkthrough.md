# Walkthrough: deselect a history result by clicking the grid's empty space

A click on the empty space in the Generate panel's history now deselects the selected result, and its preview leaves the canvas ([findings](../../investigations/history-deselect-and-preview/findings.md)). The fix is in the PhotoCraft fork's grid. It now sends an empty selection for a click that hits no item, as Qt does in Krita. The plug-in needed no code change.

## What Was Implemented

### 1. PhotoCraft fork (`coreyx/photocraft`, `feat/process-plugins`)
- **`crates/ui-egui/src/process_plugin_ui/render.rs`** (`dc548e7fe`), `empty_click` and `remember_area`, used by `thumb_grid` and `list`:
  - **What a list keeps:** its area at the full width it was laid out in, from one frame to the next.
  - **How the click is sensed:** before the items are drawn, on that area. The items are registered after it and sit above it, so a click on a thumbnail or header still selects it.
  - **What it sends:** `select []` for a plain primary click, in a list allowing several selected items, while something is selected.
  - **What it ignores:** Shift, Ctrl/⌘ and Alt clicks, right-clicks, and single-selection lists.
- **`crates/ui-egui/src/process_plugin_ui/tests.rs`** (`7b4bcbefa`): `a_click_on_a_grids_empty_space_clears_its_selection`.

### 2. Plug-in
- **`tests/photocraft/test_qt_mirror_rich.py`** (`48759d6`): `test_history_list` sends `select []` after selecting a result. The grid's `selected` empties, the history has no selected item, and Apply hides.

## Verification & Test Results

### Automated Tests
- **`a_click_on_a_grids_empty_space_clears_its_selection`:** a click right of the last thumbnail sends `[]`. A second click, with nothing selected, sends nothing. A click on a thumbnail sends its id. In a single-selection list, a click on empty space sends nothing. Before the fix it failed on the first assertion, with no event sent. **Passed**
- **`test_history_list`:** **Passed**, with the mirror's other 24 tests in `test_qt_mirror_rich.py`.

### Regression Testing
- **Plug-in**, the CI-equivalent pass:

  | Check | Result |
  |---|---|
  | Format, lint, `upstream_changes.py` | Clean |
  | `pyright` | 0 errors |
  | Plug-in tests | 352 passed |
  | Upstream unit tests | 268 passed, 27 skipped |
  | Stand-in tests | 246 passed, 19 skipped |
  | Coverage gate | 93.3% of lines and 78.5% of branches overall |

- **Fork:**
  - `cargo fmt --check` and `cargo clippy -p photocraft-ui-egui --tests` are clean.
  - `cargo test -p photocraft-ui-egui --lib`: 4882 passed, 24 failed. These are the same 24 debug-build glyph failures as before; see `context-menu-reopen-fix`'s walkthrough.
  - In `process_plugin_ui`, the same four tests fail with this change stashed.

## Manual Verification
Done in the fork's release build, with the plug-in in an isolated profile and your local ComfyUI. One generation gave two results:
1. **Selecting a result:** the first result was selected, its preview was on the canvas and Apply showed. **Passed**
2. **Deselecting:** a click on the empty space right of the second result deselected it. The preview left the canvas and Apply hid. **Passed**
3. **Clicks that keep the selection:** with the second result selected, each of these kept it selected, with its preview showing:
   - a click on the prompt;
   - a click on the Apply row's background;
   - a click on the selected result again;
   - a right-click on the grid's empty space, which also opened no menu.

   **Passed**
4. **Space**, with the pointer over the grid, deselected the result and its preview left. **Passed**
5. **The settings dialog's page list:** a click beside and under the list kept Styles selected. **Passed**
6. **Ctrl+click** wasn't tried: the control protocol's `ui.click` takes no modifiers. Its handling is unchanged by this work.

To check on your side, in your PhotoCraft fork install, which has this build:
1. Generate, then click a result.
2. Click empty space in the grid beside or after the results. The highlight, Apply and the preview go.

## Follow-ups
- **Generate did nothing in a document that was open before the plug-in started.** In this session, PhotoCraft restored a recovered document at launch, and clicks on Generate there queued nothing and logged nothing. In a new document, Generate worked at once. This looks like the upstream `GenerationWidget.model` setter guard (`ai_diffusion/ui/generation.py:831`) noted in `generate-panel-rows-fit`'s follow-ups: given the model the widget started with, it doesn't connect the widget's signals. It needs its own investigation.
