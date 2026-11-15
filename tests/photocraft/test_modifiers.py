"""PhotoCraft's modifiers as Qt's (``qt_mirror.adapters.text.qt_modifiers``; spec
``macos-modifier-tests-and-message-box-titles``).

PhotoCraft reports the Command key as ``meta`` on a Mac, and Qt calls the Command key Control
there, so the two swap on macOS only."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from photocraft_host.qt_mirror.adapters.text import qt_modifiers

Mod = Qt.KeyboardModifier


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_ctrl_is_control_off_macos(platform: str):
    assert qt_modifiers({"ctrl": True}, platform) == Mod.ControlModifier
    assert qt_modifiers({"meta": True}, platform) == Mod.MetaModifier


def test_command_is_control_on_macos():
    assert qt_modifiers({"meta": True}, "darwin") == Mod.ControlModifier, "Command"
    assert qt_modifiers({"ctrl": True}, "darwin") == Mod.MetaModifier, "the Control key"


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_shift_and_alt_are_the_same_everywhere(platform: str):
    assert qt_modifiers({"shift": True, "alt": True}, platform) == (
        Mod.ShiftModifier | Mod.AltModifier
    )
    assert qt_modifiers({}, platform) == Mod.NoModifier
    assert qt_modifiers({"shift": False, "ctrl": False}, platform) == Mod.NoModifier
