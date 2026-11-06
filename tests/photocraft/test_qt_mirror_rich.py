"""Tests for the Qt mirror's rich widgets against the mock PhotoCraft (TASK-26): prompt fields
(highlighting, weighting keys, autocomplete, resizing), lists and the generation history, menus
and pop-ups, widgets sent as images, and dialogs shown by PhotoCraft."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from PyQt6.QtCore import QEvent, QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from photocraft_host.qt_mirror import Mirror, dialogs, install, tracker
from photocraft_host.transport import Transport

from .mock_host import MockHost, find_widget
from .test_qt_mirror import PANEL, Panel, column, settle, wait_for


@pytest.fixture
def host() -> Iterator[MockHost]:
    mock = MockHost()
    yield mock
    mock.close()


@pytest.fixture
def link(host: MockHost) -> Iterator[Transport]:
    transport = Transport(host.plugin_reader, host.plugin_writer)
    transport.start()
    install(transport)
    yield transport


@pytest.fixture
def mirror(
    host: MockHost, link: Transport, qt_app: QApplication
) -> Iterator[Callable[[QWidget], Panel]]:
    started: list[Mirror] = []

    def run(widget: QWidget) -> Panel:
        m = Mirror(widget, link, PANEL, "Test", poll_ms=60_000)
        m.start()
        started.append(m)
        return Panel(host, m, qt_app)

    yield run
    for m in started:
        m.stop()


# -- prompt fields


class Highlighter(QSyntaxHighlighter):
    """Colours the word "cat", like upstream's prompt highlighter colours syntax."""

    def highlightBlock(self, text: str | None):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#d08770"))
        fmt.setFontItalic(True)
        text = text or ""
        at = text.find("cat")
        if at >= 0:  # Qt positions are UTF-16 units
            self.setFormat(len(text[:at].encode("utf-16-le")) // 2, 3, fmt)


class Prompt(QPlainTextEdit):
    """A prompt field with its own keys and a resize handle, as upstream's ``TextPromptWidget``."""

    activated = pyqtSignal()
    handle_dragged = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.keys: list[tuple[Qt.Key, Qt.KeyboardModifier]] = []
        self.highlighter = Highlighter(self.document())
        self.words = QStringListModel(["cat ears", "catgirl", "dog"])
        self.completer = QCompleter(self.words)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setWidget(self)
        self.completer.activated.connect(self._insert)
        self.textChanged.connect(self._complete)
        self.line_count = 2
        self.is_resizable = True

    def keyPressEvent(self, e: QKeyEvent | None):
        assert e is not None
        self.keys.append((Qt.Key(e.key()), e.modifiers()))
        if e.key() == Qt.Key.Key_Return and e.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.activated.emit()
        elif (
            e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)
            and e.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.setPlainText(f"({self.toPlainText()}:1.1)")
        else:
            super().keyPressEvent(e)

    def _complete(self):
        word = self.toPlainText().split(" ")[-1]
        if len(word) >= 2:
            self.completer.setCompletionPrefix(word)
            self.completer.complete()
        else:
            popup = self.completer.popup()
            if popup is not None:
                popup.hide()

    def _insert(self, text: str):
        words = self.toPlainText().split(" ")
        words[-1] = text
        self.blockSignals(True)
        self.setPlainText(" ".join(words))
        self.blockSignals(False)


def popup_of(prompt: Prompt):
    view = prompt.completer.popup()
    assert view is not None
    return view


def test_prompt_text_highlighting_and_size(mirror):
    prompt = Prompt()
    prompt.setPlaceholderText("Describe the content")
    prompt.blockSignals(True)
    prompt.setPlainText("a 🐱 cat")
    prompt.blockSignals(False)
    panel = mirror(column(prompt))
    props = panel.props(prompt)
    assert panel.node(prompt)["kind"] == "textEdit"
    assert props["text"] == "a 🐱 cat" and props["placeholder"] == "Describe the content"
    # "cat" starts at character 4 (the emoji is two UTF-16 units but one character).
    assert props["spans"] == [{"start": 4, "end": 7, "color": "#d08770", "italic": True}]
    assert props["keys"] == ["Ctrl+Up", "Ctrl+Down", "Shift+Enter"]
    assert (props["lines"], props["minLines"], props["maxLines"], props["resizable"]) == (
        2,
        1,
        10,
        True,
    )


def test_prompt_edits_cursor_and_keys(mirror):
    prompt = Prompt()
    panel = mirror(column(prompt))
    panel.user(prompt, "change", "a b", done=lambda: prompt.toPlainText() == "a b")
    panel.user(prompt, "change", "a bird", done=lambda: prompt.toPlainText() == "a bird")
    assert prompt.textCursor().position() == 6, "after the typed text"
    panel.user(prompt, "change", "a big bird", done=lambda: prompt.toPlainText() == "a big bird")
    doc = prompt.document()
    assert doc is not None and doc.isUndoAvailable()
    prompt.undo()
    assert prompt.toPlainText() == "a bird", "one undo step per edit, as typing"
    prompt.redo()

    panel.user(
        prompt,
        "cursor",
        {"anchor": 2, "cursor": 5},
        done=lambda: prompt.textCursor().hasSelection(),
    )
    assert prompt.textCursor().selectedText() == "big"

    weighted = lambda: prompt.toPlainText() == "(a big bird:1.1)"
    panel.host.send_event(
        "panel.input",
        {
            "owner": PANEL,
            "nodeId": panel.mirror.node_id(prompt),
            "kind": "key",
            "value": "Up",
            "modifiers": {"ctrl": True},
        },
    )
    wait_for(panel.app, weighted)
    activated: list[bool] = []
    prompt.activated.connect(lambda: activated.append(True))
    panel.host.send_event(
        "panel.input",
        {
            "owner": PANEL,
            "nodeId": panel.mirror.node_id(prompt),
            "kind": "key",
            "value": "Enter",
            "modifiers": {"shift": True},
        },
    )
    wait_for(panel.app, lambda: activated == [True])
    assert prompt.toPlainText() == "(a big bird:1.1)", (
        "Shift+Enter generated rather than adding a line"
    )


def test_autocomplete(mirror):
    prompt = Prompt()
    panel = mirror(column(prompt))
    panel.user(prompt, "change", "ca", done=lambda: bool(popup_of(prompt).isVisible()))
    props = panel.props(prompt)
    assert props["completions"] == ["cat ears", "catgirl"]
    assert "Down" in props["keys"] and "Enter" in props["keys"]
    # The arrow keys go to the completer's pop-up, which moves its highlight.
    panel.host.send_event(
        "panel.input",
        {"owner": PANEL, "nodeId": panel.mirror.node_id(prompt), "kind": "key", "value": "Down"},
    )
    wait_for(panel.app, lambda: popup_of(prompt).currentIndex().row() == 0)
    panel.flush()
    assert panel.props(prompt)["completionIndex"] == 0
    panel.user(prompt, "menu", 1, done=lambda: prompt.toPlainText() == "catgirl")
    assert not popup_of(prompt).isVisible()
    panel.flush()
    assert "completions" not in panel.props(prompt)


def test_resizing_a_prompt_reports_its_handle(mirror):
    prompt = Prompt()
    dragged: list[int] = []
    prompt.handle_dragged.connect(dragged.append)
    panel = mirror(column(prompt))
    panel.user(prompt, "change", {"lines": 4}, done=lambda: bool(dragged))
    spacing = prompt.fontMetrics().lineSpacing()
    assert round((dragged[0] - 5) / spacing) == 4


# -- lists


class History(QListWidget):
    """An icon-mode list with headers, overlay buttons and keys, as upstream's history."""

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.apply = QPushButton("Apply", self)
        self.apply.setVisible(False)
        self.itemSelectionChanged.connect(lambda: self.apply.setVisible(bool(self.selectedItems())))
        self.discarded: list[str] = []
        self.copied: list[str] = []

    def event(self, e: QEvent | None):
        assert e is not None
        if (
            e.type() == QEvent.Type.ShortcutOverride
            and isinstance(e, QKeyEvent)
            and e.key() == Qt.Key.Key_Delete
        ):
            self.discarded += [i.toolTip() for i in self.selectedItems()]
            e.accept()
            return True
        return super().event(e)

    def _menu(self, pos):
        item = self.itemAt(pos)
        menu = QMenu(self)
        menu.addAction("Copy Prompt", lambda: self.copied.append(item.toolTip() if item else ""))
        disabled = menu.addAction("Save Image")
        assert disabled is not None
        disabled.setEnabled(False)
        menu.exec(self.mapToGlobal(pos))


def thumb(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def test_history_list(mirror):
    history = History()
    header = QListWidgetItem("12:00 - a cat")
    header.setToolTip("a cat")
    history.addItem(header)
    for color in ("red", "blue"):
        item = QListWidgetItem(thumb(color), "")
        item.setToolTip(color)
        history.addItem(item)
    clicked: list[str] = []
    doubled: list[str] = []
    history.itemClicked.connect(lambda i: clicked.append(i.toolTip()))
    history.itemDoubleClicked.connect(lambda i: doubled.append(i.toolTip()))
    panel = mirror(column(history))

    outer = panel.node(history)
    assert outer["kind"] == "column", "the list and its overlay buttons"
    grid, overlay = outer["children"]
    assert grid["kind"] == "thumbGrid" and grid["props"]["selectionMode"] == "multi"
    items = grid["props"]["items"]
    assert items[0]["kind"] == "header" and items[0]["text"] == "12:00 - a cat"
    assert all(i["image"].startswith("image:") for i in items[1:])
    assert grid["props"]["keys"] == ["Delete", "Space"]
    assert overlay["children"][0]["props"] == {"text": "Apply", "visible": False}

    red, blue = items[1]["id"], items[2]["id"]
    grid_id = grid["id"]
    send = lambda kind, value: panel.host.send_event(
        "panel.input", {"owner": PANEL, "nodeId": grid_id, "kind": kind, "value": value}
    )
    send("select", [red])
    wait_for(panel.app, lambda: clicked == ["red"])
    panel.flush()
    grid = find_widget(panel.tree, grid_id)
    assert grid is not None and grid["props"]["selected"] == [red]
    assert "visible" not in panel.props(history.apply), "Apply shows with a selection"
    send("click", {"item": blue, "count": 2})
    wait_for(panel.app, lambda: doubled == ["blue"])
    send("select", [red, blue])
    send("key", "Delete")
    wait_for(panel.app, lambda: sorted(history.discarded) == ["blue", "red"])


def test_selecting_a_list_item_makes_it_current(mirror):
    """As a click does; the settings dialog switches pages on ``currentRowChanged``."""
    pages = QListWidget()
    for text in ("Connection", "Styles", "Diffusion"):
        pages.addItem(text)
    pages.setCurrentRow(0)
    rows: list[int] = []
    pages.currentRowChanged.connect(rows.append)
    panel = mirror(column(pages))
    node = panel.node(pages)
    diffusion = next(i["id"] for i in node["props"]["items"] if i["text"] == "Diffusion")
    panel.host.send_event(
        "panel.input",
        {"owner": PANEL, "nodeId": node["id"], "kind": "select", "value": [diffusion]},
    )
    wait_for(panel.app, lambda: rows == [2])
    assert pages.currentRow() == 2


def test_context_menus_pop_up_in_photocraft(mirror):
    history = History()
    item = QListWidgetItem(thumb("red"), "")
    item.setToolTip("red")
    history.addItem(item)
    panel = mirror(column(history))
    grid_id = f"{panel.mirror.node_id(history)}.items"
    grid = find_widget(panel.tree, grid_id)
    assert grid is not None
    red = grid["props"]["items"][0]["id"]
    panel.host.send_event(
        "panel.input", {"owner": PANEL, "nodeId": grid_id, "kind": "context", "value": red}
    )
    wait_for(panel.app, lambda: panel.mirror._menus != {})
    panel.flush()
    popup = find_widget(panel.tree, f"{grid_id}.menu")
    assert (
        popup is not None
        and popup["kind"] == "popup"
        and popup["props"] == {"anchor": grid_id, "open": True}
    )
    copy, save = popup["children"]
    assert copy["props"]["text"] == "Copy Prompt" and save["props"]["enabled"] is False
    panel.host.send_event(
        "panel.input", {"owner": PANEL, "nodeId": copy["id"], "kind": "click", "value": 1}
    )
    wait_for(panel.app, lambda: history.copied == ["red"])
    panel.flush()
    assert find_widget(panel.tree, f"{grid_id}.menu") is None, "closed after choosing"


# -- menus and pop-ups


def test_tool_button_menu(mirror):
    button = QToolButton()
    button.setText("Workspace")
    menu = QMenu(button)
    chosen: list[str] = []
    menu.addAction("Generate", lambda: chosen.append("generate"))
    menu.addSeparator()
    sub = menu.addMenu("More")
    assert sub is not None
    sub.addAction("Live", lambda: chosen.append("live"))
    button.setMenu(menu)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    panel = mirror(column(button))
    entries = panel.props(button)["menu"]
    assert [e.get("text", e.get("kind")) for e in entries] == ["Generate", "separator", "More"]
    assert entries[2]["items"] == [{"id": "2/0", "text": "Live"}]
    panel.user(button, "menu", "0", done=lambda: chosen == ["generate"])
    panel.user(button, "menu", "2/0", done=lambda: chosen == ["generate", "live"])


def test_tool_button_widget_popup(mirror):
    button = QToolButton()
    button.setText("Queue")
    content = QWidget()
    QVBoxLayout(content).addWidget(QLabel("Batch size"))
    action = QWidgetAction(button)
    action.setDefaultWidget(content)
    button.addAction(action)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    panel = mirror(column(button))
    popup_id = f"{panel.mirror.node_id(button)}.popup"
    popup = find_widget(panel.tree, popup_id)
    assert popup is not None and popup["props"] == {
        "anchor": panel.mirror.node_id(button),
        "open": False,
    }
    panel.user(button, "click", 1, done=content.isVisible)
    popup = find_widget(panel.tree, popup_id)
    assert popup is not None and popup["props"]["open"] is True
    assert popup["children"][0]["children"][0]["props"]["text"] == "Batch size"
    panel.host.send_event(
        "panel.input", {"owner": PANEL, "nodeId": popup_id, "kind": "change", "value": False}
    )
    wait_for(panel.app, lambda: not content.isVisible())
    panel.flush()
    popup = find_widget(panel.tree, popup_id)
    assert popup is not None and popup["props"]["open"] is False


def test_menu_opened_outside_input_is_not_shown(mirror, qt_app):
    panel = mirror(column(QLabel("x")))
    menu = QMenu()
    menu.addAction("Nothing")
    assert menu.exec() is None, "never blocks"
    panel.flush()
    assert not any(c["kind"] == "popup" for c in panel.tree.get("children", []))


# -- widgets that draw themselves


class Switch(QPushButton):
    """A button that paints itself (as upstream's switch and generate button)."""

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("green" if self.isChecked() else "grey"))


class Track(QWidget):
    """A plain widget that paints itself and takes drags (as upstream's interval slider)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(120, 20)
        self.events: list[tuple[str, int, Qt.KeyboardModifier]] = []

    def paintEvent(self, a0):
        QPainter(self).fillRect(self.rect(), QColor("blue"))

    def mousePressEvent(self, a0: QMouseEvent | None):
        assert a0 is not None
        self.events.append(("press", round(a0.position().x()), a0.modifiers()))

    def mouseMoveEvent(self, a0: QMouseEvent | None):
        assert a0 is not None
        self.events.append(("move", round(a0.position().x()), a0.modifiers()))

    def mouseReleaseEvent(self, a0: QMouseEvent | None):
        assert a0 is not None
        self.events.append(("release", round(a0.position().x()), a0.modifiers()))


def test_self_drawn_widgets_are_images(mirror, host: MockHost):
    switch, track = Switch(), Track()
    switch.setCheckable(True)
    switch.setFixedSize(40, 20)
    panel = mirror(column(switch, track))
    node = panel.node(switch)
    assert node["kind"] == "image" and node["props"]["interactive"] is True
    assert (node["props"]["width"], node["props"]["height"]) == (40, 20)
    off = node["props"]["image"]
    assert off.removeprefix("image:") in host.images

    panel.user(
        switch,
        "pointer",
        {"x": 5, "y": 5, "button": "left", "action": "click"},
        done=switch.isChecked,
    )
    assert panel.props(switch)["image"] != off, "drawn again"

    send = lambda value, mods=None: panel.host.send_event(
        "panel.input",
        {
            "owner": PANEL,
            "nodeId": panel.mirror.node_id(track),
            "kind": "pointer",
            "value": value,
            "modifiers": mods or {},
        },
    )
    send({"x": 10, "y": 5, "action": "press"}, {"ctrl": True})
    send({"x": 50, "y": 5, "action": "move"})
    send({"x": 90, "y": 5, "action": "release"})
    wait_for(panel.app, lambda: len(track.events) == 3)
    assert [(e[0], e[1]) for e in track.events] == [("press", 10), ("move", 50), ("release", 90)]
    assert track.events[0][2] & Qt.KeyboardModifier.ControlModifier


def test_styled_tool_buttons_stay_native(mirror):
    class Styled(QToolButton):
        def paintEvent(self, a0):
            QPainter(self).fillRect(self.rect(), QColor("red"))

    button = Styled()
    button.setText("Workspace")
    panel = mirror(column(button))
    assert panel.node(button)["kind"] == "toolButton"


# -- dialogs


def test_message_boxes_ask_photocraft(link, host: MockHost, qt_app):
    asked: list[dict] = []

    def answer(p, _):
        asked.append(p)
        return {"button": p["buttons"][-1]}

    host.answers["dialog.message"] = answer
    picked = QMessageBox.question(None, "Delete Workflow", "Are you sure?")
    assert {k: asked[0][k] for k in ("kind", "title", "text")} == {
        "kind": "question",
        "title": "Delete Workflow",
        "text": "Are you sure?",
    }
    assert set(asked[0]["buttons"]) == {"Yes", "No"}
    assert picked in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No)

    box = QMessageBox(
        QMessageBox.Icon.Warning,
        "Confirm Deletion",
        "Delete everything?",
        QMessageBox.StandardButton.Cancel,
    )
    box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    host.answers["dialog.message"] = lambda p, _: (asked.append(p), {"button": "Delete"})[1]
    # Krita's Qt returns a custom button's index; upstream checks for 0 (newer Qt offsets it).
    assert box.exec() == 0, "the first custom button"
    assert asked[-1]["kind"] == "warning" and asked[-1]["buttons"][0] == "Cancel", (
        "the default first"
    )
    clicked = box.clickedButton()
    assert clicked is not None and clicked.text() == "Delete"

    host.answers["dialog.message"] = lambda p, _: {}
    assert (
        QMessageBox.warning(None, "Oops", "Closed without a choice")
        == QMessageBox.StandardButton.NoButton
    )


def test_file_pickers_ask_photocraft(link, host: MockHost):
    asked: list[dict] = []
    host.answers["dialog.file"] = lambda p, _: (
        asked.append(p),
        {"path": "loras/style.safetensors"},
    )[1]
    path, chosen = QFileDialog.getOpenFileName(
        None, "Select LoRA file", None, "LoRA files (*.safetensors);;All files (*)"
    )
    assert path == "loras/style.safetensors" and chosen == "LoRA files"
    assert asked[0] == {
        "mode": "open",
        "title": "Select LoRA file",
        "filters": [{"name": "LoRA files", "extensions": ["safetensors"]}],
    }
    host.answers["dialog.file"] = lambda p, _: (asked.append(p), {})[1]
    assert QFileDialog.getExistingDirectory(None, "Select Directory", "server") == ""
    assert asked[-1] == {"mode": "folder", "title": "Select Directory", "start": "server"}


def test_dialogs_are_mirrored_into_photocraft_windows(link, host: MockHost, qt_app):
    dialog = QDialog()
    dialog.setWindowTitle("System Information")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Version 1.0"))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok is not None

    def press_ok():
        dialog_id = next(iter(host.dialogs))
        host.send_event(
            "dialog.input",
            {
                "owner": dialog_id,
                "nodeId": ok.property(tracker.ID_PROPERTY),
                "kind": "click",
                "value": 1,
            },
        )

    QTimer.singleShot(100, press_ok)
    assert dialog.exec() == QDialog.DialogCode.Accepted
    (opened,) = [p for m, p in host.calls if m == "dialog.open"]
    assert opened["title"] == "System Information" and opened["modal"] is True
    assert opened["tree"]["children"][0]["props"]["text"] == "Version 1.0"
    assert ("dialog.close", {"dialogId": opened["dialogId"]}) in host.calls


def test_dialogs_open_at_their_qt_size(link, host: MockHost, qt_app):
    def opened(title: str) -> dict:
        (params,) = [p for m, p in host.calls if m == "dialog.open" and p["title"] == title]
        return params

    settings = QDialog()
    settings.setWindowTitle("Configuration")
    QVBoxLayout(settings).addWidget(QLabel("Server URL"))
    settings.setMinimumSize(960, 480)
    settings.resize(1000, 600)
    settings.show()
    sized = opened("Configuration")
    assert (sized["width"], sized["height"]) == (1000, 600)
    assert (sized["minWidth"], sized["minHeight"]) == (960, 480)
    settings.hide()

    plain = QDialog()
    plain.setWindowTitle("Plain")
    QVBoxLayout(plain).addWidget(QLabel("Text"))
    plain.show()
    params = opened("Plain")
    assert params["width"] > 0 and params["height"] > 0
    assert "minWidth" not in params and "minHeight" not in params
    plain.hide()


def test_a_dialog_closed_in_photocraft_is_rejected(link, host: MockHost, qt_app):
    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(QLabel("Settings"))
    dialog.show()
    dialog_id = next(iter(host.dialogs))
    rejected: list[bool] = []
    dialog.rejected.connect(lambda: rejected.append(True))
    host.send_event("dialog.closed", {"dialogId": dialog_id})
    wait_for(qt_app, lambda: rejected == [True])
    assert not dialog.isVisible()
    assert dialogs._open == {}


def test_input_dialogs_go_through_photocraft(link, host: MockHost, qt_app):
    def type_and_accept():
        dialog_id = next(iter(host.dialogs))
        mirror = dialogs._open[next(iter(dialogs._open))]
        edit = next(w for w in mirror._widgets.values() if type(w).__name__ == "QLineEdit")
        host.send_event(
            "dialog.input",
            {
                "owner": dialog_id,
                "nodeId": edit.property(tracker.ID_PROPERTY),
                "kind": "change",
                "value": "fox",
            },
        )
        settle(qt_app, 0.1)
        box = next(w for w in mirror._widgets.values() if isinstance(w, QDialogButtonBox))
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        host.send_event(
            "dialog.input",
            {
                "owner": dialog_id,
                "nodeId": ok.property(tracker.ID_PROPERTY),
                "kind": "click",
                "value": 1,
            },
        )

    QTimer.singleShot(150, type_and_accept)
    text, ok = QInputDialog.getText(None, "Name", "Preset name")
    assert (text, ok) == ("fox", True)


def test_open_url_goes_to_photocraft(link, host: MockHost):
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    assert QDesktopServices.openUrl(QUrl("https://example.com/docs"))
    assert host.opened == ["https://example.com/docs"]
