# Sliding Window Patterns

## When to reach for it

When a problem asks for the longest or shortest contiguous subarray or substring satisfying a condition, grow the right edge freely and shrink the left edge conditionally.

- "Contiguous subarray/substring" + a constraint (≤ k distinct, sum, longest/shortest)
- Subarray of explicit static width `K`
- Longest contiguous substring criteria
- Smallest window containing specific items

## Picking feature

A CONTIGUOUS run plus a condition that stays true (or false) as the window grows — that monotonicity is what lets the left edge only ever move right.

- **not prefix-sum** — values can be negative, or the question is "count subarrays summing to k" — the window cannot decide which edge to move; use prefix totals + a hashmap
- **not two-pointer** — the two indices are chosen from anywhere in a sorted array (a pair), not the two ends of one contiguous run

## Quick Reference


| Pattern | Window Resizing | Key Internal Metrics | Use Case |
|---------|-----------------|----------------------|----------|
| **Fixed Window** | Subarray bounds static, `r` shifts `l` | Single `sum` or static counter tracking | Continuous subsegments of static width `k` |
| **Dynamic (Max)**| `r` expands, `l` shrinks inside loop | Frequency map tracker, custom boolean switches | Finding longest subarray matching criteria |
| **Dynamic (Min)**| `r` expands, `l` aggressively moves | Aggregate requirements verification | Finding shortest sequence matching criteria |

---

## Template: Fixed Window Pattern

*When:* Computing aggregate metrics across consecutive element windows of an exact static width k.

**Use Case**: Computing aggregate metrics across consecutive element windows of an exact static width `k`.


| Component | Value |
|-----------|-------|
| **Loop** | `for r in range(len(arr))` |
| **Key Formula** | `if r >= k - 1:` trigger condition |
| **Window Eviction**| `arr[r - k + 1]` dropped from status |

**Implementation**:
```python
def find_max_average(nums: list[int], k: int) -> float:
    curr_sum = 0
    # Initialize first window prefix sum
    for i in range(k): curr_sum += nums[i]
    max_sum = curr_sum
    
    for r in range(k, len(nums)):
        curr_sum += nums[r] - nums[r - k]  # Add right, subtract left element
        max_sum = max(max_sum, curr_sum)
    return max_sum / k
```
Complexity: O(n) time · O(1) space — each element is added once and subtracted once; a single running sum

