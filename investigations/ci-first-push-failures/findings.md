# Findings: CI fails on the fork's first push

## Problem

The first push of `feat/ai-diffusion-for-photocraft` to `coreyx/photocraft-ai-diffusion` ran the "PhotoCraft plug-in" workflow (`.github/workflows/photocraft.yml`) at `a91f688`. The files are the same at `30256f5`, the head after the attribution rewrite. No platform passed:

| Job | Step | Failure |
|---|---|---|
| ubuntu-22.04 | Plug-in tests | `test_bootstrap.py::test_with_its_runtime_ready_the_plugin_starts_on_the_same_connection`: `assert proc.wait(timeout=30) == 0`. Its message, the log's tail, starts with `qt.network.ssl: Cannot set unavailable backend named "schannel" as active` |
| ubuntu-22.04 | Plug-in tests | `test_transport.py::test_the_plugin_process_starts_headless_and_shuts_down`: `assert -6 == 0` at line 381 |
| ubuntu-22.04 | Upstream code on the stand-in | `test_live.py::test_the_plugins_own_overhead_for_a_live_update`: 498 ms, against `< 250 ms` |
| windows-2022 | Upstream code on the stand-in | The same test: 478 ms |
| macos-14 | none | Cancelled after one second, with no steps |

The other 333 plug-in tests and 243 stand-in tests passed on Linux. On Windows only the live-overhead test failed. The force-push of `30256f5` started no new run. The next push will start one.

## Investigation

- **The two Linux plug-in failures are one crash.** Both processes exited with -6 (`SIGABRT`). The schannel line in the bootstrap test's message is only the first line of the log tail that the assertion prints. Its last lines show the cause: when the session ended, `ai_diffusion/backend/network.py` `_finished` raised `RuntimeError: Event loop is closed` and then `InvalidStateError: invalid state`. Both happened while upstream's request to `http://127.0.0.1:8188` was failing; no ComfyUI runs on CI.
- **Reproduced on Windows.** A minimal script makes one `RequestManager.http` request to a closed loopback port, calls `eventloop.stop()` as the plug-in's shutdown does, and runs Qt until the refusal arrives. It aborted with exit code `0xC0000409`, Windows' code for `abort()`, two runs out of two. With a `sys.excepthook` set, it logged the `InvalidStateError` and exited 0, two runs out of two.
- **Why Windows CI passed.** A refused loopback connection takes about 2.0 s on Windows, because it retries the connection, against an immediate refusal on Linux. Measured: 2.03, 2.06 and 2.02 s. The tests shut the plug-in down sooner than that, so on Windows the reply never finishes inside the window between closing the loop and quitting.
- **macOS never ran.** The job's annotation reads `The configuration 'macos-14-arm64-us-default' is not supported`, and it has no runner name. `fail-fast` is `false` in this workflow, so the other jobs' failures didn't cancel it. The PhotoCraft fork's CI uses `macos-15`. Upstream's `test.yml` names `macos-14` too, but it runs only on `main` and on pull requests.
- **The live-overhead test measures the test's fake PhotoCraft.** Timed locally with the test's own setup:
  - 142–159 ms without coverage;
  - 199–224 ms under `coverage run`, which this CI step uses (`photocraft.yml:92`);
  - 478–498 ms on the CI machines, under coverage.

  A profile of one preparation (204 ms under coverage) puts 200 ms in `tests/photocraft/mock_host.py`. That's 145 ms in `_composite`'s inner loop and 55 ms in `_region`, both Python loops over every pixel of the 1024×1024 document. The plug-in's own code, the stand-in's `pixels.read` call and upstream's preparation, takes about 4 ms.

## Root Cause(s)

