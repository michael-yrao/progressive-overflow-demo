"""Tests for export_bigo.py — the Big-O Trainer contract generator.

Stdlib unittest, mirroring test_showcase.py's style (tempfile fixtures,
`mock.patch.object` on module paths). Run it with:

    python scripts/test_bigo.py

⚠️ EOL fixtures are written with `write_bytes`, never `Path.write_text` — see
test_showcase.py's identical warning about CRLF translation on Windows.

⚠️ export_bigo.py reads state from THREE modules, not just its own constants:
`export_showcase.REPO` / `links.source_roots()` / `links.TRACKER` (source file
resolution + title/url), and `effort_budget.TRACKER` (the difficulty join). A fixture
that patches only export_bigo's own REPO/MANIFEST/OUT/MISS_FILE would silently fall
through to the real repo for the other three — `SyntheticRepoTestCase` patches all six.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import contract_schema
import effort_budget
import export_bigo as bo
import export_showcase as es
import links


def _write(path: Path, text: str) -> None:
    """Write `text` as literal UTF-8 bytes — see the module docstring's EOL warning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


# ── COMPLEXITY_POOL / CONFUSABLE invariants ──────────────────────────────────────────

class ValidateLabelTests(unittest.TestCase):
    def test_valid_label_passes(self):
        bo.validate_label("O(n)", "time", "1")  # must not raise

    def test_todo_is_not_a_pool_label(self):
        self.assertNotIn(bo.TODO_LABEL, bo.POOL_RANK)

    def test_typo_names_close_matches(self):
        with self.assertRaises(bo.BigOError) as cm:
            bo.validate_label("O(n logn)", "time", "146")
        message = str(cm.exception)
        self.assertIn("146", message)
        self.assertIn("O(n log n)", message)


class ConfusablePoolMembershipTests(unittest.TestCase):
    def test_every_confusable_key_and_value_is_in_the_pool(self):
        for label, alternatives in bo.CONFUSABLE.items():
            with self.subTest(label=label):
                self.assertIn(label, bo.POOL_RANK)
            for alt in alternatives:
                with self.subTest(label=label, alt=alt):
                    self.assertIn(alt, bo.POOL_RANK)

    def test_validator_runs_clean_at_import(self):
        bo._validate_confusable_pool()  # must not raise


# ── options_for: deterministic multiple-choice construction ─────────────────────────

class OptionsForTests(unittest.TestCase):
    def test_deterministic_for_the_same_inputs(self):
        first = bo.options_for("O(n)", "146:v", "time")
        second = bo.options_for("O(n)", "146:v", "time")
        self.assertEqual(first, second)

    def test_returns_exactly_option_count_unique_labels(self):
        options = bo.options_for("O(n)", "1", "time")
        self.assertEqual(len(options), bo.OPTION_COUNT)
        self.assertEqual(len(set(options)), bo.OPTION_COUNT)

    def test_contains_the_correct_answer(self):
        options = bo.options_for("O(V+E)", "210", "time")
        self.assertIn("O(V+E)", options)

    def test_sorted_by_pool_rank(self):
        options = bo.options_for("O(n²)", "973", "space")
        ranks = [bo.POOL_RANK[label] for label in options]
        self.assertEqual(ranks, sorted(ranks))

    def test_every_pool_label_produces_a_valid_option_set(self):
        for label in bo.COMPLEXITY_POOL:
            with self.subTest(label=label):
                options = bo.options_for(label, "999", "time")
                self.assertEqual(len(options), bo.OPTION_COUNT)
                self.assertIn(label, options)

    def test_correct_answer_index_is_not_constant_across_all_pool_labels(self):
        # Regression: a purely nearest-rank (non-randomized) top-up put every
        # no-CONFUSABLE label's correct answer at the SAME sorted position (index 2),
        # which is a second, unintended answer key the site could be gamed against.
        positions = {bo.options_for(label, "999", "time").index(label)
                     for label in bo.COMPLEXITY_POOL}
        self.assertGreaterEqual(len(positions), 3)

    def test_options_can_differ_between_two_keys_for_the_same_label(self):
        differing = any(
            bo.options_for(label, "111", "time") != bo.options_for(label, "222", "time")
            for label in bo.COMPLEXITY_POOL)
        self.assertTrue(differing)


