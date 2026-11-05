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
    #: The plug-in's own data folder; ``None`` if PhotoCraft gave none.
    data_dir: Path | None
    log_dir: Path | None
    dark_theme: bool

    @staticmethod
    def from_result(result: dict) -> Welcome:
        theme = result.get("theme") or {}
        return Welcome(
            host_version=str(result.get("hostVersion", "")),
            protocol=int(result.get("protocol", 0)),
            locale=str(result.get("locale", "en")),
            data_dir=Path(str(result["dataDir"])) if result.get("dataDir") else None,
            log_dir=Path(str(result["logDir"])) if result.get("logDir") else None,
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


def start(transport, welcome: Welcome) -> list:
    """Start the plug-in proper once connected, as Krita starts a Python plug-in: import
    upstream (which registers its extension and docker with the ``krita`` stand-in), set the
    extension up and let it create its actions, then create the docker and mirror it into a
    PhotoCraft panel. Returns the mirrors, which must stay alive."""
    log.info(
        "connected to PhotoCraft %s (protocol %s, locale %s)",
        welcome.host_version,
        welcome.protocol,
        welcome.locale,
    )
    if welcome.data_dir is None:
        # Upstream would otherwise fall back to a folder of its own choosing (REQ-13.3).
        raise RuntimeError("PhotoCraft gave the plug-in no data folder")
    # The stand-in, installed as ``krita`` (install_krita_shim), used here by its own name.
    from photocraft_host import krita, qt_mirror

    krita.attach(transport, welcome.host_version, locale=welcome.locale, data_dir=welcome.data_dir)
    qt_mirror.install(transport)
    if os.environ.get("PHOTOCRAFT_PLUGIN_DEBUG") != "1":
        # Upstream opens a debugger port (debugpy, 127.0.0.1:5678) whenever its debugpy
        # checkout is present. A plug-in PhotoCraft runs must not accept code from a port
        # unasked, so the import fails and upstream skips it (it catches ImportError).
        sys.modules["debugpy"] = None  # type: ignore[assignment]

    import ai_diffusion

    from . import krita_reuse

    for config in krita_reuse.detect():  # read-only; the Connection page shows them (REQ-31.0.1)
        log.info("Krita AI Diffusion found in %s (%s)", config.folder, config.server_mode)
    from ai_diffusion.settings import settings

    settings.changed.connect(  # reuse ends when the user picks another server (REQ-31.0.11)
        lambda key, value: krita_reuse.forget_when_switched(settings, key, value)
    )

    instance = krita.Krita.instance()
    instance.load_action_file(Path(ai_diffusion.__file__).parent / "ai_diffusion.action")
    window = instance.activeWindow()
    for extension in instance.extensions():
        extension.setup()
        extension.createActions(window)
    mirrors = []
    for factory in instance.dockWidgetFactories():
        dock = instance.create_dock(factory)
        content = dock.widget()
        if content is None:
            continue
        mirror = qt_mirror.Mirror(content, transport, factory.id(), dock.windowTitle())
        mirror.start()
        mirrors.append(mirror)
        dock.canvasChanged(krita.Canvas(krita.View()) if instance.activeDocument() else None)
    return mirrors


def _application_closing():
    krita = sys.modules.get("krita")
    if krita is not None and hasattr(krita, "attach"):
        krita.Krita.instance().notifier().applicationClosing.emit()


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
    # Upstream stops its managed server when the application closes.
    serve_session(transport, app, on_shutdown=_application_closing)
    transport.start()
    plugin_id, version = identity()
    try:
        welcome = connect(
            transport, os.environ.get("PHOTOCRAFT_PLUGIN_NONCE", ""), plugin_id, version
        )
    except (transport_module.RemoteError, TimeoutError, ConnectionError) as e:
        log.error("PhotoCraft refused the connection: %s", e)
        return 2
    try:
        _running = start(transport, welcome)
    except Exception:
        log.exception("the plug-in failed to start")
        return 3
    return app.exec()


if __name__ == "__main__":
    code = main()
    # Leave without Python's teardown: it would destroy upstream's widgets after the
    # QApplication, which crashes Qt. Everything that must happen on exit (upstream stopping
    # its server, the answer to shutdown) has happened by now.
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
