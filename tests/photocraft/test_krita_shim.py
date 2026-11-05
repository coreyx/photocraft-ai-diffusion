"""Tests for the ``krita`` stand-in against the mock PhotoCraft: documents and switching between
them, layer identity, creating, moving and deleting layers, visibility, masks, vector layers,
selections, resizing, annotations, actions and the slider spin box.

Upstream's own tests also run against the stand-in (``tests/photocraft/upstream_shim.py``); these
cover what they don't, and the places where PhotoCraft and Krita differ.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from PyQt6.QtCore import QByteArray, QUuid
from PyQt6.QtWidgets import QApplication, QDoubleSpinBox

from photocraft_host.krita import (
    Canvas,
    DockWidget,
    DockWidgetFactory,
    DockWidgetFactoryBase,
    Document,
    DoubleSliderSpinBox,
    Extension,
    Krita,
    Node,
    Selection,
    View,
    attach,
)
from photocraft_host.krita._document import _mask_uid
from photocraft_host.transport import Transport

from .mock_host import HOST_VERSION, MockHost, MockLayer

RED = bytes([0, 0, 255, 255])  # bgra8
BLUE = bytes([255, 0, 0, 255])


def wait_for(app: QApplication, condition: Callable[[], bool], timeout: float = 5.0):
    """Process Qt events until ``condition`` holds."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        app.processEvents()
        time.sleep(0.005)


def settle(app: QApplication):
    """Run the event loop turns the stand-in defers work to (visibility, deletions)."""
    for _ in range(5):
        app.processEvents()


def filled(width: int, height: int, pixel: bytes) -> bytearray:
    return bytearray(pixel * (width * height))


def methods(host: MockHost) -> list[str]:
    return [method for method, _ in host.calls]


@pytest.fixture
def host():
    mock = MockHost()
    yield mock
    mock.close()


@pytest.fixture
def connect(host: MockHost, qt_app: QApplication):
    """Connect a fresh ``Krita`` singleton to the mock, once the test has opened its documents
    (``fresh=False`` connects the one the test already set up)."""
    Krita._instance = None

    def run(fresh: bool = True) -> Krita:
        if fresh:
            Krita._instance = None
        link = Transport(host.plugin_reader, host.plugin_writer)
        link.start()
        attach(link, HOST_VERSION)
        return Krita.instance()

    yield run
    Krita._instance = None


def only_doc(krita: Krita) -> Document:
    doc = krita.activeDocument()
    assert doc is not None
    return doc


# -- documents


def test_documents_and_switching_between_them(host: MockHost, connect, qt_app: QApplication):
    a = host.add_document("A", 8, 8, [MockLayer("Paper", pixels=filled(8, 8, RED))])
    b = host.add_document("B", 16, 4, [MockLayer("Sky", pixels=filled(16, 4, BLUE))])
    krita = connect()

    docs = {d.name(): d for d in krita.documents()}
    assert set(docs) == {"A", "B"}
    assert krita.activeDocument() is docs["B"], "the host's active document"
    assert (docs["A"].width(), docs["A"].height(), docs["B"].width()) == (8, 8, 16)

    paper = docs["A"].rootNode().childNodes()[0]
    sky = docs["B"].rootNode().childNodes()[0]
    assert paper.name() == "Paper" and sky.name() == "Sky"
    assert docs["A"].rootNode().childNodes()[0] is paper, "one node per layer"
    assert docs["B"].nodeByUniqueID(paper.uniqueId()) is None, "layers belong to their document"

    krita.setActiveDocument(docs["A"])
    assert host.active_doc == a.id
    assert krita.activeDocument() is docs["A"]
    # Reads go to each node's own document whichever is active.
    assert sky.pixelData(0, 0, 1, 1).data() == BLUE
    assert paper.pixelData(0, 0, 1, 1).data() == RED

    # The user switches documents in PhotoCraft.
    host.send_event("document.activated", {"doc": b.id})
    wait_for(qt_app, lambda: krita.activeDocument() is docs["B"])
    assert krita.activeDocument() is not None and krita.activeDocument().name() == "B"


