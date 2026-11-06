"""Qt layouts as protocol containers: box layouts become ``row``/``column``, grid and form
layouts ``grid``/``form``, a stacked layout a ``stack``. Stretch factors and expanding size
policies become ``grow``; spacer items become ``spacer`` nodes. Pixel geometry isn't sent:
PhotoCraft lays the widgets out itself (design D7)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QBoxLayout,
    QFormLayout,
    QGridLayout,
    QLayout,
    QLayoutItem,
    QStackedLayout,
)

from .tree import Node, node

if TYPE_CHECKING:
    from .adapters.base import Context


def layout_kind(layout: QLayout) -> str:
    if isinstance(layout, QBoxLayout):
        horizontal = layout.direction() in (
            QBoxLayout.Direction.LeftToRight,
            QBoxLayout.Direction.RightToLeft,
        )
        return "row" if horizontal else "column"
    if isinstance(layout, QGridLayout):
        return "grid"
    if isinstance(layout, QFormLayout):
        return "form"
    if isinstance(layout, QStackedLayout):
        return "stack"
    return "column"


def layout_props(layout: QLayout) -> dict[str, Any]:
    spacing = layout.spacing()
    props: dict[str, Any] = {"spacing": spacing if spacing >= 0 else None}
    if isinstance(layout, QStackedLayout):
        props["current"] = 0
    return props


def _direction(layout: QLayout) -> Qt.Orientation | None:
    kind = layout_kind(layout)
    if kind == "row":
        return Qt.Orientation.Horizontal
    if kind == "column":
        return Qt.Orientation.Vertical
    return None


def _item_node(item: QLayoutItem, item_id: str, ctx: Context) -> Node | None:
    if (widget := item.widget()) is not None:
        return ctx.build(widget)
    if (inner := item.layout()) is not None:
        return layout_node(inner, ctx)
    if item.spacerItem() is not None:
        return node(item_id, "spacer")
    return None


def _grow(layout: QLayout, index: int, item: QLayoutItem, n: Node):
    """Set ``grow`` (and a spacer's ``size``) from the layout's stretch and the item's policy."""
    direction = _direction(layout)
    if direction is None:
        return
    stretch = layout.stretch(index) if isinstance(layout, QBoxLayout) else 0
    # setFixedWidth/Height keeps an Expanding policy; Qt's layout honours the maximum instead.
    least, most = item.minimumSize(), item.maximumSize()
    fixed = (
        most.width() <= least.width()
        if direction == Qt.Orientation.Horizontal
        else most.height() <= least.height()
    )
    expands = bool(item.expandingDirections() & direction) and not fixed
    if stretch > 0:
        n["props"]["grow"] = stretch
    elif expands:
        n["props"]["grow"] = 1
    if n["kind"] == "spacer" and not expands and stretch == 0:
        hint = item.sizeHint()
        n["props"]["size"] = (
            hint.width() if direction == Qt.Orientation.Horizontal else hint.height()
        )


def layout_items(layout: QLayout, ctx: Context) -> list[Node]:
    """The layout's items as nodes, in the order and arrangement the container kind expects."""
    lid = ctx.node_id(layout)
    if isinstance(layout, QStackedLayout):
        current = layout.currentWidget()
        return [ctx.build(current)] if current is not None else []
    if isinstance(layout, QFormLayout):
        return _form_items(layout, lid, ctx)
    out: list[Node] = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None or (n := _item_node(item, f"{lid}.{i}", ctx)) is None:
            continue
        if isinstance(layout, QGridLayout):
            row, col, row_span, col_span = layout.getItemPosition(i)
            n["props"].update({"row": row, "col": col})
            if row_span > 1:
                n["props"]["rowSpan"] = row_span
            if col_span > 1:
                n["props"]["colSpan"] = col_span
        else:
            _grow(layout, i, item, n)
        out.append(n)
    return out


def _form_items(layout: QFormLayout, lid: str, ctx: Context) -> list[Node]:
    """A form's rows as alternating label and field nodes; a spanning row gets an empty label."""
    out: list[Node] = []
    roles = QFormLayout.ItemRole
    for row in range(layout.rowCount()):
        spanning = layout.itemAt(row, roles.SpanningRole)
        if spanning is not None:
            field = _item_node(spanning, f"{lid}.{row}.span", ctx)
            if field is not None:
                out += [node(f"{lid}.{row}.label", "spacer", {"size": 0}), field]
            continue
        label_item, field_item = (
            layout.itemAt(row, roles.LabelRole),
            layout.itemAt(row, roles.FieldRole),
        )
        label = (
            _item_node(label_item, f"{lid}.{row}.label", ctx) if label_item is not None else None
        )
        field = (
            _item_node(field_item, f"{lid}.{row}.field", ctx) if field_item is not None else None
        )
        if label is None and field is None:
            continue
        out.append(label or node(f"{lid}.{row}.label", "spacer", {"size": 0}))
        out.append(field or node(f"{lid}.{row}.field", "spacer", {"size": 0}))
    return out


def layout_node(layout: QLayout, ctx: Context) -> Node:
    """A layout nested in another (or owned by an adapted widget) as its own container node."""
    return node(
        ctx.node_id(layout), layout_kind(layout), layout_props(layout), layout_items(layout, ctx)
    )
