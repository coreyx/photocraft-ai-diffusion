---
status: approved
---

# Make the plug-in's CI pass on all three platforms

The first push's CI run failed for three separate reasons:
- the plug-in process aborts at shutdown when a network reply finishes after upstream has closed its event loop;
- the macOS job names a runner GitHub no longer offers;
- the live-overhead test times the mock host's per-pixel Python loops rather than the plug-in.

This plan fixes all three. It also stops the TLS set-up from logging warnings on platforms that don't have the backend it asks for.

**Related documents**
- [Investigation findings](../../investigations/ci-first-push-failures/findings.md)

## User Review Required

> [!IMPORTANT]
> **One more upstream file changes.** `ai_diffusion/backend/network.py` gets a guard in `RequestManager._finished` and a row in `UPSTREAM-CHANGES.md`. The same double exception can happen in Krita when it closes, so the guard is worth offering upstream. The host-side exception hook (TASK-1) would prevent the abort on its own. Without the guard, though, every Linux shutdown with a request in flight would still log a traceback.

> [!IMPORTANT]
> **Verifying this needs two actions on GitHub:**
> - pushing the branch (a normal push, not a force-push);
> - disabling upstream's `test.yml` in the repository's Actions settings (TASK-11).
>
> The second is the step the first walkthrough already lists for after the first push. `UPSTREAM-CHANGES.md:69` records the decision to disable that workflow rather than edit it, so `test.yml` keeps its `macos-14` label.

> [!NOTE]
> **With the exception hook, an exception that escapes a Qt slot is logged and the plug-in keeps running,** instead of the process aborting. That is how upstream's code behaves in Krita. Code after the exception in that slot doesn't run, so a later problem can follow from it. The log says where it started.

> [!NOTE]
> **macOS will run in CI for the first time.** If it fails for reasons other than the ones fixed here, the walkthrough reports them and they get their own spec, rather than being folded into this one.

## Open Questions

- **Is the macOS TLS backend `securetransport` in the PyQt6 6.11 wheels?** The plan asks for it on macOS (TASK-6). If Qt doesn't offer it, Qt logs one warning and keeps its default, and the start-up line shows which backend is active. The first macOS CI run answers this. A macOS assertion next to the Windows one in `test_transport.py` waits for that answer, and the walkthrough records it.
- **Can `gh workflow disable test.yml` find the workflow?** `gh workflow list` currently shows only "PhotoCraft plug-in", so GitHub may not have registered `test.yml` yet. If the command can't find it, it also hasn't run. The walkthrough then notes that it must be disabled once it appears, which happens on the first pull request or push to `main`.

## Proposed Changes

### Plug-in process

#### [MODIFY] `photocraft_host/main.py`
- [x] **TASK-1:** Add `install_excepthook()`, which sets `sys.excepthook` to log the exception with `log.critical("unhandled exception in the plug-in", exc_info=(type, value, tb))`. Call it first thing in `main()`, before the `QApplication` is created.
  - A comment explains why: PyQt6 calls `qFatal` (`abort`) when an exception escapes a slot while `sys.excepthook` is Python's default, and Krita's own Python host doesn't stand behind the plug-in process here.
  - `KeyboardInterrupt` goes to `sys.__excepthook__`, so Ctrl+C still behaves normally when the process is run by hand.

#### [MODIFY] `ai_diffusion/backend/network.py`
- [x] **TASK-2:** In `RequestManager._finished`, once the tracker's future is known, return without touching it when `future.done()` or `future.get_loop().is_closed()`. In the `except` branch, call `future.set_exception(e)` only when the future isn't done yet. The existing `future.cancelled()` check is covered by `done()`, so it merges into the new check.

#### [MODIFY] `UPSTREAM-CHANGES.md`
- [ ] **TASK-3:** Add a row for `ai_diffusion/backend/network.py`, status `changed`. Reason: a reply that finishes after `eventloop.stop()` raised `RuntimeError` and then `InvalidStateError` from inside a Qt slot, which aborts a process without an exception hook. This is a bug fix also present in Krita, worth offering upstream. Task: TASK-2. Place the row in the table's path order.

### Tests for the shutdown abort

#### [NEW] `tests/photocraft/late_reply.py`
- [ ] **TASK-4:** A helper script, run as a subprocess the way `tests/photocraft/tls_crash.py` is. It reproduces the shutdown race deterministically on every platform, without relying on how fast a refused connection fails:
  1. Start a local TCP server on a free loopback port, in a thread. It accepts one connection and holds it open without answering.
  2. Set up the `krita` stand-in with a temporary data folder, then upstream's `eventloop` and a `RequestManager`, and send a GET to that server.
  3. Once the request is connected, call `eventloop.stop()`, then let the server close the connection, which makes the reply finish with an error.
  4. Run Qt until the reply has finished, with a 10 s cap. Print `finished` and exit with `app.exec()`'s code.

  With `--raise-in-slot`, it instead calls `photocraft_host.main.install_excepthook()`, raises `ValueError` from a `QTimer.singleShot` slot, prints `survived` after the next event and exits 0.

