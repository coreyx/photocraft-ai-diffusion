---
status: approved
---

# AI Diffusion for PhotoCraft Tech Stack

## Summary

The work spans two repositories.

- **Host side**, in a GitHub fork of PhotoCraft, MIT OR Apache-2.0: the PhotoCraft toolchain as it is (Rust 1.95, edition 2024, egui 0.37 / craft-ui, `photocraft-cms`, `photocraft-psd`), plus a new protocol crate and new engine, app and UI modules. It talks to plug-ins over the child process's stdio, using length-prefixed frames that carry a JSON header and a raw binary payload.
- **Plug-in side**, in this repository, GPL-3.0: Krita AI Diffusion's Python, merged in with its git history, running on CPython 3.12 that `uv` provisions, with headless PyQt6 6.11 (offscreen platform). On top of that sit a `krita` API shim over the protocol and a generic Qt-widget mirror that sends Krita AI Diffusion's unchanged widget tree to PhotoCraft to draw natively. Tests use pytest, pytest-cov and graph-parity fixtures captured from unmodified Krita AI Diffusion.

## Decisions

### Repositories and source layout

**Choice:**
- **Host**: `github.com/coreyx/photocraft`, a GitHub fork of `storytold/photocraft`. Work happens on branch `feat/process-plugins`, cut from the upstream `main` commit current when work starts (`5617e00` or later). Every host commit is a small, self-contained change, so the series can be offered upstream as a sequence of PRs (REQ-12).
- **Plug-in**: this repository, `github.com/coreyx/photocraft-ai-diffusion`. Krita AI Diffusion's history is merged in: add a remote `upstream` for `Acly/krita-ai-diffusion`, then merge tag `v1.54.0-pre` (commit `828b70c`) with `--allow-unrelated-histories`. `ai_diffusion/` stays at the repository root exactly where upstream has it.
- **Our own code goes in new top-level packages**, never mixed into upstream files:
  - `photocraft_host/`: the protocol client, the `krita` shim and the Qt mirror;
  - `packaging/`: the plug-in manifest, build scripts and the uv lockfile;
  - `tests/photocraft/`: our tests.
- **Spec documents**: the spec for both repositories stays here, under `spec/`. Commits in the fork carry the same `Spec:`/`Task:`/`Session:` trailers.

**Why:**
- The license split (REQ-38.0.2, [APP-004]) needs separate repositories.
- REQ-38.0.3 / 38.2 asks that later Krita AI Diffusion releases merge with conflicts only in files we changed. A real git merge of upstream history is the only thing that gives that. Copying a snapshot would turn every future update into a manual diff.
- A GitHub fork keeps the host series rebasable on upstream and lets it go up as PRs.

**Alternatives considered:**
- *Vendoring a snapshot of Krita AI Diffusion*: no merge base, so later updates become manual.
- *A git submodule of upstream plus patch files*: patch maintenance is fragile and tooling-unfriendly.
- *One repository for host and plug-in*: mixes licenses and makes upstreaming the host impossible.

### Host language, toolchain and crate placement

**Choice:** PhotoCraft's own toolchain: Rust stable ≥ 1.95, edition 2024, `cargo xtask ci`. The new code is placed by PhotoCraft's layer rules ([APP-011], host analysis §1a):

