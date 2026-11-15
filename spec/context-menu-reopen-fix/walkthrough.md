# Walkthrough: reopen a plug-in's context menu after one was dismissed

A plug-in's context menu now opens again after the user dismissed one by clicking elsewhere ([findings](../../investigations/context-menu-stops-opening/findings.md)). Two changes:
- the PhotoCraft fork drops a removed widget's local values;
- the mirror opens each menu under a new id.

Either change alone fixes it.

## What Was Implemented

### 1. PhotoCraft fork (`coreyx/photocraft`, `feat/process-plugins`, local commits)
- **`crates/ui-egui/src/process_plugin_ui/mod.rs`** (`cf7d0bf06`): `Tree::apply` collects the ids of a removed node and everything under it, and drops their local values once the patch has applied. A failed patch still changes nothing. A popup the plug-in inserts again under the same id then shows as the plug-in sends it.
- **`crates/ui-egui/src/process_plugin_ui/tests.rs`** (`191afd4e2`): `a_removed_popup_leaves_no_local_state`. It stores a local `open: false` on a popup, as a click elsewhere does, removes the popup, and inserts it again open. The menu's entry is drawn.

### 2. Plug-in
- **`photocraft_host/qt_mirror/menus.py`**: `popup_id(anchor)` gives each menu opened with `exec()` its own id, `<anchor>.menu.<n>`. `popup_node` takes that id, and the menu's entries' ids follow it.
- **`photocraft_host/qt_mirror/mirror.py`**: `_menus` keeps each open menu with its id, chosen once when it opens.
- **`tests/photocraft/test_qt_mirror_rich.py`**:
  - the history context-menu test finds its popup by kind and anchor;
  - `test_a_context_menu_opens_again_after_being_dismissed` right-clicks, sends `change: false`, right-clicks again, and checks a popup is open under a new id.

## Verification & Test Results

### Automated Tests
- **`a_removed_popup_leaves_no_local_state`:** passes; without the fix it fails, because the local `open` survives the removal. **Passed**
- **`test_a_context_menu_opens_again_after_being_dismissed`:** passes; without the plug-in change it fails, because the second menu reuses `w8.items.menu`. **Passed**

### Regression Testing
- **Plug-in**, the CI-equivalent pass (format, lint, `pyright`, `upstream_changes.py`, the three suites under coverage, and the coverage gate). The last run covers this spec and `generate-panel-rows-fit` together: 352 plug-in tests, and coverage 93.3% of lines and 78.4% of branches. The full table is in that spec's walkthrough.
- **Fork:** `cargo fmt --check` and `cargo clippy -p photocraft-ui-egui --tests` are clean.
  - `cargo test -p photocraft-ui-egui --lib`: 4879 passed, 24 failed.
  - All 24 fail the same way with this spec's two files put back to `ed671fa68`, the commit before. They're font and glyph assertions in the fork's debug test build, for example `No glyph for "▾" (U+25BE) in Name("medium")`, in the i18n, type-tool, layer-row and plug-in UI tests. See Follow-ups.

## Manual Verification
Done in the fork's release build, with the rebuilt package in an isolated profile and your local ComfyUI, after 12 generations:
1. **Reopening after a dismissal:** right-click a result in the history, and the menu opens. Click elsewhere, and it closes. Right-click again, and it opens. **Passed**
2. **The mode drop-down:** with a selection, open it, click elsewhere, and open it again. **Passed**, checked in the session for `generate-panel-rows-fit`.

## Follow-ups
- **The fork's debug test build has 24 tests failing on missing glyphs.** That predates this work. One example: the "▾" its split buttons draw isn't in the `medium` font, and this egui version panics on a missing glyph in debug builds. Either the font needs the glyph, or the tests need `MissingGlyphPolicy::Tofu`.
- **The fork's commits are local.** Push `feat/process-plugins` to `coreyx/photocraft` when you want them published.
