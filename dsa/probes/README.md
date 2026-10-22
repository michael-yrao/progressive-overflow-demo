# 🎯 Recognition probes

**One unseen LeetCode problem per week, label stripped, solved cold.** Full rationale in
`.claude/memory/project_recognition_probes.md`. Scaffold one with `python scripts/new_problem.py
--probe --number <n> --title "<name>"` — it writes here, with a "you name it" header and a
local-link-only report (no LC/NC), so the technique is never spoiled.

## Why this directory exists at all

Two reasons, both structural.

**1. The normal scaffold path is a spoiler.** `new_problem.py` writes to
`dsa/leetcode/<pattern>/<number>_<name>.py` — so the *folder name tells you the technique* before you
have read the problem statement. For every other rep that is harmless. For a probe it destroys the only
thing being measured.

**2. It keeps probes out of the tracker automatically.** `cse.config.yml` sets
`solutions.roots: ["dsa/leetcode"]`, and `update_review_dates.py` auto-creates a tracker row for any
file it discovers under those roots. `dsa/probes/` sits **outside** that root, so a probe file is never
discovered and no `discovery_skip` entry is ever needed — the preferred handling for **disposable reps**.

> ⚠️ **Never move this directory under `dsa/leetcode/`, and never add `dsa/probes` to
> `solutions.roots`.** Either change silently resurrects a tracker row for every probe ever run, which
> is the whole cost this design avoids.

## The rules

| | |
|---|---|
| **Cadence** | ~1/week |
| **Pull from** | techniques already at **🟢 or 🎓** in `technique_coverage.md`, **Medium or below** |
| **Pick order** | **technique first, then problem** — the easiest *unseen* problem that genuinely forces it. Difficulty is a consequence, never a dial |
| **Difficulty** | ratchets **per technique**: probed Easy → 🟢 → next probe of that technique is **Medium**. **Cap at Medium**, no Hard |
| **Never pull from** | anything 🟡 or with no 🟢 — those need *conversion reps*; a probe there just manufactures a 🟡 row |
| **Label** | stripped. No pattern name, no topic tag, no "this is like problem X" |
| **The measured thing** | the **pre-code call** — shape → technique → the one feature that picks it. The code is secondary |

## What gets logged

- **Always** → the recognition call (hit or miss) to the recognition ledger, **and a row in the
  [Probe log](#-probe-log--the-tally) below** (the only place a disposable 🟢 probe is counted).
- **🟢 → no tracker row.** The probe tested whether the *technique* transfers, not an asset to maintain.
  ⭐ If a 🟢 probe later earns a row (learner override, or a 🟡/🔴), **move the file into
  `dsa/leetcode/<pattern>/` in the same edit** — once a row exists, the retry scripts must be able to
  reach it, and they resolve retries only under `solutions.roots`.
- **🟡 / 🔴 → it earns a row**, because only a gap needs repetition.

## The free diagnostic

Because a 🟢 creates no row and a 🟡/🔴 does, **the row-creation rate over a rolling ~15 probes *is* the
measure of whether the pool still teaches anything**:

- **mostly 🟢** → the pool has stopped teaching. **Two ordered levers, cheapest first:** raise difficulty
  inside the pool you already own (adds zero permanent demand), and *only* when Medium is also mostly 🟢,
  open the next expansion tier (every new technique is maintenance demand forever).
- **a steady stream of 🟡/🔴** → real gaps remain; keep consolidating.

## 📒 Probe log — the tally

Every probe gets a row here, **hand-added when it runs**. This is the only place probes are *counted*: a
🟢 probe is disposable and creates no tracker row, so without this table it vanishes from every "problems
solved" figure, and the free diagnostic above loses its denominator. `update_review_dates.py` reads this
table to fold rowless probes into the tracker's summary counts (the `+N` suffix).

| # | Date | Problem | Technique | Result | Tracker row? |
|---|---|---|---|---|---|
| 1 | 2026-08-03 | 242 Valid Anagram | Hashing | 🔴 | ✅ earned |
| 2 | 2026-08-11 | 15 3Sum | Two-pointers | 🟢 | — |
| 3 | 2026-08-28 | 567 Permutation in String | Sliding-window | 🟢 | — |
| 4 | 2026-09-19 | 703 Kth Largest Element in a Stream | Heap | 🟡 | ✅ earned |
| 5 | 2026-10-04 | 102 Binary Tree Level Order Traversal | Tree-DFS | 🟢 | — |
| 6 | 2026-10-10 | 19 Remove Nth Node From End of List | Linked-list | 🟡 | ✅ earned |

_Add one row per probe. Result is 🟢 / 🟡 / 🔴; "Tracker row?" is `—` for a disposable 🟢 or `✅ earned`
for a 🟡/🔴._
