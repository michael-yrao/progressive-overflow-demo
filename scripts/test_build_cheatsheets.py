"""Tests for build_cheatsheets.py — the /learn cheat-sheet generator.

Stdlib unittest, matching test_gamify.py's header/runner style. Run it with:

    python scripts/test_build_cheatsheets.py

Covers: fence-aware heading splitting, the per-heading parsers (one fixture doc per
current doc style — see docs/foundations/dsa/patterns/README.md's "The machine-readable
contract" for the doc styles), label-vs-id resolution for both notWhen and the top-level
signals table, the Complexity-line grammar's edge cases, check_cheatsheets.py's
hard-failure conditions, and a GOLDEN test that builds from the REAL docs and compares
against scripts/fixtures/cheat-sheets.seed.json.

⚠️ The golden test is expected to fail until every technique doc is re-headed to the
contract. It fails with a readable per-technique/per-field diff, not a crash, so the
remaining gap is legible from the test output alone.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_cheatsheets as bc
import check_cheatsheets as cc

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ── fixture docs, one per current doc style ──────────────────────────────────────────

# Style A: already carries When/Template/Practice/Common pitfalls (dummy_node.md's
# family); this fixture also exercises fence-awareness (a `##`-looking line inside the
# python fence) and both notWhen resolution branches (a real technique id vs. a label).
STYLE_A_DOC = """# Widget Pattern

## When to reach for it
This is one sentence about widgets, spanning the whole first paragraph here.
Some prose can continue on the next physical line of the same paragraph.

- widget signal one
- widget signal two

## Picking feature
The one discriminating feature, as a sentence.

- **not sliding-window** — the window itself is not the point here
- **not Gizmo** — no dedicated page exists for gizmos

## Template: All arrangements
*When:* every arrangement must be produced
```python
def widget(items):
    ## this looks like a heading but is a comment inside the fence
    return items
```
Complexity: O(n · n!) time · O(n) space — n! arrangements, each built in O(n) — dominates

## Common pitfalls
- pitfall one
- pitfall two, continued
  on a second physical line

