"""PhotoCraft host adapter for AI Diffusion for PhotoCraft.

This package is the part of the plug-in written by this project (everything
under ``ai_diffusion/`` comes from upstream Krita AI Diffusion). It connects the
upstream code to PhotoCraft's process plug-in protocol:

- ``transport``: framing and request/response/event messaging over stdio.
- ``krita``: a stand-in for the ``krita`` module that upstream imports.
- ``qt_mirror``: sends upstream's Qt widget tree to PhotoCraft to draw natively.
- ``krita_reuse``: detects and reuses an existing Krita AI Diffusion setup.
- ``cloud``: the optional cloud-module seam (off by default).
- ``main``: the plug-in process entry point.
"""

__all__: list[str] = []
