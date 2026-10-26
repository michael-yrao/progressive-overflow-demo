"""Emit an honest-progress data contract (progress.json) for the practice log.

This is the source-tier half of the gamification feature: it reads the records
that already exist — the DSA tracker, the weekly schedules, the technique-coverage
view — and emits ONE machine-readable file that a viewer (progressiveoverflow.com)
renders as a dashboard. Per the intervention ladder, a tool that emits the value
outranks a rule that asks someone to compute it.

    dsa_progress.md  +  schedules/*.md  +  technique_coverage.md  ->  progress.json

Design constraints this file honours (see docs/ARCHITECTURE.md and CLAUDE.md):

  * HONEST PROCESS ONLY. Every number here is earnable only by genuine learning —
    showing up (streak), problems maturing up the ladder (pipeline / trophy case),
    technique breadth (coverage). Nothing rewards raw volume or a self-reported
    rating, so nothing here creates pressure to inflate a comfort call.

  * SINGLE SOURCE OF TRUTH. Tuned thresholds are read from cse.config.yml's
    `gamification:` block; a DEFAULT_CONFIG fallback exists only for a pre-config
    run and ANNOUNCES itself when it fires. The badge CATALOG (names / icons /
    descriptions) is content, not a tuned number, so it lives here.

  * CURATED / NON-SENSITIVE. progress.json carries aggregate stats, per-problem
    status and a comfort timeline, and links — never solution code, never
    stuck-log prose. The source repo can be public without exposing struggle notes.

  * FAIL-SOFT. A parse gap degrades to partial output with a visible note; it never
    raises out of the hook. A fresh adopter checkout (no roadmap.yml, no schedule
    history, an empty Waiting Room) yields empty arrays, not an error. Windows cp1252
    consoles get force_utf8() like every other script here.

Usage:
    python scripts/gamify.py                 # write progress.json + progress-summary.json (+ README badge)
    python scripts/gamify.py --validate       # compute + validate schema, write nothing
    python scripts/gamify.py --banner         # one honest line for the SessionStart hook
    python scripts/gamify.py --stdout         # print the JSON instead of writing it
    python scripts/gamify.py --date 2026-09-20  # override the resolved session date

Two files, one build. progress.json is the full contract (includes `problems[]`, the
heavy part). progress-summary.json is the same payload minus `problems[]`, with a
COMPACT trophyCase (graduated entries drop their timeline/repDates) — a few KB, cheap
enough for a dashboard landing to fetch on every page view without mounting per-problem
components. See summary_of().
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Iterator

import _console
import contract_schema

# effort_budget already solves tracker parsing and schedule discovery; reuse it rather
# than re-deriving the same regexes (DRY, and it keeps the two in lockstep).
import effort_budget as eb

# A session that runs past midnight keeps its START date — see session_date.py. main()
# resolves "today" through it instead of dt.date.today() so gamify doesn't silently roll a
# late-night regeneration onto the next calendar day.
import session_date

# "Which file is problem N" comes from links.solution_files() (keyed by the leading number,
# same walk as links.find_file) — reused rather than re-globbed here so a problem's `file`
# field can never disagree with the `[file]` link the coach pastes in chat.
import links

# Holds (docs/foundations/dsa/mastery/holds.yml) feed each problem's `heldUntil`; the parser
# stays in update_review_dates.py, which applies the same file to the tracker.
import update_review_dates
from update_review_dates import load_holds

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
TRACKER = REPO / "docs/foundations/dsa/mastery/dsa_progress.md"
COVERAGE = REPO / "docs/foundations/dsa/mastery/technique_coverage.md"
TECHNIQUES_YML = REPO / "docs/foundations/dsa/mastery/techniques.yml"
CATALOGUE_YML = REPO / "curriculum/dsa/techniques.yml"
ROADMAP_YML = REPO / "docs/foundations/dsa/mastery/roadmap.yml"
PROBES_README = REPO / "dsa/probes/README.md"
LEETCODE = REPO / "dsa/leetcode"
DRAFT_MARKER = "<!-- status: draft -->"  # the same line build_week.py writes
# The generated contract lives under dashboard/, keeping the repo root uncluttered. The
# website fetches dashboard/progress-summary.json first.
DASHBOARD = REPO / "dashboard"
OUT = DASHBOARD / "progress.json"
SCHEMA = DASHBOARD / "progress.schema.json"
OUT_SUMMARY = DASHBOARD / "progress-summary.json"
# Every archived + live week, for the Overview board's past-week navigation — a SEPARATE
# file, not folded into progress.json/-summary.json, so their own sizes stay small; the
# site fetches this one only when a viewer steps back a week.
OUT_HISTORY = DASHBOARD / "schedule-history.json"
README = REPO / "README.md"
CONFIG = REPO / "cse.config.yml"

SCHEMA_VERSION = 1
SITE = "https://progressiveoverflow.com"

# The summary's studyDays is a ROLLING WINDOW, not the lifetime list: it exists only to draw
# the site's streak-calendar heatmap (~20 weeks visible), and without a cap it grows by one
# entry per practice day forever. The lifetime COUNT already lives in streak.studyDays and
# streak.longest — nothing is lost by trimming the date list itself. 183 days (~26 weeks)
# gives the calendar a little slack beyond what it renders.
SUMMARY_STUDY_DAYS_WINDOW = 183

# The comfort ladder as an ordinal, so a timeline can be plotted as a step chart.
# Keyed by glyph, never by the words blank/shaky/clean/graduated (the config scrape
# hazard — see cse.config.example.yml). 🏆 Retired is terminal, above 🎓.
LEVEL = {"🔴": 0, "🟡": 1, "🟢": 2, "🎓": 3, "🏆": 4}

# graduatedCount's bar: a technique's problem counts once it reaches 🎓 or better.
# UNTRACKED_LEVEL is below LEVEL's own floor (🔴 = 0) so an LC number with no tracker row
# (comfort_by_number has nothing for it) never accidentally counts as graduated.
GRADUATED_LEVEL = LEVEL["🎓"]
UNTRACKED_LEVEL = -1

# Announced fallback — used only when cse.config.yml has no `gamification:` block or
# PyYAML is unavailable. Neutral key names on purpose: none contains the substrings
# blank/shaky/clean/graduated, which a word-keyed config scrape searches for.
DEFAULT_CONFIG = {
    "streak_freeze_max": 2,           # most streak freezes the bank holds
    "streak_freeze_earn_every": 7,    # study days that earn one freeze
    "streak_milestones": [7, 30, 100],
    "trophy_milestones": [1, 10, 25, 50],   # 🎓 + 🏆 combined
    "on_schedule_target": 0.9,        # fraction of active rows not overdue
}


# ── config ────────────────────────────────────────────────────────────────────────

def load_config() -> tuple[dict, bool]:
    """Return (gamification config, used_fallback). Tolerant like effort_budget's."""
    try:
        import yaml  # noqa: PLC0415
        loaded = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
        cfg = loaded.get("gamification")
        if not cfg:
            return dict(DEFAULT_CONFIG), True
        merged = {**DEFAULT_CONFIG, **cfg}
        return merged, False
    except Exception:  # noqa: BLE001 — a missing config is a normal state, not an error
        return dict(DEFAULT_CONFIG), True


# ── retired list + category map (data the tracker table alone does not carry) ───────

RETIRED_ENTRY = re.compile(r"^\s*-\s*(\d+)\.\s*(.+?)\s*(?:—|--)\s*retired\s*(\d{4}-\d{2}-\d{2})",
                           re.MULTILINE)


def parse_retired() -> list[dict]:
    """The `## 🏆 Retired` plain-bullet list at the tail of the tracker.

    Retired rows leave the 7-column table, so parse_rows() never sees them; they are
    the terminal trophy tier and belong in the trophy case. `_None yet._` -> [].
    """
    try:
        text = TRACKER.read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"##\s*🏆\s*Retired(.*)$", text, re.S)
    if not m:
        return []
    return [{"lcNumber": int(n), "title": t.strip(), "retiredOn": d}
            for n, t, d in RETIRED_ENTRY.findall(m.group(1))]


PROBLEM_URL = re.compile(r"\[(\d+)\.[^\]]*\]\((https?://[^)]+)\)")


def problem_urls() -> dict[int, str]:
    """LeetCode number -> its canonical URL, from the tracker's markdown links.

    parse_rows() drops the URL; the dashboard wants it to deep-link each problem, so
    read it here rather than guessing a slug from the (method-suffixed) title.
    """
    try:
        text = TRACKER.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {int(n): url for n, url in PROBLEM_URL.findall(text)}


# The Waiting Room's own 4-column table, scoped from its own heading to the next `## `
# heading. The identical `| Difficulty | Problem | Trigger | Notes |` header can recur
# verbatim on another table further down the same file, and the Knowledge Expansion
# Queue's header is close enough to confuse a header-only match — neither is scanned,
# since the section is bounded before any row regex runs.
WAITING_ROOM_SECTION = re.compile(r"##\s*⏳\s*Waiting Room.*?(?=\n##\s|\Z)", re.S)

# Anchored on the ROW SHAPE, not the header: `| <Easy|Medium|Hard> | [<n>. <title>](<url>) |
# ...`. The cell must START with the link right after the difficulty cell, so a row whose
# link is only PART of the cell (e.g. "Digit DP (technique) — e.g. [<n>. ...]") is
# correctly excluded — such a row credits no technique's `queued:` spec anyway.
WAITING_ROOM_ROW = re.compile(
    r"^\|\s*(Easy|Medium|Hard)\s*\|\s*\[(\d+)\.\s*(.+?)\]\((https?://[^)]+)\)\s*\|",
    re.MULTILINE)


def parse_waiting_room(tracker_text: str) -> dict[int, dict]:
    """The `## ⏳ Waiting Room` table -> {number: {"title", "url", "difficulty"}}.

    A pure function over the tracker's own text (never a second file read — build_payload
    reads TRACKER once and passes the string in here). Scoped to the Waiting Room section
    alone via WAITING_ROOM_SECTION, so a look-alike header elsewhere in the same file is
    never mistaken for a Waiting Room row. No section -> {} (a fresh adopter's tracker).

    A number can appear more than once in the section (two phase-gated variants, or a
    dedicated method-variant row) — the FIRST occurrence in file order wins, so a later
    duplicate is silently ignored rather than overwriting the earlier title/url. Only
    title/url/difficulty are returned; the Notes cell (coaching prose, judge links) never
    reaches the caller — planned_for()'s curation rule (Notes never exported) depends on
    that.
    """
    section = WAITING_ROOM_SECTION.search(tracker_text)
    if not section:
        return {}
    by_number: dict[int, dict] = {}
    for difficulty, number, title, url in WAITING_ROOM_ROW.findall(section.group(0)):
        num = int(number)
        if num not in by_number:
            by_number[num] = {"title": title, "url": url, "difficulty": difficulty}
    return by_number


def category_map() -> dict[int, str]:
    """LeetCode number -> technique folder, scanned from the solution tree.

    The folder name is the technique (the site's algorithm categories mirror these
    exactly), so this is how a problem gets grouped and deep-linked to its visualizer.
    """
    out: dict[int, str] = {}
    if not LEETCODE.is_dir():
        return out
    for path in LEETCODE.rglob("*.py"):
        m = re.match(r"(\d+)_", path.name)
        if m:
            out.setdefault(int(m.group(1)), path.parent.name)
    return out


# ── schedule index: date -> {problem number -> comfort glyph earned that rep} ───────

