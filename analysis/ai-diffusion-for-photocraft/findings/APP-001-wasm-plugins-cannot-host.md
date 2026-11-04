---
id: APP-001
skill: app-analysis
category: host extension surface
classification: observed
confidence: high
source: photocraft crates/plugins/src/runtime.rs:14,208-210; crates/plugins/src/manifest.rs:18-20; docs/plugins.md:39-48,183-187; docs/scorecard.md:263
conflicts_with: []
---

PhotoCraft's only plug-in mechanism is ABI v1: sandboxed WebAssembly filter modules run by `wasmi`, with no host imports (no network, files, clock or UI). `Kind::Filter` is the only kind. Panel plug-ins, progress callbacks and reading other layers are planned for an unbuilt ABI v2, whose planned scope still has no network access. It cannot host a ComfyUI client with a docked panel.
