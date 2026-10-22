"""Tests for remaining.py's ROW_NUMBER — the regex behind the "what's left" board.

Stdlib unittest, same style as test_gamify.py: a small fixture file in a temp dir, read
through unstruck_numbers() rather than asserting on the regex object directly, so a
future rewrite of ROW_NUMBER only breaks this file if the observable output changes.

    python scripts/test_remaining.py
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import remaining


class UnstruckNumbersTests(unittest.TestCase):
    """A day-block mixing every row shape ROW_NUMBER must (or must not) carry a number
    for: a plain linked row, a tag-glyph-prefixed linked row, a bare 🆕 intake with no
    local file yet to link, a struck-through row (done, must stay excluded), a line that
    is not a table row at all, a linked row behind a prefix OUTSIDE the tag-glyph legend
    (🔁 review marker, a `**PROBE #6** —` label), a plain summary/carry-table row
    whose first cell is a bare count or number with no legend glyph (must NOT be misread
    as a bare 🆕 intake), and a deferred (→) row kept unstruck on its planned day with
    an ISO date in its Next cell — excluded even though it carries no `~~`."""

    LABEL = "Wed Sep 23"

    FIXTURE = f"""## Daily Schedule

| Problem | S | E | Next | Technique |
|---|:-:|:-:|:-:|---|
| ▸ **{LABEL}** · 7.6 units — sample day |  |  |  |  |
| [560 Subarray Sum Equals K](../../../dsa/leetcode/arrays_and_hash/560_subarray_sum_equals_k.py) · [LC](https://leetcode.com/problems/subarray-sum-equals-k/) | 🟡 | | | Prefix-sum |
| 🔥 [846 Hand of Straights](../../../dsa/leetcode/greedy/846_hand_of_straights.py) · [LC](https://leetcode.com/problems/hand-of-straights/) | 🟡 | | | Greedy |
| 🆕 39 Combination Sum · [LC](https://leetcode.com/problems/combination-sum/) | 🆕 | | | Backtracking |
| ~~[134 Gas Station](../../../dsa/leetcode/greedy/134_gas_station.py) · [LC](https://leetcode.com/problems/gas-station/)~~ | 🟡 | 🟢 | 2026-10-21 | Greedy |
| 🔁 [57 Insert Interval](../../../dsa/leetcode/arrays_and_hash/57_insert_interval.py) · [LC](https://leetcode.com/problems/insert-interval/) | 🟡 | | | Intervals |
| 🎯 **PROBE #6** — [637 Average of Levels](../../../dsa/probes/637_average_of_levels_in_binary_tree.py) · [LC](https://leetcode.com/problems/average-of-levels-in-binary-tree/) | 🟢 | | | BFS |
| → [202 Happy Number](../../../dsa/leetcode/graphs/202_happy_number.py) · [LC](https://leetcode.com/problems/happy-number/) | 🟢 s1 |  | 2026-10-01 | Cycle-detection |
| 5 overdue rows | 9.0 |
| 743 Network Delay Time | Aug 4 |
A stray line of prose, not a table row at all — must not be read as one.
"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.schedule = Path(self._tmpdir.name) / "20260921_schedule.md"
        self.schedule.write_text(self.FIXTURE, encoding="utf-8")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _numbers(self) -> list[str]:
        return remaining.unstruck_numbers(self.schedule, self.LABEL)

    def test_bracketed_row_is_counted(self):
        self.assertIn("560", self._numbers())

    def test_tag_glyph_bracketed_row_is_counted(self):
        self.assertIn("846", self._numbers())

    def test_bare_new_intake_row_is_counted(self):
        # The bug this file exists to pin: a 🆕 row with no `[` before its number used
        # to be silently dropped.
        self.assertIn("39", self._numbers())

    def test_struck_row_is_excluded(self):
        self.assertNotIn("134", self._numbers())

    def test_review_marker_outside_the_legend_is_still_counted(self):
        # 🔁 isn't one of ROW_TAG_GLYPHS, but the bracketed branch's prefix is permissive
        # by design (unlike the bare-number branch) — this must not regress.
        self.assertIn("57", self._numbers())

    def test_probe_label_prefix_is_still_counted(self):
        self.assertIn("637", self._numbers())

    def test_bare_number_with_no_legend_glyph_is_not_counted(self):
        # A carry/summary-table row ("5 overdue rows"), not a problem row — must not be
        # misread via the bare-number branch, which requires a legend glyph.
        self.assertNotIn("5", self._numbers())

    def test_bare_number_prefix_of_a_non_intake_row_is_not_counted(self):
        # Same trap, a real LC number as the bare leading token of a non-intake row.
        self.assertNotIn("743", self._numbers())

    def test_deferred_row_is_excluded(self):
        # A → row stays unstruck on its planned day with the day it moved TO in its
        # Next cell -- not actually open here, even though (unlike a struck row) it
        # carries no `~~`.
        self.assertNotIn("202", self._numbers())

    def test_non_row_prose_line_contributes_no_number(self):
        # Every number present is accounted for by the genuine problem rows above; any
        # extra would mean a non-problem line was misread as one.
        self.assertEqual(len(self._numbers()), 5)

    def test_order_matches_the_day_blocks_row_order(self):
        self.assertEqual(self._numbers(), ["560", "846", "39", "57", "637"])


class SplitOpenNumbersTests(unittest.TestCase):
    """split_open_numbers() separates coding rows from `Complexity`-technique rows, both
    in file order, and drops struck rows from either group."""

    LABEL = "Sun Mar 14"
    HEADER = "| ▸ **" + LABEL + "** · 3.0 units — sample |  |  |  |  |"
    CODING = "| [9003 Lost Map](../a.py) · [PO](https://x) | 🟡 | | | Graphs |"
    CODING_2 = "| [133 Clone Graph](../b.py) · [LC](https://x) | 🟡 | | | BFS |"
    COMPLEXITY = "| [211 Design Add](../c.py) · [LC](https://x) | 🟢 | | | Complexity  |"
    STRUCK_COMPLEXITY = "| ~~[648 Replace Words](../d.py) · [LC](https://x)~~ | 🟢 | 🟢 | | Complexity |"

    def test_splits_by_technique_cell(self):
        cases = [
            ("mixed block", [self.CODING, self.COMPLEXITY, self.CODING_2], (["9003", "133"], ["211"])),
            ("struck complexity row excluded", [self.CODING, self.STRUCK_COMPLEXITY], (["9003"], [])),
            ("no complexity rows", [self.CODING, self.CODING_2], (["9003", "133"], [])),
        ]
        for name, rows, expected in cases:
            with self.subTest(name=name):
                text = "\n".join([self.HEADER, *rows]) + "\n"
                with tempfile.TemporaryDirectory() as tmp:
                    schedule = Path(tmp) / "20270308_schedule.md"
                    schedule.write_text(text, encoding="utf-8")
                    self.assertEqual(
                        remaining.split_open_numbers(schedule, self.LABEL), expected)


class OpenMockTests(unittest.TestCase):
    """open_mock() is true only for a 🎤 row that is neither struck (done) nor deferred
    (→, an ISO date in its Next cell) -- the same openness test unstruck_numbers() uses."""

    LABEL = "Sun Mar 14"

    def test_open_only_for_an_unstruck_undeferred_mock_row(self):
        cases = [
            ("| 🎤 Mock interview (Medium) | 🎤 |  |  | Mock |", True),
            ("| ~~🎤 Mock interview (Medium)~~ | 🎤 | 🟡 | 2027-03-24 | Mock |", False),
            ("| → 🎤 Mock interview (Medium) | 🎤 |  | 2027-03-15 | Mock |", False),
        ]
        for row, expected in cases:
            with self.subTest(row=row):
                text = ("| ▸ **" + self.LABEL + "** · 3.0 units — mock day |  |  |  |  |"
                        + "\n" + row + "\n")
                with tempfile.TemporaryDirectory() as tmp:
                    schedule = Path(tmp) / "20270308_schedule.md"
                    schedule.write_text(text, encoding="utf-8")
                    self.assertEqual(remaining.open_mock(schedule, self.LABEL), expected)


class MethodLabelTests(unittest.TestCase):
    """The board line names the due method only for a problem with 2+ tracker rows."""

    LABEL = "Mon Mar 15"
    BASE = "[{n} T](dsa/x.py) · [LC](https://x)"

    def test_label_cases(self):
        cases = [
            ("single-row problem: no suffix", "| [9 Two Sum](../x.py) · [LC](u) | 🟢 | | | Hash |",
             {"9": 1}, "9", ""),
            ("multi-row, due row is the 2nd variant: suffix",
             "| [53 Maximum Subarray (Prefix Sum)](../x.py) · [LC](u) | 🟢 | | | Prefix-sum |",
             {"53": 2}, "53", " · method: Prefix Sum"),
            ("real-title parenthetical, single row: unchanged",
             "| [208 Implement Trie (Prefix Tree)](../x.py) · [LC](u) | 🟢 | | | Trie |",
             {"208": 1}, "208", ""),
        ]
        for name, row, counts, number, suffix in cases:
            with self.subTest(name=name):
                text = f"| ▸ **{self.LABEL}** · 1.0 units — t |  |  |  |  |\n{row}\n"
                with tempfile.TemporaryDirectory() as tmp:
                    schedule = Path(tmp) / "20270315_schedule.md"
                    schedule.write_text(text, encoding="utf-8")
                    methods = remaining.open_row_methods(schedule, self.LABEL)
                line = self.BASE.format(n=number)
                self.assertEqual(remaining.label_line(line, number, methods, counts), line + suffix)


class OrderByPriorityTests(unittest.TestCase):
    """order_by_priority() is the tie-break main() applies between unstruck_numbers()'s
    file order and schedule_priority.day_order()'s priority order: a day whose file order
    puts a 🟢 review ahead of a 🟡 conversion must print the 🟡 first, and a number
    day_order() never saw must sink to the end."""

    def test_reorders_by_priority_and_sinks_an_unpriced_number(self):
        numbers = ["560", "846", "999"]  # file order; 999 has no day_order entry
        priority = ["846", "560"]  # 846 (🟡) outranks 560 (🟢) in the day's priority
        self.assertEqual(
            remaining.order_by_priority(numbers, priority),
            ["846", "560", "999"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
