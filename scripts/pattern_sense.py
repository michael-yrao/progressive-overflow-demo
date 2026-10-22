"""Weekly Pattern Sense deck: propose picks, export the site contract, ingest a results code.

The site's Pattern Sense "This week" deck deals `per_week` problems the learner has NOT done and
has NOT planned, drawn from the company_demand "Asked by >=N target companies and untracked"
table (Gated rows only). The coach labels each pick (family + technique + cue) and writes a
paraphrase into `dashboard/pattern_sense.yml`; this script exports the public contract
`dashboard/pattern-sense.json` (no slug, no title, no tags: a title spoils the technique) and
decodes the results code the site shows at the end of a deck. With no deck in the yml, `export`
prints a one-line notice and exits 0 without writing, so the site keeps its fallback.

Usage:
    python scripts/pattern_sense.py propose --week 2026-11-30   # picks + spares; writes nothing
    python scripts/pattern_sense.py export                      # write dashboard/pattern-sense.json
    python scripts/pattern_sense.py export --check              # validate decks + file; write nothing
    python scripts/pattern_sense.py export --stdout             # print the JSON
    python scripts/pattern_sense.py ingest "PS1 2026-11-30 a3f9c2 1004:+/+ 55:+/. 76:4/1"
    python scripts/pattern_sense.py ingest CODE --json PATH     # decode against an exported JSON
    python scripts/pattern_sense.py ingest --pending            # decode dashboard/pattern_sense_results/*.json

Results code: `PS1 <week> <vocabHash> <n>:<f>/<t> ...`, problems in deck order. `f`/`t` is `+`
when correct, else the 1-based chip index chosen (`f` indexes the sorted `families`, `t` the
correct family's `techniques`). `t` is `.` when the correct family has one technique.

Config: `cse.config.yml` key `pattern_sense` (`starts`, `per_week`). No in-script default.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping

import _console
import check_phantom_scaffolds as cps
import company_demand as cd
import contract_schema
import gamify
import new_problem as npb

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
MASTERY = REPO / "docs" / "foundations" / "dsa" / "mastery"
COMPANY_DEMAND = MASTERY / "company_demand.md"
TECHNIQUES_YML = MASTERY / "techniques.yml"
PROBES_README = REPO / "dsa" / "probes" / "README.md"
MOCKS_README = REPO / "docs" / "foundations" / "dsa" / "mocks" / "README.md"
SOLUTION_DIRS = (REPO / "dsa" / "leetcode", REPO / "dsa" / "probes")
CONFIG = REPO / "cse.config.yml"
DASHBOARD = REPO / "dashboard"
DECKS_YML = DASHBOARD / "pattern_sense.yml"
OUT = DASHBOARD / "pattern-sense.json"
SCHEMA = DASHBOARD / "pattern-sense.schema.json"
RESULTS_DIR = DASHBOARD / "pattern_sense_results"
RESULTS_FILE_VERSION = 1

SCHEMA_VERSION = 1
CONFIG_KEY = "pattern_sense"
RESULTS_TAG = "PS1"
VOCAB_HASH_LEN = 6
EXPANSION_FAMILY = "expansion"
MONDAY = 0
CORRECT = "+"
NO_STEP_TWO = "."
POOL_GATED_GLYPH = "✓"
POOL_COLUMNS = 6
TOP_COLUMNS = 7
PROBE_LOG_HEADING = "## 📒 Probe log"
PROBE_QUEUE_HEADING = "## 🎣 Queued probe candidates"
MOCK_LOG_HEADING = "## Log"
RESERVE_HEADING = "### bigtech — top-"
REQUIRED_PROBLEM_KEYS = ("number", "slug", "family", "technique", "prompt", "constraints", "cue")
CODE_PROBLEM = re.compile(r"^(\d+):(\+|\d+)/(\+|\d+|\.)$")
LINK_SLUG = re.compile(r"\]\([^)]*?/problems/([a-z0-9-]+)")
LEADING_NUMBER = re.compile(r"^\W*(\d{1,4})\b")
TAG = re.compile(r"<[^>]+>")


class PatternSenseError(Exception):
    """A fatal config, deck or results-code problem. Never swallowed."""


# ── data shapes ───────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PoolRow:
    slug: str
    family: str
    companies: int
    max_freq: float


@dataclass(frozen=True)
class Candidate:
    number: int
    slug: str
    family: str
    companies: int
    max_freq: float
    is_premium: bool


@dataclass(frozen=True)
class Exclusions:
    """Every set a pool row is tested against. Numbers except `reserve` (slugs)."""
    tracker: frozenset[int] = frozenset()
    planned: frozenset[int] = frozenset()
    files: frozenset[int] = frozenset()
    probed: frozenset[int] = frozenset()
    mocked: frozenset[int] = frozenset()
    decked: frozenset[int] = frozenset()
    reserve: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Picks:
    main: tuple[Candidate, ...]
    spare: tuple[Candidate, ...]


@dataclass(frozen=True)
class Vocabulary:
    family_of: Mapping[str, str]          # technique name -> family id
    started: frozenset[str]               # technique names with a tracked problem


@dataclass(frozen=True)
class DeckRules:
    per_week: int
    starts: dt.date


# ── config ────────────────────────────────────────────────────────────────────────────

def _as_date(value: object, label: str) -> dt.date:
    if isinstance(value, dt.datetime):
        raise PatternSenseError(f"{label}: expected a date, got a datetime ({value!r})")
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise PatternSenseError(f"{label}: {value!r} is not a YYYY-MM-DD date") from exc


def parse_config(raw: object) -> DeckRules:
    """`cse.config.yml`'s `pattern_sense` block -> DeckRules. No default: absent is an error."""
    if not isinstance(raw, dict):
        raise PatternSenseError(
            f"cse.config.yml has no `{CONFIG_KEY}` block (starts, per_week) — add it; "
            "this script has no default")
    missing = [k for k in ("starts", "per_week") if k not in raw]
    if missing:
        raise PatternSenseError(f"cse.config.yml `{CONFIG_KEY}` is missing {missing}")
    per_week = raw["per_week"]
    if not isinstance(per_week, int) or isinstance(per_week, bool) or per_week < 1:
        raise PatternSenseError(f"`{CONFIG_KEY}.per_week` must be a positive integer")
    return DeckRules(per_week=per_week, starts=_as_date(raw["starts"], f"{CONFIG_KEY}.starts"))


