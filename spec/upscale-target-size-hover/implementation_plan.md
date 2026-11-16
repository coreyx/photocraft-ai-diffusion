---
status: approved
---

# Show Upscale's target size only while the pointer is over the scale row

In PhotoCraft, Upscale's "Target size" line shows all the time. Upstream shows it only while the pointer is over the scale row or the slider is held. PhotoCraft never tells the plug-in where the pointer is, and Qt's offscreen cursor sits over the Upscale page before it is laid out. This adds a `hover` input to PhotoCraft's plug-in protocol. PhotoCraft sends it for widgets the plug-in marks as hover-aware, and the mirror turns it into Qt's `Enter`/`Leave` events with Qt's cursor moved to match. Until the first hover, the cursor is parked outside every window.

**Related documents**
- [Investigation findings](../../investigations/upscale-target-size-always-shown/findings.md)

## User Review Required

> [!IMPORTANT]
> This adds to PhotoCraft's plug-in protocol: a common prop `hover` and an input kind `hover`, in the fork (`coreyx/photocraft`, `feat/process-plugins`). The change is additive. Plug-ins that don't set `hover` get no new events, and the protocol number stays 1. The plug-in's behavior needs the fork's PhotoCraft from this release on. With an older PhotoCraft, the line never shows instead of always showing.

> [!NOTE]
> The mirror marks a widget as hover-aware when its Python class overrides `enterEvent` or `leaveEvent`. In upstream's code, that's `FactorWidget` and `GenerateButton`.
>
> `GenerateButton` sets `WA_Hover`, so while the pointer is over it, Qt may draw its image with its hover look, as Krita does. Its cost estimate on hover applies only to the online service, which this project doesn't ship.

> [!NOTE]
> **One small difference from Krita.** If the pointer leaves the scale row during a slider drag, the line clears at once. Krita keeps it until the slider is released. PhotoCraft sends no press/release state for sliders, and the mirror replays each step as press, move and release.

## Open Questions

None at this time.

## Proposed Changes

### PhotoCraft fork: protocol (`../photocraft`)

#### [MODIFY] `crates/process-plugin-protocol/src/event.rs`
- [x] **TASK-1:** Add `InputKind::Hover` (wire name `"hover"`), documented as: the pointer moved onto (`value` true) or off (`value` false) a widget whose `hover` prop is true.
  - In `crates/process-plugin-protocol/src/tests.rs`, add `hover_input_has_the_documented_wire_shape`. It decodes `{"owner":"main","nodeId":"row","kind":"hover","value":true}` to `InputKind::Hover`, and encodes `InputKind::Hover` back to `"hover"`.

#### [MODIFY] `crates/process-plugin-protocol/src/widget.rs`, `docs/process-plugins.md`
- [x] **TASK-2:** Document the common prop `hover` (default false) in the module docs and in the docs' list of common props. Add a paragraph under the input events saying when `hover` is sent:
  - when the pointer moves onto or off the widget's drawn area;
  - with `false` when a hovered widget is hidden or removed.

### PhotoCraft fork: drawing (`../photocraft`)

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/render.rs`
- [x] **TASK-3:** In `node()`, for a node with `hover: true`, test after drawing whether its rect contains the pointer, with `ui.rect_contains_pointer(response.rect)`.
  - Keep the last state in the tree's local values under `(id, "hovered")`, a key the plug-in never sets, and emit `InputKind::Hover` only when the state changes.
  - When such a node is skipped because it is hidden, and its local state says hovered, emit `false` and drop the state.
  - A removed node's local values are already dropped by `Tree::apply`, so a node inserted again starts unhovered.
  - Add a doc comment on the new helper (`report_hover`) saying why: a plug-in drawing with its own toolkit can only show hover-dependent UI if it hears about the pointer.

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/tests.rs`
- [x] **TASK-4:** Add `a_hover_node_reports_the_pointer_entering_and_leaving`. The harness holds a column with `hover: true` and a label inside, and a second column without `hover`. It checks:
  - moving the pointer onto the first column sends one `hover` `true`, and further frames over it send nothing;
  - moving off sends one `false`;
  - hovering the second column sends nothing;
  - setting `visible: false` on the first column while it's hovered sends `false`.

