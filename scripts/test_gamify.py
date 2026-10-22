"""Tests for gamify.py — the honest-progress contract generator.

Stdlib unittest on purpose: a test that needs an uninstalled framework is a test that
never runs. Run it with:

    python scripts/test_gamify.py

The functions under test are pure (they take plain dicts) or are pointed at a temp tree
(`_fixture_repo` below), so nothing here reads the repo's own tracker, schedules or
progress.json — the point is to pin the streak math, the timeline reconstruction, and the
badge triggers, which are the parts most likely to drift silently, on any checkout
including a fresh one.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import contract_schema
import effort_budget as eb
import gamify
import links

MASTERY_DIR = "docs/foundations/dsa/mastery"
PROBES_FILE = "dsa/probes/README.md"

# A small but populated repo: one graduated problem, two techniques where the second
# `builds_on` the first. Used wherever a test needs build_payload() to see real inputs.
POPULATED_REPO = {
    f"{MASTERY_DIR}/dsa_progress.md": (
        "| Easy | [1. Alpha](https://leetcode.com/problems/alpha/) "
        "| 🎓 | 3 | 2026-12-01 | 2026-09-19 | 2026-09-19 |\n"),
    f"{MASTERY_DIR}/technique_coverage.md": (
        "## Coverage\n\n"
        "| Technique | Family | Tier | Min | Problems | Best | 🟢 | Variants | Gaps |\n"
        "|---|---|---|---:|---:|:---:|:---:|---|---|\n"
        "| Base | f | core | 1 (1+0) | 1 (1) | 🎓 | ✅ | — | — |\n"
        "| Derived | f | core | 1 (1+0) | 0 (—) | — | ❌ | — | *not started* |\n"),
    f"{MASTERY_DIR}/techniques.yml": (
        "techniques:\n"
        "  - name: Base\n"
        "  - name: Derived\n"
        "    builds_on: [Base]\n"),
}


@contextlib.contextmanager
def _fixture_repo(files: dict[str, str] | None = None):
    """Point gamify, effort_budget and links at a temp tree holding only `files` (repo-
    relative path -> text). No `files` is a fresh adopter's checkout: no tracker, no
    roadmap, no schedules, no solutions."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in (files or {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        mastery = root / MASTERY_DIR
        patches = [
            mock.patch.object(gamify, "REPO", root),
            mock.patch.object(gamify, "TRACKER", mastery / "dsa_progress.md"),
            mock.patch.object(gamify, "COVERAGE", mastery / "technique_coverage.md"),
            mock.patch.object(gamify, "TECHNIQUES_YML", mastery / "techniques.yml"),
            mock.patch.object(gamify, "ROADMAP_YML", mastery / "roadmap.yml"),
            mock.patch.object(gamify, "PROBES_README", root / PROBES_FILE),
            mock.patch.object(gamify, "LEETCODE", root / "dsa/leetcode"),
            mock.patch.object(gamify, "CONFIG", root / "cse.config.yml"),
            mock.patch.object(eb, "TRACKER", mastery / "dsa_progress.md"),
            mock.patch.object(eb, "CONFIG", root / "cse.config.yml"),
            mock.patch.object(eb, "SCHEDULES", root / "docs/foundations/schedules"),
            mock.patch.object(eb, "ROADMAP_YML", mastery / "roadmap.yml"),
            mock.patch.object(eb, "PROBE_POOL", root / PROBES_FILE),
            mock.patch.object(links, "source_roots", return_value=[root / "dsa/leetcode"]),
        ]
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            yield root


def _row(num, comfort, streak, diff="Medium", due="2026-12-01", reps=""):
    return {"num": str(num), "title": f"P{num}", "diff": diff, "comfort": comfort,
            "streak": streak, "due": due, "reps": reps}


class StreakTests(unittest.TestCase):
    TODAY = dt.date(2026, 9, 20)

    def _days(self, *iso):
        return [dt.date.fromisoformat(d) for d in iso]

    def test_freeze_bank_replay(self):
        cases = [
            # (name, days, today, earn_every, expected fields)
            ("empty", [], "2026-09-20", 7,
             {"current": 0, "longest": 0, "freezes": 2, "freezesLeft": 2, "frozenDays": []}),
            ("consecutive run", ["2026-09-18", "2026-09-19", "2026-09-20"], "2026-09-20", 7,
             {"current": 3, "longest": 3, "freezes": 2, "frozenDays": []}),
            ("1-day gap bridged spends a freeze", ["2026-09-18", "2026-09-20"], "2026-09-20", 7,
             {"current": 2, "freezes": 1, "frozenDays": ["2026-09-19"]}),
            ("gap bigger than the bank resets the run and empties it",
             ["2026-09-10", "2026-09-14"], "2026-09-14", 7,
             {"current": 1, "longest": 1, "freezes": 0, "frozenDays": []}),
            ("earning at earn_every, capped at the max",
             ["2026-09-18", "2026-09-20", "2026-09-21", "2026-09-22"], "2026-09-22", 2,
             {"freezes": 2, "frozenDays": ["2026-09-19"]}),
            ("trailing miss within the bank stays live",
             ["2026-09-17"], "2026-09-19", 7,
             {"current": 1, "freezes": 2, "freezesLeft": 1, "frozenDays": ["2026-09-18"]}),
            ("trailing misses beyond the bank lapse",
             ["2026-09-10"], "2026-09-20", 7,
             {"current": 0, "freezes": 2, "freezesLeft": 0, "frozenDays": []}),
        ]
        for name, days, today, earn_every, expected in cases:
            with self.subTest(name):
                s = gamify.compute_streak(self._days(*days), 2, earn_every,
                                          dt.date.fromisoformat(today))
                self.assertEqual({k: s[k] for k in expected}, expected)
                self.assertEqual(s["freezeMax"], 2)

    def test_study_days_counts_distinct_dates(self):
        days = self._days("2026-09-19", "2026-09-20")
        s = gamify.compute_streak(days, 2, 7, self.TODAY)
        self.assertEqual(s["studyDays"], 2)
        self.assertEqual(s["lastStudyDay"], "2026-09-20")


class PipelineTests(unittest.TestCase):
    def test_counts_and_green_streak_split(self):
        rows = [_row(1, "🔴", 0), _row(2, "🟡", 0), _row(3, "🟢", 0),
                _row(4, "🟢", 1), _row(5, "🟢", 2), _row(6, "🟢", 5), _row(7, "🎓", 3)]
        retired = [{"lcNumber": 704}]
        pl = gamify.pipeline(rows, retired)
        self.assertEqual(pl["blank"], 1)
        self.assertEqual(pl["shaky"], 1)
        self.assertEqual(pl["clean"]["total"], 4)
        self.assertEqual(pl["clean"]["s0"], 1)
        self.assertEqual(pl["clean"]["s1"], 1)
        self.assertEqual(pl["clean"]["s2plus"], 2)   # streak 2 and streak 5
        self.assertEqual(pl["graduated"], 1)
        self.assertEqual(pl["retired"], 1)

    def test_difficulty_mix(self):
        rows = [_row(1, "🟢", 1, "Easy"), _row(2, "🟢", 1, "Hard"), _row(3, "🟡", 0, "Hard")]
        self.assertEqual(gamify.difficulty_mix(rows), {"Easy": 1, "Medium": 0, "Hard": 2})

    def test_on_schedule_overdue_and_due(self):
        today = dt.date(2026, 9, 20)
        rows = [_row(1, "🟢", 1, due="2026-09-19"),   # overdue
                _row(2, "🟢", 1, due="2026-09-20"),   # due today
                _row(3, "🟢", 1, due="2026-10-01")]   # future
        os = gamify.on_schedule(rows, today)
        self.assertEqual(os["overdue"], 1)
        self.assertEqual(os["dueToday"], 1)
        self.assertEqual(os["totalActive"], 3)


class TimelineTests(unittest.TestCase):
    def test_reconstruction_and_anchor(self):
        rows = [_row(763, "🟡", 0, reps="2026-09-09, 2026-09-19")]
        sched = {"2026-09-09": {763: "🔴"}, "2026-09-19": {763: "🟡"}}
        problems = gamify.build_problems(rows, sched, {763: "greedy"},
                                         {763: "https://leetcode.com/problems/partition-labels/"})
        tl = problems[0]["timeline"]
        self.assertEqual([p["comfort"] for p in tl], ["🔴", "🟡"])
        self.assertEqual([p["level"] for p in tl], [0, 1])
        self.assertEqual(problems[0]["category"], "greedy")
        self.assertEqual(problems[0]["url"], "https://leetcode.com/problems/partition-labels/")

    def test_unknown_rep_is_activity_dot_but_last_anchors_to_current(self):
        rows = [_row(206, "🎓", 3, reps="2026-04-23, 2026-09-19")]
        sched = {}  # pre-archive: nothing known
        problems = gamify.build_problems(rows, sched, {}, {})
        tl = problems[0]["timeline"]
        self.assertIsNone(tl[0]["comfort"])            # activity dot, never fabricated
        self.assertEqual(tl[-1]["comfort"], "🎓")       # last point anchors to current comfort
        self.assertEqual(tl[-1]["level"], 3)

    def test_multi_variant_number_does_not_fabricate(self):
        # Two rows share one number (e.g. a Recursion and an Iterative method row). The
        # schedule index is keyed by number and cannot say which variant a rep was, so
        # reconstructed comfort must degrade to activity dots (null) — only the final point
        # anchors to each row's own comfort.
        rows = [_row(21, "🎓", 3, reps="2026-09-19"),
                _row(21, "🟢", 1, reps="2026-09-19")]
        sched = {"2026-09-19": {21: "🎓"}}  # would wrongly apply to BOTH without the guard
        problems = gamify.build_problems(rows, sched, {}, {})
        self.assertEqual(problems[0]["timeline"][-1]["comfort"], "🎓")   # anchored to its own
        self.assertEqual(problems[1]["timeline"][-1]["comfort"], "🟢")   # not the other variant

    def test_had_turnaround(self):
        blank_then_clean = [{"date": "1", "comfort": "🔴"}, {"date": "2", "comfort": "🟢"}]
        clean_only = [{"date": "1", "comfort": "🟢"}, {"date": "2", "comfort": "🟢"}]
        self.assertTrue(gamify._had_turnaround([{"timeline": blank_then_clean}]))
        self.assertFalse(gamify._had_turnaround([{"timeline": clean_only}]))


class BadgeTests(unittest.TestCase):
    CFG = {"streak_milestones": [7, 30], "trophy_milestones": [1, 10]}

    @staticmethod
    def _default_techniques():
        """One green, one not — the ordinary "some breadth, not full" shape."""
        return [{"name": "A", "hasGreen": True}, {"name": "B", "hasGreen": False}]

    def _stats(self, graduated=0, retired=0, clean_total=0, longest=0, no_green=1,
               techniques=None):
        techs = techniques if techniques is not None else self._default_techniques()
        return {
            "pipeline": {"graduated": graduated, "retired": retired,
                         "clean": {"total": clean_total}},
            "streak": {"longest": longest},
            "coverage": {"noGreen": no_green, "started": 56, "total": len(techs)},
            "techniques": techs,
        }

    def test_locked_when_nothing_earned(self):
        badges = gamify.compute_badges(self._stats(), [], self.CFG)
        earned = {b["id"] for b in badges if b["earned"]}
        self.assertEqual(earned, set())

    def test_graduation_and_trophy_milestones(self):
        stats = self._stats(graduated=12, retired=0, clean_total=5)
        problems = [{"difficulty": "Hard", "comfort": "🎓", "timeline": []}]
        badges = {b["id"]: b["earned"] for b in gamify.compute_badges(stats, problems, self.CFG)}
        self.assertTrue(badges["first-graduate"])
        self.assertTrue(badges["trophies-1"])
        self.assertTrue(badges["trophies-10"])       # 12 >= 10
        self.assertTrue(badges["first-hard-clean"])  # a Hard at 🎓
        self.assertFalse(badges["first-retire"])     # 0 retired
        # all-green needs a green in EVERY technique on the roadmap, not just the started
        # ones — one ungreened technique keeps it locked even with a loaded pipeline.
        self.assertFalse(badges["all-green"])

    def test_all_green_locked_despite_no_green_zero(self):
        """noGreen==0 (the OLD "every started technique" signal) no longer drives
        all-green on its own — only a green in every techniques.yml entry does."""
        stats = self._stats(no_green=0)
        badges = {b["id"]: b["earned"] for b in gamify.compute_badges(stats, [], self.CFG)}
        self.assertFalse(badges["all-green"])

    def test_all_green_earned_when_every_technique_has_green(self):
        techs = [{"name": "A", "hasGreen": True}, {"name": "B", "hasGreen": True}]
        stats = self._stats(techniques=techs)
        badges = {b["id"]: b for b in gamify.compute_badges(stats, [], self.CFG)}
        self.assertTrue(badges["all-green"]["earned"])
        self.assertEqual(badges["all-green"]["progress"], {"current": 2, "target": 2})

    def test_all_green_locked_when_no_techniques_at_all(self):
        stats = self._stats(techniques=[])
        badges = {b["id"]: b for b in gamify.compute_badges(stats, [], self.CFG)}
        self.assertFalse(badges["all-green"]["earned"])
        self.assertEqual(badges["all-green"]["progress"], {"current": 0, "target": 0})

    def test_streak_badges_use_longest(self):
        stats = self._stats(longest=30)
        badges = {b["id"]: b["earned"] for b in gamify.compute_badges(stats, [], self.CFG)}
        self.assertTrue(badges["streak-7"])
        self.assertTrue(badges["streak-30"])

    def test_progress_on_counter_badges_absent_on_event_badges(self):
        stats = self._stats(graduated=1, longest=30)
        badges = {b["id"]: b for b in gamify.compute_badges(stats, [], self.CFG)}
        self.assertEqual(badges["streak-7"]["progress"], {"current": 30, "target": 7})
        self.assertEqual(badges["trophies-1"]["progress"], {"current": 1, "target": 1})
        self.assertIn("progress", badges["all-green"])
        self.assertNotIn("progress", badges["comeback"])
        self.assertNotIn("progress", badges["first-retire"])

    def test_trophies_description_pluralization(self):
        badges = {b["id"]: b["description"]
                  for b in gamify.compute_badges(self._stats(), [], self.CFG)}
        self.assertIn("1 problem graduated", badges["trophies-1"])
        self.assertIn("10 problems graduated", badges["trophies-10"])


class DeferredToTests(unittest.TestCase):
    """eb.deferred_to(done, next_cell) over its four meaningful cases: `done`
    short-circuits before the Next cell is even read, and a Next cell that is not, once
    stripped, nothing but an ISO date is never mistaken for a deferral."""

    CASES = [
        ("not struck, ISO date -> that date", False, "2026-10-01", "2026-10-01"),
        ("struck, ISO date -> None (done short-circuits)", True, "2026-10-01", None),
        ("not struck, empty Next cell -> None", False, "", None),
        ("not struck, free-form Next text -> None", False, "—", None),
    ]

    def test_deferred_to(self):
        for label, done, next_cell, expected in self.CASES:
            with self.subTest(label):
                self.assertEqual(eb.deferred_to(done, next_cell), expected)


class CreditPulledEarlierTests(unittest.TestCase):
    """gamify._credit_pulled_earlier: a row pulled to an earlier day is done iff its copy
    on that day is done; a row moved later is untouched."""

    @staticmethod
    def _days(origin_date: str, origin_target: str, other_date: str, other_done: bool,
              other_title: str = "Min-heap") -> list[dict]:
        origin = {"lcNumber": 332, "title": "Min-heap", "done": False, "deferredTo": origin_target}
        other = {"lcNumber": 332, "title": other_title, "done": other_done, "deferredTo": None}
        return [
            {"date": origin_date, "items": [origin]},
            {"date": other_date, "items": [other]},
        ]

    CASES = [
        ("pulled earlier, earlier copy done", ("2026-10-10", "2026-10-09", "2026-10-09", True), True),
        ("pulled earlier, earlier copy not done", ("2026-10-10", "2026-10-09", "2026-10-09", False), False),
        ("moved later", ("2026-10-09", "2026-10-10", "2026-10-10", True), False),
        ("same number, other variant done", ("2026-10-10", "2026-10-09", "2026-10-09", True,
                                             "Pre-sorted"), False),
    ]

    def test_credit(self):
        for label, args, expected_done in self.CASES:
            with self.subTest(label):
                days = self._days(*args)
                result = gamify._credit_pulled_earlier(days)
                origin = result[0]["items"][0]
                self.assertEqual(origin["done"], expected_done)
                self.assertEqual(origin["deferredTo"], args[1])
                self.assertFalse(days[0]["items"][0]["done"])


