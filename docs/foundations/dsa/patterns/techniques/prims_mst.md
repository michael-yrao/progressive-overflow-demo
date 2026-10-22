# Prim's — Minimum Spanning Tree

> Written Aug 1, 2026, straight off the 1584 rep, so the gotchas below are the ones that actually bit.
>
> ⚠️ **Scope note.** This note covers Prim's *only*. The **Prim vs Dijkstra vs Kruskal** discriminator lives
> in `graph_algorithm_selection.md`, written ~Aug 5 — deliberately after 778 (Aug 2) and 332 (Aug 4), so it
> can't spoil either rep.

## Quick Reference

| | |
|---|---|
| **Solves** | cheapest set of edges connecting **all** nodes, no cycles |
| **Input** | connected, **undirected**, weighted graph |
| **Output** | total weight (or the edge set) of a minimum spanning tree |
| **Two implementations** | **dense → array, `O(V²)`** · sparse → heap, `O(E log V)` |
| **Key state** | `dist[i]` = cheapest single edge attaching `i` to the component **so far** |
| **Negative weights** | fine — unlike shortest-path algorithms, Prim's never adds weights together |

---

## 1. What problem it solves

You have a connected weighted graph and want to keep every node reachable while paying as little total edge
weight as possible. Drop any edge from the answer and the graph splits; add any edge and you create a cycle,
which by definition wastes weight. That's a **spanning tree** — `V` nodes, exactly `V−1` edges — and the
minimum-weight one is the MST.

**The trap the name sets:** an MST does *not* give you shortest paths. It minimizes the **total** of all edges
in the tree, not the distance between any particular pair. Those are different objectives and they routinely
disagree.

---

## 2. The procedure

Grow one component outward from an arbitrary start node. Each round:

1. **Pick** the unvisited node whose `dist` is smallest. Mark it visited. *(Its `dist` is the edge you just
   bought — that's why summing `dist` at the end gives the answer.)*
2. **Relax** every remaining unvisited node `j` against the node you just added:
   `dist[j] = min(dist[j], weight(picked, j))`.

Repeat until every node is in. Start with `dist = [∞] * V` and `dist[0] = 0`, so round 1 picks node 0 for free.

**The loop counter means nothing.** `for i in range(V)` works only because you add exactly one node per round —
`i` is never a node id and is never read inside the body. Prefer the form that says what it means:

```
while len(visited) < V:
```

---

## Template: The procedure

```python
def prim_mst(adj: list[list[int]]) -> int:      # adj[u][v] = weight; dense matrix input
    V = len(adj)
    in_tree = [False] * V
    best = [float('inf')] * V                    # cheapest known edge INTO each node from the tree
    best[0] = 0                                  # start anywhere
    total = 0
    for _ in range(V):
        u = min((v for v in range(V) if not in_tree[v]), key=lambda v: best[v])
        in_tree[u] = True
        total += best[u]                          # this edge joins the tree
        for v in range(V):                        # relax: is there a cheaper way INTO v now?
            if not in_tree[v] and adj[u][v] < best[v]:
                best[v] = adj[u][v]
    return total
```
Complexity: O(V²) time · O(V) space — V rounds, each doing two O(V) scans (find-the-min, then relax); the dist array plus the visited set.

---

## 3. The invariant — and what it forbids

> **`dist[i]` is the weight of the cheapest single edge that would attach node `i` to the component
> *as it currently stands*.**

The "as it currently stands" is load-bearing. The component **grows**, and a set that only grows can only give
node `i` *more* ways in — so `dist[i]` **only ever decreases.**

**That is what makes the update a `min`, not an assignment.** Writing

```
dist[j] = weight(picked, j)        # ✗
```

silently redefines the array to mean *"distance to the node I added most recently,"* which is a completely
different quantity and is wrong the moment a newly added node is farther from `j` than an earlier one was.

**The general rule, worth more than this problem:** *when an array's meaning is relative to a growing set, the
write is a `min`/`max`, never an assignment.* And when you write the invariant into a comment, **state what it
forbids**, not just what it holds — a comment that says "cheapest edge to the component" describes the goal;
one that adds "so it only decreases — the update is a `min`" catches the bug.

### The failing case

```
points = [[0,0], [1,0], [0,1]]      # true MST = 2 (attach both to the origin)
```

| Round | Added | `dist` after relaxing |
|---|---|---|
| 1 | node 0 | `[0, 1, 1]` |
| 2 | node 1 | assignment → `[0, 1, 2]` ❌ · `min` → `[0, 1, 1]` ✅ |

Node 2 is distance 2 from node 1 but only 1 from node 0, which is *already in the component*. The assignment
throws that away. Returns **3** instead of **2**.

---

## 4. Complexity

**Array version (used on 1584):**

- **Time `O(V²)`** — `V` rounds, each doing two `O(V)` scans (find-the-min, then relax).
- **Space `O(V)`** — the `dist` array plus the `visited` set.

⚠️ **The work across rounds is a SUM, not a product.** `(V−1) + (V−2) + … + 1 = V(V−1)/2 = O(V²)`. Writing it
as `(V−1) × (V−2) × …` gives `V!`, which is a different universe. Loop work **accumulates**; it compounds only
when loops are *nested*.

**Heap version:** `O(E log V)`.

**Which one — decide from edge count, not habit.** On 1584 the graph is **complete** (every pair of points has
a Manhattan distance, so every pair is an edge), giving `E ≈ V²`. Therefore:

| | Time on a dense graph |
|---|---|
| array | `O(V²) = O(E)` |
| heap | `O(E log V) = O(V² log V)` ← **worse** |

The heap is an optimization for **sparse** graphs, where `E ≪ V²` and you'd rather not scan all `V` every
round. Reaching for a heap reflexively costs you a `log V` here. **Ask "how many edges does this graph
actually have?" before choosing the structure** — on a geometry problem the answer is almost always `V²`,
because the edges are implied rather than given.

---

## Common pitfalls

- **Relax only unvisited nodes.** A visited node's `dist` is already spent; letting it drop later corrupts the
  final `sum(dist)`.
- **`sum(dist)` is the answer** precisely because `dist[i]` freezes at the moment `i` is picked, and `dist[0]`
  is 0. If either of those stops being true, the accumulator is wrong.
- **The start node is arbitrary.** Any node gives a correct MST (possibly a different one of equal weight).
- **Negative weights are fine.** Prim's compares edges; it never sums them into a path, so there's nothing for
  a negative edge to break. *(This is the opposite of the shortest-path algorithms.)*
- **Disconnected input** ⟹ no spanning tree exists. 1584 can't hit this (a complete graph is always
  connected), but a general graph can: the min-picker would return a node whose `dist` is still ∞.
- **Ties don't matter.** Any minimum-weight choice is fine; MSTs aren't unique when weights repeat.

---

## When to reach for it

You have a connected weighted graph and want to keep every node reachable while paying as little total edge weight as possible.

- connect all points/nodes at minimum total cost
- minimum cost to make all X connected
- Weights given as coordinates rather than an edge list
- Undirected + weighted + wants a structure, not a path

| Signal | Reading |
|---|---|
| "connect **all** points/nodes at minimum **total** cost" | MST |
| "minimum cost to make all X connected" | MST |
| Weights given as **coordinates** rather than an edge list | MST on a **complete** graph → **array version** |
| Undirected + weighted + wants a *structure*, not a *path* | MST |
| Wants distance **between two specific nodes** | **not** MST — different objective |

**The one-line discriminator:** an MST asks *"what's the cheapest way to keep everything connected?"* — a
question about the **whole graph**. A shortest-path question names a **source** (and usually a target). If a
problem statement never names a source node, you're almost certainly not in shortest-path territory.

## Picking feature

The objective is the cheapest set of edges that keeps EVERYTHING connected — a cost over the whole graph, not a distance from one source.

- **not Dijkstra / shortest path** — the question is the cheapest ROUTE between nodes — a source-relative distance; an MST is not a shortest-path tree
- **not union-find** — Kruskal's (sort the edges, union-find) is the other MST — reach for it on a sparse edge list; Prim's O(V²) wins on a dense graph or a point set

---

## Practice

- [1584. Min Cost to Connect All Points](../../../../../dsa/leetcode/graphs/1584_min_cost_to_connect_all_points.py)
  — array version, complete graph. *(🟡 Aug 1, 2026 — the relaxation-assignment bug above.)*