### Plug-in: mirror (`photocraft_host/qt_mirror`)

#### [MODIFY] `photocraft_host/qt_mirror/mirror.py`
- [x] **TASK-5:** Add the module function `wants_hover(widget)`. It is true when a class in `type(widget).__mro__`, other than PyQt6's own classes, defines `enterEvent` or `leaveEvent`. In `Mirror.build`, set `props["hover"] = True` for such widgets, and `None` otherwise, so the prop is left out.
- [ ] **TASK-6:** In `Mirror._on_input`, handle `kind == "hover"` before looking up an adapter, for any tracked widget, enabled or not, as Qt delivers hover. The new `Mirror._hover(widget, inside)` works as follows:
  - **On `true`:** move Qt's cursor to the widget's centre with `QCursor.setPos`, then send it a `QEnterEvent`.
  - **On `false`:** park the cursor at `PARKED_CURSOR`, then send it `QEvent.Type.Leave`.
  - The doc comment says why: upstream's widgets decide from `QCursor.pos()` and their enter/leave handlers, and on the offscreen platform the cursor never moves by itself.

#### [MODIFY] `photocraft_host/qt_mirror/__init__.py`
- [ ] **TASK-7:** Add the constant `PARKED_CURSOR = QPoint(-100000, -100000)`, used by `mirror.py`. In `install()`, park Qt's cursor there once a `QGuiApplication` exists.
  - Comment why: the offscreen platform starts the cursor at (10, 10), inside any widget at the top left of a window that isn't laid out yet. Upstream's `FactorWidget` reads that as the pointer being over it ([findings](../../investigations/upscale-target-size-always-shown/findings.md), cause 1).

### Plug-in: tests (`tests/photocraft`)

#### [MODIFY] `tests/photocraft/test_qt_mirror_rich.py`
- [ ] **TASK-8:** Add `test_hover_reaches_widgets_that_handle_it`. A panel holds a widget class overriding `enterEvent`/`leaveEvent` that records `rect().contains(mapFromGlobal(QCursor.pos()))`, and a plain `QLabel`. It checks:
  - the first node has `hover: true` and the label's has no `hover`;
  - a `hover` `true` input runs `enterEvent` with the cursor inside;
  - `false` runs `leaveEvent` with the cursor outside;
  - `hover` on the label changes nothing.

#### [MODIFY] `tests/photocraft/upstream_docker.py`, `tests/photocraft/test_upstream_docker.py`
- [ ] **TASK-9:** Extend the docker run with a 1024×1024 document and a new result, `target_size`, recording the label after each step. The test asserts:
  - after switching to Upscale, the line is empty (it was `Target size: 2048 x 2048`);
  - after `hover` `true` on `FactorWidget`, then a slider `change` to 250, it reads `Target size: 2560 x 2560`;
  - after `hover` `false`, it is empty.

## Verification Plan

### Automated Tests
This project's tests replace the generic `scratch/` script:
1. Fork: the new protocol and drawing tests (TASK-1, TASK-4) pass. `cargo fmt --check` and `cargo clippy -p photocraft-ui-egui -p photocraft-process-plugin-protocol --tests` are clean. `cargo test -p photocraft-process-plugin-protocol` passes. `cargo test -p photocraft-ui-egui --lib` has no failures beyond the 24 known debug-build glyph failures.
2. Plug-in: TASK-8 and TASK-9 pass, and fail without TASK-5 to TASK-7. TASK-9's first check reproduces the 2048 × 2048 line.
3. Plug-in: the CI-equivalent pass (format, lint, `upstream_changes.py`, `pyright`, the plug-in, upstream and stand-in tests, and the coverage gate) passes, with the workspace snapshots unchanged.

### Manual Verification
In the fork's release build, with the rebuilt package in an isolated profile and your local ComfyUI:
1. Open a 1024×1024 document and switch the panel to Upscale. No "Target size" line shows.
2. Move the pointer over the scale row. "Target size: 2048 x 2048" shows. Move it away, and the line goes.
3. Drag the slider to 3x. The line follows, reading 3072 x 3072, and goes once the pointer leaves the row.
4. Change the Scale field with the keyboard while the pointer is elsewhere. No line shows.
5. Hover the Generate button in Generate. It still works, and nothing else changes besides any hover look.
