"""Resolve the *session* date, which past midnight is not the wall-clock date.

Why this module exists
----------------------
A study session that starts at 22:00 and runs to 01:00 is **one session with one date**
— its start date. Every date-touching script here defaulted to `datetime.now()`, so past
midnight they all silently rolled to the next day. That mis-stamped attempt methods,
tracker rows, and whole schedule boards; `feedback_session_dating` recorded four-plus
occurrences and recurred three times *after* being promoted to a memory file, because a
memory file cannot fix a default that lives in the tool.

The detection rule is the one already written in CLAUDE.md, now executable:

    "past midnight, check `git log --date=iso` — commits from minutes ago mean a
     *live session*, not a new day."

`restore_history.py` solved the same problem from a different signal (the dated stubs in
the stashed files). That signal is better when it exists — it reads the session's own
artifacts — but it only exists once files have been touched. Git history works before
anything has been written, which is what scaffolding needs.

Design note: the override flag is `--date`, and it is an **override**, not the mechanism.
A flag that must be remembered is just a paragraph with a CLI; the default has to be
right on its own.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta

# A GitHub Actions run is a bot, not a learner mid-session: the wall date is the date.
CI_ENV_VAR = "GITHUB_ACTIONS"
CI_ENV_TRUE = "true"

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()

# Before this hour, a session is assumed to possibly belong to the previous day.
# 05:00 is late enough to cover a long night and early enough that a genuine
# early-morning start is not misread (nobody in this repo's history starts at 04:00).
SMALL_HOURS_CUTOFF = 5

# How recent the last commit must be for the session to count as still live.
#
# ⚠️ This is the WEAKER of the two signals and must never be the only one. Two traps,
# both found by testing against the real 2026-07-29 failure:
#   1. In a past-midnight session the last commit is often ALSO past midnight, so it
#      carries the rolled-over date — the signal is polluted by the very bug being
#      fixed. Never test "was the commit yesterday?", only "was it recent?".
#   2. This repo batches commits to session end (feedback_batch_commits), so for most
#      of a session the newest commit is the PREVIOUS session's close-out, 24h+ back.
# Hence the primary signal below is the dirty working tree, not this.
LIVE_SESSION_WINDOW = timedelta(hours=6)


def last_commit_time() -> datetime | None:
    """Committer timestamp of HEAD as a naive local datetime, or None if unavailable."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%cI"],
            text=True,
            encoding="utf-8",  # never inherit the Windows cp1252 default (Git's output is UTF-8)
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None  # no git, no commits, or not a repo — caller falls back to the clock
    if not out:
        return None
    try:
        return datetime.fromisoformat(out).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def has_uncommitted_changes() -> bool:
    """True if the working tree is dirty.

    This is the PRIMARY liveness signal. The workflow commits clean at session end
    (CLAUDE.md: "commit + push once at session end"), so a dirty tree during the small
    hours means a session is still in progress — and a session in progress at 00:40
    started yesterday. It needs no timestamp and so cannot be fooled by a commit that
    itself carries a rolled-over date.
    """
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False
    return bool(out.strip())


def detect_session_date(now: datetime | None = None) -> tuple[datetime, str | None]:
    """Return (session_date, reason_if_overridden).

    `reason` is None when the wall-clock date was used, so callers can stay quiet in the
    normal case and announce only the interesting one. Announcing matters: the override
    is a heuristic, and a visible wrong guess is cheap to fix with --date while a silent
    one is exactly the failure this module exists to prevent.
    """
    now = now or datetime.now()
    if now.hour >= SMALL_HOURS_CUTOFF or os.environ.get(CI_ENV_VAR) == CI_ENV_TRUE:
        return now, None

    session = now - timedelta(days=1)

    if has_uncommitted_changes():
        return session, "working tree is dirty — a session is in progress, so it started yesterday"

    committed = last_commit_time()
    if committed is not None and now - committed <= LIVE_SESSION_WINDOW:
        mins = int((now - committed).total_seconds() // 60)
        return session, f"last commit was {mins} min ago — live session, not a new day"

    # Small hours, clean tree, no recent commit: nothing suggests work in progress.
    # Fall back to the clock rather than guess.
    return now, None


def _announce_override(explicit: datetime, now: datetime | None) -> None:
    """Print one line when `--date` contradicts a detection that had a reason."""
    detected, reason = detect_session_date(now)
    if not reason or detected.date() == explicit.date():
        return
    print(f"--date {explicit.strftime('%Y-%m-%d')} overrides the detected session date "
          f"{detected.strftime('%Y-%m-%d')} ({reason}); the override is for a wrong "
          f"detection, not for re-deciding which day has started.")


def resolve_datetime(explicit: str | None = None, *, now: datetime | None = None,
                     announce: bool = True) -> datetime:
    """Session date as a datetime. `explicit` (YYYY-MM-DD or YYYYMMDD) always wins."""
    if explicit:
        for candidate in ("%Y-%m-%d", "%Y%m%d"):
            try:
                parsed = datetime.strptime(explicit, candidate)
            except ValueError:
                continue
            if announce:
                _announce_override(parsed, now)
            return parsed
        raise SystemExit(f"--date: expected YYYY-MM-DD or YYYYMMDD, got {explicit!r}")

    session, reason = detect_session_date(now)
    if reason and announce:
        print(f"Using session date {session.strftime('%Y-%m-%d')} ({reason}). "
              f"Override with --date if that's wrong.")
    return session


def resolve(explicit: str | None = None, *, fmt: str = "%Y-%m-%d",
            now: datetime | None = None, announce: bool = True) -> str:
    """Session date formatted with `fmt`. See `resolve_datetime`."""
    return resolve_datetime(explicit, now=now, announce=announce).strftime(fmt)
