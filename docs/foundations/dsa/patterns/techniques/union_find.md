# Union-Find (Disjoint Set Union) Patterns

Union-Find tracks a partition of elements into disjoint groups, supporting two near-O(1) operations: **find** (which group is x in?) and **union** (merge two groups). With path compression + union by rank, both are effectively O(α(n)) ≈ O(1).

## When to reach for it

Union-Find tracks a partition of elements into disjoint groups, supporting two near-O(1) operations: find (which group is x in?) and union (merge two groups). With path compression + union by rank, both are effectively O(α(n)) ≈ O(1).

- "are these two connected?" / "how many connected components?"
- grouping / clustering elements as edges arrive (dynamic connectivity)
- detecting a cycle in an **undirected** graph (union two already-connected nodes → cycle)
- "redundant connection," "number of provinces," "accounts merge"
- anything where you incrementally merge sets and query membership

If the problem is about *connectivity* and edges come one at a time, Union-Find usually beats DFS/BFS.

## Picking feature

Edges arrive ONE AT A TIME, or the only question is "are these two in the same group?" — union-find answers it in near-O(1) per edge without ever walking the graph.

- **not DFS/BFS** — the graph is given whole and you need to WALK it (a path, an order, levels) — group membership alone is not the question
- **not topological-sort** — edges are directed and the question is order, not connectivity


## Template: Template

```python
parent = list(range(n))
rank = [0] * n

def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]   # path compression (halving)
        x = parent[x]
    return x

def union(a, b):
    ra, rb = find(a), find(b)
    if ra == rb:
        return False            # already connected → (for cycle detection) this edge is redundant
    if rank[ra] < rank[rb]:
        ra, rb = rb, ra
    parent[rb] = ra
    if rank[ra] == rank[rb]:
        rank[ra] += 1
    return True
```
Complexity: O(α(n)) per op time · O(n) space — With path compression + union by rank, both find and union are effectively O(α(n)) ≈ O(1); the parent and rank arrays are the only state

## Two facts worth memorizing

- **A tree of `n` nodes has exactly `n - 1` edges.** So "is this a valid tree?" = `len(edges) == n-1` **and** everything unions into one component. (This is the 261 sticking point — Union-Find catches cycles, the edge count catches disconnection.)
- **`union` returning False = the two were already connected** = for an undirected graph, this edge closes a cycle. That's the whole trick behind Redundant Connection.

## Practice

- LC 323 — Number of Connected Components in an Undirected Graph
- LC 261 — Graph Valid Tree
- LC 684 — Redundant Connection
- LC 130 — Surrounded Regions
- LC 547 — Number of Provinces

| Problem | NC150? | Wrinkle |
|---|---|---|
| 323. Number of Connected Components | ✅ | Count roots after unioning edges (done) |
| 261. Graph Valid Tree | No | + edge-count / connectivity check (done) |
| 684. Redundant Connection | ✅ | First edge whose union fails = the cycle edge (done) |
| 130. Surrounded Regions | ✅ | Union border 'O's to a dummy node (done) |
| 547. Number of Provinces | ✅ | Adjacency-matrix version |

## Common pitfalls

- **Skipping path compression** — without it, `find` degrades to O(n) and trees get tall.
- **Union without checking roots first** — always `find` both and compare roots before merging.
- **1D index mapping for grids** — flatten `(r, c)` → `r * cols + c`. Use `cols` (width) for the stride and `col` for the offset — mixing `rows`/`cols` here is the 130 typo trap.
- **Forgetting the dummy node** — border/"escape" problems (130) union everything on the border to one extra sentinel node, then check who shares its root.
