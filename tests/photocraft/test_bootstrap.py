"""The plug-in's first program (TASK-42, REQ-13.0.2): hello at once, the runtime installed with
progress and Retry, then the plug-in run in the same process on the same connection."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from photocraft_host import bootstrap
from photocraft_host.framing import encode, read_frame

# -- the runtime


def test_a_runtime_is_ready_once_installed_from_this_lock(tmp_path: Path):
    lock = tmp_path / "uv.lock"
    lock.write_text("version = 1\n")
    runtime = tmp_path / "runtime"
    digest = bootstrap.lock_digest(lock)
    assert not bootstrap.is_ready(runtime, digest)
    runtime.mkdir()
    (runtime / bootstrap.READY_MARK).write_text(digest)
    assert bootstrap.is_ready(runtime, digest)
    lock.write_text("version = 1\n# another lock\n")
    assert not bootstrap.is_ready(runtime, bootstrap.lock_digest(lock)), "a new package re-installs"


def test_where_the_runtime_keeps_its_packages(tmp_path: Path):
    packages = bootstrap.site_packages(tmp_path).relative_to(tmp_path).as_posix()
    expected = (
        "Lib/site-packages"
        if sys.platform.startswith("win")
        else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    assert packages == expected


# -- provisioning, against a stand-in PhotoCraft


class _Host:
    """Plays PhotoCraft on a pair of pipes: answers every request, records them, and presses
    the panel's Retry button when asked to."""

    def __init__(self):
        plugin_in, self._to_plugin = os.pipe()
        self._from_plugin, plugin_out = os.pipe()
        self.reader = os.fdopen(plugin_in, "rb", buffering=0)
        self.writer = os.fdopen(plugin_out, "wb", buffering=0)
        self._out = os.fdopen(self._to_plugin, "wb", buffering=0)
        self._in = os.fdopen(self._from_plugin, "rb", buffering=0)
        self.requests: list[tuple[str, dict[str, Any]]] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while (frame := read_frame(self._in)) is not None:
            header = frame.header
            if header["type"] == "request":
                self.requests.append((header["method"], header.get("params") or {}))
                self._out.write(encode({"type": "response", "id": header["id"], "result": {}}))

    def press_retry(self):
        data = {"panelId": bootstrap.PANEL_ID, "nodeId": "retry", "kind": "click", "value": True}
        self._out.write(encode({"type": "event", "topic": "panel.input", "data": data}))

    def ping(self, request_id: int):
        self._out.write(
            encode({"type": "request", "id": request_id, "method": "ping", "params": {}})
        )

    def patched(self, node: str) -> list[dict[str, Any]]:
        return [
            op["props"]
            for method, params in self.requests
            if method == "panel.patch"
            for op in params["ops"]
            if op["id"] == node
        ]


def _wait(condition, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met"
        time.sleep(0.01)


def test_provisioning_shows_progress_and_retries_after_a_failure(tmp_path: Path):
    host = _Host()
    session = bootstrap.Session(host.reader, host.writer)
    attempts: list[int] = []

    def install(_plugin: Path, runtime: Path, _cache: Path, on_line) -> int:
        attempts.append(len(attempts))
        on_line("Resolved 3 packages in 2ms")
        if len(attempts) == 1:
            on_line("error: Failed to download `pyqt6`: connection reset")
            return 2
        on_line("Installed 3 packages in 1.2s")
        runtime.mkdir(parents=True, exist_ok=True)
        return 0

    result: list[bool] = []
    worker = threading.Thread(
        target=lambda: result.append(
            bootstrap.provision(
                session, tmp_path, tmp_path / "runtime", tmp_path / "cache", install
            )
        )
    )
    worker.start()
    _wait(lambda: {"visible": True} in host.patched("retry"))
    assert any("connection reset" in p.get("text", "") for p in host.patched("detail"))
    host.ping(900)  # PhotoCraft's pings are answered meanwhile
    host.press_retry()
    worker.join(10)
    assert result == [True] and len(attempts) == 2
    methods = [m for m, _ in host.requests]
    assert methods[0] == "panel.register" and methods[-1] == "panel.unregister"
    register = host.requests[0][1]
    assert register["panelId"] == bootstrap.PANEL_ID and register["title"] == "AI Diffusion"
    assert {"text": "Installed 3 packages in 1.2s"} in host.patched("detail")


# -- the whole start, with a runtime already installed


def test_with_its_runtime_ready_the_plugin_starts_on_the_same_connection(tmp_path: Path):
    repo = Path(__file__).resolve().parents[2]
    data = tmp_path / "data"
    runtime = data / "runtime"
    runtime.mkdir(parents=True)
    (runtime / bootstrap.READY_MARK).write_text(
        bootstrap.lock_digest(repo / "packaging" / "runtime" / "uv.lock")
    )
    (data / "settings.json").write_text('{"auto_update": false}')
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PHOTOCRAFT_PLUGIN_NONCE": "n0nce",
        "PHOTOCRAFT_PLUGIN_DIR": str(repo),
    }
    log_path = tmp_path / "plugin.log"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(repo / "photocraft_host" / "bootstrap.py")],
            cwd=repo,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log_file,
        )
        assert proc.stdin is not None and proc.stdout is not None
        requests: list[tuple[int, str]] = []
        try:
            started = time.monotonic()
            hello = read_frame(proc.stdout)
            assert hello is not None and hello.header["method"] == "hello"
            assert time.monotonic() - started < 10, "within PhotoCraft's 10 seconds"
            welcome = {"hostVersion": "test", "protocol": 1, "locale": "en", "dataDir": str(data)}
            proc.stdin.write(
                encode({"type": "response", "id": hello.header["id"], "result": welcome})
            )
            proc.stdin.flush()
            sent_shutdown = False
            while (frame := read_frame(proc.stdout)) is not None:
                header = frame.header
                if header["type"] == "request":
                    requests.append((header["id"], header["method"]))
                    result: object = [] if header["method"] == "doc.list" else {}
                    proc.stdin.write(
                        encode({"type": "response", "id": header["id"], "result": result})
                    )
                    if header["method"] == "panel.register" and not sent_shutdown:
                        # The plug-in proper is running: ping it, then end the session.
                        ping = {"type": "request", "id": 100, "method": "ping", "params": {}}
                        bye = {"type": "request", "id": 101, "method": "shutdown", "params": {}}
                        proc.stdin.write(encode(ping) + encode(bye))
                        sent_shutdown = True
                    proc.stdin.flush()
                elif header.get("id") == 101:
                    break
            assert proc.wait(timeout=30) == 0, log_path.read_text(errors="replace")[-3000:]
        finally:
            if proc.poll() is None:
                proc.kill()
    log = log_path.read_text(errors="replace")
    methods = [m for _, m in requests]
    assert "panel.register" in methods, log[-3000:]
    assert methods.count("action.register") == 15, "the plug-in proper started"
    assert "connected to PhotoCraft test" in log
    assert ("panel.register", bootstrap.PANEL_ID) not in [(m, "") for m in methods]
    ids = [i for i, _ in requests]
    assert min(ids) > hello.header["id"], "the plug-in's requests follow the bootstrap's"
    assert len(set(ids)) == len(ids)
