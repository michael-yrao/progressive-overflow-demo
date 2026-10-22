# Binary Search Patterns

## When to reach for it

Binary search works on any monotonic yes/no boundary, not just sorted arrays. Use it when you can test a candidate answer cheaply and the search space is sorted or monotonically structured.

- Sorted, or "smallest/largest x that works", or "find position"

## Picking feature

A yes/no predicate that flips exactly once across the search space — a sorted array, or a monotonic answer space like "can finish at speed k" — so halving the range is safe.

- **not two-pointer** — you need a PAIR of positions meeting a condition, not one boundary — sorted input alone doesn't make it a binary search
- **not sliding-window** — the thing you want is a contiguous run whose validity changes as it grows, not a single index

## Quick Reference

| Pattern | Loop | Midpoint | Use Case |
|---------|------|----------|----------|
| **Exact Value** | `while l <= r` | `(l + r) // 2` | Find exact match |
| **Min Boundary** | `while l < r` | `(l + r) // 2` | Find first true |
| **Max Boundary** | `while l < r` | `(l + r + 1) // 2` | Find last true |

---

## Template: Exact Value Search

*When:* Find an exact target value in the array

**Use Case**: Find an exact target value in the array

| Component | Value |
|-----------|-------|
| **Loop** | `while l <= r` |
| **Midpoint** | `mid = (l + r) // 2` |
| **Return** | `mid` at exit or when found |

**Update Rules**:
```python
if nums[mid] == target:
    return mid  # Found exact match
elif nums[mid] > target:
    r = mid - 1  # Search left
else:
    l = mid + 1  # Search right
```
Complexity: O(log n) time · O(1) space — each step halves the candidate range; only two indices are held

**Example**: [LeetCode 704 - Binary Search](https://leetcode.com/problems/binary-search/)

---

## Template: Minimum Boundary Search (First True Position)

*When:* Find the leftmost position where a monotonic predicate is true

**Use Case**: Find the leftmost position where a monotonic predicate is true

| Component | Value |
|-----------|-------|
| **Loop** | `while l < r` |
| **Midpoint** | `mid = (l + r) // 2` (left-biased) |
| **Return** | `l` at loop exit |

**Update Rules**:
```python
if is_valid(mid):  # Predicate is true
    r = mid  # Keep mid as candidate, search left
else:  # Predicate is false
    l = mid + 1  # Move past mid, search right
```
Complexity: O(log n · c) time · O(1) space — log n probes, each paying one predicate check costing c; `r = mid` keeps the valid candidate inside the range

**Example**: [LeetCode 34 - Find First and Last Position](https://leetcode.com/problems/find-first-and-last-position-of-element-in-sorted-array/)

---

## Template: Maximum Boundary Search (Last True Position)

*When:* Find the rightmost position where a monotonic predicate is true

**Use Case**: Find the rightmost position where a monotonic predicate is true

| Component | Value |
|-----------|-------|
| **Loop** | `while l < r` |
| **Midpoint** | `mid = (l + r + 1) // 2` (right-biased) |
| **Return** | `l` at loop exit |

**Update Rules**:
```python
if is_valid(mid):  # Predicate is true
    l = mid  # Keep mid as candidate, search right
else:  # Predicate is false
    r = mid - 1  # Move before mid, search left
```
Complexity: O(log n · c) time · O(1) space — mirror of the minimum form — log n probes, each paying the predicate; `l = mid` keeps the last valid candidate

**Example**: [LeetCode 74 - Search a 2D Matrix](https://leetcode.com/problems/search-a-2d-matrix/)

---

## Understanding `is_valid(mid)`

### What is it?

`is_valid(mid)` is **not a literal function**—it's a placeholder representing the **monotonic predicate** specific to your problem.

It answers: *"Does `mid` satisfy the problem's constraint?"*

### Why it matters

For binary search to work on boundaries, you need a **monotonic** condition:
- **Min Boundary**: `F F F T T T` ← Find first `T`
- **Max Boundary**: `T T T F F F` ← Find last `T`

### Real Examples

#### Example 1: Koko Eating Bananas (Max Boundary)
```python
# Problem: Find minimum speed k such that Koko finishes within h hours
# is_valid(mid) = "Can Koko finish at speed mid?"

def can_finish(piles, mid, h):
    hours = sum(math.ceil(pile / mid) for pile in piles)
    return hours <= h  # This is is_valid(mid)

while l < r:
    mid = (l + r + 1) // 2
    if can_finish(piles, mid, h):  # is_valid(mid)
        l = mid  # Keep mid, search for smaller speeds
    else:
        r = mid - 1  # Too slow, search for faster speeds
```

#### Example 2: LeetCode 74 - Search 2D Matrix (Max Boundary)
```python
# Problem: Find which row contains the target
# is_valid(mid) = "Is the first element of row mid <= target?"

while l < r:
    mid = (l + r + 1) // 2
    if matrix[mid][0] <= target:  # is_valid(mid)
        l = mid  # Keep mid, search later rows
    else:
        r = mid - 1  # Row too large, search earlier rows
```

#### Example 3: LeetCode 34 - Find First Position (Min Boundary)
```python
# Problem: Find the first index where nums[mid] >= target
# is_valid(mid) = "Is nums[mid] >= target?"

while l < r:
    mid = (l + r) // 2
    if nums[mid] >= target:  # is_valid(mid)
        r = mid  # Keep mid, search earlier positions
    else:
        l = mid + 1  # Too small, search right
```

### Pattern Recognition

To identify `is_valid(mid)` in a problem:

1. **Read the problem goal** (find min/max of X that satisfies condition Y)
2. **Ask: "Does this candidate value work?"**
3. **That question is your `is_valid(mid)` condition**

| Problem Type | is_valid Question |
|--------------|-------------------|
| Koko Eating Bananas | Can Koko finish at this speed? |
| Search 2D Matrix | Does this row possibly contain the target? |
| Find First Match | Does this value >= target? |
| Capacity to Ship | Can I ship all packages with this capacity? |

---

## Key Insights

### Why Bias Matters

- **Left-biased** `mid = (l + r) // 2`: Naturally tends toward the lower half when interval is even
  - Use with `r = mid` to find the **first true** position
  - Prevents infinite loops when `mid == l`

- **Right-biased** `mid = (l + r + 1) // 2`: Naturally tends toward the upper half when interval is even
  - Use with `l = mid` to find the **last true** position
  - Prevents infinite loops when `mid == r`

### Mental Model

| Scenario | Pattern | Midpoint | When Valid | When Invalid |
|----------|---------|----------|-----------|--------------|
| Exact match | `l <= r` | `(l+r)//2` | Return/Found | Move away from mid |
| First true | `l < r` | `(l+r)//2` | `r = mid` | `l = mid+1` |
| Last true | `l < r` | `(l+r+1)//2` | `l = mid` | `r = mid-1` |

The bias ensures the loop converges to the correct boundary **without getting stuck**.

## Practice

- LC 704 — Binary Search
- LC 34 — Find First and Last Position of Element in Sorted Array
- LC 74 — Search a 2D Matrix

## Common pitfalls

- left <= right (find exact) vs left < right (find boundary) — mixing them causes off-by-one
- right = mid vs right = mid − 1 — if mid can be the answer, use right = mid
- Max-boundary form: with `l = mid` compute `mid = (l + r + 1) // 2`, or the loop never terminates when `l == r − 1`
- Rotated sorted array: identify which half is sorted first, then decide which side the target is on
- Integer overflow on mid — (left + right) // 2 is safe in Python; in Java/C++ use left + (right − left) / 2
