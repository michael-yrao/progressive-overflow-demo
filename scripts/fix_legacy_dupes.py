#!/usr/bin/env python3
"""Fix legacy lint debt in solution files that predates the date-stamp convention.

Two defects, both born of pre-convention attempts that `restore_history.py` pastes back
verbatim (by design it never parses the history slice, so it faithfully preserves them):

  1. **Duplicate class-level method names** - e.g. two bare `def topKFrequent(...)`. Python
     binds the name to the LAST def, so every earlier one is dead code (linters: F811).
  2. **Class-level methods missing `self`** - `def foo(nums, k)` inside a class; broken as a
     method (`sol.foo(a, b)` binds the instance to `nums`).

The fix (mechanical, never touches logic):
  - Duplicates are **dated-renamed** from the tracker's Attempt Dates (newest kept first,
    older dates assigned down the file). Self-recursive calls inside a renamed body are
    re-scoped to the new name so each attempt stays self-consistent. When the available
    dates can't cover the duplicates, the file is **reported and skipped** - never guessed.
  - Missing `self` is inserted in place.

Usage:
  python scripts/fix_legacy_dupes.py            # fix in place
  python scripts/fix_legacy_dupes.py --dry-run  # report only
  python scripts/fix_legacy_dupes.py --file dsa/leetcode/trees/235_*.py
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dsa" / "leetcode"
TRACKER = ROOT / "docs" / "foundations" / "dsa" / "mastery" / "dsa_progress.md"

DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
DATED_METHOD_RE = re.compile(r"_(\d{8})$")


def tracker_dates(number: str) -> list[str]:
    """All Attempt-Dates stamps (YYYYMMDD) for a problem number, newest first, deduped.

    A problem may span several tracker rows (one per method); we union their dates, since a
    file's methods collectively cover them."""
    if not TRACKER.exists():
        return []
    stamps: set[str] = set()
    for line in TRACKER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or f"[{number}." not in line:
            continue
        for y, m, d in DATE_RE.findall(line):
            stamps.add(f"{y}{m}{d}")
    return sorted(stamps, reverse=True)


def class_level_methods(cls: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [b for b in cls.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))]


def first_arg(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    args = fn.args.posonlyargs + fn.args.args
    return args[0].arg if args else None


def fix_file(path: Path, dry_run: bool) -> list[str]:
    """Return a list of human-readable actions taken (or that would be taken)."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [f"SKIP (syntax error): {e}"]
    lines = text.splitlines(keepends=True)
    actions: list[str] = []
    number = path.name.split("_", 1)[0]

    # Collect line-based edits as (lineno_1based, old_substr, new_substr) applied at the end.
    def_renames: list[tuple[int, str, str]] = []          # def-line renames
    recursion_edits: list[tuple[int, int, str, str]] = []  # (start,end, old, new) body rescope
    self_inserts: list[int] = []                           # def linenos needing `self`

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = class_level_methods(node)

        # (2) missing self - flag class-level methods whose first param isn't self/cls
        for m in methods:
            if first_arg(m) not in ("self", "cls"):
                self_inserts.append(m.lineno)
                actions.append(f"add self -> {node.name}.{m.name} (line {m.lineno})")

        # (1) duplicate names
        names = [m.name for m in methods]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            group = [m for m in methods if m.name == dup]  # in file order (top = newest)
            # Dates already consumed by DATED methods anywhere in this class:
            used = {mm.group(1) for m in methods
                    if (mm := DATED_METHOD_RE.search(m.name))}
            avail = [d for d in tracker_dates(number) if d not in used]
            # Keep the FIRST (newest) occurrence's name; the rest need distinct dated names.
            need = group[1:]
            if len(avail) < len(need):
                actions.append(
                    f"SKIP dup {node.name}.{dup} - need {len(need)} date(s), tracker offers "
                    f"{len(avail)} ({avail or 'none'}); rename by hand.")
                continue
            for m, stamp in zip(need, avail):  # newest available -> topmost remaining
                new_name = f"{dup}_{stamp}"
                def_renames.append((m.lineno, f"def {dup}(", f"def {new_name}("))
                recursion_edits.append((m.lineno, m.end_lineno or m.lineno,
                                        f"self.{dup}(", f"self.{new_name}("))
                actions.append(f"rename dup -> {node.name}.{new_name} (was line {m.lineno})")

    if not actions or dry_run:
        return actions

    # Apply edits (line-indexed; each def line is unique so order is safe).
    for lineno in self_inserts:
        i = lineno - 1
        # insert `self, ` (or `self`) as the first parameter
        lines[i] = re.sub(r"\(\s*", lambda mm: mm.group(0) + "self"
                          + ("" if lines[i][mm.end():].lstrip().startswith(")") else ", "),
                          lines[i], count=1)
    for lineno, old, new in def_renames:
        lines[lineno - 1] = lines[lineno - 1].replace(old, new, 1)
    for start, end, old, new in recursion_edits:
        for i in range(start, end):  # body only (exclude the def line at start-1)
            lines[i] = lines[i].replace(old, new)

    path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return actions


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--file", help="fix a single file instead of the whole tree")
    args = ap.parse_args()

    targets = [Path(args.file)] if args.file else sorted(SRC.rglob("*.py"))
    total = 0
    for p in targets:
        acts = fix_file(p, args.dry_run)
        if acts:
            total += 1
            rel = p.relative_to(ROOT) if ROOT in p.parents else p
            print(f"{rel}")
            for a in acts:
                print(f"    {a}")
    verb = "would fix" if args.dry_run else "fixed"
    print(f"\n{total} file(s) {verb}." if total else "No legacy duplicate/self debt found.")


if __name__ == "__main__":
    main()
