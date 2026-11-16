# Walkthrough: build the plug-in's dockers before the active document

The AI Image Generation panel now works in a document that was open before the plug-in started, such as one PhotoCraft restored at launch ([findings](../../investigations/generate-dead-in-restored-document/findings.md)). While the plug-in builds a docker, the `krita` stand-in reports no active document, as Krita does when it builds its dockers before any document opens. The docker is handed the document afterwards, and upstream's workspaces bind to it. No upstream file changed.

## What Was Implemented

### 1. The `krita` stand-in
- **`photocraft_host/krita/_app.py`** (`0fbd385`): `Krita.create_dock` sets `_building_dock` around `factory.create()`, and clears it in a `finally`. While it's set, `activeDocument()` returns `None`. The docstring explains why: upstream's workspaces start from `root.active_model` and bind a model only when it changes.

### 2. Tests
- **`tests/photocraft/test_krita_shim.py`** (`1dc583b`): `test_a_docker_is_built_before_the_active_document`.
  - A docker built while a document is open sees no active document.
  - Afterwards the document is active again.
  - A docker whose constructor raises leaves it active too.
- **`tests/photocraft/upstream_interactions.py` and `test_upstream_interactions.py`** (`4c1e0ed`): `test_a_docker_built_with_a_document_open_binds_it`.
  - Upstream's `ImageDiffusionWidget` is built through `create_dock` with the script's document already open.
  - Its Generate, Upscale, Live and Custom Graph workspaces are handed the document's model, as `update_content` does.
  - Each has bindings, and Generate's click reaches the model.
  - `DockWidgetFactory` and `Krita` are imported from `photocraft_host.krita`, not `krita`, because `pyright` reads `krita` as Krita's own stubs.

## Verification & Test Results

### Automated Tests
- **`test_a_docker_is_built_before_the_active_document`:** before the fix, the docker saw the open document. **Passed** after it.
- **`test_a_docker_built_with_a_document_open_binds_it`:** before the fix, all four workspaces had 0 bindings. **Passed** after it.

### Regression Testing
The plug-in's CI-equivalent pass:

| Check | Result |
|---|---|
| Format, lint, `upstream_changes.py` | Clean |
| `pyright` | 0 errors |
| Plug-in tests | 354 passed |
| Upstream unit tests | 268 passed, 27 skipped |
| Stand-in tests | 246 passed, 19 skipped |
| Coverage gate | 93.3% of lines and 78.5% of branches overall; the stand-in at 96.8% of lines |

## Manual Verification
Done in the fork's release build, with the rebuilt package in an isolated profile and your local ComfyUI. PhotoCraft restored a recovered document at launch, before the plug-in started.
1. **The history:** in the restored document, the history showed the document's earlier results. Before the fix it was empty there. **Passed**
2. **Generate:** with a prompt typed, Generate queued a job, and its result arrived with its preview on the canvas. Before the fix, nothing was queued. **Passed**
3. **Upscale:**
   - it showed the document's target size (2048 × 2048) and prompt;
   - turning "Refine upscaled image" off disabled its controls, and turning it on enabled them.

   **Passed**
4. **Live:** it showed the document's prompt and strength. Its start button started Live (the button turned to pause and the preview area showed), and a second click stopped it. **Passed**
5. **A new document** wasn't tried after the fix. It worked before the fix, and the fix only changes what a docker sees while it's built.

To check on your side, in your PhotoCraft fork install, which now has this plug-in code:
1. Quit PhotoCraft with a document open so it's restored, or open PhotoCraft with an image file.
2. Click Generate in that document. A job is queued and its result arrives.

## Follow-ups
- **The Upscale workspace runs past the dock's right edge** at the default dock width. The Scale drop-down, the Tile Overlap field and the Use Prompt switch were cut off. The Generate workspace was fixed for this in `generate-panel-rows-fit`, but Upscale's rows weren't checked there.
