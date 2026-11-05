"""Tests for the Qt mirror against the mock PhotoCraft: each adapter's node and its input played
back through Qt, layouts as containers, hidden and disabled widgets, the tree diff, and changes
reaching PhotoCraft as one patch per flush."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from photocraft_host.krita import DoubleSliderSpinBox
from photocraft_host.qt_mirror import Mirror, diff
from photocraft_host.transport import Transport

from .mock_host import MockHost, apply_patches, find_widget

PANEL = "test"


def wait_for(app: QApplication, condition: Callable[[], bool], timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        app.processEvents()
        time.sleep(0.005)


def settle(app: QApplication, seconds: float = 0.1):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


class Panel:
    """A widget mirrored into the mock host, with helpers to read the host's copy and to act
    as the user in PhotoCraft."""

    def __init__(self, host: MockHost, mirror: Mirror, app: QApplication):
        self.host, self.mirror, self.app = host, mirror, app

    @property
    def tree(self) -> dict:
        return self.host.panels[PANEL]["tree"]

    def node(self, widget: QWidget) -> dict:
        found = find_widget(self.tree, self.mirror.node_id(widget))
        assert found is not None, f"{type(widget).__name__} isn't in the panel"
        return found

    def props(self, widget: QWidget) -> dict[str, Any]:
        return self.node(widget).get("props", {})

    def flush(self):
        self.mirror.flush()

    def user(
        self, widget: QWidget, kind: str, value: Any = None, done: Callable[[], bool] | None = None
    ):
        """Send PhotoCraft's input event for ``widget`` and wait until it is handled."""
        seen: list[bool] = []
        self.mirror._transport.on("panel.input", lambda *_: seen.append(True))
        data = {"owner": PANEL, "nodeId": self.mirror.node_id(widget), "kind": kind, "value": value}
        self.host.send_event("panel.input", data)
        wait_for(self.app, lambda: bool(seen) and (done is None or done()))
        self.flush()


@pytest.fixture
def host() -> Iterator[MockHost]:
    mock = MockHost()
    yield mock
    mock.close()


@pytest.fixture
def mirror(host: MockHost, qt_app: QApplication) -> Iterator[Callable[[QWidget], Panel]]:
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    started: list[Mirror] = []

    def run(widget: QWidget, **kwargs) -> Panel:
        m = Mirror(widget, link, PANEL, "Test", poll_ms=kwargs.pop("poll_ms", 60_000), **kwargs)
        m.start()
        started.append(m)
        return Panel(host, m, qt_app)

    yield run
    for m in started:
        m.stop()


def column(*widgets: QWidget) -> QWidget:
    root = QWidget()
    layout = QVBoxLayout(root)
    for w in widgets:
        layout.addWidget(w)
    return root


def red_icon() -> QIcon:
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("red"))
    return QIcon(pixmap)


# -- display


def test_label_text_rich_text_and_picture(mirror, host: MockHost):
    plain, rich, picture = (
        QLabel("Strength"),
        QLabel("<b>Bold</b> <a href='https://example.com'>link</a>"),
        QLabel(),
    )
    rich.setOpenExternalLinks(True)
    plain.setWordWrap(True)
    pixmap = QPixmap(4, 3)
    pixmap.fill(QColor("blue"))
    picture.setPixmap(pixmap)
    panel = mirror(column(plain, rich, picture))
    assert panel.node(plain)["kind"] == "label" and panel.props(plain) == {
        "text": "Strength",
        "wrap": True,
    }
    assert panel.props(rich)["format"] == "rich"
    image = panel.props(picture)
    assert panel.node(picture)["kind"] == "image" and (image["width"], image["height"]) == (4, 3)
    assert image["image"].removeprefix("image:") in host.images

    activated: list[str] = []
    rich.linkActivated.connect(activated.append)
    panel.user(rich, "click", "https://example.com", done=lambda: bool(activated))
    assert activated == ["https://example.com"]
    wait_for(panel.app, lambda: host.opened == ["https://example.com"])

    plain.setText("Weight")  # no signal: the setter hook notices it
    assert panel.mirror._flush_timer.isActive()
    panel.flush()
    assert panel.props(plain)["text"] == "Weight"


