"""The DSA curriculum catalog: milestone.yml flattened into one ordered problem list.

The file lives at curriculum/dsa/milestone.yml (shipped by cse-coach). This repo may not
carry it; every reader here degrades to an empty catalog rather than raising, so a repo
without a curriculum simply has nothing to seat as new work.

    phases:
      - name: Arrays & Hashing
        folder: arrays_and_hash        # optional; else snake_case of the name
        problems:
          - { number: 217, title: "Contains Duplicate", difficulty: Easy }

Each file is parsed once per path (the loader is cached), because catalog_entry is called
per problem inside loops.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MILESTONE = REPO_ROOT / "curriculum" / "dsa" / "milestone.yml"

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def folder_for(phase: dict) -> str:
    """The phase's `folder:` key, else its name as snake_case."""
    explicit = phase.get("folder")
    if explicit:
        return str(explicit)
    return _NON_ALNUM.sub("_", str(phase.get("name", "")).lower()).strip("_")


def _entry(phase: dict, problem: dict) -> dict:
    if "number" not in problem or "title" not in problem:
        raise ValueError(f"milestone problem needs a number and a title: {problem!r}")
    return {
        "number": int(problem["number"]),
        "title": str(problem["title"]),
        "difficulty": str(problem.get("difficulty", "")),
        "folder": folder_for(phase),
    }


@functools.cache
def _load(path_text: str) -> tuple[tuple[tuple[str, object], ...], ...]:
    """Flattened entries for one file, as tuples of items so the cached value is immutable."""
    path = Path(path_text)
    if not path.is_file():
        return ()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    flat = [
        _entry(phase, problem)
        for phase in data.get("phases") or []
        for problem in phase.get("problems") or []
    ]
    return tuple(tuple(entry.items()) for entry in flat)


def intake_order(path: Path = DEFAULT_MILESTONE) -> tuple[dict, ...]:
    """Every problem of every phase, phases in file order. Empty when the file is absent."""
    return tuple(dict(items) for items in _load(str(path)))


@functools.cache
def _index(path_text: str) -> dict[int, tuple[tuple[str, object], ...]]:
    return {dict(items)["number"]: items for items in reversed(_load(path_text))}


def catalog_entry(number: int, path: Path = DEFAULT_MILESTONE) -> dict | None:
    """{title, difficulty, folder} for a problem number, or None when the catalog lacks it."""
    items = _index(str(path)).get(number)
    if items is None:
        return None
    entry = dict(items)
    return {key: entry[key] for key in ("title", "difficulty", "folder")}
