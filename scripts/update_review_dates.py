from __future__ import annotations

import argparse
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

# Running this as a script puts scripts/ on sys.path automatically; loading it as a module
# (the template's tests, or any importer) does not. This guard keeps `import session_date`
# resolvable in both — a distribution requirement the practice repo doesn't need but the
# shipped test harness does.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import session_date  # noqa: E402
from new_problem import slice_has_real_attempt  # noqa: E402

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()

# Session "now", resolved once in main(). A study session that crosses midnight keeps
# its START date, so stamping attempt dates from the wall clock silently mis-dates every
# row written after 00:00 — see scripts/session_date.py and feedback_session_dating.
_SESSION_NOW: datetime | None = None


def session_now() -> datetime:
    """The session's 'today'. Use this instead of datetime.now() for anything stamped."""
    return _SESSION_NOW or session_date.resolve_datetime()

# --- Configuration -----------------------------------------------------------
# Defaults reproduce cse-progress's original behavior exactly. cse.config.yml (if
# present at the repo root) overrides intervals, source root, and solution globs.
# Parsed with stdlib only (no PyYAML dependency) for the small subset we need.

DEFAULT_CONFIG = {
    "source_root": "dsa/leetcode",
    "source_globs": ["*.py"],
    "clean_provisional": 10,  # first Clean right after a Blank (streak 0) — lock-down check
    "clean_streak1": 30,
    "clean_streak2": 60,
    "graduated": 180,  # 🎓 streak-3 tier: recurring spot check
    "shaky": 10,
    "blank": 2,
    "graduate_at_streak": 3,
    "discovery_skip": [],  # problem numbers whose source files should NOT be auto-added
}


def load_config(path: Path = Path("cse.config.yml")) -> dict:
    """Read intervals, source root and globs from cse.config.yml.

    ⚠️ **Structured keys are read with a real YAML parser; the regex scrape below is only
    a fallback for when PyYAML is unavailable.** It used to be the *only* path, and that
    was a live hazard rather than a theoretical one: on Aug 7, 2026 an unrelated
    `effort_budget` block was added to the config containing effort WEIGHTS —

        comfort_base: {blank: 3.0, shaky: 2.0, clean: 1.0, graduated: 0.5}

    — and the scraper, which searches the whole file text with no notion of nesting,
    read `shaky: 2.0` as the Shaky INTERVAL (10 days -> 2) and `graduated: 0.5` as the
    Graduated interval (180 days -> 0). Three rows were silently rewritten to wrong
    review dates in the same commit that introduced the block. Nothing errored.

    A flat regex over a nested document cannot tell "the interval named shaky" from "some
    other mapping that happens to contain the word shaky", so it will mis-read any future
    addition that reuses a word. Parse the structure when we can.
    """
    cfg = dict(DEFAULT_CONFIG)
    if not path.exists():
        return cfg
    text = path.read_text(encoding="utf-8")

    try:
        import yaml  # noqa: PLC0415
        doc = yaml.safe_load(text) or {}
    except Exception:  # noqa: BLE001 — PyYAML missing or the file is mid-edit
        doc = None

    if isinstance(doc, dict):
        intervals = doc.get("intervals") or {}
        if isinstance(intervals, dict):
            clean = intervals.get("clean") if isinstance(intervals.get("clean"), dict) else {}

            def _first(*candidates):
                """First non-None candidate. The graduated interval has lived in three
                places across the Jul 26, 2026 rename — `intervals.clean.retired`,
                `intervals.clean.graduated`, and `intervals.graduated` — and all three
                appear in configs in the wild, so all three are honoured."""
                for c in candidates:
                    if isinstance(c, (int, float)):
                        return c
                return None

            pairs = [
                (_first(clean.get("provisional")), "clean_provisional"),
                (_first(clean.get("streak1")), "clean_streak1"),
                (_first(clean.get("streak2")), "clean_streak2"),
                (_first(clean.get("graduated"), clean.get("retired"),
                        intervals.get("graduated"), intervals.get("retired")), "graduated"),
                (_first(intervals.get("shaky")), "shaky"),
                (_first(intervals.get("blank")), "blank"),
            ]
            for value, key in pairs:
                if isinstance(value, (int, float)):
                    cfg[key] = int(value)
        for key, cfg_key in (("graduate_at_streak", "graduate_at_streak"),
                             ("retire_at_streak", "graduate_at_streak")):
            if isinstance(doc.get(key), int):
                cfg[cfg_key] = doc[key]
        solutions = doc.get("solutions") or {}
        if isinstance(solutions, dict):
            if solutions.get("globs"):
                cfg["source_globs"] = list(solutions["globs"])
            if solutions.get("roots"):
                cfg["source_root"] = str(solutions["roots"][0])
        if isinstance(doc.get("discovery_skip"), list):
            cfg["discovery_skip"] = [int(x) for x in doc["discovery_skip"]
                                     if isinstance(x, int) or str(x).isdigit()]
        return cfg

    # ---- Fallback: no PyYAML. Same scrape as before, with the same known weakness. ----
    def _int(pattern: str, key: str) -> None:
        m = re.search(pattern, text)
        if m:
            cfg[key] = int(m.group(1))

    def _list(pattern: str) -> list[str] | None:
        m = re.search(pattern, text)
        if not m:
            return None
        items = [x.strip().strip("'\"") for x in m.group(1).split(",")]
        return [x for x in items if x]

    _int(r"provisional:\s*(\d+)", "clean_provisional")
    _int(r"streak1:\s*(\d+)", "clean_streak1")
    _int(r"streak2:\s*(\d+)", "clean_streak2")
    # Accept the pre-Jul-26-2026 key names too, so an older cse.config.yml keeps working.
    _int(r"retired:\s*(\d+)", "graduated")
    _int(r"graduated:\s*(\d+)", "graduated")
    _int(r"\bshaky:\s*(\d+)", "shaky")
    _int(r"\bblank:\s*(\d+)", "blank")
    _int(r"retire_at_streak:\s*(\d+)", "graduate_at_streak")
    _int(r"graduate_at_streak:\s*(\d+)", "graduate_at_streak")

    globs = _list(r"globs:\s*\[([^\]]*)\]")
    if globs:
        cfg["source_globs"] = globs
    roots = _list(r"roots:\s*\[([^\]]*)\]")
    if roots:
        cfg["source_root"] = roots[0]
    skip = _list(r"discovery_skip:\s*\[([^\]]*)\]")
    if skip is not None:
        cfg["discovery_skip"] = [int(x) for x in skip if x.isdigit()]
    return cfg


