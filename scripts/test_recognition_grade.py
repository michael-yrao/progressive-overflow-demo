"""Tests for recognition_grade.py: pick grading, the ledger line, the hit tally.

    python -m unittest scripts/test_recognition_grade.py
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import recognition_grade as rg

TECHNIQUES = """techniques:
  - name: Hash Map Lookup
    family: arrays_and_hash
    problems:
      - {number: 1}
      - {number: 219}
  - name: Two Pointers
    family: two_pointers
    problems:
      - {number: 11}
      - {number: 219}
  - name: Dynamic Programming
    family: dynamic_programming
  - name: Prefix Math
    family: math_sim
  - name: Trie Insert
    family: tries
  - name: Backtracking
    family: backtracking
"""
HAND_WRITTEN = ("- **2026-10-01 · 5 Foo** (🟢 rep) — ✅\n  **hit, not measured.**\n"
                "- **2026-10-02 · 6 Bar** (🟢 site rep) — ❌ **miss: no top-of-method call.** Note.\n")


def hit(answer: str, basis: str = rg.BASIS_TECHNIQUE) -> rg.PickGrade:
    return rg.PickGrade(rg.RESULT_HIT, basis, answer)


class RecognitionGradeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "techniques.yml"
        path.write_text(TECHNIQUES, encoding="utf-8")
        self.decls, self.families = rg.load_declarations(path)

    def test_grade_pick(self):
        miss_tech = rg.PickGrade(rg.RESULT_MISS, rg.BASIS_TECHNIQUE, "Hash Map Lookup")
        cases = [
            ("declared hit", ("Hash Map Lookup", "1", "arrays_and_hash"), hit("Hash Map Lookup")),
            ("declared miss", ("Two Pointers", "1", "arrays_and_hash"), miss_tech),
            ("several declaring, second picked", ("Two Pointers", "219", "arrays_and_hash"),
             hit("Two Pointers")),
            ("several declaring, miss lists both", ("Backtracking", "219", "x"),
             rg.PickGrade(rg.RESULT_MISS, rg.BASIS_TECHNIQUE, "Hash Map Lookup / Two Pointers")),
            ("alias 1d dp", ("Dynamic Programming", "70", "1d_dynamic_programming"),
             hit("dynamic_programming", rg.BASIS_FAMILY)),
            ("alias 2d dp", ("Dynamic Programming", "62", "2d_dynamic_programming"),
             hit("dynamic_programming", rg.BASIS_FAMILY)),
            ("alias math", ("Prefix Math", "48", "math_and_geometry"), hit("math_sim", rg.BASIS_FAMILY)),
            ("alias trie", ("Trie Insert", "208", "trie"), hit("tries", rg.BASIS_FAMILY)),
            ("family miss", ("Backtracking", "300", "trie"),
             rg.PickGrade(rg.RESULT_MISS, rg.BASIS_FAMILY, "tries")),
            ("folder other", ("Backtracking", "300", "other"),
             rg.PickGrade(rg.RESULT_UNGRADED, rg.BASIS_UNDECLARED, "other")),
            ("unknown pick", ("Made Up", "1", "arrays_and_hash"),
             rg.PickGrade(rg.RESULT_UNGRADED, rg.BASIS_UNKNOWN_PICK, "arrays_and_hash")),
        ]
        for label, (picked, number, folder), expected in cases:
            with self.subTest(label):
                self.assertEqual(rg.grade_pick(picked, number, folder, self.decls, self.families), expected)

    def test_pick_line(self):
        head = "- **2026-10-18 · 11 Container** (🟢 site rep; picked before code: Two Pointers) — "
        cases = [
            ("hit", hit("Two Pointers"), head + "✅ **hit** (technique: Two Pointers)."),
            ("miss", rg.PickGrade(rg.RESULT_MISS, rg.BASIS_FAMILY, "tries"),
             head + "❌ **miss** — it is tries (family)."),
            ("ungraded", rg.PickGrade(rg.RESULT_UNGRADED, rg.BASIS_UNDECLARED, "other"),
             head + "⚪ **ungraded** (no declaration; folder other)."),
        ]
        for label, grade, expected in cases:
            with self.subTest(label):
                line = rg.pick_line("2026-10-18", "11", "Container", "🟢", "Two Pointers", grade)
                self.assertEqual(line, expected)

    def test_tally(self):
        grades = [hit("Two Pointers"), rg.PickGrade(rg.RESULT_MISS, rg.BASIS_FAMILY, "tries"),
                  rg.PickGrade(rg.RESULT_UNGRADED, rg.BASIS_UNDECLARED, "other")]
        lines = "\n".join(rg.pick_line("2026-10-18", "11", "C", "🟢", "Two Pointers", g) for g in grades)
        cases = [("empty", "", (0, 0)), ("mixed with hand-written", lines + "\n" + HAND_WRITTEN, (1, 2))]
        for label, text, expected in cases:
            with self.subTest(label):
                self.assertEqual(rg.tally(text), expected)


if __name__ == "__main__":
    unittest.main()