| Piece | Location | Layer | Notes |
|---|---|---|---|
| Protocol types and frame codec | new crate `crates/process-plugin-protocol` (`photocraft-process-plugin-protocol`) | L0, standalone | Pure `serde` types, frame encode and decode, version constants. Builds for wasm. Registered in `xtask/src/layers.rs`. |
| Request handlers against the document | new engine module `crates/engine/src/process_plugin/` | L5 | Document, layer, pixel, selection, blob, vector, preview-layer and action-registry handling, each as `Session` operations. No process spawning and no I/O. Change events come from per-document revision and selection diffs. |
| Process spawning and transport | `apps/photocraft/src/process_plugins.rs` | exempt (app) | Native only. Injected through `Services` the same way the update check is (`updates_cmds.rs` precedent). |
| UI | new `crates/ui-egui/src/plugin_ui/` | L6 | Widget-tree renderer, a generic plug-in dock group with dynamic tabs, dialogs, the plug-in manager preferences page, and plug-in actions in menus, the command palette and Keyboard Shortcuts. |
| Document storage | `photocraft-doc` (`Document.plugin_data`), `photocraft-format` (`.pcraft` version bump), `photocraft-io` / `photocraft-psd` (PSD image resource) | L1/L3/L4 | See "Plug-in data in documents". |
| Test plug-in | `examples/process-plugin-echo` (Rust binary) | exempt | Protocol conformance and widget-gallery plug-in, used by host tests. Host CI never needs Python. |

**Why:** The engine is deliberately network-free and process-free and must compile for wasm (REQ-1.0.7), so process and transport code belongs in the app crate, as the updater and VectorCraft hand-off already do. Static registries (`cmd.rs`, `PANELS`) stay static, and dynamic plug-in content goes through one generic slot each, which keeps shared-file edits small (REQ-12.0.3).

**Alternatives considered:**
- *Putting transport in the engine*: breaks the engine's network/process-free design and the wasm build.
- *A new dock group per plug-in panel*: needs the closed `dock::Group` enum changed per plug-in, which is impossible at run time.

### Plug-in transport

**Choice:** **The child process's stdio.** The host launches the plug-in with piped stdin and stdout. Each message is a frame:

```
magic "PCPP" (4 bytes) · header length u32 LE · payload length u64 LE · JSON header (UTF-8) · payload bytes
```

- Limits: header ≤ 1 MiB, payload ≤ 512 MiB (REQ-3.0.6).
- stderr is the plug-in's log stream, captured by the host into the plug-in log file.
- The host passes a random session nonce in the launch environment. The plug-in echoes it in its `hello` frame, which proves the frames come from the process the host started (REQ-1.0.6).
- In the plug-in, the original stdout file descriptor is duplicated for frames, and `sys.stdout` is redirected to stderr, so a stray `print` can't corrupt the stream.

**Why:**
- Only the process the host launched can talk to it: there's no port to discover and no firewall prompt (REQ-1.0.6).
- It works the same on Windows, macOS and Linux with no `unsafe` and no new dependency.
- Pipe throughput (well over 1 GB/s locally) moves a 2048² RGBA image (16 MiB) in about 10–20 ms, within REQ-3.1's 150 ms budget.

**Alternatives considered:**
- *Loopback TCP with a bearer token* (the existing control-channel model): adds a listening port, token plumbing and possible firewall prompts.
- *Named pipes / Unix domain sockets* (the `interprocess` crate): platform-specific behavior and a new dependency, with no gain over stdio.
- *Shared memory for pixels*: needs `unsafe` memory mapping, which PhotoCraft forbids.

### Message encoding

**Choice:** **JSON headers through `serde_json` in Rust and the standard `json` module in Python, plus raw binary payloads.**
- Pixels travel as raw RGBA8, RGBA16 or RGBA32F rows with their stride given in the header.
- Masks travel as raw 8-bit rows.
- Icons and thumbnails travel as PNG or WebP bytes and are cached by content hash (REQ-5.0.6).
- Requests carry an `id`; responses and errors echo it; events have no `id`.
- Errors are typed: `not_found`, `invalid`, `unsupported`, `busy`, `too_large`, `internal` (REQ-2.0.6).

**Why:** JSON is debuggable, already a dependency on both sides, and fast enough for control messages. Bulk data never goes through JSON, so the base64 overhead and the 1 MiB-class limits of the control channel ([APP-002]) don't apply.

**Alternatives considered:** *MessagePack, CBOR or protobuf* add a dependency and a schema step on both sides for no measurable gain, since the payload bytes already travel raw.

### Host concurrency

