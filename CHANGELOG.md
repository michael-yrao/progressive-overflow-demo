# Changelog

## v0.12.1 — 2026-10-26

- The saved complexity "why" text per bound now allows up to 2000 characters (was 500).

## v0.12.0 — 2026-10-22

- The DSA technique catalogue now ships as `curriculum/dsa/techniques.yml`, and `neetcode.yml` as
  `curriculum/dsa/neetcode.yml`. Both are engine-owned and arrive through the normal sync.
- `docs/foundations/dsa/mastery/techniques.yml` stays yours, as an overlay on the catalogue.
- `scripts/update_coach.py` gains a repeatable `--only GLOB` to sync a subset of paths.
- `totals.solutions` is dropped from `dashboard/progress.json` and its schema.

### Migration for existing learners

- After syncing, `curriculum/dsa/techniques.yml` arrives.
- Your old `docs/foundations/dsa/mastery/techniques.yml` is now an overlay and keeps working,
  because the merge is additive.
- To clean it up, delete every entry and key the catalogue already carries, and keep only
  `queued` / `planned` / `review`, variant `queued`, your custom (9001+) specs and any technique
  of your own.
- A stale entry, such as the old single `Binary Search` (now split into exact match / min boundary /
  max boundary), otherwise shows up as an extra learner-local technique.
