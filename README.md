# AI Diffusion for PhotoCraft

Generative AI inside [PhotoCraft](https://github.com/storytold/photocraft), the open-source Rust image editor. Generate, refine, inpaint, live-paint and upscale with local or remote [ComfyUI](https://github.com/comfyanonymous/ComfyUI), using regional prompts, control layers, styles and custom ComfyUI graphs, all from a panel inside PhotoCraft.

> **Status: feature-complete, not yet released.** Everything in the [specification](spec/ai-diffusion-for-photocraft/) is implemented and tested. It needs the PhotoCraft built from the [`coreyx/photocraft`](https://github.com/coreyx/photocraft) fork (branch `feat/process-plugins`) until the plug-in host is part of PhotoCraft. What's still open is in the [walkthrough](spec/ai-diffusion-for-photocraft/walkthrough.md#follow-ups).

## Based on Krita AI Diffusion

This project is a port of [**Krita AI Diffusion**](https://github.com/Acly/krita-ai-diffusion) (v1.54.0-pre), the generative AI plug-in for Krita, and aims to work the same way. Nearly all of the generation logic, ComfyUI integration, styles, presets and translations come from Krita AI Diffusion, and its git history is part of this repository. Credit for that work belongs to the Krita AI Diffusion contributors. See [NOTICE](NOTICE) for attribution, and [UPSTREAM-CHANGES.md](UPSTREAM-CHANGES.md) for every file this project changes.

The differences from Krita AI Diffusion are deliberate and few:

- It runs inside PhotoCraft instead of Krita.
- It can detect an existing Krita AI Diffusion setup and use the same ComfyUI server and models.
- Documents in any bit depth or colour mode are converted for generation instead of refused.
- The online-service mode is not included.
- The Animation workspace is deferred until PhotoCraft has a Frame Animation panel.

## How it works

AI Diffusion for PhotoCraft runs as its own process next to PhotoCraft:

- **PhotoCraft's side** is a generic process plug-in host. It lets a plug-in read and change documents, receive change events, and show panels that PhotoCraft draws natively. It's developed in the [`coreyx/photocraft`](https://github.com/coreyx/photocraft) fork, branch `feat/process-plugins`.
- **This plug-in** runs Krita AI Diffusion's Python code on Python 3.12 with headless PyQt6. It replaces only Krita's API (with a stand-in that talks to PhotoCraft) and the way its Qt widgets reach the screen (mirrored into PhotoCraft's own UI).

The full specification is in [`spec/ai-diffusion-for-photocraft/`](spec/ai-diffusion-for-photocraft/), and the analysis it's based on is in [`analysis/ai-diffusion-for-photocraft/`](analysis/ai-diffusion-for-photocraft/).

## Installing

1. Get the package for your platform (`ai-diffusion-for-photocraft-<version>-<platform>.zip`) from a release, or build it with `python packaging/build.py --version <version>`. Packages exist for Windows x64, macOS (Apple silicon and Intel) and Linux x64. Each bundles its own Python.
2. In PhotoCraft, open Preferences › Plug-ins and install the package.
3. On first start, the plug-in installs its runtime (PyQt6) into its data folder and shows its progress in a panel. Later starts take under a second.
4. Open the AI Image Generation panel and, in its settings, pick a server on the Connection page:
   - a ComfyUI server the plug-in installs and manages;
   - a ComfyUI server you run yourself;
   - the server and models of a Krita AI Diffusion setup found on this computer.

Updates come from this project's releases: the plug-in checks for them, verifies the download, and PhotoCraft installs it and restarts the plug-in.

## Developing

Set up with [uv](https://docs.astral.sh/uv/), on Python 3.12:

```sh
uv venv .venv --python 3.12
uv pip install --python .venv -r requirements-photocraft.txt
git submodule update --init
```

CI (`.github/workflows/photocraft.yml`) runs:
- `ruff` and `pyright`;
- this project's tests (`tests/photocraft`);
- upstream's unit tests;
- upstream's tests on the PhotoCraft stand-in (`tests/photocraft_upstream`);
- a coverage gate.

End-to-end tests against a real ComfyUI with models:

```sh
PHOTOCRAFT_E2E_COMFYUI=127.0.0.1:8188 python -m pytest -p tests.photocraft.upstream_shim \
  tests/photocraft_upstream/test_e2e_gpu.py -v
```

To merge a new Krita AI Diffusion release, follow [`docs/upstream-merge.md`](docs/upstream-merge.md).

## License

[GNU General Public License v3.0](LICENSE), the same as Krita AI Diffusion. PhotoCraft itself and the host changes in its fork are MIT OR Apache-2.0. The plug-in and PhotoCraft are separate programs that communicate over a protocol.

AI models you download through the plug-in come with their own licenses, and some don't allow commercial use. The plug-in shows each model's license before downloading it.
