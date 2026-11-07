"""The Qt set-up the plug-in process does before upstream runs (``photocraft_host.qt_setup``;
spec ``plugin-tls-and-fonts-fix``)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from photocraft_host.qt_setup import configure_fonts, use_platform_tls

HERE = Path(__file__).resolve().parent


def test_windows_gets_the_system_font_folder():
    environ = {"WINDIR": r"D:\Windows"}
    assert configure_fonts(environ, "win32") == r"D:\Windows\Fonts"
    assert environ["QT_QPA_FONTDIR"] == r"D:\Windows\Fonts"
    assert configure_fonts({}, "win32") == r"C:\Windows\Fonts", "the default folder"


def test_a_font_folder_set_explicitly_is_kept():
    environ = {"WINDIR": r"C:\Windows", "QT_QPA_FONTDIR": r"E:\Fonts"}
    assert configure_fonts(environ, "win32") is None
    assert environ["QT_QPA_FONTDIR"] == r"E:\Fonts"


def test_macos_and_linux_are_left_alone():
    for platform in ("darwin", "linux"):
        environ: dict[str, str] = {}
        assert configure_fonts(environ, platform) is None
        assert environ == {}


def test_each_platform_asks_only_for_its_own_tls_backend(monkeypatch: pytest.MonkeyPatch):
    """Qt logs a warning for each backend it is asked for and doesn't have."""
    from PyQt6.QtNetwork import QSslSocket

    asked: list[str] = []
    monkeypatch.setattr(QSslSocket, "setActiveBackend", lambda name: asked.append(name) or True)
    for platform, expected in (("win32", ["schannel"]), ("darwin", ["securetransport"])):
        asked.clear()
        use_platform_tls(platform)
        assert asked == expected, platform
    asked.clear()
    use_platform_tls("linux")
    assert asked == [], "Linux keeps Qt's own choice"


def _foreign_openssl() -> Path | None:
    r"""A folder with an OpenSSL of its own and the ``openssl`` tool: Git for Windows'
    ``mingw64\bin``, found on ``PATH`` or at its default install folder."""
    candidates = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/mingw64/bin")
    for folder in candidates:
        if (folder / "libssl-3-x64.dll").exists() and (folder / "openssl.exe").exists():
            if Path(sys.base_prefix) not in folder.parents:  # not Python's own
                return folder
    return None


@pytest.mark.skipif(sys.platform != "win32", reason="schannel and the crash are Windows'")
@pytest.mark.timeout(120)
def test_https_with_a_foreign_openssl_on_path_doesnt_crash(tmp_path: Path):
    """The 30-second crash's preconditions (``tls_crash.py``): Python's ``ssl`` loaded, another
    OpenSSL first on ``PATH``, one HTTPS request through Qt. Without the fix this process ends
    in an access violation when the connection is torn down; with it, Qt uses schannel."""
    folder = _foreign_openssl()
    if folder is None:
        pytest.skip("no OpenSSL other than Python's on this machine (Git for Windows has one)")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [str(folder / "openssl.exe"), "req", "-x509", "-newkey", "rsa:2048", "-nodes"]
        + ["-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=127.0.0.1"],
        check=True,
        capture_output=True,
    )
    env = {**os.environ, "PATH": f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"}
    run = subprocess.run(
        [sys.executable, str(HERE / "tls_crash.py"), str(cert), str(key), "5", "fix"],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )
    assert run.returncode == 0, f"exit {run.returncode:#x}: {run.stderr[-2000:]}"
    assert "backend schannel (Secure Channel" in run.stdout
    assert "status 200" in run.stdout and "survived" in run.stdout
