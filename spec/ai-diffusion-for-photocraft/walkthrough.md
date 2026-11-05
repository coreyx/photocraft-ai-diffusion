# Walkthrough: AI Diffusion for PhotoCraft

Krita AI Diffusion (v1.54.0-pre) now runs inside PhotoCraft as a separate process plug-in, with the same generation features, settings and ComfyUI integration. PhotoCraft's side is a generic process plug-in host, built in the `coreyx/photocraft` fork. The plug-in runs upstream's Python code on headless PyQt6. A `krita` API stand-in talks to PhotoCraft, and a mirror turns upstream's Qt widgets into panels PhotoCraft draws natively. The online service is left out. The plug-in can use an existing Krita AI Diffusion setup's server and models.

## What Was Implemented

All 46 tasks in [tasks.md](tasks.md) are done. One commit per task in this repository, and the host work also in the fork.

### 1. Repositories and baselines (Milestone 1, TASK-1 to TASK-4)
- **This repository** carries Krita AI Diffusion's full history, merged at `v1.54.0-pre` (`828b70c`).
- **Attribution**: `README.md`, `NOTICE` and `LICENSE` (GPL-3.0) credit Krita AI Diffusion.
- **[UPSTREAM-CHANGES.md](../../UPSTREAM-CHANGES.md)** lists every upstream file this project changes, with the reason.
- **Tooling**: `requirements-photocraft.txt`, `packaging/runtime/` (pinned PyQt6 6.11 runtime) and `.github/workflows/photocraft.yml`.
- **Graph-parity fixtures**: 121 scenarios captured from upstream (`tests/photocraft/fixtures/graphs`, `tests/photocraft/parity/`).
- **The fork's baseline**: recorded in [HOST-BASE.md](HOST-BASE.md).

### 2. The process plug-in host, in the PhotoCraft fork (Milestones 2–4, TASK-5 to TASK-21, plus TASK-23, 26 and 43)

These were developed on `feat/process-plugins`, with the same tree on `feat/process-plugins-upstream` (prepared to offer to `storytold/photocraft`).

- **The protocol and plug-in manager**:
  - a protocol crate: framed JSON plus binary payloads over stdin/stdout, with versioned methods;
  - launching and supervising plug-ins;
  - Preferences › Plug-ins (install from a `.zip`, restart, turn off, remove);
  - an echo plug-in with host tests.
- **What a plug-in can do with documents**:
  - persistent layer uids;
  - document, layer and undo requests;
  - pixel, selection and mask transfer;
  - change events;
  - data stored in documents (`.pcraft` optional fields);
  - transient previews shown outside the document;
  - editable pose vector content;
  - resampling a document.
- **Its UI**:
  - host services and progress;
  - a native renderer for widget trees;
  - panels in the dock;
  - dialogs, message boxes and pickers;
  - actions in menus and shortcuts;
  - widgets that claim keys, and grid headers.
- **`plugin.update`**: a plug-in can ask PhotoCraft to install a newer package of itself and restart it (TASK-43).
- **Docs**: `docs/process-plugins.md` in the fork documents the protocol, installing, and the security model.

### 3. Krita AI Diffusion running in PhotoCraft (Milestone 5, TASK-22 to TASK-27)
- **`photocraft_host/transport.py`, `framing.py`, `main.py`**: the plug-in process connects to PhotoCraft (`hello`/`welcome`), keeps stdout for frames only, and starts upstream as Krita starts a Python plug-in.
- **`photocraft_host/krita/`**: the `krita` API stand-in upstream imports, backed by PhotoCraft's requests: documents, layers, selection, annotations as plug-in data, actions and dockers.
- **`photocraft_host/qt_mirror/`**: upstream's Qt widgets mirrored into PhotoCraft panels. Prompt fields, lists, menus, dialogs and drawn widgets (sent as images) are included.
- **Upstream adaptations**: bit depth and colour modes are converted rather than refused (REQ-37). The plug-in's data folder comes from PhotoCraft. Animation is hidden until PhotoCraft has a timeline (REQ-26). Each changed upstream file is listed in UPSTREAM-CHANGES.md.