# ── latest_dated_attempt: date wins, tie -> lowest in file, none -> None ─────────────

class LatestDatedAttemptTests(unittest.TestCase):
    def test_later_date_wins(self):
        source = (
            "class Solution:\n"
            "    def early_20260101(self, x):\n"
            "        return x\n"
            "\n"
            "    def late_20260301(self, x):\n"
            "        return x\n"
        )
        lines = source.split("\n")
        table = es.symbol_table(ast.parse(source))
        self.assertEqual(bo.latest_dated_attempt(table, lines), ("Solution", "late_20260301"))

    def test_tie_prefers_the_candidate_lowest_in_the_file(self):
        source = (
            "class Solution:\n"
            "    def first_20260501(self, x):\n"
            "        return x\n"
            "\n"
            "    def second_20260501(self, x):\n"
            "        return x\n"
        )
        lines = source.split("\n")
        table = es.symbol_table(ast.parse(source))
        self.assertEqual(bo.latest_dated_attempt(table, lines), ("Solution", "second_20260501"))

    def test_no_dated_candidate_returns_none(self):
        source = "class Solution:\n    def plain(self, x):\n        return x\n"
        lines = source.split("\n")
        table = es.symbol_table(ast.parse(source))
        self.assertIsNone(bo.latest_dated_attempt(table, lines))

    def test_only_solution_methods_and_non_solution_top_level_symbols_are_candidates(self):
        # A DESIGN class's own METHODS are never candidates (only "Solution.<m>" methods
        # and top-level defs/classes != "Solution" are) — so a dated method on a
        # non-Solution class must not win over a dated top-level function.
        source = (
            "class DesignThing:\n"
            "    def op_20260901(self, x):\n"
            "        return x\n"
            "\n"
            "def freeFunc_20260101(x):\n"
            "    return x\n"
        )
        lines = source.split("\n")
        table = es.symbol_table(ast.parse(source))
        self.assertEqual(bo.latest_dated_attempt(table, lines), (None, "freeFunc_20260101"))


# ── resolve_pick: container semantics ────────────────────────────────────────────────

class ResolvePickTests(unittest.TestCase):
    def _table_and_lines(self, source: str) -> tuple[dict, list[str]]:
        return es.symbol_table(ast.parse(source)), source.split("\n")

    def test_auto_picked_solution_method_gets_container_solution(self):
        table, lines = self._table_and_lines(
            "class Solution:\n    def method_20260301(self, x):\n        return x\n")
        container, symbol, _node = bo.resolve_pick(
            {"lc": 1, "time": "O(1)", "space": "O(1)"}, table, lines, "1")
        self.assertEqual((container, symbol), ("Solution", "method_20260301"))

    def test_auto_picked_top_level_symbol_gets_container_none(self):
        table, lines = self._table_and_lines("def solve_20260301(x):\n    return x\n")
        container, symbol, _node = bo.resolve_pick(
            {"lc": 1, "time": "O(1)", "space": "O(1)"}, table, lines, "1")
        self.assertEqual((container, symbol), (None, "solve_20260301"))

    def test_explicit_symbol_defaults_container_to_solution(self):
        table, lines = self._table_and_lines(
            "class Solution:\n    def picked(self, x):\n        return x\n")
        container, symbol, _node = bo.resolve_pick(
            {"lc": 1, "time": "O(1)", "space": "O(1)", "symbol": "picked"}, table, lines, "1")
        self.assertEqual((container, symbol), ("Solution", "picked"))

    def test_explicit_container_null_for_a_design_class(self):
        table, lines = self._table_and_lines(
            "class DesignThing:\n    def op(self, x):\n        return x\n")
        container, symbol, _node = bo.resolve_pick(
            {"lc": 1, "time": "O(1)", "space": "O(1)", "symbol": "DesignThing", "container": None},
            table, lines, "1")
        self.assertIsNone(container)
        self.assertEqual(symbol, "DesignThing")

    def test_container_without_symbol_raises(self):
        table, lines = self._table_and_lines("class Solution:\n    def x(self):\n        return 1\n")
        with self.assertRaises(bo.BigOError):
            bo.resolve_pick({"lc": 1, "time": "O(1)", "space": "O(1)", "container": None},
                             table, lines, "1")

    def test_nothing_dated_raises_telling_the_author_to_add_symbol(self):
        table, lines = self._table_and_lines(
            "class Solution:\n    def plain(self, x):\n        return x\n")
        with self.assertRaises(bo.BigOError) as cm:
            bo.resolve_pick({"lc": 1, "time": "O(1)", "space": "O(1)"}, table, lines, "1")
        self.assertIn("symbol:", str(cm.exception))


