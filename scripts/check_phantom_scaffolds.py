#!/usr/bin/env python3
"""Two scaffold-lifecycle leaks that leave a tracked artifact with no valid home.

1. PHANTOM ROW — a scaffolded-but-never-attempted file that discovery turned into a tracker
   row (`update_review_dates.py::discover_source_problems` plants `Unknown` difficulty, 🔴,
   streak 0, blank dates for any source file with no row). The rep never happened, yet the row
   bills a near-term review forever. Deleting the .py does NOT remove the row (self_eval
   2026-08-31, 84); both must go, OR the rep must actually be recorded. The upfront kickoff
   scaffold makes this systematic — every board item left unattempted at close-out is a latent
   phantom (self_eval 2026-09-13 follow-on). The ungameable signal is an EMPTY Rep Dates cell:
   a row with no dated attempt is a row for a rep that never happened.

2. STRANDED PROBE — a file in dsa/probes/ whose number has earned a tracker row. probes/ is
   OUTSIDE solutions.roots (`dsa/leetcode`), so update_review_dates.py cannot maintain its
   review dates and restore_history.py cannot handle its stash: a tracked row whose file the
   tooling cannot see (self_eval 2026-09-16 — 547 stranded five days; 648 predicted, confirmed).
   An earned probe must be `git mv`d to its canonical dsa/leetcode/<category>/ path.

Run at close-out; report-only from the pre-commit hook.
    python scripts/check_phantom_scaffolds.py            # report
    python scripts/check_phantom_scaffolds.py --check     # exit 1 on any finding
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACKER = REPO / "docs" / "foundations" / "dsa" / "mastery" / "dsa_progress.md"
PROBES_DIR = REPO / "dsa" / "probes"
# solutions.roots from cse.config.yml — where a tracked file is allowed to live. Read cheaply;
# a probe under any of these is fine, a probe outside all of them is stranded.
DEFAULT_ROOTS = ["dsa/leetcode"]

ROW_NUM = re.compile(r"\[(\d{1,4})\.")


def solution_roots() -> list[str]:
    try:
        text = (REPO / "cse.config.yml").read_text(encoding="utf-8")
        m = re.search(r"roots:\s*\[([^\]]*)\]", text)
        if m:
            return [r.strip().strip('"\'') for r in m.group(1).split(",") if r.strip()]
    except OSError:
        pass
    return DEFAULT_ROOTS


def tracker_rows() -> list[tuple[str, str, str]]:
    """(difficulty, number, rep_dates_cell) for every 7-column tracker row."""
    out = []
    for line in TRACKER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        if cells[0] in ("Difficulty", "---") or cells[0].startswith("---"):
            continue
        num = ROW_NUM.search(cells[1])
        if not num:
            continue
        out.append((cells[0], num.group(1), cells[6]))
    return out


def tracker_numbers() -> set[str]:
    return {n for _, n, _ in tracker_rows()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any finding")
    args = ap.parse_args()

    findings: list[str] = []

    # 1 — phantom rows: a tracker row with no dated attempt ever (empty Rep Dates), or the
    #     `Unknown` difficulty discovery stamps on a file it had to invent a row for.
    for diff, num, reps in tracker_rows():
        if diff.lower() == "unknown" or not reps:
            findings.append(
                f"PHANTOM ROW — {num} (difficulty {diff!r}, Rep Dates empty): a row for a rep "
                f"that never happened. Record the rep, or delete the file AND this row.")

    # 2 — stranded probes: a probes/ file whose number has a tracker row.
    roots = solution_roots()
    tracked = tracker_numbers()
    if PROBES_DIR.exists():
        for f in sorted(PROBES_DIR.glob("*.py")):
            m = re.match(r"(\d{1,4})_", f.name)
            if not m:
                continue
            num = m.group(1)
            if num in tracked and not any(f"{r}/" in f.as_posix() for r in roots):
                findings.append(
                    f"STRANDED PROBE — {num} ({f.name}) earned a tracker row but sits in "
                    f"dsa/probes/, outside solutions.roots {roots}. `git mv` it to its "
                    f"canonical dsa/leetcode/<category>/ path so the tooling can maintain it.")

    if not findings:
        print("✅ no phantom rows, no stranded probes")
        return 0
    print(f"⚠️  {len(findings)} scaffold-lifecycle finding(s)\n")
    for f in findings:
        print(f"   {f}")
    if args.check:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
