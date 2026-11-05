"""Run upstream's own unit tests against the ``krita`` stand-in and the mock host.

Load as a pytest plugin before upstream's conftest imports ``ai_diffusion``:

    python -m pytest -p tests.photocraft.upstream_shim tests/test_layer.py tests/test_document.py
        tests/test_persistence.py tests/test_model.py tests/photocraft_upstream

(one command, wrapped here). ``tests/photocraft_upstream`` holds this project's tests of
upstream's code on the stand-in.

It installs ``photocraft_host.krita`` as ``krita`` in place of upstream's mock
(``tests/mock/krita.py``), connected to a :class:`MockHost`. Upstream's tests make documents with
``krita.Document()``; here that opens a document in the mock host (a checkerboard background,
as upstream's mock has) and returns the stand-in's document for it. ``IS_MOCK`` stays set, so
upstream keeps its test behaviour (its data folder beside the source, no Krita version check).
"""

from __future__ import annotations

import importlib.machinery
import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import photocraft_host.krita as shim
from photocraft_host.transport import Transport

from .mock_host import MockHost, MockLayer

#: Upstream tests that check behaviour of upstream's mock rather than of upstream's code, or
#: states PhotoCraft never reaches. What they would cover is in this project's own shim tests.
MOCK_ONLY = {
    "test_selection_bounds_changed": "sets the mock's private _selection",
    "test_current_time_changed": "sets the mock's private _current_time (animation is deferred)",
    "test_active_not_in_document_list_yet": (
        "an active document Krita has not listed yet; PhotoCraft lists a document once it is open"
    ),
    "test_active_not_in_tree_falls_back_to_last_active": (
        "an active layer outside the layer tree, which PhotoCraft never reports"
    ),
    "test_active_after_close_and_reopen": (
        "closes a document from the plug-in, which upstream never does and PhotoCraft has no request for"
    ),
    "test_layer_removed": (
        "deletes a document's only layer: PhotoCraft then has no active layer, and upstream's "
        "layer poller waits for one before it reports changes"
    ),
    "test_active_layer_changes": (
        "expects adding a layer to leave the active layer as it was; in Krita and PhotoCraft the "
        "new layer becomes active (upstream's RestoreActiveLayer handles it)"
    ),
    "test_write_pixels": (
        "expects a layer's bounds to keep pixels cleared to transparent; PhotoCraft reports the "
        "bounds of the layer's content"
    ),
}

_host = MockHost()
_transport = Transport(_host.plugin_reader, _host.plugin_writer)
_transport.start()


def _checkerboard(width: int, height: int, square: int = 32) -> bytearray:
    """BGRA bytes of the neutral checkerboard upstream's mock documents start with."""
    light, dark = bytes([210, 210, 210, 255]), bytes([170, 170, 170, 255])
    out = bytearray()
    for y in range(height):
        for x in range(width):
            out += light if ((x // square) + (y // square)) % 2 == 0 else dark
    return out


def _open(name: str, width: int = 512, height: int = 512):
    return _host.add_document(
        name, width, height, [MockLayer("Background", pixels=_checkerboard(width, height))]
    )


def _document(width: int = 512, height: int = 512) -> shim.Document:
    """Open a document in the mock host and return the stand-in's document for it."""
    return open_document("Test", width, height)


def open_document(
    name: str, width: int = 512, height: int = 512, mode: str = "rgb", depth: str = "u8"
) -> shim.Document:
    """Open a document in the mock host, in PhotoCraft's colour ``mode`` and ``depth``, and
    return the stand-in's document for it (for this project's tests of upstream code)."""
    doc = _open(name, width, height)
    doc.mode, doc.depth = mode, depth
    host = shim.Krita.instance()._host
    assert host is not None
    info, _ = host.call("doc.info", {"doc": doc.id})
    return host._add(info)


def _install():
    module = types.ModuleType("krita")
    # ai_diffusion/__init__.py probes with importlib.util.find_spec, which needs a spec.
    module.__spec__ = importlib.machinery.ModuleSpec("krita", None)
    for name in shim.__all__:
        setattr(module, name, getattr(shim, name))
    module.IS_MOCK = True  # type: ignore[attr-defined]
    module.Document = _document  # type: ignore[attr-defined]
    sys.modules["krita"] = module
    _host.open_document = lambda path: _open(os.path.basename(path) or "Untitled")


_install()


@pytest.fixture(autouse=True)
def photocraft_connection(reset_krita_state):
    """Connect each test's fresh ``Krita`` singleton (upstream's ``reset_krita_state`` makes a new
    one per test) to a mock PhotoCraft with no documents open, as upstream's mock starts."""
    _host.reset()
    _transport._listeners.clear()
    shim.attach(_transport, "test")
    yield


def pytest_collection_modifyitems(config, items):
    for item in items:
        reason = MOCK_ONLY.get(item.name)
        if reason:
            item.add_marker(pytest.mark.skip(reason=f"upstream mock only: {reason}"))
