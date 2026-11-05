"""The Connection page's Krita AI Diffusion section (REQ-31.0.2, design D10).

It shows each Krita AI Diffusion configuration found on this machine: where it is, its server
mode, the server address or install folder, the backend, the version and the model folders,
with a button to look again. Using that server and importing its settings come with TASK-41.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ai_diffusion.localization import translate as _

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
        folders = "<br>".join(escape(str(f)) for f in config.model_folders) or _("none found")
        rows.append((_("Model folders"), folders))
    if config.plugin_version:
        rows.append((_("Plugin version"), config.plugin_version))
    lines = [f"<b>{escape(config.location)}</b>: {escape(str(config.folder))}"]
    for name, value in rows:
        value = value if name == _("Model folders") else escape(value)
        lines.append(f"&nbsp;&nbsp;{escape(name)}: {value}")
    return "<br>".join(lines)


class KritaReuseWidget(QWidget):
    """Shows the Krita AI Diffusion configurations found, and finds them again on request."""

    def __init__(
        self,
        parent: QWidget | None = None,
        detect: Callable[[], list[KritaConfig]] = krita_reuse.detect,
    ):
        super().__init__(parent)
        self._detect = detect
        self.configs: list[KritaConfig] = []

        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._detect_button = QPushButton(_("Detect Krita AI Diffusion"), self)
        self._detect_button.clicked.connect(self.refresh)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(QLabel("<b>" + _("Krita AI Diffusion") + "</b>", self), 1)
        header.addWidget(self._detect_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.addLayout(header)
        layout.addWidget(self._summary)
        self.refresh()

    def refresh(self):
        """Look for configurations again (read-only) and show what was found."""
        self.configs = self._detect()
        if self.configs:
            self._summary.setText("<br><br>".join(describe(c) for c in self.configs))
        else:
            self._summary.setText(_("No Krita AI Diffusion configuration found on this computer."))
