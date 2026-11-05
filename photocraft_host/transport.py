"""PhotoCraft's process plug-in protocol over the plug-in's standard input and output.

A frame is ``"PCPP" | header length (u32 LE) | payload length (u64 LE) | header JSON | payload``
(PhotoCraft's ``docs/process-plugins.md``). Headers are requests, responses, errors or events.

The :class:`Transport` runs a reader thread that does nothing but read frames:

- a response or error completes the :meth:`Transport.call` waiting for it, by request id, so
  replies may arrive in any order;
- a request from the host or an event is handed to the Qt thread through a queued signal, where
  request handlers (:meth:`Transport.handle`) and event handlers (:meth:`Transport.on`) run.

:meth:`Transport.call` blocks the calling (Qt) thread until the reply arrives or its deadline
passes, without re-entering the Qt event loop: upstream code that calls the ``krita`` API expects
the call to return a value, as Krita's own API does, and must not see other events run in the
middle of it. PhotoCraft answers every request within a frame, so the wait is short.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import sys
import threading
from collections.abc import Callable
from typing import IO, Any, NamedTuple

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

MAGIC = b"PCPP"
_PREFIX = struct.Struct("<4sIQ")
PREFIX_LEN = _PREFIX.size
#: Largest header and payload accepted, as PhotoCraft's defaults.
MAX_HEADER = 1 << 20
MAX_PAYLOAD = 512 << 20
#: How long a call waits for PhotoCraft's answer by default, in seconds.
DEFAULT_TIMEOUT = 30.0


class ProtocolError(Exception):
    """The other side broke the framing or sent something that isn't a protocol message."""