def load_rules() -> DeckRules:
    import yaml  # noqa: PLC0415
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    return parse_config(config.get(CONFIG_KEY))


# ── vocabulary ────────────────────────────────────────────────────────────────────────

def build_families(entries: list[dict]) -> list[dict]:
    """[{id, techniques}] for every family except `expansion`, sorted by id; each technique
    list in techniques.yml file order. These arrays ARE the site's chip order."""
    by_family: dict[str, list[str]] = {}
    for entry in entries:
        family, name = entry.get("family"), entry.get("name")
        if not family or not name:
            raise PatternSenseError(f"techniques.yml entry without name/family: {entry!r}")
        if family == EXPANSION_FAMILY:
            continue
        by_family.setdefault(family, []).append(name)
    return [{"id": fid, "techniques": by_family[fid]} for fid in sorted(by_family)]


def vocab_hash(families: list[dict]) -> str:
    text = "\n".join(f"{f['id']}:{'|'.join(f['techniques'])}" for f in families)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:VOCAB_HASH_LEN]


def load_technique_entries() -> list[dict]:
    import yaml  # noqa: PLC0415
    config = yaml.safe_load(TECHNIQUES_YML.read_text(encoding="utf-8")) or {}
    return config.get("techniques") or []


def started_techniques() -> frozenset[str]:
    """Started = the technique's row in technique_coverage.md does not carry the
    `*not started*` marker (gamify.parse_techniques' `started`), i.e. it has a tracked problem."""
    rows = gamify.parse_techniques([])
    return frozenset(r["name"] for r in rows if r["started"])


# ── pool + exclusion parsing (pure) ───────────────────────────────────────────────────

