"""Updates from this project's releases, and diagnostics, on the ``krita`` stand-in (TASK-43,
REQ-36).

With a stand-in for GitHub: a newer release found, with its package for this platform and the
SHA-256 from its ``SHA256SUMS``; a tampered package refused; a good one handed to PhotoCraft
(``plugin.update``), which installs it and restarts the plug-in. Diagnostics without the home
folder, the user name, the launch nonce or token values; logs that rotate.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import hashlib
import logging.handlers
from pathlib import Path

import krita
import pytest

from ai_diffusion import util
from ai_diffusion.model import root as root_module
from ai_diffusion.model.updates import AutoUpdate, UpdateState, package_platform
from ai_diffusion.settings import settings

from ..conftest import qtapp

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)

RELEASES = "https://api.github.com/repos/coreyx/photocraft-ai-diffusion/releases/latest"


def _host():
    from ..photocraft import upstream_shim

    return upstream_shim._host


class _GitHub:
    """GitHub's answers for a release ``version`` whose package is ``package``."""

    def __init__(self, version: str, package: bytes, listed: bytes | None = None):
        self.name = f"ai-diffusion-for-photocraft-{version}-{package_platform()}.zip"
        self.package = package
        digest = hashlib.sha256(listed if listed is not None else package).hexdigest()
        self.sums = f"{digest}  {self.name}\nabc123  other-platform.zip\n".encode()
        self.release = {
            "tag_name": f"v{version}",
            "assets": [
                {"name": self.name, "browser_download_url": f"https://example.com/{self.name}"},
                {"name": "SHA256SUMS", "browser_download_url": "https://example.com/SHA256SUMS"},
            ],
        }
        self.asked: list[str] = []

    async def get(self, url: str, timeout: float | None = None):
        self.asked.append(url)
        return self.release

    async def download(self, url: str):
        self.asked.append(url)
        return self.sums if url.endswith("SHA256SUMS") else self.package


def _update(github: _GitHub, current: str = "1.0.0") -> AutoUpdate:
    update = AutoUpdate(current_version=current)
    update._request_manager = github  # type: ignore[assignment]
    return update


async def _check(update: AutoUpdate):
    await update._handle_errors(update._check, UpdateState.failed_check, "check")


@qtapp
async def test_a_newer_release_is_found_with_its_checksum():
    github = _GitHub("1.2.0", b"package")
    update = _update(github)
    assert update.api_url == RELEASES
    await _check(update)
    assert (update.state, update.latest_version) == (UpdateState.available, "1.2.0")
    assert update._package is not None
    assert update._package.url.endswith(github.name)
    assert update._package.sha256 == hashlib.sha256(b"package").hexdigest()


@qtapp
async def test_the_same_or_an_older_release_is_not_an_update():
    for current in ("1.2.0", "1.10.0"):
        update = _update(_GitHub("1.2.0", b"package"), current)
        await _check(update)
        assert update.state is UpdateState.latest, current


@qtapp
async def test_a_tampered_package_is_not_installed():
    """REQ-36.2."""
    github = _GitHub("1.2.0", b"tampered package", listed=b"the real package")
    update = _update(github)
    await _check(update)
    await update._handle_errors(update._run, UpdateState.failed_update, "update")
    assert update.state is UpdateState.failed_update
    assert "corrupted" in update.error
    assert _host().updates == [], "PhotoCraft was not asked to install it"


@qtapp
async def test_a_good_package_is_installed_by_photocraft():
    """REQ-36.1: PhotoCraft installs it and restarts the plug-in."""
    update = _update(_GitHub("1.2.0", b"the package"))
    await _check(update)
    await update._handle_errors(update._run, UpdateState.failed_update, "update")
    assert update.state is UpdateState.restart_required, update.error
    (path,) = _host().updates
    assert Path(path).read_bytes() == b"the package"
    assert Path(path).is_relative_to(util.user_data_dir)


def test_diagnostics_hide_paths_names_and_secrets(monkeypatch: pytest.MonkeyPatch):
    """REQ-36.3."""
    home = Path.home()
    monkeypatch.setenv("PHOTOCRAFT_PLUGIN_NONCE", "nonce-7d1f")
    saved = settings.server_authorization
    settings.server_authorization = "sk-secret-token"
    util.client_logger.info(
        f"connecting with sk-secret-token from {home / 'Pictures'} (nonce-7d1f)"
    )
    util.client_logger.info(f"data in {util.user_data_dir}, as JSON {str(util.user_data_dir)!r}")
    for handler in util.client_logger.handlers:
        handler.flush()
    try:
        report = root_module.collect_diagnostics()
    finally:
        settings.server_authorization = saved
    for secret in (
        "sk-secret-token",
        "nonce-7d1f",
        str(home),
        home.as_posix(),
        str(util.user_data_dir),
    ):
        assert secret not in report, secret
    if len(home.name) > 2:
        assert home.name not in report
    assert "<plug-in data>" in report and "~" in report


def test_logs_rotate_at_10_mb_with_4_backups():
    """REQ-36.0.4."""
    for logger in (util.client_logger, util.server_logger):
        (handler,) = [
            h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert (handler.maxBytes, handler.backupCount) == (10 * 1024 * 1024, 4)
