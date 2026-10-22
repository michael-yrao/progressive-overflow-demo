"""Emit the Big-O Trainer data contract (big-o.json) from the learner's own solutions.

The site's Big-O Trainer used to deal from a hand-written array of paraphrased snippets —
not the learner's real code, and nothing detected drift. This script removes the paraphrase
the same way export_showcase.py removed showcase's: it reads `dashboard/bigo.yml` (the
hand-curated pick of which attempt answers each LeetCode number's time/space question) and
emits `dashboard/big-o.json`, a byte-identical, line-numbered slice of the REAL solution
file plus a multiple-choice question built from a single canonical complexity-label pool.
See decisions.yml `dashboard-contract-exporters-oct6`.

Design constraints this file honours (mirrors export_showcase.py — see CLAUDE.md):

  * NOT FAIL-SOFT. A malformed manifest, a symbol that no longer exists, an unrecognized
    complexity label, or a scaffolded (never-really-attempted) pick is a hard error
    (exit 1) — a stale/wrong contract is the exact drift this tool exists to remove.

  * EMPTY MANIFEST = NOTHING TO EXPORT, NOT AN EMPTY FILE. A manifest with no entries exits
    0 with a one-line notice and writes no big-o.json, so the site's fallback (taken only
    when this repo's big-o.json is a 404) is not suppressed by an empty generated file.

  * VERBATIM, EOL-AGNOSTIC. Segments are sliced straight off the solution file via
    `export_showcase.read_lines` — never re-derived here.

  * SINGLE SOURCE OF TRUTH for the link precedence, the manifest shape rules, and the
    symbol-resolution rules: this module imports `export_showcase` and reuses its
    helpers rather than copying them. The only things unique to this file are the
    complexity-label pool, the difficulty/miss joins, and the multiple-choice options.

Usage:
    python scripts/export_bigo.py             # write dashboard/big-o.json
    python scripts/export_bigo.py --stdout     # print the JSON, do not write
    python scripts/export_bigo.py --check      # build in memory, validate, write nothing;
                                                 # exit 1 on any failure
    python scripts/export_bigo.py --date 2026-09-24   # override generatedAt (default: today)

`--check` also fails when `dashboard/big-o.json` already exists on disk and has drifted
from what the manifest + live source files + tracker would produce right now. Run this
before committing; the pre-commit hook runs it report-only (exit 2, a schema violation,
stops the commit).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import datetime as dt
import difflib
import json
import random
import re
import sys
from pathlib import Path
from typing import NamedTuple

import _console
import contract_schema
import effort_budget as eb
import export_showcase as es
import links

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
DASHBOARD = REPO / "dashboard"
MANIFEST = DASHBOARD / "bigo.yml"
OUT = DASHBOARD / "big-o.json"
SCHEMA = REPO / "dashboard" / "big-o.schema.json"
MISS_FILE = REPO / "docs" / "foundations" / "dsa" / "mastery" / "complexity_gotchas.md"

SCHEMA_VERSION = 1


class BigOError(es.ShowcaseError):
    """A fatal manifest/contract problem. Never caught silently — see the module
    docstring's NOT FAIL-SOFT constraint."""


# ── the one canonical complexity-label pool, simplest → hardest ────────────────────────
#
# Spellings are the site's runtime answer-check contract (exact string equality) — see
# decisions.yml `dashboard-contract-exporters-oct6`. Multiplication is `·` (never `×`);
# `log` is space-separated; superscripts are unicode (`²`, `³`, `ⁿ`).
COMPLEXITY_POOL: tuple[str, ...] = (
    "O(1)",
    "O(log n)",
    "O(log k)",
    "O(log(m·n))",
    "O(h)",
    "O(k)",
    "O(n)",
    "O(V)",
    "O(E)",
    "O(max(m, n))",
    "O(min(n, k))",
    "O(n + m)",
    "O(V+E)",
    "O(n log k)",
    "O(n log m)",
    "O(n log n)",
    "O(E log V)",
    "O(E log E)",
    "O(n·k)",
    "O(n·k log k)",
    "O(m·n)",
    "O(V·E)",
    "O(k·E)",
    "O(n·α(n))",
    "O(n²)",
    "O(n²·k)",
    "O(n² log n)",
    "O(n³)",
    "O(n·L²)",
    "O(2ⁿ)",
    "O(n·2ⁿ)",
    "O(n^d)",
    "O(n!)",
)
POOL_RANK: dict[str, int] = {label: index for index, label in enumerate(COMPLEXITY_POOL)}

