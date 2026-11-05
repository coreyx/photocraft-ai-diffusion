"""The image fallback for widgets that draw themselves (design D7).

A widget whose class overrides ``paintEvent`` (upstream's switch, interval slider, spinner,
generate button and server-mode buttons) can't be described as a standard widget: it is sent as
an image of itself (``QWidget.grab()``), and pointer input on the image is played back as Qt
mouse events at the same place in the widget. The image is grabbed again on every flush; only a
changed image is uploaded and patched.

Tool buttons that merely style themselves keep their native adapter: their look is an icon and
text, and a mouse press on a tool button with a menu would open Qt's own (blocking) menu.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget

from .adapters.base import Adapter, Context, Input, number, overrides
from .adapters.text import qt_modifiers

_BUTTONS = {
    "left": Qt.MouseButton.LeftButton,
    "right": Qt.MouseButton.RightButton,
    "middle": Qt.MouseButton.MiddleButton,
}


def draws_itself(widget: QWidget, adapter: Adapter | None) -> bool:
    """Whether ``widget`` paints itself beyond what its adapter (or a plain ``QWidget``) shows."""
    if adapter is not None and not adapter.raster_allowed:
        return False
    return overrides(widget, adapter.qt_class if adapter is not None else QWidget, "paintEvent")


class RasterAdapter(Adapter):
    """A self-drawing widget as an interactive image."""

    qt_class = QWidget
    kind = "image"

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        width, height = widget.width(), widget.height()
        if width <= 0 or height <= 0:
            return {"width": 0, "height": 0}
        return {
            "image": ctx.image(widget.grab()),
            "width": width,
            "height": height,
            "interactive": True,
        }

    def children(self, widget: QWidget, ctx: Context):
        return []

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        if event.kind != "pointer" or not isinstance(event.value, dict):
            return
        value = event.value
        at = QPointF(number(value.get("x")), number(value.get("y")))
        button = _BUTTONS.get(str(value.get("button", "left")), Qt.MouseButton.LeftButton)
        mods = qt_modifiers(event.modifiers)
        action = value.get("action")
        steps = {
            "click": [
                (QEvent.Type.MouseButtonPress, button),
                (QEvent.Type.MouseButtonRelease, button),
            ],
            "press": [(QEvent.Type.MouseButtonPress, button)],
            "move": [(QEvent.Type.MouseMove, Qt.MouseButton.NoButton)],
            "release": [(QEvent.Type.MouseButtonRelease, button)],
        }.get(str(action), [])
        for event_type, which in steps:
            held = (
                button
                if event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove)
                else Qt.MouseButton.NoButton
            )
            global_at = widget.mapToGlobal(at)
            QApplication.sendEvent(
                widget, QMouseEvent(event_type, at, global_at, which, held, mods)
            )
