"""The record side of a fold: what the coach otherwise applies by hand after a site rep.

Pure text writers: each takes a file's text (LF line ends) and returns new text. fold_attempt.py
reads the files, calls `record_rep`, and writes back what changed. The schedule writers live in
fold_schedule.py and are re-exported here.

Run with cwd = the repo root: update_review_dates reads cse.config.yml from the cwd at import.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import effort_budget as eb
import recognition_grade
import update_review_dates as urd
from fold_schedule import (Placement, RepFacts, apply_schedule, find_live_row,  # noqa: F401
                           replace_at, reprice_days, seat_next_review, strike_schedule_row)

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
VARIANT = re.compile(r"\(([^()]*)\)\s*$")
FIRST_BRACKET_CLOSE = re.compile(r"\]")
SCHEDULE_LINK_PREFIX = "../../../"
QUEUE_HEADER = "## ⏳ End-of-week complexity cleanup queue"
RECOGNITION_MISS = ("- **{iso} · {number} {title}{technique}** ({glyph} site rep) — ❌ **miss: no "
                    "top-of-method call.** Site-completed rep; the method opens with code, not the "
                    "recognition comment.")
GRADUATED_COMFORTS = (urd.COMFORT_GRADUATED, urd.COMFORT_RETIRED)
UNSTREAKED_START = {urd.COMFORT_SHAKY, urd.COMFORT_BLANK, urd.COMFORT_GRADUATED}
UNSEEN_COMFORT = urd.COMFORT_BLANK
UNSEEN_STREAK = 0
DEFAULT_DIFFICULTY = "Medium"
TABLE_SEPARATOR_PREFIX = "|---"


class RecordError(Exception):
    """A record step cannot be applied; the message says why."""


@dataclass(frozen=True)
class Outcome:
    comfort: str
    streak: int
    next_iso: str
    previous_comfort: str
    is_duplicate: bool
    is_retirement_candidate: bool


@dataclass(frozen=True)
class RepInput:
    number: str
    title: str
    iso: str
    rating: str
    glyph: str
    has_recognition: bool
    queue_rows: tuple[str, ...]
    difficulty: str = DEFAULT_DIFFICULTY
    url: str = ""
    picked: str = ""
    pick: recognition_grade.PickGrade | None = None


@dataclass(frozen=True)
class RecordInputs:
    tracker: str
    schedule: str | None
    week_start: dt.date | None
    complexity: str
    recognition: str
    base_cell: str
    holds: dict
    config: dict
    pricing_config: dict


@dataclass(frozen=True)
class RecordOutput:
    tracker: str
    schedule: str | None
    complexity: str
    recognition: str
    lines: tuple[str, ...]
    next_iso: str = ""
    next_cell: str = ""
    next_start: str = ""
    technique: str = ""


@dataclass(frozen=True)
class TrackerEdit:
    """The tracker after one rep, and what the schedule step needs about the row it touched."""
    tracker: str
    outcome: Outcome
    variant: str | None
    start_before: str
    lines: tuple[str, ...]


def tracker_matches(text: str, number: str) -> list[tuple[int, re.Match]]:
    """(line index, ROW_RE match) of every tracker row of problem `number`."""
    found = []
    for index, line in enumerate(text.split("\n")):
        match = urd.ROW_RE.match(line)
        if match and str(urd.extract_problem_number(match["problem"])) == number:
            found.append((index, match))
    return found


def row_variant(problem: str) -> str | None:
    match = VARIANT.search(problem)
    return match.group(1) if match else None


def choose_tracker_row(tracker_text: str, number: str, schedule_title: str | None,
                       iso: str) -> int | None:
    """Line index of the tracker row this rep belongs to; None when the tracker has none."""
    matches = tracker_matches(tracker_text, number)
    if len(matches) <= 1:
        return matches[0][0] if matches else None
    for index, match in matches:
        variant = row_variant(match["problem"])
        if variant and schedule_title and variant in schedule_title:
            return index
    undone = [(index, m) for index, m in matches if m["latest"].strip() != iso] or matches
    return min(undone, key=lambda pair: pair[1]["next"].strip() or "9999")[0]


def next_state(comfort: str, streak: int, rating: str, graduate_at: int) -> tuple[str, int]:
    """Comfort and streak after one rep, per the ladder in spaced-repetition.md."""
    if rating == "shaky":
        return urd.COMFORT_SHAKY, 0
    if rating == "blank":
        return urd.COMFORT_BLANK, 0
    if comfort == urd.COMFORT_BLANK:
        return urd.COMFORT_CLEAN, 0
    if comfort == urd.COMFORT_SHAKY:
        return urd.COMFORT_CLEAN, 1
    raised = streak + 1
    if comfort == urd.COMFORT_CLEAN and raised >= graduate_at:
        return urd.COMFORT_GRADUATED, raised
    return (urd.COMFORT_GRADUATED if comfort in GRADUATED_COMFORTS else comfort), raised


def held_next(title: str, next_iso: str, holds: dict) -> str:
    if title not in holds:
        return next_iso
    return urd.apply_holds([{"problem": title, "next_review": next_iso}],
                           {title: holds[title]})[0]["next_review"]


def row_outcome(match: re.Match, rating: str, iso: str, config: dict, holds: dict) -> Outcome:
    """The row's state after the rep; an already-recorded `iso` leaves the row as it is."""
    comfort, streak = match["comfort"], int(match["streak"])
    if iso in ISO_DATE.findall(match["attempts"]):
        return Outcome(comfort, streak, match["next"].strip(), comfort, True, False)
    new_comfort, new_streak = next_state(comfort, streak, rating, config["graduate_at_streak"])
    next_iso = held_next(match["problem"].strip(), ladder_due(new_comfort, new_streak, iso), holds)
    is_candidate = comfort in GRADUATED_COMFORTS and rating == "clean"
    return Outcome(new_comfort, new_streak, next_iso, comfort, False, is_candidate)


