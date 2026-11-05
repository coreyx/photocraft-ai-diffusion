"""Upstream's prompt features and styles on the ``krita`` stand-in (TASK-31, REQ-21, REQ-22).

Prompt processing itself (comments, wildcards, LoRA syntax, layer references, merging) is
upstream's ``text.py``, checked by upstream's own ``tests/test_text.py`` run on the stand-in; a
prompt referencing a layer is checked end to end by the parity scenarios ``*-layer-reference``.
Here: the prompt read from a PNG when PhotoCraft opens it, the translate route, the 20 built-in
styles, a user style saved in the plug-in's own data folder, the steps/strength maths, and styles
hidden when their model is missing.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import krita
import pytest
from krita import Krita
from PyQt6.QtGui import QImage

from ai_diffusion import util
from ai_diffusion.backend.client import filter_supported_styles
from ai_diffusion.backend.comfy_client import ComfyClient
from ai_diffusion.backend.workflow import apply_strength, snap_to_percent
from ai_diffusion.document import KritaDocument
from ai_diffusion.model.connection import Connection
from ai_diffusion.model.custom_workflow import WorkflowCollection
from ai_diffusion.model.model import DocumentModel
from ai_diffusion.persistence import import_prompt_from_file
from ai_diffusion.style import Style, Styles

from ..conftest import qtapp
from ..mock.client import MockClient

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)


def _png(path: Path, key: str, text: str) -> Path:
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFF808080)
    image.setText(key, text)
    assert image.save(str(path), "PNG")
    return path


def _opened_model(path: Path, folder: Path) -> DocumentModel:
    """The document model for a file opened in PhotoCraft, as the plug-in creates it."""
    doc = Krita.instance().openDocument(str(path))
    assert doc is not None and doc.fileName() == str(path)
    Krita.instance().setActiveDocument(doc)
    kd = KritaDocument.active()
    assert kd is not None
    conn = Connection()
    model = DocumentModel(kd, conn, WorkflowCollection(conn, folder=folder))
    import_prompt_from_file(model)
    return model


def test_a1111_prompt_is_read_from_an_opened_png(tmp_path: Path):
    params = "a lighthouse at dusk, oil painting\nNegative prompt: blurry, lowres\nSteps: 20, Sampler: Euler"
    model = _opened_model(_png(tmp_path / "a1111.png", "parameters", params), tmp_path)
    assert model.regions.positive == "a lighthouse at dusk, oil painting"
    assert model.regions.negative == "blurry, lowres"


def test_comfyui_prompt_is_read_from_an_opened_png(tmp_path: Path):
    graph = {
        "3": {"class_type": "KSampler", "inputs": {"positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a red fox"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "watermark"}},
    }
    model = _opened_model(_png(tmp_path / "comfy.png", "prompt", json.dumps(graph)), tmp_path)
    assert (model.regions.positive, model.regions.negative) == ("a red fox", "watermark")


@qtapp
async def test_the_translate_route(monkeypatch: pytest.MonkeyPatch):
    asked: list[str] = []

    async def get(self, route: str):
        asked.append(route)
        return "a cat on a mat"

    monkeypatch.setattr(ComfyClient, "_get", get)
    client = ComfyClient.__new__(ComfyClient)
    assert await client.translate("un chat", "fr") == "a cat on a mat"
    assert asked == ["api/etn/translate/fr/un chat"]


def test_twenty_built_in_styles(tmp_path: Path):
    styles = Styles(Styles.default_builtin_folder, tmp_path / "styles")
    builtin = styles.filtered(show_builtin=True)
    assert len(builtin) == 20
    assert all(s.filename.startswith("built-in/") for s in builtin)
    assert {"built-in/cinematic-photo-xl.json", "built-in/flux.json"} <= {
        s.filename for s in builtin
    }


def test_a_user_style_is_kept_in_the_plugin_data_folder(tmp_path: Path):
    assert Styles.default_user_folder.parent == util.user_data_dir, "never Krita AI Diffusion's"
    styles = Styles(Styles.default_builtin_folder, tmp_path / "styles")
    style = styles.create("my-style.json", checkpoint="my_model.safetensors")
    style.name = "My Style"
    style.style_prompt = "{prompt}, watercolor"
    style.cfg_scale = 5.5
    style.save()
    reloaded = Styles(Styles.default_builtin_folder, tmp_path / "styles")
    found = reloaded.find(style.filename)
    assert found is not None
    assert (found.name, found.style_prompt, found.cfg_scale) == (
        "My Style",
        "{prompt}, watercolor",
        5.5,
    )
    assert found.checkpoints == ["my_model.safetensors"]


def test_steps_and_strength():
    assert apply_strength(1.0, 20) == (20, 0)
    assert apply_strength(0.5, 20) == (20, 10)
    assert apply_strength(0.2, 20, min_steps=8) == (40, 32), "at least 8 steps run"
    assert snap_to_percent(20, 10, 20) == 50
    assert snap_to_percent(40, 32, 20) is None


def test_styles_without_their_model_are_hidden(tmp_path: Path):
    client = MockClient()  # has one SD 1.5 checkpoint
    (checkpoint,) = client.models.checkpoints
    usable = Style(tmp_path / "usable.json")
    usable.checkpoints = [checkpoint]
    missing = Style(tmp_path / "missing.json")
    missing.checkpoints = ["not_installed.safetensors"]
    assert filter_supported_styles([usable, missing], client) == [usable]
