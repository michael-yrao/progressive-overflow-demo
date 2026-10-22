"""Tests for new_problem.py's premium-problem link resolver (decision
`problem-link-order-sep27`, extended by `problem-link-order-oct04`: LeetCode -> NeetCode ->
HelloInterview -> progressiveoverflow practice page).

Stdlib unittest, same fixture style as test_links.py: mock.patch.object over the module's
own path constants, with a tempfile-backed neetcode.yml/hellointerview.yml — never the
live repo files, never the network.

    python scripts/test_new_problem.py
"""
from __future__ import annotations

import ast
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import new_problem


class LoadHelloInterviewMapTests(unittest.TestCase):
    """load_hellointerview_map(): valid entries, a missing file, and a malformed entry."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_map(self, text: str) -> Path:
        p = self.tmp_path / "hellointerview.yml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_loads_valid_entries(self):
        p = self._write_map(
            "problems:\n"
            "  - {leetcode_slug: meeting-rooms, "
            "path: /learn/code/intervals/can-attend-meetings}\n"
        )
        with mock.patch.object(new_problem, "HELLOINTERVIEW_MAP_PATH", p):
            result = new_problem.load_hellointerview_map()
        self.assertEqual(
            result, {"meeting-rooms": "/learn/code/intervals/can-attend-meetings"})

    def test_missing_file_returns_empty_map_no_exception(self):
        missing = self.tmp_path / "no_such_file.yml"
        with mock.patch.object(new_problem, "HELLOINTERVIEW_MAP_PATH", missing):
            result = new_problem.load_hellointerview_map()  # must not raise
        self.assertEqual(result, {})

    def test_ignores_malformed_entry(self):
        p = self._write_map(
            "problems:\n"
            "  - {leetcode_slug: meeting-rooms, "
            "path: /learn/code/intervals/can-attend-meetings}\n"
            "  - {leetcode_slug: no-path-here}\n"
            "  - {path: /learn/code/no-slug-here}\n"
            "  - just-a-string\n"
        )
        with mock.patch.object(new_problem, "HELLOINTERVIEW_MAP_PATH", p):
            result = new_problem.load_hellointerview_map()
        self.assertEqual(
            result, {"meeting-rooms": "/learn/code/intervals/can-attend-meetings"})


class LoadNeetcodeSlugsTests(unittest.TestCase):
    """load_neetcode_slugs(): valid entries, a missing file (-> None, UNKNOWN), a
    readable-but-empty file (-> empty frozenset), and a malformed entry."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_map(self, text: str) -> Path:
        p = self.tmp_path / "neetcode.yml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_loads_valid_entries(self):
        p = self._write_map(
            "problems:\n"
            "  - {leetcode_slug: two-sum, number: 1, premium: false}\n"
            "  - {leetcode_slug: meeting-rooms, number: 252, premium: true}\n"
        )
        with mock.patch.object(new_problem, "NEETCODE_MAP_PATH", p):
            result = new_problem.load_neetcode_slugs()
        self.assertEqual(result, frozenset({"two-sum", "meeting-rooms"}))

    def test_missing_file_returns_none_not_empty_set(self):
        missing = self.tmp_path / "no_such_file.yml"
        with mock.patch.object(new_problem, "NEETCODE_MAP_PATH", missing):
            result = new_problem.load_neetcode_slugs()  # must not raise
        self.assertIsNone(result)

    def test_readable_but_empty_returns_empty_frozenset(self):
        p = self._write_map("problems: []\n")
        with mock.patch.object(new_problem, "NEETCODE_MAP_PATH", p):
            result = new_problem.load_neetcode_slugs()
        self.assertEqual(result, frozenset())
        self.assertIsNotNone(result)

    def test_ignores_malformed_entry(self):
        p = self._write_map(
            "problems:\n"
            "  - {leetcode_slug: two-sum, number: 1, premium: false}\n"
            "  - {number: 999, premium: false}\n"
            "  - just-a-string\n"
        )
        with mock.patch.object(new_problem, "NEETCODE_MAP_PATH", p):
            result = new_problem.load_neetcode_slugs()
        self.assertEqual(result, frozenset({"two-sum"}))


