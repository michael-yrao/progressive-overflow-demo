#!/usr/bin/env python3
"""Compact digest of the OPEN self-eval entries — the LITM-safe way to run a meta-review.

## Why this exists

`self_eval_log.md` grows without bound. The meta-review's job is to CLUSTER the
open entries by root cause and promote any 2+ recurrence up the intervention ladder. Reading
the whole file to do that is the lost-in-the-middle failure: a rule (or a recurrence) stated in the middle of a long read gets skimmed past.
The cure recorded there is *small hot context*, not compressing the middle — so this prints
ONE line per open entry (date, priority, the "what" in ~14 words, any recurrence-family tag),
turning the cluster step into a ~15-line read instead of a 79K-token one.

Pair with `scripts/session_date.py`'s sibling `session_start_memory.py::meta_review_banner`,
which FIRES the review (injects the OVERDUE banner). This is what you run WHEN it fires.

## What counts as open

An entry is a dated block starting `## YYYY-MM-DD ...` or `- **YYYY-MM-DD ...` (or `- YYYY-...`).
Status is read from the entry's STATUS MARKER, never from prose: `is_closed()` treats a
`consolidated→`/`status: consolidated` marker as closed, lets an explicit `open`/`(status: open)`
marker beat a prose "resolved", and only then falls back to a trailing "resolved". A bare keyword
match wrongly closed three still-open entries whose prose merely contained "resolved" — this is why
the precise marker check exists.

Deliberately TAG-AGNOSTIC: unlike the banner (which requires a `[P\\d]` tag and so silently
misses an untagged entry), this counts every open dated block.
That gap is itself a finding: entries SHOULD carry `[Px]` and, going forward, a `fam:` tag so the
clustering below can be mechanical rather than eyeballed.

Usage:
    python scripts/meta_review_digest.py            # digest of opens since the last meta-review
    python scripts/meta_review_digest.py --all      # every open entry, not just since last review
    python scripts/meta_review_digest.py --check     # exit 1 if any open entry exists (CI parity)
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / ".claude" / "memory" / "self_eval_log.md"

# A block starts at a dated header (## form) or a dated bullet (- form, optional ** bold).
BLOCK_START = re.compile(r"^(?:## |-\s+\*{0,2})(\d{4}-\d{2}-\d{2})\b")
# A meta-review section header — its own block, never an entry, never archived.
META_HEADER = re.compile(r"^#+\s.*META-REVIEW\D*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
# Status must be read from the STATUS MARKER, not from prose: "resolved"/"consolidated"
# appear in prose ("stop once the conversation has resolved") in entries that are still
# OPEN, so a bare keyword match wrongly closes them. An explicit open marker WINS.
CONS_STATUS = re.compile(r"consolidated\s*(?:→|->|:)|`consolidated|status:\s*consolidated", re.IGNORECASE)
OPEN_STATUS = re.compile(r"`open`|\(status:\s*open\)|\.\s+open\.\s*$", re.IGNORECASE | re.MULTILINE)
RESOLVED_TAIL = re.compile(r"(?<![a-z])resolved\b\.?\s*$", re.IGNORECASE)


def is_closed(body: str) -> bool:
    """Whether an entry's own STATUS is closed (consolidated/resolved), not its prose."""
    if CONS_STATUS.search(body):
        return True
    if OPEN_STATUS.search(body):
        return False                       # explicit open marker beats a prose "resolved"
    lines = [ln for ln in body.strip().splitlines() if ln.strip()]
    tail = " ".join(lines[-2:]) if lines else ""
    return bool(RESOLVED_TAIL.search(tail.strip()))


# A recurrence-family tag, either the prose form or the shorthand this script promotes.
FAM = re.compile(r"(?:Recurrence family|fam)\s*[:=]\s*([^.\n]+)", re.IGNORECASE)
PRIORITY = re.compile(r"\[(P\d)\]")
# A fix that was written down but never made. Flagged so the review cannot mistake a
# proposal for a landed rung.
PROPOSED_ONLY = re.compile(r"proposed,?\s+(?:but\s+)?not\s+(?:yet\s+)?(?:edited|landed|written|done|applied)", re.I)


