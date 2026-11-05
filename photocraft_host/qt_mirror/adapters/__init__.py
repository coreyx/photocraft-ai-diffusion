"""One adapter per Qt widget class the mirror draws natively (design D7). A widget is mapped by
the most specific class in its hierarchy that has an adapter; a plain ``QWidget`` is a container
for its layout."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from .base import Adapter, Context, Input
from .buttons import CheckBoxAdapter, PushButtonAdapter, RadioButtonAdapter, ToolButtonAdapter
from .containers import (
    GroupBoxAdapter,
    ScrollAreaAdapter,
    SplitterAdapter,
    StackAdapter,
    TabsAdapter,
)
from .display import FrameAdapter, LabelAdapter, ProgressAdapter
from .inputs import (
    ComboAdapter,
    DoubleParseSpinBoxAdapter,
    DoubleSpinBoxAdapter,
    LineEditAdapter,
    SliderAdapter,
    SliderSpinAdapter,
    SpinBoxAdapter,
)

ADAPTERS: list[Adapter] = [
    LabelAdapter(),
    PushButtonAdapter(),
    ToolButtonAdapter(),
    CheckBoxAdapter(),
    RadioButtonAdapter(),
    ComboAdapter(),
    SliderAdapter(),
    SpinBoxAdapter(),
    DoubleSpinBoxAdapter(),
    LineEditAdapter(),
    ProgressAdapter(),
    ScrollAreaAdapter(),
    StackAdapter(),
    TabsAdapter(),
    SplitterAdapter(),
    GroupBoxAdapter(),
    FrameAdapter(),
    DoubleParseSpinBoxAdapter(),
    SliderSpinAdapter(),
]

_by_class: dict[type, Adapter] = {a.qt_class: a for a in ADAPTERS}


def adapter_for(widget: QWidget) -> Adapter | None:
    """The adapter for the most specific class of ``widget`` that has one."""
    for cls in type(widget).__mro__:
        if (adapter := _by_class.get(cls)) is not None:
            return adapter
    return None


__all__ = ["ADAPTERS", "Adapter", "Context", "Input", "adapter_for"]