def test_documents_opened_and_closed_in_photocraft(host: MockHost, connect, qt_app: QApplication):
    krita = connect()
    created: list[Document] = []
    closed: list[str] = []
    krita.notifier().imageCreated.connect(created.append)
    krita.notifier().imageClosed.connect(closed.append)
    assert krita.activeDocument() is None and krita.documents() == []

    doc = host.add_document("New", 4, 4)
    host.send_event("document.opened", {"doc": doc.id})
    wait_for(qt_app, lambda: len(created) == 1)
    assert created[0].name() == "New" and krita.activeDocument() is created[0]

    doc.path = "pictures/new.pcraft"
    host.send_event("document.saved", {"doc": doc.id, "name": "new.pcraft", "path": doc.path})
    wait_for(qt_app, lambda: created[0].fileName() == "pictures/new.pcraft")

    host.send_event("document.closed", {"doc": doc.id})
    wait_for(qt_app, lambda: closed == ["pictures/new.pcraft"])
    assert krita.activeDocument() is None and krita.documents() == []


def test_open_document(host: MockHost, connect):
    krita = connect()
    doc = krita.openDocument("pictures/photo.png")
    assert doc is not None and doc.name() == "photo.png"
    assert doc.fileName() == "pictures/photo.png"
    assert krita.activeDocument() is doc


def test_version_names_photocraft(connect):
    assert connect().version() == f"PhotoCraft {HOST_VERSION}"


# -- layers


def test_layer_changes_in_photocraft_keep_node_identity(
    host: MockHost, connect, qt_app: QApplication
):
    mock = host.add_document("A", 4, 4, [MockLayer("One"), MockLayer("Two")])
    doc = only_doc(connect())
    one, two = doc.rootNode().childNodes()
    assert one.uniqueId() == QUuid(mock.layers[0].uid)
    assert doc.nodeByUniqueID(QUuid(mock.layers[1].uid)) is two
    assert doc.activeNode() is two

    # Renamed and deleted in PhotoCraft; the shim learns of it from the event.
    mock.layers[0].name = "Renamed"
    del mock.layers[1]
    host.send_event(
        "layers.changed", {"doc": mock.id, "tree": [mock.info(layer) for layer in mock.layers]}
    )
    wait_for(qt_app, lambda: len(doc.rootNode().childNodes()) == 1)
    assert doc.rootNode().childNodes()[0] is one and one.name() == "Renamed"
    assert two.parentNode() is None, "a deleted layer's node leaves the tree"


def test_new_layers_are_created_where_they_are_added(host: MockHost, connect):
    mock = host.add_document("A", 4, 4, [MockLayer("Bottom"), MockLayer("Top")])
    doc = only_doc(connect())
    bottom, top = doc.rootNode().childNodes()

    painted = doc.createNode("Painted", "paintlayer")
    painted.setPixelData(QByteArray(RED * 4), 1, 1, 2, 2)
    assert "pixels.createLayer" not in methods(host), "a detached layer's pixels wait"
    doc.rootNode().addChildNode(painted, bottom)
    assert [n.name() for n in doc.rootNode().childNodes()] == ["Bottom", "Painted", "Top"]
    assert painted.bounds().getRect() == (1, 1, 2, 2)
    created = mock.find(painted.uniqueId().toString().strip("{}"))
    assert (
        created.pixels is not None and created.pixels[(1 * 4 + 1) * 4 : (1 * 4 + 1) * 4 + 4] == RED
    )

    group = doc.createGroupLayer("Group")
    doc.rootNode().addChildNode(group, None)
    empty = doc.createNode("Empty", "paintlayer")
    group.addChildNode(empty, None)
    assert group.type() == "grouplayer"
    assert [n.name() for n in group.childNodes()] == ["Empty"]
    assert empty.parentNode() is group
    assert top.parentNode() is doc.rootNode()


def test_remove_then_add_is_a_move(host: MockHost, connect, qt_app: QApplication):
    host.add_document("A", 4, 4, [MockLayer("Layer"), MockLayer("Other")])
    doc = only_doc(connect())
    layer, _ = doc.rootNode().childNodes()
    group = doc.createGroupLayer("Group")
    doc.rootNode().addChildNode(group, None)

    doc.rootNode().removeChildNode(layer)
    group.addChildNode(layer, None)
    settle(qt_app)
    assert "layer.delete" not in methods(host)
    assert layer.parentNode() is group and layer.uniqueId() in [
        n.uniqueId() for n in group.childNodes()
    ]


def test_remove_without_add_deletes_on_the_next_turn(host: MockHost, connect, qt_app: QApplication):
    host.add_document("A", 4, 4, [MockLayer("Layer"), MockLayer("Other")])
    doc = only_doc(connect())
    layer, other = doc.rootNode().childNodes()

    doc.rootNode().removeChildNode(layer)
    assert "layer.delete" not in methods(host)
    settle(qt_app)
    assert methods(host).count("layer.delete") == 1
    assert doc.rootNode().childNodes() == [other]

    other.remove()
    assert doc.rootNode().childNodes() == [], "remove() deletes at once"


