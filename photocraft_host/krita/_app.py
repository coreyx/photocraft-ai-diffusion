"""The application side of the ``krita`` stand-in: the ``Krita`` singleton, its notifier,
actions, window, dock widgets, and the connection to PhotoCraft they share.

Upstream registers its extension and docker when ``ai_diffusion`` is imported, before the plug-in
is connected, so the singleton exists from the start and keeps what it is given; the connection
is attached once PhotoCraft has welcomed the plug-in (:func:`attach`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QDockWidget, QDoubleSpinBox, QHBoxLayout, QSlider, QWidget

from ._document import Document

#: The document events the shim keeps its caches with.
TOPICS = [
    "document.opened",
    "document.closed",
    "document.saved",
    "document.renamed",
    "document.activated",
    "layers.changed",
    "layer.activated",
]


@dataclass(frozen=True)
class HostInfo:
    """What PhotoCraft told the plug-in when it connected, for upstream code that needs it."""

    version: str
    #: PhotoCraft's UI language, as a BCP 47 tag (``"ja"``, ``"pt-BR"``).
    locale: str = "en"
    #: The plug-in's own data folder, separate from Krita AI Diffusion's.
    data_dir: Path | None = None


def photocraft_host() -> HostInfo | None:
    """PhotoCraft's details once the plug-in is connected, else ``None``.

    Upstream code checks for this function to tell it runs in PhotoCraft rather than Krita."""
    host = Krita.instance()._host
    return host.info if host is not None else None


class _Host:
    """The connection to PhotoCraft and the open documents as the shim sees them."""

    def __init__(self, transport: Any, info: HostInfo):
        self.transport = transport
        self.info = info
        self.host_version = info.version
        self.docs: dict[str, Document] = {}
        self.active: str | None = None

    def call(self, method: str, params: dict[str, Any], payload: bytes = b"") -> tuple[Any, bytes]:
        return self.transport.call(method, params, payload)

    def load(self):
        """Learn the open documents, and follow them through events from now on."""
        for info in self.transport.call("doc.list")[0] or []:
            self._add(info)
        for topic in TOPICS:
            self.transport.on(topic, getattr(self, "_on_" + topic.replace(".", "_")))
        self.transport.on("action.triggered", self._on_action_triggered)
        self.transport.call("events.subscribe", {"topics": TOPICS})

    def _on_action_triggered(self, data: dict, _payload: bytes):
        """The user chose one of the plug-in's actions in PhotoCraft (a menu or a shortcut)."""
        if data.get("doc") is not None and str(data["doc"]) in self.docs:
            self.active = str(data["doc"])
        action = Krita.instance().action(str(data.get("id", "")))
        if action is not None:
            action.trigger()

    def _canvas_changed(self):
        """Tell the dockers the active document changed, as Krita does when a view activates."""
        canvas = Canvas(View()) if self.active is not None else None
        for dock in Krita.instance()._docks:
            dock.canvasChanged(canvas)

    def _add(self, info: dict[str, Any]) -> Document:
        doc = self.docs.get(str(info["doc"]))
        if doc is None:
            doc = Document(self, info)
            self.docs[doc._id] = doc
        else:
            doc._info = info
        if info.get("active"):
            self.active = doc._id
        return doc

    def _on_document_opened(self, data: dict, _payload: bytes):
        info, _ = self.call("doc.info", {"doc": data["doc"]})
        self._add(info)
        Krita.instance().notifier().imageCreated.emit(self.docs[str(data["doc"])])
        self._canvas_changed()

    def _on_document_closed(self, data: dict, _payload: bytes):
        doc = self.docs.pop(str(data["doc"]), None)
        if self.active == str(data["doc"]):
            self.active = None
        if doc is not None:
            Krita.instance().notifier().imageClosed.emit(doc.fileName())
        self._canvas_changed()

    def _on_document_saved(self, data: dict, _payload: bytes):
        self._on_document_renamed(data, _payload)
        doc = self.docs.get(str(data["doc"]))
        if doc is not None:
            Krita.instance().notifier().imageSaved.emit(doc.fileName())

    def _on_document_renamed(self, data: dict, _payload: bytes):
        doc = self.docs.get(str(data["doc"]))
        if doc is not None:
            doc._info = {
                **doc._info,
                "name": data.get("name", doc.name()),
                "path": data.get("path"),
            }

    def _on_document_activated(self, data: dict, _payload: bytes):
        self.active = str(data["doc"])
        self._canvas_changed()

    def _on_layers_changed(self, data: dict, _payload: bytes):
        doc = self.docs.get(str(data["doc"]))
        if doc is not None:
            doc.update_tree(data.get("tree") or [])

    def _on_layer_activated(self, data: dict, _payload: bytes):
        doc = self.docs.get(str(data["doc"]))
        if doc is not None:
            doc._active = data.get("uid")