def ladder_due(comfort: str, streak: int, iso: str) -> str:
    """The ISO date the ladder puts the next review on after a rep on `iso`."""
    return urd.format_date(urd.compute_next_review_date(
        comfort, dt.datetime.strptime(iso, "%Y-%m-%d"), streak))


def new_row(rep: RepInput, config: dict, holds: dict) -> tuple[str, Outcome]:
    """(tracker row line, outcome) for a problem the tracker has never seen: its first rep
    moves it off the unseen state the way any rep would (clean 🟢 s0, shaky 🟡, blank 🔴)."""
    comfort, streak = next_state(UNSEEN_COMFORT, UNSEEN_STREAK, rep.rating, config["graduate_at_streak"])
    problem = f"{rep.number}. {rep.title}"
    next_iso = held_next(problem, ladder_due(comfort, streak, rep.iso), holds)
    row = urd.build_row({
        "difficulty": rep.difficulty, "problem": problem, "url": rep.url, "comfort": comfort,
        "streak": streak, "next_review": next_iso, "latest_attempt_date": rep.iso,
        "attempts": rep.iso})
    return row, Outcome(comfort, streak, next_iso, UNSEEN_COMFORT, False, False)


def insert_tracker_row(text: str, row_line: str) -> str:
    """The tracker with `row_line` straight after the review table's separator (the hook re-sorts)."""
    lines = text.split("\n")
    header = next((i for i, ln in enumerate(lines) if ln in urd.TABLE_HEADERS_ALL), None)
    if header is None or header + 1 >= len(lines) or not lines[header + 1].startswith(TABLE_SEPARATOR_PREFIX):
        raise RecordError("no review table found in the tracker")
    at = header + 2
    return "\n".join([*lines[:at], row_line, *lines[at:]])


def apply_tracker_row(text: str, row_index: int, rating: str, iso: str, config: dict,
                      holds: dict | None = None) -> str:
    """The tracker with row `row_index` advanced one rep; the same text when `iso` is already in it."""
    lines = text.split("\n")
    match = urd.ROW_RE.match(lines[row_index])
    if match is None:
        raise RecordError(f"tracker line {row_index + 1} is not a review row")
    outcome = row_outcome(match, rating, iso, config, holds or {})
    if outcome.is_duplicate:
        return text
    attempts = f"{match['attempts']}, {iso}" if match["attempts"].strip() else iso
    row = urd.build_row({
        "difficulty": match["difficulty"], "problem": match["problem"], "url": match["url"],
        "comfort": outcome.comfort, "streak": outcome.streak, "next_review": outcome.next_iso,
        "latest_attempt_date": iso, "attempts": attempts})
    return "\n".join(replace_at(lines, row_index, row))


