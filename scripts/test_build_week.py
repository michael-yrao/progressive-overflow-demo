"""Tests for build_week.py. Run with: py -m pytest scripts/test_build_week.py -q"""
from __future__ import annotations

import datetime as dt
import json
import urllib.error

import pytest

import build_week as bw

D = dt.date
NOW = dt.datetime


def _no_network(url: str, timeout: float) -> bytes:
    raise urllib.error.URLError("offline")


# (now, existing mondays, start monday, lead hours, early) -> (monday, skip prefix)
TARGET_CASES = [
    pytest.param(NOW(2026, 10, 21, 12), set(), None, 0, False, D(2026, 10, 19), None,
                 id="current-missing-builds-this-monday"),
    pytest.param(NOW(2026, 10, 21, 12), set(), D(2026, 11, 2), 0, False, D(2026, 11, 2), None,
                 id="future-start-builds-start-monday"),
    pytest.param(NOW(2026, 10, 25, 13), {D(2026, 10, 19)}, None, 10, False, None, "boundary",
                 id="before-boundary-minus-lead"),
    pytest.param(NOW(2026, 10, 25, 14), {D(2026, 10, 19)}, None, 10, False, D(2026, 10, 26), None,
                 id="at-boundary"),
    pytest.param(NOW(2026, 10, 25, 14), {D(2026, 10, 19), D(2026, 10, 26)}, None, 10, False,
                 None, "20261026_schedule.md exists", id="next-exists"),
    pytest.param(NOW(2026, 10, 21, 12), {D(2026, 10, 19)}, None, 0, True, D(2026, 10, 26), None,
                 id="early-builds-next"),
]


@pytest.mark.parametrize(("now", "existing", "start", "lead", "early", "monday", "skip"),
                         TARGET_CASES)
def test_target_week(now, existing, start, lead, early, monday, skip):
    target = bw.target_week(now, frozenset(existing), start, dt.timedelta(hours=lead), early)
    assert target.monday == monday
    assert (target.skip is None) if skip is None else target.skip.startswith(skip)


FULL_BLOCK = {"weekly_build": True, "build_lead_hours": 0, "practice_index_url": "u",
              "prefer_practice_spec": True}


def test_load_automation():
    assert bw.load_automation({}).is_enabled is False
    assert bw.load_automation({"automation": FULL_BLOCK}).is_enabled is True
    incomplete = {"automation": {"weekly_build": True, "build_lead_hours": 0}}
    with pytest.raises(bw.BuildRefused, match="automation.practice_index_url"):
        bw.load_automation(incomplete)


CATALOG = tuple({"number": n, "title": f"P{n}", "difficulty": "Easy", "folder": "f"}
                for n in (1, 2, 3, 4, 5))

# (rows' numbers, site numbers, per week, paused) -> picked numbers
INTAKE_CASES = [
    pytest.param([], None, 2, True, [], id="paused"),
    pytest.param([], None, 3, False, [1, 2, 3], id="index-unavailable-curriculum-order"),
    pytest.param([], frozenset({4, 5}), 2, False, [4, 5], id="index-preferred"),
    pytest.param(["1", "2"], None, 5, False, [3, 4, 5], id="dated-row-excluded"),
    pytest.param(["99"], None, 1, False, [1], id="cap"),
]


@pytest.mark.parametrize(("tracked", "site", "per_week", "paused", "expected"), INTAKE_CASES)
def test_intake_candidates(tracked, site, per_week, paused, expected):
    rows = [{"num": n} for n in tracked]
    picked = bw.intake_candidates(CATALOG, rows, site, per_week, paused)
    assert [entry["number"] for entry in picked] == expected


MONDAY = D(2026, 10, 26)


def _item(number: int, due_offset: int = 0, cost: float = 1.0, is_priority: bool = False):
    due = MONDAY + dt.timedelta(days=due_offset)
    return bw.SeatItem(str(number), f"[{number}]", "🟢", "", due, cost, is_priority, (number,))


def _plan(items, first_offset=0, ceiling=8.0, max_rows=8):
    ctx = bw.PlanContext(MONDAY, MONDAY + dt.timedelta(days=first_offset), ceiling, max_rows,
                         tuple(items))
    plan = bw.plan_week(ctx)
    seated = {f"{d.day:%a}": [i.number for i in d.items] for d in plan.days if d.items}
    return seated, [i.number for i in plan.carried], plan.notes, [d.day.weekday() for d in plan.days]


