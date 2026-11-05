"""Start the plug-in as PhotoCraft does, in one language, and report the text PhotoCraft shows.

    python tests/photocraft/upstream_languages.py <data-dir> <language|-> <host-locale>

``language`` is set in ``settings.json`` (``-``: not set, so the host's locale decides). The
docker panel and the settings dialog are opened through the mirror, and every text, title and
item label PhotoCraft received is printed as JSON, with the language the plug-in chose. Run in
its own process by ``test_upstream_languages.py``: strings are translated at import.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from PyQt6.QtWidgets import QApplication


def _texts(node: Any, out: set[str]):
    """Every text PhotoCraft would show from a mirrored tree."""
    if isinstance(node, dict):
        props = node.get("props", {})
        for key in ("text", "title", "placeholder", "tooltip"):
            if isinstance(props.get(key), str):
                out.add(props[key])
        for item in props.get("items", []) or []:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                out.add(item["text"])
            elif isinstance(item, str):
                out.add(item)
        for child in node.get("children", []) or []:
            _texts(child, out)


def main() -> int:
    data_dir, language, locale = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    data_dir.mkdir(parents=True, exist_ok=True)
    settings: dict[str, Any] = {"auto_update": False}
    if language != "-":
        settings["language"] = language
    (data_dir / "settings.json").write_text(json.dumps(settings))
    app = QApplication([])

    from photocraft_host import main as plugin_main
    from photocraft_host.transport import Transport
    from tests.photocraft.mock_host import MockHost

    plugin_main.install_krita_shim()
    host = MockHost()
    host.add_document("Languages", 256, 256)
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    welcome = plugin_main.Welcome("test", 1, locale, data_dir, None, True)
    mirrors = plugin_main.start(link, welcome)

    from ai_diffusion.localization import Localization

    def wait(condition, timeout: float = 10.0):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    handled: list[bool] = []
    link.on("action.triggered", lambda *_: handled.append(True))
    host.send_event("action.triggered", {"id": "ai_diffusion_settings"})
    wait(lambda: bool(handled) and bool(host.dialogs))
    for mirror in mirrors:
        mirror.flush()
    texts: set[str] = set()
    for panel in host.panels.values():
        texts.add(panel.get("title", ""))
        _texts(panel.get("tree"), texts)
    for dialog in host.dialogs.values():
        texts.add(dialog.get("title", ""))
        _texts(dialog.get("tree"), texts)

    print(json.dumps({"language": Localization.current.id, "texts": sorted(texts)}), flush=True)
    host.close()
    return 0


if __name__ == "__main__":
    code = main()
    os._exit(code)  # see workspace_snapshots.py: no interpreter teardown
