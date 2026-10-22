"""Tests for check_schedule_integrity.py's check 4 — header_vs_rows (the header/Goal-vs-rows
build-drift check).

Stdlib unittest, mirrors test_check_timeline_gaps.py's runner style. header_vs_rows() is pure
(Path in, findings out) but DOES read the filesystem — unlike gamify's pure functions, a
schedule week is a whole markdown file, not a plain dict, so each fixture is written to the
test's own temp dir rather than depending on a real (and mutable) schedule file.

False positives are the whole difficulty this check exists to survive (see the module
docstring), so the fixtures below are built directly from the traps a real week's prose
contains: a date, a decimal unit count, an approximate rep count, a plain intake count, a
"+N" interval suffix, and a bare-numbered 🆕 intake row with no link/bold before its number.
Numbers, dates and titles below are invented — chosen only to exercise the traps, not to
reflect any real schedule.

    python scripts/test_check_schedule_integrity.py
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import check_schedule_integrity as csi
import effort_budget as eb

# A minimal, valid Daily Schedule table header + separator — every fixture's rows sit below it.
_TABLE_HEAD = "| Problem | S | E | Next | Technique |\n|---|:-:|:-:|:-:|---|\n"

# A build-drift shape: the Goal paragraph promises TWO recursion intakes (301, then 777) but
# the Daily Schedule only ever seats a row for 301.
FIXTURE_POSITIVE_DRIFT = f"""# Week of March 14 - 20, 2027

