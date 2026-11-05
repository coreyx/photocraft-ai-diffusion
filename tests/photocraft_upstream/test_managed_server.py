"""Upstream's managed ComfyUI server on the ``krita`` stand-in (TASK-37, REQ-29).

Installing for real (uv, Python, ComfyUI, CUDA torch, models) is the end-to-end test in TASK-45.
Here, with the installer's network steps replaced: the default install folder, the plug-in's own
``extra_model_paths.yaml`` section (kept through an upgrade, with the user's edits), a failed
install that keeps what finished and can be retried, a failed model download, Verify finding a
corrupted model and re-downloading it, and the server process ending with the plug-in: for real
on Windows (a job object), and the process-group watcher used on macOS and Linux.

Runs with the stand-in loaded (``python -m pytest -p tests.photocraft.upstream_shim ...``); under
upstream's own mock the module is skipped.
"""

from __future__ import annotations

import asyncio
import builtins
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import krita
import pytest

from ai_diffusion import platform_tools, util
from ai_diffusion.backend import resources, server
from ai_diffusion.backend.resources import VerificationState
from ai_diffusion.backend.server import Server, ServerState
from ai_diffusion.settings import Settings

from ..conftest import qtapp

if not hasattr(krita, "attach"):
    pytest.skip("needs the PhotoCraft krita stand-in", allow_module_level=True)

SECTION = "photocraft-ai-diffusion-managed"
REPO = Path(__file__).resolve().parents[2]


def test_the_default_install_folder_is_in_the_plugin_data():
    assert Settings._server_path.default == str(util.user_data_dir / "server")


def _fresh_comfy(folder: Path, example: str = "#comfyui:\n#    base_path: path/to/comfyui/\n"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "extra_model_paths.yaml.example").write_text(example)
    return folder


def test_the_model_paths_section_is_the_plugins_own(tmp_path: Path):
    comfy = _fresh_comfy(tmp_path / "ComfyUI")
    server._configure_extra_model_paths(comfy)
    text = (comfy / "extra_model_paths.yaml").read_text()
    assert f"\n{SECTION}:\n" in text and "krita-managed" not in text
    assert "    model_patches: model_patches" in text
    server._configure_extra_model_paths(comfy)
    assert (comfy / "extra_model_paths.yaml").read_text() == text, (
        "configuring again changes nothing"
    )


def test_an_upgrade_keeps_the_users_model_paths_and_models(tmp_path: Path):
    old, new = _fresh_comfy(tmp_path / "old"), _fresh_comfy(tmp_path / "new")
    server._configure_extra_model_paths(old)
    edited = (old / "extra_model_paths.yaml").read_text() + "\nmy-models:\n    base_path: D:/ai\n"
    (old / "extra_model_paths.yaml").write_text(edited)
    server._upgrade_extra_model_paths(old, new)
    assert (new / "extra_model_paths.yaml").read_text() == edited

    (tmp_path / "old_models" / "loras").mkdir(parents=True)
    (tmp_path / "old_models" / "loras" / "mine.safetensors").write_bytes(b"lora")
    server._upgrade_models_dir(tmp_path / "old_models", tmp_path / "models")
    assert (tmp_path / "models" / "loras" / "mine.safetensors").read_bytes() == b"lora"


