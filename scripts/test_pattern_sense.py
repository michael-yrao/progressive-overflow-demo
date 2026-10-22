"""Tests for pattern_sense.py — pure functions only, no network, no repo state.

Run: python -m unittest scripts/test_pattern_sense.py
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pattern_sense as ps  # noqa: E402

WEEK = "2026-11-30"
RULES = ps.DeckRules(per_week=3, starts=dt.date(2026, 11, 30))

FAMILIES = [
    {"id": "arrays_and_hash", "techniques": ["Hash Map Lookup", "Frequency Counting"]},
    {"id": "greedy", "techniques": ["Greedy (single pass)"]},
    {"id": "sliding_window", "techniques": ["Sliding Window", "Fixed Window"]},
    {"id": "two_pointers", "techniques": ["Opposite Ends", "Fast Slow"]},
]
HASH = ps.vocab_hash(FAMILIES)
VOCAB = ps.Vocabulary(
    family_of={t: f["id"] for f in FAMILIES for t in f["techniques"]} | {"Segment Tree": "expansion"},
    started=frozenset(t for f in FAMILIES for t in f["techniques"] if t != "Fast Slow"),
)


def problem(number, family, technique, **extra):
    return {"number": number, "slug": f"slug-{number}", "family": family, "technique": technique,
            "prompt": "Given an array, return the answer.", "constraints": ["1 <= n <= 10"],
            "cue": "the picking feature", **extra}


def deck(week=WEEK, problems=None, **extra):
    base = problems if problems is not None else [
        problem(1004, "sliding_window", "Sliding Window"),
        problem(55, "greedy", "Greedy (single pass)"),
        problem(76, "sliding_window", "Fixed Window"),
    ]
    return {"week": week, "problems": base, **extra}


def cand(number, family, companies=3, freq=10.0, premium=False):
    return ps.Candidate(number, f"slug-{number}", family, companies, freq, premium)


class EligibleTests(unittest.TestCase):
    def test_exclusions(self):
        clean = cand(1, "greedy")
        cases = [
            ("clean row kept", clean, ps.Exclusions(), True),
            ("tracker row", clean, ps.Exclusions(tracker=frozenset({1})), False),
            ("planned", clean, ps.Exclusions(planned=frozenset({1})), False),
            ("file under dsa/", clean, ps.Exclusions(files=frozenset({1})), False),
            ("probe log or queue", clean, ps.Exclusions(probed=frozenset({1})), False),
            ("mock log", clean, ps.Exclusions(mocked=frozenset({1})), False),
            ("earlier deck or skipped", clean, ps.Exclusions(decked=frozenset({1})), False),
            ("mock reserve slug", clean, ps.Exclusions(reserve=frozenset({"slug-1"})), False),
            ("premium", cand(1, "greedy", premium=True), ps.Exclusions(), False),
            ("no family", cand(1, "—"), ps.Exclusions(), False),
        ]
        for name, candidate, exclusions, expected in cases:
            with self.subTest(name):
                self.assertEqual(ps.eligible(candidate, exclusions), expected)


class PickTests(unittest.TestCase):
    def numbers(self, candidates, last_shown, per_week):
        picks = ps.pick(candidates, last_shown, per_week)
        return [c.number for c in picks.main], [c.number for c in picks.spare]

    def test_pick(self):
        cases = [
            ("least recently shown family first, never shown oldest",
             [cand(1, "a"), cand(2, "b"), cand(3, "c")],
             {"a": "2026-11-30", "b": "2026-12-07"}, 2, ([3, 1], [2])),
            ("tie on recency: more candidates first",
             [cand(1, "x"), cand(2, "y"), cand(3, "y")], {}, 1, ([2], [1])),
            ("tie on recency and count: family name",
             [cand(1, "y"), cand(2, "x")], {}, 1, ([2], [1])),
            ("within a family: companies, then max freq, then lower number",
             [cand(5, "a", 3, 50.0), cand(4, "a", 4, 10.0), cand(3, "a", 3, 60.0), cand(2, "a", 3, 60.0)],
             {}, 1, ([4], [2])),
            ("second pass fills from the same family order",
             [cand(1, "a"), cand(2, "a", 2), cand(3, "b")], {}, 3, ([1, 3, 2], [])),
        ]
        for name, candidates, last_shown, per_week, expected in cases:
            with self.subTest(name):
                self.assertEqual(self.numbers(candidates, last_shown, per_week), expected)


class ParseResultsCodeTests(unittest.TestCase):
    def parse(self, code, decks=None, families=FAMILIES, current=HASH):
        return ps.parse_results_code(code, decks if decks is not None else [deck()], families, current)

    def test_shared_example(self):
        parsed = self.parse(f"PS1 {WEEK} {HASH} 1004:+/+ 55:+/. 76:4/1")
        self.assertEqual(parsed["answers"], [
            {"number": 1004, "family": "+", "technique": "+"},
            {"number": 55, "family": "+", "technique": "."},
            {"number": 76, "family": "two_pointers", "technique": "Sliding Window"},
        ])

    def test_rejections(self):
        ok = "1004:+/+ 55:+/. 76:+/+"
        cases = [
            ("bad version tag", f"PS2 {WEEK} {HASH} {ok}", None),
            ("hash mismatch", f"PS1 {WEEK} deadbe {ok}", None),
            ("week with no deck", f"PS1 2026-12-07 {HASH} {ok}", None),
            ("deck already ingested", f"PS1 {WEEK} {HASH} {ok}", [deck(results={"ingested": "x"})]),
            ("missing number", f"PS1 {WEEK} {HASH} 1004:+/+ 55:+/.", None),
            ("out of order", f"PS1 {WEEK} {HASH} 55:+/. 1004:+/+ 76:+/+", None),
            ("family index out of range", f"PS1 {WEEK} {HASH} 1004:9/+ 55:+/. 76:+/+", None),
            ("technique index out of range", f"PS1 {WEEK} {HASH} 1004:+/3 55:+/. 76:+/+", None),
            ("dot on multi-technique family", f"PS1 {WEEK} {HASH} 1004:+/. 55:+/. 76:+/+", None),
            ("index on single-technique family", f"PS1 {WEEK} {HASH} 1004:+/+ 55:+/1 76:+/+", None),
        ]
        for name, code, decks in cases:
            with self.subTest(name):
                with self.assertRaises(ps.PatternSenseError):
                    self.parse(code, decks)

    def test_two_digit_indices(self):
        big = [{"id": f"f{i:02d}", "techniques": [f"t{j}" for j in range(1, 12)] if i == 1 else [f"u{i}"]}
               for i in range(1, 13)]
        decks = [deck(problems=[problem(7, "f01", "t3")])]
        parsed = self.parse(f"PS1 {WEEK} {ps.vocab_hash(big)} 7:12/10", decks, big, ps.vocab_hash(big))
        self.assertEqual(parsed["answers"], [{"number": 7, "family": "f12", "technique": "t10"}])


class PendingResultsTests(unittest.TestCase):
    def test_pending_results(self):
        def body(**changes):
            return {"schemaVersion": 1, "week": WEEK, "vocabulary": HASH,
                    "code": f"PS1 {WEEK} {HASH} 1004:+/+ 55:+/. 76:+/+",
                    "submittedAt": "2026-12-01T20:14:03Z", **changes}

        name = "dashboard/pattern_sense_results/20261130.json"
        cases = [
            ("valid, deck not ingested", name, body(), [deck()], True, None),
            ("deck already has results", name, body(), [deck(results={"ingested": "x"})], False, None),
            ("filename differs from week", "x/20261207.json", body(), [deck()], False, "file name"),
            ("wrong schemaVersion", name, body(schemaVersion=2), [deck()], False, "schemaVersion"),
            ("code week mismatch", name, body(code=f"PS1 2026-12-07 {HASH} 1004:+/+"), [deck()], False,
             "code does not start"),
            ("code vocabulary mismatch", name, body(code=f"PS1 {WEEK} deadbe 1004:+/+"), [deck()], False,
             "code does not start"),
        ]
        for label, path, content, decks, is_pending, error in cases:
            with self.subTest(label):
                pending, errors = ps.pending_results([(path, content)], decks)
                self.assertEqual(bool(pending), is_pending)
                if error:
                    self.assertEqual(len(errors), 1)
                    self.assertIn(path, errors[0])
                    self.assertIn(error, errors[0])
                else:
                    self.assertEqual(errors, [])


class ValidateTests(unittest.TestCase):
    def check(self, decks, ex=ps.Exclusions()):
        return "\n".join(ps.validate(decks, VOCAB, RULES, ex))

    def test_validate(self):
        def with_first(**changes):
            first = {**deck()["problems"][0], **changes}
            return [deck(problems=[first, *deck()["problems"][1:]])]

        cases = [
            ("valid deck", [deck()], ps.Exclusions(), ""),
            ("unknown technique", with_first(technique="Nope"), ps.Exclusions(), "unknown technique"),
            ("family mismatch", with_first(family="greedy"), ps.Exclusions(), "not 'greedy'"),
            ("expansion", with_first(family="expansion", technique="Segment Tree"), ps.Exclusions(), "expansion"),
            ("not started", with_first(family="two_pointers", technique="Fast Slow"), ps.Exclusions(),
             "not started"),
            ("technique in prompt", with_first(prompt="Use a sliding window here."), ps.Exclusions(),
             "names the technique"),
            ("allow_terms lifts it", with_first(prompt="Use a sliding window here.",
                                                allow_terms=["Sliding Window"]), ps.Exclusions(), ""),
            ("number in two decks", [deck(), deck(week="2026-12-07")], ps.Exclusions(), "more than once"),
            ("wrong count", [deck(problems=deck()["problems"][:2])], ps.Exclusions(), "per_week"),
            ("not a Monday", [deck(week="2026-12-01")], ps.Exclusions(), "not a Monday"),
            ("before starts", [deck(week="2026-11-23")], ps.Exclusions(), "before pattern_sense.starts"),
            ("now ineligible", [deck()], ps.Exclusions(tracker=frozenset({55})), "no longer eligible"),
        ]
        for name, decks, ex, expected in cases:
            with self.subTest(name):
                errors = self.check(decks, ex)
                if expected:
                    self.assertIn(expected, errors)
                else:
                    self.assertEqual(errors, "")

    def test_ingested_deck_skips_started_and_eligible(self):
        problems = [problem(1004, "two_pointers", "Fast Slow"), *deck()["problems"][1:]]
        ingested = deck(problems=problems, results={"ingested": "2026-12-07"})
        ex = ps.Exclusions(tracker=frozenset({1004, 55, 76}))
        self.assertEqual(self.check([ingested], ex), "")


class ExportEmptyDecksTests(unittest.TestCase):
    def test_empty_decks_exit_zero_and_write_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            decks_yml = Path(tmp) / "pattern_sense.yml"
            out = Path(tmp) / "pattern-sense.json"
            decks_yml.write_text("schemaVersion: 1\ndecks: []\n", encoding="utf-8")
            args = argparse.Namespace(check=False, stdout=False, date=None)
            stderr = io.StringIO()
            real_load_decks = ps.load_decks  # its default path is bound at definition time
            with mock.patch.object(ps, "DECKS_YML", decks_yml), mock.patch.object(ps, "OUT", out), \
                    mock.patch.object(ps, "load_decks", lambda: real_load_decks(decks_yml)), \
                    contextlib.redirect_stderr(stderr):
                code = ps.cmd_export(args)
            self.assertEqual(code, 0)
            self.assertFalse(out.exists())
            self.assertIn("no decks", stderr.getvalue())


class LoadExclusionsAbsentSourcesTests(unittest.TestCase):
    def test_absent_optional_files_exclude_nothing(self):
        """Unfixed code raises FileNotFoundError reading the three optional files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracker = root / "tracker.md"
            tracker.write_text("", encoding="utf-8")
            with mock.patch.object(ps, "PROBES_README", root / "probes.md"), \
                    mock.patch.object(ps, "MOCKS_README", root / "mocks.md"), \
                    mock.patch.object(ps, "COMPANY_DEMAND", root / "demand.md"), \
                    mock.patch.object(ps, "SOLUTION_DIRS", ()), \
                    mock.patch.object(ps, "load_technique_entries", lambda: []), \
                    mock.patch.object(ps, "planned_numbers", lambda *args: frozenset()), \
                    mock.patch.object(ps.cps, "tracker_numbers", lambda: []), \
                    mock.patch.object(ps.gamify, "TRACKER", tracker), \
                    mock.patch.object(ps.gamify, "load_roadmap", lambda warnings: {}), \
                    mock.patch.object(ps.gamify, "parse_waiting_room", lambda text: []):
                ex = ps.load_exclusions([], None)
        self.assertEqual((ex.probed, ex.mocked, ex.reserve), (frozenset(), frozenset(), frozenset()))


if __name__ == "__main__":
    unittest.main()
