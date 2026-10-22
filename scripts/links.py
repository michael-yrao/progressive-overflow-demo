"""Emit the `[file] · [LC/NC]` link pair for one or more problems — the SOURCE FIX for
the link rule outside a scaffold.

`new_problem.py` already prints a `LINKS:` line on every scaffold. The kickoff / restate /
hand-over / "what's next" cases have no such tool, so their links get hand-authored — and
the dominant failure is TRANSCRIPTION: copying a path out of a schedule row, which stores
`../../../dsa/...` (correct relative to that file, three folders deep) but DEAD when the
chat renderer resolves it from the repo root.

This tool removes the transcription. Give it problem numbers; it prints one
`[<number> <title>](<repo-root-relative path>) · [<judge label>](<url>)` line per number
(`LC`, `NC`, `Kattis`, `CSES`, `HelloInterview`, or another judge's bare hostname — see
`judge_label`), reading the path from disk and the title/URL from the file's own
docstring header (falling back to the tracker). The agent runs it and pastes the
output — it is structurally impossible to emit a wrong path.

Per the intervention ladder in `.claude/memory/feedback_self_evaluation.md`:
source fix > hook > CLAUDE.md step > memory file. This is the top rung, matching
`new_problem.py`'s `report_links()`.

Usage:
    python scripts/links.py 269 853 424
    python scripts/links.py 853               # single problem
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# The `·` separator and any glyph in a problem title is unmappable on a stock Windows
# console (cp1252) and would render as `?` or, from the git hook, crash the run. Force
# UTF-8 stdout the same way every other script here does.
import _console

_console.force_utf8()

# Repo root is two levels up from scripts/ — the base the chat renderer resolves against,
# which is the whole point: paths printed here are ALWAYS repo-root-relative.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = "dsa/leetcode"
TRACKER = REPO_ROOT / "docs" / "foundations" / "dsa" / "mastery" / "dsa_progress.md"

# The site's practice page for a number (it exists iff a spec `dsa/tests/<n>_*.yml` does).
# One definition: new_problem.py imports these. `SITE_LABEL` is the site's short name,
# like `LC`/`NC`.
SPEC_DIR = Path("dsa") / "tests"
SITE_PRACTICE_URL_TEMPLATE = "https://progressiveoverflow.com/practice/{number}"
SITE_PRACTICE_URL_PREFIX = "https://progressiveoverflow.com/practice/"
SITE_LABEL = "PO"

# Header line: `853. Car Fleet   ·   https://leetcode.com/problems/car-fleet/`. The `·`
# and the URL are optional — a legacy file may carry only `853. Car Fleet`.
HEADER = re.compile(r"^\s*(\d{1,4})\.\s+(.+?)(?:\s+·\s+(https?://\S+))?\s*$")
# Tracker row cell: `[49. Group Anagrams](https://leetcode.com/problems/group-anagrams/)`.
TRACKER_CELL = re.compile(r"\[(\d{1,4})\.\s*([^\]]+?)\]\((https?://[^)]+)\)")

# Host -> the short label printed next to a problem-page link. Kattis/CSES are the
# external-judge convention (`decisions.yml` `external-judge-problems-sep26`): a problem
# the LC/NeetCode pull doesn't cover (e.g. a negative-edge shortest-path form) is
# hand-picked from another judge, keeping a synthetic 9001-9999 id under the normal root.
# HelloInterview is a different convention (`problem-link-order-sep27`): the SAME
# LeetCode-numbered problem, linked to that premium judge instead of the free NeetCode
# mirror — no synthetic id involved; its label is spelled out in full ("HelloInterview"),
# not abbreviated the way LC/NC are. The site's practice page
# (progressiveoverflow.com/practice/<n>) is the fourth link step after LeetCode,
# NeetCode and HelloInterview (decision `problem-link-order-oct04`); it exists for any
# number with a spec in dsa/tests. Any host not listed here falls back to its bare
# hostname (judge_label below) rather than silently mislabeling it "LC".
JUDGE_LABELS = {
    "leetcode.com": "LC",
    "neetcode.io": "NC",
    "open.kattis.com": "Kattis",
    "cses.fi": "CSES",
    "hellointerview.com": "HelloInterview",
    "progressiveoverflow.com": "PO",
}


def judge_label(url: str) -> str:
    """The short label for a problem-page URL's host: `LC`, `NC`, `Kattis`, `CSES`,
    `HelloInterview`, or — for any other judge — the bare hostname (leading `www.`
    stripped).

    `new_problem.py`'s `report_links()` imports this rather than re-deriving the label —
    links.py has no import of new_problem.py (verified), so the direction is acyclic, and
    importing it there triggers no module-level side effect (this module only defines
    names + calls `_console.force_utf8()`, already a no-op the second time).
    """
    host = urlparse(url).hostname or ""
    host = host.removeprefix("www.")
    return JUDGE_LABELS.get(host, host)


def source_roots() -> list[Path]:
    """Solution roots from cse.config.yml, defaulting to dsa/leetcode.

    Mirrors new_problem.py's source_root(), but returns ALL roots — a problem could live
    under any of them, and matching on the number is what identifies it.
    """
    cfg = REPO_ROOT / "cse.config.yml"
    if cfg.exists():
        m = re.search(r"roots:\s*\[([^\]]*)\]", cfg.read_text(encoding="utf-8"))
        if m:
            roots = [r.strip().strip("'\"") for r in m.group(1).split(",") if r.strip()]
            if roots:
                return [REPO_ROOT / r for r in roots]
    return [REPO_ROOT / DEFAULT_ROOT]


_LEADING_NUMBER = re.compile(r"^(\d{1,4})_")


def solution_files() -> dict[int, list[Path]]:
    """Every solution file under every configured root, keyed by its leading problem
    number: `{39: [<root>/backtracking/39_combination_sum.py], ...}`, each list sorted.

    ONE glob for the whole tree — `gamify.py` needs a path for every tracker row on each
    commit, and `export_showcase.py`'s auto-fill (stage 2) needs the same map to find files
    with no manifest entry. The NUMBER is the identity (same rule as new_problem.py's twin
    check); a number with two files is a twin, and the caller decides what to do with it
    (`find_file` warns and takes the first).
    """
    files: dict[int, list[Path]] = {}
    # Roots in config order, sorted WITHIN each root — the same order `find_file` walks, so
    # a twin resolves to the same first file here as there (a final cross-root sort would
    # not, once a second root is configured).
    for root in source_roots():
        for path in sorted(root.glob("*/*.py")):
            m = _LEADING_NUMBER.match(path.name)
            if m:
                files.setdefault(int(m.group(1)), []).append(path)
    return files


def find_file(number: str) -> Path | None:
    """The solution file for `number`, or None. The NUMBER is the identity (same rule as
    new_problem.py's twin check), so glob `<root>/*/<number>_*.py` across every root.

    On the rare twin (a forked history), warn and take the first — the caller still gets a
    working link, and the fork is a separate problem flagged loudly.
    """
    hits: list[Path] = []
    for root in source_roots():
        hits.extend(sorted(root.glob(f"*/{number}_*.py")))
    if not hits:
        return None
    if len(hits) > 1:
        joined = ", ".join(p.relative_to(REPO_ROOT).as_posix() for p in hits)
        print(f"WARNING: {number} matches {len(hits)} files ({joined}); using the first.",
              file=sys.stderr)
    return hits[0]


def header_title_url(path: Path) -> tuple[str | None, str | None]:
    """(title, url) from the file's docstring header line, each None if absent.

    The header is the authoritative source: it carries the true slug even when the filename
    disagrees (229_majority_element_2 vs .../majority-element-ii) and it is the only place
    that records a premium (neetcode.io) link. Scan only the first docstring block.
    """
    text = path.read_text(encoding="utf-8")
    parts = text.split('"""')
    block = parts[1] if len(parts) >= 2 else text
    for line in block.splitlines():
        m = HEADER.match(line)
        if m:
            return m.group(2).strip(), (m.group(3).rstrip(".,;)") if m.group(3) else None)
    return None, None


def tracker_title_url(number: str) -> tuple[str | None, str | None]:
    """(title, url) for `number` from the tracker — the fallback when the file has no
    header, and the only source when there is no file at all."""
    try:
        lines = TRACKER.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    for line in lines:
        for num, title, url in TRACKER_CELL.findall(line):
            if num == number:
                return title.strip(), url.rstrip("/") + "/" if url else None
    return None, None


TRACKER_LAST_ATTEMPT_COLUMN = 5
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def tracker_row_counts() -> dict[str, int]:
    """`{problem number: how many tracker rows carry it}`, read in one pass.

    A tracker ROW is a table line whose last-attempt cell is an ISO date — the same test
    `check_schedule_integrity.tracker_attempts` uses — so the waiting-room / queue rows
    (a trigger instead of a date) never count. Two rows for one number are two solve
    methods of the same problem (e.g. a Kadane row and a Prefix Sum row for one number)."""
    try:
        lines = TRACKER.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    counts: dict[str, int] = {}
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) <= TRACKER_LAST_ATTEMPT_COLUMN or not _ISO_DATE.match(
                cells[TRACKER_LAST_ATTEMPT_COLUMN]):
            continue
        cell = TRACKER_CELL.search(cells[1])
        if cell:
            counts[cell.group(1)] = counts.get(cell.group(1), 0) + 1
    return counts


