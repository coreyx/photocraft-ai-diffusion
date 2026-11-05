"""The optional cloud module (design D11, REQ-32).

The Interstice online service is not part of this plug-in. It is available only when the flag
``PHOTOCRAFT_AI_CLOUD=1`` is set and a separate ``ai_diffusion_cloud`` package can be imported;
otherwise every cloud feature is left out: its settings, its page and its requests.
"""

from __future__ import annotations

import importlib.util
import os

FLAG = "PHOTOCRAFT_AI_CLOUD"
MODULE = "ai_diffusion_cloud"


def enabled() -> bool:
    """Whether the cloud module is switched on and present."""
    return os.environ.get(FLAG) == "1" and importlib.util.find_spec(MODULE) is not None
