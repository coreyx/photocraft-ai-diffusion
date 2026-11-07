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


#: Qt's TLS backend that uses the operating system's own TLS, by ``sys.platform``.
PLATFORM_TLS = {"win32": "schannel", "darwin": "securetransport"}


def use_platform_tls(platform: str = sys.platform) -> str:
    r"""Make the operating system's TLS (schannel on Windows, Secure Transport on macOS) Qt's
    active backend before any request is made. Returns the active backend.

    Qt otherwise prefers its OpenSSL backend whenever it can load an OpenSSL from the DLL search
    path, such as the one in Git for Windows' ``mingw64\bin``. Python's ``ssl``, which the
    plug-in imports through websockets, has already loaded Python's own OpenSSL by then, and two
    OpenSSL builds in one process crash it about 30 seconds after Qt's first HTTPS request
    (``investigations/plugin-crash-after-30-seconds/findings.md``). Linux has no such backend:
    there Qt's choice is left as it is.

    Only the platform's own backend is asked for: Qt logs a warning for each one it doesn't have
    (``investigations/ci-first-push-failures/findings.md``).
    """
    from PyQt6.QtNetwork import QSslSocket

    # Set rather than list first: asking which backends are available can load OpenSSL.
    if (name := PLATFORM_TLS.get(platform)) is not None:
        QSslSocket.setActiveBackend(name)
    return QSslSocket.activeBackend()


def font_family_count() -> int:
    """How many font families Qt found, for the plug-in's start-up log: none means every text Qt
    draws comes out as empty boxes. Needs a ``QGuiApplication``."""
    from PyQt6.QtGui import QFontDatabase

    return len(QFontDatabase.families())
