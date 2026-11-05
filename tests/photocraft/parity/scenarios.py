"""The graph-parity scenario matrix.

A scenario is a document plus panel settings. ``build_document`` uses only the
``krita`` API, so the same function later runs on this project's ``krita`` shim
over the mock host. ``setup_model`` uses only upstream's own ``DocumentModel``
API, which both sides run unchanged. Any difference in the resulting
``WorkflowInput`` or ComfyUI prompt therefore comes from the host adapter, which
is exactly what the parity tests are meant to catch.

Pixel content is drawn with ``QPainter`` into ``QImage`` buffers so it is fully
deterministic and needs no image files.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtCore import QByteArray, QPointF, QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter

#: Architectures covered, by upstream ``Arch`` member name. ``flux_k`` (Flux Kontext) is an
#: edit-only architecture; ``flux2_4b`` (Flux 2 Klein) supports both generation and editing.
ARCHS = ["sd15", "sdxl", "illu", "flux", "flux_k", "flux2_4b", "zimage"]

#: Inpaint modes, by upstream ``InpaintMode`` member name.
INPAINT_MODES = [
    "automatic",
    "fill",
    "expand",
    "add_object",
    "remove_object",
    "replace_background",
    "custom",
]

DOC_SIZE = (512, 512)
SEED = 1234
PROMPT = "a lighthouse on a cliff at dusk"


@dataclass
class Scenario:
    """One parity case: how to build the document, how to set up the panel, and what to run."""

    id: str
    arch: str
    #: ``generate`` (the Generate button), ``upscale`` or ``control_image``.
    action: str = "generate"
    strength: float = 1.0
    inpaint_mode: str | None = None
    #: ``None``, ``("rect", x, y, w, h)`` or ``("ellipse", x, y, w, h)``.
    selection: tuple | None = None
    regions: list[dict[str, Any]] = field(default_factory=list)
    controls: list[dict[str, Any]] = field(default_factory=list)
    upscale: dict[str, Any] = field(default_factory=dict)
    size: tuple[int, int] = DOC_SIZE

    def describe(self) -> dict[str, Any]:
        """Return the scenario's parameters as plain JSON data, stored next to its fixture."""
        return {
            "id": self.id,
            "arch": self.arch,
            "action": self.action,
            "strength": self.strength,
            "inpaint_mode": self.inpaint_mode,
            "selection": list(self.selection) if self.selection else None,
            "regions": self.regions,
            "controls": self.controls,
            "upscale": self.upscale,
            "size": list(self.size),
        }


# --- pixel content ---------------------------------------------------------------------------


