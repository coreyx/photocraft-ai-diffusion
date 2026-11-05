"""Audits shared by the tests and the GPU end-to-end suite (TASK-45, REQ-39).

- ``secrets_in`` finds secret values (tokens, the launch nonce) in log files and output: the
  plug-in must never write one (REQ-31.0.8, 36.0.3).
- ``outside_allowed`` checks the hosts a session asked against the allow-list: the ComfyUI
  server in use, and the places the plug-in itself may reach: this project's releases on GitHub
  for updates, and the model and package sources the installer downloads from.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

#: Hosts the plug-in may ask besides its ComfyUI server (whose host the caller adds).
ALLOWED_HOSTS = {
    "api.github.com",  # update checks: this project's releases (REQ-36.0.2)
    "github.com",  # update packages, uv and ComfyUI downloads
    "objects.githubusercontent.com",  # where GitHub's downloads redirect
    "release-assets.githubusercontent.com",
    "huggingface.co",  # models in the catalog (REQ-29.0.2)
    "cdn-lfs.huggingface.co",
    "cas-bridge.xethub.hf.co",
    "civitai.com",
    "pypi.org",  # the managed server's Python packages
    "files.pythonhosted.org",
    "download.pytorch.org",
}
#: Hosts that must never be asked: the online service the plug-in leaves out (REQ-32).
FORBIDDEN_FRAGMENTS = ("interstice",)


def secrets_in(texts: Iterable[str], secrets: Iterable[str]) -> list[str]:
    """Each secret value found in any of ``texts``."""
    values = [s for s in secrets if s]
    return sorted({s for text in texts for s in values if s in text})


def log_texts(*folders: Path) -> list[str]:
    """The contents of every log file in ``folders`` (and their sub-folders)."""
    texts = []
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and (path.suffix in (".log", ".txt") or ".log." in path.name):
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return texts


def outside_allowed(hosts: Iterable[str], server_hosts: Iterable[str]) -> list[str]:
    """The hosts asked that are not on the allow-list (with the server's own hosts added), and
    any that belong to the online service."""
    allowed = ALLOWED_HOSTS | set(server_hosts) | {"127.0.0.1", "localhost", "::1"}
    return sorted(
        h
        for h in set(hosts)
        if h not in allowed or any(f in h.lower() for f in FORBIDDEN_FRAGMENTS)
    )