class ResolvePremiumLinkTests(unittest.TestCase):
    """resolve_premium_link(): the order (NeetCode -> HelloInterview -> progressiveoverflow
    practice page), and the None-vs-empty NeetCode-list distinction."""

    HI_MAP = {"meeting-rooms": "/learn/code/intervals/can-attend-meetings"}

    def test_neetcode_wins_even_when_also_in_hellointerview_map(self):
        # The order test: meeting-rooms sits in BOTH maps; NeetCode must win.
        link = new_problem.resolve_premium_link(
            "252", "meeting-rooms", frozenset({"meeting-rooms"}), self.HI_MAP)
        self.assertEqual(link.url, "https://neetcode.io/problems/meeting-rooms")
        self.assertEqual(link.judge, "NeetCode")

    def test_neetcode_url_honors_neetcode_renames(self):
        # alien-dictionary -> foreign-dictionary is a real NEETCODE_RENAMES entry.
        link = new_problem.resolve_premium_link(
            "269", "alien-dictionary", frozenset({"alien-dictionary"}), {})
        self.assertEqual(link.url, "https://neetcode.io/problems/foreign-dictionary")
        self.assertEqual(link.judge, "NeetCode")

    def test_hellointerview_wins_when_only_there(self):
        link = new_problem.resolve_premium_link("252", "meeting-rooms", frozenset(), self.HI_MAP)
        self.assertEqual(
            link.url,
            "https://www.hellointerview.com/learn/code/intervals/can-attend-meetings",
        )
        self.assertEqual(link.judge, "HelloInterview")

    def test_progressiveoverflow_fallback_when_in_neither(self):
        link = new_problem.resolve_premium_link("77", "some-other-problem", frozenset(), {})
        self.assertEqual(link.url, "https://progressiveoverflow.com/practice/77")
        self.assertEqual(link.judge, "PO")
        self.assertIn("neither NeetCode nor HelloInterview", link.reason)

    def test_unreadable_neetcode_list_falls_back_to_neetcode_mirror_unverified(self):
        # None (unreadable/unknown), not an empty set, must NOT fall through to
        # HelloInterview even though it has the slug — an unknown list is not an
        # absent one.
        link = new_problem.resolve_premium_link("252", "meeting-rooms", None, self.HI_MAP)
        self.assertEqual(link.url, "https://neetcode.io/problems/meeting-rooms")
        self.assertEqual(link.judge, "NeetCode")
        self.assertIn("unverified", link.reason)

    def test_readable_empty_neetcode_list_falls_through_to_hellointerview(self):
        # An empty-but-READABLE list is a real "NeetCode does not list it" answer, so
        # it falls through normally (unlike the None/unreadable case above).
        link = new_problem.resolve_premium_link("252", "meeting-rooms", frozenset(), self.HI_MAP)
        self.assertEqual(link.judge, "HelloInterview")

    def test_reason_names_the_same_judge_as_the_url_host(self):
        cases = [
            new_problem.resolve_premium_link(
                "252", "meeting-rooms", frozenset({"meeting-rooms"}), {}),
            new_problem.resolve_premium_link("252", "meeting-rooms", frozenset(), self.HI_MAP),
            new_problem.resolve_premium_link("77", "some-other-problem", frozenset(), {}),
            new_problem.resolve_premium_link("252", "meeting-rooms", None, {}),
        ]
        for link in cases:
            with self.subTest(url=link.url):
                self.assertIn(link.judge, link.reason)
                host_word = "progressiveoverflow" if link.judge == "PO" else link.judge.split(".")[0]
                self.assertIn(host_word.lower(), link.url.lower())


