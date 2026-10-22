"""Validate the technique docs (+ intuition_cheatsheet.md) against the /learn cheat-sheet
markdown contract that scripts/build_cheatsheets.py reads (see that module's docstring
for "the markdown contract").

    python scripts/check_cheatsheets.py             # report
    python scripts/check_cheatsheets.py --check      # exit 1 on a hard contract violation

Reuses build_cheatsheets.py's own parser (imported, never duplicated — the parser is the
arbiter of the contract). Six hard checks:

  1. a technique doc missing a required heading (When to reach for it / Picking feature /
     Common pitfalls / Practice / at least one Template: …);
  2. a Template section whose python fence has no valid `Complexity: … ` line right after it;
  3. a Practice section that resolves to zero key problems;
  4. an intuition_cheatsheet.md signal row whose Doc column links `techniques/<x>.md` for
     an `<x>` that doesn't actually exist as a file;
  5. the `## Decision tree` section: missing entirely, a malformed/dangling bullet (the
     parser's own `problems`), a root that is itself a leaf, an inner node with no
     children, or a linked leaf whose `techniques/<stem>.md` doesn't exist.
  6. coverage: every `signals[].reach` (the table) must appear as a decision-tree leaf
     `reach` — a table row with no leaf is a finding.

A row/bullet that does NOT link a technique page is a LABEL (heap, Boyer-Moore voting, …)
and is always allowed — there is no hardcoded label list; "is it a label" is simply "did the
Doc/notWhen resolution find a real file", derived fresh from the table/doc each run.
Blocking from the pre-commit hook as of Sep 23, 2026 — all 18 docs passed, so
`--check` is wired to fail the commit on a violation.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _console

_console.force_utf8()

import build_cheatsheets as bc

REQUIRED_HEADINGS = (bc.HEADING_WHEN, bc.HEADING_PICKING, bc.HEADING_PITFALLS, bc.HEADING_PRACTICE)


def check_required_headings(path: Path, sections: list[tuple[str, list[str]]]) -> list[str]:
    present = {h for h, _ in sections}
    missing = [h for h in REQUIRED_HEADINGS if h not in present]
    if not any(h.startswith(bc.HEADING_TEMPLATE_PREFIX) for h, _ in sections):
        missing.append(f"{bc.HEADING_TEMPLATE_PREFIX}<title> (at least one)")
    return [f"{path.name}: missing '## {h}' heading" for h in missing]


def check_template_complexity(path: Path, sections: list[tuple[str, list[str]]]) -> list[str]:
    findings = []
    for heading, body in bc.find_template_sections(sections):
        variant = bc.parse_template_section(heading, body)
        if variant["complexity"]["time"] == bc.TODO:
            findings.append(
                f"{path.name}: '## {heading}' has no Complexity line after its python fence")
    return findings


def check_practice_nonempty(path: Path, sections: list[tuple[str, list[str]]]) -> list[str]:
    lines = bc.find_section(sections, bc.HEADING_PRACTICE)
    if lines is None:
        return []  # the missing heading itself is reported by check_required_headings
    if not bc.parse_practice_section(lines):
        return [f"{path.name}: '## {bc.HEADING_PRACTICE}' resolves to zero key problems "
                f"(bullets must read 'LC <n> — <title>' or '[<n>. <title>](…)')"]
    return []


def check_doc(path: Path) -> list[str]:
    sections = bc.split_h2_sections(bc.read_text(path))
    return (check_required_headings(path, sections)
            + check_template_complexity(path, sections)
            + check_practice_nonempty(path, sections))


def check_signal_links() -> list[str]:
    lines = bc.find_h2_section_raw(bc.read_text(bc.INTUITION_DOC), bc.SIGNAL_TABLE_HEADING) or []
    findings = []
    for cells in bc.parse_signal_rows(lines):
        target = bc.signal_doc_target(cells[2])
        if target is not None and not (bc.TECHNIQUES_DIR / target).is_file():
            findings.append(
                f"intuition_cheatsheet.md: Doc column links 'techniques/{target}', which "
                f"does not exist (row: '{cells[0][:60]}')")
    return findings


def _decision_section() -> tuple[dict | None, list[str]]:
    """Parse `## Decision tree` once: (root node or `None`, findings so far). Findings
    cover a missing section, the parser's own fail-soft `problems` (a malformed or
    dangling bullet, zero/multiple roots), and a root that is itself a leaf."""
    lines = bc.find_h2_section_raw(bc.read_text(bc.INTUITION_DOC), bc.DECISION_TREE_HEADING)
    if lines is None:
        return None, [f"intuition_cheatsheet.md: missing '## {bc.DECISION_TREE_HEADING}' "
                      f"section"]
    problems: list[str] = []
    root = bc.parse_decision_tree(lines, problems)
    if root is not None and "children" not in root:
        problems.append("decision tree: root bullet is a leaf, expected an inner node")
    return root, problems


def check_no_dangling_branches(node: dict) -> list[str]:
    if "children" not in node:
        return []
    findings = []
    if not node["children"]:
        findings.append(f"decision tree: inner node '{node['label']}' has no children")
    for child in node["children"]:
        findings.extend(check_no_dangling_branches(child))
    return findings


def check_decision_leaf_links(root: dict) -> list[str]:
    findings = []
    for leaf in bc.decision_tree_leaves(root):
        if leaf.get("page") is False:
            continue
        slug = leaf["reach"].replace("-", "_")
        if not bc.is_technique_doc(slug):
            findings.append(f"decision tree: leaf '{leaf['label']}' links "
                            f"'techniques/{slug}.md', which does not exist")
    return findings


def check_decision_tree() -> list[str]:
    root, findings = _decision_section()
    if root is None:
        return findings
    return findings + check_no_dangling_branches(root) + check_decision_leaf_links(root)


def check_signal_coverage() -> list[str]:
    root, _findings = _decision_section()
    if root is None:
        return []  # the missing/malformed section itself is reported by check_decision_tree
    tree_reach = {leaf["reach"] for leaf in bc.decision_tree_leaves(root)}
    table_reach = {row["reach"] for row in bc.parse_signal_table()}
    return [f"intuition_cheatsheet.md: signal row reaches '{r}', which has no matching "
            f"decision-tree leaf" for r in sorted(table_reach - tree_reach)]


def collect_findings() -> list[str]:
    findings: list[str] = []
    for path in bc.discover_technique_docs():
        findings.extend(check_doc(path))
    findings.extend(check_signal_links())
    findings.extend(check_decision_tree())
    findings.extend(check_signal_coverage())
    return findings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 on a hard contract violation")
    args = ap.parse_args()

    findings = collect_findings()
    if findings:
        print(f"❌ CHEAT-SHEET CONTRACT VIOLATIONS ({len(findings)})")
        for f in findings:
            print(f"   {f}")
    else:
        print("✅ every technique doc + the signals table + the decision tree satisfies "
              "the cheat-sheet contract")

    if args.check and findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
