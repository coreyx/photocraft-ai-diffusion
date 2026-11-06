---
status: approved
---

# Lay plug-in dialogs out as Qt does: stretch and size

PhotoCraft draws the plug-in's settings dialog with most of its Connection page out of view, so a server can't be set up there. Two things go wrong:
- a `grow` spacer takes a row's whole width, pushing what follows it past the edge;
- dialogs open at the host's 420×320 default, because `dialog.open` carries no size.

This makes stretch share the leftover space as Qt's does, lets a plug-in give a dialog's size, and has the plug-in send its Qt dialog's size. Most of the work is in the fork (`coreyx/photocraft`, `feat/process-plugins`, mirrored on `feat/process-plugins-upstream`). Only the size reporting is in this repository.

**Related documents**
- [Investigation findings](../../investigations/connection-page-incomplete-in-photocraft/findings.md)
- [Process plug-in host spec](../ai-diffusion-for-photocraft/design.md)

## User Review Required

> [!IMPORTANT]
> The protocol gains four optional `dialog.open` fields: `width`, `height`, `minWidth`, `minHeight`. A plug-in that doesn't send them gets today's behaviour, so nothing breaks either way and the protocol version stays 1. `docs/process-plugins.md` in the fork documents them, and they go in the series prepared for `storytold/photocraft`.

> [!NOTE]
> A row's items after a `grow` spacer are right-aligned, and items between two `grow` spacers are centred, as Qt's stretch places them. Rows without `grow` spacers draw exactly as today, so the echo plug-in and the panels already in use don't change.

## Open Questions

None at this time.

## Proposed Changes

### Fork: protocol and docs

#### [MODIFY] `crates/process-plugin-protocol/src/method.rs`
- [x] **TASK-1:** `OpenDialogParams` gains optional `width`, `height`, `min_width` and `min_height` (`Option<u32>`, camelCase on the wire). They are omitted when absent and ignored when 0. The crate's tests cover a round trip with and without them.

#### [MODIFY] `docs/process-plugins.md`
- [x] **TASK-2:** `dialog.open`'s row lists the four fields: the dialog's initial size and minimum size in points, kept within PhotoCraft's window.

### Fork: drawing dialogs and rows

