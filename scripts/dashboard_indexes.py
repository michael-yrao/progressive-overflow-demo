"""Derived dashboard contracts: the practice index and the per-problem showcase split.

The site fetches these small files instead of the full practice.json / showcase.json:

    dashboard/practice-index.json       every practice problem number
    dashboard/showcase-index.json       every showcase problem, its variants and its file
    dashboard/showcase/<lcNumber>.json  that problem's entries, unchanged

Each derived file carries the `schemaVersion` and `generatedAt` of the source JSON it comes
from, so the same source always yields the same bytes. `export_practice.py` and
`export_showcase.py` call the builders below with the payload they just built; running this
script directly derives the same files from the committed practice.json / showcase.json,
without re-reading any solution file:

    python scripts/dashboard_indexes.py

A source JSON that is absent (an adopter who has not generated it yet) is skipped, not an
error: its derived files are simply not produced.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import _console
import contract_schema

REPO = Path(__file__).resolve().parent.parent
DASHBOARD = REPO / "dashboard"

PRACTICE_INDEX_NAME = "practice-index.json"
SHOWCASE_INDEX_NAME = "showcase-index.json"
SHOWCASE_DIR_NAME = "showcase"
PRACTICE_INDEX_SCHEMA = "practice-index.schema.json"
SHOWCASE_INDEX_SCHEMA = "showcase-index.schema.json"
SHOWCASE_PROBLEM_SCHEMA = "showcase-problem.schema.json"
GENERATED_AT_KEY = "generatedAt"


# ── builders ────────────────────────────────────────────────────────────────────────────

def _envelope(source: dict) -> dict:
    return {"schemaVersion": source["schemaVersion"],
            GENERATED_AT_KEY: source[GENERATED_AT_KEY]}


def build_practice_index(practice: dict) -> dict:
    """`{schemaVersion, generatedAt, numbers}` — every problem number, ascending, deduped."""
    numbers = sorted({problem["number"] for problem in practice["problems"]})
    return {**_envelope(practice), "numbers": numbers}


def _group_by_number(entries: list[dict]) -> dict[int, list[dict]]:
    """Entries grouped by lcNumber, each group in showcase.json order."""
    groups: dict[int, list[dict]] = {}
    for entry in entries:
        groups.setdefault(entry["lcNumber"], []).append(entry)
    return groups


def showcase_problem_path(lc_number: int) -> str:
    """The per-problem file's path relative to dashboard/, forward slashes."""
    return f"{SHOWCASE_DIR_NAME}/{lc_number}.json"


def build_showcase_split(showcase: dict) -> dict[str, dict]:
    """Payload per dashboard-relative path: the index plus one file per lcNumber."""
    groups = _group_by_number(showcase["entries"])
    envelope = _envelope(showcase)
    index_problems = [
        {"lcNumber": number,
         "variants": [entry["variant"] for entry in groups[number]],
         "file": showcase_problem_path(number)}
        for number in sorted(groups)
    ]
    files = {SHOWCASE_INDEX_NAME: {**envelope, "problems": index_problems}}
    for number, entries in groups.items():
        files[showcase_problem_path(number)] = {**envelope, "entries": entries}
    return files


def build_practice_files(practice: dict) -> dict[str, dict]:
    return {PRACTICE_INDEX_NAME: build_practice_index(practice)}


# ── rendering, writing, checking ───────────────────────────────────────────────────────

def render_compact(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def _stale_showcase_files(dashboard: Path, files: dict[str, dict]) -> list[Path]:
    """`dashboard/showcase/*.json` on disk that `files` no longer names."""
    directory = dashboard / SHOWCASE_DIR_NAME
    if not directory.is_dir():
        return []
    return [path for path in sorted(directory.glob("*.json"))
            if f"{SHOWCASE_DIR_NAME}/{path.name}" not in files]


def write_files(dashboard: Path, files: dict[str, dict], *, prune_showcase: bool = False) -> None:
    """Write each payload compact; with `prune_showcase`, delete showcase/*.json not in
    `files`."""
    for relative, payload in files.items():
        target = dashboard / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_compact(payload), encoding="utf-8")
    if prune_showcase:
        for stale in _stale_showcase_files(dashboard, files):
            stale.unlink()


