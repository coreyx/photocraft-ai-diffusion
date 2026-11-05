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
middle of it. PhotoCraft answers every request within a frame, so the wait is short. The few
requests that wait for the user (a message box, a file picker) use
:meth:`Transport.call_waiting`, which runs the event loop meanwhile, as a modal Qt dialog does.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import IO, Any

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal

from .framing import (
    MAGIC,
    MAX_HEADER,
    MAX_PAYLOAD,
    PREFIX_LEN,
    Frame,
    ProtocolError,
    encode,
    read_frame,
    stdio_streams,
)

#: The framing, re-exported: the transport is where the plug-in and its tests look for it.
__all__ = [
    "DEFAULT_TIMEOUT",
    "MAGIC",
    "MAX_HEADER",
    "MAX_PAYLOAD",
    "PREFIX_LEN",
    "Frame",
    "ProtocolError",
    "RemoteError",
    "Transport",
    "encode",
    "read_frame",
    "stdio_streams",
]

log = logging.getLogger(__name__)

#: How long a call waits for PhotoCraft's answer by default, in seconds.
DEFAULT_TIMEOUT = 30.0


class RemoteError(Exception):
    """PhotoCraft refused a request: ``code`` is the protocol's error code."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


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

    def __init__(
        self,
        reader: IO[bytes],
        writer: IO[bytes],
        parent: QObject | None = None,
        first_id: int = 1,
    ):
        """``first_id``: the first request id, after those the bootstrap already used when it
        continues a session it opened."""
        super().__init__(parent)
        self._reader = reader
        self._writer = writer
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._next_id = first_id
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
        request_id, pending = self._request(method, params, payload)
        if not pending.done.wait(timeout):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"PhotoCraft did not answer {method} within {timeout} s")
        return self._answer(pending)

    def call_waiting(
        self, method: str, params: Any = None, payload: bytes = b""
    ) -> tuple[Any, bytes]:
        """Send request ``method`` and wait for its answer with no deadline, running the Qt
        event loop meanwhile.

        For requests PhotoCraft answers once the user has chosen (``dialog.message``,
        ``dialog.file``), the way Qt's own modal dialogs wait: pings, events and timers go on,
        so the plug-in stays responsive while the user takes their time.
        """
        _request_id, pending = self._request(method, params, payload)
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: (pending.done.is_set() or self.is_closed) and loop.quit())
        timer.start()
        if not pending.done.is_set():
            loop.exec()
        timer.stop()
        return self._answer(pending)

    def _request(self, method: str, params: Any, payload: bytes) -> tuple[int, _Pending]:
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
        return request_id, pending

    def _answer(self, pending: _Pending) -> tuple[Any, bytes]:
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
