---
status: approved
---

# Requirements Specification: AI Diffusion for PhotoCraft

## 1. Project Summary

**AI Diffusion for PhotoCraft** brings the full feature set of Krita AI Diffusion v1.54.0 into PhotoCraft, the open-source Rust image editor. Users get generation, refinement, inpainting, live painting, upscaling, animation, regional prompts, control layers and custom ComfyUI graphs in a docked panel, driven by a local or remote ComfyUI server, and it should behave the same way Krita AI Diffusion does in Krita.

The work has two parts with deliberately separate licenses:

1. **A generic process plug-in host for PhotoCraft (MIT OR Apache-2.0).** It lives in a PhotoCraft fork and is written so it can be offered upstream. It lets an out-of-process plug-in read and write the document, receive change events, show a docked panel and dialogs that PhotoCraft draws, register actions, and store data in the document. None of it is specific to AI.
2. **The AI Diffusion plug-in (GPL-3.0).** It adapts Krita AI Diffusion's Python code with as small a diff as possible. The Krita API layer is replaced by a shim over the host protocol, and the Qt widget UI is replaced by panel descriptions that PhotoCraft renders. Keeping the diff small means later Krita AI Diffusion releases can be merged in.

The plug-in keeps **its own configuration**, at parity with Krita AI Diffusion's: every settings page, including Connection with managed-local and custom-server modes. It works without Krita installed. It differs from Krita AI Diffusion in only these places:

- the Interstice online service is off behind a feature flag (REQ-32);
- it can detect an existing Krita AI Diffusion configuration and use the same ComfyUI server and models (REQ-31);
- non-8-bit and non-RGB documents are converted at the boundary instead of refused (REQ-37);
- updates are checked against this project's own release feed instead of Interstice (REQ-36).

The parity baseline is Krita AI Diffusion **v1.54.0** (commit `828b70c`). The host baseline is PhotoCraft at commit `5617e00` or later.

**Out of scope**:
- the PhotoCraft web (WebAssembly) build;
- importing Krita `.kra` files;
- the Interstice cloud service itself;
- FreeBSD support for the managed server installer;
- new AI features that Krita AI Diffusion v1.54.0 does not have.

**Terms**:
- **Host**: PhotoCraft, with the process plug-in host added.
- **Plug-in**: AI Diffusion for PhotoCraft, running as a separate process.
- **Inventory §x**: a section of the Krita AI Diffusion inventory linked below. It is the authoritative description of the behavior these requirements call "parity".
- **Parity**: the same inputs, defaults, options, labels, ComfyUI requests and resulting layers as Krita AI Diffusion v1.54.0. The only allowed differences are the ones this document names, plus mechanical renaming (Krita → PhotoCraft, plug-in name).

**Related documents**
- [App findings](../../analysis/ai-diffusion-for-photocraft/app-findings.md)
- [Krita AI Diffusion inventory](../../analysis/ai-diffusion-for-photocraft/reference/krita-ai-diffusion-inventory.md)
- [PhotoCraft host analysis](../../analysis/ai-diffusion-for-photocraft/reference/photocraft-host-analysis.md)

## 2. Requirements (EARS Format)

Requirements use the Easy Approach to Requirements Syntax (EARS):
- **Ubiquitous**: The system shall <response>.
- **Event-Driven**: When <trigger>, the system shall <response>.
- **State-Driven**: While <precondition>, the system shall <response>.
- **Unwanted Behavior**: If <unwanted condition>, then the system shall <response>.
- **Optional Feature**: Where <feature is enabled>, the system shall <response>.

---

**Part A: PhotoCraft process plug-in host (MIT OR Apache-2.0).** REQ-1 to REQ-12.

### REQ-1: Process plug-in discovery and lifecycle

**User Story**: As a PhotoCraft user, I want to install a plug-in that runs as its own program and have PhotoCraft start, connect to and stop it, so that rich plug-ins work without risking PhotoCraft's stability.

**Source**: new, not present in any findings. Motivated by [APP-001], [APP-002] and [APP-011].

- **1.0.1 (Ubiquitous)**: The host shall discover process plug-ins from a manifest file in a plug-ins folder. The manifest declares the plug-in's id, name, version, required host API version, launch command and license.
- **1.0.2 (Event-Driven)**: When PhotoCraft starts and an enabled process plug-in is installed, the host shall launch it, authenticate the connection, and negotiate the protocol version before exchanging any document data.
- **1.0.3 (Unwanted Behavior)**: If a plug-in process exits, crashes, stops responding, or sends a malformed or oversized message, then the host shall disconnect it, remove its UI, tell the user, and keep running. The user's documents and undo history must be unaffected.
- **1.0.4 (Event-Driven)**: When the user asks to restart, disable or remove a process plug-in, the host shall do so without restarting PhotoCraft.
- **1.0.5 (Event-Driven)**: When PhotoCraft quits, the host shall ask each plug-in to shut down, wait a bounded time, and then terminate it.
- **1.0.6 (Ubiquitous)**: The host shall accept plug-in connections only from processes it launched itself, over a local channel that no other machine can reach.
- **1.0.7 (Ubiquitous)**: Process plug-ins shall be supported on Windows, macOS and Linux desktop builds. Builds without process-plug-in support (web) shall still compile, with the feature absent.

#### Acceptance Criteria
- **1.1**: A plug-in folder with a valid manifest appears in the plug-in list, and its process starts within 5 s of PhotoCraft becoming ready.
- **1.2**: A manifest that requires an unsupported host API version is listed as incompatible and is not launched.
- **1.3**: Killing the plug-in process while a document is open shows a notice, removes the plug-in's panel and actions, and leaves the document and undo history intact. PhotoCraft does not crash.
- **1.4**: A plug-in that sends invalid frames or exceeds the message size limit is disconnected, and the event is logged.
- **1.5**: A connection attempt without the launch token is refused.
- **1.6**: Restart, disable and enable each take effect without restarting PhotoCraft.
- **1.7**: On quit, the plug-in process is gone within 10 s.
- **1.8**: `cargo check --target wasm32-unknown-unknown` passes for the host crates.

### REQ-2: Document and layer tree access

**User Story**: As a plug-in author, I want to read and change the open documents and their layer trees, so that the plug-in can create and manage the layers it works with.

**Source**: reverse-engineered from app-findings.md, Krita host surface [APP-009], inventory §5.2–§5.3.

- **2.0.1 (Ubiquitous)**: The host shall expose the open documents, the active document, and each document's id, file path, width, height, resolution, bit depth, colour mode and colour profile.
- **2.0.2 (Ubiquitous)**: The host shall expose each document's layer tree. Each layer reports a stable id, name, kind (pixel, group, vector/shape, text, smart object, adjustment, mask), parent, child order, visibility, lock state, opacity, blend mode and bounds. A layer's id must stay the same across save and reload.
- **2.0.3 (Ubiquitous)**: The host shall let a plug-in create pixel layers and groups, and rename, move, re-parent, show, hide, lock, unlock and delete them. It shall also let a plug-in add a layer mask to a layer and set the active layer.
- **2.0.4 (Ubiquitous)**: Each document-changing request from a plug-in shall be one undoable step with a plug-in-supplied label. A plug-in shall also be able to group several requests into one undo step.
- **2.0.5 (Event-Driven)**: When a plug-in requests a canvas resize, the host shall resize the document canvas. The upscale workflow depends on this.
- **2.0.6 (Unwanted Behavior)**: If a request names a document or layer that no longer exists, then the host shall reject it with a typed error and change nothing.

#### Acceptance Criteria
- **2.1**: Listing the layer tree of a test PSD returns every layer with the correct parent, order, kind and bounds.
- **2.2**: A layer created by a plug-in keeps the same id after the document is saved as `.pcraft` and reopened.
- **2.3**: Each create, rename, move, group, hide, lock and delete request shows up in the Layers panel, and Edit › Undo reverts it in one step.
- **2.4**: Three requests sent as one undo group are reverted by a single Undo.
- **2.5**: A request naming a deleted layer returns a typed "not found" error, and the document is unchanged.

### REQ-3: Pixel and mask transfer

**User Story**: As a plug-in author, I want to read layer, group and composite pixels and the selection mask, and to write pixels into layers, quickly and with correct colour, so that images can go to and from a generation server.

**Source**: reverse-engineered from app-findings.md [APP-002], [APP-007], [APP-009] and inventory §5.4–§5.5. Bit-depth conversion is new (approved preliminary plan).

