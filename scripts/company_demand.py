#!/usr/bin/env python3
"""Generate the company-demand report: what target companies ask, mapped onto techniques.

`pull_interview.py` answers "what can I pull next, gated by what I already know". This
answers a different question: **what do the target companies ask most, which technique
family does each problem belong to, and how much of that demand does the tracker already
cover?** Same source data (the liquidslr company-wise CSVs), a different join — against
`techniques.yml` families instead of the milestone-category gate — and a different output
shape: one report per company tier (the `TIERS` roster below), then a cross-tier "asked by
several targets and still untracked" list.

Run by hand — it needs the network for anything but `--local` — so this is NOT wired into
the pre-commit hook (unlike `technique_coverage.py`, which only reads local files).

Usage:
    python scripts/company_demand.py --tier all
    python scripts/company_demand.py --tier fintech --window 3mo --top 50
    python scripts/company_demand.py --company Google,Meta --top 30
    python scripts/company_demand.py --local scripts/fixtures/company_demand_sample.csv --stdout

Stdlib only, plus PyYAML via `technique_coverage._load_yaml()` (already a repo-wide
dependency, auto-installed there).
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pull_interview as pi  # noqa: E402
import technique_coverage as tc  # noqa: E402

DEFAULT_TOP = 100
MIN_COMPANIES_CROSS_TIER = 3
#: pull_interview.main()'s own phase-plan-match threshold, mirrored here (see
#: `_in_phase_plan`) so a short/generic normalised title can't false-positive.
MIN_PHASE_TITLE_LEN = 6
UNTRACKED_GLYPH = "—"  # —
UNMAPPED_FAMILY = "—"  # —
SCHEDULED_GLYPH = "\U0001f4c5"  # 📅
IN_PHASE_PLAN_GLYPH = "\U0001f4cb"  # 📋 — in the phase plan, no tracker row yet
GRADUATED_GLYPH = "\U0001f393"  # 🎓 — also what a 🏆 tracker row displays as here
TROPHY_GLYPH = "\U0001f3c6"  # 🏆
GREEN_GLYPH = "\U0001f7e2"  # 🟢
YELLOW_GLYPH = "\U0001f7e1"  # 🟡
RED_GLYPH = "\U0001f534"  # 🔴

# ── Company tiers ────────────────────────────────────────────────────────────
# The default ROSTER: edit it to the learner's own target companies. Folder names are the
# source repo's exact spelling (e.g. "J.P. Morgan", not "JPMorgan").
TIERS: dict[str, list[str]] = {
    "bigtech": ["Google", "Meta", "Amazon", "Microsoft", "Apple", "Netflix"],
    "dataplat": ["Snowflake", "Databricks", "Datadog", "Confluent", "MongoDB"],
    "fintech": ["Stripe", "Robinhood", "Citadel", "Bloomberg", "Goldman Sachs", "J.P. Morgan"],
    "supp": ["Uber", "Airbnb", "DoorDash", "LinkedIn"],
}

# ── Vocabulary dump ──────────────────────────────────────────────────────────
# One-liner over the roster's 6mo CSVs (`--tier all`'s default window):
#   python3 -c "import sys,csv,io; sys.path.insert(0,'scripts'); \
#     import pull_interview as pi, company_demand as cd; tags=set(); \
#     [tags.update(t.strip() for t in (r.get('Topics') or '').split(',') if t.strip()) \
#      for c in sorted({c for cs in cd.TIERS.values() for c in cs}) \
#      for r in csv.DictReader(io.StringIO(pi.fetch_csv(pi.DEFAULT_REPO, pi.DEFAULT_BRANCH, c, '6mo')))]; \
#     print(sorted(tags))"
# 142 distinct tags, EXACT spellings (en dashes, apostrophes) as the source repo returns them:
# 0-1 Knapsack, A* Search, Algorithm X, Array, Backtracking, Bellman–Ford Algorithm,
# Biconnected Component, Bidirectional Search, Binary Indexed Tree, Binary Lifting,
# Binary Search, Binary Search Tree, Binary Tree, Bipartite Graph, Bit Manipulation,
# Bitmask, Borůvka's Algorithm, Boyer–Moore Majority Vote Algorithm, Boyer–Moore
# String-Search Algorithm, Bracket Sequences, Brainteaser, Breadth-First Search, Bridge
# (Graph), Brute-Force Search, Bubble Sort, Bucket Sort, Cartesian Tree, Combinatorics,
# Complete Knapsack, Concurrency, Counting, Counting Sort, DP on Trees, Dancing Links,
# Data Stream, Database, Depth-First Search, Design, Dijkstra's Algorithm, Directed
# Acyclic Graph, Divide and Conquer, Doubly-Linked List, Dynamic Programming,
# Enumeration, Euclidean Algorithm, Euler's Theorem, Euler's Totient Function, Eulerian
# Circuit, Eulerian Path, Fermat's Little Theorem, Floyd's Cycle Finding Algorithm,
# Floyd–Warshall Algorithm, Game Theory, Geometry, Graph Coloring, Graph Theory, Greatest
# Common Divisor, Greedy, Hamiltonian Path, Hash Function, Hash Table, Heap (Priority
# Queue), Heuristic Search, Hungarian Algorithm, Impartial Game, Inclusion-Exclusion
# Principle, Interactive, Iterator, K Shortest Path, K-D Tree, Knapsack Problem,
# Knuth–Morris–Pratt Algorithm, Kosaraju's Algorithm, Kruskal's Algorithm, Least Common
# Multiple, Linear Algebra, Linked List, Longest Common Subsequence, Longest Increasing
# Subsequence, Lowest Common Ancestor, Lyndon Factorization, Manacher, Math, Matrix,
# Meet in the Middle, Memoization, Merge Sort, Minimax, Minimum Spanning Tree, Monotonic
# Queue, Monotonic Stack, Newton's Method, Nim Game, Number Theory, Ordered Set,
# Persistent Data Structure, Pigeonhole Principle, Prefix Sum, Prim's Algorithm,
# Primality Test, Prime Factorization, Prime Number Sieve, Probability and Statistics,
# Queue, Quickselect, Quicksort, Radix Sort, Randomized, Range Minimum/Maximum Query,
# Recursion, Rolling Hash, Segment Tree, Semi-Eulerian Graph, Shell, Shortest Path, Sieve
# Theory, Simulation, Sliding Window, Sorting, Sprague–Grundy Theorem, Sqrt
# Decomposition, Stack, String, String Matching, Strongly Connected Component,
# Successive Shortest Path Algorithm, Suffix Array, Suffix Automaton, Suffix Tree, Sweep
# Line, Tarjan's SCC Algorithm, Ternary Search, Timsort, Topological Sort, Tournament
# Sort, Treap, Tree, Trie, Two Pointers, Union-Find, Z Algorithm, Zero-Sum Game.
#
# Checked, and NOT present anywhere in that data (6mo or `all` window):
# JavaScript, Pandas, Data Frame. EXCLUDED_TAGS keeps "JavaScript"/"Pandas" anyway —
# a data-platform-adjacent company can surface one later, and dropping the guard the
# day it does is a worse failure mode than carrying an inert entry now.

# ── Topic tag -> technique family ────────────────────────────────────────────
# Every value here MUST be a `family:` that exists in techniques.yml (enforced by
# test_company_demand.py).
TREE_TAGS = {"Tree", "Binary Tree", "Binary Search Tree"}

TOPIC_TO_FAMILY: dict[str, str] = {
    "Array": "arrays_and_hash", "Hash Table": "arrays_and_hash",
    "Counting": "arrays_and_hash", "Enumeration": "arrays_and_hash",
    "Boyer–Moore Majority Vote Algorithm": "arrays_and_hash",
    "Two Pointers": "two_pointers",
    "Sliding Window": "sliding_window",
    "Greedy": "greedy",
    "Stack": "stack", "Monotonic Stack": "stack", "Monotonic Queue": "stack",
    "Queue": "stack", "Bracket Sequences": "stack",
    "Binary Search": "binary_search",
    "Linked List": "linked_list", "Doubly-Linked List": "linked_list",
    "Floyd's Cycle Finding Algorithm": "linked_list",
    "Tree": "trees", "Binary Tree": "trees", "Binary Search Tree": "trees",
    # DFS/BFS default to graphs; _family_for_row() overrides to trees when a tree
    # tag rides along on the same row.
    "Depth-First Search": "graphs", "Breadth-First Search": "graphs",
    "Trie": "tries",
    "Heap (Priority Queue)": "heap",
    "Backtracking": "backtracking", "Algorithm X": "backtracking",
    "Dancing Links": "backtracking",
    # Graph tag spellings the source repo actually uses — several names for the same
    # concept as the "Graph"/"Union Find" keys, kept alongside them rather than replacing
    # them. Topological Sort lives here, not under advanced_graphs: techniques.yml files
    # the technique under family: graphs.
    "Graph": "graphs", "Union Find": "graphs", "Union-Find": "graphs",
    "Matrix": "graphs", "Graph Theory": "graphs", "Bipartite Graph": "graphs",
    "Graph Coloring": "graphs", "Directed Acyclic Graph": "graphs",
    "Topological Sort": "graphs",
    "Shortest Path": "advanced_graphs", "Minimum Spanning Tree": "advanced_graphs",
    "Strongly Connected Component": "advanced_graphs",
    "Eulerian Circuit": "advanced_graphs", "Eulerian Path": "advanced_graphs",
    # Named-algorithm tags — the CSVs tag some rows with the named algorithm rather than
    # (or alongside) the general "Shortest Path"/"Minimum Spanning Tree" family tag.
    "Dijkstra's Algorithm": "advanced_graphs", "Bellman–Ford Algorithm": "advanced_graphs",
    "Floyd–Warshall Algorithm": "advanced_graphs", "Kruskal's Algorithm": "advanced_graphs",
    "Prim's Algorithm": "advanced_graphs",
    "Dynamic Programming": "dynamic_programming", "Memoization": "dynamic_programming",
    "Knapsack Problem": "dynamic_programming", "0-1 Knapsack": "dynamic_programming",
    "Complete Knapsack": "dynamic_programming",
    "Longest Increasing Subsequence": "dynamic_programming",
    "Longest Common Subsequence": "dynamic_programming", "DP on Trees": "dynamic_programming",
    "Line Sweep": "intervals", "Sweep Line": "intervals",
    "Prefix Sum": "prefix_sum",
    "Recursion": "recursion",
    "Sorting": "sorting", "Divide and Conquer": "sorting", "Merge Sort": "sorting",
    "Quickselect": "sorting", "Quicksort": "sorting", "Bucket Sort": "sorting",
    "Counting Sort": "sorting", "Radix Sort": "sorting", "Bubble Sort": "sorting",
    "Tournament Sort": "sorting",
    # The strings / math_sim / design / bit_manipulation families (decision
    # `company-demand-families-sep26`) — each a `tier: core` family in techniques.yml.
    "String": "strings",
    "Math": "math_sim", "Simulation": "math_sim", "Brainteaser": "math_sim",
    # Geometry is squarely math/simulation demand, not competitive-programming depth,
    # once a math_sim family exists to hold it.
    "Geometry": "math_sim",
    "Design": "design", "Data Stream": "design", "Iterator": "design",
    "Ordered Set": "design",
    "Bit Manipulation": "bit_manipulation",
    # Bitmask sits here for the same reason Geometry sits in math_sim.
    "Bitmask": "bit_manipulation",
    # Advanced-graph / expansion algorithm-name tags.
    "Segment Tree": "expansion", "Binary Indexed Tree": "expansion",
    "String Matching": "expansion", "Number Theory": "expansion",
    "Rolling Hash": "expansion", "Hash Function": "expansion",
    "Suffix Array": "expansion", "Randomized": "expansion",
    "Reservoir Sampling": "expansion", "Rejection Sampling": "expansion",
    "Combinatorics": "expansion", "Probability and Statistics": "expansion",
    "Game Theory": "expansion",
    "Tarjan's SCC Algorithm": "expansion", "Kosaraju's Algorithm": "expansion",
    "Bidirectional Search": "expansion", "A* Search": "expansion",
    "Heuristic Search": "expansion", "Lowest Common Ancestor": "expansion",
    "Binary Lifting": "expansion", "Range Minimum/Maximum Query": "expansion",
    "Persistent Data Structure": "expansion", "Hungarian Algorithm": "expansion",
    "Successive Shortest Path Algorithm": "expansion",
    "Fermat's Little Theorem": "expansion",
    "Knuth–Morris–Pratt Algorithm": "expansion", "Z Algorithm": "expansion",
    "Manacher": "expansion", "Boyer–Moore String-Search Algorithm": "expansion",
}

#: Rows carrying any of these tags are SQL/shell/JS/pandas practice, not DSA — dropped
#: from every table. Counted and reported in the banner, never silent.
EXCLUDED_TAGS: frozenset[str] = frozenset({
    "Database", "Shell", "Concurrency", "JavaScript", "Pandas",
})

#: Tags that are neither mapped to a family nor excluded — genuinely left for the
#: unmapped-topics table, on purpose. "Interactive" (LC's guess-the-number style rows)
#: has no technique-family home; "Data Frame" is Pandas's sibling tag and would only
#: ever ride alongside an already-excluded "Pandas" row.
DELIBERATELY_UNMAPPED: frozenset[str] = frozenset({"Interactive", "Data Frame"})

# First mapped-family match wins when a problem carries several tags.
FAMILY_PRIORITY: list[str] = [
    "design", "tries", "advanced_graphs", "graphs", "trees", "linked_list", "heap",
    "stack", "backtracking", "dynamic_programming", "sliding_window", "greedy", "binary_search",
    "intervals", "two_pointers", "prefix_sum", "sorting", "strings", "math_sim",
    "bit_manipulation", "recursion", "expansion", "arrays_and_hash",
]


@dataclass(frozen=True)
class Problem:
    """One de-duplicated problem, unioned across a tier's companies."""

    slug: str
    title: str
    difficulty: str
    link: str
    topics: frozenset[str]
    frequency: float
    companies: frozenset[str]

    @property
    def family(self) -> str:
        """Tag-priority family. This is a FALLBACK for an untracked problem — a
        tracked, credited problem uses `ReportContext.family_of()` instead (the
        vocabulary's own credit, not a tag guess). See `resolve_family_by_number`."""
        return _family_for_topics(self.topics)


