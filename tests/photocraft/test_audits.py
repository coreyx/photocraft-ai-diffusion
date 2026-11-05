"""The audits (TASK-45, REQ-39.4, 39.5): run on a whole plug-in session against a stand-in
ComfyUI server, with secrets set, and on themselves."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .audits import log_texts, outside_allowed, secrets_in

HERE = Path(__file__).resolve().parent


def test_a_session_writes_no_secret_and_asks_only_allowed_hosts(tmp_path: Path):
    """The cloud script's session (start-up, connecting, generating) with a ComfyUI token and an
    online-service token in its settings, and PhotoCraft's launch nonce."""
    nonce = "audit-nonce-5e2c"
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PHOTOCRAFT_PLUGIN_NONCE": nonce,
        "AI_DIFFUSION_UPDATE_URL": "http://127.0.0.1:9/releases/latest",
    }
    env.pop("PHOTOCRAFT_AI_CLOUD", None)
    run = subprocess.run(
        [sys.executable, str(HERE / "upstream_cloud.py"), str(tmp_path / "data"), "off"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        cwd=tmp_path,
        env=env,
    )
    assert run.returncode == 0, run.stderr[-3000:]
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["prompts"] == 1, "a whole session ran"
    # The script stores this online-service token; it must reach no log and no output.
    token = "token-from-the-online-service"
    texts = [run.stdout, run.stderr, *log_texts(tmp_path / "data")]
    assert secrets_in(texts, [token, nonce]) == []
    assert outside_allowed(result["hosts"], [result["stub_host"]]) == []


def test_the_audits_find_what_they_look_for(tmp_path: Path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "client.log").write_text("connecting with sk-1234 to 127.0.0.1")
    (tmp_path / "logs" / "client.log.1").write_text("older: tok-9")
    texts = log_texts(tmp_path)
    assert secrets_in(texts, ["sk-1234", "tok-9", "", "absent"]) == ["sk-1234", "tok-9"]
    hosts = [
        "127.0.0.1",
        "api.github.com",
        "comfy.example",
        "api.interstice.cloud",
        "tracker.example",
    ]
    assert outside_allowed(hosts, ["comfy.example"]) == ["api.interstice.cloud", "tracker.example"]
