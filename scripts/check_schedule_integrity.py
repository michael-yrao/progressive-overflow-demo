#!/usr/bin/env python3
"""The two propagation misses that are actually possible: a rated rep whose schedule row was
never completed, and a rated rep whose row was never struck.

CLAUDE.md's **Schedule Integrity Rule** ends with *"the spaced repetition dates are the source of
truth; the weekly schedules must reflect them."* This checks that the CURRENT week's schedule file
reflects what the tracker says happened — nothing more.

## ⚠️ What this deliberately does NOT check, and why

The first version of this script enforced the rule's broadest reading — *every* computed next-review
date must appear in some schedule file — and reported **73 of 115 rows on a healthy repo**. That is
not a finding, it is a broken instrument: the rule cannot mean that, because a 🟢 s2 landing in
February 2027 has no week file, no preview, and no business having one. **Distant dates are handled by
the weekly build's own tracker sweep** (*"FIRST do a full tracker sweep for ALL problems with
next_review_date ≤ end of that week"*), which is a pull, not a push. Pre-placing them would be
duplicate bookkeeping that rots.

So this script checks only the window where a *push* is genuinely owed: the week being worked.

A ninth check (**9**, moves `--check`): a row whose problem has a practice spec
(`dsa/tests/<n>_*.yml`) and whose judge link is not the site must carry
`· [PO](https://progressiveoverflow.com/practice/<n>)` — compose the cell with
`links.py --schedule`.

## The nine checks (five move `--check`, four are report-only)

| | Miss | Why it is invisible without this |
|---|---|---|
| **1** | A **struck-through** row with an empty `End` or `Next` cell | the row reads as done, the tracker is correct, and only the schedule is short a fact — nothing downstream notices |
| **2** | A tracker row **attempted during this week** whose number is **not struck** in the file | the rep happened and the board still advertises it as pending; the next kickoff re-offers a problem that was already done |
| **3** | A tracker row **due on or before this week's Sunday** seated on **no day** of the built board | the weekly build's own sweep silently dropped an overdue rep; a leak once crossed a week boundary and slipped two builds |
| **4** | A day-header label or the week's **Goal** paragraph **names** a problem that appears on **no row** anywhere in the week's Daily Schedule | build prose promised a rep no row carried |

Check 3 also reads the `## ⏭️ Carried to next week (row cap)` section: a due row named there counts
as seated only when it is proven (`effort_budget.is_unproven`); an unproven one is flagged.
Four more checks are **report-only** (printed after the findings, never moving `--check`):
**5** a day block over `max_rows_per_day`; **6** the week's 🆕 row count differs from
`intake_per_week` (zero when the unproven-overdue backstop is triggered); **7** a numbered row
that was on a started day (on or before today) at HEAD is gone from the working file — it
must stay there as a `→` row; **8** a day header's `· planned N units` figure was removed or
lowered since HEAD, or a started day's units dropped with no planned figure pinning the original.
Checks 7 and 8 compare against `git show HEAD:<file>` and skip a file new in the commit.

**An em-dash, `unrated`, or `✅` in a cell is intentional, not missing.** Teaches, primers and probes
are unrated by design and legitimately carry no comfort and no date, so only a genuinely **empty**
cell is reported. A checker that flags deliberate blanks gets ignored within a week.

**Check 4's known false-positive shapes, recorded rather than chased.** `PROSE_NUMBER` is tuned
against real weeks, not proven correct — it can still misread `12 🟡 conversions` (a REP COUNT, not
a problem, followed by a comfort glyph) or `by December 2026, the` (four digits immediately before a
comma) as a genuine mention. Check 4 is report-only, so a rare false positive there costs a manual
glance, not a silent miss. **The obvious-looking fix — intersect a candidate with the tracker's known
LC numbers — does NOT work and should not be attempted:** a 🆕 intake is untracked BY DEFINITION (its
whole point is that it has no tracker row yet), so that filter would drop every genuine new-intake
mention while still admitting a tracked date/count number that happens to match a real problem's LC
number.

Usage:
    python scripts/check_schedule_integrity.py            # report
    python scripts/check_schedule_integrity.py --check    # exit 1 on any finding
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Callable

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()

import effort_budget
import links
import session_date
from links import SITE_LABEL, SITE_PRACTICE_URL_TEMPLATE


TRACKERS = [
    Path("docs/foundations/dsa/mastery/dsa_progress.md"),
    Path("docs/foundations/system_design/mastery/design_progress.md"),
]

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A link's text or a bold mention — NOT a bare \b\d+\b, which collides with dates
# ("Aug 14" vs problem 14) and unit counts. Both forms are the schedule files' own conventions.
MENTION = re.compile(r"(?:\[|\*\*)\s*(\d{1,4})\b")
# A cell that is deliberately blank: an em-dash, a tick, "unrated", "n/a".
INTENTIONAL = re.compile(r"^(—|-|–|✅.*|unrated.*|n/?a)$", re.I)

# ── Check 4: a build PROMISE (a day-header label, or the week's Goal paragraph) named a
# problem no row of the week ever carried. False positives are the whole difficulty here: a
# schedule's own prose packs dates, unit counts, rep counts, intake counts and interval
# suffixes right next to genuine mentions like "39 Combination Sum" — see
# test_check_schedule_integrity.py for the real week this is tuned against.

# A day header's LABEL only — the free text after "units —", up to the next "|". Mirrors
# gamify.py's DAY_LABEL precedent (that script strips the same slice for its own display
# purpose); kept local because the two scripts scan it for unrelated reasons.
DAY_LABEL = re.compile(r"units\s*—\s*(?P<label>[^|]+)")
# The week's Goal paragraph: from "**Goal:**" to the first blank line — the paragraph
# itself never contains one (every current schedule file wraps it as one run of lines).
GOAL_PARAGRAPH = re.compile(r"\*\*Goal:\*\*(?P<body>.*?)\n\s*\n", re.DOTALL)

_MONTH_ABBR = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
PROSE_NUMBER_MIN_DIGITS = 2
PROSE_NUMBER_MAX_DIGITS = 4
# Comfort glyphs AND build-tag glyphs both end a genuine mention ("22 🔴", "🆕 1631
# Dijkstra" reads its glyph before the number, "1489 🟡" reads it after — either shape
# needs to close a match here).
PROSE_FOLLOW_GLYPHS = "🔴🟡🟢🎓🆕🎯🎤⚙️🔥⚠️"
# A number is a genuine MENTION — not a date, a decimal, a rep count, or a "+2"/"×2"
# interval suffix — when it is 2-4 digits, not glued to another digit/decimal-point/`+`/`~`
# or a month abbreviation on its LEFT, and followed by either a Capitalized word, one of
# the glyphs above, or a list separator (`·`, `,`, `)`). Under-extraction (missing a real
# mention, e.g. "743×2") is an acceptable failure mode — see the module docstring's
# broken-instrument warning; a false positive is not.
PROSE_NUMBER = re.compile(
    rf"(?<![\d.+~])(?<!{_MONTH_ABBR}\s)"
    rf"(\d{{{PROSE_NUMBER_MIN_DIGITS},{PROSE_NUMBER_MAX_DIGITS}}})"
    rf"(?!\.\d)"
    rf"(?=\s*[{PROSE_FOLLOW_GLYPHS}·,)]|\s+[A-Z])"
)

# A row's build-time tag glyphs (⚠️ protected · 🔥 backfill · 🆕 new · 🎯 probe · 🎤 mock · ⚙️
# variant · 🔤 primer · → moved — the legend on any schedule file's "Tags:" line) AND the
# `~~`/`**` emphasis that can wrap them (a struck or bolded 🆕/🎯 row), stripped from the
# front so a bare-numbered row still yields its number. A single repeated alternation
# handles any interleaving (`~~**🎯 …` really occurs in this repo's archive) — stripping
# glyphs and emphasis in two separate passes would miss that stacked form. Without this, a
# row's number goes invisible and check 4 reads a genuinely SEATED row as unseated — a
# false positive, not the under-extraction this module tolerates elsewhere. Kept local:
# gamify.py solves the identical problem with its own `_LEADING_EMPHASIS`, but importing it
# here would couple two independently-owned scripts over an incidental shared string.
ROW_TAG_PREFIX = re.compile(rf"^(?:~~|\*\*|[⚠️🔥🆕🎯🎤⚙️🔤{effort_budget.MOVE_ARROWS}\s])+")
ROW_BARE_NUMBER = re.compile(r"^(\d{1,4})\b")

# The Daily Schedule section's own heading — week_row_numbers() scans ONLY between here
# and the next "## " section heading (see _daily_schedule_slice). Any 5-pipe-delimited
# table elsewhere in the file — a capacity table before it, a Waiting Room/preview table
# after it — would otherwise be read as a row purely because it happens to share the Daily
# table's column count, which can silently mask a real header-vs-rows drift (a number named
# in the Goal paragraph but seated only in such a table would wrongly count as "seated").
DAILY_SCHEDULE_HEADING = re.compile(r"^##\s+Daily Schedule\b", re.MULTILINE)
NEXT_SECTION_HEADING = re.compile(r"^##\s+\S", re.MULTILINE)


def _prose_numbers(text: str) -> set[int]:
    """Every genuine problem mention in one slice of prose — see PROSE_NUMBER."""
    return {int(n) for n in PROSE_NUMBER.findall(text)}


def week_named_numbers(path: Path, day_header: re.Pattern) -> set[int]:
    """Every LC number this week's build PROSE promises: named in a day-header's label,
    or in the **Goal** paragraph. Both are prose, not rows — the whole point of check 4
    is to catch when they disagree with what actually got seated.

    `day_header` (pass `eb.DAY_HEADER`) gates the DAY_LABEL scan to lines that are actually
    a "▸ **Wkd Mon D**" header — `DAY_LABEL` alone only needs literal "units —" text, which
    a capacity/build note ("9.0 units — ALL placed (355 · 18)") can also contain; ungated,
    such a line's numbers would be misread as a day-header promise.
    """
    text = path.read_text(encoding="utf-8")
    named: set[int] = set()
    for line in text.splitlines():
        if not day_header.search(line):
            continue
        label = DAY_LABEL.search(line)
        if label:
            named |= _prose_numbers(label["label"])
    goal = GOAL_PARAGRAPH.search(text)
    if goal:
        named |= _prose_numbers(goal["body"])
    return named


def _row_number(cell: str) -> int | None:
    """A row's LC number: MENTION (linked or bold) first, else a bare leading number once
    the row's build-time tag glyphs are stripped (see ROW_TAG_PREFIX).
    """
    m = MENTION.search(cell)
    if m:
        return int(m.group(1))
    m = ROW_BARE_NUMBER.match(ROW_TAG_PREFIX.sub("", cell))
    return int(m.group(1)) if m else None


def _daily_schedule_slice(text: str) -> str:
    """The text strictly between "## Daily Schedule" and the NEXT "## " section heading
    (Waiting Room, a preview, build notes, …) — falls back to the whole file if the Daily
    Schedule heading is missing (a malformed schedule file), and to EOF if there is no
    later "## " heading at all. Under-scanning on either fallback is the safer failure: it
    can under-report a finding, never fabricate one, matching this module's own
    false-positive-is-the-real-risk stance.
    """
    heading = DAILY_SCHEDULE_HEADING.search(text)
    if not heading:
        return text
    rest = text[heading.end():]
    following = NEXT_SECTION_HEADING.search(rest)
    end = heading.end() + following.start() if following else len(text)
    return text[heading.start():end]


def week_row_numbers(path: Path, sched_row: re.Pattern) -> set[int]:
    """Every LC number seated as a row ANYWHERE in the week's Daily Schedule — any day,
    not just the day a header names it under, since a directed pair can be declared in
    one place (a Goal paragraph, or one day's header) and seated on a different day's row.

    Scoped to just the Daily Schedule section (see _daily_schedule_slice) — a 5-pipe table
    before OR after it would otherwise be read as a row purely because it happens to share
    the Daily table's column count.
    """
    body = _daily_schedule_slice(path.read_text(encoding="utf-8"))
    numbers: set[int] = set()
    for line in body.splitlines():
        if "▸" in line:
            continue  # a day header, not a problem row
        m = sched_row.match(line)
        if not m:
            continue
        num = _row_number((m["c1"] or "").strip())
        if num is not None:
            numbers.add(num)
    return numbers


def header_vs_rows(path: Path) -> list[str]:
    """Check 4, pure: a number the build PROSE names with no matching row anywhere in the
    week. Takes a Path, returns findings, prints nothing — so a test can point it at a
    synthetic fixture and assert on the returned list directly.
    """
    try:
        import effort_budget as eb  # sibling script; a reuse failure must never break this
    except Exception as exc:  # noqa: BLE001 — mirrors main()'s check-3 tolerance
        print(f"   (header-vs-rows check skipped: {exc.__class__.__name__}: {exc})", file=sys.stderr)
        return []
    missing = week_named_numbers(path, eb.DAY_HEADER) - week_row_numbers(path, eb.SCHED_ROW)
    return [
        f"{num} named in a day header or the Goal paragraph but seated on no row of {path.name}"
        for num in sorted(missing)
    ]


def week_of(path: Path) -> tuple[dt.date, dt.date]:
    monday = dt.datetime.strptime(path.name[:8], "%Y%m%d").date()
    return monday, monday + dt.timedelta(days=6)


def schedule_rows(path: Path) -> list[tuple[str, bool, list[str]]]:
    """(raw problem cell, is_struck, [start, end, next]) for every daily-table row."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        problem = cells[0]
        if "▸" in problem or problem.startswith("---") or not problem:
            continue  # day header, separator, spacer
        is_daily_row = (MENTION.search(problem) or "PROBE" in problem
                        or "PRIMER" in problem or "Mock" in problem)
        if not is_daily_row:
            continue  # a table that is not the daily board (capacity, triggers, landing list)
        rows.append((problem, "~~" in problem, cells[1:4]))
    return rows


def done_row_findings(rows: list[tuple[str, bool, list[str]]]) -> list[str]:
    """Check 1 — a struck (done) row whose End comfort or Next review date is still blank."""
    findings: list[str] = []
    for problem, struck, (start, end, nxt) in rows:
        if not struck:
            continue
        label = re.sub(r"[~*]", "", problem).split("]")[0].lstrip("[")[:60]
        if not end:
            findings.append(f"struck but no End (comfort) — {label}")
        if not nxt and not INTENTIONAL.match(end or ""):
            findings.append(f"struck, rated {end}, but no Next (review date) — {label}")
    return findings


def site_link_findings(rows: list[tuple[str, bool, list[str]]],
                       has_spec: Callable[[int], bool]) -> list[str]:
    """Check 9 — a row whose number has a practice spec, and whose judge link is not already
    the site, must carry `· [PO](<site practice url>)` for that same number. Row links are
    composed by `links.py --schedule`; a row missing the link was hand-authored or predates it.
    """
    findings: list[str] = []
    for problem, _, _ in rows:
        num = _row_number(problem)
        if num is None or not has_spec(num):
            continue
        run_link = f"[{SITE_LABEL}]({SITE_PRACTICE_URL_TEMPLATE.format(number=num)})"
        if run_link not in problem:
            label = re.sub(r"[~*]", "", problem).split("]")[0].lstrip("[")[:60]
            findings.append(f"has a practice page but its row lacks {run_link} — {label}")
    return findings


def tracker_attempts(path: Path) -> list[tuple[str, int, dt.date]]:
    """(row title, problem number, latest attempt date)."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not DATE.match(cells[5]):
            continue
        number = re.match(r"\[(\d+)\.", cells[1])
        if not number:
            continue
        title = re.sub(r"\]\(.*", "", cells[1]).lstrip("[")
        out.append((title, int(number.group(1)), dt.date.fromisoformat(cells[5])))
    return out


# ── Check 3's seating decision. A flat "is this number LISTED anywhere" test (struck or
# not) masks two real shapes: (1) a tracker number with MORE than one row (two solve
# methods for the same LC problem, e.g. Prim's vs Kruskal on one MST problem) where a struck
# rep for ONE method keeps the number "listed" while the OTHER method's overdue row goes
# unseated; (2) a single tracker row's own struck rep this week keeps its number "listed"
# even though nothing UNSTRUCK seats its NEXT (already-due) rep. is_seated() below is the
# fix: "seated" means an unstruck, method-compatible board row, not a merely-listed number.

ROW_METHOD = re.compile(r"\(([^()]+)\)")
BOARD_ROW_NOISE = re.compile(r"[*~`]")


def row_method(title: str) -> str | None:
    """A tracker row's method: the text of the LAST parenthetical in its title (e.g.
    "Kruskal" out of "... (Kruskal)"), or None when the title carries no parenthetical at
    all — true of most single-technique rows.
    """
    matches = ROW_METHOD.findall(title)
    return matches[-1] if matches else None


def _normalized_board_text(text: str) -> str:
    """A board row's text with markdown emphasis stripped and lowercased, for a
    case-insensitive method-containment check."""
    return BOARD_ROW_NOISE.sub("", text).lower()


def _due_within(row: dict, sunday: dt.date) -> bool:
    return dt.date.fromisoformat(row["due"]) <= sunday


def is_seated(tracker_row: dict, tracker_rows_for_number: list[dict],
              pending_board_rows: list[str], sunday: dt.date) -> bool:
    """Is `tracker_row` (a tracker row due on/before `sunday`) seated by some UNSTRUCK
    board row?

    `tracker_rows_for_number` is every tracker row sharing tracker_row's problem number, at
    ANY due date — its length picks the rule. Exactly one row for the number: any unstruck
    mention seats it. More than one: an unstruck mention seats THIS row only when its text
    names this row's method (row_method); a mention that names NO tracker method for the
    number at all still seats it, but only when the number is otherwise unambiguous — exactly
    one of its tracker rows due within the week.
    """
    if not pending_board_rows:
        return False
    if len(tracker_rows_for_number) <= 1:
        return True

    method = row_method(tracker_row["title"])
    known_methods = {m for r in tracker_rows_for_number if (m := row_method(r["title"]))}
    due_count = sum(1 for r in tracker_rows_for_number if _due_within(r, sunday))

    for board_text in pending_board_rows:
        normalized = _normalized_board_text(board_text)
        if method and method.lower() in normalized:
            return True
        names_a_tracker_method = any(m.lower() in normalized for m in known_methods)
        if not names_a_tracker_method and due_count == 1:
            return True
    return False


def pending_board_mentions(rows: list[tuple[str, bool, list[str]]]) -> dict[int, list[str]]:
    """Every problem number seated by an UNSTRUCK board row, mapped to the raw cell text
    of each unstruck row that mentions it — is_seated's own `pending_board_rows` input, per
    number. A struck row never contributes: it is a masking case's whole point that a
    struck rep for one method (or an already-done rep) must not seat a still-due row.
    Pure over `schedule_rows()`'s own return shape, so a test can build `rows` directly.
    """
    pending: dict[int, list[str]] = {}
    for problem, struck, _ in rows:
        if struck:
            continue
        for n in MENTION.findall(problem):
            pending.setdefault(int(n), []).append(problem)
    return pending


CARRIED_HEADING = re.compile(r"^##\s+\S*\s*Carried to next week\b.*$", re.MULTILINE)
CARRIED_BULLET = re.compile(r"^\s*-\s*\[(\d+)\b", re.MULTILINE)


def carried_numbers(path: Path) -> set[int]:
    """Problem numbers named in the `## ⏭️ Carried to next week (row cap)` section: one
    `- [N Title](path) · …` bullet per row, read up to the next `## ` heading."""
    text = path.read_text(encoding="utf-8")
    heading = CARRIED_HEADING.search(text)
    if not heading:
        return set()
    rest = text[heading.end():]
    following = NEXT_SECTION_HEADING.search(rest)
    section = rest[:following.start()] if following else rest
    return {int(n) for n in CARRIED_BULLET.findall(section)}


def due_row_findings(tracker_rows: list[dict], pending_by_number: dict[int, list[str]],
                     carried: set[int], sunday: dt.date, schedule_name: str,
                     cfg: dict) -> list[str]:
    """Check 3, pure: a tracker row due on/before `sunday` that is neither seated by an
    unstruck board row nor validly carried. A row named in the carried section counts as
    seated only when it is proven (effort_budget.is_unproven is the one definition); an
    unproven one is flagged as un-carriable.
    """
    rows_by_number: dict[int, list[dict]] = {}
    for r in tracker_rows:
        rows_by_number.setdefault(int(r["num"]), []).append(r)
    findings: list[str] = []
    for r in tracker_rows:
        if not _due_within(r, sunday):
            continue
        num = int(r["num"])
        if is_seated(r, rows_by_number[num], pending_by_number.get(num, []), sunday):
            continue
        what = f"{r['num']} {r['title'][:40]} ({r['comfort']})"
        if num not in carried:
            findings.append(f"due {r['due']} but seated on no day of {schedule_name} — {what}")
        elif effort_budget.is_unproven(r["comfort"], r["streak"], cfg):
            findings.append(f"due {r['due']} in the carried section of {schedule_name} "
                            f"but cannot be carried (unproven) — {what}")
    return findings


def week_day_items(path: Path, monday: dt.date) -> dict[dt.date, list[dict]]:
    """Parsed rows of each of the week's seven day blocks, reading the file once."""
    lines = path.read_text(encoding="utf-8").splitlines()
    days = [monday + dt.timedelta(days=offset) for offset in range(7)]
    return {d: effort_budget.parse_day_block(lines, monday, d)[0] for d in days}