class _FakeInstaller:
    """Stands in for the installer's network steps: each writes what the real one would leave."""

    def __init__(self, fail_node: str | None = None):
        self.fail_node = fail_node
        self.nodes: list[str] = []

    def patch(self, monkeypatch: pytest.MonkeyPatch):
        async def noop(*_args, **_kwargs):
            pass

        async def create_venv(srv: Server, _cb):
            python = srv.path / "venv" / ("Scripts" if platform_tools.is_windows else "bin")
            python.mkdir(parents=True)
            exe = python / ("python.exe" if platform_tools.is_windows else "python3")
            exe.write_bytes(b"")
            srv._python_cmd = exe

        async def install_comfy(_srv: Server, comfy_dir: Path, _network, _cb):
            (comfy_dir / "custom_nodes").mkdir(parents=True)
            for name in ("main.py", "nodes.py"):
                (comfy_dir / name).write_text("")

        async def install_node(srv: Server, pkg, _network, _cb):
            self.nodes.append(pkg.name)
            if pkg.name == self.fail_node:
                self.fail_node = None  # fails once
                raise RuntimeError("download interrupted")
            assert srv.comfy_dir is not None or (srv.path / "ComfyUI").exists()
            (srv.path / "ComfyUI" / "custom_nodes" / pkg.folder).mkdir()

        monkeypatch.setattr(Server, "_install_uv", noop)
        monkeypatch.setattr(Server, "_create_venv", create_venv)
        monkeypatch.setattr(Server, "_install_comfy", install_comfy)
        monkeypatch.setattr(Server, "_install_custom_node", install_node)
        monkeypatch.setattr(Server, "_log_python_version", noop)
        monkeypatch.setattr(server, "determine_system_encoding", noop)


@qtapp
async def test_a_failed_install_keeps_what_finished_and_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    nodes = [*resources.required_custom_nodes, *resources.optional_custom_nodes]
    installer = _FakeInstaller(fail_node=nodes[2].name)
    installer.patch(monkeypatch)
    srv = Server(str(tmp_path / "server"))
    assert srv.state is ServerState.not_installed

    with pytest.raises(RuntimeError):
        await srv.install(lambda _progress: None)
    assert (srv.path / ".version").read_text() == "incomplete"
    assert [n.name for n in nodes[:2]] == installer.nodes[:2]
    for kept in nodes[:2]:
        assert (srv.path / "ComfyUI" / "custom_nodes" / kept.folder).exists(), "kept"
    assert srv.state is ServerState.missing_resources, "Install is offered again"
    assert nodes[2].name in srv.missing_resources

    installer.nodes.clear()
    await srv.install(lambda _progress: None)
    assert installer.nodes == [n.name for n in nodes[2:]], "only what was missing"
    assert (srv.path / ".version").read_text() == f"{resources.version} {srv.backend.name}"
    yaml = srv.path / "ComfyUI" / "extra_model_paths.yaml"
    assert not yaml.exists() or SECTION in yaml.read_text()


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Server:
    _FakeInstaller().patch(monkeypatch)
    return Server(str(tmp_path / "server"))


@qtapp
async def test_a_failed_download_keeps_the_models_that_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    srv = _installed(tmp_path, monkeypatch)
    await srv.install(lambda _progress: None)
    first, second = resources.optional_models[0], resources.optional_models[1]
    fetched: list[str] = []

    async def download(name, _network, url, file: Path, _cb):
        fetched.append(url)
        if url == second.files[0].url:
            raise RuntimeError("connection reset")
        file.write_bytes(b"model")

    monkeypatch.setattr(server, "_download_cached", download)
    with pytest.raises(RuntimeError):
        await srv.download([first.id.string, second.id.string], lambda _progress: None)
    assert all((srv.path / f.path).exists() for f in first.files), "kept"
    assert first.id.string not in srv.missing_resources
    assert second.id.string in srv.missing_resources, "offered again"


@qtapp
async def test_verify_finds_a_corrupted_model_and_replaces_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    srv = _installed(tmp_path, monkeypatch)
    await srv.install(lambda _progress: None)
    model = resources.required_models[0]
    file = model.files[0]
    target = srv.path / file.path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not the model")
    srv.state = ServerState.stopped

    bad = await srv.verify(lambda _progress: None)
    mismatched = [s for s in bad if s.state is VerificationState.mismatch]
    assert [s.file.path for s in mismatched] == [file.path]

    replaced: list[tuple[str, bool]] = []

    async def download(name, _network, url, path: Path, _cb):
        replaced.append((url, path.exists()))
        path.write_bytes(b"downloaded again")

    monkeypatch.setattr(server, "_download_cached", download)
    await srv.fix_models(mismatched, lambda _progress: None)
    assert replaced == [(file.url, False)], "the corrupted file is removed, then downloaded"
    assert target.read_bytes() == b"downloaded again"


