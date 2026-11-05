---
status: approved
---

# Use the platform's TLS and the system fonts in the plug-in process

The plug-in crashes about 30 seconds after its first HTTPS request whenever another OpenSSL build with the same file names is on `PATH` (Git for Windows' `mingw64\bin`, for one). Python's `ssl` and Qt's `openssl` backend then load two different builds. This change:
- keeps Qt on the platform's own TLS;
- gives Qt's offscreen platform the system fonts on Windows, which it otherwise lacks;
- quiets two misleading log messages;
- re-runs every scenario that crashed.

**Related documents**
- [Investigation findings](../../investigations/plugin-crash-after-30-seconds/findings.md)
- [AI Diffusion for PhotoCraft walkthrough](../ai-diffusion-for-photocraft/walkthrough.md)

## User Review Required

> [!IMPORTANT]
> On Windows and macOS, the plug-in's own HTTPS goes through the operating system's TLS (schannel, Secure Transport) instead of whatever OpenSSL Qt can find. That covers update checks, model and ComfyUI downloads, and HTTPS ComfyUI servers. Certificates are then checked against the system's certificate store, which is what a plain Windows install of the plug-in already does today. The websocket connection to ComfyUI uses Python's `ssl` and is unaffected. Krita AI Diffusion inside Krita behaves differently: Krita bundles its own OpenSSL.

> [!NOTE]
> Re-running the managed CUDA install test downloads several gigabytes (ComfyUI, PyTorch, an SDXL checkpoint and its required models) into `.local-scratch/` and takes up to an hour. It runs in the background.

## Open Questions

None at this time. Linux, where Qt has only an OpenSSL backend, is checked during the deferred Linux GPU run, not here.

## Proposed Changes

### Qt set-up in the plug-in process

#### [NEW] `photocraft_host/qt_setup.py`
- [x] **TASK-1:** `configure_fonts(environ: MutableMapping[str, str], platform: str = sys.platform) -> str | None`:
  - On Windows, when `QT_QPA_FONTDIR` isn't set, set it to `%WINDIR%\Fonts`. Qt's offscreen platform on Windows looks in Qt's own (empty) font folder otherwise.
  - Return the folder set, or `None`. An explicit setting is kept, and other platforms are left alone.
- [x] **TASK-2:** `use_platform_tls() -> str`:
  - When Qt offers the platform's own TLS backend (`schannel` on Windows, `securetransport` on macOS), make it the active one with `QSslSocket.setActiveBackend`, before any request is made.
  - Return the active backend's name.
  - A docstring explains why: two OpenSSL builds in one process crash it (the findings).
- [x] **TASK-3:** `font_family_count() -> int`, for the start-up log line.

#### [MODIFY] `photocraft_host/main.py`
- [x] **TASK-4:** In `main()`, call `configure_fonts(os.environ)` before the `QApplication` is created, and `use_platform_tls()` right after, before `install_krita_shim()`. Log one line: `Qt: TLS <backend>, <n> font families`.

### Upstream adaptations

#### [MODIFY] `ai_diffusion/model/updates.py`
- [x] **TASK-5:** In `_check_release`, a `NetworkError` with status 404 means no release is published yet. Log it at info level ("No release of the plug-in is published yet"), with no traceback, and set the state to `UpdateState.latest`. Other errors keep going through `_handle_errors`.

#### [MODIFY] `ai_diffusion/extension.py`
- [x] **TASK-6:** Skip the "not installed in a 'pykrita' directory" warning when `krita` is the PhotoCraft stand-in (`hasattr(krita, "photocraft_host")`, as the other PhotoCraft branches check). In PhotoCraft, the install folder is PhotoCraft's.

#### [MODIFY] `UPSTREAM-CHANGES.md`
- [x] **TASK-7:** Add the `extension.py` row, and extend `updates.py`'s row with the 404 case. `tests/photocraft/upstream_changes.py` must still pass.

### Tests

#### [NEW] `tests/photocraft/test_qt_setup.py`
- [x] **TASK-8:** `configure_fonts` unit tests:
  - Windows with no setting: the folder is set;
  - an existing setting is kept;
  - macOS and Linux: nothing is set.
- [x] **TASK-9:** Windows-only slow test in a child process, the crash's preconditions:
  - Put a foreign OpenSSL folder at the front of `PATH`: Git for Windows' `mingw64\bin`, found on `PATH` or at its default install folder. The test is skipped when there isn't one.
  - Run `import ssl`, create a `QCoreApplication` and call `use_platform_tls()`.
  - Assert that the active backend is `schannel` and that Qt reports Secure Channel as its TLS library. Qt still loads the foreign OpenSSL when it loads its backends, but never uses it; the test checks for the crash itself instead.
  - Make an HTTPS request through `QNetworkAccessManager` to a local HTTPS server (Python's `ssl`, a certificate made for the test, its errors ignored for this request), then keep the event loop running past 40 s. Assert that the process exits normally. Before the fix, the same sequence crashed between 30 and 35 s.
- [x] **TASK-10:** A started plug-in process logs `Qt: TLS …, <n> font families` with `n > 0` (an assertion added to `test_transport.py`'s headless process test). It runs in CI on all three platforms, so CI shows whether macOS and Linux need a font setting too.

#### [MODIFY] `tests/photocraft/test_updates_diagnostics.py`
- [ ] **TASK-11:** A local HTTP server answers the release URL with 404 (`AI_DIFFUSION_UPDATE_URL`). The check ends as `latest`, and its log has the info line and no traceback.

### Records

#### [MODIFY] `spec/ai-diffusion-for-photocraft/walkthrough.md`
- [ ] **TASK-12:** Change the native-crash follow-up to point to the findings and to this fix, with the scenarios re-run and their results.

## Verification Plan

### Automated Tests
The project's pytest suites, rather than a `scratch/` script: this repository's tests live in `tests/photocraft` and `tests/photocraft_upstream`, and CI runs them on three platforms.
1. `tests/photocraft/test_qt_setup.py`: the font set-up, and a foreign OpenSSL not loaded with Qt left on schannel (TASK-8, TASK-9).
2. `test_transport.py`'s headless process test: the start-up line with a non-zero font count (TASK-10).
3. `test_updates_diagnostics.py`: a 404 ends as `latest`, with no traceback (TASK-11).
4. Regression: the whole project suite, the stand-in suite, upstream's unit tests, the parity check, `ruff`, `pyright` and `tests/photocraft/upstream_changes.py`.

### Manual Verification
Each scenario that crashed, re-run on this machine with the fix:
1. **The minimal-host run with the update check on**, from Git Bash (Git's `mingw64\bin` on `PATH`): `python .local-scratch/longrun.py <repo> 60 '{"auto_update": true, "server_mode": "external", "server_url": "127.0.0.1:8188"}'` survives 60 s. Before the fix, it crashed at 35 s.
2. **The real PhotoCraft from Git Bash.** Rebuild the package and unpack it into the isolated profile. Launch PhotoCraft from Git Bash with `PHOTOCRAFT_CONFIG_DIR` and no `QT_QPA_FONTDIR`. Then:
   - the plug-in stays up for 75 s with nothing touched;
   - the Generate button reads "Generate";
   - the style list opens;
   - a generation from the panel comes back.
3. **The websocket close-frame reproduction** (`.local-scratch/close-crash-repro/`): no crash. If it still crashes, it has a different cause, and the walkthrough says so.
4. **The managed CUDA install test** from Git Bash (`PHOTOCRAFT_E2E_COMFYUI=127.0.0.1:8188 PHOTOCRAFT_E2E_INSTALL=<.local-scratch/managed-install> pytest ... -k managed_cuda`): it installs, downloads the SDXL workload, launches on a free port and connects.
