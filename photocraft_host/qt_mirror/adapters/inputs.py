"""Value inputs: drop-downs, sliders, number boxes and text fields. A change from PhotoCraft is
set through the widget's own API and followed by the signal Qt emits for a user edit
(``activated``, ``sliderReleased``, ``editingFinished``, ``textEdited``), so upstream's handlers
for user input run."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSlider,
    QSpinBox,
    QWidget,
)

from ...krita import DoubleParseSpinBox, DoubleSliderSpinBox
from .base import Adapter, Context, Input, number


class ComboAdapter(Adapter):
    """``QComboBox``: items by index, with separators."""

    qt_class = QComboBox
    kind = "combo"
    signals = ("currentIndexChanged",)

    def connect(self, widget: QWidget, changed: Callable[[], None]) -> None:
        assert isinstance(widget, QComboBox)
        super().connect(widget, changed)
        model = widget.model()
        if model is not None:
            for signal in (
                model.rowsInserted,
                model.rowsRemoved,
                model.dataChanged,
                model.modelReset,
            ):
                signal.connect(changed)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QComboBox)
        items: list[dict[str, Any]] = []
        for i in range(widget.count()):
            role = Qt.ItemDataRole.AccessibleDescriptionRole
            if widget.itemData(i, role) == "separator":
                items.append({"kind": "separator"})
                continue
            item: dict[str, Any] = {"id": str(i), "text": widget.itemText(i)}
            if (icon := ctx.icon(widget.itemIcon(i))) is not None:
                item["icon"] = icon
            items.append(item)
        index = widget.currentIndex()
        return {"items": items, "value": str(index) if index >= 0 else None}

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QComboBox)
        if event.kind != "change":
            return
        try:
            index = int(event.value)
        except (TypeError, ValueError):
            return
        if not 0 <= index < widget.count():
            return
        widget.setCurrentIndex(index)
        widget.activated.emit(index)
        widget.textActivated.emit(widget.itemText(index))


class SliderAdapter(Adapter):
    """``QSlider``: replayed as a press, a move and a release."""

    qt_class = QSlider
    kind = "slider"
    signals = ("valueChanged", "rangeChanged")

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QSlider)
        return {
            "min": widget.minimum(),
            "max": widget.maximum(),
            "step": widget.singleStep(),
            "value": widget.value(),
            "orientation": "vertical" if widget.orientation() == Qt.Orientation.Vertical else None,
        }

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QSlider)
        if event.kind != "change":
            return
        widget.setSliderDown(True)
        widget.setSliderPosition(round(number(event.value, widget.value())))
        widget.setSliderDown(False)


def _spin_props(
    widget: QAbstractSpinBox, value: float, lo: float, hi: float, step: float
) -> dict[str, Any]:
    props: dict[str, Any] = {"min": lo, "max": hi, "step": step, "value": value}
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        props["prefix"] = widget.prefix() or None
        props["suffix"] = widget.suffix() or None
    if isinstance(widget, QDoubleSpinBox):
        props["decimals"] = widget.decimals()
    return props


class SpinBoxAdapter(Adapter):
    """``QSpinBox``: whole numbers."""

    qt_class = QSpinBox
    kind = "spin"
    signals = ("valueChanged",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QSpinBox)
        return _spin_props(
            widget, widget.value(), widget.minimum(), widget.maximum(), widget.singleStep()
        )

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QSpinBox)
        if event.kind == "change":
            widget.setValue(round(number(event.value, widget.value())))
            widget.editingFinished.emit()


class DoubleSpinBoxAdapter(Adapter):
    """``QDoubleSpinBox``: numbers with decimals."""

    qt_class = QDoubleSpinBox
    kind = "spin"
    signals = ("valueChanged",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QDoubleSpinBox)
        return _spin_props(
            widget, widget.value(), widget.minimum(), widget.maximum(), widget.singleStep()
        )

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QDoubleSpinBox)
        if event.kind == "change":
            widget.setValue(number(event.value, widget.value()))
            widget.editingFinished.emit()


class LineEditAdapter(Adapter):
    """``QLineEdit``: text, placeholder, password echo; Enter is ``returnPressed``."""

    qt_class = QLineEdit
    kind = "lineEdit"
    signals = ("textChanged",)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, QLineEdit)
        password = widget.echoMode() in (
            QLineEdit.EchoMode.Password,
            QLineEdit.EchoMode.PasswordEchoOnEdit,
        )
        return {
            "text": widget.text(),
            "placeholder": widget.placeholderText() or None,
            "password": password or None,
            "readOnly": widget.isReadOnly() or None,
        }

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, QLineEdit)
        if widget.isReadOnly():
            return
        if event.kind == "change" and isinstance(event.value, str):
            if event.value != widget.text():
                widget.setText(event.value)
                widget.textEdited.emit(event.value)
        elif event.kind == "key" and event.value == "Enter":
            widget.returnPressed.emit()
            widget.editingFinished.emit()
        elif event.kind == "focus" and event.value is False:
            widget.editingFinished.emit()


class DoubleParseSpinBoxAdapter(Adapter):
    """The ``krita`` stand-in's ``DoubleParseSpinBox``: a number box (its inner
    ``QDoubleSpinBox`` isn't mirrored separately)."""

    qt_class = DoubleParseSpinBox
    kind = "spin"

    def connect(self, widget: QWidget, changed: Callable[[], None]) -> None:
        assert isinstance(widget, DoubleParseSpinBox)
        widget.widget().valueChanged.connect(changed)

    def props(self, widget: QWidget, ctx: Context) -> dict[str, Any]:
        assert isinstance(widget, DoubleParseSpinBox)
        spin = widget.widget()
        return _spin_props(spin, spin.value(), spin.minimum(), spin.maximum(), spin.singleStep())

    def children(self, widget: QWidget, ctx: Context):
        return []

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, DoubleParseSpinBox)
        if event.kind == "change":
            spin = widget.widget()
            spin.setValue(number(event.value, spin.value()))
            spin.editingFinished.emit()


class SliderSpinAdapter(DoubleParseSpinBoxAdapter):
    """The ``krita`` stand-in's ``DoubleSliderSpinBox`` (Krita's slider and number box in one).
    A change ends with ``draggingFinished``, as releasing Krita's slider does."""

    qt_class = DoubleSliderSpinBox
    kind = "sliderSpin"

    def apply(self, widget: QWidget, event: Input, ctx: Context) -> None:
        assert isinstance(widget, DoubleSliderSpinBox)
        if event.kind == "change":
            widget.setValue(number(event.value, widget.value()))
            widget.draggingFinished.emit()
