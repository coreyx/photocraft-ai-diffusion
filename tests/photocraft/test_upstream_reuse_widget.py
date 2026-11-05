"""The Connection page's Krita AI Diffusion section (TASK-45 coverage of TASK-40/41, REQ-31),
used as the user would in ``upstream_reuse_widget.py``."""

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
    tmp = tmp_path_factory.mktemp("reuse-widget")
    run = subprocess.run(
        [sys.executable, str(HERE / "upstream_reuse_widget.py"), str(tmp / "data"), str(tmp)],
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=180,
        cwd=tmp,
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "AI_DIFFUSION_UPDATE_URL": "http://127.0.0.1:9/releases/latest",
        },
    )
    assert run.returncode == 0, run.stderr[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_what_is_found_is_listed_and_looked_for_again(results: dict):
    assert results["empty_at_first"]
    listed = results["listed"]
    assert listed["empty_hidden"] and listed["managed"] and listed["custom"]
    assert listed["use_offered"] == [True, True, False], "a configuration set up for no server"
    assert listed["after_looking_again"] == 2


def test_importing_asks_again_before_the_token(results: dict):
    """REQ-31.5, 31.0.8."""
    imported = results["import"]
    assert imported["questions"] == 2
    assert imported["token_when_declined"] == ""
    assert imported["token_when_confirmed"]
    assert imported["history_size"] == 2400
    assert imported["said"] == [True, True]


def test_using_a_custom_server_from_the_section(results: dict):
    """REQ-31.3."""
    assert results["use"] == {"configured": True, "url": True, "connected": True}


def test_a_reused_server_lacking_nodes_offers_the_two_ways_on(results: dict):
    """REQ-31.0.6: this plug-in's own server sharing the models, or connecting anyway."""
    lacking = results["lacking"]
    assert lacking["error_kind"] == "missing_resources"
    assert lacking["own_server"] and lacking["anyway"]
    assert lacking["checks_resources_after_anyway"] is False
    assert lacking["shared_mode"] == "shared_models"
    assert lacking["notice_names_the_install"]
    assert lacking["shared_without_a_source"] is False
