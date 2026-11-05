"""Upstream's settings dialog used through the Qt mirror on a fresh plug-in data folder (TASK-36,
REQ-28): the keys written on first run, connecting to a custom ComfyUI address with no Krita AI
Diffusion present, every control changing its key and surviving a restart, Restore Defaults, and
the recently used document settings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

#: Inventory §2.11, less ``access_token`` and ``last_news`` (kept only while the cloud module is
#: enabled) and ``language`` (written once the user picks one; until then it follows PhotoCraft).
FIRST_RUN_KEYS = {
    "auto_update",
    "server_mode",
    "server_path",
    "server_url",
    "server_backend",
    "server_arguments",
    "server_authorization",
    "check_server_resources",
    "selection_feather",
    "selection_min_transition",
    "selection_grow_offset",
    "selection_blend",
    "selection_padding",
    "color_match",
    "nsfw_filter",
    "new_seed_after_apply",
    "prompt_translation",
    "save_image_metadata",
    "save_image_format",
    "save_image_quality_webp",
    "save_image_quality_jpeg",
    "save_image_file_name_format",
    "confirm_discard_image",
    "prompt_line_count",
    "prompt_line_count_live",
    "show_negative_prompt",
    "generation_finished_action",
    "show_steps",
    "tag_files",
    "apply_behavior",
    "apply_region_behavior",
    "apply_behavior_live",
    "apply_region_behavior_live",
    "show_builtin_styles",
    "recent_styles_count",
    "recent_styles",
    "history_size",
    "history_storage",
    "history_format",
    "multi_threading",
    "performance_preset",
    "batch_size",
    "resolution_multiplier",
    "max_pixel_count",
    "dynamic_caching",
    "tiled_vae",
    "debug_dump_workflow",
    "document_defaults",
}

#: The keys the Diffusion, Interface, Performance and Plugin pages set.
PAGE_KEYS = {
    "selection_feather",
    "selection_blend",
    "selection_padding",
    "color_match",
    "nsfw_filter",
    "language",
    "prompt_translation",
    "prompt_line_count",
    "show_negative_prompt",
    "show_steps",
    "recent_styles_count",
    "tag_files",
    "generation_finished_action",
    "apply_behavior",
    "apply_region_behavior",
    "apply_behavior_live",
    "apply_region_behavior_live",
    "new_seed_after_apply",
    "save_image_format",
    "save_image_metadata",
    "debug_dump_workflow",
    "history_size",
    "history_storage",
    "performance_preset",
    "batch_size",
    "resolution_multiplier",
    "max_pixel_count",
    "tiled_vae",
    "dynamic_caching",
    "multi_threading",
    "auto_update",
}


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict:
    work = tmp_path_factory.mktemp("settings")
    run = subprocess.run(
        [sys.executable, str(HERE / "upstream_settings.py"), str(work / "data")],
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


def test_first_run_writes_every_key_with_its_default(results: dict):
    assert set(results["first_run"]) == FIRST_RUN_KEYS
    assert results["first_run_not_default"] == []


def test_connect_to_a_custom_url_from_the_connection_page(results: dict):
    """REQ-28.4: no Krita AI Diffusion anywhere; Custom ComfyUI, an address, Connect."""
    assert results["dialog_title"] == "Configure Image Diffusion"
    assert results["server_mode"] == "external" and results["server_url"]
    assert (results["connection"], results["connection_error"]) == ("connected", "")
    assert results["connected_to"] == ["/system_stats"]
    # REQ-30.1: the stand-in server has an SD 1.5 checkpoint and every required node and model.
    workloads = results["supported_workloads"]
    assert "<b>SD 1.5</b>: supported" in workloads
    assert "<b>SD XL</b>: missing Diffusion checkpoint model" in workloads


def test_every_control_changes_its_key(results: dict):
    assert set(results["changes"]) == PAGE_KEYS
    wrong = {k: v for k, v in results["changes"].items() if v["expected"] != v["actual"]}
    assert wrong == {}


def test_changes_survive_a_restart(results: dict):
    assert results["after_restart"] == results["changed"]


def test_restore_defaults(results: dict):
    """REQ-28.3: every key on the current page is reset, in the settings and the controls (as
    upstream does, the other pages' keys are reset too)."""
    assert results["restored"] and all(all(r.values()) for r in results["restored"].values())
    assert results["restored_everywhere"] == []


def test_recent_document_settings_apply_to_a_new_document(results: dict):
    assert results["document_defaults"] == 3
    assert results["new_document_batch_count"] == 3


#: Package items that are not one model: core components and workloads.
BUNDLES = {"Python", "ComfyUI", "Custom nodes", "Required models", "Stable Diffusion 1.5"}
BUNDLES |= {"Stable Diffusion XL", "Flux", "Flux 2", "Z-Image"}


def test_model_licenses_are_shown_before_downloading(results: dict):
    """REQ-29.0.4: each model's license, linked, with a mark when it restricts use."""
    workloads = results["workload_licenses"]
    assert workloads and all(
        "<a href=" in props.get("text", "") and props.get("format") == "rich"
        for props in workloads.values()
    )
    krea = next(
        props["text"] for label, props in workloads.items() if label.startswith("Flux Krea")
    )
    assert "FLUX.1 [dev] Non-Commercial License" in krea and "Non-commercial" in krea
    zimage = next(
        props["text"] for label, props in workloads.items() if label.startswith("Z-Image")
    )
    assert "Apache-2.0" in zimage and "Non-commercial" not in zimage

    packages = results["package_licenses"]
    models = {name: text for name, text in packages.items() if name not in BUNDLES}
    assert models and all("<a href=" in text for text in models.values())
    assert "MAT Inpaint" in packages["Required models"], "what a bundle installs is listed"
    assert "Non-commercial" in packages["Required models"]


def test_a_krita_ai_diffusion_managed_install_is_shown(results: dict):
    """REQ-31.1: the install at Krita AI Diffusion's default path, with its backend, version and
    model folders, on the Connection page."""
    reuse = results["krita_reuse"]
    text = reuse["text"]
    assert "Server: Local Managed Server" in text
    assert f"Install folder: {reuse['server']}" in text
    assert "Backend: cuda" in text and "Version: 1.54.0" in text
    assert all(folder in text for folder in reuse["models"])