# Pedagogically useful distractors for the answers that show up most often — every value
# here must itself be a COMPLEXITY_POOL member (`_validate_confusable_pool` checks this
# at import).
CONFUSABLE: dict[str, tuple[str, ...]] = {
    "O(1)": ("O(n)", "O(log n)", "O(k)"),
    "O(log n)": ("O(1)", "O(log k)", "O(h)", "O(k)", "O(n)"),
    "O(h)": ("O(log n)", "O(n)"),
    "O(k)": ("O(1)", "O(n)", "O(log k)"),
    "O(n)": ("O(1)", "O(log n)", "O(h)", "O(n log n)", "O(n²)"),
    "O(n + m)": ("O(n)", "O(max(m, n))", "O(min(n, k))", "O(V+E)", "O(n log k)", "O(m·n)"),
    "O(V)": ("O(E)", "O(V+E)", "O(n)"),
    "O(E)": ("O(V)", "O(V+E)", "O(E log E)"),
    "O(V+E)": ("O(V)", "O(E)", "O(V·E)", "O(E log V)"),
    "O(n log k)": ("O(n log n)", "O(n)", "O(n·k)"),
    "O(n log n)": ("O(n)", "O(n log k)", "O(E log V)", "O(n·k)", "O(n²)"),
    "O(E log V)": ("O(V+E)", "O(E log E)", "O(V·E)"),
    "O(E log E)": ("O(E log V)", "O(V+E)", "O(E)"),
    "O(n·k)": ("O(n)", "O(n log k)", "O(m·n)"),
    "O(m·n)": ("O(n + m)", "O(n·k)", "O(n·k log k)", "O(n log n)", "O(n²)", "O(V·E)"),
    "O(V·E)": ("O(V+E)", "O(E log V)"),
    "O(k·E)": ("O(E)", "O(V·E)", "O(E log V)"),
    "O(n·α(n))": ("O(n)", "O(n log n)", "O(n²)"),
    "O(n²)": ("O(n log n)", "O(n·k)", "O(m·n)", "O(n³)", "O(n²·k)", "O(n² log n)"),
    "O(n³)": ("O(n²)", "O(n² log n)"),
    "O(2ⁿ)": ("O(n·2ⁿ)", "O(n!)", "O(n²)"),
    "O(n·2ⁿ)": ("O(2ⁿ)", "O(n!)"),
    "O(n^d)": ("O(n²)", "O(n³)", "O(n!)"),
    "O(n!)": ("O(2ⁿ)", "O(n·2ⁿ)", "O(n^d)"),
}


def _validate_confusable_pool() -> None:
    """Every CONFUSABLE key and value must be a real COMPLEXITY_POOL member — a typo'd
    distractor would otherwise silently produce an option the site can never match a
    correct answer to. Runs at import; also exercised directly by test_bigo.py."""
    for label, alternatives in CONFUSABLE.items():
        if label not in POOL_RANK:
            raise AssertionError(f"CONFUSABLE key {label!r} is not in COMPLEXITY_POOL")
        for alt in alternatives:
            if alt not in POOL_RANK:
                raise AssertionError(
                    f"CONFUSABLE[{label!r}] contains {alt!r}, not in COMPLEXITY_POOL")


_validate_confusable_pool()

OPTION_COUNT = 4
TODO_LABEL = "TODO"
MISS_SECTION_MARKERS = ("complexity cleanup queue", "Ledger")

# How far (in POOL_RANK steps) options_for() looks for pool top-up candidates before
# widening — keeps distractors plausible (Two Sum's O(n) shouldn't sit next to O(n^d)).
_POOL_TOP_UP_WINDOW = 6

ALLOWED_ENTRY_KEYS = frozenset({
    "lc", "time", "space", "symbol", "container", "file", "variant", "helpers",
    "whyTime", "whySpace", "note",
})
REQUIRED_ENTRY_KEYS = ("lc", "time", "space")

_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# ── pure extraction helpers (take `table`/`lines`/`tree`/`text`; no filesystem access) ─