# ── is_scaffold: placeholder-body detection ──────────────────────────────────────────

class IsScaffoldTests(unittest.TestCase):
    def _node(self, source: str) -> ast.AST:
        return ast.parse(source).body[0]

    def test_bare_pass_is_scaffold(self):
        self.assertTrue(bo.is_scaffold(self._node("def f():\n    pass\n")))

    def test_bare_ellipsis_is_scaffold(self):
        self.assertTrue(bo.is_scaffold(self._node("def f():\n    ...\n")))

    def test_docstring_plus_pass_is_scaffold(self):
        node = self._node('def f():\n    """TODO"""\n    pass\n')
        self.assertTrue(bo.is_scaffold(node))

    def test_class_of_all_scaffold_methods_is_scaffold(self):
        node = self._node(
            "class Solution:\n    def a(self):\n        pass\n    def b(self):\n        ...\n")
        self.assertTrue(bo.is_scaffold(node))

    def test_class_with_one_real_method_is_not_scaffold(self):
        node = self._node(
            "class Solution:\n    def a(self):\n        pass\n"
            "    def b(self):\n        return 1\n")
        self.assertFalse(bo.is_scaffold(node))

    def test_real_body_is_not_scaffold(self):
        self.assertFalse(bo.is_scaffold(self._node("def f(x):\n    return x + 1\n")))


# ── parse_miss_numbers: section-scoped table parsing ─────────────────────────────────

class ParseMissNumbersTests(unittest.TestCase):
    FIXTURE = (
        "# Complexity Gotchas\n"
        "\n"
        "## Recurring categories\n"
        "| 999 not a real row, wrong section | should be ignored | x |\n"
        "\n"
        "## ⏳ End-of-week complexity cleanup queue (widened Sep 23)\n"
        "| Problem | Missed bound | Queued | Cleared |\n"
        "|---|---|---|---|\n"
        "| 743 Network Delay Time | space miss | 2026-09-03 | |\n"
        "| ↳ not a real number row, arrow-prefixed | x | y | z |\n"
        "\n"
        "## \U0001f3af Cold complexity probes\n"
        "| 111 should be ignored, unmarked section | x | y | z |\n"
        "\n"
        "## Ledger (miss history)\n"
        "| Problem | Category | Said -> Actual | First-miss date | Freebie |\n"
        "|---|---|---|---|---|\n"
        "| 242 Valid Anagram | fixed-alphabet | O(n) -> O(1) | 2026-07-22 | spent |\n"
        "| ↳ TRANSFERRED - 875 Koko | not a real row | x | y | z |\n"
    )

    def test_only_numbers_from_marked_sections_are_collected(self):
        self.assertEqual(bo.parse_miss_numbers(self.FIXTURE), frozenset({743, 242}))

    def test_empty_text_yields_no_numbers(self):
        self.assertEqual(bo.parse_miss_numbers(""), frozenset())


class MissNumbersTests(unittest.TestCase):
    def test_absent_ledger_is_no_misses_and_any_other_read_failure_raises(self):
        # A fresh adopter has no complexity_gotchas.md yet (no misses); a path that exists
        # but cannot be read as a file (a directory) is still a hard BigOError.
        absent = Path(tempfile.gettempdir()) / "definitely-does-not-exist-bigo-miss-ledger.md"
        unreadable = Path(tempfile.gettempdir())
        rows = [("absent ledger", absent, frozenset(), None),
                ("unreadable ledger", unreadable, None, bo.BigOError)]
        for label, ledger, expected, error in rows:
            with self.subTest(label), mock.patch.object(bo, "MISS_FILE", ledger):
                if error is None:
                    self.assertEqual(bo.miss_numbers(), expected)
                else:
                    with self.assertRaises(error) as cm:
                        bo.miss_numbers()
                    self.assertIn(str(ledger), str(cm.exception))