**Goal:** clear the 🔴 re-rep and open Recursion with exactly **2 intakes** (301 Foo Problem,
then 777 Bar Problem — no primer, learner's call).

---

## Daily Schedule

{_TABLE_HEAD}| ▸ **Mon Mar 14** · 5.0 units — 301 🔴 re-rep |  |  |  |  |
| [301 Foo Problem](../../../dsa/leetcode/recursion/301_foo_problem.py) · [LC](https://leetcode.com/problems/foo-problem/) | 🔴 | | | Recursion |
"""

# A clean week packing every trap from the module docstring right next to genuine mentions
# that DO all have rows: a date ("Mar 21"), a decimal unit count ("6.8 units"), an approximate
# rep count ("~26 reps"), a bare intake count ("2 recursion intakes"), "+2" interval
# suffixes, and a "·"-separated number list (12 · 88 · 640).
FIXTURE_NEGATIVE_CLEAN = f"""# Week of March 21 - 27, 2027

**Goal:** a review-heavy week by demand (not light by choice — ~26 reps come due). NEW intake
is held to the learner's floor of **2 recursion intakes**. Primary: clear the two 🔴
re-reps (301 Foo Problem +2, 850 Baz Problem +2) and drain the conversion backlog
(12 · 88 · 640).

---

## Daily Schedule

{_TABLE_HEAD}| ▸ **Mon Mar 21** · 6.8 units — 301 🔴 re-rep + 850 🔴 re-rep |  |  |  |  |
| [301 Foo Problem](../../../dsa/leetcode/recursion/301_foo_problem.py) · [LC](https://leetcode.com/problems/foo-problem/) | 🔴 | | | Recursion |
| [850 Baz Problem](../../../dsa/leetcode/binary_search/850_baz_problem.py) · [LC](https://leetcode.com/problems/baz-problem/) | 🔴 | | | Binary-search |
| [12 Qux Problem](../../../dsa/leetcode/greedy/12_qux_problem.py) · [LC](https://leetcode.com/problems/qux-problem/) | 🟡 | | | Greedy |
| [88 Quux Problem](../../../dsa/leetcode/graphs/88_quux_problem.py) · [LC](https://leetcode.com/problems/quux-problem/) | 🟡 | | | Graph |
| [640 Corge Problem](../../../dsa/leetcode/binary_search/640_corge_problem.py) · [LC](https://leetcode.com/problems/corge-problem/) | 🟢 | | | Binary-search |
"""

# The 🆕-row trap: a NEW intake's Problem cell carries no `[`/`**` before its number (no local
# solution file exists yet to link), so MENTION alone would both under-extract the row AND
# (via schedule_rows()'s own filter) drop it from the board entirely. A clean week naming 501
# and 502 in the Goal paragraph, each seated as a bare 🆕 row, must report nothing.
FIXTURE_BARE_NEW_ROW = f"""# Week of March 21 - 27, 2027

**Goal:** NEW intake is held to the learner's floor of **2 recursion intakes** (501
Alpha Problem, 502 Beta Problem).

---

## Daily Schedule

{_TABLE_HEAD}| ▸ **Wed Mar 23** · 7.6 units — Recursion intake 1 |  |  |  |  |
| 🆕 501 Alpha Problem · [LC](https://leetcode.com/problems/alpha-problem/) | 🆕 | | | Recursion |
| |  |  |  |  |
| ▸ **Fri Mar 25** · 6.9 units — Recursion intake 2 |  |  |  |  |
| 🆕 502 Beta Problem · [LC](https://leetcode.com/problems/beta-problem/) | 🆕 | | | Recursion |
"""

# The pre-Daily-Schedule masking trap: a Capacity table BEFORE "## Daily Schedule" that
# happens to share the Daily table's 5-column shape, with the number sitting in ITS first
# cell too — the exact position week_row_numbers() reads. Unscoped, this reads as a seated
# row and silences the real drift the check exists to catch; scoped to "## Daily Schedule"
# onward, it must still report both numbers as missing.
FIXTURE_PRE_DAILY_SCHEDULE_TABLE = f"""# Week of March 21 - 27, 2027

**Goal:** NEW intake is held to the learner's floor of **2 recursion intakes** (501
Alpha Problem, 502 Beta Problem).

---

## Capacity

| **501** Alpha Problem | x | y | z | w |
| **502** Beta Problem | x | y | z | w |

---

## Daily Schedule

{_TABLE_HEAD}| ▸ **Wed Mar 23** · 7.6 units — Recursion intake |  |  |  |  |
"""

# The emphasised-tag-row trap: a DONE (struck) or bolded 🆕/🎯 row, where `~~`/`**` wraps the
# tag glyph too. Unstripped, `_row_number` returns None for a row that IS seated, which in
# check 4 reads as a genuine problem going FALSE POSITIVE (a seated row reported missing) —
# the failure the module docstring says is unacceptable, worse than under-extraction.
FIXTURE_EMPHASISED_TAG_ROW = f"""# Week of March 21 - 27, 2027

**Goal:** NEW intake is held to the learner's floor of **2 recursion intakes** (501
Alpha Problem, 502 Beta Problem).

---

## Daily Schedule

{_TABLE_HEAD}| ▸ **Wed Mar 23** · 7.6 units — Recursion intake 1 |  |  |  |  |
| ~~🆕 501 Alpha Problem · [LC](https://leetcode.com/problems/alpha-problem/)~~ | 🆕 | 🟢 | 2027-04-01 | Recursion |
| |  |  |  |  |
| ▸ **Fri Mar 25** · 6.9 units — Recursion intake 2 |  |  |  |  |
| **🆕 502 Beta Problem** | 🆕 | | | Recursion |
"""

# The post-Daily-Schedule masking trap: mirrors FIXTURE_PRE_DAILY_SCHEDULE_TABLE, but the
# 5-column lookalike table sits AFTER "## Daily Schedule" (a Waiting Room / next-week
# preview shape) instead of before it. Unscoped past the section's own end, this reads as
# seated rows and silences the drift; bounded to the section, it must still report both.
FIXTURE_POST_DAILY_SCHEDULE_TABLE = f"""# Week of March 21 - 27, 2027

**Goal:** NEW intake is held to the learner's floor of **2 recursion intakes** (501
Alpha Problem, 502 Beta Problem).

---

## Daily Schedule

{_TABLE_HEAD}| ▸ **Wed Mar 23** · 7.6 units — Recursion intake |  |  |  |  |

---

## Waiting Room

| **501** Alpha Problem | x | y | z | w |
| **502** Beta Problem | x | y | z | w |
"""

# The non-header "units —" trap: a capacity/build-note line that happens to contain the
# literal text "units —" (DAY_LABEL's only trigger) without being an actual "▸" day header.
# Its numbers must NOT be read as a build promise.
FIXTURE_NON_HEADER_UNITS_LINE = f"""# Week of March 21 - 27, 2027

**Goal:** a light week, nothing special.

```
9.0 units — ALL placed (730 · 40)
```

---

## Daily Schedule

{_TABLE_HEAD}| ▸ **Mon Mar 21** · 6.8 units — green batch |  |  |  |  |
"""


class HeaderVsRowsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = Path(self._tmpdir.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_goal_names_a_problem_with_no_row_is_flagged(self):
        path = self._write("20270314_schedule.md", FIXTURE_POSITIVE_DRIFT)
        findings = csi.header_vs_rows(path)
        self.assertEqual(len(findings), 1)
        self.assertIn("777", findings[0])

    def test_clean_week_full_of_trap_text_reports_nothing(self):
        path = self._write("20270321_schedule.md", FIXTURE_NEGATIVE_CLEAN)
        self.assertEqual(csi.header_vs_rows(path), [])

    def test_bare_numbered_new_intake_row_satisfies_its_own_goal_mention(self):
        path = self._write("20270321_schedule.md", FIXTURE_BARE_NEW_ROW)
        self.assertEqual(csi.header_vs_rows(path), [])

    def test_a_5_column_table_before_daily_schedule_does_not_mask_a_real_drift(self):
        path = self._write("20270321_schedule.md", FIXTURE_PRE_DAILY_SCHEDULE_TABLE)
        findings = csi.header_vs_rows(path)
        self.assertEqual(len(findings), 2)
        joined = " ".join(findings)
        self.assertIn("501", joined)
        self.assertIn("502", joined)

    def test_a_5_column_table_after_daily_schedule_does_not_mask_a_real_drift(self):
        path = self._write("20270321_schedule.md", FIXTURE_POST_DAILY_SCHEDULE_TABLE)
        findings = csi.header_vs_rows(path)
        self.assertEqual(len(findings), 2)
        joined = " ".join(findings)
        self.assertIn("501", joined)
        self.assertIn("502", joined)

    def test_struck_or_bolded_tag_row_is_still_recognised_as_seated(self):
        path = self._write("20270321_schedule.md", FIXTURE_EMPHASISED_TAG_ROW)
        self.assertEqual(csi.header_vs_rows(path), [])


class TrapExtractionTests(unittest.TestCase):
    """Direct pins on week_named_numbers()/week_row_numbers(), the two extraction halves
    header_vs_rows() diffs — narrower than the end-to-end fixtures above, so a future
    regression in just one half points straight at the broken side.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, text: str) -> Path:
        path = Path(self._tmpdir.name) / "20270321_schedule.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_date_decimal_count_and_interval_suffix_are_not_named(self):
        path = self._write(FIXTURE_NEGATIVE_CLEAN)
        named = csi.week_named_numbers(path, eb.DAY_HEADER)
        # Traps that must NOT surface as a required mention.
        for trap in (21, 26, 2, 8):
            self.assertNotIn(trap, named)
        # Genuine mentions that must.
        for real in (301, 850, 12, 88, 640):
            self.assertIn(real, named)

    def test_bare_new_row_still_yields_its_number(self):
        path = self._write(FIXTURE_BARE_NEW_ROW)
        self.assertEqual(csi.week_row_numbers(path, eb.SCHED_ROW), {501, 502})

    def test_row_scan_ignores_a_5_column_table_before_daily_schedule(self):
        path = self._write(FIXTURE_PRE_DAILY_SCHEDULE_TABLE)
        self.assertEqual(csi.week_row_numbers(path, eb.SCHED_ROW), set())

    def test_row_scan_ignores_a_5_column_table_after_daily_schedule(self):
        path = self._write(FIXTURE_POST_DAILY_SCHEDULE_TABLE)
        self.assertEqual(csi.week_row_numbers(path, eb.SCHED_ROW), set())

    def test_struck_and_bolded_tag_rows_still_yield_their_number(self):
        self.assertEqual(csi._row_number("~~🆕 501 Alpha Problem · [LC](https://x)~~"), 501)
        self.assertEqual(csi._row_number("**🆕 502 Beta Problem**"), 502)
        # The stacked form that really occurs in this repo's archive.
        self.assertEqual(csi._row_number("~~**🎯 650 Grault Problem**~~"), 650)

    def test_non_header_units_line_is_not_read_as_a_day_header_promise(self):
        path = self._write(FIXTURE_NON_HEADER_UNITS_LINE)
        named = csi.week_named_numbers(path, eb.DAY_HEADER)
        self.assertNotIn(730, named)
        self.assertNotIn(40, named)


class IsSeatedTests(unittest.TestCase):
    """Direct pins on is_seated(), check 3's seating decision — pure, so no fixture files
    are needed. The two masking shapes it exists to fix (see check_schedule_integrity's
    module docstring, check 3): a second tracker row for the same LC number whose only
    board mention is a struck rep for the OTHER method, and a single row's own struck rep
    keeping its number "listed" while its next (already-due) rep seats nowhere.
    """

    SUNDAY = dt.date(2027, 3, 21)

    KRUSKAL_ROW = {"num": "9101", "title": "Connect All Points (Kruskal)",
                   "due": "2027-02-20"}  # overdue
    PRIMS_ROW = {"num": "9101", "title": "Connect All Points (Prim's MST)",
                 "due": "2027-05-20"}  # not due this week

    def test_pending_board_mentions_excludes_struck_rows(self):
        struck = "~~[9101 Connect All Points](x)~~ · [LC](y)"
        unstruck = "**9101** Connect All Points (Kruskal) re-rep"
        board_rows = [
            (struck, True, ["🟢", "🟢", "2027-05-20"]),
            (unstruck, False, ["", "", ""]),
        ]
        pending = csi.pending_board_mentions(board_rows)
        self.assertEqual(pending.get(9101), [unstruck])

    def test_two_rows_one_number_only_struck_board_row_is_flagged(self):
        # board has only a STRUCK row for 9101 -> pending_board_mentions drops it, so no
        # unstruck mention ever reaches is_seated.
        board_rows = [
            ("~~[9101 Connect All Points](x)~~ · [LC](y)", True,
             ["🟢", "🟢", "2027-05-20"]),
        ]
        pending = csi.pending_board_mentions(board_rows)
        seated = csi.is_seated(self.KRUSKAL_ROW, [self.KRUSKAL_ROW, self.PRIMS_ROW],
                                pending.get(9101, []), self.SUNDAY)
        self.assertFalse(seated)

    def test_two_rows_one_number_unstruck_row_naming_its_own_method_is_not_flagged(self):
        pending = ["**9101** Connect All Points (Kruskal) re-rep"]
        seated = csi.is_seated(self.KRUSKAL_ROW, [self.KRUSKAL_ROW, self.PRIMS_ROW],
                                pending, self.SUNDAY)
        self.assertTrue(seated)

    def test_two_rows_one_number_unstruck_row_naming_the_other_method_is_flagged(self):
        pending = ["**9101** Connect All Points (Prim's MST) re-rep"]
        seated = csi.is_seated(self.KRUSKAL_ROW, [self.KRUSKAL_ROW, self.PRIMS_ROW],
                                pending, self.SUNDAY)
        self.assertFalse(seated)

    def test_single_row_due_this_week_only_struck_board_row_is_flagged(self):
        row = {"num": "9102", "title": "Nested Brackets", "due": "2027-03-18"}
        board_rows = [
            ("~~[9102 Nested Brackets](x)~~ · [LC](y)", True, ["🔴", "🟢", "2027-04-18"]),
        ]
        pending = csi.pending_board_mentions(board_rows)
        seated = csi.is_seated(row, [row], pending.get(9102, []), self.SUNDAY)
        self.assertFalse(seated)

    def test_single_row_due_this_week_unstruck_board_row_is_not_flagged(self):
        row = {"num": "9102", "title": "Nested Brackets", "due": "2027-03-18"}
        pending = ["**9102** Nested Brackets re-rep"]
        seated = csi.is_seated(row, [row], pending, self.SUNDAY)
        self.assertTrue(seated)

    def test_unstruck_row_with_no_method_text_seats_the_sole_due_variant(self):
        due_row = {"num": "9103", "title": "Subset Sums (BFS)", "due": "2027-03-18"}
        other_row = {"num": "9103", "title": "Subset Sums (Union-Find)",
                     "due": "2027-05-01"}  # not due this week -> due_count is 1, unambiguous
        pending = ["**9103** Subset Sums"]  # no method text at all
        seated = csi.is_seated(due_row, [due_row, other_row], pending, self.SUNDAY)
        self.assertTrue(seated)


class DoneRowFindingsTests(unittest.TestCase):
    """Check 1 on the UNNUMBERED mock row shape (`🎤 Mock interview (Medium)`: no `[N`/`**N`
    for MENTION to match), read through schedule_rows() so the test also proves its
    "Mock" whitelist -- without it the row is dropped before check 1 ever sees it."""

    def test_struck_mock_row_with_blank_end_is_flagged_and_unstruck_is_not(self):
        cases = [
            ("| ~~🎤 Mock interview (Medium)~~ | 🎤 |  | 2027-03-21 | Mock |", 1),
            ("| 🎤 Mock interview (Medium) | 🎤 |  |  | Mock |", 0),
        ]
        for row, expected_findings in cases:
            with self.subTest(row=row):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "20270314_schedule.md"
                    path.write_text(_TABLE_HEAD + row + "\n", encoding="utf-8")
                    findings = csi.done_row_findings(csi.schedule_rows(path))
                self.assertEqual(len(findings), expected_findings)


class SiteLinkFindingsTests(unittest.TestCase):
    """Check 9: a row with a practice spec needs its `[PO]` link, unless its judge is the site."""

    def test_site_link_findings_table(self):
        site = "https://progressiveoverflow.com/practice"
        cases = [
            ("spec, no [PO]", f"[743 X](f.py) · [LC](https://leetcode.com/p/x/)", {743}, 1),
            ("spec, [PO] present", f"[743 X](f.py) · [LC](https://leetcode.com/p/x/) · [PO]({site}/743)",
             {743}, 0),
            ("spec, [PO] names another number",
             f"[743 X](f.py) · [LC](https://leetcode.com/p/x/) · [PO]({site}/744)", {743}, 1),
            ("site is the judge", f"[9003 X](f.py) · [PO]({site}/9003)", {9003}, 0),
            ("no spec", f"[743 X](f.py) · [LC](https://leetcode.com/p/x/)", set(), 0),
        ]
        for name, cell, specs, expected in cases:
            with self.subTest(name):
                findings = csi.site_link_findings([(cell, False, ["", "", ""])], lambda n: n in specs)
                self.assertEqual(len(findings), expected, findings)


_CFG = {"carry_forward_min_streak": 2, "intake_per_week": 2,
        "intake_pause_overdue_unproven": 2}
_MONDAY = dt.date(2027, 3, 15)
_TODAY = dt.date(2027, 3, 16)


def _day(*items: dict) -> dict[dt.date, list[dict]]:
    return {_MONDAY: list(items)}


class RowCapFindingsTests(unittest.TestCase):
    """Check 5: a day block over the cap, Complexity rows excluded."""

    def test_over_cap_only_when_more_than_cap_non_complexity_rows(self):
        plain = {"is_complexity": False}
        complexity = {"is_complexity": True}
        cap = 3
        cases = [
            ("at cap", [plain] * cap, 0),
            ("one over", [plain] * (cap + 1), 1),
            ("complexity excluded", [plain] * cap + [complexity], 0),
        ]
        for name, items, expected in cases:
            with self.subTest(name):
                self.assertEqual(len(csi.row_cap_findings(_day(*items), cap)), expected)


class DueRowCarriedSectionTests(unittest.TestCase):
    """Check 3 with the carried section: only a proven row may be carried."""

    SUNDAY = dt.date(2027, 3, 21)
    CARRIED_SECTION = ("## ⏭️ Carried to next week (row cap)\n\n"
                       "- [5 Title](x.py) · 🟢 s2 · due 2027-03-15 · carried from Sat\n")

    def _findings(self, streak: int, section: str) -> list[str]:
        row = {"num": "5", "title": "Title", "due": "2027-03-15",
               "comfort": "🟢", "streak": streak}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20270315_schedule.md"
            path.write_text("## Daily Schedule\n\n" + section, encoding="utf-8")
            carried = csi.carried_numbers(path)
        return csi.due_row_findings([row], {}, carried, self.SUNDAY, "20270315_schedule.md", _CFG)

    def test_carried_row_accepted_only_when_proven(self):
        cases = [
            ("s2 carried accepted", 2, self.CARRIED_SECTION, None),
            ("s1 carried flagged", 1, self.CARRIED_SECTION, "cannot be carried (unproven)"),
            ("absent flagged", 2, "", "seated on no day"),
        ]
        for name, streak, section, expected in cases:
            with self.subTest(name):
                findings = self._findings(streak, section)
                if expected is None:
                    self.assertEqual(findings, [])
                else:
                    self.assertEqual(len(findings), 1)
                    self.assertIn(expected, findings[0])


class IntakeFindingsTests(unittest.TestCase):
    """Check 6: the week's 🆕 count vs intake_per_week, or 0 when the backstop triggers."""

    def test_new_row_count_against_expected(self):
        new = {"is_new": True, "deferred_to": None}
        overdue = {"comfort": "🔴", "streak": 0, "due": "2027-03-11"}
        triggering = [overdue] * _CFG["intake_pause_overdue_unproven"]
        per_week = _CFG["intake_per_week"]
        cases = [
            ("at the rate", [new] * per_week, [], 0),
            ("one over", [new] * (per_week + 1), [], 1),
            ("zero when triggered", [], triggering, 0),
        ]
        for name, items, tracker_rows, expected in cases:
            with self.subTest(name):
                findings = csi.intake_findings(_day(*items), tracker_rows, _CFG, _TODAY)
                self.assertEqual(len(findings), expected)


def _week_lines(mon_rows: list[str], wed_header: str = "7.8 units", mon_header: str = "5.0 units",
                wed_rows: list[str] | None = None) -> list[str]:
    """A two-day week (Mon Mar 15 started, Wed Mar 17 future) as schedule lines."""
    return ([f"| ▸ **Mon Mar 15** · {mon_header} — label |  |  |  |  |"] + mon_rows
            + ["|  |  |  |  |  |", f"| ▸ **Wed Mar 17** · {wed_header} — label |  |  |  |  |"]
            + (wed_rows or []))


def _row(num: int, method: str | None = None, struck: bool = False, moved: bool = False) -> str:
    title = f"{num} Title" + (f" ({method})" if method else "")
    cell = f"~~[{title}](x.py)~~ · [LC](y)" if struck else f"[{title}](x.py) · [LC](y)"
    return f"| {'→ ' if moved else ''}{cell} | 🟢 s2 | | {'2027-03-19' if moved else ''} | Graphs |"


class DroppedRowFindingsTests(unittest.TestCase):
    """Check 7: a numbered row on a started day at HEAD must survive in the working file."""

    def test_started_day_rows_must_survive(self):
        mock = "| 🎤 Mock interview | 🎤 | | | Mock |"
        cases = [
            ("kept and struck", [_row(9104)], [_row(9104, struck=True)], 0, None),
            ("kept as moved", [_row(9104)], [_row(9104, moved=True)], 0, None),
            ("deleted on started day", [_row(9104)], [], 1, "9104"),
            ("two variants, one deleted", [_row(9105, "Dijkstra"), _row(9105, "Prim")],
             [_row(9105, "Prim")], 1, "(Dijkstra)"),
            ("numberless mock becomes numbered", [mock], [_row(7, struck=True)], 0, None),
        ]
        for name, head_rows, work_rows, expected, naming in cases:
            with self.subTest(name):
                findings = csi.dropped_row_findings(
                    _week_lines(head_rows), _week_lines(work_rows), _MONDAY, _TODAY)
                self.assertEqual(len(findings), expected)
                if naming:
                    self.assertIn(naming, findings[0])
        with self.subTest("deleted on future day"):
            head = _week_lines([], wed_rows=[_row(9104)])
            self.assertEqual(csi.dropped_row_findings(head, _week_lines([]), _MONDAY, _TODAY), [])


class PlannedFigureFindingsTests(unittest.TestCase):
    """Check 8: a planned figure is never lowered or removed, and is pinned when built drops."""

    def test_planned_never_lowered_and_pinned_when_built_drops(self):
        def mon(units: str) -> list[str]:
            return _week_lines([], mon_header=units)

        def wed(units: str) -> list[str]:
            return _week_lines([], wed_header=units)

        cases = [
            ("drop with pin", mon("6.6 units"), mon("3.8 units · planned 6.6 units"), 0, None),
            ("drop, no pin, started", mon("6.6 units"), mon("3.8 units"), 1,
             "add '· planned 6.6 units'"),
            ("drop on a future day", wed("6.6 units"), wed("3.8 units"), 0, None),
            ("lowered", mon("3.8 units · planned 6.6 units"),
             mon("3.8 units · planned 5.0 units"), 1, "lowered 6.6 → 5.0"),
            ("removed", mon("3.8 units · planned 6.6 units"), mon("3.8 units"), 1,
             "removed (was 6.6)"),
            ("even swap", mon("7.8 units"), mon("7.8 units"), 0, None),
        ]
        for name, head, work, expected, naming in cases:
            with self.subTest(name):
                findings = csi.planned_figure_findings(head, work, _MONDAY, _TODAY)
                self.assertEqual(len(findings), expected)
                if naming:
                    self.assertIn(naming, findings[0])


class CurrentScheduleTests(unittest.TestCase):
    """eb.current_schedule() picks the week that SPANS `today`, not just the newest file —
    the Sunday-close-out case: next week's Monday file already exists (built ahead of
    time), but a `today` still inside THIS week must keep resolving to THIS week's file.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmpdir.name)
        self._orig_eb_schedules = eb.SCHEDULES
        eb.SCHEDULES = tmp_dir

    def tearDown(self):
        eb.SCHEDULES = self._orig_eb_schedules
        self._tmpdir.cleanup()

    def _write_week(self, monday: str) -> Path:
        path = eb.SCHEDULES / f"{monday}_schedule.md"
        path.write_text(
            f"# Week of {monday}\n\n## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n|---|:-:|:-:|:-:|---|\n",
            encoding="utf-8")
        return path

    def test_picks_this_week_when_next_weeks_monday_already_exists(self):
        this_week = self._write_week("20270314")  # Mon Mar 14, 2027
        self._write_week("20270321")  # Mon Mar 21, built ahead by the Sunday close-out
        today = dt.date(2027, 3, 17)  # Wed Mar 17 — inside this week, not next week
        self.assertEqual(eb.current_schedule(today), this_week)

    def test_falls_back_to_newest_when_no_file_spans_today(self):
        self._write_week("20270228")
        newest = self._write_week("20270307")
        today = dt.date(2027, 4, 1)  # past both weeks' spans
        self.assertEqual(eb.current_schedule(today), newest)


if __name__ == "__main__":
    unittest.main()
