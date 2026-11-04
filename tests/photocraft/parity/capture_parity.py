"""Capture graph-parity fixtures from unmodified upstream Krita AI Diffusion.

Checks the upstream tag out into a temporary git worktree (with its submodules),
runs the parity driver against that worktree, writes the fixtures into
``tests/photocraft/fixtures/graphs``, and removes the worktree. Because the
driver only imports ``ai_diffusion`` from the worktree, the fixtures describe
upstream as released, never this repository's modified copy::

    python tests/photocraft/parity/capture_parity.py            # tag v1.54.0-pre
    python tests/photocraft/parity/capture_parity.py --ref <tag>

Requires the ``upstream`` remote (``Acly/krita-ai-diffusion``) and its tag to
have been fetched.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
FIXTURES = REPO_ROOT / "tests" / "photocraft" / "fixtures" / "graphs"
DEFAULT_REF = "v1.54.0-pre"


def _git(*args: str, cwd: Path = REPO_ROOT) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


def capture(ref: str, output: Path) -> int:
    """Write fixtures for every scenario from upstream ``ref`` into ``output``; return exit code."""
    temp = Path(tempfile.mkdtemp(prefix="parity-upstream-"))
    worktree = temp / "upstream"
    try:
        _git("worktree", "add", "--detach", str(worktree), ref)
        _git("submodule", "update", "--init", "ai_diffusion/websockets", cwd=worktree)
        if output.exists():
            shutil.rmtree(output)
        result = subprocess.run(
            [
                sys.executable,
                str(HERE / "driver.py"),
                "--source",
                str(worktree),
                "--write",
                str(output),
            ],
            cwd=temp,
            check=False,
        )
        return result.returncode
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)], cwd=REPO_ROOT, check=False
        )
        shutil.rmtree(temp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--ref", default=DEFAULT_REF, help=f"upstream tag (default {DEFAULT_REF})")
    parser.add_argument("--output", type=Path, default=FIXTURES, help="fixture folder")
    args = parser.parse_args(argv)
    return capture(args.ref, args.output)


if __name__ == "__main__":
    sys.exit(main())