def test_visibility_is_sent_once_on_the_next_turn(host: MockHost, connect, qt_app: QApplication):
    mock = host.add_document(
        "A",
        2,
        1,
        [
            MockLayer("Under", pixels=filled(2, 1, BLUE)),
            MockLayer("Over", pixels=filled(2, 1, RED)),
        ],
    )
    doc = only_doc(connect())
    under, over = doc.rootNode().childNodes()

    # Hidden and shown again before the event loop runs: PhotoCraft hears nothing.
    over.setVisible(False)
    over.setVisible(True)
    settle(qt_app)
    assert "layer.update" not in methods(host)

    # Hidden to read the composite without it, as upstream does.
    over.setVisible(False)
    assert not over.visible()
    assert doc.pixelData(0, 0, 1, 1).data() == BLUE, "the composite leaves the hidden layer out"
    read = [p for m, p in host.calls if m == "pixels.read"][-1]
    assert read["exclude"] == [mock.layers[1].uid]
    settle(qt_app)
    assert [p for m, p in host.calls if m == "layer.update"] == [
        {"doc": mock.id, "uid": mock.layers[1].uid, "visible": False}
    ]
    assert not mock.layers[1].visible and under.visible()


def test_layer_properties(host: MockHost, connect):
    mock = host.add_document("A", 4, 4, [MockLayer("Layer")])
    layer = only_doc(connect()).rootNode().childNodes()[0]
    layer.setName("Named")
    layer.setOpacity(51)
    layer.setLocked(True)
    layer.setBlendingMode("multiply")
    assert (mock.layers[0].name, mock.layers[0].opacity, mock.layers[0].locked) == (
        "Named",
        0.2,
        True,
    )
    assert mock.layers[0].blend == "multiply"
    assert (layer.name(), layer.opacity(), layer.locked(), layer.blendingMode()) == (
        "Named",
        51,
        True,
        "multiply",
    )
    calls = len(host.calls)
    layer.setBlendingMode("multiply")
    assert len(host.calls) == calls, "an unchanged mode isn't sent"
    assert layer.colorDepth() == "U8" and not layer.animated()


def test_thumbnail(host: MockHost, connect):
    host.add_document("A", 8, 8, [MockLayer("Layer", pixels=filled(8, 8, RED))])
    layer = only_doc(connect()).rootNode().childNodes()[0]
    image = layer.thumbnail(4, 4)
    assert (image.width(), image.height()) == (4, 4)
    assert image.pixelColor(1, 1).red() == 255


# -- masks


def test_a_layer_mask_is_a_transparency_mask_child(host: MockHost, connect):
    mock = host.add_document("A", 4, 4, [MockLayer("Layer", pixels=filled(4, 4, RED))])
    doc = only_doc(connect())
    layer = doc.rootNode().childNodes()[0]

    mask = doc.createTransparencyMask("Mask")
    mask.setPixelData(QByteArray(b"\xff" * 4), 1, 1, 2, 2)
    layer.addChildNode(mask, None)

    stored = mock.layers[0].mask
    assert stored is not None and len(stored) == 16, "a canvas-sized gray8 mask"
    assert stored[5] == 255 and stored[0] == 0
    child = layer.childNodes()[0]
    assert child.type() == "transparencymask"
    assert child.uniqueId() == QUuid(_mask_uid(mock.layers[0].uid))
    assert child.bounds().getRect() == (0, 0, 4, 4)
    assert child.pixelData(1, 1, 2, 2).data() == b"\xff" * 4


# -- vector layers


def test_vector_layers(host: MockHost, connect):
    mock = host.add_document("A", 200, 200)
    mock.dpi = 144.0
    doc = only_doc(connect())

    pose = doc.createVectorLayer("Pose")
    doc.rootNode().addChildNode(pose, None)
    group = mock.find(pose.uniqueId().toString().strip("{}"))
    assert group.kind == "group" and group.data.get("vector.group") == "1"
    assert pose.type() == "vectorlayer"

    shapes = pose.addShapesFromSvg('<svg><circle id="kp_0" cx="40" cy="60" r="4"/></svg>')
    assert [s.name() for s in shapes] == ["kp_0"]
    position = shapes[0].position()
    assert (position.x(), position.y()) == (18.0, 28.0), "points at 144 dpi"
    pose.addShapesFromSvg('<svg><line id="bone" x1="0" y1="0" x2="10" y2="10"/></svg>')
    assert [s.name() for s in pose.shapes()] == ["kp_0", "bone"]

    shapes[0].remove()
    assert [s.name() for s in pose.shapes()] == ["bone"]


