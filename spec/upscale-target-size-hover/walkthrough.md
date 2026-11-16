# Walkthrough: show Upscale's target size only while the pointer is over the scale row

In PhotoCraft, Upscale's "Target size" line used to show all the time ([findings](../../investigations/upscale-target-size-always-shown/findings.md)). Now it shows only while the pointer is over the scale row, as in Krita. PhotoCraft's plug-in protocol has a new `hover` input, which PhotoCraft sends for widgets the plug-in marks as hover-aware. The mirror plays it back to Qt as `Enter`/`Leave`, moving Qt's offscreen cursor to match. Until then, the cursor is parked outside every window. No upstream file changed.

## What Was Implemented

### 1. PhotoCraft fork (`coreyx/photocraft`, `feat/process-plugins`)
- **`crates/process-plugin-protocol/src/event.rs`** (`d5a1ad787`): `InputKind::Hover` (`"hover"`), with a wire-shape test in `tests.rs`.
- **`crates/process-plugin-protocol/src/widget.rs`, `docs/process-plugins.md`** (`6aa011ae2`): the common prop `hover` (default false), and when the `hover` input is sent.
- **`crates/ui-egui/src/process_plugin_ui/render.rs`** (`90fdf71f2`): new `report_hover` and `unhover` helpers.
  - For a node with `hover: true`, `node()` tests whether its drawn rect contains the pointer, and sends `hover` only when that changes. The state is kept in the tree's local values under `hovered`, a key the plug-in never sets.
  - When a hidden subtree holds a hovered node, PhotoCraft sends `false` for it. That search runs only while some node is hovered.
  - A full tree replacement clears local values, so a node still under the pointer is reported as entered again. That's harmless: upstream's handler just runs its check again.
- **`crates/ui-egui/src/process_plugin_ui/tests.rs`** (`470958e1a`): `a_hover_node_reports_the_pointer_entering_and_leaving`.

### 2. Plug-in
- **`photocraft_host/qt_mirror/mirror.py`** (`e611eb8`, `65f2076`, `74b0b09`):
  - `wants_hover(widget)` marks a widget as hover-aware when its Python class overrides `enterEvent` or `leaveEvent`. The answer is cached per class. In upstream's code, that's `FactorWidget` and `GenerateButton`. `Mirror.build` sends such a widget with `hover: true`.
  - `Mirror._on_input` handles `hover` before looking up an adapter, and only for widgets it marked. `Mirror._hover` then plays it back:
    - **`true`:** moves Qt's cursor to the widget's centre and sends a `QEnterEvent`.
    - **`false`:** parks the cursor at `PARKED_CURSOR`, if it's still in that widget, and sends `Leave`.
  - **Added during implementation:** the mirror ignores `hover` on a widget it didn't mark, since the protocol sends it only for those.
- **`photocraft_host/qt_mirror/__init__.py`** (`3a5b112`): `install()` calls the new `park_cursor()`.
  - **Changed from the plan:** `PARKED_CURSOR` is defined in `mirror.py`, not `__init__.py`. `__init__.py` imports `mirror.py`, so defining it there avoids a circular import.
- **`tests/photocraft/test_qt_mirror_rich.py`** (`74b0b09`): `test_hover_reaches_widgets_that_handle_it`.
  - The test window is shown, so Qt may send an extra `Enter` or `Leave` of its own when the cursor moves. Each sees the same cursor, so the test checks every one rather than counting them.
- **`tests/photocraft/upstream_docker.py`, `test_upstream_docker.py`** (`500695f`): the docker run uses a 1024×1024 document and records `target_size`.
  - **Changed from the plan:** the docker shows its workspaces only once a server is connected. Faking that broke other upstream widgets, which need a real client. So the run mirrors an Upscale page of its own as a second panel.
  - It gives that page the document's model before the page is laid out. It clears `_model` first, because upstream's setter binds nothing for the model a widget started with.

## Verification & Test Results

### Automated Tests
- **`a_hover_node_reports_the_pointer_entering_and_leaving`:** **Passed.** It checks:
  - one `true` on entering, and none while the pointer stays;
  - one `false` on leaving;
  - nothing for a node without the prop;
  - `false` when the node is hidden under the pointer.

  With the `hover` emit removed, it fails on the first check.
- **`hover_input_has_the_documented_wire_shape`:** **Passed.**
- **`test_hover_reaches_widgets_that_handle_it`:** **Passed.** Without the hover playback, it times out waiting for `Enter`.
- **`test_the_target_size_shows_only_while_the_pointer_is_over_the_scale_row`:** **Passed.** It sees an empty line at first, 2560 x 2560 while hovered at 2.5x, and an empty line after leaving. It catches each cause:
  - **Without the parked cursor:** the line shows `Target size: 2048 x 2048` at first, the reported symptom.
  - **Without the hover playback:** the line stays after the pointer leaves.

### Regression Testing
- **Fork:**
  - `cargo fmt --check` and `cargo clippy -p photocraft-ui-egui -p photocraft-process-plugin-protocol --tests` are clean.
  - `cargo test -p photocraft-process-plugin-protocol` passed.
  - `cargo test -p photocraft-ui-egui --lib`: 4,884 passed and 24 failed, the same 24 known debug-build glyph failures as before. That includes the same five plug-in UI tests that also fail without this work.
- **Plug-in:** the CI-equivalent pass.

  | Check | Result |
  |---|---|
  | Format, lint, `upstream_changes.py` | Clean |
  | `pyright` | 0 errors |
  | Plug-in tests | 357 passed |
  | Upstream unit tests | 268 passed, 27 skipped |
  | Stand-in tests | 246 passed, 19 skipped |
  | Coverage gate | 93.3% of lines and 78.7% of branches overall; the stand-in at 96.8% of lines |

  The workspace snapshots didn't change.
- **Exit code 127:** a single pytest file run with `-k` sometimes exited with code 127 after printing its results. The same happens on the tree without this work, so it comes from interpreter teardown. Runs of whole files, and the CI-equivalent pass, exited 0.

## Manual Verification
I ran these in the fork's release build, with the rebuilt package in an isolated profile, your local ComfyUI, and a new 1024×1024 document:
1. **Opening Upscale:** no "Target size" line shows. **Passed**
2. **Hovering the scale row:** `Target size: 2048 x 2048` shows. **Passed**
3. **The slider:** clicking it at 3x with the pointer over the row shows `Target size: 3072 x 3072`. Moving the pointer to the canvas removes it. **Passed**
4. **The keyboard:** clicking the Scale field, moving the pointer away and pressing Down sets 2.5 with no line. **Passed**
5. **Generate:** hovering the Generate button leaves it looking as before, and clicking it produced an image. **Passed**

The plug-in's log showed no errors. Your PhotoCraft fork install now has this build and plug-in code. The previous ones are in its `backup-2026-11-16-hover` folder. To check on your side:
1. Open a document and switch the AI Image Generation panel to Upscale.
2. Move the pointer over the scale row, and then away from it. The target size shows, and then goes.

## Follow-ups
- **The line is left-aligned in PhotoCraft.** Upstream adds it with `AlignRight`, but the mirror doesn't send a layout item's alignment.
- **Keyboard on the slider.** A value set on the slider itself with the keyboard while the pointer is elsewhere would show the line until the next hover. The mirror replays slider changes with the slider held down. Pointer drags always come with a hover, and the Scale field isn't affected.
- **A document PhotoCraft restored at launch** kept the panel on "Create a new document" in this session until a new document was opened. It may be the case the earlier fix for documents open before the plug-in started doesn't cover. It needs its own investigation.
