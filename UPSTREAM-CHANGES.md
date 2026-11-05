# Changes to upstream Krita AI Diffusion files

This project keeps Krita AI Diffusion's files as unchanged as possible, so later upstream releases can be merged with `git merge` (REQ-38.0.3). Every upstream file this project changes is listed here with the reason.

- **Upstream:** [`Acly/krita-ai-diffusion`](https://github.com/Acly/krita-ai-diffusion)
- **Base:** tag `v1.54.0-pre`, commit `828b70c`
- **Not upstream files:** code added by this project lives in `photocraft_host/`, `packaging/`, `tests/photocraft/` and `tests/photocraft_upstream/`, and isn't listed here.

**Status values:**
- **changed**: the file differs from upstream.
- **pending**: the design expects to change the file, but it hasn't been changed yet.
- **removed**: the file is deleted here.

| File | Status | Reason | Task |
|---|---|---|---|
| `README.md` | changed | Replaced with this project's README, which carries the attribution (REQ-38.1). When merging, keep ours. | TASK-2 |
| `ai_diffusion/__init__.py` | changed | Accept the PhotoCraft host in the Krita version check. The `krita` stand-in marks itself with `photocraft_host`, which every PhotoCraft branch below checks for. | TASK-24 |
| `ai_diffusion/util.py` | changed | `user_data_dir` is the data folder PhotoCraft gives the plug-in (REQ-13.0.3). Without one it raises rather than fall back to Krita AI Diffusion's folder. | TASK-24 |
| `ai_diffusion/document.py` | changed | In PhotoCraft, RGB, Grayscale, CMYK and Lab in any depth are accepted, and the other modes are refused by name. `color_conversion_note` describes the conversion (REQ-37). Krita's check is unchanged. | TASK-24 |
| `ai_diffusion/ui/diffusion.py` | changed | The docker shows `color_conversion_note` above the workspaces (REQ-37.0.2). Empty, so hidden, in Krita. | TASK-24 |
| `ai_diffusion/model/jobs.py` | changed | `JobParams.from_dict` restores `workflow_kind` and `inpaint_mode` as enums and `frame` as a tuple; jobs restored from a document had strings (REQ-33.0.2). The design placed this in `persistence.py`; the function lives here. | TASK-24 |
| `ai_diffusion/localization.py` | changed | The default language is PhotoCraft's UI language when there is a catalog for it, else English (REQ-34.0.2): `language_for_locale`, `default_language`. In Krita the default stays English. | TASK-24 |
| `ai_diffusion/ui/__init__.py` | changed | Defines `ANIMATION_ENABLED`: false in PhotoCraft (the `krita` stand-in's `photocraft_host` marker), true in Krita. Animation waits for a PhotoCraft timeline (REQ-26). | TASK-27 |
| `ai_diffusion/ui/widget.py` | changed | `ANIMATION_ENABLED`: the workspace menu leaves out Animation | TASK-27 |
| `ai_diffusion/ui/actions.py` | changed | `ANIMATION_ENABLED`: Toggle Workspace skips Animation (and starts from Generate if a document was in Animation) | TASK-27 |
| `ai_diffusion/ui/custom_workflow.py` | changed | `ANIMATION_ENABLED`: the Graph workspace's generate menu leaves out Generate Animation | TASK-27 |
| `ai_diffusion/ui/live.py` | changed | `ANIMATION_ENABLED`: the Live Record button is hidden | TASK-27 |
| `ai_diffusion/settings.py` | changed | `language` defaults to `default_language()`, and is written to `settings.json` only when it differs from that default, so the plug-in follows PhotoCraft's language until the user picks one (REQ-34.0.2). Importing Krita AI Diffusion's settings should drop an English `language` for the same reason (TASK-40). | TASK-24 |
| `ai_diffusion/settings.py` | pending | Gate cloud-only keys; drop `last_news` | TASK-36 |
| `ai_diffusion/backend/server.py` | pending | Default path, `extra_model_paths.yaml` section name, guard on Krita AI Diffusion installs | TASK-37 |
| `ai_diffusion/presets/models.json` | pending | License fields per model (REQ-29.0.4) | TASK-37 |
| `ai_diffusion/backend/cloud_client.py` | pending | Behind the cloud module loader (REQ-32) | TASK-39 |
| `ai_diffusion/ui/settings.py`, `ai_diffusion/ui/server.py` | pending | Cloud widgets gated; Krita AI Diffusion detection section | TASK-39, TASK-40 |
| `ai_diffusion/model/updates.py` | pending | Update source is this project's GitHub Releases (REQ-36) | TASK-43 |
| `ai_diffusion/language/*.json` | pending | Krita-specific strings adapted to PhotoCraft (REQ-34) | TASK-44 |

## Kept as upstream has them

- **The debugger in `extension.py`.** Upstream opens a debugger port (debugpy on 127.0.0.1:5678) when its `debugpy` checkout is present. The plug-in's start-up (`photocraft_host/main.py`) makes that import fail unless `PHOTOCRAFT_PLUGIN_DEBUG=1` is set, so `extension.py` is unchanged and a PhotoCraft plug-in never accepts code from a port unasked.

- **Git submodules** `ai_diffusion/websockets` (python-websockets 14.2, `624a36c`) and `ai_diffusion/debugpy` (1.8.20, `7ac3d1f`), with `.gitmodules`. They stay at upstream's pinned commits. Upstream imports `websockets` from the vendored path (`from ..websockets.src import websockets`), so keeping the submodule avoids editing `comfy_client.py` and `__init__.py`.

  This differs from tech.md's literal plan of installing websockets as a normal dependency. The intent of that plan (pinned at upstream's commit, smallest diff) is unchanged.
- **Build and test configuration**: `pyproject.toml`, `requirements.txt` and `.gitignore` stay unchanged. This project's runtime pins live in `packaging/runtime/pyproject.toml`, its development dependencies in `requirements-photocraft.txt`, and its type-check settings in `packaging/pyrightconfig.json`. Local ignores (`.venv/`, coverage output) go in `.git/info/exclude`.
- **Upstream CI** `.github/workflows/test.yml` is kept unchanged. It installs a ComfyUI server and downloads models, so it is disabled for this repository in GitHub's Actions settings (`gh workflow disable test.yml`) rather than edited. This project's CI is `.github/workflows/photocraft.yml`.
- **Test images in Git LFS** (`tests/images/*.png`). When cloning, fetch them from upstream if this repository's LFS storage doesn't have them: `git lfs fetch upstream v1.54.0-pre`.

## Merging a new upstream release

The procedure is written down in TASK-46 (`docs/upstream-merge.md`).
