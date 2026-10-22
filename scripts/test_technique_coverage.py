"""Tests for technique_coverage.py — the `queued:` key on a `problems:` spec.

Stdlib unittest, pytest-compatible. String
fixtures only: a tiny techniques.yml + a tiny dsa_progress.md, written to temp files with
the module's own path constants monkeypatched — never the live repo files. Run it with:

    python scripts/test_technique_coverage.py

Pins the `queued:` key: a `problems:` spec with no matching tracker row and a `queued:`
trigger is reported as a known gap (the Gaps cell + the Action list), never silently
folded into "declared, not queued"; a `queued:` on a spec that DOES match a row is a no-op;
an unqueued unreached spec is still counted AND listed; and the rendered `## Coverage`
table still round-trips through gamify.parse_techniques() with the right `problems` list,
`thin` flag, and no false `hasVariantGap`.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import gamify
import technique_coverage as tc

TECHNIQUES_FIXTURE = """
version: 1
techniques:
  - name: Test Tech
    family: test_family
    problems:
      - {number: 100, queued: "ignored-trigger"}
      - {number: 200, queued: "surplus>=1"}
      - {number: 300}
"""

TRACKER_FIXTURE = (
    "| Difficulty | Problem | Comfort | Streak | Next Review Date | Latest Rep Date | Rep Dates |\n"
    "|---|---|---|---|---|---|---|\n"
    "| Medium | [100. Test Problem](https://example.com/100) | 🟢 | 1 "
    "| 2026-01-01 | 2026-01-01 | 2026-01-01 |\n"
)


class QueuedProblemTests(unittest.TestCase):
    """resolve()/render() against the fixtures above — never the live repo files.

    100 has a matching tracker row (and its own, irrelevant `queued:` key — it is matched,
    so the key is never consulted). 200 has no tracker row and a `queued:` trigger — a
    known gap. 300 has no tracker row and no `queued:` — plain "declared, not queued".
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self._techniques_path = tmp / "techniques.yml"
        self._tracker_path = tmp / "dsa_progress.md"
        self._techniques_path.write_text(TECHNIQUES_FIXTURE, encoding="utf-8")
        self._tracker_path.write_text(TRACKER_FIXTURE, encoding="utf-8")

        self._orig_techniques_yml = tc.TECHNIQUES_YML
        self._orig_tracker_md = tc.TRACKER_MD
        tc.TECHNIQUES_YML = self._techniques_path
        tc.TRACKER_MD = self._tracker_path

        self._orig_gamify_coverage = gamify.COVERAGE

    def tearDown(self):
        tc.TECHNIQUES_YML = self._orig_techniques_yml
        tc.TRACKER_MD = self._orig_tracker_md
        gamify.COVERAGE = self._orig_gamify_coverage
        self._tmpdir.cleanup()

    def _render(self) -> str:
        config = tc.yaml.safe_load(tc.TECHNIQUES_YML.read_text(encoding="utf-8"))
        rows = tc.parse_tracker(tc.TRACKER_MD)
        # DEFAULT_COVERAGE_THRESHOLD directly, never a disk read of the live
        # cse.config.yml — this fixture stays isolated from repo state, same as the
        # techniques.yml/tracker fixtures above.
        resolved, claimed = tc.resolve(config, rows, tc.DEFAULT_COVERAGE_THRESHOLD)
        return tc.render(resolved, rows, claimed)

    def test_queued_problem_in_gaps_cell_and_action_list_not_in_problems_parens(self):
        report = self._render()
        self.assertIn("queued: 200 `surplus>=1`", report)   # Gaps cell style (bare)
        self.assertIn("queued: 200 (`surplus>=1`)", report)  # Action list style (parens)
        # The Problems cell's parenthetical carries only the MATCHED number.
        self.assertIn("1 (100)", report)
        self.assertNotIn("(100, 200)", report)
        self.assertNotIn("(200)", report)

    def test_unqueued_unreached_problem_counted_and_listed_under_declared_not_queued(self):
        report = self._render()
        self.assertIn("**Declared, not queued (1)**", report)
        self.assertIn(": 300", report)
        self.assertIn("**Queued (1)**", report)

    def test_queued_on_a_matched_spec_is_ignored_with_no_error(self):
        report = self._render()
        # 100 is matched (a tracker row exists) despite its own `queued:` key — it counts
        # as an ordinary solved problem, never as a queued gap, and the key raises nothing.
        self.assertIn("1 (100)", report)
        self.assertNotIn("ignored-trigger", report)

    def test_coverage_table_round_trips_through_gamify_parse_techniques(self):
        report = self._render()
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(report)
        tmp.close()
        gamify.COVERAGE = Path(tmp.name)
        try:
            rows = {r["name"]: r for r in gamify.parse_techniques([])}
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        row = rows["Test Tech"]
        self.assertEqual(row["problems"], [100])
        self.assertEqual(row["problemCount"], 1)
        self.assertTrue(row["thin"])
        self.assertFalse(row["hasVariantGap"])


class ComputeCoverageThresholdTests(unittest.TestCase):
    """Table-driven test of `compute_coverage_threshold()` — the pure formula behind the
    per-technique coverage bar (decision `coverage-threshold-formula-sep27`):

        floor     = an explicit override, else clamp(ceil(plan_share * declared),
                    floor_min, floor_max)
        threshold = floor + unclean

    Fixed config throughout (`plan_share=0.5, floor_min=1, floor_max=5`) — only
    `declared`/`unclean`/`override` vary per case.
    """

    CFG = {"plan_share": 0.5, "floor_min": 1, "floor_max": 5}

    CASES = {
        "zero declared clamps up to floor_min": (
            {"declared": 0, "unclean": 0, "override": None}, (1, 1)),
        "a mid declared count rounds its floor up": (
            # ceil(0.5 * 5) = ceil(2.5) = 3
            {"declared": 5, "unclean": 0, "override": None}, (3, 3)),
        "a large declared count clamps down to floor_max": (
            # ceil(0.5 * 20) = 10, clamped to floor_max=5
            {"declared": 20, "unclean": 0, "override": None}, (5, 5)),
        "an explicit override replaces the computed floor": (
            # the computed floor from declared=1 would be 1; the override wins instead
            {"declared": 1, "unclean": 0, "override": 4}, (4, 4)),
        "unclean adds on top of a computed floor": (
            {"declared": 5, "unclean": 2, "override": None}, (3, 5)),
        "unclean adds on top of an overridden floor": (
            {"declared": 1, "unclean": 2, "override": 4}, (4, 6)),
    }

    def test_floor_and_threshold(self):
        for label, (kwargs, expected) in self.CASES.items():
            with self.subTest(label):
                self.assertEqual(
                    tc.compute_coverage_threshold(**kwargs, **self.CFG), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
