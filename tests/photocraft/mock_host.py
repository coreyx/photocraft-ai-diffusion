"""An in-process stand-in for PhotoCraft, speaking the process plug-in protocol over pipes.

Tests connect a :class:`photocraft_host.transport.Transport` to a :class:`MockHost` and drive the
plug-in as PhotoCraft would, without PhotoCraft:

- the host answers the plug-in's requests on its own thread from an in-memory model of the open
  documents (layers with bgra8 pixels, selection, blobs, layer data), and records the panels,
  actions, notices, progress and other UI requests it receives;
- tests send events (:meth:`MockHost.send_event`) and host requests such as ``ping`` and
  ``shutdown`` (:meth:`MockHost.request`), and read what the plug-in asked for
  (:attr:`MockHost.calls`).

Only what the tests need is modelled: pixels are 8-bit sRGB (``bgra8``/``rgba8``), and colour
conversion, compositing beyond "top visible pixel wins" and file formats are left out.
"""

from __future__ import annotations

import copy
import itertools
import os
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QImage

from photocraft_host import transport

#: What the mock answers ``hello`` with.
HOST_VERSION = "0.20.1-mock"


@dataclass
class MockLayer:
    """A layer of a mock document: its pixels (``bgra8`` over the whole canvas) and properties."""

    name: str
    kind: str = "pixel"
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    blend: str = "normal"
    pixels: bytearray | None = None
    children: list[MockLayer] = field(default_factory=list)
    data: dict[str, str] = field(default_factory=dict)
    mask: bytearray | None = None

    def info(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "name": self.name,
            "kind": self.kind,
            "visible": self.visible,
            "locked": self.locked,
            "opacity": self.opacity,
            "blend": self.blend,
            "bounds": {"x": 0, "y": 0, "width": 0, "height": 0},
            "hasMask": self.mask is not None,
            "animated": False,
            "children": [c.info() for c in self.children],
        }


@dataclass
class MockDocument:
    """An open mock document."""

    id: str
    name: str
    width: int
    height: int
    layers: list[MockLayer] = field(default_factory=list)
    active_layer: str | None = None
    selection: bytearray | None = None
    blobs: dict[str, bytes] = field(default_factory=dict)
    path: str | None = None
    dpi: float = 72.0
    #: PhotoCraft's colour mode and depth names (``"rgb"``, ``"cmyk"``...; ``"u8"``, ``"u16"``, ``"f32"``).
    mode: str = "rgb"
    depth: str = "u8"

    def bounds(self, layer: MockLayer) -> tuple[int, int, int, int]:
        """Content bounds: the box of non-transparent pixels, or the union of the children's."""
        if layer.children:
            boxes = [b for b in (self.bounds(c) for c in layer.children) if b[2] and b[3]]
            if not boxes:
                return 0, 0, 0, 0
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
            return x0, y0, x1 - x0, y1 - y0
        if layer.pixels is None:
            return 0, 0, 0, 0
        alpha = layer.pixels[3::4]
        rows = [y for y in range(self.height) if any(alpha[y * self.width : (y + 1) * self.width])]
        if not rows:
            return 0, 0, 0, 0
        cols = [x for x in range(self.width) if any(alpha[y * self.width + x] for y in rows)]
        return cols[0], rows[0], cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1

    def info(self, layer: MockLayer) -> dict[str, Any]:
        info = layer.info()
        x, y, w, h = self.bounds(layer)
        info["bounds"] = {"x": x, "y": y, "width": w, "height": h}
        info["children"] = [self.info(c) for c in layer.children]
        return info

    def walk(self) -> list[tuple[MockLayer | None, MockLayer]]:
        """Every layer with its parent group, bottom to top, depth first."""
        out: list[tuple[MockLayer | None, MockLayer]] = []

        def visit(parent: MockLayer | None, layers: list[MockLayer]):
            for layer in layers:
                out.append((parent, layer))
                visit(layer, layer.children)

        visit(None, self.layers)
        return out

    def find(self, uid: str) -> MockLayer:
        for _, layer in self.walk():
            if layer.uid == uid:
                return layer
        raise _Refused("notFound", f"no layer '{uid}'")

    def find_or_none(self, uid: str) -> MockLayer | None:
        return next((layer for _, layer in self.walk() if layer.uid == uid), None)

    def siblings(self, uid: str) -> list[MockLayer]:
        for parent, layer in self.walk():
            if layer.uid == uid:
                return parent.children if parent else self.layers
        raise _Refused("notFound", f"no layer '{uid}'")