def _bgra_bytes(image: QImage) -> QByteArray:
    """Return an ARGB32 image's pixels as tightly packed BGRA bytes, as Krita's API uses."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    bits = image.constBits()
    assert bits is not None
    raw = bits.asstring(image.sizeInBytes())
    stride = image.bytesPerLine()
    packed = b"".join(raw[y * stride : y * stride + width * 4] for y in range(height))
    return QByteArray(packed)


def background_image(width: int, height: int) -> QImage:
    """A sky-to-sea gradient with a dark cliff shape, so every region of the canvas differs."""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(0, height))
    gradient.setColorAt(0.0, QColor(40, 60, 140))
    gradient.setColorAt(0.6, QColor(230, 150, 90))
    gradient.setColorAt(1.0, QColor(20, 70, 110))
    painter.fillRect(0, 0, width, height, QBrush(gradient))
    painter.setBrush(QColor(50, 40, 35))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRect(0, int(height * 0.55), int(width * 0.45), height)
    painter.end()
    return image


def blob_image(width: int, height: int, rect: QRect, color: QColor) -> QImage:
    """A transparent layer with one opaque ellipse: used as region and control layer content."""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(rect)
    painter.end()
    return image


def selection_mask(shape: tuple) -> tuple[QByteArray, int, int, int, int]:
    """An 8-bit selection mask for a rectangle or ellipse, cropped to the selected pixels.

    Returns ``(data, x, y, width, height)``. Krita reports a selection's tight bounds
    (``Selection.x()``, ``width()`` ...), and upstream decides between Fill and Expand and
    places the inpaint area from them, so the mask is stored at exactly those bounds: an
    ellipse Qt draws without antialiasing doesn't reach every edge of its rectangle, and
    upstream's mock reports whatever rectangle it is given.
    """
    kind, x, y, w, h = shape
    image = QImage(w, h, QImage.Format.Format_Grayscale8)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setBrush(QColor(255, 255, 255))
    painter.setPen(Qt.PenStyle.NoPen)
    if kind == "rect":
        painter.drawRect(0, 0, w, h)
    else:
        painter.drawEllipse(0, 0, w, h)
    painter.end()
    bits = image.constBits()
    assert bits is not None
    raw = bits.asstring(image.sizeInBytes())
    stride = image.bytesPerLine()
    rows = [raw[r * stride : r * stride + w] for r in range(h)]
    used_rows = [r for r in range(h) if any(rows[r])]
    used_cols = [c for c in range(w) if any(rows[r][c] for r in used_rows)]
    top, bottom = used_rows[0], used_rows[-1] + 1
    left, right = used_cols[0], used_cols[-1] + 1
    data = QByteArray(b"".join(rows[r][left:right] for r in range(top, bottom)))
    return data, x + left, y + top, right - left, bottom - top


# --- building a scenario --------------------------------------------------------------------


def build_document(scenario: Scenario, krita: Any):
    """Create the scenario's document through the ``krita`` API and make it active.

    ``krita`` is the module providing ``Krita`` and ``Selection`` (upstream's mock, or this
    project's shim). Returns the krita document.
    """
    width, height = scenario.size
    app = krita.Krita.instance()
    doc = app.openDocument(scenario.id)
    if (doc.width(), doc.height()) != (width, height):
        doc.resizeImage(0, 0, width, height)
    background = doc.rootNode().childNodes()[0]
    background.setPixelData(_bgra_bytes(background_image(width, height)), 0, 0, width, height)

    if scenario.selection:
        selection = krita.Selection()
        selection.setPixelData(*selection_mask(scenario.selection))
        doc.setSelection(selection)

    app.setActiveDocument(doc)
    return doc


def setup_model(scenario: Scenario, model: Any, style: Any, api: Any):
    """Configure upstream's ``DocumentModel`` for the scenario, using only upstream's model API.

    ``api`` bundles the upstream enums needed here (``InpaintMode``, ``ControlMode``), passed
    in so this module never imports ``ai_diffusion`` itself.
    """
    width, height = scenario.size
    model.style = style
    model.fixed_seed = True
    model.seed = SEED
    model.strength = scenario.strength
    model.regions.positive = PROMPT
    model.regions.negative = "blurry"
    if scenario.inpaint_mode:
        model.inpaint.mode = api.InpaintMode[scenario.inpaint_mode]

    for index, spec in enumerate(scenario.regions):
        region = model.regions.create_region(group=False)
        layer = region.layers[0]
        x, y, w, h = spec["ellipse"]
        image = api.Image(blob_image(width, height, QRect(x, y, w, h), QColor(*spec["color"])))
        layer.write_pixels(image, api.Bounds(0, 0, width, height))
        region.positive = spec["prompt"]
        model.layers.active = model.layers.root.child_layers[0]
        assert index + 1 == len(model.regions)

    for spec in scenario.controls:
        layer = model.layers.create(f"Control {spec['mode']}")
        x, y, w, h = spec.get("ellipse", (96, 96, 320, 320))
        image = api.Image(blob_image(width, height, QRect(x, y, w, h), QColor(20, 20, 20)))
        layer.write_pixels(image, api.Bounds(0, 0, width, height))
        model.layers.active = layer
        control = model.regions.control.emplace()
        control.mode = api.ControlMode[spec["mode"]]
        control.layer_id = layer.id
        if "strength" in spec:
            control.use_custom_strength = True
            control.strength = int(spec["strength"] * 50)

    if scenario.action == "upscale":
        model.upscale.factor = scenario.upscale.get("factor", 2.0)
        model.upscale.use_diffusion = scenario.upscale.get("diffusion", False)
        if "strength" in scenario.upscale:
            model.upscale.strength = scenario.upscale["strength"]


# --- the matrix ---------------------------------------------------------------------------------

_SELECTION = ("ellipse", 160, 120, 200, 180)
_EDGE_SELECTION = ("rect", 352, 0, 160, 512)  # touches the canvas edge: auto-detects Expand


def _matrix() -> list[Scenario]:
    result: list[Scenario] = []
    for arch in ARCHS:
        result.extend((
            Scenario(f"{arch}-generate", arch),
            Scenario(f"{arch}-refine", arch, strength=0.6),
            Scenario(f"{arch}-refine-region", arch, strength=0.6, selection=_SELECTION),
        ))
        for mode in INPAINT_MODES:
            result.append(
                Scenario(f"{arch}-inpaint-{mode}", arch, inpaint_mode=mode, selection=_SELECTION)
            )
        result.append(
            Scenario(
                f"{arch}-inpaint-automatic-edge",
                arch,
                inpaint_mode="automatic",
                selection=_EDGE_SELECTION,
            )
        )

    regions = [
        {"prompt": "a red sailboat", "ellipse": (40, 260, 200, 160), "color": (200, 30, 30)},
        {"prompt": "a flock of birds", "ellipse": (260, 40, 220, 140), "color": (30, 200, 30)},
        {"prompt": "a stone tower", "ellipse": (300, 200, 160, 260), "color": (30, 30, 200)},
    ]
    for arch in ["sd15", "sdxl"]:
        result.extend((
            Scenario(f"{arch}-regions", arch, regions=regions),
            Scenario(f"{arch}-regions-refine", arch, strength=0.5, regions=regions),
        ))
    dominant = [{"prompt": "a calm sea", "ellipse": (-200, -200, 912, 912), "color": (9, 9, 9)}]
    result.append(Scenario("sdxl-regions-dominant", "sdxl", regions=dominant))

    control_sets: dict[str, list[dict[str, Any]]] = {
        "depth": [{"mode": "depth"}],
        "depth-reference": [{"mode": "depth"}, {"mode": "reference", "strength": 0.8}],
        "scribble": [{"mode": "scribble", "strength": 0.6}],
        "canny": [{"mode": "canny_edge"}],
        "pose": [{"mode": "pose"}],
        "style-composition": [{"mode": "style"}, {"mode": "composition"}],
    }
    for arch in ["sd15", "sdxl", "flux", "zimage"]:
        for name, controls in control_sets.items():
            result.append(Scenario(f"{arch}-control-{name}", arch, controls=controls))

    for arch in ["sd15", "sdxl", "flux"]:
        result.extend((
            Scenario(f"{arch}-upscale-simple", arch, action="upscale", upscale={"factor": 2.0}),
            Scenario(
                f"{arch}-upscale-tiled",
                arch,
                action="upscale",
                upscale={"factor": 2.0, "diffusion": True, "strength": 0.3},
            ),
        ))
    result.append(
        Scenario(
            "sdxl-refine-tiled-1x",
            "sdxl",
            action="upscale",
            upscale={"factor": 1.0, "diffusion": True, "strength": 0.4},
        )
    )

    for mode in ["canny_edge", "depth", "scribble", "line_art", "pose", "segmentation"]:
        result.append(
            Scenario(
                f"sdxl-control-image-{mode}",
                "sdxl",
                action="control_image",
                controls=[{"mode": mode}],
            )
        )
    return result


SCENARIOS: list[Scenario] = _matrix()
SCENARIOS_BY_ID: dict[str, Scenario] = {s.id: s for s in SCENARIOS}
StyleFactory = Callable[[str], Any]