def test_progress_bar(mirror):
    bar = QProgressBar()
    bar.setRange(0, 200)
    bar.setValue(50)
    panel = mirror(column(bar))
    assert panel.node(bar)["kind"] == "progress"
    assert panel.props(bar)["value"] == pytest.approx(0.25) and panel.props(bar)["text"] == "25%"
    bar.setRange(0, 0)
    panel.flush()
    assert "value" not in panel.props(bar), "busy"
    bar.setTextVisible(False)
    panel.flush()
    assert "text" not in panel.props(bar)


def test_frames(mirror):
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    vline = QFrame()
    vline.setFrameShape(QFrame.Shape.VLine)
    box = QFrame()
    QHBoxLayout(box).addWidget(QLabel("inside"))
    panel = mirror(column(line, vline, box))
    assert panel.node(line)["kind"] == "separator"
    assert panel.props(vline)["orientation"] == "vertical"
    assert (
        panel.node(box)["kind"] == "row"
        and panel.node(box)["children"][0]["props"]["text"] == "inside"
    )


# -- buttons


def test_push_button_click_and_toggle(mirror):
    button, toggle = QPushButton("&Generate"), QPushButton("Live")
    button.setDefault(True)
    button.setIcon(red_icon())
    toggle.setCheckable(True)
    clicks: list[bool] = []
    toggles: list[bool] = []
    button.clicked.connect(clicks.append)
    toggle.toggled.connect(toggles.append)
    panel = mirror(column(button, toggle))
    assert panel.node(button)["kind"] == "button"
    assert panel.props(button)["text"] == "Generate" and panel.props(button)["default"] is True
    assert panel.props(button)["icon"].startswith("image:")
    assert panel.node(toggle)["kind"] == "toggleButton" and panel.props(toggle)["checked"] is False

    panel.user(button, "click", 1, done=lambda: bool(clicks))
    panel.user(toggle, "change", True, done=lambda: toggles == [True])
    assert panel.props(toggle)["checked"] is True
    panel.user(toggle, "change", True)
    assert toggles == [True], "already on: no second toggle"


def test_tool_button(mirror):
    icon_only, text_only, checkable = QToolButton(), QToolButton(), QToolButton()
    icon_only.setIcon(red_icon())
    icon_only.setText("Settings")
    text_only.setText("More")
    text_only.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    checkable.setCheckable(True)
    checkable.setIcon(red_icon())
    panel = mirror(column(icon_only, text_only, checkable))
    assert "text" not in panel.props(icon_only) and panel.props(icon_only)["icon"].startswith(
        "image:"
    )
    assert panel.props(text_only) == {"text": "More"}
    assert panel.props(checkable)["checkable"] is True

    clicked: list[bool] = []
    icon_only.clicked.connect(clicked.append)
    panel.user(icon_only, "click", 1, done=lambda: bool(clicked))
    panel.user(checkable, "change", True, done=checkable.isChecked)
    assert panel.props(checkable)["checked"] is True


def test_check_box_and_tristate(mirror):
    check, tri = QCheckBox("Seed fixed"), QCheckBox("Mixed")
    tri.setTristate(True)
    tri.setCheckState(Qt.CheckState.PartiallyChecked)
    states: list[int] = []
    check.stateChanged.connect(states.append)
    panel = mirror(column(check, tri))
    assert panel.props(check) == {"text": "Seed fixed", "checked": False}
    assert panel.props(tri)["tristate"] is True and "checked" not in panel.props(tri)
    panel.user(check, "change", True, done=lambda: bool(states))
    assert check.isChecked() and panel.props(check)["checked"] is True
    panel.user(tri, "change", False, done=lambda: tri.checkState() == Qt.CheckState.Unchecked)


