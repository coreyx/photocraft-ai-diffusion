"""Turn a ``WorkflowInput`` and its ComfyUI prompt into stable, comparable JSON.

Two runs of the same scenario must produce identical output, and so must
upstream and this project's plug-in when they behave the same. Upstream gives
images random ``uuid4`` ids inside the prompt, so every image is replaced by a
content hash (pixel data plus size and format). Everything else is kept as is.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

#: ComfyUI node types whose ``id`` input names an image in ``ComfyWorkflow.images`` or
#: ``ComfyWorkflow.image_data``.
_IMAGE_ID_NODES = {"ETN_LoadImageCache", "ETN_InjectImage", "ETN_InjectMask"}


def image_hash(image: Any) -> str:
    """Return a content hash of an upstream ``Image``: its size, pixel format and pixel bytes."""
    digest = hashlib.sha256()
    digest.update(f"{image.width}x{image.height}:{image._qimage.format().name}".encode())
    digest.update(bytes(image.data.data()))
    return "image:" + digest.hexdigest()[:24]


def _bytes_hash(data: bytes) -> str:
    return "image-bytes:" + hashlib.sha256(data).hexdigest()[:24]


def normalize_input(work: Any, serializer_cls: Any) -> dict[str, Any]:
    """Serialize a ``WorkflowInput`` with images replaced by content hashes.

    ``serializer_cls`` is upstream's ``ai_diffusion.backend.api.Serializer``. Its image
    references are list indices into the images it collected; they become hashes here.
    """
    serializer = serializer_cls()
    data = serializer._object(work)
    hashes = [image_hash(image) for image in serializer._images]

    def replace(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {k: replace(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v, key) for v in value]
        if isinstance(value, int) and not isinstance(value, bool) and _is_image_field(key):
            return hashes[value]
        return value

    return replace(data)


def _is_image_field(key: str) -> bool:
    """Whether a serialized ``WorkflowInput`` field holds an image index.

    These are the fields of upstream's ``api`` dataclasses typed ``Image`` or ``Mask``.
    """
    return key in {"initial_image", "hires_image", "hires_mask", "mask", "image", "images"}


def normalize_graph(workflow: Any) -> dict[str, Any]:
    """Return a ``ComfyWorkflow``'s prompt with image ids replaced by content hashes."""
    ids: dict[str, str] = {k: image_hash(v) for k, v in workflow.images.items()}
    ids.update({k: _bytes_hash(v) for k, v in workflow.image_data.items()})
    root = deepcopy(workflow.root)
    for node in root.values():
        inputs = node.get("inputs", {})
        if node.get("class_type") in _IMAGE_ID_NODES and isinstance(inputs.get("id"), str):
            inputs["id"] = ids.get(inputs["id"], inputs["id"])
    return root


def diff(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """List the paths where two normalized JSON values differ, for readable test failures."""
    if type(expected) is not type(actual):
        return [f"{path}: type {type(expected).__name__} != {type(actual).__name__}"]
    if isinstance(expected, dict):
        result: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                result.append(f"{path}.{key}: missing")
            elif key not in expected:
                result.append(f"{path}.{key}: unexpected")
            else:
                result.extend(diff(expected[key], actual[key], f"{path}.{key}"))
        return result
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path}: length {len(expected)} != {len(actual)}"]
        result = []
        for index, (a, b) in enumerate(zip(expected, actual)):
            result.extend(diff(a, b, f"{path}[{index}]"))
        return result
    if isinstance(expected, float) and isinstance(actual, float):
        return [] if abs(expected - actual) <= 1e-9 else [f"{path}: {expected!r} != {actual!r}"]
    return [] if expected == actual else [f"{path}: {expected!r} != {actual!r}"]
