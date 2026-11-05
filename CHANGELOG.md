# Changelog

All notable changes to AI Diffusion for PhotoCraft are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Changes inherited from Krita AI Diffusion are in its own release notes; this file covers what this project adds and changes.

## [Unreleased]

### Added
- Krita AI Diffusion v1.54.0-pre as a PhotoCraft process plug-in:
  - generate, refine, inpaint, Live and upscale;
  - regional prompts, control layers and pose editing;
  - styles and custom ComfyUI graphs.

  It needs the PhotoCraft built from the `coreyx/photocraft` fork (`feat/process-plugins`).
- A `krita` API stand-in backed by PhotoCraft, and a mirror that shows the plug-in's Qt panels, menus and dialogs as native PhotoCraft UI.
- Documents in any bit depth and in RGB, Grayscale, CMYK or Lab are converted for generation instead of refused.
- Previews are shown outside the document, so they add no undo step and are never saved.
- The plug-in's state (prompts, history, regions) is stored in the document and restored when it's reopened.
- Krita AI Diffusion reuse:
  - detects its configurations on this computer;
  - uses the same ComfyUI server, a managed install included, without changing it;
  - imports settings and files, with tokens only after a second confirmation;
  - offers this plug-in's own server sharing the same models.
- Each model's license is shown before it's downloaded, with non-commercial terms marked.
- Packages for Windows x64, macOS (Apple silicon and Intel) and Linux x64. Each bundles Python 3.12 and installs its runtime on first start, behind a setup panel.
- Updates from this project's GitHub releases, checksum-verified and installed by PhotoCraft.
- The UI follows PhotoCraft's language, in all 14 languages.
- A merge procedure for new Krita AI Diffusion releases (`docs/upstream-merge.md`), with a check that `UPSTREAM-CHANGES.md` lists exactly the upstream files changed.

### Changed
- The UI names PhotoCraft where Krita AI Diffusion names Krita, and credits Krita AI Diffusion.
- Documentation and project links point at this project.
- Flux Redux downloads from Black Forest Labs' own Hugging Face repository. It's gated, so accept its license there first.

### Removed
- The online-service mode. Its client moved to an optional `ai_diffusion_cloud` module that this project's packages don't include.
- The Animation workspace, until PhotoCraft has a Frame Animation panel.

### Fixed
- The plug-in crashed about 30 seconds after its first HTTPS request (such as the update check) when another OpenSSL was on `PATH`, Git for Windows' for one. Qt now uses the operating system's TLS on Windows and macOS.
- On Windows, text in panels drawn as images (the Generate button) showed as empty boxes: Qt's offscreen platform found no fonts.
- With no release published yet, the update check logged an error with a traceback. It now logs that no release is published. The warning about not being installed in a `pykrita` folder no longer appears in PhotoCraft.
- Connecting could hang at "Connecting" because a running task was garbage-collected.
- Selection feather, blend and padding reverted to their defaults on restart.
- Connecting again right after connecting failed with `CancelledError`.
- `extra_model_paths.yaml` lost the plug-in's section when a `model_patches` line was added.
- Reopening a document whose embedded workflow was active didn't restore its graph.

### Security
- Custom and managed ComfyUI servers were sent the online service's access token when connecting. They now get only the ComfyUI token set for them.
- Diagnostics hide the data folder, home folder, user name, launch nonce and token values.
- The debugger port upstream opens when its `debugpy` checkout is present stays closed unless `PHOTOCRAFT_PLUGIN_DEBUG=1` is set.