def row_cap_findings(day_items: dict[dt.date, list[dict]], cap: int) -> list[str]:
    """Check 5 (report-only): a day block with more rows than `cap`, Complexity rows aside."""
    findings: list[str] = []
    for day, items in day_items.items():
        count = effort_budget.count_rows(items)
        if count > cap:
            findings.append(f"{day:%a %b %d}: {count} rows, cap is {cap} — "
                            f"carry the lowest-priority proven rows forward")
    return findings


def intake_findings(day_items: dict[dt.date, list[dict]], tracker_rows: list[dict],
                    cfg: dict, today: dt.date) -> list[str]:
    """Check 6 (report-only): the week's 🆕 row count differs from `intake_per_week`, or
    from zero when the unproven-overdue backstop is triggered (the same helper the no-flag
    effort_budget output uses). A row deferred off its day is counted on the day it moved
    to, not twice."""
    _, triggered = effort_budget.unproven_overdue(tracker_rows, cfg, today)
    expected = 0 if triggered else cfg["intake_per_week"]
    seated = sum(1 for items in day_items.values()
                 for it in items if it["is_new"] and not it["deferred_to"])
    if seated == expected:
        return []
    return [f"{seated} 🆕 rows this week, expected {expected}"
            + (" (intake backstop triggered)" if triggered else "")]