CONFIG = load_config()

MARKDOWN_PATH = Path("docs/foundations/dsa/mastery/dsa_progress.md")
SOURCE_ROOT = Path(CONFIG["source_root"])
TABLE_HEADER = "| Difficulty | Problem | Comfort | Streak | Next Review Date | Latest Rep Date | Rep Dates |"
# "Attempt" → "Rep" rename, Aug 9, 2026 (see build_summary_lines). Both older spellings stay RECOGNIZED
# so an un-migrated tracker still parses; the migration block near the end of rewrite_table() upgrades
# whichever it finds to TABLE_HEADER. Never drop these — a header this function can't match makes the
# whole table invisible, and the pre-commit hook would then rewrite the file without it.
TABLE_HEADER_ATTEMPT_ERA = "| Difficulty | Problem | Comfort | Streak | Next Review Date | Latest Attempt Date | Attempt Dates |"
TABLE_HEADER_LEGACY = "| Difficulty | Problem | Comfort | Next Review Date | Latest Attempt Date | Attempt Dates |"
# Every header spelling that carries a Streak column (i.e. everything except the 6-column legacy form).
TABLE_HEADERS_CURRENT = (TABLE_HEADER, TABLE_HEADER_ATTEMPT_ERA)
# Every header spelling this parser accepts, in any era.
TABLE_HEADERS_ALL = (TABLE_HEADER, TABLE_HEADER_ATTEMPT_ERA, TABLE_HEADER_LEGACY)
ROW_SEPARATOR = "|---|---|---|---|---|---|---|"
ROW_SEPARATOR_LEGACY = "|---|---|---|---|---|---|"

COMFORT_CLEAN = "🟢"
COMFORT_SHAKY = "🟡"
COMFORT_BLANK = "🔴"
# 🎓 Graduated = streak-3 tier, recurring +180 spot checks. Still IN this table.
COMFORT_GRADUATED = "🎓"
# 🏆 Retired = TERMINAL. Earned by two clean spot checks at 🎓; leaves the review table
# entirely for the plain-list "## 🏆 Retired" section, so it normally has no rows here.
# Kept parseable so a legacy 🏆 row (pre-Jul 26 2026 naming, when 🏆 meant the streak-3
# tier) still parses and is treated as 🎓 rather than being silently dropped.
COMFORT_RETIRED = "🏆"
COMFORT_VALUES = f"{COMFORT_CLEAN}|{COMFORT_SHAKY}|{COMFORT_BLANK}|{COMFORT_GRADUATED}|{COMFORT_RETIRED}"

ROW_RE = re.compile(
    r"^\| (?P<difficulty>[^|]+) \| \[(?P<problem>[^\]]+)\]\((?P<url>[^)]+)\) \| (?P<comfort>" + COMFORT_VALUES + r") \| (?P<streak>\d+) \| (?P<next>[^|]*) \| (?P<latest>[^|]*) \| (?P<attempts>.*) \|$"
)
ROW_RE_LEGACY = re.compile(
    r"^\| (?P<difficulty>[^|]+) \| \[(?P<problem>[^\]]+)\]\((?P<url>[^)]+)\) \| (?P<comfort>🟢|🟡|🔴) \|\s*(?P<next>[^|]*?)\s*\|\s*(?P<latest>[^|]*?)\s*\|\s*(?P<attempts>.*?)\s*\|$"
)
# Permissive variant for git diff output — streak field is optional
DIFF_ROW_RE = re.compile(
    r"^\| (?P<difficulty>[^|]+) \| \[(?P<problem>[^\]]+)\]\((?P<url>[^)]+)\) \| (?P<comfort>[^|]+) \| (?:(?P<streak>\d+) \| )?(?P<next>[^|]*) \| (?P<latest>[^|]*) \| (?P<attempts>.*) \|$"
)
# Extensions come from CONFIG["source_globs"] (e.g. ["*.py", "*.java"]) so the
# engine is language-agnostic; defaults to Python only.
_EXTENSIONS = sorted({g.rsplit(".", 1)[-1] for g in CONFIG["source_globs"] if "." in g})
_EXT_ALT = "|".join(re.escape(e) for e in _EXTENSIONS) or "py"
SOURCE_FILE_RE = re.compile(r"^(?P<number>\d+)_(?P<name>.+)\.(?:" + _EXT_ALT + r")$")
SOURCE_GLOBS = CONFIG["source_globs"]


