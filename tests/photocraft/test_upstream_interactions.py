"""Upstream's real Generate workspace used through the Qt mirror (TASK-26): prompt weighting with
Ctrl+Up, tag autocomplete, and the generate button drawn as an image."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict:
    work = tmp_path_factory.mktemp("interactions")
    run = subprocess.run(
        [sys.executable, str(HERE / "upstream_interactions.py"), str(work / "data")],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        cwd=work,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_ctrl_up_weights_the_word_at_the_cursor(results: dict):
    assert results["weighted"] == "a (cat:1.1)"
    assert results["model_prompt"] == "a (cat:1.1)", "the document's prompt follows"


def test_tags_autocomplete(results: dict):
    assert results["completer_opened"], "typing a word opens the tag completer"
    assert results["completions"] and results["completions"][0] == "1girl"
    assert results["completed"] == "a (cat:1.1), 1girl"


def test_the_generate_button_is_an_image_that_clicks(results: dict):
    assert results["button_kind"] == "image"
    assert results["generate_clicked"]