- **3.0.1 (Ubiquitous)**: The host shall return pixels for a rectangle of a single layer, a group's composite, or the document composite (with chosen layers excluded) as 8-bit straight-alpha RGBA in sRGB. 16-bit and 32-bit float are also available on request.
- **3.0.2 (Ubiquitous)**: The host shall return the current selection as an 8-bit coverage mask for a rectangle, along with the selection's bounds, or report that there is no selection.
- **3.0.3 (Ubiquitous)**: The host shall write supplied pixels into a rectangle of a pixel layer, and shall create a pixel layer from supplied pixels at a given offset.
- **3.0.4 (Ubiquitous)**: The host shall convert between the document's bit depth, colour mode and ICC profile and the transfer format on every read and write, using its own colour engine.
- **3.0.5 (Ubiquitous)**: The host shall read a layer's alpha, or a layer mask, as a coverage mask.
- **3.0.6 (Ubiquitous)**: Pixel data shall travel over a bulk channel that does not base64-encode inside JSON, and has no 1 MiB-class limit.

#### Acceptance Criteria
- **3.1**: Reading a 2048×2048 composite and writing a 1024×1024 layer each take ≤ 150 ms of host and transport overhead on the reference machine defined in `tech.md`.
- **3.2**: An 8-bit sRGB round trip (read, then write back unchanged) is bit-exact.
- **3.3**: On a 16-bit RGB document, a read gives 8-bit sRGB values within ±1 of the reference conversion. A write produces 16-bit layer data whose display matches within ±1/255.
- **3.4**: On CMYK, Lab and Grayscale documents, a read gives sRGB pixels that match the host's own soft-proof or display conversion within ±2/255.
- **3.5**: An elliptical selection read as a mask matches the host's selection coverage exactly, and with no selection the host reports "none".
- **3.6**: Excluding a layer from a composite read gives the same result as hiding that layer and reading.

### REQ-4: Change events

**User Story**: As a plug-in author, I want to be told when the user changes the document, layers, selection, active layer, active document or current frame, so that the plug-in can react (for example, in live painting) without polling.

**Source**: derived from app-findings.md (Krita AI Diffusion polls every 20–500 ms, inventory §5.9). The push model is new.

- **4.0.1 (Event-Driven)**: When a document's pixels, layer tree, layer properties, selection, active layer, active document or current animation frame changes, the host shall send a change event to each subscribed plug-in. The event names the document and what kind of change it was, and includes a monotonically increasing revision.
- **4.0.2 (Ubiquitous)**: The host shall coalesce events so that a burst of changes, such as a brush stroke, produces at most one event per kind per display frame.
- **4.0.3 (Event-Driven)**: When a document is opened, closed, saved or renamed, the host shall send a matching lifecycle event.

#### Acceptance Criteria
- **4.1**: Painting one stroke produces at least one pixels-changed event within 50 ms of the stroke ending, and no more than one per frame while the stroke is in progress.
- **4.2**: Each of the following produces the matching event within 50 ms: changing the selection, switching the active layer, switching documents, scrubbing the timeline, renaming a layer, and reordering layers.
- **4.3**: Changes made by the plug-in itself raise events tagged with the plug-in as their origin.

### REQ-5: Plug-in panels and dialogs drawn by the host

**User Story**: As a plug-in author, I want to describe a docked panel and dialogs as a widget tree that PhotoCraft draws natively, so that the plug-in's UI looks and behaves like part of PhotoCraft.

**Source**: new. It is needed because PhotoCraft panels are a static table [APP-011] and Krita AI Diffusion's UI is Qt widgets (inventory §2).

- **5.0.1 (Ubiquitous)**: The host shall let a plug-in register one or more dockable panels, each listed in the Window menu, and draw each one from a widget tree the plug-in supplies and updates incrementally.
- **5.0.2 (Ubiquitous)**: The widget vocabulary shall be enough to reproduce every widget in inventory §2:
  - layout: rows, columns, grids, groups, collapsible sections, tabs, stacked pages, scroll areas, splitters;
  - labels with rich text, links and icons;
  - buttons, including tool, toggle and split buttons with drop-down menus;
  - check boxes, switches and radio groups;
  - combo boxes with icons, separators and sub-headers;
  - integer and float sliders paired with spin boxes;
  - single-line and multi-line text editors with syntax-highlight spans, a resizable height, and an inline completion popup;
  - progress bars;
  - image views, and thumbnail grids or lists with selection, overlays, context menus and drag reordering;
  - tooltips, popups and anchored menus;
  - a list of rows whose items are themselves widget trees (regions, control layers);
  - a file or folder path field with a picker.
- **5.0.3 (Event-Driven)**: When the user interacts with a plug-in widget, the host shall send the interaction to the plug-in: the value, click, key (including modifiers), selection, context-menu choice, drag or text cursor.
- **5.0.4 (Ubiquitous)**: The host shall let a plug-in open modal and non-modal dialogs, including a multi-page settings dialog, message boxes with standard buttons, and file and folder pickers.
- **5.0.5 (Ubiquitous)**: Plug-in UI shall use PhotoCraft's theme tokens, fonts and DPI scaling. It shall stay responsive while the plug-in is busy: no host frame waits for a plug-in reply.
- **5.0.6 (Ubiquitous)**: Plug-in-supplied icons (SVG or PNG) and images shall be cached by the host and referred to by id after the first transfer.

#### Acceptance Criteria
- **5.1**: A test plug-in that uses every widget kind in 5.0.2 renders with the PhotoCraft theme and round-trips each kind of interaction.
- **5.2**: A plug-in panel can be docked, undocked, tabbed and hidden from the Window menu, and its layout persists across restarts.
- **5.3**: A plug-in that stops responding for 10 s does not freeze the host UI, and its panel shows a "not responding" state.
- **5.4**: The multi-line editor shows highlight spans, an inline completion popup driven by plug-in suggestions, and a draggable height.
- **5.5**: A thumbnail list with 200 images scrolls at 60 fps on the reference machine.

### REQ-6: Plug-in actions, menus and shortcuts

**User Story**: As a user, I want the plug-in's actions in PhotoCraft's menus, the command palette and the keyboard shortcuts editor, so that I can trigger them like built-in commands.

**Source**: reverse-engineered from inventory §2.9 (Krita actions). The runtime registration is new [APP-011].

- **6.0.1 (Ubiquitous)**: The host shall let a plug-in register actions at run time, each with an id, label, optional icon and optional default shortcut. Registered actions appear in a plug-in submenu, the command palette and Edit › Keyboard Shortcuts.
- **6.0.2 (Event-Driven)**: When the user triggers a plug-in action, the host shall send it to the plug-in along with the active document.
- **6.0.3 (Ubiquitous)**: Shortcuts the user assigns to plug-in actions shall persist across restarts, and conflicts shall be reported the same way as for built-in commands.
- **6.0.4 (Ubiquitous)**: The host shall let a plug-in enable, disable, check and uncheck its actions.

#### Acceptance Criteria
- **6.1**: Fifteen registered actions appear in the plug-in submenu and in Keyboard Shortcuts, and each one, triggered from either place, reaches the plug-in.
- **6.2**: A shortcut assigned to a plug-in action works after restarting PhotoCraft.
- **6.3**: Assigning a shortcut that is already in use produces the standard conflict prompt.

### REQ-7: Transient preview layers

**User Story**: As a user, I want to preview a generated result on the canvas without it entering my undo history or my saved file, so that I can browse results freely.

**Source**: reverse-engineered from inventory §1.6 (the `[Preview]` locked layer). Keeping it out of undo and the saved file is new.

- **7.0.1 (Ubiquitous)**: The host shall let a plug-in show, update and remove a transient preview layer at a given position in the layer stack. It is displayed and composited like a locked pixel layer, labelled in the Layers panel, but is not recorded in undo history, not saved, and not editable by the user.
- **7.0.2 (Ubiquitous)**: The host shall let a plug-in draw the preview with an optional hatch pattern multiplied outside a given rectangle. This is used for live painting.
- **7.0.3 (Ubiquitous)**: Transient preview layers shall be excluded from composite reads unless the plug-in explicitly asks for them.

#### Acceptance Criteria
- **7.1**: Showing, updating and removing a preview adds no undo steps, and the saved file contains no preview layer.
- **7.2**: The preview shows in the Layers panel as locked, and painting on it is refused.
- **7.3**: A composite read with default options does not include the preview.

### REQ-8: Plug-in data stored in documents

**User Story**: As a user, I want the plug-in's per-document state (prompts, regions, history, settings) saved inside my document, so that reopening it restores my AI work.

**Source**: reverse-engineered from app-findings.md [APP-012] and inventory §6.10.

