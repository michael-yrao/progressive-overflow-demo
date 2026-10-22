# System Design Study Guide — the mock-interview model

> This guide is the SD *mechanics*: how a mock runs, how it is scored, what gets written
> down. The *what to study* map (the Interview-ROI line and its tiers) is below it.

## The split — study is yours, the interview is mine

**The learner studies system design; the coach runs mock interviews on it.**

| | Owner |
|---|---|
| **Learning system design** — concepts, technologies, patterns, worked breakdowns | **the learner**, on their own time, off the schedule, via a resource of their choice (HelloInterview, Grokking, *Designing Data-Intensive Applications*, …) |
| **Interviewing you on it** — cold mocks, sustained pushback, scoring, what to fix next | **the coach**, in the SD slot |

**Why this model.** A repo cannot be both a textbook and a scoreboard — the textbook half is
open-ended work with no exit condition, and it competes for the same slots as the thing that
actually gets graded. Finished textbooks already exist. This repo keeps the two jobs it does
better than any website: **measurement over time**, and **the adversarial half you cannot do
alone.** Nothing on the schedule is ever "read about X" — if a mock shows you don't know
sharding, the fix is your own study time on sharding, not a scheduled slot.

## How a mock runs

**One question = one row = one ~45-min cold mock = one rating.** ([`mastery/design_progress.md`](mastery/design_progress.md))

1. The coach names the next question off the board and starts a cold ~45-min mock. No reading,
   no prep, no notes — cold is the whole point.
2. The learner drives the framework; the coach plays the interviewer: clarifying answers when
   asked, then sustained pushback (see the probe bank below).
3. ~15-min debrief written to [`mocks/`](mocks/) `<date>_<slug>.md` from
   [`templates/mock_debrief_template.md`](templates/mock_debrief_template.md): the rubric score,
   where it broke, the open probes to fire next time, and what to go study.
4. Score on the rubric, set the Comfort in the tracker, let the interval engine schedule the
   re-mock.

> **⚠️ One mock is one sitting.** A design spread over several sessions cannot be rated — the
> second sitting is no longer cold — and an unratable rep never enters the interval engine at
> all (it silently leaves the tracker while looking like progress). If a mock overruns, finish
> at HLD depth and **rate what happened**; push the untouched deep dives to a *separate* row.

## The rubric — 7 points, scored cold

The interview framework, as seven scored checkpoints. #1–4 are the **skeleton**; #5–7 are what
separates "correct" from "senior."

| # | Checkpoint | Passes when… |
|---|-----------|--------------|
| 1 | **Requirements** | functional + non-functional scoped; the *non-functional* ones (scale, latency, consistency) are named, not just the features |
| 2 | **Estimation** | back-of-envelope QPS / storage / bandwidth, with the numbers driving later choices |
| 3 | **API design** | the core endpoints, right shape, right granularity |
| 4 | **Data model + high-level design** | entities + the boxes-and-arrows request flow — HLD altitude, not storage internals |
| 5 | **Deep dives & the forks** | each major fork defended: *trigger → choice → one-line why → where it breaks at 10×* |
| 6 | **Failure modes & bottlenecks** | SPOFs named, races handled (idempotency/locking), which piece saturates first + the fix |
| 7 | **Evolve / operate / scale** | rollout & migration, observability, behavior at 10× / 100× |

**Score → Comfort (feeds the same interval engine as DSA):**