### 4. Generation features (Milestone 6, TASK-28 to TASK-35)
- Generation, the queue, regions, control layers, pose editing, prompt features, styles, Live, upscaling and the Graph workspace run on the stand-in with upstream's own code.
- Previews are shown outside the document. Live reads are cached.
- A reopened document gets its plug-in state back.
- **Parity**: the graphs the plug-in builds match upstream's in all 121 scenarios.

### 5. Configuration, servers and Krita AI Diffusion reuse (Milestone 7, TASK-36 to TASK-41)
- **Settings**: parity with upstream. Online-service keys are only written while the cloud module is enabled.
- **The managed server**:
  - every catalog model's license is shown before download;
  - its own `extra_model_paths.yaml` section;
  - on macOS and Linux, the server ends with the plug-in.
- **Custom servers**: connecting, reconnecting, and keeping the queue across a dropped websocket.
- **The online service**: moved out to an optional `ai_diffusion_cloud` module (`photocraft_host/cloud.py`).
- **Krita AI Diffusion reuse** (`photocraft_host/krita_reuse.py`, `krita_reuse_widget.py`):
  - detects Krita AI Diffusion configurations on Windows, macOS and Linux;
  - uses the same server, and launches a managed install read-only;
  - imports settings and files, with tokens only after a second confirmation;
  - offers this plug-in's own server sharing the same models;
  - stops reusing once you switch away.

### 6. Packaging, updates, localization and release readiness (Milestone 8, TASK-42 to TASK-46)
- **`packaging/build.py`**:
  - builds one package per platform (Windows x64, macOS Apple silicon and Intel, Linux x64);
  - bundles CPython 3.12 (python-build-standalone) and uv, each pinned by SHA-256;
  - writes a `SHA256SUMS`.
- **`photocraft_host/bootstrap.py`**: says `hello` at once, installs the runtime (`uv sync --frozen`) on first start behind a setup panel, then hands the connection to the plug-in.
- **The release workflow**: `.github/workflows/release.yml`.
- **Updates and diagnostics**: updates come from this project's GitHub releases, are checksum-verified, and are installed through `plugin.update`. Diagnostics hide the data folder, home folder, user name, nonce and tokens.
- **Localization**: the UI names PhotoCraft, and the plug-in follows PhotoCraft's language. A string audit allows "Krita" only nominatively (in names such as "Krita AI Diffusion"), and all 14 languages are checked.
- **Coverage gate (TASK-45)**:
  - `.coveragerc` and `tests/photocraft/coverage_gate.py` run in CI;
  - the plug-in's processes now save their coverage on exit (`framing.leave`);
  - the reuse widget is tested in its own process.
- **Secrets and network audits** (`tests/photocraft/audits.py`).
- **The GPU end-to-end suite** (`tests/photocraft_upstream/test_e2e_gpu.py`).
- **Upstream merges (TASK-46)**:
  - `tests/photocraft/upstream_changes.py` checks UPSTREAM-CHANGES.md against git, and previews a merge's conflicts;
  - `docs/upstream-merge.md` is the merge procedure;
  - `tests/photocraft/test_model_licenses.py` requires a license for every catalog model.

### Upstream bugs fixed along the way
These are fixed here and worth offering upstream. Each is in UPSTREAM-CHANGES.md.
- **Security**: custom and managed servers were sent the online service's access token as a websocket Bearer header (`model/connection.py`).
- `eventloop.run()` kept no reference to its task, so connecting could hang at "Connecting".
- `SliderSetting` returned floats for int settings, which reverted to their defaults on restart.
- `Connection.disconnect()` raised `CancelledError` when the message task hadn't started.
- `extra_model_paths.yaml` lost the plug-in's section when `model_patches` was added.
- Reopening a document whose embedded workflow was active didn't restore its graph.

