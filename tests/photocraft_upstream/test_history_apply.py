"""Upstream's history, preview, apply and Save Image on the ``krita`` stand-in (TASK-32, REQ-23).

The preview is PhotoCraft's transient preview (design D4): shown over the document without a
layer, so previewing adds no undo step and is never saved. Apply behaviours ``layer``,
``layer_active`` and ``replace`` and the region behaviours ``replace`` and ``layer_group`` are
upstream's own ``tests/test_model.py`` tests, which run on the stand-in; here: the preview, the
transparency-mask region behaviour (a layer mask in PhotoCraft), the names applied layers get,
history pruning and Save Image's file name.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path

import krita
import pytest
from krita import Krita

from ai_diffusion.backend.client import ClientEvent, ClientMessage
from ai_diffusion.image import Extent, Image, ImageCollection
from ai_diffusion.model.jobs import JobRegion
from ai_diffusion.settings import (
    ApplyBehavior,
    ApplyRegionBehavior,
    GenerationFinishedAction,
    settings,
)

from ..conftest import qtapp
from ..test_model import _DOC_BOUNDS, _make_finished_job, _model_env, _run_generate

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)


def _host():
    from ..photocraft import upstream_shim  # imported late: importing installs the stand-in

    return upstream_shim._host


@asynccontextmanager
async def _env(folder: Path, doc=None):
    async with _model_env(doc or krita.Document(), folder) as pair:
        await asyncio.sleep(0)
        try:
            yield pair
        finally:
            for _ in range(5):
                await asyncio.sleep(0)


def _layer_names(model) -> list[str]:
    return [layer.name for layer in model.layers.updated().all]


@qtapp
async def test_previewing_shows_a_transient_preview_without_layers_or_undo(tmp_path: Path):
    async with _env(tmp_path) as (model, _client):
        job = _make_finished_job(model, [Image.create(Extent(512, 512), fill=0xFFFF0000)])
        layers = _layer_names(model)
        host = _host()
        calls = len(host.calls)
        assert job.id is not None
        model.jobs.select(job.id, 0)
        assert host.preview is not None
        assert host.preview["label"] == "[Preview] test job"
        assert host.preview["rect"] == {"x": 0, "y": 0, "width": 512, "height": 512}
        assert host.preview["bytes"] == 512 * 512 * 4
        edits = {"layer.create", "pixels.write", "pixels.createLayer", "layer.update", "undo.begin"}
        assert not edits & {m for m, _ in host.calls[calls:]}, "no layer, no undo step"
        assert _layer_names(model) == layers

        model.jobs.selection = []
        assert host.preview is None, "deselecting hides it"


@qtapp
async def test_only_the_first_result_is_previewed_automatically(tmp_path: Path):
    settings.generation_finished_action = GenerationFinishedAction.preview
    async with _env(tmp_path) as (model, client):
        first = await _run_generate(model, client)
        client.push(
            ClientMessage(
                ClientEvent.finished,
                first.id or "",
                1,
                ImageCollection([Image.create(Extent(512, 512))]),
            )
        )
        for _ in range(100):
            await asyncio.sleep(0)
            if model.jobs.selection:
                break
        assert [s.job for s in model.jobs.selection] == [first.id]
        second = await _run_generate(model, client)
        client.push(
            ClientMessage(
                ClientEvent.finished,
                second.id or "",
                1,
                ImageCollection([Image.create(Extent(512, 512))]),
            )
        )
        for _ in range(100):
            await asyncio.sleep(0)
        assert [s.job for s in model.jobs.selection] == [first.id], "as in Krita: the preview stays"

        # Applying ends the preview; the next result is previewed again.
        model.apply_generated_result(first.id or "", 0)
        assert _host().preview is None
        third = await _run_generate(model, client)
        client.push(
            ClientMessage(
                ClientEvent.finished,
                third.id or "",
                1,
                ImageCollection([Image.create(Extent(512, 512))]),
            )
        )
        for _ in range(100):
            await asyncio.sleep(0)
            if model.jobs.selection:
                break
        assert [s.job for s in model.jobs.selection] == [third.id]


@qtapp
async def test_applied_layers_are_named_after_the_prompt_and_seed(tmp_path: Path):
    async with _env(tmp_path) as (model, _client):
        settings.apply_behavior = ApplyBehavior.layer
        job = _make_finished_job(
            model, [Image.create(Extent(512, 512), fill=0xFF00FF00)], seed=1234
        )
        model.apply_generated_result(job.id or "", 0)
        assert "[Generated] test job (1234)" in _layer_names(model)


@qtapp
async def test_a_region_result_with_a_transparency_mask_gets_a_layer_mask(tmp_path: Path):
    async with _env(tmp_path) as (model, _client):
        content = Image.create(Extent(512, 512), fill=0)
        content.draw_image(Image.create(Extent(256, 512), fill=0xFF2040A0), (256, 0))
        layer = model.layers.create("Sky", content, _DOC_BOUNDS)
        region = model.regions.emplace()
        region.link(layer)
        result = Image.create(Extent(512, 512), fill=0xFFFF0000)
        job = _make_finished_job(
            model, [result], regions=[JobRegion(layer.id_string, "sky", _DOC_BOUNDS)]
        )
        model.apply_result(
            result, job.params, ApplyBehavior.layer, ApplyRegionBehavior.transparency_mask
        )
        group = layer.parent_layer
        assert group is not None and not group.is_root
        doc = next(iter(_host().docs.values()))
        stored = doc.find(group.id_string.strip("{}"))
        assert stored.mask is not None, "PhotoCraft's layer mask stands in for Krita's"
        assert stored.mask[100 * 512 + 400] == 255 and stored.mask[100 * 512 + 100] == 0


@qtapp
async def test_history_is_pruned_to_its_size(tmp_path: Path):
    size = settings.history_size
    settings.history_size = 1  # MB; each 512x512 result is about 1 MB
    try:
        async with _env(tmp_path) as (model, _client):
            jobs = [
                _make_finished_job(model, [Image.create(Extent(512, 512))], seed=i)
                for i in range(3)
            ]
            for job in jobs:
                job.id = f"job-{job.params.seed}"
            model.jobs.prune(keep=jobs[-1])
            assert [j.id for j in model.jobs] == ["job-2"], "oldest results discarded first"
    finally:
        settings.history_size = size


@qtapp
async def test_save_image_names_the_file_after_the_document(tmp_path: Path):
    doc = Krita.instance().openDocument(str(tmp_path / "portrait.pcraft"))
    assert doc is not None
    async with _env(tmp_path, doc) as (model, _client):
        job = _make_finished_job(model, [Image.create(Extent(512, 512), fill=0xFF808080)])
        model.save_result(job.id or "", 0)
        (saved,) = [p for p in tmp_path.iterdir() if p.name.startswith("portrait-generated-")]
        assert re.fullmatch(r"portrait-generated-\d{8}-\d{6}-0-test job\.\w+", saved.name)
        assert Image.load(saved).extent == Extent(512, 512)
