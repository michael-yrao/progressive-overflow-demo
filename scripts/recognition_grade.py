"""Grade a technique pick the site recorded before the learner wrote code.

Pure: no repo reads except `load_declarations`' one read of techniques.yml. A pick is graded against
the technique entries that declare the problem's number; with none, against the solution folder's
family. fold_record.log_recognition_pick writes the ledger line `pick_line` builds.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from technique_coverage import TECHNIQUES_YML

FOLDER_FAMILY = {"1d_dynamic_programming": "dynamic_programming",
                 "2d_dynamic_programming": "dynamic_programming",
                 "math_and_geometry": "math_sim", "trie": "tries"}
RESULT_HIT = "hit"
RESULT_MISS = "miss"
RESULT_UNGRADED = "ungraded"
BASIS_TECHNIQUE = "technique"
BASIS_FAMILY = "family"
BASIS_UNDECLARED = "no declaration"
BASIS_UNKNOWN_PICK = "unknown pick"
NAME_SEPARATOR = " / "
PICK_MARKER = "picked before code:"
HIT_MARK = "✅ **hit**"
MISS_MARK = "❌ **miss**"
LINE_HEAD = "- **{iso} · {number} {title}** ({glyph} site rep; picked before code: {picked}) — "
LINE_TAIL = {
    RESULT_HIT: "✅ **hit** ({basis}: {answer}).",
    RESULT_MISS: "❌ **miss** — it is {answer} ({basis}).",
    RESULT_UNGRADED: "⚪ **ungraded** ({basis}; folder {answer}).",
}


@dataclass(frozen=True)
class PickGrade:
    result: str
    basis: str
    answer: str


def load_declarations(path: Path = TECHNIQUES_YML) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """(number -> declaring entry names in file order, name -> family); the first entry wins on a
    duplicate name. A missing file gives two empty maps."""
    if not path.is_file():
        return {}, {}
    entries = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("techniques") or []
    declared: dict[str, list[str]] = {}
    families: dict[str, str] = {}
    for entry in entries:
        name = entry["name"]
        families.setdefault(name, entry.get("family"))
        for problem in entry.get("problems") or []:
            declared.setdefault(str(problem["number"]), []).append(name)
    return {number: tuple(names) for number, names in declared.items()}, families


def grade_pick(picked: str, number: str, folder: str, decls: dict[str, tuple[str, ...]],
               families: dict[str, str]) -> PickGrade:
    if picked not in families:
        return PickGrade(RESULT_UNGRADED, BASIS_UNKNOWN_PICK, folder)
    names = decls.get(number)
    if names:
        if picked in names:
            return PickGrade(RESULT_HIT, BASIS_TECHNIQUE, picked)
        return PickGrade(RESULT_MISS, BASIS_TECHNIQUE, NAME_SEPARATOR.join(names))
    family = FOLDER_FAMILY.get(folder, folder)
    if family in families.values():
        result = RESULT_HIT if families[picked] == family else RESULT_MISS
        return PickGrade(result, BASIS_FAMILY, family)
    return PickGrade(RESULT_UNGRADED, BASIS_UNDECLARED, folder)


def pick_line(iso: str, number: str, title: str, glyph: str, picked: str, grade: PickGrade) -> str:
    head = LINE_HEAD.format(iso=iso, number=number, title=title, glyph=glyph, picked=picked)
    return head + LINE_TAIL[grade.result].format(basis=grade.basis, answer=grade.answer)


def tally(text: str) -> tuple[int, int]:
    """(hits, graded) over the pick lines in a ledger; ungraded and hand-written lines count in neither."""
    pick_lines = [line for line in text.splitlines() if PICK_MARKER in line]
    hits = sum(HIT_MARK in line for line in pick_lines)
    misses = sum(MISS_MARK in line for line in pick_lines)
    return hits, hits + misses