_DFS_BFS_TAGS = frozenset({"Depth-First Search", "Breadth-First Search"})


def _family_for_topics(topics: frozenset[str]) -> str:
    """First FAMILY_PRIORITY match among this problem's mapped families, else '—'.

    DFS/BFS is resolved separately from the static TOPIC_TO_FAMILY lookup: its default
    there is `graphs`, but `graphs` sits ahead of `trees` in FAMILY_PRIORITY, so simply
    adding both families would let a Tree+DFS row lose to `graphs` even though the DFS
    tag itself should read as `trees` on that row.
    """
    mapped = {TOPIC_TO_FAMILY[t] for t in topics if t in TOPIC_TO_FAMILY and t not in _DFS_BFS_TAGS}
    if topics & _DFS_BFS_TAGS:
        mapped.add("trees" if topics & TREE_TAGS else "graphs")
    for family in FAMILY_PRIORITY:
        if family in mapped:
            return family
    return UNMAPPED_FAMILY


def unmapped_tags(topics: frozenset[str]) -> frozenset[str]:
    """Tags with no TOPIC_TO_FAMILY entry — reported, never silently dropped. This
    includes DELIBERATELY_UNMAPPED tags ("Interactive") on purpose: that set only
    documents that a tag was considered and rejected, it does not silence the report —
    EXCLUDED_TAGS rows never reach here at all, since parse_problems() drops the whole
    row before a Problem is ever built."""
    return frozenset(t for t in topics if t not in TOPIC_TO_FAMILY)


