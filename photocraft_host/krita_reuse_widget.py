"""The Connection page's Krita AI Diffusion section (REQ-31, design D10).

It shows each Krita AI Diffusion configuration found on this machine (where it is, its server
mode, the server address or install folder, the backend, the version and the model folders),
with a button to look again, and for each:

- **Use the same ComfyUI server**: a custom server's address, or a managed install, which is
  connected to if it runs and started as the managed server is otherwise. Nothing is installed
  and no model is downloaded.
- **Import settings**: its settings and user files; tokens only after a separate confirmation.

It also says when the reused install was moved, deleted or changed, and when the reused server
lacks what this plug-in needs, offers this plug-in's own server sharing the same models, or
connecting anyway with those features disabled.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ai_diffusion import eventloop, util
from ai_diffusion.backend.comfy_client import ComfyClient
from ai_diffusion.backend.server import ServerState
from ai_diffusion.localization import translate as _
from ai_diffusion.model.connection import ConnectionState
from ai_diffusion.model.root import root
from ai_diffusion.settings import Settings, settings

from . import krita_reuse
from .krita_reuse import KritaConfig

_MODES = {
    "managed": "Local Managed Server",
    "external": "Custom Server",
    "cloud": "Online Service",
    "undefined": "Not set up",
}


def describe(config: KritaConfig) -> str:
    """One configuration as rich text: its mode and the details that matter for using it."""
    rows = [(_("Server"), _(_MODES.get(config.server_mode, config.server_mode)))]
    if config.is_custom:
        rows.append((_("Address"), config.server_url))
    elif config.is_managed:
        rows.append((_("Install folder"), str(config.server_path)))
        backend = config.installed_backend or config.server_backend
        rows.extend((
            (_("Backend"), backend or _("unknown")),
            (_("Version"), config.version or _("not installed")),
        ))
    if config.plugin_version:
        rows.append((_("Plugin version"), config.plugin_version))
    lines = [f"<b>{escape(config.location)}</b>: {escape(str(config.folder))}"]
    lines += [f"&nbsp;&nbsp;{escape(name)}: {escape(value)}" for name, value in rows]
    if config.is_managed:
        folders = "<br>".join(
            f"&nbsp;&nbsp;&nbsp;&nbsp;{escape(str(f))}" for f in config.model_folders
        )
        lines.append(
            f"&nbsp;&nbsp;{escape(_('Model folders'))}: "
            + (f"<br>{folders}" if folders else _("none found"))
        )
    return "<br>".join(lines)


class _ConfigWidget(QWidget):
    """One configuration, with its actions."""

    def __init__(self, config: KritaConfig, parent: KritaReuseWidget):
        super().__init__(parent)
        self.config = config
        self.summary = QLabel(describe(config), self)
        self.summary.setWordWrap(True)
        self.use_button = QPushButton(_("Use the same ComfyUI server"), self)
        self.use_button.setVisible(config.is_custom or config.is_managed)
        self.use_button.clicked.connect(lambda: parent.use(config))
        self.import_button = QPushButton(_("Import settings"), self)
        self.import_button.clicked.connect(lambda: parent.import_from(config))

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.use_button)
        buttons.addWidget(self.import_button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.addWidget(self.summary)
        layout.addLayout(buttons)


class KritaReuseWidget(QWidget):
    """Shows the Krita AI Diffusion configurations found and lets the user use or import one."""

    #: The settings changed: the page shows them again.
    configured = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        detect: Callable[[], list[KritaConfig]] = krita_reuse.detect,
    ):
        super().__init__(parent)
        self._detect = detect
        self.configs: list[KritaConfig] = []
        self._items: list[_ConfigWidget] = []

        self._detect_button = QPushButton(_("Detect Krita AI Diffusion"), self)
        self._detect_button.clicked.connect(self.refresh)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(QLabel("<b>" + _("Krita AI Diffusion") + "</b>", self), 1)
        header.addWidget(self._detect_button)

        self._empty = QLabel(_("No Krita AI Diffusion configuration found on this computer."), self)
        self.notice = QLabel(self)
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet("font-weight:bold")
        self.notice.setVisible(False)

        self._own_server_button = QPushButton(_("Set up my own server sharing these models"), self)
        self._own_server_button.clicked.connect(self.share_models)
        self._anyway_button = QPushButton(_("Connect anyway, with those features disabled"), self)
        self._anyway_button.clicked.connect(self.connect_anyway)
        fallback = QHBoxLayout()
        fallback.setContentsMargins(0, 0, 0, 0)
        fallback.addWidget(self._own_server_button)
        fallback.addWidget(self._anyway_button)
        fallback.addStretch()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 8)
        self._layout.addLayout(header)
        self._layout.addWidget(self._empty)
        self._configs_layout = QVBoxLayout()
        self._configs_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addLayout(self._configs_layout)
        self._layout.addWidget(self.notice)
        self._layout.addLayout(fallback)

        root.connection.state_changed.connect(self._update_fallback)
        self.refresh()

    def refresh(self):
        """Look for configurations again (read-only), and check the one in use."""
        for item in self._items:
            self._configs_layout.removeWidget(item)
            item.deleteLater()
        self.configs = self._detect()
        self._items = [_ConfigWidget(config, self) for config in self.configs]
        for item in self._items:
            self._configs_layout.addWidget(item)
        self._empty.setVisible(not self.configs)
        self._show_notice(krita_reuse.validate(settings))
        self._update_fallback()

    def item(self, config: KritaConfig) -> _ConfigWidget:
        return next(i for i in self._items if i.config is config)

    def _show_notice(self, text: str | None):
        self.notice.setText(text or "")
        self.notice.setVisible(bool(text))

    def _source(self) -> KritaConfig | None:
        """The configuration the reuse in effect came from."""
        source = settings.photocraft_reuse.get("source_settings", "")
        return next((c for c in self.configs if str(c.folder / "settings.json") == source), None)

    def _update_fallback(self, *_):
        reused = bool(settings.photocraft_reuse) and self._source() is not None
        missing = root.connection.error_kind == "missing_resources"
        self._own_server_button.setVisible(reused and missing)
        self._anyway_button.setVisible(reused and missing)

    # -- actions

    def use(self, config: KritaConfig):
        """Use the server ``config`` uses (REQ-31.0.3, 31.0.4)."""
        krita_reuse.use_same_server(config, settings)
        self._show_notice(None)
        self.configured.emit()
        eventloop.run(self._connect(config))

    async def _connect(self, config: KritaConfig):
        connection = root.connection
        if config.is_custom:
            if client := connection.create_client(settings):
                await connection._connect(client)
            return
        server = root.server
        server.path = Path(settings.server_path)
        server.backend = settings.server_backend
        server.check_install()
        self.configured.emit()
        # Krita AI Diffusion may have started it already; otherwise start it as the managed
        # server is started.
        await connection._connect(ComfyClient(krita_reuse.managed_url(config)))
        if connection.state is ConnectionState.connected:
            return
        if server.state in (ServerState.stopped, ServerState.missing_resources):
            url = await server.start()
            self.configured.emit()
            await connection._connect(ComfyClient(url))

    def import_from(self, config: KritaConfig):
        """Import ``config``'s settings and files (REQ-31.0.7); tokens only if confirmed again
        (REQ-31.0.8)."""
        secrets = False
        if config.has_secrets:
            answer = QMessageBox.question(
                self,
                _("Import settings"),
                _(
                    "Krita AI Diffusion's settings include a server access token. Import it too? It is only needed to connect to a server that requires it."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            secrets = answer == QMessageBox.StandardButton.Yes
        result = krita_reuse.import_settings(config, util.user_data_dir, settings, secrets)
        self.configured.emit()
        QMessageBox.information(
            self,
            _("Import settings"),
            _("Imported {settings} settings and {files} files from Krita AI Diffusion.").format(
                settings=len(result["settings"]), files=len(result["files"])
            ),
        )

    def share_models(self):
        """This plug-in's own managed server, using the reused install's models (REQ-31.0.6)."""
        if (config := self._source()) is None:
            return
        krita_reuse.share_models(config, settings, Path(Settings._server_path.default))
        server = root.server
        server.path = Path(settings.server_path)
        server.check_install()
        self.configured.emit()
        self._show_notice(
            _(
                "Install your own server below: models already in {path} are not downloaded again."
            ).format(path=str(config.server_path))
        )

    def connect_anyway(self):
        """Keep the reused server, with the features it lacks disabled (REQ-31.0.6)."""
        settings.check_server_resources = False
        settings.save()
        connection = root.connection
        if client := connection.create_client(settings):
            eventloop.run(connection._connect(client))
