"""Buttons: push, tool, check and radio buttons. Input is played back with ``click()``, which
emits ``pressed``, ``released``, ``clicked`` and ``toggled`` as a real click does."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QPushButton,
    QRadioButton,
    QToolButton,
    QWidget,
)

from .base import Adapter, Context, Input, plain_label


def _set_checked(button: QAbstractButton, value: Any):
    """Bring a checkable button to ``value`` the way a click would."""
    if bool(value) != button.isChecked():
        button.click()


class PushButtonAdapter(Adapter):
    """``QPushButton``: a button, or a toggle button when checkable."""

    qt_class = QPushButton
    signals = ("toggled",)

    def kind_of(self, widget: QWidget) -> str:
        assert isinstance(widget, QPushButton)
        return "toggleButton" if widget.isCheckable() else "button"

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QPushButton)
        props: dict[str, Any] = {
            "text": plain_label(widget.text()),
            "icon": ctx.icon(widget.icon()),
        }
        if widget.isCheckable():
            props["checked"] = widget.isChecked()
        elif widget.isDefault():
            props["default"] = True
        return props

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QPushButton)
        if event.kind == "click":
            widget.click()
        elif event.kind == "change" and widget.isCheckable():
            _set_checked(widget, event.value)


class ToolButtonAdapter(Adapter):
    """``QToolButton``: text and/or icon as its style shows them; checkable or not."""

    qt_class = QToolButton
    kind = "toolButton"
    signals = ("toggled",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QToolButton)
        style = widget.toolButtonStyle()
        icon = ctx.icon(widget.icon())
        shows_text = style != Qt.ToolButtonStyle.ToolButtonIconOnly or icon is None
        shows_icon = style != Qt.ToolButtonStyle.ToolButtonTextOnly
        props: dict[str, Any] = {
            "text": plain_label(widget.text()) if shows_text else None,
            "icon": icon if shows_icon else None,
        }
        if widget.isCheckable():
            props["checkable"] = True
            props["checked"] = widget.isChecked()
        return props

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QToolButton)
        if event.kind == "click":
            widget.click()
        elif event.kind == "change" and widget.isCheckable():
            _set_checked(widget, event.value)


class CheckBoxAdapter(Adapter):
    """``QCheckBox``: two-state or tristate."""

    qt_class = QCheckBox
    kind = "checkbox"
    signals = ("stateChanged", "toggled")

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QCheckBox)
        tristate = widget.isTristate()
        partial = widget.checkState() == Qt.CheckState.PartiallyChecked
        return {
            "text": plain_label(widget.text()),
            "checked": None if tristate and partial else widget.isChecked(),
            "tristate": tristate or None,
            "icon": ctx.icon(widget.icon()),
        }

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QCheckBox)
        if event.kind != "change":
            return
        if not widget.isTristate():
            _set_checked(widget, event.value)
            return
        # A click cycles through three states, so the state the user picked is set directly.
        states = {None: Qt.CheckState.PartiallyChecked, True: Qt.CheckState.Checked}
        target = states.get(
            event.value if event.value is None else bool(event.value), Qt.CheckState.Unchecked
        )
        if widget.checkState() != target:
            widget.setCheckState(target)
            widget.clicked.emit(target == Qt.CheckState.Checked)


class RadioButtonAdapter(Adapter):
    """``QRadioButton``: drawn as a check box; turning one on turns its siblings off, as Qt
    does, and turning a checked one off is refused (and shown again as on)."""

    qt_class = QRadioButton
    kind = "checkbox"
    signals = ("toggled",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QRadioButton)
        return {"text": plain_label(widget.text()), "checked": widget.isChecked(), "radio": True}

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QRadioButton)
        if event.kind == "change" and event.value and not widget.isChecked():
            widget.click()