- **8.0.1 (Ubiquitous)**: The host shall let a plug-in store named binary blobs in a document, under a namespace for that plug-in. The blobs are saved in `.pcraft` and kept when the document is saved as PSD or PSB.
- **8.0.2 (Ubiquitous)**: The host shall let a plug-in store small key/value data on individual layers, which is kept on save, reload and layer duplication.
- **8.0.3 (Unwanted Behavior)**: If a blob exceeds the configured size limit (default 256 MiB per document), then the host shall refuse it with a typed error.
- **8.0.4 (Ubiquitous)**: Saving or loading a document with plug-in data shall work whether or not the plug-in is installed. Data shall never be dropped silently.

#### Acceptance Criteria
- **8.1**: Blobs written by a plug-in are byte-identical after a save and reopen as `.pcraft`.
- **8.2**: Blobs are also byte-identical after a save and reopen as PSD.
- **8.3**: Opening, editing and saving such a document with the plug-in disabled keeps the blobs.
- **8.4**: Layer key/value data survives saving, reopening and duplicating the layer.

### REQ-9: Animation and timeline access

**User Story**: As a plug-in author, I want to read the timeline and an animated layer's frames and to create animated layers from frames, so that animation generation works.

**Source**: reverse-engineered from inventory §1.1.4 and §5.7. The mapping onto PhotoCraft's frame model is an open question in app-findings.md.

- **9.0.1 (Ubiquitous)**: The host shall expose a document's timeline: whether it exists, fps, current frame, playback range and frame count.
- **9.0.2 (Ubiquitous)**: The host shall report which frames of a layer hold distinct content (keyframes), read a layer's pixels at a given frame, and write pixels into a layer at a given frame.
- **9.0.3 (Ubiquitous)**: The host shall create an animated layer from an ordered list of frames placed at given frame numbers.
- **9.0.4 (Event-Driven)**: When the current frame changes, the host shall send a frame-changed event (REQ-4).

#### Acceptance Criteria
- **9.1**: On a document with a 24-frame animated layer, the keyframe list and per-frame pixel reads match what the timeline shows.
- **9.2**: Importing 10 frames at frames 0–9 creates one animated layer that plays back those frames.
- **9.3**: Writing pixels at frame 5 changes only frame 5.

### REQ-10: Editable pose vector content

**User Story**: As a user, I want to see an OpenPose skeleton on the canvas and drag its joints with PhotoCraft's tools, so that pose control works as it does in Krita.

**Source**: reverse-engineered from inventory §1.3 (pose vector layers). The host representation is new (app-findings.md, open question).

- **10.0.1 (Ubiquitous)**: The host shall let a plug-in create a vector layer from SVG made of circles and lines, with element ids, stroke colours, stroke widths and opacities. The layer shall display those elements.
- **10.0.2 (Ubiquitous)**: The user shall be able to select and move the individual elements of such a layer, and duplicate them, with PhotoCraft's existing selection tools.
- **10.0.3 (Ubiquitous)**: The host shall let a plug-in read back the layer's elements with their ids and current geometry, and replace or add elements.
- **10.0.4 (Event-Driven)**: When the user moves or duplicates an element of such a layer, the host shall send a layer-changed event (REQ-4).

#### Acceptance Criteria
- **10.1**: An 18-joint, 17-bone SVG skeleton renders with the right colours and opacity.
- **10.2**: Dragging a joint changes its coordinates when read back and raises a change event.
- **10.3**: Duplicating a joint gives a new element with a distinct id, and reading back returns both.
- **10.4**: The layer and its element ids survive saving and reopening.

### REQ-11: Host services for plug-ins

**User Story**: As a plug-in author, I want standard services from the host (notices, file dialogs, URLs, clipboard, locale, data folders), so that the plug-in integrates without platform-specific code.

**Source**: reverse-engineered from inventory §5.11–§5.12 and §2.10.

- **11.0.1 (Ubiquitous)**: The host shall give plug-ins:
  - notices;
  - file and folder open/save pickers with filters;
  - opening a URL or folder in the system browser or file manager;
  - clipboard text read and write;
  - the UI language and its changes;
  - the host version;
  - a per-plug-in data folder and a log folder.
- **11.0.2 (Ubiquitous)**: The host shall show plug-in progress (fraction plus message) in its status area, with a Cancel button that sends a cancel request to the plug-in. Plug-in progress shall not lock any document [APP-003].

#### Acceptance Criteria
- **11.1**: Each service, called from a test plug-in, behaves the same as for built-in features on Windows, macOS and Linux.
- **11.2**: While plug-in progress is shown, the user can keep painting on the same document.

### REQ-12: Host code quality and upstream compatibility

**User Story**: As the maintainer of the PhotoCraft fork, I want the host changes to meet PhotoCraft's own rules, so that they can be proposed upstream and rebased easily.

**Source**: derived from app-findings.md (governance) [APP-004], [APP-010].

- **12.0.1 (Ubiquitous)**: All host changes shall be MIT OR Apache-2.0, written without reference to Krita AI Diffusion source, and free of AI-specific code or naming.
- **12.0.2 (Ubiquitous)**: Host changes shall pass PhotoCraft's `cargo xtask ci`:
  - formatting, clippy with its no-panic lints, and the layer check;
  - tests, `panic_hunt` fuzzing of every new command, and the wasm check;
  - no `unsafe` outside the crates that already allow it;
  - git dependencies only from `storytold`.
- **12.0.3 (Ubiquitous)**: Host changes shall be organized as a series of small, focused commits, each of which builds and passes tests on its own, with minimal edits to shared files.
- **12.0.4 (Ubiquitous)**: Every new host message and command shall be documented in a `docs/process-plugins.md` page in the PhotoCraft fork.

#### Acceptance Criteria
- **12.1**: `cargo xtask ci` passes on the fork branch.
- **12.2**: Searching the host diff for "diffusion", "comfy", "krita" or "stable" finds nothing outside test fixtures that name an example plug-in.
- **12.3**: New host code meets PhotoCraft's coverage bar: 80% line coverage and 70% branch coverage on new crates and modules, measured with the tool named in `tech.md`.
- **12.4**: `docs/process-plugins.md` documents every message type with an example.

---

**Part B: AI Diffusion for PhotoCraft (GPL-3.0).** REQ-13 to REQ-39.

### REQ-13: Plug-in packaging, runtime and identity

**User Story**: As a user, I want to install AI Diffusion for PhotoCraft as one plug-in package that sets up its own runtime, so that I don't have to install Python by hand.

**Source**: new. It follows from the approved choice to adapt the Python code.

- **13.0.1 (Ubiquitous)**: The plug-in shall ship as a process-plug-in package (REQ-1) for Windows x64, macOS (arm64 and x64) and Linux x64. It shall run its code under an isolated Python runtime with headless PyQt6 (QtCore, QtGui, QtNetwork) that it provides itself.
- **13.0.2 (Event-Driven)**: When the plug-in starts for the first time, it shall provision its runtime if needed, showing progress in its panel, and then open its panel.
- **13.0.3 (Ubiquitous)**: The plug-in shall present itself as "AI Diffusion for PhotoCraft". Its data shall live in its own folder (the host-provided data folder, REQ-11), separate from Krita AI Diffusion's.
- **13.0.4 (Ubiquitous)**: The plug-in shall not need Krita, Qt widgets or a display server.

#### Acceptance Criteria
- **13.1**: On a clean machine with PhotoCraft installed, installing the package and starting PhotoCraft ends with the plug-in panel visible and showing the Connection setup screen.
- **13.2**: The plug-in runs on a headless Linux CI runner (no display) against a mock host.
- **13.3**: No file is written in Krita AI Diffusion's data folder during install or normal use.

### REQ-14: Docker panel and workspaces

**User Story**: As a user, I want one AI panel with the same five workspaces as Krita AI Diffusion, so that my workflow carries over.

**Source**: reverse-engineered from inventory §1.1 and §2.1–§2.2.

- **14.0.1 (Ubiquitous)**: The plug-in panel shall provide the Generate, Upscale, Live, Animation and Graph workspaces. Each has the controls, defaults and labels listed in inventory §1.1 and §2.2, selected through a workspace drop-down.
- **14.0.2 (State-Driven)**: While the plug-in has no connection, the panel shall show the connection status and a button that opens Settings › Connection.
- **14.0.3 (Event-Driven)**: When the user leaves the Live workspace, live generation shall stop.
- **14.0.4 (Ubiquitous)**: Each document shall keep its own workspace, prompts, regions, control layers, queue and history. Switching documents switches the panel to that document's state.