class ParseTechniquesTests(unittest.TestCase):
    """parse_techniques() against a small fixture table, not the live repo file — pins the
    Problems-cell parsing (count vs. the parenthetical LC list) against the tricky tokens
    a real table can contain (*+Nv*, em-dash, tilde-strikeout elsewhere), the Tier
    column + the started/*not started* Gaps marker, and the Min column -> minProblems.
    The Min cell carries technique_coverage.py's `(floor+unclean)` breakdown — pinned here
    too, alongside the leading threshold integer."""

    FIXTURE = """## Coverage

| Technique | Family | Tier | Min | Problems | Best | 🟢 | Variants | Gaps |
|---|---|---|---:|---:|:---:|:---:|---|---|
| Hierholzer (Eulerian path) | advanced_graphs | core | 3 (2+1) | 2 *+1v* (332, 2097) | 🟢 | ✅ | pre-sorted adjacency ×1 | thin (2/3) |
| Bellman-Ford | advanced_graphs | core | 3 (3+0) | 1 (787) | 🟢 | ✅ | — | thin (1/3) |
| Dijkstra | advanced_graphs | core | 3 (3+0) | 1 (778) | 🟢 | ✅ | **Min-over-max ×0** | variant: **Min-over-max** |
| Frequency Counting | arrays_and_hash | core | 2 (2+0) | 2 (49, 242) | 🎓 | ✅ | — | — |
| Knapsack | dynamic_programming | dp | 3 (3+0) | 0 (—) | — | ❌ | — | *not started* |

## Vocabulary maintenance

- some unrelated bullet
"""

    def setUp(self):
        self._orig_coverage = gamify.COVERAGE
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(self.FIXTURE)
        tmp.close()
        gamify.COVERAGE = Path(tmp.name)

    def tearDown(self):
        gamify.COVERAGE.unlink(missing_ok=True)
        gamify.COVERAGE = self._orig_coverage

    def test_variant_rep_annotation_does_not_pollute_count_or_problems(self):
        rows = {r["name"]: r for r in gamify.parse_techniques([])}
        row = rows["Hierholzer (Eulerian path)"]
        self.assertEqual(row["problemCount"], 2)
        self.assertEqual(row["problems"], [332, 2097])
        self.assertEqual(row["family"], "advanced_graphs")
        self.assertEqual(row["bestComfort"], "🟢")
        self.assertTrue(row["hasGreen"])
        self.assertTrue(row["thin"])
        self.assertFalse(row["hasVariantGap"])

    def test_started_technique_has_tier_core_and_started_true(self):
        rows = {r["name"]: r for r in gamify.parse_techniques([])}
        row = rows["Bellman-Ford"]
        self.assertEqual(row["tier"], "core")
        self.assertTrue(row["started"])

    def test_not_started_technique_has_its_declared_tier_and_started_false(self):
        rows = {r["name"]: r for r in gamify.parse_techniques([])}
        row = rows["Knapsack"]
        self.assertEqual(row["tier"], "dp")
        self.assertFalse(row["started"])

    def test_min_problems_read_from_the_min_column(self):
        rows = {r["name"]: r for r in gamify.parse_techniques([])}
        self.assertEqual(rows["Bellman-Ford"]["minProblems"], 3)
        self.assertEqual(rows["Frequency Counting"]["minProblems"], 2)

    def test_not_started_technique_still_carries_its_declared_min_problems(self):
        rows = {r["name"]: r for r in gamify.parse_techniques([])}
        row = rows["Knapsack"]
        self.assertEqual(row["minProblems"], 3)
        self.assertEqual(row["problemCount"], 0)

    def test_min_cell_breakdown_and_its_old_bare_integer_fallback(self):
        """One case reads `minProblems`/`coverageFloor`/`uncleanCount` from the current
        `N (floor+unclean)` Min cell (this class's own FIXTURE); the other reads a bare
        integer Min cell — an older report, written before the breakdown existed — and
        must still produce all three fields, falling back to floor=minProblems and
        unclean=0 rather than leaving the two additive fields unset."""
        current_rows = {r["name"]: r for r in gamify.parse_techniques([])}
        with self.subTest("current (floor+unclean) breakdown"):
            row = current_rows["Hierholzer (Eulerian path)"]
            self.assertEqual((row["minProblems"], row["coverageFloor"], row["uncleanCount"]),
                              (3, 2, 1))

        old_fixture = """## Coverage

| Technique | Family | Tier | Min | Problems | Best | 🟢 | Variants | Gaps |
|---|---|---|---:|---:|:---:|:---:|---|---|
| Bellman-Ford | advanced_graphs | core | 3 | 1 (787) | 🟢 | ✅ | — | thin (1/3) |
"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(old_fixture)
        tmp.close()
        orig_coverage = gamify.COVERAGE
        gamify.COVERAGE = Path(tmp.name)
        try:
            old_rows = {r["name"]: r for r in gamify.parse_techniques([])}
        finally:
            gamify.COVERAGE.unlink(missing_ok=True)
            gamify.COVERAGE = orig_coverage
        with self.subTest("older report, bare-integer Min cell"):
            row = old_rows["Bellman-Ford"]
            self.assertEqual((row["minProblems"], row["coverageFloor"], row["uncleanCount"]),
                              (3, 3, 0))

    def test_simple_single_problem_row(self):
        rows = {r["name"]: r for r in gamify.parse_techniques([])}
        row = rows["Bellman-Ford"]
        self.assertEqual(row["problemCount"], 1)
        self.assertEqual(row["problems"], [787])

    def test_variant_gap_flag(self):
        rows = {r["name"]: r for r in gamify.parse_techniques([])}
        self.assertTrue(rows["Dijkstra"]["hasVariantGap"])

    def test_em_dash_row_is_zero_and_empty_not_a_crash(self):
        rows = {r["name"]: r for r in gamify.parse_techniques([])}
        row = rows["Knapsack"]
        self.assertEqual(row["problemCount"], 0)
        self.assertEqual(row["problems"], [])
        self.assertIsNone(row["bestComfort"])
        self.assertFalse(row["hasGreen"])
        self.assertFalse(row["thin"])
        self.assertFalse(row["hasVariantGap"])

    def test_header_and_separator_rows_excluded(self):
        names = {r["name"] for r in gamify.parse_techniques([])}
        self.assertNotIn("Technique", names)
        self.assertEqual(len(gamify.parse_techniques([])), 5)

    def test_missing_file_fails_soft(self):
        gamify.COVERAGE = Path(tempfile.gettempdir()) / "no-such-coverage-file.md"
        self.assertEqual(gamify.parse_techniques([]), [])


class ParseTechniquesWrongColumnCountTests(unittest.TestCase):
    """An older technique_coverage.py emitting a 7-column table (no Min / no 🟢 columns)
    must not silently yield [] with no signal — it warns and returns []."""

    FIXTURE = """## Coverage