## Practice
- LC 1 — Two Sum
- [2. Add Two Numbers](https://leetcode.com/problems/add-two-numbers/)
- a bullet matching neither Practice pattern is silently skipped
"""

# Style B: re-headed from "Quick Reference / 1. Pattern" (backtracking.md's family) —
# once re-headed the section shape is identical to style A, so this fixture instead
# covers a template with NO `*When:*` line and a doc with no notWhen bullets at all.
STYLE_B_DOC = """# Gadget Patterns

## When to reach for it
Gadgets solve problems whose shape is a gadget.

- gadget signal

## Picking feature
Gadgets apply whenever a gadget is needed.

## Template: The one template
```python
def gadget():
    return 1
```
Complexity: O(1) time · O(1) space — constant work

## Common pitfalls
- forgetting the gadget

## Practice
- LC 99 — Ninety Nine
"""

# An algorithm write-up (floyd_warshall.md's family): several notWhen labels reusing the
# SAME label text (as floyd_warshall.md's seed entry does for "Dijkstra" twice), and a
# complexity why-clause that itself contains " — ".
ALGORITHM_DOC = """# Some Algorithm

## When to reach for it
Use it when the shape matches.

- the shape signal

## Picking feature
The whole-graph feature.

- **not Dijkstra** — one source, non-negative weights
- **not Dijkstra** — all pairs, large sparse graph — n times Dijkstra wins

## Template: The procedure
```python
def solve():
    pass
```
Complexity: O(n^3) time · O(n^2) space — three nested loops — independent of edge count

## Common pitfalls
- a pitfall

## Practice
- LC 1334 — Find the City
"""


def _sections(doc_text: str) -> list[tuple[str, list[str]]]:
    return bc.split_h2_sections(doc_text)


class FenceAwareSplitTests(unittest.TestCase):
    def test_heading_count_and_order(self):
        sections = _sections(STYLE_A_DOC)
        self.assertEqual([h for h, _ in sections],
                         [bc.HEADING_WHEN, bc.HEADING_PICKING, "Template: All arrangements",
                          bc.HEADING_PITFALLS, bc.HEADING_PRACTICE])

    def test_comment_inside_fence_is_not_a_heading(self):
        sections = _sections(STYLE_A_DOC)
        template_body = bc.find_section(sections, "Template: All arrangements")
        # the fake heading line must have SURVIVED as body text, not split the section
        joined = "\n".join(template_body)
        self.assertIn("## this looks like a heading but is a comment inside the fence", joined)

    def test_h1_extraction_strips_emoji_and_patterns_suffix(self):
        text = "# 🧠 Some Technique Patterns\n\nbody\n"
        self.assertEqual(bc.extract_h1(text), "Some Technique")

    def test_h1_without_patterns_suffix_is_unchanged(self):
        text = "# Dummy Node (Sentinel)\n\nbody\n"
        self.assertEqual(bc.extract_h1(text), "Dummy Node (Sentinel)")


class CleanMarkdownTests(unittest.TestCase):
    """clean()'s three unwrap rules — bold/italic/link — plus the flanking guard that keeps
    a spaced multiplication like `` `r * cols + c` `` from being read as italics (B2's
    seed pitfalls carry none of these three markup kinds, so the docs' own italics/links
    are stripped here rather than left for C1 to rewrite prose)."""

    def test_bold_is_stripped(self):
        self.assertEqual(bc.clean("**different speeds**"), "different speeds")

    def test_single_asterisk_italic_is_unwrapped(self):
        self.assertEqual(bc.clean("check the stack *before* popping"),
                         "check the stack before popping")

    def test_link_is_reduced_to_its_text(self):
        self.assertEqual(bc.clean("a pass-through payload. See [recursion](recursion.md)."),
                         "a pass-through payload. See recursion.")

    def test_spaced_multiplication_in_backticks_is_not_italics(self):
        self.assertEqual(bc.clean("flatten `(r, c)` -> `r * cols + c`"),
                         "flatten `(r, c)` -> `r * cols + c`")

    def test_backticks_pass_through_untouched(self):
        self.assertEqual(bc.clean("use `collections.deque`"), "use `collections.deque`")


class WhenSectionTests(unittest.TestCase):
    def test_paragraph_and_first_bullet_list(self):
        lines = bc.find_section(_sections(STYLE_A_DOC), bc.HEADING_WHEN)
        when_to_use, signals = bc.parse_when_section(lines)
        self.assertEqual(when_to_use, "This is one sentence about widgets, spanning the "
                                      "whole first paragraph here. Some prose can continue "
                                      "on the next physical line of the same paragraph.")
        self.assertEqual(signals, ["widget signal one", "widget signal two"])

    def test_missing_section_degrades_to_todo_and_empty(self):
        when_to_use, signals = bc.parse_when_section([])
        self.assertEqual(when_to_use, bc.TODO)
        self.assertEqual(signals, [])


class PickingSectionTests(unittest.TestCase):
    def test_id_and_label_resolution(self):
        lines = bc.find_section(_sections(STYLE_A_DOC), bc.HEADING_PICKING)
        feature, not_when = bc.parse_picking_section(lines)
        self.assertEqual(feature, "The one discriminating feature, as a sentence.")
        self.assertEqual(not_when, [
            {"technique": "sliding-window",
             "because": "the window itself is not the point here"},
            {"technique": "Gizmo", "page": False,
             "because": "no dedicated page exists for gizmos"},
        ])

    def test_no_not_when_bullets_is_an_empty_list(self):
        lines = bc.find_section(_sections(STYLE_B_DOC), bc.HEADING_PICKING)
        _feature, not_when = bc.parse_picking_section(lines)
        self.assertEqual(not_when, [])

    def test_repeated_label_keeps_both_entries(self):
        lines = bc.find_section(_sections(ALGORITHM_DOC), bc.HEADING_PICKING)
        _feature, not_when = bc.parse_picking_section(lines)
        self.assertEqual(len(not_when), 2)
        self.assertTrue(all(nw["technique"] == "Dijkstra" and nw.get("page") is False
                            for nw in not_when))
        self.assertEqual(not_when[1]["because"],
                         "all pairs, large sparse graph — n times Dijkstra wins")


class ComplexityLineTests(unittest.TestCase):
    def test_time_with_interior_dot_and_why_with_em_dash(self):
        line = "Complexity: O(n · n!) time · O(n) space — n! arrangements — dominates"
        got = bc.parse_complexity_line(line)
        self.assertEqual(got, {"time": "O(n · n!)", "space": "O(n)",
                               "why": "n! arrangements — dominates"})

    def test_simple_line(self):
        got = bc.parse_complexity_line("Complexity: O(1) time · O(1) space — constant work")
        self.assertEqual(got, {"time": "O(1)", "space": "O(1)", "why": "constant work"})

    def test_malformed_line_is_todo_triple(self):
        got = bc.parse_complexity_after(["not a complexity line"], 0)
        self.assertEqual(got, {"time": bc.TODO, "space": bc.TODO, "why": bc.TODO})


class TemplateSectionTests(unittest.TestCase):
    def test_when_code_and_complexity(self):
        heading, body = _sections(STYLE_A_DOC)[2]
        variant = bc.parse_template_section(heading, body)
        self.assertEqual(variant["title"], "All arrangements")
        self.assertEqual(variant["when"], "every arrangement must be produced")
        self.assertIn("def widget(items):", variant["code"])
        self.assertNotIn("```", variant["code"])
        self.assertEqual(variant["complexity"]["time"], "O(n · n!)")

    def test_template_without_when_line_omits_the_key(self):
        heading, body = _sections(STYLE_B_DOC)[2]
        variant = bc.parse_template_section(heading, body)
        self.assertNotIn("when", variant)


class PitfallsAndPracticeTests(unittest.TestCase):
    def test_pitfalls_join_continuation_lines(self):
        lines = bc.find_section(_sections(STYLE_A_DOC), bc.HEADING_PITFALLS)
        self.assertEqual(bc.parse_pitfalls_section(lines),
                         ["pitfall one", "pitfall two, continued on a second physical line"])

    def test_practice_both_bullet_styles_and_skips_unmatched(self):
        lines = bc.find_section(_sections(STYLE_A_DOC), bc.HEADING_PRACTICE)
        self.assertEqual(bc.parse_practice_section(lines), [
            {"lcNumber": 1, "title": "Two Sum"},
            {"lcNumber": 2, "title": "Add Two Numbers"},
        ])

    def test_missing_practice_heading_is_empty(self):
        self.assertEqual(bc.parse_practice_section([]), [])


class SignalTableResolutionTests(unittest.TestCase):
    """The intuition_cheatsheet.md table is already in its final form (untouched by the
    concurrent doc re-heading), so these exercise the real file directly."""

    def test_matches_seed_exactly(self):
        seed = json.loads((FIXTURES / "cheat-sheets.seed.json").read_text(encoding="utf-8"))
        self.assertEqual(bc.parse_signal_table(), seed["signals"])

    def test_id_row_omits_page(self):
        rows = bc.parse_signal_table()
        two_pointer = next(r for r in rows if r["reach"] == "two-pointer")
        self.assertNotIn("page", two_pointer)
        self.assertEqual(two_pointer["note"], "converge from ends")

    def test_label_row_carries_page_false(self):
        rows = bc.parse_signal_table()
        heap = next(r for r in rows if r["see"].startswith('"Kth largest'))
        self.assertEqual(heap["reach"], "heap")
        self.assertIs(heap["page"], False)

    def test_default_note_extracts_parenthetical(self):
        self.assertEqual(bc.default_note("binary search (min/max boundary)"),
                         "min/max boundary")
        self.assertEqual(bc.default_note("sliding window"), "")


# ── decision tree fixtures ────────────────────────────────────────────────────────────

# Covers: 2-space indent (the outer list), a blank line inside the list (never ends it), a
# continuation line joined onto an inner node's own label, a leaf whose label carries its
# own parenthetical plus a trailing note, a bold no-page leaf, a `?` question label, and
# trailing prose after the list (ends it, excluded from the parsed bullets).
DECISION_TREE_SECTION = """## Decision tree

Intro prose describing the tree; not part of the list.

- What is the **shape**?
  - Array / string
    - Sorted — or can you sort it?
      continuation text that joins onto the sorted bullet's own label
      - Pair/triple summing to a target → [two pointers](techniques/two_pointer.md) (converge from ends)
    - "Kth largest / smallest" → **heap**

  - Linked list
    - "Reverse" (in place) → [in-place reversal](techniques/in_place_reversal.md) (rewire next)

Trailing prose that should never be treated as a bullet.

## Single-trick techniques

unrelated section, must not be parsed as part of the tree
"""

# Covers: a consistent 4-space-per-level indent (tolerance beyond the doc's usual 2).
FOUR_SPACE_DECISION_TREE_SECTION = """## Decision tree

- Root question?
    - Child one
        - Leaf one → [two pointers](techniques/two_pointer.md)
    - Child two → **heap**

## Next
"""

# Two root bullets at indent 0 — parse_decision_tree must reject this.
TWO_ROOTS_DECISION_TREE_SECTION = """## Decision tree

- Root one
  - child one → **heap**
- Root two
  - child two → **quickselect**

## Next
"""

# An arrow present but neither a link nor a bold tail follows it.
MALFORMED_LEAF_DECISION_TREE_SECTION = """## Decision tree

- Root question?
  - Something → not a link or bold

## Next
"""


def _decision_tree_lines(section_text: str) -> list[str]:
    return bc.find_h2_section_raw(section_text, bc.DECISION_TREE_HEADING)


def assert_valid_decision_node(node: dict, path: str = "root") -> None:
    """Hand-rolled recursive check that `node` (and everything under it) matches the
    schema's decisionNode `oneOf`: a leaf carries exactly {label, reach, reachLabel,
    note[, page]} (and `page`, if present, is `False`); an inner node carries exactly
    {label, children} with at least one child, each itself valid."""
    is_leaf, is_inner = "reach" in node, "children" in node
    assert is_leaf != is_inner, f"{path}: must be a leaf XOR an inner node, got {node!r}"
    if is_leaf:
        assert set(node) <= {"label", "reach", "reachLabel", "note", "page"}, path
        assert isinstance(node["label"], str) and isinstance(node["reach"], str), path
        assert isinstance(node["reachLabel"], str), path
        assert isinstance(node["note"], str), path
        assert "page" not in node or node["page"] is False, path
    else:
        assert set(node) == {"label", "children"}, path
        assert isinstance(node["children"], list) and node["children"], path
        for i, child in enumerate(node["children"]):
            assert_valid_decision_node(child, f"{path}.children[{i}]")


class DecisionTreeParserTests(unittest.TestCase):
    def test_depth_and_continuation_are_preserved(self):
        root = bc.parse_decision_tree(_decision_tree_lines(DECISION_TREE_SECTION))
        self.assertEqual(root["label"], "What is the shape?")
        array_string = root["children"][0]
        self.assertEqual(array_string["label"], "Array / string")
        sorted_node = array_string["children"][0]
        self.assertEqual(sorted_node["label"], "Sorted — or can you sort it? continuation "
                                               "text that joins onto the sorted bullet's "
                                               "own label")
        self.assertEqual(len(sorted_node["children"]), 1)

    def test_blank_line_inside_list_does_not_end_it(self):
        root = bc.parse_decision_tree(_decision_tree_lines(DECISION_TREE_SECTION))
        # "Linked list" sits AFTER the blank line inside the list; if the blank line had
        # ended the list it would never make it into the tree.
        labels = [c["label"] for c in root["children"]]
        self.assertIn("Linked list", labels)

    def test_trailing_prose_after_the_list_is_excluded(self):
        items = bc.collect_nested_bullets(_decision_tree_lines(DECISION_TREE_SECTION))
        joined = " ".join(text for _indent, text in items)
        self.assertNotIn("Trailing prose", joined)

    def test_link_leaf_id_and_note(self):
        root = bc.parse_decision_tree(_decision_tree_lines(DECISION_TREE_SECTION))
        sorted_node = root["children"][0]["children"][0]
        leaf = sorted_node["children"][0]
        self.assertEqual(leaf, {"label": "Pair/triple summing to a target",
                                "reach": "two-pointer", "reachLabel": "two pointers",
                                "note": "converge from ends"})

    def test_leaf_label_with_its_own_parenthetical_plus_trailing_note(self):
        root = bc.parse_decision_tree(_decision_tree_lines(DECISION_TREE_SECTION))
        linked_list = root["children"][1]
        leaf = linked_list["children"][0]
        self.assertEqual(leaf, {"label": '"Reverse" (in place)',
                                "reach": "in-place-reversal",
                                "reachLabel": "in-place reversal", "note": "rewire next"})

    def test_bold_leaf_is_page_false_with_empty_note(self):
        root = bc.parse_decision_tree(_decision_tree_lines(DECISION_TREE_SECTION))
        heap_leaf = root["children"][0]["children"][1]
        self.assertEqual(heap_leaf, {"label": '"Kth largest / smallest"', "reach": "heap",
                                     "reachLabel": "heap", "note": "", "page": False})

    def test_reach_label_is_the_authors_link_or_bold_text(self):
        root = bc.parse_decision_tree(_decision_tree_lines(DECISION_TREE_SECTION))
        link_leaf = root["children"][0]["children"][0]["children"][0]
        self.assertEqual(link_leaf["reachLabel"], "two pointers")
        bold_leaf = root["children"][0]["children"][1]
        self.assertEqual(bold_leaf["reachLabel"], bold_leaf["reach"])

    def test_question_label_keeps_its_question_mark(self):
        root = bc.parse_decision_tree(_decision_tree_lines(DECISION_TREE_SECTION))
        self.assertTrue(root["label"].endswith("?"))

    def test_clean_runs_on_labels_and_notes_not_on_the_stem(self):
        section = """## Decision tree

