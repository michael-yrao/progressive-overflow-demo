"""Tests for fold_record.py (and the schedule writers in fold_schedule.py): pure text in, text out.

    python -m pytest scripts/test_fold_record.py -q
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

import fold_record
import update_review_dates as urd
from fold_schedule import RepFacts

ISO = "2026-10-19"
WEEK_START = dt.date(2026, 10, 19)
CONFIG = {"clean_provisional": 10, "clean_streak1": 30, "clean_streak2": 60, "graduated": 180,
          "shaky": 10, "blank": 2, "graduate_at_streak": 3}
TITLE_HEAVY = "332. Reconstruct Itinerary (min-heap ordering)"
TITLE_SORTED = "332. Reconstruct Itinerary (pre-sorted adjacency)"
TRACKER_HEAD = "| Difficulty | Problem | Comfort | Streak | Next Review Date | Latest Rep Date | Rep Dates |\n|---|---|---|---|---|---|---|"
LINK_79 = "[79 Word Search](../../../dsa/b/79_word_search.py) · [LC](https://lc/79)"
LINK_332 = "[332 Reconstruct Itinerary (min-heap ordering)](../../../dsa/g/332.py) · [LC](https://lc/332)"


def tracker_row(title: str, comfort: str, streak: int, next_iso: str, latest: str, reps: str) -> str:
    return urd.build_row({"difficulty": "Hard", "problem": title, "url": "https://lc/332",
                          "comfort": comfort, "streak": streak, "next_review": next_iso,
                          "latest_attempt_date": latest, "attempts": reps})


def schedule(mon: str = "", tue: str = "", tue_header: str = "~3.0 units",
             mon_header: str = "~2.0 units") -> str:
    """A week file: Mon Oct 19 and Tue Oct 20 hold the given rows; Wed Oct 21 is empty."""
    parts = ["| Problem | S | E | Next | Technique |", "|---|:-:|:-:|:-:|---|",
             f"| ▸ **Mon Oct 19** · {mon_header} — A |  |  |  |  |", *([mon] if mon else []),
             "|  |  |  |  |  |",
             f"| ▸ **Tue Oct 20** · {tue_header} — B |  |  |  |  |", *([tue] if tue else []),
             "|  |  |  |  |  |",
             "| ▸ **Wed Oct 21** · ~1.0 units — C |  |  |  |  |", "|  |  |  |  |  |"]
    return "\n".join(parts)


ROW_79 = f"| {LINK_79} | 🟡 |  |  | Backtracking |"
ROW_332 = f"| {LINK_332} | 🟡 |  |  | Hierholzer |"
FACTS = RepFacts("332", "🟡", "2026-10-29", "[332 Reconstruct Itinerary](../../../dsa/g/332.py)",
                 "🟡", "Hierholzer")


class FoldRecordTests(unittest.TestCase):
    def test_apply_tracker_row(self):
        reps = "2026-10-01"
        cases = [
            ("shaky", "🟢", 1, "shaky", ("🟡", 0, "2026-10-29")),
            ("blank", "🟡", 0, "blank", ("🔴", 0, "2026-10-21")),
            ("clean after blank", "🔴", 0, "clean", ("🟢", 0, "2026-10-29")),
            ("clean after shaky", "🟡", 0, "clean", ("🟢", 1, "2026-11-18")),
            ("clean after clean", "🟢", 1, "clean", ("🟢", 2, "2026-12-18")),
            ("promotion at graduate_at_streak", "🟢", 2, "clean", ("🎓", 3, "2027-04-17")),
        ]
        for label, comfort, streak, rating, (new_comfort, new_streak, due) in cases:
            with self.subTest(label), mock.patch.dict(urd.CONFIG, CONFIG):
                text = f"{TRACKER_HEAD}\n{tracker_row(TITLE_HEAVY, comfort, streak, '2026-10-19', '2026-10-01', reps)}"
                expected = tracker_row(TITLE_HEAVY, new_comfort, new_streak, due, ISO, f"{reps}, {ISO}")
                result = fold_record.apply_tracker_row(text, 2, rating, ISO, CONFIG)
                self.assertEqual(result.split("\n")[2], expected)
        with self.subTest("duplicate date"):
            text = f"{TRACKER_HEAD}\n{tracker_row(TITLE_HEAVY, '🟡', 0, '2026-10-29', ISO, f'{reps}, {ISO}')}"
            self.assertEqual(fold_record.apply_tracker_row(text, 2, "clean", ISO, CONFIG), text)

    def test_first_rep_inserts_row(self):
        url = "https://lc/79"
        placeholder = f"| Medium | [79. Word Search]({url}) | 🔴 | 0 |  |  |  |"
        cases = [
            ("clean", "clean", TRACKER_HEAD, "🟢", "2026-10-29"),
            ("shaky", "shaky", TRACKER_HEAD, "🟡", "2026-10-29"),
            ("blank", "blank", TRACKER_HEAD, "🔴", "2026-10-21"),
            ("placeholder is updated in place", "clean", f"{TRACKER_HEAD}\n{placeholder}", "🟢", "2026-10-29"),
        ]
        for label, rating, tracker, comfort, due in cases:
            with self.subTest(label), mock.patch.dict(urd.CONFIG, CONFIG), \
                    mock.patch.object(fold_record, "reprice_days", side_effect=lambda text, *_: text):
                inputs = fold_record.RecordInputs(tracker, schedule(mon=ROW_79), WEEK_START, "",
                                                  f"{LINK_79}", {}, CONFIG, {})
                rep = fold_record.RepInput("79", "Word Search", ISO, rating, (),
                                           "Medium", url)
                out = fold_record.record_rep(inputs, rep)
                rows = [ln for ln in out.tracker.split("\n") if "79. Word Search" in ln]
                self.assertEqual(rows, [urd.build_row({
                    "difficulty": "Medium", "problem": "79. Word Search", "url": url, "comfort": comfort,
                    "streak": 0, "next_review": due, "latest_attempt_date": ISO, "attempts": ISO})])
                self.assertEqual(out.next_iso, due)
                self.assertIn(f"| ~~{LINK_79}~~ | 🟡 | {comfort} | {due} | Backtracking |", out.schedule)

    def test_choose_tracker_row(self):
        heavy = lambda latest, due: tracker_row(TITLE_HEAVY, "🟡", 0, due, latest, latest)  # noqa: E731
        sorted_ = lambda latest, due: tracker_row(TITLE_SORTED, "🟢", 1, due, latest, latest)  # noqa: E731
        both = f"{TRACKER_HEAD}\n{heavy('2026-10-09', '2026-10-29')}\n{sorted_('2026-09-15', '2026-10-15')}"
        done_today = f"{TRACKER_HEAD}\n{heavy(ISO, '2026-10-05')}\n{sorted_('2026-09-15', '2026-10-15')}"
        cases = [
            ("single row", f"{TRACKER_HEAD}\n{heavy('2026-10-09', '2026-10-29')}", None, 2),
            ("variant match", both, "[332 Reconstruct Itinerary (pre-sorted adjacency)](x)", 3),
            ("no match: soonest due", both, None, 3),
            ("no match: a row already done today is skipped", done_today, None, 3),
        ]
        for label, text, schedule_title, expected in cases:
            with self.subTest(label):
                self.assertEqual(fold_record.choose_tracker_row(text, "332", schedule_title, ISO), expected)

    def test_strike_schedule_row(self):
        struck = f"| ~~{LINK_79}~~ | 🟡 | 🟡 | 2026-10-29 | Backtracking |"
        cases = [
            ("found", schedule(mon=ROW_79), "79", ISO, schedule(mon=struck), True),
            ("already struck", schedule(mon=struck), "79", ISO, schedule(mon=struck), False),
            ("absent day", schedule(tue=ROW_79), "79", ISO, schedule(tue=ROW_79), False),
        ]
        for label, text, number, day, expected, found in cases:
            with self.subTest(label):
                result, was_found = fold_record.strike_schedule_row(
                    text, WEEK_START, dt.date.fromisoformat(day), number, "🟡", "2026-10-29")
                self.assertEqual((result, was_found), (expected, found))

    def test_apply_schedule(self):
        struck_79 = f"| ~~{LINK_79}~~ | 🟡 | 🟡 | 2026-10-29 | Backtracking |"
        copy_332 = f"| ← ~~{LINK_332}~~ | 🟡 | 🟡 | 2026-10-29 | Hierholzer |"
        copy_79 = f"| → ~~{LINK_79}~~ | 🟡 | 🟡 | 2026-10-29 | Backtracking |"
        new_cell = "[5 Demo](../../../dsa/x/5_demo.py)"
        cases = [
            ("on today, unstruck", schedule(mon=ROW_79), ISO, "79", schedule(mon=struck_79)),
            ("on a later day",
             schedule(tue=ROW_332), ISO, "332",
             schedule(mon=copy_332, tue=f"| ← {LINK_332} | 🟡 |  | 2026-10-19 | Hierholzer |",
                      tue_header="~3.0 units · planned 3.0 units")),
            ("on an earlier day",
             schedule(mon=ROW_79), "2026-10-20", "79",
             schedule(mon=f"| → {LINK_79} | 🟡 |  | 2026-10-20 | Backtracking |", tue=copy_79,
                      mon_header="~2.0 units · planned 2.0 units")),
            ("not in the week",
             schedule(mon=ROW_79), ISO, "5",
             schedule(mon=f"{ROW_79}\n| ~~{new_cell}~~ | 🟡 | 🟡 | 2026-10-29 | Demo |")),
            ("already struck today", schedule(mon=struck_79), ISO, "79", schedule(mon=struck_79)),
        ]
        for label, text, today, number, expected in cases:
            with self.subTest(label):
                facts = RepFacts(number, "🟡", "2026-10-29", new_cell, "🟡",
                                 "Demo" if number == "5" else FACTS.technique)
                placed = fold_record.apply_schedule(text, WEEK_START, dt.date.fromisoformat(today), facts)
                self.assertEqual(placed.text, expected)

    def test_seat_next_review(self):
        seated = f"| {LINK_332} | 🟢 s1 |  |  | Hierholzer |"
        cases = [
            ("in the week", "2026-10-21",
             schedule().replace("| ▸ **Wed Oct 21** · ~1.0 units — C |  |  |  |  |\n|  |  |  |  |  |",
                                f"| ▸ **Wed Oct 21** · ~1.0 units — C |  |  |  |  |\n{seated}\n|  |  |  |  |  |")),
            ("outside the week", "2026-11-18", schedule()),
        ]
        for label, next_iso, expected in cases:
            with self.subTest(label):
                result = fold_record.seat_next_review(schedule(), WEEK_START, next_iso, "332", LINK_332,
                                                      "🟢 s1", "Hierholzer")
                self.assertEqual(result, expected)

    def test_queue_complexity(self):
        text = ("intro\n## ⏳ End-of-week complexity cleanup queue (added)\nprose\n"
                "| Problem | Missed bound | Queued | Cleared |\n|---|---|---|---|\n| a | b | c | d |\n- bullet\n")
        row = "| 332 Reconstruct Itinerary | **time** | 2026-10-19 | |"
        result = fold_record.queue_complexity(text, row)
        self.assertEqual(result, text.replace("| a | b | c | d |\n", f"| a | b | c | d |\n{row}\n"))


if __name__ == "__main__":
    unittest.main()
