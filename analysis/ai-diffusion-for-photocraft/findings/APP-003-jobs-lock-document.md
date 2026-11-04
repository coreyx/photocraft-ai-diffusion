---
id: APP-003
skill: app-analysis
category: host runtime
classification: observed
confidence: high
source: photocraft crates/engine/src/jobs.rs:14,23-24
conflicts_with: []
---

While an engine job runs on a document, commands that would edit that document are disabled. On wasm, jobs run inline. A generation that waits minutes on ComfyUI must therefore not be modeled as an engine job holding the document. Krita AI Diffusion lets the user keep painting while generating.
