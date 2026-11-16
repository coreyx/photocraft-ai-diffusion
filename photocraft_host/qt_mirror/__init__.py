"""The Qt mirror: upstream's real Qt widgets, drawn natively by PhotoCraft (design D7).

:class:`Mirror` sends a widget tree to PhotoCraft as a panel and keeps it current; the adapters
in :mod:`.adapters` say how each Qt class looks as a protocol node and how input from PhotoCraft
is played back into it.
"""

from typing import Any

from PyQt6.QtGui import QCursor, QGuiApplication

from . import dialogs, menus, tracker
from .adapters.text import install_completer_hook
from .mirror import PARKED_CURSOR, Mirror
from .tree import diff


def install(transport: Any = None):
    """Install the hooks the mirror relies on, before upstream builds its widgets: setter hooks
    (:mod:`.tracker`), ``QMenu.exec`` (:mod:`.menus`) and the completer hook (which field a
    ``QCompleter`` serves is only learned when it is attached). With a ``transport``, Qt's
    dialogs are also routed to PhotoCraft (:mod:`.dialogs`)."""
    tracker.install_hooks()
    menus.install()
    install_completer_hook()
    if transport is not None:
        dialogs.install(transport)
    park_cursor()


def park_cursor():
    """Move Qt's cursor outside every window, where it stays until PhotoCraft reports the pointer
    over a hover-aware widget.

    The offscreen platform starts it at (10, 10), inside any widget at the top left of a window
    not laid out yet. Upstream's ``FactorWidget``, given the document's scale before the Upscale
    page was first laid out, took that for the pointer over it and showed the target size for
    good (``investigations/upscale-target-size-always-shown``, cause 1)."""
    if QGuiApplication.instance() is not None:
        QCursor.setPos(PARKED_CURSOR)


__all__ = ["Mirror", "diff", "install"]
