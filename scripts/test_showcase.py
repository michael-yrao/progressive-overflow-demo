"""Tests for export_showcase.py — the grounded-solutions contract generator.

Stdlib unittest (tempfile fixtures, `mock.patch.object(sys, "argv")`,
`redirect_stdout`). Run it with:

    python scripts/test_showcase.py

⚠️ EOL fixtures are written with `write_bytes` / `Path.write_bytes`, never
`Path.write_text` or `NamedTemporaryFile(mode="w")` — those translate `\\n` to the
platform's line ending (CRLF on Windows), which would silently turn an "LF fixture" into
CRLF and make the CRLF/LF-agnosticism test pass vacuously.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import contract_schema
import export_showcase as es
import links


def _write(path: Path, text: str) -> None:
    """Write `text` as literal UTF-8 bytes — see the module docstring's EOL warning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


# ── pure helpers: read_lines / def_start_line / symbol_table ────────────────────────

class ReadLinesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_lf_and_crlf_fixtures_give_identical_lines(self):
        lf_path = self.dir / "lf.py"
        crlf_path = self.dir / "crlf.py"
        _write(lf_path, "a = 1\nb = 2\n")
        _write(crlf_path, "a = 1\r\nb = 2\r\n")
        # Prove the fixtures are what they claim to be before trusting the assertion below.
        self.assertNotIn(b"\r\n", lf_path.read_bytes())
        self.assertIn(b"\r\n", crlf_path.read_bytes())
        self.assertEqual(es.read_lines(lf_path), es.read_lines(crlf_path))

    def test_trailing_newline_yields_trailing_empty_string(self):
        path = self.dir / "trailing.py"
        _write(path, "a = 1\n")
        self.assertEqual(es.read_lines(path), ["a = 1", ""])


