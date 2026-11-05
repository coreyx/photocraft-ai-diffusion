"""Qt dialogs shown by PhotoCraft (design D7).

The plug-in has no windows of its own, so every way upstream opens a dialog is routed to
PhotoCraft:

- message boxes (``QMessageBox.information/question/warning/critical`` and ``exec()`` on a
  configured ``QMessageBox``) become PhotoCraft's own message box (``dialog.message``); the
  button the user picks is clicked on the Qt box, so ``exec()``'s result and ``clickedButton()``
  are what Qt would give;
- file pickers (``QFileDialog.getOpenFileName``, ``getOpenFileNames``, ``getSaveFileName``,
  ``getExistingDirectory``) become PhotoCraft's (``dialog.file``);
- any other ``QDialog`` (the settings dialog, the system information window) is mirrored into a
  PhotoCraft dialog window when shown; ``exec()`` waits for it to close;
- ``QInputDialog``'s static helpers build their dialog in Python so it goes through ``exec()``
  above (Qt's own helpers would block on a dialog nobody can see);
- ``QDesktopServices.openUrl`` opens links and folders through PhotoCraft.

Waiting for the user runs the Qt event loop (:meth:`Transport.call_waiting`, a nested loop for
``exec``), as Qt's modal dialogs do, so the plug-in keeps answering PhotoCraft meanwhile.
"""

from __future__ import annotations

import itertools
import logging
import re
from typing import Any

from PyQt6.QtCore import QEvent, QEventLoop, QObject, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QFileDialog, QInputDialog, QLineEdit, QMessageBox, QWidget

from .adapters.base import plain_label

log = logging.getLogger(__name__)

_transport: Any = None
_dialog_ids = itertools.count(1)
_open: dict[int, Any] = {}
_originals: dict[str, Any] = {}

_KINDS = {
    QMessageBox.Icon.Question: "question",
    QMessageBox.Icon.Warning: "warning",
    QMessageBox.Icon.Critical: "critical",
}


def _message(kind: str, title: str, text: str, buttons: list[str]) -> str | None:
    """Show a PhotoCraft message box and return the label of the button picked."""
    if _transport is None:
        log.warning("message box before connecting: %s", text)
        return None
    params = {"kind": kind, "title": title, "text": text, "buttons": buttons}
    result, _ = _transport.call_waiting("dialog.message", params)
    return (result or {}).get("button")


def message_box_exec(box: QMessageBox) -> int:
    """``QMessageBox.exec()``: ask PhotoCraft, then click the chosen button on the Qt box."""
    text = box.text()
    if box.informativeText():
        text += "\n\n" + box.informativeText()
    buttons = box.buttons()
    default = box.defaultButton()
    if default in buttons:  # the first button is PhotoCraft's default
        buttons.remove(default)
        buttons.insert(0, default)
    labels = [plain_label(b.text()) for b in buttons]
    picked = _message(_KINDS.get(box.icon(), "information"), box.windowTitle(), text, labels)
    chosen = next((b for b, label in zip(buttons, labels, strict=True) if label == picked), None)
    if chosen is None:
        chosen = box.escapeButton()
    if chosen is not None:
        chosen.click()
    else:
        box.reject()
    if chosen is not None and box.standardButton(chosen) == QMessageBox.StandardButton.NoButton:
        # A custom button: Krita's Qt returns its index among the custom buttons, which
        # upstream compares with (its Delete is 0). Qt 6.5 and later return an offset value.
        custom = [
            b for b in buttons if box.standardButton(b) == QMessageBox.StandardButton.NoButton
        ]
        return custom.index(chosen)
    return box.result()


def _standard_box(kind: QMessageBox.Icon):
    def show(
        parent: QWidget | None, title: str, text: str, buttons: Any = None, default: Any = None
    ) -> QMessageBox.StandardButton:
        box = QMessageBox(kind, title, text, parent=parent)
        if buttons is None and kind != QMessageBox.Icon.Question:
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
        if buttons is not None:
            box.setStandardButtons(QMessageBox.StandardButton(buttons))
        elif kind == QMessageBox.Icon.Question:
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if default is not None and default != QMessageBox.StandardButton.NoButton:
            box.setDefaultButton(QMessageBox.StandardButton(default))
        message_box_exec(box)
        clicked = box.clickedButton()
        return (
            box.standardButton(clicked)
            if clicked is not None
            else QMessageBox.StandardButton.NoButton
        )

    return staticmethod(show)


def _filters(spec: str | None) -> list[dict[str, Any]]:
    """Qt filter strings (``"LoRA files (*.safetensors);;All files (*)"``) as PhotoCraft's."""
    out = []
    for part in (spec or "").split(";;"):
        match = re.match(r"\s*(.*?)\s*\(([^)]*)\)\s*$", part)
        if not match:
            continue
        extensions = [
            p.split(".", 1)[1]
            for p in match.group(2).split()
            if "." in p and p.split(".", 1)[1] != "*"
        ]
        if extensions:
            out.append({"name": match.group(1) or ", ".join(extensions), "extensions": extensions})
    return out


def _pick(mode: str, title: str | None, start: str | None, spec: str | None = None) -> str:
    if _transport is None:
        return ""
    params: dict[str, Any] = {"mode": mode, "title": title or ""}
    if filters := _filters(spec):
        params["filters"] = filters
    if start:
        params["start"] = str(start)
    result, _ = _transport.call_waiting("dialog.file", params)
    return str((result or {}).get("path") or "")


def _get_open_file_name(parent=None, caption="", directory="", filter="", *args, **kwargs):
    path = _pick("open", caption, directory, filter)
    return path, (_filters(filter)[0]["name"] if path and _filters(filter) else "")