**Choice:**
- **Two `std::thread`s per plug-in** (frame reader and frame writer) feed `crossbeam-channel` 0.5 queues, which are already in `Cargo.lock`.
- The UI thread drains them once per egui frame and applies document requests through `Session`.
- Pixel conversion for large reads and writes runs on PhotoCraft's existing `rayon` pool.
- The UI thread never blocks on a plug-in (REQ-5.0.5). Each request has a deadline, and missing it marks the plug-in "not responding" (REQ-5.3).
- Plug-in work never takes an engine job lock ([APP-003], REQ-11.0.2).

**Why:** This matches PhotoCraft's own update-check pattern and needs no async runtime in the engine.

**Alternatives considered:** *tokio in the app crate*. It's already a workspace dependency, but it brings nothing that two blocking pipe threads don't already do.

### Colour conversion

**Choice:** PhotoCraft's own `photocraft-cms` and `photocraft-color` convert between the document's depth, mode and ICC profile and the sRGB transfer format, using `Surface::read_region`/`write_region` (f32) and the existing 8-bit paths (REQ-3.0.4, REQ-37).

**Why:** PhotoCraft's rules forbid assuming sRGB or adding u8-only public paths, and its CMS is the oracle its own tests check against.

**Alternatives considered:** Converting in the plug-in (Qt colour management) would give results that disagree with what PhotoCraft displays.

### Plug-in data in documents

**Choice:**
- **Document blobs**: a new `Document.plugin_data: BTreeMap<String, Arc<Vec<u8>>>`, keyed `<plugin-id>/<name>`.
  - **.pcraft**: stored as its own section, with the format version bumped.
  - **PSD/PSB**: stored in one image resource in the Photoshop-reserved **plug-in resource range (ID 4000–4999)**, using ID **4242**. Its contents are a small length-prefixed container of (key, bytes) entries, named "PhotoCraft plug-in data". `photocraft-psd` already round-trips arbitrary image resources (a test writes ID 4000).
- **Layer key/value data**: the existing **layer XMP** (`layer.xmpMetadata`), using a custom namespace `https://photocraft.invalid/ns/process-plugin/1.0/` with the plug-in id as a sub-element. It already survives PSD, PSB, TIFF, `.pcraft` and duplication (REQ-8.0.2).
- **Stable layer ids**: PhotoCraft layer ids are confirmed or made stable across save and reload (REQ-2.0.2). If needed, a persisted UUID is added to the layer's XMP under the same namespace.

**Why:** These cover REQ-8, REQ-33 and [APP-012] using mechanisms PSD and PhotoCraft already preserve. The plug-in resource ID range is what Photoshop sets aside for exactly this purpose, so other PSD tools pass it through.

**Alternatives considered:**
- *Document XMP for blobs*: XMP is text, so blobs would need base64 and become ~33% larger, and there's no raw setter.
- *Sidecar files*: lost whenever the document is copied or emailed.

### Rendering widgets and vector content

**Choice:**
- **Widgets**: the PhotoCraft fork's own egui 0.37 and craft-ui widgets with `theme::Tokens`.
  - Syntax highlighting uses `TextEdit` with a custom `layouter` (`LayoutJob`) built from the highlight spans the plug-in sends.
  - Completion popups use egui `Popup`/`Area` anchored to the text cursor.
  - Thumbnails are egui textures keyed by content hash.
- **Pose vector content**: no new rendering library. `usvg`/`resvg` 0.45 are already in the tree and parse the plug-in's SVG. `design.md` decides whether pose content maps to existing shape layers or a new multi-element vector kind.

**Why:** It matches PhotoCraft's look, theming and DPI handling (REQ-5.0.5), and adds no dependency.

**Alternatives considered:** Embedding a web view or a second toolkit for plug-in panels. That's forbidden by PhotoCraft (no web view, no JavaScript) and wouldn't look native.

### Plug-in runtime: Python and Qt

