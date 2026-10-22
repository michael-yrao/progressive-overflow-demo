# cse-coach

**A spaced-repetition coach for technical mastery — DSA and System Design.**
You don't fill out a tracker. You *talk to your coach*, and it handles
the scheduling, the spaced repetition, and keeping you honest — so you just show
up and do the reps.

---

## The one thing to understand first

**This repo is a coach, not a spreadsheet.** You work with it through
conversation, the same way you'd work with a real mentor sitting next to you:

- You tell it when you're **starting** a problem. It sets up your file — with the
  problem statement and a link already filled in, so you never paste anything.
- You ask it questions while you work. It won't hand you the answer — that's the point.
- When you're done, it reads how the attempt went and **proposes a grade** (🟢/🟡/🔴)
  for you to confirm or correct — then logs it and schedules your next review.

You never manually edit the tracker, compute review dates, or plan your week.
**Your only job is to do the reps and answer one question honestly: "Clean,
Shaky, or Blank?"** The coach does the rest.

Open the repo in Claude Code and just talk to it in plain language. There are no
commands to memorize.

---

## Getting started (about 2 minutes)

Sign in with GitHub at progressiveoverflow.com/start and choose DSA. The site creates `<you>/cse-progress` from this template, asks four questions, and builds your first week. Everything after that (practice, ratings, reviews, next week) happens on the site; nothing to install. While this repo is private, that works for collaborators only.

Prefer the chat coach? Clone your copy, open it in Claude Code, and say "set me up".

