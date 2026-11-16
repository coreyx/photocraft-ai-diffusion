# Walkthrough: keep a long drop-down choice from pushing the Upscale workspace past the panel

At the dock's default width, the Upscale workspace now fits in the panel even with the default upscaler, `Default (4x_NMKD-Superscale-SP_178000_G)`, selected ([findings](../../investigations/upscale-panel-rows-overflow/findings.md)). The fork's drop-down now cuts a long choice with "…" instead of growing to fit it. In a panel, the plug-in's mirror now sizes Qt drop-downs for a short contents length instead of their longest item. No upstream file changed.

## What Was Implemented

### 1. PhotoCraft fork (`coreyx/photocraft`, `feat/process-plugins`)
- **`crates/ui-egui/src/process_plugin_ui/render.rs`** (`dcd5a03c6`): `combo()` builds craft-ui's `ComboBox` with `.truncate()`.
  - A choice too wide for the drop-down is cut with an ellipsis rather than widening it.
  - When the plug-in gives the drop-down no `tooltip`, the full choice shows on hover. It shows only when the text was actually cut; a new `combo_text_is_cut` measures that.
  - The open list still shows every choice in full, and the accessible value is still the full name.
  - A comment explains why: craft-ui's `width` is only a minimum, and a drop-down wider than the panel widened egui's layout region. `row()` then put every later row's right-aligned items past the visible edge.
- **`crates/ui-egui/src/process_plugin_ui/tests.rs`** (`a87dd4182`): `a_long_combo_choice_stays_inside_the_panel`, drawn in a 300-point vertical scroll area like a panel's body. It checks four things:
  - the drop-down ends inside the panel;
  - the spin box in the next row ends inside it too;
  - the drop-down's accessible value is the full name;
  - hovering it shows the full name.
  - **Changed from the plan:** the drop-down sits in a row after a button, as upstream's upscaler does, not directly in a column. In a column egui wraps the text, so the drop-down already fit and the test passed without the fix.

### 2. Plug-in
- **`photocraft_host/qt_mirror/mirror.py`** (`7264e4d`): a new `fit_combo_to_panel` and the constant `PANEL_COMBO_CHARS = 8`.
  - For a `QComboBox` with Qt's default `AdjustToContentsOnFirstShow`, it sets `AdjustToMinimumContentsLengthWithIcon` and a minimum contents length of 8 characters. A drop-down whose code chose its own policy keeps it.
  - A panel's mirror calls it on first tracking a drop-down in `Mirror.build`. A dialog's mirror never does.
  - **Added beyond the plan:** `Mirror.start` also calls it for the panel's existing drop-downs before measuring the panel's size hint. Otherwise a long name would still have widened the first layout until PhotoCraft sent its width. A dialog parented to the panel is skipped, since it's a window of its own.
- **`tests/photocraft/test_qt_mirror_rich.py`** (`26a7f32`): `test_a_long_drop_down_choice_doesnt_widen_the_panel`.
  - After PhotoCraft's width of 280 points arrives, the panel lays out at 280, and the self-drawn Upscale button's image leaves room for the queue button.
  - A drop-down set to `AdjustToContents` keeps that policy.
  - A drop-down in a dialog keeps `AdjustToContentsOnFirstShow`.

## Verification & Test Results

### Automated Tests
- **`a_long_combo_choice_stays_inside_the_panel`:** before the fix, the drop-down ended at 381 points of 300. With the tooltip branch disabled, the hover check failed. **Passed** after the fix.
- **`test_a_long_drop_down_choice_doesnt_widen_the_panel`:** before the fix, the panel never came down to 280. **Passed** after it.

### Regression Testing
- **Fork:**
  - `cargo fmt --check` and `cargo clippy -p photocraft-ui-egui --tests`: clean.
  - `cargo test -p photocraft-ui-egui --lib`: 4,883 passed and 24 failed, the 24 known debug-build glyph failures. Five of them are plug-in UI tests, so I ran those on the tree without this change, and the same five fail there.
- **Plug-in:** the CI-equivalent pass.

  | Check | Result |
  |---|---|
  | Format, lint, `upstream_changes.py` | Clean |
  | `pyright` | 0 errors |
  | Plug-in tests | 355 passed |
  | Upstream unit tests | 268 passed, 27 skipped |
  | Stand-in tests | 246 passed, 19 skipped |
  | Coverage gate | 93.3% of lines and 78.6% of branches overall; the stand-in at 96.8% of lines |

  The workspace snapshots (`tests/photocraft/fixtures/mirror/*.json`) didn't change.

## Manual Verification
I ran these in the fork's release build, with the rebuilt package in an isolated profile, your local ComfyUI, and the dock at its default width.
1. **The upscaler drop-down:** in Upscale with the default upscaler, it ends inside the panel, its name cut as `Default (4x_NMKD-Superscale-SP_1…`. Hovering shows the full name. **Passed**
2. **The other rows:** the Scale field, the Tile Overlap field, the Use Prompt switch and the queue button are all inside the panel. **Passed**
3. **The list:** opening the upscaler drop-down shows all four names in full. **Passed**
4. **Generate:** its rows look as before, and the style drop-down opens with every style. **Passed**
5. **Settings:** the dialog opens at its usual size. Its style preset drop-down shows its full name and opens with every preset. **Passed**

To check on your side, in your PhotoCraft fork install, which now has this build and plug-in code:
1. Open the AI Image Generation panel and switch to Upscale.
2. Everything ends inside the panel, and hovering the upscaler shows its full name.

## Follow-ups
- **Upscale's "Target size: 2048 x 2048" line always shows** in PhotoCraft. Upstream shows it only while the scale slider is held or the pointer is over the factor widget (`ai_diffusion/ui/upscale.py:94-100`).