def tracker_comfort_by_slug() -> dict[str, str]:
    """Best comfort glyph per LeetCode slug, across every tracker row.

    A small, deliberate extension of `pull_interview.read_tracker()`: that function only
    keeps the *set* of solved slugs and the numbers that are Clean/Retired, not a per-slug
    comfort glyph. Uses `technique_coverage.ROW_RE` rather than `read_tracker`'s own
    pattern, so this join stays independent of that function's comfort alternation (see
    decision `company-demand-families-sep26`).
    """
    best: dict[str, str] = {}
    if not tc.TRACKER_MD.exists():
        return best
    for line in tc.TRACKER_MD.read_text(encoding="utf-8").splitlines():
        match = tc.ROW_RE.match(line)
        if not match:
            continue
        slug = pi.slug_from_link(match.group("url"))
        comfort = match.group("comfort")
        if slug not in best or tc.COMFORT_RANK[comfort] > tc.COMFORT_RANK[best[slug]]:
            best[slug] = comfort
    return best


def tracker_number_by_slug() -> dict[str, int]:
    """LeetCode number per tracker slug — a sibling to `tracker_comfort_by_slug()`,
    same ROW_RE/TITLE_RE join against the tracker, so a slug can be looked up against
    `resolve_family_by_number()`'s number-keyed credit map (see `ReportContext.family_of`)."""
    out: dict[str, int] = {}
    if not tc.TRACKER_MD.exists():
        return out
    for line in tc.TRACKER_MD.read_text(encoding="utf-8").splitlines():
        match = tc.ROW_RE.match(line)
        if not match:
            continue
        title_match = tc.TITLE_RE.match(match.group("title").strip())
        if not title_match:
            continue
        slug = pi.slug_from_link(match.group("url"))
        out.setdefault(slug, int(title_match.group("number")))
    return out


