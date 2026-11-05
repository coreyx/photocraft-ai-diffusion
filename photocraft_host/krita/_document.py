"""Documents, layers, vector shapes and selections of the ``krita`` stand-in.

Each :class:`Document` keeps a local copy of its layer tree, filled from PhotoCraft's
``layer.tree`` and kept current by ``layers.changed`` events and by refetching after the shim's
own structural edits, so the many reads upstream makes (its layer poller runs every 500 ms) cost
nothing. Pixel and selection reads and every write go to PhotoCraft.

Krita's API names nodes by object identity and ``uniqueId()``; here each layer has one
:class:`Node` per document for its whole life, keyed by PhotoCraft's persistent layer uid.

Where Krita and PhotoCraft differ:

- A transparency mask is a child node in Krita and a layer mask in PhotoCraft. A layer with a
  mask shows it as a ``transparencymask`` child node, with a uid derived from the layer's.
- Krita applies visibility changes immediately and upstream hides layers briefly to read a
  composite without them. Here a visibility change is applied locally at once and sent to
  PhotoCraft on the next event loop turn; a change undone before then sends nothing, and a
  composite read leaves the locally hidden layers out. So that pattern adds no undo steps.
- ``removeChildNode`` followed by ``addChildNode`` of the same node is a move (as upstream uses
  it); a node removed and not re-added in the same turn is deleted.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QByteArray, QObject, QPointF, QRect, QTimer, QUuid
from PyQt6.QtGui import QImage

if TYPE_CHECKING:
    from ._app import _Host

#: PhotoCraft layer kinds as Krita node types.
_NODE_TYPES = {
    "pixel": "paintlayer",
    "group": "grouplayer",
    "shape": "filllayer",
    "text": "filllayer",
    "fill": "filllayer",
    "smart": "filelayer",
    "adjustment": "filterlayer",
    "video": "paintlayer",
}
#: Layer data marking a vector (pose) group, as PhotoCraft's ``vector.*`` methods set it.
_VECTOR_GROUP_KEY = "vector.group"
#: PhotoCraft's colour modes and depths as Krita's names.
_COLOR_MODELS = {"rgb": "RGBA", "grayscale": "GRAYA", "cmyk": "CMYKA", "lab": "LABA"}
_COLOR_DEPTHS = {"u8": "U8", "u16": "U16", "f32": "F32"}


#: Requests that only read the document. Any other request may change its pixels or selection,
#: so sending one clears the document's read cache.
_READS = frozenset({
    "pixels.read",
    "mask.read",
    "selection.read",
    "selection.bounds",
    "layer.tree",
    "layer.active",
    "layer.thumbnail",
    "layerData.get",
    "blob.get",
    "blob.list",
    "vector.shapes",
    "doc.info",
})
#: Most pixel reads kept per document (upstream reads the same few areas on every poll).
_CACHE_ENTRIES = 16
_UNREAD = object()


def _bytes(value: QByteArray | bytes | bytearray | memoryview) -> bytes:
    return value.data() if isinstance(value, QByteArray) else bytes(value)


def _rect(x: int, y: int, w: int, h: int) -> dict[str, int]:
    return {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}


def _mask_uid(layer_uid: str) -> str:
    """The uid of a layer's mask node: stable, and a valid UUID like the layer's own."""
    return str(uuid.uuid5(uuid.UUID(layer_uid), "transparencymask"))


def _tight_bounds(data: bytes, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    """Bounds of the non-zero bytes of a ``w`` x ``h`` coverage buffer placed at ``(x, y)``."""
    rows = [r for r in range(h) if any(data[r * w : (r + 1) * w])]
    if not rows:
        return 0, 0, 0, 0
    cols = [c for c in range(w) if any(data[r * w + c] for r in rows)]
    return x + cols[0], y + rows[0], cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1


class Node(QObject):
    """A layer (or the root, or a layer's mask) of a document."""

    def __init__(self, name: str = "layer", node_type: str = "paintlayer"):
        super().__init__()
        self._doc: Document | None = None
        self._uid: str | None = None
        self._name = name
        self._type = node_type
        self._parent: Node | None = None
        self._children: list[Node] = []
        self._visible = True
        self._host_visible = True
        self._locked = False
        self._blend = "normal"
        self._opacity = 1.0
        self._bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._animated = False
        self._has_mask = False
        self._is_mask = False
        self._kind = "pixel"
        self._pending: tuple[bytes, int, int, int, int] | None = None
        self._removing = False
        self._unique = QUuid.createUuid()

    # -- identity and tree

    def uniqueId(self) -> QUuid:
        return QUuid(self._uid) if self._uid else self._unique

    def name(self) -> str:
        return self._name

    def setName(self, name: str):
        if self._attached() and name != self._name:
            self._doc_or_fail().call("layer.update", {"uid": self._uid, "name": name})
        self._name = name

    def type(self) -> str:
        return self._type

    def parentNode(self) -> Node | None:
        return self._parent

    def childNodes(self) -> list[Node]:
        return list(self._children)

    def _attached(self) -> bool:
        return self._doc is not None and self._uid is not None

    def _doc_or_fail(self) -> Document:
        if self._doc is None:
            raise RuntimeError(f"layer '{self._name}' is not in a document")
        return self._doc

    def addChildNode(self, node: Node, above: Node | None) -> bool:
        """Put ``node`` in this group, directly above ``above`` (or on top)."""
        doc = self._doc_or_fail()
        placement: dict[str, Any] = {}
        if above is not None and above._uid:
            placement["above"] = above._uid
        if self._uid:
            placement["parent"] = self._uid
        if node._attached():
            node._removing = False
            doc.call("layer.move", {"uid": node._uid, **placement})
        elif node._is_mask:
            doc._add_mask(self, node)
        elif node._type == "vectorlayer":
            result = doc.call("layer.create", {"kind": "group", "name": node._name, **placement})
            node._uid = str(result["uid"])
            doc.call("layerData.set", {"uid": node._uid, "key": _VECTOR_GROUP_KEY, "value": "1"})
            doc._vector_groups.add(node._uid)
        elif node._pending is not None and node._type == "paintlayer":
            data, x, y, w, h = node._pending
            params = {"name": node._name, "rect": _rect(x, y, w, h), "format": "bgra8", **placement}
            result = doc.call("pixels.createLayer", params, data)
            node._uid = str(result["uid"])
        else:
            kind = "group" if node._type == "grouplayer" else "pixel"
            result = doc.call("layer.create", {"kind": kind, "name": node._name, **placement})
            node._uid = str(result["uid"])
        node._pending = None
        doc._adopt(node)
        doc._refresh()
        return True

    def removeChildNode(self, node: Node):
        """Take ``node`` out of this group: a move when it is added somewhere else in the same
        turn, else a deletion."""
        if not node._attached():
            return
        node._removing = True
        QTimer.singleShot(0, node._finish_removal)

    def _finish_removal(self):
        if self._removing and self._attached():
            self.remove()

    def remove(self):
        self._removing = False
        if not self._attached():
            return
        doc = self._doc_or_fail()
        if self._is_mask:
            # PhotoCraft has no "delete mask" request; hiding it everywhere is the closest.
            doc.call(
                "layer.addMask",
                {"uid": self._parent._uid if self._parent else None, "from": "image"},
                b"\xff" * (doc.width() * doc.height()),
            )
        else:
            doc.call("layer.delete", {"uid": self._uid})
        doc._refresh()

    # -- properties

    def visible(self) -> bool:
        return self._visible

    def setVisible(self, value: bool):
        self._visible = bool(value)
        if self._attached():
            self._doc_or_fail()._schedule_visibility(self)

    def locked(self) -> bool:
        return self._locked

    def setLocked(self, value: bool):
        if self._attached() and bool(value) != self._locked:
            self._doc_or_fail().call("layer.update", {"uid": self._uid, "locked": bool(value)})
        self._locked = bool(value)

    def opacity(self) -> int:
        return round(self._opacity * 255)

    def setOpacity(self, value: int):
        opacity = max(0.0, min(1.0, value / 255))
        if self._attached():
            self._doc_or_fail().call("layer.update", {"uid": self._uid, "opacity": opacity})
        self._opacity = opacity

    def blendingMode(self) -> str:
        return self._blend

    def setBlendingMode(self, mode: str):
        # Upstream sets a layer's own mode to make Krita redraw it; PhotoCraft redraws by itself.
        if mode == self._blend:
            return
        if self._attached():
            self._doc_or_fail().call("layer.update", {"uid": self._uid, "blend": mode})
        self._blend = mode

    def animated(self) -> bool:
        return self._animated

    def hasKeyframeAtTime(self, _time: int) -> bool:
        return False

    def colorDepth(self) -> str:
        """The depth of the pixels this node hands out: always 8-bit, because PhotoCraft
        converts to ``bgra8`` at the boundary whatever the document's own depth."""
        return "U8"

    def bounds(self) -> QRect:
        if self._is_mask and self._doc is not None:
            return QRect(0, 0, self._doc.width(), self._doc.height())
        return QRect(*self._bounds)

    # -- pixels

    def pixelData(self, x: int, y: int, w: int, h: int) -> QByteArray:
        """The layer's own pixels (bgra8), or a mask's coverage (one byte per pixel)."""
        if not self._attached():
            return QByteArray(bytes(w * h * (1 if self._is_mask else 4)))
        doc = self._doc_or_fail()
        if self._is_mask:
            parent = self._parent._uid if self._parent else None
            data = doc.read_pixels(
                "mask.read", {"uid": parent, "which": "layerMask", "rect": _rect(x, y, w, h)}
            )
            return QByteArray(data)
        source = {
            "kind": "group" if self._type in ("grouplayer", "vectorlayer") else "layer",
            "uid": self._uid,
        }
        data = doc.read_pixels(
            "pixels.read", {"source": source, "rect": _rect(x, y, w, h), "format": "bgra8"}
        )
        return QByteArray(data)

    def projectionPixelData(self, x: int, y: int, w: int, h: int) -> QByteArray:
        """The layer as it composites (for a group, its children together), bgra8."""
        return self.pixelData(x, y, w, h)

    def pixelDataAtTime(self, _x: int, _y: int, w: int, h: int, _time: int) -> QByteArray:
        return QByteArray(bytes(w * h * 4))

    def setPixelData(self, value: QByteArray | bytes, x: int, y: int, w: int, h: int) -> bool:
        """Write bgra8 pixels (a mask: coverage) into the rectangle."""
        data = _bytes(value)
        if not self._attached():
            self._pending = (data, x, y, w, h)
            return True
        doc = self._doc_or_fail()
        if self._is_mask:
            parent = self._parent
            if parent is not None:
                self._pending = (data, x, y, w, h)
                doc._add_mask(parent, self)
                self._pending = None
            return True
        doc.call(
            "pixels.write", {"uid": self._uid, "rect": _rect(x, y, w, h), "format": "bgra8"}, data
        )
        doc._refresh()
        return True

    def thumbnail(self, w: int, h: int) -> QImage:
        if not self._attached():
            return QImage(w, h, QImage.Format.Format_ARGB32)
        _, png = self._doc_or_fail().call_with_payload(
            "layer.thumbnail", {"uid": self._uid, "width": w, "height": h}
        )
        image = QImage.fromData(png)
        return image if not image.isNull() else QImage(w, h, QImage.Format.Format_ARGB32)


class Shape(QObject):
    """One element of a vector (pose) layer: a circle or a line."""

    def __init__(
        self,
        layer: VectorLayer | None = None,
        handle: str = "",
        element_id: str = "",
        svg: str = "",
    ):
        super().__init__()
        self._layer = layer
        self._handle = handle
        self._id = element_id
        self._svg = svg
        self._z = 0

    def name(self) -> str:
        return self._id

    def setName(self, name: str):
        if self._layer is not None and self._layer._doc is not None and self._handle:
            doc = self._layer._doc
            doc.call("layerData.set", {"uid": self._handle, "key": "vector.id", "value": name})
            doc.call("layer.update", {"uid": self._handle, "name": name})
        self._id = name

    def position(self) -> QPointF:
        """The top-left of the shape's box, in points (Krita's vector unit)."""

        def attr(name: str) -> float:
            match = re.search(rf'\s{name}="([-0-9.eE+]+)"', self._svg)
            return float(match.group(1)) if match else 0.0

        if self._svg.startswith("<circle"):
            x, y = attr("cx") - attr("r"), attr("cy") - attr("r")
        else:
            x, y = min(attr("x1"), attr("x2")), min(attr("y1"), attr("y2"))
        scale = 72.0 / (self._layer._doc.resolution() if self._layer and self._layer._doc else 72.0)
        return QPointF(x * scale, y * scale)

    def remove(self):
        if self._layer is not None and self._layer._doc is not None and self._handle:
            self._layer._doc.call(
                "vector.removeShapes", {"uid": self._layer._uid, "ids": [self._handle]}
            )
            self._layer._doc._refresh()

    def setZIndex(self, z: int):
        """Below the layer's other shapes when ``z`` is negative (upstream draws bones below
        joints). PhotoCraft's moves place a layer above another, so the shape goes above the
        bottom one, which then goes above it."""
        self._z = z
        layer = self._layer
        if z >= 0 or layer is None or layer._doc is None or not self._handle:
            return
        doc = layer._doc
        siblings = [c for c in layer._children if c._uid != self._handle]
        if not siblings:
            return
        bottom = siblings[0]._uid
        doc.call("layer.move", {"uid": self._handle, "parent": layer._uid, "above": bottom})
        doc.call("layer.move", {"uid": bottom, "parent": layer._uid, "above": self._handle})
        doc._refresh()

    def zIndex(self) -> int:
        return self._z


class VectorLayer(Node):
    """A vector (pose) layer: in PhotoCraft, a marked group of shape layers."""

    def __init__(self, name: str = "vector layer"):
        super().__init__(name, "vectorlayer")
        self._kind = "group"

    def shapes(self) -> list[Shape]:
        if not self._attached():
            return []
        result = self._doc_or_fail().call("vector.shapes", {"uid": self._uid})
        return [Shape(self, s["handle"], s["id"], s["svg"]) for s in result.get("shapes", [])]

    def addShapesFromSvg(self, svg: str) -> list[Shape]:
        """Add the SVG's circles and lines; returns the new shapes."""
        doc = self._doc_or_fail()
        before = {s._handle for s in self.shapes()}
        doc.call("vector.addSvg", {"uid": self._uid, "svg": svg})
        doc._refresh()
        return [s for s in self.shapes() if s._handle not in before]


class Selection(QObject):
    """A selection: 8-bit coverage over a rectangle."""

    def __init__(self, extent: tuple[int, int] | None = None):
        super().__init__()
        self._extent = extent
        self._x = self._y = self._w = self._h = 0
        self._data = b""

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h

    def _set(self, data: bytes, x: int, y: int, w: int, h: int):
        self._data, self._x, self._y, self._w, self._h = data, x, y, w, h

    def setPixelData(self, value: QByteArray | bytes, x: int, y: int, w: int, h: int):
        """Take ``w`` x ``h`` coverage at ``(x, y)``; the selection's bounds become those of its
        non-zero pixels, as in Krita."""
        data = _bytes(value)
        bx, by, bw, bh = _tight_bounds(data, x, y, w, h)
        self._set(bytes(self._crop(data, x, y, w, h, bx, by, bw, bh)), bx, by, bw, bh)

    @staticmethod
    def _crop(
        data: bytes, x: int, y: int, w: int, _h: int, cx: int, cy: int, cw: int, ch: int
    ) -> bytearray:
        out = bytearray(cw * ch)
        for row in range(ch):
            start = (cy - y + row) * w + (cx - x)
            out[row * cw : (row + 1) * cw] = data[start : start + cw]
        return out

    def pixelData(self, x: int, y: int, w: int, h: int) -> QByteArray:
        out = bytearray(w * h)
        x0, x1 = max(x, self._x), min(x + w, self._x + self._w)
        y0, y1 = max(y, self._y), min(y + h, self._y + self._h)
        for ry in range(y0, y1):
            src = (ry - self._y) * self._w + (x0 - self._x)
            dst = (ry - y) * w + (x0 - x)
            out[dst : dst + max(0, x1 - x0)] = self._data[src : src + max(0, x1 - x0)]
        return QByteArray(bytes(out))

    def duplicate(self) -> Selection:
        copy = Selection(self._extent)
        copy._set(self._data, self._x, self._y, self._w, self._h)
        return copy

    def invert(self):
        """Select what wasn't: over the document when known, else over the selection's box."""
        if self._extent is not None:
            w, h = self._extent
            current = _bytes(self.pixelData(0, 0, w, h))
            self._set(bytes(255 - v for v in current), 0, 0, w, h)
        else:
            self._set(bytes(255 - v for v in self._data), self._x, self._y, self._w, self._h)


class Document(QObject):
    """An open PhotoCraft document."""

    def __init__(self, host: _Host, info: dict[str, Any]):
        super().__init__()
        self._host = host
        self._id = str(info["doc"])
        self._info = info
        self._root = Node("root", "grouplayer")
        self._root._doc = self
        self._nodes: dict[str, Node] = {}
        self._active: str | None = None
        self._vector_groups: set[str] = set()
        self._plain_groups: set[str] = set()
        self._visibility_pending: set[str] = set()
        self._loaded = False
        self._pixel_cache: dict[str, bytes] = {}
        self._selection_cache: Any = _UNREAD

    # -- talking to PhotoCraft

    def call(self, method: str, params: dict[str, Any], payload: bytes = b"") -> Any:
        return self.call_with_payload(method, params, payload)[0]

    def call_with_payload(
        self, method: str, params: dict[str, Any], payload: bytes = b""
    ) -> tuple[Any, bytes]:
        if method not in _READS:
            self.invalidate()
        return self._host.call(method, {"doc": self._id, **params}, payload)

    def invalidate(self, selection: bool = True):
        """Forget cached pixels (and the selection): the document changed, or may have.

        Upstream reads the same areas many times a second (the live workspace polls every
        100 ms); between changes those reads are answered here. PhotoCraft's change events
        (``pixels.changed``, ``layers.changed``, ``selection.changed``) and every request that
        may change the document clear the cache.
        """
        self._pixel_cache.clear()
        if selection:
            self._selection_cache = _UNREAD

    def read_pixels(self, method: str, params: dict[str, Any]) -> bytes:
        """The payload of a pixel read, from the cache while nothing changed."""
        key = method + json.dumps(params, sort_keys=True)
        data = self._pixel_cache.get(key)
        if data is None:
            data = self.call_with_payload(method, params)[1]
            if len(self._pixel_cache) >= _CACHE_ENTRIES:
                self._pixel_cache.clear()
            self._pixel_cache[key] = data
        return data

    def _ensure(self):
        if not self._loaded:
            self._refresh()

    def _refresh(self):
        """Fetch the layer tree and active layer again (after a structural edit)."""
        self.update_tree(self.call("layer.tree", {}))
        active = self.call("layer.active", {})
        self._active = str(active) if active else None

    def update_tree(self, tree: list[dict[str, Any]]):
        """Bring the local tree in line with PhotoCraft's (``layer.tree`` / ``layers.changed``)."""
        self._loaded = True
        seen: set[str] = set()

        def build(parent: Node, infos: list[dict[str, Any]]) -> list[Node]:
            nodes = []
            for info in infos:
                uid = str(info["uid"])
                seen.add(uid)
                node = self._nodes.get(uid)
                if node is None:
                    vector = info.get("kind") == "group" and self._is_vector_group(uid)
                    node = VectorLayer(info["name"]) if vector else Node(info["name"])
                    node._uid, node._doc = uid, self
                    self._nodes[uid] = node
                node._name = info["name"]
                node._kind = info.get("kind", "pixel")
                if not isinstance(node, VectorLayer):
                    node._type = _NODE_TYPES.get(node._kind, "paintlayer")
                node._host_visible = bool(info.get("visible", True))
                if uid not in self._visibility_pending:
                    node._visible = node._host_visible
                node._locked = bool(info.get("locked", False))
                node._opacity = float(info.get("opacity", 1.0))
                node._blend = str(info.get("blend", "normal"))
                node._animated = bool(info.get("animated", False))
                b = info.get("bounds") or {}
                node._bounds = (
                    int(b.get("x", 0)),
                    int(b.get("y", 0)),
                    int(b.get("width", 0)),
                    int(b.get("height", 0)),
                )
                node._parent = parent
                node._has_mask = bool(info.get("hasMask", False))
                children = build(node, info.get("children", []))
                if node._has_mask:
                    children.insert(0, self._mask_node(node))
                node._children = children
                nodes.append(node)
            return nodes

        self._root._children = build(self._root, tree)
        for uid in list(self._nodes):
            if uid not in seen and not self._nodes[uid]._is_mask:
                gone = self._nodes.pop(uid)
                gone._doc, gone._parent = None, None
        self._nodes = {
            uid: n
            for uid, n in self._nodes.items()
            if not n._is_mask or (n._parent and n._parent._uid in seen and n._parent._has_mask)
        }

    def _is_vector_group(self, uid: str) -> bool:
        """Whether the group ``uid`` is a vector (pose) layer: asked once per group."""
        if uid not in self._vector_groups and uid not in self._plain_groups:
            value = (self.call("layerData.get", {"uid": uid, "key": _VECTOR_GROUP_KEY}) or {}).get(
                "value"
            )
            (self._vector_groups if value else self._plain_groups).add(uid)
        return uid in self._vector_groups

    def _mask_node(self, layer: Node) -> Node:
        assert layer._uid is not None
        uid = _mask_uid(layer._uid)
        mask = self._nodes.get(uid)
        if mask is None:
            mask = Node(f"{layer._name} Mask", "transparencymask")
            mask._uid, mask._doc, mask._is_mask = uid, self, True
            self._nodes[uid] = mask
        mask._parent = layer
        return mask

    def _adopt(self, node: Node):
        node._doc = self
        if node._uid:
            self._nodes[node._uid] = node

    def _add_mask(self, parent: Node, mask: Node):
        """Give ``parent`` the mask's pending coverage as its layer mask."""
        w, h = self.width(), self.height()
        canvas = bytearray(w * h)
        if mask._pending is not None:
            data, x, y, mw, mh = mask._pending
            for row in range(mh):
                cy = y + row
                if 0 <= cy < h:
                    for col in range(mw):
                        cx = x + col
                        if 0 <= cx < w:
                            canvas[cy * w + cx] = data[row * mw + col]
        self.call("layer.addMask", {"uid": parent._uid, "from": "image"}, bytes(canvas))
        mask._pending = None
        if parent._uid:
            mask._uid, mask._doc, mask._is_mask = _mask_uid(parent._uid), self, True
            self._nodes[mask._uid] = mask

    def _schedule_visibility(self, node: Node):
        if node._uid is None:
            return
        if node._visible == node._host_visible:
            self._visibility_pending.discard(node._uid)
            return
        if not self._visibility_pending:
            QTimer.singleShot(0, self._flush_visibility)
        self._visibility_pending.add(node._uid)

    def _flush_visibility(self):
        pending, self._visibility_pending = self._visibility_pending, set()
        for uid in pending:
            node = self._nodes.get(uid)
            if node is not None and node._visible != node._host_visible:
                self.call("layer.update", {"uid": uid, "visible": node._visible})
                node._host_visible = node._visible

    # -- the document

    def width(self) -> int:
        return int(self._info.get("width", 0))

    def height(self) -> int:
        return int(self._info.get("height", 0))

    def resolution(self) -> float:
        return float(self._info.get("dpi", 72.0))

    def colorModel(self) -> str:
        return _COLOR_MODELS.get(
            str(self._info.get("mode", "rgb")), str(self._info.get("mode", "")).upper()
        )

    def colorDepth(self) -> str:
        return _COLOR_DEPTHS.get(str(self._info.get("depth", "u8")), "U8")

    def fileName(self) -> str:
        return str(self._info.get("path") or "")

    def name(self) -> str:
        return str(self._info.get("name", ""))

    def rootNode(self) -> Node:
        self._ensure()
        return self._root

    def activeNode(self) -> Node | None:
        self._ensure()
        return self._nodes.get(self._active) if self._active else None

    def setActiveNode(self, node: Node):
        if node._uid and not node._is_mask:
            self.call("layer.setActive", {"uid": node._uid})
            self._active = node._uid

    def nodeByUniqueID(self, uid: QUuid) -> Node | None:
        self._ensure()
        return self._nodes.get(uid.toString().strip("{}"))

    def createNode(self, name: str, node_type: str) -> Node:
        node = Node(name, node_type)
        node._doc = self
        return node

    def createVectorLayer(self, name: str) -> VectorLayer:
        node = VectorLayer(name)
        node._doc = self
        return node

    def createGroupLayer(self, name: str) -> Node:
        return self.createNode(name, "grouplayer")

    def createTransparencyMask(self, name: str) -> Node:
        node = self.createNode(name, "transparencymask")
        node._is_mask = True
        return node

    def selection(self) -> Selection | None:
        """A copy of the selection (read once until it changes)."""
        if self._selection_cache is _UNREAD:
            self._selection_cache = self._read_selection()
        cached = self._selection_cache
        return cached.duplicate() if cached is not None else None

    def _read_selection(self) -> Selection | None:
        bounds = (self.call("selection.bounds", {}) or {}).get("bounds")
        if not bounds:
            return None
        x, y, w, h = int(bounds["x"]), int(bounds["y"]), int(bounds["width"]), int(bounds["height"])
        _, data = self.call_with_payload("selection.read", {"rect": _rect(x, y, w, h)})
        selection = Selection((self.width(), self.height()))
        selection._set(data, x, y, w, h)
        return selection

    def setSelection(self, selection: Selection | None):
        if selection is None or selection.width() == 0:
            self.call("selection.set", {"clear": True})
            return
        rect = _rect(selection.x(), selection.y(), selection.width(), selection.height())
        self.call(
            "selection.set",
            {"rect": rect},
            _bytes(
                selection.pixelData(
                    selection.x(), selection.y(), selection.width(), selection.height()
                )
            ),
        )

    def pixelData(self, x: int, y: int, w: int, h: int) -> QByteArray:
        """The composite (bgra8), without PhotoCraft's transient preview and without the layers
        hidden locally and not yet sent."""
        exclude = [
            uid
            for uid in self._visibility_pending
            if (n := self._nodes.get(uid)) is not None and not n._visible
        ]
        params: dict[str, Any] = {
            "source": {"kind": "composite"},
            "rect": _rect(x, y, w, h),
            "format": "bgra8",
        }
        if exclude:
            params["exclude"] = exclude
        return QByteArray(self.read_pixels("pixels.read", params))

    def showPreview(self, data: QByteArray | bytes, x: int, y: int, w: int, h: int, label: str):
        """Show a preview image over the document without adding it to the document (no layer,
        no undo step, never saved): PhotoCraft's transient preview (design D4). Not in Krita's
        API; upstream calls it where Krita would create a locked ``[Preview]`` layer."""
        self.call(
            "preview.show",
            {"label": label, "rect": _rect(x, y, w, h), "format": "bgra8"},
            _bytes(data),
        )

    def hidePreview(self):
        self.call("preview.hide", {})

    def refreshProjection(self):
        """Nothing to do: PhotoCraft composites by itself."""

    def scaleImage(self, w: int, h: int, xres: float, _yres: float, _strategy: str) -> bool:
        self.call("doc.resizeImage", {"width": int(w), "height": int(h), "dpi": float(xres)})
        self._info = self.call("doc.info", {})
        self._refresh()
        return True

    def resizeImage(self, _x: int, _y: int, w: int, h: int) -> bool:
        self.call("doc.resizeCanvas", {"width": int(w), "height": int(h), "anchor": "topLeft"})
        self._info = self.call("doc.info", {})
        self._refresh()
        return True

    def annotation(self, key: str) -> QByteArray:
        result, data = self.call_with_payload("blob.get", {"name": key})
        return QByteArray(data) if result and result.get("found") else QByteArray()

    def setAnnotation(self, key: str, _description: str, data: QByteArray | bytes):
        self.call("blob.set", {"name": key}, _bytes(data))

    def removeAnnotation(self, key: str):
        self.call("blob.delete", {"name": key})

    # Animation is deferred (design D2): one frame, no timeline.
    def currentTime(self) -> int:
        return 0

    def playBackStartTime(self) -> int:
        return 0

    def playBackEndTime(self) -> int:
        return 0

    def importAnimation(self, _files: list[str], _offset: int, _step: int) -> bool:
        return False
