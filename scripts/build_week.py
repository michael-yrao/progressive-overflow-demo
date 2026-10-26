"""The mechanical weekly build: write the next week's schedule file with no coach in the loop.

    py scripts/build_week.py [--week YYYY-MM-DD] [--now YYYY-MM-DDTHH:MM] [--early] [--dry-run]
    py scripts/build_week.py --top-up [--now YYYY-MM-DDTHH:MM]

`--now` is local time in the config's `timezone`. Run from the repo root (the weekly-build
workflow does). Exit 2 (`refused: ...`): no cse.config.yml, unknown timezone, a missing or
out-of-range `automation` key, a --week that is not a Monday. Exit 0 skips: `skipped: weekly
build is off`, `skipped: <file> exists` (live or archive), `skipped: boundary <iso> not
reached`. Success prints `built: YYYY-MM-DD`. `--dry-run` prints the week instead, writes and
moves nothing. `--dry-run`, an explicit `--week` and `--early` (operator requests) all ignore
`automation.weekly_build: false`.

`--top-up` seats into the newest live week every due tracker row that has no cell there and
was not struck in the previous week's file, on days from today on. It honours
`automation.weekly_build` and never archives or moves a file. Exit 0 prints `topped-up: <n>
rows into YYYY-MM-DD`, `skipped: nothing to top up` or `skipped: no live week to top up`.

The steps, each a function returning frozen data:
  1 target_week          which Monday to build, or why to skip
  2 stale_live_files     live files older than the target, moved with `git mv` by archive()
  3 due_rows             tracker rows due by the target Sunday (parse_rows once)
  4 intake_paused        the unproven-overdue backstop
  5 intake_candidates    new problems from the curriculum, site-runnable first
  6 build_items          each row rendered and priced once, through price_day_items
  7 (sort in build_items) priority_key, then due, then number
  8 plan_week            seat unproven and new rows first, proven rows after, the rest carried
  9 render_week          the week file text
 10 finish               reprice_days, sort_day_blocks, write, then the integrity check

Dropped in headless mode (the coach-driven build keeps them): forecast talk, the complexity
block, the Pattern Sense deck, the technique_comfort_audit pull order, primers/probes/mocks,
spec authoring (replaced by preferring site-runnable problems), the next-week preview, prose
goals and day labels, and the SD slot.

Tuned numbers (ceiling, max_rows_per_day, intake_per_week, intake_pause_overdue_unproven,
carry_forward_min_streak, build_lead_hours) are read from cse.config.yml, never copied here.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import subprocess
import sys
import urllib.request
import zoneinfo
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

import _console
import curriculum
import effort_budget as eb
import fold_record
import fold_schedule
import links
import schedule_priority

_console.force_utf8()

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_NAME = "cse.config.yml"
LIVE_DIR = Path("docs/foundations/schedules")
ARCHIVE_DIR = LIVE_DIR / "archive"
TECHNIQUES_PATH = Path("docs/foundations/dsa/mastery/techniques.yml")
CATALOGUE_PATH = Path("curriculum/dsa/techniques.yml")
SCHEDULE_NAME = "{monday:%Y%m%d}_schedule.md"
SCHEDULE_SUFFIX = "_schedule.md"
BUILT_BY_MARKER = "<!-- built-by: build_week.py -->"
DAYS_PER_WEEK = 7
SITE_INDEX_TIMEOUT_S = 10
MAX_LEAD_HOURS = 10
EXIT_REFUSED = 2
INDEX_SCHEMA_VERSION = 1
AUTOMATION_KEYS = ("build_lead_hours", "practice_index_url", "prefer_practice_spec")
NEW_GLYPH = eb.NEW_GLYPH
EMPTY_ROW = "|  |  |  |  |  |"
TAGS_LINE = "Tags: 🎯 probe · → moved."
DEFAULT_TIMEZONE = "UTC"
DEFAULT_DIFFICULTY = "Medium"

Opener = Callable[[str, float], bytes]


class BuildRefused(Exception):
    """The build cannot run; the message is the `refused:` line."""


@dataclass(frozen=True)
class Automation:
    is_enabled: bool
    lead_hours: int
    index_url: str
    prefers_spec: bool


@dataclass(frozen=True)
class WeekTarget:
    monday: dt.date | None
    skip: str | None


@dataclass(frozen=True)
class SeatItem:
    number: str
    cell: str
    start: str
    technique: str
    due: dt.date
    cost: float
    is_priority: bool
    key: tuple


@dataclass(frozen=True)
class DayPlan:
    day: dt.date
    items: tuple[SeatItem, ...]
    units: float
    base_rows: int = 0  # rows already in the day's block before this plan seats anything


@dataclass(frozen=True)
class WeekPlan:
    days: tuple[DayPlan, ...]
    carried: tuple[SeatItem, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class PlanContext:
    monday: dt.date
    first_day: dt.date
    ceiling: float
    max_rows: int
    items: tuple[SeatItem, ...]


@dataclass(frozen=True)
class BuildInputs:
    monday: dt.date
    cfg: dict
    rows: tuple[dict, ...]
    site_numbers: frozenset[int] | None
    techniques: dict
    first_day: dt.date


def monday_of(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def day_label(day: dt.date) -> str:
    return f"{day:%a %b} {day.day}"


# ---------------------------------------------------------------- config

def load_automation(root_cfg: dict, is_required: bool = False) -> Automation:
    """The `automation` block. Missing block: disabled. Enabled (or required, as in a
    dry run) with a missing or out-of-range key: BuildRefused naming it."""
    block = root_cfg.get("automation")
    if not isinstance(block, dict):
        return Automation(False, 0, "", False)
    is_enabled = block.get("weekly_build") is True
    if is_enabled or is_required:
        missing = [key for key in AUTOMATION_KEYS if block.get(key) is None]
        if missing:
            raise BuildRefused(f"automation.{missing[0]} missing from {CONFIG_NAME}")
    lead = int(block.get("build_lead_hours") or 0)
    if not 0 <= lead <= MAX_LEAD_HOURS:
        raise BuildRefused(f"automation.build_lead_hours {lead} is outside 0..{MAX_LEAD_HOURS}")
    return Automation(is_enabled, lead, str(block.get("practice_index_url") or ""),
                      block.get("prefer_practice_spec") is True)


def read_start_date(root_cfg: dict) -> dt.date | None:
    """The optional top-level `start_date`; None when the config has none."""
    raw = root_cfg.get("start_date")
    if raw is None:
        return None
    return raw if isinstance(raw, dt.date) else dt.date.fromisoformat(str(raw))


def check_timezone(name: str) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise BuildRefused(f"timezone {name!r} is not one zoneinfo knows") from exc


# ---------------------------------------------------------------- steps 1-2

def target_week(now: dt.datetime, existing_mondays: frozenset[dt.date],
                start_monday: dt.date | None, lead: dt.timedelta, early: bool) -> WeekTarget:
    """The Monday to build. The current week (floored at the start Monday) when its file is
    missing; else the next week once `now` reaches next Monday 00:00 minus `lead` (or `early`)."""
    current = monday_of(now.date())
    if start_monday and current < start_monday:
        current = start_monday
    if current not in existing_mondays:
        return WeekTarget(current, None)
    if monday_of(now.date()) < current:  # the start week is still ahead and already built
        return WeekTarget(None, f"{SCHEDULE_NAME.format(monday=current)} exists")
    following = current + dt.timedelta(days=DAYS_PER_WEEK)
    if following in existing_mondays:
        return WeekTarget(None, f"{SCHEDULE_NAME.format(monday=following)} exists")
    boundary = dt.datetime.combine(following, dt.time.min) - lead
    if early or now >= boundary:
        return WeekTarget(following, None)
    return WeekTarget(None, f"boundary {boundary.isoformat(timespec='minutes')} not reached")


def monday_of_file(path: Path) -> dt.date | None:
    stamp = path.name.removesuffix(SCHEDULE_SUFFIX)
    if len(stamp) != 8 or not stamp.isdigit() or path.name == stamp:
        return None
    try:
        return dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
    except ValueError:
        return None


def schedule_files(folder: Path) -> dict[dt.date, Path]:
    if not folder.is_dir():
        return {}
    found = ((monday_of_file(path), path) for path in folder.glob(f"*{SCHEDULE_SUFFIX}"))
    return {monday: path for monday, path in found if monday is not None}


def stale_live_files(live: dict[dt.date, Path], target: dt.date) -> tuple[Path, ...]:
    return tuple(path for monday, path in sorted(live.items()) if monday < target)


def archive(repo: Path, files: tuple[Path, ...]) -> None:
    (repo / ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
    for path in files:
        subprocess.run(["git", "mv", str(path), str(repo / ARCHIVE_DIR / path.name)],
                       cwd=repo, check=True)


# ---------------------------------------------------------------- steps 3-5

def due_rows(rows: list[dict], sunday: dt.date) -> tuple[dict, ...]:
    return tuple(row for row in rows if dt.date.fromisoformat(row["due"]) <= sunday)


def urlopen_bytes(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - config URL
        return response.read()


def fetch_site_numbers(url: str, opener: Opener,
                       timeout: float = SITE_INDEX_TIMEOUT_S) -> frozenset[int] | None:
    """The practice index's problem numbers, or None on any network, JSON or schema failure."""
    if not url:
        return None
    try:
        data = json.loads(opener(url, timeout))
        if data["schemaVersion"] != INDEX_SCHEMA_VERSION:
            return None
        return frozenset(int(number) for number in data["numbers"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def intake_candidates(catalog: tuple[dict, ...], rows: tuple[dict, ...] | list[dict],
                      site_numbers: frozenset[int] | None, intake_per_week: int,
                      is_paused: bool) -> tuple[dict, ...]:
    """Curriculum-order problems with no dated tracker row, runnable-on-the-site first when
    `site_numbers` is given, at most `intake_per_week`."""
    if is_paused:
        return ()
    tracked = {int(row["num"]) for row in rows}
    fresh = [entry for entry in catalog if entry["number"] not in tracked]
    if site_numbers is not None:
        fresh.sort(key=lambda entry: entry["number"] not in site_numbers)
    return tuple(fresh[:intake_per_week])


# ---------------------------------------------------------------- steps 6-7

def load_techniques(catalogue: Path, overlay: Path) -> dict[tuple[str, str | None], str]:
    """(number, method) -> technique name from the merged catalogue + overlay; (number, None) is the first."""
    data = curriculum.load_techniques(catalogue, overlay)
    found: dict[tuple[str, str | None], str] = {}
    for technique in data.get("techniques") or []:
        for problem in technique.get("problems") or []:
            number = str(problem.get("number"))
            found.setdefault((number, problem.get("method")), technique["name"])
            found.setdefault((number, None), technique["name"])
    return found


def render_row(item_cell: str, start: str, technique: str) -> str:
    return f"| {item_cell} | {start} |  |  | {technique} |"


def tracked_cell(row: dict, variant: str | None, site_numbers: frozenset[int] | None) -> str:
    link = links.schedule_link_line(row["num"], site_numbers=site_numbers)
    title = fold_record.VARIANT.sub("", row["title"]).strip()
    base = fold_record.schedule_cell(link, f"{row['num']} {title}")
    return fold_record.add_variant(base, variant)


def priced(inputs: BuildInputs, by_num: dict[str, list[dict]], number: str, line: str,
           difficulty: str) -> tuple[float, tuple]:
    """Cost through price_day_items (the pricing path the headers use) and the sort key."""
    parsed = eb.parse_sched_line(line)
    cost = eb.price_day_items(inputs.monday, [parsed], by_num.get(number, []), inputs.cfg)["built"]
    return cost, schedule_priority.priority_key(parsed, difficulty)


def tracked_item(row: dict, inputs: BuildInputs, by_num: dict[str, list[dict]]) -> SeatItem:
    variant = fold_record.row_variant(row["title"])
    cell = tracked_cell(row, variant, inputs.site_numbers)
    start = fold_record.start_cell(row["comfort"], row["streak"])
    technique = variant or inputs.techniques.get((row["num"], None), "")
    cost, key = priced(inputs, by_num, row["num"], render_row(cell, start, technique), row["diff"])
    return SeatItem(row["num"], cell, start, technique, dt.date.fromisoformat(row["due"]), cost,
                    eb.is_unproven(row["comfort"], row["streak"], inputs.cfg),
                    (*key, row["due"], int(row["num"])))


def new_item(entry: dict, inputs: BuildInputs, by_num: dict[str, list[dict]]) -> SeatItem:
    number = str(entry["number"])
    url = links.SITE_PRACTICE_URL_TEMPLATE.format(number=number)
    cell = f"{NEW_GLYPH} [{number} {entry['title']}]({url})"
    line = render_row(cell, NEW_GLYPH, "")
    cost, key = priced(inputs, by_num, number, line, entry["difficulty"] or DEFAULT_DIFFICULTY)
    return SeatItem(number, cell, NEW_GLYPH, "", inputs.first_day, cost, True,
                    (*key, inputs.first_day.isoformat(), entry["number"]))


def rows_by_number(rows: tuple[dict, ...] | list[dict]) -> dict[str, list[dict]]:
    by_num: dict[str, list[dict]] = {}
    for row in rows:
        by_num.setdefault(row["num"], []).append(row)
    return by_num


def build_items(inputs: BuildInputs, new_entries: tuple[dict, ...]) -> tuple[SeatItem, ...]:
    by_num = rows_by_number(inputs.rows)
    items = [tracked_item(row, inputs, by_num) for row in inputs.rows]
    items += [new_item(entry, inputs, by_num) for entry in new_entries]
    return tuple(sorted(items, key=lambda item: item.key))


# ---------------------------------------------------------------- step 8

def week_days(monday: dt.date, first_day: dt.date) -> tuple[dt.date, ...]:
    days = (monday + dt.timedelta(days=offset) for offset in range(DAYS_PER_WEEK))
    return tuple(day for day in days if day >= first_day)


def earliest_index(plan: WeekPlan, item: SeatItem) -> int:
    for index, day_plan in enumerate(plan.days):
        if day_plan.day >= item.due:
            return index
    return len(plan.days) - 1


def fits(day_plan: DayPlan, item: SeatItem, ctx: PlanContext) -> bool:
    return day_plan.base_rows + len(day_plan.items) < ctx.max_rows and day_plan.units + item.cost <= ctx.ceiling


def place(plan: WeekPlan, item: SeatItem, index: int, note: str | None = None) -> WeekPlan:
    target = plan.days[index]
    seated = replace(target, items=(*target.items, item), units=target.units + item.cost)
    days = (*plan.days[:index], seated, *plan.days[index + 1:])
    notes = (*plan.notes, note) if note else plan.notes
    return replace(plan, days=days, notes=notes)


def seat(plan: WeekPlan, item: SeatItem, ctx: PlanContext) -> WeekPlan:
    """A new plan with `item` on its earliest fitting day. Nothing fits: a priority item is
    forced onto the least-loaded eligible day (noted); any other is carried."""
    start = earliest_index(plan, item)
    for index in range(start, len(plan.days)):
        if fits(plan.days[index], item, ctx):
            return place(plan, item, index)
    if not item.is_priority:
        return replace(plan, carried=(*plan.carried, item))
    forced = min(range(start, len(plan.days)), key=lambda index: plan.days[index].units)
    return place(plan, item, forced, f"forced over cap: {plan.days[forced].day:%a}")


def plan_week(ctx: PlanContext) -> WeekPlan:
    """Unproven and new rows first (forced if need be), then proven rows; leftovers carry."""
    empty = tuple(DayPlan(day, (), 0.0) for day in week_days(ctx.monday, ctx.first_day))
    return seat_all(WeekPlan(empty, (), ()), ctx)


def seat_all(plan: WeekPlan, ctx: PlanContext) -> WeekPlan:
    """`ctx.items` seated onto `plan`: priority items first, then the rest."""
    for item in (i for i in ctx.items if i.is_priority):
        plan = seat(plan, item, ctx)
    for item in (i for i in ctx.items if not i.is_priority):
        plan = seat(plan, item, ctx)
    return plan


# ---------------------------------------------------------------- step 9

def week_title(monday: dt.date) -> str:
    sunday = monday + dt.timedelta(days=DAYS_PER_WEEK - 1)
    end = f"{sunday.day}" if sunday.month == monday.month else f"{sunday:%B} {sunday.day}"
    return f"# Week of {monday:%B} {monday.day} – {end}, {sunday.year}"


def day_block(day_plan: DayPlan) -> list[str]:
    header = f"| ▸ **{day_label(day_plan.day)}** · ~{day_plan.units:.1f} units |  |  |  |  |"
    rows = [render_row(item.cell, item.start, item.technique) for item in day_plan.items]
    return [header, *rows, EMPTY_ROW]


def carried_bullets(carried: tuple[SeatItem, ...]) -> list[str]:
    return [f"- {item.cell} · {item.start} · due {item.due.isoformat()}" for item in carried]


def render_week(monday: dt.date, plan: WeekPlan, due_count: int) -> str:
    seated = [item for day_plan in plan.days for item in day_plan.items]
    new_count = sum(1 for item in seated if item.start == NEW_GLYPH)
    sunday = monday + dt.timedelta(days=DAYS_PER_WEEK - 1)
    built = " · ".join(f"{day_plan.day:%a} {day_plan.units:.1f}" for day_plan in plan.days)
    lines = [
        week_title(monday), "", BUILT_BY_MARKER, "",
        f"**Goal:** {len(seated) - new_count} reviews and {new_count} new problems seated, "
        f"{len(plan.carried)} carried.", "", "---", "",
        "## ⚖️ Capacity", "", "```",
        f"reviews  {due_count} due by {sunday:%b} {sunday.day}",
        f"built    per day, build_week.py: {built}", "```", "", "---", "",
        "## Daily Schedule", "",
        "Columns: **S** = start comfort · **E** = end comfort · **Next** = next-review · "
        "**Technique** = one-word tag.", "", TAGS_LINE, "",
        "| Problem | S | E | Next | Technique |", "|---|:-:|:-:|:-:|---|",
    ]
    for day_plan in plan.days:
        lines += day_block(day_plan)
    lines += ["", "**⚙️ Build notes**", *[f"- {note}" for note in plan.notes], ""]
    if plan.carried:
        lines += ["---", "", "## ⏭️ Carried to next week (row cap)", "", *carried_bullets(plan.carried), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- step 10 and main

def finish(text: str, inputs: BuildInputs, plan: WeekPlan) -> str:
    days = tuple(day_plan.day for day_plan in plan.days)
    repriced = fold_schedule.reprice_days(text, inputs.monday, days, list(inputs.rows), inputs.cfg)
    difficulty_of = {row["num"]: row["diff"] for row in inputs.rows}
    return schedule_priority.sort_day_blocks(repriced, difficulty_of)


# ---------------------------------------------------------------- top-up

NOTES_MARKER = "**⚙️ Build notes**"
NOTE_BULLET = "- "
SKIP_NOTHING_TO_TOP_UP = "skipped: nothing to top up"
SKIP_NO_LIVE_WEEK = "skipped: no live week to top up"


@dataclass(frozen=True)
class WeekView:
    """A schedule file read once: its lines and where each day's header sits."""
    lines: list[str]
    headers: dict[dt.date, int]


def view_of(text: str, monday: dt.date) -> WeekView:
    lines = text.split("\n")
    return WeekView(lines, fold_schedule.day_headers(lines, monday))


def cell_variant(cell: str) -> str | None:
    """The `(variant)` a schedule cell carries inside its `[N Title (variant)]` link text."""
    match = eb.SCHED_NUM.search(cell)
    if match is None:
        return None
    return fold_record.row_variant(cell[match.end():].split("]", 1)[0])


def matching_cells(week: WeekView, row: dict) -> list[fold_schedule.Row]:
    """The week's cells for this tracker row: same number, and the same variant (or none)."""
    variant = fold_record.row_variant(row["title"])
    found = fold_schedule.rows_for(week.lines, week.headers, row["num"])
    return [cell for cell in found if cell_variant(cell.cells[0]) == variant]


def missing_rows(rows: tuple[dict, ...], week: WeekView) -> tuple[dict, ...]:
    """Rows with no cell in `week`. A rep struck last week whose follow-up is due this week is
    exactly the case an early build misses, so last week's file is not consulted."""
    return tuple(row for row in rows if not matching_cells(week, row))


def eligible_days(monday: dt.date, today: dt.date, start: dt.date | None,
                  week: WeekView) -> tuple[dt.date, ...]:
    """The week's days from today (or the start date) on that have a block in the file."""
    first_day = max(monday, today, start) if start else max(monday, today)
    return tuple(day for day in week_days(monday, first_day) if day in week.headers)


def existing_day_plan(day: dt.date, week: WeekView, monday: dt.date, rows: list[dict],
                      cfg: dict) -> DayPlan:
    """An empty plan carrying the day's current row count and priced units, read from the file."""
    items, _ = eb.parse_day_block(week.lines, monday, day)
    if not items:
        return DayPlan(day, (), 0.0)
    with contextlib.redirect_stdout(sys.stderr):
        units = eb.price_day_items(day, items, rows, cfg)["built"]
    return DayPlan(day, (), units, len(items))


def insert_seated(lines: list[str], monday: dt.date, plan: WeekPlan) -> list[str]:
    """`lines` with each seated item's row at the end of its day's block."""
    result = lines
    for day_plan in plan.days:
        for item in day_plan.items:
            end = fold_schedule.block_end(result, fold_schedule.day_headers(result, monday)[day_plan.day])
            result = fold_schedule.insert_at(result, end, render_row(item.cell, item.start, item.technique))
    return result


def add_build_notes(lines: list[str], notes: tuple[str, ...]) -> list[str]:
    """`notes` as bullets at the end of the Build notes section (the section is added if absent)."""
    if not notes:
        return lines
    bullets = [f"{NOTE_BULLET}{note}" for note in notes]
    if NOTES_MARKER not in lines:
        return [*lines, "", NOTES_MARKER, *bullets, ""]
    end = lines.index(NOTES_MARKER) + 1
    while end < len(lines) and lines[end].startswith(NOTE_BULLET):
        end += 1
    return [*lines[:end], *bullets, *lines[end:]]


def seated_count(plan: WeekPlan) -> int:
    return sum(len(day_plan.items) for day_plan in plan.days)


def top_up_plan(inputs: BuildInputs, missing: tuple[dict, ...], week: WeekView,
                days: tuple[dt.date, ...], all_rows: list[dict]) -> WeekPlan:
    """The missing rows seated by `seat()` onto day plans that start from the file's own rows."""
    by_num = rows_by_number(inputs.rows)
    items = tuple(sorted((tracked_item(row, inputs, by_num) for row in missing),
                         key=lambda item: item.key))
    ctx = PlanContext(inputs.monday, inputs.first_day, inputs.cfg["ceiling"],
                      inputs.cfg["max_rows_per_day"], items)
    start = WeekPlan(tuple(existing_day_plan(day, week, inputs.monday, all_rows, inputs.cfg)
                           for day in days), (), ())
    return seat_all(start, ctx)


def top_up(args: argparse.Namespace, now: dt.datetime, repo: Path, root_cfg: dict,
           automation: Automation, opener: Opener) -> str:
    """Seat the newest live week's missing due rows into it; the `topped-up:` / `skipped:` line."""
    live = schedule_files(repo / LIVE_DIR)
    if not live:
        return SKIP_NO_LIVE_WEEK
    monday = max(live)
    week = view_of(live[monday].read_text(encoding="utf-8"), monday)
    days = eligible_days(monday, now.date(), read_start_date(root_cfg), week)
    if not days:
        return SKIP_NOTHING_TO_TOP_UP
    all_rows = eb.parse_rows()
    rows = due_rows(all_rows, monday + dt.timedelta(days=DAYS_PER_WEEK - 1))
    missing = missing_rows(rows, week)
    if not missing:
        return SKIP_NOTHING_TO_TOP_UP
    inputs = BuildInputs(monday, eb.load_config(), rows,
                         fetch_site_numbers(automation.index_url, opener),
                         load_techniques(repo / CATALOGUE_PATH, repo / TECHNIQUES_PATH), days[0])
    plan = top_up_plan(inputs, missing, week, days, all_rows)
    if seated_count(plan) == 0:
        return SKIP_NOTHING_TO_TOP_UP
    lines = add_build_notes(insert_seated(week.lines, monday, plan), plan.notes)
    touched = replace(plan, days=tuple(day_plan for day_plan in plan.days if day_plan.items))
    text = finish("\n".join(lines), inputs, touched)
    if args.dry_run:
        return f"{text}\ndry-run: {monday.isoformat()}"
    write_checked(live[monday], monday, repo, text)
    return f"topped-up: {seated_count(plan)} rows into {monday.isoformat()}"


def write_checked(path: Path, monday: dt.date, repo: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    check_integrity(path, monday, repo)


def check_integrity(path: Path, monday: dt.date, repo: Path) -> None:
    """Report-only: the checker's findings go to stderr and never change the exit code."""
    result = subprocess.run(
        [sys.executable, str(repo / "scripts" / "check_schedule_integrity.py"),
         "--file", str(path), "--date", monday.isoformat()],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False)
    print(result.stdout + result.stderr, file=sys.stderr, end="")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--week", type=dt.date.fromisoformat, help="build this Monday")
    parser.add_argument("--now", type=dt.datetime.fromisoformat, help="local time, naive")
    parser.add_argument("--early", action="store_true", help="ignore the boundary and the weekly_build switch")
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    parser.add_argument("--top-up", action="store_true",
                        help="seat missing due rows into the newest live week")
    return parser.parse_args(argv)


def load_root_config(repo: Path) -> dict:
    path = repo / CONFIG_NAME
    if not path.is_file():
        raise BuildRefused(f"no {CONFIG_NAME} — onboard first")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def resolve_target(args: argparse.Namespace, now: dt.datetime, repo: Path,
                   root_cfg: dict, automation: Automation) -> WeekTarget:
    existing = frozenset(schedule_files(repo / LIVE_DIR)) | frozenset(schedule_files(repo / ARCHIVE_DIR))
    if args.week is not None:
        if args.week.weekday() != 0:
            raise BuildRefused(f"--week {args.week.isoformat()} is not a Monday")
        if args.week in existing:
            return WeekTarget(None, f"{SCHEDULE_NAME.format(monday=args.week)} exists")
        return WeekTarget(args.week, None)
    lead = dt.timedelta(hours=automation.lead_hours)
    start = read_start_date(root_cfg)
    return target_week(now, existing, monday_of(start) if start else None, lead, args.early)


def assemble(monday: dt.date, root_cfg: dict, automation: Automation,
             repo: Path, opener: Opener) -> tuple[BuildInputs, WeekPlan, int]:
    cfg = eb.load_config()
    sunday = monday + dt.timedelta(days=DAYS_PER_WEEK - 1)
    all_rows = eb.parse_rows()
    rows = due_rows(all_rows, sunday)
    site_numbers = fetch_site_numbers(automation.index_url, opener)
    start = read_start_date(root_cfg)
    first_day = max(monday, start) if start else monday
    inputs = BuildInputs(monday, cfg, rows, site_numbers,
                         load_techniques(repo / CATALOGUE_PATH, repo / TECHNIQUES_PATH), first_day)
    _, is_paused = eb.unproven_overdue(all_rows, cfg, monday)
    preferred = site_numbers if automation.prefers_spec else None
    entries = intake_candidates(curriculum.intake_order(), all_rows, preferred,
                                cfg["intake_per_week"], is_paused)
    ctx = PlanContext(monday, first_day, cfg["ceiling"], cfg["max_rows_per_day"],
                      build_items(inputs, entries))
    plan = plan_week(ctx)
    notes = build_notes(is_paused, site_numbers, plan.notes)
    return inputs, replace(plan, notes=notes), len(rows)


def build_notes(is_paused: bool, site_numbers: frozenset[int] | None,
                seat_notes: tuple[str, ...]) -> tuple[str, ...]:
    notes = list(seat_notes)
    if is_paused:
        notes.append("intake paused: the unproven-overdue backstop tripped")
    if site_numbers is None:
        notes.append("practice index unavailable: new problems follow curriculum order")
    return tuple(notes)


def run(args: argparse.Namespace, repo: Path, opener: Opener) -> str:
    """The `skipped:` / `built:` / dry-run output line(s); raises BuildRefused."""
    root_cfg = load_root_config(repo)
    zone = check_timezone(str(root_cfg.get("timezone") or DEFAULT_TIMEZONE))
    automation = load_automation(root_cfg, is_required=args.dry_run)
    is_operator_request = args.dry_run or args.week is not None or args.early
    if not automation.is_enabled and not is_operator_request:
        return "skipped: weekly build is off"
    now = args.now or dt.datetime.now(zone).replace(tzinfo=None)
    if args.top_up:
        return top_up(args, now, repo, root_cfg, automation, opener)
    target = resolve_target(args, now, repo, root_cfg, automation)
    if target.monday is None:
        return f"skipped: {target.skip}"
    inputs, plan, due_count = assemble(target.monday, root_cfg, automation, repo, opener)
    text = finish(render_week(target.monday, plan, due_count), inputs, plan)
    if args.dry_run:
        return f"{text}\ndry-run: {target.monday.isoformat()}"
    return write_week(repo, target.monday, text)


def write_week(repo: Path, monday: dt.date, text: str) -> str:
    live = schedule_files(repo / LIVE_DIR)
    archive(repo, stale_live_files(live, monday))
    path = repo / LIVE_DIR / SCHEDULE_NAME.format(monday=monday)
    write_checked(path, monday, repo, text)
    return f"built: {monday.isoformat()}"


def main(argv: list[str] | None = None, repo: Path = REPO_ROOT,
         opener: Opener = urlopen_bytes) -> int:
    try:
        print(run(parse_args(argv), repo, opener))
    except BuildRefused as exc:
        print(f"refused: {exc}")
        return EXIT_REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
