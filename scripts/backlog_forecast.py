"""Forecast the review backlog per weekly intake rate (report-only model).

Replays the tracker day by day under the config's ladder, row cap and effort ceiling,
sampling each rep's outcome from the S->E tallies of the archived schedules.
Usage: python scripts/backlog_forecast.py [--weeks 26] [--seeds 40] [--intake N] [--check]
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
import re
import sys
from collections import Counter
from itertools import accumulate
from pathlib import Path

import _console

_console.force_utf8()

import effort_budget as eb
import schedule_priority
import session_date

TRACKER_STOP = "## ⏳"
SCHED_START = re.compile(r"🆕|🎯|🎤|🔴|🟡|🟢(?: s\d)?|🎓")
SCHED_END = re.compile(r"🟢|🟡|🔴")
BARE_GREEN, GREEN_S1, NEW_CLASS = "🟢", "🟢 s1", "🆕"
NO_DATA_CLASSES = ("🟢 s2", "🎓")
SUNDAY, DAYS_PER_WEEK = 6, 7
# Archives whose file stamp (YYYYMMDD) sorts before this are left out of the tallies. The
# default keeps every archive; raise it to drop weeks written under an older Start-glyph
# convention.
TALLY_FROM_STAMP = "00000000"
BACKLOG_WEEKS, UNPROVEN_WEEKS = (4, 8, 13, 26), (8, 26)
SLOPE_FROM_WEEK, SLOPE_TO_WEEK = 8, 26
DEFAULT_WEEKS, DEFAULT_SEEDS, MAX_REPORTED_INTAKE = 26, 40, 5
BRACKETS, OUTCOMES = ("pessimistic", "optimistic"), ("🟢", "🟡", "🔴")

def schedule_files() -> list[Path]:
    archive = sorted(p for p in eb.SCHEDULES.glob("archive/*_schedule.md") if p.name[:8] >= TALLY_FROM_STAMP)
    return archive + sorted(eb.SCHEDULES.glob("*_schedule.md"))

def tally_text(text: str) -> Counter:
    """S->E counts from one schedule's text; a legacy bare 🟢 Start counts as an s1."""
    tally: Counter = Counter()
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 5 or "▸" in cells[1]:
            continue
        start, end = SCHED_START.fullmatch(cells[2]), SCHED_END.fullmatch(cells[3])
        if start and end:
            tally[(GREEN_S1 if start[0] == BARE_GREEN else start[0], end[0])] += 1
    return tally

def load_tracker() -> list[dict]:
    """Active tracker rows (up to the waiting room); `due` is a date ordinal."""
    rows = []
    for line in eb.TRACKER.read_text(encoding="utf-8").splitlines():
        if line.startswith(TRACKER_STOP):
            break
        m = eb.ROW.match(line)
        if m:
            rows.append({"comfort": m["comfort"], "streak": int(m["streak"]), "diff": m["diff"],
                         "due": dt.date.fromisoformat(m["due"]).toordinal(),
                         "attempts": eb.attempt_count(m["reps"])})
    return rows

def load_ladder_and_forecast() -> tuple[dict, dict]:
    """(interval ladder, backlog_forecast block) from one read of the config; a missing key raises."""
    import yaml
    cfg = yaml.safe_load(eb.CONFIG.read_text(encoding="utf-8"))
    iv = cfg["intervals"]
    ladder = {**iv["clean"], "shaky": iv["shaky"], "blank": iv["blank"],
              "graduate_at": cfg.get("graduate_at_streak", cfg.get("retire_at_streak"))}
    return ladder, cfg["backlog_forecast"]

def ladder_step(comfort: str, streak: int, outcome: str, ladder: dict) -> tuple[str, int, int]:
    """(new comfort, new streak, days until next) after one rep with `outcome`."""
    if outcome == "🔴":
        return "🔴", 0, ladder["blank"]
    if outcome == "🟡":
        return "🟡", 0, ladder["shaky"]
    new_streak = streak + 1 if comfort in ("🟢", "🎓") else 0
    if new_streak >= ladder["graduate_at"]:
        return "🎓", new_streak, ladder["graduated"]
    tier = "provisional" if new_streak == 0 else "streak2" if new_streak == 2 else "streak1"
    return "🟢", new_streak, ladder[tier]

