# Walkthrough: Use the platform's TLS and the system fonts in the plug-in process

The plug-in no longer crashes when another OpenSSL is on `PATH`. At start-up, Qt is switched to the operating system's own TLS (schannel on Windows, Secure Transport on macOS), so Python's `ssl` and Qt never run two OpenSSL builds side by side. On Windows, Qt's offscreen platform now gets the system fonts, so text in widgets the mirror sends as images renders. A missing release and upstream's `pykrita` check no longer log misleading messages. The cause is in the [findings](../../investigations/plugin-crash-after-30-seconds/findings.md).

## What Was Implemented

### 1. Qt set-up in the plug-in process
- **`photocraft_host/qt_setup.py`** (new):
  - `configure_fonts` sets `QT_QPA_FONTDIR` to `%WINDIR%\Fonts` on Windows unless it's already set; it leaves other platforms alone.
  - `use_platform_tls` makes `schannel` or `securetransport` Qt's active backend where Qt has one. Linux is left as it is.
  - `font_family_count` counts the font families Qt found.
- **`photocraft_host/main.py`**: `main()` sets up the fonts before the `QApplication` exists and the TLS backend right after it. It logs `Qt: TLS <backend>, <n> font families`.

### 2. Upstream adaptations (each in [UPSTREAM-CHANGES.md](../../UPSTREAM-CHANGES.md))
- **`ai_diffusion/model/updates.py`**: a 404 from GitHub (no release published yet) logs "No release of the plug-in is published yet" and ends as `latest`, with no traceback. Other errors still fail the check.
- **`ai_diffusion/extension.py`**: the "not installed in a 'pykrita' directory" warning is skipped in PhotoCraft.

### 3. Tests
- **`tests/photocraft/test_qt_setup.py`** (new):
  - the font folder on each platform;
  - on Windows, `tls_crash.py`: the crash's preconditions in a child process. That's Python's `ssl` loaded, Git for Windows' OpenSSL first on `PATH`, and one HTTPS request through Qt to a local server, with a certificate made for the test by that folder's `openssl.exe`.
- **`tests/photocraft/test_transport.py`**: a started plug-in logs a non-zero font count, and schannel on Windows. CI runs this on all three platforms.
- **`tests/photocraft_upstream/test_updates_diagnostics.py`**: a local server answers the release URL with 404, then with 500.
- **`tests/photocraft/upstream_shim.py`**: the stand-in test harness switches Qt to the platform's TLS as the plug-in does. The GPU suite runs upstream's code in the test process, so it needs this to behave like the plug-in.

### 4. Records
- **The original walkthrough** ([spec/ai-diffusion-for-photocraft/walkthrough.md](../ai-diffusion-for-photocraft/walkthrough.md)): its crash follow-up now points to the findings and this fix, and the real-PhotoCraft trial and the managed install are recorded as far as they were done.
- **The findings**: the close-frame crash is confirmed as the same cause.

### Changes from the plan as approved
- **TASK-9** was revised and re-approved before it was implemented. Setting a TLS backend makes Qt load every backend, so the foreign OpenSSL is still *loaded*, just never used. The test therefore checks for the crash itself, not for which libraries are loaded.
- **TASK-9's wait** is 5 seconds instead of the plan's 40. Without the fix, tearing the connection down at exit is enough to crash (checked by hand twice at 5 s, once at 45 s). The test stays fast in CI.
- **TASK-11's test** is in `tests/photocraft_upstream/`, where the update tests are; the plan named `tests/photocraft/`.
- **The harness change** (`upstream_shim.py`) wasn't planned. Without it, the managed install re-run crashed again, because the fix runs only in the plug-in's `main()`.

## Verification & Test Results

### Automated Tests
- **The font folder on each platform** (`test_qt_setup.py`, 3 tests): **Passed**.
- **HTTPS with Git's OpenSSL on `PATH`** (`test_qt_setup.py`, Windows): **Passed**. Qt used schannel, the request returned 200, and the process exited normally.

  Run without the fix, `tls_crash.py` ended in an access violation or heap corruption (exit 139 or 127) three times out of three: twice at 5 s, once at 45 s.
- **The start-up log line** (`test_transport.py`): **Passed**, `Qt: TLS schannel, 57 font families`.
- **No release yet** (`test_updates_diagnostics.py`): **Passed**. The 404 ends as `latest` with the info line and no traceback, and a 500 still fails the check.

### Regression Testing
Final pass on Windows, all **passed**:

| Check | Result |
|---|---|
| Project suite (includes the parity test) | 334 passed |
| Upstream's tests and this project's tests of upstream code, on the stand-in | 246 passed, 19 skipped |
| Upstream's unit tests | 279 passed, 122 skipped |
| `ruff format`, `ruff check`, `pyright` | clean |
| `tests/photocraft/upstream_changes.py` | passes |
| Package contents check | passes |

## Manual Verification
Each scenario that crashed, re-run on Windows from Git Bash with Git's `mingw64\bin` on `PATH`:
1. **The plug-in for 60 s against a minimal host, with the update check on** (`.local-scratch/longrun.py`): **Passed**. It survived the 60 s, logged `Qt: TLS schannel, 57 font families`, and logged "No release of the plug-in is published yet" instead of an error with a traceback. Before the fix: a crash at 35 s.
2. **The real PhotoCraft** (the fork's release build, with an isolated settings folder, the package rebuilt and reinstalled, no `QT_QPA_FONTDIR` set): **Passed**.
   - The plug-in stayed up past 75 s with nothing touched.
   - The Generate and Apply buttons show their text, and the style list opens.
   - A generation from the panel came back: six images, with a preview on the canvas.
   - No `pykrita` warning was logged.

   Seen once in this run: the update check failed with "HTTP/2 protocol error" after 17 s. Six requests to the same URL on schannel right after all answered 404 in under 0.2 s, so it looks like a passing network failure. It was logged as an error, as errors other than 404 should be.
3. **The websocket close-frame reproduction**: **Passed**, three runs out of three, no crash. At the commit where the crash was found (`2c04b79`) it crashed three times out of three, and stopped from `a43826c` (TASK-39) on. At `2c04b79` without Git's folder on `PATH`, it didn't crash either: it was the same cause, triggered by an HTTPS request at start-up that TASK-39 removed.
4. **The managed CUDA install test** (`test_e2e_gpu.py -k managed_cuda`): **Passed**, with the hosts audit. It installed, downloaded the SDXL workload, launched on a free port and connected, in 3 minutes 23 seconds (downloads cached from earlier attempts). Before the harness change, it crashed during the custom nodes' downloads.

Still for you to check by hand:
- **On a machine where Git's folder isn't on `PATH`** (most users'): start PhotoCraft normally and check that the plug-in's log says `Qt: TLS schannel` and a non-zero font count.
- **On macOS**, when there's a Mac: check that the log says `securetransport` and that the panel's text renders. CI checks the font count there too.

## Follow-ups
- **Linux** has only Qt's OpenSSL backend. Check whether the bundled Python's `ssl` (python-build-standalone links OpenSSL statically) can clash with the system `libssl.so.3` that Qt loads. That belongs with the deferred Linux GPU run: leave the plug-in up for more than a minute after an HTTPS request.
- **The Generate button** was a little wider than a narrow panel during the first trial. It's cosmetic, and came from the mirror's layout. A separate spec if wanted.
- **Prompt font**: the prompt field shows a monospace font in PhotoCraft. Also cosmetic.
