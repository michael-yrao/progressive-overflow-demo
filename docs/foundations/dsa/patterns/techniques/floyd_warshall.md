# Floyd–Warshall — All-Pairs Shortest Paths

> Written Jul 31, 2026, during the 1334 teaching session. First exposure to the algorithm.

## Quick Reference

| | |
|---|---|
| **Question it answers** | Shortest distance between **every pair** of nodes |
| **Core move** | For each pair, is it cheaper to go direct, or to route through some intermediate node? |
| **Shape** | Three nested loops over an `n × n` table — stopover loop **outermost** |
| **Time / Space** | `O(n³)` / `O(n²)` |
| **Handles negative weights?** | **Yes** (unlike Dijkstra). Also *detects* negative cycles |
| **Reach for it when** | You need all pairs, `n` is small (≲ 400), or the graph is dense |

---

## 1. What problem it solves

Dijkstra answers *"from **one** source, what's the distance to everything?"* Floyd–Warshall answers
*"what's the distance between **every** pair?"* — in about five lines and with no heap, no frontier,
and no visited set.

**The assumption it repairs:** traversal algorithms (BFS/DFS with a visited set) assume *the first time
you reach a node is good enough*. That's true in an unweighted graph, where the first arrival really is
the closest. **With weights it is simply false** — you can arrive at a node via an expensive route,
mark it done, and lock out a cheaper arrival that still had budget left to travel further.

That failure is the reason this algorithm exists. See §7 for the worked counterexample.

---

## Template: The procedure

*When:* let one node at a time become a legal stopover

**Step 1 — build the table.**

```
dist[i][j] = weight of the direct edge i→j
dist[i][i] = 0
dist[i][j] = infinity   when there is no direct edge
```

**Step 2 — let one node at a time become a legal stopover.**

```python
for k in all nodes:            # the stopover — MUST be outermost
    for i in all nodes:
        for j in all nodes:
            if dist[i][k] + dist[k][j] < dist[i][j]:
                dist[i][j] = dist[i][k] + dist[k][j]
```
Complexity: O(n³) time · O(n²) space — Three nested loops, each over all n nodes; every (k, i, j) triple is one constant-time comparison, independent of edge count (time). The table; in-place updating means no second copy (space).

Read the loop body in plain words: *"I'm now allowing trips that stop at k. Does that make the
i → j trip cheaper?"*

**Step 3 — there is no step 3.** Once every `k` has had its turn, the table holds true shortest
distances. No convergence check, no repeat passes.

---

## 3. Why it works (the invariant)

This is the load-bearing idea, and it's what makes the loop order non-negotiable.

> **After processing stopovers `k = 0 … K`, `dist[i][j]` holds the shortest i→j path that is allowed
> to pass through only the nodes `{0 … K}` as intermediates.**

Endpoints `i` and `j` are always allowed; the restriction is on what you may pass *through*.

**Base case.** Before any `k` runs, the table holds direct edges — which is exactly "the shortest path
using **no** intermediates." The invariant holds for the empty set. ✓

**Inductive step.** Now let node `k` become legal. Any shortest i→j path allowed to use `{0…k}` either:

- **doesn't use k** → it was already found, and it's the current `dist[i][j]` (correct for `{0…k-1}`), or
- **uses k** → it splits at `k` into `i → k` and `k → j`, and *each of those halves uses only
  `{0…k-1}` as intermediates* — so both are already correct in the table.

Taking the min of those two is precisely the loop body. ✓

**Why "uses k" means "uses k exactly once":** a shortest path never revisits a node (with non-negative
weights, a repeat would mean a cycle you could delete and get shorter). So one clean split point.

### Why `k` must be the outermost loop

The induction is over the **stopover set**, and that set has to grow one node at a time across the
*whole table*. Putting `k` inside means asking "try every stopover for this pair" while other pairs are
still unfinished — `dist[i][k]` may not yet include the intermediates it needs, so the guarantee
evaporates and you'd need repeated passes to converge.

**Pairs inner, stopover outer.** This is the single most common way to get Floyd–Warshall wrong.

### Why updating in place is safe

A natural worry: during iteration `k` you *read* `dist[i][k]` and `dist[k][j]` while *writing* to the
same table. Doesn't that corrupt things?

No — and the reason is neat. Could `dist[i][k]` change during iteration `k`? Its update would be
`dist[i][k] + dist[k][k]`, and `dist[k][k] = 0`, so the candidate equals what's already there. Row `k`
and column `k` are **frozen** during round `k`. No second table needed.

---

## 4. Worked trace

Three cities. Roads: `0–1 = 4`, `1–2 = 1`, `0–2 = 10` (undirected).

Initial:

```
        0     1     2
  0     0     4    10
  1     4     0     1
  2    10     1     0
```

**k = 0** — stopovers at 0. Best candidate is `1→0→2` = 4 + 10 = 14, worse than the existing 1. No change.

**k = 1** — stopovers at 1. `0→2` is currently 10, but `0→1→2` = 4 + 1 = **5**. Update (and its mirror).

```
        0     1     2
  0     0     4     5   ←
  1     4     0     1
  2     5     1     0
```