# ── build_payload + --check staleness, end to end against a synthetic repo ──────────

class SyntheticRepoTestCase(unittest.TestCase):
    """A tiny synthetic repo tree so build_payload/_stale_reasons/main() tests never
    touch the real dsa/leetcode/, dashboard/bigo.yml, complexity_gotchas.md, or
    dsa_progress.md."""

    SOURCE = (
        "class Solution:\n"
        "    def target_20260101(self, x):\n"
        "        # only comment\n"
        "        return x\n"
    )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.dashboard = self.repo / "dashboard"
        self.root = self.repo / "dsa" / "leetcode" / "cat"
        self.source_path = self.root / "1_target.py"
        _write(self.source_path, self.SOURCE)

        tracker_path = self.repo / "docs" / "foundations" / "dsa" / "mastery" / "dsa_progress.md"
        _write(tracker_path,
               "| Easy | [1. Target](https://leetcode.com/problems/target/) "
               "| \U0001f7e2 | 1 | 2026-12-01 |\n")
        miss_path = self.repo / "docs" / "foundations" / "dsa" / "mastery" / "complexity_gotchas.md"
        _write(miss_path, "# Complexity Gotchas\n\n## Ledger (miss history)\n")

        self._orig_roots = links.source_roots
        self._orig_links_tracker = links.TRACKER
        self._orig_eb_tracker = effort_budget.TRACKER
        links.source_roots = lambda: [self.repo / "dsa" / "leetcode"]
        links.TRACKER = tracker_path
        effort_budget.TRACKER = tracker_path

        self._patches = [
            mock.patch.object(es, "REPO", self.repo),
            mock.patch.object(bo, "REPO", self.repo),
            mock.patch.object(bo, "DASHBOARD", self.dashboard),
            mock.patch.object(bo, "MANIFEST", self.dashboard / "bigo.yml"),
            mock.patch.object(bo, "OUT", self.dashboard / "big-o.json"),
            mock.patch.object(bo, "MISS_FILE", miss_path),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        links.source_roots = self._orig_roots
        links.TRACKER = self._orig_links_tracker
        effort_budget.TRACKER = self._orig_eb_tracker
        self._tmp.cleanup()

    def _write_manifest(self, entries_yaml: str) -> None:
        _write(bo.MANIFEST, f"schemaVersion: 1\nentries:\n{entries_yaml}")

    def _manifest_entry(self, **overrides) -> dict:
        base = {"lc": 1, "time": "O(n)", "space": "O(1)", "symbol": "target_20260101"}
        base.update(overrides)
        return base

    def _entry_yaml(self, **overrides) -> str:
        return f"  - {self._manifest_entry(**overrides)}\n".replace("'", "")


class BuildPayloadTests(SyntheticRepoTestCase):
    def test_build_payload_produces_the_expected_fields(self):
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        payload, warnings, skipped = bo.build_payload(manifest, dt.date(2026, 9, 24))
        self.assertEqual(len(payload["entries"]), 1)
        entry = payload["entries"][0]
        self.assertEqual(entry["key"], "1")
        self.assertEqual(entry["time"], "O(n)")
        self.assertEqual(entry["space"], "O(1)")
        self.assertEqual(entry["difficulty"], "Easy")
        self.assertEqual(payload["pool"], list(bo.COMPLEXITY_POOL))
        self.assertFalse(entry["isMiss"])
        self.assertEqual(len(entry["timeOptions"]), bo.OPTION_COUNT)
        self.assertIn(entry["time"], entry["timeOptions"])
        self.assertEqual(warnings, [])
        self.assertEqual(skipped, 0)

    def test_duplicate_key_raises(self):
        entry = self._manifest_entry()
        manifest = {"schemaVersion": 1, "entries": [entry, dict(entry)]}
        with self.assertRaises(bo.BigOError):
            bo.build_payload(manifest, dt.date(2026, 9, 24))

    def test_todo_time_is_skipped_with_a_warning(self):
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry(time="TODO")]}
        payload, warnings, skipped = bo.build_payload(manifest, dt.date(2026, 9, 24))
        self.assertEqual(payload["entries"], [])
        self.assertTrue(any(w.endswith("TODO — skipped") for w in warnings))
        self.assertEqual(skipped, 1)

    def test_todo_space_is_skipped_with_a_warning(self):
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry(space="TODO")]}
        payload, warnings, skipped = bo.build_payload(manifest, dt.date(2026, 9, 24))
        self.assertEqual(payload["entries"], [])
        self.assertTrue(any(w.endswith("TODO — skipped") for w in warnings))
        self.assertEqual(skipped, 1)

    def test_unrecognized_label_raises(self):
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry(time="O(banana)")]}
        with self.assertRaises(bo.BigOError):
            bo.build_payload(manifest, dt.date(2026, 9, 24))

    def test_is_miss_true_when_the_number_is_in_a_marked_section(self):
        _write(bo.MISS_FILE,
               "# Complexity Gotchas\n\n## Ledger (miss history)\n"
               "| 1 Target | cat | x | y | z |\n")
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        payload, _warnings, _skipped = bo.build_payload(manifest, dt.date(2026, 9, 24))
        self.assertTrue(payload["entries"][0]["isMiss"])

    def test_scaffold_pick_raises(self):
        _write(self.source_path,
               "class Solution:\n    def target_20260101(self, x):\n        pass\n")
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        with self.assertRaises(bo.BigOError) as cm:
            bo.build_payload(manifest, dt.date(2026, 9, 24))
        self.assertIn("scaffold", str(cm.exception))