**Choice:**
- **CPython 3.12**, provisioned by **uv** (pinned 0.11.x) from python-build-standalone into `<plug-in data>/runtime/` on first run, using `uv sync --frozen` against a committed `uv.lock` (REQ-13.0.1–13.0.2). The plug-in package bundles the platform's `uv` binary.
- **PyQt6 6.11.x** (GPL-3.0; bundles Qt 6.11), with `QApplication` started under `QT_QPA_PLATFORM=offscreen`. QtCore and QtNetwork run upstream's logic unchanged. QtGui provides `QImage`/`QPainter` image maths. QtWidgets exists only for the Qt mirror. No display server is needed (REQ-13.0.4, 13.2).
- **python-websockets** pinned to the commit of upstream's submodule (`624a36c`, BSD-3), installed as a normal dependency instead of a git submodule. **debugpy** is a dev dependency only.
- **Event loop**: upstream's `eventloop.py` (asyncio pumped by a 20 ms `QTimer`), unchanged. The frame reader runs on a Python thread and posts to the Qt thread through a queued signal.

**Why:**
- This is the approved "adapt the Python" route. Krita AI Diffusion already targets PyQt6 and Python ≥ 3.10.
- 3.12 matches the managed ComfyUI venv, so uv's download cache is shared.
- uv's pinned standalone Pythons make the runtime reproducible and independent of any system Python.

**Alternatives considered:**
- *Freezing with PyInstaller or Nuitka*: a large build matrix, antivirus false positives, and every update needs a rebuild per platform.
- *System Python*: version and package conflicts.
- *PySide6* (LGPL): would change upstream's imports throughout.

### The `krita` API shim

**Choice:** A Python package `photocraft_host/krita/`, put on `sys.path` ahead of everything else. It implements the subset of the `krita` module that Krita AI Diffusion uses (inventory §5, H-01 to H-72), modelled on upstream's `tests/mock/krita.py`, over the protocol.
- Synchronous Krita calls (such as `node.pixelData(...)`) become blocking request/response round trips from the Qt thread, with deadlines.
- Host change events update a local cache, so upstream's 20 ms and 500 ms polling timers read local state and cost almost nothing. The timers can stay as they are.
- `Krita.instance()`, `Extension`, `DockWidgetFactory` and actions map to plug-in registration (REQ-5, REQ-6).

**Why:** `document.py`, `layer.py` and `pose.py` stay nearly unchanged, which keeps the upstream diff small (REQ-38.0.3). Upstream's own mock shows exactly which surface is needed.

**Alternatives considered:** *Rewriting `document.py`/`layer.py` against a new API* is a bigger diff on the very files upstream changes most.

### Qt widget mirror (approved approach)

**Choice:** A generic bridge, `photocraft_host/qt_mirror/`, that:
1. Builds Krita AI Diffusion's real widgets (docker, settings dialog, server UI) offscreen with upstream's `ui/` code, almost unchanged.
2. Walks the `QWidget` tree and maps each class to a protocol widget kind:
   - `QLabel`, `QPushButton`, `QToolButton` (with menus), `QCheckBox`, `QRadioButton`, `QComboBox`;
   - `QSlider`, `QSpinBox`, `QDoubleSpinBox`, `QLineEdit`, `QTextEdit` / `QPlainTextEdit` (formats taken from `QSyntaxHighlighter`, completions from `QCompleter`);
   - `QProgressBar`, `QListWidget` (icons and context menus), `QScrollArea`, `QStackedWidget`, `QTabWidget`, `QSplitter`, `QGroupBox`, `QFrame`;
   - `QHBoxLayout`, `QVBoxLayout`, `QGridLayout`, `QFormLayout`.
3. Tracks changes with a Qt event filter (show/hide, enable, text, value, geometry and layout requests). It sends incremental tree diffs on a timer tick, batched to at most one diff per 16 ms.
4. Applies host input back through the widgets' own Qt APIs and synthetic events, so upstream's signal handlers run unchanged.
5. **Falls back** for the 8 widgets that draw themselves (`interval_slider.py`, `switch.py`, parts of `widget.py`, `live.py`, `settings.py`): they're shown as `QWidget.grab()` images with pointer and key events forwarded.
6. Intercepts `QMessageBox`, `QFileDialog` and `QInputDialog` and routes them to host dialogs and pickers (REQ-5.0.4, REQ-11).

