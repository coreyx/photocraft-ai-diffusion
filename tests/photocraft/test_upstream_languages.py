"""The plug-in in each of its 14 languages, and its default from PhotoCraft's (TASK-44, REQ-34):
the docker panel and the settings dialog as PhotoCraft receives them."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CATALOGS = HERE.parents[1] / "ai_diffusion" / "language"
LANGUAGES = sorted(p.stem for p in CATALOGS.glob("*.json"))

#: Text of the settings dialog's pages and buttons, in English.
KEYS = [
    "Connection",
    "Styles",
    "Diffusion",
    "Interface",
    "Performance",
    "Plugin",
    "Restore Defaults",
    "Configure Image Diffusion",
    "Server Configuration",
    "Open Settings folder",
]


def _run(tmp_path: Path, language: str, locale: str) -> dict:
    run = subprocess.run(
        [
            sys.executable,
            str(HERE / "upstream_languages.py"),
            str(tmp_path / "data"),
            language,
            locale,
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert run.returncode == 0, run.stderr[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _translations(language: str) -> dict[str, str]:
    data = json.loads((CATALOGS / f"{language}.json").read_text(encoding="utf-8"))["translations"]
    return {k: v for k, v in data.items() if v}


def test_there_are_14_languages():
    assert len(LANGUAGES) == 14 and "en" in LANGUAGES


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_panel_and_settings_in_each_language(language: str, tmp_path: Path):
    """REQ-34.1: chosen in the settings (as after switching and restarting)."""
    result = _run(tmp_path, language, "en")
    assert result["language"] == language
    texts = set(result["texts"])
    translations = _translations(language)
    expected = {key: translations.get(key, key) for key in KEYS}
    # Some arrive as rich text (a link's label inside its markup).
    missing = {k: v for k, v in expected.items() if not any(v in text for text in texts)}
    assert not missing, missing
    if language != "en":
        # Upstream's catalogs cover these to different degrees (French and Thai about half).
        assert sum(1 for k, v in expected.items() if v != k) >= len(KEYS) // 2, "translated"


def test_photocrafts_language_is_the_default(tmp_path: Path):
    """REQ-34.2: Japanese PhotoCraft, no language chosen in the plug-in."""
    result = _run(tmp_path, "-", "ja")
    assert result["language"] == "ja"
    assert _translations("ja")["Configure Image Diffusion"] in result["texts"]


def test_an_unknown_host_language_falls_back_to_english(tmp_path: Path):
    result = _run(tmp_path, "-", "eo")
    assert result["language"] == "en"
    assert "Configure Image Diffusion" in result["texts"]