# ── Checks 7 and 8 compare the working file with the committed one (HEAD): a started day's
# rows and its planned total must survive an edit.

UNITS_TOLERANCE = 0.05  # header totals are one-decimal figures; anything under is rounding
DAYS_PER_WEEK = 7


def head_text(path: Path) -> str | None:
    """`path` as committed at HEAD, or None when git cannot show it (a file new in this
    commit, a path outside the repo, git missing)."""
    import subprocess
    try:
        rel = path.resolve().relative_to(effort_budget.REPO).as_posix()
        done = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=effort_budget.REPO,
                              capture_output=True, encoding="utf-8")
    except (OSError, ValueError):
        return None
    return done.stdout if done.returncode == 0 else None


def _row_key(item: dict) -> tuple[int, str | None]:
    return item["num"], row_method(item["text"])


def _day_row_keys(lines: list[str], monday: dt.date, day: dt.date) -> collections.Counter:
    items = effort_budget.parse_day_block(lines, monday, day)[0]
    return collections.Counter(_row_key(it) for it in items if it["num"] is not None)


def _week_days(monday: dt.date) -> list[dt.date]:
    return [monday + dt.timedelta(days=offset) for offset in range(DAYS_PER_WEEK)]


def dropped_row_findings(head_lines: list[str], work_lines: list[str],
                         monday: dt.date, today: dt.date) -> list[str]:
    """Check 7 (report-only): a numbered row present on a started day (`day <= today`) at HEAD
    that is gone from the working file. A row leaves a started day only as a struck or `→`
    row, which still counts as present."""
    findings: list[str] = []
    for day in _week_days(monday):
        if day > today:
            continue
        gone = _day_row_keys(head_lines, monday, day) - _day_row_keys(work_lines, monday, day)
        for num, method in sorted(gone, key=lambda k: (k[0], k[1] or "")):
            name = f"{num} ({method})" if method else f"{num}"
            findings.append(f"{day:%a %b %d}: {name} was on this started day at HEAD and is "
                            f"gone — keep it there as a → row with its new date in Next")
    return findings


