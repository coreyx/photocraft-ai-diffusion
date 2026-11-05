# Findings: the plug-in crashes about 30 seconds after it starts

## Problem

Inside the real PhotoCraft (built from the fork's `feat/process-plugins`), on Windows, the AI Diffusion plug-in process died about 30 seconds after starting. It happened three times in a row and once more with no interaction at all. PhotoCraft reported "stopped unexpectedly: the plug-in exited with code -1073741819" (`0xC0000005`, access violation), and the panel disappeared. Python's fault handler showed the main thread inside Qt's event loop (`app.exec()`, `photocraft_host/main.py:218`), not in Python code.

Two other native crashes looked related:
- **The managed install test**: heap corruption (`0xc0000374`) during `uv pip install`.
- **A ComfyUI stand-in** that never answers the websocket close frame (recorded in the walkthrough's follow-ups).

## Investigation

- **Timing.** The crash came 31–36 s after the plug-in started in every run. With nothing touched, it came at 30.8 s. So it was a timer or a delayed event, not a user action. (The first crash happened to coincide with opening the style list.)
- **Outside PhotoCraft.** A driver that plays a minimal PhotoCraft (answers every request, pings every 5 s) ran the plug-in from source for 60 s, connected to a ComfyUI:
  - with `auto_update` off, it **survived**;
  - with `auto_update` on, it **died at about 30 s** with `0xc0000374`.

  The trigger was the update check: one HTTPS `GET` to `api.github.com` through Qt (`ai_diffusion/model/updates.py:152`, via `RequestManager`, `ai_diffusion/backend/network.py:88`, `:146`), which answers 404 while the project has no release.
- **No plug-in code.** A 40-line script made the same HTTPS request with a bare `QCoreApplication` and `QNetworkAccessManager`, then idled:
  - alone, it **survived** 70 s;
  - with `import ssl` first, as the plug-in does through websockets (`ai_diffusion/backend/comfy_client.py:22`), it **crashed between 30 and 35 s** (access violation);
  - with `import ssl` and Qt's TLS backend set to `schannel`, it **survived**.
- **Which OpenSSL.** These runs were started from Git Bash, whose `PATH` includes Git for Windows' `mingw64\bin`. That folder holds OpenSSL 3.5.7 under the same file names Python uses (`libssl-3-x64.dll`, `libcrypto-3-x64.dll`).

  | Run | Qt's TLS | Python's `ssl` |
  |---|---|---|
  | With `import ssl` first | openssl, 3.5.7, loaded from Git's folder | 3.5.8 (3.5.9 in the plug-in's bundled Python), from Python's own `DLLs` |
  | Without Python's `ssl` | Git's copy, the only one loaded | not loaded |
  | Started from PowerShell (no OpenSSL on `PATH`) | Secure Channel (`schannel`) | its own OpenSSL, the only one in the process |

  With `import ssl` first, two OpenSSL builds are loaded side by side.
- **In the real workflow.** PhotoCraft launched from PowerShell: the plug-in stayed up past 75 s, and a generation through the real UI worked (six results from ComfyUI, a preview on the canvas). The crashing trial had been launched from Git Bash, so the plug-in inherited Git's `PATH`.

## Root Cause(s)

1. **Two OpenSSL builds in one process.** The plug-in imports Python's `ssl` at start-up (websockets, `comfy_client.py:22`), which loads the OpenSSL that ships with Python. Qt's network module picks its `openssl` TLS backend whenever it can load OpenSSL. It looks for `libssl-3-x64.dll`/`libcrypto-3-x64.dll` on the DLL search path, and loads a different build by path when one is there (Git for Windows' `mingw64\bin` here; MSYS2, other toolchains and some applications ship such copies too).

   The first HTTPS request through Qt (`network.py:146`) then runs on a second OpenSSL. About 30 s later the process dies inside Qt's event loop, with an access violation or heap corruption. The exact timer is inferred, not observed: the delay is consistent with Qt dropping the idle keep-alive TLS connection to the server.

   Without a foreign OpenSSL on `PATH`, Qt falls back to Windows' `schannel` and nothing crashes. That's why most users wouldn't see it, and why developers with Git's tools on `PATH` would.

   ```mermaid
   sequenceDiagram
       participant P as Plug-in start
       participant Py as Python ssl (OpenSSL 3.5.8, Python's DLLs)
       participant Qt as Qt network (openssl backend)
       participant G as OpenSSL 3.5.7 (found on PATH)
       P->>Py: import websockets → import ssl
       P->>Qt: update check: HTTPS GET api.github.com
       Qt->>G: load libssl/libcrypto by path (a second build)
       G-->>Qt: TLS session, reply 404
       Note over Qt,G: connection kept alive, idle
       Qt->>G: ~30 s later: idle connection torn down
       G--xP: access violation / heap corruption
   ```

2. **Why the tests never saw it.** The tests turn the update check off (`auto_update: false`), and every test's plug-in process exits well within 30 s; the GPU suite ran 18 s. Upstream's managed installer does download over HTTPS through Qt (`server.py:282`, ComfyUI from GitHub), which explains the heap corruption during the install test (run from Git Bash) a little later, during `uv pip install`.

3. **Not the cause, found along the way.** On Windows, Qt's `offscreen` platform finds no fonts at all (`QFontDatabase.families()` is empty, in the bundled runtime and the development environment alike). Widgets the mirror sends as images, such as the Generate button, draw their text as empty boxes. Setting `QT_QPA_FONTDIR` to `%WINDIR%\Fonts` gives 57 families and fixes the drawing. It is unrelated to the crash.

**Update (after the fix):** the close-frame crash is the same cause. Its reproduction crashed at the commit it was found at (`2c04b79`) and no longer from `a43826c` (TASK-39) on, and at `2c04b79` it didn't crash with Git's folder left off `PATH`. Before TASK-39, the plug-in's start-up made an HTTPS request through Qt as well. With the fix ([spec/plugin-tls-and-fonts-fix](../../spec/plugin-tls-and-fonts-fix/implementation_plan.md)), every scenario that crashed passes from Git Bash.

## Recommended Fix

- **One TLS stack for Qt.** At start-up, before any network request, set Qt's TLS backend to the platform's own (`QSslSocket.setActiveBackend("schannel")` on Windows). Qt then never loads a foreign OpenSSL, whatever is on `PATH`.
  - macOS: Qt's native backend (`securetransport`).
  - Linux: Qt only has `openssl` there. Check whether Python's `ssl` (python-build-standalone links OpenSSL statically) can clash with the system `libssl.so.3` that Qt loads. Include that in the Linux GPU run.
- **Fonts for the offscreen platform.** Before the `QApplication` is created, set `QT_QPA_FONTDIR` to the system font folder (Windows `%WINDIR%\Fonts`). macOS and Linux need checking too.
- **Regression tests:**
  - Check the active TLS backend and the font count in a started plug-in process.
  - Add a slow opt-in test that keeps the plug-in alive past 40 s after an HTTPS request, with an OpenSSL on `PATH` that differs from Python's.
- **Re-run what crashed before:**
  - the managed CUDA install test;
  - the websocket close-frame reproduction;
  - the real-PhotoCraft trial launched from Git Bash.
- **Smaller items** the trial found, worth fixing in the same pass:
  - The update check logs a 404 with a traceback while no release exists.
  - Upstream warns about a missing `pykrita` folder, which means nothing in PhotoCraft.
