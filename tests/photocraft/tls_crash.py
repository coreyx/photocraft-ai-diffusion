"""The 30-second crash's preconditions, in a process of its own (``test_qt_setup.py``).

    python tests/photocraft/tls_crash.py <cert.pem> <key.pem> <seconds> <fix|nofix>

Python's ``ssl`` is imported (as the plug-in does through websockets) while a foreign OpenSSL is
first on ``PATH`` (the test arranges it). One HTTPS request goes through Qt to a local server,
then the event loop runs for ``seconds``. Before the fix, the process crashed between 30 and 35
seconds after the request. With ``fix``, ``qt_setup.use_platform_tls`` runs first. Prints the
TLS backend Qt used, the request's status and ``survived``.
"""

from __future__ import annotations

import http.server
import os
import ssl
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6.QtCore import QCoreApplication, QTimer, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QSslSocket


class Handler(http.server.BaseHTTPRequestHandler):
    """Answers every request, keeping the connection open as servers do (HTTP/1.1)."""

    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def main() -> int:
    cert, key, seconds, mode = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    app = QCoreApplication([])
    if mode == "fix":
        from photocraft_host import qt_setup

        qt_setup.use_platform_tls()
    manager = QNetworkAccessManager()
    reply = manager.get(QNetworkRequest(QUrl(f"https://127.0.0.1:{server.server_port}/")))
    assert reply is not None
    # The certificate is made for this test; the TLS session must still be set up for real.
    reply.sslErrors.connect(lambda _errors: reply.ignoreSslErrors())

    def finished():
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        print(f"backend {QSslSocket.activeBackend()} ({QSslSocket.sslLibraryVersionString()})")
        print(f"status {status}", flush=True)

    reply.finished.connect(finished)
    QTimer.singleShot(int(seconds * 1000), app.quit)
    app.exec()
    print("survived", flush=True)
    server.shutdown()
    return 0


if __name__ == "__main__":
    code = main()
    from photocraft_host import framing

    framing.leave(code)  # no interpreter teardown; saves a coverage measurement
