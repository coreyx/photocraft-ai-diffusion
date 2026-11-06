# Walkthrough: Plug-in dialog layout fix

PhotoCraft now draws the plug-in's settings dialog the way Qt lays it out. The dialog opens at the size the plug-in gives it, and rows share their width as Qt's stretch and expanding widgets do. The Connection page shows the server-mode buttons, Server URL with Connect, and the bottom row with Ok, so a server can be set up there. The cause is in the [findings](../../investigations/connection-page-incomplete-in-photocraft/findings.md).

## What Was Implemented

### 1. Fork: protocol and docs (`coreyx/photocraft`, `feat/process-plugins`)
- **`crates/process-plugin-protocol/src/method.rs`**: `dialog.open` takes optional `width`, `height`, `minWidth` and `minHeight`. They are left out when absent and ignored when 0, and the protocol version stays 1 (`3687b6d54`).
- **`docs/process-plugins.md`**: documents the four fields (`2432ca348`).

### 2. Fork: drawing dialogs and rows
- **`crates/ui-egui/src/process_plugin_dialogs.rs`**: a dialog opens at its size, within the main window less a margin, with its minimum. A sized dialog scrolls its content, so it keeps that size (`0b2c4ad8e`, `410035c54`).
- **`crates/ui-egui/src/process_plugin_ui/render.rs`** (`0e2cb9255`, `feb367760`):
  - Rows with `grow` children lay out as Qt does. Items after the last growing child go to the right edge, and items between two `grow` spacers are centred. Growing widgets share the leftover width, and the growing child's cell is as tall as the row's space.
  - A column's `grow` spacer takes no height where the height is unbounded.
  - A `scroll` node inside another scroll area lays its children out directly.
- **Found during the manual check, fixed within TASK-4 and TASK-5's intent**:
  - *The bottom row was one pixel below the dialog's edge* (`8b5dbd56c`). Inside a sized dialog's scroll area, egui reports the visible height as available, so the page's trailing stretch filled it. egui also hides scrollbars until hovered, so nothing showed that the row was there. The renderer is now told when the caller scrolls the whole tree, and there the height counts as unbounded. Panels draw as before.
  - *Slider settings squeezed their descriptions to 40 points* (`496f5961e`). This was on the Diffusion and Performance pages: egui's slider takes all the width it's offered. In a row with growing widgets, a fixed item now gets at most an equal share of the row's width.

### 3. Fork: tests
- **`crates/ui-egui/src/process_plugin_dialogs_tests.rs`** (`88e9321e5`, extended in `8b5dbd56c` and `496f5961e`):
  - stretch to the right edge, centring between two spacers, and a growing line edit before a button;
  - a stretch in a scroll area adding no height;
  - dialog sizes and minimums;
  - a settings page's shape at 960×480, with its server panel's trailing stretch, that keeps its size with Server URL, Connect, Ok and Restore Defaults inside the window;
  - a slider after a stretch leaving the growing description over 250 points.

### 4. Fork: upstream series
- `feat/process-plugins-upstream` holds all of this as one topic commit, `ab226346c`. It replaces `b523d12ab`, which TASK-8's commit names, because the two fixes above were folded in. Both branches' trees are identical.
- [HOST-BASE.md](../ai-diffusion-for-photocraft/HOST-BASE.md) lists it as topic 15.

### 5. Plug-in
- **`photocraft_host/qt_mirror/mirror.py`**: `dialog_size()` sends a dialog's `width` and `height`, the larger of its Qt size and size hint. It sends `minWidth` and `minHeight` only for a minimum the dialog's code set; a shown dialog always has one from its layout, measured with Qt's fonts.
- **`photocraft_host/qt_mirror/adapters/lists.py`**: a list no longer always grows; its layout decides. Inside the column that carries its overlay buttons, it still fills that column.
- **`photocraft_host/qt_mirror/layouts.py`**: an item whose maximum equals its minimum in the layout's direction doesn't grow. `setFixedWidth` keeps an Expanding policy, and upstream's page list uses it.
- **Records**: the dialog-close walkthrough's Connection-page follow-up points to the findings and this fix.

