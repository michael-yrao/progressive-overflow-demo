# Two Pointers Patterns

## When to reach for it

Use two pointers on a sorted array or string when searching for a pair, triplet, or re-arranging elements in-place — it collapses an O(n²) nested search to O(n).

- Sorted array + "find a pair/triple summing to target"
- Sorted Sequence Pairs
- Node Loop / Middle Node
- In-place Content Removal

## Picking feature

Sorted (or sortable) input where moving ONE index in a known direction can only change the comparison one way — that monotonic response is what lets two indices replace a nested loop.

- **not sliding-window** — the pair must be a contiguous RUN, not two arbitrary positions
- **not binary-search** — you need one boundary index, not a pair

## Quick Reference


| Pattern | Initial Pointer Setup | Pointer Movement | Use Case |
|---------|-----------------------|------------------|----------|
| **Opposite Ends** | `l = 0`, `r = len(arr) - 1` | `l += 1` and/or `r -= 1` | Sorted arrays, searching pairs, checking palindromes |
| **Fast & Slow** | `slow = 0`, `fast = 0` | `slow += 1`, `fast += 2` | Linked lists, cycle detection, finding midpoints |
| **Separation** | `i = 0`, `j = 0` | `j += 1`, `i` moves conditionally | In-place partitioning, removing duplicates |

---

## Template: Opposite Ends Pattern

*When:* Finding pairs or checking symmetries in sorted structural constraints.

**Use Case**: Finding pairs or checking symmetries in sorted structural constraints.

![Opposite-direction pointers converging from both ends of a sorted array](../../images/two_pointers_technique.svg)

| Component | Value |
|-----------|-------|
| **Loop** | `while l < r` |
| **Key Check** | `current_sum = arr[l] + arr[r]` or `arr[l] == arr[r]` |
| **Return** | Indices `[l, r]` or a boolean validation |

**Implementation**:
```python
def two_sum_sorted(numbers: list[int], target: int) -> list[int]:
    l, r = 0, len(numbers) - 1
    while l < r:
        cur = numbers[l] + numbers[r]
        if cur == target:
            return [l + 1, r + 1]  # Return 1-indexed positions
        elif cur < target:
            l += 1  # Sum too small, move left pointer rightward
        else:
            r -= 1  # Sum too large, move right pointer leftward
    return []
```
Complexity: O(n) time · O(1) space — the pointers close by at least one step per iteration

