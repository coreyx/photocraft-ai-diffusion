# Findings: the Generate panel's button rows run past the panel's edge, and the mode drop-down is missing

## Problem

Two reports about the same part of the Generate panel in PhotoCraft:
1. The drop-downs next to the main (Generate) button, and those next to the strength input, are pushed off the edge of the screen.
2. The Generation mode drop-down on the main button doesn't appear. Upstream documents it ([Selections](https://docs.interstice.cloud/selections/)): with a selection, the button shows the operation (Fill or Expand by default), and a drop-down beside it picks a more specific mode (Fill, Expand, Add Content, Remove Content, Replace Background, Custom).

## Investigation

- **The two rows in upstream** (`ai_diffusion/ui/generation.py`):
  - **Strength row** (`:760-772`): the strength slider and spin box (`StrengthWidget`), the layer count, Add Control Layer and Add Region.
  - **Generate row** (`:799-810`): `GenerateButton`, the mode drop-down (`inpaint_mode_button`, a `QToolButton` whose only content is `setArrowType(DownArrow)`), the region mask toggle, then `QueueButton`.
  - The mode drop-down shows only with a selection, a region-only generation or a model that can toggle edit (`:1012-1025`).
- **How the plug-in lays them out.** A script built upstream's `GenerationWidget` on the mock host and printed Qt's geometry and the tree the mirror sends.
  - **The panel width.** The plug-in lays its panel out off screen at `max(360, sizeHint)` px (`photocraft_host/qt_mirror/mirror.py:40`, `:173`); here, 360. PhotoCraft never tells it the panel's real width.
  - **`GenerateButton` and `QueueButton` paint themselves** (`widget.py:982`, `:326`), so the mirror sends them as fixed-size images (`photocraft_host/qt_mirror/raster.py:42-53`). Without a selection, the Generate image is 267 × 27 px and the queue button 85 px. With a selection, the mode drop-down appears and the Generate image narrows to 243 px.
  - **The strength slider is sent as a native `sliderSpin`**, with no `grow`. After it come two 28 px tool buttons.
  - **The mode drop-down arrives as `toolButton {"text": ""}`**, with no icon: the mirror's button adapter doesn't carry Qt's `arrowType` (`photocraft_host/qt_mirror/adapters/buttons.py`). With the waits fixed, the tree does follow its `setVisible(True)`.
- **How the fork draws them** (`crates/ui-egui/src/process_plugin_ui/render.rs`):
  - **`image()`** (`:576-581`) sizes an image at `min(width, available width)`: it takes everything left in the row, up to its own width.
  - **`slider()`** with a spin box sets its width to the available width minus 64 px.
  - **`row()`** shares the width only among children marked `grow`. A row without any is laid out left to right, so whatever comes after a wide child goes past the edge.
  - **`tool_button()`** with no icon and empty text draws `egui::Button::new("").frame(false)`: a frameless button with nothing in it.
  - **The dock** (`crates/ui-egui/src/panels/dock.rs:73`) is 250 px at least and resizable. A panel's body sits in a vertical scroll area, with margins and a scroll bar taking part of that.

## Root Cause(s)

1. **The Generate row is laid out for a 360 px panel, and its widest part is a fixed image** (bug 1, the Generate row; bug 2's first cause).
   - The Generate button's image is drawn at the width it gets in the plug-in's 360 px layout: 243–267 px.
   - In a panel narrower than that layout, the fork gives the image all the width left (`render.rs:579`). The mode drop-down, the region mask toggle and the queue button then fall past the edge.
   - The cause lives in both repositories: the plug-in doesn't know the panel's width (`mirror.py:173`), and the protocol has no way to send it (`docs/process-plugins.md` has `width` only for dialogs, `:277-283`).
2. **The strength slider takes the whole row** (bug 1, the strength row).
   - The fork's `sliderSpin` asks for the available width minus 64 px, and nothing in the row is marked `grow`, so the row doesn't share. Add Control Layer and Add Region (2 × 28 px, plus spacing and the spin box) don't fit in what's left.
   - Unlike cause 1, this happens at any panel width.
3. **The mode drop-down is an empty, frameless button** (bug 2's second cause). Upstream gives it no text and no icon, only Qt's down arrow (`generation.py:779-780`). The mirror doesn't send `arrowType`, and the fork draws a button with no icon and no text as nothing. So even in a panel wide enough, the drop-down is there and clickable, but invisible.

The selection itself does reach upstream. It polls the selection every 20 ms (`ai_diffusion/document.py:357-364`), and the stand-in refreshes its cached selection on PhotoCraft's `selection.changed` (`photocraft_host/krita/_app.py:32`, `:147`). With a selection, upstream makes the drop-down visible, and the mirror sends that.

## Recommended Fix

1. **Lay the panel out at PhotoCraft's width** (fork and plug-in):
   - The fork sends a panel's content width when it is shown and when it changes, for example a `panel.resized {panelId, width}` event, documented in `docs/process-plugins.md`.
   - The mirror resizes its Qt root to that width, keeping 360 px as the fallback until the first one arrives. Qt then reflows, the Generate image is drawn at the width that fits, and the row's tail stays in view, as in a Krita docker.
   - Below Qt's minimum width (274 px for this panel), the fork should let the panel scroll sideways or keep the dock at least that wide, rather than cut the row.
2. **Share a row's width with sliders** (fork, or the mirror): a `sliderSpin` in a row shouldn't take the available width itself.
   - **In the fork:** `slider()` takes only its share when it is in a row.
   - **In the mirror:** the mirror already marks a widget `grow` when its layout says it expands (`photocraft_host/qt_mirror/layouts.py:69-86`). The strength widget doesn't expand, but Qt still gives it the row's spare width, because nothing else in the row expands. Marking the widgets Qt stretches that way, when a row has no expanding one, would let `row()` give the slider what the fixed items leave, as Qt does.
3. **Draw a tool button's arrow** (plug-in, or both):
   - The button adapter sends `arrowType` when there's no icon and no text, for example as an `icon:` reference such as `icon:chevron-down`, if the fork has that icon.
   - Alternatively the fork draws an `arrow` prop, or never draws an empty button invisibly.
4. **Verify** in PhotoCraft at the dock's minimum and default widths:
   - with no selection: Generate, the region toggle and the queue button are in view;
   - with a selection: Fill shows, the drop-down's arrow shows, and clicking it opens the mode menu;
   - the strength row shows Add Control Layer and Add Region.