def resolve_family_by_number(resolved: list[tc.Resolved]) -> dict[int, str]:
    """LeetCode number -> the family of the technique that CREDITS it in techniques.yml.

    Tag priority alone gets this wrong for a tracked problem whenever its LeetCode tags
    don't agree with what it's actually drilled as: Trapping Rain Water carries a
    "Dynamic Programming" tag, but a vocabulary can credit it to a prefix/suffix-max
    technique (family `two_pointers`) — the vocabulary's own credit is ground truth for a
    tracked problem, tag priority is only ever a fallback for one that isn't (see
    `ReportContext.family_of`).

    A number credited to several techniques (rare — e.g. one number crediting both a
    DFS and a BFS entry) keeps the FIRST family in FAMILY_PRIORITY order, matching how
    `_family_for_topics` already breaks a multi-tag tie.
    """
    priority_rank = {family: rank for rank, family in enumerate(FAMILY_PRIORITY)}
    by_number: dict[int, str] = {}
    for tech in resolved:
        if not tech.is_started:
            continue
        for number in tech.numbers:
            current = by_number.get(number)
            if current is None or priority_rank.get(tech.family, len(FAMILY_PRIORITY)) < \
                    priority_rank.get(current, len(FAMILY_PRIORITY)):
                by_number[number] = tech.family
    return by_number