class RemoteError(Exception):
    """PhotoCraft refused a request: ``code`` is the protocol's error code."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Frame(NamedTuple):
    """One decoded frame: its JSON header and its binary payload."""

    header: dict[str, Any]
    payload: bytes


def encode(header: dict[str, Any], payload: bytes = b"") -> bytes:
    """The bytes of a frame holding ``header`` and ``payload``."""
    head = json.dumps(header, separators=(",", ":")).encode("utf-8")
    if len(head) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ProtocolError(
            f"frame too large: header {len(head)} bytes, payload {len(payload)} bytes"
        )
    return _PREFIX.pack(MAGIC, len(head), len(payload)) + head + payload


def _read_exactly(stream: IO[bytes], n: int) -> bytes | None:
    """``n`` bytes from ``stream``, or ``None`` when it ends before the first byte."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if remaining == n:
                return None
            raise ProtocolError(f"stream ended inside a frame ({n - remaining} of {n} bytes)")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: IO[bytes]) -> Frame | None:
    """The next frame from ``stream``, or ``None`` at the end of the stream between frames.

    Lengths are checked before anything is read into memory; any malformed input is a
    :class:`ProtocolError`.
    """
    prefix = _read_exactly(stream, PREFIX_LEN)
    if prefix is None:
        return None
    magic, header_len, payload_len = _PREFIX.unpack(prefix)
    if magic != MAGIC:
        raise ProtocolError(f"bad frame magic {magic!r}")
    if header_len > MAX_HEADER or payload_len > MAX_PAYLOAD:
        raise ProtocolError(
            f"frame too large: header {header_len} bytes, payload {payload_len} bytes"
        )
    head = _read_exactly(stream, header_len) if header_len else b""
    payload = _read_exactly(stream, payload_len) if payload_len else b""
    if head is None or payload is None:
        raise ProtocolError("stream ended inside a frame")
    try:
        header = json.loads(head.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError(f"frame header is not JSON: {e}") from e
    if not isinstance(header, dict) or header.get("type") not in (
        "request",
        "response",
        "error",
        "event",
    ):
        raise ProtocolError("frame header is not a protocol message")
    return Frame(header, payload)


class _Pending:
    """A call waiting for its reply."""

    __slots__ = ("done", "frame")

    def __init__(self):
        self.done = threading.Event()
        self.frame: Frame | None = None


RequestHandler = Callable[[Any, bytes], Any]
EventHandler = Callable[[Any, bytes], None]


class Transport(QObject):
    """Requests, responses and events with PhotoCraft over a pair of byte streams."""

    #: Emitted (on the Qt thread) for each request or event from the host.
    _incoming = pyqtSignal(object)
    #: Emitted (on the Qt thread) once the connection has ended, with the reason.
    closed = pyqtSignal(str)

    def __init__(self, reader: IO[bytes], writer: IO[bytes], parent: QObject | None = None):
        super().__init__(parent)
        self._reader = reader
        self._writer = writer
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._next_id = 1
        self._closed: str | None = None
        self._handlers: dict[str, RequestHandler] = {}
        self._listeners: dict[str, list[EventHandler]] = {}
        self._thread: threading.Thread | None = None
        # The reader thread emits; Qt's automatic connection queues the call to this object's
        # thread (the Qt thread), where the slot runs.
        self._incoming.connect(self._dispatch)

    # -- lifecycle

    def start(self):
        """Start reading frames on a background thread."""
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._read_loop, name="photocraft-transport", daemon=True
            )
            self._thread.start()

    @property
    def is_closed(self) -> bool:
        return self._closed is not None

    def _read_loop(self):
        reason = "PhotoCraft closed the connection"
        try:
            while True:
                frame = read_frame(self._reader)
                if frame is None:
                    break
                self._route(frame)
        except (ProtocolError, OSError, ValueError) as e:
            reason = f"connection error: {e}"
            log.error(reason)
        self._close(reason)

    def _route(self, frame: Frame):
        kind = frame.header["type"]
        if kind in ("response", "error"):
            with self._state_lock:
                pending = self._pending.pop(frame.header.get("id", -1), None)
            if pending is None:
                log.warning("reply to unknown request %s", frame.header.get("id"))
                return
            pending.frame = frame
            pending.done.set()
        else:
            self._incoming.emit(frame)

    def _close(self, reason: str):
        with self._state_lock:
            if self._closed is not None:
                return
            self._closed = reason
            waiting = list(self._pending.values())
            self._pending.clear()
        for pending in waiting:
            pending.done.set()
        self.closed.emit(reason)

    # -- sending

    def _send(self, header: dict[str, Any], payload: bytes = b""):
        data = encode(header, payload)
        with self._write_lock:
            if self._closed is not None:
                raise ConnectionError(self._closed)
            self._writer.write(data)
            self._writer.flush()

    def call(
        self,
        method: str,
        params: Any = None,
        payload: bytes = b"",
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> tuple[Any, bytes]:
        """Send request ``method`` and wait for its answer: ``(result, payload)``.

        Raises :class:`RemoteError` when PhotoCraft refuses it, :class:`TimeoutError` when no
        answer comes within ``timeout`` seconds, and :class:`ConnectionError` when the connection
        is closed.
        """
        pending = _Pending()
        with self._state_lock:
            if self._closed is not None:
                raise ConnectionError(self._closed)
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = pending
        header = {
            "type": "request",
            "id": request_id,
            "method": method,
            "params": {} if params is None else params,
        }
        try:
            self._send(header, payload)
        except BaseException:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        if not pending.done.wait(timeout):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"PhotoCraft did not answer {method} within {timeout} s")
        frame = pending.frame
        if frame is None:
            raise ConnectionError(self._closed or "the connection closed")
        if frame.header["type"] == "error":
            error = frame.header.get("error") or {}
            raise RemoteError(str(error.get("code", "internal")), str(error.get("message", "")))
        return frame.header.get("result"), frame.payload

    def respond(self, request_id: int, result: Any = None, payload: bytes = b""):
        """Answer the host's request ``request_id``."""
        self._send(
            {"type": "response", "id": request_id, "result": {} if result is None else result},
            payload,
        )

    def refuse(self, request_id: int, code: str, message: str):
        """Refuse the host's request ``request_id`` with an error ``code``."""
        self._send({"type": "error", "id": request_id, "error": {"code": code, "message": message}})

    # -- receiving

    def handle(self, method: str, handler: RequestHandler):
        """Answer the host's ``method`` requests with ``handler(params, payload)``'s result.

        A handler may return ``(result, payload)`` to send a payload. Exceptions become
        ``internal`` errors.
        """
        self._handlers[method] = handler

    def on(self, topic: str, handler: EventHandler):
        """Call ``handler(data, payload)`` on the Qt thread for each ``topic`` event."""
        self._listeners.setdefault(topic, []).append(handler)

    def off(self, topic: str, handler: EventHandler):
        """Stop calling ``handler`` for ``topic``."""
        handlers = self._listeners.get(topic, [])
        if handler in handlers:
            handlers.remove(handler)

    def _dispatch(self, frame: Frame):
        header = frame.header
        if header["type"] == "event":
            for handler in list(self._listeners.get(str(header.get("topic")), [])):
                try:
                    handler(header.get("data"), frame.payload)
                except Exception:
                    log.exception("event handler for %s failed", header.get("topic"))
            return
        request_id = header.get("id", -1)
        method = str(header.get("method"))
        handler = self._handlers.get(method)
        try:
            if handler is None:
                self.refuse(request_id, "unsupported", f"the plug-in does not handle '{method}'")
                return
            answer = handler(header.get("params"), frame.payload)
            if (
                isinstance(answer, tuple)
                and len(answer) == 2
                and isinstance(answer[1], bytes | bytearray)
            ):
                self.respond(request_id, answer[0], bytes(answer[1]))
            else:
                self.respond(request_id, answer)
        except ConnectionError:
            pass
        except Exception as e:
            log.exception("handler for %s failed", method)
            try:
                self.refuse(request_id, "internal", str(e))
            except ConnectionError:
                pass


def stdio_streams() -> tuple[IO[bytes], IO[bytes]]:
    """The plug-in's frame streams, set up so nothing else can write into the frame channel.

    Frames go out on the original standard output. Descriptor 1 is then pointed at standard
    error, so ``print`` and any library writing to stdout end up in the plug-in's log instead of
    corrupting the frames.
    """
    frames_out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    frames_in = os.fdopen(os.dup(0), "rb", buffering=0)
    return frames_in, frames_out