| Technique | Family | Min | Problems | Best | Variants | Gaps |
|---|---|---:|---:|:---:|---|---|
| Bellman-Ford | advanced_graphs | 3 | 1 (787) | 🟢 | — | thin (1/3) |
"""

    def setUp(self):
        self._orig_coverage = gamify.COVERAGE
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(self.FIXTURE)
        tmp.close()
        gamify.COVERAGE = Path(tmp.name)

    def tearDown(self):
        gamify.COVERAGE.unlink(missing_ok=True)
        gamify.COVERAGE = self._orig_coverage

    def test_wrong_column_count_returns_empty(self):
        self.assertEqual(gamify.parse_techniques([]), [])

    def test_wrong_column_count_warns_with_the_actual_count(self):
        warnings: list[str] = []
        gamify.parse_techniques(warnings)
        self.assertEqual(len(warnings), 1)
        self.assertIn("7 columns", warnings[0])
        self.assertIn("expected 9", warnings[0])


def _tech_row(name, problems=None, started=True):
    return {"name": name, "family": "f", "tier": "core", "started": started,
            "minProblems": 3, "problemCount": len(problems or []),
            "problems": problems or [], "bestComfort": None, "hasGreen": False,
            "thin": True, "hasVariantGap": False}


def _yaml_entry(name, builds_on=None, problems=None):
    return {"name": name, "builds_on": builds_on, "problems": problems}


def _problem(num, comfort, title=""):
    return {"lcNumber": num, "comfort": comfort, "title": title}


class EnrichTechniquesTests(unittest.TestCase):
    """enrich_techniques() against plain-dict fixtures (parse_techniques()'s row shape and
    techniques.yml's own entry shape) — never the live repo file. Pins: builds_on copies
    through; defaults to []; an unknown name is dropped with a warning; a self-edge is
    dropped with a warning; a 2-cycle is detected and one edge dropped; graduatedCount
    counts 🎓 and 🏆 but not 🟢; planned carries every declared-but-untracked problem;
    enrich_techniques never mutates its inputs.

    planned carries EVERY declared-untracked problem, `queued` key or not (trigger null
    without one); title/url/difficulty resolve from `waiting_room` first, then the
    `catalog` param (roadmap.yml, via load_roadmap() — see gamify.build_payload());
    `plannedTotal` = problemCount + len(planned); `untriedVariations` names an unqueued
    `×0` variant from the row's (internal, stripped-before-return) `_variantsCell`; a
    number declared under two entries counts in each; two `method:` rows for the same
    untracked number collapse to ONE planned entry."""

    def test_builds_on_copies_through(self):
        rows = [_tech_row("B")]
        entries = [_yaml_entry("A"), _yaml_entry("B", ["A"])]
        out = gamify.enrich_techniques(rows, entries, {}, {}, [])
        self.assertEqual(out[0]["buildsOn"], ["A"])

    def test_builds_on_defaults_to_empty_list(self):
        rows = [_tech_row("Root")]
        entries = [_yaml_entry("Root")]
        out = gamify.enrich_techniques(rows, entries, {}, {}, [])
        self.assertEqual(out[0]["buildsOn"], [])

    def test_unknown_name_dropped_with_warning(self):
        rows = [_tech_row("B")]
        entries = [_yaml_entry("B", ["Nonexistent"])]
        warnings: list[str] = []
        out = gamify.enrich_techniques(rows, entries, {}, {}, warnings)
        self.assertEqual(out[0]["buildsOn"], [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("Nonexistent", warnings[0])

    def test_self_edge_dropped_with_warning(self):
        rows = [_tech_row("A")]
        entries = [_yaml_entry("A", ["A"])]
        warnings: list[str] = []
        out = gamify.enrich_techniques(rows, entries, {}, {}, warnings)
        self.assertEqual(out[0]["buildsOn"], [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("itself", warnings[0])

    def test_two_cycle_detected_and_one_edge_dropped(self):
        rows = [_tech_row("A"), _tech_row("B")]
        entries = [_yaml_entry("A", ["B"]), _yaml_entry("B", ["A"])]
        warnings: list[str] = []
        out = gamify.enrich_techniques(rows, entries, {}, {}, warnings)
        by_name = {r["name"]: r["buildsOn"] for r in out}
        # exactly one of the two edges survives — the DFS back-edge is dropped
        total_edges = len(by_name["A"]) + len(by_name["B"])
        self.assertEqual(total_edges, 1)
        self.assertTrue(any("cycle" in w for w in warnings))

    def test_graduated_and_retired_count_graduated_streak_and_clean_do_not(self):
        rows = [_tech_row("T", problems=[1, 2, 3, 4])]
        entries = [_yaml_entry("T")]
        comfort_by_number = {1: "🎓", 2: "🏆", 3: "🟢", 4: "🟡"}
        problems = [_problem(1, "🎓"), _problem(3, "🟢"), _problem(4, "🟡")]
        out = gamify.enrich_techniques(rows, entries, comfort_by_number, {}, [],
                                       problems=problems)
        self.assertEqual(out[0]["graduatedCount"], 2)

    def test_rows_and_graduated_count_follow_the_number_and_method_join(self):
        recursion = _problem(206, "🟢", "Reverse Linked List (Recursion)")
        iterative = _problem(206, "🎓", "Reverse Linked List (Iterative)")
        problems = [recursion, iterative, _problem(5, "🎓", "Plain")]
        as_row = lambda p: {"lcNumber": p["lcNumber"], "title": p["title"]}  # noqa: E731
        cases = [
            ("method spec credits only its variant",
             [{"number": 206, "method": "Recursion"}], [206], {}, [recursion], 0),
            ("method-less spec credits every variant",
             [{"number": 206}], [206], {}, [recursion, iterative], 1),
            ("no yaml entry credits every row of the numbers",
             None, [206, 5], {}, [recursion, iterative, problems[2]], 2),
            ("retired number still counts",
             [{"number": 206, "method": "Recursion"}, {"number": 77}], [206, 77],
             {77: "🏆"}, [recursion], 1),
        ]
        for label, specs, numbers, comfort, expected_rows, expected_graduated in cases:
            with self.subTest(label):
                rows = [_tech_row("T", problems=numbers)]
                entries = [_yaml_entry("T", problems=specs)] if specs is not None else []
                out = gamify.enrich_techniques(rows, entries, comfort, {}, [], problems=problems)
                self.assertEqual(out[0]["rows"], [as_row(p) for p in expected_rows])
                self.assertEqual(out[0]["graduatedCount"], expected_graduated)

    def test_untracked_problem_number_does_not_count(self):
        rows = [_tech_row("T", problems=[99])]
        entries = [_yaml_entry("T")]
        out = gamify.enrich_techniques(rows, entries, {}, {}, [])
        self.assertEqual(out[0]["graduatedCount"], 0)

    def test_does_not_mutate_inputs(self):
        row = _tech_row("B")
        entry = _yaml_entry("B", ["A"])
        rows, entries = [row], [_yaml_entry("A"), entry]
        gamify.enrich_techniques(rows, entries, {}, {}, [])
        self.assertNotIn("buildsOn", row)
        self.assertNotIn("graduatedCount", row)
        self.assertNotIn("planned", row)

    def test_comfort_by_number_malformed_glyph_does_not_raise_or_count(self):
        # build_problems() itself is fail-soft (LEVEL.get(r["comfort"]), never LEVEL[...]),
        # so _comfort_by_number must be too: a tracker cell outside LEVEL's five glyphs
        # must never raise build_payload out of its "never raises" contract.
        problems = [_problem(1, "?")]
        comfort_by_number = gamify._comfort_by_number(problems, retired=[])
        self.assertNotIn(1, comfort_by_number)

        rows = [_tech_row("T", problems=[1])]
        entries = [_yaml_entry("T")]
        out = gamify.enrich_techniques(rows, entries, comfort_by_number, {}, [])
        self.assertEqual(out[0]["graduatedCount"], 0)

    def test_queued_and_untracked_problem_appears_in_planned(self):
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[{"number": 9001, "queued": "surplus>=1"}])]
        waiting_room = {9001: {"title": "Cracking the Safe", "url": "https://x",
                               "difficulty": "Hard"}}
        out = gamify.enrich_techniques(rows, entries, {}, waiting_room, [])
        self.assertEqual(out[0]["planned"], [
            {"lcNumber": 9001, "title": "Cracking the Safe", "url": "https://x",
             "difficulty": "Hard", "trigger": "surplus>=1"}])

    def test_queued_but_already_tracked_problem_is_absent_from_planned(self):
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[{"number": 146, "queued": "rated:146"}])]
        out = gamify.enrich_techniques(rows, entries, {146: "🟢"}, {}, [])
        self.assertEqual(out[0]["planned"], [])

    def test_queued_problem_with_no_waiting_room_row_emits_nulls_and_one_warning(self):
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[{"number": 394, "queued": "surplus>=1"}])]
        warnings: list[str] = []
        out = gamify.enrich_techniques(rows, entries, {}, {}, warnings)
        self.assertEqual(out[0]["planned"], [
            {"lcNumber": 394, "title": None, "url": None, "difficulty": None,
             "trigger": "surplus>=1"}])
        self.assertEqual(len(warnings), 1)
        self.assertIn("394", warnings[0])

    def test_not_started_technique_still_carries_planned(self):
        rows = [_tech_row("T", started=False)]
        entries = [_yaml_entry("T", problems=[{"number": 6, "queued": "surplus>=1"}])]
        waiting_room = {6: {"title": "Zigzag Conversion", "url": "https://x",
                            "difficulty": "Medium"}}
        out = gamify.enrich_techniques(rows, entries, {}, waiting_room, [])
        self.assertEqual(len(out[0]["planned"]), 1)
        self.assertEqual(out[0]["planned"][0]["lcNumber"], 6)

    def test_declared_unqueued_untracked_problem_has_null_trigger(self):
        # `queued` is optional on an untracked spec — it is still `planned`, just with
        # `trigger: None` instead of a trigger string.
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[{"number": 547}])]
        catalog = {547: {"title": "Number of Provinces", "url": "https://x",
                         "difficulty": "Medium"}}
        out = gamify.enrich_techniques(rows, entries, {}, {}, [], catalog=catalog)
        self.assertEqual(out[0]["planned"], [
            {"lcNumber": 547, "title": "Number of Provinces", "url": "https://x",
             "difficulty": "Medium", "trigger": None}])

    def test_title_resolves_from_catalog_when_no_waiting_room_row(self):
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[{"number": 501, "queued": "surplus>=1"}])]
        catalog = {501: {"title": "Catalog Title", "url": "https://catalog",
                         "difficulty": "Hard"}}
        out = gamify.enrich_techniques(rows, entries, {}, {}, [], catalog=catalog)
        self.assertEqual(out[0]["planned"], [
            {"lcNumber": 501, "title": "Catalog Title", "url": "https://catalog",
             "difficulty": "Hard", "trigger": "surplus>=1"}])

    def test_waiting_room_wins_over_catalog_when_both_have_the_number(self):
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[{"number": 502, "queued": "surplus>=1"}])]
        waiting_room = {502: {"title": "WR Title", "url": "https://wr",
                              "difficulty": "Easy"}}
        catalog = {502: {"title": "Catalog Title", "url": "https://catalog",
                         "difficulty": "Hard"}}
        out = gamify.enrich_techniques(rows, entries, {}, waiting_room, [], catalog=catalog)
        self.assertEqual(out[0]["planned"], [
            {"lcNumber": 502, "title": "WR Title", "url": "https://wr",
             "difficulty": "Easy", "trigger": "surplus>=1"}])

    def test_planned_total_equals_problem_count_plus_planned_length(self):
        rows = [_tech_row("T", problems=[1, 2])]
        entries = [_yaml_entry("T", problems=[
            {"number": 1}, {"number": 2}, {"number": 503, "queued": "surplus>=1"}])]
        catalog = {503: {"title": "Extra Problem", "url": "https://x", "difficulty": "Easy"}}
        out = gamify.enrich_techniques(rows, entries, {1: "🎓", 2: "🎓"}, {}, [],
                                       catalog=catalog)
        self.assertEqual(len(out[0]["planned"]), 1)
        self.assertEqual(out[0]["plannedTotal"],
                         out[0]["problemCount"] + len(out[0]["planned"]))
        self.assertEqual(out[0]["plannedTotal"], 3)

    def test_untried_variations_names_unqueued_gaps_and_omits_queued_one(self):
        # Both unqueued names carry parentheses, and one of them also carries a slash; a
        # queued gap in the same cell must still be excluded.
        rows = [_tech_row("T")]
        rows[0]["_variantsCell"] = (
            "**0/1 edge weights (0-1 BFS vs Dijkstra) ×0** · "
            "**Max-min bottleneck (maximize the minimum edge) ×0** · "
            "~~Multiplicative relaxation (maximize the product)~~ *(queued: `surplus>=1`)*")
        entries = [_yaml_entry("T")]
        out = gamify.enrich_techniques(rows, entries, {}, {}, [])
        self.assertEqual(out[0]["untriedVariations"], [
            "0/1 edge weights (0-1 BFS vs Dijkstra)",
            "Max-min bottleneck (maximize the minimum edge)"])
        self.assertNotIn("_variantsCell", out[0])

    def test_declared_under_two_entries_counts_the_problem_in_each(self):
        rows = [_tech_row("A"), _tech_row("B")]
        entries = [_yaml_entry("A", problems=[{"number": 23, "queued": "surplus>=1"}]),
                  _yaml_entry("B", problems=[{"number": 23, "queued": "surplus>=1"}])]
        catalog = {23: {"title": "Merge k Sorted Lists", "url": "https://x",
                       "difficulty": "Hard"}}
        out = gamify.enrich_techniques(rows, entries, {}, {}, [], catalog=catalog)
        by_name = {r["name"]: r for r in out}
        self.assertEqual(by_name["A"]["planned"][0]["lcNumber"], 23)
        self.assertEqual(by_name["B"]["planned"][0]["lcNumber"], 23)

    def test_two_method_rows_for_same_untracked_number_produce_one_planned_entry(self):
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[
            {"number": 206, "method": "Iterative", "queued": "surplus>=1"},
            {"number": 206, "method": "Recursion"},
        ])]
        catalog = {206: {"title": "Reverse Linked List", "url": "https://x",
                        "difficulty": "Easy"}}
        out = gamify.enrich_techniques(rows, entries, {}, {}, [], catalog=catalog)
        self.assertEqual(len(out[0]["planned"]), 1)
        # The first NON-NULL `queued` across the number's rows wins.
        self.assertEqual(out[0]["planned"][0]["trigger"], "surplus>=1")

    def test_two_method_rows_queued_on_the_second_row_still_resolves(self):
        # The mirror case: the FIRST row for the number carries no `queued` at all, and
        # the trigger only shows up on the SECOND row — it must still come through
        # rather than being lost behind the first row's null.
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[
            {"number": 19, "method": "Iterative"},
            {"number": 19, "method": "Postorder Recursion", "queued": "surplus>=1"},
        ])]
        catalog = {19: {"title": "Remove Nth Node From End of List", "url": "https://x",
                       "difficulty": "Medium"}}
        out = gamify.enrich_techniques(rows, entries, {}, {}, [], catalog=catalog)
        self.assertEqual(len(out[0]["planned"]), 1)
        self.assertEqual(out[0]["planned"][0]["trigger"], "surplus>=1")

    def test_declared_without_rows_warning(self):
        resolved = {"title": "T", "url": "https://x", "difficulty": "Easy"}
        aggregated = ("techniques.yml: 4 declared problems have no Waiting Room row or "
                      "roadmap.yml entry — planned entries emitted with nulls (first: 11, 12, 13).")
        cases = [
            ("no dated rows: silent", False, [11, 12, 13, 14], {}, False, []),
            ("undeclared numbers: one aggregated line", True, [11, 12, 13, 14, 15], {15: resolved},
             True, [aggregated]),
            ("every number resolved: no line", True, [11, 12], {11: resolved, 12: resolved},
             True, []),
        ]
        for label, has_rows, numbers, catalog, roadmap_line, expected in cases:
            with self.subTest(label):
                entries = [_yaml_entry("T", problems=[{"number": n} for n in numbers])]
                warnings: list[str] = []
                with mock.patch.object(gamify, "ROADMAP_YML", Path("missing/roadmap.yml")):
                    gamify.load_roadmap(warnings, has_tracker_rows=has_rows)
                self.assertEqual(len(warnings), int(roadmap_line))
                warnings.clear()
                gamify.enrich_techniques([_tech_row("T")], entries, {}, {}, warnings,
                                         catalog=catalog, has_tracker_rows=has_rows)
                self.assertEqual(warnings, expected)

    def test_missing_title_warning_fires_once_for_untracked_unqueued_problem(self):
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[{"number": 999}])]
        warnings: list[str] = []
        out = gamify.enrich_techniques(rows, entries, {}, {}, warnings)
        self.assertEqual(out[0]["planned"], [
            {"lcNumber": 999, "title": None, "url": None, "difficulty": None,
             "trigger": None}])
        self.assertEqual(len(warnings), 1)
        self.assertIn("999", warnings[0])

    def test_planned_false_and_untracked_is_absent_from_planned_and_total(self):
        # `planned: false` opts an untracked number (a recognition probe whose row was
        # dropped) out of both `planned` and `plannedTotal`.
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[{"number": 547, "planned": False}])]
        out = gamify.enrich_techniques(rows, entries, {}, {}, [])
        self.assertEqual(out[0]["planned"], [])
        self.assertEqual(out[0]["plannedTotal"], out[0]["problemCount"])

    def test_one_planned_false_spec_among_several_keeps_the_number_in(self):
        # A number is excluded only when EVERY untracked spec for it carries
        # `planned: false` — a single ordinary spec keeps it in.
        rows = [_tech_row("T")]
        entries = [_yaml_entry("T", problems=[
            {"number": 547, "planned": False},
            {"number": 547, "queued": "surplus>=1"},
        ])]
        catalog = {547: {"title": "Number of Provinces", "url": "https://x",
                         "difficulty": "Medium"}}
        out = gamify.enrich_techniques(rows, entries, {}, {}, [], catalog=catalog)
        self.assertEqual(len(out[0]["planned"]), 1)
        self.assertEqual(out[0]["planned"][0]["lcNumber"], 547)
        self.assertEqual(out[0]["planned"][0]["trigger"], "surplus>=1")

    def test_planned_false_on_a_tracked_number_does_not_affect_problem_count(self):
        # `planned: false` only ever governs the untracked-number `planned` list — a
        # number that already has a tracker row stays counted in `problemCount`
        # (which comes from the coverage table, not from this key) regardless.
        rows = [_tech_row("T", problems=[547])]
        entries = [_yaml_entry("T", problems=[{"number": 547, "planned": False}])]
        out = gamify.enrich_techniques(rows, entries, {547: "🎓"}, {}, [],
                                       problems=[_problem(547, "🎓")])
        self.assertEqual(out[0]["problemCount"], 1)
        self.assertEqual(out[0]["graduatedCount"], 1)
        self.assertEqual(out[0]["planned"], [])


class ParseWaitingRoomTests(unittest.TestCase):
    """parse_waiting_room() against a small string fixture (never the live repo file).
    Pins: scoped to the `## ⏳ Waiting Room` section alone (a look-alike header before AND
    after the section is ignored); a Kattis row (external-judge URL) parses like an LC row;
    a Notes cell carrying its own markdown links (`[Kattis \\`shortestpath3\\`](...)`,
    `[CSES 1673](...)`) never leaks into the title; a duplicated number keeps its FIRST
    occurrence; a text with no Waiting Room heading at all returns {}."""

    FIXTURE = (
        "## Some Other Section\n\n"
        "| Difficulty | Problem | Trigger | Notes |\n"
        "|---|---|---|---|\n"
        "| Medium | [999. Decoy Outside Section](https://leetcode.com/problems/decoy/) "
        "| `surplus>=1` | Never parsed — outside the Waiting Room. |\n\n"
        "## ⏳ Waiting Room — will enter rotation\n\n"
        "Some prose about the trigger vocabulary.\n\n"
        "| Difficulty | Problem | Trigger | Notes |\n"
        "|---|---|---|---|\n"
        "| Easy | [9001. Single Source Shortest Path, Negative Weights]"
        "(https://open.kattis.com/problems/shortestpath3) | `surplus>=1` | Hand-picked "
        "from [Kattis `shortestpath3`](https://open.kattis.com/problems/shortestpath3). "
        "See [CSES 1673](https://cses.fi/problemset/task/1673) too. |\n"
        "| Hard | [1216. Valid Palindrome III (backtracking)]"
        "(https://leetcode.com/problems/valid-palindrome-iii/) | `phase:Backtracking` "
        "| First occurrence — wins. |\n"
        "| Hard | [1216. Valid Palindrome III (1DP)]"
        "(https://leetcode.com/problems/valid-palindrome-iii/) | `phase:1D-DP` "
        "| Duplicate number — ignored. |\n\n"
        "## Grind 75 Fill\n\n"
        "| Difficulty | Problem | Trigger | Notes |\n"
        "|---|---|---|---|\n"
        "| Medium | [815. Another Decoy Row](https://leetcode.com/problems/another/) "
        "| `surplus>=1` | Same header shape, past the boundary — never parsed. |\n"
    )

    def test_scoped_to_waiting_room_section_only(self):
        result = gamify.parse_waiting_room(self.FIXTURE)
        self.assertNotIn(999, result)
        self.assertNotIn(815, result)
        self.assertIn(9001, result)
        self.assertIn(1216, result)

    def test_kattis_row_parses_like_an_lc_row(self):
        result = gamify.parse_waiting_room(self.FIXTURE)
        self.assertEqual(result[9001], {
            "title": "Single Source Shortest Path, Negative Weights",
            "url": "https://open.kattis.com/problems/shortestpath3",
            "difficulty": "Easy"})

    def test_notes_links_never_leak_into_title(self):
        result = gamify.parse_waiting_room(self.FIXTURE)
        self.assertNotIn("Kattis", result[9001]["title"])
        self.assertNotIn("CSES", result[9001]["title"])

    def test_first_occurrence_of_a_duplicate_number_wins(self):
        result = gamify.parse_waiting_room(self.FIXTURE)
        self.assertEqual(result[1216]["title"], "Valid Palindrome III (backtracking)")

    def test_no_waiting_room_heading_returns_empty(self):
        self.assertEqual(gamify.parse_waiting_room("# Nothing here\n\nplain text\n"), {})


class ParseCurrentWeekScheduleTests(unittest.TestCase):
    """parse_current_week_schedule() against a small fixture week (not the live repo file)
    — pins the Today's-board slice: a plain row, a struck/done row (glyph swap-out and
    title cleanup on a `~~[...]~~` cell), a bare-number 🆕 row (lcNumber via the fallback,
    url via the row's own [LC] link, kind "new"), a row whose own [LC] link wins over a
    (deliberately different) urls.get() value, a 🔤 concept-primer row (kind "primer", no
    lcNumber/url at all), a row struck AHEAD of its tag glyph (`~~🆕 <n> ...~~` — pins
    tags/kind survive emphasis ahead of the glyph, and done stays true), and the three
    Sunday `🎯 ... | Complexity` rows (kind "complexity" beats the 🎯 tag) — together the
    five `kind` values are all covered. Also pins `_schedule_item_url`'s full 3-way
    precedence: an NC-only row WITH a tracker entry (the tracker join wins over the row's
    own NC link) and an NC-only row with NO tracker entry (the NC link is used as the last
    resort). Also pins the tracker-joined `difficulty` — including the honest null for a
    number the tracker doesn't have yet."""

    FIXTURE = (
        "## Daily Schedule\n\n"
        "| Problem | S | E | Next | Technique |\n"
        "|---|:-:|:-:|:-:|---|\n"
        "| ▸ **Mon Sep 21** · 6.8 units — Test day one |  |  |  |  |\n"
        "| ⚠️🔥 [22 Generate Parentheses](../../../dsa/leetcode/backtracking/22_generate_parentheses.py)"
        " · [LC](https://leetcode.com/problems/generate-parentheses/) | 🔴 | | | Backtracking |\n"
        "| ~~[100 Same Tree](../../../dsa/leetcode/trees/100_same_tree.py)~~"
        " · [LC](https://leetcode.com/problems/same-tree/) | 🟢 | 🎓 | 2026-10-01 | Tree-DFS |\n"
        "| [55 Jump Game](../../../dsa/leetcode/greedy/55_jump_game.py)"
        " · [LC](https://leetcode.com/problems/jump-game/) | 🟡 | | | Greedy |\n"
        "| |  |  |  |  |\n"
        "| ▸ **Tue Sep 22** · 5.0 units — Test day two |  |  |  |  |\n"
        "| 🆕 39 Combination Sum · [LC](https://leetcode.com/problems/combination-sum/)"
        " | 🆕 | | | Backtracking |\n"
        "| |  |  |  |  |\n"
        "| ▸ **Thu Sep 24** · 3.0 units — Test day three |  |  |  |  |\n"
        "| [77 Word Break](../../../dsa/leetcode/dp/77_word_break.py)"
        " · [LC](https://leetcode.com/problems/word-break/) | 🟡 | | | DP |\n"
        # The 🔤 row shape: a bare **Bold Title** with no digit after `**` (so
        # eb.SCHED_NUM finds nothing and the bare-number fallback also finds nothing,
        # since the title itself starts with a letter, not a number), 🔤 in both the
        # Problem cell and the S column, and a free-form Technique cell that is NOT
        # "Complexity" — the only kind/tag branch no other fixture row exercises.
        "| 🔤 **Two Pointers primer** — before the phase opens Oct 5"
        " | 🔤 | | | concept overview, no LC number |\n"
        # Emphasis-before-glyph: older weeks strike (or bold, or both) the WHOLE row ahead
        # of its tag glyph rather than plain — a real shape, not a hypothetical.
        "| ~~🆕 39 Combination Sum · [LC](https://leetcode.com/problems/combination-sum/)~~"
        " | 🆕 | | | Backtracking |\n"
        "| |  |  |  |  |\n"
        # NC-only rows (no [LC] at all) — _schedule_item_url's 3-way precedence, per-case:
        "| ▸ **Fri Sep 25** · 4.0 units — Test day four |  |  |  |  |\n"
        # 200 IS in the tracker: the tracker join (precedence 2) must win over this row's
        # own [NC] link (precedence 3) — an NC url must never beat a real LC one.
        "| [200 Number of Islands](../../../dsa/leetcode/graphs/200_number_of_islands.py)"
        " · [NC](https://neetcode.io/problems/number-of-islands) | 🟡 | | | BFS |\n"
        "| |  |  |  |  |\n"
        "| ▸ **Sat Sep 26** · ~4.0 units — Test day five |  |  |  |  |\n"
        # 269 is NOT in the tracker: nothing outranks the row's own [NC] link, so it's
        # used as the last resort rather than leaving url null.
        "| [269 Alien Dictionary](../../../dsa/leetcode/graphs/269_alien_dictionary.py)"
        " · [NC](https://neetcode.io/problems/foreign-dictionary) | 🟡 | | | Topological Sort |\n"
        "| |  |  |  |  |\n"
        "| ▸ **Sun Sep 27** · 2.0 units — Complexity day |  |  |  |  |\n"
        "| 🎯 [226 Invert Binary Tree](../../../dsa/leetcode/trees/226_invert_binary_tree.py)"
        " · [LC](https://leetcode.com/problems/invert-binary-tree/) — complexity re-ask (time)"
        " | 🎯 | | | Complexity |\n"
        "| 🎯 [98 Validate BST](../../../dsa/leetcode/trees/98_validate_bst.py)"
        " · [LC](https://leetcode.com/problems/validate-binary-search-tree/) — complexity re-ask (space)"
        " | 🎯 | | | Complexity |\n"
        "| 🎯 [543 Diameter of Binary Tree](../../../dsa/leetcode/trees/543_diameter_of_binary_tree.py)"
        " · [LC](https://leetcode.com/problems/diameter-of-binary-tree/) — complexity re-ask (time)"
        " | 🎯 | | | Complexity |\n"
    )

    # Joined by lcNumber into the schedule items above: 22 -> Medium, 100 -> Easy,
    # 200 -> Medium. 39 (the 🆕 row), 77, and 269 are deliberately ABSENT — 39 must
    # resolve to null (no tracker entry yet); 77 pins that difficulty and url are joined
    # independently (77 gets its url from its own [LC] link despite no tracker row); 269
    # (NC-only, no tracker row) pins the honest-null-turned-NC-last-resort case.
    TRACKER_FIXTURE = (
        "| Medium | [22. Generate Parentheses](https://leetcode.com/problems/generate-parentheses/) "
        "| 🔴 | 0 | 2026-12-01 |\n"
        "| Easy | [100. Same Tree](https://leetcode.com/problems/same-tree/) "
        "| 🎓 | 3 | 2026-12-05 |\n"
        "| Medium | [200. Number of Islands](https://leetcode.com/problems/number-of-islands/) "
        "| 🟡 | 1 | 2026-11-01 |\n"
    )

    # Joined by lcNumber into the schedule items above, mirroring TRACKER_FIXTURE's own
    # markdown links (problem_urls() reads the same file). 55 and 39 are deliberately
    # absent — the honest-null / own-link-only cases pinned below. 77's entry is
    # deliberately a DIFFERENT url than its row's own [LC] link, to pin that the row's own
    # [LC] link wins (see _schedule_item_url) rather than this tracker join. 200's entry
    # pins the OPPOSITE precedence case: this tracker join must win over 200's own [NC]
    # link (an NC url must never outrank a real LC one). 269 is deliberately absent from
    # both TRACKER_FIXTURE and here — its own [NC] link is the only source available.
    URLS = {22: "https://leetcode.com/problems/generate-parentheses/",
            100: "https://leetcode.com/problems/same-tree/",
            77: "https://leetcode.com/problems/STALE-SLUG-DO-NOT-PREFER/",
            200: "https://leetcode.com/problems/number-of-islands/"}

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_schedules = eb.SCHEDULES
        self._orig_tracker = eb.TRACKER
        self._orig_gamify_tracker = gamify.TRACKER
        sched_dir = Path(self._tmpdir.name)
        (sched_dir / "20260921_schedule.md").write_text(self.FIXTURE, encoding="utf-8")
        eb.SCHEDULES = sched_dir
        tracker_path = sched_dir / "dsa_progress.md"
        tracker_path.write_text(self.TRACKER_FIXTURE, encoding="utf-8")
        eb.TRACKER = tracker_path
        gamify.TRACKER = tracker_path

    def tearDown(self):
        eb.SCHEDULES = self._orig_schedules
        eb.TRACKER = self._orig_tracker
        gamify.TRACKER = self._orig_gamify_tracker
        self._tmpdir.cleanup()

    def test_all_seven_days_emitted_with_correct_dates(self):
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        self.assertIsNotNone(result)
        self.assertEqual(result["weekOf"], "2026-09-21")
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual(result["days"][0]["date"], "2026-09-21")
        self.assertEqual(result["days"][6]["date"], "2026-09-27")

    def test_monday_items_and_done_row_parsed(self):
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        mon = result["days"][0]
        self.assertEqual(mon["weekday"], "Monday")
        self.assertEqual(mon["units"], 6.8)
        self.assertEqual(mon["label"], "Test day one")
        # An approximate price ("~4.0 units") is still a price — the `~` must not null the
        # units, or the dashboard's workload bar for that day vanishes.
        self.assertEqual(result["days"][5]["units"], 4.0)
        self.assertEqual(len(mon["items"]), 3)

        plain, done, untracked = mon["items"]
        self.assertEqual(plain, {"lcNumber": 22, "title": "Generate Parentheses",
                                 "technique": "Backtracking", "startComfort": "🔴",
                                 "startNote": None,
                                 "difficulty": "Medium",
                                 "url": "https://leetcode.com/problems/generate-parentheses/",
                                 "file": None,
                                 "tags": ["protected", "backfill"], "kind": "rep",
                                 "done": False, "deferredTo": None, "pulledIn": False,
                                 "endComfort": None, "endNote": None, "nextReview": None})
        # The 100 row's E cell is "🎓" (no trailing note) and Next is "2026-10-01" — pins
        # endComfort/nextReview are emitted, and a glyph with nothing following it yields
        # endNote null rather than an empty string.
        self.assertEqual(done, {"lcNumber": 100, "title": "Same Tree",
                                "technique": "Tree-DFS", "startComfort": "🟢",
                                "startNote": None,
                                "difficulty": "Easy",
                                "url": "https://leetcode.com/problems/same-tree/",
                                "file": None,
                                "tags": [], "kind": "rep",
                                "done": True, "deferredTo": None, "pulledIn": False,
                                "endComfort": "🎓", "endNote": None, "nextReview": "2026-10-01"})
        # 55 has a real lcNumber but is deliberately absent from TRACKER_FIXTURE — the
        # honest-null case for `difficulty` (a number the tracker doesn't have yet). `url`
        # is NOT null, though: 55's row carries its own [LC] link, which _schedule_item_url
        # reads directly, independently of the (absent) tracker join.
        self.assertEqual(untracked, {"lcNumber": 55, "title": "Jump Game",
                                     "technique": "Greedy", "startComfort": "🟡",
                                     "startNote": None,
                                     "difficulty": None,
                                     "url": "https://leetcode.com/problems/jump-game/",
                                     "file": None,
                                     "tags": [], "kind": "rep",
                                     "done": False, "deferredTo": None, "pulledIn": False,
                                     "endComfort": None, "endNote": None, "nextReview": None})

    def test_new_intake_row_gets_lcnumber_from_fallback_and_url_from_own_link(self):
        # 🆕 39 has no `[`/`**` before its number, so eb.SCHED_NUM (by design) finds
        # nothing — but _schedule_item_lc_number's bare-digits fallback still recovers 39
        # from the tag-stripped title, and _schedule_item_url reads its url straight off
        # the row's own [LC] link (39 has no TRACKER_FIXTURE/URLS entry at all).
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        tue = result["days"][1]
        self.assertEqual(len(tue["items"]), 1)
        self.assertEqual(tue["items"][0], {"lcNumber": 39, "title": "Combination Sum",
                                           "technique": "Backtracking", "startComfort": None,
                                           "startNote": None,
                                           "difficulty": None,
                                           "url": "https://leetcode.com/problems/combination-sum/",
                                           "file": None,
                                           "tags": ["new"], "kind": "new",
                                           "done": False, "deferredTo": None, "pulledIn": False,
                                           "endComfort": None, "endNote": None, "nextReview": None})

    def test_row_own_link_url_wins_over_tracker_join(self):
        # 77's URLS entry is deliberately a different (stale) url — the row's own [LC]
        # link must win, per _schedule_item_url's precedence.
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        thu = result["days"][3]
        self.assertEqual(len(thu["items"]), 3)
        self.assertEqual(thu["items"][0], {"lcNumber": 77, "title": "Word Break",
                                           "technique": "DP", "startComfort": "🟡",
                                           "startNote": None,
                                           "difficulty": None,
                                           "url": "https://leetcode.com/problems/word-break/",
                                           "file": None,
                                           "tags": [], "kind": "rep",
                                           "done": False, "deferredTo": None, "pulledIn": False,
                                           "endComfort": None, "endNote": None, "nextReview": None})

    def test_primer_row_has_no_lcnumber_and_kind_primer(self):
        # The only kind/tag branch ("primer") not otherwise exercised by a row above. No
        # `[`/`**digit` for eb.SCHED_NUM, and the tag-stripped title starts with a letter,
        # not a digit, so the bare-number fallback also comes up empty — lcNumber and url
        # are both honestly null, same as a concept primer with no attached LC problem.
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        thu = result["days"][3]
        self.assertEqual(thu["items"][1], {
            "lcNumber": None, "title": "Two Pointers primer — before the phase opens Oct 5",
            "technique": "concept overview, no LC number", "startComfort": None,
            "startNote": None,
            "difficulty": None, "url": None,
            "file": None,
            "tags": ["primer"], "kind": "primer",
            "done": False, "deferredTo": None, "pulledIn": False,
            "endComfort": None, "endNote": None, "nextReview": None})

    def test_emphasis_before_glyph_does_not_blank_out_tags(self):
        # `~~🆕 39 ...~~` (whole row struck AHEAD of its tag glyph) is a real archived
        # shape, not hypothetical — a plain `cell.lstrip()` would see "~~" first and never
        # reach "🆕", yielding tags: [] and kind: "rep". done stays keyed off the raw "~~"
        # check either way, so pinning it True here also confirms the emphasis strip in
        # _leading_tags didn't leak into (or otherwise disturb) done detection.
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        thu = result["days"][3]
        self.assertEqual(thu["items"][2], {
            "lcNumber": 39, "title": "Combination Sum",
            "technique": "Backtracking", "startComfort": None,
            "startNote": None,
            "difficulty": None,
            "url": "https://leetcode.com/problems/combination-sum/",
            "file": None,
            "tags": ["new"], "kind": "new",
            "done": True, "deferredTo": None, "pulledIn": False,
            "endComfort": None, "endNote": None, "nextReview": None})

    def test_complexity_technique_wins_kind_over_the_probe_tag(self):
        # All three Sunday rows are 🎯-tagged AND carry Technique "Complexity" — kind must
        # come out "complexity" (the more specific fact), not "probe", and tags still
        # records the 🎯 glyph regardless of which kind it resolved to.
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        sun = result["days"][6]
        self.assertEqual(len(sun["items"]), 3)
        for item in sun["items"]:
            self.assertEqual(item["kind"], "complexity")
            self.assertEqual(item["tags"], ["probe"])
        self.assertEqual(sun["items"][0]["lcNumber"], 226)
        self.assertEqual(sun["items"][0]["title"], "Invert Binary Tree")
        self.assertEqual(sun["items"][0]["url"],
                          "https://leetcode.com/problems/invert-binary-tree/")

    def test_nc_only_row_loses_to_a_tracker_lc_join(self):
        # 200's row carries only its own [NC] link, but 200 HAS a tracker entry — the
        # tracker join (precedence 2) must win over that row's own NC link
        # (precedence 3): an NC url must never outrank a real LC one.
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        fri = result["days"][4]
        self.assertEqual(len(fri["items"]), 1)
        self.assertEqual(fri["items"][0], {
            "lcNumber": 200, "title": "Number of Islands",
            "technique": "BFS", "startComfort": "🟡",
            "startNote": None,
            "difficulty": "Medium",
            "url": "https://leetcode.com/problems/number-of-islands/",
            "file": None,
            "tags": [], "kind": "rep",
            "done": False, "deferredTo": None, "pulledIn": False,
            "endComfort": None, "endNote": None, "nextReview": None})

    def test_nc_only_row_with_no_tracker_entry_uses_nc_as_last_resort(self):
        # 269's row also carries only its own [NC] link, and 269 has NO tracker entry —
        # nothing outranks the NC link here, so it is used rather than leaving url null.
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        sat = result["days"][5]
        self.assertEqual(len(sat["items"]), 1)
        self.assertEqual(sat["items"][0], {
            "lcNumber": 269, "title": "Alien Dictionary",
            "technique": "Topological Sort", "startComfort": "🟡",
            "startNote": None,
            "difficulty": None,
            "url": "https://neetcode.io/problems/foreign-dictionary",
            "file": None,
            "tags": [], "kind": "rep",
            "done": False, "deferredTo": None, "pulledIn": False,
            "endComfort": None, "endNote": None, "nextReview": None})

    def test_day_with_no_block_has_no_items(self):
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS)
        wed = result["days"][2]
        self.assertEqual(wed["items"], [])

    def test_pinned_header_keeps_units_and_label(self):
        # The `· planned N units` pin sits between the units and the label; DAY_HEADER must
        # stop at the first `· ~N units` and DAY_LABEL must still read the label after the pin.
        pinned_fixture = (
            "## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n"
            "|---|:-:|:-:|:-:|---|\n"
            "| ▸ **Wed Oct 7** · ~3.8 units · planned 6.6 units — pinned label |  |  |  |  |\n"
            "| → [202 Happy Number](../../../dsa/leetcode/graphs/202_happy_number.py) · [LC]"
            "(https://leetcode.com/problems/happy-number/) | 🟢 s1 |  | 2026-10-09 | "
            "Cycle-detection |\n"
        )
        (Path(self._tmpdir.name) / "20261005_schedule.md").write_text(
            pinned_fixture, encoding="utf-8")
        result = gamify.parse_current_week_schedule(dt.date(2026, 10, 5), self.URLS)
        wed = result["days"][2]
        self.assertEqual(wed["units"], 3.8)
        self.assertEqual(wed["label"], "pinned label")

    def test_deferred_row_emits_date_and_its_new_day_copy_emits_null(self):
        # A `→` row: stays on its ORIGINAL day, not struck, with the day it moved TO in its
        # Next cell; the copy seated on the NEW day carries the same row with an empty Next
        # cell. The first fixture to cover a `→` row at all -- every other row in this
        # class's FIXTURE is a plain, struck, or intake row.
        deferred_fixture = (
            "## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n"
            "|---|:-:|:-:|:-:|---|\n"
            "| ▸ **Mon Sep 28** · 8.0 units — deferred-row test |  |  |  |  |\n"
            "| → [202 Happy Number](../../../dsa/leetcode/graphs/202_happy_number.py) · [LC]"
            "(https://leetcode.com/problems/happy-number/) | 🟢 s1 |  | 2026-10-01 | "
            "Cycle-detection |\n"
            "|  |  |  |  |  |\n"
            "| ▸ **Thu Oct 1** · 7.8 units — deferred-row test |  |  |  |  |\n"
            "| → [202 Happy Number](../../../dsa/leetcode/graphs/202_happy_number.py) · [LC]"
            "(https://leetcode.com/problems/happy-number/) | 🟢 s1 |  |  | Cycle-detection |\n"
        )
        sched_dir = Path(self._tmpdir.name)
        (sched_dir / "20260928_schedule.md").write_text(deferred_fixture, encoding="utf-8")
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 28), self.URLS)
        mon, thu = result["days"][0], result["days"][3]
        self.assertEqual(mon["items"][0]["deferredTo"], "2026-10-01")
        self.assertIsNone(thu["items"][0]["deferredTo"])

    def test_left_arrow_origin_row_exports_deferred_to(self):
        # A `←` row (moved to an EARLIER day) stays on its origin day unstruck with the new
        # date in Next, and exports it as deferredTo.
        left_fixture = (
            "## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n"
            "|---|:-:|:-:|:-:|---|\n"
            "| ▸ **Thu Oct 1** · 7.8 units — left-arrow test |  |  |  |  |\n"
            "| ← [202 Happy Number](../../../dsa/leetcode/graphs/202_happy_number.py) · [LC]"
            "(https://leetcode.com/problems/happy-number/) | 🟢 s1 |  | 2026-09-28 | "
            "Cycle-detection |\n"
        )
        (Path(self._tmpdir.name) / "20260928_schedule.md").write_text(
            left_fixture, encoding="utf-8")
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 28), self.URLS)
        item = result["days"][3]["items"][0]
        self.assertEqual(item["deferredTo"], "2026-09-28")
        self.assertEqual(item["title"], "Happy Number")

    def test_pulled_in_flag_over_arrow_and_struck_combinations(self):
        link = ("[202 Happy Number](../../../dsa/leetcode/graphs/202_happy_number.py) · "
                "[LC](https://leetcode.com/problems/happy-number/)")
        cases = [
            ("left-arrow struck copy", f"| ← ~~{link}~~ | 🟢 s1 | 🟢 |  | Cycle-detection |", True),
            ("left-arrow origin with Next", f"| ← {link} | 🟢 s1 |  | 2026-09-28 | Cycle-detection |", False),
            ("right-arrow struck copy", f"| → ~~{link}~~ | 🟢 s1 | 🟢 |  | Cycle-detection |", False),
            ("plain struck row", f"| ~~{link}~~ | 🟢 s1 | 🟢 |  | Cycle-detection |", False),
        ]
        for name, row, expected in cases:
            with self.subTest(name):
                fixture = (
                    "## Daily Schedule\n\n"
                    "| Problem | S | E | Next | Technique |\n"
                    "|---|:-:|:-:|:-:|---|\n"
                    "| ▸ **Thu Oct 1** · 7.8 units — pulled-in test |  |  |  |  |\n"
                    f"{row}\n"
                )
                (Path(self._tmpdir.name) / "20260928_schedule.md").write_text(
                    fixture, encoding="utf-8")
                result = gamify.parse_current_week_schedule(dt.date(2026, 9, 28), self.URLS)
                self.assertIs(result["days"][3]["items"][0]["pulledIn"], expected)

    def test_mock_rows_tags_kind_and_lcnumber_before_and_after_the_session(self):
        # The pre-session row names no problem (lcNumber null); the post-session row is
        # struck and linked, so it carries the base problem's number. Both are kind "mock"
        # via the 🎤 tag -- the Technique cell ("Mock") plays no part in the kind.
        mock_fixture = (
            "## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n"
            "|---|:-:|:-:|:-:|---|\n"
            "| ▸ **Sun Oct 4** · 3.0 units — mock before |  |  |  |  |\n"
            "| 🎤 Mock interview (Medium) | 🎤 |  |  | Mock |\n"
            "|  |  |  |  |  |\n"
            "| ▸ **Mon Oct 5** · 3.0 units — mock after |  |  |  |  |\n"
            "| 🎤 ~~[131 Palindrome Partitioning](../../../dsa/leetcode/backtracking/"
            "131_palindrome_partitioning.py) · [LC](https://leetcode.com/problems/"
            "palindrome-partitioning/)~~ | 🎤 | 🟡 | 2026-10-21 | Mock |\n"
        )
        sched_dir = Path(self._tmpdir.name)
        (sched_dir / "20261004_schedule.md").write_text(mock_fixture, encoding="utf-8")
        result = gamify.parse_current_week_schedule(dt.date(2026, 10, 4), self.URLS)
        before, after = result["days"][0]["items"][0], result["days"][1]["items"][0]
        cases = [(before, ["mock"], "mock", None, False),
                 (after, ["mock"], "mock", 131, True)]
        for item, tags, kind, lc_number, done in cases:
            with self.subTest(lcNumber=lc_number):
                self.assertEqual(item["tags"], tags)
                self.assertEqual(item["kind"], kind)
                self.assertEqual(item["lcNumber"], lc_number)
                self.assertEqual(item["done"], done)

    def test_no_current_schedule_file_is_none(self):
        result = gamify.parse_current_week_schedule(dt.date(2030, 1, 1), self.URLS)
        self.assertIsNone(result)

    def test_items_carry_solution_file_from_the_files_map(self):
        # `files` (links.solution_files()) joins each item's own solution path by lcNumber;
        # a number with no file — and a row with no number at all (the 🔤 primer) — is an
        # honest null, never a guessed path.
        files = {22: [gamify.REPO / "dsa/leetcode/backtracking/22_generate_parentheses.py"],
                 100: [gamify.REPO / "dsa/leetcode/trees/100_same_tree.py"]}
        result = gamify.parse_current_week_schedule(dt.date(2026, 9, 21), self.URLS, files)
        plain, done, untracked = result["days"][0]["items"]
        self.assertEqual(plain["file"], "dsa/leetcode/backtracking/22_generate_parentheses.py")
        self.assertEqual(done["file"], "dsa/leetcode/trees/100_same_tree.py")
        self.assertIsNone(untracked["file"])                  # 55: no file yet
        primer = result["days"][3]["items"][1]
        self.assertIsNone(primer["lcNumber"])
        self.assertIsNone(primer["file"])                     # no number → no lookup


