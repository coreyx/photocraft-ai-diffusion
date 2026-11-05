---
status: approved
---

# Implementation Tasks: AI Diffusion for PhotoCraft

This document defines the implementation plan as a numbered checklist. Each task is linked to one or more acceptance criteria from [`requirements.md`](./requirements.md).

**Where the work happens:**
- **Host tasks** (Milestones 2–4) are committed in the PhotoCraft fork (`coreyx/photocraft`, branch `feat/process-plugins`).
- **Plug-in tasks** are committed in this repository.
- Both carry the `Spec:`/`Task:`/`Session:` trailers.

**Testing:** every task includes its own tests:
- **Host:** `cargo nextest`, plus `egui_kittest` snapshots for UI.
- **Plug-in:** `pytest` against the mock host.

A task isn't done until its tests and the relevant existing suites pass (`cargo xtask ci` in the fork; `pytest`, `ruff` and `pyright` here).

**Deferred and not planned here:** REQ-9, REQ-26, criterion 24.4, and Graph's Generate Animation mode.

## Task List

### Milestone 1: Repositories and baselines are in place

Both repositories exist with their history, licenses and tooling, and the upstream parity fixtures are captured.

- [x] **TASK-1: Create the PhotoCraft fork and host branch**
  - **Associated Acceptance Criteria**: none (project setup)
  - **Concrete Steps**:
    1. Confirm with the user, then run `gh repo fork storytold/photocraft` under the user's account. Clone it beside this repository.
    2. Create branch `feat/process-plugins` from upstream `main` and record the base commit in `spec/ai-diffusion-for-photocraft/HOST-BASE.md`.
    3. Build and run `cargo xtask ci` on the untouched base to record the baseline pass/fail state.