1. Click **Use this template** on GitHub → clone your copy.
2. Open it in [Claude Code](https://claude.com/claude-code).
3. Say **"set me up"** (or run `/cse-init`). Your coach asks a handful of
   questions all at once — your name, start date, what you're aiming for, your
   language, and which pillar to start
   with. Answer them in one pass.
4. That's it. It builds your roadmap, your first week's schedule, and installs a
   git hook that keeps your review dates current automatically.

> **No git setup on you.** Setup initializes the repo (if needed) and wires up the
> commit hook that keeps your review dates current — you never run a git command
> for it. Invoking setup is the only step.

---

## How you actually use it, day to day

**Start with "start today."** That one phrase kicks off your day: your coach
checks what's due, sets up the solution files for anything you're coding today,
and lays out your plan. (Memory-only reps — quick warmups and blind sprints — get
*no* file on purpose; reproducing the structure from memory is the exercise.)

```
You:   Start today.
Coach: Morning. 3 things today, you're under your cap of 5:
       • Warmup — Contains Duplicate (blueprint, no code needed)
       • Active block — Two Sum (new) → file's ready at 1_two_sum.py
       • Sunday's coming: I'll run you a System Design mock
       Which do you want first?
```

From there it's a conversation. Here's a real one:

```
You:   Starting Two Sum.
Coach: Nice — set up dsa/leetcode/arrays_and_hash/1_two_sum.py with the problem
       statement, a link, and today's attempt banner. It's yours to write. Go.

You:   Can the array have duplicate values?
Coach: Yep, it can. (Ask me anything about the problem — I'll clarify freely.
       I just won't hand you the approach unless you're truly stuck.)

You:   Done.
Coach: That read as 🟢 Clean — blank page, right complexity, no hints from me.
       Confirm, or would you call it Shaky?

You:   Clean.
Coach: Logged 🟢 Clean. I'll bring it back in ~30 days and I've already put it
       on your schedule for Aug 12. Next up whenever you're ready: Valid Anagram.
```

Three moves, every problem:

| You say… | The coach does… |
|----------|-----------------|
| "Starting `<problem>`" | Sets up a dated solution file with the problem statement + link filled in (LeetCode, or NeetCode if it's premium) — you write every line of the solution |
| (ask clarifying questions) | Answers freely; **won't spoil** the approach unless you're stuck or ask outright |
| "Clean / Shaky / Blank" | Grades honestly, logs it, computes your next review, and schedules it — proactively |

**Be honest with the grade.** 🟢 Clean means you wrote it from a blank page,
correct complexity, no peeking. If you glanced at a hint or weren't sure of the
data structure, that's 🟡 Shaky — and the coach will hold that line even if you're
tempted to round up. That honesty is what makes the spaced repetition actually work.

---

## What the coach is doing for you in the background

- **Spaced repetition** — Clean pushes a problem ~30 days out, Shaky ~10, Blank
  ~2. Three cleans in a row and it *retires* (spot-checked every ~6 months).
- **Scheduling** — it fills your weekly schedule, protects your main practice
  block, caps your day so you don't burn out, and re-slots anything you defer.
- **Keeping you honest** — strict Clean bar; coding required for Clean; it writes
  the scaffold but never the solution.
- **Reaching past your target** — whatever you're aiming for, it trains you one
  level beyond it, because that's how you clear the target with room to spare.
- **Starting System Design at the right time** — it starts you on DSA and tells you
  when you're ready for the coach to begin running scored System Design mock
  interviews. You can lead with whatever you want; it'll just tell you honestly if
  you're reaching ahead of your foundation.

---

## The two pillars

| Pillar | You practice by… | Graded by… |
|--------|------------------|------------|
| **DSA** | coding the solution from scratch | re-solving from a blank page |
| **System Design** | studying on your own, then getting **mock-interviewed** | a cold ~45-min mock, scored on a 7-point rubric |

Both run on the same coach, the same Clean/Shaky/Blank scale, and the same schedule. DSA
is the weekday focus. **System Design works differently: you study it on your own time
(HelloInterview, Grokking, DDIA — your choice), and the coach's job is to interview you
on it.** Once you're ready, it runs a cold mock each week — one design question, ~45
minutes, full pushback — then scores it and tells you exactly what to go study before the
next one. A shorter midweek "deep-dive" round drills the follow-ups you couldn't defend.
See `cse.config.example.yml` (`system_design.cadence`).

---

## See your progress

Every rep you log emits an honest-progress dashboard at
**`progressiveoverflow.com/progress?repo=<owner>/<name>`** — the pre-commit hook keeps it
current automatically. It works once your repo is **public**; while it's private, the link
just won't resolve for anyone but you.

`dashboard/showcase.yml` and `dashboard/bigo.yml` ship empty: until you add entries,
`export_showcase.py` and `export_bigo.py` write nothing and the site shows the author's
showcase and Big-O deck instead of yours.

**Published:** aggregate stats (streak, reps), the maturation pipeline (🔴→🟡→🟢→🎓→🏆) and
trophy case, technique-breadth coverage, and per-problem status with its comfort timeline —
plus deep links back to the problem.

**Never published:** your stuck-log prose, and your solution code unless you add entries to
`dashboard/showcase.yml` or `dashboard/bigo.yml`, which publish exactly the slices you choose. The
contract (`dashboard/progress.schema.json`) is curated and non-sensitive by design — see
`.claude/skills/cse-coach/references/motivation.md` for the full rule.

Want a badge here too? It's opt-in: `scripts/gamify.py`'s `update_readme_badge()` looks for a
named pair of HTML-comment markers anywhere in this file, and only writes a one-line summary
between them if it finds both — see that function's docstring for the exact marker text to add.
No markers, no badge; nothing here activates it by default.

The site also renders a **technique cheat sheet** at `progressiveoverflow.com/learn`, generated
from `docs/foundations/dsa/patterns/techniques/` by `python scripts/build_cheatsheets.py`
(contract: `dashboard/cheat-sheets.schema.json`) — run deliberately rather than on every commit
by the hook; `scripts/check_cheatsheets.py --check` guards the docs themselves in pre-commit.

---

## Staying up to date

Your repo is **yours** — your trackers, your schedules, your solutions. But the
*engine* behind it (the scheduling scripts, the coaching rules, the curriculum)
keeps improving here. Because "Use this template" deliberately cuts the git
connection to this repo, there's no `git pull` that could bring those over. So
there's a command that does it properly:

```sh
python scripts/update_coach.py --dry-run   # what would change?
python scripts/update_coach.py             # bring it in
```

**You won't usually type either of those.** Your coach checks at the start of each
session and mentions it in one line if something's waiting — you just say yes.

### Will it overwrite my stuff?

No. It compares three versions of every engine file — what you have, what's new
upstream, and what you had *at your last update* — and that third one is what lets
it tell "you customized this" apart from "you're just behind":

| | What happens |
|---|---|
| A file you never touched | quietly updated |
| A file **you edited**, unchanged upstream | **yours wins** — untouched |
| A file **you edited** that *also* changed upstream | **nothing is written.** It's reported, with a diff saved in `.coach-sync/conflicts/`, and your coach will walk you through it |
| Your trackers, schedules, solutions, `cse.config.yml` | **never even looked at** |

That last row is structural, not a promise: those paths aren't in the sync manifest,
so no code path in the updater can write to them.

---

## The philosophy (why it's built this way)

The goal isn't to pass an interview — it's genuine mastery, with the interview as
a milestone you clear on the way past it. Everything is organized around one idea:
**reach beyond the target so you always hit it.** For the full rationale — the
Interview-ROI line, the comfort system, backlog recovery — see
[`docs/PHILOSOPHY.md`](docs/PHILOSOPHY.md).

---

## Requirements

- Python 3.9+ (for the scheduling script)
- Git (the pre-commit hook auto-updates your review dates)
- [Claude Code](https://claude.com/claude-code) (recommended) — this is how you talk
  to your coach. Other agents (GitHub Copilot, caveman) also work via
  [`AGENTS.md`](AGENTS.md) as a lower-credit option; Claude Code gives the fullest
  experience.
