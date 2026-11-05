"""Upstream's pose editing on the ``krita`` stand-in (TASK-30, REQ-20): a pose made from an image
becomes a vector (pose) layer of joint and bone shapes; moving a joint in PhotoCraft redraws its
bones; Add Skeleton adds a person. Upstream's ``pose.py`` runs unchanged on the stand-in's
``VectorLayer`` and ``Shape``, which PhotoCraft keeps as a marked group of shape layers.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import krita
import pytest
from PyQt6.QtCore import QCoreApplication

from ai_diffusion.backend.resources import ControlMode
from ai_diffusion.document import KritaDocument, _pose_layers
from ai_diffusion.image import Bounds, Extent
from ai_diffusion.layer import LayerType
from ai_diffusion.model.jobs import JobKind
from ai_diffusion.pose import BoneIndex, JointIndex, Pose, parse_id

from ..conftest import qtapp
from ..test_model import _model_env

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)

#: An OpenPose result for one person (what ComfyUI's pose estimator returns), 18 keypoints.
KEYPOINTS = [
    (256, 80), (256, 140), (206, 140), (186, 210), (176, 280), (306, 140), (326, 210),
    (336, 280), (226, 300), (221, 390), (216, 470), (286, 300), (291, 390), (296, 470),
    (246, 70), (266, 70), (236, 76), (276, 76),
]  # fmt: skip
OPEN_POSE = {
    "canvas_width": 512,
    "canvas_height": 512,
    "people": [{"pose_keypoints_2d": [v for x, y in KEYPOINTS for v in (x, y, 1.0)]}],
}


@asynccontextmanager
async def _env(folder: Path):
    async with _model_env(krita.Document(), folder) as pair:
        await asyncio.sleep(0)
        try:
            yield pair
        finally:
            for _ in range(5):
                await asyncio.sleep(0)


def _joints(layer) -> dict[JointIndex, tuple[float, float]]:
    """Joint centres in pixels, read back through the stand-in as upstream reads them."""
    doc = KritaDocument.active_instance()
    assert doc is not None
    out = {}
    for shape in layer.node.shapes():
        index = parse_id(shape.name())
        if isinstance(index, JointIndex):
            radius = Pose(doc.extent)._radius
            pos = shape.position()
            out[index] = ((pos.x() + radius) * doc.resolution, (pos.y() + radius) * doc.resolution)
    return out


def _bone_svgs(layer) -> dict[BoneIndex, str]:
    return {
        i: s._svg for s in layer.node.shapes() if isinstance(i := parse_id(s.name()), BoneIndex)
    }


def _pose_layer(model):
    control = model.regions.control.emplace()
    control.mode = ControlMode.pose
    job = model.jobs.add_control(control, Bounds(0, 0, 512, 512))
    assert job.kind is JobKind.control_layer
    layer = model.add_control_layer(job, OPEN_POSE)
    model.layers.update()
    return layer


@qtapp
async def test_a_pose_from_an_image_keeps_its_joints(tmp_path: Path):
    async with _env(tmp_path) as (model, _client):
        layer = _pose_layer(model)
        assert layer.type is LayerType.vector
        joints = _joints(layer)
        assert len(joints) == 18
        for i, (x, y) in enumerate(KEYPOINTS):
            got = joints[JointIndex(0, i)]
            assert abs(got[0] - x) <= 1 and abs(got[1] - y) <= 1, (i, got)
        assert len(_bone_svgs(layer)) == 17, "the bones between them"


def _move_joint(layer, joint: JointIndex, dx: float, dy: float):
    """Move a joint shape in the mock PhotoCraft, as dragging it in the canvas does."""
    # Imported here: importing the harness installs the stand-in as ``krita``, which must not
    # happen when this module is merely collected under upstream's own mock.
    from ..photocraft import upstream_shim

    host = upstream_shim._host
    doc = next(iter(host.docs.values()))
    group = doc.find(layer.id.toString().strip("{}"))
    shape = next(c for c in group.children if c.data.get("vector.id") == joint.id)
    svg = shape.data["svg"]
    cx = float(re.search(r'cx="([-0-9.]+)"', svg).group(1)) + dx  # type: ignore[union-attr]
    cy = float(re.search(r'cy="([-0-9.]+)"', svg).group(1)) + dy  # type: ignore[union-attr]
    svg = re.sub(r'cx="[-0-9.]+"', f'cx="{cx}"', svg)
    shape.data["svg"] = re.sub(r'cy="[-0-9.]+"', f'cy="{cy}"', svg)


def _poll_pose_layers():
    """Upstream polls pose layers on a timer created when ``ai_diffusion.document`` is imported.
    Upstream's test set-up imports it before Qt's application exists, so the timer never ran;
    in the plug-in the application comes first. Start it as it would run."""
    if not _pose_layers._timer.isActive():
        _pose_layers._timer.start()
    _pose_layers.update()


@qtapp
async def test_moving_a_joint_redraws_its_bones_within_a_second(tmp_path: Path):
    async with _env(tmp_path) as (model, _client):
        layer = _pose_layer(model)
        model.layers.active = layer
        model.layers.update()
        _poll_pose_layers()
        elbow = JointIndex(0, 3)  # right elbow: bones to the shoulder and the wrist
        before = _bone_svgs(layer)
        _move_joint(layer, elbow, 30, -20)
        moved = time.monotonic()
        x, y = KEYPOINTS[3][0] + 30, KEYPOINTS[3][1] - 20
        # Upstream's pose layers are polled every 500 ms; the bones must follow within 1 s.
        while time.monotonic() - moved < 1.0:
            QCoreApplication.processEvents()
            await asyncio.sleep(0.02)
            bones = _bone_svgs(layer)
            changed = [i for i, svg in bones.items() if svg != before.get(i)]
            if changed and all(f"{x}" in bones[i] or f"{float(x)}" in bones[i] for i in changed):
                break
        else:
            raise AssertionError("the bones were not redrawn within a second")
        assert {i.bone for i in changed} <= {2, 3}, "only the bones at the elbow"
        assert len(_bone_svgs(layer)) == 17, "redrawn, not added"
        assert abs(_joints(layer)[elbow][1] - y) <= 1


@qtapp
async def test_add_skeleton(tmp_path: Path):
    async with _env(tmp_path) as (model, _client):
        layer = _pose_layer(model)
        model.layers.active = layer
        model.layers.update()
        _poll_pose_layers()  # as it has run by the time the user clicks Add Skeleton
        doc = KritaDocument.active_instance()
        assert doc is not None
        doc.add_pose_character(layer)
        joints = _joints(layer)
        assert {i.person for i in joints} == {0, 1}, "a second person"
        assert len([i for i in joints if i.person == 1]) == 18
        assert len([i for i in _bone_svgs(layer) if i.person == 1]) == 17
        assert Extent(512, 512) == doc.extent
