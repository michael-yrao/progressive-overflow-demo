#!/usr/bin/env python3
"""Generate the DSA technique-coverage report.

The spaced-repetition tracker (`dsa_progress.md`) is keyed by **problem**. That is the
right key for scheduling reviews and the wrong key for answering "do I actually know
topological sort?" — a question about a *technique*, which is spread across several
problems and sometimes several methods of the same problem.

This script joins a hand-authored technique vocabulary (`techniques.yml`) against the
tracker and emits `technique_coverage.md`, one row per technique, with three gap checks:

  no-green   no problem for this technique has ever come back 🟢 — a phase-exit blocker
             under the per-algorithm exit rule (recognition + execution, >=1 🟢 each)
  thin       fewer problems than the computed coverage threshold (`cse.config.yml`'s
             `coverage_threshold`: a floor sized off the technique's own declared problem
             count, plus its still-🔴/🟡 problems) — a technique needs more than one
             surface form before it is a skill rather than recall of one problem's solution
  variant    a declared method variant with zero problems behind it (the Kahn's-vs-DFS
             case that prompted this tool). Variants already sitting in the Waiting Room
             or Expansion Queue are marked `queued:` in the YAML and reported separately,
             so a known gap never masquerades as a new finding.

It also reports **unmapped** tracker rows. That is the anti-drift guard: a newly solved
problem shows up as unmapped until someone assigns it a technique, so the vocabulary
cannot silently fall behind the tracker the way method parentheticals do.

`techniques.yml` ships as a curriculum-wide vocabulary, so on a young tracker most of the
problems it names are simply **not solved yet**. That is the expected state, not a
finding — so an unmatched spec is split three ways: no tracker row for that number, but
the `problems:` entry itself carries a `queued: <trigger>` (same vocabulary as a
`variants:` queue) is **queued** — a known gap, named in the Action list and the Gaps
cell rather than re-reported as new; no tracker row and no `queued:` key is **declared,
not queued** (counted AND listed, so a thin technique's open slots are visible, not just
their number); a row that exists but whose *method* string doesn't match is real
**drift** and is listed. Without that split a fresh repo opens with a hundred-line
"problem" list and the report stops being read.

Usage:
    python scripts/technique_coverage.py            # write the report
    python scripts/technique_coverage.py --check    # exit 1 if the report is stale
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Git runs hooks with a cp1252 console on Windows; the first emoji printed would
# otherwise kill the script mid-report while the commit still succeeds. See _console.
import _console

_console.force_utf8()


def _load_yaml():
    """Return the `yaml` module, auto-installing PyYAML on first use.

    This script runs from the daily pre-commit hook, so it cannot assume the
    one-time `bootstrap.py` setup was ever run on this machine — a fresh clone
    would otherwise fail the coverage step on every commit. Try the import; if
    it's missing, pip-install PyYAML (falling back to `--user` for PEP-668
    externally-managed environments) and retry once. If the install itself
    fails (offline, locked-down Python), print one clear line and exit 0 — the
    hook already treats this step as non-fatal, so a stale report never blocks
    committing the day's work.
    """
    try:
        import yaml  # noqa: PLC0415
        return yaml
    except ImportError:
        pass
    for extra in ([], ["--user"]):
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", *extra, "pyyaml"]
            )
            import yaml  # noqa: PLC0415
            return yaml
        except (subprocess.CalledProcessError, ImportError):
            continue
    sys.stderr.write(
        "technique_coverage: PyYAML is required but could not be installed "
        "automatically. Install it with `pip3 install pyyaml` and re-run.\n"
    )
    raise SystemExit(0)


yaml = _load_yaml()

REPO_ROOT = Path(__file__).resolve().parent.parent
MASTERY = REPO_ROOT / "docs" / "foundations" / "dsa" / "mastery"
TECHNIQUES_YML = MASTERY / "techniques.yml"
TRACKER_MD = MASTERY / "dsa_progress.md"
REPORT_MD = MASTERY / "technique_coverage.md"
CSE_CONFIG_YML = REPO_ROOT / "cse.config.yml"

#: Announced fallback for `cse.config.yml`'s `coverage_threshold` block — mirrors that
#: block's own values (see cse.config.yml). This script already assumes techniques.yml
#: exists, so this fallback exists only for a config predating the coverage_threshold
#: feature (decision `coverage-threshold-formula-sep27`), never a pre-config repo.
DEFAULT_COVERAGE_THRESHOLD = {"plan_share": 0.5, "floor_min": 1, "floor_max": 5}

# Comfort tiers, weakest to strongest. Ordering drives "best comfort" and the
# no-green check; 🎓 and 🏆 both imply the technique has been executed cleanly.
COMFORT_ORDER = ["🔴", "🟡", "🟢", "🎓", "🏆"]
COMFORT_RANK = {c: i for i, c in enumerate(COMFORT_ORDER)}
GREEN_OR_BETTER = {"🟢", "🎓", "🏆"}

# Matches a review row in dsa_progress.md. Deliberately looser than the tracker's own
# ROW_RE (which owns rewriting the file) — this script only ever reads.
ROW_RE = re.compile(
    r"^\|\s*(?P<difficulty>[^|]+?)\s*\|\s*\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)\s*\|\s*"
    r"(?P<comfort>" + "|".join(COMFORT_ORDER) + r")\s*\|\s*(?P<streak>\d+)\s*\|"
)
# "210. Course Schedule II (Kahn's)" -> number 210, method "Kahn's"
TITLE_RE = re.compile(r"^(?P<number>\d+)\.\s*(?P<name>.+?)(?:\s*\((?P<method>[^)]+)\))?$")


@dataclass(frozen=True)
class Row:
    """One solved-problem row in the tracker."""

    number: int
    name: str
    method: str | None
    comfort: str
    streak: int
    difficulty: str

    @property
    def label(self) -> str:
        return f"{self.number} {self.name}" + (f" ({self.method})" if self.method else "")


@dataclass
class Resolved:
    """A technique after its YAML entry has been joined against the tracker."""

    name: str
    family: str
    #: The technique's computed coverage bar: `coverage_floor + unclean_count` (see
    #: `compute_coverage_threshold`). Set once, after `coverage_floor` and every matched
    #: row are known — never read before `resolve()` finishes building this technique.
    min_problems: int
    #: The floor half of `min_problems` — either the config formula's clamp(ceil(
    #: plan_share * declared), floor_min, floor_max), or an explicit `min_problems:`
    #: override from techniques.yml, which REPLACES the formula's floor (unclean_count
    #: is still added on top either way). Kept alongside `min_problems` so the Min cell
    #: can render both halves (`gamify.parse_techniques()` reads them back out).
    coverage_floor: int
    #: How many of this technique's credited problems (distinct numbers) are still
    #: 🔴/🟡 best comfort — added on top of `coverage_floor` because a shaky rep hasn't
    #: earned the technique credit toward the bar yet, whether the floor came from the
    #: formula or a manual override.
    unclean_count: int = 0
    #: Curriculum tier: "core" (already-started NC150/pattern-doc techniques — the
    #: implicit default for any YAML entry with no `tier:` key), "dp" (DP framework
    #: lenses), "tier1" (Knowledge Expansion Queue, above the interview-ROI line),
    #: "tier2"/"tier3" (below the line — competitive-programming horizon). Declared
    #: purely so the honest denominator can be shown TIERED rather than as one flat
    #: fraction (see study_guide.md's Interview-ROI Line) — it changes no gap check.
    tier: str = "core"
    rows: list[Row] = field(default_factory=list)
    variant_rows: dict[str, list[Row]] = field(default_factory=dict)
    queued_variants: dict[str, str] = field(default_factory=dict)
    #: A `problems:` entry with no matching tracker row AND a `queued: <trigger>` key —
    #: declared and already waiting on a fired trigger, so it is reported (Gaps cell +
    #: Action list) rather than silently counted as "not reached yet". Keyed by number,
    #: same trigger vocabulary as a `variants:` queue.
    queued_problems: dict[int, str] = field(default_factory=dict)
    needs_review: list[str] = field(default_factory=list)
    #: Declared, and a tracker row for that NUMBER exists, but the method didn't match.
    #: That is vocabulary drift and is worth naming.
    drifted: list[str] = field(default_factory=list)
    #: Declared and not in the tracker at all — simply not reached yet. Counted, not listed.
    unreached: list[str] = field(default_factory=list)

    @property
    def best_comfort(self) -> str:
        if not self.rows:
            return "—"
        return max((r.comfort for r in self.rows), key=lambda c: COMFORT_RANK[c])

    @property
    def has_green(self) -> bool:
        return any(r.comfort in GREEN_OR_BETTER for r in self.rows)

    @property
    def numbers(self) -> list[int]:
        """The DISTINCT problem numbers behind this technique, ascending.

        ``rows`` is one entry per *tracker row*, and a problem with two tracked method
        variants owns two rows (19 Postorder + 19 Iterative, 206 Iterative + Recursion).
        Counting rows therefore credited **one problem as two**, and the entire reason a
        technique wants 3-4 problems is *different surface forms* — two methods on the
        same problem is one surface form, drilled twice. Linked List Reversal, Remove Nth
        From End and Linked List Merge each read "2" while holding a single problem.

        So every coverage COUNT is over distinct numbers; ``rows`` stays the unit for
        comfort, greens and the variant breakdown, which are genuinely per-row.
        """
        return sorted({r.number for r in self.rows})

    @property
    def n_problems(self) -> int:
        return len(self.numbers)

    @property
    def has_multi_variant_problem(self) -> bool:
        """True when some problem contributes more than one row — i.e. rows > problems."""
        return len(self.rows) > self.n_problems

    @property
    def is_started(self) -> bool:
        """Has the learner solved anything under this technique at all?

        Every gap check is gated on this. A technique with zero rows is not weak — it is
        **ahead of the learner**, and reporting it as no-green + thin + a variant gap
        turns the whole action list into curriculum the learner already knows is coming.
        On a young tracker that is the entire report, and a report that is all noise on
        day one is one nobody opens on day two.
        """
        return bool(self.rows)

    @property
    def gaps(self) -> list[str]:
        if not self.is_started:
            return ["*not started*"]
        out: list[str] = []
        if not self.has_green:
            out.append("**no-green**")
        if self.n_problems < self.min_problems:
            out.append(f"thin ({self.n_problems}/{self.min_problems})")
        if self.queued_problems:
            out.append(f"queued: {_queued_label(self.queued_problems, parenthesize=False)}")
        for variant, rows in self.variant_rows.items():
            if not rows and variant not in self.queued_variants:
                out.append(f"variant: **{variant}**")
        return out


def parse_tracker(path: Path) -> list[Row]:
    """Read every review row out of the tracker. Non-table lines are ignored."""
    if not path.exists():
        raise SystemExit(f"Tracker not found: {path}")

    rows: list[Row] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        match = ROW_RE.match(line)
        if not match:
            continue
        title_match = TITLE_RE.match(match.group("title").strip())
        if not title_match:
            continue
        rows.append(
            Row(
                number=int(title_match.group("number")),
                name=title_match.group("name").strip(),
                method=(title_match.group("method") or "").strip() or None,
                comfort=match.group("comfort"),
                streak=int(match.group("streak")),
                difficulty=match.group("difficulty").strip(),
            )
        )
    return rows


def _matches(row: Row, spec: dict) -> bool:
    """Does a tracker row satisfy a YAML problem spec?

    `method` is the join key for problems carrying several rows (200 DFS vs BFS,
    323 DFS/BFS/Union-Find). Omit it to match every row for that number.
    """
    if row.number != spec["number"]:
        return False
    method = spec.get("method")
    return True if method is None else row.method == method


def load_coverage_threshold_config() -> dict:
    """Return `cse.config.yml`'s `coverage_threshold` block, merged over
    `DEFAULT_COVERAGE_THRESHOLD`. Fail-soft, announced (see module docstring on
    `DEFAULT_COVERAGE_THRESHOLD`): a missing file, unparsable YAML, or a config that
    predates this block all fall back to the built-in defaults with one printed line,
    rather than raising out of the pre-commit hook this script runs in.
    """
    try:
        cfg = yaml.safe_load(CSE_CONFIG_YML.read_text(encoding="utf-8")) or {}
    except OSError:
        cfg = {}
    block = cfg.get("coverage_threshold")
    if not block:
        print(
            "technique_coverage: cse.config.yml has no coverage_threshold block — using "
            f"built-in defaults {DEFAULT_COVERAGE_THRESHOLD}.",
            file=sys.stderr,
        )
        return dict(DEFAULT_COVERAGE_THRESHOLD)
    return {**DEFAULT_COVERAGE_THRESHOLD, **block}


def _all_opted_out(specs: list[dict]) -> bool:
    """True when every spec for one declared problem number carries `planned: false`
    (mirrors `gamify._all_opted_out` — a recognition probe declared for credit but not
    part of the plan should not inflate the technique's declared-problem count either).
    """
    return all(spec.get("planned") is False for spec in specs)


def _declared_count(specs: list[dict]) -> int:
    """The `declared` input to the coverage-threshold formula: the count of DISTINCT
    problem numbers under one technique's `problems:`, excluding a number whose every
    spec opts out via `planned: false` (see `_all_opted_out`). Declared variations,
    difficulty and company demand are deliberately not inputs — only breadth of
    surface-form problems is.
    """
    by_number: dict[int, list[dict]] = {}
    for spec in specs:
        by_number.setdefault(spec["number"], []).append(spec)
    return sum(1 for number_specs in by_number.values() if not _all_opted_out(number_specs))


def _unclean_count(rows: list[Row]) -> int:
    """The `unclean` input to the coverage-threshold formula: how many distinct problem
    numbers credited to a technique have a BEST comfort (across that number's matched
    rows) of 🔴 or 🟡 — still shaky, so it doesn't yet earn the technique credit toward
    the bar the way a 🟢-or-better problem does.
    """
    by_number: dict[int, list[Row]] = {}
    for row in rows:
        by_number.setdefault(row.number, []).append(row)
    dirty = {"🔴", "🟡"}
    return sum(
        1 for number_rows in by_number.values()
        if max((r.comfort for r in number_rows), key=lambda c: COMFORT_RANK[c]) in dirty
    )


def compute_coverage_threshold(
    *, declared: int, unclean: int, override: int | None,
    plan_share: float, floor_min: int, floor_max: int,
) -> tuple[int, int]:
    """Return (floor, threshold) for one technique's coverage bar.

    floor = an explicit `min_problems:` override when the technique declares one, else
    clamp(ceil(plan_share * declared), floor_min, floor_max). `unclean` is always added
    on top of the floor to get `threshold` — whether the floor came from the formula or
    a manual override, a still-shaky problem hasn't earned its coverage credit yet.
    """
    computed_floor = min(max(math.ceil(plan_share * declared), floor_min), floor_max)
    floor = computed_floor if override is None else override
    return floor, floor + unclean


def _queued_label(queued: dict[int, str], *, parenthesize: bool) -> str:
    """Render a `queued_problems` map (number -> trigger), sorted by number.

    Two call sites want two punctuation styles for the same data: the Gaps cell reads
    ``945 `trigger` `` (bare, so it stays a short inline fragment), the Action list reads
    ``945 (`trigger`)`` (parenthesized, matching how the Variants column already wraps a
    queued trigger). Neither ever contains the word "variant" — `gamify.parse_techniques()`
    reads that substring out of the Gaps cell to flag a variant gap, and a queued PROBLEM
    is not a variant gap.
    """
    parts = []
    for number, trigger in sorted(queued.items()):
        trigger_str = f"`{trigger}`"
        parts.append(f"{number} ({trigger_str})" if parenthesize else f"{number} {trigger_str}")
    return ", ".join(parts)


def resolve(
    config: dict, rows: list[Row], threshold_config: dict,
) -> tuple[list[Resolved], set[str]]:
    """Join the technique vocabulary against the tracker rows."""
    resolved: list[Resolved] = []
    claimed: set[str] = set()
    solved_numbers = {r.number for r in rows}

    for entry in config.get("techniques", []):
        specs = entry.get("problems") or []
        floor, _ = compute_coverage_threshold(
            declared=_declared_count(specs),
            unclean=0,  # unclean isn't known until rows are matched below; added after
            override=entry.get("min_problems"),
            **threshold_config,
        )
        tech = Resolved(
            name=entry["name"],
            family=entry.get("family", "—"),
            min_problems=floor,  # finalized to floor + unclean_count once rows are matched
            coverage_floor=floor,
            tier=entry.get("tier") or "core",
        )
        for variant in entry.get("variants", []) or []:
            tech.variant_rows[variant["name"]] = []
            if variant.get("queued"):
                tech.queued_variants[variant["name"]] = variant["queued"]

        for spec in specs:
            matched = [r for r in rows if _matches(r, spec)]
            if not matched:
                # No row for this number, and it is already declared queued (waiting on
                # a fired trigger, same vocabulary as a `variants:` queue) -> report it as
                # queued rather than falling into drift/unreached. A `queued:` key on a
                # spec that DOES have a row (the `matched` branch below) is simply never
                # consulted, so it is a no-op there, not an error.
                trigger = spec.get("queued")
                if trigger:
                    tech.queued_problems[spec["number"]] = trigger
                    continue
                label = str(spec["number"]) + (f" ({spec['method']})" if spec.get("method") else "")
                # A row exists for the number but the method didn't match -> drift.
                # No row at all -> the learner simply hasn't reached this problem.
                bucket = tech.drifted if spec["number"] in solved_numbers else tech.unreached
                bucket.append(label)
                continue
            for row in matched:
                tech.rows.append(row)
                claimed.add(row.label)
                variant = spec.get("variant") or spec.get("method")
                if variant and variant in tech.variant_rows:
                    tech.variant_rows[variant].append(row)
                if spec.get("review"):
                    tech.needs_review.append(row.label)

        tech.unclean_count = _unclean_count(tech.rows)
        tech.min_problems = tech.coverage_floor + tech.unclean_count
        resolved.append(tech)

    return resolved, claimed


def _min_cell(t: Resolved) -> str:
    """Render the Min column: the threshold, then its floor+unclean breakdown in
    parens (e.g. `8 (4+4)`) — `gamify.parse_techniques()` reads both the leading
    integer (threshold) and the two parenthesised ones (floor, unclean) back out.
    """
    return f"{t.min_problems} ({t.coverage_floor}+{t.unclean_count})"


def render(resolved: list[Resolved], rows: list[Row], claimed: set[str]) -> str:
    """Build the markdown report."""
    lines: list[str] = []
    add = lines.append

    add("# DSA Technique Coverage")
    add("")
    add("<!-- GENERATED by scripts/technique_coverage.py — do not edit by hand.")
    add("     Source of truth is techniques.yml (vocabulary) + dsa_progress.md (comfort).")
    add("     Regenerate: python scripts/technique_coverage.py -->")
    add("")
    add(
        "> The tracker is keyed by **problem**; this is keyed by **technique**. Use it at the "
        "weekly build to decide what to pull, and at phase exit to check the per-algorithm bar "
        "(recognition + execution, ≥1 🟢 each)."
    )
    add("")

    started = [t for t in resolved if t.is_started]
    blockers = [t for t in started if not t.has_green]
    thin = [t for t in started if t.n_problems < t.min_problems]
    variant_gaps = [
        (t, v)
        for t in started
        for v, vr in t.variant_rows.items()
        if not vr and v not in t.queued_variants
    ]
    queued_techs = [t for t in started if t.queued_problems]

    add(
        f"> **{len(started)}/{len(resolved)}** techniques started &nbsp;·&nbsp; "
        f"**{len(blockers)}** with no 🟢 &nbsp;·&nbsp; "
        f"**{len(thin)}** thin &nbsp;·&nbsp; "
        f"**{len(variant_gaps)}** unqueued variant gaps"
    )
    add("")

    if blockers or thin or variant_gaps or queued_techs:
        add("## ⚠️ Action list")
        add("")
        if blockers:
            add("**No 🟢 — blocks per-algorithm phase exit.** Execution is unproven.")
            add("")
            for t in sorted(blockers, key=lambda t: t.name):
                probs = ", ".join(str(r.number) for r in t.rows)
                add(f"- **{t.name}** ({t.family}) — best {t.best_comfort} across {probs}")
            add("")
        if thin:
            add(
                "**Thin — below its computed coverage bar** (`cse.config.yml`'s "
                "`coverage_threshold`). One instance trains recall of that problem, not "
                "the skill."
            )
            add("")
            for t in sorted(thin, key=lambda t: (t.n_problems, t.name)):
                probs = ", ".join(str(n) for n in t.numbers) or "none"
                extra = f" ({len(t.rows)} rows)" if t.has_multi_variant_problem else ""
                add(f"- **{t.name}** ({t.family}) — {t.n_problems}/{t.min_problems}{extra}: {probs}")
            add("")
        if queued_techs:
            add(
                "**Queued — declared, and already sitting in the Waiting Room / Expansion "
                "Queue.** A known gap with a fill already picked, not a new finding."
            )
            add("")
            for t in sorted(queued_techs, key=lambda t: t.name):
                label = _queued_label(t.queued_problems, parenthesize=True)
                add(f"- **{t.name}** ({t.family}) — queued: {label}")
            add("")
        if variant_gaps:
            add("**Unqueued variant gaps — a method never once exercised, and not in any queue.**")
            add("")
            for t, v in sorted(variant_gaps, key=lambda p: p[0].name):
                done = [k for k, rs in t.variant_rows.items() if rs]
                have = ", ".join(f"{k} ×{len(t.variant_rows[k])}" for k in done) or "none"
                add(f"- **{t.name}** — missing **{v}**. Exercised: {have}")
            add("")

    add("## Coverage")
    add("")
    add(
        "Every declared technique gets a row, started or not — a not-started row's Gaps "
        "cell reads `*not started*` (never blockers/thin/variant noise; see `is_started`)."
    )
    add("")
    add("| Technique | Family | Tier | Min | Problems | Best | 🟢 | Variants | Gaps |")
    add("|---|---|---|---:|---:|:---:|:---:|---|---|")
    for t in sorted(resolved, key=lambda t: (t.family, t.name)):
        probs = ", ".join(str(n) for n in t.numbers) or "—"
        if t.variant_rows:
            parts = []
            for v, rs in t.variant_rows.items():
                if rs:
                    parts.append(f"{v} ×{len(rs)}")
                elif v in t.queued_variants:
                    parts.append(f"~~{v}~~ *(queued: `{t.queued_variants[v]}`)*")
                else:
                    parts.append(f"**{v} ×0**")
            variants = " · ".join(parts)
        else:
            variants = "—"
        add(
            f"| {t.name} | {t.family} | {t.tier} | {_min_cell(t)} | {t.n_problems}"
            + (f" *+{len(t.rows) - t.n_problems}v*" if t.has_multi_variant_problem else "")
            + f" ({probs}) | {t.best_comfort} | "
            f"{'✅' if t.has_green else '❌'} | {variants} | {' · '.join(t.gaps) or '—'} |"
        )
    add("")

    unmapped = sorted({r.label for r in rows} - claimed)
    review = sorted({label for t in resolved for label in t.needs_review})
    drifted = sorted({label for t in resolved for label in t.drifted})
    unreached = sorted({label for t in resolved for label in t.unreached})
    queued_numbers = sorted({n for t in resolved for n in t.queued_problems})

    if unmapped or review or drifted or unreached or queued_numbers:
        add("## Vocabulary maintenance")
        add("")
        if unmapped:
            add(
                f"**Unmapped tracker rows ({len(unmapped)})** — solved but assigned to no "
                "technique. Add them to `techniques.yml`, or coverage silently drifts behind "
                "the tracker."
            )
            add("")
            for label in unmapped:
                add(f"- {label}")
            add("")
        if review:
            add(
                f"**Method unconfirmed ({len(review)})** — mapped, but the tracker row carries no "
                "method parenthetical, so the variant credited here is an assumption. Confirm and "
                "drop the `review: true` flag."
            )
            add("")
            for label in review:
                add(f"- {label}")
            add("")
        if drifted:
            add(
                f"**Method drift ({len(drifted)})** — the tracker HAS a row for this problem, but "
                "not with the method the vocabulary declares. Either the parenthetical changed or "
                "the YAML names the wrong variant; the technique is not being credited."
            )
            add("")
            for label in drifted:
                add(f"- {label}")
            add("")
        if queued_numbers:
            add(
                f"**Queued ({len(queued_numbers)})** — listed in the Action list above; a "
                "known gap with a fill already picked, not counted below."
            )
            add("")
        if unreached:
            add(
                f"**Declared, not queued ({len(unreached)})** — declared in the vocabulary, no "
                "tracker row, and not yet in any queue. This is the normal state for curriculum "
                f"ahead of the learner; it is a roadmap, not a finding: {', '.join(unreached)}"
            )
            add("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the report on disk differs from freshly generated output",
    )
    args = parser.parse_args()

    config = yaml.safe_load(TECHNIQUES_YML.read_text(encoding="utf-8"))
    rows = parse_tracker(TRACKER_MD)
    threshold_config = load_coverage_threshold_config()
    resolved, claimed = resolve(config, rows, threshold_config)
    report = render(resolved, rows, claimed)

    if args.check:
        current = REPORT_MD.read_text(encoding="utf-8") if REPORT_MD.exists() else ""
        if current != report:
            print(f"{REPORT_MD.name} is stale — run: python scripts/technique_coverage.py")
            return 1
        print(f"{REPORT_MD.name} is up to date.")
        return 0

    REPORT_MD.write_text(report, encoding="utf-8", newline="\n")
    unmapped = len({r.label for r in rows} - claimed)
    print(
        f"Wrote {REPORT_MD.relative_to(REPO_ROOT)} — "
        f"{len(resolved)} techniques, {len(rows)} rows, {unmapped} unmapped."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
