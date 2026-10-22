# 📐 Concept Name: [e.g., Little's Law]

> **Role:** [what kind of thing this is — e.g. "Capacity math", "Measurement foundation", "Replication tuning"] · **Family sibling:** [related concept card, if any]
> **You'll want this when:** [**THE TRIGGER — write this first.** Name the *symptom*, not the topic: *"you're asked how many servers and you only have QPS and latency"*, *"the interviewer just asked 'and p99?'"*. This line is what makes the card findable at the moment of confusion — and a concept card is far more often reached for mid-panic than read in advance.]
> **Drill:** answer the [Recall Card](#-recall-card-the-rep) cold, then unfold to check.

## 🦴 The spine — everything else derives from this
> **[One sentence. The single load-bearing idea. If they remember nothing else, this.]**

Three facts. Everything else on this page is a consequence of one of them.

| Fact | What you get | What it costs / means |
|---|---|---|
| [fact 1] | [the capability it buys] | [the price or the implication] |
| [fact 2] | | |
| [fact 3] | | |

## 🎯 In one line
[A single dense sentence a learner could say out loud in an interview — the definition plus why it matters, not just the definition.]

## 🧠 Core mechanics
[How it actually works. For a *formula*: state it, define every term, then show the intuition in 2–3 lines — never a proof first. For a *phenomenon*: the mechanism that produces it.]

**Make it concrete.** A tiny worked example with real numbers beats a paragraph of prose:
```
[e.g. 1,000 QPS × 50ms hold time → L = 1000 × 0.05 = 50 concurrent connections]
```

## 📊 The numbers worth memorizing
[A small table of the values you'd actually cite under pressure. Concepts live or die on having *a number* ready — this is the section that gets reread.]

| [Input] | [Result] |
|---|---|
| | |

## ⚠️ Gotchas (the misuses that get caught)
* **[Gotcha 1]** — [what people get wrong, and the correction]
* **[Gotcha 2]** — [especially: the boundary where this concept stops applying]
* **[Where you must NOT use this]** — [every concept has a domain; naming it is what separates understanding from recitation]

## 🌐 Design consequences (why an engineer cares)
* [What you'd actually *do differently* knowing this — a sizing decision, a threshold, a component choice]
* [Cross-link the other concepts and components this touches: `[Zipfian skew](zipfian_distribution.md)`, `[caching](../components/caching.md)`]

---

## 🃏 Recall Card (the rep)
*Answer each from memory before unfolding. Miss one → it's not 🟢.*

<details><summary><b>1. [State the core definition / formula, and define every term.]</b></summary>

[Answer. Keep it to the length you'd actually say out loud.]
</details>

<details><summary><b>2. [A "why does it work" question — the mechanism, not the recitation.]</b></summary>

[Answer]
</details>

<details><summary><b>3. [A numeric plug-in question — force an actual calculation.]</b></summary>

[Answer with the arithmetic shown]
</details>

<details><summary><b>4. [The gotcha as a question — "what breaks if…"]</b></summary>

[Answer]
</details>

<details><summary><b>5. [The boundary — "when must you NOT use this?"]</b></summary>

[Answer]
</details>

<details><summary><b>6. [A design-consequence question — "so what would you change?"]</b></summary>

[Answer]
</details>

<!--
Notes for whoever fills this in:
- 5–7 Recall Card questions is the working range. Fewer doesn't measure; more turns a
  quick self-check into a study session.
- Every question must be answerable COLD, out loud, without the page — this is your own
  self-check before a mock, not a scheduled rep. If a question only makes sense while
  looking at the note, it's a reading comprehension check, not a check of recall.
- Write the "You'll want this when" trigger FIRST and make it a symptom. That line is the
  entire reason this card gets found when it's needed.
- Keep the spine to three facts. A fourth is a sign the concept should be two cards.
-->
