"""Upstream's regions and control layers on the ``krita`` stand-in (TASK-29, REQ-18, REQ-19):
region links kept across saving and reopening, re-linked into groups and dropped when their layer
is deleted, Create Region, the two-way sync between the active region and the active layer, and
control layers made from an image or removed with their source layer.

The region masks and prompts in the submitted graphs (overlapping regions, a dominant region, the
background region) and the Depth+Reference and from-image graphs are checked by the parity suite
on PhotoCraft (``test_parity_tools.py::test_photocraft_builds_upstream_graphs``).

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import krita
import pytest
from krita import Krita

from ai_diffusion.backend.client import ClientEvent, ClientMessage
from ai_diffusion.backend.resources import ControlMode
from ai_diffusion.document import KritaDocument
from ai_diffusion.image import Bounds, Extent, Image, ImageCollection
from ai_diffusion.layer import LayerType
from ai_diffusion.model.connection import Connection
from ai_diffusion.model.control import control_mode_text
from ai_diffusion.model.custom_workflow import WorkflowCollection
from ai_diffusion.model.model import DocumentModel
from ai_diffusion.model.region import RegionLink
from ai_diffusion.persistence import ModelSync

from ..conftest import qtapp
from ..test_model import _model_env, _wait_for_enqueue

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)


@asynccontextmanager
async def _env(doc, folder: Path):
    """Upstream's model test set-up, letting the connection's message task start before it is
    torn down (upstream's tests always await something first)."""
    async with _model_env(doc, folder) as pair:
        await asyncio.sleep(0)
        try:
            yield pair
        finally:
            for _ in range(5):
                await asyncio.sleep(0)


def _paint(model: DocumentModel, name: str, color: int = 0xFF2040A0):
    """A new paint layer with some content, made active (as the user would)."""
    layer = model.layers.create(
        name, Image.create(Extent(64, 64), fill=color), Bounds(10, 10, 64, 64)
    )
    model.layers.update()
    return layer


@qtapp
async def test_region_links_survive_saving_and_reopening(tmp_path: Path):
    doc = krita.Document()
    async with _env(doc, tmp_path) as (model, _client):
        layer = _paint(model, "Sky")
        region = model.regions.create_region(group=False)
        region.positive = "a stormy sky"
        assert region.is_linked(layer)
        sync = ModelSync(model)
        sync._save()
        uid = layer.id

    Krita.instance().setActiveDocument(doc)
    conn = Connection()
    reopened = DocumentModel(
        KritaDocument(doc, None), conn, WorkflowCollection(conn, folder=tmp_path)
    )
    ModelSync(reopened)
    (region,) = list(reopened.regions)
    assert region.positive == "a stormy sky"
    (linked,) = region.layers
    assert linked.id == uid and linked.name == "Sky", "linked by the layer's persistent uid"


@qtapp
async def test_moving_a_linked_layer_into_a_group_links_the_group(tmp_path: Path):
    async with _env(krita.Document(), tmp_path) as (model, _client):
        layer = _paint(model, "Boat")
        region = model.regions.create_region(group=False)
        group = model.layers.create_group("Harbour")
        model.layers.update()
        # The user drags the layer into the group in PhotoCraft's Layers panel.
        node, group_node = layer.node, group.node
        assert node.parentNode() is not None
        node.parentNode().removeChildNode(node)
        group_node.addChildNode(node, None)
        model.layers.update()
        assert region.is_linked(group, RegionLink.direct)
        assert not region.is_linked(layer, RegionLink.direct)


@qtapp
async def test_deleting_a_linked_layer_removes_the_link(tmp_path: Path):
    async with _env(krita.Document(), tmp_path) as (model, _client):
        layer = _paint(model, "Tree")
        region = model.regions.create_region(group=False)
        layer.node.remove()
        model.layers.update()
        assert region.layers == []
        assert not model.regions.is_linked(layer)


@qtapp
async def test_create_region(tmp_path: Path):
    async with _env(krita.Document(), tmp_path) as (model, _client):
        unlinked = _paint(model, "Hill")
        first = model.regions.create_region()
        assert first.layers == [unlinked], "an unlinked active layer is linked"

        # The active layer is linked now: a group "Region <n>" with a "Paint layer" is made.
        second = model.regions.create_region()
        (group,) = second.layers
        assert group.type is LayerType.group and group.name == "Region 1"
        assert [c.name for c in group.child_layers] == ["Paint layer"]

        # In Live (group=False) it is a single layer.
        model.layers.active = unlinked
        third = model.regions.create_region(group=False)
        (layer,) = third.layers
        assert layer.type is LayerType.paint and layer.name == "Region 2"


@qtapp
async def test_active_region_and_active_layer_follow_each_other(tmp_path: Path):
    async with _env(krita.Document(), tmp_path) as (model, _client):
        sky = _paint(model, "Sky")
        sky_region = model.regions.create_region(group=False)
        sea = _paint(model, "Sea")
        sea_region = model.regions.create_region(group=False)

        model.regions.active = sky_region
        model.layers.update()
        assert model.layers.active.id == sky.id, "choosing a region activates its layer"

        # The user picks the Sea layer in PhotoCraft.
        doc = model.document
        assert isinstance(doc, KritaDocument)
        doc._doc.setActiveNode(sea.node)
        model.layers.update()
        assert model.regions.active is sea_region, "activating a linked layer selects its region"


def test_control_modes_have_upstreams_labels():
    assert {mode.name: mode.text for mode in control_mode_text} == {
        "reference": "Reference",
        "inpaint": "Inpaint",
        "style": "Style",
        "composition": "Composition",
        "face": "Face",
        "universal": "Universal",
        "scribble": "Scribble",
        "line_art": "Line Art",
        "soft_edge": "Soft Edge",
        "canny_edge": "Canny Edge",
        "depth": "Depth",
        "normal": "Normal",
        "pose": "Pose",
        "segmentation": "Segment",
        "blur": "Unblur",
        "stencil": "Stencil",
        "hands": "Hands",
    }


@qtapp
async def test_control_errors_name_the_missing_model(tmp_path: Path):
    async with _env(krita.Document(), tmp_path) as (model, _client):
        _paint(model, "Source")
        control = model.regions.control.emplace()
        for mode in (ControlMode.canny_edge, ControlMode.depth, ControlMode.reference):
            control.mode = mode
            # The mock server has no ControlNet or IP-Adapter models.
            assert not control.is_supported, mode
            assert control.error_text.startswith((
                "The ControlNet model is not installed",
                "The server is missing",
                "Not supported for",
            )), control.error_text


@qtapp
async def test_control_image_from_a_layer_and_removal_with_its_source(tmp_path: Path):
    async with _env(krita.Document(), tmp_path) as (model, client):
        _paint(model, "Photo")
        control = model.regions.control.emplace()
        control.mode = ControlMode.canny_edge
        job = model.generate_control_layer(control)
        assert job is not None
        await _wait_for_enqueue(client, 1)
        for _ in range(100):
            await asyncio.sleep(0)
            if job.id:
                break
        edges = Image.create(Extent(512, 512), fill=0xFFFFFFFF)
        client.push(ClientMessage(ClientEvent.finished, job.id or "", 1, ImageCollection([edges])))
        for _ in range(200):
            await asyncio.sleep(0)
            if control.layer_id and model.layers.find(control.layer_id) is not None:
                break
        model.layers.update()
        made = model.layers.find(control.layer_id)
        assert made is not None and made.name == "[Control] Canny Edge"

        # Deleting the control's layer in PhotoCraft removes the control layer entry.
        made.node.remove()
        model.layers.update()
        assert len(model.regions.control) == 0
