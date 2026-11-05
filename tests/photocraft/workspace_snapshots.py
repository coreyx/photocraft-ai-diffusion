"""Mirror each of upstream's four workspaces against the mock PhotoCraft and print their widget
trees as structure snapshots (JSON). Run in its own process by ``test_workspace_snapshots.py``,
because upstream picks its data folder once, on first import, and its widgets need a
``QApplication``.

A snapshot keeps what describes the panel's structure: each node's kind, the Qt class it came
from, its visible text (labels, button text, items, titles) and its visibility. Node ids and
image hashes are left out, since they differ from run to run.

    python tests/photocraft/workspace_snapshots.py <data-dir>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from PyQt6.QtWidgets import QApplication

#: The props a snapshot keeps.
KEPT = ("text", "title", "placeholder", "checkable", "visible", "enabled", "orientation", "format")


def snapshot(mirror: Any, n: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": n["kind"]}
    widget = mirror.widget(n["id"])
    if widget is not None:
        out["qt"] = type(widget).__name__
    props = n.get("props", {})
    for key in KEPT:
        if key in props:
            out[key] = props[key]
    if "items" in props:
        out["items"] = [item.get("text", item.get("kind")) for item in props["items"]]
    if "icon" in props or "image" in props:
        out["picture"] = True
    if n.get("children"):
        out["children"] = [snapshot(mirror, c) for c in n["children"]]
    return out


def main() -> int:
    data_dir = Path(sys.argv[1])
    app = QApplication([])

    from photocraft_host import main as plugin_main
    from photocraft_host.qt_mirror import Mirror
    from photocraft_host.transport import Transport
    from tests.photocraft.mock_host import MockHost

    plugin_main.install_krita_shim()
    import krita

    host = MockHost()
    host.add_document("Snapshot", 512, 512)
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    krita.attach(link, "snapshot", locale="en", data_dir=data_dir)  # pyright: ignore[reportAttributeAccessIssue]

    from ai_diffusion import eventloop
    from ai_diffusion.model.model import Workspace
    from ai_diffusion.model.root import root
    from ai_diffusion.settings import settings
    from ai_diffusion.ui.custom_workflow import CustomWorkflowWidget
    from ai_diffusion.ui.generation import GenerationWidget
    from ai_diffusion.ui.live import LiveWidget
    from ai_diffusion.ui.upscale import UpscaleWidget

    eventloop.setup()
    settings.load()
    settings.auto_update = False  # no network
    root.init()
    model = root.model_for_active_document()
    assert model is not None

    snapshots = {}
    for name, cls, workspace in [
        ("generation", GenerationWidget, Workspace.generation),
        ("upscaling", UpscaleWidget, Workspace.upscaling),
        ("live", LiveWidget, Workspace.live),
        ("custom", CustomWorkflowWidget, Workspace.custom),
    ]:
        model.workspace = workspace
        widget = cls()
        widget.model = model  # type: ignore[attr-defined]
        app.processEvents()
        mirror = Mirror(widget, link, f"snapshot-{name}", name, poll_ms=60_000)
        mirror.start()
        tree = mirror.tree
        assert tree is not None
        snapshots[name] = snapshot(mirror, tree)
        mirror.stop()
    print(json.dumps(snapshots), flush=True)
    host.close()
    return 0


if __name__ == "__main__":
    code = main()
    # Skip interpreter teardown: Python would destroy upstream's widgets after the
    # QApplication, which crashes Qt. Everything worth keeping has been printed.
    os._exit(code)
