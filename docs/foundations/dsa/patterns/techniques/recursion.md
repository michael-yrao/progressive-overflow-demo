# 🧠 Recursion & Call Stack Traversal Patterns

## When to reach for it

The structure is self-similar (a list is a node plus a smaller list; a tree is a root plus subtrees) and the work at each node is the same — let the call stack carry the position instead of an explicit loop.

- Pipeline/Chain Construction
- End-Relative Analytics

## Picking feature

Where the work sits relative to the recursive call is the whole decision: BEFORE it (head / pre-order) when the current node decides what comes next; AFTER it (tail / post-order) when you need the answer from the end first.

- **not tree-dfs** — the structure is a TREE — same idea, but the pre / in / post vocabulary is the one to reason with
- **not dynamic-programming** — the recursion revisits the same state — add a cache or the call tree explodes

## Quick Reference


| Pattern | Execution Order | Stack Frame Lifecycle | Core Use Case |
| :--- | :--- | :--- | :--- |
| **Head Recursion** | State updates on the way **DOWN** | Evaluated *before* diving to next frame | Building pipelines, tree down-traversal, accumulations |
| **Tail Recursion**| State updates on the way **UP** | Evaluated *after* returning from base case | Counting from tail, reversing chains, post-order trees |

---

## Template: Head Recursion (Pre-Order Execution)

*When:* Building structural pipelines forward, or executing state evaluations on the way down toward the base case.

**Use Case**: Building structural pipelines forward, or executing state evaluations on the way down toward the base case.


| Component | Value |
| :--- | :--- |
| **Work Execution** | Evaluated **before** invoking the recursive function call |
| **Data Stream Direction** | Emits processing results from start boundary to end boundary |
| **State Retention** | Passed forward directly into the next frame's input parameters |

**Implementation**:
```python
def mergeTwoLists(self, list1: ListNode, list2: ListNode) -> ListNode:
    # Base Case: If either list runs out, return the remaining pool
    if not list1: return list2
    if not list2: return list1
    
    # WORK HAPPENS FIRST: Compare current head elements
    if list1.val < list2.val:
        # Delegate remaining pipeline structure to the next frame
        list1.next = self.mergeTwoLists(list1.next, list2)
        return list1 # Return current node as the confirmed segment head
    else:
        list2.next = self.mergeTwoLists(list1, list2.next)
        return list2 # Return current node as the confirmed segment head
```
Complexity: O(n + m) time · O(n + m) space — one frame per node of the merged output; the call stack is the extra space