_TRACKER_VARIANT_SUFFIX = re.compile(r" \(([^()]*)\)$")
"""Matches one trailing ` (…)` parenthetical, capturing its inner text — a candidate to
strip from a TRACKER-sourced title only (e.g. tracker row "200. Number of Islands (DFS)",
because the tracker author hand-appends the variant to tell same-numbered rows apart).
Whether the candidate is actually stripped is decided by `_is_real_title_parenthetical`
(some LeetCode titles, e.g. 208 "Implement Trie (Prefix Tree)", genuinely end in a
parenthetical baked into the tracker's own title). A HEADER-sourced title is never
touched; `resolve_title_url` applies the strip to a tracker-sourced title."""

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """lowercase `text` with every run of non-alphanumeric characters collapsed to a
    single `-`, matching how LeetCode/NeetCode builds a problem's URL slug from its
    title — used by `_is_real_title_parenthetical` to compare a title fragment against
    the URL's own slug."""
    return _SLUG_NON_ALNUM.sub("-", text.lower()).strip("-")


def _is_real_title_parenthetical(inner: str, url: str | None) -> bool:
    """True when `inner` (the text inside a title's trailing `(…)`) is genuinely part of
    the problem's real name rather than a tracker-only variant tag like "DFS"/"BFS" —
    e.g. LC 208's real title is "Implement Trie (Prefix Tree)", and its URL slug
    `implement-trie-prefix-tree` ends in `-prefix-tree`, while a variant tag like "(DFS)"
    on LC 200's tracker row never appears in `number-of-islands`. With no `url` to check
    against there is nothing to confirm, so the candidate is treated as NOT real (the
    existing strip-by-default behaviour)."""
    if not url:
        return False
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.endswith("-" + _slugify(inner))


