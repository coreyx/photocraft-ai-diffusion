"""A stand-in ComfyUI server for connection tests.

It answers what upstream's ``ComfyClient`` asks for (``system_stats``, ``object_info``, the
tooling nodes' ``api/etn/...`` routes, ``prompt``, ``queue``, ``interrupt``) and keeps a
websocket open, on a local port. ``object_info`` lists every node upstream requires (less
``missing_nodes``) and, for each loader node, the files of upstream's model catalog;
``checkpoints`` names which checkpoints are installed. Prompts are accepted and recorded but
never run, so the client's queue stays as it is. ``drop_websockets()`` ends the open websockets
abruptly, as a network failure would.

HTTP and the websocket share one port, as in ComfyUI; the websocket is the minimal part of
RFC 6455 the client needs (the handshake, text frames to the client, frames from it read and
ignored).

    with StubComfy() as server:
        settings.server_url = server.url
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading
from collections import defaultdict
from collections.abc import Collection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self

from ai_diffusion.backend import resources

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

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


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


def _text_frame(text: str) -> bytes:
    data = text.encode()
    if len(data) < 126:
        header = bytes([0x81, len(data)])
    elif len(data) < 1 << 16:
        header = bytes([0x81, 126]) + len(data).to_bytes(2, "big")
    else:
        header = bytes([0x81, 127]) + len(data).to_bytes(8, "big")
    return header + data


def _read_frame(stream) -> int | None:
    """Read one frame from the client (masked, as clients send them); its opcode, or ``None``
    once the connection ends."""
    header = stream.read(2)
    if len(header) < 2:
        return None
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(stream.read(2), "big")
    elif length == 127:
        length = int.from_bytes(stream.read(8), "big")
    stream.read(4 + length)  # the mask and the payload, not needed here
    return header[0] & 0x0F


class StubComfy:
    """A local ComfyUI stand-in, serving HTTP and the websocket on one port."""

    def __init__(
        self,
        checkpoints: dict[str, str] | None = None,
        languages: list[dict[str, str]] | None = None,
        missing_nodes: Collection[str] = (),
        port: int = 0,
    ):
        self.checkpoints = checkpoints or {"dreamshaper_8.safetensors": "sd15"}
        self.languages = languages or [{"code": "fr", "name": "French"}]
        self.missing_nodes = set(missing_nodes)
        self.port = port
        self.requests: list[str] = []
        self.prompts: list[dict[str, Any]] = []
        self.websocket_connects = 0
        self._sockets: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> Self:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"  # one request per connection, as needed here

            def log_message(self, format: str, *args: Any):
                pass  # quiet

            def do_GET(self):
                stub.requests.append(self.path)
                if self.path.split("?", 1)[0] == "/ws":
                    stub._websocket(self)
                else:
                    self._json(stub._get(self.path))

            def do_POST(self):
                stub.requests.append(f"POST {self.path}")
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(stub._post(self.path, body))

            def _json(self, body: Any):
                if body is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.drop_websockets()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def drop_websockets(self):
        """End every open websocket without a closing handshake, as a network failure does."""
        with self._lock:
            sockets, self._sockets = self._sockets, set()
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _get(self, path: str) -> Any:
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

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        route = path.split("?", 1)[0].strip("/")
        if route == "prompt":
            self.prompts.append(body)
            return {"prompt_id": body.get("prompt_id"), "number": len(self.prompts)}
        if route in ("queue", "interrupt") or route.startswith("api/etn/workflow/"):
            return {}
        return None

    def _websocket(self, handler: BaseHTTPRequestHandler):
        key = handler.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(hashlib.sha1((key + _WEBSOCKET_GUID).encode()).digest())
        handler.protocol_version = "HTTP/1.1"  # a websocket handshake is HTTP/1.1
        handler.send_response(101, "Switching Protocols")
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept.decode())
        handler.end_headers()
        sock: socket.socket = handler.connection
        with self._lock:
            self._sockets.add(sock)
            self.websocket_connects += 1
        status = {"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 0}}}}
        try:
            sock.sendall(_text_frame(json.dumps(status)))
            while (opcode := _read_frame(handler.rfile)) is not None:
                if opcode == 0x8:  # the client closes: answer, as the closing handshake asks
                    sock.sendall(bytes([0x88, 0]))
                    break
        except OSError:
            pass
        handler.close_connection = True
