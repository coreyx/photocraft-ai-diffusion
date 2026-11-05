"""The plug-in's first program: install its runtime if needed, then run it (REQ-13.0.2).

PhotoCraft starts it with the Python the package bundles (``python -I
photocraft_host/bootstrap.py``). It says ``hello`` at once, as PhotoCraft wants within 10
seconds. When the runtime in ``<plug-in data>/runtime`` (PyQt6) doesn't match the package's
``runtime/uv.lock``, it shows a panel with progress while ``uv sync --frozen`` installs it, and
offers Retry if that fails. Then it hands the connection to the plug-in
(:func:`photocraft_host.main.main`) in this same process. Until then it uses the standard library
only, since PyQt6 is what it installs.

The connection is handed over without losing a frame: this module's reader thread keeps reading
standard input and, from then on, passes each frame to the plug-in's transport through a pipe.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

PLUGIN_DIR = Path(os.environ.get("PHOTOCRAFT_PLUGIN_DIR") or Path(__file__).resolve().parents[1])
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))  # started with -I: nothing else is on the path

from photocraft_host import framing

log = logging.getLogger("photocraft_host.bootstrap")

PANEL_ID = "aiDiffusionSetup"
#: The file in the runtime that says which ``uv.lock`` it was installed from.
READY_MARK = ".photocraft-runtime"


# -- the runtime


def lock_digest(lock: Path) -> str:
    """What identifies a runtime: the lock it comes from, and the Python running it."""
    data = lock.read_bytes() + sys.version.encode()
    return hashlib.sha256(data).hexdigest()


def is_ready(runtime: Path, digest: str) -> bool:
    mark = runtime / READY_MARK
    return mark.is_file() and mark.read_text(encoding="utf-8").strip() == digest


def site_packages(runtime: Path) -> Path:
    if sys.platform.startswith("win"):
        return runtime / "Lib" / "site-packages"
    return (
        runtime
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )


def runtime_project(plugin_dir: Path) -> Path:
    """The folder with the runtime's ``pyproject.toml`` and ``uv.lock``: ``runtime/`` in the
    package, ``packaging/runtime/`` in a source checkout."""
    packaged = plugin_dir / "runtime"
    return packaged if (packaged / "uv.lock").is_file() else plugin_dir / "packaging" / "runtime"


def uv_program(plugin_dir: Path) -> Path:
    return plugin_dir / "uv" / ("uv.exe" if sys.platform.startswith("win") else "uv")


def run_uv(plugin_dir: Path, runtime: Path, cache: Path, on_line: Callable[[str], None]) -> int:
    """``uv sync --frozen`` of the package's runtime project into ``runtime``, with the bundled
    Python and nothing downloaded but the locked packages. Each line uv prints goes to
    ``on_line``; returns uv's exit code."""
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(runtime),
        "UV_PYTHON": sys.executable,
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_CACHE_DIR": str(cache),
        "UV_NO_PROGRESS": "1",  # lines, not redrawn progress bars
    }
    command = [
        str(uv_program(plugin_dir)),
        "sync",
        "--frozen",
        "--project",
        str(runtime_project(plugin_dir)),
    ]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0  # type: ignore[attr-defined]
    process = subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        creationflags=flags,
    )
    assert process.stdout is not None
    for line in process.stdout:
        if line.strip():
            on_line(line.strip())
    return process.wait()


# -- the connection, before the plug-in has it


