"""Finding Krita AI Diffusion's configuration (TASK-40, REQ-31.0.1, 31.1, 31.8), on synthetic
folder layouts for each OS and packaging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from photocraft_host import krita_reuse
from photocraft_host.krita_reuse import detect


def _config(folder: Path, **settings) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text(json.dumps(settings, indent=4))
    return folder


def _managed_install(server: Path, version: str = "1.54.0 cuda", yaml: str = "") -> Path:
    (server / "models" / "checkpoints").mkdir(parents=True)
    (server / "ComfyUI" / "models").mkdir(parents=True)
    (server / ".version").write_text(version)
    if yaml:
        (server / "ComfyUI" / "extra_model_paths.yaml").write_text(yaml)
    return server


def _plugin(krita: Path, version: str = "1.54.0"):
    plugin = krita / "pykrita" / "ai_diffusion"
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "__init__.py").write_text(
        f'"""Generative AI plugin for Krita"""\n\n__version__ = "{version}"\n'
    )


def test_a_windows_managed_install_at_its_default_path(tmp_path: Path):
    """REQ-31.1: backend, version and model folders of a managed install at the default path."""
    roaming = tmp_path / "Roaming"
    data = _config(roaming / "krita" / "ai_diffusion", server_mode="managed", server_backend="cuda")
    shared = tmp_path / "D" / "ai-models"
    shared.mkdir(parents=True)
    _managed_install(
        data / "server",
        yaml=f"comfyui:\n    base_path: {shared.as_posix()}\n#   base_path: commented/out\n",
    )
    _plugin(roaming / "krita")
    env = {"APPDATA": str(roaming), "LOCALAPPDATA": str(tmp_path / "Local")}
    (config,) = detect("win32", env, tmp_path)
    assert (config.location, config.server_mode, config.is_managed) == ("Krita", "managed", True)
    assert config.server_path == data / "server"
    assert (config.version, config.installed_backend, config.server_backend) == (
        "1.54.0",
        "cuda",
        "cuda",
    )
    assert config.plugin_version == "1.54.0"
    assert config.model_folders == [
        data / "server" / "models",
        data / "server" / "ComfyUI" / "models",
        shared,
    ]


def test_a_windows_custom_server_from_the_microsoft_store_krita(tmp_path: Path):
    local = tmp_path / "Local"
    store = local / "Packages" / "KDEe.V.Krita_abc123" / "LocalCache" / "Roaming" / "krita"
    _config(store / "ai_diffusion", server_mode="external", server_url="192.0.2.10:8188")
    env = {"APPDATA": str(tmp_path / "Roaming"), "LOCALAPPDATA": str(local)}
    (config,) = detect("win32", env, tmp_path)
    assert (config.location, config.is_custom, config.server_url) == (
        "Krita (Microsoft Store)",
        True,
        "192.0.2.10:8188",
    )
    assert config.model_folders == [], "a custom server's models are checked online"


def test_settings_kept_in_the_plugin_folder(tmp_path: Path):
    """REQ-31.8 (portable): the data kept beside the plug-in, as before 1.15 or when its data
    folder can't be made, with the server inside it."""
    roaming = tmp_path / "Roaming"
    _plugin(roaming / "krita", "1.14.0")
    folder = _config(roaming / "krita" / "pykrita" / "ai_diffusion", server_mode="managed")
    _managed_install(folder / "server", "1.14.0 cpu")
    (config,) = detect(
        "win32", {"APPDATA": str(roaming), "LOCALAPPDATA": str(tmp_path / "L")}, tmp_path
    )
    assert config.location == "Krita plug-in folder"
    assert (config.server_path, config.version, config.plugin_version) == (
        folder / "server",
        "1.14.0",
        "1.14.0",
    )


