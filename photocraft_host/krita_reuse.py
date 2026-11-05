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
from typing import Any

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


# -- using a detected configuration (design D10, REQ-31.0.3 to 31.0.11)
#
# Reuse is an ordinary configuration plus provenance in the ``photocraft_reuse`` setting:
# ``{"mode": "same_server" | "shared_models", "source_settings", "server_url"?,
# "server_path"?, "detected_version"?, "shared_models"?}``. Switching to any other server
# clears it.

SAME_SERVER = "same_server"
SHARED_MODELS = "shared_models"
#: Settings not imported: where the server is (Use the same ComfyUI server sets those), this
#: plug-in's own, and the secrets (imported only after a separate confirmation).
NOT_IMPORTED = {
    "server_mode",
    "server_path",
    "server_url",
    "server_backend",
    "server_arguments",
    "photocraft_reuse",
    "last_news",
    *SECRETS,
}
#: Folders of user files imported: styles, sampler and other presets, tag files, workflows.
IMPORTED_FOLDERS = ("styles", "presets", "tags", "workflows")


def use_same_server(config: KritaConfig, settings: Any) -> None:
    """Configure this plug-in to use the server ``config`` uses: its address for a custom server,
    its install folder (with its backend and arguments) for a managed one. Nothing is installed,
    and nothing in Krita AI Diffusion's folders changes."""
    from ai_diffusion.settings import ServerBackend, ServerMode

    provenance: dict[str, Any] = {
        "mode": SAME_SERVER,
        "source_settings": str(config.folder / "settings.json"),
    }
    # The provenance is written last: changing the server first clears any earlier one.
    if config.is_custom:
        provenance["server_url"] = config.server_url
        settings.server_mode = ServerMode.external
        settings.server_url = config.server_url
    elif config.is_managed:
        provenance["server_path"] = str(config.server_path)
        provenance["detected_version"] = config.version
        backend = config.installed_backend or config.server_backend
        if backend in ServerBackend.__members__:
            settings.server_backend = ServerBackend[backend]
        settings.server_arguments = config.server_arguments
        settings.server_path = str(config.server_path)
        settings.server_mode = ServerMode.managed
    else:
        raise ValueError(f"no server to use: Krita AI Diffusion is in '{config.server_mode}' mode")
    settings.photocraft_reuse = provenance
    settings.save()


def managed_url(config: KritaConfig) -> str:
    """The address a managed install answers on when Krita AI Diffusion has started it."""
    match = re.search(r"--port[ =](\d+)", config.server_arguments)
    return f"127.0.0.1:{match.group(1) if match else 8188}"


