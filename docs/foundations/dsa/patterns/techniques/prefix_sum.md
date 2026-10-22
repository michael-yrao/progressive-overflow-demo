# Prefix Sum Patterns

A **prefix sum** array stores running totals so any range sum becomes a single subtraction. The high-leverage variant pairs prefix sums with a **hashmap** to answer "how many subarrays sum to k" in O(n).

## When to reach for it

A prefix sum array stores running totals so any range sum becomes a single subtraction. The high-leverage variant pairs prefix sums with a hashmap to answer "how many subarrays sum to k" in O(n).

- "sum of a subarray / range" — especially many range queries
- "number of subarrays with sum == k" (or sum divisible by k)
- "longest/shortest subarray summing to k"
- any running-total or cumulative question

If brute force is "try every subarray and sum it" (O(n²) or O(n³)), prefix sums collapse it.

## Picking feature

Many RANGE-SUM questions on a fixed array, or "how many subarrays sum to k" — a running total turns each range into one subtraction, and a hashmap of seen totals turns the count into a lookup.

- **not sliding-window** — values are all non-negative and the question is longest/shortest run — the window is O(1) space and simpler; prefix + hashmap is what you reach for when negatives break the window


## Template: Range sum queries

`prefix[i]` = sum of `arr[0..i-1]` (with `prefix[0] = 0`). Then:

```python
prefix = [0] * (len(arr) + 1)
for i, x in enumerate(arr):
    prefix[i + 1] = prefix[i] + x
# sum of arr[l..r] inclusive:
range_sum = prefix[r + 1] - prefix[l]
```
Complexity: O(n) build · O(1) per query time · O(n) space — one pass builds n + 1 running totals; each range query is a single subtraction

The `+1` offset (prefix has length n+1, `prefix[0]=0`) removes all the off-by-one pain — a range is just the difference of two prefix values.

## Template: Subarrays summing to k (prefix + hashmap)

The unlock: a subarray `(j, i]` sums to `k` iff `prefix[i] - prefix[j] == k`, i.e. `prefix[j] == prefix[i] - k`. So as you sweep, ask "have I seen a prefix equal to `current - k`?"

```python
count = 0
running = 0
seen = {0: 1}                 # prefix 0 seen once (empty prefix) — REQUIRED
for x in arr:
    running += x
    count += seen.get(running - k, 0)   # subarrays ending here that sum to k
    seen[running] = seen.get(running, 0) + 1
return count
```
Complexity: O(n) time · O(n) space — one pass; the hashmap holds up to n distinct prefix totals

## Practice

- LC 560 — Subarray Sum Equals K
- LC 238 — Product of Array Except Self
- LC 303 — Range Sum Query - Immutable
- LC 304 — Range Sum Query 2D - Immutable
- LC 525 — Contiguous Array

| Problem | NC150? | Wrinkle |
|---|---|---|
| 560. Subarray Sum Equals K | ✅ | The canonical prefix+hashmap (done) |
| 238. Product of Array Except Self | ✅ | Prefix *and* suffix products (same idea, multiply) |
| 303 / 304. Range Sum Query (1D / 2D) | No | Precompute prefix, O(1) queries |
| 525. Contiguous Array | No | Map +1/-1, find equal 0s and 1s via prefix |

## Common pitfalls

- **Forgetting `seen = {0: 1}`** — without the empty-prefix seed, you miss subarrays that start at index 0.
- **Off-by-one** — decide up front whether `prefix[i]` includes `arr[i]` or not, and keep the length-(n+1) convention to stay sane.
- **Counting vs length** — "how many subarrays" stores counts in the map; "longest subarray" stores the *first index* a prefix was seen (so you maximize length).
