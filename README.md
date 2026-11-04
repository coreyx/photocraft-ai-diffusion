# AI Diffusion for PhotoCraft

Generative AI inside [PhotoCraft](https://github.com/storytold/photocraft), the open-source Rust image editor. Generate, refine, inpaint, live-paint and upscale with local or remote [ComfyUI](https://github.com/comfyanonymous/ComfyUI), using regional prompts, control layers, styles and custom ComfyUI graphs, all from a panel inside PhotoCraft.

> **Status: in development.** This is not usable yet. Work is tracked in [`spec/ai-diffusion-for-photocraft/tasks.md`](spec/ai-diffusion-for-photocraft/tasks.md).

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

## License

[GNU General Public License v3.0](LICENSE), the same as Krita AI Diffusion. PhotoCraft itself and the host changes in its fork are MIT OR Apache-2.0. The plug-in and PhotoCraft are separate programs that communicate over a protocol.

AI models you download through the plug-in come with their own licenses, and some don't allow commercial use. The plug-in shows each model's license before downloading it.
