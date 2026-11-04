---
id: APP-012
skill: app-analysis
category: persistence
classification: observed
confidence: high
source: krita-ai-diffusion ai_diffusion/document.py:126-130,258-266; ai_diffusion/persistence.py:164,253; photocraft crates/engine/src/cmd/layer_xmp_cmds.rs:1-3,17,88; crates/doc/src/lib.rs:680,863-867; AGENTS.md:138-141
conflicts_with: []
---

Krita AI Diffusion persists per-document state as `.kra` annotations: a document id, `ui.json`, and history results as concatenated WebP blobs. PhotoCraft has no generic named-blob store on documents. Layer XMP (read/write, up to 4 MiB, kept in PSD, PSB, TIFF and `.pcraft`) and document XMP (no raw setter) are the nearest equivalents. Adding a new `Document` field forces `.pcraft` format changes.