# -- the server process ends with the plug-in


class _Watched:
    """The calls the server watcher makes, with the plug-in alive for ``alive_for`` checks."""

    def __init__(self, alive_for: int, server_exits_after: int | None = None):
        self.checks = 0
        self.alive_for = alive_for
        self.server_exits_after = server_exits_after
        self.signals: list[tuple[int, int]] = []

    def killpg(self, group: int, sig: int):
        if sig == 0:
            self.checks += 1
            if self.server_exits_after is not None and self.checks > self.server_exits_after:
                raise ProcessLookupError
            return
        self.signals.append((group, sig))

    def getppid(self) -> int:
        return 100 if self.checks <= self.alive_for else 1


def _run_watcher(watched: _Watched):
    modules: dict[str, Any] = {
        "os": watched,
        "signal": SimpleNamespace(SIGTERM=15, SIGKILL=9),
        "sys": SimpleNamespace(argv=["-c", "100", "4242"]),
        "time": SimpleNamespace(sleep=lambda _s: None),
    }

    def importer(name, *args, **kwargs):
        return modules[name] if name in modules else builtins.__import__(name, *args, **kwargs)

    exec(
        platform_tools._server_watcher, {"__builtins__": {**vars(builtins), "__import__": importer}}
    )


def test_the_watcher_ends_the_server_group_when_the_plugin_is_gone():
    watched = _Watched(alive_for=3)
    _run_watcher(watched)
    assert watched.checks == 4
    assert watched.signals == [(4242, 15), (4242, 9)]


def test_the_watcher_stops_when_the_server_exits_by_itself():
    watched = _Watched(alive_for=100, server_exits_after=2)
    _run_watcher(watched)
    assert watched.signals == []


@qtapp
async def test_on_macos_and_linux_the_server_gets_its_own_group_and_a_watcher(
    monkeypatch: pytest.MonkeyPatch,
):
    started: list[tuple[tuple, dict]] = []

    async def spawn(*args, **kwargs):
        started.append((args, kwargs))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(platform_tools, "is_windows", False)
    monkeypatch.setattr(platform_tools, "is_linux", False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await platform_tools.create_process("python", "main.py", is_job=True)
    (server_args, server_kwargs), (watcher_args, watcher_kwargs) = started
    assert server_args == ("python", "main.py") and server_kwargs["start_new_session"]
    assert watcher_args == (
        sys.executable,
        "-c",
        platform_tools._server_watcher,
        str(os.getpid()),
        "4242",
    )
    assert watcher_kwargs["start_new_session"], "it outlives the plug-in's process group"

    started.clear()
    await platform_tools.create_process("python", "--version")
    assert len(started) == 1 and "start_new_session" not in started[0][1], "only the server"


def _alive(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


_PLUGIN = """
import asyncio, sys, time
sys.path.insert(0, sys.argv[1])
from ai_diffusion import platform_tools

async def main():
    server = await platform_tools.create_process(
        sys.executable, "-c", "import time; time.sleep(120)", is_job=True
    )
    print(server.pid, flush=True)
    await asyncio.sleep(120)

asyncio.run(main())
"""


@pytest.mark.skipif(not platform_tools.is_windows, reason="the job object is Windows'")
def test_on_windows_the_server_ends_when_the_plugin_process_is_killed():
    plugin = subprocess.Popen(
        [sys.executable, "-c", _PLUGIN, str(REPO)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert plugin.stdout is not None
        server_pid = int(plugin.stdout.readline())
        assert _alive(server_pid)
        plugin.kill()  # as PhotoCraft ending the plug-in, or a crash: no clean-up runs
        plugin.wait(10)
        deadline = time.monotonic() + 10
        while _alive(server_pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(server_pid)
    finally:
        plugin.kill()
