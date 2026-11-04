---
id: APP-002
skill: app-analysis
category: host extension surface
classification: observed
confidence: high
source: photocraft docs/control-protocol.md:11-115,192,381-382,476-485; crates/engine/src/inspect.rs:20,45,52
conflicts_with: []
---

The desktop control channel (loopback TCP, JSON lines, bearer token) can inspect documents and run any engine command. In bridge mode it has no direct pixel write, no bulk selection-mask read, no change events and no way to add UI. Requests are capped at 1 MiB and replies time out after 60 s. Used as-is it cannot support a native-feeling panel or live painting. The process-plug-in host must add these capabilities.
