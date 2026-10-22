# Circuit rank — how many independent cycles a graph has

Also called the cyclomatic number, or the graph's first Betti number.

```
rank = E − V + C          C = number of connected components
```

That is the number of edges you must remove to leave no cycles. It is exactly the
number of independent cycles.

## The zero case is the useful one

**rank = 0 ⟺ no cycles.** Set `C = 1` (connected) and it forces `E = V − 1`.

So for a graph on `V` vertices, **any two of these force the third**:

1. connected
2. acyclic
3. `E = V − 1`

Nothing about trees is being asserted here — it is `rank = E − V + C` read three ways.

## Two corollaries worth knowing

**Add any edge to a tree and you get exactly one cycle.** Rank goes 0 → 1.

**Remove an edge from a cycle and connectivity survives.** Rank drops, `C` does not
change — which is the whole argument for why connected + `V−1` edges cannot contain a
cycle: deleting the cycle edge would leave `V` vertices connected by `V−2`.

## Where it shows up

**261 Graph Valid Tree.** Two ways to spend the same theorem:

| | Check directly | Get free |
|---|---|---|
| **DFS** | connected (`len(visited) == V`) + edge count | acyclic |
| **Union-Find** | acyclic (a `find` collision *is* a cycle) + connected | edge count |

⚠️ **DFS cannot drop the edge-count line.** A triangle `V=3, [[0,1],[1,2],[2,0]]`
visits all three vertices, so `len(visited) == V` passes on a non-tree. Union-Find can
drop it — it observes the cycle rather than inferring it.

**MST problems** (1584, 1489): a spanning tree is a rank-0 subgraph, and every edge you
reject is one that would have raised the rank.
