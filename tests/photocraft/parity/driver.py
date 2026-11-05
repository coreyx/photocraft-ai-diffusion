"""Run the parity scenarios against an ``ai_diffusion`` checkout and write or check fixtures.

Run it as a script with the checkout to test as ``--source``. It puts that checkout
(and its ``tests/mock`` folder, which supplies upstream's mock ``krita`` module)
at the front of ``sys.path``, so the scenarios exercise that checkout's code and
nothing else::

    python tests/photocraft/parity/driver.py --source <checkout> --write <fixtures dir>
    python tests/photocraft/parity/driver.py --source <checkout> --check <fixtures dir>

For each scenario it builds the document through the ``krita`` API, sets up a
``DocumentModel`` with a mock client that reports the full model catalog, runs the
scenario's action, and records the ``WorkflowInput`` the model enqueued and the
ComfyUI prompt ``workflow.create`` builds from it. A scenario upstream refuses
(for example an unsupported control mode for an architecture) records the error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _prepare_path(source: Path) -> None:
    """Make ``source`` the only place ``ai_diffusion`` and ``krita`` are imported from."""
    here = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != here.parents[2]]
    sys.path.insert(0, str(source / "tests"))
    sys.path.insert(0, str(source / "tests" / "mock"))
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(here))


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--source", type=Path, required=True, help="ai_diffusion checkout to run")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path, help="write fixtures into this folder")
    group.add_argument("--check", type=Path, help="compare against fixtures in this folder")
    parser.add_argument("--only", nargs="*", help="scenario ids to run (default: all)")
    parser.add_argument(
        "--host",
        choices=["mock", "photocraft"],
        default="mock",
        help="upstream's mock krita (default), or this project's krita stand-in on the mock PhotoCraft",
    )
    args = parser.parse_args(argv)

    _prepare_path(args.source.resolve())
    reset = _install_photocraft() if args.host == "photocraft" else None
    runner = _Runner(reset)
    return runner.run(args.write, args.check, args.only)


def _krita_fidelity(krita: Any) -> None:
    """Give upstream's test mock two behaviours of real Krita that its stubs leave out, and that
    the scenarios depend on. Only the mock (test scaffolding) is patched; upstream's
    ``ai_diffusion`` code runs unmodified.

    - ``Node.bounds()`` is a layer's exact bounds: its non-transparent pixels (for a group, its
      children's), where the mock reports the whole area ever written. Regions and reference
      control images are cut to these bounds.
    - ``Selection.invert()`` inverts the selection over the image, where the mock does
      nothing. Replace Background inpaints the inverted selection.
    """
    from PyQt6.QtCore import QByteArray, QRect

    def exact_bounds(node) -> tuple[int, int, int, int]:
        children = [c for c in node.childNodes() if c.type() != "transparencymask"]
        if node.type() == "grouplayer" and children:
            boxes = [b for b in (exact_bounds(c) for c in children) if b[2] and b[3]]
            if not boxes:
                return 0, 0, 0, 0
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
            return x0, y0, x1 - x0, y1 - y0
        x, y, w, h = node._bounds
        data = bytes(node._pixel_data)
        if not w or not h or len(data) < w * h * 4:
            return x, y, w, h
        alpha = data[3::4]
        rows = [r for r in range(h) if any(alpha[r * w : (r + 1) * w])]
        if not rows:
            return 0, 0, 0, 0
        cols = [c for c in range(w) if any(alpha[r * w + c] for r in rows)]
        return x + cols[0], y + rows[0], cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1

    krita.Node.bounds = lambda self: QRect(*exact_bounds(self))

    original_selection = krita.Document.selection

    def selection(self):
        result = original_selection(self)
        if result is not None:
            result._image = (self.width(), self.height())
        return result

    original_duplicate = krita.Selection.duplicate

    def duplicate(self):
        copy = original_duplicate(self)
        copy._image = getattr(self, "_image", None)
        return copy

    def invert(self):
        image = getattr(self, "_image", None)
        if image is None:
            return
        width, height = image
        current = bytes(self.pixelData(0, 0, width, height).data())
        inverted = bytes(255 - v for v in current)
        rows = [r for r in range(height) if any(inverted[r * width : (r + 1) * width])]
        if not rows:
            self._x = self._y = self._width = self._height = 0
            self._data = QByteArray()
            return
        cols = [c for c in range(width) if any(inverted[r * width + c] for r in rows)]
        x0, y0, x1, y1 = cols[0], rows[0], cols[-1] + 1, rows[-1] + 1
        cropped = b"".join(inverted[r * width + x0 : r * width + x1] for r in range(y0, y1))
        self._x, self._y, self._width, self._height = x0, y0, x1 - x0, y1 - y0
        self._data = QByteArray(cropped)

    krita.Document.selection = selection
    krita.Selection.duplicate = duplicate
    krita.Selection.invert = invert


def _install_photocraft():
    """Put the ``krita`` stand-in, on the mock PhotoCraft, where ``import krita`` finds it
    (before upstream's mock), and return the function that reconnects it for a scenario."""
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo))
    from tests.photocraft import upstream_shim

    return upstream_shim.connect_fresh


