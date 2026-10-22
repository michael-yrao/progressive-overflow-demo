# System Design — Mock Interview Progress

<!--
Notes for the coach / future agents:
- This is the System Design spaced-repetition tracker, the sibling of dsa_progress.md.
  SAME 7-column format, SAME interval math, driven by the SAME script:
      python scripts/update_review_dates.py --tracker \
             docs/foundations/system_design/mastery/design_progress.md
  The pre-commit hook recomputes + re-sorts this file when it is staged. There is NO
  source-file discovery here — rows are added by hand as you run mocks.
- THE MODEL IS MOCK INTERVIEWS (not study lanes). The learner studies system design on
  their OWN, off the schedule; the coach's job is running COLD mock interviews on that
  material and scoring them on the 7-point rubric in ../study_guide.md.
- THE ROW IS A MOCK. One question = one row = one ~45-min cold mock = one rating.
  A question is 🔴/blank and inert (no review load) until its first mock runs.
- Column reuse (the parser requires the literal DSA headers):
    * "Difficulty" → "Design (Easy|Med|Hard)", the design's own interview tier.
    * "Problem"    → the design question, plus a "· debrief" link to
                     ../mocks/<date>_<slug>.md once a mock has run.
- Rating is the 7-point rubric in ../study_guide.md, scored right after the mock:
    * 🟢 Clean  — skeleton (#1–4) solid AND #5 forks, #6 failure modes, #7 evolve/operate
                  all pass, driven cold.        → the standard engine ladder (+30/+60/🎓)
    * 🟡 Shaky  — skeleton (#1–4) solid, #5–#7 shaky.                → short interval, streak → 0
    * 🔴 Blank  — couldn't drive the framework cold.                 → shortest interval, streak → 0
- To log a mock: write the debrief to ../mocks/, set Comfort, add today's date to Rep
  Dates + Latest Rep Date, then stage this file and commit (or run the script).
- Retire at streak 3 (🏆), spot-check every 180 days — same as DSA.
- Replace the example row once you log your first mock. Seed the rest of your board from
  the design questions in ../../../../curriculum/system_design/tier1_interview_core.yml
  (or a source of your choice) — a row costs nothing at 🔴 until its first mock runs.
-->

> **Auto-refresh note:** regenerated when this file is staged for commit, or when
> `python scripts/update_review_dates.py --tracker docs/foundations/system_design/mastery/design_progress.md` runs.

| Difficulty | Problem | Comfort | Streak | Next Review Date | Latest Rep Date | Rep Dates |
|---|---|---|---|---|---|---|
| Design (Easy) | URL Shortener | 🔴 | 0 |  |  |  |
