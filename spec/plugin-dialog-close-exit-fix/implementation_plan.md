---
status: approved
---

# Keep the plug-in running when its last dialog closes

Closing the plug-in's settings dialog, or any dialog it shows, ends the plug-in process. Qt quits the event loop when the last window closes, and in the plug-in a dialog is the only window there ever is. This keeps the event loop running until PhotoCraft stops the plug-in.

**Related documents**
- [Investigation findings](../../investigations/plugin-exits-when-dialog-closes/findings.md)

## User Review Required

> [!NOTE]
> The plug-in then ends only when PhotoCraft asks it to (`shutdown`) or the connection closes, as the design intends. Neither path changes.

## Open Questions

None at this time.

## Proposed Changes

### Plug-in process

#### [MODIFY] `photocraft_host/main.py`
- [x] **TASK-1:** In `main()`, right after the `QApplication` is created, call `app.setQuitOnLastWindowClosed(False)`, with a comment saying why: dialogs are the only windows the plug-in shows.

### Tests

#### [MODIFY] `tests/photocraft/test_transport.py`
- [x] **TASK-2:** A process test, following `test_the_plugin_process_starts_headless_and_shuts_down`:
  - Start the plug-in as PhotoCraft does, and answer its requests.
  - Send the `action.triggered` event for `ai_diffusion_settings`, and wait for its `dialog.open` request.
  - Send `dialog.closed` for that dialog.
  - Send `ping` a second later, and require the answer and a process that's still running, then shut it down cleanly.
  - Check by hand that the test fails without TASK-1.

## Verification Plan

### Automated Tests
The project's pytest suite (this repository's equivalent of a `scratch/` script):
1. The new process test (TASK-2), which fails without TASK-1.
2. Regression: the project suite, the stand-in suite, upstream's unit tests, `ruff` and `pyright`.

### Manual Verification
1. Rebuild the package, reinstall it into the isolated PhotoCraft profile, and launch PhotoCraft.
2. Open the plug-in's settings dialog and close it, three times: with the close button, with Cancel, and with OK.
3. Check that the AI Image Generation panel is still there, and that PhotoCraft's log has no "stopped unexpectedly".
4. Generate once from the panel.
