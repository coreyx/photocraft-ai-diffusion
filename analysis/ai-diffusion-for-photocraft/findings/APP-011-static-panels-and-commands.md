---
id: APP-011
skill: app-analysis
category: host extension surface
classification: observed
confidence: high
source: photocraft crates/engine/src/cmd.rs:11-28,237-246; crates/ui-egui/src/panels/panel_docking.rs:25-44; crates/ui-egui/src/dock.rs:22-80; crates/ui-egui/src/panels/dock.rs:98-122
conflicts_with: []
---

PhotoCraft's command registry is a static `OnceLock` of `fn`-pointer `CommandSpec`s, and its dock panels come from a static `PANELS` table and a closed `dock::Group` enum. Nothing can be registered at run time. Plug-in-provided panels, commands and menu items require new host machinery: a dynamic registry or a generic "plug-in panel" slot.
