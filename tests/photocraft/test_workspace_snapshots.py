"""Structure snapshots of upstream's four workspaces as the Qt mirror sends them to PhotoCraft
(TASK-25). A change in upstream's UI, or in how the mirror maps it, shows up here as a diff to
review. Set ``PHOTOCRAFT_UPDATE_SNAPSHOTS=1`` to write new snapshots after checking the change.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SNAPSHOTS = HERE / "fixtures" / "mirror"
WORKSPACES = ["generation", "upscaling", "live", "custom"]


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory: pytest.TempPathFactory) -> dict:
    work = tmp_path_factory.mktemp("snapshots")
    result = subprocess.run(
        [sys.executable, str(HERE / "workspace_snapshots.py"), str(work / "data")],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        cwd=work,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("workspace", WORKSPACES)
def test_workspace_structure(snapshots: dict, workspace: str):
    tree = snapshots[workspace]
    path = SNAPSHOTS / f"{workspace}.json"
    if os.environ.get("PHOTOCRAFT_UPDATE_SNAPSHOTS") == "1" or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tree, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    assert tree == json.loads(path.read_text(encoding="utf-8"))


def test_every_workspace_has_its_switcher(snapshots: dict):
    """Each workspace starts with the workspace selector, a tool button with an icon."""

    def switchers(n: dict) -> list[dict]:
        own = [n] if n.get("qt") == "WorkspaceSelectWidget" else []
        return own + [s for c in n.get("children", []) for s in switchers(c)]

    for workspace in WORKSPACES:
        found = switchers(snapshots[workspace])
        assert [(n["kind"], n.get("picture")) for n in found] == [("toolButton", True)], workspace
