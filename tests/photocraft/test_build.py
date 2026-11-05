"""The package build (TASK-42): what each platform's zip holds, its manifest, and the checks
that stop a build (a download whose checksum doesn't match). Downloads are faked here; a real
build is ``python packaging/build.py``."""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import tomllib

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packaging"))

import build  # pyright: ignore[reportMissingImports]  (packaging/ is put on the path above)

#: The keys PhotoCraft's manifest allows (``docs/process-plugins.md``); others are refused.
MANIFEST_KEYS = {"id", "name", "version", "protocol", "license", "description", "command"}


def _tar(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _zip(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Fake python-build-standalone and uv archives, with the platform pins pointed at them."""
    files: dict[str, bytes] = {}
    for name, platform in list(build.PLATFORMS.items()):
        windows = name.startswith("windows")
        python = {"python/python.exe": b"MZ"} if windows else {"python/bin/python3": b"\x7fELF"}
        python["python/LICENSE.txt"] = b"PSF"
        uv = (
            _zip({"uv.exe": b"MZuv", "uvx.exe": b"MZuvx"})
            if windows
            else _tar({f"{platform.uv.name.removesuffix('.tar.gz')}/uv": b"\x7fELFuv"})
        )
        python_data = _tar(python)
        files[platform.python.name], files[platform.uv.name] = python_data, uv
        pins = build.Platform(
            build.Download(platform.python.name, hashlib.sha256(python_data).hexdigest()),
            build.Download(platform.uv.name, hashlib.sha256(uv).hexdigest()),
            platform.python_program,
            platform.uv_program,
        )
        monkeypatch.setitem(build.PLATFORMS, name, pins)
    return files


def _get(files: dict[str, bytes]):
    def get(url: str) -> bytes:
        return files[url.rsplit("/", 1)[1]]

    return get


@pytest.mark.parametrize("name", sorted(build.PLATFORMS))
def test_each_platform_package(name: str, downloads: dict[str, bytes], tmp_path: Path):
    package = build.build(name, "1.2.3", tmp_path / "dist", tmp_path / "cache", _get(downloads))
    assert package.name == f"ai-diffusion-for-photocraft-1.2.3-{name}.zip"
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        manifest = tomllib.loads(archive.read("photocraft-plugin.toml").decode())
        uv_program = build.PLATFORMS[name].uv_program
        assert {
            "photocraft-plugin.toml",
            manifest["command"][0],
            f"uv/{uv_program}",
            "ai_diffusion/__init__.py",
            "ai_diffusion/backend/cloud_client.py",
            "photocraft_host/bootstrap.py",
            "photocraft_host/framing.py",
            "runtime/pyproject.toml",
            "runtime/uv.lock",
            "LICENSE",
            "NOTICE",
            "THIRD-PARTY.txt",
        } <= names
        assert not [n for n in names if n.startswith(("ai_diffusion_cloud/", "tests/", "spec/"))]
        assert not [n for n in names if n.startswith("/") or ".." in n.split("/")], "no escapes"
        assert "uv/uvx.exe" not in names, "only uv itself"
        third_party = archive.read("THIRD-PARTY.txt").decode()
    assert set(manifest) == MANIFEST_KEYS
    assert (manifest["id"], manifest["name"], manifest["version"]) == (
        "io.github.coreyx.ai-diffusion-for-photocraft",
        "AI Diffusion for PhotoCraft",
        "1.2.3",
    )
    assert manifest["protocol"] == 1 and manifest["license"] == "GPL-3.0-only"
    assert manifest["command"][1:] == ["-I", "photocraft_host/bootstrap.py"]
    assert (
        f"CPython {build.PYTHON_VERSION}" in third_party and f"uv {build.UV_VERSION}" in third_party
    )


def test_a_download_that_doesnt_match_its_checksum_stops_the_build(
    downloads: dict[str, bytes], tmp_path: Path
):
    name = "linux-x64"
    downloads[build.PLATFORMS[name].uv.name] = b"tampered"
    with pytest.raises(SystemExit, match="SHA-256"):
        build.build(name, "1.0.0", tmp_path / "dist", tmp_path / "cache", _get(downloads))


def test_downloads_are_cached_by_checksum(downloads: dict[str, bytes], tmp_path: Path):
    fetched: list[str] = []

    def get(url: str) -> bytes:
        fetched.append(url)
        return _get(downloads)(url)

    for _ in range(2):
        build.build("macos-arm64", "1.0.0", tmp_path / "dist", tmp_path / "cache", get)
    assert len(fetched) == 2, "the second build uses the cache"


def test_sha256sums_lists_every_package(downloads: dict[str, bytes], tmp_path: Path):
    out = tmp_path / "dist"
    packages = [
        build.build(n, "1.0.0", out, tmp_path / "cache", _get(downloads))
        for n in ("linux-x64", "windows-x64")
    ]
    sums = build.write_sums(packages, out).read_text().splitlines()
    assert sums == [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in packages]


def test_build_output_in_the_checkout_ignores_itself(tmp_path: Path, monkeypatch):
    """Upstream's .gitignore stays unchanged: the folders the build makes ignore themselves."""
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "build", lambda *_args: tmp_path / "dist" / "package.zip")
    monkeypatch.setattr(build, "write_sums", lambda _packages, out: out / "SHA256SUMS")
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    assert build.main(["--platform", "linux-x64"]) == 0
    assert (tmp_path / "dist" / ".gitignore").read_text() == "*\n"
    assert (tmp_path / ".cache" / ".gitignore").read_text() == "*\n"
    assert not (tmp_path / ".cache" / "packaging" / ".gitignore").exists()
    assert build.main(["--platform", "linux-x64", "--out", str(elsewhere)]) == 0
    assert not (elsewhere / ".gitignore").exists(), "only folders in the checkout"
