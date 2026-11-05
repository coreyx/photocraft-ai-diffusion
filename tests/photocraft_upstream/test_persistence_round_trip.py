"""Upstream's per-document state across saving, closing and reopening in PhotoCraft (TASK-35,
REQ-33).

Upstream keeps a document's state in Krita annotations (``ai_diffusion/document_id``, ``ui.json``
and ``result<N>.webp``); the stand-in stores each as a plug-in blob. Here the document is saved,
closed and opened again (a new document in PhotoCraft) and the plug-in starts afresh, with
nothing kept in memory: the workspace, prompts, a region and a control layer with their linked
layers, the seed, history within ``history_storage`` and an embedded workflow all come back.
That PhotoCraft keeps the blobs and layer uids through ``.pcraft``, PSD and PSB byte for byte is
the fork's own test (see ``MockHost.save_and_reopen``).

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
from krita import Krita
from PyQt6.QtCore import QByteArray

from ai_diffusion.backend.resources import ControlMode
from ai_diffusion.image import Bounds, Extent, Image, ImageCollection
from ai_diffusion.model.jobs import Job, JobKind, JobParams
from ai_diffusion.model.model import Workspace
from ai_diffusion.persistence import ModelSync
from ai_diffusion.settings import settings

from ..conftest import qtapp
from ..test_model import _model_env

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)


def _shim():
    from ..photocraft import upstream_shim  # imported late: importing installs the stand-in

    return upstream_shim


@asynccontextmanager
async def _env(doc, folder: Path):
    async with _model_env(doc, folder) as (model, client):
        await asyncio.sleep(0)
        try:
            yield model, client
        finally:
            for _ in range(5):
                await asyncio.sleep(0)


async def _until(condition, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.01)


def _restart_plugin():
    """A fresh plug-in process: a new ``Krita`` connected to the same PhotoCraft, which lists the
    documents that are open."""
    shim = _shim()
    krita.Krita._instance = None  # type: ignore[attr-defined]
    shim._transport._listeners.clear()
    krita.attach(shim._transport, "test")  # pyright: ignore[reportAttributeAccessIssue]


def _noise(seed: int) -> Image:
    """A result that compresses badly, so each takes a measurable share of history storage."""
    data = bytearray(256 * 256 * 4)
    state = seed
    for i in range(0, len(data), 4):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        data[i : i + 3] = state.to_bytes(4, "little")[:3]
        data[i + 3] = 255
    return Image.from_packed_bytes(QByteArray(bytes(data)), Extent(256, 256))


async def _finish(model, sync: ModelSync, job_id: str, image: Image):
    params = JobParams(bounds=Bounds(0, 0, 256, 256), name=job_id, seed=7)
    job = model.jobs.add_job(Job(job_id, JobKind.diffusion, params))
    model.jobs.set_results(job, ImageCollection([image]))
    model.jobs.notify_finished(job)
    await _until(lambda: sync._image_task is not None)
    assert sync._image_task is not None
    await sync._image_task


GRAPH = {
    "1": {"class_type": "ETN_KritaCanvas", "inputs": {}},
    "2": {"class_type": "ETN_KritaOutput", "inputs": {"images": ["1", 0]}},
}


@qtapp
async def test_the_documents_state_survives_saving_closing_and_reopening(tmp_path: Path):
    shim = _shim()
    doc = Krita.instance().openDocument(str(tmp_path / "portrait.pcraft"))
    assert doc is not None
    host_doc = shim._host.docs[doc._id]  # pyright: ignore[reportAttributeAccessIssue]
    storage = settings.history_storage
    try:
        async with _env(doc, tmp_path) as (model, _client):
            sync = ModelSync(model)
            model.regions.positive = "a lighthouse at dusk"
            model.regions.negative = "blurry"
            sky = model.layers.create("Sky", Image.create(Extent(512, 256), fill=0xFF3366CC))
            region = model.regions.emplace()
            region.link(sky)
            region.positive = "a stormy sky"
            sketch = model.layers.create("Sketch", Image.create(Extent(512, 512), fill=0xFF202020))
            control = model.regions.control.emplace()
            control.mode = ControlMode.scribble
            control.layer_id = sketch.id
            model.seed, model.fixed_seed = 4242, True
            model.custom.set_graph("photocraft-test", GRAPH, model.name)
            await _until(lambda: model.custom.graph is not None)
            model.workspace = Workspace.upscaling

            # History keeps results up to history_storage (in MB): room for one here.
            await _finish(model, sync, "job-1", _noise(1))
            one = sync.memory_used
            settings.history_storage = one * 1.5 / (1024 * 1024)  # pyright: ignore[reportAttributeAccessIssue]
            await _finish(model, sync, "job-2", _noise(2))
            sync._save()
            embedded = model.custom.workflow_id
            assert model.custom.graph is not None
            graph_before = model.custom.graph.root
            names = sorted(host_doc.blobs)
            assert "ui.json" in str(names) and "result1.webp" in str(names)
            assert not any("result0" in n for n in names), "the older result was pruned"

        reopened = shim._host.save_and_reopen(host_doc)
        assert reopened.id != host_doc.id
        _restart_plugin()
        (doc2,) = Krita.instance().documents()

        async with _env(doc2, tmp_path) as (model2, _client):
            ModelSync(model2)
            assert model2.workspace is Workspace.upscaling
            assert (model2.regions.positive, model2.regions.negative) == (
                "a lighthouse at dusk",
                "blurry",
            )
            (region2,) = list(model2.regions)
            assert region2.positive == "a stormy sky"
            assert [layer.name for layer in region2.layers] == ["Sky"]
            (control2,) = list(model2.regions.control)
            assert control2.mode is ControlMode.scribble
            linked = model2.layers.find(control2.layer_id)
            assert linked is not None and linked.name == "Sketch"
            assert (model2.seed, model2.fixed_seed) == (4242, True)

            assert [job.id for job in model2.jobs] == ["job-2"]
            (result,) = model2.jobs.find("job-2").results  # pyright: ignore[reportOptionalMemberAccess]
            # What was stored: the result in the history format (lossy WebP by default).
            data, offsets = ImageCollection([_noise(2)]).to_bytes(settings.history_format)
            assert Image.compare(result, ImageCollection.from_bytes(data, offsets)[0]) == 0

            await _until(lambda: model2.custom.graph is not None)
            assert model2.custom.workflow_id == embedded == "Embedded Workflow (portrait)"
            graph = model2.custom.graph
            assert graph is not None and graph.root == graph_before
    finally:
        settings.history_storage = storage
