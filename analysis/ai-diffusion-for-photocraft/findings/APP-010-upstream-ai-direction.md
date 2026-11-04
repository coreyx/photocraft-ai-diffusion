---
id: APP-010
skill: app-analysis
category: upstream governance
classification: documented
confidence: medium
source: photocraft docs/gaps.md:226-239; docs/roadmap.md:93,111; docs/scorecard.md:263-264; docs/target-app-parity.md:87,227-229; README.md:416
conflicts_with: []
---

PhotoCraft's maintainers gate all AI features on owner decision #41 (model licences, local vs remote). The planned AI direction is local ONNX inference in an unbuilt `ml` crate (subject selection, matting), not a ComfyUI client. Plug-in hosting beyond ABI v1 also needs owner decisions. The same team ships ArtCraft as its AI studio. It is uncertain whether upstream would accept a generic process-plug-in host.
