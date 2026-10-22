"""Which rule files have not been read against the decisions that postdate them.

    python scripts/reconcile.py                      # report the backlog
    python scripts/reconcile.py --check              # exit 1 if anything is unreconciled
    python scripts/reconcile.py --file a.md b.md     # mark these read, stamped today
    python scripts/reconcile.py --all                # mark EVERYTHING read (see the warning)

Why a DATE and not a dependency list
------------------------------------
The first design for this was `depends_on: [effort_budget.ceiling, ...]` in every rule file,
inverted into a concept index. It was abandoned for a reason visible in this repo's own
history: **every detector built out of WORDS has already failed here.**

  - `RETIRED_TERMS` only catches spellings it was handed. It had `daily_cap` and not
    "daily cap", so eight live instances of a superseded rule went unflagged — including
    "5. **5-Problem Daily Cap**: Never exceed 5 problems in a day" sitting in the study
    guide's own protocol list.
  - the restated-value check matches the CURRENT config value, so a line asserting a STALE
    one (`ceiling 9.0`) is invisible to it by construction.

A dependency list is more words, and would have failed the same way: the rule that broke
worst (`feedback_unseen_on_non_sd_days`) rested on "an SD day costs 3.0 units" — a premise
its author would never have thought to declare, because at the time it was simply true.

**A date cannot be misspelled, and every file already needs one.** So this check starts
COMPLETE: a file with no `reconciled` field is reported as unreconciled rather than skipped,
which means nothing can be silently absent. That property is the whole argument.

⚠️ Why `reconciled:` is a field and not `git log -1`
----------------------------------------------------
Git mtime measures "was edited", not "was re-examined against the new decision". A typo fix
would have stamped `feedback_unseen_on_non_sd_days` current on the day it was the most
broken file in the repo. Bumping this field is a deliberate assertion — *"I read this rule
against that decision, and it is either still right or now fixed."* Automating it from git
would restore exactly the silence this exists to break.

⚠️ This does not remove the audit work. It makes it visible and tracked instead of
invisible, which was the actual failure — nobody knew the backlog existed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
DECISIONS = REPO / "decisions.yml"

#: Files that carry rules and therefore need reconciling. Memory files all have YAML
#: frontmatter; the normative docs take the same field inside an HTML comment.
RULE_GLOBS = (
    ".claude/memory/*.md",
    # ⚠️ CLAUDE.md is IN SCOPE, and it is the most important file here (added Aug 17, 2026).
    # It is always injected, so when it and a memory file disagree, THIS is the copy that
    # gets obeyed — which makes a stale rule here strictly worse than a stale rule anywhere
    # else. That is not hypothetical: `feedback_batch_commits.md` carried "ask before every
    # commit and push", one day old and correct, while step 8 here still said "commit + push
    # once at session end" — and ~12 commits ran on the stale copy.
    #
    # Nothing else catches this class. The value checker only tracks cse.config.yml numbers;
    # the retired-vocabulary list has no entry for a superseded PHRASING of a workflow step.
    # Recording the decision and letting THIS file fall out of date is what surfaces it.
    "CLAUDE.md",
    # The coaching engine moved into the skill (2026-09-10). Its rules are opt-in reads, so a
    # decision that postdates a reference file's `reconciled:` is the signal that the skill has
    # not been read against the change — the same temporal check CLAUDE.md gets. SKILL.md carries
    # `reconciled:` in frontmatter; each reference file carries it as an HTML comment.
    ".claude/skills/**/*.md",
)

#: Not rules: an append-only dated log records what was true AT THE TIME and is never
#: reconciled — back-dating it would destroy the history it exists to hold.
RULE_EXCLUDE = ("self_eval_log.md", "MEMORY.md", "decisions.yml")

FRONTMATTER_FIELD = re.compile(r"^reconciled:\s*(\d{4}-\d{2}-\d{2})\s*$", re.M)
#: Same assertion for a file with no YAML frontmatter (CLAUDE.md, and any normative doc).
COMMENT_FIELD = re.compile(r"<!--\s*reconciled:\s*(\d{4}-\d{2}-\d{2})\s*-->")


def load_decisions() -> list[dict]:
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        sys.exit("reconcile: needs PyYAML (pip install pyyaml)")
    data = yaml.safe_load(DECISIONS.read_text(encoding="utf-8")) or {}
    out = []
    for d in data.get("decisions", []):
        date = d.get("date")
        if isinstance(date, dt.date):
            d["date"] = date
        elif isinstance(date, str):
            d["date"] = dt.date.fromisoformat(date)
        else:
            continue
        out.append(d)
    return sorted(out, key=lambda d: d["date"], reverse=True)


def rule_files() -> list[Path]:
    seen = []
    for pattern in RULE_GLOBS:
        for p in sorted(REPO.glob(pattern)):
            if p.is_file() and p.name not in RULE_EXCLUDE:
                seen.append(p)
    return seen


def reconciled_date(path: Path) -> dt.date | None:
    """The file's own assertion of when it was last read against the decision log."""
    text = path.read_text(encoding="utf-8")
    # Frontmatter only — a date mentioned in the body is prose, not an assertion.
    if text.startswith("---"):
        end = text.find("\n---", 3)
        head = text[:end] if end != -1 else text
    else:
        head = text[:400]
    m = FRONTMATTER_FIELD.search(head) or COMMENT_FIELD.search(text)
    if not m:
        return None
    try:
        return dt.date.fromisoformat(m.group(1))
    except ValueError:
        return None