1. **An unhandled exception in a Qt slot aborts the plug-in at shutdown (both Linux plug-in failures).** The chain:

   ```mermaid
   sequenceDiagram
       participant H as Host (test or PhotoCraft)
       participant M as photocraft_host/main.py
       participant E as ai_diffusion/extension.py
       participant L as ai_diffusion/eventloop.py
       participant N as backend/network.py
       participant Q as PyQt6
       Note over N: autostart's request to 127.0.0.1:8188 in flight
       H->>M: shutdown
       M->>E: applicationClosing (main.py:178-181)
       E->>L: eventloop.stop() (extension.py:59-61)
       Note over L: _loop.close() (eventloop.py:46-53)
       M->>Q: QTimer.singleShot(0, app.quit) (main.py:113-115)
       Q->>N: reply finished: connection refused (immediate on Linux)
       N->>N: future.set_exception → loop.call_soon → RuntimeError: Event loop is closed (network.py:243)
       N->>N: except: future.set_exception(e) → InvalidStateError (network.py:244-246)
       N-->>Q: exception escapes the slot
       Q->>Q: no sys.excepthook installed → qFatal → abort (-6)
   ```

   - **Upstream closes its asyncio loop before the application quits.** PyQt6 aborts on an exception that escapes a slot only when `sys.excepthook` is Python's default, as the reproduction shows. The plug-in process installs no hook: `grep excepthook` over `photocraft_host/` finds nothing. Why this doesn't abort Krita wasn't checked. Krita's Python host setting a hook of its own is the likely reason.
   - **`network.py:244-246` turns the first error into a second one.** `Future.set_exception` has already marked the future done before `call_soon` raised, so the `except` branch's `set_exception` raises `InvalidStateError`. That exception escapes the slot.
   - **This isn't limited to tests.** Any reply that finishes between `eventloop.stop()` and `app.quit` aborts the process when PhotoCraft shuts the plug-in down. On Linux, a refused connection hits that window every time. Any platform can hit it with a reply that happens to finish in that tick.

2. **The CI matrix names a macOS runner GitHub no longer provides.** It's `macos-14` at `.github/workflows/photocraft.yml:59`, and also at `test.yml:39`.

3. **The live-overhead test times the mock host's per-pixel Python loops, not the plug-in.** `tests/photocraft/mock_host.py:543-556` (`_region`) and `:558-576` (`_composite`) copy 4 bytes at a time over a million pixels. That cost is about 97% of what the test measures. It scales with the machine and with coverage tracing, so it passes locally at 60% of the budget and fails on CI at nearly twice it. Real PhotoCraft composites natively. The end-to-end check of the budget on the reference GPU is the GPU suite's (TASK-45).
   - Smaller: the test's docstring cites REQ-24.3. The 250 ms budget is criterion 24.1 (`spec/ai-diffusion-for-photocraft/requirements.md:544`), and 24.3 is Apply.

4. **Contributing, cosmetic: the TLS setup asks for schannel everywhere.** `qt_setup.use_platform_tls` (`photocraft_host/qt_setup.py:31-51`) tries `schannel`, then `securetransport`, on every platform. Each unavailable one logs a `qt.network.ssl: Cannot set unavailable backend` warning on stderr: two warnings at every start on Linux, and on macOS one for schannel. It didn't cause any failure, but it heads every Linux log and put it first in the bootstrap test's message, which looked like the cause.

## Recommended Fix

1. **Shutdown abort:**
   - Install a `sys.excepthook` in the plug-in process (`photocraft_host/main.py`, before upstream is imported) that logs the exception instead of letting PyQt6 abort.
   - Stop network replies from reaching a closed loop. Either let `RequestManager._finished` skip a future whose loop is closed (and not call `set_exception` on a future that's already done), or abort in-flight replies before `eventloop.stop()`. The second touches upstream code, so prefer the host-side hook plus the smallest upstream guard, and list it in the upstream changes check.
   - Make the regression test deterministic on every platform: a shutdown with a reply that finishes after the loop has closed, for example to a closed port with Windows' delay waited out, must still exit 0.
2. **macOS:** change `macos-14` to `macos-15` in `photocraft.yml`, matching the PhotoCraft fork, and in `test.yml` too, so it doesn't fail the same way on a pull request.
3. **Live overhead:** measure what the test is named for, the plug-in's own overhead. Leave the budget at 250 ms rather than raising it, and either:
   - make the mock host's `_region` and `_composite` copy by rows and slices, not by pixel, so the fake costs a few milliseconds; or
   - subtract the time spent inside the mock host's handlers from the measured time.

   The first is simpler and also speeds up the other tests that read pixels. Correct the docstring to 24.1.
4. **TLS warnings:** choose the backend by platform (`schannel` on `win32`, `securetransport` on `darwin`, nothing to set elsewhere) instead of trying each one. Keep the comment's reason, which is why Qt's OpenSSL must not be used on Windows. Add a macOS assertion next to the Windows one at `test_transport.py:393-394`, once CI shows which backend macOS reports.
