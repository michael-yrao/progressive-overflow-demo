# Intervals

## When to reach for it

Sort the intervals, then sweep left-to-right keeping a small piece of state.

- Intervals: "merge/insert overlapping" (→ a set)
- Intervals: "max that fit" / "min to remove" / "min arrows" (→ a number)
- "merge/combine overlapping intervals"
- "insert an interval and merge"
- "max intervals that fit" / "min to remove/erase"
- "min rooms / max overlap / peak concurrency"
- "does this new booking conflict?"

## Picking feature

The sort key follows the goal, never the input: merging (the answer is a SET of intervals) sorts by START; scheduling (the answer is a NUMBER — keep / remove / count) sorts by END.

- **not sliding-window** — the input is a contiguous run over one array, not a list of ranges to sort
- **not heap** — you must count SIMULTANEOUS overlaps (meeting rooms II) — a min-heap of end times, not a merge

## The one decision that categorizes everything

Almost every interval problem is the same shape:

> **Sort the intervals, then sweep left-to-right keeping a small piece of state.**

The *only* thing that changes between problems is **what you sort by** — and the sort key
follows the **goal**, not the input. Get the sort key right and the rest of the algorithm
falls out. Get it wrong and no amount of clever sweeping saves you.

| If the goal is… | Sort by | Why | Canonical |
|---|---|---|---|
| **Fuse overlapping intervals into one** | **start** | processing in start-order makes overlaps *adjacent*, so a local compare is enough | 56 Merge, 57 Insert |
| **Keep the most non-overlapping / remove the fewest** | **end** | the earliest-*ending* interval frees the line soonest → most room for the future | 435 Non-overlapping |
| **Max number overlapping at once (concurrency)** | **start** (+ a min-heap / sweep on ends) | you walk time forward and count how many are currently open | Meeting Rooms II |

**The trap:** merge and scheduling *look* identical (both are "sorted intervals, one sweep")
but sort by **opposite keys**. That discrimination — *what am I actually optimizing?* — is the
whole recognition skill. See [recognition_gotchas.md](../../mastery/recognition_gotchas.md).

---

## The overlap test (memorize this one line)

Two intervals `[a, b]` and `[c, d]` **overlap** iff:

```
a <= d  AND  c <= b
```

