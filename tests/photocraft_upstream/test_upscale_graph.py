"""Upstream's Upscale and Graph workspaces on the ``krita`` stand-in (TASK-34, REQ-25, REQ-27).

Tiled and simple upscale graphs are in the parity suite on PhotoCraft; custom workflow import,
parameters (with their order and groups) and text outputs are upstream's own
``tests/test_custom_workflow.py``, which runs on the stand-in. Here: the 2x upscale resampling
the PhotoCraft document and adding the ``[Upscale]`` layer, a Graph run reading the canvas, the
selection and a layer through PhotoCraft, and live Graph re-runs only when an input changed.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

import krita
import pytest
from krita import Selection
from PyQt6.QtCore import QByteArray

from ai_diffusion.backend.client import ClientEvent, ClientMessage
from ai_diffusion.image import Bounds, Extent, Image, ImageCollection
from ai_diffusion.model.custom_workflow import CustomGenerationMode
from ai_diffusion.model.model import Workspace

from ..conftest import qtapp
from ..test_model import _model_env

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)


def _host():
    from ..photocraft import upstream_shim  # imported late: importing installs the stand-in

    return upstream_shim._host


@asynccontextmanager
async def _env(folder: Path):
    async with _model_env(krita.Document(), folder) as pair:
        await asyncio.sleep(0)
        try:
            yield pair
        finally:
            for _ in range(5):
                await asyncio.sleep(0)


async def _until(condition, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.01)


async def _finish(client, job, extent: Extent):
    await _until(lambda: job.id is not None)
    image = Image.create(extent, fill=0xFF446688)
    client.push(ClientMessage(ClientEvent.finished, job.id or "", 1, ImageCollection([image])))


@qtapp
async def test_a_2x_upscale_resamples_the_document_and_adds_a_layer(tmp_path: Path):
    async with _env(tmp_path) as (model, client):
        model.workspace = Workspace.upscaling
        model.upscale.factor = 2.0
        model.upscale.use_diffusion = False
        model.upscale_image()
        await _until(lambda: len(client.enqueued) == 1)
        doc = next(iter(_host().docs.values()))
        assert (doc.width, doc.height) == (1024, 1024), "Image Size, through doc.resizeImage"
        assert [m for m, _ in _host().calls if m == "doc.resizeImage"]
        job = next(iter(model.jobs))
        await _finish(client, job, Extent(1024, 1024))
        await _until(
            lambda: any(l.name.startswith("[Upscale]") for l in model.layers.updated().all)
        )
        layer = next(l for l in model.layers.all if l.name.startswith("[Upscale]"))
        assert layer.bounds == Bounds(0, 0, 1024, 1024)


def _graph(*nodes: dict) -> dict:
    return {str(i + 1): node for i, node in enumerate(nodes)}


CANVAS_GRAPH = _graph(
    {"class_type": "ETN_KritaCanvas", "inputs": {}},
    # "automatic" fails in upstream itself (get_selection_modifiers takes no InpaintContext.automatic).
    {"class_type": "ETN_KritaSelection", "inputs": {"context": "mask_bounds", "padding": 0}},
    {"class_type": "ETN_KritaImageLayer", "inputs": {"name": "Sketch"}},
    {"class_type": "ETN_KritaOutput", "inputs": {"images": ["1", 0]}},
)


async def _use_graph(model, graph: dict):
    model.workspace = Workspace.custom
    model.custom.set_graph("photocraft-test", graph, document_name="test")
    await _until(lambda: model.custom.graph is not None)


@qtapp
async def test_a_graph_reads_canvas_selection_and_layer_through_photocraft(tmp_path: Path):
    async with _env(tmp_path) as (model, client):
        sketch = model.layers.create(
            "Sketch", Image.create(Extent(64, 64), fill=0xFFAA2222), Bounds(32, 32, 64, 64)
        )
        selection = Selection()
        selection.setPixelData(QByteArray(b"\xff" * (100 * 80)), 200, 150, 100, 80)
        model.document._doc.setSelection(selection)  # type: ignore[attr-defined]
        await _use_graph(model, CANVAS_GRAPH)
        model.custom.params = {"Sketch": sketch.id.toString()}
        model.custom.generate()
        await _until(lambda: len(client.enqueued) == 1)
        work = client.enqueued[0]
        assert work.images is not None and work.images.initial_image is not None
        assert work.images.hires_mask is not None, "the selection, read from PhotoCraft"
        assert work.inpaint is not None and work.inpaint.target_bounds.width >= 100
        assert work.custom_workflow is not None
        layer_image = work.custom_workflow.params["Sketch"]
        assert isinstance(layer_image, Image)
        pixel = layer_image.pixel(40, 40)
        assert isinstance(pixel, tuple) and pixel[:3] == (0xAA, 0x22, 0x22)


@qtapp
async def test_a_live_graph_runs_again_only_when_an_input_changed(tmp_path: Path):
    async with _env(tmp_path) as (model, client):
        await _use_graph(
            model,
            _graph(
                {"class_type": "ETN_KritaCanvas", "inputs": {}},
                {"class_type": "ETN_KritaOutput", "inputs": {"images": ["1", 0]}},
            ),
        )
        model.custom.mode = CustomGenerationMode.live
        model.custom.is_live = True
        await _until(lambda: len(client.enqueued) == 1)
        await _finish(client, next(iter(model.jobs)), Extent(512, 512))
        await asyncio.sleep(0.6)
        assert len(client.enqueued) == 1, "nothing changed: no new run"

        host = _host()
        doc = next(iter(host.docs.values()))
        layer = doc.layers[0]
        assert layer.pixels is not None
        layer.pixels[0:400] = bytes([0, 0, 255, 255]) * 100
        host.send_event("pixels.changed", {"doc": doc.id, "revision": 2, "layers": [layer.uid]})
        await _until(lambda: len(client.enqueued) == 2)
        model.custom.is_live = False
