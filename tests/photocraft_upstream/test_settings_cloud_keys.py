"""Cloud-only settings on the ``krita`` stand-in (TASK-36, REQ-28.0.1, REQ-32).

``access_token`` and ``last_news`` are kept in ``settings.json`` only while the cloud module is
enabled; otherwise they are neither written nor read, so a token stored by another install is
never used.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import krita
import pytest

from ai_diffusion.settings import Settings

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)

from photocraft_host import cloud


def _settings(path: Path) -> Settings:
    settings = Settings()
    settings.default_path = path
    return settings


def test_cloud_keys_are_not_written_or_read_without_the_cloud_module(tmp_path: Path):
    path = tmp_path / "settings.json"
    settings = _settings(path)
    settings.access_token = "secret"
    settings.last_news = "digest"
    settings.save()
    stored = json.loads(path.read_text())
    assert "access_token" not in stored and "last_news" not in stored
    assert "server_url" in stored

    path.write_text(
        json.dumps({"access_token": "from-elsewhere", "server_url": "example.com:8188"})
    )
    loaded = _settings(path)
    loaded.load()
    assert (loaded.access_token, loaded.server_url) == ("", "example.com:8188")


def test_cloud_keys_are_kept_with_the_cloud_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cloud, "enabled", lambda: True)
    path = tmp_path / "settings.json"
    settings = _settings(path)
    settings.access_token = "token"
    settings.save()
    assert json.loads(path.read_text())["access_token"] == "token"
    loaded = _settings(path)
    loaded.load()
    assert loaded.access_token == "token"


def test_the_cloud_module_needs_the_flag_and_the_package(monkeypatch: pytest.MonkeyPatch):
    present = lambda name: object() if name == cloud.MODULE else None
    monkeypatch.delenv(cloud.FLAG, raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", present)
    assert not cloud.enabled(), "the flag is off"
    monkeypatch.setenv(cloud.FLAG, "1")
    assert cloud.enabled()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert not cloud.enabled(), "the package is missing"
