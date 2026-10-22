"""Report what a live practice repo has that canonical cse-coach does not.

    python scripts/promote_report.py --source ../cse-progress
    python scripts/promote_report.py --source ../cse-progress --diff
    python scripts/promote_report.py --source ../cse-progress --only memory

This is the **opposite direction** from `update_coach.py`, and the two must not be
confused:

    update_coach.py    canonical -> adopters   applies changes
    promote_report.py  practice  -> canonical  REPORTS ONLY, never writes

Why report-only, permanently: rules are *discovered* in a live practice repo, but one
learner's idiosyncrasy must not silently become canon for every adopter. Promotion
stays a deliberate human act. What this fixes is not the deciding - it is the fact
that, unautomated, the backlog of things worth promoting was **invisible**, so nobody
could tell a deliberate decline from a thing nobody noticed. (When first run against
cse-progress it found 32 unported memory rules and a pre-commit fix for a silent
tracker-staging bug that canonical still shipped.)

Paths already considered and rejected go in `.coach-sync/declined.md`, with a reason, and
are hidden from the report (`--all` shows them). That file is what makes the distinction
above actually work: without it every run re-asks questions that were already answered,
and a report that is mostly noise is one nobody opens.

The comparison is scoped to `ENGINE_PATHS`, so the practice repo's own data -
trackers, schedules, solutions, self-eval log - is never read or reported.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coach_sync import ENGINE_PATHS, hash_file, iter_tracked  # noqa: E402

# Git runs hooks with a cp1252 console on Windows; the first non-ASCII character printed
# would otherwise kill the script mid-run while the commit still succeeds. See _console.
import _console

_console.force_utf8()

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Paths already considered and deliberately not promoted. Without this the report cannot
#: distinguish a decision from an oversight, and a run where most rows are already-answered
#: questions is one that stops being read - the exact failure this tool exists to prevent.
DECLINED_PATH = Path(".coach-sync/declined.md")

#: A declined bullet's leading path: has a file extension, or contains a `/` (an
#: extension-less file under a directory, e.g. `.githooks/pre-commit`). Bare decision ids
#: and `key:` config-block bullets have neither, so they do not match.
DECLINED_BULLET = re.compile(r"\s*-\s+`?([^\s`]+\.[A-Za-z0-9]+|[^\s`/]*(?:/[^\s`/]+)+)`?")

#: Group findings by area so a long report stays scannable. First match wins.
AREAS = (
    ("memory", ".claude/memory/"),
    ("skills", ".claude/skills/"),
    ("agent-hooks", ".claude/hooks/"),
    ("scripts", "scripts/"),
    ("hooks", ".githooks/"),
    ("curriculum", "curriculum/"),
    ("patterns", "docs/foundations/dsa/patterns/"),
    ("templates", "/templates/"),
)


def area_of(rel: str) -> str:
    for name, prefix in AREAS:
        if prefix.startswith("/") and prefix in f"/{rel}":
            return name
        if rel.startswith(prefix):
            return name
    return "other"


def read_declined(canonical: Path) -> set[str]:
    """Paths listed in `.coach-sync/declined.md`, read from its `- <path> — reason` bullets.

    Deliberately a markdown file rather than a bare list: a decline is only useful with its
    reason attached, and a reason nobody can find is how a decline silently becomes dogma.
    """
    path = canonical / DECLINED_PATH
    if not path.is_file():
        return set()
    declined: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = DECLINED_BULLET.match(line)
        if m:
            declined.add(m.group(1))
    return declined


def compare(source: Path, canonical: Path) -> dict[str, list[str]]:
    """Bucket every engine path by how the two repos differ."""
    in_source = iter_tracked(source, ENGINE_PATHS)
    in_canonical = iter_tracked(canonical, ENGINE_PATHS)

    buckets: dict[str, list[str]] = {"new": [], "changed": [], "canonical_only": []}
    for rel in sorted(in_source | in_canonical):
        if rel not in in_canonical:
            buckets["new"].append(rel)
        elif rel not in in_source:
            buckets["canonical_only"].append(rel)
        elif hash_file(source / rel) != hash_file(canonical / rel):
            buckets["changed"].append(rel)
    return buckets


def print_group(title: str, paths: list[str], note: str) -> None:
    if not paths:
        return
    print(f"\n{title} ({len(paths)})")
    print(f"  {note}")
    by_area: dict[str, list[str]] = {}
    for rel in paths:
        by_area.setdefault(area_of(rel), []).append(rel)
    for area in sorted(by_area):
        print(f"\n  [{area}]")
        for rel in by_area[area]:
            print(f"    {rel}")


def print_diffs(source: Path, canonical: Path, paths: list[str], limit: int) -> None:
    for rel in paths:
        print(f"\n----- {rel} -----")
        diff = list(
            difflib.unified_diff(
                (canonical / rel).read_text(encoding="utf-8", errors="replace").splitlines(),
                (source / rel).read_text(encoding="utf-8", errors="replace").splitlines(),
                fromfile=f"canonical/{rel}",
                tofile=f"source/{rel}",
                lineterm="",
                n=1,
            )
        )
        for line in diff[:limit]:
            print(line)
        if len(diff) > limit:
            print(f"... {len(diff) - limit} more diff lines")


def _force_utf8_stdout() -> None:
    """Print UTF-8 regardless of console codepage.

    Required, not cosmetic: the files this reports on are memory rules and pattern
    docs, which are full of emoji (the Comfort scale is literally emoji). A Windows
    console defaults to cp1252, where printing one raises UnicodeEncodeError and
    kills the report mid-run. Same failure class as the cp1252 crashes already on
    record in this project's self-eval log.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - non-standard stream
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(
        description="Report promotion candidates from a live practice repo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source", type=Path, required=True, help="the live practice repo")
    parser.add_argument("--canonical", type=Path, default=REPO_ROOT, help="this repo")
    parser.add_argument("--diff", action="store_true", help="show diffs for changed files")
    parser.add_argument("--only", help="restrict to one area, e.g. memory, scripts, hooks")
    parser.add_argument("--diff-lines", type=int, default=40, help="max diff lines per file")
    parser.add_argument("--all", action="store_true",
                        help="include paths listed in .coach-sync/declined.md (hidden by default)")
    args = parser.parse_args(argv)

    source, canonical = args.source.resolve(), args.canonical.resolve()
    if not source.is_dir():
        print(f"error: --source is not a directory: {source}", file=sys.stderr)
        return 2

    buckets = compare(source, canonical)

    declined = set() if args.all else read_declined(canonical)
    if declined:
        hidden = sum(len([p for p in v if p in declined]) for v in buckets.values())
        buckets = {k: [p for p in v if p not in declined] for k, v in buckets.items()}
    else:
        hidden = 0

    if args.only:
        buckets = {k: [p for p in v if area_of(p) == args.only] for k, v in buckets.items()}

    print(f"source:    {source}")
    print(f"canonical: {canonical}")

    print_group(
        "NOT IN CANONICAL",
        buckets["new"],
        "exists in the practice repo only - candidates to promote",
    )
    print_group(
        "DIFFERENT",
        buckets["changed"],
        "both have it, contents differ - the practice repo may hold a fix "
        "(or a local customization that should stay local)",
    )
    print_group(
        "CANONICAL ONLY",
        buckets["canonical_only"],
        "informational - canonical ships these, the practice repo does not",
    )

    if args.diff and buckets["changed"]:
        print_diffs(source, canonical, buckets["changed"], args.diff_lines)

    candidates = len(buckets["new"]) + len(buckets["changed"])
    print(f"\n{candidates} promotion candidate(s). Nothing was written - this is a report.")
    return 1 if candidates else 0


if __name__ == "__main__":
    raise SystemExit(main())
