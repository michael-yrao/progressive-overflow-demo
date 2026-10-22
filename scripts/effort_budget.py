"""Price a study day in effort units instead of counting problems.

The daily cap used to be an integer: "at most N problems." That cannot tell a
five-minute 🟢 Easy from a 🔴 Hard, so three days in the same week were all "7
problems" while measuring 5.5, 8.0 and 10.5 units of actual work. Every weekly
schedule note reading "Saturday is the heaviest day by some margin" was a human
correcting for that by hand, in prose, one week at a time.

This script is the source fix for that: it prints the number, so the number does
not have to be remembered or re-derived. Per the intervention ladder in
.claude/memory/feedback_self_evaluation.md — a tool that emits the right value
outranks a rule that asks someone to compute it.

    units = base(comfort, streak) × difficulty(tier, demoted?) × attempt_factor
            (weights and the three familiarity layers live in cse.config.yml; the
             flat comfort_units × difficulty was the pre-Sep-3-2026 form)

Usage:
    python scripts/effort_budget.py                     # demand, floor, ceiling, due queue
    python scripts/effort_budget.py --schedule-day      # today, AS BUILT (done vs left)
    python scripts/effort_budget.py --schedule-day 2026-08-18
    python scripts/effort_budget.py --day 19 110 42     # price a HYPOTHETICAL day
    python scripts/effort_budget.py --day 269 560       # (--sd is retired: SD is unpriced)
    python scripts/effort_budget.py --due 2026-08-08    # what is due on a date, priced
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import math
import re
import sys
from pathlib import Path

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()

import session_date

REPO = Path(__file__).resolve().parent.parent
TRACKER = REPO / "docs/foundations/dsa/mastery/dsa_progress.md"
CONFIG = REPO / "cse.config.yml"

# Weights are keyed by the comfort GLYPH, never by the words blank/shaky/clean/graduated
# — see the note in cse.config.yml. Those words collide with update_review_dates.py's
# fallback config scrape and, in this file's first draft, silently rewrote three review
# dates by being read as intervals.
# Streak -> interval for a 🟢. Non-clean comforts have a flat interval.
CLEAN_INTERVAL = {0: 10, 1: 30, 2: 60}
FLAT_INTERVAL = {"🔴": 2, "🟡": 10, "🎓": 180}

ROW = re.compile(
    r"\|\s*(?P<diff>Easy|Medium|Hard)\s*\|\s*"
    r"\[(?P<num>\d+)\.\s*(?P<title>[^\]]+)\]\([^)]*\)\s*\|\s*"
    r"(?P<comfort>🔴|🟡|🟢|🎓)\s*\|\s*(?P<streak>\d+)\s*\|\s*"
    r"(?P<due>\d{4}-\d{2}-\d{2})"
    # The tail is OPTIONAL on purpose: a malformed or legacy row must still price,
    # it just cannot participate in the already-repped-today guard below.
    r"(?:\s*\|\s*(?P<latest>\d{4}-\d{2}-\d{2})\s*\|\s*(?P<reps>[^|]*))?"
)

SCHEDULES = REPO / "docs/foundations/schedules"

# A day header in a weekly schedule: "| ▸ **Tue Aug 18** · 8.0 units |  |  |  |  |"
DAY_HEADER = re.compile(
    r"\|\s*▸\s*\*\*(?P<wd>\w{3})\s+(?P<mon>\w{3})\s+(?P<day>\d{1,2})\*\*"
    # `~` = an approximate price, still a price. A day that moved rows off after it started
    # pins its original total: "· ~3.8 units · planned 6.6 units — label" (units=3.8, planned=6.6).
    r"(?:[^|]*?·\s*~?\s*(?P<units>[\d.]+)\s*units"
    r"(?:\s*·\s*planned\s+~?\s*(?P<planned>[\d.]+)\s*units)?)?"
)
# Any 5-column row of the daily table.
SCHED_ROW = re.compile(r"^\|(?P<c1>[^|]*)\|(?P<c2>[^|]*)\|(?P<c3>[^|]*)\|(?P<c4>[^|]*)\|(?P<c5>.*)\|\s*$")
# The problem number is the first digits following a "[" or a "**" in the first cell.
SCHED_NUM = re.compile(r"(?:\[|\*\*)(\d+)")
GLYPH = re.compile(r"[🔴🟡🟢🎓]")
# A 🆕 Start cell means the row was UNSEEN going into its rep -- GLYPH does not match it,
# so parse_schedule_day() would otherwise return start=None and price_day_items() would
# fall through to the tracker's comfort, which by pricing time is what the row EARNED
# from today's rep, not what it cost to start. A 🆕 row must always bill as Blank.
NEW_GLYPH = "🆕"
# A 🎯 Start cell means the row is a RECOGNITION PROBE on a problem with no tracker row
# yet -- untracked and never repped, so it must bill Blank the same way an untracked 🆕
# row does (see price_day_items()). A 🎯 row that IS already tracked is a cold re-ask on
# something already seen, not a fresh exposure, and keeps the ordinary tracked pricing.
PROBE_GLYPH = "🎯"
# A 🎤 Start cell means the row is the monthly DSA MOCK INTERVIEW: a cold, timed problem
# the learner has never seen. Pre-session the row carries no problem number (the base is
# named only when the mock starts), so it bills Blank at the difficulty named in its
# `(Easy|Medium|Hard)` hint -- see price_day_items(). Post-session the row is numbered
# and still bills Blank (is_mock folds into is_intake there).
MOCK_GLYPH = "🎤"
MOCK_DIFFICULTY = re.compile(r"\((Easy|Medium|Hard)\)")
DEFAULT_MOCK_DIFFICULTY = "Medium"
# A row whose Technique cell is "Complexity" is a cold re-ask of time/space on code that
# already exists, not a rep -- see is_complexity_technique() and price_day_items().
TECHNIQUE_COMPLEXITY = "complexity"

# A bare-number row has no `[`/`**` before its digits at all -- a 🆕 intake or 🎯 probe row
# written `🆕 <n> <title>` rather than `🆕 [<n> <title>](...)`. SCHED_NUM alone cannot
# find such a number (it would go UNPRICED), so sched_row_number() below falls back to the
# leading digits of the row's tag-stripped title. This tag vocabulary mirrors gamify.py's own
# _SCHEDULE_TAGS -- kept as a separate copy here rather than imported, because gamify.py
# imports effort_budget, not the other way around.
# The move arrows: `←` = moved to an EARLIER day, `→` = moved to a LATER day. Defined ONCE here;
# gamify.py, remaining.py and check_schedule_integrity.py import it, so every parser treats
# the two arrows identically (decision `moves-leave-a-row-oct10`).
MOVE_ARROWS = "←→"
_SCHED_ROW_TAGS = f"⚠️🔥🆕🎯🎤⚙️🔤{MOVE_ARROWS}"
_LEADING_SCHED_TAGS = re.compile(rf"^[{re.escape(_SCHED_ROW_TAGS)}\s]+")
_LEADING_SCHED_DIGITS = re.compile(r"^\s*(\d+)\b")


def sched_row_number(cell: str, text: str) -> str | None:
    """The problem number named by one schedule row's Problem cell.

    SCHED_NUM first -- a `[` or `**` immediately before the digits, the shape almost every
    row has. Falls back to the leading digits of `text` (the link-unwrapped,
    `~~`/`**`-stripped title parse_schedule_day() already builds) once its leading tag
    glyph is stripped, for a bare-number row SCHED_NUM cannot see at all.

    Shared with gamify.py's _schedule_item_lc_number(), which delegates here so pricing
    and the dashboard never disagree on which number a row names.
    """
    num = SCHED_NUM.search(cell)
    if num:
        return num.group(1)
    stripped = _LEADING_SCHED_TAGS.sub("", text)
    fallback = _LEADING_SCHED_DIGITS.match(stripped)
    return fallback.group(1) if fallback else None


def is_complexity_technique(technique: str | None) -> bool:
    """Is the Technique cell a complexity re-ask rather than a rep of the problem?

    Shared by price_day_items() (prices it at 0) and gamify.py's _schedule_item_kind()
    (classifies it as KIND_COMPLEXITY) so the two checks cannot drift apart.
    """
    return technique is not None and technique.strip().lower() == TECHNIQUE_COMPLEXITY


def load_config() -> dict:
    """Read the effort_budget block, falling back to the documented defaults.

    Deliberately tolerant: a missing or malformed config must not stop the script
    from pricing a day, because the weights are a judgment call recorded in the
    doc and the defaults here are that same judgment.
    """
    defaults = {
        "comfort_units": {"🔴": 3.0, "🟡": 2.0, "🟢": 1.0, "🎓": 0.5},
        "difficulty": {"Easy": 0.5, "Medium": 1.0, "Hard": 1.5},
        # Familiarity discounting (Sep 3, 2026) — must mirror cse.config.yml, or a machine
        # without PyYAML prices every familiar rep at the old flat rate.
        "green_streak_units": {0: 1.0, 1: 0.8, 2: 0.6},
        "difficulty_demotion": {"trigger": {"comfort": "🟢", "min_streak": 2},
                                "map": {"Hard": "Medium", "Medium": "Easy", "Easy": "Easy"}},
        "attempt_decay": {"applies_to": ["🔴", "🟡"], "min_attempts": 5,
                          "per_attempt": 0.05, "floor": 0.70},
        # Fallback only — used when PyYAML is missing and cse.config.yml cannot be read.
        # It must track the config, or a machine without PyYAML silently prices every day
        # against the wrong ceiling and calls over-full days "ok".
        "ceiling": 8.0,
        "floor_min": 3.0,
        # Scheduling keys — must mirror cse.config.yml (same reason as ceiling).
        "max_rows_per_day": 8,
        "intake_per_week": 2,
        "intake_pause_overdue_unproven": 8,
        "carry_forward_min_streak": 2,
    }
    try:
        import yaml  # noqa: PLC0415
        loaded = (yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {})
        cfg = loaded.get("effort_budget") or {}
    except Exception as exc:  # noqa: BLE001 — no config is a normal state, not an error
        print(f"effort_budget: config unreadable ({exc.__class__.__name__}: {exc}); "
              "using built-in defaults", file=sys.stderr)
        return defaults
    for key, val in defaults.items():
        if key not in cfg:
            cfg[key] = val
        elif isinstance(val, dict):
            cfg[key] = {**val, **(cfg[key] or {})}
    return cfg


def parse_rows() -> list[dict]:
    rows = []
    for line in TRACKER.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            rows.append({**m.groupdict(), "streak": int(m.group("streak"))})
    return rows


def interval(row: dict) -> int:
    if row["comfort"] in FLAT_INTERVAL:
        return FLAT_INTERVAL[row["comfort"]]
    return CLEAN_INTERVAL.get(row["streak"], 60)


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def attempt_count(reps: str | None, before: dt.date | None = None) -> int:
    """How many dated attempts this row carries.

    `before` counts only attempts strictly earlier than that date — the familiarity a
    row had GOING IN to a rep on `before`, which is what the day-as-built pricing wants.
    None counts every attempt (the current familiarity), which is right for demand and
    hypothetical-day pricing.
    """
    dates = _DATE.findall(reps or "")
    if before is not None:
        cut = before.isoformat()
        dates = [d for d in dates if d < cut]
    return len(dates)


def _green_base(streak: int, cfg: dict) -> float:
    """Streak-graded green base (layer A). Falls back gracefully if the block is absent."""
    gsu = cfg.get("green_streak_units") or {}
    if not gsu:
        return cfg["comfort_units"]["🟢"]
    if streak in gsu:
        return gsu[streak]
    return gsu[max(gsu)]          # streak past the top key prices at the top key


def _is_proven(comfort: str, streak: int, cfg: dict, min_streak: int | None = None) -> bool:
    """Has this row earned the difficulty demotion (layer B)? 🎓, or 🟢 at min_streak.

    `min_streak` overrides the demotion trigger's streak -- is_unproven() passes the
    carry-forward threshold so "proven" is decided in this one function.
    """
    if comfort == "🎓":
        return True
    trig = (cfg.get("difficulty_demotion") or {}).get("trigger") or {}
    threshold = min_streak if min_streak is not None else trig.get("min_streak", 2)
    return comfort == trig.get("comfort", "🟢") and streak >= threshold


UNPROVEN_CANDIDATES = ("🔴", "🟡", "🟢")


def is_unproven(comfort: str, streak: int, cfg: dict) -> bool:
    """The ONE definition of unproven: 🔴, 🟡, or a 🟢 below carry_forward_min_streak.

    Unproven rows are never carried past their week and are what the intake backstop
    counts. 🎓 is proven by definition.
    """
    return comfort in UNPROVEN_CANDIDATES and not _is_proven(
        comfort, streak, cfg, min_streak=cfg["carry_forward_min_streak"])


def _attempt_factor(comfort: str, attempts: int, cfg: dict) -> float:
    """Chronic-row decay (layer C). 1.0 unless comfort is in scope AND attempts ≥ min."""
    ad = cfg.get("attempt_decay") or {}
    if comfort not in (ad.get("applies_to") or []):
        return 1.0
    min_attempts = ad.get("min_attempts", 5)
    if attempts < min_attempts:
        return 1.0
    per = ad.get("per_attempt", 0.05)
    floor = ad.get("floor", 0.70)
    return max(floor, 1.0 - per * (attempts - (min_attempts - 1)))


def price(comfort: str, streak: int, diff: str, attempts: int, cfg: dict) -> float:
    """The one pricing function — every path routes through it (added Sep 3, 2026).

        base(comfort, streak) × difficulty(tier, demoted?) × attempt_factor

    (A) greens decay with streak, (B) proven rows price one tier easier, (C) chronic
    🔴/🟡 with ≥ min_attempts get a bounded discount. See cse.config.yml for the why and
    the guardrails (no ordering inversion; conversion pressure preserved on fresh rows).
    """
    base = _green_base(streak, cfg) if comfort == "🟢" else cfg["comfort_units"][comfort]
    if _is_proven(comfort, streak, cfg):
        diff = (cfg.get("difficulty_demotion") or {}).get("map", {}).get(diff, diff)
    return base * cfg["difficulty"][diff] * _attempt_factor(comfort, attempts, cfg)


def units(row: dict, cfg: dict) -> float:
    return price(row["comfort"], row["streak"], row["diff"],
                 attempt_count(row.get("reps")), cfg)


def label(row: dict) -> str:
    streak = f" s{row['streak']}" if row["comfort"] == "🟢" else ""
    return f"{row['comfort']}{streak} {row['diff'][0]}"


def report_demand(rows: list[dict], cfg: dict, today: dt.date) -> None:
    reps = sum(1 / interval(r) for r in rows)
    cost = sum(units(r, cfg) / interval(r) for r in rows)
    floor = max(cfg["floor_min"], math.ceil(cost))
    overdue = [r for r in rows if dt.date.fromisoformat(r["due"]) < today]

    print(f"{len(rows)} rows · demand {reps:.2f} reps/day = "
          f"{cost:.2f} units/day ({cost * 7:.1f}/week)")
    print(f"advisory floor {floor:.0f} u/day (= ceil demand, min {cfg['floor_min']:.0f}) "
          f"· hard ceiling {cfg['ceiling']:.0f} u/day")
    if cost > cfg["ceiling"]:
        # Say it plainly: this is arithmetic, not a discipline problem, and the only
        # fixes are maturation (🟢 s1->s2->🎓) or shrinking the library.
        print(f"⚠ demand ({cost:.1f}) EXCEEDS the ceiling ({cfg['ceiling']:.0f}) — the "
              f"backlog grows no matter how the days are arranged.")
    print(f"overdue: {len(overdue)} rows, "
          f"{sum(units(r, cfg) for r in overdue):.1f} units to clear")
    unproven_count, triggered = unproven_overdue(rows, cfg, today)
    verdict = "TRIGGERED" if triggered else "not triggered"
    print(f"overdue unproven: {unproven_count} ({unproven_label(cfg)}) · intake pauses at "
          f"{cfg['intake_pause_overdue_unproven']} — {verdict}")
    print(f"intake: {cfg['intake_per_week']}/week")


def unproven_overdue(rows: list[dict], cfg: dict, today: dt.date) -> tuple[int, bool]:
    """(count of overdue unproven tracker rows, is the intake backstop triggered).

    Overdue means due strictly before `today`. Triggered at intake_pause_overdue_unproven
    or more; the next weekly build then seats no 🆕.
    """
    count = sum(1 for r in rows
                if dt.date.fromisoformat(r["due"]) < today
                and is_unproven(r["comfort"], r["streak"], cfg))
    return count, count >= cfg["intake_pause_overdue_unproven"]


def unproven_label(cfg: dict) -> str:
    """`🔴/🟡/🟢 s0/🟢 s1` -- the unproven set, spelled from carry_forward_min_streak."""
    greens = "/".join(f"🟢 s{s}" for s in range(cfg["carry_forward_min_streak"]))
    return "/".join(["🔴", "🟡", greens])


def row_cap_lines(row_count: int, cfg: dict) -> list[str]:
    """`rows N / cap M`, plus the carry warning when N is over the cap."""
    cap = cfg["max_rows_per_day"]
    lines = [f"  rows {row_count} / cap {cap}"]
    if row_count > cap:
        lines.append(f"  !! {row_count} ROWS, cap is {cap} — "
                     f"carry the lowest-priority proven rows forward")
    return lines


def price_day(nums: list[str], rows: list[dict], cfg: dict, sd: bool,
              today: dt.date | None = None) -> None:
    by_num: dict[str, list[dict]] = {}
    for r in rows:
        by_num.setdefault(r["num"], []).append(r)

    # --- guard: this flag is a LIVE PRICER, not a ledger -----------------------
    # Comfort in the tracker is the comfort a row EARNED at its last rep. Units are
    # billed on the comfort a row carried GOING IN. Those agree only until a rep is
    # logged -- after that, pricing the same number here understates it, silently and
    # always in the same direction. Compounded with handing this flag the REMAINING
    # items and reading the total as the day's total, that invented 5.0 units of spare
    # capacity on a day already at the ceiling (Aug 18, 2026).
    if today is not None:
        stale = [n for n in nums
                 for r in by_num.get(n, []) if repped_on(r, today)]
        blind = [n for n in nums
                 for r in by_num.get(n, []) if not rep_dates_readable(r)]
        if blind:
            print(f"  !! could not read the Rep Dates column for "
                  f"{', '.join(sorted(set(blind)))} -- those numbers were NOT checked "
                  f"for a rep dated {today}.")
            print("     Treat the total below as unverified and use --schedule-day.")
            print()
        if stale:
            print(f"  !! {', '.join(sorted(set(stale)))} already have a rep dated "
                  f"{today} -- they are priced here at the comfort they EARNED,")
            print("     not the one they were BILLED at, so this total UNDERSTATES the "
                  "day as built.")
            print("     For a day in progress use --schedule-day, which prices from the "
                  "schedule's Start column.")
            print()

    total = 0.0
    for num in nums:
        found = by_num.get(num)
        if not found:
            # An untracked number is a NEW problem: no row, no history. Price it as a
            # Blank Medium, because that is what a first exposure usually costs.
            guess = cfg["comfort_units"]["🔴"] * cfg["difficulty"]["Medium"]
            total += guess
            print(f"  {num:>5}  {guess:4.1f}  (untracked — priced as a new 🔴 Medium)")
            continue
        if len(found) > 1:
            # Multi-variant problem (e.g. 130 BFS and 130 Union-Find). Which variant is
            # scheduled is not recoverable from the number, so price the dearest and say so.
            worst = max(found, key=lambda r: units(r, cfg))
            total += units(worst, cfg)
            variants = ", ".join(f"{label(r)}" for r in found)
            print(f"  {num:>5}  {units(worst, cfg):4.1f}  {label(worst)}  "
                  f"⚠ {len(found)} variants ({variants}) — priced the dearest")
            continue
        row = found[0]
        total += units(row, cfg)
        print(f"  {num:>5}  {units(row, cfg):4.1f}  {label(row)}  {row['title'][:44]}")

    if sd:
        # SD IS NOT PRICED (Aug 16, 2026). The budget used to add an SD slot to the day's
        # total; the model changed and the flag did not. SD moved to a separate repo, is
        # self-directed, and is OFF-BOARD — so the ceiling was lowered 9.0 -> 8.0 to be the
        # honest DSA-only number, and SD takes the leftover evening. Pricing SD into the day
        # AND holding the lowered ceiling would charge for it twice.
        #
        # The flag still parses, and says this, rather than being deleted: silently dropping
        # 3.0 units from a total someone expected it in is how a day gets over-filled without
        # anyone noticing. Accepting it and explaining is the only version that cannot
        # mislead.
        print("  SD     —    not priced: SD is off-board since Aug 16, 2026. The 8.0 "
              "ceiling is\n         DSA-only and already sized so SD fits the leftover "
              "evening. --sd adds nothing.")

    ceiling = cfg["ceiling"]
    verdict = "OVER" if total > ceiling else "ok"
    print(f"\n  TOTAL {total:.1f} / {ceiling:.0f} units — {verdict}"
          + (f" by {total - ceiling:.1f}" if total > ceiling else
             f" ({ceiling - total:.1f} spare)"))
    if total > ceiling:
        print("  Trim the CHEAPEST items last: dropping a 🟢 Easy saves 0.5, dropping a "
              "🟡 saves 2.0. Never trim the active block.")
    print("\n".join(row_cap_lines(len(nums), cfg)))


def repped_on(row: dict, day: dt.date) -> bool:
    """Did this row get a rep on `day`?

    Reads the tracker's own Rep Dates column. Used only by the --day guard: a row
    already repped today has ALREADY been paid for, and its comfort in the tracker
    is now the comfort it EARNED, not the one it was billed at.
    """
    return day.isoformat() in (row["reps"] or "")


def rep_dates_readable(row: dict) -> bool:
    """Could the Rep Dates column be read at all for this row?

    ⚠️ The tail of ROW is optional, so a row whose Latest/Rep Dates cells do not match
    comes back with reps=None -- and `repped_on` would then answer "no rep today" for a
    row it never actually read. A guard that quietly declines to fire is worse than no
    guard, so the caller reports these rather than treating them as clean.
    """
    return row["reps"] is not None


def find_schedule(day: dt.date) -> Path | None:
    """The weekly schedule file whose 7-day span contains `day`.

    Searches the live folder first, then archive/, so an audit still works on a week
    that has already been closed out.
    """
    best: tuple[dt.date, Path] | None = None
    for folder in (SCHEDULES, SCHEDULES / "archive"):
        if not folder.is_dir():
            continue
        for path in folder.glob("*_schedule.md"):
            stamp = path.name.split("_")[0]
            if len(stamp) != 8 or not stamp.isdigit():
                continue
            try:
                start = dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
            except ValueError:
                continue
            if start <= day < start + dt.timedelta(days=7):
                if best is None or start > best[0]:
                    best = (start, path)
    return best[1] if best else None


def current_schedule(day: dt.date) -> Path | None:
    """The schedule file whose 7-day span actually contains `day`.

    Prefers find_schedule(day) (live schedules/, then archive/): after a Sunday close-out
    has already built NEXT week's file, `day` still falls inside THIS week's span, so that
    lookup keeps returning the week actually being worked rather than the newest file on
    disk. Falls back to the newest live file only when no file's span contains `day` (a
    stale or missing schedule tree).
    """
    spanning = find_schedule(day)
    if spanning is not None:
        return spanning
    if not SCHEDULES.exists():
        return None
    files = sorted(SCHEDULES.glob("[0-9]" * 8 + "_schedule.md"))
    return files[-1] if files else None


_FULL_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def deferred_to(done: bool, next_cell: str) -> str | None:
    """The ISO date a schedule row was deferred TO, or None.

    A `→` row stays on its planned day, not struck, with the day it moved to written
    into its Next cell (deferred-rows-stay-on-planned-day-sep29) -- the one clean
    discriminator from every other row shape: a DONE row's Next cell holds its
    ordinary spaced-repetition review date (a real date that is not a deferral), and
    a fresh row's Next cell is blank. `done` is checked FIRST so a struck row's real
    review date can never be misread as one.

    ONE helper decides this, shared by parse_sched_line() below (pricing/priority)
    and gamify.py's _parse_schedule_day_full() (the dashboard export) -- so pricing,
    the export, and remaining.py's skip check can never disagree on which row counts
    as deferred.
    """
    if done:
        return None
    stripped = next_cell.strip()
    return stripped if _FULL_ISO_DATE.fullmatch(stripped) else None


DEFERRAL_MARKERS = tuple(MOVE_ARROWS)


def _is_unreadable_deferral(done: bool, row_text: str, next_cell: str) -> bool:
    """An unstruck `→`/`←` row whose Next cell is filled but is not a full ISO date.

    A Next cell that itself starts with `→` is the older shape (`→ Aug 31 wk`) that
    archived schedules still carry; it is history, not a mistake, so it stays silent."""
    if done or not row_text.startswith(DEFERRAL_MARKERS):
        return False
    stripped = next_cell.strip()
    if not stripped or stripped.startswith(DEFERRAL_MARKERS):
        return False
    return not _FULL_ISO_DATE.fullmatch(stripped)


def parse_sched_line(line: str) -> dict | None:
    """Parse one line of a schedule day's table into an item dict, or None if the line is
    not a problem row (no SCHED_ROW match, a blank separator row, or a markdown rule).

    Extracted from parse_schedule_day()'s per-row loop body so schedule_priority.py can
    read a row (num/start/start_streak/is_new/is_probe/is_mock/is_complexity/done/text) the same
    way pricing does, without re-deriving the parse. See parse_schedule_day() for the item
    shape and the START column's rationale.
    """
    m = SCHED_ROW.match(line)
    if not m:
        return None
    cell = m["c1"]
    if not cell.strip() or set(cell.strip()) <= {"-", ":"}:
        return None            # blank separator row, or a markdown rule
    glyph = GLYPH.search(m["c2"] or "")
    streak_m = re.search(r"s(\d+)", m["c2"] or "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    # Strip markdown emphasis wherever it sits, not just at the ends: the strike
    # wraps the LINK (`~~[<n> ...](...)~~ · [LC](...)`), so trailing-only stripping
    # leaves a stray `~~` in the middle of the printed title.
    text = re.sub(r"~~|\*\*", "", text)
    # text is computed before the number so sched_row_number()'s bare-number fallback
    # can read off this same tag-stripped, link-unwrapped string.
    num = sched_row_number(cell, text)
    start_glyph = glyph.group(0) if glyph else None
    done = "~~" in cell
    next_cell = m["c4"]
    row_text = re.sub(r"\s+", " ", text).strip(" ·*")
    if _is_unreadable_deferral(done, row_text, next_cell):
        print(f"WARNING: schedule row {num}: → row's Next cell '{next_cell.strip()}' is not "
              "YYYY-MM-DD; read as not deferred", file=sys.stderr)
    return {
        "num": num,
        "start": start_glyph,
        # A 🟢 Start cell with no `sN` carries no streak -- None, not 0, so
        # price_day_items() can tell "streak zero" from "streak unknown" and
        # print its own warning instead of silently pricing the highest 🟢 price.
        "start_streak": (int(streak_m.group(1)) if streak_m
                         else None if start_glyph == "🟢" else 0),
        "is_new": NEW_GLYPH in (m["c2"] or ""),
        "is_probe": PROBE_GLYPH in (m["c2"] or ""),
        "is_mock": MOCK_GLYPH in (m["c2"] or ""),
        "is_complexity": is_complexity_technique(m["c5"]),
        "done": done,
        "deferred_to": deferred_to(done, next_cell),
        "text": row_text,
    }


def parse_schedule_day(path: Path, day: dt.date) -> tuple[list[dict], float | None]:
    """Pull one day's block out of a weekly schedule's daily table.

    Returns (items, stated_units). Each item carries the problem number, the START
    comfort glyph as written at build time, whether that Start cell was 🆕 or 🎯
    (is_new/is_probe -- see NEW_GLYPH/PROBE_GLYPH), and whether the row is struck through.

    The START column is the whole point of this function. It is written once, at the
    weekly build, and never mutated -- so it survives a rep being logged, which the
    tracker's Comfort column does not. Pricing a day from the tracker AFTER reps land
    charges the comfort the rows EARNED instead of the one they were BILLED at, and
    therefore always understates the day.
    """
    week_start = dt.date(int(path.name[:4]), int(path.name[4:6]), int(path.name[6:8]))
    return parse_day_block(path.read_text(encoding="utf-8").splitlines(), week_start, day)


def count_rows(items: list[dict]) -> int:
    """Rows a day block carries against max_rows_per_day: every parsed row except the
    Complexity-technique ones and rows moved off the day (`deferred_to` set, not done
    there). Struck rows count (their `deferred_to` is None); separators never reach
    `items`."""
    return sum(1 for it in items if not it.get("is_complexity") and not it.get("deferred_to"))


def parse_day_block(lines: list[str], week_start: dt.date,
                    day: dt.date) -> tuple[list[dict], float | None]:
    """parse_schedule_day()'s body over already-read lines, so a caller walking all seven
    days of a week reads the file once instead of seven times."""
    wanted = None
    for offset in range(7):
        d = week_start + dt.timedelta(days=offset)
        if d == day:
            wanted = (d.strftime("%a"), d.strftime("%b"), d.day)
            break
    if wanted is None:
        return [], None

    items: list[dict] = []
    stated: float | None = None
    inside = False
    for line in lines:
        header = DAY_HEADER.search(line)
        if header:
            hit = (header["wd"], header["mon"], int(header["day"])) == wanted
            if hit:
                inside = True
                stated = float(header["units"]) if header["units"] else None
            elif inside:
                break          # the next day's header ends this day's block
            continue
        if not inside:
            continue
        if not line.lstrip().startswith("|"):
            break              # the daily table ended.
                               # ⚠️ On the LAST day of the week there is no next day
                               # header to break on, so without this the scan runs to
                               # EOF and any later 5-column table is priced into Sunday.
                               # A total that silently absorbs rows is the same class of
                               # error this whole flag exists to prevent.
        item = parse_sched_line(line)
        if item is not None:
            items.append(item)
    return items, stated


def day_header_figures(lines: list[str], day: dt.date) -> tuple[float | None, float | None]:
    """(units, planned) from `day`'s header line: the stated total and the pinned
    `· planned N units` figure, each None when the header omits it (or has no header)."""
    wanted = (day.strftime("%a"), day.strftime("%b"), day.day)
    for line in lines:
        header = DAY_HEADER.search(line)
        if header and (header["wd"], header["mon"], int(header["day"])) == wanted:
            units = float(header["units"]) if header["units"] else None
            planned = float(header["planned"]) if header["planned"] else None
            return units, planned
    return None, None


# Any OTHER table row in the tracker file shaped `| Easy|Medium|Hard | [N. Title](url) |
# ...` -- the Waiting Room and Knowledge Expansion Queue tables, e.g. The tracker's OWN
# review rows (ROW) share this same leading shape, so this also matches those -- harmless,
# because source (a) (parse_rows(), the caller's `rows`) is always tried first and a
# number found there never reaches this fallback.
DIFFICULTY_TABLE_ROW = re.compile(
    r"^\|\s*(?P<diff>Easy|Medium|Hard)\s*\|\s*\[(?P<num>\d+)\.\s*[^\]]*\]\([^)]*\)\s*\|",
    re.MULTILINE)

ROADMAP_YML = REPO / "docs/foundations/dsa/mastery/roadmap.yml"
PROBE_POOL = REPO / "dsa/probes/README.md"
# A queued-probe-candidate row: `| **<n> <title>** (Medium) | Technique | ...`
PROBE_POOL_ROW = re.compile(r"\*\*(?P<num>\d+)\s+[^*]*\*\*\s*\((?P<diff>Easy|Medium|Hard)\)")


def _tracker_table_difficulty() -> dict[str, str]:
    """num -> difficulty from any OTHER table row in the tracker file (DIFFICULTY_TABLE_ROW
    above). First occurrence wins. Source (b) in lookup_untracked_difficulty()'s order."""
    out: dict[str, str] = {}
    for m in DIFFICULTY_TABLE_ROW.finditer(TRACKER.read_text(encoding="utf-8")):
        out.setdefault(m["num"], m["diff"])
    return out


