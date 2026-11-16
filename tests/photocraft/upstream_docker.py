"""Start the plug-in as PhotoCraft does (``photocraft_host.main.start``) against the mock
PhotoCraft, then use upstream's actions and docker: trigger each of the 15 actions, read the
workspace menu, cycle workspaces, and leave Live while it runs. Prints what happened as JSON;
run in its own process by ``test_upstream_docker.py``.

    python tests/photocraft/upstream_docker.py <data-dir>
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
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "settings.json").write_text('{"auto_update": false}')  # no network
    app = QApplication([])
    errors: list[str] = []
    sys.excepthook = lambda kind, value, tb: errors.append(f"{kind.__name__}: {value}")

    from photocraft_host import main as plugin_main
    from photocraft_host.transport import Transport
    from tests.photocraft.mock_host import MockHost, find_widget

    plugin_main.install_krita_shim()
    host = MockHost()
    host.add_document("Docker", 1024, 1024)
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    welcome = plugin_main.Welcome("test", 1, "en", data_dir, None, True)
    mirrors = plugin_main.start(link, welcome)

    from ai_diffusion.model.model import Workspace
    from ai_diffusion.model.root import root

    def wait(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                return False
            app.processEvents()
            time.sleep(0.005)
        return True

    def trigger(action_id: str):
        handled: list[bool] = []
        link.on("action.triggered", lambda *_: handled.append(True))
        host.send_event("action.triggered", {"id": action_id})
        wait(lambda: bool(handled))
        app.processEvents()

    model = root.model_for_active_document()
    assert model is not None
    results: dict[str, Any] = {
        "actions": {a: v["label"] for a, v in host.actions.items()},
        "panels": {p: v["title"] for p, v in host.panels.items()},
    }

    mirror = mirrors[0]
    mirror.flush()
    results["panel_root"] = (
        find_widget(host.panels["imageDiffusion"]["tree"], mirror.node_id(mirror.root)) is not None
    )
    # The docker shows its welcome page until connected; the workspace selector's menu is read
    # the way the mirror sends it as the button's menu prop.
    from ai_diffusion.ui.widget import WorkspaceSelectWidget
    from photocraft_host.qt_mirror import menus

    selectors = [w for w in app.allWidgets() if isinstance(w, WorkspaceSelectWidget)]
    menu = selectors[0].menu() if selectors else None
    results["workspace_menu"] = (
        [e.get("text") for e in menus.items_of(menu, mirror)] if menu else []
    )

    workspaces = []
    for name in ("upscaling", "live", "graph", "generation"):
        trigger(f"ai_diffusion_switch_workspace_{name}")
        workspaces.append(model.workspace.name)
    results["switched"] = workspaces

    results["target_size"] = target_size_on_hover(app, host, link, model, wait)

    cycle = []
    for _ in range(5):
        trigger("ai_diffusion_toggle_workspace")
        cycle.append(model.workspace.name)
    results["toggle_cycle"] = cycle

    model.workspace = Workspace.live
    model.live._is_active = True  # running, without a server to generate with
    trigger("ai_diffusion_switch_workspace_generation")
    results["live_after_leaving"] = model.live.is_active

    regions = len(model.regions)
    trigger("ai_diffusion_create_region")
    results["regions_added"] = len(model.regions) - regions
    edit = model.edit_mode
    trigger("ai_diffusion_toggle_edit_mode")
    results["edit_mode_toggled"] = model.edit_mode != edit

    dialogs_before = len([m for m, _ in host.calls if m == "dialog.open"])
    trigger("ai_diffusion_settings")
    wait(lambda: len([m for m, _ in host.calls if m == "dialog.open"]) > dialogs_before)
    opened = [p for m, p in host.calls if m == "dialog.open"]
    results["settings_dialog"] = opened[-1]["title"] if opened else None

    for action_id in host.actions:
        if action_id != "ai_diffusion_settings":
            trigger(action_id)
    results["errors"] = errors

    print(json.dumps(results), flush=True)
    host.close()
    return 0


def target_size_on_hover(app, host, link, model, wait) -> dict[str, str]:
    """Upscale's "Target size" line: when the page is first shown, while the pointer is over the
    scale row as the slider moves, and after it leaves (spec ``upscale-target-size-hover``).

    The docker shows its workspaces only once a server is connected, so an Upscale page of its
    own is mirrored as a second panel. It gets the document's scale before it is first laid
    out, as when the docker gives it the document on connecting: with Qt's offscreen cursor at
    its starting point, the page took that for the pointer over the scale row."""
    from ai_diffusion.ui.upscale import FactorWidget, UpscaleWidget
    from photocraft_host.qt_mirror import Mirror

    page = UpscaleWidget()
    # Upstream's setter binds nothing when given the model the widget started with (the active
    # document's, here); the docker gives it the document's model after starting with none.
    page._model = None  # pyright: ignore[reportAttributeAccessIssue]
    page.model = model  # binding applies the document's scale, 2x, before any layout
    factor = page.findChild(FactorWidget)
    assert factor is not None
    mirror = Mirror(page, link, "upscaleCheck", "Upscale", poll_ms=60_000)
    mirror.start()

    def send(widget: Any, kind: str, value: Any):
        mirror.flush()
        handled: list[bool] = []
        link.on("panel.input", lambda *_: handled.append(True))
        data = {"owner": "upscaleCheck", "nodeId": mirror.node_id(widget), "kind": kind}
        host.send_event("panel.input", {**data, "value": value, "modifiers": {}})
        wait(lambda: bool(handled))
        app.processEvents()

    seen = {"shown": factor.target_label.text()}
    send(factor, "hover", True)
    send(factor.slider, "change", 250)
    seen["dragged"] = factor.target_label.text()
    send(factor, "hover", False)
    seen["left"] = factor.target_label.text()
    mirror.stop()
    return seen


if __name__ == "__main__":
    code = main()
    from photocraft_host import framing

    framing.leave(code)  # no interpreter teardown; saves a coverage measurement