def make_sampler(tally: Counter, optimistic: bool, green_rate: float):
    """sampler(start_class, rng) -> outcome glyph; classes with no tally are bracketed
    (optimistic: `green_rate` 🟢, the rest 🟡; pessimistic: 🟢 s1-like)."""
    def dist(cls: str) -> list[tuple[str, float]]:
        counts = [tally[(cls, e)] for e in OUTCOMES]
        if not sum(counts):
            if optimistic:
                return [("🟢", green_rate), ("🟡", 1.0)]
            counts = [tally[(GREEN_S1, e)] for e in OUTCOMES]
        return list(zip(OUTCOMES, (c / sum(counts) for c in accumulate(counts))))
    table = {c: dist(c) for c in {c for c, _ in tally} | set(NO_DATA_CLASSES)}
    def sample(cls: str, rng: random.Random) -> str:
        roll = rng.random()
        return next((e for e, cum in table.get(cls) or dist(cls) if roll < cum), "🔴")
    return sample

def simulate(rows: list[dict], eb_cfg: dict, ladder: dict, start: dt.date, intake: int,
             weeks: int, sampler, rng: random.Random) -> dict:
    """Run the tracker forward; returns overdue / unproven-overdue per week, 🎓 count, units/week."""
    cap, ceiling = eb_cfg["max_rows_per_day"], eb_cfg["ceiling"]

    def keyed(r: dict) -> dict:
        item = {"start": r["comfort"], "start_streak": r["streak"]}
        return {**r, "key": (schedule_priority.priority_key(item, r["diff"]), r["due"]),
                "cost": eb.price(r["comfort"], r["streak"], r["diff"], r["attempts"], eb_cfg)}

    def rep(r: dict, outcome: str, day: int) -> dict:
        comfort, streak, days = ladder_step(r["comfort"], r["streak"], outcome, ladder)
        return keyed({**r, "comfort": comfort, "streak": streak, "due": day + days,
                      "attempts": r["attempts"] + 1})

    pool = [keyed(r) for r in rows]
    new_cost = eb.price("🔴", 0, "Medium", 0, eb_cfg)
    mock_cost = eb.price("🔴", 0, eb.DEFAULT_MOCK_DIFFICULTY, 0, eb_cfg)
    seat_days = [(k * DAYS_PER_WEEK) // intake for k in range(intake)]
    total_units, out = 0.0, {"backlog": {}, "unproven": {}}
    for offset in range(weeks * DAYS_PER_WEEK):
        today = start + dt.timedelta(days=offset)
        day, n_rows, units = today.toordinal(), 0, 0.0
        for _ in range(seat_days.count(offset % DAYS_PER_WEEK)):
            blank = {"comfort": "🔴", "streak": 0, "diff": "Medium", "attempts": 0}
            pool.append(rep(blank, sampler(NEW_CLASS, rng), day))
            n_rows, units = n_rows + 1, units + new_cost
        if today.weekday() == SUNDAY:
            n_rows, units = n_rows + 1, units + mock_cost
        seated = {}
        for r in sorted((r for r in pool if r["due"] <= day), key=lambda r: r["key"]):
            if n_rows >= cap:
                break
            if units + r["cost"] > ceiling:
                continue
            cls = f"🟢 s{r['streak']}" if r["comfort"] == "🟢" else r["comfort"]
            seated[id(r)] = rep(r, sampler(cls, rng), day)
            n_rows, units = n_rows + 1, units + r["cost"]
        pool, total_units = [seated.get(id(r), r) for r in pool], total_units + units
        if (offset + 1) % DAYS_PER_WEEK == 0:
            # End-of-day `due <= day` is the next morning's `due < today`, effort_budget's overdue.
            overdue, week = [r for r in pool if r["due"] <= day], (offset + 1) // DAYS_PER_WEEK
            out["backlog"][week], out["unproven"][week] = len(overdue), count_unproven(overdue, eb_cfg)
    out["graduated"] = sum(1 for r in pool if r["comfort"] == "🎓")
    out["units_per_week"] = total_units / weeks
    return out

def count_unproven(rows: list[dict], eb_cfg: dict) -> int:
    return sum(1 for r in rows if eb.is_unproven(r["comfort"], r["streak"], eb_cfg))

def mean_at(runs: list[dict], weeks: tuple, field: str) -> list[float]:
    return [sum(r[field][w] for r in runs) / len(runs) for w in weeks]

def verdict(slope: float, steady_max: float, piling_min: float) -> str:
    return "steady" if slope <= steady_max else "piling" if slope >= piling_min else "edge"

def week_labels(weeks: tuple) -> str:
    return "/".join(str(w) for w in weeks)

def report_tally(tally: Counter) -> None:
    print("Outcome tally (start -> end):")
    for (s, e), n in sorted(tally.items(), key=lambda kv: (kv[0][0], OUTCOMES.index(kv[0][1]))):
        print(f"  {s:<5} -> {e}  {n:>3}")
    if any(not any(c == s for c, _ in tally) for s in NO_DATA_CLASSES):
        print("no data for 🟢 s2/🎓 — bracketed s1-like vs backlog_forecast.optimistic_green_rate 🟢")

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--weeks", type=int, default=DEFAULT_WEEKS)
    ap.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    ap.add_argument("--intake", type=int, help="one intake rate instead of 0..5")
    ap.add_argument("--check", action="store_true", help="exit 1 when the configured intake reads piling")
    args = ap.parse_args()
    start = session_date.resolve_datetime(None, announce=False).date()
    eb_cfg, (ladder, forecast), rows = eb.load_config(), load_ladder_and_forecast(), load_tracker()
    tally = sum((tally_text(p.read_text(encoding="utf-8")) for p in schedule_files()), Counter())
    configured = eb_cfg["intake_per_week"]
    intakes = [args.intake] if args.intake is not None else sorted({*range(MAX_REPORTED_INTAKE + 1), configured})
    report_tally(tally)
    print(f"\n{len(rows)} active rows · {args.weeks} weeks from {start} · {args.seeds} seeds"
          "\nbacklog = overdue rows · unproven = overdue 🔴/🟡/🟢 below the carry streak")
    slopes: dict[int, float] = {}
    backlog_weeks = tuple(w for w in BACKLOG_WEEKS if w <= args.weeks)
    unproven_weeks = tuple(w for w in UNPROVEN_WEEKS if w <= args.weeks)
    has_slope = max(SLOPE_FROM_WEEK, SLOPE_TO_WEEK) <= args.weeks
    for intake in intakes:
        for bracket in BRACKETS:
            sampler = make_sampler(tally, bracket == "optimistic", forecast["optimistic_green_rate"])
            runs = [simulate(rows, eb_cfg, ladder, start, intake, args.weeks, sampler, random.Random(s))
                    for s in range(args.seeds)]
            b, u = mean_at(runs, backlog_weeks, "backlog"), mean_at(runs, unproven_weeks, "unproven")
            if bracket == BRACKETS[0] and has_slope:
                at = dict(zip(backlog_weeks, b))
                slopes[intake] = (at[SLOPE_TO_WEEK] - at[SLOPE_FROM_WEEK]) / (SLOPE_TO_WEEK - SLOPE_FROM_WEEK)
            grad, upw = (sum(r[f] for r in runs) / len(runs) for f in ("graduated", "units_per_week"))
            print(f"intake {intake} {bracket:<11} backlog wk{week_labels(backlog_weeks)} " + "/".join(f"{x:.0f}" for x in b)
                  + f" · unproven wk{week_labels(unproven_weeks)} " + "/".join(f"{x:.0f}" for x in u)
                  + f" · 🎓 wk{args.weeks} {grad:.0f} · {upw:.1f} units/wk")
    n_unproven = count_unproven([r for r in rows if r["due"] < start.toordinal()], eb_cfg)
    print(f"\ncurrent unproven-overdue: {n_unproven} (intake pauses at {eb_cfg['intake_pause_overdue_unproven']})")
    state = verdict(slopes[configured], forecast["steady_max_slope"], forecast["piling_min_slope"]) if configured in slopes else "not simulated"
    print(f"configured intake_per_week: {configured} → {state}")
    return 1 if args.check and state == "piling" else 0

if __name__ == "__main__":
    sys.exit(main())
