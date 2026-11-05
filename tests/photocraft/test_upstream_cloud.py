"""The cloud module boundary in a running plug-in (TASK-39, REQ-32): without the cloud module, a
stored online-service mode, the Connection page and the requests made; with a stand-in cloud
module and the flag, the online service is offered and used."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

STUB_MODULE = """
class CloudClient:
    default_api_url = "https://api.cloud.example"
    default_web_url = "https://www.cloud.example"

    def __init__(self, url, access_token=""):
        self.url = url
        self.access_token = access_token
"""


def _run(work: Path, *args: str, flag: bool) -> dict:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    env.pop("PHOTOCRAFT_AI_CLOUD", None)
    # The update check asks this project's releases on GitHub; here a closed local port stands
    # in, so the test sees the request without the network.
    env["AI_DIFFUSION_UPDATE_URL"] = "http://127.0.0.1:9/releases/latest"
    if flag:
        env["PHOTOCRAFT_AI_CLOUD"] = "1"
    run = subprocess.run(
        [sys.executable, str(HERE / "upstream_cloud.py"), str(work / "data"), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        cwd=work,
        env=env,
    )
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def off(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return _run(tmp_path_factory.mktemp("cloud-off"), "off", flag=False)


@pytest.fixture(scope="module")
def stub(tmp_path_factory: pytest.TempPathFactory) -> dict:
    work = tmp_path_factory.mktemp("cloud-stub")
    module = work / "modules" / "ai_diffusion_cloud"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text(STUB_MODULE)
    return _run(work, "stub", str(work / "modules"), flag=True)


def test_a_stored_online_service_mode_loads_as_undecided(off: dict):
    """REQ-32.2: no error, and the stored access token isn't read either."""
    assert off["server_mode"] == "undefined"
    assert off["access_token"] is False


def test_the_connection_page_offers_only_local_and_custom_servers(off: dict):
    """REQ-32.1 (the Krita AI Diffusion options come with TASK-40)."""
    assert off["setup_options"] == [
        "<b>Option 1: Local Managed Server</b>",
        "<b>Option 2: Custom ComfyUI</b>",
    ]
    assert off["mode_buttons"] == ["managed", "external"]


def test_startup_and_generation_ask_no_host_but_the_server(off: dict):
    """REQ-32.1: the update check (this project's releases, here on a local port),
    connecting and generating reach no host but those."""
    assert (off["connection"], off["prompts"]) == ("connected", 1)
    assert off["hosts"] == [off["stub_host"]]
    assert off["cloud_client"] == "CloudUnavailable"


def test_with_the_cloud_module_the_online_service_is_offered_and_used(stub: dict):
    """REQ-32.4: under the module's own name, and connecting creates the module's client."""
    assert stub["server_mode"] == "cloud" and stub["access_token"] is True
    assert stub["setup_options"][0] == "<b>Option 1: Online Service</b>"
    assert "<a href='https://www.cloud.example'>www.cloud.example</a>" in stub["setup_links"][0]
    assert stub["mode_buttons"] == ["cloud", "managed", "external"]
    assert stub["cloud_client"] == {
        "module": "ai_diffusion_cloud",
        "url": "https://api.cloud.example",
        "token": True,
    }