def _in_phase_plan(title: str, phase_text: str) -> bool:
    """Mirrors `pull_interview.main()`'s phase-plan flag exactly: a normalised title
    longer than MIN_PHASE_TITLE_LEN, contained in the phase-plan table's Categories blob."""
    norm_title = pi._norm(title)
    return len(norm_title) > MIN_PHASE_TITLE_LEN and norm_title in phase_text


def status_glyph(slug: str, comfort_by_slug: dict[str, str], roadmap: set[str],
                  title: str = "", phase_text: str = "") -> str:
    """Tracker comfort takes priority over the roadmap: `roadmap_slugs()` includes every
    tracked slug too (it scans dsa_progress.md as one of its planning docs), so checking
    the roadmap first would misclassify a tracked problem as merely 'scheduled'. The
    phase-plan flag (📋) is the weakest signal — a fuzzy title match, not a link — so it
    is checked last and only when a caller supplies `title`/`phase_text`; callers that
    don't keep the old behaviour exactly."""
    comfort = comfort_by_slug.get(slug)
    if comfort == TROPHY_GLYPH:  # 🏆 displays as 🎓 for this report
        return GRADUATED_GLYPH
    if comfort is not None:
        return comfort
    if slug in roadmap:
        return SCHEDULED_GLYPH
    if phase_text and _in_phase_plan(title, phase_text):
        return IN_PHASE_PLAN_GLYPH
    return UNTRACKED_GLYPH


@dataclass(frozen=True)
class ReportContext:
    """Everything joined from the tracker/vocabulary once per report, threaded through
    every render_* function instead of each one re-deriving it (and re-reading the
    tracker/roadmap/techniques.yml on every call)."""

    resolved: list[tc.Resolved]
    comfort_by_slug: dict[str, str]
    roadmap: set[str]
    phase_text: str
    number_by_slug: dict[str, int]
    family_by_number: dict[int, str]

    def family_of(self, problem: Problem) -> str:
        number = self.number_by_slug.get(problem.slug)
        if number is not None and number in self.family_by_number:
            return self.family_by_number[number]
        return problem.family

    def status_of(self, problem: Problem) -> str:
        return status_glyph(problem.slug, self.comfort_by_slug, self.roadmap,
                             title=problem.title, phase_text=self.phase_text)


def build_report_context() -> ReportContext:
    resolved, _ = tc.resolve(tc.curriculum.load_techniques(tc.CATALOGUE_YML, tc.TECHNIQUES_YML),
                              tc.parse_tracker(tc.TRACKER_MD),
                              tc.load_coverage_threshold_config())
    return ReportContext(
        resolved=resolved,
        comfort_by_slug=tracker_comfort_by_slug(),
        roadmap=pi.roadmap_slugs(),
        phase_text=pi.roadmap_phase_text(),
        number_by_slug=tracker_number_by_slug(),
        family_by_number=resolve_family_by_number(resolved),
    )


def fetch_companies(companies: list[str], window: str) -> tuple[dict[str, str], list[str]]:
    """Fetch each company's CSV once. Returns (company -> csv text, skipped company names)."""
    texts: dict[str, str] = {}
    skipped: list[str] = []
    for company in companies:
        try:
            texts[company] = pi.fetch_csv(pi.DEFAULT_REPO, pi.DEFAULT_BRANCH, company, window)
        except Exception as exc:  # matches pull_interview's own catch-and-continue
            print(f"! skipping {company}: {exc}", file=sys.stderr)
            skipped.append(company)
    return texts, skipped


@dataclass(frozen=True)
class ParsedCsv:
    """One company's CSV, split three ways: keepable problems, the count EXCLUDED_TAGS
    dropped (SQL/shell/JS/pandas rows — never a technique-family question), and the rows
    with an empty Topics field (neither excluded by tag nor mappable by tag — a JS/pandas
    row with no tag at all, or a brand-new untagged DSA problem; see UNTAGGED_FOOTER_HEADING)."""

    problems: list[Problem]
    excluded: int
    untagged: list[Problem]


