"""Tests for effort_budget.py's row cap and unproven-overdue backstop.

    python -m pytest scripts/test_effort_budget.py -q
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import unittest
from unittest import mock

import curriculum
import effort_budget as eb

_CFG = eb.load_config()
_MIN_STREAK = _CFG["carry_forward_min_streak"]
_PAUSE_AT = _CFG["intake_pause_overdue_unproven"]
_TODAY = dt.date(2026, 10, 6)
_OVERDUE = "2026-10-01"


def _tracker_row(comfort: str, streak: int) -> dict:
    return {"comfort": comfort, "streak": streak, "due": _OVERDUE}


class LookupUntrackedDifficultyTests(unittest.TestCase):
    def test_lookup_untracked_difficulty(self):
        cases = [
            ("tracker table wins", {"5": "Easy"}, {"difficulty": "Hard"}, ("Easy", False)),
            ("milestone row", {}, {"difficulty": "Hard"}, ("Hard", False)),
            ("catalog lacks it: guessed Medium", {}, None, ("Medium", True)),
        ]
        for label, table, entry, expected in cases:
            with self.subTest(label), \
                    mock.patch.object(eb, "_tracker_table_difficulty", return_value=table), \
                    mock.patch.object(eb, "_roadmap_difficulty", return_value={}), \
                    mock.patch.object(eb, "_probe_pool_difficulty", return_value={}), \
                    mock.patch.object(curriculum, "catalog_entry", return_value=entry):
                self.assertEqual(eb.lookup_untracked_difficulty("5"), expected)


class CountRowsTests(unittest.TestCase):
    def test_counts_every_row_but_complexity_and_separators(self):
        lines = [
            "| [5 A](x.py) · [LC](y) | 🟢 s2 | | | Greedy |",
            "| ~~[6 B](x.py) · [LC](y)~~ | 🟢 s2 | 🟢 | 2026-12-01 | Greedy |",
            "| 4 cold complexity probes | 🎯 | | | Complexity |",
            "|---|:-:|:-:|:-:|---|",
            "| → [7 C](x.py) · [LC](y) | 🟢 s2 | | 2026-12-01 | Greedy |",
        ]
        cases = [
            ("plain row counts", lines[:1], 1),
            ("struck row counts", lines[1:2], 1),
            ("complexity row does not", lines[2:3], 0),
            ("separator does not", lines[3:4], 0),
            ("moved row does not", lines[4:], 0),
            ("all together", lines, 2),
        ]
        for name, block, expected in cases:
            with self.subTest(name):
                items = [it for it in map(eb.parse_sched_line, block) if it is not None]
                self.assertEqual(eb.count_rows(items), expected)


class DayHeaderFiguresTests(unittest.TestCase):
    def test_units_and_planned(self):
        cases = [
            ("pinned", "| ▸ **Wed Oct 7** · ~3.8 units · planned 6.6 units — label |  |  |  |  |",
             dt.date(2026, 10, 7), (3.8, 6.6)),
            ("unpinned", "| ▸ **Wed Oct 7** · ~3.8 units — label |  |  |  |  |",
             dt.date(2026, 10, 7), (3.8, None)),
            ("sunday with a trailing block",
             "| ▸ **Sun Mar 14** · ~6.8 units · planned 7.0 units + complexity block — x |  |  |  |  |",
             dt.date(2027, 3, 14), (6.8, 7.0)),
        ]
        for name, line, day, expected in cases:
            with self.subTest(name):
                self.assertEqual(eb.day_header_figures([line], day), expected)


class DeferralWarningTests(unittest.TestCase):
    def test_unreadable_deferral_warns_and_reads_as_not_deferred(self):
        cases = [
            ("non-ISO Next warns", "| → [743 A](x.py) · [LC](y) | 🟡 | | Dec 7 | Graph |", None, True),
            ("ISO Next is silent", "| → [743 A](x.py) · [LC](y) | 🟡 | | 2026-12-07 | Graph |",
             "2026-12-07", False),
            ("struck row is silent", "| ~~→ [743 A](x.py)~~ · [LC](y) | 🟡 | 🟢 | Dec 7 | Graph |", None, False),
            ("legacy → cell is silent", "| → [743 A](x.py) · [LC](y) | 🟡 | | → Aug 31 wk | Graph |", None, False),
        ]
        for name, line, expected_to, expects_warning in cases:
            with self.subTest(name):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    item = eb.parse_sched_line(line)
                self.assertEqual(item["deferred_to"], expected_to)
                self.assertEqual("'Dec 7'" in stderr.getvalue() and "743" in stderr.getvalue(),
                                 expects_warning)
                if not expects_warning:
                    self.assertEqual(stderr.getvalue(), "")


class MoveArrowRowTests(unittest.TestCase):
    def test_left_arrow_row_is_deferred_when_unstruck_and_done_when_struck(self):
        cases = [
            ("unstruck ← with Next date is deferred, not done",
             "| ← [332 A](x.py) · [LC](y) | 🟢 s1 | | 2026-10-09 | Hierholzer |",
             "2026-10-09", False),
            ("struck ← row is done, not deferred",
             "| ← ~~[332 A](x.py)~~ · [LC](y) | 🟢 s1 | 🟡 | 2026-10-19 | Hierholzer |",
             None, True),
        ]
        for name, line, expected_to, expected_done in cases:
            with self.subTest(name):
                item = eb.parse_sched_line(line)
                self.assertEqual(item["deferred_to"], expected_to)
                self.assertEqual(item["done"], expected_done)
                self.assertEqual(item["num"], "332")


class RowCapLinesTests(unittest.TestCase):
    def test_warning_line_only_over_the_cap(self):
        cap = _CFG["max_rows_per_day"]
        cases = [("at cap", cap, 1), ("over cap", cap + 1, 2)]
        for name, count, expected_lines in cases:
            with self.subTest(name):
                self.assertEqual(len(eb.row_cap_lines(count, _CFG)), expected_lines)


class IsUnprovenTests(unittest.TestCase):
    def test_unproven_below_carry_streak_proven_at_or_above(self):
        cases = [
            ("green below min streak", "🟢", _MIN_STREAK - 1, True),
            ("green at min streak", "🟢", _MIN_STREAK, False),
            ("graduated", "🎓", 0, False),
        ]
        for name, comfort, streak, expected in cases:
            with self.subTest(name):
                self.assertEqual(eb.is_unproven(comfort, streak, _CFG), expected)


class UnprovenOverdueTests(unittest.TestCase):
    def test_backstop_triggers_at_the_pause_threshold(self):
        cases = [
            ("one under", _PAUSE_AT - 1, False),
            ("at threshold", _PAUSE_AT, True),
        ]
        for name, count, expected_triggered in cases:
            with self.subTest(name):
                rows = [_tracker_row("🔴", 0)] * count
                self.assertEqual(eb.unproven_overdue(rows, _CFG, _TODAY),
                                 (count, expected_triggered))


if __name__ == "__main__":
    unittest.main()