def _without_date(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    return {key: value for key, value in payload.items() if key != GENERATED_AT_KEY}


def _drift_reason(path: Path, relative: str, payload: dict) -> str | None:
    """Why the on-disk file differs from `payload` (ignoring generatedAt), or None."""
    if not path.exists():
        return f"{relative}: missing — regenerate"
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"{relative}: cannot read: {exc}"
    if _without_date(existing) != _without_date(payload):
        return f"{relative}: differs from its source — regenerate"
    return None


def stale_reasons(dashboard: Path, files: dict[str, dict], *,
                  check_extra_showcase: bool = False) -> list[str]:
    """Every way the on-disk derived files drift from `files`: differing, missing, and (with
    `check_extra_showcase`) a showcase/*.json that should not exist."""
    reasons = [reason for relative, payload in files.items()
               if (reason := _drift_reason(dashboard / relative, relative, payload))]
    if check_extra_showcase:
        reasons.extend(f"{SHOWCASE_DIR_NAME}/{path.name}: extra file — regenerate"
                       for path in _stale_showcase_files(dashboard, files))
    return reasons


# ── schema validation ──────────────────────────────────────────────────────────────────

def _lowest_problem_path(files: dict[str, dict]) -> str | None:
    """The per-problem file with the lowest lcNumber in `files`, or None."""
    prefix = f"{SHOWCASE_DIR_NAME}/"
    numbered = [(int(Path(path).stem), path) for path in files
                if path.startswith(prefix) and Path(path).stem.isdigit()]
    return min(numbered)[1] if numbered else None


def schema_errors(files: dict[str, dict]) -> list[str]:
    """Schema violations in the two indexes and ONE sampled per-problem payload (the lowest
    lcNumber's); only the keys present in `files` are checked."""
    sample = _lowest_problem_path(files)
    checks = [(PRACTICE_INDEX_NAME, PRACTICE_INDEX_SCHEMA),
              (SHOWCASE_INDEX_NAME, SHOWCASE_INDEX_SCHEMA)]
    if sample:
        checks.append((sample, SHOWCASE_PROBLEM_SCHEMA))
    return [f"{relative}: {message}"
            for relative, schema_name in checks if relative in files
            for message in contract_schema.validate(files[relative], DASHBOARD / schema_name)]


def load_validation_sample(dashboard: Path) -> dict[str, dict]:
    """The on-disk files `schema_errors` checks: both indexes and the lowest-numbered
    per-problem file, each only if it exists."""
    names = [f"{SHOWCASE_DIR_NAME}/{path.name}"
             for path in (dashboard / SHOWCASE_DIR_NAME).glob("*.json")]
    sample = _lowest_problem_path(dict.fromkeys(names))
    wanted = [PRACTICE_INDEX_NAME, SHOWCASE_INDEX_NAME, *([sample] if sample else [])]
    return {relative: _load_json(dashboard / relative)
            for relative in wanted if (dashboard / relative).is_file()}


def exit_on_schema_errors(files: dict[str, dict]) -> None:
    """Print any schema violation to stderr and exit 2, so the caller writes nothing."""
    contract_schema.exit_on_errors("derived dashboard files violate their schema:",
                                   schema_errors(files))


# ── CLI: derive from the committed source JSON ─────────────────────────────────────────

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _derive_if_present(source: Path, build: Callable[[dict], dict[str, dict]]) -> dict[str, dict]:
    """`build` applied to the source JSON, or {} when the source has not been generated."""
    return build(_load_json(source)) if source.is_file() else {}


def build_derived(dashboard: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """The practice files and the showcase files derived from the committed source JSON;
    each is {} when its source JSON is absent."""
    return (_derive_if_present(dashboard / "practice.json", build_practice_files),
            _derive_if_present(dashboard / "showcase.json", build_showcase_split))


def main() -> None:
    try:
        practice_files, showcase_files = build_derived(DASHBOARD)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: cannot derive from dashboard JSON: {exc!r}", file=sys.stderr)
        sys.exit(1)
    if not practice_files and not showcase_files:
        print("no practice.json or showcase.json - nothing to derive")
        return
    exit_on_schema_errors({**practice_files, **showcase_files})
    write_files(DASHBOARD, practice_files)
    if showcase_files:
        write_files(DASHBOARD, showcase_files, prune_showcase=True)
    print(f"wrote {len(practice_files) + len(showcase_files)} derived files under dashboard/")


if __name__ == "__main__":
    main()
