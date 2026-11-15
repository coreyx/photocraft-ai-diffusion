---
status: approved
---

# Fix the macOS message box titles and the modifier tests

On macOS, Qt drops a message box's title, so every message box the plug-in shows reaches PhotoCraft untitled. The mirror will keep the title it was given instead of reading it back from the box. Four other macOS test failures come from tests that send `ctrl` where PhotoCraft sends `meta` for the Command key on a Mac. The tests will send the platform's command modifier, and a unit test will cover both branches of the modifier mapping. The plug-in's modifier behavior doesn't change.

**Related documents**
- [Investigation findings](../../investigations/macos-ctrl-and-message-box-titles/findings.md)

## User Review Required

> [!IMPORTANT]
> **The mirror wraps `QMessageBox.__init__` and `QMessageBox.setWindowTitle`** in the plug-in process, alongside the static methods it already replaces (`dialogs.py:324`). The wrappers call Qt's own methods first and only record the title on the box.
> - A local check with PyQt6 6.11 confirmed the wrap records the title for a box built with positional arguments, with `parent=` as a keyword, and from a subclass's `super().__init__`. A box built with no arguments records nothing, and restoring the original works.
> - Every message box in the plug-in process goes through it, upstream's included. That is the point, but it's a wider patch than the static methods alone.
> - No upstream file changes.

> [!NOTE]
> **Verification relies on macOS CI.** There's no Mac here. The new title test simulates macOS on every platform by clearing the box's title through `QDialog.setWindowTitle`, which is what macOS's `QMessageBox` leaves. The CI run on `macos-15` then checks the real thing. A check on a real Mac with the fork's PhotoCraft joins the other manual steps.

> [!NOTE]
> **Verifying needs a push to `feat/ai-diffusion-for-photocraft`** (a normal push), as the last spec's did.

## Open Questions

None at this time. The two side points in the findings stay out of scope and are listed as follow-ups for the walkthrough:
- whether PhotoCraft's own text field acts on Command+Up before forwarding it;
- the global modifier read at `region.py:385`.

## Proposed Changes

### Message box titles

#### [MODIFY] `photocraft_host/qt_mirror/dialogs.py`
- [x] **TASK-1:** Record a message box's title where macOS can't drop it, and send that.
  - Add `TITLE_PROPERTY = "photocraft_title"`.
  - In `install()`, keep the originals in `_originals` and replace two methods:
    - `QMessageBox.__init__`: call the original, then, when the first positional argument is a `QMessageBox.Icon` and a second one follows, store that second argument (the title) with `setProperty(TITLE_PROPERTY, title)`.
    - `QMessageBox.setWindowTitle`: store the title the same way, then call the original.
  - A comment explains why: Qt's `QMessageBox::setWindowTitle` ignores the title on macOS (`#ifndef Q_OS_MAC`), and the constructor sets it through that method, so `windowTitle()` is empty there whatever platform plug-in runs.
  - `message_box_exec` sends `box.property(TITLE_PROPERTY)` when it's set, and `box.windowTitle()` otherwise.
  - `_standard_box` needs no change: it builds its box with the constructor, so the title is recorded.

#### [MODIFY] `tests/photocraft/test_qt_mirror_rich.py`
- [x] **TASK-2:** Test titles as macOS leaves them, on every platform.
  - In `test_message_boxes_ask_photocraft`, the "Confirm Deletion" box (built with the constructor, shown with `exec()`) also asserts `asked[-1]["title"] == "Confirm Deletion"`.
  - Add `test_a_message_box_title_survives_qt_dropping_it`:
    - build a `QMessageBox` with a title and clear it with `QDialog.setWindowTitle(box, "")`, as macOS's `QMessageBox` leaves it;
    - `exec()` it, and check that `dialog.message` carries the original title;
    - then check that a title set later with `box.setWindowTitle("Later")` is the one sent.

### Modifier tests

#### [MODIFY] `photocraft_host/qt_mirror/adapters/text.py`
- [x] **TASK-3:** Give `qt_modifiers` a `platform: str = sys.platform` parameter, used instead of reading `sys.platform` directly, as `configure_fonts` and `use_platform_tls` do. Its callers (`text.py:106`, `raster.py:64`) keep calling it without one.

#### [NEW] `tests/photocraft/test_modifiers.py`
- [x] **TASK-4:** Unit tests of `qt_modifiers`:
  - on `win32` and `linux`, `{"ctrl": True}` gives `ControlModifier` and `{"meta": True}` gives `MetaModifier`;
  - on `darwin`, `{"meta": True}` (Command) gives `ControlModifier` and `{"ctrl": True}` gives `MetaModifier`;
  - `shift` and `alt` map the same everywhere, and an empty dict gives `NoModifier`.

#### [MODIFY] `tests/photocraft/mock_host.py`
- [x] **TASK-5:** Add `COMMAND = "meta" if sys.platform == "darwin" else "ctrl"`, with a comment saying it is the modifier PhotoCraft sends for the key Qt calls Control: Command on a Mac (fork `render.rs:100`), Ctrl elsewhere.

#### [MODIFY] `tests/photocraft/test_qt_mirror_rich.py` and `tests/photocraft/upstream_interactions.py`
- [ ] **TASK-6:** Send `COMMAND` where the tests mean Qt's Control:
  - `test_qt_mirror_rich.py:203`, the Up key in `test_prompt_edits_cursor_and_keys`;
  - `test_qt_mirror_rich.py:520`, the press in `test_self_drawn_widgets_are_images`;
  - `upstream_interactions.py:101`: `send(prompt_id, "key", "Up", **{COMMAND: True})`, importing `COMMAND` from `tests.photocraft.mock_host`. The script puts the repository on `sys.path` already.

  The assertions stay as they are: they check Qt's Control, which is what upstream reads.

## Verification Plan

### Automated Tests
The project's pytest suites, as in this repository's earlier plans:
1. `tests/photocraft/test_modifiers.py`: both branches of `qt_modifiers` (TASK-3, TASK-4).
2. `test_qt_mirror_rich.py`'s message box tests, including the simulated macOS title. The new test is run once before TASK-1's change to confirm it fails (TASK-1, TASK-2).
3. The four modifier tests pass locally with `COMMAND` (TASK-5, TASK-6).
4. Regression, as CI runs it:
   - format, lint and `pyright`;
   - `upstream_changes.py`, which must still report no upstream file changed;
   - the plug-in suite, upstream's unit tests and the stand-in suite, under coverage, and the coverage gate.

### Manual Verification
1. Push `feat/ai-diffusion-for-photocraft`, then check that the "PhotoCraft plug-in" run passes on all three platforms, macOS included: `gh run list -R coreyx/photocraft-ai-diffusion`, then `gh run view <id> -R coreyx/photocraft-ai-diffusion`.
2. On a Mac with the fork's PhotoCraft, when one is available:
   - Command+Up in the prompt weights the word at the cursor;
   - deleting a custom workflow asks with the title "Delete Workflow".

   The walkthrough lists this for later.