def test_radio_buttons_stay_exclusive(mirror):
    a, b = QRadioButton("Full"), QRadioButton("Single")
    root = QWidget()
    layout = QHBoxLayout(root)
    layout.addWidget(a)
    layout.addWidget(b)
    a.setChecked(True)
    panel = mirror(root)
    assert panel.props(a)["checked"] is True and panel.props(a)["radio"] is True
    panel.user(b, "change", True, done=b.isChecked)
    assert not a.isChecked() and panel.props(a)["checked"] is False
    # Turning the checked one off is refused, and PhotoCraft is told so again.
    sets_before = len(panel.host.panels[PANEL]["patches"])
    panel.user(b, "change", False)
    assert b.isChecked()
    assert len(panel.host.panels[PANEL]["patches"]) == sets_before + 1, "the value is confirmed"
    assert panel.props(b)["checked"] is True


# -- value inputs


def test_combo_box(mirror):
    combo = QComboBox()
    combo.addItems(["SDXL", "Flux"])
    combo.insertSeparator(2)
    combo.addItem(red_icon(), "Custom")
    activated: list[int] = []
    combo.activated.connect(activated.append)
    panel = mirror(column(combo))
    items = panel.props(combo)["items"]
    assert [i.get("text") for i in items] == ["SDXL", "Flux", None, "Custom"]
    assert items[2] == {"kind": "separator"} and items[3]["icon"].startswith("image:")
    assert panel.props(combo)["value"] == "0"

    panel.user(combo, "change", "1", done=lambda: activated == [1])
    assert combo.currentIndex() == 1 and panel.props(combo)["value"] == "1"
    combo.addItem("Pony")  # through the model's signals
    assert panel.mirror._flush_timer.isActive()
    panel.flush()
    assert panel.props(combo)["items"][-1]["text"] == "Pony"
    panel.user(combo, "change", "99")
    assert combo.currentIndex() == 1, "out of range: ignored"


def test_slider_replays_a_drag(mirror):
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(1, 20)
    slider.setValue(7)
    events: list[str] = []
    slider.sliderPressed.connect(lambda: events.append("pressed"))
    slider.sliderMoved.connect(lambda v: events.append(f"moved {v}"))
    slider.sliderReleased.connect(lambda: events.append("released"))
    panel = mirror(column(slider))
    assert panel.props(slider) == {"min": 1, "max": 20, "step": 1, "value": 7}
    panel.user(slider, "change", 12, done=lambda: "released" in events)
    assert events == ["pressed", "moved 12", "released"] and slider.value() == 12
    assert panel.props(slider)["value"] == 12


def test_spin_boxes_and_clamping(mirror):
    spin, double = QSpinBox(), QDoubleSpinBox()
    spin.setRange(1, 100)
    spin.setSuffix(" steps")
    double.setRange(0.0, 2.0)
    double.setDecimals(2)
    double.setSingleStep(0.05)
    finished: list[bool] = []
    spin.editingFinished.connect(lambda: finished.append(True))
    panel = mirror(column(spin, double))
    assert panel.node(spin)["kind"] == "spin" and panel.props(spin)["suffix"] == " steps"
    assert panel.props(double)["decimals"] == 2 and panel.props(double)["step"] == pytest.approx(
        0.05
    )

    panel.user(spin, "change", 30, done=lambda: bool(finished))
    assert spin.value() == 30 and panel.props(spin)["value"] == 30
    # Clamped to the range; PhotoCraft gets the clamped value back.
    panel.user(double, "change", 5.0, done=lambda: double.value() == pytest.approx(2.0))
    assert panel.props(double)["value"] == pytest.approx(2.0)


def test_line_edit(mirror):
    edit, secret = QLineEdit(), QLineEdit()
    edit.setPlaceholderText("Negative prompt")
    secret.setEchoMode(QLineEdit.EchoMode.Password)
    edited: list[str] = []
    returned: list[bool] = []
    edit.textEdited.connect(edited.append)
    edit.returnPressed.connect(lambda: returned.append(True))
    panel = mirror(column(edit, secret))
    assert panel.props(edit) == {"text": "", "placeholder": "Negative prompt"}
    assert panel.props(secret)["password"] is True
    panel.user(edit, "change", "blurry", done=lambda: edited == ["blurry"])
    assert edit.text() == "blurry" and panel.props(edit)["text"] == "blurry"
    panel.user(edit, "key", "Enter", done=lambda: bool(returned))
    edit.setReadOnly(True)
    panel.user(edit, "change", "ignored")
    assert edit.text() == "blurry"


