---
id: APP-007
skill: app-analysis
category: pixel contract
classification: observed
confidence: high
source: krita-ai-diffusion ai_diffusion/document.py:194-202; ai_diffusion/image.py:335-349; photocraft AGENTS.md:64, crates/color/src/lib.rs:28-60
conflicts_with: []
---

Krita AI Diffusion only works on 8-bit RGBA documents and refuses everything else with an error. PhotoCraft documents can be 8, 16 or 32-bit in RGB, CMYK, Lab, Grayscale and other modes. Its rules forbid u8-only public pixel paths and assuming sRGB. Matching Krita exactly means refusing unsupported documents. The alternative is converting at the host boundary, which is a requirements decision.
