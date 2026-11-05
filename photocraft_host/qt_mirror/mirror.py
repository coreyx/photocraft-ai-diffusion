"""The Qt mirror: sends a live Qt widget tree to PhotoCraft as a panel, keeps it current with
patches, and plays the user's input back into the widgets (design D7, REQ-14.0.1).

Every widget and layout gets a node id that stays with it for its lifetime (a Qt property, so
it survives PyQt handing out a new wrapper for the same object). A flush builds the tree again
and sends the difference from the last tree sent; only widgets that changed produce patches.
"""

from __future__ import annotations

import itertools
import logging
from typing import Any

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QIcon, QImage, QPixmap, QTextDocumentFragment
from PyQt6.QtWidgets import QLayout, QWidget

from . import tracker
from .adapters import Input, adapter_for
from .adapters.base import might_be_rich
from .images import ImageCache
from .layouts import layout_items, layout_kind, layout_node, layout_props
from .tree import Node, diff, node, wire

log = logging.getLogger(__name__)

#: How long a change waits before it is sent, gathering what changes with it (one frame).
FLUSH_MS = 16
#: How often the tree is compared anyway, for changes nothing announced.
POLL_MS = 500

_ids = itertools.count(1)


def _tooltip(widget: QWidget) -> str | None:
    tip = widget.toolTip()
    if not tip:
        return None
    if might_be_rich(tip):
        return QTextDocumentFragment.fromHtml(tip).toPlainText()
    return tip


class Mirror(QObject):
    """Mirrors ``root`` (and everything inside it) into the PhotoCraft panel ``panel_id``."""

    def __init__(
        self,
        root: QWidget,
        transport: Any,
        panel_id: str,
        title: str,
        *,
        icon: str | None = None,
        flush_ms: int = FLUSH_MS,
        poll_ms: int = POLL_MS,
    ):
        super().__init__()
        self.root = root
        self.panel_id = panel_id
        self.title = title
        self._icon = icon
        self._transport = transport
        self._images = ImageCache(transport)
        self._filter = tracker.ChangeFilter(self.mark_dirty)
        self._tracked: set[str] = set()
        self._widgets: dict[str, QWidget] = {}
        self._sent: Node | None = None
        self._force: set[str] = set()
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(flush_ms)
        self._flush_timer.timeout.connect(self.flush)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(poll_ms)
        self._poll_timer.timeout.connect(self.flush)

    # -- lifecycle

    def start(self):
        """Register the panel with the whole tree, then follow changes and input."""
        tracker.register(self)
        tree = self.build_tree()
        params: dict[str, Any] = {"panelId": self.panel_id, "title": self.title, "tree": wire(tree)}
        if self._icon:
            params["icon"] = self._icon
        self._transport.call("panel.register", params)
        self._sent = tree
        self._transport.on("panel.input", self._on_input)
        self._poll_timer.start()

    def stop(self):
        """Remove the panel and stop following the widgets."""
        self._poll_timer.stop()
        self._flush_timer.stop()
        self._transport.off("panel.input", self._on_input)
        tracker.unregister(self)
        if self._sent is not None:
            self._transport.call("panel.unregister", {"panelId": self.panel_id})
            self._sent = None

    def mark_dirty(self):
        if self._sent is not None and not self._flush_timer.isActive():
            self._flush_timer.start()

    def flush(self):
        """Send what changed since the last flush, as one ``panel.patch``."""
        if self._sent is None:
            return
        tree = self.build_tree()
        ops = diff(self._sent, tree, self._force)
        self._force.clear()
        if ops:
            self._transport.call("panel.patch", {"panelId": self.panel_id, "ops": ops})
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
        return self.build(self.root)

    def node_id(self, obj: QObject) -> str:
        nid = obj.property(tracker.ID_PROPERTY)
        if not nid:
            prefix = "l" if isinstance(obj, QLayout) else "w"
            nid = f"{prefix}{next(_ids)}"
            obj.setProperty(tracker.ID_PROPERTY, nid)
        return str(nid)

    def build(self, widget: QWidget) -> Node:
        """The node for ``widget``, with its content unless it is hidden."""
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
        hidden = widget.isHidden() and widget is not self.root
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
        return node(nid, kind, props, children)

    def layout_node(self, layout: QLayout) -> Node:
        return layout_node(layout, self)

    def icon(self, icon: QIcon | None) -> str | None:
        return self._images.icon(icon)

    def image(self, picture: QPixmap | QImage) -> str:
        return self._images.image(picture)

    def call(self, method: str, params: dict[str, Any]) -> Any:
        return self._transport.call(method, params)[0]

    # -- input

    def _on_input(self, data: dict[str, Any], _payload: bytes):
        if data.get("owner") != self.panel_id:
            return
        node_id = str(data.get("nodeId", ""))
        widget = self._widgets.get(node_id)
        if widget is None:
            return
        self._force.add(node_id)
        self.mark_dirty()
        adapter = adapter_for(widget)
        if adapter is None or not widget.isEnabled():
            return  # shown again as it is
        event = Input(
            str(data.get("kind", "")), data.get("value"), dict(data.get("modifiers") or {})
        )
        try:
            adapter.apply(widget, event, self)
        except Exception:
            log.exception("input %s on %s (%s) failed", event.kind, node_id, type(widget).__name__)