def all_source_files() -> list[Path]:
    """All solution files under SOURCE_ROOT matching the configured globs."""
    seen: dict[str, Path] = {}
    for glob in SOURCE_GLOBS:
        for path in SOURCE_ROOT.rglob(glob):
            seen[path.as_posix()] = path
    return list(seen.values())


# Problems with source files that should NOT be auto-discovered (curriculum items
# that will re-enter the tracker naturally when the user solves and logs them).
DISCOVERY_SKIP_NUMBERS: set[int] = set(CONFIG["discovery_skip"])
ROMAN_NUMERALS = {
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
    "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx",
}


def parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value or value == "Not Attempted":
        return None
    return datetime.strptime(value, "%Y-%m-%d")


def format_date(date: datetime | None) -> str:
    return date.strftime("%Y-%m-%d") if date else ""


def parse_latest_attempt_date_from_attempts(attempts: str) -> datetime | None:
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", attempts)
    parsed_dates = []
    for date_text in dates:
        try:
            parsed_dates.append(datetime.strptime(date_text, "%Y-%m-%d"))
        except ValueError:
            continue
    return max(parsed_dates) if parsed_dates else None


def extract_problem_number(problem_title: str) -> int | None:
    match = re.match(r"^(?P<number>\d+)\.", problem_title)
    if not match:
        return None
    return int(match.group("number"))


def compute_next_review_date(comfort: str, latest_attempt_date: datetime | None, streak: int = 1) -> datetime | None:
    if not latest_attempt_date:
        return None
    if comfort in (COMFORT_CLEAN, COMFORT_GRADUATED, COMFORT_RETIRED):
        if comfort == COMFORT_CLEAN and streak == 0:
            # Provisional Clean: a 🟢 logged with streak 0 is the FIRST Clean directly
            # following a 🔴 Blank. One Clean right after a Blank may be recall of fresh
            # teaching, not durable retention, so it gets a short lock-down (+10) to verify
            # before earning the normal +30. Survives (Clean again) → log streak 1 → +30.
            days = CONFIG["clean_provisional"]
        elif streak >= CONFIG["graduate_at_streak"]:
            days = CONFIG["graduated"]  # 🎓 recurring spot check
        elif streak == 2:
            days = CONFIG["clean_streak2"]
        else:
            days = CONFIG["clean_streak1"]
    elif comfort == COMFORT_SHAKY:
        days = CONFIG["shaky"]
    else:  # BLANK
        days = CONFIG["blank"]
    return latest_attempt_date + timedelta(days=days)


# --- Holds -------------------------------------------------------------------
# A learner-requested deferral past the ladder date lives in holds.yml, never as a typed
# tracker date (the tracker recomputes Next from the ladder on every run). Next Review =
# max(ladder date, hold `until`); a hold whose date has passed falls out of the max.
HOLDS_PATH = MARKDOWN_PATH.parent / "holds.yml"
HOLD_DATE_FIELDS = ("until", "since")


class HoldsError(ValueError):
    """holds.yml is malformed, or names a row the tracker does not have."""


def _hold_date_text(label: str, field: str, value: object) -> str:
    if isinstance(value, date):  # PyYAML turns an unquoted YYYY-MM-DD into a date
        return value.isoformat()
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise HoldsError(f"hold {label}: `{field}` must be a YYYY-MM-DD date, got {value!r}")


def _parse_hold_entry(index: int, entry: object) -> tuple[str, str]:
    if not isinstance(entry, dict):
        raise HoldsError(f"hold #{index}: entry must be a mapping, got {type(entry).__name__}")
    row = entry.get("row")
    if not isinstance(row, str) or not row.strip():
        raise HoldsError(f"hold #{index}: `row` must be the tracker row's problem title")
    label = repr(row.strip())
    why = entry.get("why")
    if not isinstance(why, str) or not why.strip():
        raise HoldsError(f"hold {label}: `why` must name a decision id")
    dates = {field: _hold_date_text(label, field, entry.get(field)) for field in HOLD_DATE_FIELDS}
    return row.strip(), dates["until"]


def load_holds(path: Path = HOLDS_PATH) -> dict[str, str]:
    """Row title -> `until` (YYYY-MM-DD). No file means no holds."""
    if not path.exists():
        return {}
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(doc, list):
        raise HoldsError("top level must be a list of hold entries")
    holds: dict[str, str] = {}
    for index, entry in enumerate(doc, start=1):
        row, until = _parse_hold_entry(index, entry)
        if row in holds:
            raise HoldsError(f"hold {row!r}: listed twice")
        holds[row] = until
    return holds


