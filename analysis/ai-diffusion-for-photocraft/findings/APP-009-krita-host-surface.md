---
id: APP-009
skill: app-analysis
category: host API needed
classification: observed
confidence: high
source: krita-ai-diffusion tests/mock/krita.py:1-5 (760 lines); ai_diffusion/document.py, layer.py, pose.py; inventory §5 (H-01..H-72)
conflicts_with: []
---

The Krita API surface Krita AI Diffusion uses is small and pixel-centric:

- the active document and its size;
- named binary annotations;
- the layer tree with stable UUIDs (create, move, remove, rename, group, show/hide, transparency masks);
- layer and projection pixel get/set in 8-bit BGRA;
- the selection mask;
- vector-layer SVG import for poses;
- a few animation calls;
- docker and action registration.

It uses no undo macros, colour profiles, view transforms or save calls. `tests/mock/krita.py` implements exactly this subset, and it is the reference spec for the host-protocol shim.