def stamp(path: Path, when: dt.date) -> bool:
    """Write/refresh `reconciled:` in the frontmatter. Returns True if the file changed."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        # No frontmatter (CLAUDE.md): carry the assertion in an HTML comment instead, placed
        # right under the title so it is visible to a reader, not buried.
        marker = f"<!-- reconciled: {when} -->"
        if COMMENT_FIELD.search(text):
            new = COMMENT_FIELD.sub(marker, text, count=1)
        else:
            lines = text.split("\n")
            at = 1 if lines and lines[0].startswith("#") else 0
            lines.insert(at, "\n" + marker if at else marker)
            new = "\n".join(lines)
        if new == text:
            return False
        path.write_text(new, encoding="utf-8", newline="\n")
        return True
    end = text.find("\n---", 3)
    if end == -1:
        return False
    head, rest = text[:end], text[end:]
    if FRONTMATTER_FIELD.search(head):
        new_head = FRONTMATTER_FIELD.sub(f"reconciled: {when}", head)
    else:
        new_head = head.rstrip("\n") + f"\nreconciled: {when}"
    if new_head == head:
        return False
    path.write_text(new_head + rest, encoding="utf-8", newline="\n")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if anything is unreconciled")
    ap.add_argument("--file", nargs="+", metavar="PATH",
                    help="mark these files reconciled as of --date (default: today)")
    ap.add_argument("--all", action="store_true",
                    help="mark EVERY rule file reconciled. Only after actually reading them — "
                         "a blanket stamp turns this check into a rubber stamp forever")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="date to stamp (default: the session date)")
    args = ap.parse_args()

    if args.date:
        when = dt.date.fromisoformat(args.date)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import session_date  # noqa: PLC0415
            when = dt.date.fromisoformat(session_date.resolve(fmt="%Y-%m-%d", announce=False))
        except Exception:  # noqa: BLE001 — fall back to wall clock rather than refusing
            when = dt.date.today()

    decisions = load_decisions()
    if not decisions:
        sys.exit("reconcile: decisions.yml has no dated decisions")
    newest = decisions[0]["date"]

    if args.file or args.all:
        targets = ([REPO / f for f in args.file] if args.file else rule_files())
        changed = [p for p in targets if stamp(p, when)]
        print(f"Stamped reconciled: {when} on {len(changed)} file(s).")
        for p in changed:
            print(f"   {p.relative_to(REPO).as_posix()}")
        return

    stale: list[tuple[Path, dt.date | None, list[dict]]] = []
    for path in rule_files():
        rd = reconciled_date(path)
        pending = [d for d in decisions if rd is None or d["date"] > rd]
        if pending:
            stale.append((path, rd, pending))

    total = len(rule_files())
    if not stale:
        print(f"✅ all {total} rule files reconciled against decisions up to {newest}")
        return

    print(f"\n🕒 UNRECONCILED RULE FILES ({len(stale)} of {total})")
    print(f"   Newest decision: {newest}. A file below has not been READ against the")
    print("   decisions listed with it — it may still be right; nobody has checked.")
    print("   After reading one: python scripts/reconcile.py --file <path>\n")
    for path, rd, pending in sorted(stale, key=lambda t: (t[1] or dt.date.min)):
        rel = path.relative_to(REPO).as_posix()
        seen = rd.isoformat() if rd else "never"
        ids = ", ".join(d["id"] for d in pending[:4])
        more = f" (+{len(pending) - 4} more)" if len(pending) > 4 else ""
        print(f"   {rel}")
        print(f"      reconciled: {seen}  ·  pending: {ids}{more}")

    if args.check:
        sys.exit(1)


if __name__ == "__main__":
    main()
