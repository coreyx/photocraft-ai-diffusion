"""Noticing when a mirrored widget changes (design D7).

Three sources mark a mirror dirty:
- an event filter on every mirrored widget, for show/hide, enabled, font, tooltip, layout and
  child changes;
- each adapter's value signals (``textChanged``, ``valueChanged``, ...);
- hooks on the setters that change what a widget shows without any signal or event
  (``QLabel.setText``, ``QAbstractButton.setIcon``, ``QProgressBar.setFormat``, ...). Upstream
  calls these from Python, so wrapping the PyQt methods catches every call it makes.

A dirty mirror flushes once, 16 ms later, into a single ``panel.patch``.
"""

from __future__ import annotations

import functools
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import (
    QAbstractButton,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolButton,
)

if TYPE_CHECKING:
    from .mirror import Mirror

#: The Qt property that holds a mirrored object's node id.
ID_PROPERTY = "_photocraft_mirror_id"

#: Events after which a widget may look different.
EVENTS = {
    QEvent.Type.Show,
    QEvent.Type.Hide,
    QEvent.Type.ShowToParent,
    QEvent.Type.HideToParent,
    QEvent.Type.EnabledChange,
    QEvent.Type.FontChange,
    QEvent.Type.ToolTipChange,
    QEvent.Type.LayoutRequest,
    QEvent.Type.ChildAdded,
    QEvent.Type.ChildRemoved,
    QEvent.Type.ParentChange,
}

#: Setters that change what a widget shows without a signal or an event.
SETTERS: dict[type, tuple[str, ...]] = {
    QLabel: ("setText", "setPixmap", "clear", "setNum", "setTextFormat", "setWordWrap"),
    QAbstractButton: ("setText", "setIcon", "setCheckable"),
    QPushButton: ("setDefault",),
    QToolButton: ("setToolButtonStyle",),
    QGroupBox: ("setTitle", "setCheckable"),
    QProgressBar: ("setFormat", "setTextVisible", "setRange", "setMinimum", "setMaximum"),
    QTabWidget: ("setTabText", "setTabEnabled", "setTabIcon", "addTab", "insertTab", "removeTab"),
    QLineEdit: ("setPlaceholderText", "setEchoMode", "setReadOnly"),
    QSpinBox: ("setRange", "setMinimum", "setMaximum", "setSingleStep", "setPrefix", "setSuffix"),
    QDoubleSpinBox: (
        "setRange",
        "setMinimum",
        "setMaximum",
        "setSingleStep",
        "setPrefix",
        "setSuffix",
        "setDecimals",
    ),
    QSlider: ("setSingleStep", "setOrientation"),
    QSplitter: ("setSizes", "setOrientation"),
    QScrollArea: ("setWidget",),
    QFrame: ("setFrameShape",),
}

_mirrors: weakref.WeakSet[Mirror] = weakref.WeakSet()
_hooked = False


def _notify(obj: Any):
    if isinstance(obj, QObject) and obj.property(ID_PROPERTY) is not None:
        for mirror in list(_mirrors):
            mirror.mark_dirty()


def _hook(cls: type, name: str):
    original: Callable[..., Any] = getattr(cls, name)
    if getattr(original, "_photocraft_hook", False):
        return

    @functools.wraps(original)
    def setter(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        _notify(self)
        return result

    setter._photocraft_hook = True  # type: ignore[attr-defined]
    setattr(cls, name, setter)


def install_hooks():
    """Wrap the setters in ``SETTERS`` (once per process)."""
    global _hooked
    if _hooked:
        return
    for cls, names in SETTERS.items():
        for name in names:
            _hook(cls, name)
    _hooked = True


def register(mirror: Mirror):
    install_hooks()
    _mirrors.add(mirror)


def unregister(mirror: Mirror):
    _mirrors.discard(mirror)


class ChangeFilter(QObject):
    """The event filter installed on mirrored widgets: marks its mirror dirty, never consumes."""

    def __init__(self, changed: Callable[[], None]):
        super().__init__()
        self._changed = changed

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is not None and a1.type() in EVENTS:
            self._changed()
        return False