class DifficultyJoinTests(SyntheticRepoTestCase):
    def test_no_tracker_row_is_null_plus_a_warning(self):
        _write(effort_budget.TRACKER, "")
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        payload, warnings, _skipped = bo.build_payload(manifest, dt.date(2026, 9, 24))
        self.assertIsNone(payload["entries"][0]["difficulty"])
        self.assertTrue(any("no difficulty found" in w for w in warnings))

    def test_disagreeing_rows_warn_and_keep_the_first(self):
        _write(effort_budget.TRACKER,
               "| Easy | [1. Target](https://leetcode.com/problems/target/) "
               "| \U0001f7e2 | 1 | 2026-12-01 |\n"
               "| Hard | [1. Target](https://leetcode.com/problems/target/) "
               "| \U0001f7e2 | 1 | 2026-12-01 |\n")
        by_num, warnings = bo.difficulty_by_number()
        self.assertEqual(by_num[1], "Easy")
        self.assertTrue(any("disagree" in w for w in warnings))


class TwinRequiresFileTests(SyntheticRepoTestCase):
    def test_twin_without_file_raises_naming_the_twin(self):
        other_root = self.repo / "dsa" / "leetcode" / "other"
        _write(other_root / "1_other_target.py", self.SOURCE)
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        # resolve_source_file is reused straight from export_showcase, so a twin still
        # raises es.ShowcaseError (BigOError's own base class), not a bare BigOError.
        with self.assertRaises(es.ShowcaseError) as cm:
            bo.build_payload(manifest, dt.date(2026, 9, 24))
        self.assertIn("twin", str(cm.exception))

    def test_twin_with_explicit_file_resolves(self):
        other_root = self.repo / "dsa" / "leetcode" / "other"
        _write(other_root / "1_other_target.py", self.SOURCE)
        manifest = {"schemaVersion": 1,
                     "entries": [self._manifest_entry(file="dsa/leetcode/cat/1_target.py")]}
        payload, _warnings, _skipped = bo.build_payload(manifest, dt.date(2026, 9, 24))
        self.assertEqual(len(payload["entries"]), 1)