#### [NEW] `tests/photocraft/test_late_reply.py`
- [ ] **TASK-5:** Two subprocess tests:
  - `test_a_reply_finishing_after_the_event_loop_closed_doesnt_abort`: the helper with no hook exits 0, prints `finished`, and its stderr has neither `InvalidStateError` nor `Event loop is closed`. This fails at the current head; checked before TASK-2 is applied.
  - `test_an_exception_escaping_a_qt_slot_is_logged_not_fatal`: the helper with `--raise-in-slot` exits 0, prints `survived`, and its stderr has `unhandled exception in the plug-in` and `ValueError`.

### TLS backend

#### [MODIFY] `photocraft_host/qt_setup.py`
- [ ] **TASK-6:** Replace the `PLATFORM_TLS` tuple with a mapping, `{"win32": "schannel", "darwin": "securetransport"}`. `use_platform_tls(platform: str = sys.platform)` calls `QSslSocket.setActiveBackend` only with that platform's backend. On any other platform it doesn't call it. It returns `QSslSocket.activeBackend()` as before.
  - The docstring keeps its reason (two OpenSSL builds in one process on Windows) and says that Linux leaves Qt's choice alone.
  - Callers in `tls_crash.py` and `upstream_shim.py` keep calling it with no argument.

#### [MODIFY] `tests/photocraft/test_qt_setup.py`
- [ ] **TASK-7:** Add `test_each_platform_asks_only_for_its_own_tls_backend`. With `QSslSocket.setActiveBackend` monkeypatched to record its calls, `use_platform_tls("win32")` asks for `["schannel"]`, `"darwin"` for `["securetransport"]`, and `"linux"` for nothing.

### CI

#### [MODIFY] `.github/workflows/photocraft.yml`
- [ ] **TASK-8:** Change `macos-14` to `macos-15` in the test matrix (line 59), matching the PhotoCraft fork's CI.

### Live-overhead test

#### [MODIFY] `tests/photocraft/mock_host.py`
- [ ] **TASK-9:** Make the mock host's pixel copies cost milliseconds rather than hundreds of them, with the same results:
  - `MockHost._region` copies each row's clipped run with one slice assignment instead of a byte copy per pixel.
  - `MockHost._composite`'s `draw` reads each layer's alpha bytes with one slice (`pixels[3::4]`). It copies a layer with no transparent pixel whole, skips a fully transparent one, and keeps the per-pixel loop only for layers with mixed alpha.

  The existing pixel tests (`tests/photocraft` and `tests/photocraft_upstream`) check that nothing changed.

#### [MODIFY] `tests/photocraft_upstream/test_live.py`
- [ ] **TASK-10:** In `test_the_plugins_own_overhead_for_a_live_update`, cite criterion 24.1 instead of REQ-24.3 in the docstring, and keep the `< 0.25` s assertion unchanged.

### GitHub repository settings

#### [MODIFY] `coreyx/photocraft-ai-diffusion` Actions settings
- [ ] **TASK-11:** Disable upstream's workflow with `gh workflow disable test.yml -R coreyx/photocraft-ai-diffusion`, as the first walkthrough's step 4 says. If GitHub hasn't registered it yet, record that in the walkthrough instead (see Open Questions).

## Verification Plan

### Automated Tests
The project's pytest suites rather than a `scratch/` script, as in the earlier plans: this repository's tests live in `tests/photocraft` and `tests/photocraft_upstream`, and CI runs them on three platforms.
1. `tests/photocraft/test_late_reply.py`: a reply finishing after the loop closed doesn't abort, and an exception escaping a slot is logged (TASK-1, TASK-2, TASK-4, TASK-5). Its first test is run before TASK-2 to confirm it reproduces the abort.
2. `tests/photocraft/test_qt_setup.py`: each platform asks only for its own backend (TASK-6, TASK-7).
3. `test_live.py`'s overhead test stays under 250 ms. With the mock host's copies sped up, it should be a few tens of milliseconds locally, with and without `coverage run` (TASK-9, TASK-10).
4. Regression, all locally:
   - the whole project suite, the stand-in suite and upstream's unit tests, with the commands CI uses;
   - `ruff check`, `ruff format --diff` and `pyright`;
   - `python tests/photocraft/upstream_changes.py` (TASK-3).

### Manual Verification
1. Push `feat/ai-diffusion-for-photocraft`, then check that the "PhotoCraft plug-in" run passes on all three platforms:
   - `gh run list -R coreyx/photocraft-ai-diffusion`, then `gh run view <id> -R coreyx/photocraft-ai-diffusion`;
   - the coverage gate and the upstream changes check included.
2. In the macOS job's plug-in test log, read the `Qt: TLS <backend>, <n> font families` line. Record the backend and font count in the walkthrough, which answers the first open question.
3. Run `gh workflow list --all -R coreyx/photocraft-ai-diffusion` and check that `test.yml` shows as disabled, or record that it isn't registered yet (TASK-11).
4. On this machine, start the plug-in against a minimal host with no ComfyUI running and shut it down within a second (`tests/photocraft/test_transport.py`'s headless test does this). It exits 0. On Windows the refusal arrives too late for this to have failed before the fix, so this is a sanity check; the deterministic check is item 1 of Automated Tests.
