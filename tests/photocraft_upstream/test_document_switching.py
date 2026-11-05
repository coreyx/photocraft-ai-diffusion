"""Upstream's per-document state running on the ``krita`` stand-in: each PhotoCraft document
keeps its own prompt and history while the user switches between them.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

from pathlib import Path

import krita
import pytest
from krita import Krita

from ai_diffusion.document import KritaDocument
from ai_diffusion.image import Bounds, Extent, Image, ImageCollection
from ai_diffusion.model.connection import Connection
from ai_diffusion.model.custom_workflow import WorkflowCollection
from ai_diffusion.model.jobs import Job, JobKind, JobParams
from ai_diffusion.model.model import DocumentModel
from ai_diffusion.model.root import Root
from ai_diffusion.persistence import ModelSync, RecentlyUsedSync

from ..conftest import qtapp

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)


def _root(workflows: Path) -> Root:
    """A ``Root`` with what ``model_for_active_document`` uses, and no server or updates."""
    root = Root()
    root._connection = Connection()
    root._workflows = WorkflowCollection(root._connection, folder=workflows)
    root._models = []
    root._recent = RecentlyUsedSync()
    return root


def _finish(model: DocumentModel, job_id: str, name: str, colour: int) -> Job:
    params = JobParams(bounds=Bounds(0, 0, 64, 64), name=name, seed=7)
    job = model.jobs.add_job(Job(job_id, JobKind.diffusion, params))
    model.jobs.set_results(job, ImageCollection([Image.create(Extent(64, 64), fill=colour)]))
    model.jobs.notify_finished(job)
    return job


@qtapp
async def test_each_document_keeps_its_prompt_and_history(tmp_path: Path):
    root = _root(tmp_path)
    fox_doc = krita.Document()
    whale_doc = krita.Document()

    Krita.instance().setActiveDocument(fox_doc)
    fox = root.model_for_active_document()
    assert fox is not None
    fox.regions.positive = "a red fox"
    _finish(fox, "fox-job", "fox", 0xFFFF0000)

    Krita.instance().setActiveDocument(whale_doc)
    whale = root.model_for_active_document()
    assert whale is not None and whale is not fox
    assert whale.regions.positive != "a red fox"
    assert len(whale.jobs) == 0
    whale.regions.positive = "a blue whale"
    _finish(whale, "whale-job", "whale", 0xFF0000FF)

    Krita.instance().setActiveDocument(fox_doc)
    assert root.model_for_active_document() is fox
    assert fox.regions.positive == "a red fox"
    assert [job.params.name for job in fox.jobs] == ["fox"]

    # Each document stores its own state, and gets it back when opened again.
    for entry in root._models:
        sync = entry.sync
        assert sync is not None
        if sync._image_task is not None:
            await sync._image_task
        sync._save()

    for doc, prompt, name in [(fox_doc, "a red fox", "fox"), (whale_doc, "a blue whale", "whale")]:
        Krita.instance().setActiveDocument(doc)
        reopened = KritaDocument(doc, None)
        conn = Connection()
        model = DocumentModel(reopened, conn, WorkflowCollection(conn, folder=tmp_path))
        ModelSync(model)
        assert model.regions.positive == prompt
        assert [job.params.name for job in model.jobs] == [name]
