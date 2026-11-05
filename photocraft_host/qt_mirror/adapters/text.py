"""Multi-line text: ``QPlainTextEdit`` and ``QTextEdit``, upstream's prompt fields.

What the host draws: the text, the highlighting upstream's ``QSyntaxHighlighter`` applied (as
``spans``), the completer's pop-up list (as ``completions``) and the field's size in lines.
What comes back is played into Qt so upstream's code runs as if typed:

- an edit is applied through a ``QTextCursor`` as the smallest replacement, which leaves the
  cursor after the typed text (where the completer looks) and keeps Qt's undo history;
- ``cursor`` moves Qt's cursor and selection;
- keys the field claims (``keys``) arrive as Qt key events: Ctrl+Up/Down re-weight a prompt and
  Shift+Enter generates (upstream's ``keyPressEvent``), and while the completer is open the
  arrow keys, Enter, Tab and Escape go to its pop-up, as in Qt;
- choosing a completion selects it in the pop-up and presses Enter there.

PhotoCraft counts text positions in characters; Qt in UTF-16 code units. Positions are
converted both ways.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QEvent, QModelIndex, QObject, Qt
from PyQt6.QtGui import QFontMetrics, QKeyEvent, QTextCursor, QTextFormat
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCompleter,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

from .. import tracker
from .base import Adapter, Context, Input, overrides

#: The Qt property on a text field holding its completer (recorded by ``QCompleter.setWidget``).
COMPLETER = "_photocraft_completer"
#: Keys a field with its own key handling claims.
FIELD_KEYS = ["Ctrl+Up", "Ctrl+Down", "Shift+Enter"]
#: Keys that go to the completer's pop-up while it is open.
COMPLETION_KEYS = ["Up", "Down", "Enter", "Tab", "Shift+Tab", "Escape"]
#: Lines a resizable field may grow to.
MAX_LINES = 10

_KEYS = {
    "Up": Qt.Key.Key_Up,
    "Down": Qt.Key.Key_Down,
    "Left": Qt.Key.Key_Left,
    "Right": Qt.Key.Key_Right,
    "Enter": Qt.Key.Key_Return,
    "Return": Qt.Key.Key_Return,
    "Tab": Qt.Key.Key_Tab,
    "Escape": Qt.Key.Key_Escape,
    "Delete": Qt.Key.Key_Delete,
    "Backspace": Qt.Key.Key_Backspace,
    "Space": Qt.Key.Key_Space,
    "Home": Qt.Key.Key_Home,
    "End": Qt.Key.Key_End,
    "PageUp": Qt.Key.Key_PageUp,
    "PageDown": Qt.Key.Key_PageDown,
}
_TEXT = {"Enter": "\r", "Return": "\r", "Tab": "\t", "Space": " ", "Escape": "\x1b"}


def utf16(text: str, index: int) -> int:
    """The UTF-16 position of character ``index``."""
    return len(text[:index].encode("utf-16-le")) // 2


def from_utf16(text: str, position: int) -> int:
    """The character index of UTF-16 ``position``."""
    units = 0
    for i, ch in enumerate(text):
        if units >= position:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


def qt_modifiers(modifiers: dict[str, bool]) -> Qt.KeyboardModifier:
    """PhotoCraft's modifiers (``{shift, ctrl, alt, meta}``) as Qt's."""
    mods = Qt.KeyboardModifier.NoModifier
    # Qt's Control is the Command key on macOS, which PhotoCraft reports as meta.
    ctrl, meta = ("meta", "ctrl") if sys.platform == "darwin" else ("ctrl", "meta")
    if modifiers.get(ctrl):
        mods |= Qt.KeyboardModifier.ControlModifier
    if modifiers.get(meta):
        mods |= Qt.KeyboardModifier.MetaModifier
    if modifiers.get("shift"):
        mods |= Qt.KeyboardModifier.ShiftModifier
    if modifiers.get("alt"):
        mods |= Qt.KeyboardModifier.AltModifier
    return mods


def key_event(
    name: str, modifiers: dict[str, bool], event_type=QEvent.Type.KeyPress
) -> QKeyEvent | None:
    """A Qt key event for a key PhotoCraft forwarded (its name and modifiers)."""
    key = _KEYS.get(name)
    if key is None:
        return None
    mods = qt_modifiers(modifiers)
    if key == Qt.Key.Key_Tab and modifiers.get("shift"):
        key = Qt.Key.Key_Backtab
    return QKeyEvent(event_type, key, mods, _TEXT.get(name, ""))


def press(target: QObject, name: str, modifiers: dict[str, bool]):
    """Send a key press and release to ``target``."""
    for event_type in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        event = key_event(name, modifiers, event_type)
        if event is not None:
            QApplication.sendEvent(target, event)


def _record_completer(completer: QCompleter, widget: QWidget | None):
    if widget is not None:
        widget.setProperty(COMPLETER, completer)


def install_completer_hook():
    """Remember which field a completer serves: upstream creates completers without a parent
    and attaches them with ``QCompleter.setWidget``."""
    original: Callable[..., Any] = QCompleter.setWidget
    if getattr(original, "_photocraft_hook", False):
        return

    def set_widget(self: QCompleter, widget: QWidget | None):
        original(self, widget)
        _record_completer(self, widget)

    set_widget._photocraft_hook = True  # type: ignore[attr-defined]
    QCompleter.setWidget = set_widget  # type: ignore[method-assign]


def completer_of(widget: QWidget) -> QCompleter | None:
    completer = widget.property(COMPLETER)
    return completer if isinstance(completer, QCompleter) else None


def _popup(widget: QWidget) -> QAbstractItemView | None:
    completer = completer_of(widget)
    popup = completer.popup() if completer is not None else None
    return popup if popup is not None and popup.isVisible() else None


def _spans(widget: QPlainTextEdit | QTextEdit) -> list[dict[str, Any]]:
    """The highlighter's formats as character ranges with a colour, italics or bold."""
    spans: list[dict[str, Any]] = []
    doc = widget.document()
    if doc is None:
        return spans
    offset = 0  # characters before the block
    block = doc.begin()
    while block.isValid():
        text = block.text()
        layout = block.layout()
        for fr in layout.formats() if layout is not None else []:
            fmt = fr.format
            span: dict[str, Any] = {
                "start": offset + from_utf16(text, fr.start),
                "end": offset + from_utf16(text, fr.start + fr.length),
            }
            if fmt.hasProperty(QTextFormat.Property.ForegroundBrush):
                span["color"] = fmt.foreground().color().name()
            if fmt.fontItalic():
                span["italic"] = True
            if fmt.fontWeight() >= 600:
                span["bold"] = True
            if span["end"] > span["start"] and len(span) > 2:
                spans.append(span)
        offset += len(text) + 1
        block = block.next()
    return spans


