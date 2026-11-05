"""Tests for the transport and the entry point: framing, calls with deadlines, replies in any
order, events and host requests on the Qt thread, and the plug-in process started headless
against a host speaking the protocol over its standard input and output."""

from __future__ import annotations

import io
import os
import re
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from photocraft_host import main as plugin_main
from photocraft_host import transport
from photocraft_host.transport import (
    Frame,
    ProtocolError,
    RemoteError,
    Transport,
    encode,
    read_frame,
)

from .mock_host import HOST_VERSION, MockHost


def wait_for(app: QApplication, condition: Callable[[], bool], timeout: float = 5.0):
    """Process Qt events until ``condition`` holds."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        app.processEvents()
        time.sleep(0.005)


def answer_to(app: QApplication, host: MockHost, request_id: int, timeout: float = 5.0) -> Frame:
    """The plug-in's answer to the host's request, processing Qt events (where the plug-in
    answers) until it arrives."""
    deadline = time.monotonic() + timeout
    while (frame := host.reply(request_id)) is None:
        if time.monotonic() > deadline:
            raise TimeoutError(f"no answer to request {request_id}")
        app.processEvents()
        time.sleep(0.005)
    return frame


@pytest.fixture
def host():
    mock = MockHost()
    yield mock
    mock.close()


@pytest.fixture
def connected(host: MockHost):
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    yield host, link
    host.close()


# -- framing


def test_frames_round_trip():
    header = {"type": "request", "id": 3, "method": "pixels.write", "params": {"doc": "1"}}
    data = encode(header, b"\x01\x02\x03") + encode({"type": "event", "topic": "t", "data": None})
    stream = io.BytesIO(data)
    assert read_frame(stream) == Frame(header, b"\x01\x02\x03")
    assert read_frame(stream) == Frame({"type": "event", "topic": "t", "data": None}, b"")
    assert read_frame(stream) is None, "a clean end between frames"


@pytest.mark.parametrize(
    "data",
    [
        b"XXXX" + struct.pack("<IQ", 2, 0) + b"{}",
        b"PCPP" + struct.pack("<IQ", transport.MAX_HEADER + 1, 0),
        b"PCPP" + struct.pack("<IQ", 2, transport.MAX_PAYLOAD + 1),
        b"PCPP" + struct.pack("<IQ", 10, 0) + b"{}",
        b"PCPP" + struct.pack("<IQ", 3, 0) + b"{x}",
        b"PCPP" + struct.pack("<IQ", 2, 0) + b"[]",
        b"PCPP" + struct.pack("<IQ", 15, 0) + b'{"type":"what"}',
        b"PCP",
    ],
)
def test_malformed_frames_are_errors(data: bytes):
    with pytest.raises(ProtocolError):
        read_frame(io.BytesIO(data))


def test_oversized_frames_are_not_sent():
    with pytest.raises(ProtocolError):
        encode({"type": "event", "topic": "t", "data": "x" * (transport.MAX_HEADER + 1)})


# -- calls


def test_hello_returns_the_welcome(connected):
    _, link = connected
    welcome = plugin_main.connect(link, "test-nonce", "org.example.p", "1.0")
    assert welcome.host_version == HOST_VERSION
    assert (welcome.protocol, welcome.locale, welcome.dark_theme) == (1, "en", True)


def test_a_wrong_nonce_is_refused(connected):
    _, link = connected
    with pytest.raises(RemoteError) as refused:
        plugin_main.connect(link, "forged", "org.example.p", "1.0")
    assert refused.value.code == "invalid"


def test_calls_carry_payloads_both_ways(connected):
    host, link = connected
    doc = host.add_document(width=2, height=1)
    uid = doc.layers[0].uid
    link.call(
        "pixels.write",
        {
            "doc": doc.id,
            "uid": uid,
            "rect": {"x": 0, "y": 0, "width": 2, "height": 1},
            "format": "bgra8",
        },
        b"\x01\x02\x03\x04\x05\x06\x07\x08",
    )
    _, px = link.call(
        "pixels.read",
        {
            "doc": doc.id,
            "source": {"kind": "layer", "uid": uid},
            "rect": {"x": 0, "y": 0, "width": 2, "height": 1},
            "format": "rgba8",
        },
    )
    assert px == b"\x03\x02\x01\x04\x07\x06\x05\x08"
    with pytest.raises(RemoteError) as missing:
        link.call("doc.info", {"doc": "99"})
    assert missing.value.code == "notFound"


def test_a_call_without_an_answer_times_out(connected):
    host, link = connected
    host.answers["slow.method"] = lambda _p, _b: time.sleep(0.5)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        link.call("slow.method", timeout=0.1)
    assert time.monotonic() - started < 0.4
    # The late answer is dropped, and the connection keeps working.
    time.sleep(0.5)
    assert link.call("doc.list") == ([], b"")


def test_replies_may_arrive_in_any_order():
    to_plugin_r, to_plugin_w = os.pipe()
    to_host_r, to_host_w = os.pipe()
    host_in, host_out = (
        os.fdopen(to_host_r, "rb", buffering=0),
        os.fdopen(to_plugin_w, "wb", buffering=0),
    )
    link = Transport(
        os.fdopen(to_plugin_r, "rb", buffering=0), os.fdopen(to_host_w, "wb", buffering=0)
    )
    link.start()

    def answer_backwards():
        first, second = read_frame(host_in), read_frame(host_in)
        assert first is not None and second is not None
        for frame in (second, first):
            host_out.write(
                encode({
                    "type": "response",
                    "id": frame.header["id"],
                    "result": frame.header["method"],
                })
            )

    host = threading.Thread(target=answer_backwards)
    host.start()
    results: dict[str, object] = {}
    callers = [
        threading.Thread(target=lambda m=m: results.__setitem__(m, link.call(m)[0]))
        for m in ("first", "second")
    ]
    for caller in callers:
        caller.start()
    for thread in [*callers, host]:
        thread.join(5)
    assert results == {"first": "first", "second": "second"}
    host_out.close()
    host_in.close()


def test_a_closed_connection_ends_waiting_calls(connected, qt_app: QApplication):
    host, link = connected
    reasons: list[str] = []
    link.closed.connect(reasons.append)
    host.answers["hang"] = lambda _p, _b: time.sleep(10)
    outcome: list[BaseException] = []

    def caller():
        try:
            link.call("hang", timeout=5)
        except BaseException as e:
            outcome.append(e)

    thread = threading.Thread(target=caller)
    thread.start()
    time.sleep(0.1)
    host.close()
    thread.join(3)
    assert outcome and isinstance(outcome[0], ConnectionError)
    wait_for(qt_app, lambda: bool(reasons))
    with pytest.raises(ConnectionError):
        link.call("doc.list")


# -- the host's requests and events


def test_events_and_host_requests_run_on_the_qt_thread(connected, qt_app: QApplication):
    host, link = connected
    seen: list[tuple[object, bool]] = []
    link.on(
        "pixels.changed",
        lambda data, _payload: seen.append((
            data,
            threading.current_thread() is threading.main_thread(),
        )),
    )
    host.send_event("pixels.changed", {"doc": "1", "revision": 4})
    wait_for(qt_app, lambda: bool(seen))
    assert seen == [({"doc": "1", "revision": 4}, True)]
    link.handle("ping", lambda _p, _b: {})
    request = host.request_async("ping")
    assert answer_to(qt_app, host, request).header == {
        "type": "response",
        "id": request,
        "result": {},
    }
    unknown = host.request_async("nope")
    assert answer_to(qt_app, host, unknown).header["error"]["code"] == "unsupported"


def test_a_failing_handler_answers_internal(connected, qt_app: QApplication):
    host, link = connected

    def broken(_p, _b):
        raise RuntimeError("boom")

    link.handle("broken", broken)
    link.on("t", lambda _d, _p: (_ for _ in ()).throw(ValueError("ignored")))
    host.send_event("t", None)
    request = host.request_async("broken")
    assert answer_to(qt_app, host, request).header["error"] == {
        "code": "internal",
        "message": "boom",
    }


def test_shutdown_answers_then_quits(connected, qt_app: QApplication):
    host, link = connected

    class App:
        quit_called = False

        def quit(self):
            App.quit_called = True

    saved: list[bool] = []
    plugin_main.serve_session(link, App(), on_shutdown=lambda: saved.append(True))
    request = host.request_async("shutdown")
    wait_for(qt_app, lambda: App.quit_called)
    assert saved == [True]
    assert host.wait_reply(request).header["type"] == "response"


def test_the_identity_comes_from_the_manifest(tmp_path: Path):
    (tmp_path / "photocraft-plugin.toml").write_text(
        'id = "org.example.p"\nversion = "2.1.0"\n', encoding="utf-8"
    )
    assert plugin_main.identity(tmp_path) == ("org.example.p", "2.1.0")
    assert plugin_main.identity(tmp_path / "missing") == (
        plugin_main.DEFAULT_ID,
        plugin_main.DEFAULT_VERSION,
    )


# -- the process, headless


def _serve_until(proc: subprocess.Popen, request_id: int, seen: list[tuple[str, dict]]) -> Frame:
    """Answer the plug-in's requests as a minimal PhotoCraft (no documents open) until the
    answer to our own request ``request_id`` arrives; record what the plug-in asked for."""
    assert proc.stdin is not None and proc.stdout is not None
    while True:
        frame = read_frame(proc.stdout)
        assert frame is not None, "the plug-in closed the connection"
        header = frame.header
        if header["type"] == "request":
            seen.append((header["method"], header.get("params") or {}))
            result: object = [] if header["method"] == "doc.list" else {}
            proc.stdin.write(encode({"type": "response", "id": header["id"], "result": result}))
            proc.stdin.flush()
        elif header.get("id") == request_id:
            return frame


def test_the_plugin_process_starts_headless_and_shuts_down(repo_root: Path, tmp_path: Path):
    """REQ-13.2: the plug-in runs with no display, against a host on its stdin/stdout; it
    starts upstream, registers its actions and docker panel, and stops on ``shutdown``."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "settings.json").write_text('{"auto_update": false}')  # no network in tests
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PHOTOCRAFT_PLUGIN_NONCE": "n0nce",
        "PHOTOCRAFT_PLUGIN_DIR": str(repo_root),
    }
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    log_path = tmp_path / "plugin.log"
    # The log goes to a file: upstream logs enough to fill a pipe nobody reads meanwhile.
    log_file = log_path.open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "photocraft_host.main"],
        cwd=repo_root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
    )
    assert proc.stdin is not None and proc.stdout is not None
    seen: list[tuple[str, dict]] = []
    try:
        hello = read_frame(proc.stdout)
        assert hello is not None
        assert hello.header["method"] == "hello"
        assert hello.header["params"]["nonce"] == "n0nce"
        assert hello.header["params"]["protocol"] == 1
        welcome = {
            "hostVersion": "test",
            "protocol": 1,
            "locale": "en",
            "dataDir": str(data_dir),
            "logDir": "",
            "theme": {"dark": False},
        }
        proc.stdin.write(encode({"type": "response", "id": hello.header["id"], "result": welcome}))
        proc.stdin.write(encode({"type": "request", "id": 100, "method": "ping", "params": {}}))
        proc.stdin.flush()
        pong = _serve_until(proc, 100, seen)
        assert pong.header == {"type": "response", "id": 100, "result": {}}
        proc.stdin.write(encode({"type": "request", "id": 101, "method": "shutdown", "params": {}}))
        proc.stdin.flush()
        bye = _serve_until(proc, 101, seen)
        assert bye.header["id"] == 101
        assert proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
        log_file.close()
    stderr = log_path.read_text(errors="replace")
    assert "connected to PhotoCraft test" in stderr, stderr[-4000:]
    # Qt's TLS backend and fonts (spec plugin-tls-and-fonts-fix): without fonts, every text Qt
    # draws (widgets the mirror sends as images) comes out as empty boxes.
    qt_line = re.search(r"Qt: TLS (\S+), (\d+) font families", stderr)
    assert qt_line, stderr[-4000:]
    assert int(qt_line.group(2)) > 0, "Qt found no fonts"
    if sys.platform == "win32":
        assert qt_line.group(1) == "schannel"
    actions = {p["id"]: p for m, p in seen if m == "action.register"}
    assert len(actions) == 15, sorted(actions)
    assert actions["ai_diffusion_generate"]["label"] == "Generate image"
    assert not any("shortcut" in a for a in actions.values()), "no default shortcuts"
    panels = [p for m, p in seen if m == "panel.register"]
    assert [p["panelId"] for p in panels] == ["imageDiffusion"]
    assert (data_dir / "settings.json").exists() and (data_dir / "logs").is_dir()
