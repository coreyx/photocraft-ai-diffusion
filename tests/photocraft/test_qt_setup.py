"""The Qt set-up the plug-in process does before upstream runs (``photocraft_host.qt_setup``;
spec ``plugin-tls-and-fonts-fix``)."""

from __future__ import annotations

from photocraft_host.qt_setup import configure_fonts


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