**Why:** It's the user-approved approach. It keeps the ~10.6k-line UI layer and its behavior identical to upstream (REQ-14 to REQ-28 parity, REQ-38.2 mergeability) while PhotoCraft draws real native widgets.

**Alternatives considered:** A hand-written native UI. It was rejected because of its upstream divergence.

### Plug-in packaging, installation and updates

**Choice:**
- **Package**: one zip per platform (`windows-x64`, `macos-arm64`, `macos-x64`, `linux-x64`), containing:
  - the manifest `photocraft-plugin.toml` (id `io.github.coreyx.ai-diffusion-for-photocraft`, host API version, launch command);
  - the `uv` binary, the Python sources and `uv.lock`;
  - `LICENSE`, `NOTICE` and third-party licenses.
- **Install**: PhotoCraft's plug-in manager unpacks the zip into `<PhotoCraft config>/process-plugins/<id>/`.
- **Release**: packages are built by GitHub Actions in this repository and published as GitHub Releases with `SHA256SUMS`.
- **Updates**: the update check reads the GitHub Releases API, unauthenticated (REQ-36), and verifies the SHA-256 before installing.

**Why:** It's simple, reproducible and auditable. Because there's no frozen binary, an update is a small source zip.

**Alternatives considered:** *Bundling the full Python runtime in the zip*. That's kept as an optional "offline" package variant for later, and isn't the default because it makes every update about 100 MB.

### Managed ComfyUI and Krita AI Diffusion reuse

**Choice:** Upstream's `backend/server.py` installer is reused unchanged in its logic: uv, Python 3.12 venv, ComfyUI at commit `e9027f2b`, the pinned custom nodes, torch lock files and the `models.json` catalog. Our changes are:
- the default path `<plug-in data>/server`;
- the `extra_model_paths.yaml` section name `photocraft-ai-diffusion-managed`;
- a license field per catalog entry (REQ-29.0.4);
- a guard that disables Upgrade, Re-install and Delete for an install Krita AI Diffusion manages (REQ-31.0.5).

Detection of Krita AI Diffusion (REQ-31) is a new module, `photocraft_host/krita_reuse.py`. It reads `settings.json` and `.version` read-only and never imports upstream code that would write.

**Why:** It reaches parity with REQ-29 and REQ-30 with the smallest diff, and keeps our install separate from Krita AI Diffusion's.

**Alternatives considered:** Writing the installer in Rust inside the host. That would be AI-specific code in the host, which breaks REQ-12.0.1.

### Cloud module boundary

**Choice:** Upstream's `backend/cloud_client.py`, the cloud parts of `ui/settings.py` / `ui/server.py`, and `model/updates.py`'s Interstice calls move behind `photocraft_host/cloud.py`, a loader that imports an optional package `ai_diffusion_cloud`. The flag `PHOTOCRAFT_AI_CLOUD=1` and a manifest setting turn it on. The shipped package contains no cloud module and no Interstice strings (REQ-32).

**Why:** This keeps a clean seam for a future service of your own without shipping Interstice code.

**Alternatives considered:** Deleting the cloud code outright. That would conflict with every upstream merge that touches it.

### Testing and quality tooling

**Choice:**