**k = 2** — stopovers at 2. `0→1` is 4; `0→2→1` = 5 + 1 = 6. Worse. No change.

Done. Note what happened at `k = 1`: it improved a pair **neither of whose endpoints was node 1**.
That's the mechanism doing the thing a source-based traversal can't do in one sweep.

---

## 5. Complexity

| | | Why |
|---|---|---|
| **Time** | `O(n³)` | Three nested loops, each over all `n` nodes. Every `(k, i, j)` triple is one constant-time comparison. Independent of edge count |
| **Space** | `O(n²)` | The table. In-place updating means no second copy (§3) |

**It does not depend on `E`.** A dense graph costs the same as a sparse one — which is exactly when
this beats the alternative.

**vs. running Dijkstra from every node:** that's `O(n · E log n)`. On a **sparse** graph (`E ≈ n`)
that's about `n² log n` and it wins. On a **dense** graph (`E ≈ n²`) it becomes `n³ log n` — *worse*
than Floyd–Warshall, and far more code.

---

## 6. When to reach for which

| Situation | Use |
|---|---|
| One source, non-negative weights | **Dijkstra** |
| One source, **negative** weights allowed | **Bellman-Ford** |
| **All pairs**, small or dense graph | **Floyd–Warshall** |
| All pairs, large sparse graph, non-negative | n × Dijkstra |
| Unweighted (or all weights equal) | **plain BFS** — don't bring out shortest-path machinery |

The `n ≲ 400` rule of thumb: `400³` = 64M, near the edge of comfort. A problem that hands you
`n ≤ 100` or `n ≤ 200` and asks an all-pairs question is signposting this algorithm.

---

## 7. The counterexample that motivates all of this

Graph: `0–1 = 3`, `1–2 = 1`, `1–3 = 4`, `2–3 = 1`. Budget 6, starting from node 3.

**Truth:** 3 reaches 2 (cost 1), 1 (cost 2, via 2), and 0 (cost 5, via 2→1). All three.

**DFS with a visited set**, taking neighbour 1 before neighbour 2:

- `3 → 1`, cost 4. Mark **1 visited**.
  - `1 → 0` costs 7 — over budget, prune (correctly).
  - `1 → 2` costs 5. Mark **2 visited**.
- Back at 3: try `3 → 2` — cost **1**, but 2 is already marked. **Skip.**

Answer: `{1, 2}` — node 0 is lost. Nothing went over budget wrongly; the damage is that node 2 was
reached at a price of 5 and stamped done, so the *cheap* arrival at price 1 — the one with budget left
to spend on `2 → 1 → 0` — was refused.

Dropping the visited set instead means enumerating every simple path: correct, exponential, useless.

**The lesson, in one line:** a boolean "visited" is the wrong thing to track per node. The useful fact
is not *whether* you reached it, or *by which route*, but **what it cost**.

---

## Common pitfalls

- **`float('inf')` is safe to add in Python** — `inf + inf` is `inf`, no overflow. In a fixed-width
  integer language use a sentinel like `1e9` and guard against `sentinel + sentinel` wrapping.
- **`dist[i][i] = 0`** must be seeded, or the "route through k" candidate misbehaves and the §3
  frozen-row argument breaks.
- **Undirected graphs need both directions** written at seed time: `dist[u][v]` *and* `dist[v][u]`.
- **Parallel edges** between the same pair: keep the **minimum**, don't overwrite blindly. (1334
  guarantees distinct pairs, so it doesn't bite there — but it will elsewhere.)
- **Negative cycles**, if the problem allows negative weights: after the run, `dist[i][i] < 0` for any
  `i` means `i` sits on a negative cycle.
- The three loops are **`k, i, j` in that order**. Say it out loud before writing them.

---

## When to reach for it

You need all pairs, n is small (≲ 400), or the graph is dense

Reach for this when you see:

- "shortest distance **between every pair**" / "for each node, something about all other nodes"
- a **small** `n` (≤ ~400) paired with a weighted graph — especially when `n` is suspiciously small
  next to a large-sounding problem
- a per-node aggregate that needs *all* its distances before it can be computed (a count, a max, a sum)
- weights that may be **negative**, in an all-pairs setting

**Anti-trigger:** unweighted graph → BFS. Single source → Dijkstra or Bellman-Ford. Don't pay `n³`
for a question that only ever asked about one starting point.

## Picking feature

All pairs, small or dense graph

- **not Dijkstra** — One source, non-negative weights
- **not Bellman-Ford** — One source, negative weights allowed
- **not BFS** — the graph is unweighted (or every edge costs the same) — plain BFS gives shortest paths in O(V + E) without any shortest-path machinery
- **not Dijkstra** — All pairs, large sparse graph, non-negative — n × Dijkstra wins over O(n³)

---

## Practice

- LC 1334 — Find the City With the Smallest Number of Neighbors at a Threshold Distance

| Problem | Notes |
|---|---|
| [1334. Find the City With the Smallest Number of Neighbors at a Threshold Distance](../../../../../dsa/leetcode/graphs/1334_find_the_city_with_the_smallest_number_of_neighbors_at_a_threshold_distance.py) | Canonical. Build the table, then per row count entries ≤ threshold; ties break to the **larger** index |