def resolve_title_url(number: str, path: Path | None) -> tuple[str | None, str | None]:
    """(title, url) for `number`: the file's own docstring header first, the tracker
    second — the one implementation of that precedence. `link_line()` below calls this
    too, and `export_showcase.py` reuses it rather than re-deriving the same order.

    A tracker-sourced title (no truthy header title) loses a trailing ` (variant)` tag
    — a technique spoiler like "Graph Valid Tree (Union-Find)" — unless
    `_is_real_title_parenthetical` says it is part of the problem's real name. A header
    title is never touched.
    """
    file_title, file_url = header_title_url(path) if path else (None, None)
    track_title, track_url = tracker_title_url(number)
    url = file_url or track_url
    if file_title:
        return file_title, url
    if track_title:
        match = _TRACKER_VARIANT_SUFFIX.search(track_title)
        if match and not _is_real_title_parenthetical(match.group(1), url):
            track_title = track_title[:match.start()]
    return track_title, url


def link_line(number: str) -> str | None:
    """The `[file] · [judge label]` line for `number` (e.g. `LC`, `NC`, `Kattis`,
    `HelloInterview`), or None if nothing on disk knows it.

    Path is ALWAYS repo-root-relative (the fix). Title/URL prefer the file header, then the
    tracker (resolve_title_url). A problem with no file yields no file link — that is
    new_problem.py's job (it prints LINKS: on the scaffold), so we say so rather than
    invent a path.
    """
    path = find_file(number)
    title, url = resolve_title_url(number, path)

    if path is None:
        if url:
            label = judge_label(url)
            print(f"NOTE: {number} has no solution file yet — scaffold it with new_problem.py "
                  f"for the file link. Problem-page link only:", file=sys.stderr)
            return f"[{number}{(' ' + title) if title else ''}]() · [{label}]({url})"
        print(f"WARNING: nothing on disk knows problem {number} (no file, no tracker row).",
              file=sys.stderr)
        return None

    rel = path.relative_to(REPO_ROOT).as_posix()
    name = f"{number} {title}" if title else number
    if not url:
        print(f"WARNING: {number} has no problem-page URL in its header or the tracker; "
              f"emitting the file link alone.", file=sys.stderr)
        return f"[{name}]({rel})"
    label = judge_label(url)
    return f"[{name}]({rel}) · [{label}]({url})"


