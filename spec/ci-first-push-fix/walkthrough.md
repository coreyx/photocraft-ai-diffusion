# Walkthrough: CI first-push fix

This fixes the three causes of the first push's CI failures ([findings](../../investigations/ci-first-push-failures/findings.md)):
- the plug-in process aborted at shutdown when a network reply finished after upstream had closed its event loop;
- the macOS job named a runner GitHub no longer offers;
- the live-overhead test timed the mock host's per-pixel loops rather than the plug-in.

It also stops the TLS set-up from logging a warning for each backend a platform doesn't have.

Linux and Windows now pass in CI. On macOS, where the job ran for the first time, every test this spec added or fixed passes. Five other tests fail because of how Qt handles the keyboard and message boxes on macOS; they're listed in Follow-ups.

## What Was Implemented

### 1. The shutdown abort
- **`photocraft_host/main.py`**: `install_excepthook()` logs an exception nothing caught (`unhandled exception in the plug-in`, at critical level) instead of letting PyQt6 abort the process. `main()` installs it first thing. `KeyboardInterrupt` still goes to Python's own hook.
- **`ai_diffusion/backend/network.py`** (upstream): `RequestManager._finished` leaves a future alone once it's done or its event loop has closed. The `except` branch sets an exception only on a future that isn't done. This was the double exception, `RuntimeError` then `InvalidStateError`, that escaped the slot.
- **`UPSTREAM-CHANGES.md`**: a row for `network.py`, marked as a bug fix also in Krita and worth offering upstream.
  - Deviation: the plan said to place it in path order, but the table isn't sorted by path. The row sits after the related `eventloop.py` fix instead.
  - Its Task column follows the existing style for later specs (`ci-first-push-fix TASK-2`).

### 2. Tests for the abort
- **`tests/photocraft/late_reply.py`**: a helper run as its own process. A local server accepts the request and holds it. Once the request has arrived, `eventloop.stop()` runs, then the server answers `503` and closes the connection, so the reply finishes after the loop has closed. A second mode, `--raise-in-slot`, raises from a Qt slot under the plug-in's hook.
  - Deviation: the plan had the server only close the connection. Qt resends a GET whose connection closed without a response, and the resend then waited for a refused connection: 4 s on Windows, ending in `ConnectionRefusedError`.
  - The server also has to read the request before answering. An answer sent first counted as a dropped connection too.
  - With both changes, the reply ends with `503` about 10 ms after the loop closes, on any platform.
- **`tests/photocraft/test_late_reply.py`**: a late reply doesn't abort and raises nothing, and an exception escaping a slot is logged and the process carries on.

### 3. TLS backend
- **`photocraft_host/qt_setup.py`**: `PLATFORM_TLS` maps `win32` to `schannel` and `darwin` to `securetransport`. `use_platform_tls(platform=sys.platform)` asks for that platform's backend only. On Linux it asks for none, so Qt no longer logs `Cannot set unavailable backend` at every start.
- **`tests/photocraft/test_qt_setup.py`**: each platform asks only for its own backend.

### 4. CI
- **`.github/workflows/photocraft.yml`**: the macOS job runs on `macos-15`, as the PhotoCraft fork's CI does. Upstream's `test.yml` is unchanged, as `UPSTREAM-CHANGES.md` records.
- **Upstream's `test.yml`, disabling it on GitHub**: not possible yet. `gh workflow disable test.yml` answers `HTTP 404: workflow test.yml not found on the default branch`, because GitHub has registered only `photocraft.yml`. See Manual Verification.

### 5. Live-overhead test
- **`tests/photocraft/mock_host.py`**:
  - `_region` copies a row's run at a time.
  - `_composite` copies an opaque layer whole, skips a transparent one, and keeps the per-pixel loop for mixed alpha or a buffer that isn't the canvas's size.
- **`tests/photocraft_upstream/test_live.py`**: the docstring cites criterion 24.1. The 250 ms budget is unchanged.

## Verification & Test Results

### Automated Tests
The project's pytest suites, as in this repository's earlier plans:
- **The new tests fail when their fix is taken out.** Both tests in `test_late_reply.py` fail when their fix is removed: the process aborts with `0xc0000409` without the reply guard for the first, and without the exception hook for the second. With the fixes they pass. **Passed**
- **The helper reproduces the abort** with the guard reverted, 3 runs out of 3, and exits 0 with it, 3 out of 3. Before the server's two changes, it still aborted without the guard, but the guarded run took 4 s and ended on a refused resend. **Passed**, after the deviation above.
- **`test_each_platform_asks_only_for_its_own_tls_backend`** passes, and fails against the old version. **Passed**
- **The mock host's new copies give the same bytes** as the old ones on 300 random documents: opaque, transparent, mixed and missing layers, with 6 rectangles each, some reaching past every edge. **Passed**
- **Live overhead:** 3–13 ms locally, and 4–17 ms under `coverage run`. Before this change it was 142–159 ms, and 199–224 ms under coverage. **Passed**

