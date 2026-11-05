"""Widgets that show something: labels, progress bars and frames."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QProgressBar, QWidget

from ..layouts import layout_items, layout_kind, layout_props
from .base import Adapter, Context, Input, might_be_rich


def _is_rich(label: QLabel) -> bool:
    fmt = label.textFormat()
    if fmt == Qt.TextFormat.RichText:
        return True
    if fmt == Qt.TextFormat.PlainText:
        return False
    return might_be_rich(label.text())


class LabelAdapter(Adapter):
    """``QLabel``: text, rich text with links, or a picture."""

    qt_class = QLabel
    kind = "label"

    def kind_of(self, widget: QWidget) -> str:
        assert isinstance(widget, QLabel)
        pixmap = widget.pixmap()
        return "image" if pixmap is not None and not pixmap.isNull() else "label"

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QLabel)
        pixmap = widget.pixmap()
        if pixmap is not None and not pixmap.isNull():
            return {"image": ctx.image(pixmap), "width": pixmap.width(), "height": pixmap.height()}
        rich = _is_rich(widget)
        return {
            "text": widget.text(),
            "format": "rich" if rich else None,
            "wrap": widget.wordWrap() or None,
        }

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QLabel)
        if event.kind != "click" or not isinstance(event.value, str):
            return
        href = event.value
        widget.linkActivated.emit(href)
        if widget.openExternalLinks():
            # Qt would open it itself; the plug-in has no desktop, so PhotoCraft does.
            ctx.call("open.url", {"url": href})


class ProgressAdapter(Adapter):
    """``QProgressBar``: a fraction, or busy when its range is empty."""

    qt_class = QProgressBar
    kind = "progress"
    signals = ("valueChanged",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QProgressBar)
        lo, hi = widget.minimum(), widget.maximum()
        value = None if hi <= lo else (widget.value() - lo) / (hi - lo)
        if value is not None:
            value = max(0.0, min(1.0, value))
        text = widget.text() if widget.isTextVisible() else None
        # A null value is what PhotoCraft draws as busy.
        return {"value": value, "text": text or None}


class FrameAdapter(Adapter):
    """``QFrame``: a line when shaped as one, else a container for its layout."""

    qt_class = QFrame

    def kind_of(self, widget: QWidget) -> str:
        assert isinstance(widget, QFrame)
        if widget.frameShape() in (QFrame.Shape.HLine, QFrame.Shape.VLine):
            return "separator"
        layout = widget.layout()
        return layout_kind(layout) if layout is not None else "column"

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QFrame)
        if widget.frameShape() == QFrame.Shape.VLine:
            return {"orientation": "vertical"}
        layout = widget.layout()
        return layout_props(layout) if layout is not None else {}

    def children(self, widget: QWidget, ctx: Context):
        layout = widget.layout()
        return layout_items(layout, ctx) if layout is not None else []
