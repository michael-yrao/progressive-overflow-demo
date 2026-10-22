# Patterns

Two ways in, one source of truth:

- **`techniques/`** — the actual content. Each file is **one atomic technique**: recognition signal → template → key facts → practice ladder (NC150 flagged) → pitfalls. This is where you learn the move.
- **`data-structures/`** — **hub pages**, not content. Each says "for this kind of data, here are the techniques you reach for," linking into `techniques/`. Use these when you know the *shape* of the data but not the move.
- **`intuition_cheatsheet.md`** — recognition tables + single-trick techniques (Boyer-Moore, cyclic sort, two heaps, quickselect). Start here when you don't know what a problem wants.
- **[`../fundamentals/complexity/big_o.md`](../fundamentals/complexity/big_o.md)** — time/space complexity of every technique + data structure here, in one table.

Rule of thumb: **know the move → open a technique. Know the shape → open a hub. Know neither → cheatsheet.** Techniques are never duplicated; hubs only link.

## The machine-readable contract

Every file under `techniques/` is also read by a script: `scripts/build_cheatsheets.py` generates
progressiveoverflow.com/learn's technique cheat sheet from these docs, so the docs stay the single
source of truth (per CLAUDE.md) instead of the site hand-maintaining its own copy. It reads exactly
five `##` headings per doc — everything else (the deep-dive "Understanding …" / "Key Insights"
sections) is prose for the learner and is ignored:

- **`## When to reach for it`** — first paragraph, then one bullet per recognition signal
- **`## Picking feature`** — the discriminating feature, then `- **not <technique>** — <because>` per neighbour it's *not*
- **`## Template: <title>`** — one per variant, its python fence followed immediately by a `Complexity: <time> time · <space> space — <why>` line
- **`## Common pitfalls`** — one bullet per pitfall
- **`## Practice`** — one `LC <n> — <title>` bullet per key problem

`python scripts/check_cheatsheets.py --check` validates every doc against this contract; it is
blocking from the pre-commit hook as of Sep 23, 2026, now that all technique docs pass. The full
contract, and why it's headings and not a sidecar file, is documented in
`scripts/build_cheatsheets.py`'s module docstring.

- **`intuition_cheatsheet.md`'s own `## Decision tree`** — a single nested bullet list (shape → cue →
  technique) generated into the same `dashboard/cheat-sheets.json`'s `decisionTree` (leaves shaped
  `{label, reach, reachLabel, note, page?}`), for `/learn`'s Table ↔ Tree toggle; validated by the
  same script.

## By data structure (the "shape" lens)

| Hub | Techniques it points to |
|-----|-------------------------|
| [linked_list](data-structures/linked_list.md) | dummy_node · fast_slow_pointer · in_place_reversal · recursion |
| [tree](data-structures/tree.md) | tree_dfs · tree_bfs · recursion · dynamic_programming |
| [graph](data-structures/graph.md) | union_find · topological_sort · BFS/DFS traversal |
| [array_string](data-structures/array_string.md) | two_pointer · sliding_window · prefix_sum · binary_search · monotonic_stack |
| [stack_queue](data-structures/stack_queue.md) | monotonic_stack · monotonic_deque · plain stack · BFS queue |

## By technique (the "move" lens — A→Z)

