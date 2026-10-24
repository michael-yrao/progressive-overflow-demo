"""Schedule-file writers for the fold (see fold_record.py): strike a done row, move-pair a row
completed off its planned day, seat the next review, re-price the touched days.

Every writer takes the schedule's text (LF line ends) and returns new text; none reads or writes
a file. Row and header shapes are `effort_budget`'s regexes, imported, never copied.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import re
import sys
from dataclasses import dataclass

import effort_budget as eb

WEEK_DAYS = 7
STRIKE = "~~"
EMPTY_CELL = "  "
ARROW_LATER_DAY = "→"
ARROW_EARLIER_DAY = "←"
ARROW_PREFIX = re.compile(r"^\s*([←→])?\s*")
UNITS_WORD = "units"
PLANNED_PIN = " · planned {figure:.1f} units"
NO_BLOCK = "schedule: no block for {iso}"
PROVISIONAL_GLYPH = "❔"
END_CELL_INDEX = 2
NEXT_CELL_INDEX = 3


@dataclass(frozen=True)
class Row:
    index: int
    day: dt.date
    cells: tuple[str, str, str, str, str]

    @property
    def is_struck(self) -> bool:
        return STRIKE in self.cells[0]

    @property
    def is_live(self) -> bool:
        """Unstruck and not a moved-away origin (an origin carries its destination date)."""
        return not self.is_struck and eb.deferred_to(False, self.cells[3]) is None


@dataclass(frozen=True)
class RepFacts:
    """What one completed rep writes into the schedule."""
    number: str
    end_glyph: str
    next_iso: str
    new_row_cell: str
    start_cell: str
    technique: str


@dataclass(frozen=True)
class Placement:
    text: str
    touched: tuple[dt.date, ...]
    note: str


def replace_at(lines: list[str], index: int, line: str) -> list[str]:
    return [*lines[:index], line, *lines[index + 1:]]


def insert_at(lines: list[str], index: int, line: str) -> list[str]:
    return [*lines[:index], line, *lines[index:]]


def row_line(cells: tuple[str, ...]) -> str:
    return "|" + "|".join(cells) + "|"


def day_headers(lines: list[str], week_start: dt.date) -> dict[dt.date, int]:
    """Line index of each day header of the week, keyed by the date it names."""
    by_key = {}
    for offset in range(WEEK_DAYS):
        day = week_start + dt.timedelta(days=offset)
        by_key[(day.strftime("%a"), day.strftime("%b"), day.day)] = day
    found: dict[dt.date, int] = {}
    for index, line in enumerate(lines):
        match = eb.DAY_HEADER.search(line)
        day = by_key.get((match["wd"], match["mon"], int(match["day"]))) if match else None
        if day is not None and day not in found:
            found[day] = index
    return found


def block_end(lines: list[str], header_index: int) -> int:
    """Index just past a day's last row: the blank separator row, the next header, or the table's end."""
    index = header_index + 1
    while index < len(lines):
        line = lines[index]
        if not line.lstrip().startswith("|") or eb.DAY_HEADER.search(line):
            break
        match = eb.SCHED_ROW.match(line)
        if match and not match["c1"].strip():
            break
        index += 1
    return index


def rows_for(lines: list[str], headers: dict[dt.date, int], number: str) -> list[Row]:
    """Every row of problem `number` inside the given day blocks, in day order."""
    found = []
    for day, start in sorted(headers.items()):
        for index in range(start + 1, block_end(lines, start)):
            match = eb.SCHED_ROW.match(lines[index])
            num = eb.SCHED_NUM.search(match["c1"]) if match else None
            if num and num.group(1) == number:
                found.append(Row(index, day, tuple(match[f"c{i}"] for i in range(1, 6))))
    return found


def find_live_row(text: str, week_start: dt.date, number: str, today: dt.date) -> Row | None:
    """The live (unstruck, not moved-away) row of `number`: today's first, else the nearest day's."""
    lines = text.split("\n")
    live = [r for r in rows_for(lines, day_headers(lines, week_start), number) if r.is_live]
    live.sort(key=lambda r: (r.day != today, abs((r.day - today).days)))
    return live[0] if live else None


def find_provisional_row(text: str, week_start: dt.date, number: str, day: dt.date) -> Row | None:
    """The struck row of `number` on `day` whose End cell is the provisional glyph, else None."""
    lines = text.split("\n")
    headers = day_headers(lines, week_start)
    if day not in headers:
        return None
    return next((r for r in rows_for(lines, {day: headers[day]}, number)
                 if r.is_struck and r.cells[END_CELL_INDEX].strip() == PROVISIONAL_GLYPH), None)


def settle_schedule(text: str, week_start: dt.date, today: dt.date, facts: RepFacts) -> Placement:
    """Swap the provisional End glyph of `today`'s struck row for `facts.end_glyph`; set Next."""
    row = find_provisional_row(text, week_start, facts.number, today)
    if row is None:
        return Placement(text, (), f"schedule: no {PROVISIONAL_GLYPH} row for {facts.number} on {today.isoformat()}")
    cells = list(row.cells)
    cells[END_CELL_INDEX], cells[NEXT_CELL_INDEX] = f" {facts.end_glyph} ", f" {facts.next_iso} "
    lines = replace_at(text.split("\n"), row.index, row_line(tuple(cells)))
    return Placement("\n".join(lines), (today,), f"schedule: settled {facts.number} on {today.isoformat()}")


def cell_content(cell: str) -> str:
    """A Problem cell without its move arrow and outer spaces."""
    return ARROW_PREFIX.sub("", cell, count=1).strip()


