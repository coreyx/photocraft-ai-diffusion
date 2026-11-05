r"""Find Krita AI Diffusion's configuration on this machine, read-only (REQ-31, design D10).

Krita AI Diffusion keeps its data in ``<krita appdata>/ai_diffusion`` (falling back to a
``krita-ai-diffusion`` folder, and before version 1.15 inside the plug-in folder). ``detect``
looks in each place Krita may use on this OS, reads ``settings.json`` and, for a managed server,
``<server_path>/.version``, and lists the model folders that install has. Nothing is written,
and secrets are never kept: a configuration only notes whether it has any.

Where Krita keeps its data (``<krita appdata>``):

- Windows: ``%APPDATA%\krita`` (installer and portable zip alike); the Microsoft Store package
  under ``%LOCALAPPDATA%\Packages\<Krita package>\LocalCache\Roaming\krita``;
- Linux: ``$XDG_DATA_HOME/krita`` (``~/.local/share/krita``); Flatpak
  ``~/.var/app/org.kde.krita/data/krita``;
- macOS: ``~/Library/Application Support/krita``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

#: The settings read from Krita AI Diffusion, and their defaults when absent.
READ_SETTINGS = {
    "server_mode": "undefined",
    "server_url": "127.0.0.1:8188",
    "server_path": "",
    "server_backend": "",
    "server_arguments": "",
}
SECRETS = ("server_authorization", "access_token")


@dataclass
class KritaConfig:
    """One Krita AI Diffusion configuration found on this machine."""

    folder: Path  # its data folder (holding settings.json)
    location: str  # which kind of place it was found in, for display
    server_mode: str
    server_url: str
    server_path: Path
    server_backend: str
    server_arguments: str
    has_secrets: bool  # whether it holds a ComfyUI or online-service token (never their values)
    version: str | None = None  # the managed install's version, from its .version
    installed_backend: str | None = None
    plugin_version: str | None = None  # the installed Krita AI Diffusion plug-in's version
    model_folders: list[Path] = field(default_factory=list)

    @property
    def is_managed(self) -> bool:
        return self.server_mode == "managed"

    @property
    def is_custom(self) -> bool:
        return self.server_mode == "external"


def candidates(
    platform: str = sys.platform, env: Mapping[str, str] = os.environ, home: Path | None = None
) -> list[tuple[Path, str]]:
    """The data folders Krita AI Diffusion may use on ``platform``, each with its kind."""
    home = home or Path.home()
    krita_dirs: list[tuple[Path, str]] = []
    fallback: Path | None = None
    if platform.startswith("win"):
        roaming = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        krita_dirs.append((roaming / "krita", "Krita"))
        packages = local / "Packages"
        if packages.is_dir():
            for package in sorted(packages.glob("*Krita*")):
                krita_dirs.append((
                    package / "LocalCache" / "Roaming" / "krita",
                    "Krita (Microsoft Store)",
                ))
        fallback = local / "krita-ai-diffusion"
    elif platform == "darwin":
        support = home / "Library" / "Application Support"
        krita_dirs.append((support / "krita", "Krita"))
        fallback = support / "krita-ai-diffusion"
    else:
        data = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
        krita_dirs.extend((
            (data / "krita", "Krita"),
            (home / ".var" / "app" / "org.kde.krita" / "data" / "krita", "Krita (Flatpak)"),
        ))
        fallback = data / "krita-ai-diffusion"

    found = [(krita / "ai_diffusion", kind) for krita, kind in krita_dirs]
    found.append((fallback, "Krita AI Diffusion folder"))
    # Before version 1.15, and when its data folder can't be made, the plug-in kept its data
    # beside itself.
    found += [
        (krita / "pykrita" / "ai_diffusion", f"{kind} plug-in folder") for krita, kind in krita_dirs
    ]
    return found


def _read_json(path: Path) -> dict:
    """Read a JSON file as Krita AI Diffusion does: lines starting with ``//`` are comments."""
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("//")]
    data = json.loads("\n".join(lines))
    return data if isinstance(data, dict) else {}


def _plugin_version(folder: Path) -> str | None:
    """The version of the Krita AI Diffusion plug-in installed beside a data folder, if any."""
    for init in (
        folder.parent / "pykrita" / "ai_diffusion" / "__init__.py",
        folder / "__init__.py",
    ):
        if init.is_file():
            match = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
            if match:
                return match.group(1)
    return None


def _yaml_base_paths(comfy_dir: Path) -> list[Path]:
    """The ``base_path`` of each section of ComfyUI's ``extra_model_paths.yaml``."""
    path = comfy_dir / "extra_model_paths.yaml"
    if not path.is_file():
        return []
    bases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s+base_path:\s*(.+?)\s*$", line)
        if match and not line.lstrip().startswith("#"):
            base = Path(match.group(1).strip("'\""))
            bases.append(base if base.is_absolute() else (comfy_dir / base))
    return bases


def _model_folders(server_path: Path) -> list[Path]:
    """The model folders a managed install has: its own, ComfyUI's, and those in its
    ``extra_model_paths.yaml``."""
    comfy = server_path / "ComfyUI"
    candidates = [server_path / "models", comfy / "models", *_yaml_base_paths(comfy)]
    folders: list[Path] = []
    for folder in candidates:
        resolved = Path(os.path.normpath(folder))
        if resolved.is_dir() and resolved not in folders:
            folders.append(resolved)
    return folders


def read_config(folder: Path, location: str) -> KritaConfig | None:
    """The configuration in a data folder, or ``None`` if it has none (or can't be read)."""
    settings_file = folder / "settings.json"
    if not settings_file.is_file():
        return None
    try:
        settings = _read_json(settings_file)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    values = {key: settings.get(key, default) for key, default in READ_SETTINGS.items()}
    values = {
        key: value if isinstance(value, str) else READ_SETTINGS[key]
        for key, value in values.items()
    }
    server_path = Path(values["server_path"] or folder / "server")
    config = KritaConfig(
        folder=folder,
        location=location,
        server_mode=values["server_mode"],
        server_url=values["server_url"],
        server_path=server_path,
        server_backend=values["server_backend"],
        server_arguments=values["server_arguments"],
        has_secrets=any(isinstance(settings.get(k), str) and settings[k] for k in SECRETS),
        plugin_version=_plugin_version(folder),
    )
    if config.is_managed:
        version_file = server_path / ".version"
        if version_file.is_file():
            parts = version_file.read_text(encoding="utf-8").split()
            config.version = parts[0] if parts else None
            config.installed_backend = parts[1] if len(parts) > 1 else None
        config.model_folders = _model_folders(server_path)
    return config


def detect(
    platform: str = sys.platform, env: Mapping[str, str] = os.environ, home: Path | None = None
) -> list[KritaConfig]:
    """Every Krita AI Diffusion configuration on this machine, in the order Krita prefers them."""
    found = []
    for folder, location in candidates(platform, env, home):
        if (config := read_config(folder, location)) is not None:
            found.append(config)
    return found
