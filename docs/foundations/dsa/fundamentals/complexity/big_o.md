# Big-O — Complexity Reference

Time and space complexity of the techniques and data structures in [`../patterns/`](../patterns/README.md), compiled in one place. `n` = input size; `h` = tree height; `V,E` = vertices, edges; `L` = key length.

## Growth-rate ladder (best → worst)

```
O(1)  <  O(log n)  <  O(n)  <  O(n log n)  <  O(n²)  <  O(2ⁿ)  <  O(n!)
```

- **O(1)** constant — hash lookup, stack push/pop, array index.
- **O(log n)** — binary search, balanced-tree / heap operations.
- **O(n)** — one linear pass (two pointers, sliding window, prefix sum).
- **O(n log n)** — sorting, or "n items each doing a log-n op."
- **O(n²)** — nested loops / all-pairs (the thing most techniques *avoid*).
- **O(2ⁿ), O(n!)** — subsets / permutations (backtracking without pruning).

## Techniques

| Technique | Time | Space | Notes |
|-----------|------|-------|-------|
| [two_pointer](../patterns/techniques/two_pointer.md) | O(n) | O(1) | Single or dual scan, no nesting |
| [fast_slow_pointer](../patterns/techniques/fast_slow_pointer.md) | O(n) | O(1) | Floyd's cycle detection |
| [sliding_window](../patterns/techniques/sliding_window.md) | O(n) | O(1)–O(k) | Window state / freq map (≤ alphabet size) |
| [binary_search](../patterns/techniques/binary_search.md) | O(log n) | O(1) | Halve the search space each step |
| [prefix_sum](../patterns/techniques/prefix_sum.md) | O(n) build, O(1) per query | O(n) | +hashmap variant for "subarrays summing to k" |
| [monotonic_stack](../patterns/techniques/monotonic_stack.md) | O(n) | O(n) | Each element pushed & popped at most once |
| monotonic_deque (moving-window max/min) | O(n) | O(k) | Each element enters/leaves the deque once |
| [in_place_reversal](../patterns/techniques/in_place_reversal.md) | O(n) | O(1) iterative / O(n) recursive | Recursive uses call stack |
| [tree_dfs](../patterns/techniques/tree_dfs.md) | O(n) | O(h) | Stack depth = height (O(log n) balanced, O(n) skewed) |
| [tree_bfs](../patterns/techniques/tree_bfs.md) | O(n) | O(w) | w = max level width |
| [topological_sort](../patterns/techniques/topological_sort.md) | O(V + E) | O(V) | Kahn's or DFS |
| [union_find](../patterns/techniques/union_find.md) | ~O(1) amortized (O(α(n))) | O(n) | With path compression + union by rank |
| [dynamic programming](../patterns/techniques/dynamic_programming.md) | O(#states × work/state) | O(#states) | DP; complexity = distinct states × work per state |
| [backtracking](../patterns/techniques/backtracking.md) | O(bᵈ) — exponential | O(d) | b = branching factor, d = depth; pruning cuts the constant |
| [recursion](../patterns/techniques/recursion.md) | varies | O(depth) | Space is the call-stack depth |
| [dummy_node](../patterns/techniques/dummy_node.md) | O(1) overhead | O(1) | Not a complexity — an edge-case simplifier |

## Data structures

| Structure | Access | Search | Insert | Delete | Notes |
|-----------|--------|--------|--------|--------|-------|
| Array / list | O(1) | O(n) | O(1)* end / O(n) middle | O(1)* end / O(n) middle | *amortized at the end |
| Hash map / set | — | O(1) avg / O(n) worst | O(1) avg | O(1) avg | Worst case on collisions |
| Stack / Queue (deque) | — | O(n) | O(1) push | O(1) pop | Use `deque` — `list.pop(0)` is O(n) |
| Heap (binary) | O(1) peek | O(n) | O(log n) push | O(log n) pop | `heapify` a list is O(n) |
| [Linked list](../patterns/data-structures/linked_list.md) | O(n) | O(n) | O(1) at known node | O(1) at known node | No random access; splice is O(1) |
| BST (balanced) | — | O(log n) | O(log n) | O(log n) | Unbalanced degrades to O(n) |
| Trie | — | O(L) | O(L) | O(L) | L = key length |
| [Union-Find](../patterns/techniques/union_find.md) | — | ~O(1) `find` | ~O(1) `union` | — | Amortized O(α(n)) |

## Reading tips

- **Average vs worst matters** — hash maps are O(1) *average* but O(n) worst; quicksort is O(n log n) average, O(n²) worst.
- **Amortized ≠ per-op** — array append and union-find are cheap *averaged over many ops*, even if a single op occasionally costs more.
- **Space includes the call stack** — a recursive O(n)-time solution can still be O(n) *space* from recursion depth (e.g. DFS on a skewed tree).
- **The goal of most techniques is to dodge O(n²)** — two pointers, sliding window, prefix sum, and monotonic stack all turn an obvious nested-loop O(n²) into O(n).
