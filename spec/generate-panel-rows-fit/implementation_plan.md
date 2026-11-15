---
status: approved
---

# Fit the Generate panel's rows to the panel, and show the mode drop-down

In PhotoCraft, the Generate panel's button rows ran past the panel's edge, and the Generation mode drop-down was missing. There were three causes:
- the plug-in lays its panel out for 360 px, with the Generate button as a fixed image, without knowing the panel's real width;
- the strength slider takes its whole row;
- the mode drop-down, whose only content is Qt's down arrow, reaches PhotoCraft as an empty frameless button.

PhotoCraft will tell the plug-in its panel's width, so Qt lays the panel out to fit. A slider in a row will leave room for what follows it. The arrow will be sent as PhotoCraft's chevron icon.

**Related documents**
- [Investigation findings](../../investigations/generate-panel-rows-overflow/findings.md)

## User Review Required

> [!IMPORTANT]
> **A new protocol event, `panel.resized`.**
> - **What it carries:** `{panelId, width, height}`, the panel body's content size in points.
> - **When it's sent:** when PhotoCraft first draws a panel and whenever that size changes.
> - **Delivery:** like `panel.input`, it goes straight to the plug-in that owns the panel, without a subscription. A plug-in that ignores it behaves as today, so the protocol version stays 1.
> - **Where it's documented:** `docs/process-plugins.md` in the fork.

> [!IMPORTANT]
> **This changes the PhotoCraft fork** (`coreyx/photocraft`, `feat/process-plugins`) and the plug-in. The fork's commits stay local until you ask for them to be pushed. The plug-in needs the fork's change to fit its panel: with an older PhotoCraft it keeps today's 360 px layout.

> [!NOTE]
> **Below about 274 px, Qt's own minimum for this panel, the rows still don't fit.** The dock's minimum is 250 px. Below Qt's minimum the plug-in lays out at Qt's minimum, and the row's last few pixels are cut, as a too-narrow Krita docker would cut them. Raising the dock's minimum for one plug-in isn't worth it; the walkthrough notes it.

> [!NOTE]
> **The Generate button is redrawn whenever the panel's width changes.** While you drag the dock's edge, the plug-in waits until the width has been steady for 100 ms, then lays out and redraws once.

## Open Questions

None at this time.

## Proposed Changes

### PhotoCraft fork: protocol and panels

#### [MODIFY] `crates/process-plugin-protocol/src/event.rs`
- [x] **TASK-1:** Add `PANEL_RESIZED = "panel.resized"` to the UI events, listed in `ALL` and in the module comment's list of events that always go to their owner. Add `PanelResized { panel_id: String, width: f32, height: f32 }` with camelCase serde.

#### [MODIFY] `crates/ui-egui/src/process_plugin_panels.rs`
- [x] **TASK-2:** In `body()`, read the content size inside the panel's scroll area (`ui.available_width()`, and the viewport's height) and send `panel.resized` to the panel's plug-in when it differs from the last size sent for that panel by half a point or more. Keep the last size sent per panel in `Panels` (`sizes: HashMap<String, (f32, f32)>`).
  - A plug-in that isn't responding gets nothing, and its last size is left unset, so the size goes out once it responds again.
  - A panel registered again (after a restart) forgets its last size.

#### [MODIFY] `crates/ui-egui/src/process_plugin_panels_tests.rs`
- [x] **TASK-3:** Add `a_panel_tells_its_plugin_its_size`:
  - once drawn, a registered panel has sent one `panel.resized` with its `panelId` and a width within the dock's range;
  - another frame at the same size sends nothing;
  - a narrower window sends the new width.

#### [MODIFY] `docs/process-plugins.md`
- [x] **TASK-4:** Document `panel.resized` in the event table, next to `panel.input`: its payload, when it's sent, that it isn't subscribed to, and that a plug-in laying out with its own toolkit should lay its panel out at that width.

### PhotoCraft fork: rows with a slider

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/render.rs`
- [x] **TASK-5:** In `row()`, when no child grows, treat a visible `slider` or `sliderSpin` child as growing, so the items after it keep their size and the slider takes what's left. Those egui widgets take all the width offered, as the existing comment there says. A row with growing children is unchanged.

#### [MODIFY] `crates/ui-egui/src/process_plugin_ui/tests.rs`
- [x] **TASK-6:** Add `a_slider_leaves_room_for_the_buttons_after_it`: a 300 pt row of `sliderSpin`, `toolButton` and `toolButton`. Both buttons are drawn inside the row's right edge. Before TASK-5 they aren't.

### Plug-in

#### [MODIFY] `photocraft_host/qt_mirror/mirror.py`
- [x] **TASK-7:** A panel's mirror handles `panel.resized` for its own `panelId`. It keeps the latest width and, after 100 ms with no newer one, resizes its root to `max(width, root.minimumSizeHint().width())` wide, keeping its height, then marks itself dirty. Qt reflows, and the self-drawn widgets are redrawn at their new width. Dialogs, which PhotoCraft sizes from the plug-in's own size, are unchanged. A comment says why the root needs the panel's width: widgets drawn as images can't shrink in PhotoCraft.

#### [MODIFY] `photocraft_host/qt_mirror/adapters/buttons.py`
- [ ] **TASK-8:** A `QToolButton` with no icon and an `arrowType` other than `NoArrow` sends `icon: "icon:chevron-down"` (or `-up`, `-left`, `-right`). Upstream's mode drop-down (`generation.py:779-780`) is such a button, and PhotoCraft draws a button with neither icon nor text as nothing.

#### [MODIFY] `tests/photocraft/mock_host.py`, `tests/photocraft/test_qt_mirror.py` and `tests/photocraft/test_qt_mirror_rich.py`
- [ ] **TASK-9:** Tests:
  - **`test_a_panel_lays_out_at_photocraft_s_width`:** a panel with a row of a self-drawing expanding widget and a tool button, mirrored at 360 px. After `panel.resized` with `width: 280`, the root is 280 px wide, and the image's width plus the tool button's fits in 280.
  - **Below the minimum:** a width below the root's minimum lays out at the minimum.
  - **`test_an_arrow_only_tool_button_shows_a_chevron`.**

  The mock host gains `resize_panel(panel_id, width, height)`, which sends the event.

## Verification Plan

### Automated Tests
1. **Fork:**
   - `cargo test -p photocraft-process-plugin-protocol`;
   - `cargo test -p photocraft-ui-egui --lib` with the new tests (TASK-1 to TASK-6), each run once before its fix to confirm it fails;
   - `cargo clippy` and `cargo fmt --check` on both crates.
2. **Plug-in:** the new mirror tests (TASK-7 to TASK-9), and a re-run of the dump script from the investigation with `panel.resized` at 280 px. The Generate row's image plus the queue button fit in 280.
3. **Regression:** the plug-in's CI-equivalent pass, and the fork's `photocraft-ui-egui` tests.

### Manual Verification
In the fork's PhotoCraft with the rebuilt package, at the dock's default width and then dragged to about 280 px:
1. With no selection, the Generate row shows Generate, the region toggle and the queue button, all within the panel.
2. Make a selection. The button reads Fill, the drop-down shows a chevron, and clicking it opens the mode menu: Fill, Expand, Add Content, Remove Content, Replace Background, Custom.
3. The strength row shows Add Control Layer and Add Region within the panel.
