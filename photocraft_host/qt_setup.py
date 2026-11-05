"""Qt settings the plug-in process needs before upstream's code runs.

The plug-in runs Qt headless (the ``offscreen`` platform), which on Windows looks for fonts only in
Qt's own font folder, empty in the PyQt6 wheels: every text Qt draws comes out as empty boxes,
such as the Generate button the mirror sends as an image. :func:`configure_fonts` points it at
the system's fonts.
"""

from __future__ import annotations

import ntpath
import sys
from collections.abc import MutableMapping


def configure_fonts(environ: MutableMapping[str, str], platform: str = sys.platform) -> str | None:
    """On Windows, point Qt's offscreen platform at the system font folder unless
    ``QT_QPA_FONTDIR`` is already set. Call before the ``QApplication`` exists.

    Returns the folder set, or ``None`` when nothing was changed (another platform, where Qt
    finds the system's fonts itself, or a folder set explicitly)."""
    if platform != "win32" or environ.get("QT_QPA_FONTDIR"):
        return None
    windows = environ.get("WINDIR") or environ.get("SystemRoot") or r"C:\Windows"
    folder = ntpath.join(windows, "Fonts")  # a Windows path, wherever the tests run
    environ["QT_QPA_FONTDIR"] = folder
    return folder