| Comfort | Meaning | Interval |
|---|---|---|
| 🟢 **Clean** | skeleton (#1–4) solid AND #5 forks, #6 failure modes, #7 evolve/operate all pass, driven cold | the standard clean ladder |
| 🟡 **Shaky** | skeleton (#1–4) solid, #5–7 shaky | short interval, streak → 0 |
| 🔴 **Blank** | couldn't drive the framework cold | shortest interval, streak → 0 |

(Exact intervals are `cse.config.yml` `intervals`, identical to DSA — the engine computes them.)

**Depth — a high ceiling, a senior bar.** The pushback ceiling is high *on purpose*: the
interviewer keeps pushing until the answer runs out — that is how the edge of what you know gets
found. But the **bar** a checkpoint must clear to pass is junior/senior level; exceptional
(staff+) depth is not expected and does not gate a 🟢. A probe going past the bar and hitting
"I don't know" is the ceiling doing its job — it names the next study target, it doesn't fail
the mock.

## Cadence

Set by `cse.config.yml` `system_design.cadence`.

| Cadence | Slots |
|---|---|
| `mock_plus_deep_dive` | **the default** — a Sunday cold mock + a conditional midweek **deep-dive round** (SD is off-board and **unpriced** — it takes the evening, not the DSA effort ceiling) |
| `mock_only` | Sunday cold mock only |
| `paused` | no SD slot scheduled — "study mode," while the learner builds their own foundation; mocks start when they say so |

- **The Sunday mock** is the rated rep: one cold question, full framework, debrief.
- **The midweek deep-dive round** is ~25 min of pushback on a design *already* mocked, drawn from
  that debrief's open-probe bank (rubric #5–#7, no framework walk — cheaper, hence its lower
  price). It is **conditional**: it does not exist until a probe bank has something in it, and
  when the bank is empty the slot returns to DSA warmups. The deep-dive is a **warmup swap** — it
  never cuts the 45-min DSA active block.

**In `paused`/study mode, don't nudge.** Asking "ready for a mock yet?" every week converts a
learner-owned gate into a coach-owned one. Mocks begin when the learner opens one.

## The probe bank — the questions a mock fires

Every mock's pushback is drawn from these. Rehearse defending each cold; a shaky answer points at
a fork you memorized instead of understood.

- "What happens when this component dies / the DB falls over?" (single points of failure)
- "How does this behave at 10×? 100×?" (which piece saturates first, and your fix)
- "Two users do X at the same instant — what happens?" (race conditions, idempotency)
- "Why *this* database / queue / cache and not the alternative?" (defend the fork)
- "Where's the bottleneck, and how would you shard / cache / replicate around it?"
- "How do you keep these two copies in sync? What if they diverge?" (consistency)
- "How would you roll this out / migrate with zero downtime?" (real-world ops)

**The recurring forks (memorize the deciding question, not the answer):**

| Fork | Deciding question | Picks A ⟶ / ⟵ Picks B |
|------|-------------------|------------------------|
| SQL ⟷ NoSQL | Multi-row transactions / joins, or scale-out + flexible schema? | ACID & relations ⟶ SQL / massive scale, simple access ⟶ NoSQL |
| Strong ⟷ eventual consistency | Is a stale read *incorrect*, or just slightly old? | money/inventory ⟶ strong / feeds, counts ⟶ eventual |
| Sync ⟷ async (queue) | Must the caller wait, or can work be deferred? | needs the answer now ⟶ sync / fire-and-forget, spikes ⟶ async |
| Cache-aside ⟷ write-through | Read latency or write freshness the priority? | read-heavy ⟶ aside / can't serve stale ⟶ write-through |
| Replication ⟷ sharding | Read-bound (scale reads) or write/storage-bound (scale capacity)? | too many reads ⟶ replicas / too much data/writes ⟶ shards |
| Push ⟷ pull (fan-out) | Few writers→many readers, or many writers→few readers? | celebrity read fan-out ⟶ pull / normal ⟶ push-on-write |

## When a mock comes back 🔴 — teach, don't re-mock

**A mock measures; it does not teach.** A 🔴 has two causes and they need opposite responses:
*decayed* (you knew it, it faded) → the normal +2d loop. ***Never encoded*** (there was nothing
to forget) → **the learner studies it** (their half of the split), *then* re-mock. Re-mocking an
unlearned design just re-blanks it.

If the coach does teach in the moment, keep it to the **spine** (the 2–3 load-bearing facts) and
prefer formats where the learner produces: derive-the-design (give the constraint, let them invent
the mechanism, then name it) → failure-mode drill → Socratic pushback → explanation (last resort).
**A teaching session is UNRATED**, and the rated re-mock moves out far enough that forgetting is
possible — rating a mock the day after you were taught measures the *conversation*, not retention.

## Reference cards — off the review engine

Studying is the learner's own half, so notes are **not** review reps and carry no comfort, streak,
or review date. When a mock exposes a gap, write a reference card so the next debrief can point at
it:

- One **building block** → [`templates/component_template.md`](templates/component_template.md) → save under `components/`.
- One **quantitative concept** (percentiles, Little's Law, quorum math, Zipf, Bloom) →
  [`templates/concept_template.md`](templates/concept_template.md) → save under `concepts/`. These
  are the numeric foundations a "quantify every claim" push runs on mid-mock; front-load the ones
  no design reliably triggers.
- A **worked design** you want to keep → [`templates/case_study_template.md`](templates/case_study_template.md) → save under `case_studies/`.

These are remediation reference, filled *because a mock hit a gap* — not a queue to grind through.

---

## The map — what to study (Interview-ROI line)

**End goal:** become a genuine systems architect. **Passing the interview is a milestone on that
path, not the finish line.** Depth has diminishing returns *for interviews specifically*, so the
material sorts around one marker:

> **The Interview-ROI Line** — past which added systems depth stops improving interview
> performance and becomes real-world architect mastery.

**Above the line — Interview Core (Tier 1). Study this first; it's the whole SD-interview surface.**

1. **Fundamentals & estimation** — latency numbers, back-of-envelope math (QPS, storage, bandwidth), vertical vs horizontal scaling.
2. **Building blocks** — load balancing, caching (patterns, eviction, invalidation), CDN, reverse proxy / API gateway, message queues & async, rate limiting, consistent hashing, bloom filters.
3. **Data layer** — SQL vs NoSQL, indexing, replication (leader/follower, multi-leader), sharding / partitioning, CAP & PACELC, consistency levels, idempotency.
4. **The interview framework** — requirements → estimation → API design → data model → high-level diagram → deep dives → bottlenecks & tradeoffs. *Driving this fluently is ~half the score* (it's the whole rubric skeleton).
5. **Quantitative foundations** — percentiles & tail latency, Little's Law, utilization & queueing, Zipfian skew, probabilistic sketches (HLL, Count-Min), quorum math (R+W>N). Needed *mid-sentence* to justify a number; a `concepts/` card each.

**=== INTERVIEW-ROI LINE ===**

**Below the line — Architect Depth (Tier 2). High real-world ROI, low interview ROI. Long-form reading, not mock prep.**

6. **Designing Data-Intensive Applications (Kleppmann)** — the on-ramp from interview-competent to real understanding.
7. **Consensus internals** — Raft, Paxos / Multi-Paxos, ZAB.
8. **Distributed transactions** — 2PC / 3PC, Sagas, Percolator, Calvin.
9. **Consistency theory** — linearizable vs sequential vs causal vs eventual; CRDTs.
10. **Storage engines** — LSM-tree vs B-tree, WAL, compaction, MVCC.
11. **Stream processing** — exactly-once semantics, watermarks, backpressure.
12. **Foundational papers** — GFS, MapReduce, Bigtable, Dynamo, Spanner, Chubby, ZooKeeper, Kafka, Cassandra, Raft, F1.

**Tier 3 — research / specialization horizon (near-zero interview ROI):** formal methods (TLA+), MIT 6.824, consensus variants, advanced consistency (Bayou, COPS), chaos engineering, hardware-aware design, planet-scale coordination (TrueTime, HLCs).

**How to use the line:** ask *"which side is this on, and am I optimizing for the interview or for
real mastery right now?"* Finish Tier 1 before crossing. The mock board (`tier1_interview_core.yml`)
is drawn from above the line; below-the-line work is deliberate reading on its own track, not a mock.