class EndToEndPremiumResolutionTests(unittest.TestCase):
    """The loaders and the resolver composed, the way both premium call sites use them."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_missing_neetcode_file_falls_back_to_neetcode_mirror(self):
        missing = self.tmp_path / "absent.yml"
        with mock.patch.object(new_problem, "NEETCODE_MAP_PATH", missing):
            neetcode_slugs = new_problem.load_neetcode_slugs()  # must not raise -> None
            link = new_problem.resolve_premium_link("1", "two-sum", neetcode_slugs, {})
        self.assertEqual(link.url, "https://neetcode.io/problems/two-sum")
        self.assertEqual(link.judge, "NeetCode")


class ChooseHeaderUrlTests(unittest.TestCase):
    """choose_header_url(): --url wins, then premium, then the synthetic-id default, then
    the LeetCode default."""

    def test_the_four_branches(self):
        no_neetcode = lambda: frozenset()  # noqa: E731
        no_hi = lambda: {}  # noqa: E731
        cases = [
            ("explicit url wins over premium and synthetic",
             ("9001", "x", "https://example.com/x", True), "https://example.com/x", False),
            ("premium resolves through the link order",
             ("77", "some-problem", None, True),
             "https://progressiveoverflow.com/practice/77", True),
            ("synthetic id defaults to the site page",
             ("9001", "sssp", None, False),
             "https://progressiveoverflow.com/practice/9001", False),
            ("ordinary id defaults to LeetCode",
             ("49", "group-anagrams", None, False),
             "https://leetcode.com/problems/group-anagrams/", False),
        ]
        for label, (number, slug, explicit, premium), want_url, want_link in cases:
            with self.subTest(label):
                url, link = new_problem.choose_header_url(
                    number, slug, explicit, premium, no_neetcode, no_hi)
                self.assertEqual(url, want_url)
                self.assertEqual(link is not None, want_link)


class NoteMissingPracticeSpecTests(unittest.TestCase):
    """verify_links() prints one NOTE when it returns a site practice url with no spec."""

    SITE_URL = "https://progressiveoverflow.com/practice/9001"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.spec_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _verify_output(self) -> str:
        buffer = io.StringIO()
        with mock.patch.object(new_problem, "SPEC_DIR", self.spec_dir), \
                contextlib.redirect_stdout(buffer):
            new_problem.verify_links("9001", "9001", self.SITE_URL, False, check=False)
        return buffer.getvalue()

    def test_note_only_when_the_spec_is_absent(self):
        self.assertIn("NOTE:", self._verify_output())
        (self.spec_dir / "9001_sssp.yml").write_text("entry: {}\n", encoding="utf-8")
        self.assertEqual(self._verify_output(), "")


class SpecScaffoldTests(unittest.TestCase):
    """A NEW scaffold with `dsa/tests/<number>_*.yml` present reads the statement and
    signature from it; an explicit --signature still wins."""

    SPEC = (
        "number: 7\n"
        "title: Demo Problem\n"
        "statement: |\n"
        "  Spec statement line.\n"
        "entry: {class: Solution, method: demoMethod}\n"
        'signature: "nums: List[int] -> int"\n'
    )

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        repo = Path(__file__).resolve().parent.parent
        template = (repo / new_problem.TEMPLATE).read_text(encoding="utf-8")
        (self.tmp_path / new_problem.TEMPLATE).parent.mkdir(parents=True)
        (self.tmp_path / new_problem.TEMPLATE).write_text(template, encoding="utf-8")
        (self.tmp_path / "dsa" / "tests").mkdir(parents=True)
        (self.tmp_path / "dsa" / "tests" / "7_demo_problem.yml").write_text(
            self.SPEC, encoding="utf-8")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _scaffold(self, extra_args: list[str]) -> str:
        argv = ["new_problem.py", "--number", "7", "--title", "Demo Problem",
                "--pattern", "demo", "--url", "https://example.com/demo",
                "--no-link-check", "--date", "2026-10-01", *extra_args]
        previous_cwd = Path.cwd()
        os.chdir(self.tmp_path)
        try:
            with mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(io.StringIO()):
                new_problem.main()
        finally:
            os.chdir(previous_cwd)
        return (self.tmp_path / new_problem.DEFAULT_ROOT / "demo"
                / "7_demo_problem.py").read_text(encoding="utf-8")

    def test_spec_fills_statement_and_signature_and_flag_wins(self):
        from_spec = self._scaffold([])
        self.assertIn("Spec statement line.", from_spec)
        self.assertNotIn(new_problem.STATEMENT_STUB, from_spec)
        self.assertIn("def demoMethod(self, nums: List[int]) -> int:", from_spec)

        (self.tmp_path / new_problem.DEFAULT_ROOT / "demo" / "7_demo_problem.py").unlink()
        flagged = self._scaffold(["--signature", "x: str -> bool"])
        self.assertIn("Spec statement line.", flagged)
        self.assertIn("def demoMethod(self, x: str) -> bool:", flagged)


class RetryBaseNameTests(unittest.TestCase):
    """A retry stub's base name is the problem's entry point, never a variant-suffixed one."""

    def test_base_name_cases(self):
        plain = ["class Solution:", "    def levelOrder_20260901(self, root):", "        pass",
                 "    def levelOrder(self, root):", "        pass"]
        variant = ["class Solution:", "    def maxSubArray_20261011(self, nums):", "        pass",
                   "    def maxSubArrayKadane(self, nums):", "        pass"]
        snake = ["class Solution:", "    def two_sum(self, nums):", "        pass"]
        cases = [
            ("plain existing name kept", plain, "", "levelOrder"),
            ("variant-suffixed, no spec: bare entry point known in file", variant, "", "maxSubArray"),
            ("variant-suffixed with a spec: the spec's entry point", variant, "maxSubArray", "maxSubArray"),
            ("snake_case untouched", snake, "", "two_sum"),
        ]
        for name, lines, spec_method, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(new_problem.retry_base_name(lines, 0, spec_method), expected)


class RetryHelperStashTests(unittest.TestCase):
    """A single-method retry stashes the module-level helpers above `class Solution` (the
    learner's UF, TrieNode, …) with the prior attempts; a def/class the stub's signature
    names (TreeNode) is the problem's interface and stays."""

    HEADER = '"""\n7. Demo Problem\n"""\nfrom typing import List, Optional\n'
    UF = "class UF:\n    def __init__(self, n):\n        self.p = list(range(n))\n"
    UF_COMMENTED = ("class UF:\n# a column-0 comment inside the class body\n# a second one\n\n"
                    "    def __init__(self, n):\n        self.p = list(range(n))\n")
    TREE_NODE = "class TreeNode:\n    def __init__(self, val=0):\n        self.val = val\n"
    HELPER = "class Helper:\n    def run(self):\n        return 1\n"
    SOLVED = "    def find(self, n: int) -> int:\n        return n + 1\n"
    SOLVED_TREE = "    def find(self, root: Optional[TreeNode]) -> int:\n        return 1\n"
    OLD_ATTEMPT = "    def find_20260901(self, n: int) -> int:\n        return n\n"
    MARKER = new_problem.MODULE_SECTION_MARKER

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)
        self.source = self.tmp_path / new_problem.DEFAULT_ROOT / "demo" / "7_demo_problem.py"
        self.stash = self.tmp_path / new_problem.DEFAULT_ROOT / ".history" / "7_demo_problem.txt"

    def _source_text(self, gap: str, solved: str) -> str:
        return f"{self.HEADER}\n\n{gap}\n\nclass Solution:\n{solved}"

    def _retry(self, source_text: str, existing_stash: str | None) -> tuple[str, str]:
        self.source.parent.mkdir(parents=True)
        self.source.write_text(source_text, encoding="utf-8")
        if existing_stash is not None:
            self.stash.parent.mkdir(parents=True)
            self.stash.write_text(existing_stash, encoding="utf-8")
        argv = ["new_problem.py", "--number", "7", "--title", "Demo Problem",
                "--pattern", "demo", "--no-link-check", "--date", "2026-10-02"]
        previous_cwd = Path.cwd()
        os.chdir(self.tmp_path)
        try:
            with mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(io.StringIO()):
                new_problem.main()
        finally:
            os.chdir(previous_cwd)
        return self.source.read_text(encoding="utf-8"), self.stash.read_text(encoding="utf-8")

    def test_retry_extract_moves_only_helpers_the_signature_does_not_name(self):
        cases = [
            {
                "label": "helper class moves with a marker",
                "source": self._source_text(self.UF, self.SOLVED),
                "existing_stash": None,
                "source_has": [new_problem.POINTER_PREFIX],
                "source_lacks": ["class UF"],
                "stash": f"{self.SOLVED}\n{self.MARKER}\n{self.UF}",
            },
            {
                "label": "class the signature names stays",
                "source": self._source_text(self.TREE_NODE, self.SOLVED_TREE),
                "existing_stash": None,
                "source_has": [f"{self.TREE_NODE}\n\nclass Solution:"],
                "stash": self.SOLVED_TREE,
            },
            {
                "label": "comment and constant stay",
                "source": self._source_text("# a note\nLIMIT = 10\n", self.SOLVED),
                "existing_stash": None,
                "source_has": ["# a note\nLIMIT = 10\n"],
                "stash": self.SOLVED,
            },
            {
                "label": "named class stays, other helper moves",
                "source": self._source_text(f"{self.TREE_NODE}\n\n{self.HELPER}", self.SOLVED_TREE),
                "existing_stash": None,
                "source_has": [f"{self.TREE_NODE}\n\nclass Solution:"],
                "source_lacks": ["class Helper"],
                "stash": f"{self.SOLVED_TREE}\n{self.MARKER}\n{self.HELPER}",
            },
            {
                "label": "column-0 comments inside a helper stay with it",
                "source": self._source_text(self.UF_COMMENTED, self.SOLVED),
                "existing_stash": None,
                "source_has": [new_problem.POINTER_PREFIX],
                "source_lacks": ["class UF", "self.p = list(range(n))"],
                "stash": f"{self.SOLVED}\n{self.MARKER}\n{self.UF_COMMENTED}",
                "parses": True,
            },
            {
                "label": "comment directly above Solution stays attached to it",
                "source": (f"{self.HEADER}\n\n{self.UF_COMMENTED}\n# banner for Solution\n"
                           f"class Solution:\n{self.SOLVED}"),
                "existing_stash": None,
                "source_has": ["# banner for Solution\nclass Solution:"],
                "source_lacks": ["class UF", "self.p = list(range(n))"],
                "stash": f"{self.SOLVED}\n{self.MARKER}\n{self.UF_COMMENTED}",
                "parses": True,
            },
            {
                "label": "merge into an old-format stash keeps the sections apart",
                "source": self._source_text(self.UF, self.SOLVED),
                "existing_stash": self.OLD_ATTEMPT,
                "source_has": [new_problem.POINTER_PREFIX],
                "source_lacks": ["class UF"],
                "stash": f"{self.SOLVED}\n{self.OLD_ATTEMPT}\n{self.MARKER}\n{self.UF}",
            },
        ]
        for case in cases:
            with self.subTest(case["label"]):
                self.setUp()
                source_after, stash_after = self._retry(case["source"], case["existing_stash"])
                for piece in case["source_has"]:
                    self.assertIn(piece, source_after)
                for piece in case.get("source_lacks", []):
                    self.assertNotIn(piece, source_after)
                self.assertEqual(stash_after, case["stash"])
                if case.get("parses"):
                    ast.parse(source_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
