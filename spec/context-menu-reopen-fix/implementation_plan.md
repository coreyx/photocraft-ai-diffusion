---
status: approved
---

# Reopen a plug-in's context menu after one was dismissed

Once a plug-in's menu was dismissed by clicking elsewhere, its next one never showed. PhotoCraft kept the dismissed popup's local `open: false` after the popup was removed, and the plug-in reopened the next menu under the same id. The fork will drop a removed node's local values, and the mirror will give each menu it opens a new id. Either change alone fixes it; both together keep a fixed plug-in working with an older PhotoCraft and the reverse.

**Related documents**
- [Investigation findings](../../investigations/context-menu-stops-opening/findings.md)

## User Review Required

> [!IMPORTANT]
> **This changes the PhotoCraft fork** (`coreyx/photocraft`, branch `feat/process-plugins`) as well as the plug-in: `Tree::apply` in `crates/ui-egui/src/process_plugin_ui/mod.rs`. The fork's commits stay local until you ask for them to be pushed, as before.

> [!NOTE]
> **Menu entry ids change.** An `exec()` menu's popup id goes from `<anchor>.menu` to `<anchor>.menu.<n>`, and its entries' ids follow. Ids aren't part of any saved state; only `test_qt_mirror_rich.py` refers to the old form.

## Open Questions

None at this time.

## Proposed Changes

### PhotoCraft fork

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/mod.rs`
- [x] **TASK-1:** In `Tree::apply`, `Patch::Remove`: collect the ids of the removed node and every node under it, and drop their entries from `self.local`. A comment says why: a node the plug-in inserts again under the same id (a menu reopened after being dismissed) must show as the plug-in sends it, not as the user last left the removed one. `Patch::Move` keeps local values, since the node lives on.

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/tests.rs`
- [x] **TASK-2:** Add `a_removed_popup_leaves_no_local_state`:
  1. Build a tree with a popup anchored to a button, `open: true`, with one entry.
  2. Set `local[(popup, "open")] = false`, as a click elsewhere does.
  3. `Remove` the popup, then `Insert` it again with `open: true`.
  4. Check the local entry is gone, and in the harness check the entry's label is drawn.

  Before TASK-1, step 4 fails.

### Plug-in

#### [MODIFY] `photocraft_host/qt_mirror/menus.py`
- [ ] **TASK-3:** `popup_node` gives each menu it opens a fresh popup id, `f"{anchor}.menu.{next(_popup_ids)}"` with a module-level `itertools.count(1)`. A comment says why: a new menu must not inherit what PhotoCraft remembers about an earlier one under the same id. The id is chosen once per opened menu, not per rebuild of the tree. So `Mirror.open_menu` stores it alongside the menu, `mirror.py`'s `_menus` becomes `dict[str, tuple[QMenu, str]]`, and `popup_node` takes the id instead of deriving it. The close handler and the entries' ids use it.

#### [MODIFY] `tests/photocraft/test_qt_mirror_rich.py`
- [ ] **TASK-4:** The history context-menu test (`:370-392`) finds the popup by `kind == "popup"` and `anchor == grid_id` instead of its old id. Add `test_a_context_menu_opens_again_after_being_dismissed`:
  1. Right-click a result.
  2. Send `change: false` on the popup, as a click elsewhere does, and check it's gone.
  3. Right-click again.
  4. Check a popup is open again, under an id different from the first.

## Verification Plan

### Automated Tests
1. **Fork:** `cargo test -p photocraft-ui-egui --lib process_plugin_ui`, including the new test (TASK-1, TASK-2). The new test is run once before TASK-1 to confirm it fails.
2. **Plug-in:** `pytest tests/photocraft/test_qt_mirror_rich.py`, with the reopen test (TASK-3, TASK-4).
3. **Regression:**
   - Fork: `cargo test -p photocraft-ui-egui --lib`, `cargo clippy -p photocraft-ui-egui`, and `cargo fmt --check`.
   - Plug-in: the CI-equivalent pass, meaning format, lint, `pyright`, the three suites under coverage and the coverage gate.

### Manual Verification
In the fork's PhotoCraft with the rebuilt package:
1. Right-click a result in the history, then click elsewhere. Right-click again: the menu opens.
2. Choose Copy Prompt from it: the prompt is copied.
3. With a selection, open the Generate mode drop-down and click elsewhere, then open it again: it opens. This also depends on the arrow fix in `generate-panel-rows-fit`.
