"""This project's changes to upstream code (UPSTREAM-CHANGES.md, TASK-24), on the ``krita``
stand-in: colour modes and depths PhotoCraft converts or refuses, job parameters that come back
from a saved document with their enums, and the language default that follows PhotoCraft.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import krita
import pytest
from krita import Krita

from ai_diffusion.backend.api import InpaintMode, WorkflowKind
from ai_diffusion.document import KritaDocument
from ai_diffusion.image import Bounds, Extent, Image, ImageCollection
from ai_diffusion.localization import language_for_locale
from ai_diffusion.model.connection import Connection
from ai_diffusion.model.custom_workflow import WorkflowCollection
from ai_diffusion.model.jobs import Job, JobKind, JobParams
from ai_diffusion.model.model import DocumentModel
from ai_diffusion.persistence import ModelSync
from ai_diffusion.settings import Settings
from ai_diffusion.util import encode_json

from ..conftest import qtapp

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)

from ..photocraft.upstream_shim import open_document

LANGUAGES = {
    "en", "es-ca", "es", "fr", "id", "it", "ja", "ko", "pt-br", "ru", "th", "tr", "zh-cn", "zh-tw"
}  # fmt: skip


def _wrap(doc) -> KritaDocument:
    Krita.instance().setActiveDocument(doc)
    return KritaDocument(doc, None)


# -- colour modes and depths (REQ-37)


@pytest.mark.parametrize(
    "mode,depth,note",
    [
        ("rgb", "u8", None),
        ("rgb", "u16", "Images are converted from 16-bit RGB to 8-bit RGB for generation"),
        ("cmyk", "u8", "Images are converted from 8-bit CMYK to 8-bit RGB for generation"),
        ("lab", "f32", "Images are converted from 32-bit float Lab to 8-bit RGB for generation"),
        (
            "grayscale",
            "u8",
            "Images are converted from 8-bit Grayscale to 8-bit RGB for generation",
        ),
    ],
)
def test_documents_photocraft_converts_are_accepted_with_a_note(mode, depth, note):
    doc = _wrap(open_document("Doc", 64, 64, mode, depth))
    assert doc.check_color_mode() == (True, None)
    assert doc.color_conversion_note == note


@pytest.mark.parametrize("mode,name", [("bitmap", "Bitmap"), ("indexed", "Indexed"), ("multichannel", "Multichannel"), ("duotone", "Duotone")])  # fmt: skip
def test_modes_photocraft_cannot_convert_are_refused_by_name(mode, name):
    doc = _wrap(open_document("Doc", 64, 64, mode, "u8"))
    ok, message = doc.check_color_mode()
    assert not ok
    assert (
        message == f"Incompatible document: {name} mode documents can't be converted for generation"
    )
    assert doc.color_conversion_note is None, "refused, not converted"


def test_layer_pixels_are_8_bit_whatever_the_document_depth():
    doc = _wrap(open_document("Deep", 8, 8, "rgb", "u16"))
    layer = doc.layers.root.child_layers[0]
    assert layer.get_pixels().extent == Extent(8, 8)


def test_a_bitmap_document_refuses_generation(tmp_path: Path):
    doc = _wrap(open_document("Bits", 64, 64, "bitmap", "u8"))
    conn = Connection()
    model = DocumentModel(doc, conn, WorkflowCollection(conn, folder=tmp_path))
    model.generate()
    assert "Bitmap mode" in model.error.message
    assert len(model.jobs) == 0


# -- job parameters saved in documents (REQ-33)


def _stored(params: JobParams) -> dict:
    """Job parameters as a document stores them: JSON with enums by name."""
    return json.loads(json.dumps(asdict(params), default=encode_json))


def test_job_params_come_back_with_their_enums():
    params = JobParams(
        bounds=Bounds(1, 2, 30, 40),
        name="fox",
        workflow_kind=WorkflowKind.inpaint,
        inpaint_mode=InpaintMode.fill,
        frame=(3, 4, 5),
        seed=9,
    )
    restored = JobParams.from_dict(_stored(params))
    assert restored == params
    assert restored.workflow_kind is WorkflowKind.inpaint
    assert restored.inpaint_mode is InpaintMode.fill
    assert JobParams.from_dict(_stored(JobParams(Bounds(0, 0, 1, 1), "x"))).inpaint_mode is None


@qtapp
async def test_history_keeps_job_enums_after_reopening(tmp_path: Path):
    doc = Krita.instance().openDocument("history.pcraft")
    kd = _wrap(doc)
    conn = Connection()
    model = DocumentModel(kd, conn, WorkflowCollection(conn, folder=tmp_path))
    sync = ModelSync(model)
    params = JobParams(Bounds(0, 0, 64, 64), "inpainted", workflow_kind=WorkflowKind.inpaint)
    params.inpaint_mode = InpaintMode.expand
    job = model.jobs.add_job(Job("job-1", JobKind.diffusion, params))
    model.jobs.set_results(job, ImageCollection([Image.create(Extent(64, 64), fill=0xFF00FF00)]))
    model.jobs.notify_finished(job)
    if sync._image_task is not None:
        await sync._image_task
    sync._save()

    reopened = DocumentModel(_wrap(doc), conn, WorkflowCollection(conn, folder=tmp_path))
    ModelSync(reopened)
    (restored,) = list(reopened.jobs)
    assert restored.params.workflow_kind is WorkflowKind.inpaint
    assert restored.params.inpaint_mode is InpaintMode.expand


# -- language (REQ-34)


@pytest.mark.parametrize(
    "locale,language",
    [
        ("ja", "ja"),
        ("ja-JP", "ja"),
        ("pt-BR", "pt-br"),
        ("pt", "pt-br"),
        ("zh-Hans", "zh-cn"),
        ("zh-CN", "zh-cn"),
        ("zh-Hant", "zh-tw"),
        ("zh-HK", "zh-tw"),
        ("zh_TW", "zh-tw"),
        ("es-MX", "es"),
        ("ca", "es-ca"),
        ("ca-ES-valencia", "es-ca"),
        ("fr-CA", "fr"),
        ("de-DE", "en"),
        ("", "en"),
    ],
)
def test_host_locales_map_to_catalogs(locale: str, language: str):
    assert language_for_locale(locale, LANGUAGES) == language


def test_the_language_is_stored_only_once_chosen(tmp_path: Path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.default_path = path
    default = Settings._language.default
    settings.save()
    assert "language" not in json.loads(path.read_text()), "follows PhotoCraft until chosen"
    settings.language = "ko" if default != "ko" else "fr"
    settings.save()
    assert json.loads(path.read_text())["language"] == settings.language