class _Runner:
    """Imports the selected checkout lazily, after ``sys.path`` points at it."""

    def __init__(self, reset=None) -> None:
        #: Reconnects the krita stand-in before each scenario (``--host photocraft``).
        self._reset = reset
        from PyQt6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])

        # These resolve from the sys.path that _prepare_path set up (the parity folder and the
        # selected checkout's tests/mock), which a type checker running on this file can't see.
        import catalog  # pyright: ignore[reportMissingImports]
        import krita  # pyright: ignore[reportMissingImports]
        import normalize  # pyright: ignore[reportMissingImports]
        import scenarios  # pyright: ignore[reportMissingImports]

        from ai_diffusion import eventloop, util
        from ai_diffusion.backend import workflow
        from ai_diffusion.backend.api import Serializer
        from ai_diffusion.backend.resources import ControlMode
        from ai_diffusion.document import KritaDocument
        from ai_diffusion.image import Bounds, Image
        from ai_diffusion.model.connection import Connection, ConnectionState
        from ai_diffusion.model.custom_workflow import WorkflowCollection
        from ai_diffusion.model.model import DocumentModel, InpaintMode
        from ai_diffusion.model.root import root as plugin_root

        eventloop.setup()
        if reset is None:  # upstream's mock: as Krita behaves where the scenarios depend on it
            _krita_fidelity(krita)
        self.krita = krita
        self.eventloop = eventloop
        self.util = util
        self.workflow = workflow
        self.Serializer = Serializer
        self.KritaDocument = KritaDocument
        self.Connection = Connection
        self.ConnectionState = ConnectionState
        self.WorkflowCollection = WorkflowCollection
        self.DocumentModel = DocumentModel
        self.plugin_root = plugin_root
        self.catalog = catalog
        self.normalize = normalize
        self.scenarios = scenarios
        self.api = argparse.Namespace(
            InpaintMode=InpaintMode, ControlMode=ControlMode, Image=Image, Bounds=Bounds
        )
        self.models = catalog.full_client_models()

    # --- running ---

    def run(self, write: Path | None, check: Path | None, only: list[str] | None) -> int:
        selected = [s for s in self.scenarios.SCENARIOS if not only or s.id in only]
        failures: list[str] = []
        for scenario in selected:
            # Round-trip through JSON so in-memory results compare like the stored fixtures.
            result = json.loads(json.dumps(self._run_coroutine(self._capture(scenario))))
            if write:
                write.mkdir(parents=True, exist_ok=True)
                path = write / f"{scenario.id}.json"
                path.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", "utf-8")
            else:
                assert check is not None
                expected = json.loads((check / f"{scenario.id}.json").read_text("utf-8"))
                problems = self.normalize.diff(expected, result)
                if problems:
                    failures.append(f"{scenario.id}:\n  " + "\n  ".join(problems[:20]))
        print(f"{len(selected)} scenarios, {len(failures)} differ")
        for failure in failures:
            print(failure)
        return 1 if failures else 0

    def _run_coroutine(self, coro):
        task = self.eventloop.run(coro)
        while not task.done():
            self.app.processEvents()
        return task.result()

    async def _capture(self, scenario) -> dict[str, Any]:
        """Run one scenario and return its fixture: description, input and prompt (or error)."""
        self.krita.Krita._instance = None  # pyright: ignore[reportAttributeAccessIssue]
        if self._reset is not None:
            self._reset()
        self.KritaDocument._instances.clear()
        fixture: dict[str, Any] = {"scenario": scenario.describe()}

        doc = self.scenarios.build_document(scenario, self.krita)
        client = self._client()
        connection = self.Connection()
        connection.connect(client)
        for _ in range(200):
            await asyncio.sleep(0)
            if connection.state is self.ConnectionState.connected:
                break
        document = self.KritaDocument.active()
        assert document is not None, "the scenario document did not become active"
        model = self.DocumentModel(document, connection, self.WorkflowCollection(connection))
        connection.message_received.connect(model.handle_message)
        previous = getattr(self.plugin_root, "_connection", None)
        # Upstream's own model tests install the connection on the plugin root the same way.
        self.plugin_root._connection = connection  # pyright: ignore[reportAttributeAccessIssue]
        try:
            style = self._style(scenario.arch)
            self.scenarios.setup_model(scenario, model, style, self.api)
            # Upstream learns about the selection and layer changes from polling timers
            # (20 ms and 500 ms). Let them fire, as they would before a user clicks Generate.
            await asyncio.sleep(0.6)
            self._start(scenario, model)
            for _ in range(400):
                await asyncio.sleep(0)
                if client.enqueued or model.error.message:
                    break
            if client.enqueued:
                work = client.enqueued[0]
                fixture["input"] = self.normalize.normalize_input(work, self.Serializer)
                try:
                    graph = self.workflow.create(work, self.models)
                    fixture["prompt"] = self.normalize.normalize_graph(graph)
                except Exception as e:  # recorded: upstream refusing is part of the behavior
                    fixture["prompt_error"] = f"{type(e).__name__}: {e}"
            else:
                fixture["error"] = model.error.message or "nothing was enqueued"
        except Exception as e:  # a scenario upstream cannot even set up is recorded, not fatal
            fixture["exception"] = f"{type(e).__name__}: {e}"
        finally:
            try:
                await connection.disconnect()
            except asyncio.CancelledError:
                # Upstream's Connection re-raises the cancellation of its message task when
                # it is torn down mid-listen; that is the expected way for it to stop here.
                pass
            self.plugin_root._connection = previous  # pyright: ignore[reportAttributeAccessIssue]
            del doc
        return fixture

    def _start(self, scenario, model) -> None:
        if scenario.action == "generate":
            model.generate()
        elif scenario.action == "upscale":
            model.upscale_image()
        elif scenario.action == "control_image":
            control = model.regions.control[0]
            model.generate_control_layer(control)
        else:
            raise ValueError(f"unknown action {scenario.action!r}")

    def _client(self):
        from mock.client import MockClient  # pyright: ignore[reportMissingImports]

        client = MockClient()
        client.models = self.models
        return client

    def _style(self, arch_name: str):
        """A style for the architecture, set up the way upstream's own workflow tests do it."""
        from ai_diffusion.style import Arch, Style

        arch = Arch[arch_name]
        style = Style(Path(f"parity-{arch_name}.json"))
        style.checkpoints = [self.catalog.checkpoint_for(self.models, arch_name)]
        if not arch.is_sdxl_like:
            style.style_prompt = ""
        if arch.is_flux_like:
            style.sampler = "Flux - Euler simple"
            style.cfg_scale = 3.5
        if arch is Arch.zimage:
            style.sampler = "Flux - Euler simple"
            style.cfg_scale = 1.0
            style.sampler_steps = 8
        if arch.is_flux2:
            style.sampler = "Flux 2 - Euler"
            style.cfg_scale = 1.0
            style.sampler_steps = 5
        return style


if __name__ == "__main__":
    sys.exit(main())