def apply_holds(table_rows: list[dict], holds: dict[str, str]) -> list[dict]:
    """New rows with Next Review = max(ladder date, hold `until`)."""
    unmatched = sorted(set(holds) - {row["problem"].strip() for row in table_rows})
    if unmatched:
        raise HoldsError(f"hold {unmatched[0]!r}: matches no tracker row")
    return [
        {**row, "next_review": max(row["next_review"], holds.get(row["problem"].strip(), ""))}
        for row in table_rows
    ]


def count_attempt_dates(attempts: str) -> int:
    return len([part for part in attempts.split(",") if part.strip()])


def count_retired_entries(lines: list[str]) -> int:
    """Count entries in the terminal '## 🏆 Retired' section.

    Retired problems have LEFT the review table (that is what retiring means), so they
    cannot be counted from table_rows. The section is a plain bullet list precisely so
    this parser never mistakes it for table rows — see the tracker's header notes.
    """
    count = 0
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.startswith(f"## {COMFORT_RETIRED}")
            continue
        if in_section and re.match(r"^- \d+\.", stripped):
            count += 1
    return count


def count_rowless_probes(readme: Path = SOURCE_ROOT.parent / "probes" / "README.md") -> int:
    """Count disposable probes that were SOLVED but earn no tracker row.

    A clean 🟢 probe (and a 🟡/🔴 the learner overrode) creates no row in dsa_progress.md by design —
    so it is invisible to the `unique_problems` count above, which only sees the table. The probe log
    table in dsa/probes/README.md is the authority; a row counts here when it has a real result
    (🟢/🟡/🔴, i.e. not a *pending* probe) AND its "Tracker row?" cell is not a ✅. Purely additive:
    the tracker never contains these, so there is no double-counting.

    Defensive on purpose — a missing file, a renamed section, or a reformatted table returns 0 rather
    than raising, because this runs from the pre-commit hook and must never block a commit.
    """
    try:
        text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    results = {COMFORT_CLEAN, COMFORT_SHAKY, COMFORT_BLANK}
    count = 0
    in_log = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_log = "Probe log" in line
            continue
        if not in_log or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        result, tracker = cells[4], cells[5]
        if any(r in result for r in results) and "✅" not in tracker:
            count += 1
    return count


def build_summary_lines(table_rows: list[dict], retired: int = 0) -> list[str]:
    attempted_rows = [row for row in table_rows if row["latest"] is not None]
    unique_problems = len({
        extract_problem_number(row["problem"])
        for row in attempted_rows
        if extract_problem_number(row["problem"]) is not None
    })
    solutions_done = len(attempted_rows)
    rowless_probes = count_rowless_probes()
    _p = f"+{rowless_probes}" if rowless_probes else ""  # the `+N` probe-fold suffix, shared by all three counts
    total_attempts = sum(count_attempt_dates(row["attempts"]) for row in table_rows)
    clean = sum(1 for row in table_rows if row["comfort"] == COMFORT_CLEAN)
    shaky = sum(1 for row in table_rows if row["comfort"] == COMFORT_SHAKY)
    blank = sum(1 for row in table_rows if row["comfort"] == COMFORT_BLANK and row["latest"] is not None)
    # A legacy 🏆 row (pre-Jul-26-2026, when 🏆 meant the streak-3 tier) counts as 🎓.
    graduated = sum(
        1 for row in table_rows
        if row["comfort"] in (COMFORT_GRADUATED, COMFORT_RETIRED)
    )
    return [
        "",
        # "reps", not "attempts" (renamed Aug 9, 2026 at the learner's request): an *attempt* connotes
        # trying and possibly failing, and the code gets written every time — what varies is the rating,
        # not whether a solution happened. "Rep" is also the vocabulary the rest of the system already
        # uses. Only the label changed; the count is still one per dated entry in `Attempt Dates`.
        # All three counts see only the table below. Disposable 🟢 probes earn no row, so each is folded
        # in as `base+4` (source: the probe log in dsa/probes/README.md) — one rowless probe is one
        # problem, one solution, AND one rep (a single cold attempt). The base is the review-rotation
        # count; the `+N` is the probe-only work. `+N` is omitted from all three when there are none.
        (
            f"> **{unique_problems}{_p}** problems "
            f"&nbsp;·&nbsp; **{solutions_done}{_p}** solutions "
            f"&nbsp;·&nbsp; **{total_attempts}{_p}** reps"
        ),
        "",
        f"| | {COMFORT_RETIRED} Retired | {COMFORT_GRADUATED} Graduated | {COMFORT_CLEAN} Clean | {COMFORT_SHAKY} Shaky | {COMFORT_BLANK} Blank |",
        "|:---|:---:|:---:|:---:|:---:|:---:|",
        f"| **Solutions** | {retired} | {graduated} | {clean} | {shaky} | {blank} |",
        "",
    ]


