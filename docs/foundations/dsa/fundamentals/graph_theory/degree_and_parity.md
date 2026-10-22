# Degree and parity — why walks get stuck where they do

**Degree** = edges touching a vertex. **Handshake lemma:** every edge contributes 2,
so `Σ degree = 2E` and **the number of odd-degree vertices is always even.**

## The consequence that matters

Walk a graph, consuming each edge as you use it. **Every visit to a vertex burns two
edges — one in, one out.** So an even-degree vertex can never trap you: if you got in,
there is always a way out.

You can only get stuck at a vertex with **odd** degree.

## Eulerian conditions fall straight out

| | Condition |
|---|---|
| **Circuit** (start = end) | every vertex has even degree |
| **Path** (start ≠ end) | exactly two odd vertices — and they *are* the start and end |
| **Neither** | any other count of odd vertices |

Directed version: circuit needs `in == out` everywhere; path needs one vertex with
`out − in = 1` (the start) and one with `in − out = 1` (the end).

## Where it shows up

**332 Reconstruct Itinerary / Hierholzer.** This is why "getting stuck is not a
failure" — the parity argument *guarantees* you strand at the end vertex, every time,
so the walk never needs to backtrack. That is the whole reason the algorithm is linear
instead of exponential.

**2097 Valid Arrangement of Pairs.** The start vertex is not given; you find it with
`out − in = 1`, which is this rule used as a constructor rather than a check.
