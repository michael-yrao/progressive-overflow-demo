# Topological Sort Patterns

A **topological sort** orders the nodes of a **directed acyclic graph (DAG)** so every edge `u → v` has `u` before `v`. It answers "given dependencies, what's a valid order?" — and, as a side effect, detects cycles (a cyclic graph has *no* valid ordering).

## When to reach for it

A topological sort orders the nodes of a directed acyclic graph (DAG) so every edge u → v has u before v. It answers "given dependencies, what's a valid order?" — and, as a side effect, detects cycles (a cyclic graph has no valid ordering).

- "prerequisites" / "dependencies" / "build order" / "course schedule"
- "can you finish all tasks given these constraints?" (= is the graph a DAG?)
- any "do A before B" ordering over a directed graph

## Picking feature

A DIRECTED dependency graph and the question is an order (or whether one exists) — every edge u → v is a "u before v" constraint, and a cycle means no answer.

- **not union-find** — edges are undirected and the question is connectivity, not order
- **not tree-bfs** — the question is fewest steps, not a valid ordering — plain BFS without the indegree bookkeeping


## Template: Kahn's algorithm (BFS on indegrees)

*When:* Repeatedly remove nodes with no remaining prerequisites (indegree 0).

Repeatedly remove nodes with **no remaining prerequisites** (indegree 0).

```python
from collections import deque
indeg = [0] * n
adj = [[] for _ in range(n)]
for u, v in edges:            # edge u -> v  (u must come before v)
    adj[u].append(v)
    indeg[v] += 1

q = deque(i for i in range(n) if indeg[i] == 0)
order = []
while q:
    u = q.popleft()
    order.append(u)
    for v in adj[u]:
        indeg[v] -= 1
        if indeg[v] == 0:
            q.append(v)

# if len(order) < n → a cycle exists (some nodes never hit indegree 0)
return order if len(order) == n else []
```
Complexity: O(V + E) time · O(V + E) space — each node is enqueued once and each edge decremented once; adjacency lists plus the indegree array

## Template: DFS postorder (reverse)

*When:* Finish a node only after all its descendants; the reverse of finish order is a topo order.

Finish a node only after all its descendants; the **reverse of finish order** is a topo order. Cycle detection needs a 3-state color (unvisited / in-progress / done): revisiting an *in-progress* node = back edge = cycle.

```python
WHITE, GRAY, BLACK = 0, 1, 2
color = [WHITE] * n
order = []
def dfs(u):
    color[u] = GRAY
    for v in adj[u]:
        if color[v] == GRAY:      # back edge → cycle
            return False
        if color[v] == WHITE and not dfs(v):
            return False
    color[u] = BLACK
    order.append(u)               # postorder
    return True
# run dfs on every WHITE node; final answer is order reversed
```
Complexity: O(V + E) time · O(V + E) space — every node and edge is visited once; the colour array plus the recursion stack

## Which form to use

- **Kahn's** if you want the order built forward, or need to *count* how many nodes are reachable (the `len(order) == n` cycle check is clean). Usually the go-to.
- **DFS** if you're already doing DFS or want the classic postorder framing. The GRAY/BLACK cycle detection is the part people forget.

## Practice

- LC 207 — Course Schedule
- LC 210 — Course Schedule II
- LC 269 — Alien Dictionary
- LC 310 — Minimum Height Trees

| Problem | NC150? | Wrinkle |
|---|---|---|
| 207. Course Schedule | ✅ | Just "is it a DAG?" (done) |
| 210. Course Schedule II | ✅ | Return an actual valid order (done) |
| 269. Alien Dictionary | No | Build the graph from word comparisons, then topo-sort |
| 310. Minimum Height Trees | No | Kahn's from the leaves inward |

## Common pitfalls

- **Edge direction** — `u -> v` means "u before v," so `v` gets the indegree. Reversing this silently breaks everything.
- **Forgetting the cycle check** — Kahn's: `len(order) < n`; DFS: the GRAY (in-progress) state. Without it you return a bogus partial order.
- **Disconnected graphs** — seed Kahn's queue with *all* indegree-0 nodes; run DFS from *every* unvisited node.