def _get_open_file_names(parent=None, caption="", directory="", filter="", *args, **kwargs):
    path, chosen = _get_open_file_name(parent, caption, directory, filter)
    return ([path] if path else []), chosen


def _get_save_file_name(parent=None, caption="", directory="", filter="", *args, **kwargs):
    path = _pick("save", caption, directory, filter)
    return path, (_filters(filter)[0]["name"] if path and _filters(filter) else "")


def _get_existing_directory(parent=None, caption="", directory="", *args, **kwargs):
    return _pick("folder", caption, directory)


# -- mirrored dialogs


class _Closer(QObject):
    """Closes a dialog's PhotoCraft window when Qt hides the dialog."""

    def __init__(self, dialog: QDialog):
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is not None and a1.type() == QEvent.Type.Hide:
            close_window(self._dialog)
        return False


def open_window(dialog: QDialog, modal: bool):
    """Mirror ``dialog`` into a PhotoCraft dialog window (once)."""
    from .mirror import Mirror

    if id(dialog) in _open or _transport is None:
        return
    mirror = Mirror(
        dialog,
        _transport,
        f"dialog-{next(_dialog_ids)}",
        dialog.windowTitle(),
        surface="dialog",
        modal=modal,
        on_closed=lambda: _closed_by_user(dialog),
    )
    _open[id(dialog)] = mirror
    dialog.installEventFilter(_Closer(dialog))
    mirror.start()


def _closed_by_user(dialog: QDialog):
    _open.pop(id(dialog), None)
    if dialog.isVisible():
        dialog.reject()


def close_window(dialog: QDialog):
    mirror = _open.pop(id(dialog), None)
    if mirror is not None:
        mirror.stop()


def _show(self: QDialog):
    _originals["show"](self)
    if isinstance(self, QMessageBox):
        return
    open_window(self, self.isModal())


def _exec(self: QDialog) -> int:
    if isinstance(self, QMessageBox):
        return message_box_exec(self)
    self.setModal(True)
    _originals["show"](self)
    open_window(self, True)
    loop = QEventLoop()
    self.finished.connect(loop.quit)
    if self.isVisible():
        loop.exec()
    return self.result()


# -- input dialogs, built here so they go through exec() above


def _input_text(
    parent=None, title="", label="", echo=QLineEdit.EchoMode.Normal, text="", *args, **kwargs
):
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setTextEchoMode(echo)
    dialog.setTextValue(text)
    ok = dialog.exec() == QDialog.DialogCode.Accepted
    return (dialog.textValue() if ok else ""), ok


def _input_int(
    parent=None,
    title="",
    label="",
    value=0,
    minValue=-2147483647,
    maxValue=2147483647,
    step=1,
    *args,
    **kwargs,
):
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setIntRange(minValue, maxValue)
    dialog.setIntStep(step)
    dialog.setIntValue(value)
    ok = dialog.exec() == QDialog.DialogCode.Accepted
    return (dialog.intValue() if ok else value), ok


def _input_double(
    parent=None,
    title="",
    label="",
    value=0.0,
    minValue=-2147483647.0,
    maxValue=2147483647.0,
    decimals=1,
    *args,
    **kwargs,
):
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setDoubleRange(minValue, maxValue)
    dialog.setDoubleDecimals(decimals)
    dialog.setDoubleValue(value)
    ok = dialog.exec() == QDialog.DialogCode.Accepted
    return (dialog.doubleValue() if ok else value), ok


def _input_item(
    parent=None, title="", label="", items=(), current=0, editable=True, *args, **kwargs
):
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setComboBoxItems(list(items))
    dialog.setComboBoxEditable(editable)
    if 0 <= current < len(items):
        dialog.setTextValue(list(items)[current])
    ok = dialog.exec() == QDialog.DialogCode.Accepted
    return (dialog.textValue() if ok else ""), ok


def _open_url(url: QUrl) -> bool:
    if _transport is None:
        return False
    if url.isLocalFile():
        _transport.call("open.path", {"path": url.toLocalFile()})
    else:
        _transport.call("open.url", {"url": url.toString()})
    return True


def install(transport: Any):
    """Route Qt's dialogs to PhotoCraft over ``transport`` (patches are installed once)."""
    global _transport
    _transport = transport
    if _originals:
        return
    _originals["show"] = QDialog.show
    QDialog.show = _show  # type: ignore[method-assign]
    QDialog.exec = _exec  # type: ignore[method-assign]
    for name, icon in [
        ("information", QMessageBox.Icon.Information),
        ("question", QMessageBox.Icon.Question),
        ("warning", QMessageBox.Icon.Warning),
        ("critical", QMessageBox.Icon.Critical),
    ]:
        setattr(QMessageBox, name, _standard_box(icon))
    QFileDialog.getOpenFileName = staticmethod(_get_open_file_name)  # type: ignore[method-assign,assignment]
    QFileDialog.getOpenFileNames = staticmethod(_get_open_file_names)  # type: ignore[method-assign,assignment]
    QFileDialog.getSaveFileName = staticmethod(_get_save_file_name)  # type: ignore[method-assign,assignment]
    QFileDialog.getExistingDirectory = staticmethod(_get_existing_directory)  # type: ignore[method-assign,assignment]
    QInputDialog.getText = staticmethod(_input_text)  # type: ignore[method-assign,assignment]
    QInputDialog.getInt = staticmethod(_input_int)  # type: ignore[method-assign,assignment]
    QInputDialog.getDouble = staticmethod(_input_double)  # type: ignore[method-assign,assignment]
    QInputDialog.getItem = staticmethod(_input_item)  # type: ignore[method-assign,assignment]
    QDesktopServices.openUrl = staticmethod(_open_url)  # type: ignore[method-assign,assignment]
