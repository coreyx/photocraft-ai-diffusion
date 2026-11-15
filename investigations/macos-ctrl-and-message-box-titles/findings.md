# Findings: on macOS, mirrored Ctrl reaches Qt as Meta, and message boxes lose their title

## Problem

On CI's first macOS run (`macos-15`, run 42327749402, commit `7fee86f`), 5 of 340 plug-in tests failed. Linux and Windows passed all of them.

| Test | Failure |
|---|---|
| `test_qt_mirror_rich.py::test_self_drawn_widgets_are_images` | A mouse press sent with `{"ctrl": true}` arrived with `MetaModifier`, not `ControlModifier` (line 525) |
| `test_qt_mirror_rich.py::test_prompt_edits_cursor_and_keys` | `wait_for` timed out after Up sent with `{"ctrl": true}`: the prompt never became `(a big bird:1.1)` (line 206) |
| `test_upstream_interactions.py::test_ctrl_up_weights_the_word_at_the_cursor` | `'a cat' != 'a (cat:1.1)'`: Ctrl+Up didn't weight the word |
| `test_upstream_interactions.py::test_tags_autocomplete` | `'a cat, 1girl' != 'a (cat:1.1), 1girl'`: the completion worked. Only the expected text includes the weighting from the previous step. |
| `test_qt_mirror_rich.py::test_message_boxes_ask_photocraft` | `dialog.message` reached PhotoCraft with `title: ''` instead of `'Delete Workflow'` (line 551) |

The questions were why, and whether real use on a Mac is affected. No Mac was available for this investigation. It rests on the CI logs, the code on both sides of the protocol, and Qt's source.

## Investigation

- **The modifier swap is the plug-in's own, and intended.** `qt_modifiers` (`photocraft_host/qt_mirror/adapters/text.py:83-96`) maps PhotoCraft's `{shift, ctrl, alt, meta}` to Qt's modifiers. On `darwin` it maps `meta` to `ControlModifier` and `ctrl` to `MetaModifier`, with the comment "Qt's Control is the Command key on macOS, which PhotoCraft reports as meta". Key events (`text.py:106`) and mouse events on drawn widgets (`raster.py:64`) both go through it.
- **PhotoCraft does report Command as `meta`.** The fork's mirror renderer builds the modifiers from egui's as `ctrl: m.ctrl, meta: m.mac_cmd || (m.command && !m.ctrl)` (photocraft `crates/ui-egui/src/process_plugin_ui/render.rs:100`). On a Mac, egui's `ctrl` is the physical Control key and `mac_cmd` is Command. The protocol documents the same four keys (photocraft `docs/process-plugins.md:219`).
- **So on a Mac, Command arrives as Qt's Control, as in native Qt.** Qt on macOS treats Command as `ControlModifier` and the physical Control key as `MetaModifier`. Upstream checks `event.modifiers() & ControlModifier` for prompt weighting (`ai_diffusion/ui/widget.py:671-672`) and at `widget.py:974`. Through the plug-in, Command+Up therefore weights a word on a Mac, as it does in Krita on a Mac.
- **The four modifier tests send `ctrl` on every platform.** They are `test_qt_mirror_rich.py:203` and `:520`, and `upstream_interactions.py:101` (`send(prompt_id, "key", "Up", ctrl=True)`). Each expects Qt's Control, which only holds off macOS. No test covers `qt_modifiers`' `darwin` branch on its own.
- **Qt ignores a message box's title on macOS, at compile time.** Qt 6.11's `QMessageBox::setWindowTitle` (`qtbase/src/widgets/dialogs/qmessagebox.cpp`):
  ```cpp
  // Message boxes on the mac do not have a title
  #ifndef Q_OS_MAC
      QDialog::setWindowTitle(title);
  #else
      Q_UNUSED(title);
  #endif
  ```
  - The constructor `QMessageBox(icon, title, text, ...)` sets the title through this method in `QMessageBoxPrivate::init`. So does the `offscreen` platform the plug-in runs on, since the condition is the operating system, not the platform plug-in.
  - Qt's documentation says the same: "On macOS, the window title is ignored (as required by the macOS Guidelines)."