## Verification & Test Results

### Automated Tests
- **The fork's new layout tests**: **Passed**, 48 plug-in UI tests in all. Against the code before each change, the size, settings-page and slider tests fail.
- **The mirror's dialog size test** (`tests/photocraft/test_qt_mirror_rich.py`): **Passed**. It fails against the code before TASK-9. It also showed that every shown dialog has a layout minimum, so only one set by code is now sent.
- **The list grow test** (`tests/photocraft/test_qt_mirror.py`): **Passed**. Before the fix it failed, with the fixed-width list growing.
- **The captured tree**: the real settings dialog tree, captured from the plug-in, was rendered in the fork's harness at 960×640. Ok and Restore Defaults are at y 583–611 in a window ending at 656. The check was by hand and isn't committed, because the tree holds local paths.

### Regression Testing
- **Fork gate** (`cargo xtask ci`, with craft-fonts):
  - fmt, clippy, layers and scorecard: ok;
  - panic hunt, doctests, wasm (25 crates) and i18n: ok;
  - tests: 14,604 passed and 5 failed. Four are the known machine-dependent failures. The fifth is new: `photocraft-compose cmyk::tests::the_split_route_agrees_with_the_exact_path`. A property test found a CMYK case where one ink is 0.952 instead of 1.0. The fork doesn't change `photocraft-compose`, but I didn't confirm the case on the base commit, since that needs a rebuild there. It's now listed with the base failures in HOST-BASE.md.
- **After the two follow-up fixes**:
  - `photocraft-ui-egui`'s whole suite: 5,089 passed;
  - workspace clippy and fmt: clean.
- **The echo plug-in's gallery and dialog tests**: unchanged and passing. Its rows have no `grow` children.
- **Plug-in**:
  - `tests/photocraft`: 337 passed;
  - upstream's unit tests: 268 passed, 27 skipped;
  - upstream code on the stand-in: 246 passed, 19 skipped;
  - `ruff format` and `ruff check` clean, pyright 0 errors, upstream changes check ok.
- **Without craft-fonts**, five plug-in UI tests panic on a missing `▾` glyph. That's expected: HOST-BASE.md says to set `CRAFT_FONTS_DIR` for every gate run.

## Manual Verification

Done in the real PhotoCraft: the fork's release build, the rebuilt package, and an isolated profile with no saved window state.
1. **Open the plug-in's settings.** It opens at 960×640, the plug-in's size. The Connection page shows:
   - the server-mode buttons;
   - Server URL, with Connect inside the window;
   - the Connected status;
   - the bottom row: Restore Defaults, the version, Open Settings folder and Ok.

   **Passed.**
2. **Choose Custom Server, enter `127.0.0.1:8188` and click Connect.** The plug-in reconnected (logged) and shows Connected. **Passed.**
3. **Open Styles, Diffusion, Interface, Performance and Plugin.** Nothing is cut off at the right, and longer pages scroll inside the dialog. **Passed** after the slider fix; before it, the Diffusion and Performance descriptions were squeezed.
4. **Close with Ok, then generate.** The plug-in kept running, and a generation finished with six results. **Passed.**

To check it yourself, use the portable PhotoCraft in `%LOCALAPPDATA%\Programs\PhotoCraft-fork` once its exe is the current build. Then repeat steps 1, 3 and 4.

## Follow-ups
- **A dialog's window size is remembered by its id.** egui saves window sizes in `ui.ron`, keyed by the plug-in and dialog id. The plug-in numbers dialogs `dialog-1`, `dialog-2`… per session, so a later dialog with the same number opens at the size the earlier one was left at. In a profile used with the old build, the settings dialog came back at the size it had spread to. A fresh profile isn't affected.
- **Rich-text lists run together.** On the Connection page, the detected-workloads list (`<ul><li>`) shows as one line ("SD 1.5: supportedSD XL: …"). The renderer's rich-text label doesn't break list items.
- **The CMYK property-test case** above, worth reporting upstream with its saved input if it reproduces on the base.
- **PhotoCraft's update prompt** offers the official 0.20.2. Choosing Update would replace the fork, so the README now says to choose Later.
