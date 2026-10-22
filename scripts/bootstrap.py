"""cse-coach first-run setup.

Writes cse.config.yml, projects the milestone curriculum onto real dates
(study_guide roadmap), builds week 1 with scripts/build_week.py, ensures the
trackers/logs exist, and installs the git hook. The conversational intake is the
coach's job (the cse-init skill); this script does the mechanical parts and can
also run standalone.

Usage (all flags optional; prompts for anything omitted):
    python scripts/bootstrap.py --name "Alex" --start 2026-07-13 \
        --target competitive --daily-cap 5 --language python --lead dsa

Headless (the onboard Action): the four intake answers come from a file, no prompts:
    python scripts/bootstrap.py --intake intake.yml --non-interactive

Requires PyYAML:
    pip install pyyaml
(The daily engine also uses PyYAML via technique_coverage.py, which self-installs
it on first run — so this line covers the bootstrap step only; the hook is
self-sufficient.)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Git runs hooks with a cp1252 console on Windows; the first non-ASCII character printed
# would otherwise kill the script mid-run while the commit still succeeds. See _console.
import _console

_console.force_utf8()

try:
    import yaml
except ImportError:  # pragma: no cover
    raise SystemExit("bootstrap needs PyYAML for one-time setup: pip install pyyaml")

ROOT = Path(__file__).resolve().parents[1]
MILESTONE = ROOT / "curriculum" / "dsa" / "milestone.yml"
DSA_TRACKER = ROOT / "docs/foundations/dsa/mastery/dsa_progress.md"
STUDY_GUIDE = ROOT / "docs/foundations/dsa/study_guide.md"
CONFIG = ROOT / "cse.config.yml"
EXAMPLE_CONFIG = ROOT / "cse.config.example.yml"

TARGETS = ("fintech_interview", "faang_interview", "competitive")

DEFAULT_TIMEZONE = "UTC"
INTAKE_KEYS = frozenset({"name", "target", "timezone", "start_date"})
NAME_MIN_CHARS = 1
NAME_MAX_CHARS = 80
DEFAULT_DAILY_CAP = 5
MIN_REACH_BEYOND = 1
#: Gap between start_date and the first DSA mock: the example config's `dsa_mock.every_days`.
DSA_MOCK_FIRST_DUE_OFFSET_DAYS = 28
DAYS_PER_WEEK = 7
BUILD_ERROR_TAIL_LINES = 20

#: Tracker table rows (7 columns); a row with both date cells empty is the template's seed row.
TRACKER_COLUMNS = 7
NEXT_REVIEW_COLUMN = 4
LATEST_REP_COLUMN = 5


class IntakeError(ValueError):
    """The intake file is malformed; the message names the offending key."""


def ask(prompt: str, default: str) -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    return val or default


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--name")
    p.add_argument("--start")
    p.add_argument("--target", choices=TARGETS)
    p.add_argument("--daily-cap", type=int)
    p.add_argument("--language")
    p.add_argument("--lead", choices=["dsa", "system_design"])
    p.add_argument("--reach-beyond", type=int, default=1)
    p.add_argument("--sd-cadence",
                   choices=["mock_plus_deep_dive", "mock_only", "paused"],
                   default="mock_plus_deep_dive",
                   help="how the coach runs System Design mock interviews (default: "
                        "mock_plus_deep_dive — a Sunday cold mock plus a conditional midweek "
                        "deep-dive round; 'paused' schedules no SD slot)")
    p.add_argument("--non-interactive", action="store_true",
                   help="use defaults for anything not passed (no prompts)")
    p.add_argument("--intake", type=Path, metavar="PATH",
                   help="read name, target, timezone and start_date from this YAML file "
                        "(headless onboarding; no prompts)")
    return p.parse_args()


def _require_text(intake: dict, key: str) -> str:
    value = intake[key]
    if not isinstance(value, str):
        raise IntakeError(f"{key} must be text, got {type(value).__name__}")
    return value


def _parse_name(intake: dict) -> str:
    name = _require_text(intake, "name").strip()
    if not NAME_MIN_CHARS <= len(name) <= NAME_MAX_CHARS:
        raise IntakeError(f"name must be {NAME_MIN_CHARS}-{NAME_MAX_CHARS} characters "
                          f"after trimming, got {len(name)}")
    if not all(ch.isprintable() for ch in name):
        raise IntakeError("name must not contain control or non-printable characters")
    return name


def _parse_target(intake: dict) -> str:
    target = _require_text(intake, "target")
    if target not in TARGETS:
        raise IntakeError(f"target must be one of {', '.join(TARGETS)}, got {target!r}")
    return target


def _parse_timezone(intake: dict) -> str:
    zone = _require_text(intake, "timezone")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise IntakeError(f"timezone {zone!r} is not an IANA zone name ({e})") from e
    return zone


def _parse_start_date(intake: dict) -> date:
    value = intake["start_date"]
    # yaml.safe_load returns a date for an unquoted ISO date and a str for a quoted one.
    # A datetime (a timestamp) is a date subclass but is not an ISO date.
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise IntakeError(f"start_date must be an ISO date (YYYY-MM-DD), got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise IntakeError(f"start_date must be an ISO date (YYYY-MM-DD), got {value!r}") from e


def parse_intake(text: str) -> dict:
    """Validate an intake file's text and return the `gather`-shaped dict, plus
    `timezone` and `weekly_build`. Raises IntakeError naming the offending key."""
    try:
        intake = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise IntakeError(f"not valid YAML ({e})") from e
    if not isinstance(intake, dict):
        raise IntakeError("must be a mapping of name, target, timezone and start_date")
    missing = INTAKE_KEYS - intake.keys()
    if missing:
        raise IntakeError(f"missing key: {', '.join(sorted(missing))}")
    unknown = intake.keys() - INTAKE_KEYS
    if unknown:
        raise IntakeError(f"unknown key: {', '.join(sorted(map(str, unknown)))}")
    return {
        "name": _parse_name(intake),
        "start": _parse_start_date(intake).isoformat(),
        "target": _parse_target(intake),
        "timezone": _parse_timezone(intake),
        "daily_cap": DEFAULT_DAILY_CAP,
        "language": "python",
        "lead": "dsa",
        "reach_beyond": MIN_REACH_BEYOND,
        "sd_cadence": "paused",
        "weekly_build": True,
    }


def load_intake(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SystemExit(f"bootstrap: intake: cannot read {path}: {e}")
    try:
        return parse_intake(text)
    except IntakeError as e:
        raise SystemExit(f"bootstrap: intake: {e}")


def gather(a: argparse.Namespace) -> dict:
    d = {
        "name": a.name or "Learner",
        "start": a.start or date.today().isoformat(),
        "target": a.target or "competitive",
        "timezone": DEFAULT_TIMEZONE,
        "daily_cap": a.daily_cap or DEFAULT_DAILY_CAP,
        "language": a.language or "python",
        "lead": a.lead or "dsa",
        "reach_beyond": max(MIN_REACH_BEYOND, a.reach_beyond),  # floor enforced — 0 is rejected
        "sd_cadence": a.sd_cadence,
        "weekly_build": False,
    }
    if a.non_interactive:
        return d
    print("\ncse-coach setup — answer all at once (Enter accepts the default):\n")
    d["name"] = a.name or ask("What should I call you?", d["name"])
    d["start"] = a.start or ask("Start date (YYYY-MM-DD)", d["start"])
    d["target"] = a.target or ask(f"Target {TARGETS}", d["target"])
    d["daily_cap"] = a.daily_cap or int(ask("Problems per day (cap)", str(d["daily_cap"])))
    d["language"] = a.language or ask("Solution language", d["language"])
    d["lead"] = a.lead or ask("Which pillar leads (dsa/system_design)", d["lead"])
    return d


#: Substitutions applied to `cse.config.example.yml` to produce a learner's `cse.config.yml`.
#: Each pattern must match EXACTLY ONE line (see write_config's assertion) — anchored on the
#: key name, never on surrounding prose, so a comment edit to the example can't silently break
#: a substitution. Every untouched key (effort_budget's weights, intervals, gamification, …)
#: passes through from the example verbatim, so those two files can no longer drift apart —
#: the whole class of bug this replaces (see decisions.yml/self_eval for the Sep 22 bootstrap
#: drift: ceiling 9.0 vs 8.0, retire_at_streak vs graduate_at_streak, a missing gamification:
#: block, …) is now structurally impossible instead of re-synced by hand one field at a time.
CONFIG_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    (r'^learner:.*$', 'learner: {learner}'),
    (r'^start_date:.*$', 'start_date: {start}'),
    (r'^target:\s*\S+(?P<tail>.*)$', 'target: {target}{tail}'),
    (r'^reach_beyond:\s*\S+(?P<tail>.*)$', 'reach_beyond: {reach_beyond}{tail}'),
    (r'^daily_cap:\s*\S+(?P<tail>.*)$', 'daily_cap: {daily_cap}{tail}'),
    (r'^(?P<indent>\s*)priority:\s*\[.*?\](?P<tail>.*)$', '{indent}priority: [{priority}]{tail}'),
    (r'^(?P<indent>\s*)cadence:\s*\S+(?P<tail>.*)$', '{indent}cadence: {sd_cadence}{tail}'),
    (r'^(?P<indent>\s*)globs:\s*\[.*?\](?P<tail>.*)$', '{indent}globs: {globs}{tail}'),
    (r'^timezone:\s*\S+(?P<tail>.*)$', 'timezone: {timezone}{tail}'),
    (r'^(?P<indent>\s*)weekly_build:\s*\S+(?P<tail>.*)$', '{indent}weekly_build: {weekly_build}{tail}'),
    # The two PLACEHOLDER dates, filled in both modes (the start date is known and validated by
    # then). The explaining comment is dropped with the placeholder.
    (r'^(?P<indent>\s*)starts:\s*\S+.*$', '{indent}starts: {pattern_sense_starts}'),
    (r'^(?P<indent>\s*)first_due:\s*\S+.*$', '{indent}first_due: {dsa_mock_first_due}'),
)


def _substitute_line(template: str, values: dict) -> Callable[[re.Match], str]:
    """Build a `re.subn` replacement callback for one CONFIG_SUBSTITUTIONS entry.

    A FUNCTION callback, not a formatted string, on purpose: `re.sub` reinterprets
    backslashes and `\\g<name>` in a string `repl`, so a learner name containing either
    would corrupt the line. A callback's return value is inserted literally — no such
    interpretation — so it merges the match's own named groups (`indent`/`tail`, where the
    pattern captured them) with the intake `values` and formats once, safely.
    """
    def repl(m: re.Match) -> str:
        return template.format(**values, **m.groupdict())
    return repl


def _apply_substitutions(text: str, substitutions: tuple[tuple[str, str], ...],
                         values: dict) -> str:
    """Apply each (pattern, template) to exactly one line of `text`; return the new text."""
    for pattern, template in substitutions:
        # Counted BEFORE substituting, uncapped — `re.subn(..., count=1)` can only ever
        # report 0 or 1, so it cannot detect a pattern that became ambiguous (a second
        # matching line). This counts every match first, so 0 and 2+ are told apart.
        match_count = len(re.findall(pattern, text, flags=re.MULTILINE))
        if match_count == 0:
            raise SystemExit(
                f"bootstrap: {pattern!r} matched no line in {EXAMPLE_CONFIG.name} — the "
                "example file's key was renamed or removed. Update CONFIG_SUBSTITUTIONS "
                "in scripts/bootstrap.py to match its new shape."
            )
        if match_count > 1:
            raise SystemExit(
                f"bootstrap: {pattern!r} matched {match_count} lines in "
                f"{EXAMPLE_CONFIG.name} — it is no longer unique (the example likely grew "
                "a second line with this key, e.g. a second solutions root or pillar). "
                "Narrow the pattern in CONFIG_SUBSTITUTIONS so it targets the right one."
            )
        text = re.sub(pattern, _substitute_line(template, values), text, count=1,
                      flags=re.MULTILINE)
    return text


def monday_on_or_after(day: date) -> date:
    return day + timedelta(days=(-day.weekday()) % DAYS_PER_WEEK)


def monday_of_week(day: date) -> date:
    return day - timedelta(days=day.weekday())


def write_config(d: dict) -> None:
    globs = {"python": '["*.py"]', "java": '["*.java"]', "typescript": '["*.ts"]',
             "cpp": '["*.cpp"]', "go": '["*.go"]'}.get(d["language"], '["*.py"]')
    priority = ", ".join([d["lead"]] + [p for p in ("dsa", "system_design") if p != d["lead"]])
    start = date.fromisoformat(d["start"])
    values = {**d, "globs": globs, "priority": priority,
              # A JSON string is a valid YAML double-quoted scalar: quotes and backslashes escape.
              "learner": json.dumps(d["name"], ensure_ascii=False),
              "weekly_build": str(d["weekly_build"]).lower(),
              "pattern_sense_starts": monday_on_or_after(start).isoformat(),
              "dsa_mock_first_due":
                  (start + timedelta(days=DSA_MOCK_FIRST_DUE_OFFSET_DAYS)).isoformat()}

    text = _apply_substitutions(EXAMPLE_CONFIG.read_text(encoding="utf-8"),
                                CONFIG_SUBSTITUTIONS, values)
    CONFIG.write_text(text, encoding="utf-8")


def project_roadmap(start: date) -> list[dict]:
    data = yaml.safe_load(MILESTONE.read_text(encoding="utf-8"))
    tier_pace = data.get("tier_pace", {"moderate": 5, "hard": 4, "hardest": 3})
    default_pace = data.get("default_pace_per_week", 5)
    rows, cursor = [], start
    for phase in data["phases"]:
        n = len(phase["problems"])
        # difficulty_tier drives pace (via tier_pace); an explicit pace_per_week overrides it.
        pace = phase.get("pace_per_week") or tier_pace.get(phase.get("difficulty_tier")) or default_pace
        weeks = max(1, math.ceil(n / pace))
        end = cursor + timedelta(weeks=weeks) - timedelta(days=1)
        rows.append({"name": phase["name"], "start": cursor, "end": end,
                     "count": n, "pace": pace, "problems": phase["problems"]})
        cursor = end + timedelta(days=1)
    return rows


def write_study_guide(d: dict, roadmap: list[dict]) -> None:
    lines = [
        "# DSA Study Guide — projected roadmap",
        "",
        f'For **{d["name"]}**, starting **{d["start"]}**. Target: **{d["target"]}** '
        f'(reach_beyond {d["reach_beyond"]}). See [PHILOSOPHY](../../PHILOSOPHY.md) for the '
        "why (Interview-ROI line, comfort system, reach-beyond).",
        "",
        "> Dates are a plan, not a deadline. The spaced-repetition tracker is the source",
        "> of truth; the weekly schedules reflect it. Phases complete when every problem",
        "> is 🏆 Retired — not when attempted once.",
        "",
        "| Phase | Dates | New problems | Pace/wk |",
        "|-------|-------|--------------|---------|",
    ]
    for r in roadmap:
        lines.append(f'| {r["name"]} | {r["start"]:%Y-%m-%d} → {r["end"]:%Y-%m-%d} '
                     f'| {r["count"]} | {r["pace"]} |')
    lines += ["", "After the milestone: expansion Tier 1 (above the ROI line), then Tier 2 "
              "for competitive depth — see `../../../curriculum/`.", ""]
    STUDY_GUIDE.write_text("\n".join(lines), encoding="utf-8")


def strip_placeholder_rows(text: str) -> str:
    """Drop tracker table rows whose Next Review Date and Latest Rep Date are both empty.

    Only rows of the 7-column tracker table qualify; the summary table above it has a
    different column count, and the header and separator rows carry text in those cells."""
    kept = []
    for line in text.splitlines(keepends=True):
        cells = line.strip().strip("|").split("|") if line.lstrip().startswith("|") else []
        is_placeholder = (
            len(cells) == TRACKER_COLUMNS
            and not cells[NEXT_REVIEW_COLUMN].strip()
            and not cells[LATEST_REP_COLUMN].strip()
        )
        if not is_placeholder:
            kept.append(line)
    return "".join(kept)


def reset_tracker() -> None:
    cleaned = strip_placeholder_rows(DSA_TRACKER.read_text(encoding="utf-8"))
    DSA_TRACKER.write_text(cleaned, encoding="utf-8", newline="\n")


def run_build_week(start: date) -> str:
    """Build the week of `start` with build_week.py and return its `built:`/`skipped:` output.

    `--week` is passed so a clone (whose config has `weekly_build: false`) still gets
    week 1."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_week.py"),
         "--week", monday_of_week(start).isoformat()],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        output = (result.stderr.strip() or result.stdout.strip()).splitlines()
        tail = "\n".join(output[-BUILD_ERROR_TAIL_LINES:])
        raise SystemExit(f"bootstrap: build_week.py failed (exit {result.returncode}):\n{tail}")
    return result.stdout.strip()


def install_hook() -> None:
    """Set up git for the learner — they only invoke setup, nothing else.

    Initializes the repo if needed, then points git at the version-controlled
    hook so the spaced-repetition trackers auto-update on every commit.
    """
    try:
        if not (ROOT / ".git").exists():
            subprocess.run(["git", "init"], cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"],
                       cwd=ROOT, check=True, capture_output=True)
    except Exception as e:  # pragma: no cover
        print(f"  (could not set up git automatically: {e})")


def main() -> None:
    args = parse_args()
    is_intake = args.intake is not None
    d = load_intake(args.intake) if is_intake else gather(args)
    start = datetime.strptime(d["start"], "%Y-%m-%d").date()
    write_config(d)
    roadmap = project_roadmap(start)
    write_study_guide(d, roadmap)
    reset_tracker()
    build_line = run_build_week(start)
    install_hook()

    first = roadmap[0]["problems"][0]
    print(f"\n  You're set, {d['name']}. Wrote cse.config.yml, your roadmap, and week 1.")
    print(f"  Hook installed. First up: {first['number']}. {first['title']}.")
    print(f"  {build_line}")
    print("  When you finish a problem, just tell the coach: Clean, Shaky, or Blank.\n")


if __name__ == "__main__":
    main()