- Root question?
  - **Bold** cue → [*two* pointers](techniques/two_pointer.md) (a *clean* note)

## Next
"""
        root = bc.parse_decision_tree(_decision_tree_lines(section))
        leaf = root["children"][0]
        self.assertEqual(leaf["label"], "Bold cue")
        self.assertEqual(leaf["note"], "a clean note")
        self.assertEqual(leaf["reach"], "two-pointer")
        self.assertEqual(leaf["reachLabel"], "two pointers")

    def test_four_space_indent_is_tolerated(self):
        root = bc.parse_decision_tree(_decision_tree_lines(FOUR_SPACE_DECISION_TREE_SECTION))
        self.assertEqual(root["label"], "Root question?")
        self.assertEqual(len(root["children"]), 2)
        child_one = root["children"][0]
        self.assertEqual(child_one["children"][0]["reach"], "two-pointer")
        self.assertEqual(root["children"][1]["reach"], "heap")

    def test_malformed_leaf_fails_soft_and_is_reported(self):
        problems: list[str] = []
        root = bc.parse_decision_tree(
            _decision_tree_lines(MALFORMED_LEAF_DECISION_TREE_SECTION), problems)
        self.assertTrue(any("malformed leaf" in p for p in problems))
        leaf = root["children"][0]
        self.assertEqual(leaf["page"], False)
        self.assertEqual(leaf["reachLabel"], leaf["reach"])

    def test_two_roots_is_rejected(self):
        problems: list[str] = []
        root = bc.parse_decision_tree(
            _decision_tree_lines(TWO_ROOTS_DECISION_TREE_SECTION), problems)
        self.assertIsNone(root)
        self.assertTrue(any("exactly one root" in p for p in problems))

    def test_arrow_inside_label_with_link_tail_splits_at_the_last_arrow(self):
        section = """## Decision tree

