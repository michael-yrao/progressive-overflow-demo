"""Discard a DRAFT week's file so the weekly build can rebuild it.

    py scripts/rebuild_week.py YYYY-MM-DD

Run from the repo root (the weekly-build workflow does). The argument is the Monday of the
week. Exit 2 (`refused: <reason>`) when the argument is not an ISO date or not a Monday, the
live file `docs/foundations/schedules/<YYYYMMDD>_schedule.md` is missing (an archived one does
not count), the file has no draft marker line, the file text holds `~~` anywhere (a struck
cell is a logged rep), or any of the week's seven `dsa/attempts/<YYYYMMDD>/` folders holds a
file (an unfolded saved attempt). An empty attempt folder is allowed. Otherwise the file is
removed and `discarded: <relative path>` is printed (exit 0).
"""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

import _console
from build_week import DAYS_PER_WEEK, DRAFT_MARKER, EXIT_REFUSED, LIVE_DIR, SCHEDULE_NAME

_console.force_utf8()

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTEMPTS_DIR = Path("dsa/attempts")
DAY_DIR_NAME = "{day:%Y%m%d}"
STRIKE = "~~"
MONDAY_WEEKDAY = 0


class RebuildRefused(Exception):
    """The week cannot be discarded; the message is the `refused:` line."""


@dataclass(frozen=True)
class Target:
    monday: dt.date
    path: Path


def parse_monday(text: str) -> dt.date:
    try:
        monday = dt.date.fromisoformat(text)
    except ValueError:
        raise RebuildRefused(f"{text!r} is not an ISO date (YYYY-MM-DD)") from None
    if monday.weekday() != MONDAY_WEEKDAY:
        raise RebuildRefused(f"{text} is not a Monday")
    return monday


def week_days(monday: dt.date) -> tuple[dt.date, ...]:
    return tuple(monday + dt.timedelta(days=offset) for offset in range(DAYS_PER_WEEK))


def saved_attempt_days(repo: Path, monday: dt.date) -> tuple[str, ...]:
    """The week's date folders that hold at least one file."""
    names = (DAY_DIR_NAME.format(day=day) for day in week_days(monday))
    return tuple(
        name for name in names
        if any(child.is_file() for child in (repo / ATTEMPTS_DIR / name).glob("*"))
    )


def check_discardable(repo: Path, monday: dt.date) -> Target:
    rel = LIVE_DIR / SCHEDULE_NAME.format(monday=monday)
    path = repo / rel
    if not path.is_file():
        raise RebuildRefused(f"{rel.as_posix()} is missing (an archived week is not rebuilt)")
    text = path.read_text(encoding="utf-8")
    if DRAFT_MARKER not in (line.strip() for line in text.splitlines()):
        raise RebuildRefused(f"{rel.as_posix()} is not a draft")
    if STRIKE in text:
        raise RebuildRefused(f"{rel.as_posix()} has a logged rep (struck cell)")
    saved = saved_attempt_days(repo, monday)
    if saved:
        raise RebuildRefused(f"saved attempts in {ATTEMPTS_DIR.as_posix()}/{', '.join(saved)}")
    return Target(monday, path)


def run(argv: list[str], repo: Path) -> str:
    if len(argv) != 1:
        raise RebuildRefused("usage: rebuild_week.py YYYY-MM-DD")
    target = check_discardable(repo, parse_monday(argv[0]))
    target.path.unlink()
    return f"discarded: {target.path.relative_to(repo).as_posix()}"


def main(argv: list[str] | None = None, repo: Path = REPO_ROOT) -> int:
    try:
        print(run(sys.argv[1:] if argv is None else argv, repo))
    except RebuildRefused as exc:
        print(f"refused: {exc}")
        return EXIT_REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