def attach(
    transport: Any, host_version: str = "", *, locale: str = "en", data_dir: Path | None = None
) -> _Host:
    """Connect the ``krita`` stand-in to PhotoCraft, and load the open documents."""
    host = _Host(transport, HostInfo(host_version, locale, data_dir))
    instance = Krita.instance()
    instance._host = host
    host.load()
    for action in instance._actions.values():
        action._register()
    return host


class Action(QObject):
    """A command the user triggers from PhotoCraft's menus or a shortcut."""

    triggered = pyqtSignal()

    def __init__(self, name: str = "", text: str = "", menu: str = ""):
        super().__init__()
        self._name = name
        self._text = text
        self._menu = menu
        self._enabled = True
        self._registered = False

    def objectName(self) -> str:
        return self._name

    def text(self) -> str:
        """The action's text: its own, else the plug-in's ``.action`` file's, as in Krita."""
        return self._text or Krita.instance()._action_texts.get(self._name, "")

    def setText(self, text: str):
        self._text = text

    def trigger(self):
        if self._enabled:
            self.triggered.emit()

    def isEnabled(self) -> bool:
        return self._enabled

    def setEnabled(self, enabled: bool):
        self._enabled = bool(enabled)
        host = Krita.instance()._host
        if host is not None and self._registered:
            host.call("action.update", {"id": self._name, "enabled": self._enabled})

    def _register(self):
        host = Krita.instance()._host
        if host is None or self._registered or not self._name:
            return
        # Upstream creates its actions without text; Krita takes it from the plug-in's
        # .action file (Krita.load_action_file). PhotoCraft gets no default shortcut (REQ-35).
        params: dict[str, Any] = {"id": self._name, "label": self.text() or self._name}
        if self._menu:
            params["menu"] = self._menu
        host.call("action.register", params)
        self._registered = True


class Notifier(QObject):
    """Application events: documents created, closed and saved, and the application closing."""

    applicationClosing = pyqtSignal()
    imageCreated = pyqtSignal(object)
    imageClosed = pyqtSignal(str)
    imageSaved = pyqtSignal(str)
    viewCreated = pyqtSignal(object)
    viewClosed = pyqtSignal(object)
    windowCreated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._active = False

    def active(self) -> bool:
        return self._active

    def setActive(self, active: bool):
        self._active = bool(active)


class View(QObject):
    """A document's view; PhotoCraft draws the canvas, so it holds nothing."""


class Canvas(QObject):
    """The canvas a docker is told about (``DockWidget.canvasChanged``)."""

    def __init__(self, view: View | None = None):
        super().__init__()
        self._view = view

    def view(self) -> View | None:
        return self._view


class Window(QObject):
    """PhotoCraft's main window, as far as upstream needs one: to create actions."""

    def createAction(self, name: str, text: str = "", menu: str = "") -> Action:
        instance = Krita.instance()
        action = instance._actions.get(name)
        if action is None:
            action = Action(name, text, menu)
            instance._actions[name] = action
        action._register()
        return action