class MainCliTests(SyntheticRepoTestCase):
    def _run(self, argv, module=bo):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                module.main()
                code = 0
            except SystemExit as exc:
                code = exc.code or 0
        return out.getvalue(), err.getvalue(), code

    def test_empty_manifest_exits_zero_and_writes_no_output_file(self):
        # Both exporters share the rule: no entries -> notice + exit 0 + NO output file, so
        # the site's 404 fallback to the author's data is not suppressed by an empty file.
        # export_showcase is patched here because this fixture only patches export_bigo.
        showcase_manifest = self.dashboard / "showcase.yml"
        showcase_out = self.dashboard / "showcase.json"
        rows = [("bigo --check", bo, ["export_bigo.py", "--check"], bo.MANIFEST, bo.OUT),
                ("bigo write", bo, ["export_bigo.py"], bo.MANIFEST, bo.OUT),
                ("showcase --check", es, ["export_showcase.py", "--check"],
                 showcase_manifest, showcase_out),
                ("showcase write", es, ["export_showcase.py"], showcase_manifest, showcase_out)]
        for label, module, argv, manifest_path, out_path in rows:
            with self.subTest(label), \
                 mock.patch.object(es, "MANIFEST", showcase_manifest), \
                 mock.patch.object(es, "OUT", showcase_out), \
                 mock.patch.object(es, "DASHBOARD", self.dashboard):
                _write(manifest_path, "schemaVersion: 1\nentries: []\n")
                _out, err, code = self._run(argv, module)
                self.assertEqual(code, 0)
                self.assertIn("no entries", err)
                self.assertFalse(out_path.exists())

    def test_stdout_mode_prints_only_json_and_writes_nothing(self):
        self._write_manifest(self._entry_yaml())
        out, _err, code = self._run(["export_bigo.py", "--stdout"])
        self.assertEqual(code, 0)
        json.loads(out)  # raises if anything non-JSON leaked onto stdout
        self.assertFalse(bo.OUT.exists())

    def test_check_mode_with_no_existing_file_succeeds_and_writes_nothing(self):
        self._write_manifest(self._entry_yaml())
        _out, err, code = self._run(["export_bigo.py", "--check"])
        self.assertEqual(code, 0)
        self.assertIn("ok:", err)
        self.assertFalse(bo.OUT.exists())

    def test_check_mode_reports_todo_skip_count(self):
        entries = self._entry_yaml() + self._entry_yaml(lc=2, time="TODO")
        self._write_manifest(entries)
        _out, err, code = self._run(["export_bigo.py", "--check"])
        self.assertEqual(code, 0)
        self.assertIn("1 skipped as TODO", err)

    def test_default_mode_writes_the_file(self):
        self._write_manifest(self._entry_yaml())
        self._run(["export_bigo.py"])
        self.assertTrue(bo.OUT.exists())
        data = json.loads(bo.OUT.read_text(encoding="utf-8"))
        self.assertEqual(len(data["entries"]), 1)

    def test_check_mode_fails_and_writes_nothing_when_stale(self):
        self._write_manifest(self._entry_yaml())
        bo.OUT.parent.mkdir(parents=True, exist_ok=True)
        bo.OUT.write_text(json.dumps({
            "schemaVersion": 1, "generatedAt": "2020-01-01",
            "entries": [{"key": "1", "file": "dsa/leetcode/cat/1_target.py",
                         "segments": [{"kind": "attempt", "symbol": "target_20260101",
                                       "startLine": 1, "endLine": 1,
                                       "lines": ["this does not match the file"]}]}]}),
            encoding="utf-8")
        before = bo.OUT.read_text(encoding="utf-8")
        _out, err, code = self._run(["export_bigo.py", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("stale", err)
        self.assertEqual(bo.OUT.read_text(encoding="utf-8"), before)  # --check never writes

    def test_check_on_corrupted_existing_file_names_the_big_o_label(self):
        self._write_manifest(self._entry_yaml())
        bo.OUT.parent.mkdir(parents=True, exist_ok=True)
        bo.OUT.write_text(json.dumps({"schemaVersion": 1, "entries": "not-a-list"}),
                           encoding="utf-8")
        _out, err, code = self._run(["export_bigo.py", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("big-o.json:", err)
        self.assertIn("'entries' must be a list", err)
        self.assertNotIn("Traceback", err)


# ── verbatim check against a GENERATED dashboard/big-o.json, when one exists ────────

class RealBigOJsonVerbatimTests(unittest.TestCase):
    """Loads the dashboard/big-o.json generated by a prior `python scripts/export_bigo.py`
    run and pins that every segment is byte-identical to its source, every label is a
    COMPLEXITY_POOL member, and every option set contains its own answer. Skipped until
    the adopter has generated one."""

    # No sorted-options index may hold more than this share of one axis's correct
    # answers across the whole real deck — a share this high on ANY index means that
    # index is effectively a second answer key (the Sep 24 options_for review finding).
    # 0.5 is well above the 1/OPTION_COUNT = 0.25 a leak-free deck should land near, so
    # it catches real concentration without being fragile to ordinary sampling noise.
    MAX_POSITION_SHARE = 0.5

    @classmethod
    def setUpClass(cls):
        if not bo.OUT.exists():
            raise unittest.SkipTest(
                "dashboard/big-o.json not found — run `python scripts/export_bigo.py` first")
        cls.data = json.loads(bo.OUT.read_text(encoding="utf-8"))

    def _source_lines(self, file_rel: str) -> list[str]:
        raw = (bo.REPO / file_rel).read_bytes().decode("utf-8")
        return [line[:-1] if line.endswith("\r") else line for line in raw.split("\n")]

    def test_every_segment_is_byte_identical_to_its_source_file(self):
        for entry in self.data["entries"]:
            source = self._source_lines(entry["file"])
            for seg in entry["segments"]:
                start, end = seg["startLine"], seg["endLine"]
                with self.subTest(key=entry["key"], symbol=seg["symbol"]):
                    self.assertEqual(seg["lines"], source[start - 1:end])

    def test_every_label_is_in_the_pool(self):
        for entry in self.data["entries"]:
            with self.subTest(key=entry["key"]):
                self.assertIn(entry["time"], bo.COMPLEXITY_POOL)
                self.assertIn(entry["space"], bo.COMPLEXITY_POOL)

    def test_every_options_list_contains_its_own_answer(self):
        for entry in self.data["entries"]:
            with self.subTest(key=entry["key"]):
                self.assertIn(entry["time"], entry["timeOptions"])
                self.assertIn(entry["space"], entry["spaceOptions"])

    def test_answer_position_is_not_concentrated(self):
        for axis, options_key in (("time", "timeOptions"), ("space", "spaceOptions")):
            positions = Counter(
                entry[options_key].index(entry[axis]) for entry in self.data["entries"])
            total = sum(positions.values())
            for index, count in positions.items():
                share = count / total
                with self.subTest(axis=axis, index=index):
                    self.assertLessEqual(
                        share, self.MAX_POSITION_SHARE,
                        f"{axis} answers sit at index {index} in {count}/{total} entries "
                        f"({share:.0%}) — exceeds MAX_POSITION_SHARE "
                        f"({self.MAX_POSITION_SHARE:.0%})")


VALID_PAYLOAD = {
    "schemaVersion": 1, "generatedAt": "2026-09-24", "pool": ["O(1)", "O(n)"],
    "entries": [{"key": "1", "lcNumber": 1, "variant": None, "title": "T", "url": "u",
                 "file": "dsa/leetcode/cat/1_target.py", "symbol": "target_20260101",
                 "attemptDate": "2026-01-01", "difficulty": "Easy", "category": "cat",
                 "isMiss": False, "note": None, "time": "O(n)", "space": "O(1)",
                 "whyTime": None, "whySpace": None,
                 "timeOptions": ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
                 "spaceOptions": ["O(1)", "O(log n)", "O(h)", "O(n)"],
                 "segments": [{"kind": "attempt", "symbol": "target_20260101",
                               "startLine": 1, "endLine": 1, "lines": ["x"]}]}],
}


class SchemaValidationTests(unittest.TestCase):
    def test_payload_against_schema(self):
        missing_field = {k: v for k, v in copy.deepcopy(VALID_PAYLOAD).items() if k != "entries"}
        wrong_type = {**copy.deepcopy(VALID_PAYLOAD), "schemaVersion": "1"}
        rows = [("required field removed", missing_field, True),
                ("field of the wrong type", wrong_type, True),
                ("unchanged", VALID_PAYLOAD, False)]
        for name, payload, should_fail in rows:
            with self.subTest(name):
                errors = contract_schema.validate(payload, bo.SCHEMA)
                self.assertEqual(bool(errors), should_fail, errors[:3])


if __name__ == "__main__":
    unittest.main()
