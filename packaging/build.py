"""Build the plug-in's packages: one zip per platform, for PhotoCraft's Preferences › Plug-ins.

    python packaging/build.py --version 1.0.0 [--out dist] [--platform windows-x64 ...]

Each zip holds what the plug-in folder needs (tech.md, TASK-42):

- ``photocraft-plugin.toml``, the manifest, whose command runs the bootstrap with the bundled
  Python (``photocraft_host/bootstrap.py``);
- ``python/``: CPython 3.12 from python-build-standalone, for this platform;
- ``uv/``: the ``uv`` binary, which installs the runtime (PyQt6) on first run;
- ``ai_diffusion/`` and ``photocraft_host/`` (``contents.package_files``);
- ``runtime/``: the runtime's ``pyproject.toml`` and ``uv.lock``;
- ``LICENSE``, ``NOTICE`` and ``THIRD-PARTY.txt``.

Downloads are pinned and checked against the SHA-256 their publishers list; a mismatch stops
the build. The package is checked for anything of the online service (``contents.check``), and
``SHA256SUMS`` lists the zips built.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contents

ROOT = contents.ROOT
PLUGIN_ID = "io.github.coreyx.ai-diffusion-for-photocraft"
PLUGIN_NAME = "AI Diffusion for PhotoCraft"
PROTOCOL = 1

PYTHON_RELEASE = "20261026"
PYTHON_VERSION = "3.12.16"
PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/{release}/{name}"
)
UV_VERSION = "0.11.33"
UV_URL = "https://github.com/astral-sh/uv/releases/download/{version}/{name}"


@dataclass(frozen=True)
class Download:
    name: str
    sha256: str


@dataclass(frozen=True)
class Platform:
    """What one platform's package bundles, and how its manifest starts the plug-in."""

    python: Download
    uv: Download
    python_program: str  # inside the package
    uv_program: str  # inside the package's uv/ folder

    @property
    def command(self) -> list[str]:
        return [self.python_program, "-I", "photocraft_host/bootstrap.py"]


def _python(triple: str, sha256: str) -> Download:
    return Download(
        f"cpython-{PYTHON_VERSION}+{PYTHON_RELEASE}-{triple}-install_only_stripped.tar.gz", sha256
    )


#: Checksums as python-build-standalone's SHA256SUMS and uv's sha256.sum list them.
PLATFORMS: dict[str, Platform] = {
    "windows-x64": Platform(
        _python(
            "x86_64-pc-windows-msvc",
            "1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149",
        ),
        Download(
            "uv-x86_64-pc-windows-msvc.zip",
            "c253ce868ad48d29327b661452ce184c9e333e6d6f5bc8d6fcfbf4dd52b83442",
        ),
        "python/python.exe",
        "uv.exe",
    ),
    "macos-arm64": Platform(
        _python(
            "aarch64-apple-darwin",
            "353d5f1b4fd2715e7053f12f068435d5bbad16b91e057006b5d01e0925709a7e",
        ),
        Download(
            "uv-aarch64-apple-darwin.tar.gz",
            "d75e3d2bfc203d17388edaabd3aa37958edbcbfc36219e3ee0d31bb080b4baa2",
        ),
        "python/bin/python3",
        "uv",
    ),
    "macos-x64": Platform(
        _python(
            "x86_64-apple-darwin",
            "37c38fda76fec1fbf310adcbafb7f0d96af13b5511bf8ea954c3aa8eec185734",
        ),
        Download(
            "uv-x86_64-apple-darwin.tar.gz",
            "f1b919f740bd6be1d014ff58c4271b0779a32198adfb19ad9c5d1c4d9b2b4301",
        ),
        "python/bin/python3",
        "uv",
    ),
    "linux-x64": Platform(
        _python(
            "x86_64-unknown-linux-gnu",
            "ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20",
        ),
        Download(
            "uv-x86_64-unknown-linux-gnu.tar.gz",
            "aa9fca823c03289fb6e3460b3dc864f3ea895cafaf9b99247701a67b17d1b018",
        ),
        "python/bin/python3",
        "uv",
    ),
}

THIRD_PARTY = f"""Third-party software in this package
=====================================

CPython {PYTHON_VERSION}, in python/
    Python Software Foundation License (python/LICENSE.txt, or python/lib/python3.12/LICENSE.txt),
    with the licenses of the libraries it includes alongside it.
    Built by python-build-standalone {PYTHON_RELEASE}
    (https://github.com/astral-sh/python-build-standalone, whose build scripts are MPL-2.0).

uv {UV_VERSION}, in uv/
    Licensed under the Apache License 2.0 or the MIT License, at your option.
    https://github.com/astral-sh/uv

Installed on first run, not part of this package: PyQt6 and Qt, as runtime/uv.lock pins them
(GPL-3.0 and LGPL-3.0; https://www.riverbankcomputing.com/software/pyqt/).

Krita AI Diffusion, in ai_diffusion/ (GPL-3.0): see NOTICE.
"""


