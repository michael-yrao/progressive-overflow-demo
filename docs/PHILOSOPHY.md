# The cse-coach Philosophy

Why the system is built the way it is. If the README tells you *how* to use the
coach, this tells you *why* it works.

## 1. Reach beyond the target so you always hit it

The goal is **mastery**, with the interview as a milestone you clear on the way
*past* it — not the finish line. Every curriculum is organized around the
**Interview-ROI Line**:

```
  milestone            interview foundation (NC150 / SD core)
     │                 ← clears most interviews on its own
     ▼
  expansion tier 1     hard-interview depth (top of the ROI curve)
  ═══ INTERVIEW-ROI LINE ═══
     ▼
  expansion tier 2     competitive / architect / infra depth
```

You always train **at least one tier past your target** (`reach_beyond ≥ 1`, never
0). That margin is what makes the target reliable instead of aspirational. Reaching
for the end is non-negotiable — it's the whole point.

### The DSA foundation is NeetCode 150

For DSA, the "interview foundation" tier is the **NeetCode 150** — and this isn't an
arbitrary curriculum choice. The NC150 is the fundamental data-structures-and-algorithms
grounding for *any* software engineer, not just interview candidates. It's a deliberately
small, pattern-organized set (arrays & hashing, two pointers, sliding window, stack,
binary search, linked lists, trees, tries, heaps, backtracking, graphs, dynamic
programming, intervals, greedy, bit manipulation) that covers the core patterns you
actually reach for in real work — the moves behind almost every data-structure decision,
complexity trade-off, and algorithm you'll write on the job.

Three properties make it the right floor for this coach:

- **Pattern coverage over problem count.** ~150 problems chosen so that clearing them
  means owning the *patterns*, not memorizing 150 answers. Once a pattern is retired, new
  problems in it are recognition, not discovery.
- **It clears most interviews on its own.** That's why it sits exactly at the
  Interview-ROI Line — the point of maximum return before the curve flattens into
  hard-interview and competitive depth.
- **It's the transferable base for everything above it.** Expansion tiers (harder graph
  and DP variants, competitive techniques) and even System Design intuition build on these
  patterns. Skip the foundation and the reach-beyond tiers have nothing to stand on.

So the coach starts every learner here and doesn't unlock System Design as a *focus* until
the DSA foundation is largely retired (see §6). Reaching beyond the NC150 is encouraged from
day one; *replacing* it is not — it's the load-bearing base the rest of the mastery ladder
rests on.

## 2. The comfort system (honest spaced repetition)

After every rep you answer one question: **Clean, Shaky, or Blank?**

| Comfort | Meaning | Next review |
|---------|---------|-------------|
| 🟢 **Clean** | Solved from a blank page, correct complexity, **no hints** | +30d (then +60, then retire) |
| 🟡 **Shaky** | Needed a nudge, peeked, or weren't confident | +10d (streak resets) |
| 🔴 **Blank** | Couldn't recall; looked it up | +2d (streak resets) |

Three Cleans in a row → 🏆 **Retired** (spot-checked every ~180 days). The bar is
strict on purpose: honest grading is what makes the intervals mean anything.
**Coding is required for Clean** — a no-code blueprint caps at Shaky.

## 3. Phase completion = mastery, not exposure

A phase is done only when **every** associated problem (learning + pulled backlog)
is 🏆 Retired — not when each has been attempted once. Progress is measured in
"retired," not "seen."

## 4. Whiteboard fidelity

You write the full solution from scratch every time, including any
`ListNode`/`TreeNode` definitions — no shared boilerplate library. Re-deriving the
scaffolding is part of the rep, exactly like an interview whiteboard. The coach
sets up an empty dated skeleton; it never writes solution logic.

## 5. Application: pull, not push

Company lists and backlog pools are **reference pools, not checklists**. You *pull*
a problem gated by patterns you've already learned. A 🟡/🔴 pull is a diagnostic
pointing at a pattern to refresh — never a cue to learn something ad-hoc. Your
knowledge drives selection; nothing external dictates the curriculum.

## 6. Two pillars, one engine

DSA and System Design share the same comfort scale, the same interval engine, and
the same schedule. They differ in the *unit*, the *rep*, and who owns the studying:

| Pillar | Unit | Rep | Graded by |
|--------|------|-----|-----------|
| DSA | a problem | code it from scratch | re-solve from a blank page |
| System Design | a design question | **you study externally; the coach mock-interviews you** | a cold ~45-min mock, scored on a 7-point rubric |

**The System Design split.** A repo can't be both a textbook and a scoreboard — the
textbook half is open-ended and never finishes, and it competes for the slots that
grade you. So learning system design is *your* half (do it on your own time, with
whatever resource you like), and the coach keeps the two jobs it does better than any
website: **measuring you over time**, and **the adversarial half you can't do alone** —
cold mocks, sustained pushback, scoring, and naming exactly what to study next.

System Design unlocks on readiness: the coach starts running scored mocks once your
DSA foundation is largely retired. You choose the priority; the coach advises when
you're reaching ahead of your foundation.

## 7. Backlog recovery

If overdue reviews pile up (>5 overdue, or any 7+ days overdue), new intake pauses
and warmup sessions double until the backlog clears. Maintenance beats acquisition
when you're behind — a forgotten pattern is worth more to refresh than a new one is
to add.

---

*The direction of causation always runs from your knowledge outward: what you know
drives what you pull and how far you reach — never the reverse.*
