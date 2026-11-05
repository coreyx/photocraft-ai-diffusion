"""Use upstream's real Generate workspace through the Qt mirror, as PhotoCraft would: type a
prompt, re-weight a word with Ctrl+Up, pick a tag from autocomplete, and click the generate
button (sent as an image). Prints what happened as JSON; run in its own process by
``test_upstream_interactions.py``, for the same reasons as ``workspace_snapshots.py``.

    python tests/photocraft/upstream_interactions.py <data-dir>
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from PyQt6.QtWidgets import QApplication


def main() -> int:
    data_dir = Path(sys.argv[1])
    app = QApplication([])

    from photocraft_host import main as plugin_main
    from photocraft_host import qt_mirror
    from photocraft_host.qt_mirror import Mirror
    from photocraft_host.transport import Transport
    from tests.photocraft.mock_host import MockHost, find_widget

    plugin_main.install_krita_shim()
    import krita

    host = MockHost()
    host.add_document("Interactions", 512, 512)
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    krita.attach(link, "test", locale="en", data_dir=data_dir)  # pyright: ignore[reportAttributeAccessIssue]
    qt_mirror.install(link)

    from ai_diffusion import eventloop
    from ai_diffusion.model.root import root
    from ai_diffusion.settings import settings
    from ai_diffusion.ui.generation import GenerationWidget
    from ai_diffusion.ui.widget import GenerateButton, TextPromptWidget

    eventloop.setup()
    settings.load()
    settings.auto_update = False
    settings.tag_files = ["Danbooru"]
    settings.prompt_translation = "fr"
    root.init()
    model = root.model_for_active_document()
    assert model is not None
    widget = GenerationWidget()
    widget.model = model
    mirror = Mirror(widget, link, "generate", "Generate", poll_ms=60_000)
    mirror.start()

    def wait(condition: Callable[[], bool], timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                return False
            app.processEvents()
            time.sleep(0.005)
        return True

    def send(node_id: str, kind: str, value: Any, **modifiers: bool):
        handled: list[bool] = []
        link.on("panel.input", lambda *_: handled.append(True))
        host.send_event(
            "panel.input",
            {
                "owner": "generate",
                "nodeId": node_id,
                "kind": kind,
                "value": value,
                "modifiers": modifiers,
            },
        )
        wait(lambda: bool(handled))
        mirror.flush()

    prompt = next(p for p in widget.findChildren(TextPromptWidget) if not p.is_negative)
    prompt_id = mirror.node_id(prompt)
    results: dict[str, Any] = {}

    send(prompt_id, "change", "a cat")
    # Typing "cat" opens the tag completer; while it is open the arrow keys move its highlight
    # (in Krita too), so it is closed first.
    node = find_widget(host.panels["generate"]["tree"], prompt_id) or {}
    results["completer_opened"] = bool(node.get("props", {}).get("completions"))
    send(prompt_id, "key", "Escape")
    send(prompt_id, "cursor", {"anchor": 2, "cursor": 5})
    send(prompt_id, "key", "Up", ctrl=True)
    results["weighted"] = prompt.text
    results["model_prompt"] = model.regions.positive

    send(prompt_id, "change", prompt.text + ", 1gir")
    send(prompt_id, "cursor", {"anchor": len(prompt.text), "cursor": len(prompt.text)})
    node = find_widget(host.panels["generate"]["tree"], prompt_id) or {}
    completions = node.get("props", {}).get("completions", [])
    results["completions"] = completions[:3]
    if completions:
        send(prompt_id, "menu", 0)
    results["completed"] = prompt.text

    button = next(iter(widget.findChildren(GenerateButton)))
    button_node = find_widget(host.panels["generate"]["tree"], mirror.node_id(button)) or {}
    results["button_kind"] = button_node.get("kind")
    clicks: list[bool] = []
    button.clicked.connect(lambda: clicks.append(True))
    send(mirror.node_id(button), "pointer", {"x": 10, "y": 10, "button": "left", "action": "click"})
    results["generate_clicked"] = bool(clicks)
    results["error"] = model.error.message if model.error else ""

    # The prompt's translation badge: shows the language, and clicking it switches translation off.
    from PyQt6.QtWidgets import QToolButton

    badge = next(b for b in widget.findChildren(QToolButton) if b.text() == "FR" and b.isVisible())
    badge_node = find_widget(host.panels["generate"]["tree"], mirror.node_id(badge)) or {}
    results["badge"] = badge_node.get("props", {}).get("text")
    results["language_before"] = model.prompt_translation_language
    send(mirror.node_id(badge), "click", 1)
    badge_node = find_widget(host.panels["generate"]["tree"], mirror.node_id(badge)) or {}
    results["badge_after"] = badge_node.get("props", {}).get("text")
    results["language_after"] = model.prompt_translation_language

    # Upscale: without the tile/unblur control model, Image guidance is disabled and says why.
    from ai_diffusion.ui.upscale import UpscaleWidget

    upscale = UpscaleWidget()
    upscale.model = model
    # Upstream sets the control's state when the connection reports its models, as on
    # connecting to a server that lacks the tile/unblur model.
    root.connection.models_changed.emit()
    upscale_mirror = Mirror(upscale, link, "upscale", "Upscale", poll_ms=60_000)
    upscale_mirror.start()
    upscale_mirror.flush()
    unblur = (
        find_widget(
            host.panels["upscale"]["tree"], upscale_mirror.node_id(upscale.unblur_slider.widget())
        )
        or {}
    )
    results["unblur_enabled"] = unblur.get("props", {}).get("enabled")
    results["unblur_tooltip"] = unblur.get("props", {}).get("tooltip")
    upscale_mirror.stop()

    print(json.dumps(results), flush=True)
    mirror.stop()
    host.close()
    return 0


if __name__ == "__main__":
    code = main()
    from photocraft_host import framing

    framing.leave(code)  # no interpreter teardown; saves a coverage measurement
