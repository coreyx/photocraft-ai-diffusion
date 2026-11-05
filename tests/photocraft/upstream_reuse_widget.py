"""The Connection page's Krita AI Diffusion section, used as the user would, and what happened.

    python tests/photocraft/upstream_reuse_widget.py <data-dir> <work-dir>

Builds the section (``photocraft_host.krita_reuse_widget``) on the plug-in's root, with
configurations made in ``work-dir`` and stand-in ComfyUI servers, and prints JSON: what the
section lists and when it looks again, importing with the token declined and then confirmed,
using a custom server, and a reused server that lacks nodes (the two ways on: this plug-in's own
server sharing the models, or connecting anyway). Message boxes are answered by a stand-in.
Run in its own process by ``test_upstream_reuse_widget.py``: widgets need a ``QApplication``,
which the in-process harness doesn't have.
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

from PyQt6.QtWidgets import QApplication, QMessageBox


class Boxes:
    """Stands in for ``QMessageBox`` in the section: answers questions, records what it says."""

    StandardButton = QMessageBox.StandardButton

    def __init__(self):
        self.answer = QMessageBox.StandardButton.No
        self.questions: list[str] = []
        self.said: list[str] = []

    def question(self, _parent, _title, text, *_args):
        self.questions.append(text)
        return self.answer

    def information(self, _parent, _title, text):
        self.said.append(text)


def _install(server_dir: Path, version: str) -> Path:
    """A Krita AI Diffusion managed install, as far as detection looks: ComfyUI, its custom
    nodes, a venv, the required models and its ``.version``."""
    from ai_diffusion.backend import resources

    comfy = server_dir / "ComfyUI"
    for package in resources.required_custom_nodes:
        (comfy / "custom_nodes" / package.folder).mkdir(parents=True, exist_ok=True)
    (comfy / "main.py").write_text("")
    venv = server_dir / "venv" / ("Scripts" if os.name == "nt" else "bin")
    venv.mkdir(parents=True, exist_ok=True)
    (venv / ("python.exe" if os.name == "nt" else "python3")).write_bytes(b"")
    for model in resources.required_models:
        for file in model.files:
            (server_dir / file.path).parent.mkdir(parents=True, exist_ok=True)
            (server_dir / file.path).write_bytes(b"model")
    (server_dir / ".version").write_text(version)
    return server_dir


def main() -> int:
    data_dir, work = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "settings.json").write_text('{"auto_update": false}')
    app = QApplication([])

    from photocraft_host import main as plugin_main
    from photocraft_host.transport import Transport
    from tests.photocraft.mock_host import MockHost

    plugin_main.install_krita_shim()
    import krita

    host = MockHost()
    host.add_document("Reuse", 256, 256)
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    krita.attach(link, "test", locale="en", data_dir=data_dir)  # pyright: ignore[reportAttributeAccessIssue]

    from ai_diffusion import eventloop
    from ai_diffusion.backend import resources
    from ai_diffusion.model.connection import ConnectionState
    from ai_diffusion.model.root import root
    from ai_diffusion.settings import settings
    from photocraft_host import krita_reuse
    from photocraft_host import krita_reuse_widget as section
    from tests.photocraft.stub_comfy import StubComfy

    eventloop.setup()
    settings.load()
    root.init()
    boxes = Boxes()
    section.QMessageBox = boxes  # type: ignore[assignment]

    def wait(condition: Callable[[], bool], timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                return False
            app.processEvents()
            time.sleep(0.005)
        return True

    def config(folder: Path, **values: Any) -> krita_reuse.KritaConfig:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "settings.json").write_text(json.dumps(values))
        found = krita_reuse.read_config(folder, "Krita")
        assert found is not None
        return found

    configs: list[krita_reuse.KritaConfig] = []
    widget = section.KritaReuseWidget(detect=lambda: list(configs))
    configured: list[bool] = []
    widget.configured.connect(lambda: configured.append(True))
    results: dict[str, Any] = {"empty_at_first": not widget._empty.isHidden()}

    # What the section lists, and looking again.
    install = _install(work / "managed" / "server", "1.53.0 cuda")
    configs += [
        config(work / "managed", server_mode="managed", server_backend="cuda"),
        config(work / "custom", server_mode="external", server_url="192.0.2.5:8188"),
        config(work / "unset"),
    ]
    widget.refresh()
    managed, custom, unset = (widget.item(c) for c in configs)
    text = managed.summary.text()
    results["listed"] = {
        "empty_hidden": widget._empty.isHidden(),
        "managed": str(install) in text and "Model folders" in text and "1.53.0" in text,
        "custom": "192.0.2.5:8188" in custom.summary.text(),
        "use_offered": [not i.use_button.isHidden() for i in (managed, custom, unset)],
    }
    configs.pop()
    widget.refresh()
    results["listed"]["after_looking_again"] = len(widget._items)

    # Importing: the token only once confirmed again.
    secret = config(
        work / "secret",
        server_mode="external",
        server_url="192.0.2.6:8188",
        server_authorization="secret-token",
        history_size=2400,
    )
    configs[:] = [secret]
    widget.refresh()
    settings.server_authorization = ""
    widget.item(secret).import_button.click()
    declined = settings.server_authorization
    boxes.answer = QMessageBox.StandardButton.Yes
    widget.import_from(secret)
    results["import"] = {
        "questions": len(boxes.questions),
        "token_when_declined": declined,
        "token_when_confirmed": settings.server_authorization == "secret-token",
        "history_size": settings.history_size,
        "said": [s.startswith("Imported") for s in boxes.said],
    }
    settings.server_authorization = ""

    # Using a custom server.
    with StubComfy() as stub:
        custom_config = config(work / "use", server_mode="external", server_url=stub.url)
        configs[:] = [custom_config]
        widget.refresh()
        configured.clear()
        widget.item(custom_config).use_button.click()
        connected = wait(lambda: root.connection.state is ConnectionState.connected)
        results["use"] = {
            "configured": bool(configured),
            "url": settings.server_url == stub.url,
            "connected": connected,
        }
        eventloop.run(root.connection.disconnect())
        wait(lambda: root.connection.state is ConnectionState.disconnected)

    # A reused server lacking nodes: the two ways on.
    tooling = next(
        p for p in resources.required_custom_nodes if p.folder == "comfyui-tooling-nodes"
    )
    with StubComfy(missing_nodes=tooling.nodes[:1]) as lacking:
        lacking_config = config(work / "lacking", server_mode="external", server_url=lacking.url)
        configs[:] = [lacking_config]
        widget.refresh()
        widget.use(lacking_config)
        wait(lambda: root.connection.state is ConnectionState.error)
        offered = {
            "error_kind": root.connection.error_kind,
            "own_server": not widget._own_server_button.isHidden(),
            "anyway": not widget._anyway_button.isHidden(),
        }
        settings.check_server_resources = True
        widget._anyway_button.click()
        offered["checks_resources_after_anyway"] = settings.check_server_resources
        wait(lambda: root.connection.state is not ConnectionState.connecting)
        eventloop.run(root.connection.disconnect())
        wait(lambda: root.connection.state is ConnectionState.disconnected)

    shared = config(work / "shared", server_mode="managed")
    _install(work / "shared" / "server", "1.53.0 cuda")
    configs[:] = [shared]
    widget.refresh()
    settings.photocraft_reuse = {"source_settings": str(shared.folder / "settings.json")}
    configured.clear()
    widget._own_server_button.click()
    offered["shared_mode"] = settings.photocraft_reuse.get("mode")
    offered["notice_names_the_install"] = str(shared.server_path) in widget.notice.text()
    configs.clear()
    widget.refresh()
    configured.clear()
    widget.share_models()  # the reused configuration is gone: nothing to share
    offered["shared_without_a_source"] = bool(configured)
    results["lacking"] = offered

    print(json.dumps(results), flush=True)
    host.close()
    return 0


if __name__ == "__main__":
    code = main()
    from photocraft_host import framing

    framing.leave(code)  # no interpreter teardown; saves a coverage measurement
