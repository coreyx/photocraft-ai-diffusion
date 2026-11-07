"""The plug-in process survives a network reply that finishes after shutdown has closed upstream's
event loop, and an exception escaping a Qt slot (spec ``ci-first-push-fix``).

Both run ``late_reply.py`` in a process of its own: before the fix, the process aborted, which
would take the test run with it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HERE / "late_reply.py"), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.timeout(90)
def test_a_reply_finishing_after_the_event_loop_closed_doesnt_abort():
    """With Python's default ``sys.excepthook``, as upstream's code runs: no exception at all."""
    run = _run()
    assert run.returncode == 0, f"exit {run.returncode:#x}: {run.stderr[-2000:]}"
    assert "finished" in run.stdout, "the reply never finished"
    assert "InvalidStateError" not in run.stderr
    assert "Event loop is closed" not in run.stderr


@pytest.mark.timeout(90)
def test_an_exception_escaping_a_qt_slot_is_logged_not_fatal():
    run = _run("--raise-in-slot")
    assert run.returncode == 0, f"exit {run.returncode:#x}: {run.stderr[-2000:]}"
    assert "survived" in run.stdout
    assert "unhandled exception in the plug-in" in run.stderr
    assert "ValueError: raised from a Qt slot" in run.stderr
