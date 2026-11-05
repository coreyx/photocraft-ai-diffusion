"""A stand-in for Krita's ``krita`` Python module, backed by PhotoCraft.

Upstream Krita AI Diffusion is written against Krita's scripting API. This package provides the
part of that API it uses (the inventory's H-01 to H-72, and upstream's own test mock as the
reference for its surface), implemented with PhotoCraft's process plug-in protocol. The plug-in
entry point installs it as ``krita`` (``photocraft_host.main.install_krita_shim``) and connects
it once PhotoCraft has welcomed the plug-in (:func:`attach`).
"""

from ._app import (
    Action,
    Canvas,
    DockWidget,
    DockWidgetFactory,
    DockWidgetFactoryBase,
    DoubleParseSpinBox,
    DoubleSliderSpinBox,
    Extension,
    Krita,
    Notifier,
    View,
    Window,
    attach,
)
from ._document import Document, Node, Selection, Shape, VectorLayer

__all__ = [
    "Action",
    "Canvas",
    "DockWidget",
    "DockWidgetFactory",
    "DockWidgetFactoryBase",
    "Document",
    "DoubleParseSpinBox",
    "DoubleSliderSpinBox",
    "Extension",
    "Krita",
    "Node",
    "Notifier",
    "Selection",
    "Shape",
    "VectorLayer",
    "View",
    "Window",
    "attach",
]
