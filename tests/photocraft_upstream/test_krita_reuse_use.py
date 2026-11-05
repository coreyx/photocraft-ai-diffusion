"""Using a Krita AI Diffusion configuration on the ``krita`` stand-in (TASK-41, REQ-31).

With upstream's server and connection code and a stand-in ComfyUI server: using the same server
for a custom and a managed configuration (connecting with no install or download, the install
folder unchanged), the guard on installs Krita AI Diffusion manages, a moved or upgraded
install, importing settings with and without secrets, this plug-in's own server sharing the
models, and switching to another server. Starting Krita AI Diffusion's ComfyUI for real is the
end-to-end test in TASK-45.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import socket
import time
from collections.abc import Callable
from pathlib import Path

import krita
import pytest

from ai_diffusion import platform_tools
from ai_diffusion.backend import resources, server
from ai_diffusion.backend.comfy_client import ComfyClient
from ai_diffusion.backend.server import Server, ServerState
from ai_diffusion.model.connection import Connection, ConnectionState
from ai_diffusion.settings import ServerBackend, ServerMode, settings

from ..conftest import qtapp

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)

from photocraft_host import krita_reuse

from ..photocraft.stub_comfy import StubComfy


@pytest.fixture(autouse=True)
def own_settings(monkeypatch: pytest.MonkeyPatch):
    """The plug-in's settings, put back afterwards and never written."""
    saved = copy.deepcopy(settings._values)
    monkeypatch.setattr(settings, "save", lambda *_: None)

    async def no_python(*_args, **_kwargs):
        pass

    monkeypatch.setattr(server, "determine_system_encoding", no_python)
    yield
    settings.__dict__["_values"] = saved  # every setting, as imports change many


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _krita_install(server_dir: Path, version: str = "1.53.0 cuda") -> Path:
    """A Krita AI Diffusion managed install: ComfyUI, its custom nodes, a venv, the required
    models, and its .version."""
    comfy = server_dir / "ComfyUI"
    for package in resources.required_custom_nodes:
        (comfy / "custom_nodes" / package.folder).mkdir(parents=True)
    for name in ("main.py", "nodes.py"):
        (comfy / name).write_text("")
    python = server_dir / "venv" / ("Scripts" if platform_tools.is_windows else "bin")
    python.mkdir(parents=True)
    (python / ("python.exe" if platform_tools.is_windows else "python3")).write_bytes(b"")
    for model in resources.required_models:
        for file in model.files:
            (server_dir / file.path).parent.mkdir(parents=True, exist_ok=True)
            (server_dir / file.path).write_bytes(b"model")
    (server_dir / ".version").write_text(version)
    return server_dir


def _config(folder: Path, **values) -> krita_reuse.KritaConfig:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text(json.dumps(values))
    config = krita_reuse.read_config(folder, "Krita")
    assert config is not None
    return config


def _snapshot(folder: Path) -> dict[str, str | None]:
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        if p.is_file()
        else None
        for p in sorted(folder.rglob("*"))
    }


async def _until(condition: Callable[[], bool], timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.02)


async def _connect(url: str) -> Connection:
    connection = Connection()
    connection.connect(ComfyClient(url))
    await _until(lambda: connection.state in (ConnectionState.connected, ConnectionState.error), 30)
    return connection


@qtapp
async def test_using_a_custom_server(tmp_path: Path):
    """REQ-31.3."""
    with StubComfy() as stub:
        config = _config(tmp_path / "ai_diffusion", server_mode="external", server_url=stub.url)
        krita_reuse.use_same_server(config, settings)
        assert (settings.server_mode, settings.server_url) == (ServerMode.external, stub.url)
        assert settings.photocraft_reuse["mode"] == "same_server"
        connection = await _connect(settings.server_url)
        assert connection.state is ConnectionState.connected
        await connection.disconnect()


@qtapp
async def test_using_a_running_managed_install_installs_and_changes_nothing(tmp_path: Path):
    """REQ-31.2, 31.4 (the server already running, as Krita AI Diffusion started it)."""
    port = _free_port()
    data = tmp_path / "ai_diffusion"
    install = _krita_install(data / "server")
    config = _config(
        data, server_mode="managed", server_backend="cuda", server_arguments=f"--port {port}"
    )
    before = _snapshot(install)

    krita_reuse.use_same_server(config, settings)
    assert settings.server_mode is ServerMode.managed
    assert (settings.server_path, settings.server_backend) == (str(install), ServerBackend.cuda)
    assert settings.server_arguments == f"--port {port}"
    srv = Server(settings.server_path)
    assert srv.state is ServerState.stopped, "launchable as it is, not 'Upgrade required'"
    assert krita_reuse.is_krita_managed(srv.path, settings)

    with StubComfy(port=port) as _stub:
        connection = await _connect(krita_reuse.managed_url(config))
        assert connection.state is ConnectionState.connected
        await connection.disconnect()
    assert _snapshot(install) == before, "no install, no download, no change"