def candidate_symbols(table: dict[str, ast.AST]) -> list[tuple[str | None, str, ast.AST]]:
    """Every symbol an entry with no explicit `symbol:` could auto-pick: each
    `Solution.<m>` method as `("Solution", m, node)`, plus every top-level def/class
    whose name isn't "Solution" as `(None, name, node)`."""
    candidates: list[tuple[str | None, str, ast.AST]] = []
    for full_symbol, node in table.items():
        if "." in full_symbol:
            container, symbol = full_symbol.split(".", 1)
            if container == es.DEFAULT_CONTAINER:
                candidates.append((es.DEFAULT_CONTAINER, symbol, node))
        elif full_symbol != es.DEFAULT_CONTAINER:
            candidates.append((None, full_symbol, node))
    return candidates


def latest_dated_attempt(table: dict[str, ast.AST],
                          lines: list[str]) -> tuple[str | None, str] | None:
    """(container, symbol) of the `candidate_symbols` entry with the latest dated
    attempt (via `es.attempt_date` on its leading comment banner). Ties break toward the
    candidate lowest in the file (highest `def_start_line`). None when nothing in the
    file is dated."""
    best_date: str | None = None
    best_start = -1
    best_pick: tuple[str | None, str] | None = None
    for container, symbol, node in candidate_symbols(table):
        start = es.def_start_line(node)
        banner = es.leading_comment_block(lines, start)
        banner_lines = lines[banner[0] - 1:banner[1]] if banner else []
        date = es.attempt_date(symbol, banner_lines)
        if date is None:
            continue
        if best_date is None or (date, start) > (best_date, best_start):
            best_date, best_start, best_pick = date, start, (container, symbol)
    return best_pick


def _is_placeholder_stmt(stmt: ast.AST) -> bool:
    """True for a bare `pass` or a bare `...` expression statement."""
    if isinstance(stmt, ast.Pass):
        return True
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis)