| Area | Tool |
|---|---|
| Host unit, integration and snapshot tests | `cargo nextest`; `egui_kittest` snapshots for plug-in widgets; PhotoCraft's `panic_hunt` covering every new engine command; the `process-plugin-echo` test plug-in for end-to-end protocol tests |
| Host coverage | `cargo-llvm-cov` on new crates and modules, gated in our own scripts (not in PhotoCraft CI, which feature PRs may not change) |
| Plug-in tests | `pytest`, `pytest-asyncio` and `pytest-cov`; a pure-Python **mock host**, `tests/photocraft/mock_host.py`, that speaks the protocol; upstream's existing test suite run against our shim |
| Graph parity (REQ-39.0.5) | A script runs **unmodified upstream v1.54.0-pre** with its own `tests/mock/krita.py` over a fixture set, captures every `WorkflowInput` → ComfyUI prompt JSON into `tests/photocraft/fixtures/graphs/`, and our tests assert equality |
| End-to-end (REQ-39.0.6) | A real ComfyUI with small test models (the SD1.5 tiny or test checkpoints upstream's tests use), marked `@pytest.mark.gpu` and skipped without a GPU |
| Lint and types | `ruff` and `pyright` with upstream's configuration; `cargo clippy` and `rustfmt` for the host |
| CI | GitHub Actions here (lint, unit, parity and coverage on Ubuntu, Windows and macOS). The fork uses PhotoCraft's existing workflows unchanged. GPU end-to-end runs locally or on a self-hosted runner. |

**Reference machine** (REQ-3.1, 5.5, 24.1): Windows 11, an 8-core x64 CPU, 32 GB RAM and an NVIDIA RTX 3060 12 GB, or better.

**Why:** These match each side's existing conventions and the testing standards' full-tier coverage targets (REQ-12.3, REQ-39.0.4).

## Constraints & risks

- **Fork maintenance.** Upstream PhotoCraft merges dozens of PRs a day. The host series must be rebased often, and conflicts concentrate in `Document`, `.pcraft`, `cmd.rs`, the dock tables and the menus. Mitigation: keep shared-file edits surgical, rebase weekly, and offer the series upstream early. Upstream may decline it ([APP-010]), which would make the fork permanent.
- **Upstream baseline is a pre-release.** Krita AI Diffusion's newest tag is `v1.54.0-pre` (`828b70c`), which is the commit the requirements name, and there's no final `v1.54.0` tag yet. When the final tag appears, it's merged in as a normal upstream update.
- **Qt mirror complexity.** Popups, menus, focus, size policies and widgets that draw themselves are the hardest parts. Mitigation: build a gallery test early (REQ-5.1), keep the image fallback for anything the mapping doesn't cover, and measure diff traffic.
- **Runtime size and first start.** PyQt6 (~100 MB including Qt) plus CPython (~30 MB) download on first run. A first start without the network can't complete until the offline package variant exists.
- **Python start time.** Expect 1–3 s to the plug-in's `hello`. That's within REQ-1.1's 5 s, but it needs watching on slow disks.
- **macOS Gatekeeper.** A downloaded zip containing a `uv` binary gets quarantined. The plug-in manager must clear the quarantine attribute on install, or the packages must be signed and notarized. Unsigned packages will need a manual approval step.
- **Licenses.**
  - PyQt6 is GPL-3.0 and Qt is LGPL/GPL, both compatible with the GPL-3.0 plug-in.
  - python-websockets is BSD-3.
  - uv and python-build-standalone are Apache-2.0/MIT, and CPython is PSF.
  - Host additions use only dependencies already in PhotoCraft's tree.
  - Model weights carry their own licenses, which are surfaced by REQ-29.0.4.
- **Upstream node packs.** We depend on Acly's `comfyui-tooling-nodes` and `comfyui-inpaint-nodes` at upstream's pinned commits. A breaking change there arrives with each upstream merge.
- **egui fork pin.** PhotoCraft pins a `storytold/egui` fork. Our widget renderer must use only its API, so an upstream egui bump can break plug-in widgets.
- **stdout pollution.** Third-party Python code that writes to file descriptor 1 directly, below `sys.stdout`, would corrupt frames. Mitigation: duplicate the original descriptor for frames, then point descriptor 1 at stderr at startup.

Sources consulted for current versions: [PyQt6 6.11.0 (PyPI mirror)](https://simple-repository.app.cern.ch/project/PyQt6), [PyQt6 release history (piwheels)](https://www.piwheels.org/project/pyqt6/), [uv releases (pepy.tech)](https://pepy.tech/projects/uv), [uv (openmamba)](https://openmamba.org/en/rpms/base/python-uv).
