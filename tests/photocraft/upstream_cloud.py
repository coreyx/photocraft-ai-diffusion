"""The cloud module boundary in a running plug-in (TASK-39, REQ-32).

    python tests/photocraft/upstream_cloud.py <data-dir> off
    python tests/photocraft/upstream_cloud.py <data-dir> stub <stub-module-dir>

``off`` (no cloud flag): a ``settings.json`` saved with the online service loads as undecided;
the Connection page offers only the local server and a custom one; and starting up, connecting
to a stand-in ComfyUI server and generating sends no request anywhere but that server.
``stub`` (``PHOTOCRAFT_AI_CLOUD=1`` with a stand-in ``ai_diffusion_cloud`` first on the path):
the online service is kept, offered under the module's name, and connecting uses the module's
client. Prints what happened as JSON; run in its own process by ``test_upstream_cloud.py``.
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
if len(sys.argv) > 3:
    sys.path.insert(0, sys.argv[3])  # the stand-in cloud module, ahead of the repository's
sys.modules["debugpy"] = None  # type: ignore[assignment]  (as the plug-in does)

from PyQt6.QtNetwork import QNetworkAccessManager
from PyQt6.QtWidgets import QApplication, QLabel


def _record_requests() -> list[str]:
    """Wrap Qt's network calls (all of upstream's HTTP goes through them) to note each host."""
    hosts: list[str] = []
    for name in ("get", "post", "put"):
        original = getattr(QNetworkAccessManager, name)

        def record(self, request, *args, _original=original):
            hosts.append(request.url().host())
            return _original(self, request, *args)

        setattr(QNetworkAccessManager, name, record)
    return hosts


def main() -> int:
    data_dir, mode = Path(sys.argv[1]), sys.argv[2]
    data_dir.mkdir(parents=True, exist_ok=True)
    token = "token-from-the-online-service"
    (data_dir / "settings.json").write_text(
        json.dumps({"server_mode": "cloud", "access_token": token, "auto_update": True})
    )
    app = QApplication([])
    hosts = _record_requests()

    from photocraft_host import main as plugin_main
    from photocraft_host import qt_mirror
    from photocraft_host.transport import Transport
    from tests.photocraft.mock_host import MockHost

    plugin_main.install_krita_shim()
    import krita

    host = MockHost()
    host.add_document("Cloud", 512, 512)
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    krita.attach(link, "test", locale="en", data_dir=data_dir)  # pyright: ignore[reportAttributeAccessIssue]
    qt_mirror.install(link)

    from ai_diffusion import eventloop
    from ai_diffusion.backend.cloud_client import CloudClient
    from ai_diffusion.model.connection import Connection, ConnectionState
    from ai_diffusion.model.root import root
    from ai_diffusion.settings import ServerMode, settings
    from ai_diffusion.ui.settings import InitialSetupWidget, SettingsDialog

    def wait(condition: Callable[[], bool], timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                return False
            app.processEvents()
            time.sleep(0.005)
        return True

    results: dict[str, Any] = {}
    eventloop.setup()
    settings.load()
    results["server_mode"] = settings.server_mode.name
    results["access_token"] = settings.access_token == token
    root.init()  # with auto_update on: the update check
    wait(lambda: False, 0.5)

    dialog = SettingsDialog(root.server)
    dialog.show()
    setup = dialog.findChildren(InitialSetupWidget)[0]
    results["setup_options"] = [
        label.text() for label in setup.findChildren(QLabel) if label.text().startswith("<b>Option")
    ]
    results["setup_links"] = [
        label.text() for label in setup.findChildren(QLabel) if "<a href" in label.text()
    ]
    select = dialog.connection._server_mode
    results["mode_buttons"] = [
        mode_name
        for mode_name, button in (
            ("cloud", select._cloud_button),
            ("managed", select._managed_button),
            ("external", select._external_button),
        )
        if not button.isHidden()
    ]

    if mode == "stub":
        settings.server_mode = ServerMode.cloud
        client = Connection().create_client(settings)
        results["cloud_client"] = {
            "module": type(client).__module__,
            "url": getattr(client, "url", None),
            "token": getattr(client, "access_token", None) == token,
        }
    else:
        from tests.photocraft.stub_comfy import StubComfy

        with StubComfy() as stub:
            settings.server_mode = ServerMode.external
            settings.server_url = stub.url
            connection = root.connection
            client = connection.create_client(settings)
            assert client is not None
            connection.connect(client)
            wait(lambda: connection.state in (ConnectionState.connected, ConnectionState.error))
            results["connection"] = connection.state.name
            model = root.model_for_active_document()
            assert model is not None
            model.regions.positive = "a lighthouse"
            model.generate()
            wait(lambda: len(stub.prompts) == 1)
            results["prompts"] = len(stub.prompts)
            results["stub_host"] = "127.0.0.1"
            try:
                CloudClient("https://example.com")
                results["cloud_client"] = "created"
            except Exception as error:
                results["cloud_client"] = type(error).__name__
    results["hosts"] = sorted(set(hosts))

    print(json.dumps(results), flush=True)
    host.close()
    return 0


if __name__ == "__main__":
    code = main()
    os._exit(code)  # see workspace_snapshots.py: no interpreter teardown
