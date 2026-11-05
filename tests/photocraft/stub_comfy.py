"""A stand-in ComfyUI server for connection tests.

It answers what upstream's ``ComfyClient`` asks for when connecting (``system_stats``,
``object_info``, the tooling nodes' ``api/etn/...`` routes) and holds the websocket open, on a
local port. ``object_info`` lists every node upstream requires and, for each loader node, the
files of upstream's model catalog, so the SD 1.5 workload is supported; ``checkpoints`` names
which checkpoints are installed. Each request path is recorded in ``requests``.

    with StubComfy() as server:
        settings.server_url = server.url
"""

from __future__ import annotations

import contextlib
import http
import json
import logging
import threading
from collections import defaultdict
from collections.abc import Collection
from typing import Any, Self

from ai_diffusion.backend import resources
from ai_diffusion.websockets.src.websockets.datastructures import Headers
from ai_diffusion.websockets.src.websockets.exceptions import ConnectionClosed
from ai_diffusion.websockets.src.websockets.http11 import Request, Response
from ai_diffusion.websockets.src.websockets.sync.server import ServerConnection, serve

#: Loader nodes and the model folder whose files each lists, as ``ComfyClient.connect`` reads them.
LOADERS = {
    "CheckpointLoaderSimple": ("ckpt_name", "checkpoints"),
    "VAELoader": ("vae_name", "vae"),
    "ControlNetLoader": ("control_net_name", "controlnet"),
    "CLIPVisionLoader": ("clip_name", "clip_vision"),
    "IPAdapterModelLoader": ("ipadapter_file", "ipadapter"),
    "UpscaleModelLoader": ("model_name", "upscale_models"),
    "INPAINT_LoadInpaintModel": ("model_name", "inpaint"),
    "LoraLoader": ("lora_name", "loras"),
    "DualCLIPLoader": ("clip_name1", "text_encoders"),
    "ModelPatchLoader": ("name", "model_patches"),
    "StyleModelLoader": ("style_model_name", "style_models"),
}


def catalog_files() -> dict[str, list[str]]:
    """Upstream's catalog files by ComfyUI model folder, named as ComfyUI lists them."""
    folders: dict[str, list[str]] = defaultdict(list)
    for resource in resources.all_models():
        for file in resource.files:
            parts = file.path.parts
            if len(parts) >= 3 and parts[0] == "models":
                folders[parts[1]].append("/".join(parts[2:]))
    return folders


def object_info(missing: Collection[str] = ()) -> dict[str, Any]:
    """``object_info`` of a server with upstream's required nodes (except ``missing``) and the
    whole catalog installed."""
    info: dict[str, Any] = {}
    for package in resources.required_custom_nodes:
        for node in package.nodes:
            info[node] = {"input": {"required": {}}}
    files = catalog_files()
    for node, (name, folder) in LOADERS.items():
        info[node] = {"input": {"required": {name: [sorted(files[folder])]}}}
    for node in missing:
        info.pop(node, None)
    return info


class StubComfy:
    """A local ComfyUI stand-in, serving HTTP and the websocket on one port."""

    def __init__(
        self,
        checkpoints: dict[str, str] | None = None,
        languages: list[dict[str, str]] | None = None,
        missing_nodes: Collection[str] = (),
    ):
        self.checkpoints = checkpoints or {"dreamshaper_8.safetensors": "sd15"}
        self.languages = languages or [{"code": "fr", "name": "French"}]
        self.missing_nodes = set(missing_nodes)
        self.requests: list[str] = []
        self._server: Any = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self._server.socket.getsockname()[:2]
        return f"http://{host}:{port}"

    def start(self) -> Self:
        # Qt opens and drops spare connections, which the server would log as failed handshakes.
        quiet = logging.getLogger("photocraft.stub_comfy")
        quiet.setLevel(logging.CRITICAL)
        self._server = serve(
            self._websocket, "127.0.0.1", 0, process_request=self._http, logger=quiet
        )
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server = None

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def _answer(self, path: str) -> Any:
        route = path.split("?", 1)[0].strip("/")
        if route == "system_stats":
            return {
                "system": {"os": "nt", "python_version": "3.12", "comfyui_version": "0.3.60"},
                "devices": [{"name": "cuda:0 Stub GPU", "type": "cuda", "vram_total": 8 << 30}],
            }
        if route == "object_info":
            return object_info(self.missing_nodes)
        if route == "api/etn/languages":
            return self.languages
        if route == "api/etn/model_info/checkpoints":
            return {name: {"base_model": arch} for name, arch in self.checkpoints.items()}
        if route.startswith("api/etn/model_info/"):
            return {}
        if route in ("queue", "history"):
            return {}
        return None

    def _http(self, connection: ServerConnection, request: Request) -> Response | None:
        self.requests.append(request.path)
        if request.path.split("?", 1)[0] == "/ws":
            return None  # the websocket handshake goes on
        body = self._answer(request.path)
        if body is None:
            return connection.respond(http.HTTPStatus.NOT_FOUND, "Not found")
        data = json.dumps(body).encode()
        headers = Headers([
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(data))),
        ])
        return Response(http.HTTPStatus.OK.value, "OK", headers, data)

    def _websocket(self, connection: ServerConnection):
        # ComfyUI sends progress and results here; nothing is queued, so it only stays open.
        with contextlib.suppress(ConnectionClosed):
            for _ in connection:
                pass
