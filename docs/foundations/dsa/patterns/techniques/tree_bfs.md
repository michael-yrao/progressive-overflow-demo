# Tree BFS (Level-Order Traversal)

Visit nodes **level by level** using a queue. The trick that makes "per level" work is snapshotting the queue length at the start of each level.

## When to reach for it

Visit nodes level by level using a queue. The trick that makes "per level" work is snapshotting the queue length at the start of each level.

- "level order" / "group values by depth"
- shortest path / **minimum depth** (BFS finds the nearest first)
- right/left side view, largest value per level, zigzag
- anything "by distance from the root"

## Picking feature

The question is PER LEVEL (widths, right-side view, zigzag) or FEWEST EDGES from the root — only a queue processes nodes in distance order.

- **not tree-dfs** — the parent's answer depends on the children's (height, diameter, validate) — that is postorder, and BFS has no notion of "children first"


## Template: Template — the level-size snapshot

```python
from collections import deque

def level_order(root):
    if not root: return []
    q = deque([root])
    result = []
    while q:
        level = []
        for _ in range(len(q)):     # snapshot: only THIS level's nodes
            node = q.popleft()
            level.append(node.val)
            if node.left:  q.append(node.left)
            if node.right: q.append(node.right)
        result.append(level)
    return result
```
Complexity: O(n) time · O(w) space — each node is enqueued once; the queue holds one level at a time, up to the tree's maximum width w (≈ n/2 for a full tree)

`for _ in range(len(q))` freezes the count *before* you enqueue the next level — that's what separates one level from the next.

## Variations (all the same skeleton)

- **Right side view** → take `level[-1]` (or the last node dequeued each level)
- **Min depth** → return the depth when you first hit a leaf
- **Zigzag** → reverse `level` on alternate depths

## Practice

- LC 102 — Binary Tree Level Order Traversal
- LC 199 — Binary Tree Right Side View
- LC 515 — Find Largest Value in Each Tree Row
- LC 111 — Minimum Depth of Binary Tree
- LC 297 — Serialize and Deserialize Binary Tree

| Problem | NC150? | Wrinkle |
|---|---|---|
| 102. Level Order Traversal | ✅ | The base template |
| 199. Right Side View | ✅ | Last node per level |
| 515. Largest Value per Row | No | max(level) |
| 111. Minimum Depth | No | Stop at first leaf |
| 297. Serialize/Deserialize | ✅ | BFS with null markers |

## Common pitfalls

- **`list.pop(0)` instead of `deque.popleft()`** — `pop(0)` is O(n), making the whole traversal O(n²). Always use `collections.deque`.
- **Not snapshotting `len(q)`** — if you loop `while q` without the inner `range(len(q))`, you can't tell where one level ends.
- **Forgetting the empty-root guard** → `deque([None])` processes a phantom node.