def find_widget(root: dict, node_id: str) -> dict | None:
    """The node ``node_id`` in a widget tree, or ``None``."""
    if root["id"] == node_id:
        return root
    for child in root.get("children", []):
        if (hit := find_widget(child, node_id)) is not None:
            return hit
    return None


def _take_widget(root: dict, node_id: str) -> dict | None:
    children = root.get("children", [])
    for i, child in enumerate(children):
        if child["id"] == node_id:
            return children.pop(i)
        if (hit := _take_widget(child, node_id)) is not None:
            return hit
    return None


def _check_ids(root: dict):
    seen: set[str] = set()
    stack = [root]
    while stack:
        n = stack.pop()
        if n["id"] in seen:
            raise _Refused("invalid", f"duplicate widget id '{n['id']}'")
        seen.add(n["id"])
        stack.extend(n.get("children", []))


def apply_patches(root: dict, ops: list[dict]) -> dict:
    """Apply ``panel.patch`` operations as PhotoCraft does: all of them or none."""
    root = copy.deepcopy(root)
    for op in ops:
        kind = op["op"]
        if kind == "replace":
            root = copy.deepcopy(op["node"])
        elif kind == "set":
            target = find_widget(root, op["id"])
            if target is None:
                raise _Refused("invalid", f"no widget '{op['id']}'")
            props = target.setdefault("props", {})
            for key, value in op["props"].items():
                if value is None:
                    props.pop(key, None)
                else:
                    props[key] = value
        elif kind == "insert":
            parent = find_widget(root, op["parent"])
            if parent is None:
                raise _Refused("invalid", f"no widget '{op['parent']}'")
            children = parent.setdefault("children", [])
            children.insert(min(op["index"], len(children)), copy.deepcopy(op["node"]))
        elif kind == "remove":
            if root["id"] == op["id"] or _take_widget(root, op["id"]) is None:
                raise _Refused("invalid", f"can't remove '{op['id']}'")
        elif kind == "move":
            moved = _take_widget(root, op["id"])
            parent = find_widget(root, op["parent"])
            if moved is None or parent is None:
                raise _Refused("invalid", f"can't move '{op['id']}' into '{op['parent']}'")
            children = parent.setdefault("children", [])
            children.insert(min(op["index"], len(children)), moved)
        else:
            raise _Refused("invalid", f"unknown patch '{kind}'")
    _check_ids(root)
    return root


class _Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _rect(p: dict) -> tuple[int, int, int, int]:
    r = p.get("rect") or {}
    x, y, w, h = (
        int(r.get("x", 0)),
        int(r.get("y", 0)),
        int(r.get("width", 0)),
        int(r.get("height", 0)),
    )
    if w <= 0 or h <= 0:
        raise _Refused("invalid", "the rectangle is empty")
    return x, y, w, h


def _swap(px: bytes) -> bytes:
    """bgra8 <-> rgba8."""
    out = bytearray(px)
    out[0::4], out[2::4] = px[2::4], px[0::4]
    return bytes(out)