### Regression Testing
Locally, with CI's own commands (`photocraft.yml`):

| Check | Result |
|---|---|
| `ruff format --diff`, `ruff check` | Clean |
| `pyright -p packaging/pyrightconfig.json` | 0 errors. Locally it needs `--pythonpath .venv/Scripts/python.exe`, since CI installs into its own Python. |
| `tests/photocraft/upstream_changes.py` | Passes |
| Plug-in tests, under coverage | 340 passed |
| Upstream unit tests | 268 passed, 27 skipped |
| Stand-in tests, under coverage | 246 passed, 19 skipped |
| Coverage gate | Passes: overall 93.2% of lines and 78.3% of branches; the stand-in and persistence mapping 96.8% and 77.1%; the reuse 97.4% and 87.0% |

In CI, on `7fee86f` (run 42327749402):

| Job | Result |
|---|---|
| check | **Passed** |
| ubuntu-22.04 | **Passed**: plug-in tests 338 passed and 2 skipped, upstream unit tests 268 and 27, stand-in tests 244 and 21. This includes the two shutdown tests that failed on the first push. |
| windows-2022 | **Passed**: 339 passed and 1 skipped, 268 and 27, 246 and 19. This includes the live-overhead test. |
| macos-15 | **Failed: 5 of 340 plug-in tests.** The upstream unit tests, the stand-in tests and the coverage gate passed. |

On macOS, everything this spec touched passed: both `test_late_reply.py` tests, the TLS test, the headless process test, the bootstrap test and the live-overhead test. The five failures are new, from the job's first run; see Follow-ups.

## Manual Verification
- **CI on all three platforms:** done, with the results above.
- **The macOS TLS backend:** not readable from CI. The start-up line (`Qt: TLS <backend>, <n> font families`) goes to the plug-in's stderr, and pytest shows that only for a failing test. So the macOS assertion next to the Windows one in `test_transport.py` is still to add. See Follow-ups.
- **Upstream's `test.yml`:** check whether it has appeared, and disable it once it has:
  1. Run `gh workflow list --all -R coreyx/photocraft-ai-diffusion`.
  2. When `test.yml` is listed (GitHub registers it on the first pull request or push to `main`), run `gh workflow disable test.yml -R coreyx/photocraft-ai-diffusion`.
  3. Expect one run before you can: the event that registers it also starts it. It installs a ComfyUI server and downloads models, and it lists `macos-14`, so that job will be refused. Cancel the run with `gh run cancel <id> -R coreyx/photocraft-ai-diffusion` if it starts.
- **A shutdown in the real PhotoCraft on Linux** with no ComfyUI running: the plug-in should exit without "stopped unexpectedly". This belongs with the deferred Linux GPU run, since there's no Linux machine here.

## Follow-ups
- **The plug-in tests fail on macOS (5 tests), for two Qt behaviors on macOS.** They get their own investigation and spec:
  - **Ctrl and Meta are swapped:** Qt maps the Control modifier to the Command key there, so the mirror's injected `ctrl` reaches widgets as `MetaModifier`. This fails four tests:
    - `test_self_drawn_widgets_are_images`: the modifier assertion;
    - `test_prompt_edits_cursor_and_keys`: a wait times out;
    - `test_ctrl_up_weights_the_word_at_the_cursor`: Ctrl+Up doesn't weight the word;
    - `test_tags_autocomplete`, for the same reason.

    It probably affects real use on a Mac too: which key PhotoCraft sends as `ctrl` needs checking against `Qt.ApplicationAttribute.AA_MacDontSwapCtrlAndMeta`.
  - **Message box titles are empty:** `QMessageBox` has no window title on macOS, so `dialog.message` reaches PhotoCraft with `title: ""` (`test_message_boxes_ask_photocraft`). The mirror could take the title from what the box was created with.
- **A macOS assertion for the TLS backend** in `test_transport.py`, once the backend is known. One way to learn it: run the headless test on a Mac, or print the start-up line from that test.
- **The `network.py` guard** is worth offering upstream, alongside the other bug fixes `UPSTREAM-CHANGES.md` marks the same way.
- **The backup branch** `backup/pre-session-fix` is local only. It holds this branch from before the two `Session:` trailers were corrected. Delete it with `git branch -D backup/pre-session-fix`.