def test_slider_spin_box(mirror):
    box = DoubleSliderSpinBox()
    box.setRange(0.0, 1.0, 2)
    box.setValue(0.5)
    finished: list[bool] = []
    box.draggingFinished.connect(lambda: finished.append(True))
    panel = mirror(column(box))
    node = panel.node(box)
    assert node["kind"] == "sliderSpin" and node.get("children", []) == [], (
        "inner widgets not mirrored"
    )
    assert panel.props(box)["value"] == pytest.approx(0.5) and panel.props(box)["decimals"] == 2
    panel.user(box, "change", 0.75, done=lambda: bool(finished))
    assert box.value() == pytest.approx(0.75)
    assert panel.props(box)["value"] == pytest.approx(0.75)


def test_slider_spin_placed_through_widget(mirror):
    """Upstream puts ``widget()`` in its layouts and sets enabled state and tooltip on it."""
    box = DoubleSliderSpinBox()
    box.setRange(0.0, 1.0, 2)
    spin = box.widget()
    spin.setEnabled(False)
    spin.setToolTip("The tile/unblur control model is not installed.")
    finished: list[bool] = []
    box.draggingFinished.connect(lambda: finished.append(True))
    panel = mirror(column(spin))
    node = panel.node(spin)
    assert node["kind"] == "sliderSpin"
    assert node["props"]["enabled"] is False
    assert node["props"]["tooltip"] == "The tile/unblur control model is not installed."
    spin.setEnabled(True)
    panel.user(spin, "change", 0.25, done=lambda: bool(finished))
    assert box.value() == pytest.approx(0.25)


# -- containers


def test_scroll_area(mirror):
    area = QScrollArea()
    inner = column(QLabel("Scrolled"))
    area.setWidget(inner)
    area.setMaximumHeight(120)
    panel = mirror(column(area))
    assert panel.node(area)["kind"] == "scroll" and panel.props(area)["maxHeight"] == 120
    assert panel.node(area)["children"][0]["id"] == panel.mirror.node_id(inner)


def test_stack_shows_only_its_current_page(mirror):
    stack = QStackedWidget()
    first, second = QLabel("Generation"), QLabel("Upscaling")
    stack.addWidget(first)
    stack.addWidget(second)
    panel = mirror(column(stack))
    assert [c["id"] for c in panel.node(stack)["children"]] == [panel.mirror.node_id(first)]
    stack.setCurrentWidget(second)
    panel.flush()
    assert [c["props"]["text"] for c in panel.node(stack)["children"]] == ["Upscaling"]


def test_tabs(mirror):
    tabs = QTabWidget()
    one, two = QLabel("Page one"), QLabel("Page two")
    tabs.addTab(one, "&One")
    tabs.addTab(two, "Two")
    changed: list[int] = []
    tabs.currentChanged.connect(changed.append)
    panel = mirror(column(tabs))
    pages = panel.node(tabs)["children"]
    assert [p["props"]["title"] for p in pages] == ["One", "Two"]
    assert pages[0]["kind"] == "label" and pages[1].get("children", []) == []
    panel.user(tabs, "change", 1, done=lambda: changed == [1])
    pages = panel.node(tabs)["children"]
    assert pages[1]["props"]["text"] == "Page two" and panel.props(tabs)["current"] == 1
    tabs.setTabText(0, "First")
    panel.flush()
    assert panel.node(tabs)["children"][0]["props"]["title"] == "First"


def test_splitter(mirror):
    splitter = QSplitter(Qt.Orientation.Vertical)
    splitter.addWidget(QLabel("Top"))
    splitter.addWidget(QLabel("Bottom"))
    panel = mirror(column(splitter))
    assert panel.props(splitter)["orientation"] == "vertical"
    assert [c["props"]["text"] for c in panel.node(splitter)["children"]] == ["Top", "Bottom"]