def blocks(text: str) -> list[tuple[str, str]]:
    """Split the log into (date, body) blocks. Non-header preamble lines are ignored."""
    out: list[tuple[str, str]] = []
    cur_date: str | None = None
    cur: list[str] = []
    for line in text.splitlines():
        m = BLOCK_START.match(line)
        meta = META_HEADER.match(line)
        if m or meta:
            if cur_date is not None:
                out.append((cur_date, "\n".join(cur)))
            cur_date = (m.group(1) if m else "META-" + meta.group(1))
            cur = [line]
        elif cur_date is not None:
            cur.append(line)
    if cur_date is not None:
        out.append((cur_date, "\n".join(cur)))
    return out


def last_meta_review(bs: list[tuple[str, str]]) -> str | None:
    dates = [d[5:] for d, _ in bs if d.startswith("META-")]
    return max(dates) if dates else None


def summarize(body: str, width: int = 14) -> str:
    """The block's 'what', flattened to ~`width` words of the first prose line."""
    for line in body.splitlines()[1:]:
        s = line.strip().lstrip("*").strip()
        if s.lower().startswith(("**what", "what:")):
            s = re.sub(r"(?i)^\**what[^:]*:\**", "", s).strip()
        if s and not s.startswith(("---", "**Why", "**Fix", "**The")):
            words = s.split()
            return " ".join(words[:width]) + (" …" if len(words) > width else "")
    # Fall back to the tail of the header line after the em-dash.
    head = body.splitlines()[0]
    tail = re.split(r"\s[—-]\s", head, maxsplit=1)
    return (tail[1][:80] if len(tail) > 1 else head[:80]).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true",
                    help="every open entry, not just those after the last meta-review")
    ap.add_argument("--check", action="store_true", help="exit 1 if any open entry exists")
    args = ap.parse_args()

    try:
        text = LOG.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"meta_review_digest: cannot read {LOG} ({exc})")
        return 2

    bs = blocks(text)
    last = last_meta_review(bs)
    opens = [
        (d, b) for d, b in bs
        if not d.startswith("META-") and not is_closed(b)
        and (args.all or last is None or d > last)
    ]
    opens.sort(reverse=True)

    if args.check:
        return 1 if opens else 0

    scope = "ALL open" if args.all else f"open since last meta-review ({last or 'none recorded'})"
    print(f"{len(opens)} {scope}:\n")
    fam_tally: dict[str, int] = {}
    proposed_only = 0
    for d, b in opens:
        pr = PRIORITY.search(b)
        fam = FAM.search(b)
        fam_txt = fam.group(1).strip()[:38] if fam else ""
        if fam_txt:
            key = fam_txt.lower()
            fam_tally[key] = fam_tally.get(key, 0) + 1
        prefix = f"{d} [{pr.group(1)}]" if pr else f"{d} [P?]"
        line = f"  {prefix}  {summarize(b)}"
        if fam_txt:
            line += f"   ⟨fam: {fam_txt}⟩"
        if PROPOSED_ONLY.search(b):
            line += "   ⚠️ PROPOSED-ONLY"
            proposed_only += 1
        print(line)

    dupes = {k: n for k, n in fam_tally.items() if n >= 2}
    print("\nCluster hint: group the lines above by root cause; any 2+ recurrence is a promotion.")
    if dupes:
        print("  tagged families with 2+ open: " + "; ".join(f"{k} ×{n}" for k, n in dupes.items()))
    if proposed_only:
        print(f"  {proposed_only} open entries PROPOSED a fix that was never landed "
              "— land it or re-status it; a proposal is not a fix.")
    untagged = sum(1 for _, b in opens if not FAM.search(b))
    if untagged:
        print(f"  {untagged}/{len(opens)} open entries carry no fam: tag — cluster these by hand, "
              "and add a fam: tag when you log next time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
