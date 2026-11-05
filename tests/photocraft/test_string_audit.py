"""Where the plug-in's UI may say "Krita" (TASK-44, REQ-38.0.4, 38.3).

Every string the user can see is collected: text passed to ``_()`` and to Qt widgets' text,
title and tooltip calls in the plug-in's Python, the translation catalogs, and the action texts.
"Krita" may appear only nominatively: "Krita AI Diffusion" (importing from it, detecting it,
and crediting it), the ComfyUI node "Krita Style & Prompt" a workflow must name, and the
detection and import modules, which describe where Krita keeps things.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCES = [REPO / "ai_diffusion", REPO / "photocraft_host"]
SKIPPED = {"debugpy", "websockets", "__pycache__"}
#: Modules about Krita AI Diffusion's installs: detection and import context throughout.
DETECTION = {"photocraft_host/krita_reuse.py", "photocraft_host/krita_reuse_widget.py"}
UI_CALLS = {
    "_",
    "translate",
    "QLabel",
    "QPushButton",
    "QCheckBox",
    "QToolButton",
    "QGroupBox",
    "QAction",
}
UI_METHODS = {
    "setText",
    "setToolTip",
    "setWindowTitle",
    "setPlaceholderText",
    "addItem",
    "setTitle",
}
UI_MESSAGES = {"information", "warning", "critical", "question"}
# "Krita Style & Prompt" is the node's name; some catalogs translate its last words.
ALLOWED = re.compile(r"Krita(?= AI Diffusion| Style)")


def _strings(node: ast.AST) -> list[str]:
    """The literal text in an argument: a string, or an f-string's literal parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
    if isinstance(node, ast.BinOp):
        return _strings(node.left) + _strings(node.right)
    return []


def _ui_strings(path: Path) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else ""
        )
        message_box = (
            name in UI_MESSAGES
            and isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "QMessageBox"
        )
        if name in UI_CALLS or name in UI_METHODS or message_box:
            for arg in [*node.args, *(k.value for k in node.keywords)]:
                found += [(node.lineno, s) for s in _strings(arg)]
    return found


def _python_files() -> list[Path]:
    return [
        p
        for root in SOURCES
        for p in sorted(root.rglob("*.py"))
        if not SKIPPED & set(p.relative_to(REPO).parts)
    ]


def _offending(text: str) -> bool:
    return "Krita" in ALLOWED.sub("", text)


def test_ui_strings_in_the_code():
    found = []
    for path in _python_files():
        relative = path.relative_to(REPO).as_posix()
        if relative in DETECTION:
            continue
        found += [f"{relative}:{line}: {s!r}" for line, s in _ui_strings(path) if _offending(s)]
    assert found == []


def test_the_catalogs():
    found = []
    for path in sorted((REPO / "ai_diffusion" / "language").glob("*.json")):
        for key, value in json.loads(path.read_text(encoding="utf-8"))["translations"].items():
            for text in (key, value or ""):
                if _offending(text):
                    found.append(f"{path.name}: {text!r}")
    assert found == []


def test_the_action_texts():
    action = (REPO / "ai_diffusion" / "ai_diffusion.action").read_text(encoding="utf-8")
    texts = re.findall(r"<(?:text|toolTip|whatsThis)>(.*?)</", action)
    assert texts and not [t for t in texts if _offending(t)]


def test_the_audit_sees_ui_strings(tmp_path: Path):
    """The collector finds the kinds of text it is meant to (so an empty result means
    something)."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "label = QLabel(_('Restart Krita') + ' now')\n"
        "button.setToolTip(f'Krita {x}')\n"
        "QMessageBox.warning(None, 'Title', 'Krita AI Diffusion found')\n"
    )
    strings = [s for _, s in _ui_strings(sample)]
    assert sorted(s for s in strings if _offending(s)) == ["Krita ", "Restart Krita"]
    logged = tmp_path / "logged.py"
    logged.write_text("log.warning('Krita resize output')\n")
    assert _ui_strings(logged) == [], "log messages are not UI text"