i.e. *each starts before the other ends.* The **negation** (they DON'T overlap) is what most
sweeps actually branch on:

```
b < c   OR   d < a          # one is entirely before the other
```

⚠️ **Touching endpoints** — is `[1,2]` vs `[2,3]` an overlap? **It depends on the problem, and
it is almost always stated.** Use `<` vs `<=` accordingly:
- "intervals `[1,2]`,`[2,3]` do **not** overlap" (435, Merge Intervals) → touching is fine → `<`
- "a person needs the room for `[start, end)`" (Meeting Rooms) → touching is fine → `<`
- If closed on both ends and touching counts → `<=`

Getting this comparator wrong is the single most common interval bug. Read the statement's
example for the endpoint case before you pick `<` or `<=`.

---

## Template: Merge overlapping — sort by START

*When:* collapse a set of intervals so no two overlap ("merge all overlapping intervals")

**Use case**: collapse a set of intervals so no two overlap ("merge all overlapping intervals").

**Mechanism**: sort by start, walk left to right, and fuse each interval into the last one in
the result if they overlap; otherwise append a new one.

| Component | Value |
|---|---|
| **Sort** | by **start** |
| **State** | the last interval in `result` (`result[-1]`) |
| **Test** | does the current interval overlap `result[-1]`? |
| **Merge** | `result[-1][1] = max(result[-1][1], cur_end)` |

```python
# 56 Merge Intervals
intervals.sort(key=lambda x: x[0])          # by START
result = []
for start, end in intervals:
    if result and start <= result[-1][1]:   # overlaps the last kept interval
        result[-1][1] = max(result[-1][1], end)   # extend it (start is already <=, sorted)
    else:
        result.append([start, end])
return result
```
Complexity: O(n log n) time · O(n) space — the sort dominates; the sweep is O(n) and the output holds up to n merged intervals

**Why sort by start works**: once sorted by start, any interval that overlaps a previous one
overlaps the *most recent* one — so you only ever compare against `result[-1]`, never the whole
list. The start is already the smallest, so merging only ever grows the **end**.

## Template: Insert into a sorted interval list — the three-phase sweep

*When:* a sorted, non-overlapping list is given; insert one new interval (57 Insert Interval)

**Use case**: a sorted, non-overlapping list is given; insert one new interval (57 Insert Interval).

The input is *already* start-sorted, so you don't re-sort — you sweep in three phases and place
the new (growing) interval exactly once:

```python
# 57 Insert Interval
result, i, n = [], 0, len(intervals)
ns, ne = newInterval

# phase 1 — everything ending BEFORE the new one starts: copy untouched
while i < n and intervals[i][1] < ns:
    result.append(intervals[i]); i += 1

# phase 2 — everything overlapping: absorb by GROWING the new interval (no append)
while i < n and intervals[i][0] <= ne:
    ns = min(ns, intervals[i][0])
    ne = max(ne, intervals[i][1]); i += 1

# phase 3 — place the fully-grown interval ONCE, outside any loop
result.append([ns, ne])

# phase 4 — everything AFTER: copy the rest
while i < n:
    result.append(intervals[i]); i += 1
return result
```
Complexity: O(n) time · O(1) space — the list is already sorted and non-overlapping, so no sort — one sweep with constant state beyond the output

**The load-bearing idea**: the new interval has exactly **one home**, at the boundary between
the "before" group and the "after" group. Placing it once, outside the loops, is what makes it
correct — and it automatically handles the case where the new interval belongs at the very end
(phases 1–2 consume everything, then phase 3 appends it).

---

## Template: Interval scheduling — sort by END

*When:* keep the maximum number of non-overlapping intervals, or (the mirror image) remove the minimum number so the rest don't overlap

**Use case**: keep the maximum number of non-overlapping intervals, or (the mirror image) remove
the minimum number so the rest don't overlap. Recognize *either* phrasing — they're the same
problem, since `min removed = total − max kept`.

**Mechanism**: sort by end, sweep, keep a single `frontier` = the end of the last interval you
kept. If the current interval starts before the frontier, it overlaps → drop it. Otherwise keep
it and advance the frontier.

| Component | Value |
|---|---|
| **Sort** | by **end** |
| **State** | `frontier` (an int) = end of the last KEPT interval |
| **Test** | `start < frontier` → overlaps → drop |
| **Keep** | `frontier = end` |

```python
# 435 Non-overlapping Intervals  (counts removals)
intervals.sort(key=lambda x: x[1])          # by END
frontier, removed = float('-inf'), 0
for start, end in intervals:
    if start >= frontier:                   # no overlap → keep
        frontier = end
    else:                                    # overlaps → drop it
        removed += 1
return removed
```
Complexity: O(n log n) time · O(1) space — sort by end, then one sweep holding only the current frontier end

**Why sort by end (the reusable intuition)**: think of booking one meeting room to fit the most
meetings. When you commit to an interval, its only *cost* is **when it frees the room** — its end.
So always keep the interval that ends earliest; it leaves the most room for everything after. A
late-ending interval like `[0,100]` starts early but is *toxic* — it hogs the future. Sort-by-end
surfaces the cheapest interval at the front every time, so a single greedy pass is optimal.

**Why one `frontier` scalar is enough**: after sorting by end, the last interval you kept always
reaches furthest right, so it's the *only* one a future interval can collide with. Everything kept
before it ends even sooner and is "behind you." The frontier is a complete summary of the kept set
for the only question you ever ask: *does the next one overlap?*

---

## 3. Max concurrency / sweep line — count what's open at once

**Use case**: "how many rooms/CPUs/resources do I need at peak?" — the maximum number of
intervals open simultaneously (Meeting Rooms II, Car Pooling, My Calendar).

**Mechanism** (named here for recognition; work the rep when it's scheduled): separate the starts
and ends, sweep along time, `+1` on a start and `-1` on an end, and track the running max. A
min-heap of end-times is the common implementation. The key mental shift from patterns 1–2: you're
no longer keeping/dropping intervals, you're **counting overlaps at each instant**.

*(No worked code here — this category has an unattempted rep on the board.)*

---

## How to recognize which pattern

Read the **goal verb**, then pick the sort key:

| The problem asks you to… | Pattern | Sort by | State you track |
|---|---|---|---|
| "merge/combine overlapping intervals" | Merge (§1) | **start** | `result[-1]` |
| "insert an interval and merge" | Insert (§1b) | (already sorted) | growing `[ns, ne]` |
| "max intervals that fit" / "min to remove/erase" | Scheduling (§2) | **end** | `frontier` int |
| "min rooms / max overlap / peak concurrency" | Sweep line (§3) | **start** + heap on ends | running count |
| "does this new booking conflict?" | overlap test | — | the overlap one-liner |

**The two-question decision:**
1. **Am I producing a set of intervals, or a number?**
   - a *set* (merged / inserted) → §1, sort by **start**
   - a *number* (how many to keep/remove/stack) → §2 or §3
2. **If a number: am I maximizing what fits, or counting the peak overlap?**
   - maximize fit / minimize removal → §2, sort by **end**, greedy frontier
   - peak simultaneous → §3, sweep line / heap

---

## Key Insights

- **The sort key follows the goal, never the input.** The same list of intervals gets sorted by
  start for merging and by end for scheduling. Ask what you're optimizing *first*.
- **Sorting is the O(n log n) cost; the sweep is O(n).** So interval problems are almost always
  **O(n log n) time**. Space is O(n) (the sort's buffer / the output); the sweep state itself is
  O(1). State this with the why-clause at the complexity gate.
- **The overlap comparator (`<` vs `<=`) is decided by the statement**, not by habit. Touching
  endpoints are the classic off-by-one — check the problem's own example.
- **Greedy-by-end is provably optimal** for interval scheduling (exchange argument: swapping in the
  earliest-ending interval never makes the answer worse). You don't need the proof to code it —
  the procedure is enough — but that's *why* the greedy is safe.

---

## Problems by category

| Category | Sort by | Problems |
|---|---|---|
| **Merge / Insert** (§1) | start | 56 Merge Intervals · 57 Insert Interval · 57-family (interval list ops) |
| **Scheduling / max-fit** (§2) | end | 435 Non-overlapping Intervals · (Min Arrows to Burst Balloons — same greedy) |
| **Sweep line / concurrency** (§3) | start + heap | Meeting Rooms I & II · Car Pooling · My Calendar |

*(Uncategorized interval problems get mapped in [techniques.yml](../../mastery/techniques.yml) as
they're solved — same rule as any new problem.)*

## Practice

- LC 56 — Merge Intervals
- LC 57 — Insert Interval
- LC 435 — Non-overlapping Intervals

## Common pitfalls

- Touching endpoints — is `[1,2]` vs `[2,3]` an overlap? It depends on the problem, and it is almost always stated. Use `<` vs `<=` accordingly. Getting this comparator wrong is the single most common interval bug.
- The overlap comparator (`<` vs `<=`) is decided by the statement, not by habit. Touching endpoints are the classic off-by-one — check the problem's own example.
