"""Graph-parity tooling (design.md D12).

Captures what unmodified upstream Krita AI Diffusion v1.54.0-pre sends to ComfyUI
for a fixed set of document scenarios, so this project's plug-in can be checked
against it: same scenario in, same ``WorkflowInput`` and same ComfyUI prompt out.

- ``scenarios``: the scenario matrix, built only through the ``krita`` API so the
  same scenarios can later run on this project's ``krita`` shim.
- ``catalog``: a ``ClientModels`` holding every model in upstream's catalog, so
  graphs can be built without a ComfyUI server.
- ``normalize``: turns a ``WorkflowInput`` and a ComfyUI prompt into stable,
  comparable JSON (random image ids and seeds-from-uuids removed).
- ``driver``: runs the scenarios against whichever ``ai_diffusion`` package is
  first on ``sys.path`` and writes or compares fixtures.
- ``capture_parity``: command-line entry point that checks the upstream tag out
  into a temporary worktree and runs the driver there.
"""