def test_a_moved_install_and_a_version_change_are_reported(tmp_path: Path):
    """REQ-31.6, 31.0.9."""
    data = tmp_path / "ai_diffusion"
    install = _krita_install(data / "server", "1.54.0 cuda")
    config = _config(data, server_mode="managed")
    krita_reuse.use_same_server(config, settings)
    assert krita_reuse.validate(settings) is None

    (install / ".version").write_text("1.55.0 cuda")
    notice = krita_reuse.validate(settings)
    assert notice and "1.54.0" in notice and "1.55.0" in notice
    assert settings.photocraft_reuse["detected_version"] == "1.55.0"
    assert krita_reuse.validate(settings) is None, "said once"

    install.rename(tmp_path / "renamed")
    notice = krita_reuse.validate(settings)
    assert notice and "moved or deleted" in notice and str(install) in notice
    srv = Server(settings.server_path)  # what the plug-in does next: no crash
    assert srv.state is ServerState.not_installed


def test_importing_settings_without_and_with_secrets(tmp_path: Path):
    """REQ-31.5, 31.0.8."""
    data = tmp_path / "ai_diffusion"
    config = _config(
        data,
        server_mode="external",
        server_url="192.0.2.5:8188",
        server_authorization="secret-token",
        history_size=2500,
        apply_behavior="replace",
    )
    for name in (
        "styles/mine.json",
        "presets/samplers.json",
        "tags/my-tags.csv",
        "workflows/w.json",
    ):
        (data / name).parent.mkdir(parents=True, exist_ok=True)
        (data / name).write_text("{}")
    ours = tmp_path / "ours"
    (ours / "styles").mkdir(parents=True)
    (ours / "styles" / "mine.json").write_text('{"name": "kept"}')
    settings.server_authorization = ""

    result = krita_reuse.import_settings(config, ours, settings)
    assert settings.server_authorization == "", "not without the confirmation"
    assert "server_url" not in result["settings"], "where the server is: Use the same server"
    assert settings.history_size == 2500 and "apply_behavior" in result["settings"]
    assert sorted(result["files"]) == [
        "presets/samplers.json",
        "tags/my-tags.csv",
        "workflows/w.json",
    ]
    assert (ours / "styles" / "mine.json").read_text() == '{"name": "kept"}', "ours kept"
    assert "secret-token" not in repr(result)

    krita_reuse.import_settings(config, ours, settings, secrets=True)
    assert settings.server_authorization == "secret-token"


@qtapp
async def test_our_own_server_sharing_the_models_downloads_none_of_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """REQ-31.7: models already in the reused install's folders are not downloaded again."""
    data = tmp_path / "ai_diffusion"
    krita_install = _krita_install(data / "server")
    have, need = resources.default_checkpoints[0], resources.default_checkpoints[1]
    for file in have.files:
        (krita_install / file.path).parent.mkdir(parents=True, exist_ok=True)
        (krita_install / file.path).write_bytes(b"checkpoint")
    config = _config(data, server_mode="managed")

    own = tmp_path / "own"
    krita_reuse.share_models(config, settings, own)
    assert krita_reuse.shared_model_installs(settings) == [krita_install]
    comfy = own / "ComfyUI"
    comfy.mkdir(parents=True)
    (comfy / "extra_model_paths.yaml.example").write_text("#comfyui:\n")
    server._configure_extra_model_paths(comfy)
    yaml = (comfy / "extra_model_paths.yaml").read_text()
    assert f"base_path: {(krita_install / 'models').as_posix()}" in yaml

    _krita_install(own, f"{resources.version} cuda")  # our own install, finished
    srv = Server(str(own))
    assert not krita_reuse.is_krita_managed(srv.path, settings), "ours: fully managed here"
    assert have.id.string not in srv.missing_resources
    fetched: list[str] = []

    async def download(_name, _network, url, file: Path, _cb):
        fetched.append(url)
        file.write_bytes(b"downloaded")

    monkeypatch.setattr(server, "_download_cached", download)
    await srv.download([have.id.string, need.id.string], lambda _progress: None)
    assert fetched == [f.url for f in need.files]


@qtapp
async def test_switching_to_another_server_ends_the_reuse(tmp_path: Path):
    """REQ-31.9, 31.0.11: another address, then Krita AI Diffusion removed."""
    data = tmp_path / "ai_diffusion"
    config = _config(data, server_mode="external", server_url="192.0.2.5:8188")
    krita_reuse.use_same_server(config, settings)
    with StubComfy() as other:
        settings.server_url = other.url
        krita_reuse.forget_when_switched(settings, "server_url", other.url)
        assert settings.photocraft_reuse == {}
        for file in sorted(data.rglob("*"), reverse=True):
            file.unlink() if file.is_file() else file.rmdir()
        data.rmdir()
        connection = await _connect(settings.server_url)
        assert connection.state is ConnectionState.connected
        await connection.disconnect()


def test_reuse_is_kept_while_its_server_is_kept(tmp_path: Path):
    data = tmp_path / "ai_diffusion"
    install = _krita_install(data / "server")
    config = _config(data, server_mode="managed")
    krita_reuse.use_same_server(config, settings)
    krita_reuse.forget_when_switched(settings, "server_path", str(install))
    assert settings.photocraft_reuse["server_path"] == str(install)
    settings.server_path = str(tmp_path / "elsewhere")
    krita_reuse.forget_when_switched(settings, "server_path", settings.server_path)
    assert settings.photocraft_reuse == {}