def _same(a: Path | str, b: Path | str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def reused_install(settings: Any) -> Path | None:
    """The Krita AI Diffusion install this plug-in uses as its managed server, if it does."""
    provenance = settings.photocraft_reuse
    if provenance.get("mode") == SAME_SERVER and provenance.get("server_path"):
        return Path(provenance["server_path"])
    return None


def is_krita_managed(
    path: Path, settings: Any = None, configs: list[KritaConfig] | None = None
) -> bool:
    """Whether ``path`` is a ComfyUI install that Krita AI Diffusion manages: the one this plug-in
    reuses, or one a detected configuration has as its server. Such an install is never
    upgraded, re-installed, repaired or deleted from here (REQ-31.0.5)."""
    if settings is not None and (reused := reused_install(settings)) is not None:
        if _same(reused, path):
            return True
    configs = detect() if configs is None else configs
    return any(c.is_managed and _same(c.server_path, path) for c in configs)


def validate(settings: Any) -> str | None:
    """Check the reused install before connecting (REQ-31.0.9): a notice when it was moved or
    deleted, or when Krita AI Diffusion changed its version (the provenance then follows)."""
    from ai_diffusion.localization import translate as _

    install = reused_install(settings)
    if install is None:
        return None
    version_file = install / ".version"
    if not version_file.is_file():
        return _(
            "The Krita AI Diffusion server at {path} was moved or deleted. Detect Krita AI Diffusion again, or set up your own server.",
            path=str(install),
        )
    parts = version_file.read_text(encoding="utf-8").split()
    version = parts[0] if parts else None
    provenance = dict(settings.photocraft_reuse)
    if version != provenance.get("detected_version"):
        before = provenance.get("detected_version")
        provenance["detected_version"] = version
        settings.photocraft_reuse = provenance
        settings.save()
        return _(
            "Krita AI Diffusion changed its server from version {old} to {new}.",
            old=str(before),
            new=str(version),
        )
    return None


def share_models(config: KritaConfig, settings: Any, own_path: Path) -> None:
    """Set up this plug-in's own managed server in ``own_path``, using the reused install's model
    folders, so no model is downloaded again (REQ-31.0.6, 31.7)."""
    from ai_diffusion.settings import ServerMode

    settings.server_path = str(own_path)
    settings.server_mode = ServerMode.managed
    settings.photocraft_reuse = {
        "mode": SHARED_MODELS,
        "source_settings": str(config.folder / "settings.json"),
        "shared_models": [str(config.server_path)],
    }
    settings.save()


def shared_model_installs(settings: Any) -> list[Path]:
    """Other installs whose models this plug-in's own server uses, for its install and its
    ``extra_model_paths.yaml``."""
    provenance = settings.photocraft_reuse
    if provenance.get("mode") != SHARED_MODELS:
        return []
    return [Path(p) for p in provenance.get("shared_models", [])]


def forget_when_switched(settings: Any, key: str, _value: Any = None) -> None:
    """Clear the provenance once the user picks another server (REQ-31.0.11). Connected to
    ``settings.changed``."""
    provenance = settings.photocraft_reuse
    if not provenance or key not in ("server_mode", "server_url", "server_path"):
        return
    mode = getattr(settings.server_mode, "name", "")
    if provenance.get("mode") == SAME_SERVER and provenance.get("server_path"):
        kept = mode == "managed" and _same(settings.server_path, provenance["server_path"])
    elif provenance.get("mode") == SAME_SERVER:
        kept = mode == "external" and settings.server_url == provenance.get("server_url")
    else:  # shared models: this plug-in's own managed server
        kept = mode == "managed"
    if not kept:
        settings.photocraft_reuse = {}
        settings.save()


def import_settings(
    config: KritaConfig, data_dir: Path, settings: Any, secrets: bool = False
) -> dict[str, list[str]]:
    """Copy Krita AI Diffusion's settings and user files into this plug-in (REQ-31.0.7, 31.0.8):
    its settings except where its server is, and its styles, presets, tag files and workflows.
    ``server_authorization`` and ``access_token`` only with ``secrets``, after the user's
    separate confirmation. Files already here are kept. Returns what was copied, by name only,
    so it can be shown and logged without any value.
    """
    import shutil
    from enum import Enum

    from ai_diffusion.settings import Settings

    source = _read_json(config.folder / "settings.json")
    copied: list[str] = []
    for key, value in source.items():
        if key in NOT_IMPORTED and not (secrets and key in SECRETS):
            continue
        setting = getattr(Settings, f"_{key}", None)
        if setting is None:
            continue
        if isinstance(setting.default, Enum):
            if not isinstance(value, str):
                continue
            value = setting.str_to_enum(value)
        elif not isinstance(value, type(setting.default)):
            continue
        setattr(settings, key, value)
        copied.append(key)
    settings.save()

    files: list[str] = []
    for name in IMPORTED_FOLDERS:
        src = config.folder / name
        if not src.is_dir():
            continue
        for file in sorted(src.rglob("*")):
            target = data_dir / name / file.relative_to(src)
            if not file.is_file() or target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
            files.append(f"{name}/{file.relative_to(src).as_posix()}")
    return {"settings": copied, "files": files}
