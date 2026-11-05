"""What goes into the plug-in package, and the check that nothing forbidden does (REQ-32.0.4).

The package holds ``ai_diffusion`` (upstream's plug-in, without its debugger checkout and with
only the source of its vendored ``websockets``) and ``photocraft_host``. The optional cloud
module ``ai_diffusion_cloud`` is never part of it. ``check`` fails when a file's name or
content mentions the online service, so its endpoints, branding and sign-in can't ship by
accident.

    python packaging/contents.py      # exits 1 and lists the hits, if any
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("ai_diffusion", "photocraft_host")
#: Folders left out wherever they appear.
SKIPPED = {"__pycache__", ".pytest_cache"}
#: Folders left out of the package, relative to the repository.
EXCLUDED = {"ai_diffusion/debugpy"}
#: Vendored libraries of which only the source is shipped (not their tests, docs, examples).
SOURCE_ONLY = {"ai_diffusion/websockets": "src"}
FORBIDDEN = ("interstice",)


def package_files(root: Path = ROOT) -> list[Path]:
    """Every file the package holds, as paths in ``root``."""
    files: list[Path] = []
    for package in PACKAGES:
        for path in sorted((root / package).rglob("*")):
            relative = path.relative_to(root).as_posix()
            if not path.is_file() or SKIPPED & set(path.parts) or path.suffix == ".pyc":
                continue
            if any(relative == e or relative.startswith(e + "/") for e in EXCLUDED):
                continue
            vendored = next((v for v in SOURCE_ONLY if relative.startswith(v + "/")), None)
            if vendored and not relative.startswith(f"{vendored}/{SOURCE_ONLY[vendored]}/"):
                continue
            files.append(path)
    return files


def check(files: Iterable[Path], root: Path = ROOT) -> list[str]:
    """Each file whose name or content holds a forbidden word, with the word."""
    hits = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes().lower()
        for word in FORBIDDEN:
            if word in relative.lower() or word.encode() in content:
                hits.append(f"{relative}: {word}")
    return hits


if __name__ == "__main__":
    found = check(package_files())
    for hit in found:
        print(hit)
    sys.exit(1 if found else 0)