def test_a_vector_group_is_recognised_when_loaded(host: MockHost, connect):
    host.add_document(
        "A",
        4,
        4,
        [
            MockLayer("Pose", kind="group", data={"vector.group": "1"}),
            MockLayer("Plain", kind="group"),
        ],
    )
    pose, plain = only_doc(connect()).rootNode().childNodes()
    assert pose.type() == "vectorlayer" and plain.type() == "grouplayer"


# -- selections


def test_selection(host: MockHost, connect):
    mock = host.add_document("A", 4, 4)
    doc = only_doc(connect())
    assert doc.selection() is None

    selection = Selection()
    coverage = bytes([0, 0, 0, 0, 0, 255, 128, 0, 0, 255, 255, 0, 0, 0, 0, 0])
    selection.setPixelData(QByteArray(coverage), 0, 0, 4, 4)
    assert (selection.x(), selection.y(), selection.width(), selection.height()) == (1, 1, 2, 2), (
        "tight"
    )
    doc.setSelection(selection)
    assert mock.selection == bytearray(coverage)

    read = doc.selection()
    assert read is not None and (read.x(), read.y(), read.width(), read.height()) == (1, 1, 2, 2)
    assert read.pixelData(1, 1, 2, 2).data() == bytes([255, 128, 255, 255])

    inverted = read.duplicate()
    inverted.invert()
    assert (inverted.width(), inverted.height()) == (4, 4), "inverted over the document"
    assert inverted.pixelData(0, 0, 1, 1).data() == b"\xff"
    assert read.pixelData(0, 0, 1, 1).data() == b"\x00", "the duplicate is separate"

    doc.setSelection(None)
    assert mock.selection is None


# -- the document


def test_resizing(host: MockHost, connect):
    mock = host.add_document("A", 4, 2)
    doc = only_doc(connect())
    assert doc.scaleImage(8, 4, 144.0, 144.0, "Bicubic")
    assert (doc.width(), doc.height(), doc.resolution()) == (8, 4, 144.0)
    assert (mock.width, mock.height) == (8, 4)
    assert doc.resizeImage(0, 0, 10, 6)
    assert (doc.width(), doc.height()) == (10, 6)
    assert [p.get("anchor") for m, p in host.calls if m == "doc.resizeCanvas"] == ["topLeft"]


def test_annotations_are_stored_in_the_document(host: MockHost, connect):
    mock = host.add_document("A", 4, 4)
    doc = only_doc(connect())
    assert doc.annotation("ai_diffusion/document_id").size() == 0
    doc.setAnnotation("ai_diffusion/document_id", "id", QByteArray(b"abc"))
    assert mock.blobs == {"ai_diffusion/document_id": b"abc"}
    assert doc.annotation("ai_diffusion/document_id").data() == b"abc"
    doc.removeAnnotation("ai_diffusion/document_id")
    assert mock.blobs == {}


def test_annotations_on_a_closed_document_are_ignored(
    host: MockHost, connect, qt_app: QApplication
):
    """As in Krita: upstream saves its state a moment after a change, maybe after closing."""
    mock = host.add_document("A", 4, 4)
    krita = connect()
    doc = only_doc(krita)
    del host.docs[mock.id]  # closed in PhotoCraft, before the plug-in hears of it
    doc.setAnnotation("ai_diffusion/ui.json", "state", QByteArray(b"{}"))
    assert doc.annotation("ai_diffusion/ui.json").size() == 0
    host.send_event("document.closed", {"doc": mock.id})
    wait_for(qt_app, lambda: not krita.documents())
    calls = len(host.calls)
    doc.removeAnnotation("ai_diffusion/ui.json")
    assert host.calls[calls:] == [], "no requests once the plug-in knows it closed"


def test_document_basics(host: MockHost, connect):
    host.add_document("A", 4, 4)
    doc = only_doc(connect())
    assert (doc.colorModel(), doc.colorDepth(), doc.resolution()) == ("RGBA", "U8", 72.0)
    assert (doc.currentTime(), doc.playBackStartTime(), doc.playBackEndTime()) == (0, 0, 0)
    assert not doc.importAnimation(["frame.png"], 0, 1), "animation is deferred"
    doc.refreshProjection()