## Verification & Test Results

### Automated Tests
Final pass, on Windows 11 with Python 3.12:
- **This project's tests** (`pytest tests/photocraft`): **Passed**, 330 tests.
- **Upstream's tests and this project's tests of upstream code on the stand-in** (`-p tests.photocraft.upstream_shim ... tests/photocraft_upstream`): **Passed**, 245 passed, 19 skipped. The skips: upstream tests of upstream's own mock that don't apply on the stand-in, and the GPU suite without a server.
- **Upstream's unit tests** (`pytest tests --ci`, without the server and client tests): **Passed**, 279 passed, 122 skipped (upstream's GPU and cloud tests).
- **Graph parity** (`parity/driver.py --host photocraft`): **Passed**, 121 scenarios, 0 differ.
- **Coverage gate**: **Passed**.

  | Scope | Lines | Branches |
  |---|---|---|
  | Overall | 93.2% | 78.2% |
  | `krita` stand-in, with the persistence mapping | 96.8% | 77.1% |
  | Krita AI Diffusion reuse | 97.4% | 87.0% |

  REQ-39.0.4's "≥ 90%" for the stand-in, persistence and reuse code doesn't say whether it means lines or branches. It's read as lines, with the overall 70% branch floor still applying; you confirmed this reading.
- **Audits**: **Passed**. No secret value (a ComfyUI token, an online-service token, the launch nonce) appears in logs or output, and only allowed hosts were asked.
- **GPU end-to-end suite** (Windows, ComfyUI 0.42.3, RTX 5090, SD 1.5): **Passed**, 8 passed, 1 skipped.
  - Passed: generate and apply, inpaint a selection, Live, upscale, a custom graph, a control layer from an image, Krita AI Diffusion's server, and the audits.
  - Skipped: the opt-in managed CUDA install (see Manual Verification).

  Getting there:
  - **The server dropped out.** On the first run, the ComfyUI server stopped answering and the test timed out; the cause wasn't found. After a restart, generation took 21 seconds.
  - **Two test bugs, not plug-in bugs:**
    - The upscale test waited for a finished job in the job list, but upstream removes upscale jobs from the list once they finish. The test now waits on `job_finished`.
    - The control-layer test didn't set up the shared connection that upstream's control layers read.
  - Each run now gets a random canvas, because ComfyUI answers an identical graph with "no new images".
- **Upstream change log** (`tests/photocraft/upstream_changes.py`): **Passed**. It first found two gaps, both fixed: `tests/test_service.py` had no entry, and the catalog template's path was incomplete.
- **Upstream merge rehearsal**:
  - Upstream `main` is still the base, so a real merge has nothing to do.
  - A release cycle simulated with `git merge-tree` (`v1.53.0` over `v1.54.0-pre`, 77 upstream files changed) conflicts in 3 files, all listed.
  - The documented parity steps, run against an unchanged `v1.54.0-pre` checkout, match the committed fixtures and the plug-in.
- **Format, lint and type checks** (`ruff format`, `ruff check`, `pyright`): **Passed**. The package contents check finds no reference to the online service.

### Regression Testing
- **The fork**: as of TASK-43, the last fork change:
  - `cargo xtask ci`: fmt, clippy, layers and the scorecard pass. The tests have the 4 failures known before this work (`atn_crystallize` ×2, `relight_admission`, and a GPU timing test).
  - Also run: the panic-hunt run, the doc tests, the wasm build and the i18n coverage check.
  - The fork hasn't changed since. Its two branches still have identical trees.
- **This repository**: every task re-ran all three Python suites and the parity check before its commit.

## Manual Verification

