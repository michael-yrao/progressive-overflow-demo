#!/usr/bin/env python3
"""Surface reps whose comfort could not be reconstructed from the weekly schedules, so
the learner can fix the SOURCE (a schedule's End glyph) going forward instead of living
with a hollow "(pre-archive rep)" activity dot on the Problems-tab timeline chart.

gamify.py's build_problems() already does the reconstruction (and carries the docstring
promise to never fabricate a comfort) — this script REUSES it rather than re-deriving the
same logic, and adds the one thing build_problems() does not report on its own: WHY a
point came back null.

## Two very different reasons a point is null

| | Cause | Fixable? |
|---|---|---|
| **expected** | the rep date is listed by two or more variant rows of the same number, so the glyph cannot be assigned to one of them. The schedule index is keyed by NUMBER, not variant, so gamify.py deliberately degrades that point to null rather than guess which variant a rep belonged to. | No — correct, permanent behaviour, not a gap. |
| **gap** | the rep date belongs to one row only and has no matching entry in ANY schedule file (live or archive) — usually a week whose file never recorded that day's End glyph. | Yes — go back and fill in that week's schedule End cell. |

Only the second kind is a "gap" this script reports. (The FINAL point of every timeline
always anchors to the tracker's current comfort regardless of cause — see
gamify.build_problems — so a gap can only ever appear on a non-final rep.)

Usage:
    python scripts/check_timeline_gaps.py            # print the report, exit 0
    python scripts/check_timeline_gaps.py --check     # exit 1 if any real gap exists
"""
from __future__ import annotations

import argparse
import sys

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report. See _console.
import _console

_console.force_utf8()

import effort_budget as eb  # noqa: E402
import gamify  # noqa: E402


def classify_gaps(
    rows: list[dict],
    sched: dict[str, dict[int, str]],
    cats: dict[int, str] | None = None,
    urls: dict[int, str] | None = None,
) -> tuple[list[dict], dict]:
    """The pure core: reuses gamify.build_problems() for the actual reconstruction, then
    labels each null point as an EXPECTED degrade (a rep date shared by variant rows of the
    number) or a real GAP (an unshared date with no matching schedule entry).

    Takes the same `rows`/`sched` shapes gamify.build_problems() takes and never touches
    the filesystem itself, so it is directly testable with fixtures (see
    test_check_timeline_gaps.py) — same pattern as test_gamify.py's pure-function tests.

    Returns (gaps, counts). `gaps` is one entry per problem WITH a fixable gap:
    {"lcNumber", "title", "dates": [...]}. `counts` is
    {"totalReps", "reconstructed", "expectedNull", "gaps"}.
    """
    cats = cats or {}
    urls = urls or {}
    problems = gamify.build_problems(rows, sched, cats, urls)
    shared = gamify._shared_rep_dates(rows)

    total_reps = 0
    reconstructed = 0
    expected_null = 0
    gaps: list[dict] = []
    for p in problems:
        num = p["lcNumber"]
        missing_dates: list[str] = []
        for pt in p["timeline"]:
            total_reps += 1
            if pt["comfort"] is not None:
                reconstructed += 1
            elif (num, pt["date"]) in shared:
                expected_null += 1
            else:
                missing_dates.append(pt["date"])
        if missing_dates:
            gaps.append({"lcNumber": num, "title": p["title"], "dates": missing_dates})

    counts = {
        "totalReps": total_reps,
        "reconstructed": reconstructed,
        "expectedNull": expected_null,
        "gaps": sum(len(g["dates"]) for g in gaps),
    }
    return gaps, counts


def _classify_real_repo() -> tuple[list[dict], dict]:
    """Wire classify_gaps() to the actual repo files — the CLI path. Fail-soft: a
    missing/unreadable tracker degrades to an empty rows list rather than raising."""
    try:
        rows = eb.parse_rows()
    except OSError:
        rows = []
    sched = gamify.build_schedule_index()
    cats = gamify.category_map()
    urls = gamify.problem_urls()
    return classify_gaps(rows, sched, cats, urls)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any real gap exists")
    args = ap.parse_args()

    gaps, counts = _classify_real_repo()

    print(
        f"Timeline reconstruction: {counts['totalReps']} rep(s) total — "
        f"{counts['reconstructed']} reconstructed, "
        f"{counts['expectedNull']} expected-null (shared variant date), "
        f"{counts['gaps']} real gap(s)."
    )

    if not gaps:
        print("✅ no fixable gaps — every single-variant rep with a schedule entry "
              "reconstructed its comfort")
        return

    print(f"\n⚠️  {len(gaps)} problem(s) with a fixable gap:\n")
    for g in sorted(gaps, key=lambda g: g["lcNumber"]):
        dates = ", ".join(g["dates"])
        print(f"   {g['lcNumber']}. {g['title']} — missing End glyph for: {dates}")

    if args.check:
        sys.exit(1)


if __name__ == "__main__":
    main()
