---
id: APP-004
skill: app-analysis
category: licensing
classification: observed
confidence: high
source: krita-ai-diffusion LICENSE:1-2; photocraft docs/contributing.md:4-5, AGENTS.md:65, crates/raw/README.md:82, crates/affinity/README.md:85, Cargo.toml:9
conflicts_with: []
---

Krita AI Diffusion is GPL-3.0, including its bundled styles, presets, tag lists, translations and icons. PhotoCraft accepts only MIT OR Apache-2.0 contributions and in practice refuses GPL-derived code (its clean-room rule). Any code derived from Krita AI Diffusion must stay outside PhotoCraft's tree. Host changes contributed to PhotoCraft must be written independently and licensed MIT OR Apache-2.0.