class IndexReadsTests(unittest.TestCase):
    """`index_reads()` (the pre-commit hook's --from-index) reads STAGED content: an
    unstaged working-tree change to a file — here an emptied scaffold — neither alters nor
    aborts what is read. Default reads stay on the working tree. Uses a throwaway git repo."""

    def _git(self, repo: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    def test_unstaged_working_tree_change_does_not_affect_staged_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git(repo, "init", "-q")
            staged = repo / "1_staged.py"
            _write(staged, "x = 1\n")
            self._git(repo, "add", "1_staged.py")
            _write(staged, "")  # the empty scaffold: working tree only, never staged
            untracked = repo / "2_new.py"
            _write(untracked, "y = 2\n")

            with es.index_reads(repo):
                in_index = es.read_lines(staged)
                not_in_index = es.read_lines(untracked)
            default = es.read_lines(staged)

        self.assertEqual(in_index, ["x = 1", ""])
        self.assertEqual(not_in_index, ["y = 2", ""])  # unstaged path falls back
        self.assertEqual(default, [""])  # no flag: working tree, unchanged behaviour


class DefStartLineAndSymbolTableTests(unittest.TestCase):
    SOURCE = (
        "class Solution:\n"
        "    @staticmethod\n"
        "    def decorated(self):\n"
        "        return 1\n"
        "\n"
        "    def plain(self):\n"
        "        return 2\n"
        "\n"
        "class Helper:\n"
        "    pass\n"
        "\n"
        "def freeFunction():\n"
        "    return 3\n"
    )

    def setUp(self):
        self.tree = ast.parse(self.SOURCE)
        self.table = es.symbol_table(self.tree)

    def test_flat_table_has_top_level_and_dotted_method_keys(self):
        self.assertEqual(
            set(self.table),
            {"Solution", "Solution.decorated", "Solution.plain", "Helper", "freeFunction"})

    def test_decorator_included_in_def_start_line(self):
        node = self.table["Solution.decorated"]
        self.assertEqual(es.def_start_line(node), 2)  # the @staticmethod line, not `def`

    def test_plain_method_start_line_is_its_own_def_line(self):
        node = self.table["Solution.plain"]
        self.assertEqual(es.def_start_line(node), 6)

    def test_top_level_class_has_no_dot_in_its_key(self):
        self.assertIsInstance(self.table["Helper"], ast.ClassDef)


class LeadingCommentBlockTests(unittest.TestCase):
    def test_contiguous_comment_block_is_captured(self):
        lines = ["# banner line one", "# banner line two", "def f():", "    pass"]
        self.assertEqual(es.leading_comment_block(lines, 3), (1, 2))

    def test_stops_at_a_blank_line(self):
        lines = ["# stale, unrelated comment", "", "# real banner", "def f():", "    pass"]
        self.assertEqual(es.leading_comment_block(lines, 4), (3, 3))

    def test_no_comment_directly_above_returns_none(self):
        lines = ["x = 1", "def f():", "    pass"]
        self.assertIsNone(es.leading_comment_block(lines, 2))

    def test_docstring_like_string_above_a_def_is_not_included(self):
        # Pins the 1216 kPalindromeDP shape: a bare triple-quoted string statement is a
        # normal Python statement, not a '#' comment, and must never be swept in.
        lines = ['    """', "    a stray docstring-like note", '    """', "    def f():",
                 "        pass"]
        self.assertIsNone(es.leading_comment_block(lines, 4))


class AttemptDateTests(unittest.TestCase):
    def test_symbol_suffix_wins_over_banner(self):
        banner = ["# ── Attempt · 2026-01-01 ──"]
        self.assertEqual(es.attempt_date("floodFill_20260628", banner), "2026-06-28")

    def test_banner_used_when_no_symbol_suffix(self):
        banner = ["# ── Attempt · 2026-08-23 ──"]
        self.assertEqual(es.attempt_date("StockSpanner", banner), "2026-08-23")

    def test_neither_present_is_none(self):
        self.assertIsNone(es.attempt_date("numIslands", []))


# ── build_entry: the segment-slicing contract ────────────────────────────────────────

class BuildEntryTests(unittest.TestCase):
    SOURCE = (
        "class Solution:\n"                              # 1
        "\n"                                              # 2
        "    # ── Attempt · 2026-07-29 ──\n"               # 3
        "    def target_20260729(self, x):\n"              # 4
        "        # a nested def stays inside the slice\n"  # 5
        "        def inner():\n"                           # 6
        "            return x\n"                           # 7
        "        return inner()\n"                         # 8
        "\n"                                               # 9
        "    def other(self):\n"                           # 10
        "        return 0\n"                               # 11
        "\n"                                               # 12
        "class Node:\n"                                    # 13
        "    def __init__(self, v):\n"                     # 14
        "        self.v = v\n"                              # 15
    )

    def setUp(self):
        self.lines = self.SOURCE.split("\n")
        self.tree = ast.parse(self.SOURCE)

    def _entry(self, **overrides):
        base = {"lc": 1, "variant": "v", "symbol": "target_20260729",
                "container": "Solution", "file": "f.py", "helpers": []}
        base.update(overrides)
        return base

    def test_container_segment_is_exactly_one_line(self):
        out = es.build_entry(self._entry(), self.lines, self.tree, "T", "u")
        container = out["segments"][0]
        self.assertEqual(container["kind"], "container")
        self.assertEqual((container["startLine"], container["endLine"]), (1, 1))
        self.assertEqual(container["lines"], ["class Solution:"])

    def test_attempt_slice_includes_banner_and_nested_def_to_end_lineno(self):
        out = es.build_entry(self._entry(), self.lines, self.tree, "T", "u")
        attempt = next(s for s in out["segments"] if s["kind"] == "attempt")
        self.assertEqual(attempt["startLine"], 3)   # banner line
        self.assertEqual(attempt["endLine"], 8)     # through the nested def's return
        self.assertIn("        def inner():", attempt["lines"])

    def test_attempt_date_from_symbol_suffix(self):
        out = es.build_entry(self._entry(), self.lines, self.tree, "T", "u")
        self.assertEqual(out["attemptDate"], "2026-07-29")

    def test_undated_def_has_no_banner_and_null_attempt_date(self):
        out = es.build_entry(self._entry(symbol="other"), self.lines, self.tree, "T", "u")
        attempt = next(s for s in out["segments"] if s["kind"] == "attempt")
        self.assertEqual(attempt["startLine"], 10)  # no banner above `other`
        self.assertIsNone(out["attemptDate"])

    def test_dated_class_plus_helper(self):
        out = es.build_entry(
            self._entry(symbol="Node", container=None, helpers=["Solution"]),
            self.lines, self.tree, "T", "u")
        # Segments are sorted by startLine: the "Solution" helper (line 1) sorts before
        # the "Node" attempt (line 13), regardless of helpers/attempt declaration order.
        self.assertEqual([s["kind"] for s in out["segments"]], ["helper", "attempt"])
        attempt = next(s for s in out["segments"] if s["kind"] == "attempt")
        self.assertEqual((attempt["startLine"], attempt["endLine"]), (13, 15))

    def test_segments_are_sorted_by_start_line(self):
        # helper "Node" (line 13) sorts AFTER the container (line 1) and the attempt
        # (line 3-8) even though it's declared last in `helpers`.
        out = es.build_entry(self._entry(helpers=["Node"]), self.lines, self.tree, "T", "u")
        starts = [s["startLine"] for s in out["segments"]]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual([s["kind"] for s in out["segments"]], ["container", "attempt", "helper"])

    def test_helper_not_found_raises(self):
        with self.assertRaises(es.ShowcaseError):
            es.build_entry(self._entry(helpers=["NoSuchHelper"]), self.lines, self.tree, "T", "u")

    def test_container_given_for_a_top_level_class_raises_with_specific_message(self):
        # Realistic mistake: the manifest forgot `container: null` for a design problem.
        # This must fire even when the default container ("Solution") DOES exist in the
        # file (so it can't be masked by a "container not found" error firing first).
        with self.assertRaises(es.ShowcaseError) as cm:
            es.build_entry(self._entry(symbol="Node", container="Solution"),
                            self.lines, self.tree, "T", "u")
        self.assertIn("top-level class", str(cm.exception))
        self.assertIn("container: null", str(cm.exception))

    def test_container_not_found_raises(self):
        with self.assertRaises(es.ShowcaseError) as cm:
            es.build_entry(self._entry(container="NoSuchClass"), self.lines, self.tree, "T", "u")
        self.assertIn("not found", str(cm.exception))

    def test_unknown_symbol_raises(self):
        with self.assertRaises(es.ShowcaseError):
            es.build_entry(self._entry(symbol="doesNotExist"), self.lines, self.tree, "T", "u")


# ── normalize_entry: container-default vs explicit-null ─────────────────────────────

class NormalizeEntryTests(unittest.TestCase):
    def test_omitted_container_defaults_to_solution(self):
        out = es.normalize_entry({"lc": 1, "variant": "v", "symbol": "s"}, "f.py")
        self.assertEqual(out["container"], es.DEFAULT_CONTAINER)

    def test_explicit_null_container_stays_none(self):
        out = es.normalize_entry({"lc": 1, "variant": "v", "symbol": "s", "container": None}, "f.py")
        self.assertIsNone(out["container"])

    def test_never_mutates_the_raw_entry(self):
        raw = {"lc": 1, "variant": "v", "symbol": "s"}
        es.normalize_entry(raw, "f.py")
        self.assertNotIn("container", raw)
        self.assertNotIn("file", raw)

    def test_missing_helpers_defaults_to_empty_list(self):
        out = es.normalize_entry({"lc": 1, "variant": "v", "symbol": "s"}, "f.py")
        self.assertEqual(out["helpers"], [])


# ── manifest shape validation ─────────────────────────────────────────────────────────

class ValidateEntryShapeTests(unittest.TestCase):
    def _valid(self, **overrides):
        base = {"lc": 733, "variant": "bfs", "symbol": "floodFill_20260628"}
        base.update(overrides)
        return base

    def test_valid_entry_passes(self):
        es._validate_entry_shape(self._valid())  # must not raise

    def test_unknown_key_raises(self):
        with self.assertRaises(es.ShowcaseError):
            es._validate_entry_shape(self._valid(typo_field="x"))

    def test_missing_required_key_raises(self):
        raw = self._valid()
        del raw["symbol"]
        with self.assertRaises(es.ShowcaseError):
            es._validate_entry_shape(raw)

    def test_boolean_lc_is_rejected_even_though_bool_is_an_int_subclass(self):
        with self.assertRaises(es.ShowcaseError):
            es._validate_entry_shape(self._valid(lc=True))

    def test_non_string_variant_raises(self):
        with self.assertRaises(es.ShowcaseError):
            es._validate_entry_shape(self._valid(variant=42))

    def test_helpers_must_be_a_list_of_strings(self):
        with self.assertRaises(es.ShowcaseError):
            es._validate_entry_shape(self._valid(helpers="not-a-list"))
        with self.assertRaises(es.ShowcaseError):
            es._validate_entry_shape(self._valid(helpers=[1, 2]))


# ── resolve_source_file: twin / wrong-root handling, against a synthetic tree ────────

class ResolveSourceFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.root_a = self.repo / "dsa" / "leetcode"
        self.root_b = self.repo / "dsa" / "extra"
        self._orig_roots = links.source_roots
        links.source_roots = lambda: [self.root_a, self.root_b]

    def tearDown(self):
        links.source_roots = self._orig_roots
        self._tmp.cleanup()

    def test_unique_file_is_found_by_number(self):
        path = self.root_a / "graphs" / "733_flood_fill.py"
        _write(path, "class Solution:\n    pass\n")
        found = es.resolve_source_file({"lc": 733})
        self.assertEqual(found, path)

    def test_twin_without_file_raises(self):
        _write(self.root_a / "dp" / "1216_x.py", "class Solution:\n    pass\n")
        _write(self.root_b / "backtracking" / "1216_x.py", "class Solution:\n    pass\n")
        with mock.patch.object(es, "REPO", self.repo):
            with self.assertRaises(es.ShowcaseError) as cm:
                es.resolve_source_file({"lc": 1216})
        self.assertIn("twin", str(cm.exception))

    def test_twin_with_explicit_file_is_resolved(self):
        winner = self.root_a / "dp" / "1216_x.py"
        _write(winner, "class Solution:\n    pass\n")
        _write(self.root_b / "backtracking" / "1216_x.py", "class Solution:\n    pass\n")
        with mock.patch.object(es, "REPO", self.repo):
            found = es.resolve_source_file(
                {"lc": 1216, "file": "dsa/leetcode/dp/1216_x.py"})
        self.assertEqual(found, winner)

    def test_file_outside_configured_roots_raises(self):
        outside = self.repo / "elsewhere" / "733_flood_fill.py"
        _write(outside, "class Solution:\n    pass\n")
        with mock.patch.object(es, "REPO", self.repo):
            with self.assertRaises(es.ShowcaseError) as cm:
                es.resolve_source_file({"lc": 733, "file": "elsewhere/733_flood_fill.py"})
        self.assertIn("outside", str(cm.exception))

    def test_no_matching_file_raises(self):
        with self.assertRaises(es.ShowcaseError):
            es.resolve_source_file({"lc": 9999})


# ── links.resolve_title_url: header over tracker ─────────────────────────────────────

class ResolveTitleUrlTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._orig_tracker = links.TRACKER
        tracker_path = self.dir / "dsa_progress.md"
        _write(tracker_path,
               "| Medium | [733. Flood Fill Tracker](https://tracker.example/733/) "
               "| 🟢 | 1 | 2026-12-01 |\n")
        links.TRACKER = tracker_path

    def tearDown(self):
        links.TRACKER = self._orig_tracker
        self._tmp.cleanup()

    def test_header_wins_over_tracker(self):
        path = self.dir / "733_flood_fill.py"
        _write(path, '"""\n733. Flood Fill · https://leetcode.com/problems/flood-fill/\n"""\n')
        title, url = links.resolve_title_url("733", path)
        self.assertEqual(title, "Flood Fill")
        self.assertEqual(url, "https://leetcode.com/problems/flood-fill/")

    def test_tracker_used_when_file_has_no_header(self):
        path = self.dir / "733_flood_fill.py"
        _write(path, '"""\nno header line here\n"""\n')
        title, url = links.resolve_title_url("733", path)
        self.assertEqual(title, "Flood Fill Tracker")  # tracker strips the "733. " prefix
        self.assertEqual(url, "https://tracker.example/733/")

    def test_no_file_falls_back_to_tracker_only(self):
        title, url = links.resolve_title_url("733", None)
        self.assertEqual(title, "Flood Fill Tracker")


# ── build_payload + --check staleness, end to end against a synthetic repo ──────────

class SyntheticRepoTestCase(unittest.TestCase):
    """A tiny synthetic repo tree so build_payload/_stale_reasons/main() tests never
    touch the real dsa/leetcode/ tree or dashboard/showcase.json."""

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
        _write(self.repo / "docs" / "foundations" / "dsa" / "mastery" / "dsa_progress.md",
               "| Easy | [1. Target](https://leetcode.com/problems/target/) | 🟢 | 1 | 2026-12-01 |\n")

        self._orig_roots = links.source_roots
        self._orig_tracker = links.TRACKER
        links.source_roots = lambda: [self.repo / "dsa" / "leetcode"]
        links.TRACKER = self.repo / "docs" / "foundations" / "dsa" / "mastery" / "dsa_progress.md"

        self._patches = [
            mock.patch.object(es, "REPO", self.repo),
            mock.patch.object(es, "DASHBOARD", self.dashboard),
            mock.patch.object(es, "MANIFEST", self.dashboard / "showcase.yml"),
            mock.patch.object(es, "OUT", self.dashboard / "showcase.json"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        links.source_roots = self._orig_roots
        links.TRACKER = self._orig_tracker
        self._tmp.cleanup()

    def _write_manifest(self, entries_yaml: str) -> None:
        _write(es.MANIFEST, f"schemaVersion: 1\nentries:\n{entries_yaml}")

    def _manifest_entry(self) -> dict:
        return {"lc": 1, "variant": "v", "symbol": "target_20260101"}


# ── _existing_shape_error / _stale_reasons: corrupted showcase.json shapes ──────────

class ExistingShapeErrorTests(unittest.TestCase):
    def test_non_dict_top_level_is_named(self):
        self.assertIn("top level must be an object", es._existing_shape_error(["not", "a", "dict"]))

    def test_non_list_entries_is_named(self):
        self.assertIn("'entries' must be a list", es._existing_shape_error({"entries": "nope"}))

    def test_entry_missing_required_key_is_named(self):
        for missing_key in es._REQUIRED_EXISTING_ENTRY_KEYS:
            with self.subTest(missing_key=missing_key):
                entry = {"key": "1:v", "file": "f.py", "segments": []}
                del entry[missing_key]
                error = es._existing_shape_error({"entries": [entry]})
                self.assertIn("entry 0 missing", error)
                self.assertIn(repr(missing_key), error)

    def test_segment_with_null_start_line_is_named(self):
        entry = {"key": "1:v", "file": "f.py",
                  "segments": [{"symbol": "s", "startLine": None, "endLine": 1, "lines": []}]}
        error = es._existing_shape_error({"entries": [entry]})
        self.assertIn("startLine", error)

    def test_well_formed_existing_payload_has_no_shape_error(self):
        entry = {"key": "1:v", "file": "f.py",
                  "segments": [{"symbol": "s", "startLine": 1, "endLine": 1, "lines": ["x"]}]}
        self.assertIsNone(es._existing_shape_error({"entries": [entry]}))


class StaleReasonsCorruptionTests(SyntheticRepoTestCase):
    """`_stale_reasons` against a hand-corrupted showcase.json must return one clean
    reason, never raise — the caller (`main`'s `--check`) has no try/except around it."""

    def _build(self):
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        payload, _ = es.build_payload(manifest, dt.date(2026, 9, 22))
        return payload

    def _write_existing(self, obj) -> None:
        es.OUT.parent.mkdir(parents=True, exist_ok=True)
        es.OUT.write_text(json.dumps(obj), encoding="utf-8")

    def test_non_dict_top_level_yields_one_reason(self):
        self._write_existing(["not", "a", "dict"])
        reasons = es._stale_reasons(self._build(), es.OUT)
        self.assertEqual(len(reasons), 1)
        self.assertIn("top level must be an object", reasons[0])

    def test_non_list_entries_yields_one_reason(self):
        self._write_existing({"schemaVersion": 1, "entries": "not-a-list"})
        reasons = es._stale_reasons(self._build(), es.OUT)
        self.assertEqual(len(reasons), 1)
        self.assertIn("'entries' must be a list", reasons[0])

    def test_entry_missing_segments_yields_one_reason(self):
        self._write_existing({"schemaVersion": 1,
                               "entries": [{"key": "1:v", "file": "dsa/leetcode/cat/1_target.py"}]})
        reasons = es._stale_reasons(self._build(), es.OUT)
        self.assertEqual(len(reasons), 1)
        self.assertIn("missing", reasons[0])
        self.assertIn("'segments'", reasons[0])

    def test_null_start_line_yields_one_reason(self):
        self._write_existing({"schemaVersion": 1, "entries": [
            {"key": "1:v", "file": "dsa/leetcode/cat/1_target.py",
             "segments": [{"symbol": "target_20260101", "startLine": None, "endLine": 1,
                            "lines": ["x"]}]}]})
        reasons = es._stale_reasons(self._build(), es.OUT)
        self.assertEqual(len(reasons), 1)
        self.assertIn("startLine", reasons[0])


class MainCliCorruptionTests(SyntheticRepoTestCase):
    """`--check` end to end against a corrupted showcase.json: a clean printed reason
    and exit 1, never a traceback."""

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                es.main()
                code = 0
            except SystemExit as exc:
                code = exc.code or 0
        return out.getvalue(), err.getvalue(), code

    def test_check_on_corrupted_existing_file_fails_cleanly(self):
        self._write_manifest(f"  - {self._manifest_entry()}\n".replace("'", ""))
        es.OUT.parent.mkdir(parents=True, exist_ok=True)
        es.OUT.write_text(json.dumps({"schemaVersion": 1, "entries": "not-a-list"}),
                           encoding="utf-8")
        _out, err, code = self._run(["export_showcase.py", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("'entries' must be a list", err)
        self.assertNotIn("Traceback", err)



class BuildPayloadTests(SyntheticRepoTestCase):
    def test_build_payload_produces_one_entry(self):
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        payload, warnings = es.build_payload(manifest, dt.date(2026, 9, 22))
        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(payload["entries"][0]["key"], "1:v")
        self.assertEqual(warnings, [])

    def test_duplicate_key_raises(self):
        entry = self._manifest_entry()
        manifest = {"schemaVersion": 1, "entries": [entry, dict(entry)]}
        with self.assertRaises(es.ShowcaseError):
            es.build_payload(manifest, dt.date(2026, 9, 22))

    def test_wrong_lc_raises(self):
        manifest = {"schemaVersion": 1,
                     "entries": [{"lc": 2, "variant": "v", "symbol": "target_20260101"}]}
        with self.assertRaises(es.ShowcaseError):
            es.build_payload(manifest, dt.date(2026, 9, 22))

    def test_missing_url_is_a_warning_not_a_failure(self):
        links.TRACKER = self.repo / "no-such-tracker.md"
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        _, warnings = es.build_payload(manifest, dt.date(2026, 9, 22))
        self.assertEqual(len(warnings), 1)
        self.assertIn("no LeetCode/NeetCode URL", warnings[0])


class StaleCheckTests(SyntheticRepoTestCase):
    def _build(self):
        manifest = {"schemaVersion": 1, "entries": [self._manifest_entry()]}
        return es.build_payload(manifest, dt.date(2026, 9, 22))

    def test_unchanged_payload_has_no_stale_reasons(self):
        payload, _ = self._build()
        es.OUT.parent.mkdir(parents=True, exist_ok=True)
        es.OUT.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(es._stale_reasons(payload, es.OUT), [])

    def test_edited_source_makes_the_existing_json_stale(self):
        payload, _ = self._build()
        es.OUT.parent.mkdir(parents=True, exist_ok=True)
        es.OUT.write_text(json.dumps(payload), encoding="utf-8")
        # Insert a line above the attempt so its recorded startLine..endLine slice now
        # points at the wrong text.
        rest = "\n".join(self.SOURCE.split("\n")[1:])
        _write(self.source_path, "class Solution:\n    # a newly inserted line\n" + rest)
        reasons = es._stale_reasons(payload, es.OUT)
        self.assertTrue(any("no longer match" in r for r in reasons))

    def test_removed_manifest_entry_changes_the_key_set(self):
        payload, _ = self._build()
        es.OUT.parent.mkdir(parents=True, exist_ok=True)
        es.OUT.write_text(json.dumps(payload), encoding="utf-8")
        empty_payload = {**payload, "entries": []}
        reasons = es._stale_reasons(empty_payload, es.OUT)
        self.assertTrue(any("entry set changed" in r for r in reasons))


class MainCliTests(SyntheticRepoTestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                es.main()
                code = 0
            except SystemExit as exc:
                code = exc.code or 0
        return out.getvalue(), err.getvalue(), code

    def test_stdout_mode_prints_only_json_and_writes_nothing(self):
        self._write_manifest(f"  - {self._manifest_entry()}\n".replace("'", ""))
        out, _err, code = self._run(["export_showcase.py", "--stdout"])
        self.assertEqual(code, 0)
        json.loads(out)  # raises if anything non-JSON leaked onto stdout
        self.assertFalse(es.OUT.exists())

    def test_check_mode_with_no_existing_file_succeeds_and_writes_nothing(self):
        self._write_manifest(f"  - {self._manifest_entry()}\n".replace("'", ""))
        _out, err, code = self._run(["export_showcase.py", "--check"])
        self.assertEqual(code, 0)
        self.assertIn("ok:", err)
        self.assertFalse(es.OUT.exists())

    def test_check_mode_fails_and_writes_nothing_when_stale(self):
        self._write_manifest(f"  - {self._manifest_entry()}\n".replace("'", ""))
        # Write a showcase.json that does not match the live source at all.
        es.OUT.parent.mkdir(parents=True, exist_ok=True)
        es.OUT.write_text(json.dumps({
            "schemaVersion": 1, "generatedAt": "2020-01-01",
            "entries": [{"key": "1:v", "lcNumber": 1, "variant": "v", "title": "T",
                         "url": "u", "file": "dsa/leetcode/cat/1_target.py", "symbol": "target_20260101",
                         "attemptDate": "2026-01-01",
                         "segments": [{"kind": "attempt", "symbol": "target_20260101",
                                       "startLine": 1, "endLine": 1,
                                       "lines": ["this does not match the file"]}]}]}),
            encoding="utf-8")
        before = es.OUT.read_text(encoding="utf-8")
        _out, err, code = self._run(["export_showcase.py", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("stale", err)
        self.assertEqual(es.OUT.read_text(encoding="utf-8"), before)  # --check never writes

    def test_default_mode_writes_the_file(self):
        self._write_manifest(f"  - {self._manifest_entry()}\n".replace("'", ""))
        self._run(["export_showcase.py"])
        self.assertTrue(es.OUT.exists())
        data = json.loads(es.OUT.read_text(encoding="utf-8"))
        self.assertEqual(len(data["entries"]), 1)


# ── verbatim check against a GENERATED dashboard/showcase.json, when one exists ─────

class RealShowcaseJsonVerbatimTests(unittest.TestCase):
    """Loads the dashboard/showcase.json generated by a prior `python
    scripts/export_showcase.py` run and pins that every segment is byte-identical to its
    source file, read independently of export_showcase.py's own read_lines(). Skipped until
    the adopter has generated one."""

    @classmethod
    def setUpClass(cls):
        if not es.OUT.exists():
            raise unittest.SkipTest(
                "dashboard/showcase.json not found — run `python scripts/export_showcase.py` first")
        cls.data = json.loads(es.OUT.read_text(encoding="utf-8"))

    def _source_lines(self, file_rel: str) -> list[str]:
        # Independent of read_lines(): split on "\n" then strip a trailing "\r" per line,
        # never rstrip() (trailing whitespace inside a line is part of "verbatim").
        raw = (es.REPO / file_rel).read_bytes().decode("utf-8")
        return [line[:-1] if line.endswith("\r") else line for line in raw.split("\n")]

    def test_every_segment_is_byte_identical_to_its_source_file(self):
        for entry in self.data["entries"]:
            source = self._source_lines(entry["file"])
            for seg in entry["segments"]:
                start, end = seg["startLine"], seg["endLine"]
                with self.subTest(key=entry["key"], symbol=seg["symbol"]):
                    self.assertEqual(seg["lines"], source[start - 1:end])


VALID_PAYLOAD = {
    "schemaVersion": 1, "generatedAt": "2026-09-22",
    "entries": [{"key": "1:v", "lcNumber": 1, "variant": "v", "title": "T", "url": "u",
                 "file": "dsa/leetcode/cat/1_target.py", "symbol": "target_20260101",
                 "attemptDate": "2026-01-01",
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
                errors = contract_schema.validate(payload, es.SCHEMA)
                self.assertEqual(bool(errors), should_fail, errors[:3])


if __name__ == "__main__":
    unittest.main()