def test_group_box(mirror):
    group = QGroupBox("&Advanced")
    QVBoxLayout(group).addWidget(QLabel("inside"))
    group.setCheckable(True)
    toggled: list[bool] = []
    group.toggled.connect(toggled.append)
    panel = mirror(column(group))
    assert panel.node(group)["kind"] == "group" and panel.props(group)["title"] == "Advanced"
    assert panel.node(group)["children"][0]["kind"] == "column"
    panel.user(group, "change", False, done=lambda: toggled == [False])
    assert panel.props(group)["checked"] is False


# -- layouts and state


def test_box_grid_and_form_layouts(mirror):
    root = QWidget()
    outer = QVBoxLayout(root)
    row = QHBoxLayout()
    grow_edit = QLineEdit()
    fixed = QPushButton("Fixed")
    row.addWidget(fixed)
    row.addWidget(grow_edit, 2)
    row.addStretch()
    row.addSpacing(10)
    outer.addLayout(row)
    grid = QGridLayout()
    grid.addWidget(QLabel("A"), 0, 0)
    grid.addWidget(QLabel("Wide"), 1, 0, 1, 2)
    outer.addLayout(grid)
    form = QFormLayout()
    form.addRow("Steps", QSpinBox())
    form.addRow(QCheckBox("Spanning"))
    outer.addLayout(form)
    panel = mirror(root)

    top = panel.tree
    assert top["kind"] == "column"
    row_node, grid_node, form_node = top["children"]
    assert row_node["kind"] == "row"
    kinds = [c["kind"] for c in row_node["children"]]
    assert kinds == ["button", "lineEdit", "spacer", "spacer"]
    assert row_node["children"][1]["props"]["grow"] == 2
    assert "grow" not in row_node["children"][0].get("props", {})
    assert row_node["children"][2]["props"]["grow"] == 1, "a stretch"
    assert row_node["children"][3]["props"]["size"] == 10, "fixed spacing"
    wide = grid_node["children"][1]["props"]
    assert grid_node["kind"] == "grid" and (wide["row"], wide["col"], wide["colSpan"]) == (1, 0, 2)
    assert form_node["kind"] == "form"
    assert [c["kind"] for c in form_node["children"]] == ["label", "spin", "spacer", "checkbox"]


def test_expanding_widgets_grow(mirror):
    edit = QLineEdit()  # expands horizontally by default
    label = QLabel("fixed")
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    root = QWidget()
    layout = QHBoxLayout(root)
    layout.addWidget(label)
    layout.addWidget(edit)
    panel = mirror(root)
    assert panel.props(edit)["grow"] == 1 and "grow" not in panel.props(label)


def test_hidden_disabled_and_tooltips(mirror):
    group = QWidget()
    QVBoxLayout(group).addWidget(QLabel("hidden content"))
    button = QPushButton("Go")
    button.setToolTip("<b>Generate</b> an image")
    root = column(group, button)
    group.hide()
    button.setEnabled(False)
    clicked: list[bool] = []
    button.clicked.connect(clicked.append)
    panel = mirror(root)
    assert panel.props(group)["visible"] is False and panel.node(group).get("children", []) == []
    assert panel.props(button)["enabled"] is False
    assert panel.props(button)["tooltip"] == "Generate an image"

    panel.user(button, "click", 1)
    assert clicked == [], "a disabled widget ignores input"
    group.show()
    wait_for(panel.app, panel.mirror._flush_timer.isActive)
    panel.flush()
    assert "visible" not in panel.props(group)
    assert panel.node(group)["children"][0]["props"]["text"] == "hidden content"


def test_input_for_another_panel_or_unknown_widget_is_ignored(mirror, host: MockHost, qt_app):
    button = QPushButton("Go")
    clicked: list[bool] = []
    button.clicked.connect(clicked.append)
    panel = mirror(column(button))
    host.send_event(
        "panel.input", {"owner": "other", "nodeId": panel.mirror.node_id(button), "kind": "click"}
    )
    host.send_event("panel.input", {"owner": PANEL, "nodeId": "nope", "kind": "click"})
    settle(qt_app)
    assert clicked == []


