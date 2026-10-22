# Bound tightness — attainable is not the same as representative

A bound is **tight** when some input actually attains it. Tight is the bar Big-O sets,
and it is a lower bar than "describes what usually happens".

## Two ways a true bound can still be the wrong answer

**1. The aggregate differs from the per-call worst case.**

A monotonic stack's `next()` really can be O(n) — one call may pop everything. That is
attainable, so it is tight. It is still not the number that matters, because across n
calls the total is O(n), not O(n²). The naive backward scan has the *same* per-call
worst case and is O(n²) overall, so **the per-call figure cannot tell the two apart** —
which is the test for whether you are quoting the useful bound.
→ [`amortized_analysis.md`](amortized_analysis.md)

**2. The parameter is chosen badly.**

A trie holding N words of length L is `O(N·L)` in space. Attainable — give it 26 words
starting with different letters and nothing is shared. But that is the case where the
structure is **pointless**, so the bound describes a trie nobody would build.

Exact instead: **O(P)**, where `P` = the number of distinct prefixes. `P` *is* the node
count, and `P ≤ Σ|wᵢ|` with equality only when nothing is shared. **The gap between `P`
and `Σ|wᵢ|` is the entire reason to use a trie**, and quoting `O(N·L)` hides it.

## The test

> Does this bound distinguish my structure from the naive one it replaced?

If not, you are quoting something true and uninformative. Say the tight bound, then say
the one that carries the argument.

⚠️ **Do not "fix" this by averaging.** Average-case analysis needs a distribution over
inputs, which you rarely have. Choosing a better **parameter** (`P` instead of `N·L`) is
exact and needs no assumptions.

**Earned on:** 496 (Aug 16, the amortized case) · 208 (Aug 16, the parameter case — the
learner rejected `O(N·L)` as "almost never the case", which is what produced this card).
