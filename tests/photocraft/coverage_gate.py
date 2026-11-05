"""The coverage thresholds (TASK-45, REQ-39.0.4, 39.1), checked on ``coverage json`` output.

Overall: at least 80% of lines and 70% of branches in this project's code (``.coveragerc``).
The ``krita`` stand-in (which holds the persistence mapping: documents' annotations) and the
Krita AI Diffusion reuse code: at least 90% each. REQ-39.0.4 doesn't say of what; this reads it
as lines, as the overall line figure it raises, with the overall 70% of branches still required.

    python -m coverage json -o coverage.json
    python tests/photocraft/coverage_gate.py coverage.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Gate:
    """A minimum share of lines and of branches for the files whose path starts with one of
    ``prefixes`` (all files when there are none)."""

    name: str
    prefixes: tuple[str, ...]
    lines: float
    branches: float


GATES = (
    Gate("overall", (), 80.0, 70.0),
    Gate("the krita stand-in and persistence mapping", ("photocraft_host/krita/",), 90.0, 70.0),
    Gate("the Krita AI Diffusion reuse", ("photocraft_host/krita_reuse",), 90.0, 70.0),
)


def _percent(covered: int, total: int) -> float:
    return 100.0 * covered / total if total else 100.0


def measure(report: dict, gate: Gate) -> tuple[float, float]:
    """The line and branch percentages of the files ``gate`` covers."""
    lines = covered_lines = branches = covered_branches = 0
    for path, data in report["files"].items():
        path = path.replace("\\", "/")
        if gate.prefixes and not path.startswith(gate.prefixes):
            continue
        summary = data["summary"]
        lines += summary["num_statements"]
        covered_lines += summary["covered_lines"]
        branches += summary.get("num_branches", 0)
        covered_branches += summary.get("covered_branches", 0)
    if lines == 0:
        raise ValueError(f"no files measured for {gate.name}")
    return _percent(covered_lines, lines), _percent(covered_branches, branches)


def check(report: dict) -> list[str]:
    """A line per gate, starting with ``FAIL`` for each one not met."""
    out = []
    for gate in GATES:
        lines, branches = measure(report, gate)
        ok = lines >= gate.lines and branches >= gate.branches
        out.append(
            f"{'ok  ' if ok else 'FAIL'} {gate.name}: {lines:.1f}% of lines (needs {gate.lines:g}),"
            f" {branches:.1f}% of branches (needs {gate.branches:g})"
        )
    return out


if __name__ == "__main__":
    results = check(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    print("\n".join(results))
    sys.exit(1 if any(r.startswith("FAIL") for r in results) else 0)