def _day_findings(day: dt.date, started: bool, head: tuple, work: tuple) -> list[str]:
    (hu, hp), (wu, wp) = head, work
    findings: list[str] = []
    if hp is not None and wp is None:
        findings.append(f"{day:%a %b %d}: planned figure removed (was {hp:.1f})")
    elif hp is not None and wp < hp - UNITS_TOLERANCE:
        findings.append(f"{day:%a %b %d}: planned figure lowered {hp:.1f} → {wp:.1f}")
    if started and wp is None and hu is not None and wu is not None \
            and wu < hu - UNITS_TOLERANCE:
        pin = hp if hp is not None else hu
        findings.append(f"{day:%a %b %d}: header dropped {hu:.1f} → {wu:.1f} on a started day "
                        f"with no planned figure — add '· planned {pin:.1f} units' after the units")
    return findings


def planned_figure_findings(head_lines: list[str], work_lines: list[str],
                            monday: dt.date, today: dt.date) -> list[str]:
    """Check 8 (report-only): a day header's `· planned N units` figure was removed or lowered
    since HEAD, or a started day's units dropped with no planned figure to hold its original."""
    findings: list[str] = []
    for day in _week_days(monday):
        head = effort_budget.day_header_figures(head_lines, day)
        work = effort_budget.day_header_figures(work_lines, day)
        findings.extend(_day_findings(day, day <= today, head, work))
    return findings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any finding")
    ap.add_argument("--file", help="check this schedule file instead of the current one")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="override the resolved session date used to pick the current week")
    args = ap.parse_args()

    # session_date.resolve_datetime announces a heuristic guess with a bare print() to
    # stdout, the same stream this script's own findings use — redirected to stderr so an
    # announcement (rare: only past-midnight with a dirty tree or a live commit) never
    # turns a clean, no-findings run into non-silent stdout. See gamify.py main()'s
    # identical redirect for --stdout's own reason to keep stdout clean.
    with contextlib.redirect_stdout(sys.stderr):
        today = session_date.resolve_datetime(args.date).date()

    path = Path(args.file) if args.file else effort_budget.current_schedule(today)
    if path is None or not path.exists():
        print("No schedule file to check.")
        return

    monday, sunday = week_of(path)
    rows = schedule_rows(path)
    findings: list[str] = []

    # 1 — a done row that never got its result written back.
    findings.extend(done_row_findings(rows))

    # 9 — a row with a practice spec but no `· [PO](site url)` link.
    findings.extend(site_link_findings(rows, lambda n: links.site_practice_url(str(n)) is not None))

    # 2 — a rep the tracker says happened this week, still advertised as pending.
    struck_numbers = {
        int(n) for problem, struck, _ in rows if struck for n in MENTION.findall(problem)
    }
    listed_numbers = {int(n) for problem, _, _ in rows for n in MENTION.findall(problem)}
    for tracker in TRACKERS:
        if not tracker.exists():
            continue
        for title, number, attempted in tracker_attempts(tracker):
            if not (monday <= attempted <= sunday):
                continue
            if number in listed_numbers and number not in struck_numbers:
                findings.append(f"attempted {attempted} but its row is not struck — {title[:60]}")

    # 3 — a row DUE within this week but seated on no day of the built board. Checks 1-2
    # cannot see it — they reconcile rows that ARE on the board, and this failure is a row
    # that is on NO board at all. The weekly build's own rule is "sweep ALL problems with
    # next_review_date <= end of the week"; this asserts the result of that sweep. A row
    # done earlier this week has its due date advanced past sunday, so it is not flagged; a
    # deliberate deferral gets a new future date, so it is not flagged either — only a
    # genuinely-dropped due row surfaces. Reuses effort_budget's row parser (the same rows
    # behind `--due`, which this diffs against the board, per the entry).
    #
    # "Seated" is decided by is_seated(), not by the flatter listed_numbers above: a merely-
    # LISTED number (struck or not) can mask an overdue row — see is_seated's own docstring.
    pending_by_number = pending_board_mentions(rows)
    report_only: list[str] = []

    try:
        cfg = effort_budget.load_config()
        tracker_rows = effort_budget.parse_rows()
        findings.extend(due_row_findings(
            tracker_rows, pending_by_number, carried_numbers(path), sunday, path.name, cfg))

        # 5 and 6 — report-only: they never reach `findings`, so they never move --check.
        day_items = week_day_items(path, monday)
        report_only.extend(row_cap_findings(day_items, cfg["max_rows_per_day"]))
        report_only.extend(intake_findings(day_items, tracker_rows, cfg, today))
    except Exception as exc:  # a reuse failure must never break the integrity check
        print(f"   (overdue-seated / row-cap / intake checks skipped: "
              f"{exc.__class__.__name__}: {exc})", file=sys.stderr)

    # 7 and 8 — report-only, against the committed file: a separate try so a git failure
    # skips only these two.
    try:
        head = head_text(path)
        if head is not None:  # None = the file is new in this commit
            head_lines, work_lines = head.splitlines(), path.read_text(encoding="utf-8").splitlines()
            report_only.extend(dropped_row_findings(head_lines, work_lines, monday, today))
            report_only.extend(planned_figure_findings(head_lines, work_lines, monday, today))
    except Exception as exc:  # a reuse failure must never break the integrity check
        print(f"   (HEAD-comparison checks skipped: {exc.__class__.__name__}: {exc})",
              file=sys.stderr)

    # 4 — a build promise (day-header label / the week's Goal paragraph) with no matching
    # row anywhere in the week. See header_vs_rows for the false-positive guardrails.
    findings.extend(header_vs_rows(path))

    if not findings:
        print(f"✅ {path.name}: every done row carries its result, and every rep this week is struck")
    else:
        print(f"⚠️  {path.name}: {len(findings)} schedule-integrity finding(s)\n")
        for f in sorted(set(findings)):
            print(f"   {f}")

    if report_only:
        print(f"\nℹ️  {len(report_only)} report-only note(s) (do not affect --check)\n")
        for note in report_only:
            print(f"   {note}")

    if findings and args.check:
        sys.exit(1)


if __name__ == "__main__":
    main()
