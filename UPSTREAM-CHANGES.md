# Changes to upstream Krita AI Diffusion files

This project keeps Krita AI Diffusion's files as unchanged as possible, so later upstream releases can be merged with `git merge` (REQ-38.0.3). Every upstream file this project changes is listed here with the reason.

- **Upstream:** [`Acly/krita-ai-diffusion`](https://github.com/Acly/krita-ai-diffusion)
- **Base:** tag `v1.54.0-pre`, commit `828b70c`
- **Not upstream files:** code added by this project lives in `photocraft_host/`, `packaging/` and `tests/photocraft/`, and isn't listed here.

**Status values:**
- **changed**: the file differs from upstream.
- **pending**: the design expects to change the file, but it hasn't been changed yet.
- **removed**: the file is deleted here.

| File | Status | Reason | Task |
|---|---|---|---|
| `README.md` | changed | Replaced with this project's README, which carries the attribution (REQ-38.1). When merging, keep ours. | TASK-2 |
| `ai_diffusion/__init__.py` | pending | Accept the PhotoCraft host in the Krita version check | TASK-24 |
| `ai_diffusion/util.py` | pending | `user_data_dir` comes from the host | TASK-24 |
| `ai_diffusion/document.py` | pending | Relax the 8-bit RGBA check; show the colour-conversion note (REQ-37) | TASK-24 |
| `ai_diffusion/persistence.py` | pending | `JobParams.from_dict` restores enums (REQ-33.0.2) | TASK-24 |
| `ai_diffusion/localization.py` | pending | Default to the host locale (REQ-34.0.2) | TASK-24 |
| `ai_diffusion/ui/widget.py` | pending | `ANIMATION_ENABLED`: hide the Animation workspace | TASK-27 |
| `ai_diffusion/ui/actions.py` | pending | `ANIMATION_ENABLED`: skip Animation in Toggle Workspace | TASK-27 |
| `ai_diffusion/ui/custom_workflow.py` | pending | `ANIMATION_ENABLED`: hide Generate Animation | TASK-27 |
| `ai_diffusion/ui/live.py` | pending | `ANIMATION_ENABLED`: hide the Record button | TASK-27 |
| `ai_diffusion/settings.py` | pending | Gate cloud-only keys; drop `last_news` | TASK-36 |
| `ai_diffusion/backend/server.py` | pending | Default path, `extra_model_paths.yaml` section name, guard on Krita AI Diffusion installs | TASK-37 |
| `ai_diffusion/presets/models.json` | pending | License fields per model (REQ-29.0.4) | TASK-37 |
| `ai_diffusion/backend/cloud_client.py` | pending | Behind the cloud module loader (REQ-32) | TASK-39 |
| `ai_diffusion/ui/settings.py`, `ai_diffusion/ui/server.py` | pending | Cloud widgets gated; Krita AI Diffusion detection section | TASK-39, TASK-40 |
| `ai_diffusion/model/updates.py` | pending | Update source is this project's GitHub Releases (REQ-36) | TASK-43 |
| `ai_diffusion/language/*.json` | pending | Krita-specific strings adapted to PhotoCraft (REQ-34) | TASK-44 |

## Kept as upstream has them

- **Git submodules** `ai_diffusion/websockets` (python-websockets 14.2, `624a36c`) and `ai_diffusion/debugpy` (1.8.20, `7ac3d1f`), with `.gitmodules`. They stay at upstream's pinned commits. Upstream imports `websockets` from the vendored path (`from ..websockets.src import websockets`), so keeping the submodule avoids editing `comfy_client.py` and `__init__.py`.

  This differs from tech.md's literal plan of installing websockets as a normal dependency. The intent of that plan (pinned at upstream's commit, smallest diff) is unchanged.
- **Test images in Git LFS** (`tests/images/*.png`). When cloning, fetch them from upstream if this repository's LFS storage doesn't have them: `git lfs fetch upstream v1.54.0-pre`.

## Merging a new upstream release

The procedure is written down in TASK-46 (`docs/upstream-merge.md`).