def test_a_detached_node_reads_empty(connect):
    connect()
    node = Node("Loose", "paintlayer")
    assert node.pixelData(0, 0, 2, 1).data() == bytes(8)
    assert node.thumbnail(2, 2).width() == 2
    with pytest.raises(RuntimeError):
        node.addChildNode(Node(), None)


# -- the application


def test_actions_are_registered_once_connected(host: MockHost, connect):
    early = (
        Krita
        .instance()
        .activeWindow()
        .createAction("ai_diffusion_generate", "Generate", "tools/scripts")
    )
    assert Krita.instance().action("ai_diffusion_generate") is early
    assert host.actions == {}, "not registered before PhotoCraft welcomes the plug-in"
    connect(fresh=False)
    assert host.actions["ai_diffusion_generate"]["label"] == "Generate"

    triggered: list[bool] = []
    early.triggered.connect(lambda: triggered.append(True))
    early.setEnabled(False)
    early.trigger()
    assert triggered == [] and host.actions["ai_diffusion_generate"]["enabled"] is False
    early.setEnabled(True)
    early.trigger()
    assert triggered == [True]


def test_double_slider_spin_box(qt_app: QApplication):
    box = DoubleSliderSpinBox()
    box.setRange(0.0, 2.0, 2)
    box.setValue(1.25)
    spin = box.widget()
    assert isinstance(spin, QDoubleSpinBox), "as Krita's KisDoubleSliderSpinBox"
    assert (spin.value(), spin.decimals(), spin.maximum()) == (1.25, 2, 2.0)
    spin.setValue(0.5)
    assert box.value() == pytest.approx(0.5)
    assert not box.isDragging()


def test_the_active_layer(host: MockHost, connect, qt_app: QApplication):
    mock = host.add_document("A", 4, 4, [MockLayer("One"), MockLayer("Two")])
    doc = only_doc(connect())
    one, two = doc.rootNode().childNodes()
    doc.setActiveNode(one)
    assert mock.active_layer == mock.layers[0].uid and doc.activeNode() is one

    # The user picks a layer in PhotoCraft.
    host.send_event("layer.activated", {"doc": mock.id, "uid": mock.layers[1].uid})
    wait_for(qt_app, lambda: doc.activeNode() is two)


def test_writing_layer_and_mask_pixels(host: MockHost, connect):
    mock = host.add_document("A", 2, 2, [MockLayer("Layer", pixels=filled(2, 2, RED))])
    mock.layers[0].mask = bytearray(4)
    doc = only_doc(connect())
    layer = doc.rootNode().childNodes()[0]
    layer.setPixelData(QByteArray(BLUE), 1, 1, 1, 1)
    assert mock.layers[0].pixels is not None and mock.layers[0].pixels[12:16] == BLUE

    mask = layer.childNodes()[0]
    assert mask.type() == "transparencymask"
    mask.setPixelData(QByteArray(b"\xff\xff"), 0, 0, 2, 1)
    assert mock.layers[0].mask == bytearray(b"\xff\xff\x00\x00")


def test_shape_names_and_order(host: MockHost, connect):
    host.add_document("A", 100, 100)
    doc = only_doc(connect())
    pose = doc.createVectorLayer("Pose")
    doc.rootNode().addChildNode(pose, None)
    pose.addShapesFromSvg('<svg><circle id="joint" cx="5" cy="5" r="2"/></svg>')
    (bone,) = pose.addShapesFromSvg('<svg><line id="bone" x1="0" y1="0" x2="9" y2="9"/></svg>')

    bone.setZIndex(-1)
    assert bone.zIndex() == -1
    assert [s.name() for s in pose.shapes()] == ["bone", "joint"], "bones draw below joints"
    bone.setName("arm")
    assert [s.name() for s in pose.shapes()] == ["arm", "joint"]


def test_extensions_and_dockers_are_kept(connect, qt_app: QApplication):
    krita = connect()

    class Docker(DockWidget):
        pass

    extension = Extension()
    extension.setup()
    extension.createActions(krita.activeWindow())
    krita.addExtension(extension)
    factory = DockWidgetFactory("ai_diffusion", DockWidgetFactoryBase.DockRight, Docker)
    krita.addDockWidgetFactory(factory)
    assert krita.extensions() == [extension]
    assert krita.dockWidgetFactories() == [factory] and factory.id() == "ai_diffusion"
    assert isinstance(factory.create(), Docker)
    assert krita.windows() == [krita.activeWindow()]
    assert krita.icon("star").isNull()
    assert Canvas(View()).view() is not None
