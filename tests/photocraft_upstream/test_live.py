"""Upstream's Live workspace on the ``krita`` stand-in (TASK-33, REQ-24).

Upstream polls the document every 100 ms and starts a job when its input changed. The stand-in
answers those reads from a cache that PhotoCraft's change events clear, so polling an unchanged
document costs no requests, and a stroke in PhotoCraft (``pixels.changed``) is seen at the next
poll. Also: Apply and Apply to New Layer, the hatched preview, and the plug-in's own overhead
for one live update (end to end on a GPU in TASK-45).

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

from ai_diffusion.backend.client import ClientEvent, ClientMessage
from ai_diffusion.image import Extent, Image, ImageCollection
from ai_diffusion.model.model import Workspace

from ..conftest import qtapp
from ..test_model import _model_env

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)


def _host():
    from ..photocraft import upstream_shim  # imported late: importing installs the stand-in

    return upstream_shim._host


@asynccontextmanager
async def _env(folder: Path, doc=None):
    async with _model_env(doc or krita.Document(), folder) as pair:
        # The live default (Realtime - Hyper) needs a LoRA the mock server doesn't have.
        pair[0].style.live_sampler = "Fast - UniPC BH2"
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


def _reads() -> int:
    return sum(
        1 for m, _ in _host().calls if m in ("pixels.read", "selection.read", "selection.bounds")
    )


async def _start_live(model, client):
    model.workspace = Workspace.live
    model.live.is_active = True
    await _until(lambda: len(client.enqueued) == 1)
    job = next(iter(model.jobs))
    await _until(lambda: job.id is not None)
    result = Image.create(Extent(512, 512), fill=0xFF3366CC)
    client.push(ClientMessage(ClientEvent.finished, job.id or "", 1, ImageCollection([result])))
    await _until(lambda: model.live.has_result)


def _paint_in_photocraft(color: bytes):
    """A stroke on the background in PhotoCraft: the pixels change and the host says so."""
    host = _host()
    doc = next(iter(host.docs.values()))
    layer = doc.layers[0]
    assert layer.pixels is not None
    for y in range(200, 260):
        start = (y * doc.width + 200) * 4
        layer.pixels[start : start + 60 * 4] = color * 60
    host.send_event("pixels.changed", {"doc": doc.id, "revision": 2, "layers": [layer.uid]})


@qtapp
async def test_no_job_and_no_reads_without_a_change(tmp_path: Path):
    async with _env(tmp_path) as (model, client):
        await _start_live(model, client)
        reads = _reads()
        await asyncio.sleep(0.8)  # eight polls
        assert len(client.enqueued) == 1, "nothing changed: no new job"
        assert _reads() == reads, "unchanged pixels are not read again"
        model.live.is_active = False


@qtapp
async def test_a_stroke_in_photocraft_starts_the_next_job(tmp_path: Path):
    async with _env(tmp_path) as (model, client):
        await _start_live(model, client)
        _paint_in_photocraft(bytes([10, 200, 30, 255]))
        await _until(lambda: len(client.enqueued) == 2)
        model.live.is_active = False


@qtapp
async def test_the_preview_shows_the_result_over_the_canvas(tmp_path: Path):
    """The Live panel's preview is upstream's composition: the canvas, hatched, with the result
    drawn over the generated area (the whole canvas here). The mirror sends it as an image."""
    async with _env(tmp_path) as (model, client):
        await _start_live(model, client)
        composition = model.live.result_composition
        assert composition is not None and composition.extent == Extent(512, 512)
        assert composition.pixel(100, 100) == (0x33, 0x66, 0xCC, 255), "the result, over the canvas"
        model.live.is_active = False


@qtapp
async def test_apply_and_apply_to_new_layer(tmp_path: Path):
    async with _env(tmp_path) as (model, client):
        await _start_live(model, client)
        model.live.is_active = False
        before = [layer.name for layer in model.layers.updated().all]
        model.live.apply_result(layer_only=True)
        after = [layer.name for layer in model.layers.updated().all]
        assert len(after) == len(before) + 1, "Apply to New Layer adds a layer"
        # Apply (by default "Modify active layer") replaces the active layer: upstream adds the
        # new content as a layer and removes the old one just after, leaving the count as it was.
        active = model.layers.active
        model.live.apply_result()
        names = lambda: [layer.name for layer in model.layers.updated().all]
        await _until(lambda: len(names()) == len(after))
        assert model.layers.find(active.id) is None, "the active layer was replaced"


@qtapp
async def test_the_plugins_own_overhead_for_a_live_update(tmp_path: Path):
    """Reading a 1024x1024 document through PhotoCraft and preparing the live job stays well
    within the 250 ms the plug-in may add (REQ-24.3)."""
    doc = krita.Document(1024, 1024)  # pyright: ignore[reportCallIssue] (the harness takes a size)
    async with _env(tmp_path, doc) as (model, _client):
        model.workspace = Workspace.live
        model.document._doc.invalidate()  # type: ignore[attr-defined]  # a cold read, as after a stroke
        start = time.perf_counter()
        model._prepare_live_workflow()
        elapsed = time.perf_counter() - start
        assert elapsed < 0.25, f"{elapsed * 1000:.0f} ms"