def has_site_page(number: str, site_numbers: frozenset[int] | None) -> bool:
    """True when the site has a practice page for `number`: its number is in `site_numbers`
    when given, else a local spec `dsa/tests/<number>_*.yml` exists."""
    if site_numbers is not None:
        return number.isdigit() and int(number) in site_numbers
    return any((REPO_ROOT / SPEC_DIR).glob(f"{number}_*.yml"))


def site_practice_url(number: str, site_numbers: frozenset[int] | None = None) -> str | None:
    """The site's practice-page URL for `number`, or None when it has no page (a page for a
    number with no spec is empty). `site_numbers` None checks the local specs; a set means
    "the page exists iff the number is in the set"."""
    if not has_site_page(number, site_numbers):
        return None
    return SITE_PRACTICE_URL_TEMPLATE.format(number=number)


def schedule_link_line(number: str, site_numbers: frozenset[int] | None = None) -> str | None:
    """`link_line(number)` plus ` · [PO](<site url>)` — the shape of a schedule row's link
    cell. The site link is added only when the practice page exists and the row's own judge
    link is not already the site (an external-judge problem keeps its single link)."""
    line = link_line(number)
    site_url = site_practice_url(number, site_numbers)
    if line is None or site_url is None or f"]({SITE_PRACTICE_URL_PREFIX}" in line:
        return line
    return f"{line} · [{SITE_LABEL}]({site_url})"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Print the [file] · [judge label] link pair for one or more problem "
                    "numbers (judge label: LC/NC/Kattis/CSES/HelloInterview/hostname).")
    ap.add_argument("numbers", nargs="+", help="problem number(s), e.g. 269 853 424")
    ap.add_argument("--schedule", action="store_true",
                    help="print the schedule-row shape: the pair plus ` · [PO](site url)` "
                         "when the practice page exists")
    args = ap.parse_args()
    make_line = schedule_link_line if args.schedule else link_line

    missing = 0
    for number in args.numbers:
        if not number.isdigit():
            print(f"WARNING: '{number}' is not a problem number; skipping.", file=sys.stderr)
            missing += 1
            continue
        line = make_line(number)
        if line is None:
            missing += 1
            continue
        print(line)

    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