class ParseScheduleHistoryTests(unittest.TestCase):
    """parse_schedule_history() over a two-file fixture folder: one CURRENT-layout week
    (a real `▸ **Mon ...** · N units` day header, one item) and one OLD-layout week (an
    older Morning/Evening Warmup + Slot table — no `▸` day header at all, so every day
    parses zero items). Only the current-layout week has any items, so it alone must be
    emitted; the old-layout week must be skipped rather than emitted as seven empty days.
    The old-layout stamp (June) sorts alphabetically/chronologically BEFORE the
    current-layout stamp (September), so the single surviving week is also pinned to have
    come through parse_schedule_history's own `sorted(..., key=...)` call rather than
    whatever order `_schedule_weeks()` yielded it in, even though a 2-week fixture where
    one week is always filtered out can't exercise a genuine multi-week reordering."""

    CURRENT_LAYOUT_FIXTURE = (
        "## Daily Schedule\n\n"
        "| Problem | S | E | Next | Technique |\n"
        "|---|:-:|:-:|:-:|---|\n"
        "| ▸ **Mon Sep 21** · 6.8 units — Test day |  |  |  |  |\n"
        "| [22 Generate Parentheses](../../../dsa/leetcode/backtracking/22_generate_parentheses.py)"
        " · [LC](https://leetcode.com/problems/generate-parentheses/) | 🔴 | | | Backtracking |\n"
    )

    # An older layout: a `## Daily Schedule` section exists, but its day cells have no
    # `▸ **Mon ...** · N units` header for eb.DAY_HEADER to match, so
    # _parse_schedule_day_full never sets `inside = True` and every day parses [] items.
    OLD_LAYOUT_FIXTURE = (
        "# Week of June 1-7, 2026\n\n"
        "## Daily Schedule\n\n"
        "| Day | Morning Warmup (15 min) | Evening Warmup (15 min) | Active Block (45 min) |\n"
        "|-----|------------------------|------------------------|-----------------------|\n"
        "| **Mon Jun 1** | 1. Two Sum | 2. Add Two Numbers | 3. Longest Substring |\n"
    )

    URLS = {22: "https://leetcode.com/problems/generate-parentheses/"}

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_schedules = eb.SCHEDULES
        self._orig_tracker = eb.TRACKER
        self._orig_gamify_tracker = gamify.TRACKER
        sched_dir = Path(self._tmpdir.name)
        (sched_dir / "20260921_schedule.md").write_text(self.CURRENT_LAYOUT_FIXTURE,
                                                         encoding="utf-8")
        (sched_dir / "20260601_schedule.md").write_text(self.OLD_LAYOUT_FIXTURE,
                                                         encoding="utf-8")
        eb.SCHEDULES = sched_dir
        # No tracker file — eb.parse_rows() fails soft to [] (gamify._difficulty_by_num()
        # catches the OSError), which is fine here: this test pins week SELECTION, not the
        # per-item difficulty join already pinned by ParseCurrentWeekScheduleTests.
        no_tracker = sched_dir / "dsa_progress.md"
        eb.TRACKER = no_tracker
        gamify.TRACKER = no_tracker

    def tearDown(self):
        eb.SCHEDULES = self._orig_schedules
        eb.TRACKER = self._orig_tracker
        gamify.TRACKER = self._orig_gamify_tracker
        self._tmpdir.cleanup()

    def test_only_current_layout_week_is_emitted_in_ascending_order(self):
        result = gamify.parse_schedule_history(self.URLS)
        self.assertEqual([w["weekOf"] for w in result], ["2026-09-21"])
        self.assertEqual(len(result[0]["days"]), 7)
        self.assertEqual(len(result[0]["days"][0]["items"]), 1)
        self.assertEqual(result[0]["days"][0]["items"][0]["lcNumber"], 22)