class Session:
    """The protocol connection, spoken with the standard library until the plug-in takes it."""

    def __init__(self, reader: IO[bytes], writer: IO[bytes]):
        self._reader = reader
        self._writer = writer
        self._write_lock = threading.Lock()
        self._lock = threading.Lock()
        self._next_id = 1
        self._waiting: dict[int, tuple[threading.Event, list[framing.Frame]]] = {}
        self._relay: IO[bytes] | None = None
        self.on_input: Callable[[dict[str, Any]], None] = lambda _data: None
        self.on_shutdown: Callable[[], None] = lambda: None
        self.closed = threading.Event()
        threading.Thread(target=self._read_loop, name="bootstrap-reader", daemon=True).start()

    @property
    def next_id(self) -> int:
        return self._next_id

    def send(self, header: dict[str, Any], payload: bytes = b""):
        with self._write_lock:
            self._writer.write(framing.encode(header, payload))
            self._writer.flush()

    def call(self, method: str, params: dict[str, Any], timeout: float = 30.0) -> Any:
        """Send a request and wait for its answer; PhotoCraft's error is a ``RuntimeError``."""
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            done, box = threading.Event(), []
            self._waiting[request_id] = (done, box)
        self.send({"type": "request", "id": request_id, "method": method, "params": params})
        if not done.wait(timeout) or not box:
            raise TimeoutError(f"no answer to {method}")
        header = box[0].header
        if header["type"] == "error":
            error = header.get("error") or {}
            raise RuntimeError(f"{error.get('code')}: {error.get('message')}")
        return header.get("result")

    def hand_over(self) -> IO[bytes]:
        """From now on, pass every frame to the returned stream instead of handling it here."""
        read_end, write_end = os.pipe()
        with self._lock:
            self._relay = os.fdopen(write_end, "wb", buffering=0)
        return os.fdopen(read_end, "rb", buffering=0)

    def _read_loop(self):
        try:
            while (frame := framing.read_frame(self._reader)) is not None:
                with self._lock:
                    relay = self._relay
                if relay is not None:
                    relay.write(framing.encode(frame.header, frame.payload))
                else:
                    self._handle(frame)
        except (framing.ProtocolError, OSError) as e:
            log.error("connection failed: %s", e)
        finally:
            self.closed.set()
            with self._lock:
                if self._relay is not None:
                    self._relay.close()  # the plug-in's transport sees the end too

    def _handle(self, frame: framing.Frame):
        header = frame.header
        if header["type"] in ("response", "error"):
            request_id = header.get("id")
            with self._lock:
                waiting = (
                    self._waiting.pop(request_id, None) if isinstance(request_id, int) else None
                )
            if waiting is not None:
                done, box = waiting
                box.append(frame)
                done.set()
        elif header["type"] == "request":
            method = header.get("method")
            if method in ("ping", "shutdown"):
                self.send({"type": "response", "id": header["id"], "result": {}})
            else:
                error = {"code": "unsupported", "message": f"not ready for {method}"}
                self.send({"type": "error", "id": header["id"], "error": error})
            if method == "shutdown":
                self.on_shutdown()
        elif header["type"] == "event" and header.get("topic") == "panel.input":
            self.on_input(header.get("data") or {})


class ProgressPanel:
    """The panel shown while the runtime is installed: what is happening, a busy bar, and
    Retry once something failed."""

    def __init__(self, session: Session):
        self._session = session
        self._retry = threading.Event()
        session.on_input = self._input
        session.call(
            "panel.register",
            {"panelId": PANEL_ID, "title": "AI Diffusion", "tree": self._tree()},
        )

    @staticmethod
    def _tree() -> dict[str, Any]:
        return {
            "id": "root",
            "kind": "column",
            "children": [
                {
                    "id": "title",
                    "kind": "label",
                    "props": {"text": "Setting up AI Diffusion for PhotoCraft"},
                },
                {
                    "id": "status",
                    "kind": "label",
                    "props": {"text": "Installing its runtime (PyQt6). This happens once."},
                },
                {"id": "progress", "kind": "progress", "props": {}},
                {"id": "detail", "kind": "label", "props": {"text": ""}},
                {"id": "retry", "kind": "button", "props": {"text": "Retry", "visible": False}},
            ],
        }

    def _set(self, node: str, props: dict[str, Any]):
        self._session.call(
            "panel.patch", {"panelId": PANEL_ID, "ops": [{"op": "set", "id": node, "props": props}]}
        )

    def detail(self, text: str):
        self._set("detail", {"text": text[-200:]})

    def failed(self, error: str):
        self._set(
            "status",
            {"text": "The runtime could not be installed. Check the connection, then retry."},
        )
        self._set("detail", {"text": error[-400:]})
        self._set("progress", {"visible": False})
        self._set("retry", {"visible": True})

    def retrying(self):
        self._set("status", {"text": "Installing its runtime (PyQt6). This happens once."})
        self._set("progress", {"visible": None})
        self._set("retry", {"visible": False})

    def wait_for_retry(self, closed: threading.Event) -> bool:
        """Wait until the user presses Retry (``True``) or the connection ends (``False``)."""
        while not closed.is_set():
            if self._retry.wait(0.2):
                self._retry.clear()
                return True
        return False

    def close(self):
        self._session.call("panel.unregister", {"panelId": PANEL_ID})

    def _input(self, data: dict[str, Any]):
        if data.get("panelId", data.get("owner")) == PANEL_ID and data.get("nodeId") == "retry":
            self._retry.set()


