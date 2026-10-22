# Monotonic Stack Patterns

A **monotonic stack** is a stack kept in sorted order (strictly/weakly increasing or decreasing) by popping any element that would break the order *before* pushing the new one. It answers "nearest greater/smaller element" queries for every element in **O(n) total** instead of O(n²).

## When to reach for it

A monotonic stack is a stack kept in sorted order (strictly/weakly increasing or decreasing) by popping any element that would break the order before pushing the new one. It answers "nearest greater/smaller element" queries for every element in O(n) total instead of O(n²).

Use a monotonic stack when, for each element, you need the **nearest element to one side that is greater or smaller**. Tells:

- "next greater element" / "next smaller element"
- "previous greater" / "previous smaller"
- "days until a warmer temperature" (distance to next greater)
- spans, or rectangle/area problems bounded by taller/shorter neighbors

If brute force is "for each element, scan outward until I find a bigger/smaller one" (O(n²)), a monotonic stack collapses it to O(n).

## Picking feature

For each element you need the NEAREST greater/smaller to one side — the stack discards anything that can never be an answer again, so every index is pushed and popped once.

- **not sliding-window** — the question is the longest/shortest contiguous run meeting a condition, not a per-element nearest neighbour
- **not heap** — you need the global max/min at any moment, not the nearest one per position


## Template: The template

Store **indices, not values** (so you can compute distances/widths). One pass:

```python
stack = []                                  # indices; values kept increasing bottom→top
for i, x in enumerate(arr):
    while stack and arr[stack[-1]] < x:      # x breaks the order → x is popped element's "next greater"
        idx = stack.pop()
        # arr[idx]'s next-greater is x, at distance (i - idx)
    stack.append(i)
# anything left on the stack has no next-greater element
```
Complexity: O(n) time · O(n) space — every index is pushed once and popped at most once; the stack can hold all n on a sorted input

### The only two knobs

1. **`<` vs `>` in the while condition** → decreasing vs increasing stack → finds **next greater** vs **next smaller**.
2. **Iteration direction** (left→right vs right→left) → **next** vs **previous**.

Pick the two knobs from the question; the rest is bookkeeping.

### Micro-example — Next Greater Element (`[2, 1, 2, 4, 3]`)

```
i=0 x=2: stack empty → push        stack=[0]        (vals [2])
i=1 x=1: 2<1? no → push            stack=[0,1]      (vals [2,1])
i=2 x=2: 1<2? pop 1 (NGE=2); 2<2? no → push   stack=[0,2]  (vals [2,2])
i=3 x=4: 2<4 pop 2 (NGE=4); 2<4 pop 0 (NGE=4); push  stack=[3]  (vals [4])
i=4 x=3: 4<3? no → push            stack=[3,4]
leftover 4,3 → no next greater (-1)
result: idx1→2, idx2→4, idx0→4, idx3→-1, idx4→-1
```

## Practice

- LC 496 — Next Greater Element I
- LC 739 — Daily Temperatures
- LC 503 — Next Greater Element II
- LC 901 — Online Stock Span
- LC 853 — Car Fleet
- LC 84 — Largest Rectangle in Histogram
- LC 239 — Sliding Window Maximum

Each step adds exactly one wrinkle. Do 496 → 739 first; they teach the core.

| # | Problem | NC150? | Wrinkle |
|---|---------|--------|---------|
| 1 | 496. Next Greater Element I (Easy) | No | Bare "next greater" template |
| 2 | 739. Daily Temperatures (Medium) | Stack | + distance between indices |
| 3 | 503. Next Greater Element II (Medium) | No | Circular array (`i % n`) |
| 4 | 901. Online Stock Span (Medium) | No | "Previous greater" / span counting |
| 5 | 853. Car Fleet (Medium) | Stack | Sort + collapse twist |
| 6 | 84. Largest Rectangle in Histogram (Hard) | Stack | Next-smaller on **both** sides; unlocks 85 + 1504 |

## Common pitfalls

- **Storing values instead of indices** — you lose the ability to compute distances/widths. Store indices, read `arr[idx]` when you need the value.
- **`<` vs `<=`** — strict vs non-strict changes tie handling. For "next strictly greater," pop on `arr[top] < x`; for widths in histograms, the equal-height tie handling matters — reason it out per problem.
- **Forgetting leftovers** — elements still on the stack at the end have no next-greater/smaller; handle them (often `-1` or the array boundary).
- **Wrong direction** — "previous" queries iterate right→left (or check the stack *before* popping for the element that remains below).

## Template: Monotonic deque (moving-window max/min)

Same family, one crucial difference. When you need the **max or min over a sliding window** (not "nearest greater to one side"), use a **monotonic deque** — a double-ended queue that pops from *both* ends:

- **back** — pop while it breaks monotonic order, exactly like the stack (keeps the deque decreasing for a max-query)
- **front** — pop indices that have **slid out of the window** (`front <= i - k`)

The front-eviction is what a plain stack can't do, and it's the whole reason a deque handles a *moving* range. The front of the deque is always the window's answer.

```python
from collections import deque
dq = deque()                       # indices, values decreasing front→back
res = []
for i, x in enumerate(arr):
    while dq and arr[dq[-1]] < x:   # back: maintain monotonic order
        dq.pop()
    dq.append(i)
    if dq[0] <= i - k:              # front: evict out-of-window index
        dq.popleft()
    if i >= k - 1:
        res.append(arr[dq[0]])      # front = max of current window
```
Complexity: O(n) time · O(k) space — each index enters and leaves the deque once; at most k indices are alive at a time

- **239. Sliding Window Maximum** (Hard) — **in NC150 (Sliding Window block)**. The canonical monotonic-deque problem.

Recognition: "nearest greater/smaller to one side" → **stack**; "max/min over a moving window" → **deque**. Same monotonic-invariant idea, different eviction rules.

## Where this fits the plan

NC150's Stack block (Aug 3–23) contains 739, 853, and 84. The non-NC150 ladder problems (496, 503, 901) are warmup ramps to build fluency *before* the Stack block, so 84 lands as "next-smaller both sides" rather than a cold hard problem.