def test_plan_week():
    at_cap, _, _, _ = _plan([_item(1), _item(2)], max_rows=2)
    assert at_cap == {"Mon": ["1", "2"]}
    over_cap, _, _, _ = _plan([_item(1), _item(2), _item(3)], max_rows=2)
    assert over_cap == {"Mon": ["1", "2"], "Tue": ["3"]}

    at_ceiling, _, _, _ = _plan([_item(1, cost=4.0), _item(2, cost=4.0)])
    assert at_ceiling == {"Mon": ["1", "2"]}
    past_ceiling, _, _, _ = _plan([_item(1, cost=4.0), _item(2, cost=4.0), _item(3, cost=0.5)])
    assert past_ceiling == {"Mon": ["1", "2"], "Tue": ["3"]}

    saturday = 5
    forced, carried, notes, _ = _plan([_item(n, saturday, is_priority=True) for n in (1, 2, 3)],
                                      max_rows=1)
    assert forced == {"Sat": ["1", "3"], "Sun": ["2"]}
    assert carried == [] and notes == ("forced over cap: Sat",)

    _, overflow, notes, _ = _plan([_item(n, saturday) for n in (1, 2, 3)], max_rows=1)
    assert overflow == ["3"] and notes == ()

    wednesday = 2
    late_start, _, _, weekdays = _plan([_item(1)], first_offset=wednesday)
    assert weekdays == [2, 3, 4, 5, 6] and late_start == {"Wed": ["1"]}

    thursday = 3
    not_early, _, _, _ = _plan([_item(1, thursday)])
    assert not_early == {"Thu": ["1"]}


@pytest.mark.parametrize(("opener", "expected"), [
    pytest.param(_no_network, None, id="network-error"),
    pytest.param(lambda url, timeout: b"not json", None, id="bad-json"),
    pytest.param(lambda url, timeout: json.dumps({"schemaVersion": 1, "numbers": [3, 1]}).encode(),
                 frozenset({1, 3}), id="ok"),
])
def test_fetch_site_numbers(opener, expected):
    assert bw.fetch_site_numbers("https://example.test/index.json", opener) == expected


def _config(tmp_path, weekly_build: bool) -> None:
    (tmp_path / "cse.config.yml").write_text(
        "timezone: UTC\nautomation:\n"
        f"  weekly_build: {'true' if weekly_build else 'false'}\n"
        "  build_lead_hours: 0\n  practice_index_url: https://example.test/i.json\n"
        "  prefer_practice_spec: true\n", encoding="utf-8")


def _files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _main(tmp_path, *argv):
    return bw.main(list(argv), repo=tmp_path, opener=_no_network)


def test_main_no_config(tmp_path, capsys):
    assert _main(tmp_path, "--now", "2026-10-21T10:00") == 2
    assert "refused: no cse.config.yml — onboard first" in capsys.readouterr().out


def test_main_off_writes_nothing(tmp_path, capsys):
    _config(tmp_path, weekly_build=False)
    before = _files(tmp_path)
    assert _main(tmp_path, "--now", "2026-10-21T10:00") == 0
    assert "skipped: weekly build is off" in capsys.readouterr().out
    assert _files(tmp_path) == before


def test_main_file_exists(tmp_path, capsys):
    _config(tmp_path, weekly_build=True)
    live = tmp_path / bw.LIVE_DIR
    live.mkdir(parents=True)
    for stamp in ("20261019", "20261026"):
        (live / f"{stamp}_schedule.md").write_text("x", encoding="utf-8")
    before = _files(tmp_path)
    assert _main(tmp_path, "--now", "2026-10-25T23:30") == 0
    assert "skipped: 20261026_schedule.md exists" in capsys.readouterr().out
    assert _files(tmp_path) == before


def test_main_dry_run_writes_nothing(tmp_path, capsys):
    _config(tmp_path, weekly_build=False)
    before = _files(tmp_path)
    assert _main(tmp_path, "--dry-run", "--now", "2026-10-26T00:30") == 0
    assert "dry-run: 2026-10-26" in capsys.readouterr().out
    assert _files(tmp_path) == before


def test_main_week_bypasses_off_gate(tmp_path, capsys):
    _config(tmp_path, weekly_build=False)
    assert _main(tmp_path, "--week", "2026-10-26", "--now", "2026-10-21T10:00") == 0
    assert "built: 2026-10-26" in capsys.readouterr().out
    assert (tmp_path / bw.LIVE_DIR / "20261026_schedule.md").is_file()