class BuildWorkloadTests(unittest.TestCase):
    """gamify.build_workload() — planned-vs-completed effort units per scheduled day,
    scanned across BOTH the live schedules folder and its archive/ subfolder, priced via
    effort_budget.price_day_items() (the extracted pricing core of price_schedule_day()).

    Fixture rows are plain dicts (effort_budget's own row shape, via the module-level
    _row() helper) rather than a tracker markdown file + eb.parse_rows() — build_workload()
    takes `rows` straight from its caller, so nothing here needs the tracker file at all.

    CFG is a minimal, self-contained effort_budget config: no attempt_decay or
    difficulty_demotion block, so price() reduces to base(comfort/streak) x
    difficulty(tier) with no decay/demotion — expected prices below are computed by hand
    against exactly these weights, not against cse.config.yml's (which is free to change).
    """

    CFG = {
        "comfort_units": {"🔴": 3.0, "🟡": 2.0, "🟢": 1.0},
        "difficulty": {"Easy": 0.7, "Medium": 1.0, "Hard": 1.5},
    }

    # Mon Aug 10 2026: a plain 🔴 Medium row (remaining, priced 3.0), a struck 🟡 Easy row
    # (done, priced 1.4), and a struck, untracked 🎯 Complexity row on 507 (priced 0.0 by
    # design) — the done/remaining split plus a zero-priced 🎯 complexity re-ask on 507.
    # Tue Aug 11 2026: a struck 🆕 row for a number ROWS tracks at 🟢 s1 (its POST-rep
    # state) — must price as Blank (🔴), never the tracker's green, and must NOT count as
    # guessed. Wed Aug 12 2026: a struck 🆕 row for a number absent from ROWS entirely —
    # untracked, so it still guesses Blank Medium and marks the day partial. Thu Aug 13
    # 2026: a number-less 🔤 primer row only — no problem number to price, so `partial`
    # must be true even though built/done both land at 0.0.
    LIVE_FIXTURE = (
        "## Daily Schedule\n\n"
        "| Problem | S | E | Next | Technique |\n"
        "|---|:-:|:-:|:-:|---|\n"
        "| ▸ **Mon Aug 10** · 5.0 units — Test build day |  |  |  |  |\n"
        "| [501 Widget One](../../../dsa/leetcode/arrays/501_widget_one.py)"
        " · [LC](https://leetcode.com/problems/widget-one/) | 🔴 | | | Arrays |\n"
        "| ~~[502 Widget Two](../../../dsa/leetcode/arrays/502_widget_two.py)~~"
        " · [LC](https://leetcode.com/problems/widget-two/) | 🟡 | | | Arrays |\n"
        "| 🎯 ~~[507 Widget Seven](../../../dsa/leetcode/arrays/507_widget_seven.py)~~"
        " · [LC](https://leetcode.com/problems/widget-seven/) — complexity re-ask (time)"
        " | 🎯 | | | Complexity |\n"
        "| |  |  |  |  |\n"
        "| ▸ **Tue Aug 11** · 3.0 units — New-row tracked day |  |  |  |  |\n"
        "| 🆕 ~~[505 Widget Five](../../../dsa/leetcode/arrays/505_widget_five.py)"
        " · [LC](https://leetcode.com/problems/widget-five/)~~ | 🆕 | | | Arrays |\n"
        "| |  |  |  |  |\n"
        "| ▸ **Wed Aug 12** · 3.0 units — New-row untracked day |  |  |  |  |\n"
        "| 🆕 ~~[506 Widget Six](../../../dsa/leetcode/arrays/506_widget_six.py)"
        " · [LC](https://leetcode.com/problems/widget-six/)~~ | 🆕 | | | Arrays |\n"
        "| |  |  |  |  |\n"
        "| ▸ **Thu Aug 13** · 3.0 units — Primer day |  |  |  |  |\n"
        "| 🔤 **Some Primer Topic** — no LC number | 🔤 | | | concept overview |\n"
        "| |  |  |  |  |\n"
    )

    # Mon Sep 14 2026: an approximate (`~4.0`) header with no priced rows — pins that
    # `planned` reads the approximate price, not None. Wed Sep 16 2026: a struck 🟢 s1
    # Hard row (done) plus a plain 🟡 Medium row (remaining) — built > done.
    ARCHIVE_FIXTURE = (
        "## Daily Schedule\n\n"
        "| Problem | S | E | Next | Technique |\n"
        "|---|:-:|:-:|:-:|---|\n"
        "| ▸ **Mon Sep 14** · ~4.0 units — Approx day |  |  |  |  |\n"
        "| |  |  |  |  |\n"
        "| ▸ **Wed Sep 16** · 6.0 units — Struck day |  |  |  |  |\n"
        "| ~~[503 Widget Three](../../../dsa/leetcode/arrays/503_widget_three.py)~~"
        " · [LC](https://leetcode.com/problems/widget-three/) | 🟢 s1 | | | Arrays |\n"
        "| [504 Widget Four](../../../dsa/leetcode/arrays/504_widget_four.py)"
        " · [LC](https://leetcode.com/problems/widget-four/) | 🟡 | | | Arrays |\n"
        "| |  |  |  |  |\n"
    )

    # An older one-row-per-day shape: no `▸ **Day**` header this parser recognizes, so
    # every day of this week is stated=None/items=[] and build_workload() must emit
    # nothing for it.
    OLD_FORMAT_FIXTURE = (
        "## Daily Schedule\n\n"
        "| Date | Problem | Comfort |\n"
        "|---|---|---|\n"
        "| 2026-06-01 | 1 Two Sum | 🟢 |\n"
    )

    ROWS = [
        _row(501, "🔴", 0, diff="Medium"),
        _row(502, "🟡", 0, diff="Easy"),
        _row(503, "🟢", 1, diff="Hard"),
        _row(504, "🟡", 0, diff="Medium"),
        _row(505, "🟢", 1, diff="Medium"),   # POST-rep state of the Tue Aug 11 🆕 row
    ]

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_schedules = eb.SCHEDULES
        sched_dir = Path(self._tmpdir.name)
        (sched_dir / "archive").mkdir()
        (sched_dir / "20260810_schedule.md").write_text(self.LIVE_FIXTURE, encoding="utf-8")
        (sched_dir / "20260601_schedule.md").write_text(self.OLD_FORMAT_FIXTURE, encoding="utf-8")
        (sched_dir / "archive" / "20260914_schedule.md").write_text(
            self.ARCHIVE_FIXTURE, encoding="utf-8")
        eb.SCHEDULES = sched_dir

    def tearDown(self):
        eb.SCHEDULES = self._orig_schedules
        self._tmpdir.cleanup()

    def test_entries_sorted_by_date_across_live_and_archive(self):
        workload = gamify.build_workload(self.ROWS, self.CFG)
        dates = [w["date"] for w in workload]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(dates, ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13",
                                 "2026-09-14", "2026-09-16"])

    def test_planned_reads_the_approximate_header(self):
        workload = gamify.build_workload(self.ROWS, self.CFG)
        by_date = {w["date"]: w for w in workload}
        self.assertEqual(by_date["2026-09-14"]["planned"], 4.0)

    def test_planned_reads_the_pinned_figure_when_present(self):
        pinned = (
            "## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n"
            "|---|:-:|:-:|:-:|---|\n"
            "| ▸ **Mon Oct 5** · ~3.0 units · planned 5.0 units — Pinned day |  |  |  |  |\n"
            "| ~~[501 Widget One](../../../dsa/leetcode/arrays/501_widget_one.py)~~"
            " · [LC](https://leetcode.com/problems/widget-one/) | 🔴 | | | Arrays |\n"
            "| → [504 Widget Four](../../../dsa/leetcode/arrays/504_widget_four.py)"
            " · [LC](https://leetcode.com/problems/widget-four/) | 🟡 | | 2026-10-08 | Arrays |\n"
        )
        (Path(eb.SCHEDULES) / "20261005_schedule.md").write_text(pinned, encoding="utf-8")
        by_date = {w["date"]: w for w in gamify.build_workload(self.ROWS, self.CFG)}
        self.assertEqual(by_date["2026-10-05"]["planned"], 5.0)
        self.assertAlmostEqual(by_date["2026-10-05"]["built"], 3.0)

    def test_done_is_the_struck_rows_priced_sum_and_built_covers_all_rows(self):
        workload = gamify.build_workload(self.ROWS, self.CFG)
        by_date = {w["date"]: w for w in workload}
        aug10 = by_date["2026-08-10"]
        self.assertAlmostEqual(aug10["done"], 1.4)     # 502: 🟡 Easy = 2.0 * 0.7
        self.assertAlmostEqual(aug10["built"], 4.4)    # + 501: 🔴 Medium = 3.0 * 1.0
        self.assertGreaterEqual(aug10["built"], aug10["done"])
        sep16 = by_date["2026-09-16"]
        self.assertAlmostEqual(sep16["done"], 1.5)     # 503: 🟢 s1 Hard = 1.0 * 1.5
        self.assertAlmostEqual(sep16["built"], 3.5)    # + 504: 🟡 Medium = 2.0 * 1.0
        self.assertGreaterEqual(sep16["built"], sep16["done"])

    def test_complexity_reask_row_prices_zero_and_is_not_partial(self):
        # The untracked 🎯 row on 507 must cost 0, leaving done at 502's 1.4 and built at
        # 501+502's 4.4. Without the fix, 507 falls to the untracked branch, is guessed
        # as a Blank Medium (3.0), and marks the day partial.
        workload = gamify.build_workload(self.ROWS, self.CFG)
        by_date = {w["date"]: w for w in workload}
        aug10 = by_date["2026-08-10"]
        self.assertAlmostEqual(aug10["done"], 1.4)
        self.assertAlmostEqual(aug10["built"], 4.4)
        self.assertFalse(aug10["partial"])

    def test_pre_era_headerless_file_contributes_no_entries(self):
        workload = gamify.build_workload(self.ROWS, self.CFG)
        self.assertFalse(any(w["date"].startswith("2026-06") for w in workload))
        self.assertEqual(len(workload), 6)

    def test_partial_true_for_a_numberless_primer_row(self):
        workload = gamify.build_workload(self.ROWS, self.CFG)
        by_date = {w["date"]: w for w in workload}
        self.assertTrue(by_date["2026-08-13"]["partial"])
        self.assertFalse(by_date["2026-08-10"]["partial"])

    def test_new_row_prices_as_blank_not_the_tracker_post_rep_comfort(self):
        # 505 is 🆕 in the schedule but ROWS carries its POST-rep 🟢 s1 Medium. Billing
        # from the tracker (units() = 1.0 * 1.0 = 1.0) would understate the day -- it must
        # price Blank instead: 🔴 Medium = 3.0 * 1.0 = 3.0.
        workload = gamify.build_workload(self.ROWS, self.CFG)
        by_date = {w["date"]: w for w in workload}
        aug11 = by_date["2026-08-11"]
        self.assertAlmostEqual(aug11["done"], 3.0)
        self.assertAlmostEqual(aug11["built"], 3.0)
        self.assertFalse(aug11["partial"])

    def test_new_row_untracked_guesses_blank_medium_and_marks_partial(self):
        # 506 is 🆕 and absent from ROWS entirely -- still guesses Blank Medium (3.0) like
        # any other untracked number, but a guessed difficulty must mark the day partial.
        workload = gamify.build_workload(self.ROWS, self.CFG)
        by_date = {w["date"]: w for w in workload}
        aug12 = by_date["2026-08-12"]
        self.assertAlmostEqual(aug12["done"], 3.0)
        self.assertAlmostEqual(aug12["built"], 3.0)
        self.assertTrue(aug12["partial"])

    def test_price_day_items_splits_done_from_remaining(self):
        path = eb.SCHEDULES / "20260810_schedule.md"
        items, stated = eb.parse_schedule_day(path, dt.date(2026, 8, 10))
        priced = eb.price_day_items(dt.date(2026, 8, 10), items, self.ROWS, self.CFG)
        self.assertEqual(stated, 5.0)
        self.assertAlmostEqual(priced["done"], 1.4)
        self.assertAlmostEqual(priced["remaining"], 3.0)
        self.assertAlmostEqual(priced["built"], 4.4)

    def test_price_day_items_bills_start_streak(self):
        """A 🟢 Start cell bills the streak it carries (parse_schedule_day() reads it
        from `sN`), not a flat s0 -- except a BARE 🟢 (start_streak=None), which has no
        recorded streak and must price as s0 while counting as `streakless`, so a day
        with bare 🟢 cells is flagged rather than silently priced as if s0 were known.
        `green_streak_units` makes s0 and s1 price differently, so a fix that dropped the
        streak on the floor (or crashed on `None`) could not pass this."""
        cfg = {
            "comfort_units": {"🔴": 3.0, "🟡": 2.0, "🟢": 1.0},
            "difficulty": {"Medium": 1.0},
            "green_streak_units": {0: 1.0, 1: 0.8, 2: 0.6},
        }
        tracked = [_row(601, "🟢", 2, diff="Medium")]
        day = dt.date(2026, 8, 10)
        base_item = {"num": "601", "is_complexity": False, "done": False, "text": "601"}
        cases = [
            ("known streak", {**base_item, "start": "🟢", "start_streak": 1,
                              "is_new": False},
             0.8, 0),
            ("bare 🟢 (no streak)", {**base_item, "start": "🟢", "start_streak": None,
                                     "is_new": False},
             1.0, 1),
            ("new intake", {**base_item, "start": None, "start_streak": 0,
                            "is_new": True},
             3.0, 0),
        ]
        for name, item, expected_cost, expected_streakless in cases:
            with self.subTest(name):
                priced = eb.price_day_items(day, [item], tracked, cfg)
                self.assertAlmostEqual(priced["built"], expected_cost)
                self.assertEqual(priced["streakless"], expected_streakless)

    def test_price_day_items_bills_deferred_row_in_neither_total(self):
        """A row deferred off a started day (`deferred_to` set) stays listed in
        `moved_lines` but bills in neither built nor remaining; built == done + remaining
        throughout."""
        cfg = {"comfort_units": {"🔴": 3.0, "🟡": 2.0}, "difficulty": {"Medium": 1.0}}
        tracked = [_row(n, "🟡", 0, diff="Medium") for n in (701, 702, 703)]
        day = dt.date(2026, 8, 10)
        base = {"is_complexity": False, "is_new": False, "start": "🟡",
                "start_streak": None, "deferred_to": None}
        items = [
            {**base, "num": "701", "done": False, "text": "701 deferred",
             "deferred_to": "2026-12-07"},
            {**base, "num": "702", "done": True, "text": "702 struck"},
            {**base, "num": "703", "done": False, "text": "703 open"},
        ]
        cases = [
            ("deferred only", items[:1], 0.0, 0.0, 1),
            ("done only", items[1:2], 2.0, 0.0, 0),
            ("open only", items[2:], 0.0, 2.0, 0),
            ("all three", items, 2.0, 2.0, 1),
        ]
        for name, rows, done, remaining, moved in cases:
            with self.subTest(name):
                priced = eb.price_day_items(day, rows, tracked, cfg)
                self.assertAlmostEqual(priced["done"], done)
                self.assertAlmostEqual(priced["remaining"], remaining)
                self.assertAlmostEqual(priced["built"], done + remaining)
                self.assertEqual(len(priced["moved_lines"]), moved)

    def test_parse_schedule_day_start_streak(self):
        """parse_schedule_day() reads a 🟢 Start cell's `sN` into start_streak, and
        returns None (not a silent 0) for a bare 🟢 with no streak written -- the
        signal price_day_items() needs to tell 'streak zero' from 'streak unknown'."""
        fixture = (
            "## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n"
            "|---|:-:|:-:|:-:|---|\n"
            "| ▸ **Mon Aug 10** · 2.0 units — Streak test day |  |  |  |  |\n"
            "| [601 Widget One](../../../dsa/leetcode/arrays/601_widget_one.py)"
            " · [LC](https://leetcode.com/problems/widget-one/) | 🟢 s1 | | | Arrays |\n"
            "| [602 Widget Two](../../../dsa/leetcode/arrays/602_widget_two.py)"
            " · [LC](https://leetcode.com/problems/widget-two/) | 🟢 | | | Arrays |\n"
            "| |  |  |  |  |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20260810_schedule.md"
            path.write_text(fixture, encoding="utf-8")
            items, _ = eb.parse_schedule_day(path, dt.date(2026, 8, 10))
        by_num = {it["num"]: it for it in items}
        self.assertEqual(by_num["601"]["start_streak"], 1)
        self.assertIsNone(by_num["602"]["start_streak"])

    def test_parse_schedule_day_bare_number_fallback(self):
        """A 🆕 or 🎯 row written as bare digits -- no `[`/`**` before the number, e.g.
        `🆕 79 Word Search` rather than `🆕 [79 Word Search](...)` -- still parses its
        number, via sched_row_number()'s fallback (SCHED_NUM alone found nothing for
        either tag, and both rows went UNPRICED). The close-out's cold-probe row
        (Technique `Complexity`, no digits anywhere in its cell) parses num=None -- it has
        no leading digits to fall back to either."""
        fixture = (
            "## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n"
            "|---|:-:|:-:|:-:|---|\n"
            "| ▸ **Mon Aug 10** · 2.0 units — Bare-number test day |  |  |  |  |\n"
            "| 🆕 79 Word Search · [LC](https://leetcode.com/problems/word-search/)"
            " | 🆕 | | | Backtracking |\n"
            "| 🎯 452 Minimum Number of Arrows to Burst Balloons | 🎯 | | | Probe |\n"
            "| 🎯 Two cold complexity probes on mature 🟢/🎓 problems (picked at the close-out)"
            " |  |  |  | Complexity |\n"
            "| |  |  |  |  |\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20260810_schedule.md"
            path.write_text(fixture, encoding="utf-8")
            items, _ = eb.parse_schedule_day(path, dt.date(2026, 8, 10))
        self.assertEqual(len(items), 3)
        new_row, probe_row, complexity_row = items
        self.assertEqual(new_row["num"], "79")
        self.assertTrue(new_row["is_new"])
        self.assertEqual(probe_row["num"], "452")
        self.assertTrue(probe_row["is_probe"])
        self.assertIsNone(complexity_row["num"])
        self.assertTrue(complexity_row["is_complexity"])

    def test_price_day_items_complexity_row_with_no_number_prices_zero_not_unpriced(self):
        """A Complexity-technique row with no problem number (the close-out's cold-probe
        row) must price 0 and be left OUT of `unpriced` -- the is_complexity check has to
        run before the missing-number check, or it lands there and is double-counted as a
        partial/guessed row it never was."""
        cfg = {"comfort_units": {"🔴": 3.0}, "difficulty": {"Medium": 1.0}}
        item = {"num": None, "start": None, "start_streak": 0, "is_new": False,
                "is_probe": False, "is_complexity": True, "done": False,
                "text": "Two cold complexity probes on mature problems"}
        priced = eb.price_day_items(dt.date(2026, 8, 10), [item], [], cfg)
        self.assertAlmostEqual(priced["built"], 0.0)
        self.assertEqual(priced["unpriced"], [])
        self.assertEqual(priced["guessed"], 0)

    def test_parse_sched_line_mock_row_has_no_number_and_is_mock_only(self):
        """The pre-session mock row (`🎤 Mock interview (Medium)`) names no problem: num
        is None, is_mock is True, and it is neither an intake (🆕) nor a probe (🎯) row."""
        row = eb.parse_sched_line("| 🎤 Mock interview (Medium) | 🎤 |  |  | Mock |")
        self.assertIsNone(row["num"])
        self.assertTrue(row["is_mock"])
        self.assertFalse(row["is_new"])
        self.assertFalse(row["is_probe"])

    def test_price_day_items_unnumbered_mock_row_bills_blank_at_its_hinted_difficulty(self):
        """A pre-session mock row prices Blank at the `(Easy|Medium|Hard)` hint, defaults to
        Medium with a `guessed` count when there is no hint, and never lands in `unpriced`
        (the is_mock branch must run before the missing-number check)."""
        cfg = {"comfort_units": {"🔴": 3.0},
               "difficulty": {"Easy": 0.5, "Medium": 1.0, "Hard": 1.3}}
        cases = [("(Medium)", 3.0, 0), ("(Hard)", 3.9, 0), ("", 3.0, 1)]
        for hint, expected_cost, expected_guessed in cases:
            with self.subTest(hint=hint):
                row = f"| 🎤 Mock interview {hint} | 🎤 |  |  | Mock |"
                item = eb.parse_sched_line(row)
                priced = eb.price_day_items(dt.date(2026, 8, 10), [item], [], cfg)
                self.assertAlmostEqual(priced["built"], expected_cost)
                self.assertEqual(priced["guessed"], expected_guessed)
                self.assertEqual(priced["unpriced"], [])


class UntrackedDifficultyLookupTests(unittest.TestCase):
    """price_day_items()'s difficulty lookup for a numbered row with no tracker review row
    (parse_rows() -- source (a), a caller-level check via the `rows` param) tries, in
    order: (b) any other tracker-file table row shaped `| Easy|Medium|Hard |
    [N. Title](url) | ...`, (c) roadmap.yml's `problems:` entries, (d)
    dsa/probes/README.md's queued-candidate rows, then falls back to Medium + guessed.
    One number lives in exactly each source (never live repo files) so each precedence
    step is pinned on its own."""

    CFG = {"comfort_units": {"🔴": 3.0}, "difficulty": {"Easy": 0.5, "Medium": 1.0, "Hard": 1.3}}

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self._orig_tracker, self._orig_roadmap, self._orig_probes = (
            eb.TRACKER, eb.ROADMAP_YML, eb.PROBE_POOL)
        # 802 lives ONLY here (source b) -- 803/804/805 are absent from this table.
        eb.TRACKER = tmp / "dsa_progress.md"
        eb.TRACKER.write_text(
            "| Medium | [802. Waiting Room Widget](https://leetcode.com/problems/x/) "
            "| `surplus>=1` | notes |\n", encoding="utf-8")
        # 803 lives ONLY here (source c).
        eb.ROADMAP_YML = tmp / "roadmap.yml"
        eb.ROADMAP_YML.write_text(
            'problems:\n  - {number: 803, title: "Widget", url: "https://x", '
            'difficulty: Easy}\n', encoding="utf-8")
        # 804 lives ONLY here (source d).
        eb.PROBE_POOL = tmp / "probes_readme.md"
        eb.PROBE_POOL.write_text(
            "| **804 Some Probe Widget** (Hard) | Technique | Trigger | Why |\n",
            encoding="utf-8")

    def tearDown(self):
        eb.TRACKER, eb.ROADMAP_YML, eb.PROBE_POOL = (
            self._orig_tracker, self._orig_roadmap, self._orig_probes)
        self._tmpdir.cleanup()

    @staticmethod
    def _intake_item(num):
        return {"num": num, "start": None, "start_streak": 0, "is_new": True,
                "is_probe": False, "is_complexity": False, "done": False, "text": num}

    def test_each_source_in_precedence_order_and_the_not_found_fallback(self):
        day = dt.date(2026, 8, 10)
        cases = [
            ("(a) the tracker's own review rows", "801",
             [_row(801, "🟢", 2, diff="Hard")], 3.9, 0),
            ("(b) another tracker-file table row", "802", [], 3.0, 0),
            ("(c) roadmap.yml", "803", [], 1.5, 0),
            ("(d) the probe pool", "804", [], 3.9, 0),
            ("not found -> Medium, guessed", "805", [], 3.0, 1),
        ]
        for name, num, rows, expected_cost, expected_guessed in cases:
            with self.subTest(name):
                priced = eb.price_day_items(day, [self._intake_item(num)], rows, self.CFG)
                self.assertAlmostEqual(priced["built"], expected_cost)
                self.assertEqual(priced["guessed"], expected_guessed)


class PriceScheduleDayHeaderCheckTests(unittest.TestCase):
    """price_schedule_day()'s header-vs-rows check must never print 'matches' while a row
    is unpriced or guessed, even when the totals happen to agree numerically (a day with a
    guessed row must not read 'header says X -- matches')."""

    CFG = {
        "comfort_units": {"🔴": 3.0, "🟡": 2.0},
        "difficulty": {"Medium": 1.0},
        "ceiling": 8.0,
        "max_rows_per_day": eb.load_config()["max_rows_per_day"],
    }

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self._orig_schedules = eb.SCHEDULES
        self._orig_tracker, self._orig_roadmap, self._orig_probes = (
            eb.TRACKER, eb.ROADMAP_YML, eb.PROBE_POOL)
        eb.SCHEDULES = tmp
        eb.TRACKER = tmp / "dsa_progress.md"
        eb.TRACKER.write_text("", encoding="utf-8")               # no rows anywhere
        eb.ROADMAP_YML = tmp / "roadmap.yml"
        eb.ROADMAP_YML.write_text("problems: []\n", encoding="utf-8")
        eb.PROBE_POOL = tmp / "probes_readme.md"
        eb.PROBE_POOL.write_text("", encoding="utf-8")
        # The header states exactly what the untracked row below guesses to (Blank
        # Medium = 3.0 under CFG) -- the numeric coincidence the fix must see through.
        (tmp / "20260810_schedule.md").write_text(
            "## Daily Schedule\n\n"
            "| Problem | S | E | Next | Technique |\n"
            "|---|:-:|:-:|:-:|---|\n"
            "| ▸ **Mon Aug 10** · 3.0 units — Coincidence test day |  |  |  |  |\n"
            "| [901 Unknown Widget](../../../dsa/leetcode/arrays/901_unknown_widget.py)"
            " · [LC](https://leetcode.com/problems/unknown-widget/) | 🟡 | | | Arrays |\n"
            "| |  |  |  |  |\n",
            encoding="utf-8")

    def tearDown(self):
        eb.SCHEDULES = self._orig_schedules
        eb.TRACKER, eb.ROADMAP_YML, eb.PROBE_POOL = (
            self._orig_tracker, self._orig_roadmap, self._orig_probes)
        self._tmpdir.cleanup()

    def test_matches_never_prints_while_a_row_is_guessed(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            eb.price_schedule_day(dt.date(2026, 8, 10), [], self.CFG)
        out = buf.getvalue()
        self.assertNotIn("matches", out)
        self.assertIn("CANNOT VERIFY", out)


class SolutionFilesTests(unittest.TestCase):
    """links.solution_files() — the map gamify reads: keyed by the file's leading number,
    non-numbered files skipped, roots walked in config order and sorted within each root
    (so a twin's first path is the same one links.find_file returns)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root_a = Path(self._tmp.name) / "a"
        root_b = Path(self._tmp.name) / "b"
        for rel in ("graphs/200_islands.py", "trees/100_same_tree.py", "trees/notes.py",
                    "z_late/1216_twin.py"):
            (root_a / rel).parent.mkdir(parents=True, exist_ok=True)
            (root_a / rel).write_text("", encoding="utf-8")
        (root_b / "dp").mkdir(parents=True)
        (root_b / "dp/1216_twin.py").write_text("", encoding="utf-8")
        self._patches = [
            mock.patch.object(links, "source_roots", return_value=[root_a, root_b]),
            # find_file's twin warning prints paths relative to the repo root; point it at
            # the temp tree so the fixture roots are inside it.
            mock.patch.object(links, "REPO_ROOT", Path(self._tmp.name)),
        ]
        for patch in self._patches:
            patch.start()
        self.root_a, self.root_b = root_a, root_b

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self._tmp.cleanup()

    def test_keys_by_leading_number_and_skips_unnumbered_files(self):
        files = links.solution_files()
        self.assertEqual(sorted(files), [100, 200, 1216])
        self.assertEqual(files[100], [self.root_a / "trees/100_same_tree.py"])

    def test_twin_order_is_config_root_order_and_matches_find_file(self):
        files = links.solution_files()
        self.assertEqual(files[1216], [self.root_a / "z_late/1216_twin.py",
                                       self.root_b / "dp/1216_twin.py"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(links.find_file("1216"), files[1216][0])


class SolutionPathTests(unittest.TestCase):
    """solution_path()/build_problems() — the `file` field: a repo-relative POSIX path from
    the links.solution_files() map, null when absent, and a twin (two files for one number,
    e.g. 1216) takes the FIRST sorted path with exactly one warning per number."""

    FILES = {763: [gamify.REPO / "dsa/leetcode/greedy/763_partition_labels.py"],
             1216: [gamify.REPO / "dsa/leetcode/1d_dynamic_programming/1216_valid_palindrome_iii.py",
                    gamify.REPO / "dsa/leetcode/backtracking/1216_valid_palindrome_iii.py"]}

    def test_path_is_repo_relative_posix(self):
        self.assertEqual(gamify.solution_path(763, self.FILES),
                         "dsa/leetcode/greedy/763_partition_labels.py")

    def test_missing_file_is_none_and_warns_nothing(self):
        warnings: list[str] = []
        self.assertIsNone(gamify.solution_path(999, self.FILES, warnings))
        self.assertEqual(warnings, [])

    def test_twin_takes_first_and_warns_once(self):
        warnings: list[str] = []
        self.assertEqual(gamify.solution_path(1216, self.FILES, warnings),
                         "dsa/leetcode/1d_dynamic_programming/1216_valid_palindrome_iii.py")
        self.assertEqual(len(warnings), 1)
        self.assertIn("1216", warnings[0])
        self.assertIn("2 solution files", warnings[0])

    def test_build_problems_emits_file_and_one_twin_warning_per_number(self):
        rows = [_row(763, "🟡", 0, reps="2026-09-19"),
                _row(1216, "🟡", 0, reps="2026-09-19"),      # twin, two tracker rows
                _row(1216, "🔴", 0, reps="2026-09-19"),
                _row(999, "🟢", 1, reps="2026-09-19")]        # no file
        warnings: list[str] = []
        problems = gamify.build_problems(rows, {}, {}, {}, self.FILES, warnings)
        by_num = {}
        for p in problems:
            by_num.setdefault(p["lcNumber"], []).append(p["file"])
        self.assertEqual(by_num[763], ["dsa/leetcode/greedy/763_partition_labels.py"])
        self.assertEqual(by_num[1216],
                         ["dsa/leetcode/1d_dynamic_programming/1216_valid_palindrome_iii.py"] * 2)
        self.assertEqual(by_num[999], [None])
        self.assertEqual(len(warnings), 1)                    # once per NUMBER, not per row

    def test_build_problems_without_a_files_map_is_all_null(self):
        problems = gamify.build_problems([_row(763, "🟡", 0, reps="2026-09-19")], {}, {}, {})
        self.assertIsNone(problems[0]["file"])


class ScheduleItemOutcomeTests(unittest.TestCase):
    """_schedule_item_outcome(end_cell, next_cell) — pure, no file IO. Pins the real E-cell
    vocabulary (s0/s1/s2/prov/dropped), and the glyph-less cells (unrated/—/✅ delivered/
    empty) that must yield three nulls."""

    def test_glyph_with_streak_note_and_a_full_next_date(self):
        self.assertEqual(gamify._schedule_item_outcome("🟢 s2", "2026-10-21"),
                          {"endComfort": "🟢", "endNote": "s2", "nextReview": "2026-10-21"})

    def test_glyph_with_prov_note_and_no_next_date(self):
        self.assertEqual(gamify._schedule_item_outcome("🟢 prov", ""),
                          {"endComfort": "🟢", "endNote": "prov", "nextReview": None})

    def test_bare_glyph_with_a_next_date(self):
        self.assertEqual(gamify._schedule_item_outcome("🟡", "2026-09-30"),
                          {"endComfort": "🟡", "endNote": None, "nextReview": "2026-09-30"})

    def test_arrow_prefixed_note_is_stripped_to_dropped(self):
        self.assertEqual(gamify._schedule_item_outcome("🟡→dropped", ""),
                          {"endComfort": "🟡", "endNote": "dropped", "nextReview": None})

    def test_unrated_has_no_glyph_so_everything_is_null(self):
        self.assertEqual(gamify._schedule_item_outcome("unrated", ""),
                          {"endComfort": None, "endNote": None, "nextReview": None})

    def test_em_dash_has_no_glyph_so_everything_is_null(self):
        self.assertEqual(gamify._schedule_item_outcome("—", ""),
                          {"endComfort": None, "endNote": None, "nextReview": None})

    def test_checkmark_delivered_has_no_glyph_so_everything_is_null(self):
        self.assertEqual(gamify._schedule_item_outcome("✅ delivered", ""),
                          {"endComfort": None, "endNote": None, "nextReview": None})

    def test_both_cells_empty_is_all_null(self):
        self.assertEqual(gamify._schedule_item_outcome("", ""),
                          {"endComfort": None, "endNote": None, "nextReview": None})

    def test_free_form_next_cell_does_not_full_match_a_date(self):
        self.assertEqual(gamify._schedule_item_outcome("🟢", "Sep 14 phase"),
                          {"endComfort": "🟢", "endNote": None, "nextReview": None})

    def test_note_whitespace_collapsed_and_lowercased(self):
        self.assertEqual(gamify._schedule_item_outcome(" 🟢  S1 ", ""),
                          {"endComfort": "🟢", "endNote": "s1", "nextReview": None})


class DeriveEndNoteTests(unittest.TestCase):
    """derive_end_note(start_comfort, start_note, end_comfort, end_note) — pure."""

    def test_rows(self):
        cases = [
            ("🟢", "s0", "🟢", "prov", "prov"),   # explicit note wins
            ("🔴", None, "🟢", None, "s0"),
            ("🟡", None, "🟢", None, "s0"),
            ("🟢", "s0", "🟢", None, "s1"),
            ("🟢", "prov", "🟢", None, "s1"),
            ("🟢", "s1", "🟢", None, "s2"),
            ("🟢", "s2", "🟢", None, "s2"),
            ("🟢", None, "🟢", None, None),
            ("🟢", "s1", "🎓", None, None),
            ("🟢", "s1", None, None, None),
        ]
        for start, start_note, end, end_note, expected in cases:
            with self.subTest(start=start, start_note=start_note, end=end, end_note=end_note):
                self.assertEqual(
                    gamify.derive_end_note(start, start_note, end, end_note), expected)


class CellNoteTests(unittest.TestCase):
    """_cell_note(cell, glyph) — the note after a comfort glyph in an S or E cell."""

    def test_note_after_glyph(self):
        cases = [
            ("🟢 s0", "🟢", "s0"),
            ("🟢", "🟢", None),
            ("→ 🟢  S1 ", "🟢", "s1"),
            (None, None, None),
            ("🟢 " + "x" * 20, "🟢", "x" * 16),
        ]
        for cell, glyph, expected in cases:
            with self.subTest(cell=cell):
                self.assertEqual(gamify._cell_note(cell, glyph), expected)


class ScanWeekEndGlyphFallbackTests(unittest.TestCase):
    """_scan_week still falls back to the Start glyph when the End cell is empty — guards
    the _end_glyph refactor. Only the board slice (_schedule_item_outcome, above) refuses
    that fallback; the comfort timeline still wants SOME glyph recorded per rep."""

    def test_falls_back_to_start_glyph_when_end_cell_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20260921_schedule.md"
            path.write_text(
                "## Daily Schedule\n\n"
                "| Problem | S | E | Next | Technique |\n"
                "|---|:-:|:-:|:-:|---|\n"
                "| ▸ **Mon Sep 21** · 6.8 units — Test day |  |  |  |  |\n"
                "| [22 Generate Parentheses](../../../dsa/leetcode/backtracking/22_x.py)"
                " | 🔴 | | | Backtracking |\n",
                encoding="utf-8",
            )
            index: dict[str, dict[int, str]] = {}
            gamify._scan_week(path, dt.date(2026, 9, 21), index)
            self.assertEqual(index, {"2026-09-21": {22: "🔴"}})

    def test_end_glyph_survives_a_start_fallback_row_in_either_order(self):
        # 332 on one day: a struck row with End 🔴 and a `→` moved row with Start 🟡 and
        # no End. The End-sourced glyph wins whichever row comes last.
        struck = ("| ~~[332 Reconstruct Itinerary](../../../dsa/leetcode/graphs/332_x.py)~~"
                  " | 🟡 | 🔴 | | Graphs |\n")
        moved = ("| → [332 Reconstruct Itinerary](../../../dsa/leetcode/graphs/332_x.py)"
                 " | 🟡 | | | Graphs |\n")
        for label, rows in (("struck first", struck + moved), ("moved first", moved + struck)):
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "20260824_schedule.md"
                path.write_text(
                    "## Daily Schedule\n\n"
                    "| Problem | S | E | Next | Technique |\n"
                    "|---|:-:|:-:|:-:|---|\n"
                    "| ▸ **Sat Aug 29** · 6.8 units — Test day |  |  |  |  |\n" + rows,
                    encoding="utf-8",
                )
                index: dict[str, dict[int, str]] = {}
                gamify._scan_week(path, dt.date(2026, 8, 24), index)
                self.assertEqual(index, {"2026-08-29": {332: "🔴"}})


class ParseProbesTests(unittest.TestCase):
    """parse_probes() against a small fixture Probe log table, not the live repo file —
    pins the Problem-cell number/title split and (the tricky case) a MULTI-glyph Result
    cell (`🔴 → 🟡 (re-rep Sep 16)`), which must score the COLD call (the first glyph), not
    the eventual conversion."""

    FIXTURE = (
        "## 📒 Probe log — the tally\n\n"
        "Some prose above the table.\n\n"
        "| # | Date | Problem | Technique | Result | Tracker row? |\n"
        "|---|---|---|---|---|---|\n"
        "| 1 | 2026-08-10 | 977 Squares of a Sorted Array | Two Pointers | 🟢 | — |\n"
        "| 2 | 2026-08-11 | 202 Happy Number | Cycle Detection (iterated seq) | 🟡 | ✅ earned |\n"
        "| 3 | 2026-09-11 | 547 Number of Provinces | Union-Find (connected components) "
        "| 🔴 → 🟡 (re-rep Sep 16) | earned Sep 11 → **dropped Sep 16** |\n\n"
        "**Tally (3 run):** some prose that must not be parsed as a row.\n\n"
        "## 🎣 Queued probe candidates\n\n"
        "unrelated section\n"
    )

    def setUp(self):
        self._orig_probes = gamify.PROBES_README
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(self.FIXTURE)
        tmp.close()
        gamify.PROBES_README = Path(tmp.name)

    def tearDown(self):
        gamify.PROBES_README.unlink(missing_ok=True)
        gamify.PROBES_README = self._orig_probes

    # Joined by lcNumber into the items below — only 977 has a URL, pinning the honest-null
    # case for a probe number the tracker doesn't carry a link for.
    URLS = {977: "https://leetcode.com/problems/squares-of-a-sorted-array/"}

    def test_problem_cell_splits_into_number_and_title(self):
        probes = gamify.parse_probes(self.URLS)
        first = probes["items"][0]
        self.assertEqual(first["lcNumber"], 977)
        self.assertEqual(first["title"], "Squares of a Sorted Array")
        self.assertEqual(first["technique"], "Two Pointers")
        self.assertEqual(first["date"], "2026-08-10")
        self.assertEqual(first["url"], "https://leetcode.com/problems/squares-of-a-sorted-array/")

    def test_multi_glyph_result_scores_the_cold_call_not_the_conversion(self):
        probes = gamify.parse_probes(self.URLS)
        converted = probes["items"][2]
        self.assertEqual(converted["lcNumber"], 547)
        self.assertEqual(converted["result"], "🔴")  # NOT 🟡 — that's the later conversion
        self.assertIsNone(converted["url"])  # absent from URLS — honest null, not a guess

    def test_difficulty_readme_cell_first_then_tracker_then_none(self):
        # Old 6-column layout (self.FIXTURE): 977 in the map, 202 not in it, a row with no number.
        gamify.PROBES_README.write_text(
            self.FIXTURE.replace(
                "| 2026-09-11 | 547 Number of Provinces",
                "| 2026-09-11 | Number of Provinces"),
            encoding="utf-8")
        probes = gamify.parse_probes(self.URLS, {977: "Easy"})
        self.assertEqual(
            [it["difficulty"] for it in probes["items"]], ["Easy", None, None])

        # Difficulty column found by header name: cell wins over tracker, blank falls back.
        gamify.PROBES_README.write_text(
            "## 📒 Probe log\n\n"
            "| # | Date | Problem | Technique | Result | Tracker row? | Difficulty |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 1 | 2026-08-10 | 977 A | T | 🟢 | — | Medium |\n"
            "| 2 | 2026-08-11 | 202 B | T | 🟡 | — |  |\n"
            "| 3 | 2026-08-12 | 69 C | T | 🟢 | — |  |\n",
            encoding="utf-8")
        probes = gamify.parse_probes(self.URLS, {977: "Easy", 202: "Hard"})
        self.assertEqual(
            [it["difficulty"] for it in probes["items"]], ["Medium", "Hard", None])

    def test_file_probe_dir_wins_then_tracker_then_none(self):
        # REPO -> a temp tree so both file kinds resolve repo-relative.
        root = Path(tempfile.mkdtemp())
        probes_dir = root / "dsa" / "probes"
        probes_dir.mkdir(parents=True)
        (probes_dir / "977_squares.py").write_text("", encoding="utf-8")
        tracker_file = root / "dsa" / "leetcode" / "a" / "202_happy.py"
        orig_repo, orig_readme = gamify.REPO, gamify.PROBES_README
        gamify.REPO = root
        gamify.PROBES_README = probes_dir / "README.md"
        try:
            gamify.PROBES_README.write_text(self.FIXTURE, encoding="utf-8")
            probes = gamify.parse_probes(self.URLS, None, {977: [tracker_file], 202: [tracker_file]})
        finally:
            gamify.REPO, gamify.PROBES_README = orig_repo, orig_readme
        self.assertEqual(
            [it["file"] for it in probes["items"]],
            ["dsa/probes/977_squares.py", "dsa/leetcode/a/202_happy.py", None])

    def test_total_and_clean_rate(self):
        probes = gamify.parse_probes(self.URLS)
        self.assertEqual(probes["total"], 3)
        # 1 of 3 clean (977 is 🟢; 202 is 🟡; 547's COLD call is 🔴).
        self.assertAlmostEqual(probes["cleanRate"], 1 / 3)

    def test_prose_and_next_section_are_not_parsed_as_rows(self):
        probes = gamify.parse_probes(self.URLS)
        self.assertEqual(len(probes["items"]), 3)

    def test_missing_file_is_none(self):
        gamify.PROBES_README = Path(tempfile.gettempdir()) / "no-such-probes-file.md"
        self.assertIsNone(gamify.parse_probes(self.URLS))

    def test_no_table_in_file_is_none(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write("# Nothing here\n\nJust prose, no Probe log heading at all.\n")
        tmp.close()
        gamify.PROBES_README = Path(tmp.name)
        self.assertIsNone(gamify.parse_probes(self.URLS))
        gamify.PROBES_README.unlink(missing_ok=True)

    # An empty PROBE-log table — the section and its header row exist, but no data rows
    # yet — is a fresh adopter's first-run state, not a defect: it must NOT collapse to
    # the same None the missing-file/missing-section cases above return.
    EMPTY_TABLE_FIXTURE = (
        "## 📒 Probe log — the tally\n\n"
        "| # | Date | Problem | Technique | Result | Tracker row? |\n"
        "|---|---|---|---|---|---|\n"
    )

    def test_present_but_empty_table_is_zero_payload_not_none(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(self.EMPTY_TABLE_FIXTURE)
        tmp.close()
        gamify.PROBES_README = Path(tmp.name)
        self.assertEqual(gamify.parse_probes(self.URLS),
                         {"total": 0, "cleanRate": 0.0, "items": []})
        gamify.PROBES_README.unlink(missing_ok=True)

    def test_present_but_empty_table_emits_no_warning(self):
        # Runs the real build_payload() over a fixture repo whose only file is the empty
        # Probe log, so this exercises the actual warnings-list wiring in
        # main()/build_payload, not just parse_probes().
        with _fixture_repo({PROBES_FILE: self.EMPTY_TABLE_FIXTURE}):
            _payload, warnings = gamify.build_payload(dt.date(2026, 9, 20))
        self.assertFalse(any("Probe log" in w for w in warnings))

    def test_missing_probe_section_still_warns_from_build_payload(self):
        # The genuinely-wrong case (section header missing entirely) must still warn —
        # confirms the fix didn't silence a real problem along with the false-positive one.
        with _fixture_repo({PROBES_FILE: "# Nothing here\n\nJust prose, no Probe log heading at all.\n"}):
            _payload, warnings = gamify.build_payload(dt.date(2026, 9, 20))
        self.assertTrue(any("Probe log" in w for w in warnings))


class SummaryOfTests(unittest.TestCase):
    def _payload(self):
        return {
            "schemaVersion": 1,
            "generatedAt": "2026-09-20",
            "totals": {"problems": 1, "solutions": 1, "reps": 2},
            "pipeline": {"blank": 0, "shaky": 0,
                         "clean": {"s0": 0, "s1": 0, "s2plus": 0, "total": 0},
                         "graduated": 1, "retired": 1},
            "difficulty": {"Easy": 0, "Medium": 1, "Hard": 0},
            "streak": {"current": 3, "longest": 5, "lastStudyDay": "2026-09-20",
                       "studyDays": 10, "freezes": 2, "freezesLeft": 2,
                       "freezeMax": 2, "frozenDays": []},
            "coverage": {"total": 56, "started": 40, "noGreen": 2, "thin": 3, "variantGaps": 1},
            "onSchedule": {"totalActive": 10, "dueToday": 1, "overdue": 2},
            "trophyCase": {
                "graduated": [{"lcNumber": 206, "title": "Reverse Linked List",
                               "difficulty": "Easy", "url": "https://x", "comfort": "🎓",
                               "level": 3, "streak": 3, "nextReview": "2026-10-01",
                               "repDates": ["2026-01-01"], "timeline": [{"date": "2026-01-01"}]}],
                "retired": [{"lcNumber": 704, "title": "Binary Search",
                             "retiredOn": "2026-08-01"}],
            },
            "badges": [{"id": "first-graduate", "title": "First Graduation", "earned": True}],
            "techniques": [
                {"name": "Bellman-Ford", "family": "advanced_graphs", "tier": "core",
                 "started": True, "minProblems": 3, "problemCount": 1, "problems": [787],
                 "bestComfort": "🟢", "hasGreen": True, "thin": True, "hasVariantGap": False,
                 "planned": [{"lcNumber": 9001, "title": "Single Source Shortest Path,"
                              " Negative Weights", "url": "https://x", "difficulty": "Easy",
                              "trigger": "surplus>=1"}]},
                {"name": "Knapsack", "family": "dynamic_programming", "tier": "dp",
                 "started": False, "minProblems": 3, "problemCount": 0, "problems": [],
                 "bestComfort": None, "hasGreen": False, "thin": False, "hasVariantGap": False,
                 "planned": []},
            ],
            # One date far outside the summary's rolling window (well over
            # SUMMARY_STUDY_DAYS_WINDOW days before generatedAt) plus two recent ones —
            # exercises the cap in summary_of() without touching the lifetime count, which
            # comes from streak.studyDays (10 above), never from len(this list).
            "studyDays": ["2025-01-01", "2026-09-19", "2026-09-20"],
            "schedule": {"weekOf": "2026-09-21", "days": [
                {"date": "2026-09-21", "weekday": "Monday", "label": "Test day", "units": 6.8,
                 "items": [{"lcNumber": 22, "title": "Generate Parentheses",
                           "technique": "Backtracking", "startComfort": "🔴",
                           "startNote": None,
                           "difficulty": "Medium", "done": False}]},
            ]},
            # Mirrors studyDays just above: one date far outside the summary's rolling
            # window plus two recent ones, so the cap can be pinned the same way.
            "workload": [
                {"date": "2025-01-01", "planned": 4.0, "done": 4.0, "built": 4.0, "partial": False},
                {"date": "2026-09-19", "planned": 5.0, "done": 5.0, "built": 5.0, "partial": False},
                {"date": "2026-09-20", "planned": 6.0, "done": 3.0, "built": 6.0, "partial": True},
            ],
            "effortCeiling": 8.0,
            "effortFloor": 3.0,
            "probes": {"total": 3, "cleanRate": 1 / 3, "items": [
                {"date": "2026-08-10", "lcNumber": 977, "title": "Squares of a Sorted Array",
                 "technique": "Two Pointers", "result": "🟢"},
            ]},
            "problems": [{"lcNumber": 206, "title": "Reverse Linked List", "comfort": "🎓"}],
        }

    def test_no_problems_key(self):
        summary = gamify.summary_of(self._payload())
        self.assertNotIn("problems", summary)

    def test_keeps_core_aggregates(self):
        summary = gamify.summary_of(self._payload())
        for key in ("streak", "pipeline", "badges", "coverage", "totals",
                    "onSchedule", "difficulty", "schemaVersion", "generatedAt",
                    "techniques", "studyDays", "schedule", "workload", "effortCeiling",
                    "effortFloor", "probes"):
            self.assertIn(key, summary)
        self.assertEqual(summary["streak"]["current"], 3)
        self.assertEqual(summary["badges"][0]["id"], "first-graduate")

    def test_techniques_pass_through_unchanged_incl_tier_started_and_min_problems(self):
        summary = gamify.summary_of(self._payload())
        by_name = {t["name"]: t for t in summary["techniques"]}
        self.assertEqual(by_name["Bellman-Ford"]["tier"], "core")
        self.assertTrue(by_name["Bellman-Ford"]["started"])
        self.assertEqual(by_name["Bellman-Ford"]["minProblems"], 3)
        self.assertEqual(by_name["Knapsack"]["tier"], "dp")
        self.assertFalse(by_name["Knapsack"]["started"])
        self.assertEqual(by_name["Knapsack"]["minProblems"], 3)

    def test_planned_survives_into_the_summary(self):
        summary = gamify.summary_of(self._payload())
        by_name = {t["name"]: t for t in summary["techniques"]}
        self.assertEqual(by_name["Bellman-Ford"]["planned"][0]["lcNumber"], 9001)
        self.assertEqual(by_name["Knapsack"]["planned"], [])

    def test_probes_pass_through_unchanged(self):
        summary = gamify.summary_of(self._payload())
        self.assertEqual(summary["probes"], self._payload()["probes"])
        self.assertAlmostEqual(summary["probes"]["cleanRate"], 1 / 3)

    def test_probes_none_when_no_probe_log(self):
        payload = self._payload()
        payload["probes"] = None
        summary = gamify.summary_of(payload)
        self.assertIsNone(summary["probes"])

    def test_schedule_passes_through_unchanged_and_no_problems_leak(self):
        summary = gamify.summary_of(self._payload())
        self.assertEqual(summary["schedule"], self._payload()["schedule"])
        self.assertNotIn("problems", summary)

    def test_effort_ceiling_and_floor_pass_through(self):
        summary = gamify.summary_of(self._payload())
        self.assertEqual(summary["effortCeiling"], 8.0)
        self.assertEqual(summary["effortFloor"], 3.0)

    def test_schedule_none_when_no_current_week_file(self):
        payload = self._payload()
        payload["schedule"] = None
        summary = gamify.summary_of(payload)
        self.assertIsNone(summary["schedule"])

    def test_study_days_capped_to_the_rolling_window(self):
        # 2025-01-01 is far more than SUMMARY_STUDY_DAYS_WINDOW days before generatedAt
        # (2026-09-20) and must be dropped; the two recent dates stay.
        summary = gamify.summary_of(self._payload())
        self.assertEqual(summary["studyDays"], ["2026-09-19", "2026-09-20"])

    def test_workload_capped_to_the_same_rolling_window_as_study_days(self):
        # Same cutoff, same shape of fixture as studyDays above: 2025-01-01 drops,
        # the two recent entries stay.
        summary = gamify.summary_of(self._payload())
        self.assertEqual([w["date"] for w in summary["workload"]],
                         ["2026-09-19", "2026-09-20"])

    def test_study_days_cap_does_not_touch_the_lifetime_count(self):
        # The lifetime total lives in streak.studyDays/streak.longest, untouched by the cap
        # on the summary's date LIST.
        summary = gamify.summary_of(self._payload())
        self.assertEqual(summary["streak"]["studyDays"], 10)
        self.assertEqual(summary["streak"]["longest"], 5)

    def test_trophy_case_graduated_is_compact(self):
        summary = gamify.summary_of(self._payload())
        graduated = summary["trophyCase"]["graduated"]
        self.assertEqual(len(graduated), 1)
        self.assertEqual(graduated[0], {"lcNumber": 206, "title": "Reverse Linked List",
                                        "difficulty": "Easy"})
        self.assertNotIn("timeline", graduated[0])
        self.assertNotIn("repDates", graduated[0])

    def test_trophy_case_retired_passes_through(self):
        summary = gamify.summary_of(self._payload())
        self.assertEqual(summary["trophyCase"]["retired"],
                         [{"lcNumber": 704, "title": "Binary Search", "retiredOn": "2026-08-01"}])


class PayloadTests(unittest.TestCase):
    """build_payload() over fixture repos (never the checkout's own files): one table row
    per repo state. Both rows must yield a schema-valid payload and an empty schedule
    history; the fresh-adopter row additionally pins that a missing roadmap, tracker,
    coverage report and schedule history degrade to empty arrays / a null schedule rather
    than raising, and the populated row pins that techniques.yml's authored `builds_on`
    and the tracker's graduations actually reach the payload."""

    TODAY = dt.date(2026, 9, 20)
    REQUIRED_KEYS = ("schemaVersion", "generatedAt", "totals", "pipeline", "streak",
                     "problems", "badges")

    CASES = [
        ("fresh adopter: no roadmap, tracker, coverage or schedules",
         {}, 0, {}, {}),
        ("populated: builds_on and graduations reach the payload",
         POPULATED_REPO, 1, {"Base": [], "Derived": ["Base"]}, {"Base": 1, "Derived": 0}),
    ]

    def test_build_payload_over_fixture_repos(self):
        for name, files, problem_count, builds_on, graduated in self.CASES:
            with self.subTest(name), _fixture_repo(files):
                payload, _warnings = gamify.build_payload(self.TODAY)
                history = gamify.build_schedule_history(self.TODAY)
                for key in self.REQUIRED_KEYS:
                    self.assertIn(key, payload)
                self.assertEqual(payload["schemaVersion"], gamify.SCHEMA_VERSION)
                self.assertEqual(payload["generatedAt"], "2026-09-20")  # the injected today
                self.assertEqual(len(payload["problems"]), problem_count)
                self.assertEqual(payload["workload"], [])
                self.assertIsNone(payload["schedule"])
                self.assertEqual(history["weeks"], [])
                self.assertEqual({t["name"]: t["buildsOn"] for t in payload["techniques"]},
                                 builds_on)
                self.assertEqual({t["name"]: t["graduatedCount"] for t in payload["techniques"]},
                                 graduated)
                self.assertEqual(contract_schema.validate(payload, gamify.SCHEMA), [])


class MainStdoutCleanTests(unittest.TestCase):
    """main()'s session-date resolution must never leak session_date.resolve_datetime's
    announcement onto stdout: --stdout must still emit parseable JSON and --banner must
    still emit exactly one line. The real detect_session_date heuristic depends on the
    wall clock and git state, so the announcement is FORCED here via a monkeypatched
    resolve_datetime rather than relying on hitting the real heuristic by chance."""

    @staticmethod
    def _announcing_resolve_datetime(explicit=None, *, now=None, announce=True):
        if announce:
            print("Using session date 2026-09-20 (forced for test). "
                  "Override with --date if that's wrong.")
        return dt.datetime(2026, 9, 20)

    def _run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with _fixture_repo(), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(gamify.session_date, "resolve_datetime",
                               self._announcing_resolve_datetime), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            gamify.main()
        return out.getvalue(), err.getvalue()

    def test_stdout_mode_stays_parseable_json_even_when_session_date_announces(self):
        out, err = self._run_main(["gamify.py", "--stdout"])
        json.loads(out)  # raises if the announcement leaked into stdout
        self.assertIn("Using session date", err)

    def test_banner_mode_emits_exactly_one_line_even_when_session_date_announces(self):
        out, err = self._run_main(["gamify.py", "--banner"])
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("Using session date", err)


class MainDateFlagTests(unittest.TestCase):
    """--date is the flag name main() actually documents and session_date.resolve_datetime
    itself references in its announcement ("Override with --date if that's wrong") —
    --today is kept only as a hidden alias so an existing caller of the old name still
    works. Both must reach resolve_datetime's `explicit` param identically."""

    def _captured_explicit(self, argv):
        captured: dict = {}

        def fake_resolve(explicit=None, *, now=None, announce=True):
            captured["explicit"] = explicit
            return dt.datetime(2026, 9, 20)

        out, err = io.StringIO(), io.StringIO()
        with _fixture_repo(), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(gamify.session_date, "resolve_datetime", fake_resolve), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            gamify.main()
        return captured["explicit"]

    def test_date_flag_reaches_resolve_datetime(self):
        explicit = self._captured_explicit(["gamify.py", "--stdout", "--date", "2026-09-20"])
        self.assertEqual(explicit, "2026-09-20")

    def test_today_alias_resolves_to_the_same_value_as_date(self):
        explicit = self._captured_explicit(["gamify.py", "--stdout", "--today", "2026-09-20"])
        self.assertEqual(explicit, "2026-09-20")


class SchemaValidationTests(unittest.TestCase):
    def test_generated_payload_against_schema(self):
        with _fixture_repo(POPULATED_REPO):
            generated, _warnings = gamify.build_payload(dt.date(2026, 9, 20))
        missing_field = {k: v for k, v in copy.deepcopy(generated).items() if k != "totals"}
        wrong_type = {**copy.deepcopy(generated), "schemaVersion": "1"}
        rows = [("required field removed", missing_field, True),
                ("field of the wrong type", wrong_type, True),
                ("unchanged", generated, False)]
        for name, payload, should_fail in rows:
            with self.subTest(name):
                errors = contract_schema.validate(payload, gamify.SCHEMA)
                self.assertEqual(bool(errors), should_fail, errors[:3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
