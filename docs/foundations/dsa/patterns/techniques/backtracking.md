# Backtracking Patterns

## When to reach for it

Enumerate every candidate by extending a partial choice one step, recursing, then undoing it — the answer is the set of all arrangements, not a single best one.

- "All subsets / permutations / combinations", "find every way"
- Explicit Item Resequencing
- Structural Choice Sequence Steps

## Picking feature

The output is EVERY valid arrangement (all subsets / permutations / combinations), so exponential work is unavoidable — choose, recurse, un-choose.

- **not dynamic-programming** — the question is a count / min / max over choices and the same sub-state recurs — cache states instead of enumerating every path

## Quick Reference


| Pattern | Core Mechanism | State Tracking | Use Case |
|---------|----------------|----------------|----------|
| **Permutations** | Complete exploration tree | Visited element `set` tracker | Finding all possible orderings of non-unique elements |
| **Combinations & Subsets** | Index bounding sweeps | `start_index` position forward skip | Finding groupings where structural sequence order does not matter |

---

## Complexity — nodes × work per node

Every backtracking bound is the same product: **nodes in the call tree × work per node**, with
nodes ≤ **branching^depth**. Per problem, find the two factors:

1. **Depth** = what each step *consumes*, and how many steps until it's gone.
2. **Branching** = choices per step.
3. **Work per node** = the `sum(path)`, copy, or check done in each call.

| Problem | Branching | Depth = what runs out | Nodes |
|---|---|---|---|
| 78 Subsets, take/skip | 2 | the index, n steps | 2^n |
| 39 Combination Sum, take/skip | 2 | takes cap at d = target ÷ min(candidates), skips at n | 2^(d+n) |
| 39 Combination Sum, pick-next loop | up to n | takes only, d | n^d |
| 46 Permutations | n, then n−1, … | slots to fill, n | n! leaves |

⚠️ **The trap:** reading depth as n because that is what Subsets teaches. A *take* with index reuse
consumes **no** index, so the index no longer bounds the branch; the sum does, after d takes. Draw
the tiniest case (`[1]`, target 2 → depth 3 = d + n) and count. Stack space is the depth
(O(d + n) frames), not the node count.

---

## Template: Permutations Pattern

*When:* Finding every possible layout variation of an items list where ordering determines unique results.

**Use Case**: Finding every possible layout variation of an items list where ordering determines unique results.


| Component | Value |
|-----------|-------|
| **Loop** | `for i in range(len(nums))` inside recursive calls |
| **State Guard**| `if nums[i] in current_path: continue` |
| **Base Case** | `if len(current_path) == len(nums):` append copy |

**Implementation**:
```python
def permute(nums: list[int]) -> list[list[int]]:
    result = []
    
    def backtrack(current_path: list[int]):
        if len(current_path) == len(nums):
            result.append(list(current_path))  # Store copy of path
            return
            
        for i in range(len(nums)):
            if nums[i] in current_path: continue  # Skip elements already used
            current_path.append(nums[i])          # Save-state
            backtrack(current_path)               # Recurse deep
            current_path.pop()                    # Undo choice
            
    backtrack([])
    return result
```
Complexity: O(n · n!) time · O(n) space — n! complete permutations, each copied in O(n); the path and the recursion depth are both O(n) (the output list itself is not counted)

**Example**: [LeetCode 46 - Permutations](https://leetcode.com)

---

## Template: Combinations and Subsets Pattern

*When:* Generating all variations of variable-length groupings where sequence arrangement is irrelevant.

**Use Case**: Generating all variations of variable-length groupings where sequence arrangement is irrelevant.


| Component | Value |
|-----------|-------|
| **Loop** | `for i in range(start_index, len(nums))` |
| **Key Variable**| `start_index` increments forward by `i + 1` |
| **Return** | Cumulative tracks appended at top of each block |

**Implementation**:
```python
def subsets(nums: list[int]) -> list[list[int]]:
    result = []
    
    def backtrack(start_index: int, current_path: list[int]):
        result.append(list(current_path))  # Append current subset progress
        
        for i in range(start_index, len(nums)):
            current_path.append(nums[i])          # Make choice
            backtrack(i + 1, current_path)        # Move index limit forward
            current_path.pop()                    # Undo choice
            
    backtrack(0, [])
    return result
```
Complexity: O(n · 2ⁿ) time · O(n) space — 2ⁿ subsets, each copied in up to O(n); recursion depth never exceeds n

**Example**: [LeetCode 78 - Subsets](https://leetcode.com)

---

## Understanding Recursive Call Branches

### What is it?
**Recursive call branches** describe the dynamic pathways generated when a function calls itself inside a standard iteration block.

### Why it matters
Failing to make copies of tracking arrays during leaf execution captures empty elements because the state stack completely unrolls its array values back to raw states during cleanup.

### Real Examples

#### Example 1: Combination Sum (Index Reuse Branching)
```python
def combination_sum(candidates: list[int], target: int) -> list[list[int]]:
    result = []
    def backtrack(i, cur, total):
        if total == target: return result.append(list(cur))
        if total > target or i >= len(candidates): return
        
        cur.append(candidates[i])
        backtrack(i, cur, total + candidates[i])  # Reuse same index i
        cur.pop()
        backtrack(i + 1, cur, total)              # Skip index i
    backtrack(0, [], 0)
    return result
```

#### Example 2: Letter Combinations of a Phone Number (String Multi-Branch)
```python
def letter_combinations(digits: str) -> list[str]:
    if not digits: return []
    mapping = {"2": "abc", "3": "def", "4": "ghi"}  # Sample dictionary
    result = []
    
    def backtrack(i, cur_str):
        if len(cur_str) == len(digits): return result.append(cur_str)
        for char in mapping[digits[i]]:
            backtrack(i + 1, cur_str + char)  # Pure immutable string branch
            
    backtrack(0, "")
    return result
```

### Pattern Recognition


| Context | How to Identify |
|---------|-----------------|
| Explicit Item Resequencing | Apply **Permutations** tracking unique element identities |
| Structural Choice Sequence Steps | Apply **Combinations** restricting loops forward from current values |

---

## Key Insights

### The Deep Copies Overhead
- **Shallow Reference Errors**: `result.append(current_path)` only saves a permanent reference pointing to the path array. As backtracking runs `.pop()`, the objects saved inside results get stripped away too. Always use explicit copies like `list(current_path)`.

### Mental Model


| Strategy | Exploration Flow | Candidate Skip Logic |
|----------|------------------|----------------------|
| **Permutations** | Loop all elements on every step | Skip if item already exists in `current_path` |
| **Combinations** | Loop forward from `start_index` | Items behind the boundary index are dropped entirely |

## Practice

- LC 46 — Permutations
- LC 78 — Subsets

## Common pitfalls

- Appending the mutable path itself instead of a copy — every stored result later mutates into the same list
- Permutations restart `i` at 0 with a used-check; subsets start at `start_index` — mixing the two loop bounds yields duplicates or missing sets
- Forgetting to undo the choice after the recursive call (the `pop`) — the path leaks into sibling branches
- Skipping duplicates needs a sort first plus `if i > start and nums[i] == nums[i-1]: continue` — without the sort the check is meaningless
