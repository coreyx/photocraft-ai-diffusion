"""The Interstice online service for AI Diffusion for PhotoCraft (design D11, REQ-32).

Upstream Krita AI Diffusion's cloud client, kept out of the plug-in package. The plug-in loads
it only through ``photocraft_host.cloud``, when the flag is on and this package is installed.
"""

from .cloud_client import CloudClient

__all__ = ["CloudClient"]