#### Acceptance Criteria
- **14.1**: The workspace drop-down lists exactly Generate, Upscale, Live, Animation and Graph, and each one shows the controls in the inventory.
- **14.2**: With two documents open, each keeps its own prompt and history when switching between them.
- **14.3**: Switching from Live to Generate stops live generation within one cycle.

### REQ-15: Generate workspace operations

**User Story**: As a user, I want Generate to choose generate, refine, inpaint, refine-region or edit from my selection and strength, so that one button does the right thing.

**Source**: reverse-engineered from inventory §1.1.1 and §1.7.

- **15.0.1 (Ubiquitous)**: The plug-in shall pick the workflow kind and button label from strength, selection, the region-only toggle, edit mode and the model architecture, exactly as in inventory §1.1.1.
- **15.0.2 (Ubiquitous)**: The plug-in shall provide:
  - the 7 inpaint modes, auto-detecting expand vs fill;
  - the 7 fill modes and 4 context modes;
  - the custom inpaint options (Seamless, Focus, Edit, Fill, Context);
  - the per-state Generate drop-down menus;
  - Ctrl+Click on Generate to replace the queue.

  All behave as in inventory §1.7.
- **15.0.3 (Ubiquitous)**: The plug-in shall support edit-capable models: linked edit styles, edit mode with its own prompt, synthesized edit instructions, reference-latent merging, and Qwen Layered output as N layers (inventory §1.1.1).
- **15.0.4 (Ubiquitous)**: The strength slider shall work as in inventory §1.1.1: 1–100% in steps of 5, step-aligned snapping, and an optional steps suffix.

#### Acceptance Criteria
- **15.1**: For each row of the inventory §1.1.1 decision table, the button label and the submitted workflow kind match Krita AI Diffusion.
- **15.2**: For a fixed seed, style and set of inputs, the ComfyUI prompt graph the plug-in submits for each inpaint mode is identical to the one Krita AI Diffusion v1.54.0 builds. This is checked by a graph-equality test fixture.
- **15.3**: A selection that touches the canvas edge auto-detects Expand. An interior selection auto-detects Fill.
- **15.4**: Edit mode with a Flux Kontext style submits an edit graph that carries the synthesized instruction.

### REQ-16: Selection and mask processing

**User Story**: As a user, I want selections turned into inpaint masks with the same feathering, padding and blending, so that inpainted results blend as they do in Krita.

**Source**: reverse-engineered from inventory §1.7 (selection processing) and §2.11.

- **16.0.1 (Ubiquitous)**: The plug-in shall derive the denoise and composite masks from the selection using `selection_feather`, `selection_min_transition`, `selection_grow_offset`, `selection_blend` and `selection_padding`, scaled by strength, with the minimum sizes and architecture-multiple snapping in inventory §1.7.
- **16.0.2 (Ubiquitous)**: The plug-in shall ignore a selection that covers the whole document.
- **16.0.3 (Ubiquitous)**: The plug-in shall compute the context area for inpainting as in inventory §1.7.

#### Acceptance Criteria
- **16.1**: For a set of test selections, the denoise mask, composite mask and context rectangle match Krita AI Diffusion's output within ±1 per pixel.
- **16.2**: A select-all selection produces a generate or refine workflow, not an inpaint.

### REQ-17: Resolution, batches, seeds, queue and progress

**User Story**: As a user, I want the same resolution handling, batching, seeds, queue modes and progress reporting, so that results and throughput match.

**Source**: reverse-engineered from inventory §1.8.

- **17.0.1 (Ubiquitous)**: The plug-in shall handle resolution as in inventory §1.8: per-architecture ranges, two-pass for large canvases, downscale for small ones, preferred-resolution override, `resolution_multiplier` and `max_pixel_count`.
- **17.0.2 (Ubiquitous)**: The plug-in shall provide batch count (1–10), batch size (1–16) with reduction at large resolutions, fixed or random 32-bit seeds with seed + i × batch_size per job, the three queue modes, and the three cancel actions.
- **17.0.3 (Ubiquitous)**: The queue button shall show its inactive, waiting, active and upload states and the job counts. The progress bar shall tell generation apart from upload. Errors shall show in an error box with a copy button and the error kinds in inventory §1.8, cloud-only kinds excepted.

#### Acceptance Criteria
- **17.1**: For canvases of 512², 1024², 3000×2000 and 6000², the chosen working resolution and passes match Krita AI Diffusion.
- **17.2**: Batch count 3 with batch size 4 and a fixed seed S submits 3 jobs with seeds S, S+4 and S+8.
- **17.3**: Each queue mode and cancel action gives the documented queue state, and the server receives the matching interrupt or delete calls.

### REQ-18: Regions

**User Story**: As a user, I want regional prompts linked to layers and groups, so that different parts of the image get different prompts.

**Source**: reverse-engineered from inventory §1.2.

- **18.0.1 (Ubiquitous)**: The plug-in shall provide a root prompt and regions, each with its own prompt and control layers. Regions link to pixel layers or groups following the linking rules in inventory §1.2, and the region links persist on the layers (REQ-8).
- **18.0.2 (Ubiquitous)**: Region coverage, top-down subtraction, thresholds and the background region shall be computed as in inventory §1.2 (`process_regions`).
- **18.0.3 (Ubiquitous)**: The plug-in shall provide:
  - Create Region (link the active layer, or create a group `Region <n>` holding `Paint layer`; in Live, a layer `Region <n>`);
  - two-way sync between the active region and the active layer;
  - region-only generation and refinement;
  - region hierarchies;
  - per-region control layers;
  - per-region translation;
  - Segmentation from regions.
- **18.0.4 (Event-Driven)**: When a linked layer is moved into a group, the plug-in shall re-link the region to that group. When a linked layer is deleted, it shall remove the link.

#### Acceptance Criteria
- **18.1**: For a fixture document with 3 overlapping regions, the region masks and prompts in the submitted graph match Krita AI Diffusion.
- **18.2**: A region covering more than 90% collapses to a single prompt. Total coverage under 95% adds a background region.
- **18.3**: Create Region on an unlinked layer links it. On a linked layer, it creates `Region <n>` with `Paint layer`.
- **18.4**: Selecting a region activates its layer, and activating a linked layer selects its region.

### REQ-19: Control layers

**User Story**: As a user, I want the 17 control modes with presets and from-image generation, so that I can guide composition, pose, style and structure.

**Source**: reverse-engineered from inventory §1.3.

- **19.0.1 (Ubiquitous)**: The plug-in shall provide the 15 user-selectable control modes and the 2 internal modes in inventory §1.3, with labels, IP-Adapter or ControlNet families, per-architecture support checks and error texts.
- **19.0.2 (Ubiquitous)**: Each control layer shall have a layer picker, mode, a 5-step preset slider driven by `presets/control.json` (merged with user overrides), custom strength 0–1.5 and a start/end range. Defaults are as in inventory §1.3.
- **19.0.3 (Event-Driven)**: When the user runs "from image" for a mode that has a preprocessor, the plug-in shall run the preprocessor workflow and add the result as `[Control] <Mode>` (inverted to black lines on white for line modes), then point the control layer at it.
- **19.0.4 (Event-Driven)**: When the underlying layer is deleted, the plug-in shall remove the control layer.
- **19.0.5 (Ubiquitous)**: Control layers that are not "part of image" shall be excluded from the canvas capture.

#### Acceptance Criteria
- **19.1**: Each of the 15 modes appears with its label. An unsupported mode or architecture shows the inventory's error text.
- **19.2**: For a fixture with Depth and Reference control layers, the submitted graph matches Krita AI Diffusion.
- **19.3**: "From image" for Canny creates `[Control] Canny Edge` with black lines on white and re-points the control layer.
- **19.4**: Deleting the control's source layer removes the control layer from the panel.

### REQ-20: Pose control editing

**User Story**: As a user, I want pose detection to give me an editable skeleton that I can adjust before generating, so that I can direct poses.

**Source**: reverse-engineered from inventory §1.3 (pose vector layers). Depends on REQ-10.

- **20.0.1 (Event-Driven)**: When "from image" runs in Pose mode, the plug-in shall create a pose vector layer (REQ-10) from the OpenPose result, with confidence above 0.1, scaled to the canvas, and using the 18-joint, 17-bone model, palette and stroke scaling in inventory §1.3.
- **20.0.2 (Event-Driven)**: When the user moves joints, the plug-in shall regenerate the affected bones. When joints are duplicated, it shall start a new person index.
- **20.0.3 (Ubiquitous)**: The plug-in shall provide "Add Skeleton", enabled only when the control layer's layer is a pose vector layer.
- **20.0.4 (Ubiquitous)**: Generation shall rasterize the pose layer as the control image.

