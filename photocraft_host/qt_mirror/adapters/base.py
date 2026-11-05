"""What every adapter has: how a Qt widget class becomes a protocol node, and how input from
PhotoCraft is played back into it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import QLayout, QWidget

if TYPE_CHECKING:
    from ..tree import Node


@dataclass
class Input:
    """One ``panel.input`` event for a widget: ``kind`` is click, change, key, select, menu,
    context, drag, cursor, pointer or focus."""

    kind: str
    value: Any = None
    modifiers: dict[str, bool] = field(default_factory=dict)


class Context(Protocol):
    """What adapters may ask of the mirror."""

    def build(self, widget: QWidget, shown: bool = False) -> Node: ...

    def handle(self, node_id: str, handler: Callable[[Input], None]) -> None: ...

    def mark_dirty(self) -> None: ...

    def node_id(self, obj: QObject) -> str: ...

    def layout_node(self, layout: QLayout) -> Node: ...

    def icon(self, icon: QIcon | None, size: int | None = None) -> str | None: ...

    def image(self, picture: QPixmap | QImage) -> str: ...

    def call(self, method: str, params: dict[str, Any]) -> Any: ...


class Adapter:
    """Maps one Qt widget class. Subclasses set ``qt_class`` and ``kind`` and override what
    differs; the defaults describe a widget with no props of its own whose content is its
    layout."""

    qt_class: ClassVar[type[QWidget]]
    kind: ClassVar[str] = "column"
    #: Signals (by name) that change what the node shows; each marks the widget dirty.
    signals: ClassVar[tuple[str, ...]] = ()
    #: Whether a subclass that paints itself is sent as an image instead (``raster.py``).
    raster_allowed: ClassVar[bool] = True

    def kind_of(self, widget: QWidget) -> str:
        return self.kind

    def connect(self, widget: QWidget, changed: Callable[[], None]) -> None:
        """Call ``changed`` whenever what the node shows may have changed. By default, on each
        of ``signals``; adapters whose content lives elsewhere (a model) add to this."""
        for name in self.signals:
            signal = getattr(widget, name, None)
            if signal is not None:
                signal.connect(changed)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        return {}

    def children(self, widget: QWidget, ctx: Context) -> list[Node]:
        layout = widget.layout()
        return [ctx.layout_node(layout)] if layout is not None else []

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        """Play the user's input back through Qt, so the widget's own signals fire."""


def overrides(widget: QWidget, base: type, *names: str) -> bool:
    """Whether a Python class between ``widget``'s own class and ``base`` defines any of
    ``names``. (PyQt hands out a new method object on every access, so methods can't be
    compared by identity.)"""
    for cls in type(widget).__mro__:
        if cls is base:
            return False
        if not cls.__module__.startswith("PyQt6") and any(name in cls.__dict__ for name in names):
            return True
    return False


def plain_label(text: str) -> str:
    """Qt button and tab text without its ``&`` mnemonic markers (``&&`` is a literal ``&``)."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def might_be_rich(text: str) -> bool:
    """Qt's guess whether ``text`` is HTML (``Qt::mightBeRichText``)."""
    return bool(Qt.mightBeRichText(text))  # pyright: ignore[reportAttributeAccessIssue] (missing from the stubs)


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