def tracker_rows(text: str) -> list[dict]:
    """effort_budget's row dicts for a tracker text (what `parse_rows` reads from the file)."""
    return [{**m.groupdict(), "streak": int(m["streak"])}
            for m in (eb.ROW.match(line) for line in text.split("\n")) if m]


def queue_complexity(text: str, row_line: str) -> str:
    """The complexity file with `row_line` appended to the cleanup queue's table."""
    lines = text.split("\n")
    header = next((i for i, ln in enumerate(lines) if ln.startswith(QUEUE_HEADER)), None)
    start = next((i for i in range(header + 1, len(lines)) if lines[i].startswith("|")), None) \
        if header is not None else None
    if start is None:
        raise RecordError("no cleanup-queue table found")
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return "\n".join([*lines[:end], row_line, *lines[end:]])


def log_recognition_miss(text: str, iso: str, number: str, title: str, technique: str | None,
                         glyph: str) -> str:
    """The recognition ledger with a missing-top-comment entry prepended (newest first)."""
    entry = RECOGNITION_MISS.format(iso=iso, number=number, title=title, glyph=glyph,
                                    technique=f" ({technique})" if technique else "")
    return f"{entry}\n{text}"


def log_recognition_pick(text: str, iso: str, number: str, title: str, glyph: str, picked: str,
                         grade: recognition_grade.PickGrade) -> str:
    """The recognition ledger with a graded-pick entry prepended (newest first)."""
    return f"{recognition_grade.pick_line(iso, number, title, glyph, picked, grade)}\n{text}"


def add_variant(cell: str, variant: str | None) -> str:
    return FIRST_BRACKET_CLOSE.sub(f" ({variant})]", cell, count=1) if variant else cell


def schedule_cell(link_line: str | None, title: str) -> str:
    """A schedule row's Problem cell: the link line with its file link re-based to the schedule's folder."""
    if link_line is None:
        return f"[{title}]()"
    return link_line.replace("](", f"]({SCHEDULE_LINK_PREFIX}", 1)


def start_cell(comfort: str, streak: int) -> str:
    return f"{comfort} s{streak}" if comfort not in UNSTREAKED_START else comfort


def record_schedule(inputs: RecordInputs, rep: RepInput, outcome: Outcome, start_before: str,
                    variant: str | None, technique: str, tracker_after: str) -> tuple[str | None, list[str]]:
    """The schedule text after the rep (strike or move, seat the next review, re-price), plus notes."""
    if inputs.schedule is None or inputs.week_start is None:
        return inputs.schedule, [f"schedule: no block for {rep.iso}"]
    cell = add_variant(inputs.base_cell, variant)
    facts = RepFacts(rep.number, outcome.comfort, outcome.next_iso, cell, start_before, technique)
    placed = apply_schedule(inputs.schedule, inputs.week_start, dt.date.fromisoformat(rep.iso), facts)
    seated = seat_next_review(placed.text, inputs.week_start, outcome.next_iso, rep.number, cell,
                              start_cell(outcome.comfort, outcome.streak), technique)
    notes, touched = [placed.note], placed.touched
    if seated != placed.text:
        notes.append(f"schedule: seated {rep.number} on {outcome.next_iso}")
        touched = (*touched, dt.date.fromisoformat(outcome.next_iso))
    repriced = reprice_days(seated, inputs.week_start, touched, tracker_rows(tracker_after),
                            inputs.pricing_config)
    return repriced, notes


@dataclass(frozen=True)
class RepStep:
    """Tracker and schedule after a rep, plus the cell, start glyph and technique a later
    week's next-review row is seated with."""
    tracker: str
    schedule: str | None
    lines: tuple[str, ...]
    technique: str | None
    next_iso: str
    next_cell: str
    next_start: str