#### Acceptance Criteria
- **20.1**: Pose detection on a fixture photo gives a vector layer whose joint positions match Krita AI Diffusion's within 1 px.
- **20.2**: Dragging a joint re-draws the attached bones within 1 s.
- **20.3**: Add Skeleton inserts a default person scaled to the canvas.

### REQ-21: Prompt features

**User Story**: As a user, I want the same prompt syntax, highlighting, autocomplete and translation, so that my existing prompts work unchanged.

**Source**: reverse-engineered from inventory §1.5.

- **21.0.1 (Ubiquitous)**: The plug-in shall process prompts in the order and with the syntax given in inventory §1.5:
  - comments;
  - wildcards seeded per job;
  - `<lora:name[:strength]>`;
  - `<layer:Name>` references, with architecture-specific tokens;
  - LoRA trigger words;
  - edit instructions;
  - the empty-prompt substitution;
  - style prompt merging, with `{prompt}`;
  - negative prompt merging, dropped when CFG ≈ 1.
- **21.0.2 (Ubiquitous)**: Prompt editors shall provide:
  - syntax highlighting (comments, weights, `lora` and `layer` keywords, wildcards);
  - Ctrl+Up and Ctrl+Down weight adjustment by ±0.1, clamped to [-2, 2];
  - Shift+Enter to generate;
  - Ctrl+Backspace to delete a word;
  - a resizable line count, persisted and capped at 40;
  - the placeholder texts in inventory §1.5.
- **21.0.3 (Ubiquitous)**: Autocomplete shall offer LoRA names after `<lora:` (inserting trigger words too), image layer names after `<layer:`, and tag completions from the enabled tag CSV files, using the matching, ordering, colours and key handling in inventory §1.5.
- **21.0.4 (Where)**: Where `prompt_translation` is set, the plug-in shall show the language badge, toggle per-document translation on click, translate in place on Ctrl+Click through `api/etn/translate`, and wrap prompts with `lang:` directives at generation time.
- **21.0.5 (Event-Driven)**: When the user opens a PNG, JPEG or WebP file whose document prompts are empty, the plug-in shall fill the prompts from A1111 "parameters" or ComfyUI "prompt" metadata.
- **21.0.6 (Where)**: Where `save_image_metadata` is enabled, saved images shall embed A1111-style parameters.

#### Acceptance Criteria
- **21.1**: A prompt-processing fixture suite (comments, nested wildcards, LoRA strength, layer references, trigger words, `{prompt}` merge) produces the same text and LoRA list as Krita AI Diffusion's `text.py`.
- **21.2**: Ctrl+Up on `(cat:1.2)` gives `(cat:1.3)`. On plain `cat` it gives `(cat:1.1)`.
- **21.3**: Typing `<lora:` lists the server's LoRAs. Typing `blu` with the Danbooru tags enabled lists "blue" tags sorted by count.
- **21.4**: Opening a PNG with A1111 parameters fills the positive and negative prompts.

### REQ-22: Styles and sampler presets

**User Story**: As a user, I want the built-in styles, a style editor and sampler presets, so that I can pick and tune models the same way.

**Source**: reverse-engineered from inventory §1.4 and §2.7 (Styles page).

- **22.0.1 (Ubiquitous)**: The plug-in shall ship the 20 built-in styles and 15 sampler presets in inventory §1.4, read-only, with built-in style ids `built-in/<file>.json`.
- **22.0.2 (Ubiquitous)**: The plug-in shall load user styles from `<plug-in data>/styles/**/*.json` and user sampler presets from `<plug-in data>/presets/samplers.json`, with the format, validation, fallbacks and legacy mapping in inventory §1.4.
- **22.0.3 (Ubiquitous)**: The Styles settings page shall provide every field and control in inventory §2.7, including create, duplicate, delete, refresh and open-folder, the LoRA list with upload and advanced metadata, and both sampler sections with "Edit custom presets".
- **22.0.4 (Ubiquitous)**: The style drop-down shall show recent styles (`recent_styles_count`), honour `show_builtin_styles`, and hide styles whose model the server doesn't have.
- **22.0.5 (Ubiquitous)**: Steps and strength shall interact as in inventory §1.4: start_step, minimum_steps and the CFG fallback.

#### Acceptance Criteria
- **22.1**: All 20 built-in styles load with the values in the inventory table.
- **22.2**: A user style created in the editor is saved as JSON in the user styles folder and reloads unchanged.
- **22.3**: Strength 0.2 with a 20-step preset whose minimum is 4 gives the step count and start step Krita AI Diffusion uses.
- **22.4**: A style whose checkpoint is missing on the server is hidden from the drop-down.

### REQ-23: Results, history, preview and apply

**User Story**: As a user, I want to browse results, preview them on the canvas, and apply them as layers with the same naming and region behavior, so that the results workflow is unchanged.

**Source**: reverse-engineered from inventory §1.6. Preview via REQ-7.

- **23.0.1 (Ubiquitous)**: The plug-in shall keep a per-document job history:
  - job states queued, executing, finished and cancelled;
  - pruning above `history_size` MB;
  - thumbnails with seed and prompt;
  - a star on applied results;
  - discard (confirmed if `confirm_discard_image` is on);
  - clear history;
  - copy prompt (restoring Graph parameters);
  - copy seed (which also sets a fixed seed);
  - the Delete, Space and double-click bindings.
- **23.0.2 (Event-Driven)**: When the user selects a history image, the plug-in shall preview it as a transient `[Preview] <prompt ≤77 chars>` layer at the top of the stack (REQ-7), and shall remove the preview when it is deselected.
- **23.0.3 (Event-Driven)**: When a job finishes, the plug-in shall act according to `generation_finished_action`: none, preview or apply.
- **23.0.4 (Event-Driven)**: When the user applies a result, the plug-in shall create or replace layers according to `apply_behavior` and `apply_region_behavior`. Layer names follow inventory §1.6, and in the transparency-mask behavior a layer mask stands in for Krita's transparency mask.
- **23.0.5 (Event-Driven)**: When the user saves a result image, the plug-in shall composite it over the canvas and save it next to the document, using `save_image_file_name_format` and the chosen format and quality. The command is disabled until the document has been saved.

#### Acceptance Criteria
- **23.1**: Applying with each `apply_behavior` value gives the documented layer result and names.
- **23.2**: Applying with each `apply_region_behavior` value on a 2-region fixture gives the layer structure in inventory §1.6.
- **23.3**: Previewing and un-previewing 10 results adds no undo steps.
- **23.4**: History stays under the `history_size` limit by dropping the oldest results.
- **23.5**: Save Image writes a file named from the template, in the chosen format.

### REQ-24: Live painting

**User Story**: As a user, I want results to regenerate continuously as I paint, so that I can steer the image interactively.

**Source**: reverse-engineered from inventory §1.1.2. Change detection uses REQ-4.

- **24.0.1 (Ubiquitous)**: The Live workspace shall provide:
  - play and pause;
  - its own strength (default 0.3);
  - a fixed seed with randomize;
  - an edit toggle;
  - style;
  - slim region and root prompts;
  - add region and control layer;
  - a preview with a busy overlay;
  - Apply and Apply to New Layer;
  - recording.
- **24.0.2 (State-Driven)**: While live generation is active and its document is the active one, the plug-in shall rebuild the workflow input whenever the document changes. When the input differs from the last one, it shall schedule a job using the grace-period rules in inventory §1.1.2.
- **24.0.3 (Ubiquitous)**: Live jobs shall use the style's live sampler preset and its auto-injected LoRA, batch size 1, and live region padding. The result is shown with the hatch pattern outside the generated area (REQ-7).
- **24.0.4 (Event-Driven)**: When recording, the plug-in shall write `frame-<n>.webp` files into `<document>.live-frames/` next to the saved document. When recording stops, it shall import them as an animated layer `[Rec] <start>-<end>: <prompt>` (REQ-9). Recording requires a saved document.
- **24.0.5 (Unwanted Behavior)**: If a live job fails, then the plug-in shall stop live mode and show the error.

#### Acceptance Criteria
- **24.1**: With an SD1.5 or SDXL live style on the reference GPU, a stroke ends with a refreshed preview within the generation time plus ≤ 250 ms of plug-in and host overhead.
- **24.2**: Painting with no net change to the input (for example, undoing a stroke right away) schedules no new job.
- **24.3**: Apply copies the live result into the active layer. Apply to New Layer creates a new layer.
- **24.4**: Recording 5 results and stopping creates a `[Rec]` animated layer with 5 frames.

### REQ-25: Upscale workspace

