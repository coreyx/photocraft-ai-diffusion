"""The Qt mirror: sends a live Qt widget tree to PhotoCraft as a panel or a dialog window, keeps it
current with patches, and plays the user's input back into the widgets (design D7, REQ-14.0.1).

Every widget and layout gets a node id that stays with it for its lifetime (a Qt property, so
it survives PyQt handing out a new wrapper for the same object). A flush builds the tree again
and sends the difference from the last tree sent; only widgets that changed produce patches.

Some nodes stand for no widget of their own: a menu entry, a pop-up, the grid inside a list
with overlay buttons. Adapters register an input handler for those (:meth:`Mirror.handle`).
Menus upstream opens with ``QMenu.exec()`` while handling the user's input are shown as pop-ups
anchored to the widget that was used (:mod:`.menus`).
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QIcon, QImage, QPixmap, QTextDocumentFragment
from PyQt6.QtWidgets import QLayout, QMenu, QWidget

from . import menus, tracker
from .adapters import Input, adapter_for
from .adapters.base import might_be_rich
from .adapters.display import FrameAdapter
from .images import ImageCache
from .layouts import layout_items, layout_kind, layout_node, layout_props
from .tree import Node, diff, node, wire

log = logging.getLogger(__name__)

#: How long a change waits before it is sent, gathering what changes with it (one frame).
FLUSH_MS = 16
#: How often the tree is compared anyway, for changes nothing announced.
POLL_MS = 500
#: Width a panel's widgets are laid out at in Qt (a docker's), for widgets sent as images.
PANEL_WIDTH = 360

_ids = itertools.count(1)

#: The requests and events of each kind of surface: a dock panel or a dialog window.
_SURFACES = {
    "panel": {
        "key": "panelId",
        "open": "panel.register",
        "patch": "panel.patch",
        "close": "panel.unregister",
        "input": "panel.input",
    },
    "dialog": {
        "key": "dialogId",
        "open": "dialog.open",
        "patch": "dialog.patch",
        "close": "dialog.close",
        "input": "dialog.input",
    },
}


def _managed(layout: QLayout) -> set[int]:
    """Ids of the widgets a layout (and the layouts nested in it) places."""
    found: set[int] = set()
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if (w := item.widget()) is not None:
            found.add(id(w))
        elif (inner := item.layout()) is not None:
            found |= _managed(inner)
    return found


def unmanaged_children(widget: QWidget, layout: QLayout) -> list[QWidget]:
    """Child widgets of ``widget`` its layout doesn't place: widgets upstream moves over it."""
    managed = _managed(layout)
    return [
        child
        for child in widget.children()
        if isinstance(child, QWidget)
        and id(child) not in managed
        and not child.isWindow()
        and not child.objectName().startswith("qt_")
    ]


def _tooltip(widget: QWidget) -> str | None:
    tip = widget.toolTip()
    if not tip:
        return None
    if might_be_rich(tip):
        return QTextDocumentFragment.fromHtml(tip).toPlainText()
    return tip


def dialog_size(dialog: QWidget) -> dict[str, int]:
    """The size PhotoCraft opens a dialog at: the larger of its Qt size and size hint, so a
    dialog its code resized keeps that size and one laid out only by its layout still fits.
    Its minimum size goes too, when the dialog's code set one."""
    size, hint, minimum = dialog.size(), dialog.sizeHint(), dialog.minimumSize()
    out = {"width": max(size.width(), hint.width()), "height": max(size.height(), hint.height())}
    # A shown dialog's layout gives it a minimum of its own, measured with Qt's fonts; only one
    # its code set says something PhotoCraft's layout doesn't work out by itself.
    layout = dialog.layout()
    from_layout = layout is not None and minimum == layout.totalMinimumSize()
    if minimum.width() > 0 and minimum.height() > 0 and not from_layout:
        out.update(minWidth=minimum.width(), minHeight=minimum.height())
    return out