def parse_problems(text: str, company: str) -> ParsedCsv:
    """One tier's raw CSV rows for one company, not yet merged with siblings."""
    problems: list[Problem] = []
    untagged: list[Problem] = []
    excluded = 0
    for row in csv.DictReader(io.StringIO(text)):
        link = (row.get("Link") or "").strip()
        if not link:
            continue
        topics = frozenset(t.strip() for t in (row.get("Topics") or "").split(",") if t.strip())
        if topics & EXCLUDED_TAGS:
            excluded += 1
            continue
        try:
            frequency = float(row.get("Frequency") or 0)
        except ValueError:
            frequency = 0.0
        problem = Problem(
            slug=pi.slug_from_link(link),
            title=(row.get("Title") or "?").strip(),
            difficulty=(row.get("Difficulty") or "?").strip(),
            link=link,
            topics=topics,
            frequency=frequency,
            companies=frozenset({company}),
        )
        if not topics:
            # EXCLUDED_TAGS matches on TAGS; a row with no tags at all (JS/pandas rows
            # like "Create Hello World Function", but also a genuinely untagged new DSA
            # problem) can never be caught by it. Drop it from every table too, same as
            # an excluded row, but count and list it separately — it isn't necessarily
            # SQL/JS/shell noise, so it gets its own footer rather than vanishing.
            untagged.append(problem)
            continue
        problems.append(problem)
    return ParsedCsv(problems=problems, excluded=excluded, untagged=untagged)


def merge_problems(per_company: list[Problem]) -> list[Problem]:
    """De-dup by slug: keep max frequency, union the asking companies."""
    by_slug: dict[str, Problem] = {}
    for problem in per_company:
        prior = by_slug.get(problem.slug)
        if prior is None:
            by_slug[problem.slug] = problem
            continue
        by_slug[problem.slug] = Problem(
            slug=prior.slug,
            title=prior.title if prior.frequency >= problem.frequency else problem.title,
            difficulty=prior.difficulty if prior.frequency >= problem.frequency else problem.difficulty,
            link=prior.link,
            topics=prior.topics | problem.topics,
            frequency=max(prior.frequency, problem.frequency),
            companies=prior.companies | problem.companies,
        )
    ordered = sorted(by_slug.values(), key=lambda p: (-p.frequency, p.title))
    return ordered


@dataclass(frozen=True)
class TierReport:
    """Everything rendered for one company tier."""

    tier: str
    fetched: list[str]
    union: list[Problem]
    top: list[Problem]
    excluded: int


def build_tier_report(tier: str, companies: list[str], parsed_by_company: dict[str, ParsedCsv],
                       top_n: int) -> TierReport:
    fetched = [c for c in companies if c in parsed_by_company]
    per_company = [p for c in fetched for p in parsed_by_company[c].problems]
    excluded = sum(parsed_by_company[c].excluded for c in fetched)
    union = merge_problems(per_company)
    top = union[: min(top_n, len(union))]
    return TierReport(tier=tier, fetched=fetched, union=union, top=top, excluded=excluded)


def _family_row_verdict(family: str, resolved: list[tc.Resolved]) -> tuple[int, int, int, str]:
    """(started, has_green, thin, verdict) for one family, restricted to its techniques."""
    in_family = [t for t in resolved if t.family == family and t.is_started]
    if not in_family:
        return 0, 0, 0, "not started"
    thin = [t for t in in_family if t.n_problems < t.min_problems]
    missing_green = [t for t in in_family if not t.has_green]
    verdict = "thin" if (thin or missing_green) else "covered"
    return len(in_family), len(in_family) - len(missing_green), len(thin), verdict


def render_demand_table(tier: str, top: list[Problem], ctx: ReportContext) -> list[str]:
    counts: dict[str, int] = {UNMAPPED_FAMILY: 0}  # always shown, even with zero demand
    for problem in top:
        family = ctx.family_of(problem)
        counts[family] = counts.get(family, 0) + 1
    total = len(top) or 1
    lines = [f"### {tier} — demand vs supply by family", "",
             f"| Family | Demand | Started / {GREEN_GLYPH} / thin | Verdict |", "|---|---|---|---|"]
    for family, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        pct = round(100 * count / total)
        label = "(unmapped)" if family == UNMAPPED_FAMILY else family
        if family == UNMAPPED_FAMILY:
            lines.append(f"| {label} | {count} ({pct}%) | — | NO FAMILY |")
            continue
        started, has_green, thin, verdict = _family_row_verdict(family, ctx.resolved)
        lines.append(f"| {label} | {count} ({pct}%) | {started} / {has_green} / {thin} | {verdict} |")
    lines.append("")
    return lines


def render_unmapped_table(tier: str, top: list[Problem]) -> list[str]:
    tag_rows: dict[str, list[Problem]] = {}
    for problem in top:
        for tag in unmapped_tags(problem.topics):
            tag_rows.setdefault(tag, []).append(problem)
    lines = [f"### {tier} — unmapped topics", ""]
    if not tag_rows:
        lines += ["none", ""]
        return lines
    lines += ["| Tag | Count | Top 3 titles |", "|---|---|---|"]
    for tag, problems in sorted(tag_rows.items(), key=lambda kv: -len(kv[1])):
        top3 = sorted(problems, key=lambda p: -p.frequency)[:3]
        titles = ", ".join(p.title for p in top3)
        lines.append(f"| {tag} | {len(problems)} | {titles} |")
    lines.append("")
    return lines


