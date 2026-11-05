"""The check of UPSTREAM-CHANGES.md (TASK-46, REQ-38.2): on made-up tables, and on this
repository when its history reaches the base commit."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from .upstream_changes import (
    DOCUMENT,
    REPO,
    Entry,
    base_commit,
    changed_upstream_files,
    entries,
    main,
    merge_conflicts,
    problems,
    unlisted,
)

TABLE = """
- **Base:** tag `v1.0`, commit `abc1234`

| File | Status | Reason | Task |
|---|---|---|---|
| `a/one.py` | changed | why | TASK-1 |
| `a/lang/*.json`, `a/lang/template.txt` | changed | why | TASK-2 |
| `a/old.svg` | moved | why | TASK-3 |
| `a/later.py` | pending | why | TASK-4 |
"""


def test_the_table_is_read():
    assert base_commit(TABLE) == "abc1234"
    assert entries(TABLE) == [
        Entry(("a/one.py",), "changed"),
        Entry(("a/lang/*.json", "a/lang/template.txt"), "changed"),
        Entry(("a/old.svg",), "moved"),
        Entry(("a/later.py",), "pending"),
    ]


def test_exactly_the_changed_files_pass():
    changed = {"a/one.py", "a/lang/fr.json", "a/lang/template.txt", "a/old.svg"}
    assert problems(entries(TABLE), changed) == []


def test_each_kind_of_mismatch_is_reported():
    changed = {"a/one.py", "a/lang/fr.json", "a/old.svg", "a/later.py", "b/new.py"}
    assert problems(entries(TABLE), changed) == [
        "a/later.py: changed, but its entry says pending",
        "b/new.py: changed, but not listed",
        "a/lang/template.txt: listed as changed, but unchanged",
    ]


def test_a_document_without_a_base_is_refused():
    with pytest.raises(ValueError, match="no base commit"):
        base_commit("| `a.py` | changed | | |")


def _has_commit(commit: str) -> bool:
    found = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
        cwd=REPO,
        capture_output=True,
    )
    return found.returncode == 0


def test_this_repository():
    """Needs the history back to the base commit (CI's check job fetches all of it)."""
    base = base_commit(DOCUMENT.read_text(encoding="utf-8"))
    if not _has_commit(base):
        pytest.skip(f"the base commit {base} isn't in this clone's history")
    assert changed_upstream_files(base), "this project changes some upstream files"
    assert main([]) == 0


def _git(repo: Path, *args: str) -> str:
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
    return subprocess.run(
        ["git", *identity, *args], check=True, cwd=repo, capture_output=True, text=True
    ).stdout.strip()


def test_a_merge_preview_names_the_conflicts(tmp_path: Path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("one\n")
    (tmp_path / "b.txt").write_text("two\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "upstream")
    (tmp_path / "a.txt").write_text("one, upstream\n")
    (tmp_path / "b.txt").write_text("two, upstream\n")
    _git(tmp_path, "commit", "-q", "-am", "upstream")
    _git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "a.txt").write_text("one, ours\n")
    _git(tmp_path, "commit", "-q", "-am", "ours")

    conflicts = merge_conflicts("upstream", "main", repo=tmp_path)
    assert conflicts == ["a.txt"]
    assert unlisted(entries(TABLE), conflicts) == ["a.txt"]
    assert unlisted([Entry(("*.txt",), "changed")], conflicts) == []
    assert merge_conflicts("main", "main", repo=tmp_path) == []
    with pytest.raises(RuntimeError):
        merge_conflicts("no-such-branch", "main", repo=tmp_path)