**Example**: [LeetCode 167 - Two Sum II - Input Array Is Sorted](https://leetcode.com)

---

## Template: Fast & Slow Pointer Pattern (Tortoise and Hare)

*When:* Detecting structural loops, intersections, or calculating dynamic midpoints.

**Use Case**: Detecting structural loops, intersections, or calculating dynamic midpoints.


| Component | Value |
|-----------|-------|
| **Loop** | `while fast and fast.next` |
| **Key Formula** | `slow = slow.next` and `fast = fast.next.next` |
| **Return** | `True` on collision, or node reference at exit |

**Implementation**:
```python
def has_cycle(head: Optional[ListNode]) -> bool:
    slow, fast = head, head
    while fast and fast.next:
        slow = slow.next        # Moves 1 node at a time
        fast = fast.next.next   # Moves 2 nodes at a time
        if slow == fast:
            return True         # Fast caught up to slow (cycle detected)
    return False
```
Complexity: O(n) time · O(1) space — fast traverses the list in at most n/2 steps; two references

**Example**: [LeetCode 141 - Linked List Cycle](https://leetcode.com)

---

## Template: Separation Pattern

*When:* Modifying arrays in-place while separating elements based on content.

**Use Case**: Modifying arrays in-place while separating elements based on content.


| Component | Value |
|-----------|-------|
| **Loop** | `for fast in range(len(arr))` |
| **Key Formula** | `arr[slow] = arr[fast]` inside condition |
| **Return** | `slow` index or modified bounds |

**Implementation**:
```python
def remove_duplicates(nums: list[int]) -> int:
    if not nums: return 0
    slow = 0  # Points to the last unique element found
    for fast in range(1, len(nums)):
        if nums[fast] != nums[slow]:
            slow += 1  # Move unique zone boundary
            nums[slow] = nums[fast]  # Overwrite with new item
    return slow + 1
```
Complexity: O(n) time · O(1) space — fast scans once; slow only advances on a keeper — in place

**Example**: [LeetCode 26 - Remove Duplicates from Sorted Array](https://leetcode.com)

### Three-way variant — Dutch National Flag

Separation with **three** regions instead of two. `low` and `mid` advance from the front, `high`
retreats from the back, and the array is fully sorted in one pass with O(1) space. The whole
algorithm is bookkeeping on four regions — read the invariant, not the swap code:

![Dutch National Flag invariant regions: 0s below low, 1s from low to mid, unknown from mid to high, 2s above high](../../images/dutch_flag_algorithm_1.svg)

Worked end-to-end on Sort Colors, input through output:

![Dutch National Flag three-way partitioning applied to Sort Colors, showing input, pointer movement, and sorted output](../../images/dutch_flag_algorithm_2.svg)

**The one trap**: when you swap with `high`, do **not** advance `mid` — the element you just pulled
in from the back is unexamined. Swapping with `low` is safe to advance past, because what comes back
is already known to be a 1.

**Example**: [LeetCode 75 - Sort Colors](https://leetcode.com/problems/sort-colors/)

---

## Understanding Target Adjustments

### What is it?
**Target adjustments** refer to altering pointer movement logic based on an dynamic aggregate metric (e.g., expanding or closing a boundaries gap).

### Why it matters
Choosing the wrong direction or increment rule will trigger out-of-bound errors, duplicate element traps, or absolute infinite loops.

### Real Examples

#### Example 1: Valid Palindrome II (Opposite Ends Expansion/Shrinking)
```python
def valid_palindrome(s: str) -> bool:
    def check(l, r):
        while l < r:
            if s[l] != s[r]: return False
            l, r = l + 1, r - 1
        return True
    
    l, r = 0, len(s) - 1
    while l < r:
        if s[l] != s[r]:
            # Skip left OR skip right element
            return check(l + 1, r) or check(l, r - 1)
        l, r = l + 1, r - 1
    return True
```

#### Example 2: Move Zeroes (Separation Structure)
```python
def move_zeroes(nums: list[int]) -> None:
    slow = 0  # Tracks non-zero index position
    for fast in range(len(nums)):
        if nums[fast] != 0:
            nums[slow], nums[fast] = nums[fast], nums[slow]
            slow += 1
```

### Pattern Recognition


| Context | How to Identify |
|---------|-----------------|
| Sorted Sequence Pairs | Use **Opposite Ends** to close structural gaps |
| Node Loop / Middle Node | Use **Fast & Slow** to identify geometric distances |
| In-place Content Removal | Use **Separation** to stream valid inputs forward |

---

## Key Insights

### Why Sub-problem Checking Matters

- **Skipping elements**: When structural paths diverge (e.g., mismatch in validation), breaking out into a isolated verification helper function allows evaluation of fallback states without destroying state histories.

### Mental Model


| Strategy | Speed Contrast | Key Invariant |
|----------|----------------|---------------|
| **Opposite Ends** | Same velocity, converging vectors | Everything outside `[l, r]` is fully processed |
| **Fast & Slow** | 2x structural variation divergence | Distance between pointers increases by 1 step every loop |
| **Separation** | Fast scans, slow acts as insertion line | Elements before `slow` match target criteria |

## Practice

- LC 167 — Two Sum II - Input Array Is Sorted
- LC 141 — Linked List Cycle
- LC 26 — Remove Duplicates from Sorted Array
- LC 75 — Sort Colors

## Common pitfalls

- Applying two pointers to an unsorted array without sorting first — produces wrong results
- Not skipping duplicate values in 3Sum — the output will contain duplicate triplets
- Infinite loop from failing to advance a pointer after processing a match
- Off-by-one: use left < right (not <=) when the pointers must not cross
