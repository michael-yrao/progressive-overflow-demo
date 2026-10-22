# Dynamic Programming Patterns

## When to reach for it

The question asks for one number about all the ways to do something (how many, the fewest, the most, or whether any works), and the same sub-question comes up through many different paths. Solve each sub-question once, store it, and build the answer from the stored values.

- "How many ways", "minimum / maximum", "is it possible", over a sequence of choices
- The rest of the problem depends only on where you are now, not on how you got there

## Picking feature

The answer is a single count / min / max / yes-no, and a state such as "standing at index i" is reached by many different paths, so each state is solved once instead of once per path.

- **not backtracking**: every arrangement must be LISTED, not counted or optimized, and a cache cannot shrink an output that is itself exponential
- **not greedy**: one local choice can be proven safe at every step, so there is nothing to compare across branches

## Quick Reference

**Combine: what the question asks picks the combine and the invalid value**

| Question | Combine | Invalid branch returns | Base (finished) returns |
|----------|---------|------------------------|-------------------------|
| How many ways | `+` | `0` | `1` |
| Fewest / cheapest | `min` | `math.inf` | `0` |
| Most / largest | `max` | `-math.inf` | `0` |
| Is it possible | `or` | `False` | `True` |

**State shape: what one state reads picks the template**

| Shape | Cue | State `i` reads | Decision loop |
|-------|-----|-----------------|---------------|
| **Fixed jumps** | each move covers one of a few fixed distances | `i + 1`, `i + 2`, … (a constant set) | none: one term per move |
| **Any-length piece** | each move cuts off a piece of any length that has to pass a check | every `j > i` whose piece `s[i:j]` passes | `for j in range(i + 1, n + 1)` |

More shapes are added the day their first problem is done.

---

## The six slots

Backtracking's slots carry over. `path` drops out because only a number comes back, and two slots are new.

| Slot | Question to answer | 70 Climbing Stairs |
|------|--------------------|--------------------|
| **State** | What is the least I need to know to finish from here? | the stair `i` |
| **Decision** | What are the moves from this state? | 1 step or 2 steps |
| **Validity** | Which moves are illegal, and what do they return? | past `n` → `0` |
| **Base case** | Which state is finished, and what is its answer? | `i == n` → `1` |
| **Combine** | How do the moves' answers merge? | `+` |
| **Memo / fill order** | Top-down: store before returning. Bottom-up: fill each entry after everything it reads. | `memo[i] = …`; or fill `n` down to `0` |

---

## Complexity: distinct states × work per state

Backtracking costs **nodes × work per node**. With a memo, each state is expanded once and every repeat is an O(1) lookup, so nodes become **distinct states**.

1. **Distinct states** = how many values the memo key can take.
2. **Work per state** = the body of ONE call, with every child call counted as O(1). A child's own work is charged to the child's state.
3. **Space** = memo entries + the longest chain of first-time calls (top-down), or the table (bottom-up).

| Problem | Distinct states | Work per state | Time |
|---------|-----------------|----------------|------|
| 70 Climbing Stairs | `i` = 0…n → n + 1 | two calls, an add, a store → O(1) | O(n) |
| Counting palindrome partitions | `i` = 0…n → n + 1 | loop over every `j`, an O(n) palindrome check each → O(n²) | O(n³) |

⚠️ **The trap:** pricing the memoized function as the tree without the memo (O(2ⁿ)). With the memo, 70 makes 2n + 1 calls; without it, 4,356,617 at n = 30.

## Template: Fixed Jumps (top-down)

*When:* each state reads a constant set of other states, one per move, such as `i + 1` and `i + 2`.

```python
def solve(n):
    memo = {}

    def f(i):
        if i == n: return BASE              # base case: finished exactly
        if i > n: return INVALID            # validity: a move went past the end
        if i in memo: return memo[i]
        memo[i] = COMBINE(f(i + step) for step in STEPS)   # decision + combine, stored
        return memo[i]

    return f(0)
```
Complexity: O(n · k) time · O(n) space — n + 1 states, each combining k fixed moves at O(1) per move; the memo and the recursion chain are both n + 1 deep