def is_scaffold(node: ast.AST) -> bool:
    """True when `node`'s body — minus a leading docstring — is entirely `pass`/`...`
    placeholders. A `ClassDef` is a scaffold iff every one of its methods is."""
    if isinstance(node, ast.ClassDef):
        methods = [n for n in node.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        return all(is_scaffold(m) for m in methods)
    body = node.body
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return all(_is_placeholder_stmt(stmt) for stmt in body)


_MISS_HEADING = re.compile(r"^##\s+(.*)$")
_MISS_ROW_NUM = re.compile(r"^\|\s*(\d{1,4})\s")


def parse_miss_numbers(text: str) -> frozenset[int]:
    """Every LC number appearing as a table row's leading cell inside a `## ` section
    whose heading contains one of MISS_SECTION_MARKERS (case-insensitive) — the
    cleanup-queue and Ledger tables. A `↳`-prefixed transfer row, a date-led row, and a
    numeric row OUTSIDE those sections are all ignored (the leading-cell regex only
    matches a cell that starts with 1-4 digits then whitespace)."""
    numbers: set[int] = set()
    in_target_section = False
    for line in text.splitlines():
        heading = _MISS_HEADING.match(line)
        if heading:
            title = heading.group(1).lower()
            in_target_section = any(marker.lower() in title for marker in MISS_SECTION_MARKERS)
            continue
        if not in_target_section:
            continue
        row = _MISS_ROW_NUM.match(line)
        if row:
            numbers.add(int(row.group(1)))
    return frozenset(numbers)


def is_todo(label: str) -> bool:
    return label == TODO_LABEL


def validate_label(label: str, field: str, key: str) -> None:
    """`label` must be a COMPLEXITY_POOL member — else a BigOError naming close matches
    via `difflib`, so a typo'd manifest label points straight at the fix. Callers check
    `is_todo` first; TODO is never passed here."""
    if label in POOL_RANK:
        return
    suggestions = difflib.get_close_matches(label, COMPLEXITY_POOL, n=3)
    hint = f" — did you mean {suggestions}?" if suggestions else ""
    raise BigOError(f"{key}: {field} label {label!r} is not in COMPLEXITY_POOL{hint}")


def entry_key(raw: dict) -> str:
    """`str(lc)`, or `f"{lc}:{variant}"` when the manifest entry names a variant — the
    big-o.json join key (distinct from showcase's, which always carries a variant)."""
    lc = raw["lc"]
    variant = raw.get("variant")
    return f"{lc}:{variant}" if variant else str(lc)


def resolve_pick(raw: dict, table: dict[str, ast.AST], lines: list[str],
                  key: str) -> tuple[str | None, str, ast.AST]:
    """(container, symbol, node) for one manifest entry. An explicit `symbol:` uses
    `raw["container"]` when given, defaulting to `"Solution"` (showcase semantics);
    otherwise the file's own `latest_dated_attempt` picks both — container comes from
    WHERE the pick lives ("Solution" for a method, None for a top-level def/class).
    Nothing dated ⇒ BigOError telling the author to add `symbol:`. `container` given
    without `symbol` is also an error (also caught earlier, at shape-validation, but
    re-asserted here since this function is called directly in tests)."""
    if "container" in raw and "symbol" not in raw:
        raise BigOError(f"{key}: 'container' given without 'symbol'")
    if "symbol" in raw:
        symbol = raw["symbol"]
        container = raw["container"] if "container" in raw else es.DEFAULT_CONTAINER
    else:
        picked = latest_dated_attempt(table, lines)
        if picked is None:
            raise BigOError(
                f"{key}: no dated attempt found to auto-pick a symbol — add `symbol:` "
                f"(and `container:` if it isn't a Solution method)")
        container, symbol = picked
    node = es._resolve_symbol(table, container, symbol, key)
    return container, symbol, node


def options_for(correct: str, key: str, axis: str) -> list[str]:
    """Exactly OPTION_COUNT unique labels including `correct`: CONFUSABLE distractors
    first (shuffled deterministically off `random.Random(f"{key}|{axis}|{correct}")` when
    there are more than needed), then top-up drawn — via the SAME seeded rng, never a
    fixed nearest-first order — from COMPLEXITY_POOL labels within `window` pool-rank
    steps of `correct` (widened if that runs short), so a pure-nearest pick can't pin
    the correct answer to a fixed slot in the sorted return and make its position a
    second, unintended answer key. Returned sorted by POOL_RANK, so option ORDER never
    leaks which one is correct."""
    rng = random.Random(f"{key}|{axis}|{correct}")
    chosen: set[str] = {correct}

    confusables = [c for c in CONFUSABLE.get(correct, ()) if c != correct]
    rng.shuffle(confusables)
    for label in confusables:
        if len(chosen) >= OPTION_COUNT:
            break
        chosen.add(label)

    correct_rank = POOL_RANK[correct]
    window = _POOL_TOP_UP_WINDOW
    while len(chosen) < OPTION_COUNT:
        nearby = [label for label in COMPLEXITY_POOL
                  if label not in chosen and abs(POOL_RANK[label] - correct_rank) <= window]
        if nearby:
            chosen.add(rng.choice(nearby))
        else:
            window += _POOL_TOP_UP_WINDOW

    return sorted(chosen, key=lambda label: POOL_RANK[label])


# ── manifest shape validation (boundary: everything that can be malformed input) ───────

def _validate_entry_shape(raw: dict) -> None:
    """Type/shape checks for one `dashboard/bigo.yml` entry — mirrors
    `export_showcase._validate_entry_shape`'s discipline: fail with a message naming the
    bad field, never a bare KeyError/TypeError later."""
    unknown = set(raw) - ALLOWED_ENTRY_KEYS
    if unknown:
        raise BigOError(f"manifest entry has unknown key(s) {sorted(unknown)}: {raw!r}")
    missing = [k for k in REQUIRED_ENTRY_KEYS if k not in raw]
    if missing:
        raise BigOError(f"manifest entry missing required key(s) {missing}: {raw!r}")

    lc = raw["lc"]
    if not isinstance(lc, int) or isinstance(lc, bool):
        raise BigOError(f"manifest entry 'lc' must be an integer (got {lc!r})")
    for field in ("time", "space"):
        value = raw[field]
        if not isinstance(value, str) or not value.strip():
            raise BigOError(f"lc {lc}: '{field}' must be a non-empty string (got {value!r})")
    if "container" in raw and "symbol" not in raw:
        raise BigOError(f"lc {lc}: 'container' given without 'symbol'")
    for field in ("symbol", "file", "whyTime", "whySpace", "note"):
        if field in raw and raw[field] is not None and not isinstance(raw[field], str):
            raise BigOError(f"lc {lc}: '{field}' must be a string or omitted")
    if "container" in raw and raw["container"] is not None and not isinstance(raw["container"], str):
        raise BigOError(f"lc {lc}: 'container' must be a string or null")
    if "variant" in raw and raw["variant"] is not None:
        variant = raw["variant"]
        if not isinstance(variant, str) or not _KEBAB.match(variant):
            raise BigOError(f"lc {lc}: 'variant' must be kebab-case (got {variant!r})")
    if "helpers" in raw:
        helpers = raw["helpers"]
        if not isinstance(helpers, list) or not all(isinstance(h, str) for h in helpers):
            raise BigOError(f"lc {lc}: 'helpers' must be a list of strings")


# ── entry construction: delegates segment/attemptDate slicing to export_showcase ───────

def build_entry(raw: dict, file_rel: str, table: dict[str, ast.AST], lines: list[str],
                 tree: ast.Module, title: str | None, url: str | None,
                 difficulty: str | None, category: str, is_miss: bool, key: str) -> dict:
    """One `big-o.json` entry for a shape-validated, non-TODO manifest entry. Resolves
    the pick, hard-errors on a scaffold, delegates segment/attemptDate slicing to
    `es.build_entry`, and returns a NEW dict (never mutates `raw`) in the site's field
    order — with the `key` overridden to the big-o key (`es.build_entry` would compute
    `lc:variant`, which is wrong when `variant` is absent)."""
    container, symbol, node = resolve_pick(raw, table, lines, key)
    if is_scaffold(node):
        raise BigOError(
            f"{key}: '{symbol}' is an empty scaffold (no real body) — pick a dated real "
            f"attempt, or set time/space to TODO until one exists")

    normalized_raw = {**raw, "variant": raw.get("variant"), "symbol": symbol, "container": container}
    showcase_entry = es.normalize_entry(normalized_raw, file_rel)
    showcase_built = es.build_entry(showcase_entry, lines, tree, title, url)

    lc = raw["lc"]
    time_label, space_label = raw["time"], raw["space"]

    return {
        "key": key,
        "lcNumber": lc,
        "variant": raw.get("variant"),
        "title": title,
        "url": url,
        "file": file_rel,
        "symbol": symbol,
        "attemptDate": showcase_built["attemptDate"],
        "difficulty": difficulty,
        "category": category,
        "isMiss": is_miss,
        "note": raw.get("note"),
        "time": time_label,
        "space": space_label,
        "whyTime": raw.get("whyTime"),
        "whySpace": raw.get("whySpace"),
        "timeOptions": options_for(time_label, key, "time"),
        "spaceOptions": options_for(space_label, key, "space"),
        "segments": showcase_built["segments"],
    }


# ── boundary: manifest loading, difficulty/miss joins, payload assembly ────────────────

def load_manifest(path: Path) -> dict:
    return es.load_manifest(path)


def difficulty_by_number() -> tuple[dict[int, str], list[str]]:
    """(lc -> Easy/Medium/Hard, warnings) from `effort_budget.parse_rows()` — NOT
    `technique_coverage.py`, which `pip install`s on import (see `gamify.py`'s same
    choice). The first tracker row seen per number wins; a later row that disagrees is a
    warning, not an error (the tracker itself is the source of truth to fix); a number
    with no row at all maps to nothing here — the caller records that as a warning too."""
    warnings: list[str] = []
    by_num: dict[int, str] = {}
    for row in eb.parse_rows():
        num = int(row["num"])
        diff = row["diff"]
        if num not in by_num:
            by_num[num] = diff
        elif by_num[num] != diff:
            warnings.append(f"{num}: tracker rows disagree on difficulty "
                             f"({by_num[num]} vs {diff}) — using {by_num[num]}")
    return by_num, warnings


def miss_numbers() -> frozenset[int]:
    """LC numbers in the complexity-miss ledger. A repo with no ledger file yet (a fresh
    template adopter) has no misses; any other read failure is still a hard error."""
    try:
        text = MISS_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return frozenset()
    except OSError as exc:
        raise BigOError(f"cannot read miss ledger '{MISS_FILE}': {exc}") from exc
    return parse_miss_numbers(text)


_FileCache = dict[Path, tuple[list[str], ast.Module, dict[str, ast.AST]]]


def _resolve_entry_file(raw: dict, key: str, file_cache: _FileCache
                         ) -> tuple[Path, list[str], ast.Module, dict[str, ast.AST]]:
    """(path, lines, tree, table) for one manifest entry's source file — resolved via
    `es.resolve_source_file`/`check_leading_number`, then parsed once per distinct file
    and cached (several variants can share one file)."""
    path = es.resolve_source_file(raw)
    es.check_leading_number(path, raw["lc"], key)
    if path not in file_cache:
        lines = es.read_lines(path)
        tree = ast.parse("\n".join(lines))
        file_cache[path] = (lines, tree, es.symbol_table(tree))
    lines, tree, table = file_cache[path]
    return path, lines, tree, table


def _build_manifest_entry(raw: dict, key: str, difficulty_map: dict[int, str],
                           miss_nums: frozenset[int], file_cache: _FileCache
                           ) -> tuple[dict, list[str]]:
    """(entry, warnings) for one non-TODO, shape-validated, label-validated manifest
    entry — the per-row body of `build_payload`, split out to keep that function short."""
    warnings: list[str] = []
    lc = raw["lc"]
    path, lines, tree, table = _resolve_entry_file(raw, key, file_cache)

    title, url = links.resolve_title_url(str(lc), path)
    if url is None:
        warnings.append(f"{key}: no LeetCode/NeetCode URL found (header or tracker)")
    if lc not in difficulty_map:
        warnings.append(f"{key}: no difficulty found in the tracker for lc {lc}")

    file_rel = path.relative_to(REPO).as_posix()
    entry = build_entry(raw, file_rel, table, lines, tree, title, url,
                         difficulty_map.get(lc), path.parent.name, lc in miss_nums, key)
    return entry, warnings


class BuildPayloadResult(NamedTuple):
    """`build_payload`'s return. `skipped` is recorded explicitly here rather than
    re-derived by pattern-matching `warnings` strings later (the CLI's TODO-skip count
    used to do that, and a warning-message wording change would have silently broken it)."""
    payload: dict
    warnings: list[str]
    skipped: int


def build_payload(manifest: dict, today: dt.date) -> BuildPayloadResult:
    """Raises BigOError on any fatal manifest/contract problem — see the module
    docstring's NOT FAIL-SOFT constraint."""
    warnings: list[str] = []
    seen_keys: set[str] = set()
    file_cache: _FileCache = {}
    entries: list[dict] = []
    skipped = 0

    difficulty_map, difficulty_warnings = difficulty_by_number()
    warnings.extend(difficulty_warnings)
    miss_nums = miss_numbers()

    for raw in manifest["entries"]:
        _validate_entry_shape(raw)
        key = entry_key(raw)
        if key in seen_keys:
            raise BigOError(f"duplicate manifest key '{key}'")
        seen_keys.add(key)

        time_label, space_label = raw["time"], raw["space"]
        if is_todo(time_label) or is_todo(space_label):
            warnings.append(f"{key}: TODO — skipped")
            skipped += 1
            continue
        validate_label(time_label, "time", key)
        validate_label(space_label, "space", key)

        entry, entry_warnings = _build_manifest_entry(
            raw, key, difficulty_map, miss_nums, file_cache)
        warnings.extend(entry_warnings)
        entries.append(entry)

    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": today.isoformat(),
        "pool": list(COMPLEXITY_POOL),
        "entries": entries,
    }
    return BuildPayloadResult(payload, warnings, skipped)