1. **A clean machine, with the real PhotoCraft UI.** This has not been done yet. The plug-in has only run against the mock PhotoCraft in the tests, and the built package against a stand-in host: `hello` after 0.6 s, first start 12.9 s, later starts 0.3 s. On a machine (or VM) without Python or Krita:
   1. Build PhotoCraft from the fork's `feat/process-plugins` branch and run it.
   2. Build the package: `python packaging/build.py --version 0.1.0 --platform windows-x64` (or the machine's platform).
   3. In PhotoCraft, open Preferences › Plug-ins and install `dist/ai-diffusion-for-photocraft-0.1.0-<platform>.zip`.
   4. Check that a setup panel shows the runtime installing, and that the AI Image Generation panel appears when it's done.
   5. Restart PhotoCraft. The panel should appear within a second or two, with no setup panel.
   6. In the panel's settings, connect to a ComfyUI server (Connection page), generate in a new document, and apply a result. Check that Undo removes it.
   7. Inpaint a selection, start Live, and upscale. Check that the panels, menus, dialogs and the drawn widgets (the history thumbnails, the control layer list) render and respond.
   8. Save the document as `.pcraft`, close and reopen it. Check that the prompt, history and regions come back.
2. **The GPU suite on Linux.** Deferred until a Linux machine with a GPU is free. On it, with a ComfyUI that has an SD 1.5 or SDXL checkpoint and Krita AI Diffusion's required models:
   ```sh
   PHOTOCRAFT_E2E_COMFYUI=127.0.0.1:8188 python -m pytest -p tests.photocraft.upstream_shim \
     tests/photocraft_upstream/test_e2e_gpu.py -v
   ```
   All 8 should pass (the reuse case skips if no Krita AI Diffusion configuration is on that machine).
3. **The managed CUDA install (criterion 29.1).** Written but not run: it downloads tens of gigabytes and takes most of an hour. Add `PHOTOCRAFT_E2E_INSTALL=<an empty folder>` to the command above.
4. **Before the first push:**
   - Scan the outgoing commits for private details.
   - After pushing, disable upstream's CI for this repository: `gh workflow disable test.yml`. It installs a ComfyUI server and downloads models.
   - Check that this project's CI (`PhotoCraft plug-in`) passes on all three platforms, including the coverage gate and the upstream changes check.
5. **Flux Redux.** It now downloads from Black Forest Labs' own Hugging Face repository, which is gated. Accept its license on Hugging Face before installing that optional model, or the download fails.

## Follow-ups

- **A native crash to investigate.** On Windows, the plug-in process crashes (`0xc0000374`, heap corruption) when a ComfyUI server accepts the websocket but never answers the client's close frame. Its cause is unknown, so it's a case for `/investigate`. A reproduction is kept locally (not committed): a stand-in server that doesn't answer close frames, and a probe script. A plain asyncio reproduction does *not* crash, so it needs more of the connect path. PhotoCraft supervises the plug-in, so the crash ends the plug-in, not PhotoCraft. But a misbehaving server shouldn't be able to cause it at all.
- **tech.md's license line for python-build-standalone.** It says "Apache-2.0/MIT". The build scripts are MPL-2.0, and the bundled CPython is under the PSF license; `THIRD-PARTY.txt` in each package states them correctly. tech.md is approved, so correcting it needs your go-ahead to reopen it.
- **Non-commercial models.** 14 models in the catalog don't allow commercial use, including MAT, the default inpaint model the managed server requires. The installer shows each license, but anyone using the plug-in commercially needs to pick their models accordingly.
- **Offer the host to PhotoCraft.** `feat/process-plugins-upstream` in the fork is ready to propose to `storytold/photocraft`. Until it's merged there, the plug-in needs the fork.
- **Offer the upstream bug fixes** above to Krita AI Diffusion, the security fix first.
- **Animation** (REQ-26) waits for a PhotoCraft Frame Animation panel. The workspace is hidden until then.
- **The first GPU run's lost server** wasn't explained: ComfyUI stopped answering partway through. If it happens again, ComfyUI's console from that run would say why.
