#!/usr/bin/env python3
"""Weekly technique-comfort audit — the technique-keyed progression view.

`technique_coverage.md` answers "where are the GAPS" (no-green / thin / variant). This answers
a different question the learner asked for (2026-08-22): **"what is my overall comfort per
technique, and why"** — a standing progression view, refreshed at each weekly build, that also
looks FORWARD to algorithms not yet started.

Division of labour, by design:
  - The COMFORT + COVERAGE columns are GENERATED here, rolled up from the tracker via the same
    join `technique_coverage.py` uses (imported, not reimplemented). Comfort = the technique's
    demonstrated ceiling (`best_comfort`); coverage tempers it with problem/green counts, and the
    why-line carries the nuance a single emoji cannot.
  - The WHY column is HAND-AUTHORED by the coach and PRESERVED across regens, keyed by technique
    name. A technique newly appearing in the tracker is added with an empty why for the coach to
    fill (it prints a reminder naming them).
  - The FUTURE section (roadmap algorithms not yet started) is entirely hand-authored and
    preserved VERBATIM between the FUTURE markers — the phase-plan table in study_guide.md is its
    reference, but mapping a future PHASE to its ALGORITHMS is a judgement, not a parse.

Run at the weekly build (step 8), not from the pre-commit hook — this is a weekly artifact and
churning it every commit would fight the preserved narrative:

    python scripts/technique_comfort_audit.py            # rewrite, preserving why + future
    python scripts/technique_comfort_audit.py --check    # exit 1 if the generated columns are stale
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# Reuse the tracker⋈techniques join wholesale — this file must never drift from how coverage
# computes comfort, and the only way to guarantee that is to not have a second implementation.
import technique_coverage as tc

AUDIT_MD = tc.MASTERY / "technique_comfort_audit.md"

FUTURE_START = "<!-- FUTURE:START — hand-authored roadmap view; never auto-generated -->"
FUTURE_END = "<!-- FUTURE:END -->"

# A generated Started-table row: | Technique | Comfort | Coverage | Why |
# The why cell is the only hand-authored part; captured to survive regeneration.
ROW_RE = re.compile(r"^\|\s*(?P<name>[^|]+?)\s*\|[^|]*\|[^|]*\|\s*(?P<why>.*?)\s*\|\s*$")

# Family display names + order — mirrors the dsa/leetcode/<folder> grouping coverage uses.
FAMILY_ORDER = [
    "arrays_and_hash", "two_pointers", "sliding_window", "stack", "binary_search",
    "linked_list", "trees", "trie", "heap", "backtracking", "graphs", "advanced_graphs",
    "greedy", "intervals", "dp_1d", "dp_2d", "bit_manipulation", "math_and_geometry",
]


def family_rank(fam: str) -> tuple[int, str]:
    return (FAMILY_ORDER.index(fam) if fam in FAMILY_ORDER else len(FAMILY_ORDER), fam)


def coverage_cell(t: tc.Resolved) -> str:
    """Problem/green counts that temper the single best-comfort emoji."""
    greens = len({r.number for r in t.rows if r.comfort in tc.GREEN_OR_BETTER})
    weakest = min((r.comfort for r in t.rows), key=lambda c: tc.COMFORT_RANK[c])
    span = t.best_comfort if weakest == t.best_comfort else f"{weakest}→{t.best_comfort}"
    return f"{t.n_problems}p · {greens}🟢 · {span}"


def parse_existing(text: str) -> tuple[dict[str, str], str]:
    """Return (why-lines keyed by technique name, the FUTURE block verbatim incl. markers)."""
    whys: dict[str, str] = {}
    body = text
    future = ""
    if FUTURE_START in text and FUTURE_END in text:
        pre, rest = text.split(FUTURE_START, 1)
        block, _post = rest.split(FUTURE_END, 1)
        future = FUTURE_START + block + FUTURE_END
        body = pre  # only the Started tables carry generated rows to harvest whys from
    for line in body.splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        name, why = m.group("name").strip(), m.group("why").strip()
        # Skip the header/separator rows (| Technique | / |---|).
        if name.lower() == "technique" or set(name) <= {"-", ":"}:
            continue
        whys[name] = why
    return whys, future


def default_future() -> str:
    """Seed FUTURE block on first run — hand-edit after; the script never rewrites it."""
    return (
        FUTURE_START
        + "\n\n## Future algorithms (roadmap)\n\n"
        + "> Not yet started — comfort is ⚪ by definition; the value is the WHY. Reference: the\n"
        + "> phase-plan table in [`study_guide.md`](../study_guide.md). Hand-authored; edit freely.\n\n"
        + "| Algorithm | Comfort | Opens | Why |\n|---|---|---|---|\n"
        + "| _(fill at the next weekly build)_ | ⚪ | — | — |\n\n"
        + FUTURE_END
    )


def render(resolved: list[tc.Resolved], whys: dict[str, str], future: str) -> str:
    started = [t for t in resolved if t.is_started]
    started_names = {t.name for t in started}
    green_techs = sum(1 for t in started if t.has_green)
    no_green = sum(1 for t in started if not t.has_green)

    out: list[str] = []
    add = out.append
    add("# Technique Comfort Audit\n")
    add("<!-- The COMFORT + COVERAGE columns are GENERATED by scripts/technique_comfort_audit.py")
    add("     from the tracker. The WHY column is hand-authored and PRESERVED across regens.")
    add("     The FUTURE section is hand-authored and preserved verbatim between its markers.")
    add("     Run at the weekly build: python scripts/technique_comfort_audit.py -->\n")
    add(
        f"> **{len(started)}** techniques started &nbsp;·&nbsp; **{green_techs}** with a 🟢 "
        f"&nbsp;·&nbsp; **{no_green}** still zero-green. Comfort = demonstrated ceiling "
        f"(best across the technique's problems); coverage tempers it.\n"
    )

    # ── Needs-work callout — GENERATED, weakest-first. This is the pull-order source the weekly
    # build reads FIRST. Priority the schedule should honour (settled Aug 22, 2026):
    #   🔴/🟡 conversions here  >  overdue 🟢 cleans  >  thin-green fills + probes.
    # i.e. a zero-green technique outranks DISCRETIONARY work and FRESH cleans, but not a clean
    # aged far past its interval (an aged clean is a retention risk that makes NEW demand).
    zero_green = sorted(
        (t for t in started if not t.has_green),
        key=lambda t: (tc.COMFORT_RANK[t.best_comfort], t.name),
    )
    thin_green = sorted(
        (t for t in started if t.has_green and t.n_problems < t.min_problems),
        key=lambda t: (t.n_problems, t.name),
    )
    add("## ⚠️ Needs work — pull order for the weekly build\n")
    add("> Priority: **🔴/🟡 conversions below > overdue 🟢 cleans > thin-green fills**. A zero-green")
    add("> technique outranks discretionary work and fresh cleans — not a clean aged far past its interval.\n")
    add(f"**Zero-green ({len(zero_green)}) — execution unproven, weakest first:**\n")
    if zero_green:
        for t in zero_green:
            add(f"- {t.best_comfort} **{t.name}** ({t.family}) — {coverage_cell(t)}")
    else:
        add("- _none — every started technique has a 🟢._")
    add(f"\n**Thin-green ({len(thin_green)}) — proven but narrow, discretionary:**\n")
    if thin_green:
        add("- " + " · ".join(f"**{t.name}** ({t.n_problems}/{t.min_problems})" for t in thin_green))
    else:
        add("- _none._")
    add("")

    add("## Started techniques\n")
    by_family: dict[str, list[tc.Resolved]] = defaultdict(list)
    for t in started:
        by_family[t.family].append(t)

    for fam in sorted(by_family, key=family_rank):
        add(f"### {fam}\n")
        add("| Technique | Comfort | Coverage | Why |")
        add("|---|---|---|---|")
        for t in sorted(by_family[fam], key=lambda t: t.name):
            why = whys.get(t.name, "")
            add(f"| {t.name} | {t.best_comfort} | {coverage_cell(t)} | {why} |")
        add("")

    add(future if future else default_future())
    add("")

    missing = sorted(n for n in started_names if not whys.get(n))
    if missing:
        add(f"<!-- {len(missing)} technique(s) need a why-line: {', '.join(missing)} -->")
        add("")
    return "\n".join(out).rstrip() + "\n", missing


def build() -> tuple[str, list[str]]:
    config = tc.yaml.safe_load(tc.TECHNIQUES_YML.read_text(encoding="utf-8"))
    rows = tc.parse_tracker(tc.TRACKER_MD)
    resolved, _claimed = tc.resolve(config, rows, tc.load_coverage_threshold_config())
    existing = AUDIT_MD.read_text(encoding="utf-8") if AUDIT_MD.exists() else ""
    whys, future = parse_existing(existing)
    return render(resolved, whys, future)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the generated columns on disk are stale")
    args = parser.parse_args()

    report, missing = build()

    if args.check:
        current = AUDIT_MD.read_text(encoding="utf-8") if AUDIT_MD.exists() else ""
        if current != report:
            print(f"{AUDIT_MD.name} is stale — run: python scripts/technique_comfort_audit.py")
            return 1
        print(f"{AUDIT_MD.name} is up to date.")
        return 0

    AUDIT_MD.write_text(report, encoding="utf-8", newline="\n")
    msg = f"Wrote {AUDIT_MD.relative_to(tc.REPO_ROOT)}"
    if missing:
        msg += f" — ⚠️ {len(missing)} technique(s) still need a why-line: {', '.join(missing)}"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
