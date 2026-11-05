"""PhotoCraft: the boundary to the online service (design D11, REQ-32).

Upstream's online-service client lives in the optional ``ai_diffusion_cloud`` package, outside the
plug-in. ``CloudClient`` is that client when the cloud module is enabled, and otherwise a
stand-in that raises ``CloudUnavailable`` when created and names no endpoint.
"""

from photocraft_host.cloud import CloudUnavailable, client_class

CloudClient = client_class()

__all__ = ["CloudClient", "CloudUnavailable"]
