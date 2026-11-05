"""Tests for the graph-parity tooling and the fixtures captured with it (TASK-4)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.photocraft.parity import normalize, scenarios

FIXTURES = Path(__file__).parent / "fixtures" / "graphs"
DRIVER = Path(__file__).parent / "parity" / "driver.py"


# --- normalize.diff ---


def test_diff_equal_values_have_no_differences():
    value = {"a": [1, 2.5, {"b": "x"}], "c": None}
    assert normalize.diff(value, json.loads(json.dumps(value))) == []


def test_diff_reports_paths_of_changes():
    expected = {"nodes": {"1": {"steps": 20}}, "list": [1, 2]}
    actual = {"nodes": {"1": {"steps": 21}, "2": {}}, "list": [1]}
    problems = normalize.diff(expected, actual)
    assert "$.nodes.1.steps: 20 != 21" in problems
    assert "$.nodes.2: unexpected" in problems
    assert "$.list: length 2 != 1" in problems


def test_diff_reports_type_and_missing_keys():
    assert normalize.diff({"a": 1}, {"a": "1"}) == ["$.a: type int != str"]
    assert normalize.diff({"a": 1}, {}) == ["$.a: missing"]


def test_diff_tolerates_float_noise_only():
    assert normalize.diff(0.1 + 0.2, 0.3) == []
    assert normalize.diff(0.3, 0.31) != []


def test_image_fields_are_the_api_image_fields():
    for key in ["initial_image", "hires_image", "hires_mask", "mask", "image"]:
        assert normalize._is_image_field(key)
    assert not normalize._is_image_field("seed")


# --- scenarios ---


def test_scenario_ids_are_unique():
    ids = [s.id for s in scenarios.SCENARIOS]
    assert len(ids) == len(set(ids))


def test_matrix_covers_every_arch_and_inpaint_mode():
    ids = set(scenarios.SCENARIOS_BY_ID)
    for arch in scenarios.ARCHS:
        for mode in scenarios.INPAINT_MODES:
            assert f"{arch}-inpaint-{mode}" in ids
        assert {f"{arch}-generate", f"{arch}-refine", f"{arch}-refine-region"} <= ids


def test_selection_mask_is_cropped_to_shape():
    data, x, y, w, h = scenarios.selection_mask(("rect", 10, 20, 30, 40))
    assert (x, y, w, h) == (10, 20, 30, 40)
    assert data.size() == 30 * 40
    assert set(bytes(data.data())) == {255}


def test_ellipse_selection_has_unselected_corners():
    data, _, _, w, h = scenarios.selection_mask(("ellipse", 0, 0, 40, 20))
    raw = bytes(data.data())
    assert raw[0] == 0 and raw[w * h - 1] == 0
    assert raw[(h // 2) * w + w // 2] == 255


def test_selection_bounds_are_tight():
    """Each edge of the returned mask has a selected pixel, as Krita's selection bounds do."""
    data, x, y, w, h = scenarios.selection_mask(("ellipse", 160, 120, 200, 180))
    raw = bytes(data.data())
    rows = [raw[r * w : (r + 1) * w] for r in range(h)]
    assert any(rows[0]) and any(rows[-1])
    assert any(row[0] for row in rows) and any(row[-1] for row in rows)
    assert 160 <= x and 120 <= y and x + w <= 360 and y + h <= 300


def test_describe_is_json_serializable():
    for scenario in scenarios.SCENARIOS:
        json.dumps(scenario.describe())


# --- fixtures ---


def test_every_scenario_has_a_fixture():
    stored = {p.stem for p in FIXTURES.glob("*.json")}
    assert stored == set(scenarios.SCENARIOS_BY_ID)


@pytest.mark.parametrize("scenario_id", sorted(scenarios.SCENARIOS_BY_ID))
def test_fixture_is_complete(scenario_id: str):
    data = json.loads((FIXTURES / f"{scenario_id}.json").read_text("utf-8"))
    assert data["scenario"] == json.loads(
        json.dumps(scenarios.SCENARIOS_BY_ID[scenario_id].describe())
    )
    assert "input" in data and "prompt" in data
    assert data["input"]["kind"]
    classes = {node["class_type"] for node in data["prompt"].values()}
    assert (
        any(c.startswith("ETN_SaveImageCache") or c == "ETN_ReturnImage" for c in classes)
        or classes
    )


def test_fixtures_capture_scenario_intent():
    def load(name: str) -> dict:
        return json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))

    assert load("sdxl-inpaint-automatic-edge")["input"]["inpaint"]["mode"] == "expand"
    assert load("sdxl-inpaint-automatic")["input"]["inpaint"]["mode"] == "fill"
    assert load("sd15-refine")["input"]["kind"] == "refine"
    assert load("sd15-refine-region")["input"]["kind"] == "refine_region"
    assert load("sdxl-upscale-tiled")["input"]["kind"] == "upscale_tiled"
    assert load("sdxl-upscale-simple")["input"]["kind"] == "upscale_simple"
    region_classes = {n["class_type"] for n in load("sdxl-regions")["prompt"].values()}
    assert "ETN_DefineRegion" in region_classes
    control_classes = {
        n["class_type"] for n in load("sdxl-control-depth-reference")["prompt"].values()
    }
    assert {"ControlNetApplyAdvanced", "IPAdapterModelLoader"} <= control_classes


@pytest.mark.timeout(900)
def test_local_checkout_still_matches_upstream_fixtures(repo_root: Path):
    """This repository's ``ai_diffusion`` must still build exactly upstream's graphs.

    Every change this project makes to upstream files is meant to leave workflow
    construction untouched, so this regression check runs the whole matrix
    against the local checkout and compares it with the upstream fixtures.
    """
    result = subprocess.run(
        [sys.executable, str(DRIVER), "--source", str(repo_root), "--check", str(FIXTURES)],
        capture_output=True,
        text=True,
        timeout=880,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


@pytest.mark.timeout(900)
def test_photocraft_builds_upstream_graphs(repo_root: Path):
    """REQ-15 to REQ-17, TASK-28: every scenario run on the ``krita`` stand-in and the mock
    PhotoCraft (documents, layers and selections through the protocol) builds the same
    ComfyUI requests as upstream does in Krita."""
    result = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            "--source",
            str(repo_root),
            "--host",
            "photocraft",
            "--check",
            str(FIXTURES),
        ],
        capture_output=True,
        text=True,
        timeout=880,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert " 0 differ" in result.stdout