def struck_cell(cell: str, arrow: str | None = None) -> str:
    """The Problem cell struck through; a move arrow already on the cell (or given) stays in front."""
    own = ARROW_PREFIX.match(cell).group(1)
    tag = f"{arrow or own} " if (arrow or own) else ""
    return f" {tag}{STRIKE}{cell_content(cell)}{STRIKE} "


def strike_schedule_row(text: str, week_start: dt.date, day: dt.date, number: str,
                        end_glyph: str, next_iso: str) -> tuple[str, bool]:
    """Strike the first live row of `number` inside `day`'s block; set E and Next. (text, found)."""
    lines = text.split("\n")
    headers = day_headers(lines, week_start)
    if day not in headers:
        return text, False
    for row in rows_for(lines, {day: headers[day]}, number):
        if row.is_live:
            c1, c2, _, _, c5 = row.cells
            cells = (struck_cell(c1), c2, f" {end_glyph} ", f" {next_iso} ", c5)
            return "\n".join(replace_at(lines, row.index, row_line(cells))), True
    return text, False


def seat_next_review(text: str, week_start: dt.date, next_iso: str, number: str, title_cell: str,
                     start_glyph: str, technique: str) -> str:
    """An unstruck row for the next review on its day, when that day is in this week's file."""
    lines = text.split("\n")
    headers = day_headers(lines, week_start)
    day = dt.date.fromisoformat(next_iso)
    if day not in headers:
        return text
    if any(r.is_live for r in rows_for(lines, {day: headers[day]}, number)):
        return text
    cells = (f" {title_cell} ", f" {start_glyph} ", EMPTY_CELL, EMPTY_CELL, f" {technique} ")
    return "\n".join(insert_at(lines, block_end(lines, headers[day]), row_line(cells)))


def pin_planned(line: str) -> str:
    """The header with ` · planned X units` after its `~N units`, X = that figure; unchanged if pinned or unpriced."""
    match = eb.DAY_HEADER.search(line)
    if not match or not match["units"] or match["planned"]:
        return line
    end = line.index(UNITS_WORD, match.start("units")) + len(UNITS_WORD)
    return line[:end] + PLANNED_PIN.format(figure=float(match["units"])) + line[end:]


def move_pair(lines: list[str], headers: dict[dt.date, int], origin: Row, today: dt.date,
              facts: RepFacts) -> Placement:
    """Origin stays unstruck with an arrow and today's date; today gets the struck copy."""
    arrow = ARROW_EARLIER_DAY if origin.day > today else ARROW_LATER_DAY
    c1, c2, c3, _, c5 = origin.cells
    content = cell_content(c1)
    origin_cells = (f" {arrow} {content} ", c2, c3, f" {today.isoformat()} ", c5)
    copy_cells = (struck_cell(c1, arrow), c2, f" {facts.end_glyph} ", f" {facts.next_iso} ", c5)
    moved = replace_at(lines, origin.index, row_line(origin_cells))
    moved = replace_at(moved, headers[origin.day], pin_planned(moved[headers[origin.day]]))
    moved = insert_at(moved, block_end(moved, headers[today]), row_line(copy_cells))
    return Placement("\n".join(moved), (today, origin.day),
                     f"schedule: moved {facts.number} from {origin.day.isoformat()} ({arrow})")


def append_new(lines: list[str], headers: dict[dt.date, int], today: dt.date,
               facts: RepFacts) -> Placement:
    cells = (struck_cell(f" {facts.new_row_cell} "), f" {facts.start_cell} ", f" {facts.end_glyph} ",
             f" {facts.next_iso} ", f" {facts.technique} ")
    added = insert_at(lines, block_end(lines, headers[today]), row_line(cells))
    return Placement("\n".join(added), (today,),
                     f"schedule: appended {facts.number} to {today.isoformat()}")


def apply_schedule(text: str, week_start: dt.date, today: dt.date, facts: RepFacts) -> Placement:
    """Record a rep done `today`: strike it where it sits, or move-pair it, or append it."""
    lines = text.split("\n")
    headers = day_headers(lines, week_start)
    if today not in headers:
        return Placement(text, (), NO_BLOCK.format(iso=today.isoformat()))
    rows = rows_for(lines, headers, facts.number)
    todays = [r for r in rows if r.day == today]
    if any(r.is_live for r in todays):
        struck, _ = strike_schedule_row(text, week_start, today, facts.number,
                                        facts.end_glyph, facts.next_iso)
        return Placement(struck, (today,), f"schedule: struck {facts.number} on {today.isoformat()}")
    if any(r.is_struck for r in todays):
        return Placement(text, (), f"schedule: {facts.number} already struck on {today.isoformat()}")
    elsewhere = sorted((r for r in rows if r.is_live), key=lambda r: abs((r.day - today).days))
    if elsewhere:
        return move_pair(lines, headers, elsewhere[0], today, facts)
    return append_new(lines, headers, today, facts)


def reprice_days(text: str, week_start: dt.date, days: tuple[dt.date, ...],
                 rows: list[dict], cfg: dict) -> str:
    """Each day header's first figure set to what its rows price to (`price_day_items` `built`)."""
    lines = text.split("\n")
    for day in sorted(set(days)):
        headers = day_headers(lines, week_start)
        items, _ = eb.parse_day_block(lines, week_start, day)
        match = eb.DAY_HEADER.search(lines[headers[day]]) if day in headers else None
        if not items or not match or not match["units"]:
            continue
        with contextlib.redirect_stdout(sys.stderr):
            built = eb.price_day_items(day, items, rows, cfg)["built"]
        line = lines[headers[day]]
        repriced = line[:match.start("units")] + f"{built:.1f}" + line[match.end("units"):]
        lines = replace_at(lines, headers[day], repriced)
    return "\n".join(lines)