def render_top_table(tier: str, top: list[Problem], ctx: ReportContext) -> list[str]:
    lines = [f"### {tier} — top-{len(top)} problems", "",
             "| # | Diff | Problem | Family | Status | Freq | Asked by |", "|---:|---|---|---|---|---:|---|"]
    for i, p in enumerate(top, start=1):
        status = ctx.status_of(p)
        family = ctx.family_of(p)
        family_label = "—" if family == UNMAPPED_FAMILY else family
        companies = ", ".join(sorted(p.companies))
        lines.append(f"| {i} | {p.difficulty} | [{p.title}]({p.link}) | {family_label} | "
                      f"{status} | {p.frequency:.1f} | {companies} |")
    lines.append("")
    return lines


def render_summary_line(tier: str, companies: list[str], top: list[Problem], union: list[Problem],
                         ctx: ReportContext) -> str:
    # Named locals, not string-literal dict keys with escapes inside f-string braces —
    # a backslash inside an f-string `{...}` expression is a SyntaxError before
    # Python 3.12 (PEP 701), and this repo targets 3.11+.
    glyphs = [ctx.status_of(p) for p in top]
    graduated = glyphs.count(GRADUATED_GLYPH)
    green = glyphs.count(GREEN_GLYPH)
    yellow = glyphs.count(YELLOW_GLYPH)
    red = glyphs.count(RED_GLYPH)
    scheduled = glyphs.count(SCHEDULED_GLYPH)
    in_phase_plan = glyphs.count(IN_PHASE_PLAN_GLYPH)
    untracked = glyphs.count(UNTRACKED_GLYPH)
    covered = graduated + green
    pct = round(100 * covered / len(top)) if top else 0
    return (f"**{tier}** ({', '.join(companies)}): {len(union)} unique problems · "
            f"top-{len(top)} covered {pct}% ({GRADUATED_GLYPH}{graduated} · "
            f"{GREEN_GLYPH}{green} · {YELLOW_GLYPH}{yellow} · "
            f"{RED_GLYPH}{red} · {SCHEDULED_GLYPH}{scheduled} · "
            f"{IN_PHASE_PLAN_GLYPH}{in_phase_plan} · "
            f"{UNTRACKED_GLYPH} {untracked})")


def render_cross_tier(reports: list[TierReport], ctx: ReportContext,
                       learned_topics: set[str]) -> list[str]:
    """Problems asked by >= MIN_COMPANIES_CROSS_TIER companies (across ALL fetched
    companies, any tier) and still untracked (status '—'; 📅 scheduled and 📋
    phase-plan matches are both excluded, same as before)."""
    merged = merge_problems([p for report in reports for p in report.union])
    candidates = [p for p in merged
                  if len(p.companies) >= MIN_COMPANIES_CROSS_TIER
                  and ctx.status_of(p) == UNTRACKED_GLYPH]
    grouped: dict[str, list[Problem]] = {}
    for p in candidates:
        grouped.setdefault(ctx.family_of(p), []).append(p)

    lines = [f"## Asked by ≥{MIN_COMPANIES_CROSS_TIER} target companies and untracked", ""]
    if not candidates:
        lines += ["none", ""]
        return lines
    lines += ["| Family | Problem | Diff | Companies | Max freq | Gated |", "|---|---|---|---|---:|:---:|"]
    for family in sorted(grouped, key=lambda f: -len(grouped[f])):
        rows = sorted(grouped[family], key=lambda p: (-len(p.companies), -p.frequency))
        for p in rows:
            gated = "✓" if p.topics & learned_topics else "✗"
            companies = f"{len(p.companies)} ({', '.join(sorted(p.companies))})"
            fam_label = "—" if family == UNMAPPED_FAMILY else family
            lines.append(f"| {fam_label} | [{p.title}]({p.link}) | {p.difficulty} | "
                         f"{companies} | {p.frequency:.1f} | {gated} |")
    lines.append("")
    return lines


#: The untagged-rows footer's own heading, named so the banner's "(listed at the foot)"
#: promise and the test asserting the section both point at one string, not two copies.
UNTAGGED_FOOTER_HEADING = "### Untagged rows (excluded)"