def manifest(platform: Platform, version: str) -> str:
    """The manifest, in the keys PhotoCraft accepts (``docs/process-plugins.md``)."""
    command = ", ".join(f'"{part}"' for part in platform.command)
    return (
        f'id = "{PLUGIN_ID}"\n'
        f'name = "{PLUGIN_NAME}"\n'
        f'version = "{version}"\n'
        f"protocol = {PROTOCOL}\n"
        'license = "GPL-3.0-only"\n'
        'description = "Generate and edit images with diffusion models, through ComfyUI."\n'
        f"command = [{command}]\n"
    )


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=600) as response:
        return response.read()


def _download(url: str, expected: str, cache: Path, get: Callable[[str], bytes]) -> bytes:
    cached = cache / expected
    data = cached.read_bytes() if cached.is_file() else get(url)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"{url}: SHA-256 {actual}, expected {expected}")
    cache.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def _archive_members(data: bytes, name: str):
    """(path, mode, bytes) of each regular file in a .tar.gz or .zip."""
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if not info.is_dir():
                    yield info.filename, (info.external_attr >> 16) or 0o644, archive.read(info)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive.getmembers():
                if member.isfile():
                    file = archive.extractfile(member)
                    assert file is not None
                    yield member.name, member.mode, file.read()


def _add(package: zipfile.ZipFile, path: str, data: bytes, mode: int = 0o644):
    clean = PurePosixPath(path)
    if clean.is_absolute() or ".." in clean.parts:
        raise SystemExit(f"refusing to package {path}")
    info = zipfile.ZipInfo(str(clean), date_time=(2020, 1, 1, 0, 0, 0))
    info.external_attr = (0o100000 | (mode & 0o777)) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    package.writestr(info, data)


def build(
    name: str,
    version: str,
    out: Path,
    cache: Path,
    get: Callable[[str], bytes] = fetch,
    root: Path = ROOT,
) -> Path:
    """Build one platform's package into ``out`` and return its path."""
    platform = PLATFORMS[name]
    hits = contents.check(contents.package_files(root), root)
    if hits:
        raise SystemExit("the package mentions the online service:\n" + "\n".join(hits))
    python = _download(
        PYTHON_URL.format(release=PYTHON_RELEASE, name=platform.python.name),
        platform.python.sha256,
        cache,
        get,
    )
    uv = _download(
        UV_URL.format(version=UV_VERSION, name=platform.uv.name), platform.uv.sha256, cache, get
    )

    out.mkdir(parents=True, exist_ok=True)
    target = out / f"ai-diffusion-for-photocraft-{version}-{name}.zip"
    with zipfile.ZipFile(target, "w") as package:
        _add(package, "photocraft-plugin.toml", manifest(platform, version).encode())
        for path, mode, data in _archive_members(python, platform.python.name):
            if path.startswith("python/"):
                _add(package, path, data, mode)
        for path, mode, data in _archive_members(uv, platform.uv.name):
            if PurePosixPath(path).name == platform.uv_program:
                _add(package, f"uv/{platform.uv_program}", data, mode | 0o755)
        for file in contents.package_files(root):
            _add(package, file.relative_to(root).as_posix(), file.read_bytes())
        for file in ("pyproject.toml", "uv.lock"):
            _add(package, f"runtime/{file}", (root / "packaging" / "runtime" / file).read_bytes())
        for file in ("LICENSE", "NOTICE"):
            _add(package, file, (root / file).read_bytes())
        _add(package, "THIRD-PARTY.txt", THIRD_PARTY.encode())
    return target


def write_sums(packages: list[Path], out: Path) -> Path:
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in packages]
    sums = out / "SHA256SUMS"
    sums.write_text("".join(lines), encoding="utf-8")
    return sums


def ignore_in_git(folder: Path) -> None:
    """Make ``folder`` (packages or downloads made in the checkout) ignore itself in git, so
    upstream's ``.gitignore`` stays as upstream has it (UPSTREAM-CHANGES.md)."""
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / ".gitignore"
    if not marker.exists():
        marker.write_text("*\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the plug-in's packages.")
    parser.add_argument("--version", default="0.0.0-dev")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache" / "packaging")
    parser.add_argument("--platform", action="append", choices=sorted(PLATFORMS))
    args = parser.parse_args(argv)
    for folder in (args.out, args.cache):
        if folder.resolve().is_relative_to(ROOT):
            # The folder directly under the checkout: .cache rather than .cache/packaging.
            ignore_in_git(ROOT / folder.resolve().relative_to(ROOT).parts[0])
    packages = [
        build(name, args.version, args.out, args.cache)
        for name in args.platform or sorted(PLATFORMS)
    ]
    sums = write_sums(packages, args.out)
    for package in packages:
        print(package)
    print(sums)
    return 0


if __name__ == "__main__":
    sys.exit(main())