#### [MODIFY] `crates/ui-egui/src/process_plugin_dialogs.rs`
- [x] **TASK-3:** `Dialog` keeps the size and minimum size from `dialog.open`.
  - A window dialog opens at that size (`default_size`, with `min_size` for the minimum), clamped to the main window's area less a margin. Without a size, it opens at 420×320 as today.
  - A dialog with a size scrolls its content vertically (the window's own scroll area), so it keeps that size. An egui window that sizes itself to its content grows every frame when a layout fills it. In a dialog taller than the window, its last items (Ok, Restore Defaults) scroll with the page rather than staying pinned at the bottom as in Qt.
  - A modal dialog uses the same size for its content.
  - *Revised during implementation: the vertical scroll was added. The first version opened at the size, then grew.*

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/render.rs`
- [x] **TASK-4:** A `row` whose visible children include any `grow` child (a spacer or a widget, such as a line edit) lays out as Qt's stretch and expanding widgets do:
  - the items before the first `grow` child from the left;
  - the items after the last one from the right edge, in their order (egui's right-to-left layout);
  - between them, the growing widgets share the leftover width in equal parts. Each is in a cell as tall as the row's available height, laid out from the top, so a growing column (a dialog's page) isn't limited to one line.
  - with only `grow` spacers between, the items there are centred.

  The `grow` spacers themselves take no fixed space. A row without `grow` children draws as today. *Revised during implementation: the first version handled spacers only, and a growing URL field still pushed Connect past the edge.*
- [x] **TASK-5:** Unbounded heights:
  - **A `grow` spacer in a column** takes the available height only when it's bounded: finite, no taller than the screen, and not during a window's first-frame sizing pass. Otherwise, inside a scroll area for one, it takes none.
  - **A `scroll` node** whose height is unbounded (inside another scroll area, such as a sized dialog's) lays its children out directly. A nested egui scroll area would shrink to egui's minimum scrolled height, a few lines.
  - *Revised during implementation: the nested scroll case was added.*

### Fork: tests

#### [MODIFY] `crates/ui-egui/src/process_plugin_dialogs_tests.rs`
- [x] **TASK-6:** Tests with the fork's kittest harness:
  - **A row** `[button "Left", spacer grow, button "Right"]` in a sized dialog: Right's right edge is at the content's right edge and inside the window.
  - **Two `grow` spacers** centre the item between them.
  - **A growing line edit** followed by a button: the button is inside the window.
  - **A column `grow` spacer** at the end of a scroll area adds no scroll height.
  - **A dialog opened with a size and minimum size** opens at that size, and at the minimum when the size is smaller. It keeps its size over many frames, with content that fills it.
  - **The settings page's shape** (synthetic labels, the same structure as the captured Connection page): a fixed-width list beside a page column with a scroll area holding a section, a stack with a URL row (a growing line edit and Connect), then a bottom row with two `grow` spacers. Opened at 960×480 in a 1440×900 window:
    - the dialog stays 960×480;
    - "Server URL" and "Connect" are inside it horizontally and visible;
    - "Ok" is inside it horizontally.

#### [MODIFY] `crates/ui-egui/src/process_plugin_panels_tests.rs` or the echo plug-in tests
- [x] **TASK-7:** The echo plug-in's gallery, which has rows and spacers, still draws as before: its existing tests and snapshots pass unchanged, and any snapshot that changes is reviewed and explained.

### Fork: gate and series

- [ ] **TASK-8:** Fork gate:
  - `cargo xtask ci`: fmt, clippy, layers and scorecard pass; the tests show only the 4 failures known before this work;
  - the panic-hunt run, `cargo test --doc --workspace`, `cargo xtask wasm` and `cargo xtask i18n-coverage`.

  Commit on `feat/process-plugins`, cherry-pick onto `feat/process-plugins-upstream`, and confirm both branches' trees are identical. The fork commit is named in this repository's commit for this task (`HOST-BASE.md` row).

### Plug-in: dialog size

#### [MODIFY] `photocraft_host/qt_mirror/mirror.py`
- [ ] **TASK-9:** When opening a dialog, `Mirror.start` sends `width` and `height` (the larger of the Qt dialog's size and its size hint) and `minWidth` and `minHeight` (its minimum size, when set).

#### [MODIFY] `tests/photocraft/test_qt_mirror.py` (or `test_qt_mirror_rich.py`, where dialogs are tested)
- [ ] **TASK-10:** A `QDialog` with `setMinimumSize(960, 480)` and `resize(1000, 600)` opens with `width` 1000, `height` 600, `minWidth` 960 and `minHeight` 480. A dialog with no minimum size sends no `minWidth` or `minHeight`.

#### [MODIFY] `photocraft_host/qt_mirror/adapters/lists.py`
- [ ] **TASK-12:** The list adapter no longer sets `grow: 1` on every list. Whether a list grows is left to its layout (`layouts._grow`, from the layout's stretch and the list's size policy), as for other widgets. A test in `tests/photocraft/test_qt_mirror*.py`:
  - in a horizontal layout, a list with `setFixedWidth(120)` has no `grow`;
  - a list with the default policy still grows, in a vertical layout and in a horizontal one.

  *Added during implementation: upstream's settings list is fixed at 120 points, yet arrived as growing and took half the dialog's width.*

### Records

#### [MODIFY] `spec/plugin-dialog-close-exit-fix/walkthrough.md`
- [ ] **TASK-11:** Its Connection-page follow-up points to the findings and this fix.

## Verification Plan

### Automated Tests
- **Fork:** the new kittest tests (TASK-6), the existing dialog and panel tests (TASK-7), and the fork gate (TASK-8).
- **Plug-in:** the mirror test (TASK-10). Regression: the project suite, the stand-in suite, upstream's unit tests, `ruff`, `pyright` and the upstream changes check.
- **The captured tree:** the real Connection page tree captured from the plug-in, rendered with the fixed renderer at the size the plug-in now sends. It's checked by hand, not committed, because it holds local paths: Server URL, Connect and Ok are inside the dialog.

### Manual Verification
In the real PhotoCraft (the fork's release build rebuilt, the package rebuilt, an isolated profile):
1. Open the plug-in's settings. The dialog opens at least 960×480, and the Connection page shows the server-mode buttons, the server panel with Server URL and Connect, and the bottom row with the version, "Open Settings folder" and Ok.
2. Set up a custom server from the page: choose Custom Server, enter `127.0.0.1:8188`, Connect. The status says connected.
3. Open each of the other pages (Styles, Diffusion, Interface, Performance, Plugin). Nothing is cut off at the right, and anything below the fold can be scrolled to.
4. Close the dialog with Ok. The plug-in keeps running, and a generation works.
