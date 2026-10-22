"""Tests for backlog_forecast.py: tally parser, ladder step, a deterministic 2-week replay.

    python -m pytest scripts/test_backlog_forecast.py -q
"""
from __future__ import annotations

import datetime as dt
import random
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backlog_forecast as bf  # noqa: E402

LADDER = {"blank": 2, "shaky": 10, "provisional": 10, "streak1": 30, "streak2": 60,
          "graduated": 180, "graduate_at": 3}

SCHEDULE_FIXTURE = """\
| Problem | Start | End | Next | Technique |
|---|---|---|---|---|
| ▸ **Tue Oct 6** · 5.0 units | 🟡 | 🟢 |  |  |
| [1 Two Sum](x) | 🟡 | 🟢 | 2026-10-16 | Hash |
| [2 Add Two](x) | 🟢 | 🟡 | 2026-10-16 | Lists |
| [3 Pending](x) | 🟢 s2 |  |  | Lists |
| 🆕 [4 New](x) | 🆕 | 🔴 | 2026-10-08 | Trees |
"""

CFG = {"max_rows_per_day": 8, "ceiling": 8.0, "carry_forward_min_streak": 2,
       "comfort_units": {"🔴": 3.0, "🟡": 2.0, "🟢": 1.0, "🎓": 0.5},
       "difficulty": {"Easy": 0.5, "Medium": 1.0, "Hard": 1.3},
       "green_streak_units": {0: 1.0, 1: 0.8, 2: 0.6}}


def _due_rows(count: int, comfort: str, diff: str, start: dt.date) -> list[dict]:
    return [{"comfort": comfort, "streak": 0, "diff": diff, "due": start.toordinal(), "attempts": 1}
            for _ in range(count)]


def _stay_overdue_outcome(cls: str, rng: random.Random) -> str:
    return "🟡"   # a seated row leaves the overdue pool (+10 days); an unseated one stays in it


class BacklogForecastTests(unittest.TestCase):
    def test_tally_text_classes_bare_green_as_s1_and_skips_header_and_empty_end(self) -> None:
        self.assertEqual(
            bf.tally_text(SCHEDULE_FIXTURE),
            Counter({("🟡", "🟢"): 1, ("🟢 s1", "🟡"): 1, ("🆕", "🔴"): 1}))


    def test_ladder_step_table(self) -> None:
        cases = [
            (("🟢", 1, "🔴"), ("🔴", 0, 2)),
            (("🟢", 1, "🟡"), ("🟡", 0, 10)),
            (("🟡", 0, "🟢"), ("🟢", 0, 10)),
            (("🔴", 0, "🟢"), ("🟢", 0, 10)),
            (("🟢", 0, "🟢"), ("🟢", 1, 30)),
            (("🟢", 1, "🟢"), ("🟢", 2, 60)),
            (("🟢", 2, "🟢"), ("🎓", 3, 180)),
            (("🎓", 3, "🟢"), ("🎓", 4, 180)),
            (("🎓", 3, "🟡"), ("🟡", 0, 10)),
        ]
        for (comfort, streak, outcome), expected in cases:
            self.assertEqual(bf.ladder_step(comfort, streak, outcome, LADDER), expected, (comfort, streak, outcome))


    def test_two_week_replay_with_all_green_sampler(self) -> None:
        start = dt.date(2026, 10, 6)
        first = start.toordinal()
        rows = [
            {"comfort": "🟢", "streak": 2, "diff": "Easy", "due": first - 1, "attempts": 3},
            {"comfort": "🔴", "streak": 0, "diff": "Medium", "due": first, "attempts": 1},
            {"comfort": "🟡", "streak": 0, "diff": "Medium", "due": first + 30, "attempts": 1},
        ]
        result = bf.simulate(rows, CFG, LADDER, start, 0, 2, lambda cls, rng: "🟢", random.Random(0))
        # Row 1 graduates day 1 (due again +180); row 2 goes 🟢 s0 (+10), then s1 on day 11 is
        # past the 2 weeks; row 3 stays 🟡 and is not yet due.
        self.assertEqual(result["backlog"], {1: 0, 2: 0})
        self.assertEqual(result["graduated"], 1)


    def test_simulate_row_cap_stops_seating_and_ceiling_skips_to_a_cheaper_row(self) -> None:
        start = dt.date(2026, 10, 6)   # a Tuesday: the week's seat days are 6 non-Sunday days
        capped = bf.simulate(_due_rows(8, "🟡", "Medium", start), {**CFG, "max_rows_per_day": 1},
                             LADDER, start, 0, 1, _stay_overdue_outcome, random.Random(0))
        self.assertEqual(capped["backlog"][1], 2)   # 8 due, one seat per non-Sunday day

        mixed = _due_rows(1, "🔴", "Hard", start) + _due_rows(1, "🟢", "Easy", start)
        skipped = bf.simulate(mixed, {**CFG, "ceiling": 2.0}, LADDER, start, 0, 1,
                              _stay_overdue_outcome, random.Random(0))
        self.assertEqual(skipped["backlog"][1], 1)   # the 🔴 Hard row never fits; the cheaper 🟢 later one seats


    def test_sunday_mock_is_priced_from_effort_budget(self) -> None:
        start = dt.date(2026, 10, 6)
        cheap = {**CFG, "comfort_units": {**CFG["comfort_units"], "🔴": 1.0}}
        units = [bf.simulate([], cfg, LADDER, start, 0, 1, _stay_overdue_outcome,
                             random.Random(0))["units_per_week"] for cfg in (CFG, cheap)]
        self.assertEqual(units[0], bf.eb.price("🔴", 0, bf.eb.DEFAULT_MOCK_DIFFICULTY, 0, CFG))
        self.assertEqual(units[1], bf.eb.price("🔴", 0, bf.eb.DEFAULT_MOCK_DIFFICULTY, 0, cheap))
        self.assertNotEqual(units[0], units[1])


    def test_verdict_at_each_threshold_edge(self) -> None:
        steady_max, piling_min = 0.5, 1.5
        cases = [(steady_max, "steady"), (piling_min, "piling"), ((steady_max + piling_min) / 2, "edge")]
        for slope, expected in cases:
            self.assertEqual(bf.verdict(slope, steady_max, piling_min), expected, slope)


if __name__ == "__main__":
    unittest.main()