def _roadmap_difficulty() -> dict[str, str]:
    """num -> difficulty from roadmap.yml's `problems:` entries. Source (c). Tolerant like
    load_config(): a missing file or missing PyYAML degrades to {}, never raises -- a
    catalog that cannot be read is a normal state, not a reason to stop pricing a day."""
    try:
        import yaml  # noqa: PLC0415
        config = yaml.safe_load(ROADMAP_YML.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 -- a missing/unparsable roadmap is a normal state
        return {}
    return {str(p["number"]): p["difficulty"] for p in config.get("problems") or []
            if p.get("number") is not None and p.get("difficulty")}


def _probe_pool_difficulty() -> dict[str, str]:
    """num -> difficulty from dsa/probes/README.md's queued-candidate rows. Source (d)."""
    if not PROBE_POOL.is_file():
        return {}
    out: dict[str, str] = {}
    for m in PROBE_POOL_ROW.finditer(PROBE_POOL.read_text(encoding="utf-8")):
        out.setdefault(m["num"], m["diff"])
    return out


def _milestone_difficulty(num: str) -> str | None:
    """The curriculum catalog's difficulty for `num` (curriculum/dsa/milestone.yml), else None.
    Source (e). Tolerant like _roadmap_difficulty(): an unreadable catalog is a normal state."""
    if not num.isdigit():
        return None
    try:
        import curriculum  # noqa: PLC0415 -- imports yaml; stay importable without it
        entry = curriculum.catalog_entry(int(num))
    except Exception:  # noqa: BLE001 -- a missing/unparsable catalog is a normal state
        return None
    return (entry or {}).get("difficulty") or None


def lookup_untracked_difficulty(num: str) -> tuple[str, bool]:
    """Difficulty for a schedule row's problem NUMBER that has no row among the tracker's
    own review rows (parse_rows() -- source (a), checked by the caller before this is ever
    called). Tries, in order: (b) any other tracker-file table row shaped
    `| Easy|Medium|Hard | [N. Title](url) | ...`, (c) roadmap.yml's `problems:` entries,
    (d) dsa/probes/README.md's queued-candidate rows, (e) the curriculum catalog. Returns
    (difficulty, guessed) -- guessed is True only when none of (b)-(e) name the number, in
    which case the difficulty is the honest guess ("Medium"), flagged so the day's total is
    not silently understated.
    """
    for source in (_tracker_table_difficulty(), _roadmap_difficulty(),
                   _probe_pool_difficulty()):
        if num in source:
            return source[num], False
    milestone = _milestone_difficulty(num)
    return (milestone, False) if milestone else ("Medium", True)


def _bill_blank(num: str, cfg: dict) -> tuple[float, str, bool]:
    """Blank (🔴) pricing for an UNTRACKED numbered row: zero prior attempts, difficulty
    from lookup_untracked_difficulty(). Shared by price_day_items()'s two untracked-row
    branches (an intake row and a plain untracked row) so the note wording and the
    guessed-bucket bookkeeping cannot drift apart between them.

    Returns (cost, note, guessed).
    """
    diff, guess = lookup_untracked_difficulty(num)
    cost = price("🔴", 0, diff, 0, cfg)
    if guess:
        return cost, "NEW !! untracked -- guessed as a new Blank Medium", True
    return cost, f"NEW {diff[0]} (untracked; difficulty from the queue/roadmap/probe pool)", False


def price_day_items(day: dt.date, items: list[dict], rows: list[dict], cfg: dict) -> dict:
    """Price one day's parsed schedule items, splitting done from remaining.

    Pure pricing core shared by price_schedule_day() (which prints) and
    build_workload() in gamify.py (which serializes), so the dashboard reuses the exact
    same pricing without reprinting it.
    """
    by_num: dict[str, list[dict]] = {}
    for r in rows:
        by_num.setdefault(r["num"], []).append(r)

    done_total = rest_total = 0.0
    guessed = 0
    streakless = 0
    done_lines: list[str] = []
    rest_lines: list[str] = []
    moved_lines: list[str] = []
    unpriced: list[str] = []

    for it in items:
        if it.get("is_complexity"):
            # A complexity re-ask costs 0 units -- it is a cold re-ask on code that
            # already exists, not a rep of the problem. This runs BEFORE the
            # missing-number check below: a close-out row such as "N cold complexity
            # probes ..." carries no problem number at all and must still price 0
            # rather than land in `unpriced`.
            cost = 0.0
            note = "🎯 complexity re-ask -- unpriced by design"
        elif it.get("is_mock") and not it["num"]:
            # The pre-session mock row (`🎤 Mock interview (Medium)`) names no problem yet.
            # Unseen, so it bills Blank at the hinted difficulty; no hint means a guess
            # (Medium), counted so the day's total reads as a floor. Runs BEFORE the
            # missing-number check below or the row would land in `unpriced`.
            hint = MOCK_DIFFICULTY.search(it["text"])
            diff = hint.group(1) if hint else DEFAULT_MOCK_DIFFICULTY
            if not hint:
                guessed += 1
            cost = price("🔴", 0, diff, 0, cfg)
            note = f"🎤 MOCK {diff} (unseen -- billed Blank)"
        elif not it["num"]:
            unpriced.append(it["text"][:62])
            continue
        else:
            tracked = by_num.get(it["num"])
            # 🆕 OR 🎯 in the Start cell means unseen going in: a first exposure (🆕) or a
            # recognition probe with nothing tracked yet (🎯) -- see NEW_GLYPH/PROBE_GLYPH.
            is_intake = it.get("is_new") or it.get("is_probe") or it.get("is_mock")
            if it["start"] and tracked:
                # START comfort + streak (build time) x difficulty (a stable property).
                # Attempt count is the familiarity GOING IN: attempts strictly before this
                # day, joined from the tracker's Rep Dates — so day-as-built pricing bills
                # the row's state at build, not what later reps added.
                diff = tracked[0]["diff"]
                attempts = attempt_count(tracked[0].get("reps"), before=day)
                if it["start"] == "🟢" and it["start_streak"] is None:
                    # A bare 🟢 Start cell (see parse_schedule_day()) has no recorded
                    # streak. Streak 0 is the most expensive 🟢 price, so pricing it there
                    # can only OVERSTATE the row. Price at s0 (an upper bound) but say so,
                    # rather than let it read the same as a genuine streak-0 row.
                    streakless += 1
                    cost = price("🟢", 0, diff, attempts, cfg)
                    note = (f"🟢 s? {diff[0]} !! no streak in the Start cell -- "
                            f"priced as s0 (the highest 🟢 price)")
                else:
                    cost = price(it["start"], it["start_streak"], diff, attempts, cfg)
                    streak_tag = f" s{it['start_streak']}" if it["start"] == "🟢" else ""
                    note = f"{it['start']}{streak_tag} {diff[0]}"
            elif is_intake and tracked:
                # Bill Blank (🔴) regardless of what the tracker shows now -- see
                # NEW_GLYPH/PROBE_GLYPH. Only the difficulty is worth reading from the
                # tracker when a row exists; there is no start comfort to read.
                diff = tracked[0]["diff"]
                cost = price("🔴", 0, diff, 0, cfg)
                note = f"NEW {diff[0]}"
            elif is_intake:
                # Untracked 🆕/🎯 row: same Blank billing, but the difficulty has to come
                # from somewhere other than a tracker row that doesn't exist yet.
                cost, note, guess = _bill_blank(it["num"], cfg)
                if guess:
                    guessed += 1
            elif tracked:
                worst = max(tracked, key=lambda r: units(r, cfg))
                cost = units(worst, cfg)
                note = f"{label(worst)} !! no Start glyph -- priced from the tracker"
            else:
                cost, note, guess = _bill_blank(it["num"], cfg)
                if guess:
                    guessed += 1
        num_label = it["num"] or "—"
        line = f"  {num_label:>5}  {cost:4.1f}  {note}  {it['text'][:44]}"
        if it.get("deferred_to"):
            # A row deferred off a started day stays visible but bills in neither built
            # nor remaining; it prices on its new day.
            moved_lines.append(f"  {num_label:>5}  {cost:4.1f}  {note}  "
                               f"→ {it['deferred_to']}  {it['text'].lstrip(MOVE_ARROWS + ' ')[:44]}")
        elif it["done"]:
            done_total += cost
            done_lines.append(line)
        else:
            rest_total += cost
            rest_lines.append(line)

    return {
        "done": done_total,
        "remaining": rest_total,
        "built": done_total + rest_total,
        "guessed": guessed,
        "streakless": streakless,
        "unpriced": unpriced,
        "done_lines": done_lines,
        "rest_lines": rest_lines,
        "moved_lines": moved_lines,
    }


def price_schedule_day(day: dt.date, rows: list[dict], cfg: dict) -> None:
    """Price a scheduled day as BUILT, splitting done from remaining.

    This exists because --day cannot do it. --day takes a list of numbers from a
    human, so it prices exactly what it is handed -- and mid-session the natural
    thing to hand it is the REMAINING items, whose total then reads as the day's
    total. That error (Aug 18, 2026) invented 5.0 units of spare capacity on a day
    already sitting at the ceiling, and a discretionary rep got seated on it. Here
    the tool defines the day, so there is nothing to mis-hand it.
    """
    path = find_schedule(day)
    if path is None:
        print(f"no weekly schedule covers {day} (looked in {SCHEDULES} and archive/)")
        return
    items, stated = parse_schedule_day(path, day)
    _, planned = day_header_figures(path.read_text(encoding="utf-8").splitlines(), day)
    if not items:
        print(f"{day} has no block in {path.name} -- nothing scheduled, or the day "
              f"header is not in the form this parser expects.")
        return

    p = price_day_items(day, items, rows, cfg)
    done_total, rest_total, built = p["done"], p["remaining"], p["built"]
    guessed, unpriced, streakless = p["guessed"], p["unpriced"], p["streakless"]
    done_lines, rest_lines = p["done_lines"], p["rest_lines"]

    print(f"{day:%a %b %d} - {path.name}\n")
    if done_lines:
        print("  DONE")
        print("\n".join(done_lines))
    if rest_lines:
        print("\n  REMAINING")
        print("\n".join(rest_lines))
    if p["moved_lines"]:
        print("\n  MOVED (deferred off this day -- not billed here; prices on the new day)")
        print("\n".join(p["moved_lines"]))
    if unpriced:
        print("\n  UNPRICED (no problem number -- primer, probe, or free-text row)")
        for u in unpriced:
            print(f"    {u}")

    ceiling = cfg["ceiling"]
    # A total that silently omits rows is the exact failure this whole flag exists to
    # prevent, so say what could NOT be priced BEFORE saying the number.
    partial = len(unpriced) + guessed
    floor_note = "  (FLOOR -- see below)" if partial else ""
    print(f"\n  built {built:.1f}{floor_note} / done {done_total:.1f} "
          f"/ remaining {rest_total:.1f} / ceiling {ceiling:.0f}")
    print("\n".join(row_cap_lines(count_rows(items), cfg)))
    if partial:
        bits = []
        if unpriced:
            bits.append(f"{len(unpriced)} row(s) carry no problem number "
                        f"(primer / probe / free text)")
        if guessed:
            bits.append(f"{guessed} untracked or hint-less mock row(s) guessed at Blank Medium -- a new "
                        f"HARD really costs 1.5x that")
        print(f"     !! this total is a LOWER BOUND: {'; '.join(bits)}.")
    if streakless:
        print(f"  !! {streakless} 🟢 row(s) carry no streak in the Start cell -- "
              f"priced at s0, so this total may OVERSTATE the day")
    if built > ceiling:
        print(f"  !! the day as BUILT is OVER by {built - ceiling:.1f}")
    elif not partial:
        print(f"  {ceiling - built:.1f} spare against the day as built")
    else:
        print(f"  at most {ceiling - built:.1f} spare -- less once the rows above price")

    # Catch a build-time arithmetic slip too: the header states a total, and until now
    # nothing had ever checked it against the rows underneath it. Only assert a real
    # mismatch when EVERY row was priced from a Start glyph against a tracked row --
    # otherwise the difference is just the part this parser admits it cannot see, and
    # crying wrong on that is how a check stops being read. A streakless 🟢 row is priced
    # from a guessed streak (s0), so it is in the same boat -- "matches" would claim an
    # agreement this parser cannot actually vouch for.
    if stated is None:
        print("  !! the day header states no unit total -- add it so it can be checked")
    elif partial or streakless:
        # partial/streakless is checked BEFORE the "matches" comparison below, not after:
        # a guessed or unpriced row's cost can coincidentally land the totals within 0.05
        # of each other, and "matches" must never print while that is true.
        print(f"  header says {stated:.1f}, priced rows sum to {built:.1f} "
              f"(difference {stated - built:+.1f}) -- CANNOT VERIFY while rows are "
              f"unpriced or guessed. Check that difference is what those rows are worth.")
    elif abs(stated - built) <= 0.05:
        print(f"  header says {stated:.1f} -- matches")
    else:
        print(f"  !! HEADER SAYS {stated:.1f}, rows sum to {built:.1f} -- every row "
              f"priced exactly, so one of them is wrong")
    if planned is not None:
        print(f"  planned {planned:.1f} -- pinned when the day started; "
              f"{len(p['moved_lines'])} row(s) moved off")



def report_due(rows: list[dict], cfg: dict, day: dt.date) -> None:
    due = [r for r in rows if dt.date.fromisoformat(r["due"]) <= day]
    due.sort(key=lambda r: (r["due"], -units(r, cfg)))
    total = 0.0
    for r in due:
        total += units(r, cfg)
        print(f"  {r['due']}  {units(r, cfg):4.1f}  {label(r):8} {r['num']:>5} "
              f"{r['title'][:40]}")
    print(f"\n  {len(due)} due on/before {day} · {total:.1f} units "
          f"= {total / cfg['ceiling']:.1f} days at the ceiling")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", nargs="+", metavar="NUM",
                    help="price a HYPOTHETICAL day built from these problem numbers. "
                         "A live pricer, not a ledger -- for a day already in progress "
                         "use --schedule-day")
    ap.add_argument("--schedule-day", nargs="?", const="", metavar="YYYY-MM-DD",
                    help="price a scheduled day AS BUILT from the weekly schedule file "
                         "(Start column = the comfort each row was billed at), split "
                         "into done vs remaining. Defaults to today")
    ap.add_argument("--sd", action="store_true",
                    help="RETIRED — SD is off-board and unpriced since Aug 16, 2026. "
                         "Accepted so the flag explains itself; adds 0 units")
    ap.add_argument("--due", metavar="YYYY-MM-DD",
                    help="list everything due on or before this date, priced")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="override the resolved session date (default: detected session "
                         "date, not just the system clock — see session_date.py)")
    args = ap.parse_args()

    cfg = load_config()
    rows = parse_rows()
    # Resolved the way every other date-touching script here does (session_date.py):
    # a session past midnight keeps its START date. session_date.resolve_datetime
    # announces a heuristic guess with a bare print() to stdout — redirected to stderr
    # so it never lands inside this script's own stdout report (mirrors gamify.py
    # main()'s identical redirect).
    with contextlib.redirect_stdout(sys.stderr):
        today = session_date.resolve_datetime(args.today).date()

    if args.schedule_day is not None:
        target = dt.date.fromisoformat(args.schedule_day) if args.schedule_day else today
        price_schedule_day(target, rows, cfg)
    elif args.day:
        price_day(args.day, rows, cfg, args.sd, today)
    elif args.due:
        report_due(rows, cfg, dt.date.fromisoformat(args.due))
    else:
        report_demand(rows, cfg, today)


if __name__ == "__main__":
    main()
