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
    QWidgetAction,
)

from .. import menus
from ..tree import node
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


#: The Qt property holding whether a tool button's widget pop-up is open in PhotoCraft.
POPUP_OPEN = "_photocraft_popup_open"


def _popup_widget(button: QToolButton) -> QWidget | None:
    """The widget a tool button pops up through a ``QWidgetAction`` (upstream's queue button)."""
    if button.menu() is not None:
        return None
    for action in button.actions():
        if isinstance(action, QWidgetAction) and (widget := action.defaultWidget()) is not None:
            return widget
    return None


class ToolButtonAdapter(Adapter):
    """``QToolButton``: text and/or icon as its style shows them; checkable or not. A menu set
    on it becomes its ``menu`` prop; a widget it pops up (a ``QWidgetAction``) becomes a
    ``popup`` child, opened by a click."""

    qt_class = QToolButton
    kind = "toolButton"
    signals = ("toggled", "triggered")
    # Upstream's tool buttons only style an icon and text; see raster.py.
    raster_allowed = False

    def children(self, widget: QWidget, ctx: Context):
        assert isinstance(widget, QToolButton)
        content = _popup_widget(widget)
        if content is None:
            return []
        nid = ctx.node_id(widget)
        popup_id = f"{nid}.popup"

        def closed(event: Input):
            if event.kind == "change" and event.value is False:
                widget.setProperty(POPUP_OPEN, False)
                content.hide()

        ctx.handle(popup_id, closed)
        is_open = bool(widget.property(POPUP_OPEN))
        children = [ctx.build(content, shown=True)] if is_open else []
        return [node(popup_id, "popup", {"anchor": nid, "open": is_open}, children)]

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
        if (menu := widget.menu()) is not None:
            props["menu"] = menus.items_of(menu, ctx)
        return props

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QToolButton)
        if event.kind == "menu" and (menu := widget.menu()) is not None:
            menus.trigger(menu, event.value)
        elif event.kind == "click" and (content := _popup_widget(widget)) is not None:
            is_open = not bool(widget.property(POPUP_OPEN))
            widget.setProperty(POPUP_OPEN, is_open)
            # Shown, so upstream code asking isVisible() sees it as the user does.
            content.setVisible(is_open)
        elif event.kind == "click":
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