def render_untagged_footer(untagged: list[Problem]) -> list[str]:
    """Distinct titles across ALL fetched companies (merged, not per-tier) whose Topics
    field was empty — dropped from every table like an EXCLUDED_TAGS row, but listed here
    by name so nothing vanishes silently (see ParsedCsv.untagged)."""
    lines = [UNTAGGED_FOOTER_HEADING, ""]
    if not untagged:
        lines += ["none", ""]
        return lines
    lines += ["| Problem | Companies |", "|---|---:|"]
    for p in sorted(untagged, key=lambda p: (-len(p.companies), p.title)):
        lines.append(f"| [{p.title}]({p.link}) | {len(p.companies)} |")
    lines.append("")
    return lines


def render_report(tier_companies: dict[str, list[str]], texts_by_company: dict[str, str],
                   skipped: list[str], window_label: str, top_n: int, today: date) -> str:
    ctx = build_report_context()
    learned_topics_set, _ = pi.learned_topics()

    all_fetched = sorted({c for cs in tier_companies.values() for c in cs if c in texts_by_company})
    parsed_by_company = {c: parse_problems(texts_by_company[c], c) for c in all_fetched}
    excluded_total = sum(p.excluded for p in parsed_by_company.values())
    untagged_total = sum(len(p.untagged) for p in parsed_by_company.values())
    all_untagged = merge_problems([p for parsed in parsed_by_company.values() for p in parsed.untagged])
    counts_line = " · ".join(f"{c} {len(parsed_by_company[c].problems)}" for c in all_fetched)

    lines = [
        "<!-- GENERATED by scripts/company_demand.py — do not edit by hand. "
        "Regenerate: python scripts/company_demand.py --tier all -->",
        "",
        f"# Company demand — {window_label}, generated {today.isoformat()}",
        "",
        f"Fetched: {', '.join(all_fetched) or 'none'}."
        + (f" Skipped: {', '.join(skipped)}." if skipped else ""),
        "",
        counts_line or "(none fetched)",
        "",
        f"Excluded {excluded_total} SQL/JS/shell rows · {untagged_total} untagged rows "
        f"(listed at the foot).",
        "",
        # Generated status counts (🎓N · 🟢N · …) below coincidentally match a
        # cse.config.yml comfort_units value some weeks — this whole block is machine
        # output, never hand-restated, so it is exempt start to finish.
        "<!-- single-source-ok: generated status counts -->",
        "",
    ]

    reports = [build_tier_report(tier, companies, parsed_by_company, top_n)
               for tier, companies in tier_companies.items()]

    for report in reports:
        lines.append(render_summary_line(report.tier, report.fetched, report.top, report.union, ctx))
    lines.append("")

    for report in reports:
        lines += render_demand_table(report.tier, report.top, ctx)
        lines += render_unmapped_table(report.tier, report.top)
        lines += render_top_table(report.tier, report.top, ctx)

    lines += render_cross_tier(reports, ctx, learned_topics_set)
    lines += render_untagged_footer(all_untagged)

    lines += [
        "---", "",
        "Family for a multi-tag problem = first match in FAMILY_PRIORITY, UNLESS the "
        "problem is already tracked and credited to a technique in techniques.yml, in "
        "which case that technique's family wins (see `resolve_family_by_number`).",
        "",
    ]
    return "\n".join(lines) + "\n"


def _tier_arg_to_companies(args: argparse.Namespace) -> dict[str, list[str]]:
    if args.local:
        stem = Path(args.local).stem
        return {stem: [stem]}
    if args.company:
        return {"custom": [c.strip() for c in args.company.split(",") if c.strip()]}
    if args.tier == "all":
        return dict(TIERS)
    return {args.tier: TIERS[args.tier]}


def _texts_for(tier_companies: dict[str, list[str]], args: argparse.Namespace,
               window: str) -> tuple[dict[str, str], list[str]]:
    if args.local:
        stem = Path(args.local).stem
        return {stem: Path(args.local).read_text(encoding="utf-8")}, []
    companies = sorted({c for cs in tier_companies.values() for c in cs})
    return fetch_companies(companies, window)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=["bigtech", "dataplat", "fintech", "supp", "all"],
                        default="all")
    parser.add_argument("--window", choices=list(pi.WINDOWS), default="6mo")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--company", help="comma-separated companies, ad-hoc tier 'custom'")
    parser.add_argument("--local", help="a local CSV, treated as one tier named after the file")
    parser.add_argument("--out", default=str(tc.MASTERY / "company_demand.md"))
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    tier_companies = _tier_arg_to_companies(args)
    window = "all" if args.local else args.window
    texts, skipped = _texts_for(tier_companies, args, window)
    window_label = Path(args.local).name if args.local else pi.WINDOWS[window]

    report = render_report(tier_companies, texts, skipped, window_label, args.top, date.today())

    if args.stdout:
        print(report)
        return 0
    out_path = Path(args.out)
    out_path.write_text(report, encoding="utf-8", newline="\n")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
