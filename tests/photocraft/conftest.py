"""Shared test setup for this project's tests.

Qt runs headless (the plug-in never opens a window), so the offscreen platform is
selected before PyQt6 is imported anywhere. One ``QApplication`` is created for
the whole session because the Qt mirror needs widget support and Qt allows only
one application object per process.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_qt_app = QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    """Return the session's QApplication, for tests that need to process Qt events."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    return app


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root, for tests that read fixtures or upstream files."""
    return REPO_ROOT