- Root question?
  - a → b cue → [two pointers](techniques/two_pointer.md) (note)

## Next
"""
        root = bc.parse_decision_tree(_decision_tree_lines(section))
        leaf = root["children"][0]
        self.assertEqual(leaf, {"label": "a → b cue", "reach": "two-pointer",
                                "reachLabel": "two pointers", "note": "note"})

    def test_arrow_inside_label_without_a_tail_is_malformed_and_orphans_its_children(self):
        section = """## Decision tree

- Root?
  - a → b cue
    - orphan child → **heap**

## Next
"""
        problems: list[str] = []
        root = bc.parse_decision_tree(_decision_tree_lines(section), problems)
        self.assertTrue(any("malformed leaf" in p for p in problems))
        self.assertTrue(any("nested under a leaf, dropped" in p for p in problems))
        self.assertEqual(root["children"],
                         [{"label": "a", "reach": "b cue", "reachLabel": "b cue",
                           "note": "", "page": False}])

    def test_missing_section_is_a_warning_and_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "fixture.md"
            doc.write_text("# X\n\nno decision tree here\n", encoding="utf-8")
            with patch.object(bc, "INTUITION_DOC", doc):
                warnings: list[str] = []
                tree = bc.build_decision_tree(warnings)
        self.assertIsNone(tree)
        self.assertTrue(any("Decision tree" in w for w in warnings))

    def test_missing_section_makes_build_payload_omit_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "fixture.md"
            doc.write_text("# X\n\nno decision tree here\n", encoding="utf-8")
            with patch.object(bc, "INTUITION_DOC", doc):
                payload = bc.build_payload(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), [])
        self.assertNotIn("decisionTree", payload)

    def test_decision_tree_leaves_flattens_dfs(self):
        root = bc.parse_decision_tree(_decision_tree_lines(FOUR_SPACE_DECISION_TREE_SECTION))
        leaves = bc.decision_tree_leaves(root)
        self.assertEqual([leaf["reach"] for leaf in leaves], ["two-pointer", "heap"])

    def test_real_doc_decision_tree_matches_the_schema_shape(self):
        warnings: list[str] = []
        tree = bc.build_decision_tree(warnings)
        self.assertIsNotNone(tree)
        assert_valid_decision_node(tree)


class CheckCheatsheetsValidatorTests(unittest.TestCase):
    """check_cheatsheets.py's hard-failure conditions, via real temp files (it reads
    paths, not strings)."""

    def _write(self, tmpdir: str, text: str) -> Path:
        path = Path(tmpdir) / "fixture.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_heading_is_flagged(self):
        doc = "# X\n\n## When to reach for it\nprose\n- s\n"
        with tempfile.TemporaryDirectory() as tmp:
            findings = cc.check_doc(self._write(tmp, doc))
        joined = "\n".join(findings)
        self.assertIn("Picking feature", joined)
        self.assertIn("Common pitfalls", joined)
        self.assertIn("Practice", joined)

    def test_template_without_complexity_is_flagged(self):
        doc = STYLE_B_DOC.replace("Complexity: O(1) time · O(1) space — constant work",
                                  "Complexity: not the right grammar at all")
        with tempfile.TemporaryDirectory() as tmp:
            findings = cc.check_doc(self._write(tmp, doc))
        self.assertTrue(any("Complexity line" in f for f in findings))

    def test_empty_practice_is_flagged(self):
        doc = STYLE_B_DOC.replace("- LC 99 — Ninety Nine", "- not a resolvable bullet")
        with tempfile.TemporaryDirectory() as tmp:
            findings = cc.check_doc(self._write(tmp, doc))
        self.assertTrue(any("zero key problems" in f for f in findings))

    def test_well_formed_doc_has_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = cc.check_doc(self._write(tmp, STYLE_B_DOC))
        self.assertEqual(findings, [])

    def test_signal_links_all_resolve_on_the_real_table(self):
        # The real intuition_cheatsheet.md is untouched by the concurrent doc re-head, so
        # this is a genuine assertion, not a placeholder.
        self.assertEqual(cc.check_signal_links(), [])

    def test_decision_tree_missing_section_is_flagged(self):
        doc = "# X\n\nno decision tree here\n"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(bc, "INTUITION_DOC", self._write(tmp, doc)):
                findings = cc.check_decision_tree()
        self.assertTrue(any("Decision tree" in f for f in findings))

    def test_decision_tree_unknown_doc_link_is_flagged(self):
        doc = ("## Decision tree\n\n"
              "- Root?\n"
              "  - Some cue → [nope](techniques/does_not_exist.md)\n")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(bc, "INTUITION_DOC", self._write(tmp, doc)):
                findings = cc.check_decision_tree()
        self.assertTrue(any("does_not_exist.md" in f for f in findings))

    def test_decision_tree_childless_inner_node_is_flagged(self):
        doc = ("## Decision tree\n\n"
              "- Root?\n"
              "  - Leaf one → **heap**\n"
              "  - Childless question?\n")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(bc, "INTUITION_DOC", self._write(tmp, doc)):
                findings = cc.check_decision_tree()
        self.assertTrue(any("has no children" in f for f in findings))

    def test_signal_coverage_gap_is_flagged(self):
        doc = ("## Signal → technique\n\n"
              "| What you see in the prompt | Reach for | Doc |\n"
              "|---|---|---|\n"
              "| a sorted pair | two pointers (converge from ends) | "
              "[two_pointer](techniques/two_pointer.md) |\n"
              "| a stray signal | mystery move | *below* |\n\n"
              "## Decision tree\n\n"
              "- Root?\n"
              "  - Only leaf → [two pointers](techniques/two_pointer.md)\n")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(bc, "INTUITION_DOC", self._write(tmp, doc)):
                findings = cc.check_signal_coverage()
        self.assertTrue(any("mystery move" in f for f in findings))

    def test_decision_tree_and_coverage_are_clean_on_the_real_doc(self):
        self.assertEqual(cc.check_decision_tree(), [])
        self.assertEqual(cc.check_signal_coverage(), [])


# ── golden: build from the REAL docs, compare to the seed ───────────────────────────

def _diff_payload(expected: dict, actual: dict) -> list[str]:
    lines: list[str] = []
    if expected["signals"] != actual["signals"]:
        lines.append(f"signals[]: {len(expected['signals'])} expected rows vs "
                     f"{len(actual['signals'])} actual")
    exp_by_id = {t["id"]: t for t in expected["techniques"]}
    act_by_id = {t["id"]: t for t in actual["techniques"]}
    for tid in sorted(set(exp_by_id) | set(act_by_id)):
        exp, act = exp_by_id.get(tid), act_by_id.get(tid)
        if exp is None:
            lines.append(f"{tid}: unexpected technique in generator output")
        elif act is None:
            lines.append(f"{tid}: missing from generator output")
        elif exp != act:
            lines.extend(_diff_technique(tid, exp, act))
    return lines


def _diff_value(path: str, exp, act) -> list[str]:
    """Recursive, SYMMETRIC diff: a key/index present in `act` but not `exp` is flagged
    exactly like the reverse (a key/index `exp` has that `act` dropped) — at every nesting
    level (a technique's own fields, `picking`, each `variants[]`/`notWhen[]`/`keyProblems[]`
    entry, each entry's own fields), not only the top one. The bar is byte-equal
    modulo `generatedAt`/`docUrl`, so a field the generator adds that the seed never had is
    exactly as much a mismatch as a field it drops."""
    if isinstance(exp, dict) and isinstance(act, dict):
        findings: list[str] = []
        exp_keys, act_keys = set(exp), set(act)
        for k in sorted(exp_keys - act_keys):
            findings.append(f"{path}.{k}: missing from actual (expected {exp[k]!r})")
        for k in sorted(act_keys - exp_keys):
            findings.append(f"{path}.{k}: unexpected in actual (got {act[k]!r})")
        for k in sorted(exp_keys & act_keys):
            findings.extend(_diff_value(f"{path}.{k}", exp[k], act[k]))
        return findings
    if isinstance(exp, list) and isinstance(act, list):
        findings = []
        for i in range(max(len(exp), len(act))):
            if i >= len(act):
                findings.append(f"{path}[{i}]: missing from actual (expected {exp[i]!r})")
            elif i >= len(exp):
                findings.append(f"{path}[{i}]: unexpected in actual (got {act[i]!r})")
            else:
                findings.extend(_diff_value(f"{path}[{i}]", exp[i], act[i]))
        return findings
    if exp != act:
        return [f"{path}: expected {exp!r} != got {act!r}"]
    return []


def _diff_technique(tid: str, exp: dict, act: dict) -> list[str]:
    return _diff_value(tid, exp, act)


class DiffHelperSymmetryTests(unittest.TestCase):
    """_diff_value must flag a key/index `act` ADDS as loudly as one it DROPS, at both the
    technique's own top-level fields and inside a nested structure (here: `picking`)."""

    def test_extra_top_level_key_in_actual_is_flagged(self):
        findings = _diff_technique("t", {"whenToUse": "x"}, {"whenToUse": "x", "extra": "y"})
        self.assertEqual(findings, ["t.extra: unexpected in actual (got 'y')"])

    def test_missing_top_level_key_in_actual_is_flagged(self):
        findings = _diff_technique("t", {"whenToUse": "x", "extra": "y"}, {"whenToUse": "x"})
        self.assertEqual(findings, ["t.extra: missing from actual (expected 'y')"])

    def test_extra_key_inside_a_nested_dict_is_flagged(self):
        exp = {"picking": {"feature": "f"}}
        act = {"picking": {"feature": "f", "notWhen": []}}
        findings = _diff_technique("t", exp, act)
        self.assertEqual(findings, ["t.picking.notWhen: unexpected in actual (got [])"])

    def test_extra_list_item_in_actual_is_flagged(self):
        exp = {"pitfalls": ["a"]}
        act = {"pitfalls": ["a", "b"]}
        findings = _diff_technique("t", exp, act)
        self.assertEqual(findings, ["t.pitfalls[1]: unexpected in actual (got 'b')"])

    def test_identical_nested_structures_have_no_findings(self):
        payload = {"picking": {"feature": "f", "notWhen": [{"technique": "x", "because": "y"}]}}
        self.assertEqual(_diff_technique("t", payload, dict(payload)), [])


class GoldenTest(unittest.TestCase):
    def test_generator_reproduces_the_seed_modulo_generated_at(self):
        warnings: list[str] = []
        try:
            payload = bc.build_payload(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), warnings)
        except bc.BuildError as exc:
            self.fail(f"blocked before content comparison — techniques.yml join not ready "
                     f"yet (expected until the docs' C1 re-head lands 'doc:' keys): {exc}")
            return
        expected = json.loads((FIXTURES / "cheat-sheets.seed.json").read_text(encoding="utf-8"))
        diff = _diff_payload({**expected, "generatedAt": None},
                             {**payload, "generatedAt": None})
        if diff:
            self.fail("golden mismatch (" + str(len(diff)) + " field(s)):\n  "
                     + "\n  ".join(diff))


if __name__ == "__main__":
    unittest.main(verbosity=2)