TOP_UP_MONDAY = D(2026, 10, 26)
TOP_UP_NOW = "2026-10-27T09:00"


def _tracker_row(number: int, comfort: str) -> dict:
    return {"num": str(number), "title": "T", "diff": "Medium", "comfort": comfort,
            "streak": 0, "due": TOP_UP_MONDAY.isoformat()}


def _cell(number: int, is_struck: bool = False) -> str:
    link = f"[{number} T](x)"
    return f"| {'~~' + link + '~~' if is_struck else link} | 🟢 s2 |  |  | t |"


def _week_text(rows_by_offset: dict[int, list[str]]) -> str:
    lines = ["# Week", "", "| Problem | S | E | Next | Technique |", "|---|:-:|:-:|:-:|---|"]
    for offset in range(bw.DAYS_PER_WEEK):
        day = TOP_UP_MONDAY + dt.timedelta(days=offset)
        lines += [f"| ▸ **{bw.day_label(day)}** · ~0.0 units |  |  |  |  |",
                  *rows_by_offset.get(offset, []), bw.EMPTY_ROW]
    return "\n".join([*lines, "", bw.NOTES_MARKER, "- earlier note", ""])


# (existing rows by day offset, last week's cells, tracker rows, max rows per day) ->
# (output, text fragments the file must carry)
TOP_UP_CASES = [
    pytest.param({0: [_cell(90001)]}, None, [_tracker_row(90001, "🎓")], None,
                 "skipped: nothing to top up", [], id="nothing-missing"),
    pytest.param({0: [_cell(90001)]}, None,
                 [_tracker_row(90001, "🎓"), _tracker_row(90002, "🎓")], None,
                 "topped-up: 1 rows into 2026-10-26", ["[90002 T]()"], id="one-missing-seated"),
    pytest.param({0: [_cell(90001)]}, [_cell(90002, is_struck=True)],
                 [_tracker_row(90001, "🎓"), _tracker_row(90002, "🎓")], None,
                 "topped-up: 1 rows into 2026-10-26", ["[90002 T]()"], id="struck-last-week-still-seated"),
    pytest.param({offset: [_cell(90001 + offset)] for offset in range(bw.DAYS_PER_WEEK)}, None,
                 [_tracker_row(90099, "🔴")], 1,
                 "topped-up: 1 rows into 2026-10-26", ["forced over cap: Tue"], id="priority-forced"),
]


@pytest.mark.parametrize(("existing", "last_week", "tracker", "max_rows", "output", "fragments"),
                         TOP_UP_CASES)
def test_top_up(tmp_path, capsys, monkeypatch, existing, last_week, tracker, max_rows, output,
                fragments):
    _config(tmp_path, weekly_build=True)
    live = tmp_path / bw.LIVE_DIR
    archive = tmp_path / bw.ARCHIVE_DIR
    live.mkdir(parents=True)
    path = live / f"{TOP_UP_MONDAY:%Y%m%d}_schedule.md"
    path.write_text(_week_text(existing), encoding="utf-8")
    if last_week is not None:
        archive.mkdir(parents=True)
        previous = TOP_UP_MONDAY - dt.timedelta(days=bw.DAYS_PER_WEEK)
        (archive / f"{previous:%Y%m%d}_schedule.md").write_text(
            _week_text({0: last_week}).replace("Oct 26", "Oct 19"), encoding="utf-8")
    cfg = bw.eb.load_config()
    monkeypatch.setattr(bw.eb, "parse_rows", lambda: tracker)
    monkeypatch.setattr(bw.eb, "load_config",
                        lambda: {**cfg, "max_rows_per_day": max_rows or cfg["max_rows_per_day"]})
    before = path.read_text(encoding="utf-8")
    assert _main(tmp_path, "--top-up", "--now", TOP_UP_NOW) == 0
    assert capsys.readouterr().out.strip() == output
    after = path.read_text(encoding="utf-8")
    assert (after == before) == (not fragments)
    assert all(fragment in after for fragment in fragments)
    if output.startswith("topped-up"):
        monday_block = after.split("Tue Oct 27")[0]
        assert "90002" not in monday_block and "90099" not in monday_block


def test_main_non_monday_week(tmp_path, capsys):
    _config(tmp_path, weekly_build=True)
    assert _main(tmp_path, "--week", "2026-10-21", "--now", "2026-10-21T10:00") == 2
    assert "is not a Monday" in capsys.readouterr().out
