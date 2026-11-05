"""Check that ``UPSTREAM-CHANGES.md`` lists exactly the upstream files this project changed
(TASK-46, REQ-38.0.3, 38.2).

An upstream file is one that exists at the base commit the document names (``**Base:** ...
commit `<sha>```). It changed when it differs at ``HEAD`` or is gone. Files this project added are
not upstream files and need no entry. The table's first column names files in backticks,
several separated by commas, with ``*`` wildcards; a row whose status is ``pending`` names a
file not changed yet.

    python tests/photocraft/upstream_changes.py [--base <commit>] [--head HEAD]
        [--preview <upstream ref> [--merge-base <commit>]]

Prints each problem and exits 1 if there is any: a changed file with no entry, an entry for a
file that hasn't changed, or a pending entry whose file has changed. ``--preview`` also lists the
files a merge of an upstream ref would leave in conflict (``git merge-tree``, nothing changes),
and fails if one of them has no entry. ``docs/upstream-merge.md`` uses it.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCUMENT = REPO / "UPSTREAM-CHANGES.md"


@dataclass(frozen=True)
class Entry:
    """One row of the table: the files (patterns) it names and their status."""

    patterns: tuple[str, ...]
    status: str


def base_commit(text: str) -> str:
    """The base commit the document names."""
    match = re.search(r"\*\*Base:\*\*.*?commit `([0-9a-f]{7,40})`", text)
    if not match:
        raise ValueError("UPSTREAM-CHANGES.md names no base commit")
    return match.group(1)


def entries(text: str) -> list[Entry]:
    """The rows of the table of changed files."""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[0].startswith("`"):
            continue
        patterns = tuple(re.findall(r"`([^`]+)`", cells[0]))
        rows.append(Entry(patterns, cells[1].lower()))
    return rows


def changed_upstream_files(base: str, head: str = "HEAD", repo: Path = REPO) -> set[str]:
    """Files that exist at ``base`` and differ at ``head`` or are gone there."""
    out = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", base, head],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    ).stdout
    changed = set()
    for line in out.splitlines():
        status, path = line.split("\t", 1)
        if status != "A":  # added here: this project's file, not upstream's
            changed.add(path)
    return changed


def problems(rows: list[Entry], changed: set[str]) -> list[str]:
    """What doesn't match between the table and the files that changed."""
    found = []

    def matches(entry: Entry, path: str) -> bool:
        return any(fnmatch.fnmatchcase(path, p) for p in entry.patterns)

    listed = [e for e in rows if e.status != "pending"]
    for path in sorted(changed):
        if not any(matches(e, path) for e in listed):
            pending = any(matches(e, path) for e in rows if e.status == "pending")
            found.append(
                f"{path}: changed, but its entry says pending"
                if pending
                else f"{path}: changed, but not listed"
            )
    for entry in listed:
        for pattern in entry.patterns:
            if not any(fnmatch.fnmatchcase(path, pattern) for path in changed):
                found.append(f"{pattern}: listed as {entry.status}, but unchanged")
    return found


def merge_conflicts(
    upstream: str, head: str = "HEAD", merge_base: str | None = None, repo: Path = REPO
) -> list[str]:
    """The files a merge of ``upstream`` into ``head`` would leave in conflict, worked out by
    ``git merge-tree`` without touching the working tree or any branch."""
    command = ["git", "merge-tree", "--write-tree", "--name-only", "--no-messages"]
    if merge_base:
        command += ["--merge-base", merge_base]
    run = subprocess.run(
        [*command, head, upstream], check=False, capture_output=True, text=True, cwd=repo
    )
    # 1 means conflicts, but also an unknown ref: only a merge that was worked out writes a tree.
    if run.returncode not in (0, 1) or not run.stdout.strip():
        raise RuntimeError(run.stderr.strip() or f"git merge-tree failed ({run.returncode})")
    # The tree it wrote, then the conflicted files, one per line.
    return [line for line in run.stdout.splitlines()[1:] if line]


def unlisted(rows: list[Entry], paths: list[str]) -> list[str]:
    """The ``paths`` no entry of the table names."""
    return [
        p for p in paths if not any(fnmatch.fnmatchcase(p, x) for e in rows for x in e.patterns)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check UPSTREAM-CHANGES.md against git.")
    parser.add_argument("--base", help="the base commit (default: the one the document names)")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--preview", metavar="UPSTREAM", help="also list the conflicts merging UPSTREAM would have"
    )
    parser.add_argument("--merge-base", help="for --preview: the merge base to assume")
    args = parser.parse_args(argv)
    text = DOCUMENT.read_text(encoding="utf-8")
    rows = entries(text)
    base = args.base or base_commit(text)
    found = problems(rows, changed_upstream_files(base, args.head))
    for problem in found:
        print(problem)
    if not found:
        print(f"UPSTREAM-CHANGES.md lists exactly the upstream files changed since {base}.")
    if args.preview:
        conflicts = merge_conflicts(args.preview, args.head, args.merge_base)
        print(f"Merging {args.preview}: {len(conflicts)} file(s) in conflict")
        for path in conflicts:
            print(f"  {path}")
        surprises = unlisted(rows, conflicts)
        for path in surprises:
            print(f"{path}: in conflict, but not listed")
        found += surprises
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
