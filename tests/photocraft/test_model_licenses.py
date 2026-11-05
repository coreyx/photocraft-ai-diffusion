"""Every model in the catalog has a license (REQ-29.0.4), so a model an upstream merge adds
without one fails here rather than showing in the installer without its terms
(``docs/upstream-merge.md``)."""

from __future__ import annotations

import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[2] / "ai_diffusion" / "presets" / "models.json"
RESTRICTIONS = {"open", "restricted", "non_commercial"}


def test_every_model_has_a_license():
    missing = []
    for section, models in json.loads(CATALOG.read_text(encoding="utf-8")).items():
        for model in models:
            terms = model.get("license") or {}
            if not (
                terms.get("name")
                and str(terms.get("url", "")).startswith("https://")
                and terms.get("restriction") in RESTRICTIONS
            ):
                missing.append(f"{section}: {model.get('name')}")
    assert missing == []
