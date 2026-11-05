"""The plug-in started as PhotoCraft starts it, with upstream's actions and docker (TASK-27,
REQ-14, REQ-35): 15 actions with Krita AI Diffusion's names and no default shortcuts, the docker
as a panel, four workspaces (Animation is deferred), and Live stopping when it is left."""

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
    work = tmp_path_factory.mktemp("docker")
    run = subprocess.run(
        [sys.executable, str(HERE / "upstream_docker.py"), str(work / "data")],
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


def test_fifteen_actions_with_their_names(results: dict):
    actions = results["actions"]
    assert len(actions) == 15
    assert actions["ai_diffusion_generate"] == "Generate image"
    assert actions["ai_diffusion_switch_workspace_graph"] == "Switch workspace: Graph"
    assert actions["ai_diffusion_settings"] == "Show Settings"


def test_the_docker_is_a_panel(results: dict):
    assert results["panels"] == {"imageDiffusion": "AI Image Generation"}
    assert results["panel_root"]


def test_four_workspaces(results: dict):
    assert results["workspace_menu"] == ["Generate", "Upscale", "Live", "Graph"]
    assert results["switched"] == ["upscaling", "live", "custom", "generation"]
    assert results["toggle_cycle"] == ["upscaling", "live", "custom", "generation", "upscaling"]


def test_leaving_live_stops_it(results: dict):
    assert results["live_after_leaving"] is False


def test_each_action_runs(results: dict):
    assert results["regions_added"] == 1
    assert results["edit_mode_toggled"]
    assert results["settings_dialog"] == "Configure Image Diffusion"
    assert results["errors"] == []