def provision(
    session: Session,
    plugin_dir: Path,
    runtime: Path,
    cache: Path,
    install: Callable[[Path, Path, Path, Callable[[str], None]], int] = run_uv,
) -> bool:
    """Install the runtime, showing progress, until it succeeds (``True``) or PhotoCraft goes
    away (``False``). A partly installed runtime is never marked ready."""
    panel = ProgressPanel(session)
    lines: list[str] = []

    def on_line(line: str):
        lines.append(line)
        panel.detail(line)

    while True:
        lines.clear()
        try:
            code = install(plugin_dir, runtime, cache, on_line)
            error = "" if code == 0 else "\n".join(lines[-3:]) or f"uv ended with code {code}"
        except OSError as e:
            error = str(e)
        if not error:
            panel.close()
            return True
        log.error("installing the runtime failed: %s", error)
        panel.failed(error)
        if not panel.wait_for_retry(session.closed):
            return False
        panel.retrying()


def hello(session: Session) -> dict[str, Any]:
    from photocraft_host.main import PROTOCOL_VERSION, identity

    plugin_id, version = identity(PLUGIN_DIR)
    params = {
        "protocol": PROTOCOL_VERSION,
        "nonce": os.environ.get("PHOTOCRAFT_PLUGIN_NONCE", ""),
        "plugin": {"id": plugin_id, "version": version},
    }
    return session.call("hello", params, timeout=10) or {}


def main() -> int:
    """Run the plug-in, installing its runtime first if needed. Returns the exit code."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    reader, writer = framing.stdio_streams()
    session = Session(reader, writer)
    session.on_shutdown = lambda: os._exit(0)
    try:
        welcome = hello(session)
    except (RuntimeError, TimeoutError) as e:
        log.error("PhotoCraft refused the connection: %s", e)
        return 2

    data_dir = Path(str(welcome.get("dataDir") or os.environ.get("PHOTOCRAFT_PLUGIN_DATA_DIR", "")))
    runtime, cache = data_dir / "runtime", data_dir / "cache" / "uv"
    lock = runtime_project(PLUGIN_DIR) / "uv.lock"
    digest = lock_digest(lock)
    if not is_ready(runtime, digest):
        if not provision(session, PLUGIN_DIR, runtime, cache):
            return 0
        (runtime / READY_MARK).write_text(digest, encoding="utf-8")

    import site

    site.addsitedir(str(site_packages(runtime)))
    from photocraft_host import main as plugin

    stream = session.hand_over()
    return plugin.main(
        streams=(stream, writer),
        welcome=plugin.Welcome.from_result(welcome),
        first_id=session.next_id,
    )


if __name__ == "__main__":
    code = main()
    # As photocraft_host.main: leave without Python's teardown, which would crash Qt.
    logging.shutdown()
    sys.stderr.flush()
    os._exit(code)
