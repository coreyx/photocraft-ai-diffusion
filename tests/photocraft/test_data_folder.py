"""Upstream imported as PhotoCraft runs it (not in test mode): its files go to the data folder
PhotoCraft gives the plug-in, never to Krita AI Diffusion's (REQ-13.3), and it starts in
PhotoCraft's language when none was chosen (REQ-34.2).

Each case runs in a fresh Python process, because upstream decides its data folder and
language once, when it is first imported.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

#: Starts the plug-in's Python side against the mock host, imports upstream, loads its
#: settings, and prints where everything went.
SCRIPT = r"""
import json, os, sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication

# Krita AI Diffusion's folders, as upstream would pick them, in Qt's test locations.
QStandardPaths.setTestModeEnabled(True)
app = QApplication([])
generic = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
krita_dirs = [Path(generic) / "krita-ai-diffusion"]
existed = [d.exists() for d in krita_dirs]

repo, data_dir, locale, chosen = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, repo)
if chosen:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "settings.json").write_text(json.dumps({"language": chosen}))

from photocraft_host import main
from photocraft_host.transport import Transport
from tests.photocraft.mock_host import MockHost

main.install_krita_shim()
import krita

host = MockHost()
link = Transport(host.plugin_reader, host.plugin_writer)
link.start()
krita.attach(link, "test", locale=locale, data_dir=data_dir)

import ai_diffusion
from ai_diffusion import util
from ai_diffusion.localization import Localization
from ai_diffusion.settings import settings

settings.load()
print(json.dumps({
    "is_mock": getattr(krita, "IS_MOCK", False),
    "user_data_dir": str(util.user_data_dir),
    "settings": str(settings.default_path),
    "log_dir": str(util.log_dir),
    "language": Localization.current.id,
    "setting": settings.language,
    "krita_dirs_created": [d.exists() and not e for d, e in zip(krita_dirs, existed)],
}))
"""

REPO = Path(__file__).resolve().parents[2]


def run_plugin(data_dir: Path, locale: str, chosen: str = "") -> dict:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    data_dir.parent.mkdir(parents=True, exist_ok=True)  # the working directory
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(REPO), str(data_dir), locale, chosen],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
        cwd=data_dir.parent,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_files_go_to_the_host_data_folder_and_the_language_follows_photocraft(tmp_path: Path):
    data_dir = tmp_path / "process-plugins-data" / "plugin"
    out = run_plugin(data_dir, "ja-JP")
    assert not out["is_mock"], "upstream ran as in PhotoCraft, not in test mode"
    assert Path(out["user_data_dir"]) == data_dir
    assert Path(out["settings"]) == data_dir / "settings.json"
    assert Path(out["log_dir"]) == data_dir / "logs"
    assert (data_dir / "settings.json").exists() and (data_dir / "logs" / "client.log").exists()
    assert out["krita_dirs_created"] == [False], "nothing in Krita AI Diffusion's folder"
    assert (out["language"], out["setting"]) == ("ja", "ja")
    assert "language" not in json.loads((data_dir / "settings.json").read_text())


def test_a_chosen_language_wins_over_photocraft(tmp_path: Path):
    out = run_plugin(tmp_path / "data", "ja", chosen="fr")
    assert (out["language"], out["setting"]) == ("fr", "fr")


def test_an_unsupported_photocraft_language_falls_back_to_english(tmp_path: Path):
    out = run_plugin(tmp_path / "data", "de-DE")
    assert (out["language"], out["setting"]) == ("en", "en")