**Example**: [LeetCode 643 - Maximum Average Subarray I](https://leetcode.com)

---

## Template: Dynamic Window (Max Variant)

*When:* Seeking the maximum length sequence that satisfies a specific constraint configuration.

**Use Case**: Seeking the maximum length sequence that satisfies a specific constraint configuration.


| Component | Value |
|-----------|-------|
| **Loop** | `for r in range(len(s))` |
| **Key Formula** | `while condition_invalid:` shift `l` right |
| **Return** | `max_len = max(max_len, r - l + 1)` |

**Implementation**:
```python
def length_of_longest_substring(s: str) -> int:
    seen = set()
    l, max_len = 0, 0
    for r in range(len(s)):
        while s[r] in seen:
            seen.remove(s[l])   # Evict left until window character is unique
            l += 1
        seen.add(s[r])
        max_len = max(max_len, r - l + 1)  # Track global maximum distance
    return max_len
```
Complexity: O(n) time · O(min(n, Σ)) space — `r` visits each index once and `l` never moves back — at most 2n steps; the set holds the window's distinct characters, bounded by the alphabet Σ

**Example**: [LeetCode 3 - Longest Substring Without Repeating Characters](https://leetcode.com)

---

## Template: Dynamic Window (Min Variant)

*When:* Locating the smallest possible localized footprint that fulfills the mandatory requirements.

**Use Case**: Locating the smallest possible localized footprint that fulfills the mandatory requirements.


| Component | Value |
|-----------|-------|
| **Loop** | `for r in range(len(nums))` |
| **Key Formula** | `while condition_valid:` minimize length, push `l` |
| **Return** | `min_len` tracked via tracking boundaries |

**Implementation**:
```python
def min_subarray_len(target: int, nums: list[int]) -> int:
    l, total = 0, 0
    min_len = float('inf')
    for r in range(len(nums)):
        total += nums[r]
        while total >= target:  # Condition valid: aggressively shrink window
            min_len = min(min_len, r - l + 1)
            total -= nums[l]
            l += 1
    return 0 if min_len == float('inf') else min_len
```
Complexity: O(n) time · O(1) space — the same two-edge sweep; only a running total is kept

**Example**: [LeetCode 209 - Minimum Size Subarray Sum](https://leetcode.com)

---

## Understanding State Counters

### What is it?
**State counters** are associative structures (`dict`, `Counter`, array frequency tables) tracking metadata occurrences within active sliding frame parameters.

### Why it matters
Using raw sub-segment parsing on every iteration ruins algorithmic performance, scaling the time profile to \(O(K \cdot N)\). State counters maintain mutations in \(O(1)\) constant overhead updates instead.

### Real Examples

#### Example 1: Permutation in String (Fixed Window Frequency Match)
```python
from collections import Counter

def check_inclusion(s1: str, s2: str) -> bool:
    cnt1, cnt2 = Counter(s1), Counter(s2[:len(s1)-1])
    l = 0
    for r in range(len(s1) - 1, len(s2)):
        cnt2[s2[r]] += 1
        if cnt1 == cnt2: return True
        cnt2[s2[l]] -= 1
        if cnt2[s2[l]] == 0: del cnt2[s2[l]]
        l += 1
    return False
```

#### Example 2: Longest Repeating Character Replacement (Dynamic Max Optimization)
```python
def character_replacement(s: str, k: int) -> int:
    count = {}
    l, max_f = 0, 0
    for r in range(len(s)):
        count[s[r]] = 1 + count.get(s[r], 0)
        max_f = max(max_f, count[s[r]])
        # If total window len minus dominant count exceeds replacement budget
        if (r - l + 1) - max_f > k:
            count[s[l]] -= 1
            l += 1
    return (r - l + 1)
```

### Pattern Recognition


| Context | How to Identify |
|---------|-----------------|
| Subarray of explicit static width `K` | Apply **Fixed Window** array step additions/subtractions |
| Longest contiguous substring criteria | Apply **Dynamic Max Window**, adjusting via a `while` loop when bounds fail |
| Smallest window containing specific items | Apply **Dynamic Min Window**, updating the global minimum value inside a `while` loop |

---

## Key Insights

### The Sliding Loop Traversal Strategy

- **Expansion Phase**: The right pointer `r` takes step-by-step leaps via an explicit sequential iteration loop. It is the primary engine mapping data inputs.
- **Contraction Phase**: The left pointer `l` is triggered purely on constraint evaluation outcomes. Its actions represent conditional containment constraints.

### Mental Model


| Strategy | Window Behavior | Key Control Invariant |
|----------|-----------------|-----------------------|
| **Fixed Window** | `[-- Constant Size K --] ->` Shifts right by 1 | Window size is always equal to `k`. Add `r`, evict `l` immediately. |
| **Dynamic Max** | `[--- Expands Right --->]` Shrinks left if invalid | Maximize `r - l + 1`. Shrink window *only* enough to restore validity. |
| **Dynamic Min** | `[--- Expands Right --->]` Shrinks left aggressively | Minimize `r - l + 1`. Shrink window *continually* as long as it remains valid. |

## Practice

- LC 643 — Maximum Average Subarray I
- LC 3 — Longest Substring Without Repeating Characters
- LC 209 — Minimum Size Subarray Sum

## Common pitfalls

- Updating the result inside the shrink loop instead of outside — misses valid states
- Using a dict for counts but not deleting the key when count reaches zero — size check breaks
- Conflating "at most k" vs "exactly k" — exactly k = (at most k) − (at most k−1)
- Shrinking the window when it is already empty — guard with left <= right before shrinking
