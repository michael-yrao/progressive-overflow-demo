"""Sort every day's schedule rows into priority order — the SOURCE FIX for a rule that
used to be applied by hand at the weekly build (`weekly-build.md`, `scaffolding.md`).

The priority order (rank, then a streak tie-break for a clean 🟢 review):

    0 Start 🎤 mock interview (checked right after Complexity) · 1 Start 🔴 · 2 Start 🟡
    · 3 Start 🆕 · 4 Start 🎯 · 5 Start 🟢 not Easy (streak asc) · 6 Start 🟢 Easy
    (streak asc) · 7 Start 🎓 · 8 Technique = Complexity (checked first, whatever the
    Start glyph) · 9 anything unclassified (stays in file order)

`priority_key()` is the one place that order lives. `sort_day_blocks()` applies it to a
whole schedule file's text (a day block at a time, header and trailing blank separator
row left in place) and is what the pre-commit hook and this script's CLI both call.
`day_order()` gives `remaining.py` one day's problem numbers in that order, so the board
the learner sees matches the file.

Usage:
    python scripts/schedule_priority.py                  # sort the current week's file
    python scripts/schedule_priority.py PATH [PATH ...]  # sort the given file(s)
    python scripts/schedule_priority.py --check PATH     # report only; exit 1 if unsorted
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

# Git runs hooks with a cp1252 console on Windows; see _console.
import _console

_console.force_utf8()

import effort_budget
import session_date

# The rank table above, as return values of priority_key(). Named so the table in the
# module docstring and the code cannot silently drift apart.
RANK_MOCK = 0
RANK_RED = 1
RANK_YELLOW = 2
RANK_NEW = 3
RANK_PROBE = 4
RANK_GREEN_NOT_EASY = 5
RANK_GREEN_EASY = 6
RANK_GRADUATED = 7
RANK_COMPLEXITY = 8
RANK_UNCLASSIFIED = 9

# Start glyphs with a fixed rank and no streak tie-break.
_FIXED_RANK_BY_START = {
    "🔴": RANK_RED,
    "🟡": RANK_YELLOW,
    "🎓": RANK_GRADUATED,
}


def priority_key(item: dict, difficulty: str | None) -> tuple[int, int]:
    """The priority-sort key for one schedule row: (rank, streak).

    `item` is a `effort_budget.parse_sched_line()` dict. A Complexity re-ask (a cold
    time/space re-ask on code that already exists) ranks 8 regardless of its Start glyph
    — checked before any glyph-based rank, because the Start glyph on a re-ask describes
    the PROBLEM's comfort, not this row's kind. The 🎤 mock interview is checked right
    after it and ranks first (0): the day's one cold, timed block goes at the top. Only a
    clean 🟢 review (ranks 5-6) uses
    the streak tie-break; every other rank ties on 0 and keeps file order, because the
    sort this key feeds is stable.
    """
    if item.get("is_complexity"):
        return (RANK_COMPLEXITY, 0)
    if item.get("is_mock"):
        return (RANK_MOCK, 0)
    start = item.get("start")
    if start in _FIXED_RANK_BY_START:
        return (_FIXED_RANK_BY_START[start], 0)
    if item.get("is_new"):
        return (RANK_NEW, 0)
    if item.get("is_probe"):
        return (RANK_PROBE, 0)
    if start == "🟢":
        streak = item.get("start_streak") or 0
        rank = RANK_GREEN_EASY if difficulty == "Easy" else RANK_GREEN_NOT_EASY
        return (rank, streak)
    return (RANK_UNCLASSIFIED, 0)


def _difficulty_map() -> dict[str, str]:
    """num -> difficulty (Easy/Medium/Hard) from the tracker. A 🟢 row with no match here
    counts as not Easy (priority_key() falls through to RANK_GREEN_NOT_EASY)."""
    return {row["num"]: row["diff"] for row in effort_budget.parse_rows()}


def _iter_day_blocks(lines: list[str]):
    """Yield (header_index, row_start, row_end) for each day block in `lines`, using the
    same block boundary parse_schedule_day() uses: a block ends at the next day header,
    or at the first line that is not a table row (⚠️ the guard the LAST day of the week
    needs, so a later non-daily table is never absorbed — see parse_schedule_day())."""
    i = 0
    n = len(lines)
    while i < n:
        if not effort_budget.DAY_HEADER.search(lines[i]):
            i += 1
            continue
        header_index = i
        i += 1
        row_start = i
        while i < n and not effort_budget.DAY_HEADER.search(lines[i]) and lines[i].lstrip().startswith("|"):
            i += 1
        yield header_index, row_start, i


def _sorted_block_rows(row_lines: list[str], difficulty_of: dict[str, str]) -> list[str]:
    """`row_lines` (one day block's rows, header excluded) reordered by priority_key().
    A line that is not a problem row (the blank separator row, chiefly) is not sortable —
    it keeps its place at the end, after every sorted problem row."""
    keyed: list[tuple[tuple[int, int], str]] = []
    unsortable: list[str] = []
    for line in row_lines:
        item = effort_budget.parse_sched_line(line.rstrip("\r\n"))
        if item is None:
            unsortable.append(line)
        else:
            keyed.append((priority_key(item, difficulty_of.get(item["num"])), line))
    keyed.sort(key=lambda pair: pair[0])
    return [line for _, line in keyed] + unsortable


def sort_day_blocks(text: str, difficulty_of: dict[str, str]) -> str:
    """Reorder every day block's problem rows into priority order. A pure text transform:
    each day header stays first, the blank separator row stays last, and every line
    outside the `## Daily Schedule` table's day blocks is left byte-identical. Idempotent
    — sorting an already-sorted block is a no-op, because the sort is stable."""
    lines = text.splitlines(keepends=True)
    out = list(lines)
    for _, row_start, row_end in _iter_day_blocks(lines):
        out[row_start:row_end] = _sorted_block_rows(lines[row_start:row_end], difficulty_of)
    return "".join(out)


def _day_label(header_line: str) -> str:
    """'Mon Sep 28' from a day-header line, for --check's report."""
    header = effort_budget.DAY_HEADER.search(header_line)
    return f"{header['wd']} {header['mon']} {header['day']}"


def _out_of_order_days(text: str, difficulty_of: dict[str, str]) -> list[str]:
    """Day labels whose block is not already in priority order."""
    lines = text.splitlines(keepends=True)
    labels = []
    for header_index, row_start, row_end in _iter_day_blocks(lines):
        sorted_rows = _sorted_block_rows(lines[row_start:row_end], difficulty_of)
        if sorted_rows != lines[row_start:row_end]:
            labels.append(_day_label(lines[header_index]))
    return labels


def day_order(path: Path, day: dt.date) -> list[str]:
    """The day's problem numbers in priority order, for remaining.py. Draws on
    parse_schedule_day() for the day's rows (struck rows included, since remaining.py
    filters to the un-struck numbers itself and only looks up each one's rank here)."""
    items, _ = effort_budget.parse_schedule_day(path, day)
    difficulty_of = _difficulty_map()
    ordered = sorted(items, key=lambda item: priority_key(item, difficulty_of.get(item["num"])))
    return [item["num"] for item in ordered if item["num"] is not None]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sort each schedule day's rows into priority order.")
    ap.add_argument("paths", nargs="*", type=Path,
                     help="schedule file(s) to sort (default: the current week's file)")
    ap.add_argument("--check", action="store_true",
                     help="report out-of-order days; rewrite nothing; exit 1 if any are out of order")
    args = ap.parse_args()

    paths = args.paths
    if not paths:
        today = dt.date.fromisoformat(session_date.resolve())
        found = effort_budget.find_schedule(today)
        if found is None:
            print("No current-week schedule file found.", file=sys.stderr)
            sys.exit(1)
        paths = [found]

    difficulty_of = _difficulty_map()

    if args.check:
        exit_code = 0
        for path in paths:
            original = path.read_text(encoding="utf-8")
            for label in _out_of_order_days(original, difficulty_of):
                print(f"{path}: {label} is out of priority order")
                exit_code = 1
        sys.exit(exit_code)

    for path in paths:
        original = path.read_text(encoding="utf-8")
        sorted_text = sort_day_blocks(original, difficulty_of)
        if sorted_text != original:
            path.write_text(sorted_text, encoding="utf-8")
            print(f"Sorted {path}")


if __name__ == "__main__":
    main()