def record_tracker_and_schedule(inputs: RecordInputs, rep: RepInput) -> RepStep:
    """The tracker and schedule texts after the rep, with the report lines."""
    day = dt.date.fromisoformat(rep.iso)
    live = (find_live_row(inputs.schedule, inputs.week_start, rep.number, day)
            if inputs.schedule is not None and inputs.week_start is not None else None)
    found_technique = live.cells[4].strip() if live else None
    index = choose_tracker_row(inputs.tracker, rep.number, live.cells[0] if live else None, rep.iso)
    edit = mint_row(inputs, rep) if index is None else advance_row(inputs, rep, index)
    technique = found_technique or edit.variant
    schedule, notes = record_schedule(
        inputs, rep, edit.outcome, edit.start_before, edit.variant, technique or "", edit.tracker)
    return RepStep(edit.tracker, schedule, (*edit.lines, *notes), technique, edit.outcome.next_iso,
                   add_variant(inputs.base_cell, edit.variant),
                   start_cell(edit.outcome.comfort, edit.outcome.streak))


def advance_row(inputs: RecordInputs, rep: RepInput, index: int) -> TrackerEdit:
    """The tracker with its existing row `index` advanced one rep."""
    match = urd.ROW_RE.match(inputs.tracker.split("\n")[index])
    outcome = row_outcome(match, rep.rating, rep.iso, inputs.config, inputs.holds)
    tracker = apply_tracker_row(inputs.tracker, index, rep.rating, rep.iso, inputs.config, inputs.holds)
    lines = [tracker_note(rep, outcome)]
    if outcome.is_retirement_candidate:
        lines.append(f"retirement candidate {rep.number} (manual)")
    return TrackerEdit(tracker, outcome, row_variant(match["problem"]),
                       start_cell(match["comfort"], int(match["streak"])), tuple(lines))


def mint_row(inputs: RecordInputs, rep: RepInput) -> TrackerEdit:
    """The tracker with a new row for a problem it has never seen, carrying the learner's rating."""
    row_line, outcome = new_row(rep, inputs.config, inputs.holds)
    note = (f"tracker {rep.number}: new row {outcome.comfort} streak {outcome.streak}; "
            f"next {outcome.next_iso}; rep {rep.iso}")
    return TrackerEdit(insert_tracker_row(inputs.tracker, row_line), outcome, None,
                       start_cell(UNSEEN_COMFORT, UNSEEN_STREAK), (note,))


def seat_forward(text: str, week_start: dt.date, out: RecordOutput, number: str,
                 pricing_config: dict) -> str:
    """Another week's file with the next review seated on `next_iso` and its day re-priced;
    unchanged when the day has no block there or already holds a live row for `number`."""
    seated = seat_next_review(text, week_start, out.next_iso, number, out.next_cell, out.next_start,
                              out.technique)
    if seated == text:
        return text
    return reprice_days(seated, week_start, (dt.date.fromisoformat(out.next_iso),),
                        tracker_rows(out.tracker), pricing_config)


def record_rep(inputs: RecordInputs, rep: RepInput) -> RecordOutput:
    """Apply one completed rep to the tracker, the schedule and the two gotchas ledgers."""
    step = record_tracker_and_schedule(inputs, rep)
    lines = list(step.lines)
    complexity, recognition = inputs.complexity, inputs.recognition
    for queue_row in rep.queue_rows:
        complexity = queue_complexity(complexity, queue_row)
        lines.append("complexity queue: row added")
    if rep.pick is not None:
        recognition = log_recognition_pick(recognition, rep.iso, rep.number, rep.title, rep.glyph,
                                           rep.picked, rep.pick)
        lines.append(f"recognition: pick {rep.pick.result} logged")
    elif not rep.has_recognition:
        recognition = log_recognition_miss(recognition, rep.iso, rep.number, rep.title, step.technique,
                                           rep.glyph)
        lines.append("recognition: miss logged")
    return RecordOutput(step.tracker, step.schedule, complexity, recognition, tuple(lines),
                        step.next_iso, step.next_cell, step.next_start, step.technique or "")


def tracker_note(rep: RepInput, outcome: Outcome) -> str:
    if outcome.is_duplicate:
        return f"tracker {rep.number}: rep {rep.iso} already recorded; row left as it is"
    return (f"tracker {rep.number}: {outcome.previous_comfort} -> {outcome.comfort} "
            f"streak {outcome.streak}; next {outcome.next_iso}; rep {rep.iso}")
