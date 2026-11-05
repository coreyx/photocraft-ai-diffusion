"""The plug-in package's contents (TASK-39, REQ-32.3): no online-service endpoints, branding or
sign-in, and no cloud module."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packaging"))

import contents  # pyright: ignore[reportMissingImports]  (packaging/ is put on the path above)


def _relative(files: list[Path]) -> set[str]:
    return {f.relative_to(REPO).as_posix() for f in files}


def test_the_package_mentions_no_online_service():
    assert contents.check(contents.package_files()) == []


def test_the_package_holds_the_plugin_and_not_the_cloud_module():
    files = _relative(contents.package_files())
    assert {"ai_diffusion/backend/cloud_client.py", "photocraft_host/cloud.py"} <= files
    assert "ai_diffusion/websockets/src/websockets/client.py" in files
    assert not [f for f in files if f.startswith("ai_diffusion_cloud/")]
    assert not [f for f in files if "/debugpy/" in f or "/__pycache__/" in f]
    assert not [f for f in files if f.startswith("ai_diffusion/websockets/tests/")]


def test_the_check_finds_a_name_or_a_mention(tmp_path: Path):
    (tmp_path / "ai_diffusion" / "icons").mkdir(parents=True)
    (tmp_path / "photocraft_host").mkdir()
    (tmp_path / "ai_diffusion" / "icons" / "Interstice-dark.svg").write_text("<svg/>")
    (tmp_path / "photocraft_host" / "links.py").write_text("URL = 'https://api.INTERSTICE.cloud'")
    (tmp_path / "photocraft_host" / "fine.py").write_text("URL = 'https://example.com'")
    hits = contents.check(contents.package_files(tmp_path), tmp_path)
    assert sorted(hits) == [
        "ai_diffusion/icons/Interstice-dark.svg: interstice",
        "photocraft_host/links.py: interstice",
    ]
