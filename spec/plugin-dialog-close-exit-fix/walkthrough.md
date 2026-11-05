# Walkthrough: Keep the plug-in running when its last dialog closes

Closing the plug-in's settings dialog used to stop the plug-in: Qt ends the event loop when the last window closes, and in the plug-in a dialog is the only window there is. The plug-in now turns that off, and ends only when PhotoCraft asks it to or the connection closes. The cause is in the [findings](../../investigations/plugin-exits-when-dialog-closes/findings.md).

## What Was Implemented

### 1. Plug-in process
- **`photocraft_host/main.py`**: `app.setQuitOnLastWindowClosed(False)` right after the `QApplication` is created, with the reason in a comment. It covers every dialog the plug-in shows: settings, message boxes, errors.

### 2. Tests
- **`tests/photocraft/test_transport.py`**:
  - `test_closing_the_settings_dialog_keeps_the_plugin_running` starts the plug-in process as PhotoCraft does, opens the settings dialog with `action.triggered`, closes it with `dialog.closed`, and requires the plug-in to answer `ping` and then shut down cleanly.
  - The start-up shared with the headless process test moved into `_start_plugin` and `_welcome`.

## Verification & Test Results

### Automated Tests
- **The new process test**: **Passed**. With `setQuitOnLastWindowClosed(False)` taken out, it fails with "the plug-in closed the connection" (checked by hand, then restored).

### Regression Testing
Final pass on Windows, all **passed**:

| Check | Result |
|---|---|
| Project suite | 335 passed |
| Stand-in suite | 246 passed, 19 skipped |
| Upstream's unit tests | 279 passed, 122 skipped |
| `ruff format`, `ruff check`, `pyright` | clean |
| `tests/photocraft/upstream_changes.py` | passes |

## Manual Verification
Done in the real PhotoCraft (the fork's release build, a second isolated profile, the rebuilt package, driven through the control protocol):
1. Opened the settings dialog with the panel's Configure button and closed it with its close button, three times: **Passed**. The panel stayed, and PhotoCraft logged no "stopped unexpectedly".
2. Generated from the panel afterwards: **Passed**, six images with a preview on the canvas.

Still for you to check by hand: closing with OK and Cancel, and a message box. The settings dialog in PhotoCraft showed no OK or Cancel buttons (see Follow-ups). Upstream's import confirmation is one message box to try.

## Follow-ups
- **The Connection page renders incompletely in PhotoCraft.** Only the Krita AI Diffusion section and Restore Defaults are drawn. The server-mode buttons and the server panels (`_server_mode`, the `QStackedWidget` in `ui/settings.py` `ConnectionSettings`) aren't, and no OK or Cancel buttons show either. The plug-in-side tests find those widgets in the mirrored tree, so the gap is probably in how PhotoCraft's renderer draws one of them. It needs its own investigation.
- **PhotoCraft doesn't restart a plug-in that stopped on its own.** It reports the exit and waits for a restart from Preferences › Plug-ins. Restarting automatically, or offering to, would be a change in the fork.
- **A native "Open" file dialog** appeared on the screen once during this work, and was closed by hand. Neither PhotoCraft's nor the plug-in's log recorded a file request. It was probably one of the synthetic clicks driving PhotoCraft. Not reproduced.
