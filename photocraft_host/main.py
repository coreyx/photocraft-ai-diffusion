"""The plug-in process: what PhotoCraft starts from the manifest's ``command``.

1. Point standard output at the log, keeping the original for frames (:func:`transport.stdio_streams`).
2. Start Qt headless (``offscreen``): the plug-in draws nothing itself, PhotoCraft draws its UI.
3. Put the ``krita`` stand-in where upstream's ``import krita`` finds it.
4. Introduce the plug-in to PhotoCraft (``hello``) and learn the session (``welcome``).
5. Start the plug-in proper (:func:`start`), then run Qt's event loop until PhotoCraft says
   ``shutdown`` or closes the connection.

Run as ``python -m photocraft_host.main``.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import tomllib

#: The protocol version this plug-in speaks.
PROTOCOL_VERSION = 1
#: The plug-in's id and version when no manifest is found (running from a source checkout).
DEFAULT_ID = "io.github.coreyx.ai-diffusion-for-photocraft"
DEFAULT_VERSION = "0.0.0-dev"

log = logging.getLogger("photocraft_host")


@dataclass(frozen=True)
class Welcome:
    """What PhotoCraft told the plug-in when it connected."""

    host_version: str
    protocol: int
    locale: str
    data_dir: Path
    log_dir: Path
    dark_theme: bool

    @staticmethod
    def from_result(result: dict) -> Welcome:
        theme = result.get("theme") or {}
        return Welcome(
            host_version=str(result.get("hostVersion", "")),
            protocol=int(result.get("protocol", 0)),
            locale=str(result.get("locale", "en")),
            data_dir=Path(str(result.get("dataDir", ""))),
            log_dir=Path(str(result.get("logDir", ""))),
            dark_theme=bool(theme.get("dark", True)),
        )


def identity(plugin_dir: Path | None = None) -> tuple[str, str]:
    """The plug-in's id and version, from its manifest when there is one."""
    folder = plugin_dir or Path(
        os.environ.get("PHOTOCRAFT_PLUGIN_DIR", Path(__file__).resolve().parents[1])
    )
    manifest = folder / "photocraft-plugin.toml"
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        return str(data.get("id", DEFAULT_ID)), str(data.get("version", DEFAULT_VERSION))
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_ID, DEFAULT_VERSION


def setup_logging():
    """Log to standard error, which PhotoCraft keeps in the plug-in's log file."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def install_krita_shim():
    """Make ``import krita`` find the stand-in (``photocraft_host.krita``) once it exists."""
    if "krita" in sys.modules or importlib.util.find_spec("photocraft_host.krita") is None:
        return
    sys.modules["krita"] = importlib.import_module("photocraft_host.krita")


def connect(transport, nonce: str, plugin_id: str, version: str, timeout: float = 10.0) -> Welcome:
    """Send ``hello`` and return PhotoCraft's ``welcome``.

    Raises :class:`transport.RemoteError` when PhotoCraft refuses the plug-in (a wrong nonce or
    protocol version).
    """
    params = {
        "protocol": PROTOCOL_VERSION,
        "nonce": nonce,
        "plugin": {"id": plugin_id, "version": version},
    }
    result, _ = transport.call("hello", params, timeout=timeout)
    return Welcome.from_result(result or {})


def serve_session(transport, app, on_shutdown: Callable[[], None] | None = None):
    """Answer PhotoCraft's own requests: ``ping`` (on the Qt thread, so a stuck Qt thread shows
    as not responding) and ``shutdown`` (answer, then quit)."""
    transport.handle("ping", lambda _params, _payload: {})

    def shutdown(_params, _payload):
        if on_shutdown is not None:
            on_shutdown()
        # Quit after the answer is sent: this handler's return value is sent first.
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, app.quit)
        return {}

    transport.handle("shutdown", shutdown)
    transport.closed.connect(lambda reason: (log.info("connection closed: %s", reason), app.quit()))


def start(transport, welcome: Welcome):
    """Start the plug-in proper once connected. Upstream's extension and docker are set up
    here once the shim and the Qt mirror carry them (TASK-27)."""
    log.info(
        "connected to PhotoCraft %s (protocol %s, locale %s)",
        welcome.host_version,
        welcome.protocol,
        welcome.locale,
    )


def main() -> int:
    """Run the plug-in process. Returns the exit code."""
    setup_logging()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from photocraft_host import transport as transport_module

    reader, writer = transport_module.stdio_streams()
    app = QApplication(sys.argv[:1])
    install_krita_shim()
    transport = transport_module.Transport(reader, writer)
    serve_session(transport, app)
    transport.start()
    plugin_id, version = identity()
    try:
        welcome = connect(
            transport, os.environ.get("PHOTOCRAFT_PLUGIN_NONCE", ""), plugin_id, version
        )
    except (transport_module.RemoteError, TimeoutError, ConnectionError) as e:
        log.error("PhotoCraft refused the connection: %s", e)
        return 2
    start(transport, welcome)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
