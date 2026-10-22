# Tree — Technique Hub

A binary tree is nodes with `left`/`right` children. Almost everything is a traversal — the choice is *which order* you process a node relative to its children, or whether you go by *level*. This page maps to the techniques.

## Structure facts

- Traversal is either **depth-first** (pre/in/post via stack/recursion) or **breadth-first** (level-order via queue).
- **BST** adds an ordering invariant: left < node < right → inorder is sorted.
- Time O(n); space O(h) for DFS recursion (O(log n) balanced, O(n) skewed), O(width) for BFS.

## Techniques used on trees

| Technique | Reach for it when | Doc |
|---|---|---|
| **Tree DFS** (pre/in/post) | Property depends on children, parent-context, or BST order | [techniques/tree_dfs](../techniques/tree_dfs.md) |
| **Tree BFS** (level order) | Level grouping, min depth, side views | [techniques/tree_bfs](../techniques/tree_bfs.md) |
| **Recursion** | The default framing for DFS; trust-the-recursion | [techniques/recursion](../techniques/recursion.md) |
| **Memoization** | Tree DP (results reused across subtrees/paths) | [techniques/dynamic_programming](../techniques/dynamic_programming.md) |

## Picking the DFS order

| Need | Order |
|---|---|
| Parent info available before children | preorder |
| Sorted BST output / validate BST | inorder (running `prev` between L and R) |
| Child results before parent (height, balanced, diameter, delete) | postorder |
| Level grouping / min depth / side view | BFS instead |

## Representative problems

104 Max Depth, 110 Balanced, 543 Diameter, 226 Invert, 100 Same Tree, 98 Validate BST, 235/236 LCA, 102 Level Order, 199 Right Side View, 297 Serialize/Deserialize, 1448 Good Nodes.
