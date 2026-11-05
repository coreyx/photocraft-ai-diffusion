import hashlib
import os
import shutil
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NamedTuple

from PyQt6.QtCore import QObject, pyqtSignal

from .. import __version__, eventloop
from ..backend.network import NetworkError, RequestManager
from ..platform_tools import ZipFile
from ..util import client_logger as log
from .properties import ObservableProperties, Property


class UpdateState(Enum):
    unknown = 1
    checking = 2
    available = 3
    latest = 4
    downloading = 5
    installing = 6
    restart_required = 7
    failed_check = 8
    failed_update = 9


class UpdatePackage(NamedTuple):
    version: str
    url: str
    sha256: str


def _in_photocraft() -> bool:
    import krita

    return hasattr(krita, "photocraft_host")


def _plugin_version() -> str | None:
    """PhotoCraft: the plug-in's own version (its manifest's), not upstream's."""
    if not _in_photocraft():
        return None
    from photocraft_host.main import identity

    return identity()[1]


def package_platform() -> str:
    """The name of this platform's package, as packaging/build.py names them."""
    import platform
    import sys

    if sys.platform.startswith("win"):
        return "windows-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if platform.machine() == "arm64" else "macos-x64"
    return "linux-x64"


def _is_newer(latest: str, current: str) -> bool:
    """Whether ``latest`` is a later version than ``current`` (numbers compared as numbers)."""

    def key(version: str):
        return [int(p) if p.isdigit() else -1 for p in version.split("-", maxsplit=1)[0].split(".")]

    return key(latest) > key(current)


