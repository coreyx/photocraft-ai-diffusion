"""Frames of PhotoCraft's process plug-in protocol, with the standard library only.

A frame is ``"PCPP" | header length (u32 LE) | payload length (u64 LE) | header JSON | payload``
(PhotoCraft's ``docs/process-plugins.md``). This module needs nothing but Python, so the
bootstrap can speak the protocol before the runtime (PyQt6) is installed; ``transport`` builds
the plug-in's connection on it.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import sys
from typing import IO, Any, NamedTuple

MAGIC = b"PCPP"
_PREFIX = struct.Struct("<4sIQ")
PREFIX_LEN = _PREFIX.size
#: Largest header and payload accepted, as PhotoCraft's defaults.
MAX_HEADER = 1 << 20
MAX_PAYLOAD = 512 << 20


class ProtocolError(Exception):
    """The other side broke the framing or sent something that isn't a protocol message."""


class Frame(NamedTuple):
    """One decoded frame: its JSON header and its binary payload."""

    header: dict[str, Any]
    payload: bytes


def encode(header: dict[str, Any], payload: bytes = b"") -> bytes:
    """The bytes of a frame holding ``header`` and ``payload``."""
    head = json.dumps(header, separators=(",", ":")).encode("utf-8")
    if len(head) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ProtocolError(
            f"frame too large: header {len(head)} bytes, payload {len(payload)} bytes"
        )
    return _PREFIX.pack(MAGIC, len(head), len(payload)) + head + payload


def _read_exactly(stream: IO[bytes], n: int) -> bytes | None:
    """``n`` bytes from ``stream``, or ``None`` when it ends before the first byte."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if remaining == n:
                return None
            raise ProtocolError(f"stream ended inside a frame ({n - remaining} of {n} bytes)")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: IO[bytes]) -> Frame | None:
    """The next frame from ``stream``, or ``None`` at the end of the stream between frames.

    Lengths are checked before anything is read into memory; any malformed input is a
    :class:`ProtocolError`.
    """
    prefix = _read_exactly(stream, PREFIX_LEN)
    if prefix is None:
        return None
    magic, header_len, payload_len = _PREFIX.unpack(prefix)
    if magic != MAGIC:
        raise ProtocolError(f"bad frame magic {magic!r}")
    if header_len > MAX_HEADER or payload_len > MAX_PAYLOAD:
        raise ProtocolError(
            f"frame too large: header {header_len} bytes, payload {payload_len} bytes"
        )
    head = _read_exactly(stream, header_len) if header_len else b""
    payload = _read_exactly(stream, payload_len) if payload_len else b""
    if head is None or payload is None:
        raise ProtocolError("stream ended inside a frame")
    try:
        header = json.loads(head.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError(f"frame header is not JSON: {e}") from e
    if not isinstance(header, dict) or header.get("type") not in (
        "request",
        "response",
        "error",
        "event",
    ):
        raise ProtocolError("frame header is not a protocol message")
    return Frame(header, payload)


def stdio_streams() -> tuple[IO[bytes], IO[bytes]]:
    """The plug-in's frame streams, set up so nothing else can write into the frame channel.

    Frames go out on the original standard output. Descriptor 1 is then pointed at standard
    error, so ``print`` and any library writing to stdout end up in the plug-in's log instead of
    corrupting the frames.
    """
    frames_out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    frames_in = os.fdopen(os.dup(0), "rb", buffering=0)
    return frames_in, frames_out


def leave(code: int):
    """End the plug-in process at once with ``code``, skipping Python's teardown.

    The teardown would destroy upstream's widgets after the ``QApplication``, which crashes Qt;
    everything that must happen on exit has happened by the time this is called. Exit handlers
    are skipped too, so a coverage measurement running in this process (the tests measure the
    plug-in's own processes) is saved here, or it would be lost.
    """
    logging.shutdown()
    coverage = sys.modules.get("coverage")
    measurement = coverage.Coverage.current() if coverage else None
    if measurement is not None:
        measurement.stop()
        measurement.save()
    for stream in (sys.stdout, sys.stderr):
        stream.flush()
    os._exit(code)