**Example**: [LeetCode 21 - Merge Two Sorted Lists](https://leetcode.com)

---

## Template: Tail Recursion (Post-Order Execution)

*When:* Traversing to an unknown endpoint (like a tail pointer) first, then running evaluations backward relative to that end boundary.

**Use Case**: Traversing to an unknown endpoint (like a tail pointer) first, then running evaluations backward relative to that end boundary.


| Component | Value |
| :--- | :--- |
| **Work Execution** | Evaluated **after** the nested recursive call returns |
| **Data Stream Direction** | Emits processing results backwards from end boundary to start boundary |
| **State Retention** | Managed implicitly by the hardware Call Stack frames popping off |

**Implementation**:
```python
def removeNthFromEnd(self, head: ListNode, n: int) -> ListNode:
    self.counter = 0 # Explicit global scope primitive to track return index
    
    def helper(node):
        if not node: return None # Base case: plant flag at the absolute tail
        
        # DIVING PHASE: Push frames forward until tail boundary is reached
        node.next = helper(node.next)
        
        # POPPING PHASE: This logic executes in reverse order on the way up
        self.counter += 1 
        if self.counter == n:
            return node.next # Drop target node by returning its successor pointer
            
        return node # Preserve untouched structural links
        
    dummy = ListNode(0, head)
    dummy.next = helper(head)
    return dummy.next
```
Complexity: O(n) time · O(n) space — walks to the tail then unwinds — every node costs one frame

**Example**: [LeetCode 19 - Remove Nth Node From End of List](https://leetcode.com)

---

## Understanding Call Stack Traversal Direction

### What is it?
The **Call Stack Lifecycle** dictates the direction of logic processing by breaking a recursive runtime into two discrete vector fields: the journey down (Diving Phase) and the journey up (Popping Phase).

### Why it matters
Failing to recognize execution direction causes pointer truncation or counter shifts. For instance, in a singly linked list, counting forward is trivial, but counting from the end requires you to leverage the hardware stack frames to act as an implicit backward pointer engine.

### Real Examples

#### Example 1: Forward Accumulation Tree Depth (Head Pattern)
```python
def maxDepthHead(self, root: TreeNode, current_depth: int = 1) -> int:
    if not root: return current_depth - 1
    # State is accumulated on the way down via argument updates
    left = self.maxDepthHead(root.left, current_depth + 1)
    right = self.maxDepthHead(root.right, current_depth + 1)
    return max(left, right)
```

#### Example 2: Evaluative Bottom-Up Tree Depth (Tail Pattern)
```python
def maxDepthTail(self, root: TreeNode) -> int:
    if not root: return 0
    # Dive completely to leaf nodes before running math calculations
    left = self.maxDepthTail(root.left)
    right = self.maxDepthTail(root.right)
    # Work happens on the return path up the stack frames
    return max(left, right) + 1
```

### Pattern Recognition


| Context | How to Identify |
| :--- | :--- |
| **Pipeline/Chain Construction** | If current nodes must immediately resolve their connections to lookups before evaluating children, choose **Head**. |
| **End-Relative Analytics** | If constraints require metric calculations relative to an unknown end boundary, choose **Tail**. |

## Practice

- LC 21 — Merge Two Sorted Lists
- LC 19 — Remove Nth Node From End of List

## Common pitfalls

- No base case, or a base case placed after the recursive call — the stack overflows before it is ever checked
- Putting the work before the call when the answer needs the tail first (or vice versa) — the order of those two lines IS the algorithm
- Python's recursion limit (~1000 frames) — a 10⁴-node list needs the iterative form
- Mutating shared state (a counter, a list) across frames without meaning to — pass it explicitly or hold it on `self` on purpose

---

## Key Insights

### Why Call Stack Position Matters

*   **Pre-Call Location**: Code written before the helper execution runs in standard, predictable index increments. It protects memory scales because failures can exit early before exhausting system resources.
*   **Post-Call Location**: Code written after the helper execution defers processing entirely. It consumes memory space because the system must cache every single state context variable simultaneously until the final leaf node or null reference unblocks the chain.

### Mental Model

```text
    HEAD EXECUTION LOGIC                 TAIL EXECUTION LOGIC
        (Diving Down)                        (Popping Up)
 ┌─────────────────────────┐          ┌─────────────────────────┐
 │  Step 1: Do Local Work  │          │  Step 3: Do Local Work  │
 └────────────┬────────────┘          └────────────▲────────────┘
              │                                    │
              ▼                                    │
 ┌─────────────────────────┐          ┌────────────┴─────────────┐
 │  Step 2: Recursive Call │          │ Step 2: Recursive Return │
 └─────────────────────────┘          └──────────────────────────┘
```

---

## When recursion depth is the problem — and the ROI of rewriting it

**Settled Aug 16, 2026** after 261 threw `RecursionError` at `n = 2000`, which is inside
LeetCode's own constraint. Python's default limit is 1000.

**Three options, in the order you should reach for them:**

| | When |
|---|---|
| **1. Use BFS instead** | You only need *reachability* — connectivity, flood fill, unweighted shortest path. A queue has no depth limit. This covers most cases, including 261 |
| **2. `sys.setrecursionlimit(10**6)`** | You need DFS's semantics and depth is the only issue. One line; no interviewer objects |
| **3. Explicit stack (iterative DFS)** | Only when recursion is genuinely unavailable |

**BFS cannot substitute when you need either of these — and then it is DFS or nothing:**

- **Post-order output.** Hierholzer's append-on-the-way-out, DFS-based topological sort.
  A queue cannot produce it.
- **"Am I on the current path?"** Directed-graph cycle detection needs the recursion
  stack (the gray/black distinction). BFS has no concept of a current path.

⚠️ **The ROI of option 3 is near-zero as something to type cold, and non-zero as
something to say.** *"This recurses O(V) deep and n goes to 2000, so I'd raise the limit
or convert to an explicit stack"* is a complete answer in five seconds, and it is what an
interviewer is checking. The repo's own state agrees: it tracks three `(Iterative)`
variants and all three are **linked-list** problems (21, 206, 19), where
iterative-vs-recursive is a common ask. **Zero** iterative graph or tree DFS variants.

**Depth is a space term, always.** See
[`../../fundamentals/complexity/big_o.md`](../../fundamentals/complexity/big_o.md) —
`O(h)` for a tree descent, `O(V)` for a path graph, and it is the number this note is
about.