def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _section_lines(text: str, heading: str) -> list[str]:
    """Lines after the first line starting with `heading`, up to the next `#` line."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        out.append(line)
    return out


def parse_pool(text: str) -> list[PoolRow]:
    """Gated rows of the cross-tier table, in file order."""
    heading = f"## Asked by ≥{cd.MIN_COMPANIES_CROSS_TIER} target companies and untracked"
    rows: list[PoolRow] = []
    for line in _section_lines(text, heading):
        cells = _cells(line) if line.startswith("|") else []
        if len(cells) != POOL_COLUMNS or cells[5] != POOL_GATED_GLYPH:
            continue
        slug = LINK_SLUG.search(cells[1])
        count = re.match(r"\d+", cells[3])
        if not slug or not count:
            continue
        rows.append(PoolRow(slug.group(1), cells[0], int(count.group(0)), float(cells[4])))
    return rows


def mock_reserve_slugs(text: str) -> frozenset[str]:
    """Bigtech top-100 rows still untracked with at least MIN_COMPANIES_CROSS_TIER companies."""
    slugs: set[str] = set()
    for line in _section_lines(text, RESERVE_HEADING):
        cells = _cells(line) if line.startswith("|") else []
        if len(cells) != TOP_COLUMNS or cells[4] != cd.UNTRACKED_GLYPH:
            continue
        slug = LINK_SLUG.search(cells[2])
        asked_by = [c for c in cells[6].split(",") if c.strip()]
        if slug and len(asked_by) >= cd.MIN_COMPANIES_CROSS_TIER:
            slugs.add(slug.group(1))
    return frozenset(slugs)


def _numbers_in_table(text: str, heading: str, column: int) -> frozenset[int]:
    found: set[int] = set()
    for line in _section_lines(text, heading):
        cells = _cells(line) if line.startswith("|") else []
        if len(cells) <= column:
            continue
        match = LEADING_NUMBER.match(cells[column])
        if match:
            found.add(int(match.group(1)))
    return frozenset(found)


def probe_numbers(text: str) -> frozenset[int]:
    """Probe log (Problem column) plus queued probe candidates (Candidate column)."""
    return _numbers_in_table(text, PROBE_LOG_HEADING, 2) | _numbers_in_table(text, PROBE_QUEUE_HEADING, 0)


def mock_numbers(text: str) -> frozenset[int]:
    return _numbers_in_table(text, MOCK_LOG_HEADING, 2)


def numbers_from_filenames(names: list[str]) -> frozenset[int]:
    return frozenset(int(m.group(1)) for n in names if (m := re.match(r"(\d+)_", n)))


def seen_numbers(decks: list[dict]) -> frozenset[int]:
    """Every number that appeared in a deck, `skipped:` included."""
    seen: set[int] = set()
    for deck in decks:
        seen.update(p["number"] for p in deck.get("problems") or [])
        seen.update(deck.get("skipped") or [])
    return frozenset(seen)


def planned_numbers(entries: list[dict], tracked: frozenset[int],
                    waiting_room: Mapping[int, dict], roadmap: Mapping[int, dict]) -> frozenset[int]:
    """gamify's planned_for() over every techniques.yml entry, plus the whole Waiting Room
    and roadmap catalog."""
    declared = {p["lcNumber"]
                for entry in entries
                for p in gamify.planned_for(entry, set(tracked), dict(waiting_room), dict(roadmap))}
    return frozenset(declared | set(waiting_room) | set(roadmap))


# ── eligibility + pick (pure) ─────────────────────────────────────────────────────────

def slug_excluded(slug: str, family: str, ex: Exclusions) -> bool:
    """The exclusions decidable before a number is known (so before any network call)."""
    return slug in ex.reserve or family == cd.UNMAPPED_FAMILY


def number_excluded(number: int, ex: Exclusions) -> bool:
    return any(number in group for group in
               (ex.tracker, ex.planned, ex.files, ex.probed, ex.mocked, ex.decked))


def eligible(candidate: Candidate, ex: Exclusions) -> bool:
    return not (candidate.is_premium
                or slug_excluded(candidate.slug, candidate.family, ex)
                or number_excluded(candidate.number, ex))


def _within_family_key(c: Candidate) -> tuple[int, float, int]:
    return (-c.companies, -c.max_freq, c.number)


def _select(candidates: list[Candidate], last_shown: Mapping[str, str], count: int) -> list[Candidate]:
    by_family: dict[str, list[Candidate]] = {}
    for c in sorted(candidates, key=_within_family_key):
        by_family.setdefault(c.family, []).append(c)
    order = sorted(by_family, key=lambda f: (last_shown.get(f, ""), -len(by_family[f]), f))
    chosen: list[Candidate] = []
    depth = 0
    while len(chosen) < count and any(len(by_family[f]) > depth for f in order):
        for family in order:
            if len(chosen) == count:
                break
            if len(by_family[family]) > depth:
                chosen.append(by_family[family][depth])
        depth += 1
    return chosen


def pick(candidates: list[Candidate], last_shown: Mapping[str, str], per_week: int) -> Picks:
    """At most one per family, least recently shown family first (never shown = oldest; ties:
    more candidates, then name); a second pass fills a short deck. The spare round is the next
    `per_week` picks by the same ordering with the chosen ones removed."""
    main = _select(candidates, last_shown, per_week)
    taken = {c.number for c in main}
    spare = _select([c for c in candidates if c.number not in taken], last_shown, per_week)
    return Picks(tuple(main), tuple(spare))


def last_shown_by_family(decks: list[dict], before_week: str) -> dict[str, str]:
    last: dict[str, str] = {}
    for deck in decks:
        if deck["week"] >= before_week:
            continue
        for p in deck.get("problems") or []:
            last[p["family"]] = max(last.get(p["family"], ""), deck["week"])
    return last


# ── deck file ─────────────────────────────────────────────────────────────────────────

def _iso(value: object) -> str:
    return value.isoformat() if isinstance(value, dt.date) else str(value)


def load_decks(path: Path = DECKS_YML) -> list[dict]:
    """Decks from the yml, `week` normalised to an ISO string (YAML reads an unquoted date
    as a date object)."""
    import yaml  # noqa: PLC0415
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("schemaVersion") != SCHEMA_VERSION or not isinstance(raw.get("decks"), list):
        raise PatternSenseError(f"{path.name}: expected `schemaVersion: {SCHEMA_VERSION}` and a `decks:` list")
    return [{**deck, "week": _iso(deck.get("week"))} for deck in raw["decks"]]


def latest_deck(decks: list[dict]) -> dict | None:
    return max(decks, key=lambda d: d["week"]) if decks else None


def is_empty_decks(decks: list[dict]) -> bool:
    """True when the deck file holds no deck: there is nothing to export."""
    return not decks


def empty_decks_notice(decks_name: str, out_name: str) -> str:
    """The one line `export` prints, then exits 0, for an empty deck file. The output file is
    deliberately not written, so the site keeps its fallback."""
    return (f"{decks_name} has no decks - nothing to export, {out_name} not written "
            f"(the site keeps its fallback)")


def build_payload(decks: list[dict], families: list[dict], today: dt.date) -> dict:
    deck = latest_deck(decks)
    problems = [
        {"lcNumber": p["number"], "prompt": p["prompt"], "constraints": list(p["constraints"]),
         "family": p["family"], "technique": p["technique"], "cue": p["cue"]}
        for p in (deck["problems"] if deck else [])]
    return {"schemaVersion": SCHEMA_VERSION, "generatedAt": today.isoformat(),
            "week": deck["week"] if deck else None, "vocabHash": vocab_hash(families),
            "families": families, "problems": problems}


# ── validate (pure) ───────────────────────────────────────────────────────────────────

def _term_in(prompt: str, term: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", prompt, re.IGNORECASE) is not None


def _problem_errors(label: str, p: dict, vocab: Vocabulary) -> list[str]:
    missing = [k for k in REQUIRED_PROBLEM_KEYS if p.get(k) in (None, "", [])]
    if missing:
        return [f"{label}: missing {missing}"]
    technique, family = p["technique"], p["family"]
    errors: list[str] = []
    real_family = vocab.family_of.get(technique)
    if real_family is None:
        errors.append(f"{label}: unknown technique {technique!r}")
    elif EXPANSION_FAMILY in (real_family, family):
        errors.append(f"{label}: the `{EXPANSION_FAMILY}` family never appears in a deck")
    elif real_family != family:
        errors.append(f"{label}: technique {technique!r} is in family {real_family!r}, not {family!r}")
    allowed = {t.lower() for t in p.get("allow_terms") or []}
    errors += [f"{label}: prompt names the technique {name!r} (list it under allow_terms to keep it)"
               for name in vocab.family_of
               if name.lower() not in allowed and _term_in(p["prompt"], name)]
    return errors


def _deck_errors(deck: dict, rules: DeckRules) -> list[str]:
    week = deck["week"]
    try:
        monday = dt.date.fromisoformat(week)
    except ValueError:
        return [f"deck {week!r}: week is not a YYYY-MM-DD date"]
    errors: list[str] = []
    if monday.weekday() != MONDAY:
        errors.append(f"deck {week}: not a Monday")
    if monday < rules.starts:
        errors.append(f"deck {week}: before pattern_sense.starts ({rules.starts})")
    count = len(deck.get("problems") or [])
    if count != rules.per_week:
        errors.append(f"deck {week}: {count} problems, pattern_sense.per_week is {rules.per_week}")
    return errors


def _open_deck_errors(deck: dict, vocab: Vocabulary, ex: Exclusions) -> list[str]:
    """Checks that only a deck with no `results:` yet must still pass."""
    errors: list[str] = []
    for p in deck.get("problems") or []:
        label = f"deck {deck['week']} #{p.get('number')}"
        if vocab.family_of.get(p.get("technique")) and p["technique"] not in vocab.started:
            errors.append(f"{label}: technique {p['technique']!r} is not started yet")
        if number_excluded(p.get("number"), ex) or p.get("slug") in ex.reserve:
            errors.append(f"{label}: no longer eligible (tracked, planned, filed, probed, mocked, "
                          "in another deck, or in the mock reserve)")
    return errors


def validate(decks: list[dict], vocab: Vocabulary, rules: DeckRules, ex: Exclusions) -> list[str]:
    """Every deck error. The started/eligible checks skip a deck that already has `results:`."""
    errors: list[str] = []
    counts = Counter(p.get("number") for d in decks for p in d.get("problems") or [])
    for deck in decks:
        errors += _deck_errors(deck, rules)
        for p in deck.get("problems") or []:
            label = f"deck {deck['week']} #{p.get('number')}"
            errors += _problem_errors(label, p, vocab)
            if counts[p.get("number")] > 1:
                errors.append(f"{label}: number appears more than once across decks")
        if not deck.get("results"):
            others = seen_numbers([d for d in decks if d is not deck])
            errors += _open_deck_errors(deck, vocab, replace(ex, decked=ex.decked | others))
    return errors


# ── results code (pure) ───────────────────────────────────────────────────────────────

def _index(token: str, size: int, label: str) -> int:
    value = int(token)
    if not 1 <= value <= size:
        raise PatternSenseError(f"{label}: chip index {value} is out of range 1..{size}")
    return value


def _decode_family(token: str, families: list[dict], label: str) -> str:
    return CORRECT if token == CORRECT else families[_index(token, len(families), label) - 1]["id"]


def _decode_technique(token: str, techniques: list[str], label: str) -> str:
    single = len(techniques) == 1
    if single and token != NO_STEP_TWO:
        raise PatternSenseError(f"{label}: the family has one technique, expected `{NO_STEP_TWO}`")
    if not single and token == NO_STEP_TWO:
        raise PatternSenseError(f"{label}: the family has several techniques, `{NO_STEP_TWO}` is not allowed")
    if token in (CORRECT, NO_STEP_TWO):
        return token
    return techniques[_index(token, len(techniques), label) - 1]


def parse_results_code(code: str, decks: list[dict], families: list[dict], current_hash: str) -> dict:
    """Decode a PS1 code against its deck. Returns {week, answers: [{number, family, technique}]}
    where family/technique are `+`, the chosen id/name, or `.` (technique only)."""
    tokens = code.split()
    if len(tokens) < 3 or tokens[0] != RESULTS_TAG:
        raise PatternSenseError(f"not a {RESULTS_TAG} code (expected `{RESULTS_TAG} <week> <hash> ...`)")
    _, week, code_hash, *entries = tokens
    if code_hash != current_hash:
        raise PatternSenseError(
            f"vocabulary hash {code_hash} != current {current_hash}: techniques.yml changed since the deck was played")
    deck = next((d for d in decks if d["week"] == week), None)
    if deck is None:
        raise PatternSenseError(f"no deck for week {week}")
    if deck.get("results"):
        raise PatternSenseError(f"deck {week} already has results")
    problems = deck["problems"]
    if [e.split(":")[0] for e in entries] != [str(p["number"]) for p in problems]:
        raise PatternSenseError(
            f"problem numbers {[e.split(':')[0] for e in entries]} do not match the deck's "
            f"{[p['number'] for p in problems]} (missing or out of order)")
    by_id = {f["id"]: f["techniques"] for f in families}
    answers = []
    for entry, problem in zip(entries, problems):
        match = CODE_PROBLEM.match(entry)
        if not match:
            raise PatternSenseError(f"malformed entry {entry!r}")
        number, family_token, technique_token = match.groups()
        label = f"#{number}"
        answers.append({
            "number": problem["number"],
            "family": _decode_family(family_token, families, label),
            "technique": _decode_technique(technique_token, by_id[problem["family"]], label)})
    return {"week": week, "answers": answers}


def score(answers: list[dict]) -> dict:
    asked = [a for a in answers if a["technique"] != NO_STEP_TWO]
    return {"family": f"{sum(a['family'] == CORRECT for a in answers)}/{len(answers)}",
            "technique": f"{sum(a['technique'] == CORRECT for a in asked)}/{len(asked)}"}


def render_results_block(answers: list[dict], ingest_date: dt.date) -> str:
    j = json.dumps
    lines = ["    results:", f"      ingested: {ingest_date.isoformat()}",
             f"      score: {j(score(answers))}", "      problems:"]
    lines += [f"        - {{number: {a['number']}, family: {j(a['family'], ensure_ascii=False)}, "
              f"technique: {j(a['technique'], ensure_ascii=False)}}}" for a in answers]
    return "\n".join(lines)


def gotcha_lines(week: str, answers: list[dict], problems: list[dict], ingest_date: dt.date) -> list[str]:
    """One draft recognition_gotchas.md line per miss."""
    out = []
    for answer, problem in zip(answers, problems):
        misses = []
        if answer["family"] != CORRECT:
            misses.append(f"family: chose {answer['family']}, it is {problem['family']}")
        if answer["technique"] not in (CORRECT, NO_STEP_TWO):
            misses.append(f"technique: chose {answer['technique']}, it is {problem['technique']}")
        if misses:
            out.append(
                f"- **{ingest_date.isoformat()} · {problem['number']}** (Pattern Sense deck {week}; "
                f"shown by shape only, not a rep) — ❌ **miss.** {'; '.join(misses)}. "
                f"Picking feature: {problem['cue']}. → no comfort change.")
    return out


# ── statement text ────────────────────────────────────────────────────────────────────

def html_to_text(content: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", html.unescape(TAG.sub("", content))).strip()


# ── I/O wrappers ──────────────────────────────────────────────────────────────────────

def _read_optional(path: Path) -> str:
    """File text, or "" when the file is absent (a template checkout lacks some sources)."""
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def load_exclusions(decks: list[dict], before_week: str | None) -> Exclusions:
    tracker_text = gamify.TRACKER.read_text(encoding="utf-8")
    tracked = frozenset(int(n) for n in cps.tracker_numbers())
    warnings: list[str] = []
    roadmap = gamify.load_roadmap(warnings)
    earlier = [d for d in decks if before_week is None or d["week"] < before_week]
    names = [p.name for root in SOLUTION_DIRS if root.is_dir() for p in root.rglob("*.py")]
    return Exclusions(
        tracker=tracked,
        planned=planned_numbers(load_technique_entries(), tracked,
                                gamify.parse_waiting_room(tracker_text), roadmap),
        files=numbers_from_filenames(names),
        probed=probe_numbers(_read_optional(PROBES_README)),
        mocked=mock_numbers(_read_optional(MOCKS_README)),
        decked=seen_numbers(earlier),
        reserve=mock_reserve_slugs(_read_optional(COMPANY_DEMAND)))


def resolve_candidates(rows: list[PoolRow], lookup: Callable[[str], dict | None]) -> list[Candidate]:
    """One lookup per slug. A slug that cannot be resolved is reported on stderr and dropped."""
    out: list[Candidate] = []
    for row in rows:
        try:
            question = lookup(row.slug)
            number = int(question["questionFrontendId"]) if question else None
        except (OSError, ValueError, KeyError) as exc:
            print(f"  !! {row.slug}: lookup failed ({exc}) — dropped", file=sys.stderr)
            continue
        if number is None:
            print(f"  !! {row.slug}: LeetCode has no such question — dropped", file=sys.stderr)
            continue
        out.append(Candidate(number, row.slug, row.family, row.companies, row.max_freq,
                             bool(question.get("isPaidOnly"))))
    return out


def cmd_propose(week: str) -> int:
    rules = load_rules()
    decks = load_decks()
    ex = load_exclusions(decks, week)
    rows = [r for r in parse_pool(_read_optional(COMPANY_DEMAND))
            if not slug_excluded(r.slug, r.family, ex)]
    cache: dict[str, dict | None] = {}
    candidates = [c for c in resolve_candidates(
        rows, lambda s: cache[s] if s in cache else cache.setdefault(s, npb.lookup_leetcode(s)))
        if eligible(c, ex)]
    picks = pick(candidates, last_shown_by_family(decks, week), rules.per_week)
    print(f"Pattern Sense proposal for {week}: {len(candidates)} eligible of {len(rows)} pool rows")
    for title, group in (("MAIN", picks.main), ("SPARE ROUND", picks.spare)):
        print(f"\n{title}")
        for c in group:
            print(f"  {c.number:>5}  {c.slug}  [{c.family}]  {c.companies} companies, max freq {c.max_freq}")
    print("\nSTATEMENTS (terminal only; paraphrase before committing)")
    for c in picks.main:
        content = npb.fetch_statement(c.slug)
        print(f"\n=== {c.number} {c.slug} ===\n{html_to_text(content) if content else '(no statement)'}")
    return 0


def _vocabulary(entries: list[dict]) -> Vocabulary:
    return Vocabulary({e["name"]: e["family"] for e in entries}, started_techniques())


def _stale(payload: dict) -> bool:
    if not OUT.exists():
        return True
    existing = json.loads(OUT.read_text(encoding="utf-8"))
    return {**existing, "generatedAt": None} != {**payload, "generatedAt": None}


def cmd_export(args: argparse.Namespace) -> int:
    decks = load_decks()
    if is_empty_decks(decks):
        print(empty_decks_notice(DECKS_YML.name, OUT.name), file=sys.stderr)
        return 0
    rules, entries = load_rules(), load_technique_entries()
    errors = validate(decks, _vocabulary(entries), rules, load_exclusions([], None))
    if errors:
        print("ERROR: pattern_sense.yml failed its checks:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    payload = build_payload(decks, build_families(entries), today)
    contract_schema.check(payload, SCHEMA)
    if args.check:
        if _stale(payload):
            print("ERROR: dashboard/pattern-sense.json is stale or missing — run export", file=sys.stderr)
            return 1
        print(f"ok: {len(decks)} deck(s) verified, vocabHash {payload['vocabHash']}", file=sys.stderr)
        return 0
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.stdout:
        print(rendered)
        return 0
    OUT.write_text(rendered + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} (week {payload['week']}, {len(payload['problems'])} problems)")
    return 0


def _decks_from_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("week") is None:
        return []
    problems = [{**p, "number": p["lcNumber"]} for p in data["problems"]]
    return [{"week": data["week"], "problems": problems}]


def _print_ingest(code: str, decks: list[dict], families: list[dict]) -> None:
    parsed = parse_results_code(code, decks, families, vocab_hash(families))
    deck = next(d for d in decks if d["week"] == parsed["week"])
    today = dt.date.today()
    print(f"Deck {parsed['week']} score: {score(parsed['answers'])}\n")
    print("# paste under the deck in dashboard/pattern_sense.yml")
    print(render_results_block(parsed["answers"], today))
    print("\n# draft recognition_gotchas.md lines (one per miss)")
    lines = gotcha_lines(parsed["week"], parsed["answers"], deck["problems"], today)
    print("\n".join(lines) if lines else "(no misses)")


def cmd_ingest(args: argparse.Namespace) -> int:
    families = build_families(load_technique_entries())
    decks = _decks_from_json(Path(args.json)) if args.json else load_decks()
    _print_ingest(args.code, decks, families)
    return 0


# ── saved results files (site -> repo) ────────────────────────────────────────────────

def _file_error(path: str, body: object) -> str | None:
    """Why a saved results file is malformed, or None. Checks the file name against its week."""
    if not isinstance(body, dict):
        return "not a JSON object"
    if body.get("schemaVersion") != RESULTS_FILE_VERSION:
        return f"schemaVersion is {body.get('schemaVersion')!r}, expected {RESULTS_FILE_VERSION}"
    week, vocabulary, code = body.get("week"), body.get("vocabulary"), body.get("code")
    if not all(isinstance(v, str) and v for v in (week, vocabulary, code)):
        return "week, vocabulary and code must be non-empty strings"
    expected_name = f"{week.replace('-', '')}.json"
    if Path(path).name != expected_name:
        return f"file name does not match week {week} (expected {expected_name})"
    if not code.startswith(f"{RESULTS_TAG} {week} {vocabulary} "):
        return f"code does not start with `{RESULTS_TAG} {week} {vocabulary} `"
    return None


def pending_results(files: list[tuple[str, object]], decks: list[dict]
                    ) -> tuple[list[tuple[str, dict]], list[str]]:
    """(pending, errors) over (path, parsed JSON) pairs. A week whose deck already has
    `results:` is skipped silently; a malformed file yields an error naming it."""
    ingested = {d["week"] for d in decks if d.get("results")}
    pending: list[tuple[str, dict]] = []
    errors: list[str] = []
    for path, body in files:
        problem = _file_error(path, body)
        if problem:
            errors.append(f"{path}: {problem}")
        elif body["week"] not in ingested:
            pending.append((path, body))
    return pending, errors


def read_result_files(directory: Path = RESULTS_DIR) -> tuple[list[tuple[str, object]], list[str]]:
    """Every `*.json` in the folder as (path, parsed JSON); an unreadable file becomes an error."""
    files: list[tuple[str, object]] = []
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            files.append((str(path), json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: unreadable ({exc})")
    return files, errors


def cmd_ingest_pending() -> int:
    files, errors = read_result_files()
    decks = load_decks()
    pending, file_errors = pending_results(files, decks)
    errors += file_errors
    if not pending and not errors:
        print("No pending Pattern Sense results.")
        return 0
    families = build_families(load_technique_entries())
    for path, body in pending:
        print(f"=== {path} ===")
        try:
            _print_ingest(body["code"], decks, families)
        except PatternSenseError as exc:
            errors.append(f"{path}: {exc}")
        print()
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p_propose = sub.add_parser("propose", help="print picks + one spare round; writes nothing")
    p_propose.add_argument("--week", required=True, metavar="YYYY-MM-DD")
    p_export = sub.add_parser("export", help="write (or --check / --stdout) pattern-sense.json")
    p_export.add_argument("--check", action="store_true")
    p_export.add_argument("--stdout", action="store_true")
    p_export.add_argument("--date", metavar="YYYY-MM-DD", help="override generatedAt")
    p_ingest = sub.add_parser("ingest", help="decode a PS1 code or --pending saved files; writes nothing")
    p_ingest.add_argument("code", nargs="?")
    p_ingest.add_argument("--pending", action="store_true",
                          help="decode every un-ingested dashboard/pattern_sense_results/*.json")
    p_ingest.add_argument("--json", metavar="PATH", help="decode against an exported JSON's deck")
    args = ap.parse_args()
    if args.command == "ingest" and bool(args.code) == args.pending:
        ap.error("ingest takes either CODE or --pending")
    try:
        if args.command == "propose":
            return cmd_propose(args.week)
        if args.command == "export":
            return cmd_export(args)
        return cmd_ingest_pending() if args.pending else cmd_ingest(args)
    except PatternSenseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
