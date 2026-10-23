"""Fill `difficulty:` into every practice spec that lacks it, from LeetCode's public data.

The practice spec (`dsa/tests/<number>_<snake>.yml`) is the single source of a problem's
difficulty; `export_practice.py` reads it (the tracker is only a fallback). This tool fills
the key once. For each spec without `difficulty`, it takes the slug from the spec's `url`,
asks LeetCode's public GraphQL endpoint for the question's difficulty, validates it against
Easy/Medium/Hard, and inserts `difficulty: <value>` as the line after `url:`. The file's
other bytes (and its LF or CRLF endings) are untouched: the text is edited, never
round-tripped through a YAML dumper. Non-LeetCode urls (Kattis, ...) are skipped and reported.

Usage:
    python scripts/fill_spec_difficulty.py --dry-run              # print the plan, no network
    python scripts/fill_spec_difficulty.py                        # fetch and write
    python scripts/fill_spec_difficulty.py --only 4,5,6           # just these problem numbers
    python scripts/fill_spec_difficulty.py --cache slugs.json     # slug -> difficulty; a
                                                                  # re-run makes no network calls
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC_DIR = REPO / "dsa" / "tests"

LEETCODE_GRAPHQL = "https://leetcode.com/graphql"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
REQUEST_PAUSE_SECONDS = 0.3
RETRY_PAUSE_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 15.0
HTTP_TOO_MANY = 429
HTTP_SERVER_ERROR_MIN = 500
DIFFICULTIES = ("Easy", "Medium", "Hard")

_SLUG = re.compile(r"^https://leetcode\.com/problems/([a-z0-9-]+)/?")
_URL_LINE = re.compile(r"^url:.*?(\r?\n|$)", re.MULTILINE)
_DIFFICULTY_LINE = re.compile(r"^difficulty:", re.MULTILINE)
_FILENAME_NUMBER = re.compile(r"^(\d+)_")
_URL_VALUE = re.compile(r"^url:\s*(\S+)", re.MULTILINE)


# ── pure helpers ──────────────────────────────────────────────────────────────────────

def slug_from_url(url: str) -> str | None:
    """The LeetCode title slug in `url`, or None for any other judge or a url with no slug."""
    match = _SLUG.match(url.strip())
    return match.group(1) if match else None


def insert_difficulty(text: str, difficulty: str) -> str:
    """`text` with `difficulty: <value>` on the line after `url:`, in that line's own ending
    style. Unchanged when the key already exists or there is no `url:` line."""
    if _DIFFICULTY_LINE.search(text):
        return text
    match = _URL_LINE.search(text)
    if not match:
        return text
    eol = match.group(1) or "\n"
    head = text[:match.end()] if match.group(1) else text[:match.end()] + eol
    return f"{head}difficulty: {difficulty}{eol}{text[match.end():]}"


# ── network ───────────────────────────────────────────────────────────────────────────

def _post_difficulty(slug: str) -> str | None:
    payload = json.dumps({
        "query": 'query($t:String!){question(titleSlug:$t){difficulty}}',
        "variables": {"t": slug},
    }).encode()
    request = urllib.request.Request(
        LEETCODE_GRAPHQL, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                 "Referer": f"https://leetcode.com/problems/{slug}/"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = json.load(response)
    question = (body.get("data") or {}).get("question") or {}
    return question.get("difficulty")


def fetch_difficulty(slug: str) -> str | None:
    """LeetCode's difficulty string for `slug`; one retry on a 429 or 5xx."""
    try:
        return _post_difficulty(slug)
    except urllib.error.HTTPError as exc:
        if exc.code != HTTP_TOO_MANY and exc.code < HTTP_SERVER_ERROR_MIN:
            raise
        time.sleep(RETRY_PAUSE_SECONDS)
        return _post_difficulty(slug)


# ── plan and run ──────────────────────────────────────────────────────────────────────

def _spec_number(path: Path) -> int | None:
    match = _FILENAME_NUMBER.match(path.name)
    return int(match.group(1)) if match else None


def read_text(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def plan(spec_dir: Path, only: frozenset[int] | None) -> dict:
    """Which specs need a fill: `fill` (path, slug), `skipped` non-LeetCode (path, url),
    and the count of specs `already` carrying a difficulty."""
    fill, skipped, already = [], [], 0
    for path in sorted(spec_dir.glob("*.yml")):
        if only is not None and _spec_number(path) not in only:
            continue
        text = read_text(path)
        if _DIFFICULTY_LINE.search(text):
            already += 1
            continue
        url_match = _URL_VALUE.search(text)
        url = url_match.group(1) if url_match else ""
        slug = slug_from_url(url)
        if slug is None:
            skipped.append((path, url))
        else:
            fill.append((path, slug))
    return {"fill": fill, "skipped": skipped, "already": already}


def load_cache(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(slug: str, cache: dict[str, str], is_first_fetch: bool) -> tuple[str | None, bool]:
    """`(difficulty or None, did_fetch)`; the cache answers without the network."""
    if slug in cache:
        return cache[slug], False
    if not is_first_fetch:
        time.sleep(REQUEST_PAUSE_SECONDS)
    return fetch_difficulty(slug), True


def run_fill(fill: list[tuple[Path, str]], cache: dict[str, str]) -> tuple[int, list[str]]:
    """Fetch (or read from `cache`) and write each spec. Returns `(written, problems)`.
    The cache dict is updated in place with every validated fetch."""
    written, problems, fetched_any = 0, [], False
    for path, slug in fill:
        try:
            difficulty, did_fetch = resolve(slug, cache, not fetched_any)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            problems.append(f"{path.name}: fetch failed ({exc})")
            continue
        fetched_any = fetched_any or did_fetch
        if difficulty not in DIFFICULTIES:
            problems.append(f"{path.name}: LeetCode returned {difficulty!r} for {slug}")
            continue
        cache[slug] = difficulty
        write_text(path, insert_difficulty(read_text(path), difficulty))
        written += 1
    return written, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the plan; no network, no writes")
    ap.add_argument("--only", metavar="NUMBERS", help="comma-separated problem numbers")
    ap.add_argument("--cache", metavar="JSON", type=Path,
                    help="slug -> difficulty file, read first and updated after a fetch")
    args = ap.parse_args()

    only = frozenset(int(n) for n in args.only.split(",")) if args.only else None
    planned = plan(SPEC_DIR, only)
    fill, skipped = planned["fill"], planned["skipped"]
    for path, url in skipped:
        print(f"skip (not LeetCode): {path.name}  {url}")
    summary = (f"to fill: {len(fill)}, skipped non-LeetCode: {len(skipped)}, "
               f"already set: {planned['already']}")
    if args.dry_run:
        print(f"dry-run: {summary}")
        return 0

    cache = load_cache(args.cache)
    written, problems = run_fill(fill, cache)
    if args.cache is not None:
        args.cache.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    print(f"{summary}; written: {written}, failed: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