def _schedule_weeks() -> Iterator[tuple[dt.date, Path]]:
    """Every weekly schedule file (live folder first, then its archive/), each paired
    with its Monday resolved from the filename stamp — the walk `build_schedule_index`,
    `build_workload` and `parse_schedule_history` all need, so it lives in one place.

    A malformed or non-8-digit stamp is silently skipped, same as every caller did
    before this was pulled out. Callers that must never see the same Monday twice (a
    week stamp filed in both the live folder and archive/) resolve that themselves —
    `find_schedule`'s own convention is that the live folder wins, since it is walked
    first here. A fresh adopter has no schedule files at all: yields nothing.
    """
    for folder in (eb.SCHEDULES, eb.SCHEDULES / "archive"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*_schedule.md")):
            stamp = path.name.split("_")[0]
            if len(stamp) != 8 or not stamp.isdigit():
                continue
            try:
                week_start = dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
            except ValueError:
                continue
            yield week_start, path


def build_schedule_index() -> dict[str, dict[int, str]]:
    """Reconstruct the comfort EARNED per rep, per problem, from the weekly schedules.

    The tracker stores only a problem's CURRENT comfort; the per-rep history lives in
    the schedules' End column (`🟢 s1 → 🎓`). Scan every week (live + archive), resolve
    each daily block's real date from the filename stamp, and record the End glyph
    (falling back to Start) for each problem number. A rep date with no schedule (the
    pre-archive era) simply gets no entry — the timeline degrades to an activity dot,
    it is never fabricated.
    """
    index: dict[str, dict[int, str]] = {}
    for week_start, path in _schedule_weeks():
        _scan_week(path, week_start, index)
    return index


def build_workload(rows: list[dict], cfg: dict) -> list[dict]:
    """One entry per scheduled day (live + archive) with a header or priced rows.

    `done`/`built` are priced under the CURRENT cse.config.yml weights, not whatever
    a day was billed at when it was built — so the series is comparable to today's
    numbers, never to what a schedule's own Start column implied at build time. A day
    with no header AND no rows (an older one-row-per-day layout, or a week not yet
    built) contributes no entry rather than a fabricated zero. No schedules -> [].

    `planned` is the header's pinned `· planned N units` figure when a started day carries
    one (rows moved off it leave `built` below the day's original total), else the header's
    stated units.
    """
    workload: list[dict] = []
    for week_start, path in _schedule_weeks():
        lines = path.read_text(encoding="utf-8").splitlines()
        for offset in range(7):
            day = week_start + dt.timedelta(days=offset)
            items, stated = eb.parse_schedule_day(path, day)
            if stated is None and not items:
                continue
            _, pinned = eb.day_header_figures(lines, day)
            p = eb.price_day_items(day, items, rows, cfg)
            workload.append({
                "date": day.isoformat(),
                "planned": pinned if pinned is not None else stated,
                "done": round(p["done"], 1),
                "built": round(p["built"], 1),
                "partial": bool(p["unpriced"] or p["guessed"]),
            })
    workload.sort(key=lambda w: w["date"])
    return workload


def _weekday_lookup(week_start: dt.date) -> dict[tuple[str, str, int], str]:
    return {(d.strftime("%a"), d.strftime("%b"), d.day): d.isoformat()
            for d in (week_start + dt.timedelta(days=o) for o in range(7))}


def _end_glyph(cell: str | None) -> str | None:
    """The first comfort glyph (🔴🟡🟢🎓) in a schedule cell, or None for a glyph-less one
    (`unrated`, `—`, `✅ delivered`, empty). Self-contained (only eb.GLYPH) so it ports
    verbatim wherever a schedule cell needs the same read — the comfort timeline's End
    column here, and the board slice's endComfort in _schedule_item_outcome below."""
    if not cell:
        return None
    match = eb.GLYPH.search(cell)
    return match.group(0) if match else None


def _scan_week(path: Path, week_start: dt.date, index: dict[str, dict[int, str]]) -> None:
    lookup = _weekday_lookup(week_start)
    current: str | None = None
    # (date, num) keys whose glyph came from an End cell: a later row's Start-fallback glyph
    # (a `→` moved row beside the struck original) never overwrites one, in either row order.
    end_sourced: set[tuple[str, int]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        header = eb.DAY_HEADER.search(line)
        if header:
            current = lookup.get((header["wd"], header["mon"], int(header["day"])))
            continue
        if current is None:
            continue
        row = eb.SCHED_ROW.match(line)
        if not row:
            continue
        num = eb.SCHED_NUM.search(row["c1"] or "")
        if not num:
            continue
        end_glyph = _end_glyph(row["c3"])
        glyph = end_glyph or _end_glyph(row["c2"])
        if not glyph:
            continue
        key = (current, int(num.group(1)))
        if key in end_sourced and not end_glyph:
            continue
        if end_glyph:
            end_sourced.add(key)
        index.setdefault(current, {})[key[1]] = glyph


# ── this week's board (the "what do I do today" drill) ──────────────────────────────

# The legend's tag glyphs (see any schedule file's "Tags:" line) — stripped from a title's
# front so the dashboard shows the problem name, not the build-time tag. → is a real arrow,
# not emoji, but it prefixes a moved row the same way, so it's in the same strip set.
_SCHEDULE_TAGS = f"⚠️🔥🆕🎯🎤⚙️🔤{eb.MOVE_ARROWS}"
_LEADING_TAGS = re.compile(rf"^[{re.escape(_SCHEDULE_TAGS)}\s]+")
_LEADING_NUM = re.compile(r"^\d+\.?\s*")
DAY_LABEL = re.compile(r"units\s*—\s*(?P<label>[^|]+)")

# Same legend, named this time (not just stripped): a dashboard row that shows only the
# cleaned title loses WHY a problem is on today's board, so each glyph also becomes a
# machine-readable tag string. Some of these glyphs are two codepoints (a base symbol plus
# a U+FE0F variation selector, e.g. ⚠️/⚙️) — a `for ch in text` scan would split one of
# those in two and match neither half, so _leading_tags() below matches whole tokens.
TAG_PROTECTED = "protected"
TAG_BACKFILL = "backfill"
TAG_NEW = "new"
TAG_PROBE = "probe"
TAG_VARIANT = "variant"
TAG_PRIMER = "primer"
TAG_MOVED = "moved"
TAG_MOCK = "mock"
TAG_BY_GLYPH = {
    "⚠️": TAG_PROTECTED,
    "🔥": TAG_BACKFILL,
    "🆕": TAG_NEW,
    "🎯": TAG_PROBE,
    "🎤": TAG_MOCK,
    "⚙️": TAG_VARIANT,
    "🔤": TAG_PRIMER,
    **{arrow: TAG_MOVED for arrow in eb.MOVE_ARROWS},
}
# Longest-first so a two-codepoint glyph is never accidentally matched by its own leading
# codepoint alone.
_TAG_TOKEN = re.compile("|".join(re.escape(g) for g in sorted(TAG_BY_GLYPH, key=len, reverse=True)))
# A row's tag glyph is sometimes written struck (`~~`) or bolded (`**`) rather than plain
# — older archived weeks do this (e.g. `~~🆕 <n> ...~~`, `~~**🎯 Probe #3**~~`, even
# stacking both markers). `+` so a run of either marker, in either order, is consumed in
# one go.
_LEADING_EMPHASIS = re.compile(r"^(?:~~|\*\*)+")

PULLED_IN_ARROW = "←"

KIND_REP = "rep"
KIND_COMPLEXITY = "complexity"
# KIND_NEW/KIND_PRIMER/KIND_PROBE deliberately don't exist: those three `kind` values are
# always exactly the TAG_NEW/TAG_PRIMER/TAG_PROBE tag word, so reusing the tag constant
# keeps the two in lockstep instead of two literals that could drift apart.


def _leading_tags(cell: str) -> list[str]:
    """The row's build-time tags, read off the Problem cell's leading glyph run (see the
    legend on any schedule file's "Tags:" line) and named via TAG_BY_GLYPH.

    Matches whole glyph tokens left-to-right rather than iterating characters, because a
    two-codepoint glyph (⚠️, ⚙️) would otherwise be split into a base codepoint plus a
    stray U+FE0F variation selector that matches nothing.

    A glyph is sometimes struck or bolded rather than written plain — a row may be
    written `~~🆕 <n> ...~~` (the whole row struck ahead of its tag) or, stacked with
    another tag, `🔥 ~~🎯 ...~~` — so a leading `~~`/`**` run is stripped (_LEADING_EMPHASIS)
    before EVERY glyph match attempt, not just once at the very front of the cell.
    """
    return [TAG_BY_GLYPH[glyph] for glyph in _leading_glyphs(cell)]


def _leading_glyphs(cell: str) -> list[str]:
    """The raw tag glyphs of the Problem cell's leading run, in order (see _leading_tags)."""
    glyphs: list[str] = []
    rest = cell.lstrip()
    while True:
        rest = _LEADING_EMPHASIS.sub("", rest).lstrip()
        token = _TAG_TOKEN.match(rest)
        if not token:
            break
        glyphs.append(token.group(0))
        rest = rest[token.end():].lstrip()
    return glyphs


def _is_pulled_in(cell: str, deferred_to: str | None) -> bool:
    """True for the DESTINATION copy of a pulled-earlier row: a leading `←` with no
    `deferredTo`. The stale origin row (also `←`) carries its destination date, so it is not."""
    return PULLED_IN_ARROW in _leading_glyphs(cell) and deferred_to is None


def _schedule_item_kind(technique: str | None, tags: list[str]) -> str:
    """rep|new|probe|mock|complexity|primer for one schedule item.

    `complexity` is checked BEFORE any tag: the Sunday complexity re-ask rows are both
    🎯-tagged (they're still a cold-call-style probe) AND carry `Complexity` in the
    Technique cell, and Complexity is the more specific fact about what the row actually
    tests. Checking the 🎯 tag first would silently reclassify those rows as an ordinary
    probe and lose that distinction on the dashboard.
    """
    if eb.is_complexity_technique(technique):
        return KIND_COMPLEXITY
    if TAG_MOCK in tags:
        return TAG_MOCK
    if TAG_NEW in tags:
        return TAG_NEW
    if TAG_PRIMER in tags:
        return TAG_PRIMER
    if TAG_PROBE in tags:
        return TAG_PROBE
    return KIND_REP


def _schedule_item_lc_number(cell: str, text: str) -> int | None:
    """lcNumber for one schedule item.

    Delegates to eb.sched_row_number() (which carries the bare-number fallback), so
    pricing and the dashboard parse a bare-number row's number exactly the same way.
    """
    num = eb.sched_row_number(cell, text)
    return int(num) if num else None


_ROW_OWN_LC_URL = re.compile(r"\[LC\]\((https?://[^)]+)\)")
_ROW_OWN_NC_URL = re.compile(r"\[NC\]\((https?://[^)]+)\)")


def _schedule_item_url(cell: str, lc_number: int | None, urls: dict[int, str]) -> str | None:
    """Canonical LeetCode/NeetCode URL for one schedule item, in precedence order:

    1. The row's own `[LC](...)` link straight off the raw cell — a 🆕 row not yet in the
       tracker has no other way to get a URL, and a tracked row's own link is the more
       current fact about THIS occurrence if the two ever disagree.
    2. The tracker join by lcNumber (urls.get, from problem_urls()) — a LeetCode URL.
    3. The row's own `[NC](...)` link, LAST resort only: a NeetCode mirror is used when
       the LC problem is premium-gated, so it is real but weaker evidence than either LC
       source above — the dashboard renders this field as "LeetCode ↗", and an NC url
       must never win over an actual LC one.

    Honest null when none of the three has one.
    """
    lc = _ROW_OWN_LC_URL.search(cell)
    if lc:
        return lc.group(1)
    tracked = urls.get(lc_number) if lc_number else None
    if tracked:
        return tracked
    nc = _ROW_OWN_NC_URL.search(cell)
    return nc.group(1) if nc else None


def _clean_schedule_title(text: str) -> str:
    """Turn a Problem-column cell (already link-unwrapped, `~~`/`**` stripped — see
    eb.parse_schedule_day) into a display title.

    eb.parse_schedule_day stops at what PRICING needs (the text is only ever printed
    in a debug line), so it leaves the tag glyphs, the LC number, and the second link's
    unwrapped anchor text ("· LC") sitting in the string. A dashboard row shows the
    number and comfort separately, so all three would just be noise here: split off
    everything from the first " · " on (that is always the `[LC](...)` link, sometimes
    followed by a build note — neither belongs in the title), then strip a leading tag
    glyph and a leading LC-number prefix.
    """
    first = text.split(" · ")[0]
    first = _LEADING_TAGS.sub("", first)
    first = _LEADING_NUM.sub("", first)
    return re.sub(r"\s+", " ", first).strip()


# The E cell's outcome note (`s0`/`s1`/`s2`/`prov`/`dropped`) is written after the glyph,
# sometimes with a leading arrow (`🟡→dropped`) rather than a space — both are stripped
# before the note is kept.
_NOTE_LEADING_STRIP = re.compile(r"^[\s→—]+")
_WHITESPACE_RUN = re.compile(r"\s+")
# The Next cell counts only when it is NOTHING BUT an ISO date — a free-form note
# ("Sep 14 phase") is not a schedulable review date.
_FULL_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Matches the scheduleItem.endNote schema maxLength (dashboard/progress.schema.json) —
# the real vocabulary (s0/s1/s2/prov/dropped) never approaches this, so a cap is simpler
# than a truncation policy that never actually fires.
END_NOTE_MAX_LENGTH = 16


def _cell_note(cell: str | None, glyph: str | None) -> str | None:
    """The note after a comfort glyph in an S or E cell: the cell with that glyph removed, a
    leading arrow/dash/space run stripped, internal whitespace collapsed to one space,
    lowercased, and capped at END_NOTE_MAX_LENGTH chars. None when there is no glyph or
    nothing after it."""
    if not glyph:
        return None
    remainder = (cell or "").replace(glyph, "", 1)
    remainder = _NOTE_LEADING_STRIP.sub("", remainder)
    remainder = _WHITESPACE_RUN.sub(" ", remainder).strip().lower()
    return remainder[:END_NOTE_MAX_LENGTH] if remainder else None


def _schedule_item_outcome(end_cell: str | None, next_cell: str | None) -> dict:
    """The per-rep outcome earned on a schedule row, for the board slice: `{endComfort,
    endNote, nextReview}` (all None for a glyph-less/blank row).

    endComfort: the first comfort glyph in the E cell — UNLIKE the comfort-timeline read
    (_scan_week), this never falls back to the Start glyph, so the board shows only what
    was actually earned this rep, never the start comfort carried forward as if earned.
    endNote: only set when endComfort is non-null — the E cell with that glyph removed, a
    leading arrow/dash/space run stripped, internal whitespace collapsed to one space,
    lowercased, and capped at END_NOTE_MAX_LENGTH chars. nextReview: the Next cell iff,
    once stripped, it is nothing but an ISO date.
    """
    end_comfort = _end_glyph(end_cell)
    end_note = _cell_note(end_cell, end_comfort)
    stripped_next = (next_cell or "").strip()
    next_review = stripped_next if _FULL_ISO_DATE.fullmatch(stripped_next) else None
    return {"endComfort": end_comfort, "endNote": end_note, "nextReview": next_review}


_CLEAN_GLYPH = "🟢"
_RED_GLYPH = "🔴"
_YELLOW_GLYPH = "🟡"
_STREAK_AFTER_NOTE = {"s0": "s1", "prov": "s1", "s1": "s2", "s2": "s2"}
_MAX_END_STREAK = 2


def derive_end_note(start_comfort, start_note, end_comfort, end_note):
    """The explicit E-cell note wins. When the E cell is a bare 🟢, derive the streak note from the
    start: a clean after 🔴 is the provisional s0; a clean after 🟡 is s1; a clean after 🟢 s0/prov
    is s1; after 🟢 s1/s2 is s2; a 🟢 start with no note, or any other end glyph, derives nothing."""
    if end_note is not None or end_comfort != _CLEAN_GLYPH:
        return end_note
    if start_comfort == _RED_GLYPH:
        return "s0"
    if start_comfort == _YELLOW_GLYPH:
        return "s1"
    if start_comfort == _CLEAN_GLYPH:
        return _STREAK_AFTER_NOTE.get(start_note)
    return None


def end_note_from_tracker(lc_number, day_iso, end_comfort, end_note, streak_by_num):
    """The tracker's streak is authoritative for a bare 🟢 end when the row's day is the problem's
    latest rep: the note is `s<streak>` capped at s2. An explicit/derived note, a non-🟢 end, an
    unknown number, or a day that is not the latest rep leaves `end_note` untouched."""
    if end_note is not None or end_comfort != _CLEAN_GLYPH or lc_number not in streak_by_num:
        return end_note
    streak, last_rep = streak_by_num[lc_number]
    if last_rep != day_iso:
        return end_note
    return f"s{min(streak, _MAX_END_STREAK)}"


def _parse_schedule_day_full(
    path: Path, day: dt.date, difficulty_by_num: dict[int, str],
    streak_by_num: dict[int, tuple[int, str]], urls: dict[int, str],
    files: dict[int, list[Path]] | None = None,
) -> tuple[list[dict], str | None, float | None]:
    """Like eb.parse_schedule_day, but keeps the day's label and each item's technique,
    tags, kind, a display-clean title, the start comfort and its note (startComfort/
    startNote, the S cell's glyph and the text after it), and the per-rep outcome (endComfort/endNote/
    nextReview, from _schedule_item_outcome) — eb's own version only needs the number,
    the start comfort, and whether a row is done, because that is all effort pricing ever
    reads.

    `difficulty_by_num` joins each item's intrinsic Easy/Medium/Hard from the TRACKER (the
    schedule file itself carries no difficulty column) — a number the tracker doesn't have
    yet honestly gets null rather than a guess. `urls` (from problem_urls()) is the
    fallback source for each item's canonical LeetCode URL — see _schedule_item_url,
    which prefers the row's own link first; the site's own AlgorithmMeta.id is a
    shortened route slug, not the LC slug, so it cannot build a correct link itself.
    `files` (from links.solution_files()) gives each item its `file` — the learner's own
    solution path (see solution_path) — null for a row with no number or no file yet.
    """
    wanted = (day.strftime("%a"), day.strftime("%b"), day.day)
    files = files or {}
    items: list[dict] = []
    label: str | None = None
    units: float | None = None
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        header = eb.DAY_HEADER.search(line)
        if header:
            hit = (header["wd"], header["mon"], int(header["day"])) == wanted
            if hit:
                inside = True
                units = float(header["units"]) if header["units"] else None
                lbl = DAY_LABEL.search(line)
                label = lbl["label"].strip() if lbl else None
            elif inside:
                break          # the next day's header ends this day's block
            continue
        if not inside:
            continue
        if not line.lstrip().startswith("|"):
            break              # the daily table ended (see eb.parse_schedule_day's note
                               # on why this guard matters for the LAST day of a week)
        m = eb.SCHED_ROW.match(line)
        if not m:
            continue
        cell = m["c1"]
        if not cell.strip() or set(cell.strip()) <= {"-", ":"}:
            continue           # blank separator row, or a markdown rule
        # text is computed before lcNumber because _schedule_item_lc_number's fallback
        # (a bare-number 🆕 row) reads off this same tag-stripped, link-unwrapped string.
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
        text = re.sub(r"~~|\*\*", "", text)
        lc_number = _schedule_item_lc_number(cell, text)
        start = eb.GLYPH.search(m["c2"] or "")
        start_comfort = start.group(0) if start else None
        technique = (m["c5"] or "").strip() or None
        tags = _leading_tags(cell)
        deferred_to = eb.deferred_to("~~" in cell, m["c4"] or "")
        start_note = _cell_note(m["c2"], start_comfort)
        outcome = _schedule_item_outcome(m["c3"], m["c4"])
        outcome = {**outcome, "endNote": derive_end_note(
            start_comfort, start_note, outcome["endComfort"], outcome["endNote"])}
        outcome = {**outcome, "endNote": end_note_from_tracker(
            lc_number, day.isoformat(), outcome["endComfort"], outcome["endNote"], streak_by_num)}
        items.append({
            # lcNumber is honestly null only when NEITHER eb.SCHED_NUM nor the bare-number
            # fallback finds one (see _schedule_item_lc_number) — the dashboard then omits
            # that row's Visualize/LeetCode deep links.
            "lcNumber": lc_number,
            "title": _clean_schedule_title(text),
            "technique": technique,
            "startComfort": start_comfort,
            "startNote": start_note,
            "difficulty": difficulty_by_num.get(lc_number) if lc_number else None,
            "url": _schedule_item_url(cell, lc_number, urls),
            "file": solution_path(lc_number, files) if lc_number else None,
            "tags": tags,
            "kind": _schedule_item_kind(technique, tags),
            "done": "~~" in cell,
            # Shares eb.deferred_to's rule with parse_sched_line() and remaining.py's
            # skip check -- never re-derived here.
            "deferredTo": deferred_to,
            "pulledIn": _is_pulled_in(cell, deferred_to),
            **outcome,
        })
    return items, label, units


def _credit_pulled_earlier(days: list[dict]) -> list[dict]:
    """A row pulled to an EARLIER day stays on its origin day with `deferredTo` set and
    `done: false`; when the same row (number and title) is done on the `deferredTo` day, the
    origin row counts as done too (the site paints it green, not red). Rows moved to a LATER
    date, or whose earlier copy is not done (or is in another week), are unchanged. Returns
    new day/item dicts; the input is not mutated."""
    done_by_date: dict[str, set[tuple[int, str]]] = {
        day["date"]: {(i["lcNumber"], i["title"]) for i in day["items"]
                      if i["done"] and i["lcNumber"] is not None}
        for day in days
    }

    def credited(item: dict, date: str) -> dict:
        target = item["deferredTo"]
        if item["done"] or not target or target >= date:
            return item
        if (item["lcNumber"], item["title"]) in done_by_date.get(target, set()):
            return {**item, "done": True}
        return item

    return [{**day, "items": [credited(i, day["date"]) for i in day["items"]]} for day in days]


def _parse_week(path: Path, week_start: dt.date, difficulty_by_num: dict[int, str],
                streak_by_num: dict[int, tuple[int, str]], urls: dict[int, str],
                files: dict[int, list[Path]] | None) -> dict:
    """One week's `## Daily Schedule` table -> {weekOf, days:[...]} — the per-week body
    shared by `parse_current_week_schedule` (one week, resolved from `today`) and
    `parse_schedule_history` (every week). Emits ALL 7 days regardless of which ones
    actually have items — see parse_current_week_schedule's own docstring for why the
    board never bakes in a server-side "today"."""
    days: list[dict] = []
    for offset in range(7):
        day_date = week_start + dt.timedelta(days=offset)
        items, label, units = _parse_schedule_day_full(path, day_date, difficulty_by_num,
                                                       streak_by_num, urls, files)
        days.append({
            "date": day_date.isoformat(),
            "weekday": day_date.strftime("%A"),
            "label": label,
            "units": units,
            "items": items,
        })
    week = {"weekOf": week_start.isoformat(), "days": _credit_pulled_earlier(days)}
    return {**week, "isDraft": True} if _is_draft_week(path) else week


def _is_draft_week(path: Path) -> bool:
    """True when the week file carries the build's `<!-- status: draft -->` line."""
    return DRAFT_MARKER in path.read_text(encoding="utf-8").splitlines()


def _difficulty_by_num() -> dict[int, str]:
    """num -> Easy/Medium/Hard, joined from the tracker (a schedule file itself has no
    difficulty column). A number with several tracker rows (method variants) just takes
    the last one parse_rows() yields — difficulty is intrinsic to the LC problem, not the
    method, so they should always agree in practice. Shared by parse_current_week_schedule
    and parse_schedule_history so a tracker read never disagrees between the two."""
    try:
        return {int(r["num"]): r["diff"] for r in eb.parse_rows()}
    except OSError:
        return {}


def _streak_by_num() -> dict[int, tuple[int, str]]:
    """num -> (streak, last rep date ISO), from the tracker rows. A number with several rows
    (method variants) takes the row whose last rep is latest; a row with no rep date is skipped.
    Read next to _difficulty_by_num so the board's end notes agree with the tracker."""
    try:
        rows = eb.parse_rows()
    except OSError:
        return {}
    latest: dict[int, tuple[int, str]] = {}
    for r in rows:
        dates = eb._DATE.findall(r.get("reps") or "")
        if not dates:
            continue
        num = int(r["num"])
        last = max(dates)
        if num not in latest or last >= latest[num][1]:
            latest[num] = (int(r["streak"]), last)
    return latest


def parse_current_week_schedule(today: dt.date, urls: dict[int, str],
                                files: dict[int, list[Path]] | None = None) -> dict | None:
    """The CURRENT week's `## Daily Schedule` table -> {weekOf, days:[...]} — the compact
    slice behind the dashboard's Today's-board drill.

    Emits ALL 7 days; it never bakes a server-side "today" into the payload, because the
    summary is generated on commit but can be VIEWED days later — the client picks its
    own day by comparing its local date against each day's `date`. Fail-soft: no current
    schedule file -> None (the caller adds a warning). `urls` (from problem_urls()) and
    `files` (from links.solution_files()) are threaded through to each item — see
    _parse_schedule_day_full.
    """
    path = eb.find_schedule(today)
    if path is None:
        return None
    try:
        week_start = dt.date(int(path.name[:4]), int(path.name[4:6]), int(path.name[6:8]))
    except (ValueError, IndexError):
        return None
    return _parse_week(path, week_start, _difficulty_by_num(), _streak_by_num(), urls, files)


def parse_schedule_history(urls: dict[int, str],
                           files: dict[int, list[Path]] | None = None) -> list[dict]:
    """Every week from `_schedule_weeks()` whose days hold at least one item -> a list of
    {weekOf, days:[...]} (the same per-week shape `parse_current_week_schedule` emits),
    sorted by `weekOf` ascending — the data behind the dashboard's past-week navigation.

    A week whose Daily Schedule table parses empty (an older Morning/Evening Warmup +
    Slot layout `_parse_schedule_day_full` cannot read) is skipped rather than emitted as
    seven empty days — the whole point is "was there really a schedule this week", and an
    empty week answers no. No schedule files at all (a fresh adopter) -> [].

    A Monday whose stamp is filed in BOTH the live folder and archive/ is emitted once,
    keeping whichever occurrence `_schedule_weeks()` yields first — the live folder,
    since it is walked first — matching `eb.find_schedule`'s own live-wins precedence for
    the same stamp.
    """
    difficulty_by_num = _difficulty_by_num()
    streak_by_num = _streak_by_num()
    weeks_by_start: dict[dt.date, dict] = {}
    for week_start, path in _schedule_weeks():
        if week_start in weeks_by_start:
            continue
        week = _parse_week(path, week_start, difficulty_by_num, streak_by_num, urls, files)
        if any(day["items"] for day in week["days"]):
            weeks_by_start[week_start] = week
    return sorted(weeks_by_start.values(), key=lambda w: w["weekOf"])


# ── streak (SR-honest: showing up when due, with a rest-day allowance) ──────────────

def study_days(rows: list[dict]) -> list[dt.date]:
    seen: set[dt.date] = set()
    for r in rows:
        for d in eb._DATE.findall(r.get("reps") or ""):
            try:
                seen.add(dt.date.fromisoformat(d))
            except ValueError:
                continue
    return sorted(seen)


def _missed_days(prev: dt.date, cur: dt.date) -> list[dt.date]:
    """The calendar days strictly between two dates."""
    return [prev + dt.timedelta(days=n) for n in range(1, (cur - prev).days)]


def compute_streak(days: list[dt.date], freeze_max: int, earn_every: int,
                   today: dt.date) -> dict:
    """Current + longest study-day streak, with a spendable streak-freeze bank.

    A streak counts DISTINCT days practiced. The bank starts full at `freeze_max`; every
    `earn_every`-th study day (counted over the whole history) earns one freeze, never
    past the max. Each missed calendar day between two study days spends one freeze and
    keeps the run going without adding to it (the day goes to `frozenDays`); a gap longer
    than the bank breaks the run and empties the bank. Today is not missed until it is
    over, so the trailing misses are `(today - last).days - 1`: `current` is the run while
    the bank covers them, else 0. `freezes` is the bank right after the last study day;
    `freezesLeft` is what remains once the trailing misses are spent.
    """
    bank, run, longest = freeze_max, 0, 0
    frozen: list[dt.date] = []
    for index, day in enumerate(days):
        missed = _missed_days(days[index - 1], day) if index else []
        if missed and len(missed) <= bank:
            bank -= len(missed)
            frozen = frozen + missed
        elif missed:
            run, bank = 0, 0
        run += 1
        longest = max(longest, run)
        if (index + 1) % earn_every == 0:
            bank = min(freeze_max, bank + 1)
    if not days:
        return {"current": 0, "longest": 0, "lastStudyDay": None, "studyDays": 0,
                "freezes": bank, "freezesLeft": bank, "freezeMax": freeze_max,
                "frozenDays": []}
    trailing = _missed_days(days[-1], today)
    is_live = len(trailing) <= bank
    return {"current": run if is_live else 0, "longest": longest,
            "lastStudyDay": days[-1].isoformat(), "studyDays": len(days),
            "freezes": bank, "freezesLeft": bank - len(trailing) if is_live else 0,
            "freezeMax": freeze_max,
            "frozenDays": [d.isoformat() for d in (frozen + trailing if is_live else frozen)]}


# ── coverage header ─────────────────────────────────────────────────────────────────

COVERAGE_LINE = re.compile(
    r"\*\*(\d+)/(\d+)\*\*\s*techniques started.*?\*\*(\d+)\*\*\s*with no.*?"
    r"\*\*(\d+)\*\*\s*thin.*?\*\*(\d+)\*\*\s*unqueued variant", re.S)


def parse_coverage() -> dict | None:
    try:
        m = COVERAGE_LINE.search(COVERAGE.read_text(encoding="utf-8"))
    except OSError:
        return None
    if not m:
        return None
    started, total, no_green, thin, variant = (int(g) for g in m.groups())
    return {"total": total, "started": started, "noGreen": no_green,
            "thin": thin, "variantGaps": variant}


# ── per-technique table (the "which techniques?" drill behind the coverage header) ──

COVERAGE_SECTION = re.compile(r"##\s*Coverage(.*?)(?:\n##\s|\Z)", re.S)
TABLE_ROW = re.compile(r"^\|(.+)\|\s*$", re.MULTILINE)
CELL_NUMBER = re.compile(r"\d+")
PARENTHETICAL = re.compile(r"\((.*?)\)")
COMFORT_GLYPH = re.compile(r"[🔴🟡🟢🎓🏆]")
# The Min cell's floor+unclean breakdown, e.g. `8 (4+4)` — technique_coverage.py's
# `_min_cell()`. Absent on an older report written before that breakdown existed; see
# parse_techniques()'s fallback below.
MIN_CELL_BREAKDOWN = re.compile(r"\((\d+)\+(\d+)\)")

# The `## Coverage` table's fixed schema: Technique, Family, Tier, Min, Problems, Best,
# 🟢, Variants, Gaps. Not a cse.config.yml value — it's technique_coverage.py's own output
# shape, not a tuned threshold.
COVERAGE_TABLE_COLUMNS = 9

# The Variants cell's UNQUEUED-GAP rendering (technique_coverage.py's render(), the
# `variants` join): a variant with zero rows and no `queued:` entry prints
# `**<name> ×0**`; a queued gap prints `~~<name>~~ *(queued: ...)*` (single stars, so it
# never collides with this pattern); an exercised variant prints `<name> ×N` (N >= 1, no
# stars at all). Non-greedy up to " ×0**" so a name containing its own parentheses or a
# slash is still captured whole.
UNTRIED_VARIANT = re.compile(r"\*\*(.+?) ×0\*\*")


def _parse_untried_variants(variants_cell: str) -> list[str]:
    """The Variants cell's `**<name> ×0**` names — a declared method variant never once
    exercised AND not sitting in any queue (`untriedVariations`). A queued gap
    (`~~name~~ *(queued: ...)*`) is deliberately excluded — it's a known gap with a fill
    already picked, not something to name as missing. `—` (no variants declared)
    yields []."""
    return UNTRIED_VARIANT.findall(variants_cell or "")


def _fallback_min_problems(warnings: list[str]) -> int:
    """Only reached when a Min cell has no integer at all — should not happen with a
    freshly generated report. Reads `cse.config.yml`'s `coverage_threshold.floor_min`
    rather than a hard-coded literal, so this rare fallback tracks the same knob as
    everywhere else it's used (single source of truth). Fail-soft to 1, announced via
    `warnings`, when the file or key is missing."""
    try:
        import yaml  # noqa: PLC0415
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — a missing/unparsable config is a normal fail-soft state
        cfg = {}
    floor_min = (cfg.get("coverage_threshold") or {}).get("floor_min")
    if floor_min is None:
        warnings.append(
            "cse.config.yml has no coverage_threshold.floor_min — an unparseable Min "
            "cell fell back to a built-in default of 1.")
        return 1
    return floor_min


def parse_techniques(warnings: list[str]) -> list[dict]:
    """The `## Coverage` per-technique table -> one dict per row.

    Reuses parse_coverage()'s file-read + regex style. The Problems cell carries both a
    count and a parenthetical of LC numbers, and can carry `*+Nv*` (extra untracked variant
    reps) or `—` (no problems yet) — handled by taking the FIRST integer in the cell as the
    count and only the integers INSIDE the parens as the problem list, so those extra tokens
    never get mistaken for a problem number. Fail-soft: an unreadable/missing table -> [].

    The HEADER row's own cell count is checked against COVERAGE_TABLE_COLUMNS before any
    row is parsed: an older technique_coverage.py emitting a different column count would
    otherwise have every row silently skipped by the per-row count check below, losing the
    whole table with no signal. That mismatch pushes one message onto `warnings` (mutated
    in place, like build_payload's own local list) and returns [] rather than a partial,
    possibly-misaligned table.

    `tier` is technique_coverage.py's Tier column — "core" for every pre-tiering
    technique (the column simply never reads empty). `started` is derived from the Gaps
    cell's `*not started*` marker rather than re-deriving it from problemCount, so it stays
    byte-for-byte in lockstep with `is_started` (the exact gate that keeps these techniques
    out of the Action list) even if that check's definition ever changes.

    `minProblems` is the Min column — the per-technique coverage bar, computed by
    `technique_coverage.py` per `cse.config.yml`'s `coverage_threshold` formula (or an
    explicit override in `techniques.yml`) — that makes "thin" self-explanatory as
    `problemCount / minProblems` instead of a bare, unexplained label. The Min cell also
    carries that threshold's `(floor+unclean)` breakdown, read out here as
    `coverageFloor`/`uncleanCount` — additive fields alongside `minProblems`, both falling
    back to `minProblems`/0 on an older report written before the breakdown existed.
    """
    try:
        text = COVERAGE.read_text(encoding="utf-8")
    except OSError:
        return []
    section = COVERAGE_SECTION.search(text)
    if not section:
        return []

    rows = TABLE_ROW.findall(section.group(1))
    if not rows:
        return []
    header_columns = len(rows[0].split("|"))
    if header_columns != COVERAGE_TABLE_COLUMNS:
        warnings.append(
            f"technique_coverage.md Coverage table has {header_columns} columns, "
            f"expected {COVERAGE_TABLE_COLUMNS} — regenerate it with "
            "scripts/technique_coverage.py; techniques omitted.")
        return []

    out: list[dict] = []
    for line in rows:
        cells = [c.strip() for c in line.split("|")]
        if len(cells) != COVERAGE_TABLE_COLUMNS:
            continue
        (name, family, tier, min_cell, problems_cell, best_cell, green_cell,
         variants_cell, gaps_cell) = cells
        if name in ("Technique", "") or set(name) <= {"-", ":"}:
            continue  # header / markdown separator row, not data

        min_problems_match = CELL_NUMBER.search(min_cell)
        min_problems = (int(min_problems_match.group(0)) if min_problems_match
                        else _fallback_min_problems(warnings))
        # The `(floor+unclean)` breakdown is additive — an older report written before it
        # existed has a bare integer Min cell, so it falls back to crediting the whole
        # threshold to the floor with zero unclean, rather than leaving these two fields
        # unset.
        breakdown = MIN_CELL_BREAKDOWN.search(min_cell)
        coverage_floor = int(breakdown.group(1)) if breakdown else min_problems
        unclean_count = int(breakdown.group(2)) if breakdown else 0
        counts = CELL_NUMBER.findall(problems_cell)
        problem_count = int(counts[0]) if counts else 0
        paren = PARENTHETICAL.search(problems_cell)
        problems = [int(n) for n in CELL_NUMBER.findall(paren.group(1))] if paren else []
        best = COMFORT_GLYPH.search(best_cell)

        out.append({
            "name": name,
            "family": family,
            "tier": tier or "core",
            "started": "not started" not in gaps_cell,
            "minProblems": min_problems,
            "coverageFloor": coverage_floor,
            "uncleanCount": unclean_count,
            "problemCount": problem_count,
            "problems": problems,
            "bestComfort": best.group(0) if best else None,
            "hasGreen": "✅" in green_cell,
            "thin": "thin" in gaps_cell,
            "hasVariantGap": "variant" in gaps_cell,
            # Internal only — enrich_techniques() reads this to derive
            # `untriedVariations` and strips it before the row is emitted; never part of
            # the public progress.json technique schema.
            "_variantsCell": variants_cell,
        })
    return out


# ── technique graph + graduation counts (builds_on / graduatedCount) ────────────────

def load_roadmap(warnings: list[str], has_tracker_rows: bool = True) -> dict[int, dict]:
    """roadmap.yml's `problems:` list -> {number: {"title", "url", "difficulty"}} — the
    fallback title/url/difficulty source for a declared-but-untracked problem with no
    Waiting Room row (see planned_for()). Fail-soft, same style as load_config()/
    load_technique_entries(): a missing file or missing PyYAML degrades to {} with one
    warning rather than raising out of the hook. A fresh adopter has no roadmap.yml until
    the first weekly build writes one, so {} here is the normal day-one state."""
    try:
        import yaml  # noqa: PLC0415
        config = yaml.safe_load(ROADMAP_YML.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — a missing/unparsable file is a normal fail-soft state
        if has_tracker_rows:  # a fresh checkout has no roadmap yet and nothing to omit it from
            warnings.append(
                "roadmap.yml not readable — catalog title/url/difficulty omitted for every "
                "declared-untracked problem.")
        return {}
    return {p["number"]: {"title": p.get("title"), "url": p.get("url"),
                          "difficulty": p.get("difficulty")}
            for p in config.get("problems") or [] if p.get("number") is not None}


def load_technique_entries(warnings: list[str]) -> list[dict]:
    """techniques.yml's `techniques:` list, verbatim (each entry's `name` + `builds_on`
    among other keys `parse_techniques()` doesn't carry). Fail-soft to [] with a warning —
    same style as load_config(): a missing file or missing PyYAML degrades gracefully
    rather than raising out of the hook."""
    try:
        import curriculum  # noqa: PLC0415
        config = curriculum.load_techniques(CATALOGUE_YML, TECHNIQUES_YML)
    except Exception:  # noqa: BLE001 — a missing/unparsable file is a normal fail-soft state
        warnings.append(
            "techniques.yml not readable — buildsOn omitted for every technique.")
        return []
    return config.get("techniques") or []


def _resolve_builds_on(name: str, raw_by_name: dict[str, list[str]],
                       known_names: set[str], warnings: list[str]) -> list[str]:
    """One technique's raw `builds_on` list -> the edges that survive validation: an
    unknown name or a self-edge is dropped, each with one warning naming the offender.
    Cycle-breaking is a separate pass (`_break_cycles`) — it needs the whole graph, not
    one row at a time."""
    resolved = []
    for dep in raw_by_name.get(name) or []:
        if dep == name:
            warnings.append(f"techniques.yml: {name!r} lists itself in builds_on — dropped.")
            continue
        if dep not in known_names:
            warnings.append(
                f"techniques.yml: {name!r} builds_on unknown technique {dep!r} — dropped.")
            continue
        resolved.append(dep)
    return resolved


def _break_cycles(graph: dict[str, list[str]], order: list[str],
                  warnings: list[str]) -> dict[str, list[str]]:
    """DFS over `graph` in `order` (techniques.yml's own file order, so this is
    deterministic run to run). A back edge to a node still GRAY (on the current DFS
    stack) closes a cycle; only that one edge is dropped, with a warning naming it — the
    rest of both nodes' builds_on survives. Returns a NEW graph (pure, no mutation of the
    input dict's lists)."""
    cleaned = {name: list(deps) for name, deps in graph.items()}
    white, gray, black = 0, 1, 2
    color = {name: white for name in graph}

    def visit(name: str) -> None:
        color[name] = gray
        for dep in list(cleaned.get(name, [])):
            if color.get(dep) == gray:
                cleaned[name].remove(dep)
                warnings.append(
                    f"techniques.yml: builds_on cycle through {name!r} -> {dep!r} — "
                    "that edge dropped.")
            elif color.get(dep) == white:
                visit(dep)
        color[name] = black

    for name in order:
        if color.get(name) == white:
            visit(name)
    return cleaned


def _comfort_by_number(problems: list[dict], retired: list[dict]) -> dict[int, str]:
    """LC number -> its best (highest LEVEL) comfort glyph, from data build_payload already
    parsed once — never a second read of the tracker. A number can carry several tracker
    rows (method variants), so the highest LEVEL among them wins. Retired problems left
    the 7-column table (parse_retired()'s own docstring — parse_rows() never sees them), so
    they never appear in `problems`; each is 🏆, terminal above 🎓.

    Fail-soft like build_problems() itself (LEVEL.get(r["comfort"]), never LEVEL[...]): a
    tracker comfort cell outside LEVEL's five glyphs is never stored — its UNTRACKED_LEVEL
    can't outrank a real glyph already recorded, and if it's the only row for that number,
    UNTRACKED_LEVEL == UNTRACKED_LEVEL so nothing is written at all. `build_payload` must
    never raise on a malformed cell."""
    best: dict[int, str] = {}
    for p in problems:
        num, glyph = p["lcNumber"], p["comfort"]
        if LEVEL.get(glyph, UNTRACKED_LEVEL) > LEVEL.get(best.get(num), UNTRACKED_LEVEL):
            best[num] = glyph
    for r in retired:
        num = r["lcNumber"]
        if LEVEL["🏆"] > LEVEL.get(best.get(num), UNTRACKED_LEVEL):
            best[num] = "🏆"
    return best


UNRESOLVED_PREVIEW_COUNT = 3  # numbers named in the aggregated unresolved-planned warning


def _spec_source(specs: list[dict]) -> dict | None:
    """{title, url, difficulty} from the first of one number's specs carrying a `title`."""
    for spec in specs:
        if spec.get("title"):
            return {"title": spec["title"], "url": spec.get("url"),
                    "difficulty": spec.get("difficulty")}
    return None


def _planned_source(number: int, specs: list[dict], waiting_room: dict[int, dict],
                    catalog: dict[int, dict]) -> dict | None:
    return waiting_room.get(number) or catalog.get(number) or _spec_source(specs)


def _unresolved_warning(planned: list[dict]) -> list[str]:
    """One warning line for every distinct planned number whose entry came out untitled
    (no Waiting Room row, no roadmap entry, no titled spec — naming the first few), or []
    when all resolve."""
    numbers = list(dict.fromkeys(p["lcNumber"] for p in planned if p["title"] is None))
    if not numbers:
        return []
    first = ", ".join(str(n) for n in numbers[:UNRESOLVED_PREVIEW_COUNT])
    return [f"techniques.yml: {len(numbers)} declared problems have no Waiting Room row or "
            f"roadmap.yml entry — planned entries emitted with nulls (first: {first})."]


def _planned_entry(number: int, specs: list[dict], waiting_room: dict[int, dict],
                   catalog: dict[int, dict]) -> dict:
    """One `planned[]` row: title/url/difficulty resolve from `waiting_room` first, then
    `catalog` (roadmap.yml), then the first spec of that number carrying a `title`, and
    honestly null when none has it — never guessed (enrich_techniques aggregates the nulls
    into one warning)."""
    trigger = _first_trigger(specs)
    source = _planned_source(number, specs, waiting_room, catalog)
    if source is None:
        return {"lcNumber": number, "title": None, "url": None, "difficulty": None,
                "trigger": trigger}
    return {"lcNumber": number, "title": source["title"], "url": source["url"],
            "difficulty": source["difficulty"], "trigger": trigger}


SPEC_PLANNED_FIELD = "planned"  # techniques.yml `problems:` spec key; false opts a
                                # declared-untracked number out of the dashboard's
                                # `planned` list (a recognition probe, credited if it
                                # ever earns a tracker row but never part of the plan).


def _first_trigger(specs: list[dict]) -> str | None:
    """First non-null `queued` across one number's specs, in file order — a trigger
    declared on a later row for the same number is never lost behind an earlier,
    unqueued row."""
    for spec in specs:
        trigger = spec.get("queued")
        if trigger is not None:
            return trigger
    return None


def _all_opted_out(specs: list[dict]) -> bool:
    """True when EVERY spec for this number explicitly opts out via
    `planned: false` — a single ordinary (or missing-key) spec among several keeps the
    number in `planned`."""
    return all(spec.get(SPEC_PLANNED_FIELD) is False for spec in specs)


def planned_for(entry: dict | None, tracked_numbers: set[int],
                waiting_room: dict[int, dict], catalog: dict[int, dict]) -> list[dict]:
    """One techniques.yml entry's `problems:` specs -> its `planned` list: every DISTINCT
    number declared under this entry that has NOT yet earned a tracker row and is not
    opted out via `planned: false` (see `_all_opted_out`), in file order — not only specs
    carrying a `queued` trigger (that key is optional on an untracked spec; see
    techniques.yml's own schema comment). A number graduates out of `planned` on its own
    the moment it is rated (into `problems` above) — `tracked_numbers` is
    comfort_by_number's own keys, so no second edit is needed here when that happens.

    `entry` is None for a coverage-table row with no matching techniques.yml entry (the
    same silent-[] case enrich_techniques already gives buildsOn) — returns [].

    Deduped BY NUMBER within the entry: an entry may carry two `problems:` rows per number
    (one per `method:`), and an untracked number must appear in `planned` once per problem,
    not once per row — `_first_trigger` picks the first non-null `queued` across that
    number's rows, and `_all_opted_out` requires EVERY row for the number to carry
    `planned: false` before the number is excluded.

    Title/url/difficulty resolve via `_planned_entry` — the Waiting Room table first, then
    `catalog` (roadmap.yml's declared-problem catalog), then the first of that number's
    specs carrying a `title`, and honestly null when none has it (enrich_techniques reports
    those as one warning).
    """
    if not entry:
        return []
    specs_by_number: dict[int, list[dict]] = {}
    for spec in entry.get("problems") or []:
        number = spec.get("number")
        if number is None or number in tracked_numbers:
            continue
        specs_by_number.setdefault(number, []).append(spec)
    return [_planned_entry(number, specs, waiting_room, catalog)
            for number, specs in specs_by_number.items()
            if not _all_opted_out(specs)]


_TITLE_METHOD = re.compile(r"\(([^)]+)\)\s*$")  # last `(…)` group, as technique_coverage's TITLE_RE


def _problem_index(problems: list[dict]) -> dict[int, list[tuple[dict, str | None]]]:
    """LC number -> its tracker rows (build_problems() entries) paired with each title's
    trailing-parenthetical method (None when absent). Built once per enrich_techniques
    call so no technique row rescans `problems`."""
    index: dict[int, list[tuple[dict, str | None]]] = {}
    for p in problems:
        match = _TITLE_METHOD.search(p["title"])
        method = match.group(1).strip() if match else None
        index.setdefault(p["lcNumber"], []).append((p, method))
    return index


def _credited_rows(row: dict, entry: dict | None,
                   index: dict[int, list[tuple[dict, str | None]]]) -> list[dict]:
    """The tracker rows (`build_problems()` entries) a technique credits, in `row["problems"]`
    order. Mirrors technique_coverage._matches(): a techniques.yml spec for the number with
    no `method` credits every row of that number; with a `method` it credits only rows whose
    title's trailing parenthetical equals it. A number with no spec (no entry, or an entry
    that does not declare it) credits every row of the number."""
    specs_by_number: dict[int, list[dict]] = {}
    for spec in (entry or {}).get("problems") or []:
        specs_by_number.setdefault(spec.get("number"), []).append(spec)

    def is_credited(num: int, method: str | None) -> bool:
        specs = specs_by_number.get(num)
        if not specs:
            return True
        return any(s.get("method") is None or s["method"] == method for s in specs)

    return [p for num in row["problems"] for p, method in index.get(num, [])
            if is_credited(num, method)]


def _enrich_row(row: dict, builds_on: list[str], graduated: int, planned: list[dict],
                credited: list[dict], order: int | None = None) -> dict:
    """One enriched technique row: `row` (parse_techniques()'s output) plus `buildsOn`/
    `graduatedCount`/`rows`/`planned`/`plannedTotal`/`untriedVariations` — never `row`'s own
    internal `_variantsCell` (dropped here; see parse_techniques()'s docstring for why it
    exists at all). `rows` names the tracker rows the technique credits. `order` is the
    entry's index in techniques.yml (its deliberate study order); absent for a row with no
    entry."""
    public_row = {k: v for k, v in row.items() if k != "_variantsCell"}
    return {**public_row,
            **({} if order is None else {"order": order}),
            "buildsOn": builds_on,
            "graduatedCount": graduated,
            "rows": [{"lcNumber": p["lcNumber"], "title": p["title"]} for p in credited],
            "planned": planned,
            "plannedTotal": row["problemCount"] + len(planned),
            "untriedVariations": _parse_untried_variants(row.get("_variantsCell", ""))}


def enrich_techniques(rows: list[dict], yaml_entries: list[dict],
                      comfort_by_number: dict[int, str],
                      waiting_room: dict[int, dict],
                      warnings: list[str],
                      catalog: dict[int, dict] | None = None,
                      problems: list[dict] | None = None,
                      has_tracker_rows: bool = True) -> list[dict]:
    """`parse_techniques()`'s rows -> new dicts (no mutation) adding `buildsOn`,
    `graduatedCount`, `rows`, `planned`, `plannedTotal` and `untriedVariations`.

    `rows` lists the tracker rows (`{lcNumber, title}`) the technique credits, from `problems`
    (build_problems()'s output) via `_credited_rows` — the number+method join
    technique_coverage uses. `problems` defaults to [] (no rows credited).

    `buildsOn` is techniques.yml's own `builds_on` for that row's name, validated (an
    unknown name or a self-edge dropped, each warned) and cycle-broken (one back edge
    dropped per cycle, warned) against the same file's declared names — never against
    `rows`, since a coverage-table name with no matching YAML entry gets `[]` rather than
    silently reusing a stale graph.

    `graduatedCount` counts the credited tracker rows (`rows`) whose comfort has reached
    GRADUATED_LEVEL (🎓) or better, plus the row's retired (🏆, no tracker row) numbers
    read from `comfort_by_number` — data build_payload already holds, never a second read
    of the tracker.

    `planned` is planned_for()'s own list for this row's techniques.yml entry (matched by
    name; a coverage row with no YAML entry gets []): every declared problem not yet in
    comfort_by_number, resolved against `waiting_room` first and `catalog` (roadmap.yml,
    via load_roadmap() — defaults to {} when the caller has none) second. Present on
    every row, started or not — an empty list, never an absent key.

    `plannedTotal` (y = done + planned) is `problemCount + len(planned)` — exported so
    the site never re-derives it from an older-contract payload's absent field (see the
    site's own documented fallback, `problemCount + (planned?.length ?? 0)`).

    `untriedVariations` is `_parse_untried_variants()` read off the row's own (internal,
    stripped-before-return) `_variantsCell`.

    Planned numbers with no Waiting Room row and no catalog entry are reported as ONE
    warning (the first few named); `has_tracker_rows=False` (a fresh checkout, nothing to
    reconcile yet) silences it.
    """
    catalog = catalog or {}
    known_names = {e["name"] for e in yaml_entries if e.get("name")}
    order = [e["name"] for e in yaml_entries if e.get("name")]
    raw_by_name = {e["name"]: e.get("builds_on") or []
                   for e in yaml_entries if e.get("name")}
    entry_by_name = {e["name"]: e for e in yaml_entries if e.get("name")}
    order_by_name = {e["name"]: i for i, e in enumerate(yaml_entries) if e.get("name")}
    graph = {name: _resolve_builds_on(name, raw_by_name, known_names, warnings)
             for name in order}
    graph = _break_cycles(graph, order, warnings)
    tracked_numbers = set(comfort_by_number)
    index = _problem_index(problems or [])

    enriched = []
    all_planned: list[dict] = []
    for row in rows:
        entry = entry_by_name.get(row["name"])
        credited = _credited_rows(row, entry, index)
        # Retired (🏆) numbers have no tracker row, so they credit by number alone.
        retired_count = sum(1 for num in row["problems"]
                            if num not in index and comfort_by_number.get(num) == "🏆")
        graduated = retired_count + sum(
            1 for p in credited if LEVEL.get(p["comfort"], UNTRACKED_LEVEL) >= GRADUATED_LEVEL)
        planned = planned_for(entry, tracked_numbers, waiting_room, catalog)
        all_planned.extend(planned)
        enriched.append(_enrich_row(row, graph.get(row["name"], []), graduated, planned,
                                    credited, order_by_name.get(row["name"])))
    if has_tracker_rows:
        warnings.extend(_unresolved_warning(all_planned))
    return enriched


# ── recognition probes (the "is the pool still teaching?" diagnostic) ───────────────

PROBE_SECTION = re.compile(r"##\s*📒\s*Probe log(.*?)(?:\n##\s|\Z)", re.S)
PROBE_PROBLEM = re.compile(r"^(\d+)\s+(.+)$")


def _probe_files() -> dict[int, str]:
    """num -> repo-relative POSIX path of each probe's own `<n>_<snake>.py` beside the
    Probe log README. One glob for the whole directory, read once by parse_probes."""
    found: dict[int, str] = {}
    for path in sorted(PROBES_README.parent.glob("*.py")):
        m = re.match(r"(\d+)_", path.name)
        if m and path.is_relative_to(REPO):
            found.setdefault(int(m.group(1)), path.relative_to(REPO).as_posix())
    return found


def parse_probes(urls: dict[int, str],
                 difficulty_by_num: dict[int, str] | None = None,
                 files: dict[int, list[Path]] | None = None) -> dict | None:
    """The `dsa/probes/README.md` Probe log table -> {total, cleanRate, items:[...]}.

    Reuses TABLE_ROW/COMFORT_GLYPH (parse_techniques()'s style). Each probe is a cold,
    label-stripped, disposable rep — a clean 🟢 creates no tracker row (see the README's
    own docstring), so the tracker's own numbers never see it; this table is the ONLY
    place it's counted. `result` takes the FIRST comfort glyph in the Result cell — a row
    that later converted (`🔴 → 🟡 (re-rep ...)`) is scored on what the COLD call
    actually was, not its eventual outcome. `urls` (from problem_urls()) joins each item's
    canonical LeetCode URL — see problem_urls()'s docstring for why the site can't derive
    this itself. `difficulty_by_num` (from _difficulty_by_num(), read once by the caller)
    fills any item whose README `Difficulty` cell is blank or absent (the cell wins); None
    when neither has it — a clean 🟢 probe earns no tracker row. `file` is the probe's own
    file under dsa/probes/ if it has one, else the tracker solution file from `files`
    (solution_path), else None.

    Fail-soft, but the TWO empty cases mean different things and must not collapse to the
    same result: a missing file or a missing `## 📒 Probe log` section is something wrong
    (-> None, and main() warns) — but a fresh adopter checkout has the file and the
    section with a header row and NO data rows yet, which is not wrong at all, just day
    one (-> the zero payload below, no warning). Warning on day one would be the first
    thing a new user sees from an otherwise-honest tool.
    """
    try:
        text = PROBES_README.read_text(encoding="utf-8")
    except OSError:
        return None
    section = PROBE_SECTION.search(text)
    if not section:
        return None

    difficulties = difficulty_by_num or {}
    probe_files = _probe_files()
    tracker_files = files or {}
    difficulty_col: int | None = None  # found by header name, so older 6-column layouts parse
    items: list[dict] = []
    for line in TABLE_ROW.findall(section.group(1)):
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 6:
            continue
        num, date, problem_cell, technique, result_cell = cells[:5]
        if num == "#":
            difficulty_col = cells.index("Difficulty") if "Difficulty" in cells else None
            continue
        if num == "" or set(num) <= {"-", ":"}:
            continue  # separator row, not data
        logged = cells[difficulty_col] if difficulty_col is not None and difficulty_col < len(cells) else ""

        m = PROBE_PROBLEM.match(problem_cell)
        glyph = COMFORT_GLYPH.search(result_cell)
        lc_number = int(m.group(1)) if m else None
        items.append({
            "date": date,
            "lcNumber": lc_number,
            "title": m.group(2).strip() if m else problem_cell,
            "technique": technique,
            "result": glyph.group(0) if glyph else None,
            "url": urls.get(lc_number) if lc_number else None,
            "difficulty": logged or (difficulties.get(lc_number) if lc_number else None),
            "file": (probe_files.get(lc_number) or solution_path(lc_number, tracker_files))
                    if lc_number else None,
        })

    if not items:
        # File and section both present; the table just has no data rows yet (a fresh
        # adopter checkout). That's not an error — see the docstring — so it gets the
        # zero payload, not None (which main() would report as a warning).
        return {"total": 0, "cleanRate": 0.0, "items": []}
    total = len(items)
    clean = sum(1 for it in items if it["result"] == "🟢")
    return {"total": total, "cleanRate": clean / total, "items": items}


# ── the build ───────────────────────────────────────────────────────────────────────

def solution_path(num: int, files: dict[int, list[Path]],
                  warnings: list[str] | None = None) -> str | None:
    """Repo-relative POSIX path of `num`'s solution file (from links.solution_files()),
    or None when no file exists under the configured roots. A PATH, never code —
    progress.json stays code-free; the site turns it into a `blob/<branch>/<path>` link so
    every row can point at the learner's own file even before any curated showcase entry
    exists.

    A twin (two files for one number) takes the first sorted path — the same rule as
    `links.find_file` — and records one warning per number so the choice is never silent.
    The map lookup is O(1); the glob ran once, in build_payload."""
    paths = files.get(num) or []
    if not paths:
        return None
    if len(paths) > 1 and warnings is not None:
        joined = ", ".join(p.relative_to(REPO).as_posix() for p in paths)
        warnings.append(f"{num}: {len(paths)} solution files ({joined}) — `file` uses the first.")
    return paths[0].relative_to(REPO).as_posix()


def build_problems(rows: list[dict], sched: dict[str, dict[int, str]],
                   cats: dict[int, str], urls: dict[int, str],
                   files: dict[int, list[Path]] | None = None,
                   warnings: list[str] | None = None,
                   holds: dict[str, str] | None = None) -> list[dict]:
    # The schedule index is keyed by problem NUMBER, but a number can carry several rows
    # (different methods). A rep date listed by exactly one row of the number belongs to that
    # row, so it takes the glyph; a date listed by two or more rows cannot be assigned to one,
    # so attaching the glyph would FABRICATE a timeline — it degrades to an activity dot
    # (null). The final point is anchored to each row's own authoritative current comfort.
    shared = _shared_rep_dates(rows)
    files = files or {}
    holds = holds or {}
    # One twin warning per NUMBER, not per row: a multi-variant number has several tracker
    # rows but only one file lookup worth reporting.
    twin_warned: set[int] = set()
    problems = []
    for r in rows:
        num = int(r["num"])
        file_rel = solution_path(num, files, None if num in twin_warned else warnings)
        twin_warned.add(num)
        rep_dates = eb._DATE.findall(r.get("reps") or "")
        timeline = []
        for d in rep_dates:
            glyph = None if (num, d) in shared else sched.get(d, {}).get(num)
            timeline.append({"date": d, "comfort": glyph,
                             "level": LEVEL.get(glyph) if glyph else None})
        # The final point is anchored to the tracker's authoritative current comfort,
        # even when that rep's schedule row could not be read.
        if timeline and timeline[-1]["comfort"] is None:
            timeline[-1] = {"date": timeline[-1]["date"], "comfort": r["comfort"],
                            "level": LEVEL.get(r["comfort"])}
        title = r["title"].strip()
        held = {"heldUntil": holds[f"{num}. {title}"]} if f"{num}. {title}" in holds else {}
        problems.append({
            "lcNumber": num,
            "title": title,
            "url": urls.get(num),
            "file": file_rel,
            "difficulty": r["diff"],
            "category": cats.get(num),
            "comfort": r["comfort"],
            "level": LEVEL.get(r["comfort"]),
            "streak": r["streak"],
            "nextReview": r["due"],
            "repDates": rep_dates,
            "timeline": timeline,
            **held,
        })
    return problems


def _shared_rep_dates(rows: list[dict]) -> set[tuple[int, str]]:
    """`(num, date)` pairs listed in the reps of two or more rows of the same number — the
    dates whose schedule glyph cannot be assigned to one variant row."""
    seen: set[tuple[int, str]] = set()
    shared: set[tuple[int, str]] = set()
    for r in rows:
        num = int(r["num"])
        for d in set(eb._DATE.findall(r.get("reps") or "")):
            (shared if (num, d) in seen else seen).add((num, d))
    return shared


def _count_nums(rows: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for r in rows:
        counts[int(r["num"])] = counts.get(int(r["num"]), 0) + 1
    return counts


def pipeline(rows: list[dict], retired: list[dict]) -> dict:
    by = {"🔴": 0, "🟡": 0, "🟢": 0, "🎓": 0}
    green = {"s0": 0, "s1": 0, "s2plus": 0}
    for r in rows:
        by[r["comfort"]] = by.get(r["comfort"], 0) + 1
        if r["comfort"] == "🟢":
            key = "s0" if r["streak"] == 0 else "s1" if r["streak"] == 1 else "s2plus"
            green[key] += 1
    return {"blank": by["🔴"], "shaky": by["🟡"],
            "clean": {**green, "total": by["🟢"]},
            "graduated": by["🎓"], "retired": len(retired)}


def difficulty_mix(rows: list[dict]) -> dict:
    mix = {"Easy": 0, "Medium": 0, "Hard": 0}
    for r in rows:
        mix[r["diff"]] = mix.get(r["diff"], 0) + 1
    return mix


def on_schedule(rows: list[dict], today: dt.date) -> dict:
    overdue = due = 0
    for r in rows:
        try:
            nxt = dt.date.fromisoformat(r["due"])
        except ValueError:
            continue
        if nxt < today:
            overdue += 1
        elif nxt == today:
            due += 1
    return {"totalActive": len(rows), "dueToday": due, "overdue": overdue}


def _had_turnaround(problems: list[dict]) -> bool:
    """Any problem whose timeline went 🔴 ... then later 🟢/🎓 — an earned comeback."""
    for p in problems:
        seen_blank = False
        for pt in p["timeline"]:
            if pt["comfort"] == "🔴":
                seen_blank = True
            elif seen_blank and pt["comfort"] in ("🟢", "🎓"):
                return True
    return False


def compute_badges(stats: dict, problems: list[dict], cfg: dict) -> list[dict]:
    """The badge CATALOG. Every trigger keys off a genuine, unfakeable event —
    a graduation (3 cold cleans across spaced intervals), a retirement, a comeback,
    a study-day streak — never a raw count of easy greens and never a rating.

    A counter badge (streak-N, trophies-N, all-green) MAY carry an additive
    `progress: {current, target}` alongside `earned` — how far toward the target,
    even when not yet earned. A one-shot event badge (first-clean, first-hard-clean,
    first-graduate, first-retire, comeback) never carries it: there is no "current/
    target" for an event that either happened or hasn't."""
    pl = stats["pipeline"]
    trophies = pl["graduated"] + pl["retired"]
    hard_clean = any(p["difficulty"] == "Hard" and p["comfort"] in ("🟢", "🎓")
                     for p in problems)
    techs = stats.get("techniques") or []
    green = sum(1 for t in techs if t.get("hasGreen"))
    cov = stats.get("coverage") or {}
    all_green_target = cov.get("total") or len(techs)

    badges: list[dict] = []

    def add(bid: str, title: str, icon: str, desc: str, earned: bool,
            progress: tuple[int, int] | None = None) -> None:
        badge = {"id": bid, "title": title, "icon": icon,
                 "description": desc, "earned": bool(earned)}
        if progress is not None:
            current, target = progress
            badge = {**badge, "progress": {"current": int(current), "target": int(target)}}
        badges.append(badge)

    add("first-clean", "First Cold Solve", "🟢",
        "Solve one problem clean from a blank page.",
        pl["clean"]["total"] + pl["graduated"] > 0)
    add("first-hard-clean", "Hard Mode", "⛰️",
        "Solve a Hard problem clean, cold.", hard_clean)
    add("first-graduate", "First Graduation", "🎓",
        "Graduate a problem — three cold cleans across spaced reviews.",
        pl["graduated"] >= 1)
    add("first-retire", "Retired It", "🏆",
        "Retire a problem — it cleared its spot checks and left rotation for good.",
        pl["retired"] >= 1)
    add("comeback", "Comeback", "🔁",
        "Turn a Blank into a Clean on the same problem.", _had_turnaround(problems))
    add("all-green", "Full Spectrum", "🌈",
        "Have at least one clean solve in every technique on the roadmap.",
        all_green_target > 0 and green >= all_green_target,
        progress=(green, all_green_target))

    for m in sorted(cfg.get("streak_milestones") or []):
        add(f"streak-{m}", f"{m}-Day Streak", "🔥",
            f"Practice on {m} study-days without letting the streak lapse.",
            stats["streak"]["longest"] >= m,
            progress=(stats["streak"]["longest"], m))
    for m in sorted(cfg.get("trophy_milestones") or []):
        add(f"trophies-{m}", f"{m} Mastered", "💎",
            f"Reach {m} problem{'s' if m != 1 else ''} graduated or retired.",
            trophies >= m, progress=(trophies, m))

    return badges


def build_payload(today: dt.date | None = None) -> tuple[dict, list[str]]:
    """Return (payload, warnings). Never raises for a missing/partial input."""
    today = today or dt.date.today()
    warnings: list[str] = []
    cfg, fell_back = load_config()
    if fell_back:
        warnings.append("cse.config.yml had no `gamification:` block (or PyYAML is "
                        "missing) — used DEFAULT_CONFIG thresholds.")

    try:
        rows = eb.parse_rows()
    except OSError as exc:
        warnings.append(f"could not read the tracker ({exc}); emitting an empty payload.")
        rows = []

    retired = parse_retired()
    cats = category_map()
    urls = problem_urls()
    files = links.solution_files()   # one glob; every row and board item reads this map
    sched = build_schedule_index()
    coverage = parse_coverage()
    if coverage is None:
        warnings.append("technique_coverage.md not readable — coverage omitted.")
    techniques = parse_techniques(warnings)
    schedule = parse_current_week_schedule(today, urls, files)
    if schedule is None:
        warnings.append("no current weekly schedule file found — schedule omitted.")
    probes = parse_probes(urls, _difficulty_by_num(), files)
    if probes is None:
        warnings.append("dsa/probes/README.md Probe log not readable — probes omitted.")

    # Today's-board workload bar: reuse effort_budget.py's OWN config reader rather than
    # re-deriving the fallback here — it already tolerates a missing `effort_budget:`
    # block / PyYAML and returns its documented defaults for `effort_budget.ceiling` /
    # `effort_budget.floor_min` (cse.config.yml), which is the single source of truth for
    # these two numbers.
    effort_cfg = eb.load_config()

    try:
        holds = load_holds()
    except update_review_dates.HoldsError as exc:
        warnings.append(f"holds.yml not readable ({exc}) — heldUntil omitted.")
        holds = {}
    problems = build_problems(rows, sched, cats, urls, files, warnings, holds=holds)
    days = study_days(rows)

    # buildsOn/graduatedCount/planned: computed after build_problems() rather than right
    # after parse_techniques() because graduatedCount (and planned's tracked-number check)
    # needs comfort_by_number, which is built from build_problems()'s own output, never a
    # second read of the tracker. planned's own waiting_room map DOES read TRACKER again
    # here — the same per-function read convention as problem_urls() and parse_retired()
    # above, not a second read of anything comfort_by_number covers.
    yaml_entries = load_technique_entries(warnings)
    comfort_by_number = _comfort_by_number(problems, retired)
    try:
        waiting_room = parse_waiting_room(TRACKER.read_text(encoding="utf-8"))
    except OSError:
        waiting_room = {}
    # roadmap.yml: the fallback title/url/difficulty catalog for a declared-untracked
    # problem with no Waiting Room row of its own — see planned_for()/load_roadmap().
    roadmap = load_roadmap(warnings, has_tracker_rows=bool(rows))
    techniques = enrich_techniques(techniques, yaml_entries, comfort_by_number,
                                   waiting_room, warnings, catalog=roadmap,
                                   problems=problems, has_tracker_rows=bool(rows))

    stats = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": today.isoformat(),
        "totals": {
            "problems": len({p["lcNumber"] for p in problems}),
            "reps": sum(len(p["repDates"]) for p in problems),
        },
        "pipeline": pipeline(rows, retired),
        "difficulty": difficulty_mix(rows),
        "streak": compute_streak(days, int(cfg["streak_freeze_max"]),
                                 int(cfg["streak_freeze_earn_every"]), today),
        "coverage": coverage,
        "onSchedule": on_schedule(rows, today),
        "trophyCase": {"graduated": [p for p in problems if p["comfort"] == "🎓"],
                       "retired": retired},
        "techniques": techniques,
        "studyDays": [d.isoformat() for d in days],
        "schedule": schedule,
        "workload": build_workload(rows, effort_cfg),
        "effortCeiling": float(effort_cfg["ceiling"]),
        "effortFloor": float(effort_cfg["floor_min"]),
        "probes": probes,
    }
    stats["badges"] = compute_badges(stats, problems, cfg)
    stats["problems"] = problems
    if warnings:
        stats["warnings"] = warnings
    return stats, warnings


def summary_of(payload: dict) -> dict:
    """Derive the lightweight landing contract from the full payload.

    Same aggregates, NO `problems[]` (the heavy part) and a COMPACT `trophyCase`:
    graduated entries drop to `{lcNumber, title, difficulty}` (no timeline/repDates —
    the per-problem detail the landing never needs). `retired` entries are already
    compact in the full payload, so they pass through unchanged.

    `techniques` rides along whole (already small) and backs the technique-breadth drill.
    `studyDays` rides along CAPPED to the last SUMMARY_STUDY_DAYS_WINDOW days — that's all
    the streak-calendar drill renders, and without a cap this list grows by one entry per
    practice day forever. The lifetime total is untouched: it lives in `streak.studyDays`
    (count) and `streak.longest`, both copied through as-is. The full `progress.json`
    keeps every study day, uncapped.

    `schedule` (the current week's Today's-board slice) rides through whole too — it is
    one week of compact rows, small either way, and the summary is exactly where the
    landing's Today's-board drill reads it from (no separate fetch for "what do I do
    today"). `effortCeiling`/`effortFloor` (two numbers) back the workload bar's
    Light/Moderate/Heavy band next to it.

    `probes` rides through whole too — the Probe log is ~1 row/week, small either way, and
    it's the ONLY place a disposable, cold recognition probe is counted (see
    parse_probes()'s docstring), so the Recognition tab needs it with no extra fetch.

    `workload` (planned vs completed effort units per scheduled day) rides through
    CAPPED to the same rolling window as `studyDays` — the workload chart is a recent
    view, not a lifetime one, and an uncapped list grows by one entry per scheduled day
    forever. The full `progress.json` keeps every scheduled day, uncapped.
    """
    trophy_case = payload.get("trophyCase") or {}
    compact_graduated = [
        {"lcNumber": p["lcNumber"], "title": p["title"], "difficulty": p.get("difficulty")}
        for p in trophy_case.get("graduated") or []
    ]
    generated_at = dt.date.fromisoformat(payload["generatedAt"])
    cutoff = (generated_at - dt.timedelta(days=SUMMARY_STUDY_DAYS_WINDOW)).isoformat()
    recent_study_days = [d for d in (payload.get("studyDays") or []) if d >= cutoff]
    summary = {
        "schemaVersion": payload["schemaVersion"],
        "generatedAt": payload["generatedAt"],
        "totals": payload["totals"],
        "pipeline": payload["pipeline"],
        "difficulty": payload["difficulty"],
        "streak": payload["streak"],
        "coverage": payload["coverage"],
        "onSchedule": payload["onSchedule"],
        "badges": payload["badges"],
        "trophyCase": {"graduated": compact_graduated,
                       "retired": trophy_case.get("retired") or []},
        "techniques": payload.get("techniques") or [],
        "studyDays": recent_study_days,
        "schedule": payload.get("schedule"),
        "workload": [w for w in payload.get("workload") or [] if w["date"] >= cutoff],
        "effortCeiling": payload.get("effortCeiling"),
        "effortFloor": payload.get("effortFloor"),
        "probes": payload.get("probes"),
    }
    if "warnings" in payload:
        summary["warnings"] = payload["warnings"]
    return summary


def build_schedule_history(today: dt.date) -> dict:
    """dashboard/schedule-history.json's own payload: `{schemaVersion, generatedAt,
    weeks}`, every archived + live week whose Daily Schedule table parses non-empty,
    ascending by weekOf. A fresh adopter (no schedule files) gets `weeks: []`.

    A separate function (not folded into build_payload/summary_of) because this is its
    OWN file, never part of the progress.json/progress-summary.json contract — see
    OUT_HISTORY. `urls`/`files` are read independently here rather than threaded in from
    build_payload's own copies, the same per-function-read convention problem_urls() and
    parse_retired() already follow elsewhere in this file.
    """
    urls = problem_urls()
    files = links.solution_files()
    return {"schemaVersion": SCHEMA_VERSION, "generatedAt": today.isoformat(),
            "weeks": parse_schedule_history(urls, files)}


# ── outputs ─────────────────────────────────────────────────────────────────────────

def render_banner(stats: dict) -> str:
    s = stats["streak"]
    pl = stats["pipeline"]
    trophies = pl["graduated"] + pl["retired"]
    flame = f"🔥 {s['current']}-day streak" if s["current"] else "no active streak"
    return f"{flame} · {trophies} mastered (🎓{pl['graduated']} 🏆{pl['retired']}) · " \
           f"{stats['totals']['reps']} reps — dashboard: {SITE}/progress"


def badge_line(stats: dict, owner_repo: str | None) -> str:
    s = stats["streak"]
    pl = stats["pipeline"]
    cov = stats.get("coverage") or {}
    parts = [f"🔥 {s['current']}-day streak",
             f"🎓 {pl['graduated']} graduated",
             f"🏆 {pl['retired']} retired"]
    if cov:
        parts.append(f"{cov['started']}/{cov['total']} techniques")
    href = f"{SITE}/progress"
    if owner_repo:
        href += f"?repo={owner_repo}"
    return f"[![progress]({href}) {' · '.join(parts)}]({href})"


def update_readme_badge(line: str) -> bool:
    """Insert/replace the progress badge between marker comments in README.md.

    Returns True if README changed. No markers and no README -> no-op (never
    invents a README or clobbers content).
    """
    start, end = "<!-- progress-badge:start -->", "<!-- progress-badge:end -->"
    block = f"{start}\n{line}\n{end}"
    try:
        text = README.read_text(encoding="utf-8")
    except OSError:
        return False
    if start in text and end in text:
        new = re.sub(re.escape(start) + r".*?" + re.escape(end), block, text, flags=re.S)
    else:
        return False  # markers absent — leave README alone; opt-in by adding markers
    if new != text:
        README.write_text(new, encoding="utf-8")
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--banner", action="store_true",
                    help="print one honest line for the SessionStart hook, then exit")
    ap.add_argument("--validate", action="store_true",
                    help="compute + report; write nothing (for tests / CI)")
    ap.add_argument("--stdout", action="store_true", help="print the JSON, do not write")
    ap.add_argument("--repo", metavar="OWNER/NAME",
                    help="owner/name for the badge deep-link (default: none)")
    # --date (not --today) so it matches the flag session_date.resolve_datetime tells the
    # user to pass when it announces a guess ("Override with --date if that's wrong") —
    # --today is kept as a hidden alias so any existing caller of the old name still works.
    ap.add_argument("--date", dest="date", metavar="YYYY-MM-DD",
                    help="override the resolved session date (YYYY-MM-DD or YYYYMMDD)")
    ap.add_argument("--today", dest="date", help=argparse.SUPPRESS)
    args = ap.parse_args()

    # session_date.resolve_datetime announces its heuristic guess with a bare print() —
    # stdout, the same stream --stdout/--banner use for their own payload. Redirected to
    # stderr here so the announcement stays visible (CLAUDE.md's fallback-must-announce
    # rule) without corrupting --stdout's JSON or adding a line to --banner's one line.
    with contextlib.redirect_stdout(sys.stderr):
        today = session_date.resolve_datetime(args.date).date()
    stats, warnings = build_payload(today)

    if args.banner:
        print(render_banner(stats))
        return

    if args.stdout:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif args.validate:
        contract_schema.check(stats, SCHEMA)
        print(f"valid: {stats['totals']['reps']} reps · "
              f"{len(stats['problems'])} problems · {len(stats['badges'])} badges · "
              f"{stats['streak']['current']}-day streak", file=sys.stderr)
    else:
        contract_schema.check(stats, SCHEMA)
        DASHBOARD.mkdir(parents=True, exist_ok=True)
        # Compact (no indent), like the two files below: nobody reads the written
        # progress*.json as a human artifact (`--stdout` stays indented for that), and the
        # site fetches them — indentation alone was ~40% of progress-summary.json's bytes
        # once techniques[]/studyDays[] joined the summary.
        full_payload = json.dumps(stats, ensure_ascii=False, separators=(",", ":"))
        OUT.write_text(full_payload + "\n", encoding="utf-8")
        summary_payload = json.dumps(summary_of(stats), ensure_ascii=False, separators=(",", ":"))
        OUT_SUMMARY.write_text(summary_payload + "\n", encoding="utf-8")
        # Compact, same as progress-summary.json — see OUT_HISTORY.
        history_payload = json.dumps(build_schedule_history(today), ensure_ascii=False,
                                     separators=(",", ":"))
        OUT_HISTORY.write_text(history_payload + "\n", encoding="utf-8")
        changed = update_readme_badge(badge_line(stats, args.repo))
        print(f"wrote {OUT.relative_to(REPO)} + {OUT_SUMMARY.relative_to(REPO)} + "
              f"{OUT_HISTORY.relative_to(REPO)} "
              f"({stats['totals']['reps']} reps, "
              f"{stats['pipeline']['graduated']}🎓 {stats['pipeline']['retired']}🏆, "
              f"{stats['streak']['current']}-day streak)"
              + (" · README badge updated" if changed else ""))

    # Warnings go to stderr so --stdout / --validate keep a clean JSON stdout.
    for w in warnings:
        print(f"  !! {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
