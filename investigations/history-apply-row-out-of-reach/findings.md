# Findings: the history's Apply row can't be scrolled into view (not yet reproduced)

## Problem

The report: sometimes, after generating or using the plug-in normally, the Generate panel can't be scrolled all the way down to "Apply ...". The scroll stops short of it.

"Apply ..." is the row under the history in PhotoCraft: upstream's Apply button and its "…" context button. In Qt, upstream places them over the selected result (`ai_diffusion/ui/generation.py:116-133`, `:310-332`). The mirror sends the history as a column: the thumbnail grid, then a row of these overlays (`photocraft_host/qt_mirror/adapters/lists.py:135-149`). So in PhotoCraft the Apply row is the last thing in the panel.

**Status:** the cause isn't known. This records what was checked, so a later look starts from here.

## Investigation

- **The panel's real tree after two generations, laid out by PhotoCraft's renderer.**
  - The tree was captured from the mirror on the mock host, with two finished jobs of four results each and the newest selected.
  - A temporary test in the fork drew it inside a vertical scroll area like a panel's body, at 300 × 500 and 300 × 800 pt, and with the scroll offset at 0 and at its end.
  - The content was 719 pt tall in a 484 pt view, and the last button sat within the scroll range. **Not reproduced.**
- **A NaN height turned out to be the test's own.** A first run forced the scroll offset to `f32::MAX`. egui then reported a NaN content height, and its debug build stopped on `Negative desired size: [142.0 NaN]` in `row()`. With a finite offset, or none, it didn't happen. So it isn't a lead.
- **In PhotoCraft:** the fork's release build, with the rebuilt package and your local ComfyUI.
  - **After 1 and 6 results:** the Apply row showed under the history.
  - **After 12 results:** the history ran past the panel's bottom and a scroll bar appeared.
  - **Scrolling it couldn't be checked:**
    - the control protocol has no wheel or drag input, only clicks, pointer moves and pointer input in document coordinates;
    - two tries with Windows' own mouse-wheel input didn't scroll the panel;
    - that input may have reached another window, so it wasn't tried again.
- **The panel's width mattered elsewhere.** Until `spec/generate-panel-rows-fit`, the plug-in laid the panel out at 360 px, or Qt's default of 853–974 px for the never-shown dock, whatever PhotoCraft's width was. Whether that affected the history's layout or how far it scrolls wasn't established.

## Root Cause(s)

Not found.

## Recommended Fix

None yet. Next steps:
1. **Retest** with the fork and package that include `generate-panel-rows-fit`: the panel is now laid out at PhotoCraft's width, which may change what happens.
2. **If it still happens,** record which workspace, roughly how many results, the dock's width, and a screenshot at the furthest scroll. Also note whether the panel was "Not responding…" (greyed), and whether a generation was running.
3. **To reproduce here,** the control protocol needs a way to scroll: a `ui.scroll {x, y, dy}`, or a scroll field on `ui.click`, in the fork. A scroll can then be scripted against a long history.
