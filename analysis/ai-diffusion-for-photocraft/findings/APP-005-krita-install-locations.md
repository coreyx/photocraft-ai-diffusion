---
id: APP-005
skill: app-analysis
category: install detection
classification: observed
confidence: high
source: krita-ai-diffusion ai_diffusion/util.py:30-54; settings.py:164,178-195; backend/server.py:84-122,933-995; docs/src/content/docs/common-issues.mdx:104-111
conflicts_with: []
---

Krita AI Diffusion keeps its user data in `<krita appdata>/ai_diffusion`: `%APPDATA%\krita\ai_diffusion` on Windows, `~/.local/share/krita/ai_diffusion` on Linux and `~/Library/Application Support/krita/ai_diffusion` on macOS. The fallback is `<GenericDataLocation>/krita-ai-diffusion`.

- The plugin itself is at `<krita appdata>/pykrita/ai_diffusion/`.
- `settings.json` holds `server_mode`, `server_path` (default `<user data>/server`), `server_url`, `server_backend` and `server_arguments`.
- The managed model store is `<server_path>/models/<folder>/`, plus `<server_path>/ComfyUI/models/` and any extra sections in `<server_path>/ComfyUI/extra_model_paths.yaml`.

Flatpak and MSIX paths are inferred only.
