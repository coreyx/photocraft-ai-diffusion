"""The shutdown abort's preconditions, in a process of its own (``test_late_reply.py``).

    python tests/photocraft/late_reply.py [--raise-in-slot]

By default: one request through upstream's ``RequestManager`` to a local server that accepts the
connection and holds it. Once it is connected, upstream's ``eventloop.stop()`` closes the event
loop as the plug-in's shutdown does, then the server answers ``503`` and closes the connection,
so the reply finishes with an error after the loop has closed. Before the fix, that raised from inside a Qt slot and,
with Python's default ``sys.excepthook``, PyQt6 aborted the process. Prints ``finished`` once the
reply has finished, then exits with ``app.exec()``'s code.

The server decides when the reply finishes, so this doesn't depend on how fast a refused
connection fails: immediately on Linux, after about 2 seconds of retries on Windows.

With ``--raise-in-slot``: installs the plug-in's exception hook, raises ``ValueError`` from a Qt
slot, and prints ``survived`` from the next one.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

#: How long Qt may take to connect and see the connection dropped, in milliseconds.
TIME_LIMIT = 10_000


class HoldingServer:
    """Accepts connections on a free loopback port and keeps each open, unanswered, until
    :meth:`release` answers them all with an error and closes them.

    Answering rather than only closing matters: Qt resends a GET whose connection closed before
    any response, and the resend then waits for a refused connection, slow on Windows."""

    def __init__(self):
        self.socket = socket.create_server(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.connected = threading.Event()
        self._released = threading.Event()
        self._connections: list[socket.socket] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self._released.is_set():
            try:
                connection, _ = self.socket.accept()
            except OSError:  # closed by release()
                return
            # Wait for the request itself: an answer sent before it, Qt takes for a dropped
            # connection and resends the request.
            request = b""
            while b"\r\n\r\n" not in request and (chunk := connection.recv(4096)):
                request += chunk
            self._connections.append(connection)
            self.connected.set()

    def release(self):
        self._released.set()
        for connection in self._connections:
            connection.sendall(
                b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            connection.close()
        self.socket.close()


def late_reply(app: QApplication) -> int:
    from photocraft_host.main import install_krita_shim

    install_krita_shim()
    import krita

    # The data folder and session that PhotoCraft's welcome would give, without a PhotoCraft.
    session = types.SimpleNamespace(
        data_dir=Path(tempfile.mkdtemp()), locale="en", host_version="test"
    )
    krita.photocraft_host = lambda: session  # type: ignore[attr-defined]
    sys.modules["debugpy"] = None  # type: ignore[assignment]  # as main.start() keeps it out
    from ai_diffusion import eventloop
    from ai_diffusion.backend.network import RequestManager

    server = HoldingServer()
    eventloop.setup()
    net = RequestManager()

    async def request():
        await net.http("GET", f"http://127.0.0.1:{server.port}/")

    eventloop.run(request())

    def finished(_reply):
        # Connected after RequestManager's own slot, so it runs once that slot has returned.
        print("finished", flush=True)
        QTimer.singleShot(0, app.quit)

    net._net.finished.connect(finished)

    def close_loop_once_connected():
        if not server.connected.is_set():
            QTimer.singleShot(10, close_loop_once_connected)
            return
        eventloop.stop()  # what upstream's shutdown does before the application quits
        server.release()

    close_loop_once_connected()
    QTimer.singleShot(TIME_LIMIT, app.quit)
    return app.exec()


def raise_in_slot(app: QApplication) -> int:
    from photocraft_host.main import install_excepthook, setup_logging

    setup_logging()
    install_excepthook()

    def fail():
        raise ValueError("raised from a Qt slot")

    def survived():
        print("survived", flush=True)
        app.quit()

    QTimer.singleShot(0, fail)
    QTimer.singleShot(50, survived)
    return app.exec()


def main() -> int:
    app = QApplication(sys.argv[:1])
    from photocraft_host import qt_setup

    qt_setup.use_platform_tls()  # as the plug-in process does
    if "--raise-in-slot" in sys.argv[1:]:
        return raise_in_slot(app)
    return late_reply(app)


if __name__ == "__main__":
    code = main()
    from photocraft_host import framing

    framing.leave(code)  # no interpreter teardown; saves a coverage measurement
