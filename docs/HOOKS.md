# Agent hooks (optional, one paste per machine)

Seven Claude Code hooks ship in [`.claude/hooks/`](../.claude/hooks/). The scripts are
committed and travel with the repo; **their wiring does not**, because it lives in
`.claude/settings.json`, which is gitignored. So this is a one-time paste per machine,
per clone.

All seven cost nothing until they fire, and none is load-bearing. The behavior each one
guards is also enforced in the scripts and the skill. They are a backstop, not the
mechanism.

## The block

Merge into `.claude/settings.json` (create it if absent):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command",
            "command": "python \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/kickoff_scaffold_reminder.py\"",
            "timeout": 10 }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash|PowerShell",
        "hooks": [
          { "type": "command",
            "command": "if command -v python3 >/dev/null 2>&1; then python3 \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/commit_push_gate.py\"; else python \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/commit_push_gate.py\"; fi",
            "timeout": 10 }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash|PowerShell",
        "hooks": [
          { "type": "command",
            "command": "python \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/scaffold_links_reminder.py\"",
            "timeout": 10 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command",
            "command": "python \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/problem_link_reminder.py\"",
            "timeout": 10 },
          { "type": "command",
            "command": "python \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/rating_gate.py\"",
            "timeout": 10 },
          { "type": "command",
            "command": "python \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/grounded_claims.py\"",
            "timeout": 10 }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          { "type": "command",
            "command": "python \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/session_start_memory.py\"",
            "timeout": 10 }
        ]
      }
    ]
  }
}
```

One section per hook, grouped by the event that fires it.

## `kickoff_scaffold_reminder.py` — scaffold the whole board at a kickoff

`UserPromptSubmit`. Fires when the learner's prompt reads as a session kickoff, such as
"let's do our sunday session" or "/start-day". Reminds the agent to scaffold every
problem on today's schedule before presenting the board, not just the first one. Stays
silent on a named problem, a plain question, or a close-out phrase like "wrap up and
commit" — those are not a kickoff. Warn-only: it injects context and never blocks. Added
because the rule lived only in an opt-in skill reference and lapsed on back-to-back days
(2026-09-12, 2026-09-13) before a hot-tier fix held.

A second trigger covers the **scoped start**: a prompt that is neither a close-out nor a
kickoff but puts a do-verb next to a problem number ("doing 332", "let's do 417 and 543",
"235 next") injects a short reminder carrying the session date from
`scripts/session_date.py`, so the pull is reseated onto the script's date and the problem is
scaffolded in the same turn.

## `scaffold_links_reminder.py` — links after a scaffold

`PostToolUse`, matched to `Bash|PowerShell`.

Fires on a shell command that actually **invokes** `new_problem.py` (matched as
`new_problem.py … --number`, since `--number` is required by the script's argparse) and
reminds the agent to emit both the local file link and the problem-page link for every
problem it just scaffolded.

⚠️ **This hook is the backup, not the enforcement.** `new_problem.py` prints the links
itself (`report_links()`), so they arrive as tool output on every machine whether or not
you ever pasted the block above.

That split is the whole lesson, and it is worth more than the hook. The rule lapsed five
times as prose, so it was promoted to this hook — and then lapsed a **sixth** time,
because the matcher read `"Bash"` alone and the scaffold happened to run through the
PowerShell tool. It failed *silently*, and its wiring was gitignored on top of that.

> **The intervention ladder: source fix > hook > workflow step > written rule.**
> A hook that depends on a tool matcher plus a per-machine config has two ways to not
> exist at the moment it is needed. A script that prints the thing has none.

The hook still earns its place: it covers what the script cannot reach — mid-session
hand-overs and lineup tables, where no scaffold runs at all.

⚠️ The trigger was a bare `new_problem.py` substring at first, which also matched `grep`s
and read-only commands that merely *mentioned* the script. It was tightened because **a
hook that cries wolf trains the agent to skim past it**, which costs exactly the
reliability that made it worth promoting from prose in the first place.

## `problem_link_reminder.py` — the turn-shape detectors

`Stop`. Bundles four conservative detectors over the assistant's last turn: a solution-file
link whose path does not resolve from the repo root; a lineup table that carries more than
name and links (a spoiler column); a short closing nudge that pushes the learner to the next
rep ("Code it.", "ready for the next one?"); and a throat-clearing paragraph opener
("Careful —", "So:"). The hook blocks at most once per turn — it checks the detectors in
order and the first match blocks. Every rule here first lapsed as prose multiple times before
earning a hook, per the intervention ladder (source fix > hook > workflow step > written rule).
The bare-problem-number link check was removed at the learner's request: it read moved-out
schedule rows as today's board and matched non-problem numbers, so the number-needs-a-link
rule is now prose-only (boards come from `remaining.py` / `links.py`).

## `commit_push_gate.py` — commit and push are two commands

`PreToolUse`, matched to `Bash|PowerShell`. Denies one command that chains `git commit` and
`git push` (`;`, `&&`, `||`, a pipe or a newline between them). The pre-commit hook's output
has to be read between the two: an `ERROR:` line from a report-only check holds the push, and a
chained command never shows it. A lone commit, a lone push, and prose that merely names the
subcommands (a commit message containing "push") pass. The deny is `permissionDecision: "deny"`
on stdout with exit code 2. It is session-scoped: it also blocks a chained commit+push aimed at
another repo from a session opened here.

## `rating_gate.py` — complexity before the rating

`Stop`. Blocks a turn that proposes a comfort rating (green/yellow/red) before the
learner has stated both time and space complexity, each with its own keyword or proxy, in
their recent messages. It reads the learner's own words, not a checklist the agent could
tick falsely. It fires only on a genuine decision request ("Rate it?", "Confirm?"), so an
ordinary mention of the comfort scale, a session recap, or a dashboard/deploy report
carrying the same glyphs stays silent. Whether the stated complexity is correct is out of
scope for this hook — that is the coach's judgement call, not a mechanizable check.

## `grounded_claims.py` — no claim without a tool result

`Stop`. Blocks a turn whose text states a repo-artifact edit as already done, such as
"Logged the entry" or "I've updated the schedule row", with no matching tool call in that
same turn. `committed` needs a Bash/PowerShell command containing `git commit`; `pushed`
needs `git push`; every other claim verb needs a Write/Edit/MultiEdit/NotebookEdit, an
Agent/Task delegation, or a Bash/PowerShell command. A Bash/PowerShell command counts only
when it is not read-only: a plain `grep`/`cat`/`git status` read contributes nothing,
while a write, a mutating script, or an unrecognized command shape does. It never fires on
a question, a blockquote, fenced code, a table row, future/intent phrasing, a negation,
the learner as the sentence's subject, or a bare link. It is deliberately careful around
this repo's own vocabulary: `O(log n)` is not an artifact "log". A passive teaching
sentence like "dp[i] is updated from the previous row of the table" has no first-person or
sentence-initial verb, so it never matches.

## `session_start_memory.py` — load the memory index unprompted

`SessionStart`.

Injects `.claude/memory/MEMORY.md` plus a short list of always-on gates at session start.

The skill already says "read MEMORY.md at the start of each session," but that is a rule
about *starting a session*, and a session that opens with a direct technical question
("what's wrong with my code here") does not feel like a start. **The skill is always
injected; `.claude/memory/*.md` are opt-in reads** — so a rule that must fire unprompted
cannot live only in memory. This hook removes the choice.

The gate list is restated as **if/then triggers, not topics**, deliberately: the failure
it was written for happened while the index line for that very rule was present and
correct. What was missing was never the content — it was the binding to a *moment*.

Keep the list short. It is injected every session, so every line costs tokens forever.

It also prepends one-line banners when they apply: an overdue self-eval meta-review, a DSA
mock coming due (`dsa_mock.every_days`, `dsa_mock.first_due` in `cse.config.yml`), the study
streak from `dashboard/progress.json`, a Pattern Sense result waiting to be ingested, and a
completed site rep waiting in `dsa/attempts/`. Each banner is fail-soft: with no config, no
`dashboard/` and no `dsa/` (a fresh template checkout) every one returns an empty string.