def test_structure_changes_are_patched(mirror):
    root = QWidget()
    layout = QVBoxLayout(root)
    a, b = QLabel("a"), QLabel("b")
    layout.addWidget(a)
    layout.addWidget(b)
    panel = mirror(root)
    c = QLabel("c")
    layout.insertWidget(0, c)
    layout.removeWidget(a)
    a.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    panel.flush()
    assert [n["props"]["text"] for n in panel.tree["children"]] == ["c", "b"]
    ops = panel.host.panels[PANEL]["patches"][-1]
    assert {op["op"] for op in ops} == {"remove", "insert"}


def test_changes_are_sent_as_one_patch_per_flush(mirror, qt_app):
    labels = [QLabel(str(i)) for i in range(5)]
    panel = mirror(column(*labels), flush_ms=10)
    for i, label in enumerate(labels):
        label.setText(f"changed {i}")
    wait_for(qt_app, lambda: len(panel.host.panels[PANEL].get("patches", [])) == 1)
    settle(qt_app, 0.05)
    assert len(panel.host.panels[PANEL]["patches"]) == 1
    assert [panel.props(label)["text"] for label in labels] == [f"changed {i}" for i in range(5)]


def test_the_poll_catches_unannounced_changes(mirror, qt_app):
    label = QLabel("before")
    panel = mirror(column(label), poll_ms=20)
    QLabel.setText.__wrapped__(label, "after")  # type: ignore[attr-defined]  # bypass the hook
    wait_for(qt_app, lambda: panel.props(label).get("text") == "after")


def test_stop_unregisters(mirror, host: MockHost):
    panel = mirror(column(QLabel("x")))
    panel.mirror.stop()
    assert PANEL not in host.panels


# -- the diff


def n(nid: str, kind: str = "column", children=(), **props) -> dict:
    return {"id": nid, "kind": kind, "props": props, "children": list(children)}


def as_wire_tree(t: dict) -> dict:
    out = {"id": t["id"], "kind": t["kind"]}
    out["props"] = dict(t["props"])
    out["children"] = [as_wire_tree(c) for c in t["children"]]
    return out


def normalise(t: dict) -> dict:
    return {
        "id": t["id"],
        "kind": t["kind"],
        "props": t.get("props", {}),
        "children": [normalise(c) for c in t.get("children", [])],
    }


def apply_and_compare(old: dict, new: dict) -> list[dict]:
    ops = diff(old, new)
    assert normalise(apply_patches(as_wire_tree(old), ops)) == normalise(new), ops
    return ops


def test_diff_sets_changed_and_removed_props():
    ops = apply_and_compare(
        n("r", children=[n("a", "label", text="x", wrap=True)]),
        n("r", children=[n("a", "label", text="y")]),
    )
    assert ops == [{"op": "set", "id": "a", "props": {"text": "y", "wrap": None}}]
    assert diff(n("r", text="x"), n("r", text="x")) == []


def test_diff_reorders_inserts_and_removes():
    old = n("r", children=[n("a"), n("b"), n("c")])
    new = n("r", children=[n("c"), n("d", "label", text="new"), n("a")])
    ops = apply_and_compare(old, new)
    assert {op["op"] for op in ops} == {"remove", "move", "insert"}


def test_diff_moves_between_parents_and_changes_kind():
    old = n("r", children=[n("p", children=[n("x", "label", text="1")]), n("q"), n("k", "label")])
    new = n("r", children=[n("p"), n("q", children=[n("x", "label", text="1")]), n("k", "button")])
    ops = apply_and_compare(old, new)
    assert ops.index({"op": "remove", "id": "x"}) < min(
        i for i, op in enumerate(ops) if op["op"] == "insert"
    )


def test_diff_replaces_a_different_root():
    assert diff(n("r"), n("s"))[0]["op"] == "replace"


def test_diff_forces_props_the_user_just_set():
    tree = n("r", children=[n("a", "checkbox", checked=True, text="x")])
    assert diff(tree, tree, {"a"}) == [
        {"op": "set", "id": "a", "props": {"checked": True, "text": "x"}}
    ]
