"""Tests for schedule_priority.py's priority_key() and sort_day_blocks().

Stdlib unittest, same style as test_gamify.py/test_remaining.py: fixtures as plain
strings/dicts, asserted through the public functions rather than internals.

    python scripts/test_schedule_priority.py
"""
from __future__ import annotations

import random
import unittest

import schedule_priority


class PriorityKeyTests(unittest.TestCase):
    """The rank table (0-9) from the module docstring, in one shuffled-then-sorted pass:
    🎤 < 🔴 < 🟡 < 🆕 < 🎯 < 🟢 Medium s0 < 🟢 Medium s2 < 🟢 Easy s1 < 🎓 < a Complexity row
    whose Start is 🟢 < an unclassified row."""

    def test_priority_order(self):
        rows = [
            ("mock", {"start": None, "is_mock": True}, None),
            ("red", {"start": "🔴"}, None),
            ("yellow", {"start": "🟡"}, None),
            ("new", {"start": None, "is_new": True}, None),
            ("probe", {"start": None, "is_probe": True}, None),
            ("green_medium_s0", {"start": "🟢", "start_streak": 0}, "Medium"),
            ("green_medium_s2", {"start": "🟢", "start_streak": 2}, "Medium"),
            ("green_easy_s1", {"start": "🟢", "start_streak": 1}, "Easy"),
            ("graduated", {"start": "🎓"}, None),
            ("complexity_on_green",
             {"start": "🟢", "start_streak": 2, "is_complexity": True}, "Medium"),
            ("unclassified", {"start": None}, None),
        ]
        expected = [label for label, _, _ in rows]

        shuffled = list(rows)
        random.Random(0).shuffle(shuffled)
        ordered = sorted(shuffled, key=lambda row: schedule_priority.priority_key(row[1], row[2]))

        self.assertEqual([label for label, _, _ in ordered], expected)


class SortDayBlocksTests(unittest.TestCase):
    """Two day blocks — Monday unsorted (a struck 🟡 conversion filed ahead of two 🟢
    reviews, plus the trailing blank separator row) and Tuesday already sorted — followed
    by a later, non-daily 5-column table."""

    DIFFICULTY = {"300": "Easy", "100": "Medium"}

    MON_HEADER = "| ▸ **Mon Sep 28** · 7.0 units |  |  |  |  |"
    MON_EASY_ROW = "| [300 Easy Review](../x.py) · [LC](url) | 🟢 s1 |  |  | Foo |"
    MON_MEDIUM_ROW = "| [100 Medium Review](../y.py) · [LC](url) | 🟢 s1 |  |  | Bar |"
    MON_CONVERSION_ROW = "| ~~[9 Conversion](../z.py) · [LC](url)~~ | 🟡 |  |  | Baz |"
    SEPARATOR = "|  |  |  |  |  |"
    TUE_HEADER = "| ▸ **Tue Sep 29** · 5.0 units |  |  |  |  |"
    TUE_ROW = "| [200 Medium Review](../w.py) · [LC](url) | 🟢 s0 |  |  | Qux |"
    LATER_TABLE = (
        "| Later | Table | With | Five | Cols |\n"
        "|---|---|---|---|---|\n"
        "| a | b | c | d | e |\n"
    )

    FIXTURE = (
        "## Daily Schedule\n"
        "\n"
        f"{MON_HEADER}\n"
        f"{MON_EASY_ROW}\n"
        f"{MON_MEDIUM_ROW}\n"
        f"{MON_CONVERSION_ROW}\n"
        f"{SEPARATOR}\n"
        f"{TUE_HEADER}\n"
        f"{TUE_ROW}\n"
        f"{SEPARATOR}\n"
        "\n"
        f"{LATER_TABLE}"
    )

    def test_sorts_the_unsorted_day_and_leaves_the_rest_byte_identical(self):
        result = schedule_priority.sort_day_blocks(self.FIXTURE, self.DIFFICULTY)
        lines = result.splitlines()

        mon_index = lines.index(self.MON_HEADER)
        # The conversion (🟡) sorts first, then the Medium review, then the Easy review —
        # the header stays first and the blank separator stays last.
        self.assertEqual(lines[mon_index + 1:mon_index + 5], [
            self.MON_CONVERSION_ROW,
            self.MON_MEDIUM_ROW,
            self.MON_EASY_ROW,
            self.SEPARATOR,
        ])

        # Tuesday (already in order) and everything from its header on — including the
        # later, non-daily table — is untouched.
        tue_index_before = self.FIXTURE.splitlines().index(self.TUE_HEADER)
        self.assertEqual(lines[lines.index(self.TUE_HEADER):],
                          self.FIXTURE.splitlines()[tue_index_before:])

        # A second pass is a no-op (the sort is stable).
        self.assertEqual(schedule_priority.sort_day_blocks(result, self.DIFFICULTY), result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