class Mirror(QObject):
    """Mirrors ``root`` (and everything inside it) into the PhotoCraft panel ``surface_id``, or
    a dialog window when ``surface="dialog"``."""

    def __init__(
        self,
        root: QWidget,
        transport: Any,
        surface_id: str,
        title: str,
        *,
        surface: str = "panel",
        icon: str | None = None,
        modal: bool = False,
        on_closed: Callable[[], None] | None = None,
        flush_ms: int = FLUSH_MS,
        poll_ms: int = POLL_MS,
    ):
        super().__init__()
        self.root = root
        self.surface_id = surface_id
        self.title = title
        self._surface = _SURFACES[surface]
        self._is_dialog = surface == "dialog"
        self._icon = icon
        self._modal = modal
        self._on_closed = on_closed
        self._transport = transport
        self._images = ImageCache(transport)
        self._filter = tracker.ChangeFilter(self.mark_dirty)
        self._tracked: set[str] = set()
        self._widgets: dict[str, QWidget] = {}
        self._handlers: dict[str, Callable[[Input], None]] = {}
        self._menus: dict[str, QMenu] = {}
        self._sent: Node | None = None
        self._force: set[str] = set()
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(flush_ms)
        self._flush_timer.timeout.connect(self.flush)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(poll_ms)
        self._poll_timer.timeout.connect(self.flush)

    @property
    def panel_id(self) -> str:
        return self.surface_id

    # -- lifecycle

    def start(self):
        """Open the panel or dialog with the whole tree, then follow changes and input."""
        from . import install

        install()
        if not self._is_dialog and self.root.isWindow() and not self.root.isVisible():
            # Laid out and shown off screen, as a docker is in Krita: widgets drawn as images
            # need a size, and upstream asks isVisible() in places.
            hint = self.root.sizeHint()
            self.root.resize(max(PANEL_WIDTH, hint.width()), max(hint.height(), 200))
            self.root.show()
        tracker.register(self)
        tree = self.build_tree()
        params: dict[str, Any] = {
            self._surface["key"]: self.surface_id,
            "title": self.title,
            "tree": wire(tree),
        }
        if self._icon:
            params["icon"] = self._icon
        if self._is_dialog:
            params["modal"] = self._modal
            params.update(dialog_size(self.root))
        self._transport.call(self._surface["open"], params)
        self._sent = tree
        self._transport.on(self._surface["input"], self._on_input)
        if self._is_dialog:
            self._transport.on("dialog.closed", self._on_dialog_closed)
        self._poll_timer.start()

    def stop(self):
        """Remove the panel or close the dialog, and stop following the widgets."""
        self._poll_timer.stop()
        self._flush_timer.stop()
        self._transport.off(self._surface["input"], self._on_input)
        if self._is_dialog:
            self._transport.off("dialog.closed", self._on_dialog_closed)
        tracker.unregister(self)
        if self._sent is not None:
            self._sent = None
            if not self._transport.is_closed:
                self._transport.call(
                    self._surface["close"], {self._surface["key"]: self.surface_id}
                )

    def mark_dirty(self):
        if self._sent is not None and not self._flush_timer.isActive():
            self._flush_timer.start()

    def flush(self):
        """Send what changed since the last flush, as one patch."""
        if self._sent is None:
            return
        tree = self.build_tree()
        ops = diff(self._sent, tree, self._force)
        self._force.clear()
        if ops:
            self._transport.call(
                self._surface["patch"], {self._surface["key"]: self.surface_id, "ops": ops}
            )
        self._sent = tree

    @property
    def tree(self) -> Node | None:
        """The tree as PhotoCraft last received it."""
        return self._sent

    def widget(self, node_id: str) -> QWidget | None:
        """The widget a node id stands for, as of the last flush."""
        return self._widgets.get(node_id)

    # -- building the tree

    def build_tree(self) -> Node:
        self._widgets = {}
        self._handlers = {}
        tree = self.build(self.root)
        for anchor, menu in list(self._menus.items()):
            tree["children"].append(
                menus.popup_node(self, anchor, menu, lambda a=anchor: self.close_menu(a))
            )
        return tree

    def node_id(self, obj: QObject) -> str:
        nid = obj.property(tracker.ID_PROPERTY)
        if not nid:
            prefix = "l" if isinstance(obj, QLayout) else "w"
            nid = f"{prefix}{next(_ids)}"
            obj.setProperty(tracker.ID_PROPERTY, nid)
        return str(nid)

    def build(self, widget: QWidget, shown: bool = False) -> Node:
        """The node for ``widget``, with its content unless it is hidden. ``shown`` builds a
        widget Qt only shows on demand (a pop-up's content) as visible."""
        nid = self.node_id(widget)
        self._widgets[nid] = widget
        adapter = adapter_for(widget)
        if nid not in self._tracked:
            self._tracked.add(nid)
            widget.installEventFilter(self._filter)
            if adapter is not None:
                adapter.connect(widget, self.mark_dirty)
        layout = widget.layout()
        if adapter is not None:
            kind = adapter.kind_of(widget)
            props = adapter.props(widget, self)
        elif layout is not None:
            kind, props = layout_kind(layout), layout_props(layout)
        else:
            kind, props = "column", {}
        # The root is shown whenever PhotoCraft shows the panel; a top-level widget Qt has never
        # shown counts as hidden, so only the widgets inside it are asked.
        hidden = widget.isHidden() and widget is not self.root and not shown
        props.update({
            "tooltip": _tooltip(widget),
            "enabled": None if widget.isEnabled() else False,
            "visible": False if hidden else None,
        })
        if hidden:
            return node(nid, kind, props)
        if adapter is not None:
            children = adapter.children(widget, self)
        elif layout is not None:
            children = layout_items(layout, self)
        else:
            children = []
        if layout is not None and (adapter is None or isinstance(adapter, FrameAdapter)):
            if extra := unmanaged_children(widget, layout):
                # Placed over the container rather than in its layout (a prompt's translation
                # badge): sent in a row after the layout's content.
                children.append(node(f"{nid}.overlay", "row", {}, [self.build(w) for w in extra]))
        return node(nid, kind, props, children)

    def layout_node(self, layout: QLayout) -> Node:
        return layout_node(layout, self)

    def icon(self, icon: QIcon | None, size: int | None = None) -> str | None:
        return self._images.icon(icon, size) if size else self._images.icon(icon)

    def image(self, picture: QPixmap | QImage) -> str:
        return self._images.image(picture)

    def call(self, method: str, params: dict[str, Any]) -> Any:
        return self._transport.call(method, params)[0]

    def handle(self, node_id: str, handler: Callable[[Input], None]):
        """Route input on ``node_id`` (a node with no widget of its own) to ``handler``, until
        the next flush rebuilds the tree."""
        self._handlers[node_id] = handler

    # -- menus opened with QMenu.exec()

    def open_menu(self, anchor: str, menu: QMenu):
        """Show ``menu`` as a pop-up under the node ``anchor``."""
        menu.aboutToShow.emit()
        self._menus[anchor] = menu
        self.mark_dirty()

    def close_menu(self, anchor: str):
        menu = self._menus.pop(anchor, None)
        if menu is not None:
            menu.aboutToHide.emit()
        self.mark_dirty()

    # -- input

    def _on_input(self, data: dict[str, Any], _payload: bytes):
        if data.get(self._surface["key"], data.get("owner")) != self.surface_id:
            return
        node_id = str(data.get("nodeId", ""))
        event = Input(
            str(data.get("kind", "")), data.get("value"), dict(data.get("modifiers") or {})
        )
        handler = self._handlers.get(node_id)
        widget = self._widgets.get(node_id)
        if handler is None and widget is None:
            return
        self._force.add(node_id)
        self.mark_dirty()
        with menus.anchored(self, node_id):
            try:
                if handler is not None:
                    handler(event)
                    return
                assert widget is not None
                adapter = adapter_for(widget)
                if adapter is None or not widget.isEnabled():
                    return  # shown again as it is
                adapter.apply(widget, event, self)
            except Exception:
                log.exception("input %s on %s failed", event.kind, node_id)

    def _on_dialog_closed(self, data: dict[str, Any], _payload: bytes):
        if data.get("dialogId") != self.surface_id:
            return
        self._sent = None  # PhotoCraft closed it already
        self.stop()
        if self._on_closed is not None:
            self._on_closed()
