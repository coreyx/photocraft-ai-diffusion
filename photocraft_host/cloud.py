"""The optional cloud module (design D11, REQ-32).

The online service is not part of this plug-in. It is available only when the flag
``PHOTOCRAFT_AI_CLOUD=1`` is set and a separate ``ai_diffusion_cloud`` package can be imported;
otherwise every cloud feature is left out: its settings, its page and its requests, and
``client_class()`` gives a stand-in that refuses to be created (:class:`CloudUnavailable`).
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
from typing import Any

FLAG = "PHOTOCRAFT_AI_CLOUD"
MODULE = "ai_diffusion_cloud"


class CloudUnavailable(RuntimeError):
    """The online service was asked for, but the cloud module is off or not installed."""


class UnavailableCloudClient:
    """Takes the place of the cloud client class without the cloud module: it has the class
    attributes upstream reads, no endpoints, and can't be created."""

    default_api_url = ""
    default_web_url = ""

    def __init__(self, *_args: Any, **_kwargs: Any):
        raise CloudUnavailable("the online service is not available in this plug-in")


def enabled() -> bool:
    """Whether the cloud module is switched on and present."""
    return os.environ.get(FLAG) == "1" and importlib.util.find_spec(MODULE) is not None


def client_class() -> Any:
    """The cloud client class: the cloud module's when enabled, else the stand-in."""
    if enabled():
        return importlib.import_module(MODULE).CloudClient
    return UnavailableCloudClient


def module_dir() -> Path:
    """The cloud module's folder, for the branding it supplies (its ``icons``)."""
    spec = importlib.util.find_spec(MODULE)
    assert spec is not None and spec.origin is not None, "only with the cloud module"
    return Path(spec.origin).parent
