"""The Qt mirror: upstream's real Qt widgets, drawn natively by PhotoCraft (design D7).

:class:`Mirror` sends a widget tree to PhotoCraft as a panel and keeps it current; the adapters
in :mod:`.adapters` say how each Qt class looks as a protocol node and how input from PhotoCraft
is played back into it.
"""

from typing import Any

from . import dialogs, menus, tracker
from .adapters.text import install_completer_hook
from .mirror import Mirror
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


__all__ = ["Mirror", "diff", "install"]