**User Story**: As a user, I want simple and diffusion-refined tiled upscaling, so that I can enlarge images with detail.

**Source**: reverse-engineered from inventory §1.1.3.

- **25.0.1 (Ubiquitous)**: The Upscale workspace shall provide the parameters, defaults, ranges, upscaler names and order, and disabled states in inventory §1.1.3.
- **25.0.2 (Event-Driven)**: When the user starts an upscale, the plug-in shall resize the canvas to extent × factor straight away (REQ-2). It shall submit `upscale_simple` without diffusion or `upscale_tiled` with it, using the tile-size rules, default prompts and per-tile region prompts in inventory §1.1.3. The result is added as `[Upscale] <W×H> (<seed>)`.
- **25.0.3 (Ubiquitous)**: At factor 1.0 with diffusion on, the button label shall be "Refine" and no upscale model shall be used.

#### Acceptance Criteria
- **25.1**: A 2× upscale of a 1024² canvas resizes it to 2048² and adds an `[Upscale] 2048x2048 (<seed>)` layer.
- **25.2**: For a fixture, the tiled upscale graph (tile size, overlap, unblur ControlNet) matches Krita AI Diffusion.
- **25.3**: With no Unblur ControlNet installed, Image guidance is disabled and shows the tooltip.

### REQ-26: Animation workspace

**User Story**: As a user, I want to generate a full animation or a single frame, so that I can make animated pieces.

**Source**: reverse-engineered from inventory §1.1.4. Uses REQ-9.

- **26.0.1 (Ubiquitous)**: The Animation workspace shall provide sampling quality (Fast or Quality), Full Animation or Single Frame mode, a target layer for Single Frame mode, the root prompt and negative prompt, strength and control layers.
- **26.0.2 (Event-Driven)**: When Full Animation runs, the plug-in shall enqueue one job per keyframe (or per frame at strength 1) over the playback range. It samples control layers and region masks at each frame, saves `frame-<n>.png` into `<document>.animation/`, reuses identical frames, and imports the result as `[Generated] <start>-<end>: <prompt>`. A saved document is required, and at strength below 1 the active layer must be animated.
- **26.0.3 (Event-Driven)**: When Single Frame runs, the plug-in shall write the result into the target layer at the current frame. If the frame changed in the meantime, it shall report an error.

#### Acceptance Criteria
- **26.1**: Full Animation over an 8-frame range with 4 keyframes at strength 0.6 submits 4 jobs and imports an animated layer with the matching frames.
- **26.2**: Single Frame writes only the current frame of the target layer.
- **26.3**: Starting Full Animation on an unsaved document shows the documented error.

### REQ-27: Graph (custom ComfyUI workflow) workspace

**User Story**: As a user, I want to run my own ComfyUI workflows with parameters shown in the panel and canvas inputs and outputs wired in, so that I can use any graph from PhotoCraft.

**Source**: reverse-engineered from inventory §1.1.5.

- **27.0.1 (Ubiquitous)**: The plug-in shall list workflows from local files (`<plug-in data>/workflows/`), remote workflows published from the ComfyUI web UI, and workflows embedded in the document. They are sorted and labelled as in inventory §1.1.5, with import, save-as, overwrite and delete, and their confirmations.
- **27.0.2 (Ubiquitous)**: The plug-in shall support the node types in inventory §1.1.5: `ETN_KritaCanvas`, `ETN_KritaSelection`, `ETN_Parameter`, `ETN_KritaImageLayer`, `ETN_KritaMaskLayer`, `ETN_KritaStyle`, `ETN_KritaStyleAndPrompt`, the Krita Output node and Send Text. These are the node pack's own class names and are used as they are.
- **27.0.3 (Ubiquitous)**: The plug-in shall build parameter widgets for every parameter kind, with grouping and ordering by name prefix, per-group and global reset, duplicate-name validation, and values stored per workflow.
- **27.0.4 (Ubiquitous)**: The plug-in shall provide the Generate, Generate Live and Generate Animation modes. It shall map outputs (offset, name, batch mode, resize canvas, and text outputs as labels or rich text) as in inventory §1.1.5.
- **27.0.5 (Event-Driven)**: When the user clicks Open Web UI, the plug-in shall open the server URL in the browser and auto-select the next remote workflow published within 5 minutes.

#### Acceptance Criteria
- **27.1**: Importing a fixture workflow with all 6 input node types gives the expected widgets, groups and order.
- **27.2**: Running it sends the canvas, selection, layer and style inputs, and applying it creates layers named from the output node.
- **27.3**: Generate Live re-runs only when an input changes.
- **27.4**: A text output under 40 characters shows as a label, and a Markdown output renders as rich text.

### REQ-28: Settings and configuration

**User Story**: As a user, I want my own complete settings for the plug-in, the same as Krita AI Diffusion's (Connection included), so that I can configure everything independently of Krita.

**Source**: reverse-engineered from inventory §2.7 and §2.11. The user asked for full configuration parity independent of Krita.

- **28.0.1 (Ubiquitous)**: The plug-in shall keep its settings in `<plug-in data>/settings.json`, with every key, type and default in inventory §2.11. The exceptions are cloud-only keys, which are kept only while the cloud module is enabled (REQ-32), and `last_news`, which is removed.
- **28.0.2 (Ubiquitous)**: The settings dialog ("Configure Image Diffusion") shall have the Connection, Styles, Diffusion, Interface, Performance and Plugin pages, with every control in inventory §2.7, plus "Restore Defaults", the version label and "Open Settings folder".
- **28.0.3 (Ubiquitous)**: The Connection page shall offer Local Managed Server (REQ-29) and Custom Server (REQ-30), set up and stored independently of Krita AI Diffusion. It shall also offer the Krita AI Diffusion detection and reuse options (REQ-31), and Online Service only where the cloud module is enabled (REQ-32).
- **28.0.4 (Ubiquitous)**: The Performance presets (Automatic, CPU, GPU low/medium/high, Custom) shall apply the values in inventory §2.11 and show device information.
- **28.0.5 (Event-Driven)**: When the user changes `language`, the plug-in shall apply it after a restart, as Krita AI Diffusion does.
- **28.0.6 (Ubiquitous)**: The plug-in shall remember recent per-document defaults (`document_defaults`) and apply them to new documents.

#### Acceptance Criteria
- **28.1**: A fresh install writes `settings.json` with exactly the documented keys and defaults (cloud keys absent while the cloud module is disabled).
- **28.2**: Every control on every settings page changes its key, and the change survives a restart.
- **28.3**: Restore Defaults resets all keys on the current page.
- **28.4**: With no Krita AI Diffusion configuration present, a user can configure and connect to a custom ComfyUI URL entirely from the Connection page.

### REQ-29: Managed local ComfyUI server

**User Story**: As a user without ComfyUI, I want the plug-in to install, update, launch and manage a local ComfyUI with the right nodes and models, so that I can start generating without manual setup.

**Source**: reverse-engineered from inventory §2.8 and §3.E–§3.F. Model license display is new (inventory §7.1).

- **29.0.1 (Ubiquitous)**: The managed server UI shall provide:
  - the install location (default `<plug-in data>/server`, needs ≥ 16 GB);
  - the GPU backend, filtered by OS;
  - Install, Upgrade, Launch and Stop;
  - Manage › Verify (sha256), Re-install and Delete, with their confirmations;
  - status and progress;
  - View log files;
  - the "No CUDA Devices Found" warning;
  - the Workloads and Individual Packages tabs, with the model ratings and groupings in inventory §2.8.
- **29.0.2 (Event-Driven)**: When the user installs, the plug-in shall install `uv`, a Python 3.12 venv, ComfyUI at the pinned commit, the required and optional custom nodes at their pinned commits, the backend's torch from the matching lock file, and the selected models from the catalog, with sha256 checks. It shall write its own `extra_model_paths.yaml` section, named for this plug-in rather than "krita-managed".
- **29.0.3 (Event-Driven)**: When the managed server is launched, the plug-in shall start ComfyUI with the backend flags and `server_arguments`, detect readiness from stdout, connect, and make sure the server process ends when PhotoCraft or the plug-in exits.
- **29.0.4 (Ubiquitous)**: Before downloading a model, the installer shall show the model's license name and link. Models with non-commercial or restricted licenses shall be marked.
- **29.0.5 (Unwanted Behavior)**: If a download fails or a checksum doesn't match, then the plug-in shall mark the install incomplete, keep what downloaded correctly, and offer to retry.

