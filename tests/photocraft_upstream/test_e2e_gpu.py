r"""End to end on a GPU: the plug-in, on the ``krita`` stand-in with the mock PhotoCraft, against a
real ComfyUI with real models (TASK-45, REQ-39.0.6).

Skipped unless ``PHOTOCRAFT_E2E_COMFYUI`` names a server (``127.0.0.1:8188``); it then
generates, inpaints, runs Live, upscales, runs a custom graph, generates with a control layer,
and uses a Krita AI Diffusion configuration found on this machine, with whatever SD 1.5 (or
SDXL) checkpoint the server has. Cases whose models are missing are skipped. Logs are audited
for the token used, and every host asked against the allow-list.

``PHOTOCRAFT_E2E_INSTALL=<empty folder>`` additionally runs the managed CUDA install of the SDXL
workload (REQ-29.1): tens of gigabytes and most of an hour.

    PHOTOCRAFT_E2E_COMFYUI=127.0.0.1:8188 python -m pytest -p tests.photocraft.upstream_shim \\
        tests/photocraft_upstream/test_e2e_gpu.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import krita
import pytest
from krita import Krita, Selection
from PyQt6.QtCore import QByteArray
from PyQt6.QtNetwork import QNetworkAccessManager

from ai_diffusion import util
from ai_diffusion.backend.comfy_client import ComfyClient
from ai_diffusion.backend.resources import Arch, ControlMode
from ai_diffusion.document import KritaDocument
from ai_diffusion.image import Bounds, Extent, Image
from ai_diffusion.model.connection import Connection, ConnectionState
from ai_diffusion.model.custom_workflow import WorkflowCollection
from ai_diffusion.model.jobs import Job
from ai_diffusion.model.model import DocumentModel, Workspace
from ai_diffusion.model.root import root
from ai_diffusion.settings import ApplyBehavior, settings
from ai_diffusion.style import Style

from ..conftest import qtapp

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)

URL = os.environ.get("PHOTOCRAFT_E2E_COMFYUI", "")
INSTALL = os.environ.get("PHOTOCRAFT_E2E_INSTALL", "")
pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(not URL, reason="needs a ComfyUI with models: PHOTOCRAFT_E2E_COMFYUI"),
    pytest.mark.timeout(900),
]
TOKEN = "e2e-audit-token-31c7"


def _shim():
    from ..photocraft import upstream_shim

    return upstream_shim


@pytest.fixture(scope="module", autouse=True)
def recorded_hosts():
    """Every host Qt's network calls ask during the suite (all of upstream's HTTP)."""
    hosts: list[str] = []
    originals = {name: getattr(QNetworkAccessManager, name) for name in ("get", "post", "put")}
    for name, original in originals.items():

        def record(self, request, *args, _original=original):
            hosts.append(request.url().host())
            return _original(self, request, *args)

        setattr(QNetworkAccessManager, name, record)
    yield hosts
    for name, original in originals.items():
        setattr(QNetworkAccessManager, name, original)


async def _until(condition: Callable[[], bool], timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError(what)
        await asyncio.sleep(0.05)


def _checkpoint(client: ComfyClient) -> tuple[str, Arch]:
    """An installed checkpoint of a supported workload: SD 1.5 first (fastest), else SDXL."""
    preferred = os.environ.get("PHOTOCRAFT_E2E_CHECKPOINT")
    for arch in (Arch.sd15, Arch.sdxl):
        if client._supported_archs.get(arch) != []:
            continue
        for name, info in sorted(client.models.checkpoints.items()):
            if info.arch is arch and (not preferred or name == preferred):
                return name, arch
    pytest.skip("the server has no SD 1.5 or SDXL checkpoint with its required models")


@asynccontextmanager
async def _session(tmp_path: Path, size: int = 512):
    """The plug-in connected to the real server, with a document open in the mock PhotoCraft."""
    saved = settings.server_authorization
    settings.server_authorization = TOKEN  # sent to ComfyUI, which ignores it; audited below
    if not hasattr(root, "_connection"):  # once per process, as in the plug-in
        settings.auto_update = False  # root.init() would check for updates
        root.init()
    connection = root.connection  # the one upstream's control layers and regions use
    connection.connect(ComfyClient(URL))
    await _until(
        lambda: connection.state in (ConnectionState.connected, ConnectionState.error),
        180,
        "connecting",
    )
    assert connection.state is ConnectionState.connected, connection.error
    client = connection.client
    assert isinstance(client, ComfyClient)
    doc = _shim().open_document("e2e", size, size)
    # A canvas of its own each run: ComfyUI answers a graph it has already run (an upscale, a
    # custom graph without a seed) with "no new images", not with the cached result.
    background = next(iter(_shim()._host.docs.values())).layers[0]
    noise = bytearray(os.urandom(size * size * 4))
    noise[3::4] = b"\xff" * (size * size)
    background.pixels = noise
    Krita.instance().setActiveDocument(doc)  # pyright: ignore[reportArgumentType]
    document = KritaDocument(doc, None)  # pyright: ignore[reportArgumentType]
    model = DocumentModel(document, connection, WorkflowCollection(connection, folder=tmp_path))
    connection.message_received.connect(model.handle_message)
    name, arch = _checkpoint(client)
    style = Style(tmp_path / "e2e.json")
    style.checkpoints = [name]
    style.sampler_steps = 12
    model.style = style
    model.regions.positive = "a lighthouse on a cliff at dusk, oil painting"
    try:
        yield model, client, arch
    finally:
        connection.message_received.disconnect(model.handle_message)
        await connection.disconnect()
        settings.server_authorization = saved


async def _finished(model: DocumentModel, timeout: float = 600) -> Job:
    """The next job of ``model`` to finish. Watched through ``job_finished``: upstream takes
    every job but diffusion and animation out of the job list once it finishes."""
    finished: list[Job] = []

    def record(job: Job):
        finished.append(job)

    model.jobs.job_finished.connect(record)

    def done():
        if model.error:
            raise AssertionError(f"generation failed: {model.error}")
        return bool(finished)

    try:
        await _until(done, timeout, "the job finishing")
    except TimeoutError:
        states = [(job.kind.name, job.state.name) for job in model.jobs]
        connection = model._connection
        raise TimeoutError(
            f"no job finished in {timeout}s: jobs {states}, connection "
            f"{connection.state.name} {connection.error!r}"
        ) from None
    finally:
        model.jobs.job_finished.disconnect(record)
    return finished[0]


def _layer_pixels(name_prefix: str) -> bytes:
    doc = next(iter(_shim()._host.docs.values()))
    layer = next(l for _, l in doc.walk() if l.name.startswith(name_prefix))
    assert layer.pixels is not None
    return bytes(layer.pixels)


def _not_blank(pixels: bytes) -> bool:
    colors = {pixels[i : i + 3] for i in range(0, min(len(pixels), 4 * 64 * 64), 4 * 97)}
    return len(colors) > 4


@qtapp
async def test_generate_and_apply(tmp_path: Path):
    settings.apply_behavior = ApplyBehavior.layer
    async with _session(tmp_path) as (model, _client, _arch):
        model.generate()
        job = await _finished(model)
        assert job.results[0].extent == Extent(512, 512)
        model.apply_generated_result(job.id or "", 0)
        assert _not_blank(_layer_pixels("[Generated]"))


@qtapp
async def test_inpaint_a_selection(tmp_path: Path):
    async with _session(tmp_path) as (model, _client, _arch):
        selection = Selection()
        selection.setPixelData(QByteArray(b"\xff" * (192 * 160)), 160, 176, 192, 160)
        model.document._doc.setSelection(selection)  # type: ignore[attr-defined]
        model.strength = 1.0
        model.generate()
        job = await _finished(model)
        bounds = job.params.bounds
        assert bounds.width < 512 or bounds.height < 512, "only around the selection"
        assert Bounds.intersection(bounds, Bounds(160, 176, 192, 160)).width > 0


@qtapp
async def test_live(tmp_path: Path):
    async with _session(tmp_path) as (model, _client, _arch):
        model.workspace = Workspace.live
        model.live.is_active = True
        await _until(lambda: model.live.has_result, 600, "a live result")
        model.live.is_active = False
        assert model.live.result is not None and model.live.result.extent == Extent(512, 512)
        model.live.apply_result(layer_only=True)


@qtapp
async def test_upscale(tmp_path: Path):
    async with _session(tmp_path, 384) as (model, _client, _arch):
        model.workspace = Workspace.upscaling
        model.upscale.factor = 2.0
        model.upscale.use_diffusion = False
        model.upscale_image()
        job = await _finished(model)
        assert job.results[0].extent == Extent(768, 768)
        await _until(
            lambda: any(l.name.startswith("[Upscale]") for l in model.layers.updated().all),
            60,
            "the upscaled layer",
        )


@qtapp
async def test_a_custom_graph(tmp_path: Path):
    graph = {
        "1": {"class_type": "ETN_KritaCanvas", "inputs": {}},
        "2": {"class_type": "ImageInvert", "inputs": {"image": ["1", 0]}},
        "3": {"class_type": "ETN_KritaOutput", "inputs": {"images": ["2", 0]}},
    }
    async with _session(tmp_path) as (model, _client, _arch):
        source = tmp_path / "source" / "e2e-invert.json"
        source.parent.mkdir()
        source.write_text(json.dumps(graph))
        model.workspace = Workspace.custom
        model.custom.import_file(source)
        await _until(lambda: model.custom.graph is not None, 30, "the graph")
        model.custom.generate()
        job = await _finished(model)
        doc = next(iter(_shim()._host.docs.values()))
        canvas = doc.layers[0].pixels
        assert canvas is not None
        result = job.results[0]
        assert result.extent == Extent(512, 512)
        pixel = result.pixel(10, 10)
        assert isinstance(pixel, tuple)
        _b, _g, r = canvas[(10 * 512 + 10) * 4 : (10 * 512 + 10) * 4 + 3]
        assert abs(pixel[0] - (255 - r)) < 8, "the canvas, inverted by ComfyUI"


@qtapp
async def test_control_from_an_image(tmp_path: Path):
    async with _session(tmp_path) as (model, client, arch):
        mode = ControlMode.line_art
        if client.models.for_arch(arch).find_control(mode) is None:
            pytest.skip(f"no {mode.name} control model for {arch.name} on the server")
        sketch = Image.create(Extent(512, 512), fill=0xFFFFFFFF)
        for x in range(96, 416):
            for dy in range(3):
                sketch.set_pixel(x, 256 + dy, (0, 0, 0, 255))
        layer = model.layers.create("Sketch", sketch, Bounds(0, 0, 512, 512))
        control = model.regions.control.emplace()
        control.mode = mode
        control.layer_id = layer.id
        model.generate()
        job = await _finished(model)
        assert job.results[0].extent == Extent(512, 512)


@qtapp
async def test_krita_ai_diffusions_server_is_used(tmp_path: Path):
    from photocraft_host import krita_reuse

    configs = [c for c in krita_reuse.detect() if c.is_managed or c.is_custom]
    if not configs:
        pytest.skip("no Krita AI Diffusion configuration on this machine")
    config = configs[0]
    url = config.server_url if config.is_custom else krita_reuse.managed_url(config)
    connection = Connection()
    connection.connect(ComfyClient(url))
    await _until(
        lambda: connection.state in (ConnectionState.connected, ConnectionState.error),
        180,
        "connecting",
    )
    if connection.state is not ConnectionState.connected and config.is_managed:
        pytest.skip("Krita AI Diffusion's managed server isn't running (starting it is 31.2)")
    assert connection.state is ConnectionState.connected, connection.error
    await connection.disconnect()


@pytest.mark.skipif(not INSTALL, reason="the managed install: PHOTOCRAFT_E2E_INSTALL=<folder>")
@pytest.mark.timeout(5400)  # downloads tens of gigabytes
@qtapp
async def test_a_managed_cuda_install_of_the_sdxl_workload(tmp_path: Path):
    """REQ-29.1: install, download the SDXL workload, launch and connect. Tens of gigabytes."""
    from ai_diffusion.backend import resources
    from ai_diffusion.backend.server import Server, ServerBackend

    server = Server(INSTALL, ServerBackend.cuda)
    await server.install(lambda _progress: None)
    sdxl = [m.id.string for m in resources.default_checkpoints if m.arch is Arch.sdxl][:1]
    required = [m.id.string for m in resources.required_models if m.arch in (Arch.sdxl, Arch.all)]
    await server.download(sdxl + required, lambda _p: None)
    with socket.socket() as probe:  # not ComfyUI's default 8188: one may run there already
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = await server.start(port)
    try:
        connection = Connection()
        connection.connect(ComfyClient(url))
        await _until(lambda: connection.state is ConnectionState.connected, 600, "connecting")
        await connection.disconnect()
    finally:
        await server.stop()


def test_zz_audit_the_suite(recorded_hosts: list[str]):
    """Run last: the token reached no log, and no host outside the allow-list was asked."""
    from ..photocraft.audits import log_texts, outside_allowed, secrets_in

    assert secrets_in(log_texts(util.log_dir), [TOKEN]) == []
    server_host = URL.split("//")[-1].split(":")[0]
    assert outside_allowed(recorded_hosts, [server_host]) == []