def _lines(widget: QPlainTextEdit | QTextEdit) -> int | None:
    """The field's height in lines, when it is fixed (upstream sizes prompts by line count)."""
    count = getattr(widget, "line_count", None)
    if isinstance(count, int):
        return count
    if widget.minimumHeight() == widget.maximumHeight() and widget.minimumHeight() > 0:
        doc = widget.document()
        font = doc.defaultFont() if doc is not None else widget.font()
        return max(1, round((widget.minimumHeight() - 10) / QFontMetrics(font).lineSpacing()))
    return None


def _has_own_keys(widget: QWidget) -> bool:
    """Whether the field handles keys itself (upstream's prompt field does)."""
    base = QPlainTextEdit if isinstance(widget, QPlainTextEdit) else QTextEdit
    return overrides(widget, base, "keyPressEvent")


class TextEditAdapter(Adapter):
    """``QPlainTextEdit``: upstream's prompt fields."""

    qt_class: Any = QPlainTextEdit
    kind = "textEdit"
    signals = ("textChanged",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, (QPlainTextEdit, QTextEdit))
        popup = None
        if (completer := completer_of(widget)) is not None and (
            view := completer.popup()
        ) is not None:
            self._follow_popup(view, ctx)
            popup = view if view.isVisible() else None
        keys = list(FIELD_KEYS) if _has_own_keys(widget) else []
        props: dict[str, Any] = {
            "text": widget.toPlainText(),
            "placeholder": widget.placeholderText() or None,
            "readOnly": widget.isReadOnly() or None,
            "spans": _spans(widget) or None,
        }
        if popup is not None:
            model = popup.model()
            rows = model.rowCount() if model is not None else 0
            props["completions"] = (
                [str(model.index(r, 0).data() or "") for r in range(rows)]
                if model is not None
                else []
            )
            current = popup.currentIndex()
            props["completionIndex"] = current.row() if current.isValid() else None
            keys += COMPLETION_KEYS
        props["keys"] = keys or None
        if (lines := _lines(widget)) is not None:
            resizable = bool(getattr(widget, "is_resizable", False))
            props.update({
                "lines": lines,
                "minLines": 1 if resizable else lines,
                "maxLines": max(MAX_LINES, lines) if resizable else lines,
                "resizable": resizable or None,
            })
        return props

    def _follow_popup(self, view: QAbstractItemView, ctx: Context):
        """Mark the field dirty when its completer's pop-up opens, closes or moves its highlight."""
        if view.property(tracker.ID_PROPERTY + "_followed"):
            return
        view.setProperty(tracker.ID_PROPERTY + "_followed", True)
        changed = ctx.mark_dirty
        view.installEventFilter(tracker.ChangeFilter(changed, parent=view))
        if (selection := view.selectionModel()) is not None:
            selection.currentChanged.connect(lambda *_: changed())

    def children(self, widget: QWidget, ctx: Context):
        return []

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, (QPlainTextEdit, QTextEdit))
        if event.kind == "change" and isinstance(event.value, dict) and "lines" in event.value:
            self._resize(widget, int(event.value["lines"]))
        elif event.kind == "change" and isinstance(event.value, str) and not widget.isReadOnly():
            self._edit(widget, event.value)
        elif event.kind == "cursor" and isinstance(event.value, dict):
            self._move_cursor(widget, event.value)
        elif event.kind == "key" and isinstance(event.value, str):
            popup = _popup(widget)
            if popup is not None and event.value in ("Enter", "Tab"):
                self._complete(widget, popup.currentIndex().row())
            elif popup is not None and event.value in ("Up", "Down", "Escape"):
                press(popup, event.value, event.modifiers)
            else:
                press(widget, event.value, event.modifiers)
        elif event.kind == "menu":
            self._complete(widget, event.value)
        elif event.kind == "focus" and event.value:
            widget.setFocus()
        elif event.kind == "focus":
            widget.clearFocus()

    @staticmethod
    def _edit(widget: QPlainTextEdit | QTextEdit, new: str):
        old = widget.toPlainText()
        if new == old:
            return
        start = 0
        while start < min(len(old), len(new)) and old[start] == new[start]:
            start += 1
        end_old, end_new = len(old), len(new)
        while end_old > start and end_new > start and old[end_old - 1] == new[end_new - 1]:
            end_old -= 1
            end_new -= 1
        cursor = widget.textCursor()
        cursor.setPosition(utf16(old, start))
        cursor.setPosition(utf16(old, end_old), QTextCursor.MoveMode.KeepAnchor)
        widget.setTextCursor(cursor)
        cursor.insertText(new[start:end_new])
        widget.setTextCursor(cursor)

    @staticmethod
    def _move_cursor(widget: QPlainTextEdit | QTextEdit, value: dict[str, Any]):
        text = widget.toPlainText()
        try:
            anchor, position = int(value.get("anchor", 0)), int(value.get("cursor", 0))
        except (TypeError, ValueError):
            return
        cursor = widget.textCursor()
        cursor.setPosition(utf16(text, min(anchor, len(text))))
        cursor.setPosition(utf16(text, min(position, len(text))), QTextCursor.MoveMode.KeepAnchor)
        widget.setTextCursor(cursor)

    @staticmethod
    def _complete(widget: QWidget, index: Any):
        popup = _popup(widget)
        model = popup.model() if popup is not None else None
        try:
            row = int(index)
        except (TypeError, ValueError):
            return
        completer = completer_of(widget)
        if popup is None or model is None or completer is None or not 0 <= row < model.rowCount():
            return
        # What Qt does when Enter picks a completion: close the pop-up and emit activated with
        # the item and its text. (Qt's own handling of an Enter sent to the pop-up closes it
        # without emitting anything here.)
        index = model.index(row, 0)
        popup.setCurrentIndex(index)
        popup.hide()
        completer.activated[QModelIndex].emit(index)
        completer.activated.emit(str(index.data(completer.completionRole()) or ""))

    @staticmethod
    def _resize(widget: QPlainTextEdit | QTextEdit, lines: int):
        """Resize as dragging upstream's handle does (it reports the handle's position)."""
        doc = widget.document()
        spacing = QFontMetrics(
            doc.defaultFont() if doc is not None else widget.font()
        ).lineSpacing()
        dragged = getattr(widget, "handle_dragged", None)
        if dragged is not None:
            dragged.emit(lines * spacing + 5)
        elif isinstance(getattr(widget, "line_count", None), int):
            widget.line_count = lines  # type: ignore[attr-defined]


class RichTextEditAdapter(TextEditAdapter):
    """``QTextEdit``: the same, as plain text."""

    qt_class = QTextEdit
