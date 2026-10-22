# Fundamentals — the maths under the techniques

Theory the problems actually lean on, **filed by subject**. Two rules keep this from
becoming a textbook:

- **A card is written only when a rep has needed it.** Same discipline as `techniques.yml`.
- **A folder appears only when it has a second card.** Until then the card sits flat.

## graph_theory/

| Card | Answers | Earned on |
|---|---|---|
| [circuit_rank.md](graph_theory/circuit_rank.md) | `E − V + C` = independent cycles; the rank-0 case gives the tree rules | 261, Aug 16 |
| [degree_and_parity.md](graph_theory/degree_and_parity.md) | handshake lemma; why a walk strands at an odd-degree vertex; Eulerian conditions | 332 / Hierholzer |

## complexity/

| Card | Answers | Earned on |
|---|---|---|
| [big_o.md](complexity/big_o.md) | growth rates, per-technique costs | — |
| [amortized_analysis.md](complexity/amortized_analysis.md) | why one O(n) call can still be O(1) amortized | 901 · 739 · 503 |
| [bound_tightness.md](complexity/bound_tightness.md) | attainable ≠ representative; pick the parameter that shows what the structure buys | 496 · 208, Aug 16 |

## Not yet written — waiting for a rep to demand them

**combinatorics** (would be the third folder): pigeonhole — the 202 collapse ·
**exchange argument** — when greedy is provably correct.
**complexity**: monotonic predicates, why binary search on the answer is valid.

⭐ The exchange argument is already half the **Intervals + Greedy concept primer**
scheduled for the Aug 17 build, so it gets written there and lands here as a
byproduct — see [[feedback_concept_primer]]. Primers fill this folder; it is not a
separate chore.

⚠️ **The Dec 7–28 phase (Bit Manipulation + Math & Geometry) will want `number_theory/`
and `geometry/`.** Do not pre-create them — they arrive with their second card.