# ── CLI ───────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stdout", action="store_true", help="print the JSON, do not write")
    ap.add_argument("--check", action="store_true",
                     help="build in memory, validate, never write; exit 1 on any failure")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                     help="override generatedAt (default: today)")
    ap.add_argument("--from-index", action="store_true",
                     help="read each solution file's staged (index) content, not the "
                          "working tree — the pre-commit hook's mode")
    args = ap.parse_args()

    reads = es.index_reads() if args.from_index else contextlib.nullcontext()
    with reads:
        _run(args)


def _run(args: argparse.Namespace) -> None:
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    try:
        manifest = load_manifest(MANIFEST)
        if es.is_empty_manifest(manifest):
            print(es.empty_manifest_notice(MANIFEST.name, OUT.name), file=sys.stderr)
            return
        payload, warnings, skipped = build_payload(manifest, today)
    except es.ShowcaseError as exc:  # BigOError subclasses ShowcaseError
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    for w in warnings:
        print(f"  !! {w}", file=sys.stderr)

    if args.check:
        contract_schema.check(payload, SCHEMA)
        if OUT.exists():
            reasons = es._stale_reasons(payload, OUT, label="big-o.json")
            if reasons:
                print("ERROR: dashboard/big-o.json is stale:", file=sys.stderr)
                for reason in reasons:
                    print(f"  - {reason}", file=sys.stderr)
                sys.exit(1)
        print(f"ok: {len(payload['entries'])} entries verified ({skipped} skipped as TODO)",
              file=sys.stderr)
        return

    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.stdout:
        print(rendered)
        return

    contract_schema.check(payload, SCHEMA)
    DASHBOARD.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(payload['entries'])} entries)")


if __name__ == "__main__":
    main()
