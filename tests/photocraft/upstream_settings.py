"""Use upstream's settings dialog through the Qt mirror, as PhotoCraft shows it (TASK-36).

On a fresh plug-in data folder: record the ``settings.json`` written on first run; open
"Configure Image Diffusion"; choose Custom ComfyUI, enter the address of a stand-in ComfyUI
server and connect; change every control on the Diffusion, Interface, Performance and Plugin
pages; read the settings back as a restarted plug-in would; press Restore Defaults; and check
the recently used document settings. Every input goes through the mirror, as PhotoCraft sends
it. Prints what happened as JSON; run in its own process by ``test_upstream_settings.py``.

    python tests/photocraft/upstream_settings.py <data-dir>
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from PyQt6.QtWidgets import QApplication, QPushButton, QWidget


def _plain(value: Any) -> Any:
    """A value as JSON can carry it (enums by name, as settings.json stores them)."""
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def main() -> int:
    data_dir = Path(sys.argv[1])
    app = QApplication([])

    from photocraft_host import main as plugin_main
    from photocraft_host import qt_mirror
    from photocraft_host.transport import Transport
    from tests.photocraft.mock_host import MockHost, find_widget
    from tests.photocraft.stub_comfy import StubComfy

    plugin_main.install_krita_shim()
    import krita

    host = MockHost()
    host.add_document("Settings", 512, 512)
    # PhotoCraft's message box (the NSFW filter warning): the user presses its first button.
    host.answers["dialog.message"] = lambda p, _: {"button": (p.get("buttons") or [None])[0]}
    link = Transport(host.plugin_reader, host.plugin_writer)
    link.start()
    krita.attach(link, "test", locale="en", data_dir=data_dir)  # pyright: ignore[reportAttributeAccessIssue]
    qt_mirror.install(link)

    from ai_diffusion import eventloop
    from ai_diffusion.model.connection import ConnectionState
    from ai_diffusion.model.root import root
    from ai_diffusion.settings import PerformancePreset, Setting, Settings, settings
    from ai_diffusion.ui.settings import SettingsDialog
    from ai_diffusion.ui.settings_widgets import (
        ComboBoxSetting,
        FileListSetting,
        LineEditSetting,
        SliderSetting,
        SpinBoxSetting,
        SwitchSetting,
        TextSetting,
    )
    from ai_diffusion.util import encode_json
    from photocraft_host.qt_mirror import dialogs

    results: dict[str, Any] = {}
    eventloop.setup()
    settings.load()
    first_run = json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))
    defaults = {k[1:]: v.default for k, v in Settings.__dict__.items() if isinstance(v, Setting)}
    results["first_run"] = sorted(first_run)
    results["first_run_not_default"] = [
        key
        for key, value in first_run.items()
        if json.loads(json.dumps(defaults[key], default=encode_json)) != value
    ]
    settings.auto_update = False  # no update check over the network
    settings.save()
    root.init()

    def wait(condition: Callable[[], bool], timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                return False
            app.processEvents()
            time.sleep(0.005)
        return True

    dialog = SettingsDialog(root.server)
    dialog.show()
    wait(lambda: bool(host.dialogs))
    dialog_id = next(iter(host.dialogs))
    mirror = dialogs._open[id(dialog)]
    results["dialog_title"] = host.dialogs[dialog_id].get("title")

    def send(widget: QWidget, kind: str, value: Any):
        mirror.flush()
        handled: list[bool] = []
        link.on("dialog.input", lambda *_: handled.append(True))
        host.send_event(
            "dialog.input",
            {
                "dialogId": dialog_id,
                "nodeId": mirror.node_id(widget),
                "kind": kind,
                "value": value,
                "modifiers": {},
            },
        )
        wait(lambda: bool(handled))
        app.processEvents()
        mirror.flush()

    def click(widget: QWidget):
        send(widget, "click", True)

    def show_page(text: str):
        tree = host.dialogs[dialog_id]["tree"]
        node = find_widget(tree, mirror.node_id(dialog._list)) or {}
        item = next(i for i in node["props"]["items"] if i.get("text") == text)
        send(dialog._list, "select", [item["id"]])

    # -- Connection: Custom ComfyUI, its address, Connect (no Krita AI Diffusion anywhere)
    stub = StubComfy().start()
    setup = dialog.connection._setup_widget
    custom = next(b for b in setup.findChildren(QPushButton) if b.text() == "Connect via URL")
    click(custom)
    results["server_mode"] = settings.server_mode.name
    send(dialog.connection._server_url, "change", stub.url)
    results["server_url"] = settings.server_url == stub.url
    click(dialog.connection._connect_button)
    wait(lambda: root.connection.state in (ConnectionState.connected, ConnectionState.error), 30)
    results["connection"] = root.connection.state.name
    results["connection_error"] = root.connection.error
    results["connected_to"] = [r for r in stub.requests if r.startswith("/system_stats")]
    results["supported_workloads"] = dialog.connection._supported_workloads.text()
    translation = dialog.interface._widgets["prompt_translation"]
    assert isinstance(translation, ComboBoxSetting)
    wait(lambda: translation._combo.count() > 1)  # the languages the server offers

    # -- every control on the other pages
    def change(widget: QWidget) -> tuple[QWidget, str, Any, Any]:
        """The control to use, the input PhotoCraft sends, and the value the setting should get."""
        if isinstance(widget, SliderSetting):
            spin = widget._spin
            new = spin.minimum() if spin.value() != spin.minimum() else spin.maximum()
            return spin, "change", new, new
        if isinstance(widget, SpinBoxSetting):
            spin = widget._spinbox
            new = spin.minimum() if spin.value() != spin.minimum() else spin.maximum()
            return spin, "change", new, new
        if isinstance(widget, ComboBoxSetting):
            combo = widget._combo
            index = next(i for i in range(combo.count()) if i != combo.currentIndex())
            data = combo.itemData(index)
            return combo, "change", index, widget._enum_type[data] if widget._enum_type else data
        if isinstance(widget, SwitchSetting):
            click_at = {"x": 4, "y": 4, "button": "left", "action": "click"}
            return widget._switch, "pointer", click_at, not widget.value
        if isinstance(widget, FileListSetting):
            name, checkbox = widget._list_items[0]
            return checkbox, "change", True, [name]
        if isinstance(widget, (TextSetting, LineEditSetting)):
            return widget._edit, "change", "photocraft", "photocraft"
        raise TypeError(type(widget).__name__)

    changes: dict[str, dict[str, Any]] = {}

    def use(name: str, widget: QWidget):
        control, kind, value, expected = change(widget)
        send(control, kind, value)
        changes[name] = {"expected": _plain(expected), "actual": _plain(getattr(settings, name))}

    pages = [
        ("Diffusion", dialog.diffusion),
        ("Interface", dialog.interface),
        ("Performance", dialog.performance),
    ]
    for page, tab in pages:
        show_page(page)
        for name, widget in tab._widgets.items():
            use(name, widget)

    perf = dialog.performance
    for name, history in (
        ("history_size", perf._history_size),
        ("history_storage", perf._history_storage),
    ):
        spin = history._history_size
        new = spin.value() + spin.singleStep()
        send(spin, "change", new)
        changes[name] = {"expected": new, "actual": getattr(settings, name)}
    custom_preset = list(PerformancePreset).index(PerformancePreset.custom)
    send(perf._performance_preset, "change", custom_preset)
    changes["performance_preset"] = {
        "expected": "custom",
        "actual": settings.performance_preset.name,
    }
    for name, widget in (
        ("batch_size", perf._batch_size),
        ("resolution_multiplier", perf._resolution_multiplier),
        ("max_pixel_count", perf._max_pixel_count),
        ("tiled_vae", perf._tiled_vae),
        ("dynamic_caching", perf._dynamic_caching),
        ("multi_threading", perf._multi_threading),
    ):
        use(name, widget)

    show_page("Plugin")
    send(dialog.about._update_checkbox, "change", True)
    changes["auto_update"] = {"expected": True, "actual": settings.auto_update}
    results["changes"] = changes

    # -- a restarted plug-in reads the same values
    restarted = Settings()
    restarted.load()
    results["after_restart"] = {
        name: _plain(getattr(restarted, name)) for name in [*changes, "server_mode", "server_url"]
    }
    results["changed"] = {
        name: _plain(getattr(settings, name)) for name in results["after_restart"]
    }

    # -- Restore Defaults, on the Interface page
    show_page("Interface")
    click(dialog._restore_button)
    results["restored"] = {
        name: {
            "setting": _plain(getattr(settings, name)) == _plain(defaults[name]),
            "control": _plain(widget.value) == _plain(defaults[name]),
        }
        for name, widget in dialog.interface._widgets.items()
        if widget.enabled
    }
    results["restored_everywhere"] = [
        name for name in changes if _plain(getattr(settings, name)) != _plain(defaults[name])
    ]

    # -- model licenses, shown before downloading (Restore Defaults chose the managed server)
    from ai_diffusion.ui.server import PackageGroupWidget, WorkloadsTab

    show_page("Connection")
    workloads = dialog.findChildren(WorkloadsTab)[0]
    shown = {}
    for model in workloads._models:
        node = find_widget(host.dialogs[dialog_id]["tree"], mirror.node_id(model.license)) or {}
        shown[model.label] = node.get("props", {})
    results["workload_licenses"] = shown
    packages = {}
    for group in dialog.findChildren(PackageGroupWidget):
        for item in group._items:
            packages[group._package_name(item.package)] = item.label.text()
    results["package_licenses"] = packages

    # -- recently used document settings apply to the next new document
    model = root.model_for_active_document()
    assert model is not None
    model.batch_count = 3
    stored = json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))
    results["document_defaults"] = stored.get("document_defaults", {}).get("batch_count")
    second = host.add_document("Second", 256, 256)
    host.send_event("document.opened", {"doc": second.id})
    wait(lambda: any(d._id == second.id for d in krita.Krita.instance().documents()))  # pyright: ignore[reportAttributeAccessIssue]
    doc = next(d for d in krita.Krita.instance().documents() if d._id == second.id)  # pyright: ignore[reportAttributeAccessIssue]
    krita.Krita.instance().setActiveDocument(doc)
    new_model = root.model_for_active_document()
    results["new_document_batch_count"] = new_model.batch_count if new_model else None

    stub.stop()
    print(json.dumps(results, default=str), flush=True)
    mirror.stop()
    host.close()
    return 0


if __name__ == "__main__":
    code = main()
    os._exit(code)  # see workspace_snapshots.py: no interpreter teardown
