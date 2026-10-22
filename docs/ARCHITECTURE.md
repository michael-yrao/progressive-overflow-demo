# Architecture — the rule system as a tiered context-memory hierarchy

> A structural explainer of *how* this repo's coaching rules are organized, and *where* a new rule
> belongs. It names keys and files, never tuned values (so it stays single-source-clean), and states no
> per-moment rule (so it is deliberately **outside** `reconcile.py` / `check_single_source.py` scope — it
> explains stable structure, not the model). If the tiers themselves change, update it here.

## The problem it solves

An agent's context is a scarce, **always-injected budget**: anything in `CLAUDE.md` is re-sent every turn,
forever. But a rule is only useful if it fires **at the moment it applies**. Put every rule in the
always-injected file and you bloat every turn and bury the load-bearing sentences (the 898-line / 70KB
CLAUDE.md that motivated this — now ~170 lines / 10KB). Put a must-fire rule in an opt-in file and it
silently doesn't fire. The design resolves this by **routing each rule to the tier whose (residency cost ×
firing reliability) matches how it must fire.**

## The four tiers

| Tier | Loaded | Cost | Fires reliably when… | Holds | Representative |
|---|---|---|---|---|---|
| **L1 — `CLAUDE.md`** | every turn (always resident) | high (paid every turn) | always | always-on gates + repo-maintenance meta-rules | the 8 gates, "two registers", single-source, decisions/reconcile, the token cap |
| **L2 — skill references** | on trigger (the skill's `description` matches a coaching moment) | paid only when loaded | a recognizable coaching moment occurs | operational coaching rules | `.claude/skills/cse-coach/references/{review-workflow,scaffolding,weekly-build,effort-budget,spaced-repetition,technique-coverage,system-design}.md` |
| **L3 — memory** | opt-in (the agent chooses to read it) | ~0 until read | the agent deliberately looks it up | the *why* / evidence / occurrence logs / standing project state | `.claude/memory/feedback_*.md`, `project_*.md` |
| **Interrupts — hooks** | out-of-band (harness event) | ~0 attention | a tool/event fires, regardless of what's loaded | mechanical enforcement that must not depend on recall | `rating_gate.py`, `problem_link_reminder.py`, `session_start_memory.py`, pre-commit checks |

## The routing rule — "which tier?"

Ask it for every new or changed rule, in this order:

1. **Must it fire *unprompted*, every session?** → **L1** (a CLAUDE.md gate) — or, better, a **hook** if a
   tool/event can carry it (a hook can't be skipped by recall).
2. **Does it fire at a *recognizable coaching moment*** (starting/reviewing a problem, scaffolding, the
   weekly build, a mock)? → **L2**, a skill reference — it loads exactly then, at zero cost otherwise.
3. **Is it the *why*, the evidence, a judgement call with no mechanizable trigger, or standing project
   state?** → **L3**, a memory file — which cross-links its operational home in L1/L2.

**The test:** *would a second competent agent reliably hit this rule when it matters, at an acceptable
standing cost?* If a rule keeps lapsing, it is in **too cold a tier** — promote it, don't reword it.

## The maintenance loop (log-structured compaction)

The system improves itself by moving knowledge *up-tier* as it proves recurring — the same shape as an
LSM-tree's write-ahead log + compaction:

- **`self_eval_log.md` = the write-ahead log** — every correction is appended immediately (cheap, unordered).
- **The meta-review = compaction** — periodically (fired by `session_start_memory.py`'s overdue banner)
  cluster the open entries; a root cause seen 2+ times gets **promoted up-tier** (memory → skill / CLAUDE.md
  / hook) and the cold, resolved entries are **archived** out of the hot log.
- **The intervention ladder = the promotion policy** — `source fix > hook > skill reference / CLAUDE.md step
  > memory file`, ranked by firing reliability (measured: source fixes held 4/4; memory paragraphs recurred
  7/9 — the coldest tier is the weakest fix).
- **`decisions.yml` + `reconcile.py` = staleness detection / GC** — a dated decision marks every rule file
  not yet re-read against it, forcing the re-examination that keeps tiers from rotting.

## A fifth artifact: the generated data contract

`dashboard/progress.schema.json` is not a rule at all — it is the schema for `progress.json`,
computed **from** the tiers above rather than governing them (`scripts/gamify.py` reads the
tracker, the schedules, and `cse.config.yml`'s `gamification:` block, and emits it; the
pre-commit hook keeps it current). It sits at the same source tier as the tracker itself: a
derived, published artifact that a viewer (progressiveoverflow.com) renders, never a place a
rule is authored or read back. It stays in scope here for one reason only — like `decisions.yml`
before it, an engine artifact is invisible to `coach_sync.py`'s sync until named in
`ENGINE_PATHS`, and that omission is exactly the failure this document exists to prevent.

`dashboard/cheat-sheets.schema.json` (from `scripts/build_cheatsheets.py`, reading the technique
docs + `techniques.yml`) is the second contract of this same kind.

## Credited patterns (it is a composite, not one GoF pattern)

- **Progressive disclosure** — L2's lean spine + on-demand reference files.
- **Single Source of Truth / DRY** — tuned values live only in `cse.config.yml`; prose points, never copies.
- **Policy / rules-as-code** — gates are executable hooks, not remembered prose.
- **Closed-loop feedback (Kaizen / control loop)** — the self-eval sense→log→cluster→promote→prevent cycle.
- **Temporal audit log** — dated decisions + `reconciled:` dates as the model's change history.

The value is the **composition**: a knowledge base sized to a context budget, where the cost of keeping a
rule resident is paid against the reliability with which it will fire.

## How to use it

When you add or fix a rule: **name its tier first** (§ routing rule). When you promote a lapse in the
meta-review: **make an edit to the target tier**, not another note in the coldest one. When something keeps
breaking despite being "written down clearly," the fix is almost never better prose — it is a colder rule
that needs to move to a hotter tier or become a hook.