**Example**: [LeetCode 70 - Climbing Stairs](https://leetcode.com/problems/climbing-stairs/)

---

## Template: Fixed Jumps (bottom-up)

*When:* the same shape, without recursion: no stack-depth limit, and the table can shrink to the last few entries.

```python
def solve(n):
    table = [INVALID] * (n + MAX_STEP + 1)  # slots past n hold the invalid value
    table[n] = BASE                         # base case, seeded before the loop
    for i in range(n - 1, -1, -1):          # fill order: i reads i + step, so go right to left
        table[i] = COMBINE(table[i + step] for step in STEPS)
    return table[0]
```
Complexity: O(n · k) time · O(n) space — one pass over n states with k reads each; when only the last MAX_STEP entries are read, keep that many variables instead for O(1) space

**Example**: [LeetCode 70 - Climbing Stairs](https://leetcode.com/problems/climbing-stairs/)

---

## Template: Any-Length Piece (top-down)

*When:* each move cuts a piece `s[i:j]` of any length off the front of what is left, and the piece has to pass a check.

```python
def solve(s):
    n = len(s)
    memo = {}

    def f(i):
        if i == n: return BASE              # base case: the pieces cover the whole input
        if i in memo: return memo[i]
        answer = INVALID                    # no valid piece → the invalid value
        for j in range(i + 1, n + 1):       # decision: every piece that starts at i
            if is_valid_piece(s, i, j):     # validity
                answer = COMBINE(answer, f(j))
        memo[i] = answer
        return answer

    return f(0)
```
Complexity: O(n² · c) time · O(n) space — n + 1 states, each trying up to n pieces with a check costing c; the memo and the recursion chain are both n + 1 deep

**Example**: counting the palindrome partitions of a string (a 1D DP primer)

---

## Template: Any-Length Piece (bottom-up)

*When:* the same shape, without recursion.

```python
def solve(s):
    n = len(s)
    table = [INVALID] * (n + 1)
    table[n] = BASE                         # base case, seeded before the loop
    for i in range(n - 1, -1, -1):          # fill order: i reads every j > i, so go right to left
        for j in range(i + 1, n + 1):
            if is_valid_piece(s, i, j):
                table[i] = COMBINE(table[i], table[j])
    return table[0]
```
Complexity: O(n² · c) time · O(n) space — n entries, each scanning up to n pieces with a check costing c; one table of n + 1

**Example**: counting the palindrome partitions of a string (a 1D DP primer)

---

## Understanding the state

### What is it?

The state is the least you need to know to finish from here. Two different paths that reach the same state have the same answer from there on.

### Why it matters

That shared answer is what makes caching correct. If two situations that finish differently share one key, the memo hands back the wrong answer.

### Real Examples

#### Example 1: Counting palindrome partitions of `"aaaa"` (Any-Length Piece)

`"a" + "a"` and `"aa"` both stop at index 2 and both leave `"aa"` to split, so `ways(2)` is the same for both. `ways(i)` = sum of `ways(j)` over every palindrome piece `s[i:j]`:

| i | 4 (empty) | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|
| ways(i) | 1 | 1 | 2 | 4 | 8 |

#### Example 2: 70 Climbing Stairs (Fixed Jumps)

From stair `i`, the first move is 1 or 2 steps. Each climb has exactly one first move, so the two groups never overlap and the counts add. Filled from the top for `n = 3`:

| stair i | 4 (past the top) | 3 (the top) | 2 | 1 | 0 |
|---|---|---|---|---|---|
| ways(i) | 0 | 1 | 1 + 0 = 1 | 1 + 1 = 2 | 2 + 1 = 3 |

### Pattern Recognition

| Context | How to Identify |
|---------|-----------------|
| A move covers one of a few fixed distances | **Fixed Jumps**: one term per move |
| A move cuts a checked piece of any length | **Any-Length Piece**: loop over every end `j` |

---

## Key Insights

### Top-down vs bottom-up

| | Top-down (memo) | Bottom-up (table) |
|---|---|---|
| **Writing it** | straight from the recursive definition | you work out the fill order |
| **What gets computed** | only the states the recursion reaches | every slot |
| **Stack** | depth up to n; Python's default limit is 1000 frames | a plain loop |
| **Space trimming** | hard: the memo holds every entry | easy when an entry reads only a fixed few earlier ones |

### Mental Model

| Backtracking slot | DP slot |
|-------------------|---------|
| path | dropped: only the number comes back |
| state | state |
| decision | decision |
| validity | validity, returning the invalid value from the combine table |
| base case (record the path) | base case (return the finished answer) |
| — | **combine** |
| — | **memo / fill order** |

## Practice

- LC 70 — Climbing Stairs

## Common pitfalls

- No invalid-move case: a move that jumps past the end never reaches the base case and recurses until the stack limit
- Returning the combined value without storing it in the memo, so the lookup never finds anything and every repeat is solved again
- A state that leaves out a variable the answer depends on (two situations share one key) or keeps one it does not (`path`), which leaves the cache wrong or useless
- Bottom-up fill order that reads an entry before it is filled
- Pricing a memoized function as its tree without the memo: count distinct states × work per state instead
