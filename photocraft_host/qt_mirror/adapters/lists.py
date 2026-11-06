"""``QListWidget`` as a ``list``, or in icon mode as a ``thumbGrid`` (upstream's generation
history: header rows with a batch's time and prompt, then its thumbnails).

Items get an id that stays with them (in an item data role), so selection survives items being
added or removed. Input is played back as a user's would be: selecting items (``itemClicked``
for a single click), double-click (``itemDoubleClicked``), the context menu
(``customContextMenuRequested`` at the item, whose ``QMenu.exec`` then pops up in PhotoCraft) and
the keys the list handles (Delete, Space) as Qt key events.

Buttons upstream places over the list (Apply and the menu button, shown while a result is
selected) aren't in any layout; they are sent in a row under it.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QEvent, QItemSelectionModel, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListView,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from ..tree import node
from .base import Adapter, Context, Input, overrides
from .text import key_event

#: The item data role holding an item's id.
ITEM_ID = Qt.ItemDataRole.UserRole + 4242
#: Keys a list with its own key handling claims.
LIST_KEYS = ["Delete", "Space"]

_item_ids = itertools.count(1)


def item_id(item: QListWidgetItem) -> str:
    value = item.data(ITEM_ID)
    if not value:
        value = f"i{next(_item_ids)}"
        item.setData(ITEM_ID, value)
    return str(value)


def _items(widget: QListWidget) -> list[QListWidgetItem]:
    return [
        item
        for r in range(widget.count())
        if (item := widget.item(r)) is not None and not item.isHidden()
    ]


def _find(widget: QListWidget, wanted: Any) -> QListWidgetItem | None:
    return next((item for item in _items(widget) if item_id(item) == str(wanted)), None)


def overlays(widget: QListWidget) -> list[QWidget]:
    """Widgets upstream placed over the list (not its scroll bars or viewport)."""
    internal = {widget.viewport(), widget.horizontalScrollBar(), widget.verticalScrollBar()}
    return [
        child
        for child in widget.children()
        if isinstance(child, QWidget)
        and child not in internal
        and not child.objectName().startswith("qt_")
    ]


def _handles_keys(widget: QWidget) -> bool:
    return overrides(widget, QListWidget, "event", "keyPressEvent")


class ListWidgetAdapter(Adapter):
    """``QListWidget``."""

    qt_class = QListWidget
    signals = ("itemSelectionChanged", "itemChanged")

    def connect(self, widget: QWidget, changed: Callable[[], None]) -> None:
        assert isinstance(widget, QListWidget)
        super().connect(widget, changed)
        if (model := widget.model()) is not None:
            for signal in (
                model.rowsInserted,
                model.rowsRemoved,
                model.dataChanged,
                model.modelReset,
                model.layoutChanged,
            ):
                signal.connect(changed)

    def _grid_kind(self, widget: QListWidget) -> str:
        return "thumbGrid" if widget.viewMode() == QListView.ViewMode.IconMode else "list"

    def kind_of(self, widget: QWidget) -> str:
        assert isinstance(widget, QListWidget)
        return "column" if overlays(widget) else self._grid_kind(widget)

    def _grid_props(self, widget: QListWidget, ctx: Context) -> dict[str, Any]:
        icon_mode = widget.viewMode() == QListView.ViewMode.IconMode
        size = widget.iconSize().width()
        items = []
        for item in _items(widget):
            entry: dict[str, Any] = {"id": item_id(item), "tooltip": item.toolTip() or None}
            icon = item.icon()
            if icon_mode and not icon.isNull():
                entry["image"] = ctx.icon(icon, max(size, 16))
                if item.text():
                    entry["overlay"] = item.text()
            elif icon_mode:
                entry.update({"kind": "header", "text": item.text()})
            else:
                entry.update({"text": item.text(), "icon": ctx.icon(icon)})
            items.append({k: v for k, v in entry.items() if v is not None})
        multi = widget.selectionMode() in (
            QAbstractItemView.SelectionMode.ExtendedSelection,
            QAbstractItemView.SelectionMode.MultiSelection,
            QAbstractItemView.SelectionMode.ContiguousSelection,
        )
        return {
            "items": items,
            "selected": [item_id(item) for item in widget.selectedItems()],
            "selectionMode": "multi" if multi else None,
            "thumbSize": size if icon_mode else None,
            "keys": LIST_KEYS if _handles_keys(widget) else None,
        }

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QListWidget)
        if overlays(widget):
            return {}
        return self._grid_props(widget, ctx)

    def children(self, widget: QWidget, ctx: Context):
        assert isinstance(widget, QListWidget)
        extra = overlays(widget)
        if not extra:
            return []
        nid = ctx.node_id(widget)
        grid_id = f"{nid}.items"
        ctx.handle(grid_id, lambda event: self.apply(widget, event, ctx))
        # The list fills the column wrapping it; whether the column grows is up to its layout.
        grid = node(grid_id, self._grid_kind(widget), {**self._grid_props(widget, ctx), "grow": 1})
        return [grid, node(f"{nid}.overlay", "row", {}, [ctx.build(child) for child in extra])]

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QListWidget)
        if event.kind == "select" and isinstance(event.value, list):
            self._select(widget, event.value)
        elif (
            event.kind == "click"
            and isinstance(event.value, dict)
            and event.value.get("count") == 2
        ):
            if (item := _find(widget, event.value.get("item"))) is not None:
                widget.itemDoubleClicked.emit(item)
                widget.itemActivated.emit(item)
        elif event.kind == "context":
            self._context_menu(widget, event.value)
        elif event.kind == "key" and isinstance(event.value, str):
            self._key(widget, event.value, event.modifiers)

    @staticmethod
    def _select(widget: QListWidget, ids: list[Any]):
        """Select the items as a click does: one ``itemSelectionChanged`` (upstream shows the
        selected result's preview on it, so intermediate states would flicker), and
        ``itemClicked`` for a single item. The current item follows, with its signals (the
        settings dialog switches pages on ``currentRowChanged``)."""
        chosen = [item for wanted in ids if (item := _find(widget, wanted)) is not None]
        previous = widget.currentItem()
        widget.blockSignals(True)
        try:
            widget.clearSelection()
            for item in chosen:
                item.setSelected(True)
            if chosen:
                widget.setCurrentItem(chosen[-1], QItemSelectionModel.SelectionFlag.NoUpdate)
        finally:
            widget.blockSignals(False)
        widget.itemSelectionChanged.emit()
        current = widget.currentItem()
        if current is not None and current is not previous:
            widget.currentItemChanged.emit(current, previous)
            widget.currentRowChanged.emit(widget.row(current))
            widget.currentTextChanged.emit(current.text())
        if len(chosen) == 1:
            widget.itemClicked.emit(chosen[0])

    @staticmethod
    def _context_menu(widget: QListWidget, wanted: Any):
        item = _find(widget, wanted)
        if item is not None and not item.isSelected():
            widget.setCurrentItem(item)
        if widget.contextMenuPolicy() != Qt.ContextMenuPolicy.CustomContextMenu:
            return
        if item is not None:
            widget.scrollToItem(item)
            point = widget.visualItemRect(item).center()
        elif (viewport := widget.viewport()) is not None:
            point = viewport.rect().center()
        else:
            return
        widget.customContextMenuRequested.emit(point)

    @staticmethod
    def _key(widget: QListWidget, name: str, modifiers: dict[str, bool]):
        # Krita sends shortcut keys to a widget as ShortcutOverride first; upstream's history
        # handles Delete and Space there.
        for event_type in (
            QEvent.Type.ShortcutOverride,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
        ):
            event = key_event(name, modifiers, event_type)
            if event is None:
                return
            QApplication.sendEvent(widget, event)
            if event_type == QEvent.Type.ShortcutOverride and event.isAccepted():
                return
