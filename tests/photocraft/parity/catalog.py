"""A ``ClientModels`` that holds every model in upstream's catalog.

A real client learns which models exist by asking ComfyUI for the file lists of
its loader nodes, then matching those names against upstream's search patterns
(``ComfyClient.connect``). To build workflow graphs offline, this module feeds
the file names from upstream's own model catalog (``presets/models.json``)
through the same upstream matching helpers. The result is what a server with the
whole catalog installed would report.
"""

from __future__ import annotations

from collections import defaultdict

from ai_diffusion.backend import comfy_client
from ai_diffusion.backend.client import CheckpointInfo, ClientModels
from ai_diffusion.backend.resources import all_models, default_checkpoints
from ai_diffusion.files import FileFormat
from ai_diffusion.style import Arch


def _files_by_folder() -> dict[str, list[str]]:
    """Map each ComfyUI model folder to the catalog files in it, named as ComfyUI lists them."""
    folders: dict[str, list[str]] = defaultdict(list)
    for resource in all_models():
        for file in resource.files:
            parts = file.path.parts
            if len(parts) >= 3 and parts[0] == "models":
                folders[parts[1]].append("/".join(parts[2:]))
    return folders


def full_client_models() -> ClientModels:
    """Return client models as a server with the whole catalog installed would report them."""
    folders = _files_by_folder()
    models = ClientModels()
    found = models.resources

    # Same helpers, in the same order, as ComfyClient.connect uses on the loader node lists.
    found.update(comfy_client._find_text_encoder_models(folders["text_encoders"] + folders["clip"]))
    found.update(comfy_client._find_vae_models(folders["vae"]))
    found.update(comfy_client._find_control_models(folders["controlnet"]))
    found.update(comfy_client._find_clip_vision_model(folders["clip_vision"]))
    found.update(comfy_client._find_ip_adapters(folders["ipadapter"]))
    found.update(comfy_client._find_model_patches(folders["model_patches"]))
    found.update(comfy_client._find_style_models(folders["style_models"]))
    models.upscalers = sorted(folders["upscale_models"])
    found.update(comfy_client._find_upscalers(models.upscalers))
    found.update(comfy_client._find_inpaint_models(folders["inpaint"]))
    models.loras = sorted(folders["loras"])
    found.update(comfy_client._find_loras(models.loras))

    for checkpoint in default_checkpoints:
        file = checkpoint.files[0]
        is_diffusion_only = file.path.parent.name in ("diffusion_models", "unet")
        fmt = FileFormat.diffusion if is_diffusion_only else FileFormat.checkpoint
        arch = checkpoint.id.arch
        if arch is Arch.flux and "kontext" in file.name.lower():
            # The catalog files Flux Kontext under plain Flux; a server's model_info reports
            # it as the edit architecture, which is what generation then branches on.
            arch = Arch.flux_k
        models.checkpoints[file.name] = CheckpointInfo(file.name, arch, fmt)
    return models


def checkpoint_for(models: ClientModels, arch_name: str) -> str:
    """Return the first catalog checkpoint file for an architecture, by ``Arch`` member name."""
    for name, info in sorted(models.checkpoints.items()):
        if info.arch.name == arch_name:
            return name
    raise KeyError(f"no catalog checkpoint for arch {arch_name!r}")
