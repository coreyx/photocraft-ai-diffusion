"""The Qt mirror: upstream's real Qt widgets, drawn natively by PhotoCraft (design D7).

:class:`Mirror` sends a widget tree to PhotoCraft as a panel and keeps it current; the adapters
in :mod:`.adapters` say how each Qt class looks as a protocol node and how input from PhotoCraft
is played back into it.
"""

from .mirror import Mirror
from .tree import diff

__all__ = ["Mirror", "diff"]