| Technique | One-line trigger |
|-----------|------------------|
| [backtracking](techniques/backtracking.md) | Enumerate subsets/permutations/combinations; choose-explore-unchoose |
| [binary_search](techniques/binary_search.md) | Sorted data, or "smallest x that works" (min/max boundary) |
| [dummy_node](techniques/dummy_node.md) | Linked-list head may change; building/merging a list |
| [fast_slow_pointer](techniques/fast_slow_pointer.md) | Cycle detection, middle of list, find-the-duplicate |
| [in_place_reversal](techniques/in_place_reversal.md) | Reverse a list/sublist by rewiring `next` |
| [dynamic_programming](techniques/dynamic_programming.md) | Overlapping subproblems → solve each state once (memo or table) |
| [monotonic_stack](techniques/monotonic_stack.md) | Nearest greater/smaller (+ deque for moving-window max/min) |
| [prefix_sum](techniques/prefix_sum.md) | Range sums; "subarrays summing to k" (+ hashmap) |
| [recursion](techniques/recursion.md) | Self-similar subproblems; trust-the-recursion |
| [sliding_window](techniques/sliding_window.md) | Contiguous subarray/substring with a constraint |
| [topological_sort](techniques/topological_sort.md) | Ordering with dependencies on a DAG |
| [tree_bfs](techniques/tree_bfs.md) | Level order, min depth, side views |
| [tree_dfs](techniques/tree_dfs.md) | Pre/in/post traversal; property from children |
| [two_pointer](techniques/two_pointer.md) | Converging or same-direction pointers driven by an invariant |
| [union_find](techniques/union_find.md) | Connectivity / grouping / undirected cycle detection |

## Graph algorithms — the name index (added Aug 5, 2026)

**Why this is its own section:** the A→Z table above answers *"I see this shape, what's the move?"*
This one answers the reverse — **"what does this name actually solve?"** — because the advanced graph
algorithms are the ones whose *names* don't stick. A name you can't retrieve is a technique you can't
reach for cold, and recognition is one of the two phase-exit axes.

Each row **stands alone on purpose** — no "same as above", no "likewise". This gets read one row at a
time, weeks apart, and a row starting with "same" has nothing to point at.

| Algorithm | Solves | Note |
|---|---|---|
| **Dijkstra** | cheapest path from one source to everywhere, when every edge cost is non-negative | ⚠️ not written |
| **Bellman-Ford** | cheapest path from one source to everywhere, tolerating negative edge costs; works in rounds, so the number of edges used can be capped | ⚠️ not written |
| **Floyd-Warshall** | the cheapest path between *every* pair of nodes at once, by repeatedly asking whether routing through one more allowed midpoint beats the best cost known so far | [floyd_warshall](techniques/floyd_warshall.md) |
| **Prim's** | connect every node into one network for the least total edge cost, growing a single tree outward from a start node | [prims_mst](techniques/prims_mst.md) |
| **Kruskal's** | connect every node into one network for the least total edge cost, taking edges cheapest-first and skipping any that closes a cycle | ⚠️ not written |
| **Hierholzer** | find a walk that uses every edge in the graph exactly once | ⚠️ not written |
| **Topological sort** | order the nodes so that every node comes after everything it depends on | [topological_sort](techniques/topological_sort.md) |

**The shape of the list — three questions, two answers each.** Dijkstra and Bellman-Ford answer *"what's
the cheapest way to get there."* Prim's and Kruskal's answer *"what's the cheapest way to connect
everything."* Hierholzer and topological sort aren't about cost at all — they answer *"in what order do I
walk this."* Each pair differs by one condition; the picking features are in
[recognition_patterns.md](../recognition_patterns.md).

**Floyd-Warshall is the one with no partner**, and that *is* its recognition signal. Dijkstra and
Bellman-Ford answer the cheapest-path question **from one source**; Floyd-Warshall answers it **between every
pair**, which is a different question and not a loop around the other two. The trigger is a problem that needs
distances it never names a source for — *"for each city, how many others are within…"* — plus a small `n`
(≤ ~400), because the cost is O(n³) and that bound is what makes it affordable.

The **⚠️ not written** marks double as the gap list — four of these seven have no technique note, and
Bellman-Ford and Dijkstra are both gate-relevant before Aug 16.

> ✅ **Floyd-Warshall's row filled Aug 5, 2026** at 1334's close-out, as planned — the rated measurement half
> of the Jul 31 teach. **The recognition half of that rep landed: the algorithm was named cold from "all pairs
> + small n" before any code.** Execution did not — 1334 came back 🟡 (adjacency map instead of the n×n matrix),
> so Floyd-Warshall still holds **zero 🟢** going into the Aug 16 gate.
