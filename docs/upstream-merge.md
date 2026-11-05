# Merging a Krita AI Diffusion release

AI Diffusion for PhotoCraft is Krita AI Diffusion with as few changes to its files as possible, so each upstream release can be merged with `git merge` (REQ-38.0.3). [`UPSTREAM-CHANGES.md`](../UPSTREAM-CHANGES.md) lists every upstream file this project changes, with the reason. A merge conflicts only in those files, and their entries say what to keep.

This file lives at the root of `docs/`, outside the handbook site's sources (`docs/src/`), so it doesn't appear on the site.

## Before you start

You need the `upstream` remote (`https://github.com/Acly/krita-ai-diffusion.git`), the development environment from `requirements-photocraft.txt`, and a ComfyUI with models for the GPU suite.

1. Fetch the release:

   ```sh
   git fetch upstream --tags
   ```

2. Check that the change log is up to date. It must list exactly the upstream files changed since the base it names:

   ```sh
   python tests/photocraft/upstream_changes.py
   ```

3. Preview the merge. This lists the files that will conflict and fails if one of them isn't in the change log. It changes nothing:

   ```sh
   python tests/photocraft/upstream_changes.py --preview v1.55.0
   ```

   Read the entries for the conflicting files before merging.

## Merge

1. Branch from `main`, and merge the release tag:

   ```sh
   git switch -c chore/merge-krita-ai-diffusion-1.55.0 main
   git merge v1.55.0
   ```

2. Resolve each conflict by keeping upstream's change and re-applying this project's, as the file's entry describes. The entries that need more than that:

   | File | What to do |
   |---|---|
   | `README.md` | Keep ours. Note anything new upstream that belongs in our README or the attribution. |
   | `ai_diffusion/language/*.json`, `new_language.json.template` | Take upstream's catalogs, then restore the two keys the entry names. |
   | `ai_diffusion/presets/models.json` | Take upstream's catalog, then give every new model a `license` traced to its original publisher, and record the source in `analysis/ai-diffusion-for-photocraft/reference/model-licenses.json`. `tests/photocraft/test_model_licenses.py` fails until every model has one. |
   | `ai_diffusion/backend/cloud_client.py` | This project's version is the cloud boundary. Upstream's client lives in `ai_diffusion_cloud/cloud_client.py`; apply upstream's changes there (below). |
   | `ai_diffusion/icons/interstice-*.svg` | Deleted here. If upstream changed them, copy the new ones to `ai_diffusion_cloud/icons/service-*.svg`. |

3. Upstream's changes to a moved file show up at its old path: as a conflict with this project's file there, or, for a deleted file, as a modify/delete conflict. Keep ours at the old path, and carry the changes over to the new place. For the online-service client:

   ```sh
   git diff v1.54.0-pre v1.55.0 -- ai_diffusion/backend/cloud_client.py \
     | sed 's#ai_diffusion/backend/cloud_client.py#ai_diffusion_cloud/cloud_client.py#g' \
     | git apply --3way
   ```

   The moved file uses absolute imports (`from ai_diffusion.… import`) where upstream's uses relative ones, so hunks touching imports may need editing by hand.

4. If upstream moved a submodule (`ai_diffusion/websockets`, `ai_diffusion/debugpy`), take upstream's commit.

## Check

1. Update the base in `UPSTREAM-CHANGES.md` (`**Base:** tag …, commit …`) to the release you merged. Then run the check again; the table must still list exactly the changed files:

   ```sh
   python tests/photocraft/upstream_changes.py
   ```

   Add an entry for any file you had to change that wasn't listed, and remove entries for changes upstream took over.

2. Run the checks and tests, as CI does (`.github/workflows/photocraft.yml`):

   ```sh
   ruff format --check photocraft_host packaging tests/photocraft tests/photocraft_upstream
   ruff check photocraft_host packaging tests/photocraft tests/photocraft_upstream
   pyright -p packaging/pyrightconfig.json
   python -m pytest tests/photocraft
   python -m pytest -p tests.photocraft.upstream_shim tests/test_layer.py tests/test_document.py \
     tests/test_persistence.py tests/test_model.py tests/test_text.py tests/test_pose.py \
     tests/test_custom_workflow.py tests/test_resolution.py tests/photocraft_upstream
   python -m pytest tests --ci --ignore=tests/photocraft --ignore=tests/test_server.py \
     --ignore=tests/test_client.py
   python packaging/contents.py
   ```

   These catch the usual merge fallout:
   - **The string audit** (`test_string_audit.py`): new user-visible text that names Krita.
   - **The model licenses test**: new models without a license.
   - **The package check** (`packaging/contents.py`): references to the online service in the package.
   - **The settings script**: new settings that aren't written on first run.

3. Compare the graphs the plug-in builds with Krita AI Diffusion's. Record the release's own graphs from an unchanged checkout of it, then check this project on the PhotoCraft stand-in against them:

   ```sh
   git worktree add ../krita-ai-diffusion-1.55.0 v1.55.0
   git -C ../krita-ai-diffusion-1.55.0 submodule update --init  # upstream needs its websockets
   python tests/photocraft/parity/driver.py --source ../krita-ai-diffusion-1.55.0 \
     --write tests/photocraft/fixtures/graphs
   python tests/photocraft/parity/driver.py --source . --host photocraft \
     --check tests/photocraft/fixtures/graphs
   git worktree remove --force ../krita-ai-diffusion-1.55.0  # it has submodules
   ```

   Every scenario should match. A difference means the plug-in doesn't follow a workflow change upstream made. Commit the new fixtures with the merge.

4. Run the GPU suite against a ComfyUI with models:

   ```sh
   PHOTOCRAFT_E2E_COMFYUI=127.0.0.1:8188 python -m pytest -p tests.photocraft.upstream_shim \
     tests/photocraft_upstream/test_e2e_gpu.py -v
   ```

5. Upstream releases that need a newer ComfyUI or new custom nodes also need the managed server's install checked: install a fresh one from the Connection page.

## Commit

Commit the merge as `chore: merge Krita AI Diffusion 1.55.0`, and open a pull request. Mention new features or workloads that the plug-in doesn't support yet in the pull request, and in the release notes once released.

## Rehearsal record

| Date | Upstream | Result |
|---|---|---|
| 2026-11-05 | `main` = `v1.54.0-pre` (`828b70c`), the current base | Nothing to merge: `--preview upstream/main` finds no conflict. |
| 2026-11-05 | One release of upstream changes, simulated by previewing `v1.53.0` with merge base `v1.54.0-pre` (77 upstream files changed) | 3 files in conflict, all listed: `ai_diffusion/__init__.py`, `ai_diffusion/ui/settings.py`, `ai_diffusion/ui/settings_widgets.py`. The other files merged cleanly. |
| 2026-11-05 | The graph comparison (Check, step 3) for `v1.54.0-pre` | Fixtures written from an unchanged checkout matched the committed ones; the plug-in on the PhotoCraft stand-in matched them in all 121 scenarios. |

The simulation runs upstream's changes from 1.53.0 to 1.54.0-pre in reverse against this project's changes. It shows how many files a release cycle's worth of upstream changes touches, without a newer upstream release to merge:

```sh
python tests/photocraft/upstream_changes.py --preview v1.53.0 --merge-base v1.54.0-pre
```
