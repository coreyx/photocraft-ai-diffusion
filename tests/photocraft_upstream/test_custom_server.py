"""Upstream's ComfyUI client against a stand-in ComfyUI server on the ``krita`` stand-in
(TASK-38, REQ-30).

``comfy_client.py`` runs unchanged under the stand-in's event loop. Against
``tests/photocraft/stub_comfy.py``: the supported workloads it reports, refusing a server that
lacks the External Tooling Nodes (naming the pack and where to get it), probing the configured
address and then ComfyUI Desktop's port 8000 when no server is set up yet, and a dropped
websocket being reconnected with the queue kept.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import Callable
from pathlib import Path

import krita
import pytest

from ai_diffusion.backend import resources
from ai_diffusion.backend.client import MissingResources
from ai_diffusion.backend.comfy_client import ComfyClient
from ai_diffusion.document import KritaDocument
from ai_diffusion.model.connection import Connection, ConnectionState
from ai_diffusion.model.custom_workflow import WorkflowCollection
from ai_diffusion.model.model import DocumentModel
from ai_diffusion.model.root import root
from ai_diffusion.settings import ServerMode, settings
from ai_diffusion.style import Arch, Style

from ..conftest import qtapp

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)

from ..photocraft.stub_comfy import StubComfy

CHECKPOINTS = {"dreamshaper_8.safetensors": "sd15", "realvisxl.safetensors": "sdxl"}


async def _until(condition: Callable[[], bool], timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.02)


async def _connect(url: str) -> Connection:
    connection = Connection()
    connection.connect(ComfyClient(url))
    await _until(lambda: connection.state in (ConnectionState.connected, ConnectionState.error), 30)
    return connection


@qtapp
async def test_the_supported_workloads():
    with StubComfy(checkpoints=CHECKPOINTS) as stub:
        connection = await _connect(stub.url)
        assert connection.state is ConnectionState.connected, connection.error
        client = connection.client
        assert isinstance(client, ComfyClient)
        supported = client._supported_archs  # what the Connection page lists
        assert supported[Arch.sd15] == [] and supported[Arch.sdxl] == []
        flux_missing = supported[Arch.flux]
        assert any(m.kind.name == "checkpoint" for m in flux_missing), "no Flux checkpoint"
        await connection.disconnect()


@qtapp
async def test_a_server_without_the_tooling_nodes_is_refused_with_the_pack_named():
    tooling = next(
        p for p in resources.required_custom_nodes if p.folder == "comfyui-tooling-nodes"
    )
    with StubComfy(missing_nodes=tooling.nodes[:1]) as stub:
        connection = await _connect(stub.url)
        assert connection.state is ConnectionState.error
        assert connection.error_kind == "missing_resources"
        assert isinstance(connection.missing_resources, MissingResources)
        missing = connection.missing_resources.missing
        assert isinstance(missing, list), "custom nodes, not models"
        assert [(p.name, p.url) for p in missing] == [(tooling.name, tooling.url)]
        assert not [r for r in stub.requests if r.startswith("/api/etn/model_info")], "refused"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def no_server_set_up(monkeypatch: pytest.MonkeyPatch):
    """Settings as before any server is set up, with the configured address answered by nobody."""
    saved = (settings.server_mode, settings.server_url, settings.auto_update)
    settings.server_mode = ServerMode.undefined
    settings.server_url = f"127.0.0.1:{_free_port()}"
    settings.auto_update = False  # root.init() would check for updates over the network
    monkeypatch.setattr(settings, "save", lambda *_: None)
    if not hasattr(root, "_connection"):  # once per process, as in the plug-in
        root.init()
    yield
    settings.server_mode, settings.server_url, settings.auto_update = saved


@qtapp
async def test_with_no_server_set_up_port_8000_is_probed_after_the_configured_one(no_server_set_up):
    try:
        stub = StubComfy(port=8000).start()
    except OSError:
        pytest.skip("port 8000 is in use on this machine")
    try:
        await root.autostart(lambda: None)
        assert root.connection.state is ConnectionState.connected
        assert (settings.server_mode, settings.server_url) == (
            ServerMode.external,
            "127.0.0.1:8000",
        )
        await root.connection.disconnect()
    finally:
        stub.stop()


@qtapp
async def test_with_no_server_answering_nothing_is_set_up(no_server_set_up):
    """Upstream would switch to the online service; without the cloud module it stays undecided,
    so the Connection page offers the setup choices."""
    with socket.socket() as busy:
        try:
            busy.bind(("127.0.0.1", 8000))  # nothing answers on 8000 either
        except OSError:
            pytest.skip("port 8000 is in use on this machine")
        await root.autostart(lambda: None)
    assert root.connection.state is ConnectionState.disconnected
    assert settings.server_mode is ServerMode.undefined


@qtapp
async def test_a_dropped_websocket_is_reconnected_and_the_queue_kept(tmp_path: Path):
    with StubComfy(checkpoints=CHECKPOINTS) as stub:
        connection = await _connect(stub.url)
        assert connection.state is ConnectionState.connected, connection.error
        doc = KritaDocument.active() or KritaDocument(krita.Document(), None)  # pyright: ignore[reportCallIssue]
        model = DocumentModel(doc, connection, WorkflowCollection(connection, folder=tmp_path))
        style = Style(tmp_path / "sd15.json")
        style.checkpoints = ["dreamshaper_8.safetensors"]
        model.style = style
        model.regions.positive = "a lighthouse"
        for _ in range(3):
            model.generate()
        # ComfyUI gets one prompt at a time; the others wait in the plug-in's queue.
        await _until(lambda: len(stub.prompts) == 1)
        client = connection.client
        assert isinstance(client, ComfyClient)
        await _until(lambda: client.queued_count == 3)
        await _until(lambda: stub.websocket_connects >= 2)  # the connect check and the listener

        connects = stub.websocket_connects
        stub.drop_websockets()
        await _until(
            lambda: connection.error != ""
        )  # "Disconnected from server, trying to reconnect..."
        await _until(lambda: stub.websocket_connects > connects, 20)
        await _until(lambda: connection.error == "")
        assert connection.state is ConnectionState.connected
        assert client.queued_count == 3, "the queue is kept"
        assert len(stub.prompts) == 1, "nothing sent twice"
        await connection.disconnect()
