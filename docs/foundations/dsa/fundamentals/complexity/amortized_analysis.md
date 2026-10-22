# Amortized analysis — when one slow call is still cheap

A single operation costs O(n); the whole sequence still costs O(n). Not an average
over lucky inputs — a **bound on the total**, then divided.

## The accounting argument

Charge work to the **element**, not to the call. If each element can be touched a
bounded number of times *ever*, total work is bounded no matter how it clumps.

Monotonic stack: **each index is pushed once and popped at most once.** So the inner
`while` across all n calls does ≤ n pops total → **amortized O(1) per call, O(n) overall**,
even though one call can pop everything.

## Why the per-call worst case is the wrong number

On **901 Online Stock Span**, the naive backward scan is *also* O(n) worst case per
call — but O(n²) overall. The monotonic stack is O(n) overall. **The per-call worst
case cannot tell them apart**, so it is not the number being asked for.

⚠️ State both, lead with amortized: *"O(n) worst case for one call, but amortized O(1)
because each element is pushed and popped once."*

## Where it shows up

**901 · 739 Daily Temperatures · 503 Next Greater Element II** — same argument all
three times. Also **union-find with path compression** (near-constant per op) and
**dynamic arrays** (doubling makes append amortized O(1)).

⚠️ **503 has a wrinkle:** the two-pass circular loop pushes on every one of `2n`
iterations, so the stack can hold **n+1**, not n. The bound survives; the itemization
does not.