class Extension(QObject):
    """Base class of a plug-in's extension: ``setup`` once, then ``createActions``."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window: Window):
        pass


class DockWidget(QDockWidget):
    """Base class of a docker; PhotoCraft draws its widget through the Qt mirror."""

    def canvasChanged(self, canvas: Canvas | None):
        """Called when the active document changes; overridden by dockers."""


class DockWidgetFactoryBase:
    class DockPosition:
        DockTornOff = 0
        DockTop = 1
        DockBottom = 2
        DockRight = 3
        DockLeft = 4
        DockMinimized = 5

    DockLeft = DockPosition.DockLeft
    DockRight = DockPosition.DockRight
    DockTop = DockPosition.DockTop
    DockBottom = DockPosition.DockBottom


class DockWidgetFactory(DockWidgetFactoryBase):
    """How to make a docker: its id, position and widget class."""

    def __init__(self, name: str, position: int, widget_class: type):
        self._name = name
        self._position = position
        self._widget_class = widget_class

    def id(self) -> str:
        return self._name

    def create(self) -> QWidget:
        return self._widget_class()


class Krita(QObject):
    """The application singleton (``Krita.instance()``)."""

    _instance: Krita | None = None

    def __init__(self):
        super().__init__()
        self._host: _Host | None = None
        self._notifier = Notifier()
        self._actions: dict[str, Action] = {}
        self._extensions: list[Extension] = []
        self._dock_factories: list[DockWidgetFactory] = []
        self._docks: list[DockWidget] = []
        self._action_texts: dict[str, str] = {}
        self._window = Window()

    @staticmethod
    def instance() -> Krita:
        if Krita._instance is None:
            Krita._instance = Krita()
        return Krita._instance

    def _connected(self) -> _Host:
        if self._host is None:
            raise RuntimeError("the plug-in is not connected to PhotoCraft yet")
        return self._host

    def version(self) -> str:
        """PhotoCraft's version, named so upstream's diagnostics say which host it runs in."""
        return f"PhotoCraft {self._host.host_version}" if self._host else "PhotoCraft"

    def icon(self, _name: str) -> QIcon:
        return QIcon()

    def action(self, name: str) -> Action | None:
        return self._actions.get(name)

    def actions(self) -> list[Action]:
        return list(self._actions.values())

    def notifier(self) -> Notifier:
        return self._notifier

    def addExtension(self, extension: Extension):
        self._extensions.append(extension)

    def extensions(self) -> list[Extension]:
        return list(self._extensions)

    def addDockWidgetFactory(self, factory: DockWidgetFactory):
        self._dock_factories.append(factory)

    def load_action_file(self, path: Path):
        """Read action texts from a Krita ``.action`` file, as Krita does for a plug-in's."""
        try:
            tree = ElementTree.parse(path)
        except (OSError, ElementTree.ParseError):
            return
        for action in tree.iter("Action"):
            text = action.findtext("text")
            if action.get("name") and text:
                self._action_texts[str(action.get("name"))] = text

    def create_dock(self, factory: DockWidgetFactory) -> DockWidget:
        """Create a docker from its factory and keep it, so it hears of document changes."""
        dock = factory.create()
        assert isinstance(dock, DockWidget)
        self._docks.append(dock)
        return dock

    def dockWidgetFactories(self) -> list[DockWidgetFactory]:
        return list(self._dock_factories)

    def activeWindow(self) -> Window:
        return self._window

    def windows(self) -> list[Window]:
        return [self._window]

    def activeDocument(self) -> Document | None:
        host = self._host
        if host is None or host.active is None:
            return None
        return host.docs.get(host.active)

    def documents(self) -> list[Document]:
        return list(self._host.docs.values()) if self._host else []

    def setActiveDocument(self, document: Document | None):
        if document is not None:
            self._connected().call("doc.setActive", {"doc": document._id})
            self._connected().active = document._id

    def openDocument(self, filename: str) -> Document | None:
        host = self._connected()
        result, _ = host.call("doc.open", {"path": filename})
        info, _ = host.call("doc.info", {"doc": result["doc"]})
        return host._add(info)


class DoubleParseSpinBox(QWidget):
    """A number box that also accepts typed expressions (here: a QDoubleSpinBox)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._spin = QDoubleSpinBox(self)
        self._layout.addWidget(self._spin)

    def widget(self) -> QDoubleSpinBox:
        return self._spin

    def stepBy(self, steps: int):
        self._spin.stepBy(steps)


class DoubleSliderSpinBox(DoubleParseSpinBox):
    """Krita's slider and number box in one: the Qt mirror draws it as a ``sliderSpin``."""

    draggingFinished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._layout.insertWidget(0, self._slider)
        self._scale = 1
        self._slider.valueChanged.connect(self._from_slider)
        self._slider.sliderReleased.connect(self.draggingFinished)
        self._spin.valueChanged.connect(self._from_spin)

    def setRange(
        self, minimum: float, maximum: float, decimals: int = 0, _compute_fast_step: bool = True
    ):
        self._scale = 10**decimals
        self._spin.setDecimals(decimals)
        self._spin.setRange(minimum, maximum)
        self._slider.setRange(round(minimum * self._scale), round(maximum * self._scale))

    def setSoftMinimum(self, _minimum: float):
        pass

    def setSoftMaximum(self, _maximum: float):
        pass

    def setValue(self, value: float):
        self._spin.setValue(value)

    def value(self) -> float:
        return self._spin.value()

    def isDragging(self) -> bool:
        return self._slider.isSliderDown()

    def _from_slider(self, raw: int):
        value = raw / self._scale
        if abs(self._spin.value() - value) > 0.5 / self._scale:
            self._spin.setValue(value)

    def _from_spin(self, value: float):
        raw = round(value * self._scale)
        if self._slider.value() != raw:
            self._slider.setValue(raw)