class AutoUpdate(QObject, ObservableProperties):
    # PhotoCraft: this project's GitHub releases, where upstream asks the online service
    # (REQ-36.0.2). AI_DIFFUSION_UPDATE_URL points elsewhere (tests, mirrors).
    default_api_url = os.getenv(
        "AI_DIFFUSION_UPDATE_URL",
        "https://api.github.com/repos/coreyx/photocraft-ai-diffusion/releases/latest",
    )

    state = Property(UpdateState.unknown)
    latest_version = Property("")
    error = Property("")

    state_changed = pyqtSignal(UpdateState)
    latest_version_changed = pyqtSignal(str)
    error_changed = pyqtSignal(str)

    def __init__(
        self,
        plugin_dir: Path | None = None,
        current_version: str | None = None,
        api_url: str | None = None,
    ):
        super().__init__()
        self.plugin_dir = plugin_dir or Path(__file__).parent.parent.parent
        self.current_version = current_version or _plugin_version() or __version__
        self.api_url = api_url or self.default_api_url
        self._package: UpdatePackage | None = None
        self._temp_dir: TemporaryDirectory | None = None
        self._request_manager: RequestManager | None = None

    def check(self):
        if not self.api_url:
            log.info("No plugin update source configured")
            return None
        return eventloop.run(
            self._handle_errors(
                self._check, UpdateState.failed_check, "Failed to check for new plugin version"
            )
        )

    async def _check(self):
        if self.state is UpdateState.restart_required:
            return

        self.state = UpdateState.checking
        log.info(f"Checking for latest plugin version at {self.api_url}")
        if _in_photocraft():
            return await self._check_release()
        result = await self._net.get(
            f"{self.api_url}/plugin/latest?version={self.current_version}", timeout=10
        )
        self.latest_version = result.get("version")
        if not self.latest_version:
            log.error(f"Invalid plugin update information: {result}")
            self.state = UpdateState.failed_check
            self.error = "Failed to retrieve plugin update information"
        elif self.latest_version == self.current_version:
            log.info("Plugin is up to date!")
            self.state = UpdateState.latest
        elif "url" not in result or "sha256" not in result:
            log.error(f"Invalid plugin update information: {result}")
            self.state = UpdateState.failed_check
            self.error = "Plugin update package is incomplete"
        else:
            log.info(f"New plugin version available: {self.latest_version}")
            self._package = UpdatePackage(
                version=self.latest_version,
                url=result["url"],
                sha256=result["sha256"],
            )
            self.state = UpdateState.available

    def run(self):
        return eventloop.run(
            self._handle_errors(self._run, UpdateState.failed_update, "Failed to update plugin")
        )

    async def _check_release(self):
        """PhotoCraft: the latest GitHub release, its package for this platform, and that
        package's SHA-256 from the release's ``SHA256SUMS``."""
        try:
            release = await self._net.get(self.api_url, timeout=10)
        except NetworkError as e:
            if e.status != 404:
                raise
            # GitHub's answer while the project has published no release: nothing to update to.
            log.info("No release of the plug-in is published yet")
            self.state = UpdateState.latest
            return
        self.latest_version = str(release.get("tag_name", "")).removeprefix("v") or None
        assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets", [])}
        name = f"ai-diffusion-for-photocraft-{self.latest_version}-{package_platform()}.zip"
        if not self.latest_version:
            log.error(f"Invalid plugin release information: {release}")
            self.state = UpdateState.failed_check
            self.error = "Failed to retrieve plugin update information"
        elif not _is_newer(self.latest_version, self.current_version):
            log.info("Plugin is up to date!")
            self.state = UpdateState.latest
        elif not assets.get(name) or not assets.get("SHA256SUMS"):
            log.error(f"Release {self.latest_version} has no {name} or SHA256SUMS")
            self.state = UpdateState.failed_check
            self.error = "Plugin update package is incomplete"
        else:
            sums = (await self._net.download(assets["SHA256SUMS"])).decode("utf-8", "replace")
            sha256 = next(
                (line.split()[0] for line in sums.splitlines() if line.split()[1:] == [name]), None
            )
            if sha256 is None:
                self.state = UpdateState.failed_check
                self.error = "Plugin update package is not listed in SHA256SUMS"
                return
            log.info(f"New plugin version available: {self.latest_version}")
            self._package = UpdatePackage(self.latest_version, assets[name], sha256)
            self.state = UpdateState.available

    async def _run(self):
        assert self.latest_version and self._package

        self._temp_dir = TemporaryDirectory()
        archive_path = Path(self._temp_dir.name) / f"krita_ai_diffusion-{self.latest_version}.zip"
        log.info(f"Downloading plugin update {self._package.url}")
        self.state = UpdateState.downloading
        archive_data = await self._net.download(self._package.url)

        sha256 = hashlib.sha256(archive_data).hexdigest()
        if sha256 != self._package.sha256:
            log.error(f"Update package hash mismatch: {sha256} != {self._package.sha256}")
            raise RuntimeError("Downloaded plugin package is corrupted or incomplete")

        if _in_photocraft():
            # PhotoCraft installs it: the running plug-in can't replace its own Python. It stops
            # the plug-in after answering, replaces its folder and starts it again (REQ-36.0.2).
            from ..util import user_data_dir

            package = user_data_dir / "updates" / f"{self.latest_version}.zip"
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_bytes(archive_data)
            self.state = UpdateState.installing
            import krita

            krita.Krita.instance()._host.call("plugin.update", {"path": str(package)})  # type: ignore
            self.state = UpdateState.restart_required
            return

        archive_path.write_bytes(archive_data)
        source_dir = Path(self._temp_dir.name) / f"krita_ai_diffusion-{self.latest_version}"
        log.info(f"Extracting plugin archive into {source_dir}")
        self.state = UpdateState.installing
        with ZipFile(archive_path) as zip_file:
            zip_file.extractall(source_dir)

        log.info(f"Installing new plugin version to {self.plugin_dir}")
        shutil.copytree(source_dir, self.plugin_dir, dirs_exist_ok=True)
        self.current_version = self.latest_version
        self.state = UpdateState.restart_required

    @property
    def is_available(self):
        return self.latest_version is not None and self.latest_version != self.current_version

    @property
    def _net(self):
        if self._request_manager is None:
            self._request_manager = RequestManager()
        return self._request_manager

    async def _handle_errors(self, func, error_state: UpdateState, message: str):
        try:
            return await func()
        except Exception as e:
            log.exception(e)
            self.error = f"{message}: {e}"
            self.state = error_state
            return None
