"""Containers whose structure isn't a layout: scroll areas, stacks, tabs, splitters and group
boxes. Only the page a stack or tab widget shows is sent with its content, which keeps the tree
small: switching pages swaps one subtree."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGroupBox, QScrollArea, QSplitter, QStackedWidget, QTabWidget, QWidget

from ..tree import node
from .base import Adapter, Context, Input, plain_label


class ScrollAreaAdapter(Adapter):
    """``QScrollArea``: scrolls its one widget."""

    qt_class = QScrollArea
    kind = "scroll"

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QScrollArea)
        limit = widget.maximumHeight()
        return {"maxHeight": limit if limit < 16_777_215 else None}

    def children(self, widget: QWidget, ctx: Context):
        assert isinstance(widget, QScrollArea)
        inner = widget.widget()
        return [ctx.build(inner)] if inner is not None else []


class StackAdapter(Adapter):
    """``QStackedWidget``: only the current page, as the stack's single child."""

    qt_class = QStackedWidget
    kind = "stack"
    signals = ("currentChanged", "widgetRemoved")

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        return {"current": 0}

    def children(self, widget: QWidget, ctx: Context):
        assert isinstance(widget, QStackedWidget)
        page = widget.currentWidget()
        return [ctx.build(page)] if page is not None else []


class TabsAdapter(Adapter):
    """``QTabWidget``: one page per tab, titled; only the current page has content."""

    qt_class = QTabWidget
    kind = "tabs"
    signals = ("currentChanged",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QTabWidget)
        return {"current": max(widget.currentIndex(), 0)}

    def children(self, widget: QWidget, ctx: Context):
        assert isinstance(widget, QTabWidget)
        pages = []
        for i in range(widget.count()):
            page = widget.widget(i)
            if page is None:
                continue
            title = plain_label(widget.tabText(i))
            if i == widget.currentIndex():
                built = ctx.build(page)
                built["props"]["title"] = title
                pages.append(built)
            else:
                pages.append(node(ctx.node_id(page), "column", {"title": title}))
        return pages

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QTabWidget)
        if event.kind != "change":
            return
        try:
            index = int(event.value)
        except (TypeError, ValueError):
            return
        if 0 <= index < widget.count() and widget.isTabEnabled(index):
            widget.tabBarClicked.emit(index)
            widget.setCurrentIndex(index)


class SplitterAdapter(Adapter):
    """``QSplitter``: its widgets, with their current sizes."""

    qt_class = QSplitter
    kind = "splitter"
    signals = ("splitterMoved",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QSplitter)
        vertical = widget.orientation() == Qt.Orientation.Vertical
        return {"orientation": "vertical" if vertical else "horizontal", "sizes": widget.sizes()}

    def children(self, widget: QWidget, ctx: Context):
        assert isinstance(widget, QSplitter)
        return [
            ctx.build(child)
            for i in range(widget.count())
            if (child := widget.widget(i)) is not None
        ]

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QSplitter)
        if event.kind == "change" and isinstance(event.value, list):
            widget.setSizes([int(v) for v in event.value])
            widget.splitterMoved.emit(0, 0)


class GroupBoxAdapter(Adapter):
    """``QGroupBox``: a titled frame, optionally with its own check box."""

    qt_class = QGroupBox
    kind = "group"
    signals = ("toggled",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QGroupBox)
        props: dict[str, Any] = {"title": plain_label(widget.title())}
        if widget.isCheckable():
            props["checkable"] = True
            props["checked"] = widget.isChecked()
        return props

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QGroupBox)
        if (
            event.kind == "change"
            and widget.isCheckable()
            and bool(event.value) != widget.isChecked()
        ):
            widget.setChecked(bool(event.value))
            widget.clicked.emit(widget.isChecked())
