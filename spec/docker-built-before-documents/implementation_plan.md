---
status: approved
---

# Build the plug-in's dockers as Krita does, before any document is active

When a document was already open as the plug-in started, the AI Image Generation panel didn't respond in it: Generate queued nothing. The same goes for the Upscale, Live and Custom Graph workspaces. Upstream's workspace widgets connect to a document's model only when it changes from the one they were built with. Krita builds its dockers before any document opens, but the plug-in built them with that document already active. The `krita` stand-in will report no active document while a docker is being built, so the docker is handed the document afterwards, as in Krita. No upstream file changes.

**Related documents**
- [Investigation findings](../../investigations/generate-dead-in-restored-document/findings.md)

## User Review Required

> [!NOTE]
> **Only the stand-in changes**: `Krita.create_dock` in `photocraft_host/krita/_app.py`. Upstream's code and `UPSTREAM-CHANGES.md` stay as they are, and the PhotoCraft fork doesn't change.

> [!NOTE]
> **While a docker is being built, `Krita.activeDocument()` returns `None`.** That's what upstream sees in Krita at that point. The docker learns of the document right after, through `canvasChanged` (`photocraft_host/main.py:192`). `documents()` still lists the open documents.

## Open Questions

None at this time.

## Proposed Changes

### The `krita` stand-in

#### [MODIFY] `photocraft_host/krita/_app.py`
- [x] **TASK-1:** In `Krita.create_dock`, set a `_building_dock` flag around `factory.create()`, cleared in a `finally`. `activeDocument()` returns `None` while it's set. The docstring says why:
  - Krita builds its dockers before any document is open;
  - upstream's workspace widgets start from `root.active_model` and bind a model only when it differs;
  - a document active while they're built would never be bound.

### Tests

#### [MODIFY] `tests/photocraft/test_krita_shim.py`
- [x] **TASK-2:** Add `test_a_docker_is_built_before_the_active_document`, on the existing attached-host fixture with one document active:
  - a `DockWidgetFactory` whose docker records `Krita.instance().activeDocument()` while it's built records `None`;
  - after `create_dock`, `activeDocument()` is that document again;
  - when the docker's constructor raises, the flag is still cleared.

#### [MODIFY] `tests/photocraft/upstream_interactions.py` and `tests/photocraft/test_upstream_interactions.py`
- [ ] **TASK-3:** With the script's document already open, build upstream's `ImageDiffusionWidget` through `Krita.instance().create_dock`. Hand its Generate, Upscale, Live and Custom Graph workspaces the document's model, as `update_content` does once connected. Record two things:
  - **each workspace's bindings:** the length of its `_model_bindings`;
  - **Generate:** whether its `clicked` reaches the model, with `model.generate` replaced by a recorder.

  Add `test_a_docker_built_with_a_document_open_binds_it`: every workspace has bindings, and Generate reaches the model. Before TASK-1 it fails: all four have 0 bindings.

## Verification Plan

### Automated Tests
1. **Order:** the new tests are run once before TASK-1, to confirm they fail. Then the files are run again after it:
   - `pytest tests/photocraft/test_krita_shim.py -k docker` (TASK-2);
   - `pytest tests/photocraft/test_upstream_interactions.py` (TASK-3).
2. **Regression:** the CI-equivalent pass, meaning format, lint, `pyright`, `upstream_changes.py`, the three suites under coverage and the coverage gate.

### Manual Verification
In the fork's PhotoCraft release build, with the rebuilt package and your local ComfyUI:
1. With a document open, quit PhotoCraft so it restores the document at the next launch, or open PhotoCraft with an image file.
2. Once the plug-in is connected, type a prompt and click Generate in that document. A job is queued and its result shows in the history.
3. Switch the panel to Upscale and to Live in the same document. Their controls respond. For example, Live's start button starts.
4. Open a new document and generate there too. It still works.

## Visual design application

No visual change.