def humanize_raw_name(raw_name: str) -> str:
    tokens = raw_name.split("_")
    normalized_tokens: list[str] = []
    for token in tokens:
        lower = token.lower()
        if lower in ROMAN_NUMERALS:
            normalized_tokens.append(lower.upper())
        else:
            normalized_tokens.append(token.capitalize())
    return " ".join(normalized_tokens)


def build_row(entry: dict) -> str:
    return (
        f"| {entry['difficulty']} | [{entry['problem']}]({entry['url']})"
        f" | {entry['comfort']} | {entry['streak']} | {entry['next_review']} | {entry['latest_attempt_date']} | {entry['attempts']} |"
    )


# Header line: `9001. Single Source Shortest Path, Negative Weights   ·   https://open.kattis.com/…`
# — same shape as links.py's HEADER (the `·` and the URL are both optional there too), parsed
# independently here so update_review_dates.py carries no import dependency on links.py.
HEADER_URL_RE = re.compile(r"^\s*\d{1,4}\.\s+.+?(?:\s+·\s+(https?://\S+))?\s*$")


def extract_url_from_source(path: Path) -> str | None:
    """The problem-page URL recorded in the file's own header line, or None if absent.

    Scans only the FIRST docstring block (the module header) — same scope as
    extract_difficulty_from_source. A problem hand-picked from a non-LeetCode judge
    (Kattis, CSES, …) carries its real URL only here; discover_source_problems() uses it
    for the auto-row so that URL is never silently overwritten by the LeetCode-slug guess.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    parts = content.split('"""')
    block = parts[1] if len(parts) >= 2 else content
    for line in block.splitlines():
        match = HEADER_URL_RE.match(line)
        if match and match.group(1):
            return match.group(1).rstrip(".,;)")
    return None


