"""Checks that the development and CI environment matches the plug-in runtime.

These guard the assumptions the rest of the project builds on: Python 3.12,
PyQt6 6.11 running headless, and upstream's vendored websockets submodule being
present (upstream imports it from that path).
"""

import sys
from pathlib import Path

import tomllib
from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QLabel


def test_python_is_312():
    assert sys.version_info[:2] == (3, 12)


def test_qt_is_pinned_to_611(repo_root: Path):
    assert PYQT_VERSION_STR.startswith("6.11.")
    assert QT_VERSION_STR.startswith("6.11.")
    runtime = tomllib.loads((repo_root / "packaging/runtime/pyproject.toml").read_text())
    assert "PyQt6==6.11.*" in runtime["project"]["dependencies"]


def test_qt_runs_offscreen(qt_app: QApplication):
    assert QGuiApplication.platformName() == "offscreen"
    label = QLabel("hello")
    label.resize(80, 20)
    assert not label.grab().isNull()


def test_qimage_painting_works_headless():
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.fillRect(0, 0, 2, 2, 0xFF00FF00)
    painter.end()
    assert image.pixel(0, 0) == 0xFF00FF00
    assert image.pixel(3, 3) == 0


def test_vendored_websockets_submodule_present(repo_root: Path):
    assert (repo_root / "ai_diffusion/websockets/src/websockets/__init__.py").exists()
