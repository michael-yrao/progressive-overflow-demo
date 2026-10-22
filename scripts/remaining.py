"""Print today's UN-STRUCK board — the problems still open on the current day's schedule.

The SOURCE FIX for a recurring miss: when the learner asks "what's left / what else," the
coach hand-assembles the lineup from memory of what was done and DROPS an item. The open
set is fully determined by the schedule (today's block, minus the rows struck through with
`~~`), so a tool should derive it — never memory.

This reads the current week's schedule, finds the day-block for the session date, collects
the rows that are NOT struck through, and prints each as a clean `[file] · [LC/NC]` pair via
`links.py`'s `link_line` (so the paths are repo-root-relative and spoiler-free — name + links
only, exactly what a presented lineup is allowed to carry).

Per the intervention ladder (feedback_self_evaluation.md): source fix > hook > CLAUDE.md step
> memory. A "what's left" lineup now has a tool, matching `links.py` for the link pair itself.

Usage:
    python scripts/remaining.py                 # today's un-struck board (session date)
    python scripts/remaining.py --date 2026-09-18
    python scripts/remaining.py --schedule docs/foundations/schedules/20260914_schedule.md
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

import _console

_console.force_utf8()

import effort_budget as eb
import schedule_priority
import session_date
from links import link_line, tracker_row_counts, REPO_ROOT


# A day-block header: `| ▸ **Thu Sep 17** · 7.7 units — ...`. We match on the date fragment.
DAY_HEADER = re.compile(r"▸\s*\*\*[^*]*\*\*")
# Tag glyphs a row can carry before its number — the schedule's own "Tags:" legend:
# 🔥 backfill · 🎯 probe · 🎤 mock · ⚙️ variant · 🆕 new · ← → moved · ⚠️ protected · 🔤 primer.
ROW_TAG_GLYPHS = f"🔥🎯🎤⚙️🆕{eb.MOVE_ARROWS}⚠️🔤"
MOCK_LINE = "🎤 DSA mock interview — unseen; named when the mock starts (dsa-mock.md)"
CODE_LABEL = "Code"
COMPLEXITY_LABEL = "Complexity re-asks"
# A problem row's number: `[N ` for a linked row, with ANY non-bracket prefix allowed in
# front of it (the original, permissive shape — a tag glyph, a review marker like `🔁 `,
# a probe label like `🎯 **PROBE #6** — `, ...): `| [560 Subarray Sum ...](...path...) ·
# [LC](...) | ... |`. Or a bare `N ` for a 🆕 intake with no local file yet to link
# (`| 🆕 39 Combination Sum · [LC](...) | ... |`) — with no bracket to anchor on, this
# branch requires at least ONE of the legend glyphs above, so a plain summary/carry-table
# row (`| 5 overdue rows | 9.0 |`, `| 743 Network Delay Time | Aug 4 |`) is never misread
# as a problem row. Exactly one of the two capture groups fills, depending on which shape
# matched.
ROW_NUMBER = re.compile(
    rf"^\|\s*(?:(?:[^\[\]|]*?\s)?\[(\d{{1,4}})\s|(?:[{ROW_TAG_GLYPHS}]\s*)+(\d{{1,4}})\s)"
)
# The trailing `(variant)` inside a linked row's text: `[53 Maximum Subarray (Prefix Sum)]`.
ROW_VARIANT = re.compile(r"\[\d{1,4}\s[^\]]*\(([^()\]]+)\)\]")
# A problem number with at least this many tracker rows has two solve methods to tell apart.
MULTI_ROW_MIN = 2


def day_label(session: str) -> str:
    """`Sep 17` for 2026-09-17 — the fragment that appears in the day-block header."""
    d = datetime.strptime(session, "%Y-%m-%d")
    return f"{d.strftime('%b')} {d.day}"


def day_block_lines(schedule: Path, label: str) -> list[str] | None:
    """The lines of the day-block whose header contains `label`, header excluded.
    None if no block matches the label (a day with no schedule / a wrong date)."""
    lines = schedule.read_text(encoding="utf-8").splitlines()
    in_block = False
    found_block = False
    block: list[str] = []
    for line in lines:
        header = DAY_HEADER.search(line)
        if header:
            # A new day-block starts. We're in ours only if its bold date names our date —
            # not free text later in the header (a note citing another date once matched).
            in_block = re.search(rf"\b{re.escape(label)}\b", header.group(0)) is not None
            if in_block:
                found_block = True
            continue
        if in_block:
            block.append(line)
    return block if found_block else None


def is_open_row(line: str) -> bool:
    """True for a row that is neither struck through (done) nor deferred off its day.

    A row deferred off this day (→, kept here unstruck with its new day's date in the
    Next cell) is not actually open here -- eb.deferred_to is the one place that decides
    this, shared with parse_sched_line()/gamify.py's export."""
    if "~~" in line:  # struck through = done
        return False
    cells = eb.SCHED_ROW.match(line)
    return not (cells and eb.deferred_to(False, cells["c4"]))


def is_complexity_row(line: str) -> bool:
    """True when the row's Technique cell (5th column) is a cold complexity re-ask."""
    cells = eb.SCHED_ROW.match(line)
    return bool(cells) and eb.is_complexity_technique(cells["c5"])


def unstruck_rows(schedule: Path, label: str) -> list[tuple[str, bool]] | None:
    """`(number, is_complexity)` of the un-struck rows in the day-block whose header
    contains `label`, in file order. None if no block matches the label."""
    block = day_block_lines(schedule, label)
    if block is None:
        return None
    rows: list[tuple[str, bool]] = []
    for line in block:
        m = ROW_NUMBER.match(line)
        if m and is_open_row(line):
            rows.append((m.group(1) or m.group(2), is_complexity_row(line)))
    return rows