class MockHost:
    """PhotoCraft's side of a connection, run on its own thread."""

    def __init__(self, nonce: str = "test-nonce"):
        self.nonce = nonce
        self.docs: dict[str, MockDocument] = {}
        self.active_doc: str | None = None
        self.calls: list[tuple[str, Any]] = []
        self.panels: dict[str, dict] = {}
        self.actions: dict[str, dict] = {}
        self.notices: list[dict] = []
        #: URLs the plug-in asked PhotoCraft to open (``open.url``).
        self.opened: list[str] = []
        #: Packages the plug-in asked PhotoCraft to update it to (plugin.update).
        self.updates: list[str] = []
        self.progress: dict[str, dict] = {}
        self.dialogs: dict[str, dict] = {}
        self.images: dict[str, bytes] = {}
        self.subscriptions: set[str] = set()
        self.preview: dict | None = None
        self.answers: dict[str, Callable[[Any, bytes], Any]] = {}
        self._ids = itertools.count(1)
        self._doc_ids = itertools.count(1)
        #: Makes the document ``doc.open`` opens; the mock can't read files, so by default a
        #: white one named after the path.
        self.open_document: Callable[[str], MockDocument] = lambda path: self.add_document(
            os.path.basename(path) or "Untitled"
        )
        self._replies: dict[int, transport.Frame] = {}
        self._reply_ready = threading.Condition()
        to_plugin_r, to_plugin_w = os.pipe()
        to_host_r, to_host_w = os.pipe()
        #: The plug-in's ends: give these to its Transport.
        self.plugin_reader = os.fdopen(to_plugin_r, "rb", buffering=0)
        self.plugin_writer = os.fdopen(to_host_w, "wb", buffering=0)
        self._reader = os.fdopen(to_host_r, "rb", buffering=0)
        self._writer = os.fdopen(to_plugin_w, "wb", buffering=0)
        self._write_lock = threading.Lock()
        self._thread = threading.Thread(target=self._serve, name="mock-photocraft", daemon=True)
        self._thread.start()

    # -- model helpers for tests

    def add_document(
        self,
        name: str = "Untitled",
        width: int = 64,
        height: int = 48,
        layers: list[MockLayer] | None = None,
    ) -> MockDocument:
        """Open a document (active) with a white ``Background`` layer unless ``layers`` are given."""
        doc_id = str(next(self._doc_ids))
        if layers is None:
            layers = [MockLayer("Background", pixels=bytearray(b"\xff" * (width * height * 4)))]
        doc = MockDocument(
            doc_id, name, width, height, layers, active_layer=layers[-1].uid if layers else None
        )
        for _, layer in doc.walk():
            if layer.kind == "pixel" and layer.pixels is None:
                layer.pixels = bytearray(width * height * 4)
        self.docs[doc_id] = doc
        self.active_doc = doc_id
        return doc

    def save_and_reopen(self, doc: MockDocument) -> MockDocument:
        """Save ``doc``, close it and open the saved file again, as a new document.

        What comes back is what PhotoCraft keeps through ``.pcraft``, PSD and PSB, which the
        fork's own tests check byte for byte (``storage_tests.rs``
        ``blobs_survive_pcraft_and_psd_byte_for_byte``, ``roundtrip.rs``
        ``layer_uids_survive_a_native_round_trip``): pixels, masks, layer uids and values, and
        the plug-in's blobs. Nothing else carries over: the reopened document has a new id.
        """
        reopened = copy.deepcopy(doc)
        reopened.id = str(next(self._doc_ids))
        del self.docs[doc.id]
        self.send_event("document.closed", {"doc": doc.id})
        self.docs[reopened.id] = reopened
        self.active_doc = reopened.id
        self.send_event("document.opened", {"doc": reopened.id})
        return reopened

    def reset(self):
        """Close every document, and forget what plug-ins registered, as a fresh PhotoCraft has."""
        self.docs.clear()
        self.active_doc = None
        for registry in (self.panels, self.actions, self.progress, self.dialogs, self.images):
            registry.clear()
        self.notices.clear()
        self.opened.clear()
        self.updates.clear()
        self.subscriptions.clear()
        self.preview = None

    def close(self):
        """End the connection, as PhotoCraft quitting would.

        Only write ends are closed: each reader then sees the end of its stream and stops. (On
        Windows, closing a pipe another thread is blocked reading hangs.)
        """
        for stream in (self._writer, self.plugin_writer):
            try:
                with self._write_lock:
                    stream.close()
            except OSError:
                pass
        self._thread.join(5)

    # -- talking to the plug-in

    def _send(self, header: dict, payload: bytes = b""):
        with self._write_lock:
            self._writer.write(transport.encode(header, payload))
            self._writer.flush()

    def send_event(self, topic: str, data: Any, payload: bytes = b""):
        """Send the plug-in an event."""
        self._send({"type": "event", "topic": topic, "data": data}, payload)

    def request(self, method: str, params: Any = None, timeout: float = 5.0) -> transport.Frame:
        """Send the plug-in a request (``ping``, ``shutdown``) and wait for its answer frame.

        The plug-in answers on its Qt thread, so the caller must keep Qt's events flowing
        (``request_async`` plus processing events) when calling from the Qt thread.
        """
        request_id = self.request_async(method, params)
        return self.wait_reply(request_id, timeout)

    def request_async(self, method: str, params: Any = None) -> int:
        """Send the plug-in a request and return its id, without waiting."""
        request_id = next(self._ids)
        self._send({"type": "request", "id": request_id, "method": method, "params": params or {}})
        return request_id

    def wait_reply(self, request_id: int, timeout: float = 5.0) -> transport.Frame:
        with self._reply_ready:
            if not self._reply_ready.wait_for(lambda: request_id in self._replies, timeout):
                raise TimeoutError(f"the plug-in did not answer request {request_id}")
            return self._replies.pop(request_id)

    def reply(self, request_id: int) -> transport.Frame | None:
        """The plug-in's answer to ``request_id`` if it has come, without waiting."""
        with self._reply_ready:
            return self._replies.pop(request_id, None)

    # -- serving the plug-in

    def _serve(self):
        try:
            while True:
                frame = transport.read_frame(self._reader)
                if frame is None:
                    return
                kind = frame.header["type"]
                if kind in ("response", "error"):
                    with self._reply_ready:
                        self._replies[frame.header["id"]] = frame
                        self._reply_ready.notify_all()
                elif kind == "request":
                    self._answer(frame)
        except (OSError, ValueError, transport.ProtocolError):
            return

    def _answer(self, frame: transport.Frame):
        header = frame.header
        method, params, request_id = header["method"], header.get("params") or {}, header["id"]
        self.calls.append((method, params))
        try:
            handler = self.answers.get(method) or getattr(
                self, "_m_" + method.replace(".", "_"), None
            )
            if handler is None:
                raise _Refused("unsupported", f"the mock does not handle '{method}'")
            answer = handler(params, frame.payload)
            result, payload = answer if isinstance(answer, tuple) else (answer, b"")
            self._send(
                {"type": "response", "id": request_id, "result": {} if result is None else result},
                payload,
            )
        except _Refused as e:
            self._send({
                "type": "error",
                "id": request_id,
                "error": {"code": e.code, "message": e.message},
            })
        except Exception as e:  # a bug in the mock: report it as PhotoCraft would
            self._send({
                "type": "error",
                "id": request_id,
                "error": {"code": "internal", "message": repr(e)},
            })

    def _doc(self, p: dict) -> MockDocument:
        doc = self.docs.get(str(p.get("doc")))
        if doc is None:
            raise _Refused("notFound", f"no open document '{p.get('doc')}'")
        return doc

    # session
    def _m_hello(self, p, _):
        if p.get("nonce") != self.nonce:
            raise _Refused("invalid", "the hello did not carry the launch nonce")
        if p.get("protocol") != 1:
            raise _Refused("unsupported", "PhotoCraft speaks protocol 1")
        return {
            "hostVersion": HOST_VERSION,
            "protocol": 1,
            "locale": "en",
            "dataDir": "",
            "logDir": "",
            "theme": {"dark": True},
        }

    # documents
    def _doc_info(self, doc: MockDocument) -> dict:
        info = {
            "doc": doc.id,
            "name": doc.name,
            "width": doc.width,
            "height": doc.height,
            "dpi": doc.dpi,
            "depth": doc.depth,
            "mode": doc.mode,
            "active": doc.id == self.active_doc,
        }
        if doc.path:
            info["path"] = doc.path
        return info

    def _m_doc_list(self, _p, _):
        return [self._doc_info(d) for d in self.docs.values()]

    def _m_doc_info(self, p, _):
        return self._doc_info(self._doc(p))

    def _m_doc_open(self, p, _):
        doc = self.open_document(str(p.get("path", "")))
        doc.path = str(p.get("path", "")) or None
        return {"doc": doc.id}

    def _m_doc_setActive(self, p, _):
        self.active_doc = self._doc(p).id

    # layers
    def _m_layer_tree(self, p, _):
        doc = self._doc(p)
        return [doc.info(layer) for layer in doc.layers]

    def _m_layer_active(self, p, _):
        return self._doc(p).active_layer

    def _m_layer_setActive(self, p, _):
        doc = self._doc(p)
        doc.active_layer = doc.find(p["uid"]).uid

    def _place(self, doc: MockDocument, p: dict, layer: MockLayer):
        if p.get("above"):
            siblings = doc.siblings(p["above"])
            index = next(i for i, s in enumerate(siblings) if s.uid == p["above"])
            siblings.insert(index + 1, layer)
        elif p.get("parent"):
            doc.find(p["parent"]).children.append(layer)
        else:
            doc.layers.append(layer)

    def _m_layer_create(self, p, _):
        doc = self._doc(p)
        kind = p.get("kind", "pixel")
        layer = MockLayer(
            str(p.get("name", "Layer")),
            kind=kind,
            pixels=bytearray(doc.width * doc.height * 4) if kind == "pixel" else None,
        )
        self._place(doc, p, layer)
        doc.active_layer = layer.uid
        return {"uid": layer.uid}

    def _m_layer_update(self, p, _):
        layer = self._doc(p).find(p["uid"])
        for key in ("name", "visible", "locked", "opacity", "blend"):
            if key in p:
                setattr(layer, key, p[key])

    def _m_layer_move(self, p, _):
        doc = self._doc(p)
        layer = doc.find(p["uid"])
        doc.siblings(layer.uid).remove(layer)
        self._place(doc, p, layer)

    def _m_layer_delete(self, p, _):
        doc = self._doc(p)
        layer = doc.find(p["uid"])
        doc.siblings(layer.uid).remove(layer)
        # As PhotoCraft does: deleting the active layer makes the top layer active.
        if doc.active_layer is not None and doc.find_or_none(doc.active_layer) is None:
            doc.active_layer = doc.layers[-1].uid if doc.layers else None

    def _m_undo_begin(self, p, _):
        self._doc(p)
        return {"group": next(self._ids)}

    def _m_undo_end(self, _p, _):
        return None

    # pixels
    def _region(
        self, doc: MockDocument, src: bytes | bytearray, x: int, y: int, w: int, h: int
    ) -> bytes:
        out = bytearray(w * h * 4)
        for row in range(h):
            sy = y + row
            if not 0 <= sy < doc.height:
                continue
            for col in range(w):
                sx = x + col
                if 0 <= sx < doc.width:
                    i, o = (sy * doc.width + sx) * 4, (row * w + col) * 4
                    out[o : o + 4] = src[i : i + 4]
        return bytes(out)

    def _composite(
        self, doc: MockDocument, exclude: set[str], layers: list[MockLayer] | None = None
    ) -> bytearray:
        """The topmost visible non-transparent pixel of every point of ``layers`` (the whole
        document by default), groups included through their children: enough for the tests."""
        out = bytearray(doc.width * doc.height * 4)

        def draw(stack: list[MockLayer]):
            for layer in stack:
                if not layer.visible or layer.uid in exclude:
                    continue
                if layer.children:
                    draw(layer.children)
                elif layer.pixels is not None:
                    for i in range(0, len(out), 4):
                        if layer.pixels[i + 3]:
                            out[i : i + 4] = layer.pixels[i : i + 4]

        draw(doc.layers if layers is None else layers)
        return out

    def _m_pixels_read(self, p, _):
        doc = self._doc(p)
        x, y, w, h = _rect(p)
        source = p.get("source") or {}
        if source.get("kind") == "composite":
            src = self._composite(doc, set(p.get("exclude") or []))
        else:
            layer = doc.find(source.get("uid", ""))
            if source.get("kind") == "group":
                src = self._composite(doc, set(), layer.children)
            else:
                src = layer.pixels or bytearray(doc.width * doc.height * 4)
        px = self._region(doc, src, x, y, w, h)
        return {}, (px if p.get("format", "bgra8") == "bgra8" else _swap(px))

    def _write(self, doc: MockDocument, layer: MockLayer, p: dict, payload: bytes):
        x, y, w, h = _rect(p)
        if len(payload) != w * h * 4:
            raise _Refused("invalid", "the payload doesn't match the rectangle")
        px = payload if p.get("format", "bgra8") == "bgra8" else _swap(payload)
        if layer.pixels is None:
            layer.pixels = bytearray(doc.width * doc.height * 4)
        for row in range(h):
            sy = y + row
            for col in range(w):
                sx = x + col
                if 0 <= sx < doc.width and 0 <= sy < doc.height:
                    i, o = (sy * doc.width + sx) * 4, (row * w + col) * 4
                    layer.pixels[i : i + 4] = px[o : o + 4]

    def _m_pixels_write(self, p, payload):
        doc = self._doc(p)
        self._write(doc, doc.find(p["uid"]), p, payload)

    def _m_pixels_createLayer(self, p, payload):
        doc = self._doc(p)
        layer = MockLayer(str(p.get("name", "Layer")), pixels=bytearray(doc.width * doc.height * 4))
        self._write(doc, layer, p, payload)
        self._place(doc, p, layer)
        doc.active_layer = layer.uid
        return {"uid": layer.uid}

    def _m_selection_read(self, p, _):
        doc = self._doc(p)
        if doc.selection is None:
            return {"none": True}
        x, y, w, h = _rect(p)
        out = bytearray(w * h)
        for row in range(h):
            for col in range(w):
                sx, sy = x + col, y + row
                if 0 <= sx < doc.width and 0 <= sy < doc.height:
                    out[row * w + col] = doc.selection[sy * doc.width + sx]
        return {}, bytes(out)

    def _m_selection_bounds(self, p, _):
        doc = self._doc(p)
        if doc.selection is None:
            return {}
        points = [(i % doc.width, i // doc.width) for i, v in enumerate(doc.selection) if v]
        if not points:
            return {}
        xs, ys = [q[0] for q in points], [q[1] for q in points]
        return {
            "bounds": {
                "x": min(xs),
                "y": min(ys),
                "width": max(xs) - min(xs) + 1,
                "height": max(ys) - min(ys) + 1,
            }
        }

    def _m_selection_set(self, p, payload):
        doc = self._doc(p)
        if p.get("clear"):
            doc.selection = None
            return
        x, y, w, h = _rect(p)
        sel = bytearray(doc.width * doc.height)
        for row in range(h):
            for col in range(w):
                sx, sy = x + col, y + row
                if 0 <= sx < doc.width and 0 <= sy < doc.height:
                    sel[sy * doc.width + sx] = payload[row * w + col]
        doc.selection = sel
        return

    # data in documents
    def _m_blob_set(self, p, payload):
        self._doc(p).blobs[p["name"]] = bytes(payload)

    def _m_blob_get(self, p, _):
        blob = self._doc(p).blobs.get(p["name"])
        return ({"found": True}, blob) if blob is not None else {"found": False}

    def _m_blob_delete(self, p, _):
        self._doc(p).blobs.pop(p["name"], None)

    def _m_blob_list(self, p, _):
        return {"names": sorted(self._doc(p).blobs)}

    def _m_layerData_set(self, p, _):
        layer = self._doc(p).find(p["uid"])
        if p.get("value") is None:
            layer.data.pop(p["key"], None)
        else:
            layer.data[p["key"]] = p["value"]

    def _m_layerData_get(self, p, _):
        value = self._doc(p).find(p["uid"]).data.get(p["key"])
        return {} if value is None else {"value": value}

    # previews, UI and services: recorded for the tests to inspect
    def _m_preview_show(self, p, payload):
        self.preview = {**p, "bytes": len(payload)}

    def _m_preview_hide(self, _p, _):
        self.preview = None

    def _m_events_subscribe(self, p, _):
        self.subscriptions = set(p.get("topics") or [])

    def _m_panel_register(self, p, _):
        self.panels[p["panelId"]] = {"title": p["title"], "tree": p["tree"]}

    def _m_panel_patch(self, p, _):
        if p["panelId"] not in self.panels:
            raise _Refused("notFound", f"no panel '{p['panelId']}'")
        panel = self.panels[p["panelId"]]
        panel["tree"] = apply_patches(panel["tree"], p["ops"])
        panel.setdefault("patches", []).append(p["ops"])

    def _m_panel_unregister(self, p, _):
        self.panels.pop(p["panelId"], None)

    def _m_image_put(self, p, payload):
        self.images[p["hash"]] = bytes(payload)

    def _m_dialog_open(self, p, _):
        self.dialogs[p["dialogId"]] = p

    def _m_dialog_patch(self, p, _):
        dialog = self.dialogs.setdefault(p["dialogId"], {})
        if "tree" in dialog:
            dialog["tree"] = apply_patches(dialog["tree"], p["ops"])
        dialog.setdefault("patches", []).append(p["ops"])

    def _m_dialog_close(self, p, _):
        self.dialogs.pop(p["dialogId"], None)

    def _m_action_register(self, p, _):
        self.actions[p["id"]] = {**p, "enabled": True}

    def _m_action_update(self, p, _):
        if p["id"] not in self.actions:
            raise _Refused("notFound", f"no action '{p['id']}'")
        self.actions[p["id"]].update({k: v for k, v in p.items() if k != "id"})

    def _m_notice_show(self, p, _):
        self.notices.append(p)

    def _m_open_url(self, p, _):
        self.opened.append(str(p["url"]))

    def _m_open_path(self, p, _):
        self.opened.append(str(p["path"]))

    def _m_plugin_update(self, p, _):
        # PhotoCraft installs the package and restarts the plug-in after answering.
        self.updates.append(str(p["path"]))

    def _m_progress_set(self, p, _):
        self.progress[p["taskId"]] = p

    def _m_progress_clear(self, p, _):
        self.progress.pop(p["taskId"], None)

    # canvas, masks, thumbnails and vector content
    def _m_doc_resizeCanvas(self, p, _):
        doc = self._doc(p)
        w, h = int(p["width"]), int(p["height"])
        if w <= 0 or h <= 0:
            raise _Refused("invalid", "canvas size must be positive")
        for _, layer in doc.walk():
            if layer.pixels is not None:
                old = bytes(layer.pixels)
                layer.pixels = bytearray(self._region(doc, old, 0, 0, w, h))
        doc.width, doc.height = w, h

    def _m_doc_resizeImage(self, p, _):
        """Nearest-neighbour resample (enough for the tests)."""
        doc = self._doc(p)
        w, h = int(p["width"]), int(p["height"])
        if w <= 0 or h <= 0:
            raise _Refused("invalid", "image size must be positive")
        for _, layer in doc.walk():
            if layer.pixels is not None:
                old = layer.pixels
                new = bytearray(w * h * 4)
                for y in range(h):
                    sy = y * doc.height // h
                    for x in range(w):
                        sx = x * doc.width // w
                        new[(y * w + x) * 4 : (y * w + x) * 4 + 4] = old[
                            (sy * doc.width + sx) * 4 : (sy * doc.width + sx) * 4 + 4
                        ]
                layer.pixels = new
        doc.width, doc.height = w, h
        if p.get("dpi"):
            doc.dpi = float(p["dpi"])

    def _m_layer_addMask(self, p, payload):
        doc = self._doc(p)
        layer = doc.find(p["uid"])
        if p.get("from") == "image":
            if len(payload) != doc.width * doc.height:
                raise _Refused("invalid", "a mask covers the canvas")
            layer.mask = bytearray(payload)
        else:
            layer.mask = bytearray(b"\xff" * (doc.width * doc.height))

    def _m_mask_read(self, p, _):
        doc = self._doc(p)
        layer = doc.find(p["uid"])
        x, y, w, h = _rect(p)
        if p.get("which") == "layerMask":
            if layer.mask is None:
                raise _Refused("notFound", "the layer has no mask")
            src = layer.mask
            return {}, bytes(
                src[(y + r) * doc.width + x + c]
                if 0 <= x + c < doc.width and 0 <= y + r < doc.height
                else 0
                for r in range(h)
                for c in range(w)
            )
        px = self._region(doc, layer.pixels or bytearray(doc.width * doc.height * 4), x, y, w, h)
        return {}, bytes(px[3::4])

    def _m_layer_thumbnail(self, p, _):
        doc = self._doc(p)
        layer = doc.find(p["uid"])
        pixels = (
            layer.pixels
            if layer.pixels is not None
            else self._composite(doc, set(), layer.children)
        )
        full = QImage(
            bytes(pixels), doc.width, doc.height, doc.width * 4, QImage.Format.Format_ARGB32
        )
        image = full.scaled(max(1, int(p.get("width", 1))), max(1, int(p.get("height", 1))))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return {}, bytes(data.data())

    def _m_vector_shapes(self, p, _):
        doc = self._doc(p)
        group = doc.find(p["uid"])
        if group.kind != "group" or "vector.group" not in group.data:
            raise _Refused("invalid", "not a vector layer")
        return {
            "shapes": [
                {
                    "id": c.data.get("vector.id", c.name),
                    "handle": c.uid,
                    "svg": c.data.get("svg", ""),
                }
                for c in group.children
            ]
        }

    def _m_vector_addSvg(self, p, _):
        """Each ``<circle .../>`` or ``<line .../>`` becomes a shape child, its markup kept."""
        doc = self._doc(p)
        group = doc.find(p["uid"])
        for element in re.findall(r"<(?:circle|line)\b[^>]*/>", p.get("svg", "")):
            found = re.search(r'id="([^"]*)"', element)
            element_id = found.group(1) if found else "shape"
            group.children.append(
                MockLayer(element_id, kind="shape", data={"vector.id": element_id, "svg": element})
            )

    def _m_vector_removeShapes(self, p, _):
        doc = self._doc(p)
        group = doc.find(p["uid"])
        group.children = [c for c in group.children if c.uid not in set(p.get("ids") or [])]