- [x] **TASK-2: Merge upstream Krita AI Diffusion history and add licensing**
  - **Associated Acceptance Criteria**: `38.1`
  - **Concrete Steps**:
    1. Add remote `upstream` → `Acly/krita-ai-diffusion`. Merge tag `v1.54.0-pre` with `--allow-unrelated-histories`, keeping `ai_diffusion/` at the root.
    2. Replace the `websockets`/`debugpy` git submodules with dependencies declared in `pyproject.toml`, pinned to the submodule commits.
    3. Add `LICENSE` (GPL-3.0, upstream's), `NOTICE` (Krita AI Diffusion credit and copyright) and a README with attribution and the plug-in name.
    4. Create `UPSTREAM-CHANGES.md` listing the files design.md expects to change, all marked "pending".

- [x] **TASK-3: Set up plug-in project tooling and CI**
  - **Associated Acceptance Criteria**: `13.2`
  - **Concrete Steps**:
    1. Configure `pyproject.toml` and `uv.lock` for CPython 3.12: PyQt6 6.11.x, websockets (pinned), pytest, pytest-asyncio, pytest-cov, ruff and pyright, using upstream's lint configuration extended to `photocraft_host/`.
    2. Create the `photocraft_host/` and `tests/photocraft/` packages and a `conftest.py` that sets `QT_QPA_PLATFORM=offscreen`.
    3. Add a GitHub Actions workflow for lint, unit tests and coverage on Ubuntu, Windows and macOS, headless.
    4. Verify that upstream's own unit tests that don't need a server pass in this environment with upstream's mock.

- [x] **TASK-4: Capture graph-parity fixtures from unmodified upstream**
  - **Associated Acceptance Criteria**: `39.2`
  - **Concrete Steps**:
    1. Write `scripts/capture_parity.py`. It checks `v1.54.0-pre` out into a temporary worktree and runs `workflow.create` under upstream's own mock Krita and resource stubs.
    2. Define the fixture matrix: every in-scope workflow kind × SD1.5, SDXL, Flux, Flux 2 Klein, Z-Image and Qwen Edit × the 7 inpaint modes × region and control sets, plus upscale (simple and tiled) and custom-graph samples.
    3. Write the normalised prompt JSON to `tests/photocraft/fixtures/graphs/` along with the input descriptions.
    4. Add a node-id-normalising comparison helper and its tests.

### Milestone 2: The host runs a plug-in process safely

PhotoCraft discovers, launches, talks to and survives a test plug-in.

- [x] **TASK-5: Protocol crate**
  - **Associated Acceptance Criteria**: `1.4`, `1.8`
  - **Concrete Steps**:
    1. Create `crates/process-plugin-protocol` with `Frame`, the `Header` request/response/event types, typed params and results for every method in design.md, the widget `Node`/`Patch`/`InputEvent` types, and `PROTOCOL_VERSION`.
    2. Implement `encode`/`decode` with the magic check and size limits (header 1 MiB, payload 512 MiB). Malformed input returns typed errors and never panics.
    3. Register the crate in `xtask/src/layers.rs` at L0, with `[lints] workspace = true`.
    4. Add unit tests, a `cargo fuzz` target for the decoder, and confirm the wasm check passes.

- [x] **TASK-6: Plug-in manager: discovery, launch, handshake, shutdown**
  - **Associated Acceptance Criteria**: `1.1`, `1.2`, `1.3`, `1.5`, `1.7`
  - **Concrete Steps**:
    1. Implement `apps/photocraft/src/process_plugins.rs`:
       - manifest discovery under `<config>/process-plugins/*/photocraft-plugin.toml`;
       - compatibility checks;
       - launching with piped stdio and the nonce, data, log and locale environment variables.
    2. Add the reader and writer threads with `crossbeam-channel` queues, the `hello`/`welcome` handshake, nonce and version checks, per-request deadlines, and the 5 s ping with the "not responding" state.
    3. Handle crash, exit and broken pipe: remove the plug-in's UI, actions and preview, post a notice, and keep the document state.
    4. Implement shutdown (`shutdown`, a 5 s grace period, then kill) and stderr capture into a rotated log.
    5. Inject the manager through `Services::process_plugins`, native only, as `None` on wasm.

- [x] **TASK-7: Echo test plug-in and integration harness**
  - **Associated Acceptance Criteria**: `1.1`, `1.3`, `1.4`, `1.5`
  - **Concrete Steps**:
    1. Create `examples/process-plugin-echo`, a Rust binary. Its modes are conformance, crash-on-command, invalid-frame, oversize-frame, wrong-nonce, hang, and a widget gallery.
    2. Add host integration tests that drive the manager against each mode and assert the outcomes in criteria 1.1 and 1.3–1.5.

- [x] **TASK-8: Plug-ins preferences page and plug-in installation**
  - **Associated Acceptance Criteria**: `1.2`, `1.6`
  - **Concrete Steps**:
    1. Add an Edit › Preferences › Plug-ins section listing process plug-ins (name, version, status, compatible or not) next to the WASM plug-ins.
    2. Implement Restart, Disable, Enable and Remove without restarting PhotoCraft. The enabled state persists in preferences.
    3. Implement "Install Plug-in Package…": unzip into the plug-ins folder, validate the manifest, and clear macOS quarantine attributes.
    4. Add `tl!` strings, snapshot tests and `panic_hunt` coverage for the new commands.

### Milestone 3: Plug-ins can read and change documents

Every document capability the AI plug-in needs works through the protocol.

- [x] **TASK-9: Persistent layer ids**
  - **Associated Acceptance Criteria**: `2.2`
  - **Concrete Steps**:
    1. Add `Layer.uid: u128` to `photocraft-doc`. It's assigned at creation, and duplicating a layer gives a new uid.
    2. Persist it in `.pcraft` (with a format version bump and an updated reader and writer) and in PSD, PSB and TIFF through the layer XMP `pcpp:uid`. Missing uids get fresh ones on load.
    3. Add round-trip tests for `.pcraft`, PSD and TIFF, and run the PSD corpus regression tests.

- [x] **TASK-10: Plug-in broker: documents, layers and undo groups**
  - **Associated Acceptance Criteria**: `2.1`, `2.3`, `2.4`, `2.5`
  - **Concrete Steps**:
    1. Create `crates/engine/src/process_plugin/` with `PluginBroker`. Implement `doc.*`, `layer.*` (including `addMask` and `thumbnail`) and `undo.begin`/`undo.end` through `Session::edit` with the plug-in's labels.
    2. Return typed errors for stale documents and uids, and close any open undo group when a plug-in disconnects.
    3. Wire the broker to the manager's queues on the UI thread.
    4. Add unit tests against a test PSD, undo-revert tests, and `panic_hunt` coverage for every broker method.

- [x] **TASK-11: Pixel, selection and mask transfer with colour conversion**
  - **Associated Acceptance Criteria**: `3.1`, `3.2`, `3.3`, `3.4`, `3.5`, `3.6`
  - **Concrete Steps**:
    1. Implement `pixels.read` (layer, group, or composite with exclusions and `includePreview`), `pixels.write` and `pixels.createLayer` in the bgra8, rgba8, rgba16 and rgba32f formats.
    2. Convert through `photocraft-cms`/`photocraft-color` for every depth and mode. Unconvertible modes return `unsupported`.
    3. Implement `selection.read`, `selection.bounds` and `selection.set`, plus `mask.read` for alpha and layer masks.
    4. Add tests: bit-exact 8-bit round trips, ±1 on 16-bit, ±2/255 on CMYK, Lab and Grayscale against the display conversion, an elliptical selection, and composite exclusion.
    5. Add a benchmark on the reference machine for the 2048² read and the 1024² write (≤ 150 ms each).

- [x] **TASK-12: Change events**
  - **Associated Acceptance Criteria**: `4.1`, `4.2`, `4.3`
  - **Concrete Steps**:
    1. Implement the per-frame snapshot differ (D5): revision, layer-tree digest, selection generation, active layer, active document, and the `Arc` identity of layer content.
    2. Emit `document.*`, `layers.changed`, `pixels.changed`, `selection.changed` and `layer.activated`, coalesced to one per kind per frame, with `origin` set for changes the plug-in made itself.
    3. Implement `events.subscribe`.
    4. Add tests for a stroke, a selection change, a layer switch, a document switch, a rename and a reorder, with event latency measured at 50 ms or less.

- [x] **TASK-13: Plug-in data stored in documents**
  - **Associated Acceptance Criteria**: `8.1`, `8.2`, `8.3`, `8.4`
  - **Concrete Steps**:
    1. Add `Document.plugin_data` with `blob.get`, `blob.set`, `blob.delete` and `blob.list`, enforcing the size limit.
    2. Persist it in `.pcraft` (a new section) and in PSD/PSB image resource 4242 using the container format in design.md.
    3. Implement `layerData.get`/`layerData.set` using layer XMP `pcpp:data`.
    4. Add round-trip tests: `.pcraft`, PSD, editing with the plug-in disabled, and layer duplication.

- [x] **TASK-14: Transient preview layers**
  - **Associated Acceptance Criteria**: `7.1`, `7.2`, `7.3`
  - **Concrete Steps**:
    1. Store previews in `PluginBroker`, and composite them through the `display_memo` path with the optional hatch pattern outside a rectangle.
    2. Show a synthetic locked row in the Layers panel that refuses editing.
    3. Leave previews out of composite reads unless `includePreview` is set, and drop them on a document switch or disconnect.
    4. Add tests: no undo steps, nothing saved, edits refused, composite reads exclude the preview, plus a snapshot of the hatch.

- [x] **TASK-15: Pose vector groups**
  - **Associated Acceptance Criteria**: `10.1`, `10.2`, `10.3`, `10.4`
  - **Concrete Steps**:
    1. Implement `vector.createFromSvg`, `vector.shapes`, `vector.addSvg` and `vector.removeShapes` (D3). Parse the SVG with `usvg` and create one shape layer per circle or line inside a marked group, storing each element's id in layer data.
    2. Read geometry back from shape paths plus layer offsets.
    3. Make sure moving shapes with Move or Path Selection, and Duplicate Layer, raise `layers.changed`/`pixels.changed`.
    4. Add tests for an 18-joint, 17-bone skeleton: rendering snapshot, dragging, duplicating, and a save round trip.

- [x] **TASK-16: Host services and progress**
  - **Associated Acceptance Criteria**: `11.1`, `11.2`
  - **Concrete Steps**:
    1. Implement `notice.show`, `open.url`, `open.path`, `clipboard.get`/`clipboard.set` and the folders and locale in `welcome`, plus `locale.changed`.
    2. Implement `progress.set`/`progress.clear` in the status area with Cancel, which sends `progress.cancel`, without taking any engine job lock.
    3. Add tests per service (native platforms in CI), and a test that painting works while plug-in progress is active.

### Milestone 4: Plug-in panels, dialogs and actions render natively

A plug-in can build a full UI inside PhotoCraft, and the host series is ready to propose upstream.

- [x] **TASK-17: Widget-tree store and renderer**
  - **Associated Acceptance Criteria**: `5.1`, `5.4`, `5.5`
  - **Concrete Steps**:
    1. Implement `plugin_ui::PanelStore` (applying full trees and patches, plus the `image.put` cache by hash) and `render.rs` for every widget kind in design.md, using craft-ui widgets and `theme::Tokens`.
    2. Implement `textEdit` with highlight spans through a `LayoutJob` layouter, a completion popup anchored at the cursor, and resizable line counts.
    3. Implement `input.rs`: egui responses become `panel.input` events with modifiers. Show the optimistic local state until the plug-in confirms.
    4. Add tests: the echo plug-in's gallery mode round-trips every widget kind; snapshot tests; a 200-thumbnail list scrolling at 60 fps on the reference machine.

- [x] **TASK-18: Plug-in dock group and panel lifecycle**
  - **Associated Acceptance Criteria**: `5.2`, `5.3`
  - **Concrete Steps**:
    1. Add `dock::Group::Plugins` with dynamic tabs from registered panels, Window-menu entries, and persistence of dock and visibility state.
    2. Implement `panel.register`, `panel.patch` and `panel.unregister`, and a greyed "not responding" overlay with an input queue capped at 256 events.
    3. Add tests: dock, undock, tab, hide, restart persistence, and the hang mode of the echo plug-in.

- [x] **TASK-19: Plug-in dialogs and pickers**
  - **Associated Acceptance Criteria**: `5.1`
  - **Concrete Steps**:
    1. Implement `dialog.open`, `dialog.patch` and `dialog.close` (modal and modeless windows rendering widget trees), `dialog.message` (standard buttons) and `dialog.file` (open, save and folder with filters) through `Services::file_dialog`.
    2. Send `dialog.input`/`dialog.closed` events.
    3. Add tests for gallery dialogs and snapshots.

- [x] **TASK-20: Runtime plug-in actions**
  - **Associated Acceptance Criteria**: `6.1`, `6.2`, `6.3`
  - **Concrete Steps**:
    1. Implement `action.register`/`action.update`, and show actions in a "Plug-ins ▸ <plug-in>" menu, the command palette and Edit › Keyboard Shortcuts.
    2. Persist user-assigned shortcuts per plug-in action id, and use the existing conflict prompt.
    3. Send `action.triggered` with the active document.
    4. Add tests: 15 registered actions, triggering from the menu and from a shortcut, persistence across restarts, and a conflict.

- [x] **TASK-21: Host documentation, localization and upstream readiness**
  - **Associated Acceptance Criteria**: `12.1`, `12.2`, `12.3`, `12.4`
  - **Concrete Steps**:
    1. Write `docs/process-plugins.md`: every message type with an example, the manifest format, and the security model.
    2. Add every new host string to the `tl!` catalogs (English first; coverage reported by `cargo xtask i18n-coverage`).
    3. Run `cargo-llvm-cov` on the new crates and modules (≥ 80% line, ≥ 70% branch) and fill any gaps.
    4. Run `cargo xtask ci` green. Search the diff for AI naming, which should find none.
    5. Squash or reorder into small, self-contained commits ready to propose upstream.

### Milestone 5: Krita AI Diffusion runs inside PhotoCraft

The upstream plug-in starts in its own process, talks to the host through the shim, and its panel shows up natively.

- [x] **TASK-22: Transport client, entry point and mock host**
  - **Associated Acceptance Criteria**: `13.2`
  - **Concrete Steps**:
    1. Implement `photocraft_host/transport.py`:
       - frame codec;
       - descriptor setup (duplicate fd 1 for frames, then point fd 1 at stderr);
       - a reader thread that posts to the Qt thread;
       - blocking `call` with deadlines;
       - an event bus.
    2. Implement `photocraft_host/main.py`: logging, an offscreen `QApplication`, `hello`/`welcome`, putting the shim on `sys.path`, and `QApplication.exec()`.
    3. Implement `tests/photocraft/mock_host.py`, an in-process host speaking the protocol over pipes with an in-memory document model.
    4. Add transport unit tests (framing, deadlines, out-of-order responses) and run the headless start-up test in CI.

- [x] **TASK-23: The `krita` API shim**
  - **Associated Acceptance Criteria**: `14.2`
  - **Concrete Steps**:
    1. Implement `photocraft_host/krita/` covering inventory §5 H-01 to H-72:
       - `Krita`, `Document`, `Node`, `VectorLayer`, `Shape`, `Selection`, `Window`, `View`, `Canvas`, `Action`, `Notifier`, `Extension`;
       - `DockWidget`, `DockWidgetFactory(Base)`, `DoubleSliderSpinBox`;
       - the animation stubs (D2).
    2. Keep a local layer-tree cache per document, updated from events. Pixel and selection calls go to the host with `bgra8`. Annotations map to `blob.*`, and transparency masks map to `layer.addMask`.
    3. Run upstream's own unit tests against the shim plus the mock host, in place of upstream's mock, and fix any differences.
    4. Test switching between two documents (each keeps its own prompt and history).

- [x] **TASK-24: Upstream adaptations for PhotoCraft**
  - **Associated Acceptance Criteria**: `13.3`, `33.1`, `34.2`, `37.1`, `37.2`
  - **Concrete Steps**:
    1. Point `util.user_data_dir` at the host data folder. Accept the PhotoCraft host in the `__init__.py` version check.
    2. Relax the bit-depth check in `document.py`: show the "converted for generation" note for documents that aren't 8-bit RGB, and refuse unconvertible modes with the mode named.
    3. Fix `persistence.py` so `JobParams.from_dict` restores enum fields as enums. Make the localization default follow the host locale.
    4. Record each change in `UPSTREAM-CHANGES.md`. Add tests that write nothing under Krita AI Diffusion's data folder, cover the colour notes and refusal, round-trip persistence enums, and default the locale to Japanese.

- [x] **TASK-25: Qt mirror core**
  - **Associated Acceptance Criteria**: `14.1`
  - **Concrete Steps**:
    1. Implement `qt_mirror/mirror.py` (tree walk, node ids, mapping layouts to containers) and `tracker.py` (event filter, signal hooks, dirty set, one `panel.patch` per 16 ms).
    2. Add adapters for `QLabel`, `QPushButton`, `QToolButton`, `QCheckBox`, `QRadioButton`, `QComboBox`, `QSlider`, `QSpinBox`, `QDoubleSpinBox`, `QLineEdit`, `QProgressBar`, `QScrollArea`, `QStackedWidget`, `QTabWidget`, `QSplitter`, `QGroupBox`, `QFrame` and `DoubleSliderSpinBox`.
    3. Replay input through Qt APIs and `sendEvent`, so upstream's signal handlers run.
    4. Test each adapter's round trip against the mock host, plus a structure snapshot of the mirrored docker for each of the 4 workspaces.

- [x] **TASK-26: Qt mirror: rich widgets, menus, dialogs and image fallback**
  - **Associated Acceptance Criteria**: `21.2`, `21.3`
  - **Concrete Steps**:
    1. Add a `QTextEdit`/`QPlainTextEdit` adapter: highlight spans taken from `QSyntaxHighlighter` formats, `QCompleter` popups sent as `completions`, cursor and key events (Ctrl+Up/Down, Shift+Enter, Ctrl+Backspace), and resizing.
    2. Add a `QListWidget` adapter (icons, selection, context menus, double-click, Delete, Space) and `QMenu`/`QAction` mapping for tool-button and context menus.
    3. Add `raster.py`, the `grab()` image fallback for the 8 widgets that draw themselves, with pointer and key forwarding.
    4. Add `dialogs.py`, which routes `QMessageBox`/`QFileDialog`/`QInputDialog` to host dialogs, and mirror the settings `QDialog`.
    5. Test prompt weighting, autocomplete and the fallback widgets through the mock host.

- [x] **TASK-27: Docker, actions and workspace gating**
  - **Associated Acceptance Criteria**: `14.1`, `14.3`, `35.1`, `35.2`
  - **Concrete Steps**:
    1. Route upstream's `Extension.setup`/`createActions` and docker factory through the shim to `panel.register` and `action.register` (15 actions, no default shortcuts).
    2. Add the `ANIMATION_ENABLED = False` switch: hide the Animation workspace, skip it in Toggle Workspace, and hide Generate Animation and the Live Record button. Record these in `UPSTREAM-CHANGES.md`.
    3. Test each action, the workspace drop-down showing 4 entries, toggle cycling, and that leaving Live stops it.

### Milestone 6: Generation features match Krita AI Diffusion

Every in-scope workspace produces the same ComfyUI requests and layers as upstream.

- [x] **TASK-28: Generate, inpaint, selection and queue parity**
  - **Associated Acceptance Criteria**: `15.1`, `15.2`, `15.3`, `15.4`, `16.1`, `16.2`, `17.1`, `17.2`, `17.3`
  - **Concrete Steps**:
    1. Add parity tests that build every Generate fixture through the shim and mock host and compare against the TASK-4 graphs.
    2. Test the decision table, auto-detected expand vs fill, edit mode, mask and context outputs against upstream (±1), resolution and pass choices, seeds per batch, queue modes and cancel calls (mocked ComfyUI).
    3. Fix any difference found in the shim or the mirror, not in upstream logic.

- [x] **TASK-29: Regions and control layers**
  - **Associated Acceptance Criteria**: `18.1`, `18.2`, `18.3`, `18.4`, `19.1`, `19.2`, `19.3`, `19.4`
  - **Concrete Steps**:
    1. Persist region links on layers through the shim (layer data and uids), and test linking, re-linking into groups and removal on delete.
    2. Add graph parity tests for overlapping regions, a dominant region, and the background region.
    3. Test Create Region behavior and two-way active-region/active-layer sync.
    4. Test each control mode's label and error text, the Depth+Reference graph parity, from-image `[Control] Canny Edge`, and removal on source deletion.

- [x] **TASK-30: Pose control editing**
  - **Associated Acceptance Criteria**: `20.1`, `20.2`, `20.3`
  - **Concrete Steps**:
    1. Map the shim's `VectorLayer`/`Shape` onto `vector.*` groups (D3), so upstream `pose.py` runs unchanged.
    2. Test pose-from-image joint positions against upstream's output (±1 px), bone regeneration within 1 s after moving a joint, and Add Skeleton.

- [x] **TASK-31: Prompt features, styles and sampler presets**
  - **Associated Acceptance Criteria**: `21.1`, `21.2`, `21.3`, `21.4`, `22.1`, `22.2`, `22.3`, `22.4`
  - **Concrete Steps**:
    1. Run the prompt-processing fixture suite against upstream `text.py` outputs (comments, wildcards, LoRA, layer references, trigger words, merging).
    2. Test metadata import from PNG on document open, and translation badge behavior with a mocked translate route.
    3. Test the 20 built-in styles, saving and reloading a user style, the steps/strength maths, and hiding styles whose model is missing.

- [ ] **TASK-32: History, preview, apply and save**
  - **Associated Acceptance Criteria**: `23.1`, `23.2`, `23.3`, `23.4`, `23.5`
  - **Concrete Steps**:
    1. Route the `[Preview]` layer through `preview.show`/`preview.hide` in the shim (D4), replacing upstream's locked-layer creation with the smallest possible diff.
    2. Test each apply behavior and region behavior (with layer masks standing in for transparency masks), naming, history pruning, no undo steps from previewing, and the Save Image file naming.

- [ ] **TASK-33: Live workspace**
  - **Associated Acceptance Criteria**: `24.1`, `24.2`, `24.3`
  - **Concrete Steps**:
    1. Drive upstream's live scheduler from host `pixels.changed` events through the shim cache, and show the live preview with the hatch.
    2. Test: no job without a net input change, Apply versus Apply to New Layer, and live overhead ≤ 250 ms (instrumented, with GPU end-to-end in TASK-45).

- [ ] **TASK-34: Upscale and Graph workspaces**
  - **Associated Acceptance Criteria**: `25.1`, `25.2`, `25.3`, `27.1`, `27.2`, `27.3`, `27.4`
  - **Concrete Steps**:
    1. Map upstream's canvas resize to `doc.resizeCanvas`. Test the 2× upscale result layer, tiled graph parity, and the disabled Unblur state.
    2. Test custom workflow import (6 input node types, widget order and groups), running with canvas, selection, layer and style inputs, live re-runs only on changes, and text outputs.

- [ ] **TASK-35: Per-document persistence round trip**
  - **Associated Acceptance Criteria**: `33.1`, `33.2`
  - **Concrete Steps**:
    1. Map upstream's annotations (`document_id`, `ui.json`, `result<N>.webp`) to plug-in blobs through the shim.
    2. Test: save as `.pcraft` and PSD, close, reopen, and confirm identical state (workspace, prompts, regions, controls, seed, history within `history_storage`), plus restoring an embedded workflow.

### Milestone 7: Configuration, servers and Krita AI Diffusion reuse

The plug-in configures and connects to managed, custom and reused ComfyUI servers, with cloud mode switched off.

- [ ] **TASK-36: Settings parity and the plug-in data folder**
  - **Associated Acceptance Criteria**: `28.1`, `28.2`, `28.3`, `28.4`
  - **Concrete Steps**:
    1. Drop `last_news` and gate cloud keys in `settings.py`. Confirm the full set of keys and defaults is written on first run.
    2. Test every settings page control through the mirrored dialog: changes persist across restarts, Restore Defaults per page, and `document_defaults`.
    3. Test configuring and connecting to a custom URL with no Krita AI Diffusion present.

- [ ] **TASK-37: Managed ComfyUI server**
  - **Associated Acceptance Criteria**: `29.1`, `29.2`, `29.3`, `29.4`, `29.5`
  - **Concrete Steps**:
    1. Change the default path to `<plug-in data>/server` and the yaml section name to `photocraft-ai-diffusion-managed`.
    2. Add license name, link and restriction fields to `presets/models.json`, and show them in the Workloads and Packages tabs.
    3. Make sure the ComfyUI process ends with the plug-in on all OSes (Windows Job Object as upstream; a process group and parent-death watch on macOS and Linux).
    4. Test install state handling with a mocked downloader, Verify catching a corrupted file, upgrade keeping models and yaml edits, and process cleanup. The real CUDA install is tested end-to-end in TASK-45.

- [ ] **TASK-38: Custom server connection**
  - **Associated Acceptance Criteria**: `30.1`, `30.2`, `30.3`
  - **Concrete Steps**:
    1. Confirm upstream's `comfy_client.py` runs unchanged under the shim's event loop.
    2. Test against a stub ComfyUI server: the workload report, refusal when tooling nodes are missing (pack named), probing 8188 and 8000 in undefined mode, and reconnecting while keeping the queue.

- [ ] **TASK-39: Cloud module boundary and feature flag**
  - **Associated Acceptance Criteria**: `32.1`, `32.2`, `32.3`, `32.4`
  - **Concrete Steps**:
    1. Implement `photocraft_host/cloud.py` (flag plus import of `ai_diffusion_cloud`, otherwise the `CloudUnavailable` stub). Gate `cloud_client.py`, the cloud widgets and the Interstice update and news calls.
    2. Map a stored `server_mode: cloud` to undefined when the flag is off.
    3. Add a build check that fails on `interstice` in the package, and a stub cloud module for the flag-on test.
    4. Test: Connection-page contents, no cloud hosts in a network capture (mocked), loading a stored cloud mode, and the stub routing.

- [ ] **TASK-40: Detect Krita AI Diffusion configurations**
  - **Associated Acceptance Criteria**: `31.1`, `31.8`
  - **Concrete Steps**:
    1. Implement `krita_reuse.detect()`. It searches the per-OS, Flatpak, MSIX, fallback and portable locations, and reads `settings.json` and `.version` read-only.
    2. Add the detection section to the Connection page: version, mode, address or folder, backend, model folders, and a "Detect Krita AI Diffusion" button.
    3. Test with synthetic folder layouts for Windows (installer and portable), Linux (native and Flatpak) and macOS.

- [ ] **TASK-41: Reuse the same server, import settings, and switch away**
  - **Associated Acceptance Criteria**: `31.2`, `31.3`, `31.4`, `31.5`, `31.6`, `31.7`, `31.9`
  - **Concrete Steps**:
    1. Implement "Use the same ComfyUI server" (D10): custom mode writes `server_url`; managed mode writes `server_path` and launches or connects using upstream's code. Add the `photocraft_reuse` provenance key.
    2. Guard Krita-managed installs (Upgrade, Re-install and Delete disabled, with an explanation) and validate on connect (moved, deleted or version changed). Offer the "own server sharing models" and "continue with features disabled" fallbacks.
    3. Implement Import settings (styles, presets, tags, workflows), excluding secrets unless a separate confirmation is accepted. Clear provenance when switching servers.
    4. Test: connecting with no install or download, unchanged install folder hashes (apart from ComfyUI runtime output), the secret exclusion, the notice for a renamed folder, the shared-models install downloading no existing models, and switching to another URL then removing the Krita AI Diffusion folder.

### Milestone 8: Packaged, localized and release-ready

The plug-in installs from a release package, updates itself, and passes the full quality bar.

- [ ] **TASK-42: Packaging and first-run provisioning**
  - **Associated Acceptance Criteria**: `13.1`
  - **Concrete Steps**:
    1. Write `packaging/build.py`, which produces per-platform zips: the manifest (`io.github.coreyx.ai-diffusion-for-photocraft`), the `uv` binary, sources, `uv.lock` and licenses.
    2. Implement first-run provisioning (`uv python install 3.12`, then `uv sync --frozen` into `<plug-in data>/runtime/`) with progress in the panel. The manifest launch command runs a small bootstrap.
    3. Add a GitHub Actions release workflow that builds the packages and publishes `SHA256SUMS`.
    4. On a clean VM with PhotoCraft from the fork: install the package, start PhotoCraft, and confirm the panel shows the Connection setup.

- [ ] **TASK-43: Updates and diagnostics**
  - **Associated Acceptance Criteria**: `36.1`, `36.2`, `36.3`
  - **Concrete Steps**:
    1. Point `model/updates.py` at the GitHub Releases API. Download and Install verifies SHA-256, installs, then restarts the plug-in through the host.
    2. Extend diagnostics redaction to the plug-in data paths, home paths, the nonce and tokens. Confirm rotated client and server logs.
    3. Test: a newer release detected (mocked API), a tampered package rejected, and diagnostics free of secrets.

- [ ] **TASK-44: Localization and naming**
  - **Associated Acceptance Criteria**: `34.1`, `34.2`, `38.3`
  - **Concrete Steps**:
    1. Adapt Krita-specific strings to PhotoCraft in the English source and all 14 catalogs, keeping nominative uses ("Import from Krita AI Diffusion"). Set the plug-in name to "AI Diffusion for PhotoCraft".
    2. Test the panel and settings in each language, and the host-locale default.
    3. Add a string audit test that allows "Krita" only in import, detection and attribution contexts.

- [ ] **TASK-45: Coverage, secret and network audits, and the end-to-end suite**
  - **Associated Acceptance Criteria**: `39.1`, `39.3`, `39.4`, `39.5`
  - **Concrete Steps**:
    1. Enforce coverage in CI: ≥ 80% line and ≥ 70% branch overall, and ≥ 90% for `photocraft_host/krita`, the persistence mapping and `krita_reuse`.
    2. Write `@pytest.mark.gpu` end-to-end tests against a real ComfyUI with small models: generate, inpaint, live, upscale, a custom graph, control from image, and Krita AI Diffusion reuse. Include a CUDA managed install for criterion 29.1.
    3. Add audits that scan logs for secret values and check a network capture against the allow-list.
    4. Run the end-to-end suite on Windows and Linux with a GPU, and record the results in the walkthrough.

- [ ] **TASK-46: Upstream merge rehearsal**
  - **Associated Acceptance Criteria**: `38.2`
  - **Concrete Steps**:
    1. Verify that `UPSTREAM-CHANGES.md` lists exactly the upstream files changed (scripted diff against `v1.54.0-pre`).
    2. Do a trial merge of the newest upstream tag, or `main`, in a throwaway branch. Confirm conflicts appear only in listed files, and write down the merge procedure in `docs/upstream-merge.md`.