def extract_difficulty_from_source(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    top_doc = re.match(r"^\s*(['\"]{3})(.*?)(\1)", content, re.DOTALL)
    if top_doc:
        body = top_doc.group(2).strip().splitlines()
        for line in body:
            candidate = line.strip()
            if not candidate:
                continue
            normalized = candidate.lower()
            if normalized in {"easy", "medium", "hard"}:
                return candidate.capitalize()
            if any(word in normalized for word in ["easy", "medium", "hard"]):
                for token in normalized.split():
                    if token in {"easy", "medium", "hard"}:
                        return token.capitalize()
            break

    for line in content.splitlines()[:20]:
        candidate = line.strip().lower()
        if candidate.startswith("#"):
            candidate = candidate[1:].strip()
        if candidate in {"easy", "medium", "hard"}:
            return candidate.capitalize()
        if "difficulty" in candidate:
            for token in candidate.split():
                if token in {"easy", "medium", "hard"}:
                    return token.capitalize()
    return None


def get_staged_paths() -> tuple[list[Path], bool]:
    try:
        output = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            text=True,
            encoding="utf-8",
            cwd=Path.cwd(),
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [], False

    staged_paths: list[Path] = []
    markdown_staged = False
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        normalized = line.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized == MARKDOWN_PATH.as_posix():
            markdown_staged = True
            continue
        if not any(normalized.endswith("." + e) for e in _EXTENSIONS):
            continue
        path = Path(normalized)
        try:
            path.relative_to(SOURCE_ROOT)
        except ValueError:
            continue
        staged_paths.append(path)
    return staged_paths, markdown_staged


def get_staged_rows_with_changed_attempts() -> set[str]:
    """Return problem titles for rows that are brand new in the staged diff."""
    try:
        output = subprocess.check_output(
            ["git", "diff", "--cached", "--unified=0", "--", str(MARKDOWN_PATH)],
            text=True,
            encoding="utf-8",
            cwd=Path.cwd(),
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()

    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    for line in output.splitlines():
        if not (line.startswith("-| ") or line.startswith("+| ")):
            continue
        raw_line = line[1:]
        match = DIFF_ROW_RE.match(raw_line)
        if not match:
            continue
        title = match.group("problem").strip().lower()
        attempts = match.group("attempts").strip()
        if line.startswith("-| "):
            removed[title] = attempts
        else:
            added[title] = attempts

    new_rows: set[str] = set()
    for title in added:
        if title not in removed:
            new_rows.add(title)
    return new_rows


def get_staged_problem_numbers(staged_files: list[Path]) -> set[int]:
    numbers: set[int] = set()
    for path in staged_files:
        match = SOURCE_FILE_RE.match(path.name)
        if match:
            numbers.add(int(match.group("number")))
    return numbers


def fill_current_date_for_staged_rows(
    table_rows: list[dict],
    staged_files: list[Path] | None = None,
    staged_markdown_titles: set[str] | None = None,
) -> int:
    if not staged_files and not staged_markdown_titles:
        return 0

    staged_numbers = get_staged_problem_numbers(staged_files) if staged_files else set()
    now = session_now()
    updated_count = 0

    for row in table_rows:
        problem_title_low = row["problem"].strip().lower()
        is_staged = False

        if staged_markdown_titles:
            is_staged = problem_title_low in staged_markdown_titles
        elif staged_numbers:
            match = re.match(r"^(?P<number>\d+)\.", row["problem"])
            if match:
                number = int(match.group("number"))
                is_staged = number in staged_numbers

        if not is_staged:
            continue

        if row["latest"] is not None:
            continue

        attempts = [part.strip() for part in row["attempts"].split(",") if part.strip()]
        today_text = format_date(now)

        if today_text not in attempts:
            attempts.append(today_text)
            row["attempts"] = ", ".join(attempts)
            row["latest"] = now
            row["latest_attempt_date"] = format_date(now)
            row["next_review"] = format_date(compute_next_review_date(row["comfort"], now, row["streak"]))
            updated_count += 1

    return updated_count


def update_existing_row_difficulties(table_rows: list[dict], staged_files: list[Path] | None = None) -> int:
    row_number_to_indices: dict[int, list[int]] = {}
    for index, row in enumerate(table_rows):
        match = re.match(r"^(?P<number>\d+)\.", row["problem"])
        if match:
            number = int(match.group("number"))
            row_number_to_indices.setdefault(number, []).append(index)

    if not row_number_to_indices:
        return 0

    paths = all_source_files() if staged_files is None else staged_files
    updated_count = 0
    for path in paths:
        match = SOURCE_FILE_RE.match(path.name)
        if not match:
            continue
        number = int(match.group("number"))
        row_indices = row_number_to_indices.get(number)
        if not row_indices:
            continue

        difficulty = extract_difficulty_from_source(path)
        if not difficulty:
            continue

        for row_index in row_indices:
            if table_rows[row_index]["difficulty"] == "Unknown":
                table_rows[row_index]["difficulty"] = difficulty
                updated_count += 1

    return updated_count


def has_real_attempt(path: Path) -> bool:
    """True if the file holds a real attempt; a non-UTF-8 file counts as one (old behavior)."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return True
    return slice_has_real_attempt(text.splitlines())


def discover_source_problems(existing_titles: set[str], staged_files: list[Path] | None = None) -> list[dict]:
    missing_rows: list[dict] = []
    if staged_files is None:
        paths = all_source_files()
    else:
        paths = staged_files

    use_today = staged_files is not None
    now = session_now() if use_today else None

    existing_numbers = {
        extract_problem_number(title)
        for title in existing_titles
        if extract_problem_number(title) is not None
    }

    for path in paths:
        match = SOURCE_FILE_RE.match(path.name)
        if not match:
            continue
        number = int(match.group("number"))
        raw_name = match.group("name")
        title = humanize_raw_name(raw_name)
        problem_title = f"{number}. {title}"
        if problem_title.lower() in existing_titles:
            continue
        if number in existing_numbers:
            continue
        if number in DISCOVERY_SKIP_NUMBERS:
            continue
        # A scaffolded-but-never-attempted file (every body `pass`) is not a rep: a row for
        # it is phantom (references/scaffolding.md, blast radius). Unreadable → discovered.
        if not has_real_attempt(path):
            continue
        difficulty = extract_difficulty_from_source(path) or "Unknown"
        slug = raw_name.lower().replace("_", "-")
        # The header's own URL wins — it's the only correct source for a problem hand-picked
        # from a non-LeetCode judge (Kattis, CSES, …); the LC slug guess is the fallback,
        # exactly as before, for a file with no header URL.
        url = extract_url_from_source(path) or f"https://leetcode.com/problems/{slug}/"
        missing_rows.append({
            "difficulty": difficulty,
            "problem": problem_title,
            "url": url,
            "comfort": COMFORT_BLANK,
            "streak": 0,
            "latest": now,
            "latest_attempt_date": format_date(now) if now else "",
            "attempts": format_date(now) if now else "",
            "next_review": format_date(compute_next_review_date("N", now)) if now else "",
        })
        existing_titles.add(problem_title.lower())
        existing_numbers.add(number)
    return missing_rows


def recompute_simple(tracker_path: Path) -> None:
    """Recompute next-review dates and re-sort a same-format tracker WITHOUT
    source discovery. Used for the System Design / AI trackers, whose units are
    systems/capabilities (reviewed by blind sprint), not source files. Same
    7-column table and same interval math as the DSA tracker; the DSA main() is
    left untouched. Prefix (incl. header/separator) and suffix are preserved."""
    if not tracker_path.exists():
        return
    lines = tracker_path.read_text(encoding="utf-8").splitlines()
    prefix_lines: list[str] = []
    table_rows: list[dict] = []
    suffix_lines: list[str] = []
    in_table = header_seen = separator_seen = False

    for line in lines:
        if not in_table:
            prefix_lines.append(line)
            if line.strip() in TABLE_HEADERS_ALL:
                in_table = header_seen = True
            continue
        if not separator_seen:
            if line.strip() in (ROW_SEPARATOR, ROW_SEPARATOR_LEGACY):
                separator_seen = True
            prefix_lines.append(line)
            continue
        m = ROW_RE.match(line) if line.startswith("|") else None
        lm = ROW_RE_LEGACY.match(line) if (line.startswith("|") and not m) else None
        match = m or lm
        if not match:
            suffix_lines.append(line)
            continue
        comfort = match.group("comfort").strip()
        streak = int(match.group("streak")) if m else (1 if comfort == COMFORT_CLEAN else 0)
        latest = parse_date(match.group("latest"))
        attempts = match.group("attempts").strip()
        attempts_latest = parse_latest_attempt_date_from_attempts(attempts)
        if latest is None or (attempts_latest is not None and attempts_latest > latest):
            latest = attempts_latest
        table_rows.append({
            "difficulty": match.group("difficulty").strip(),
            "problem": match.group("problem").strip(),
            "url": match.group("url").strip(),
            "comfort": comfort,
            "streak": streak,
            "latest": latest,
            "latest_attempt_date": format_date(latest),
            "attempts": attempts,
            "next_review": format_date(compute_next_review_date(comfort, latest, streak)),
        })

    if not (header_seen and separator_seen):
        raise RuntimeError(f"Could not find review table header and separator in {tracker_path}.")

    sorted_rows = sorted(
        table_rows, key=lambda e: (e["latest"] is not None, e["latest"]), reverse=True
    )
    new_lines = prefix_lines + [build_row(r) for r in sorted_rows] + suffix_lines
    if new_lines != lines:
        tracker_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")
        print(f"Reordered {len(sorted_rows)} rows by latest attempt date in {tracker_path}")
    else:
        print(f"No reorder needed in {tracker_path}")


def main() -> None:
    text = MARKDOWN_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    prefix_lines: list[str] = []
    table_rows: list[dict] = []
    suffix_lines: list[str] = []
    in_table = False
    table_header_seen = False
    table_separator_seen = False
    legacy_format = False

    for line in lines:
        if not in_table:
            prefix_lines.append(line)
            if line.strip() in TABLE_HEADERS_CURRENT:
                in_table = True
                table_header_seen = True
            elif line.strip() == TABLE_HEADER_LEGACY:
                in_table = True
                table_header_seen = True
                legacy_format = True
            continue

        if in_table and not table_separator_seen:
            if line.strip() in (ROW_SEPARATOR, ROW_SEPARATOR_LEGACY):
                prefix_lines.append(line)
                table_separator_seen = True
                continue
            prefix_lines.append(line)
            continue

        new_match = ROW_RE.match(line) if line.startswith("|") else None
        legacy_match = ROW_RE_LEGACY.match(line) if (line.startswith("|") and not new_match) else None

        if new_match:
            match = new_match
            difficulty = match.group("difficulty").strip()
            problem = match.group("problem").strip()
            url = match.group("url").strip()
            comfort = match.group("comfort").strip()
            streak = int(match.group("streak"))
            latest = parse_date(match.group("latest"))
            attempts = match.group("attempts").strip()
            attempts_latest = parse_latest_attempt_date_from_attempts(attempts)
            if latest is None or (attempts_latest is not None and attempts_latest > latest):
                latest = attempts_latest
            next_review = format_date(compute_next_review_date(comfort, latest, streak))
            table_rows.append({
                "difficulty": difficulty,
                "problem": problem,
                "url": url,
                "comfort": comfort,
                "streak": streak,
                "latest": latest,
                "latest_attempt_date": format_date(latest),
                "attempts": attempts,
                "next_review": next_review,
            })
        elif legacy_match:
            match = legacy_match
            difficulty = match.group("difficulty").strip()
            problem = match.group("problem").strip()
            url = match.group("url").strip()
            comfort = match.group("comfort").strip()
            streak = 1 if comfort == COMFORT_CLEAN else 0
            latest = parse_date(match.group("latest"))
            attempts = match.group("attempts").strip()
            attempts_latest = parse_latest_attempt_date_from_attempts(attempts)
            if latest is None or (attempts_latest is not None and attempts_latest > latest):
                latest = attempts_latest
            next_review = format_date(compute_next_review_date(comfort, latest, streak))
            table_rows.append({
                "difficulty": difficulty,
                "problem": problem,
                "url": url,
                "comfort": comfort,
                "streak": streak,
                "latest": latest,
                "latest_attempt_date": format_date(latest),
                "attempts": attempts,
                "next_review": next_review,
            })
        else:
            suffix_lines.append(line)

    if not table_header_seen or not table_separator_seen:
        raise RuntimeError("Could not find review table header and separator in markdown file.")

    if legacy_format:
        print("Migrating table from legacy format (no Streak column) to new format.")

    parser = argparse.ArgumentParser(description="Update review progression markdown from source problem files.")
    parser.add_argument("--staged-only", action="store_true")
    parser.add_argument("--all-source", action="store_true")
    parser.add_argument(
        "--tracker",
        action="append",
        default=[],
        help="Extra same-format tracker(s) to recompute + re-sort without source "
        "discovery (e.g. the System Design / AI progress files). Repeatable.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Session date (YYYY-MM-DD or YYYYMMDD) used to stamp attempt dates. "
        "Default = auto-detected session date, which past midnight is YESTERDAY when a "
        "session is in progress. The pre-commit hook passes nothing, so detection is "
        "what actually protects a past-midnight commit.",
    )
    args = parser.parse_args()

    global _SESSION_NOW
    _SESSION_NOW = session_date.resolve_datetime(args.date)

    staged_files = None
    markdown_staged = False
    if args.staged_only and args.all_source:
        parser.error("--staged-only and --all-source cannot be used together.")
    staged_markdown_titles: set[str] = set()
    if args.staged_only:
        staged_files, markdown_staged = get_staged_paths()
        staged_markdown_titles = get_staged_rows_with_changed_attempts() if markdown_staged else set()
        print(f"Scanning {len(staged_files)} staged source file(s) for new problems.")
        if markdown_staged:
            print(
                f"Detected staged markdown table changes; only {len(staged_markdown_titles)} newly added row(s) are eligible for a current-date fill."
            )

    existing_titles = {row["problem"].strip().lower() for row in table_rows}

    updated_count = update_existing_row_difficulties(table_rows, staged_files=staged_files)
    if updated_count:
        print(f"Updated difficulty for {updated_count} existing review row(s) from source comments.")

    staged_date_count = fill_current_date_for_staged_rows(
        table_rows,
        staged_files=staged_files,
        staged_markdown_titles=staged_markdown_titles,
    )
    if staged_date_count:
        print(f"Filled current date for {staged_date_count} staged review row(s) with missing latest attempt dates.")

    discovered = discover_source_problems(existing_titles, staged_files=staged_files)
    if discovered:
        table_rows.extend(discovered)
        print(f"Discovered and added {len(discovered)} problem(s) from source files.")

    try:
        table_rows = apply_holds(table_rows, load_holds())
    except HoldsError as error:
        raise SystemExit(f"ERROR: {HOLDS_PATH}: {error}") from error

    sorted_rows = sorted(
        table_rows,
        key=lambda entry: (entry["latest"] is not None, entry["latest"]),
        reverse=True,
    )

    sorted_lines = [build_row(entry) for entry in sorted_rows]

    try:
        header_index = next(
            i for i, line in enumerate(prefix_lines)
            if line.strip() in TABLE_HEADERS_ALL
        )
    except StopIteration:
        header_index = len(prefix_lines)

    def _is_summary_line(line: str) -> bool:
        s = line.strip()
        if any(s.startswith(p) for p in (
            "**Problems Done:**", "**Total Successful Attempts:**", "**Mastered",
            "| Problems Done |", "| Unique Problems |", "| Solutions |",
            # Both the current header and the pre-Jul-26-2026 one. If an old header stops
            # being matched here, the previous summary block is never stripped and a new
            # one is appended — stacking a duplicate table on every run.
            f"| | {COMFORT_RETIRED} Retired |", f"| {COMFORT_RETIRED} Retired |",
            f"| | {COMFORT_GRADUATED} Graduated |", f"| {COMFORT_GRADUATED} Graduated |",
            "|:---|", "|:---:|",
        )):
            return True
        if re.match(r"^\*\*\d+ problems done\*\*$", s):
            return True
        # \d+ optionally followed by +\d+ — the probe-fold format `**107+4** problems`. Without the
        # (?:\+\d+)? the new-format line is not recognized as a prior summary, so it is never stripped
        # and a fresh one stacks under it on every run (the exact duplicate this whole guard prevents).
        if re.match(r"^> \*\*\d+(?:\+\d+)?\*\* problems", s):
            return True
        if re.match(r"^\| \*?\*?Solutions\*?\*? \|", s):
            return True
        return bool(re.match(r"^\|\s*\d+\s*(?:\|\s*\d+\s*){3,6}\|$", s))

    filtered_prefix = []
    for line in prefix_lines[:header_index]:
        if _is_summary_line(line):
            continue
        if line.strip() == "":
            if filtered_prefix and filtered_prefix[-1].strip() != "":
                filtered_prefix.append(line)
        else:
            filtered_prefix.append(line)

    while filtered_prefix and filtered_prefix[-1].strip() == "":
        filtered_prefix.pop()

    summary_lines = build_summary_lines(sorted_rows, retired=count_retired_entries(lines))

    # Replace legacy header/separator with new format
    header_and_after = []
    for line in prefix_lines[header_index:]:
        if line.strip() in (TABLE_HEADER_LEGACY, TABLE_HEADER_ATTEMPT_ERA):
            header_and_after.append(TABLE_HEADER)
        elif line.strip() == ROW_SEPARATOR_LEGACY:
            header_and_after.append(ROW_SEPARATOR)
        else:
            header_and_after.append(line)

    new_prefix = filtered_prefix + summary_lines + header_and_after
    new_lines = new_prefix + sorted_lines + suffix_lines

    if new_lines != lines:
        MARKDOWN_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")
        action = "Migrated and reordered" if legacy_format else "Reordered"
        print(f"{action} {len(sorted_rows)} rows by latest attempt date in {MARKDOWN_PATH}")
    else:
        print(f"No reorder needed in {MARKDOWN_PATH}")

    # Non-DSA trackers (System Design / AI): recompute + re-sort only, no discovery.
    for extra in args.tracker:
        recompute_simple(Path(extra))


if __name__ == "__main__":
    main()