def unstruck_numbers(schedule: Path, label: str) -> list[str] | None:
    """Problem numbers of the un-struck rows in the day-block whose header contains `label`.
    None if no block matches the label (a day with no schedule / a wrong date)."""
    rows = unstruck_rows(schedule, label)
    return None if rows is None else [number for number, _ in rows]


def split_open_numbers(schedule: Path, label: str) -> tuple[list[str], list[str]] | None:
    """`(coding, complexity)` open numbers of the day-block, each in file order.
    None if no block matches the label."""
    rows = unstruck_rows(schedule, label)
    if rows is None:
        return None
    coding = [number for number, is_complexity in rows if not is_complexity]
    complexity = [number for number, is_complexity in rows if is_complexity]
    return coding, complexity


def open_mock(schedule: Path, label: str) -> bool:
    """True when the day-block whose header contains `label` holds an un-struck,
    un-deferred row whose Start cell carries 🎤 (the monthly DSA mock interview)."""
    for line in day_block_lines(schedule, label) or []:
        cells = eb.SCHED_ROW.match(line)
        if cells and eb.MOCK_GLYPH in cells["c2"] and is_open_row(line):
            return True
    return False


def order_by_priority(numbers: list[str], priority: list[str]) -> list[str]:
    """`numbers` (unstruck_numbers()'s file-order list) reordered by each number's index
    in `priority` (schedule_priority.day_order()'s output for the day) — the board's
    priority order. A number missing from `priority` sorts after every number that IS in
    it, keeping its own relative order among the other missing numbers (a stable sort)."""
    rank = {number: index for index, number in enumerate(priority)}
    return sorted(numbers, key=lambda number: rank.get(number, len(priority)))


def open_row_methods(schedule: Path, label: str) -> dict[str, str]:
    """`{number: variant}` for the open rows of the day-block whose link text ends in a
    `(variant)` parenthetical — `[53 Maximum Subarray (Prefix Sum)](…)` gives
    `{"53": "Prefix Sum"}`. The schedule row is written from the tracker at the build, so
    it is the source of which method is due; the first open row of a number wins."""
    methods: dict[str, str] = {}
    for line in day_block_lines(schedule, label) or []:
        number = ROW_NUMBER.match(line)
        variant = ROW_VARIANT.search(line)
        if number and variant and is_open_row(line):
            methods.setdefault(number.group(1) or number.group(2), variant.group(1).strip())
    return methods


def label_line(line: str, number: str, methods: dict[str, str],
               row_counts: dict[str, int]) -> str:
    """`line` with ` · method: <variant>` appended when `number` has 2+ tracker rows and
    the day's schedule row names the due variant; otherwise `line` unchanged. A problem
    with one tracker row never gets the label (its parenthetical may be part of the real
    title, e.g. 208 Implement Trie (Prefix Tree))."""
    if row_counts.get(number, 0) < MULTI_ROW_MIN or number not in methods:
        return line
    return f"{line} · method: {methods[number]}"


def link_lines(numbers: list[str], priority: list[str],
               methods: dict[str, str] | None = None,
               row_counts: dict[str, int] | None = None) -> list[str]:
    """The printable `link_line`s for `numbers` in priority order; falsy ones dropped.
    A multi-row problem's line carries its due method (`label_line`)."""
    lines = []
    for number in order_by_priority(numbers, priority):
        line = link_line(number)
        if line:
            lines.append(label_line(line, number, methods or {}, row_counts or {}))
    return lines


def print_group(label: str, lines: list[str], is_first: bool) -> bool:
    """Print `label · N` and its lines (blank line before it unless first). Empty group
    prints nothing. Returns whether the next group is still the first printed."""
    if not lines:
        return is_first
    if not is_first:
        print()
    print(f"{label} · {len(lines)}")
    print("\n".join(lines))
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Print today's un-struck board (name + links only).")
    ap.add_argument("--date", help="session date YYYY-MM-DD (default: detected session date)")
    ap.add_argument("--schedule", help="schedule file to read (default: current week)")
    args = ap.parse_args()

    session = args.date or session_date.resolve()
    schedule = (Path(args.schedule) if args.schedule
                else eb.current_schedule(date.fromisoformat(session)))
    if schedule is None or not schedule.exists():
        print("No schedule file found.", file=sys.stderr)
        sys.exit(1)

    label = day_label(session)
    split = split_open_numbers(schedule, label)
    if split is None:
        print(f"No day-block for '{label}' in {schedule.relative_to(REPO_ROOT).as_posix()}.",
              file=sys.stderr)
        sys.exit(1)
    has_mock = open_mock(schedule, label)
    if has_mock:
        print(MOCK_LINE)
    coding, complexity = split
    if not coding and not complexity and not has_mock:
        print(f"Nothing left — every row in the {label} block is struck through. ✅")
        return

    session_day = datetime.strptime(session, "%Y-%m-%d").date()
    priority = schedule_priority.day_order(schedule, session_day)
    methods = open_row_methods(schedule, label)
    row_counts = tracker_row_counts()
    is_first = True
    for group_label, numbers in ((CODE_LABEL, coding), (COMPLEXITY_LABEL, complexity)):
        is_first = print_group(
            group_label, link_lines(numbers, priority, methods, row_counts), is_first)


if __name__ == "__main__":
    main()