- **The mirror reads the title back from the box.** The mirror replaces `QMessageBox.information/question/warning/critical` with `_standard_box` (`photocraft_host/qt_mirror/dialogs.py:88-109`, installed at `:324`). That builds `QMessageBox(kind, title, text, parent=parent)` and passes it to `message_box_exec` (`:59-85`), which sends `box.windowTitle()` as the title (`:70`). On a Mac that's empty.
- **Upstream's message boxes take both routes.**
  - Ten call sites use the static helpers, for example "Delete Workflow" in `custom_workflow.py:1024`, `generation.py:515`, `server.py:1037` and `style.py:482`. The mirror's replacement has their title as an argument.
  - Three build a `QMessageBox(icon, title, text, ...)` themselves and call `exec()`: `server.py:1189` ("Verification Failed"), `:1213` and `:1242`. Their title is dropped inside Qt's C++ constructor, before any Python code sees it.

## Root Cause(s)

1. **The modifier tests assume Windows and Linux (4 tests). This isn't a bug in the plug-in.**
   - The plug-in deliberately maps PhotoCraft's Command (`meta`) to Qt's Control on macOS (`text.py:86-87`), matching native Qt and the fork's protocol (`render.rs:100`).
   - The tests send `ctrl` and expect Control: `test_qt_mirror_rich.py:203`, `:520` and `upstream_interactions.py:101`. On macOS, `ctrl` is the physical Control key, which Qt calls Meta.
   - **Real use:** on a Mac, Command+Up weights a word, and Command-click reaches a drawn widget as Control, as in Krita there. This isn't verified on a Mac. One unverified point: whether PhotoCraft's own text field acts on Command+Up (in egui, "go to the start") before or alongside forwarding it.

2. **Message boxes lose their title on macOS (1 test). This is a real bug on a Mac.**

   ```mermaid
   sequenceDiagram
       participant U as Upstream code
       participant M as qt_mirror/dialogs.py
       participant Q as QMessageBox (C++)
       participant P as PhotoCraft
       U->>M: QMessageBox.question(parent, "Delete Workflow", text)
       M->>Q: QMessageBox(kind, "Delete Workflow", text) (dialogs.py:92)
       Note over Q: setWindowTitle ignores the title on macOS (#ifndef Q_OS_MAC)
       M->>Q: box.windowTitle() → "" (dialogs.py:70)
       M->>P: dialog.message {title: "", text, buttons}
   ```

   Every message box the plug-in shows in PhotoCraft on a Mac has no title. Examples are "Delete Workflow", "File too large", "Verification Failed" and the generation warnings. PhotoCraft draws these as its own dialogs, so it shows whatever title it's given, even though macOS conventions leave such dialogs untitled.

3. **Side finding, not verified: a global modifier read.** `ai_diffusion/ui/region.py:385` reads `QGuiApplication.keyboardModifiers()` to decide whether a click on the translation toggle should also translate the prompt (Ctrl+click). That global state might not follow events the mirror sends to a widget, on any platform. Ctrl+click there may then act as a plain click in PhotoCraft. It's outside this investigation, so the fix below doesn't cover it. It's worth its own check.

## Recommended Fix

1. **Modifier tests:** send the platform's command modifier rather than `ctrl`. Add a helper in the tests, `meta` on `darwin` and `ctrl` elsewhere, as PhotoCraft does, and use it at `test_qt_mirror_rich.py:203` and `:520` and in `upstream_interactions.py:101`. Add a unit test of `qt_modifiers` covering both branches: give it a `platform` parameter defaulting to `sys.platform`, as `configure_fonts` and `use_platform_tls` have. The plug-in's behavior doesn't change.
2. **Message box titles:** keep the title the plug-in was given instead of reading it back from the box.
   - **Static helpers:** `_standard_box` already holds `title`. Pass it to `message_box_exec`, which then sends it instead of `box.windowTitle()`.
   - **Boxes upstream builds itself:** record the title when the box is constructed, by wrapping `QMessageBox.__init__` in the mirror's install step to store the title argument (for example as a dynamic property). `message_box_exec` then prefers that, then falls back to `windowTitle()`. Whether a sip-wrapped class accepts a replaced `__init__` cleanly needs checking first; the mirror already replaces the static methods the same way (`dialogs.py:324`). Otherwise, an upstream change at the three call sites would be the fallback.
   - Keep `test_message_boxes_ask_photocraft`, and add a case for a box built with the constructor and shown with `exec()`. Both then run on macOS in CI.
3. **Verification:** macOS CI, since there's no Mac here. A check on a real Mac with the fork's PhotoCraft goes with the other manual steps: Command+Up in the prompt, and a message box's title.
