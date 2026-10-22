"""Tests for links.py — the judge-label helper and link_line's use of it.

Stdlib unittest, same style as test_gamify.py / test_remaining.py:

    python scripts/test_links.py
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import links


class JudgeLabelTests(unittest.TestCase):
    """The four named judges, plus the bare-hostname fallback for anything else."""

    def test_leetcode(self):
        self.assertEqual(links.judge_label("https://leetcode.com/problems/two-sum/"), "LC")

    def test_neetcode(self):
        self.assertEqual(links.judge_label("https://neetcode.io/problems/two-sum"), "NC")

    def test_kattis(self):
        self.assertEqual(
            links.judge_label("https://open.kattis.com/problems/shortestpath3"), "Kattis")

    def test_cses(self):
        self.assertEqual(
            links.judge_label("https://cses.fi/problemset/task/1673"), "CSES")

    def test_unknown_host_falls_back_to_hostname(self):
        self.assertEqual(
            links.judge_label("https://codeforces.com/problemset/problem/4/A"),
            "codeforces.com")

    def test_leading_www_is_stripped(self):
        # A judge fronted by "www." (unlike the four named hosts above) still reports its
        # bare hostname, not the "www." prefix.
        self.assertEqual(
            links.judge_label("https://www.spoj.com/problems/TEST/"), "spoj.com")

    def test_hellointerview_with_www(self):
        # The real HelloInterview URLs carry "www." (hellointerview.yml stores paths
        # only, joined onto HELLOINTERVIEW_HOST, which includes it).
        self.assertEqual(
            links.judge_label(
                "https://www.hellointerview.com/learn/code/intervals/can-attend-meetings"),
            "HelloInterview")

    def test_progressiveoverflow_practice_page(self):
        self.assertEqual(
            links.judge_label("https://progressiveoverflow.com/practice/9001"),
            "PO")

    def test_hellointerview_without_www(self):
        self.assertEqual(
            links.judge_label(
                "https://hellointerview.com/learn/code/intervals/can-attend-meetings"),
            "HelloInterview")


class LinkLineJudgeLabelTests(unittest.TestCase):
    """link_line() on a Kattis-sourced problem prints the `Kattis` label, not `LC`.

    Builds a scratch tree — `<tmp>/dsa/leetcode/graphs/9001_x.py` — and monkeypatches the
    module's repo-relative constants to point at it, so nothing here touches the real repo.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        graphs_dir = self.repo_root / "dsa" / "leetcode" / "graphs"
        graphs_dir.mkdir(parents=True)
        self.solution = graphs_dir / "9001_x.py"
        self.solution.write_text(
            '"""\n'
            "9001. Single Source Shortest Path, Negative Weights   ·   "
            "https://open.kattis.com/problems/shortestpath3\n"
            'Pattern: graphs\n'
            '"""\n'
            "class Solution:\n"
            "    pass\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_kattis_problem_gets_kattis_label(self):
        with mock.patch.object(links, "REPO_ROOT", self.repo_root), \
             mock.patch.object(links, "source_roots", return_value=[self.repo_root / "dsa" / "leetcode"]), \
             mock.patch.object(links, "TRACKER", self.repo_root / "no_such_tracker.md"):
            line = links.link_line("9001")

        self.assertIsNotNone(line)
        self.assertTrue(
            line.endswith("· [Kattis](https://open.kattis.com/problems/shortestpath3)"),
            line,
        )


class ScheduleLinkLineTests(unittest.TestCase):
    """schedule_link_line() adds `[PO]` only when a spec exists and the judge isn't the site."""

    def test_schedule_link_line_table(self):
        site = "https://progressiveoverflow.com/practice"
        cases = [
            ("spec + LC", "1", "https://leetcode.com/problems/target/", True,
             f"· [LC](https://leetcode.com/problems/target/) · [PO]({site}/1)"),
            ("spec + NC", "2", "https://neetcode.io/problems/target/", True,
             f"· [NC](https://neetcode.io/problems/target/) · [PO]({site}/2)"),
            ("no spec", "3", "https://leetcode.com/problems/target/", False,
             "· [LC](https://leetcode.com/problems/target/)"),
            ("judge is the site", "4", f"{site}/4", True,
             f"· [PO]({site}/4)"),
        ]
        for name, number, url, has_spec, expected_tail in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                solutions = root / "dsa" / "leetcode" / "graphs"
                solutions.mkdir(parents=True)
                (solutions / f"{number}_x.py").write_text(
                    f'"""\n{number}. Target   ·   {url}\n"""\n', encoding="utf-8")
                (root / "dsa" / "tests").mkdir(parents=True)
                if has_spec:
                    (root / "dsa" / "tests" / f"{number}_x.yml").write_text("x: 1\n", encoding="utf-8")
                with mock.patch.object(links, "REPO_ROOT", root), \
                     mock.patch.object(links, "source_roots", return_value=[root / "dsa" / "leetcode"]), \
                     mock.patch.object(links, "TRACKER", root / "no_such_tracker.md"):
                    line = links.schedule_link_line(number)
                self.assertTrue(line.endswith(expected_tail), line)
                self.assertEqual(line.count(f"]({site}/"), 1 if has_spec else 0, line)


class ScheduleLinkLineSiteNumbersTests(unittest.TestCase):
    def test_schedule_link_line_site_numbers(self):
        """A set decides the `[PO]` link; None keeps the local-spec check."""
        cases = [
            ("in set, no local spec", frozenset({7}), False, 1),
            ("not in set, local spec exists", frozenset({8}), True, 0),
            ("None, local spec exists", None, True, 1),
        ]
        for name, site_numbers, has_spec, expected_po_links in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                solutions = root / "dsa" / "leetcode" / "graphs"
                solutions.mkdir(parents=True)
                (solutions / "7_x.py").write_text(
                    '"""\n7. Target   ·   https://leetcode.com/problems/target/\n"""\n', encoding="utf-8")
                (root / "dsa" / "tests").mkdir(parents=True)
                if has_spec:
                    (root / "dsa" / "tests" / "7_x.yml").write_text("x: 1\n", encoding="utf-8")
                with mock.patch.object(links, "REPO_ROOT", root), \
                     mock.patch.object(links, "source_roots", return_value=[root / "dsa" / "leetcode"]), \
                     mock.patch.object(links, "TRACKER", root / "no_such_tracker.md"):
                    line = links.schedule_link_line("7", site_numbers=site_numbers)
                self.assertEqual(line.count(f"]({links.SITE_PRACTICE_URL_PREFIX}"), expected_po_links, line)


class IsRealTitleParentheticalTests(unittest.TestCase):
    def test_variant_tag_not_in_slug_is_not_real(self):
        self.assertFalse(
            links._is_real_title_parenthetical("DFS", "https://leetcode.com/problems/number-of-islands/"))

    def test_title_fragment_baked_into_slug_is_real(self):
        self.assertTrue(
            links._is_real_title_parenthetical(
                "Prefix Tree", "https://leetcode.com/problems/implement-trie-prefix-tree/"))

    def test_no_url_is_never_real(self):
        self.assertFalse(links._is_real_title_parenthetical("DFS", None))


class ResolveTitleUrlVariantStripTests(unittest.TestCase):
    """The trailing ` (variant)` strip applies to a tracker-sourced title only."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _resolve(self, tracker_cell: str, header: str | None) -> tuple[str | None, str | None]:
        tracker = self.tmp / "dsa_progress.md"
        tracker.write_bytes(f"| Easy | {tracker_cell} | 🟢 | 1 | 2026-12-01 |\n".encode("utf-8"))
        path = None
        if header is not None:
            path = self.tmp / "1_target.py"
            path.write_bytes(f'"""\n{header}\n"""\n'.encode("utf-8"))
        with mock.patch.object(links, "TRACKER", tracker):
            return links.resolve_title_url("1", path)

    def test_title_resolution_table(self):
        cases = [
            ("tracker variant stripped",
             "[1. Target (DFS)](https://leetcode.com/problems/target/)", None, "Target"),
            ("technique spoiler stripped",
             "[1. Graph Valid Tree (Union-Find)](https://leetcode.com/problems/graph-valid-tree/)",
             None, "Graph Valid Tree"),
            ("real parenthetical kept",
             "[1. Target (Prefix Tree)](https://leetcode.com/problems/target-prefix-tree/)",
             None, "Target (Prefix Tree)"),
            ("header title untouched",
             "[1. Target](https://leetcode.com/problems/target/)",
             "1. Target (DFS) · https://leetcode.com/problems/target/", "Target (DFS)"),
        ]
        for name, cell, header, expected in cases:
            with self.subTest(name):
                self.assertEqual(self._resolve(cell, header)[0], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
