"""Qt menus as PhotoCraft menus and pop-ups.

- A menu set on a tool button (``QToolButton.setMenu``) becomes the button's ``menu`` prop:
  PhotoCraft opens it on click and sends the chosen entry as a ``menu`` event, which triggers the
  action.
- A menu upstream opens itself with ``QMenu.exec()`` (a context menu, a button's drop-down) can't
  block the plug-in while PhotoCraft shows it. ``exec`` is replaced: called while the mirror is
  handling the user's input on a widget, it opens the menu as a ``popup`` anchored to that
  widget and returns at once. Choosing an entry triggers its action, as Qt would after ``exec``
  returned. Upstream's ``exec`` calls don't use the returned action.

Entry ids are paths of action indices (``"3"``, ``"2/1"`` for an entry of a submenu).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QWidgetAction

from .adapters.base import Input, plain_label
from .tree import Node, node

if TYPE_CHECKING:
    from .mirror import Mirror

log = logging.getLogger(__name__)

#: The mirror and node whose input is being handled, so ``QMenu.exec`` knows where it opens.
_anchor: tuple[Mirror, str] | None = None
_installed = False


@contextlib.contextmanager
def anchored(mirror: Mirror, node_id: str) -> Generator[None, None, None]:
    """While handling input on ``node_id``, menus opened with ``exec`` pop up there."""
    global _anchor
    previous, _anchor = _anchor, (mirror, node_id)
    try:
        yield
    finally:
        _anchor = previous


def _exec(self: QMenu, *args: Any, **kwargs: Any) -> QAction | None:
    """``QMenu.exec`` for the mirror: show the menu in PhotoCraft and return without blocking."""
    if _anchor is None:
        log.warning("a menu opened outside any user input (%s); it isn't shown", self.title())
        return None
    mirror, node_id = _anchor
    mirror.open_menu(node_id, self)
    return None


def install():
    """Replace ``QMenu.exec`` and ``QMenu.popup`` (once per process)."""
    global _installed
    if _installed:
        return
    QMenu.exec = _exec  # type: ignore[method-assign,assignment]
    QMenu.popup = _exec  # type: ignore[method-assign,assignment]
    _installed = True


def _actions(menu: QMenu) -> list[QAction]:
    return [a for a in menu.actions() if a.isVisible()]


def items_of(menu: QMenu, ctx: Any, prefix: str = "") -> list[dict[str, Any]]:
    """A menu's visible actions as ``menu`` prop entries."""
    entries: list[dict[str, Any]] = []
    for index, action in enumerate(_actions(menu)):
        if action.isSeparator():
            entries.append({"kind": "separator"})
            continue
        entry: dict[str, Any] = {"id": f"{prefix}{index}", "text": plain_label(action.text())}
        if (icon := ctx.icon(action.icon())) is not None and action.isIconVisibleInMenu():
            entry["icon"] = icon
        if action.isCheckable():
            entry["checkable"] = True
            entry["checked"] = action.isChecked()
        if not action.isEnabled():
            entry["enabled"] = False
        if (sub := action.menu()) is not None:
            entry["items"] = items_of(sub, ctx, f"{prefix}{index}/")
        entries.append(entry)
    return entries


def action_at(menu: QMenu, entry_id: str) -> QAction | None:
    """The action an entry id names."""
    current: QMenu | None = menu
    action: QAction | None = None
    for part in str(entry_id).split("/"):
        if current is None:
            return None
        try:
            action = _actions(current)[int(part)]
        except (ValueError, IndexError):
            return None
        current = action.menu()
    return action


def trigger(menu: QMenu, entry_id: Any) -> bool:
    """Trigger the action ``entry_id`` names, as choosing it in Qt does."""
    action = action_at(menu, str(entry_id))
    if action is None or not action.isEnabled() or action.menu() is not None:
        return False
    menu.triggered.emit(action)
    action.trigger()
    return True


def popup_node(mirror: Mirror, anchor: str, menu: QMenu, close: Callable[[], None]) -> Node:
    """A menu opened with ``exec`` as a pop-up of entries under ``anchor``."""
    popup_id = f"{anchor}.menu"

    def closed(event: Input):
        if event.kind == "change" and event.value is False:
            close()

    mirror.handle(popup_id, closed)
    return node(
        popup_id,
        "popup",
        {"anchor": anchor, "open": True},
        _entries(mirror, menu, popup_id, menu, close),
    )


def _entries(
    mirror: Mirror, menu: QMenu, base: str, top: QMenu, close: Callable[[], None], prefix: str = ""
) -> list[Node]:
    out: list[Node] = []
    for index, action in enumerate(_actions(menu)):
        entry_id = f"{prefix}{index}"
        nid = f"{base}.{entry_id}"
        if action.isSeparator():
            out.append(node(nid, "separator"))
            continue
        if isinstance(action, QWidgetAction) and (widget := action.defaultWidget()) is not None:
            out.append(mirror.build(widget))
            continue
        if (sub := action.menu()) is not None:
            title = node(f"{nid}.title", "label", {"text": plain_label(action.text())})
            out.append(
                node(
                    nid,
                    "column",
                    {},
                    [title, *_entries(mirror, sub, base, top, close, f"{entry_id}/")],
                )
            )
            continue

        def chosen(event: Input, entry_id: str = entry_id):
            if event.kind in ("click", "change"):
                close()
                trigger(top, entry_id)

        mirror.handle(nid, chosen)
        props: dict[str, Any] = {
            "text": plain_label(action.text()),
            "enabled": None if action.isEnabled() else False,
        }
        if action.isCheckable():
            out.append(node(nid, "checkbox", {**props, "checked": action.isChecked()}))
        else:
            out.append(
                node(
                    nid,
                    "toolButton",
                    {
                        **props,
                        "icon": mirror.icon(action.icon())
                        if action.isIconVisibleInMenu()
                        else None,
                        "tooltip": action.toolTip() if menu.toolTipsVisible() else None,
                    },
                )
            )
    return out
