"""The coverage gate itself (TASK-45, REQ-39.1): it measures the files each threshold names and
fails when one isn't met."""

from __future__ import annotations

import pytest

from .coverage_gate import GATES, check, measure


def _file(lines: int, covered: int, branches: int, covered_branches: int) -> dict:
    return {
        "summary": {
            "num_statements": lines,
            "covered_lines": covered,
            "num_branches": branches,
            "covered_branches": covered_branches,
        }
    }


def _report(**files: dict) -> dict:
    return {"files": {path.replace("__", "/") + ".py": data for path, data in files.items()}}


def test_each_gate_measures_its_own_files():
    report = _report(
        photocraft_host__krita___app=_file(100, 95, 10, 8),
        photocraft_host__krita_reuse=_file(100, 91, 10, 7),
        photocraft_host__transport=_file(100, 60, 10, 5),
    )
    overall, stand_in, reuse = GATES
    assert measure(report, overall) == (82.0, 66.66666666666667)
    assert measure(report, stand_in) == (95.0, 80.0)
    assert measure(report, reuse) == (91.0, 70.0)
    lines = check(report)
    assert [line.split()[0] for line in lines] == ["FAIL", "ok", "ok"], "66.7% of branches"


def test_windows_paths_and_files_without_branches():
    report = _report(photocraft_host__krita_reuse=_file(10, 9, 0, 0))
    report["files"] = {k.replace("/", "\\"): v for k, v in report["files"].items()}
    assert measure(report, GATES[2]) == (90.0, 100.0)


def test_a_gate_with_nothing_measured_is_an_error():
    with pytest.raises(ValueError, match="no files measured"):
        measure(_report(packaging__build=_file(1, 1, 0, 0)), GATES[1])
