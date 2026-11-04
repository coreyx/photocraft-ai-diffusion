---
id: APP-006
skill: app-analysis
category: install detection
classification: observed
confidence: high
source: krita-ai-diffusion ai_diffusion/backend/server.py:158-174,805-810; backend/resources.py:559-562; backend/comfy_client.py:180-263
conflicts_with: []
---

Krita AI Diffusion checks for installed models two ways:

- **Offline**: it tests whether each catalog file path exists under `server_path` or `server_path/ComfyUI`. This check ignores `extra_model_paths.yaml`.
- **Online**: it asks the running ComfyUI (`/object_info` loader choices and `/api/etn/model_info`). This path honors `extra_model_paths.yaml`.

Reusing a Krita install's models therefore means pointing our ComfyUI's `extra_model_paths.yaml` at Krita's model folders and then relying on the online check.