#### Acceptance Criteria
- **29.1**: On Windows with an NVIDIA GPU, a CUDA install of the SDXL workload finishes, launches, connects, and generates an image.
- **29.2**: Verify finds a deliberately corrupted model file and offers to re-download it.
- **29.3**: Killing PhotoCraft also ends the ComfyUI process on Windows, macOS and Linux.
- **29.4**: The workload list shows each model's license, and FLUX.1-dev-based entries are marked non-commercial.
- **29.5**: Upgrading from a previous plug-in version's install keeps the models and the user's `extra_model_paths.yaml` edits.

### REQ-30: Custom (external) ComfyUI server

**User Story**: As a user who already runs ComfyUI, I want to connect the plug-in to my server by URL, so that I can use my own setup.

**Source**: reverse-engineered from inventory §2.7 (Connection) and §3.A.

- **30.0.1 (Ubiquitous)**: The Custom Server page shall provide the URL field, Connect, status, View log files, and the report of supported workloads, missing nodes and missing models.
- **30.0.2 (Ubiquitous)**: The plug-in shall talk to ComfyUI using the endpoints, websocket messages, image transfer routes, `server_authorization` header, version checks (minimum 0.3.45) and reconnect behavior in inventory §3.A.
- **30.0.3 (State-Driven)**: While `server_mode` is undefined, the plug-in shall probe `127.0.0.1:8188` and `127.0.0.1:8000` and save whichever answers.
- **30.0.4 (Unwanted Behavior)**: If required nodes or models are missing and `check_server_resources` is on, then the plug-in shall refuse to connect and list what is missing, with download hints.

#### Acceptance Criteria
- **30.1**: Connecting to a stock ComfyUI with the required node packs reports the supported workloads correctly.
- **30.2**: Connecting to a ComfyUI that lacks `comfyui-tooling-nodes` refuses with that pack named.
- **30.3**: A server that drops the websocket is reconnected automatically and keeps the queue.

### REQ-31: Detect and reuse an existing Krita AI Diffusion configuration

**User Story**: As a user who already set up Krita AI Diffusion, I want the plug-in to find that configuration and use the same ComfyUI server and models, so that I don't have to install or download anything again.

**Source**: new, a user requirement. Grounded in [APP-005] and [APP-006] and inventory §4.

Krita AI Diffusion is configured with a ComfyUI server on the same machine in one of two ways. In **managed** mode, it installed ComfyUI itself into a folder (`server_path`) and starts it when needed. In **custom** mode, the user points it at a ComfyUI they run themselves (`server_url`). Either way the server is an ordinary ComfyUI instance with a model folder. This requirement lets our plug-in read that configuration and connect to, or start, the same server.

- **31.0.1 (Event-Driven)**: When the plug-in starts, and when the user clicks "Detect Krita AI Diffusion", the plug-in shall look for a Krita AI Diffusion configuration, read-only. It checks the per-OS `<krita appdata>/ai_diffusion` folders, the Flatpak and MSIX variants and the `krita-ai-diffusion` fallback folders, and reads `settings.json` (`server_mode`, `server_path`, `server_url`, `server_backend`, `server_arguments`) and, for managed mode, `<server_path>/.version`.
- **31.0.2 (State-Driven)**: While a configuration is detected, the Connection page shall show its server mode, the server address or install folder, its backend, its version and the model folders found. It shall offer **Use the same ComfyUI server** as the primary choice, and also **Import settings**.
- **31.0.3 (Event-Driven)**: When the user chooses Use the same ComfyUI server for a **custom-mode** configuration, the plug-in shall store that `server_url` as its own custom-server URL and connect to it (REQ-30).
- **31.0.4 (Event-Driven)**: When the user chooses Use the same ComfyUI server for a **managed-mode** configuration, the plug-in shall record that install folder as its server. It shall connect if the server is already running. Otherwise it shall start it with the same backend flags and arguments, in the same way the managed server is started (REQ-29.0.3). No second ComfyUI is installed and no models are downloaded.
- **31.0.5 (Ubiquitous)**: The plug-in shall not upgrade, re-install, repair or delete a ComfyUI install that Krita AI Diffusion manages. Krita AI Diffusion records the version it installed in `.version` and keeps that install in step with its own release. If our plug-in changed it, the two would disagree. The Upgrade, Re-install and Delete controls are therefore disabled for such an install, with a note saying why.
- **31.0.6 (Unwanted Behavior)**: If the reused server lacks a node or model version our plug-in needs, then the plug-in shall say what is missing and offer two alternatives. One is to set up its own managed server (REQ-29) that uses the same model folders through its `extra_model_paths.yaml`, so models are still not downloaded again. The other is to keep the connection anyway, with the missing features disabled.
- **31.0.7 (Event-Driven)**: When the user chooses Import settings, the plug-in shall copy the non-secret settings, user styles, sampler and control presets, tag files and saved workflows into its own data folder.
- **31.0.8 (Unwanted Behavior)**: If a reused configuration includes `server_authorization` or `access_token`, then the plug-in shall use or copy them only after a separate confirmation, and shall never log them.
- **31.0.9 (Unwanted Behavior)**: If the reused install folder or server address disappears, moves or changes version, then the plug-in shall detect it on the next connect, tell the user, and offer to detect again or to set up its own server.
- **31.0.10 (Ubiquitous)**: Model presence on a reused server shall be checked online (`/object_info` and `/api/etn/model_info`), so models reached through `extra_model_paths.yaml` count [APP-006].
- **31.0.11 (Ubiquitous)**: Reuse shall be optional and never locked in. The user can switch at any time to any other ComfyUI server by URL (REQ-30) or to the plug-in's own managed server (REQ-29). After that, the plug-in's configuration no longer depends on Krita AI Diffusion.