def test_linux_native_and_flatpak(tmp_path: Path):
    """REQ-31.8: both found, the native one first."""
    _config(tmp_path / ".local" / "share" / "krita" / "ai_diffusion", server_mode="external")
    flatpak = tmp_path / ".var" / "app" / "org.kde.krita" / "data" / "krita" / "ai_diffusion"
    _config(flatpak, server_mode="managed", server_path=str(tmp_path / "comfy"))
    _managed_install(tmp_path / "comfy", "1.53.1 rocm")
    native, flat = detect("linux", {}, tmp_path)
    assert (native.location, flat.location) == ("Krita", "Krita (Flatpak)")
    assert (flat.server_path, flat.version, flat.installed_backend) == (
        tmp_path / "comfy",
        "1.53.1",
        "rocm",
    )


def test_xdg_data_home_and_the_fallback_folder(tmp_path: Path):
    data = tmp_path / "xdg"
    _config(data / "krita-ai-diffusion", server_mode="external", server_url="localhost:8000")
    (config,) = detect("linux", {"XDG_DATA_HOME": str(data)}, tmp_path)
    assert (config.location, config.server_url) == ("Krita AI Diffusion folder", "localhost:8000")


def test_macos(tmp_path: Path):
    support = tmp_path / "Library" / "Application Support"
    _config(support / "krita" / "ai_diffusion", server_mode="managed", server_backend="mps")
    _managed_install(support / "krita" / "ai_diffusion" / "server", "1.54.0 mps")
    (config,) = detect("darwin", {}, tmp_path)
    assert (config.server_backend, config.installed_backend) == ("mps", "mps")


def test_secrets_are_noted_but_never_kept(tmp_path: Path):
    folder = _config(
        tmp_path / ".local" / "share" / "krita" / "ai_diffusion",
        server_mode="external",
        server_authorization="sk-very-secret",
        access_token="tok-very-secret",
    )
    (config,) = detect("linux", {}, tmp_path)
    assert config.has_secrets
    assert "very-secret" not in repr(config), "not in the configuration, so not in any log"
    _config(folder, server_mode="external", server_authorization="", access_token="")
    (config,) = detect("linux", {}, tmp_path)
    assert not config.has_secrets


def test_defaults_comments_and_broken_files(tmp_path: Path):
    folder = tmp_path / ".local" / "share" / "krita" / "ai_diffusion"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(
        '// a comment, as Krita AI Diffusion allows\n{"server_url": 8188}\n'
    )
    (config,) = detect("linux", {}, tmp_path)
    assert (config.server_mode, config.server_url) == ("undefined", "127.0.0.1:8188"), "defaults"
    assert config.server_path == folder / "server"
    (folder / "settings.json").write_text("{ not json")
    assert detect("linux", {}, tmp_path) == []


def test_nothing_is_written(tmp_path: Path):
    roaming = tmp_path / "Roaming"
    data = _config(roaming / "krita" / "ai_diffusion", server_mode="managed")
    _managed_install(data / "server")

    def snapshot():
        return {
            p.relative_to(tmp_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            if p.is_file()
            else None
            for p in sorted(tmp_path.rglob("*"))
        }

    before = snapshot()
    detect("win32", {"APPDATA": str(roaming), "LOCALAPPDATA": str(tmp_path / "Local")}, tmp_path)
    assert snapshot() == before


def test_the_places_looked_at_on_each_os(tmp_path: Path):
    def names(platform: str, env: dict) -> list[str]:
        return [
            p.relative_to(tmp_path).as_posix()
            for p, _ in krita_reuse.candidates(platform, env, tmp_path)
        ]

    assert names("linux", {}) == [
        ".local/share/krita/ai_diffusion",
        ".var/app/org.kde.krita/data/krita/ai_diffusion",
        ".local/share/krita-ai-diffusion",
        ".local/share/krita/pykrita/ai_diffusion",
        ".var/app/org.kde.krita/data/krita/pykrita/ai_diffusion",
    ]
    assert names("darwin", {}) == [
        "Library/Application Support/krita/ai_diffusion",
        "Library/Application Support/krita-ai-diffusion",
        "Library/Application Support/krita/pykrita/ai_diffusion",
    ]
    env = {"APPDATA": str(tmp_path / "R"), "LOCALAPPDATA": str(tmp_path / "L")}
    assert names("win32", env) == [
        "R/krita/ai_diffusion",
        "L/krita-ai-diffusion",
        "R/krita/pykrita/ai_diffusion",
    ]