#### Acceptance Criteria
- **31.1**: On a machine where Krita AI Diffusion uses a managed install at its default path, the Connection page shows that install with the right backend, version and model folders.
- **31.2**: Choosing Use the same ComfyUI server for that managed install connects (starting the server if it isn't running) and generates an image, with no install step and no model download.
- **31.3**: With a custom-mode configuration, choosing Use the same ComfyUI server sets our custom URL to the same `server_url` and connects.
- **31.4**: After using a managed install that way, the only changes in its folder are ComfyUI's own runtime output (logs, temp, output, user and cache folders). `.version`, the venv, the custom nodes and the models are unchanged.
- **31.5**: Import settings copies styles, presets and workflows. `server_authorization` and `access_token` are not used or copied unless the separate confirmation was accepted.
- **31.6**: Renaming the reused install folder produces a clear notice on the next connect, not a crash.
- **31.7**: Choosing "own managed server sharing the same models" installs ComfyUI but downloads no model file that already exists in the reused model folders.
- **31.8**: Detection finds configurations in a portable Windows Krita layout and a Linux Flatpak layout, using synthetic test folders.
- **31.9**: After reusing a detected configuration, the user enters a different ComfyUI URL, connects, and generates. Removing Krita AI Diffusion afterwards doesn't affect that connection.

### REQ-32: Cloud module feature flag

**User Story**: As the product owner, I want the online-service mode excluded by default but structurally kept, so that a future cloud service can be added without reworking the plug-in.

**Source**: derived from app-findings.md [APP-008]. The user decided this after analysis.

- **32.0.1 (Ubiquitous)**: All cloud-service code paths shall sit behind one cloud module boundary. The plug-in shall work fully without that module.
- **32.0.2 (Unwanted Behavior)**: If the cloud feature flag is off, or the cloud module is absent, then the plug-in shall hide Online Service from the Connection page and initial setup, hide cloud-only settings and error kinds, treat a stored `server_mode: cloud` as undefined, and send no request to any cloud endpoint.
- **32.0.3 (Optional Feature)**: Where the cloud flag is on and a cloud module is present, the plug-in shall show Online Service, using the endpoint and branding that module supplies.
- **32.0.4 (Ubiquitous)**: The plug-in package shall ship without Interstice endpoints, branding or sign-in flow.

#### Acceptance Criteria
- **32.1**: With the flag off, the Connection page shows only Managed and Custom (plus Krita reuse). A network capture during startup and generation shows no request to a cloud host.
- **32.2**: A `settings.json` holding `"server_mode": "cloud"` loads as undefined, without an error.
- **32.3**: The shipped package contains no `interstice` string.
- **32.4**: With the flag on and a stub cloud module present, Online Service appears and routes to the stub.

### REQ-33: Per-document persistence

**User Story**: As a user, I want my prompts, regions, control layers, workspace settings, history and embedded workflows saved with the document, so that reopening it restores everything.

**Source**: reverse-engineered from inventory §6.10 and [APP-012]. Storage via REQ-8.

- **33.0.1 (Event-Driven)**: When a document is saved, the plug-in shall store:
  - its document id;
  - the persisted model properties (workspace, style, strength, region_only, edit_mode, batch_count, seed, fixed_seed, resolution_multiplier, queue_mode, translation_enabled, layer_count);
  - regions, control layers and workspace sub-model state;
  - the embedded custom workflow;
  - up to `history_storage` MB of history images in `history_format`.

  All of it is stored as document blobs (REQ-8), and region and control links go on layers.
- **33.0.2 (Event-Driven)**: When a document holding that data is opened, the plug-in shall restore it, with enum fields restored as enums, which fixes Krita AI Diffusion's string defect.

#### Acceptance Criteria
- **33.1**: After a save, close and reopen, the workspace, prompts, regions, control layers, seed and history (within `history_storage`) are identical.
- **33.2**: An embedded workflow shows as "Embedded Workflow (<doc name>)" after reopening when it isn't otherwise known.

### REQ-34: Localization

**User Story**: As a user who doesn't read English, I want the plug-in in my language, so that I can use it comfortably.

**Source**: reverse-engineered from inventory §6.11.

- **34.0.1 (Ubiquitous)**: The plug-in shall ship the 14 UI languages Krita AI Diffusion v1.54.0 ships, using its translation catalogs and English fallback. Krita-specific strings shall be adapted to PhotoCraft.
- **34.0.2 (Ubiquitous)**: When `language` is not set explicitly, the plug-in shall default to the host's UI language if it is one of the 14, and to English otherwise.
- **34.0.3 (Ubiquitous)**: Host-side strings added for process plug-ins (Part A) shall go into PhotoCraft's own `tl!` catalogs.

#### Acceptance Criteria
- **34.1**: Switching to each of the 14 languages and restarting shows translated panel and settings text.
- **34.2**: With PhotoCraft set to Japanese and no explicit plug-in language, the plug-in starts in Japanese.

### REQ-35: Actions and keyboard bindings

**User Story**: As a user, I want the same actions and keyboard bindings, so that my muscle memory carries over.

**Source**: reverse-engineered from inventory §2.9. Registered through REQ-6.

- **35.0.1 (Ubiquitous)**: The plug-in shall register the 15 actions in inventory §2.9, with the same ids (prefix `ai_diffusion_`), labels and behaviors, and no default shortcuts.
- **35.0.2 (Ubiquitous)**: The in-panel bindings in inventory §2.9 shall behave as documented: Shift+Enter, Ctrl+Up and Ctrl+Down, Ctrl+Backspace, the autocomplete keys, Ctrl+Click on Generate, Ctrl+Click on the language badge, Delete, Space, double-click, and Enter on the workflow name.

#### Acceptance Criteria
- **35.1**: Each of the 15 actions, given a shortcut, does what the inventory describes.
- **35.2**: Toggle Workspace cycles through all 5 workspaces in order, Animation included.

### REQ-36: Plug-in information, updates and diagnostics

**User Story**: As a user, I want to see the plug-in version, check for updates, and collect diagnostics, so that I can stay current and report problems.

**Source**: reverse-engineered from inventory §2.7 (Plugin page). Checking updates against this project's own feed is new [APP-008].

- **36.0.1 (Ubiquitous)**: The Plugin page shall show the current and latest version, "Check for updates on startup" (`auto_update`), Check for Updates, Download and Install, Collect Diagnostics (copied to the clipboard and shown in a window), View log files, and documentation and support links for this project.
- **36.0.2 (Ubiquitous)**: Update checks shall use this project's GitHub Releases. Download and Install shall verify the package checksum before installing, and shall then restart the plug-in process (REQ-1).
- **36.0.3 (Ubiquitous)**: Diagnostics and logs shall redact user home paths, `server_authorization` and `access_token`.
- **36.0.4 (Ubiquitous)**: Logs shall rotate, at 10 MB with 4 backups for both the client and server logs.

#### Acceptance Criteria
- **36.1**: With a newer release published, Check for Updates shows it, and Download and Install installs it and restarts the plug-in.
- **36.2**: A tampered update package fails checksum verification and is not installed.
- **36.3**: Collected diagnostics contain no home path or token values.

### REQ-37: Colour and bit-depth handling

**User Story**: As a PhotoCraft user working in 16-bit, 32-bit or non-RGB documents, I want AI generation to work there too, so that I'm not forced to convert my document.

**Source**: new, an approved deviation from [APP-007].

- **37.0.1 (Ubiquitous)**: The plug-in shall accept documents of any bit depth and colour mode the host supports, and exchange pixels as 8-bit sRGB RGBA through the host conversion (REQ-3).
- **37.0.2 (State-Driven)**: While the active document is not 8-bit RGB, the panel shall show a subtle note that images are converted for generation.
- **37.0.3 (Unwanted Behavior)**: If the document's mode can't be converted (for example Bitmap, Indexed or Multichannel), then the plug-in shall refuse to generate, with a message naming the mode.

#### Acceptance Criteria
- **37.1**: Generating on a 16-bit RGB, an 8-bit CMYK and a 32-bit Lab document applies a result layer that looks correct in each.
- **37.2**: A Bitmap-mode document shows the refusal message.

### REQ-38: Licensing, attribution and upstream mergeability

**User Story**: As the project owner, I want the licenses kept apart and Krita AI Diffusion credited, so that the project is legally sound and future Krita AI Diffusion releases can be merged.

**Source**: derived from app-findings.md [APP-004] and inventory §7. The user decided on the plug-in architecture.

- **38.0.1 (Ubiquitous)**: The plug-in repository shall be GPL-3.0. It shall credit Krita AI Diffusion and its authors in its README, its About information and a NOTICE file, and keep the original copyright notices.
- **38.0.2 (Ubiquitous)**: The plug-in shall talk to PhotoCraft only through the process plug-in protocol. No PhotoCraft code shall be linked into the plug-in, and no plug-in code into PhotoCraft.
- **38.0.3 (Ubiquitous)**: Changes to Krita AI Diffusion's Python code shall be limited to the host shim, the UI layer, the cloud module boundary, renaming, Krita-reuse detection and documented bug fixes. Each changed upstream file shall be listed in an upstream-diff manifest.
- **38.0.4 (Ubiquitous)**: The plug-in shall use "Krita" and "Krita AI Diffusion" only nominatively (for example, "Import from Krita AI Diffusion"). It shall not use ArtCraft marks. The plug-in name shall be "AI Diffusion for PhotoCraft".

#### Acceptance Criteria
- **38.1**: The plug-in repository has `LICENSE` (GPL-3.0), `NOTICE` and README attribution.
- **38.2**: The upstream-diff manifest lists every changed upstream file. A trial merge of a later Krita AI Diffusion tag produces conflicts only in files the manifest lists.
- **38.3**: A search of the plug-in UI strings finds "Krita" only in import, detection and attribution contexts.

### REQ-39: Non-functional: reliability, security, performance and testing

**User Story**: As a user, I want the integration to be fast, safe and well-tested, so that I can trust it with my work.

**Source**: new, from the testing standards and security rules.

- **39.0.1 (Ubiquitous)**: The plug-in shall never corrupt or lose document content. Every document change it makes shall be undoable.
- **39.0.2 (Ubiquitous)**: Secrets (`server_authorization`, `access_token`, the host launch token) shall never be logged, shown in diagnostics, or stored in documents.
- **39.0.3 (Ubiquitous)**: All network access by the plug-in shall be limited to the configured ComfyUI server, model download hosts from the catalog, and this project's release feed. The cloud module's endpoints are allowed only when that module is enabled.
- **39.0.4 (Ubiquitous)**: Plug-in Python code shall have ≥ 80% line coverage and ≥ 70% branch coverage overall. The host shim, the persistence code and the Krita-reuse code shall each have ≥ 90%, measured with pytest-cov.
- **39.0.5 (Ubiquitous)**: The graph-parity tests (15.2, 18.1, 19.2, 25.2) shall compare against reference graphs captured from unmodified Krita AI Diffusion v1.54.0 running against the mocked Krita in its own test suite.
- **39.0.6 (Ubiquitous)**: End-to-end tests shall exist for: generate, inpaint, live, upscale, a custom graph, control-from-image, and Krita reuse. They run against a real ComfyUI with small test models and are gated so they can be skipped in CI without a GPU.

#### Acceptance Criteria
- **39.1**: The coverage report meets the 39.0.4 thresholds.
- **39.2**: The graph-parity suite passes for every workflow kind.
- **39.3**: A log scan after the end-to-end suite finds no secret values.
- **39.4**: A network capture during the end-to-end suite shows only allowed hosts.
- **39.5**: The end-to-end suite passes on Windows and Linux with a GPU.
