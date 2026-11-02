"""Tests for rebuild_week.py. Run with: py -m pytest scripts/test_rebuild_week.py -q"""
from __future__ import annotations

import pytest

import build_week as bw
import rebuild_week as rw

MONDAY = "2026-11-02"
LIVE = bw.LIVE_DIR / "20261102_schedule.md"
CLEAN = f"# Week\n\n{bw.DRAFT_MARKER}\n\n| 1 | Two Sum | x | y | z |\n"
STRUCK = CLEAN.replace("| x |", "| ~~x~~ |")
UNDRAFTED = CLEAN.replace(bw.DRAFT_MARKER, "")


def _attempt(tmp_path, day: str, name: str | None) -> None:
    folder = tmp_path / "dsa" / "attempts" / day
    folder.mkdir(parents=True)
    if name:
        (folder / name).write_text("pass\n", encoding="utf-8")


# (argument, file text or None, attempt day, attempt file or None) -> discarded?
CASES = [
    pytest.param("2026-11-03", CLEAN, None, None, False, id="not-a-monday"),
    pytest.param("not-a-date", CLEAN, None, None, False, id="bad-date"),
    pytest.param(MONDAY, None, None, None, False, id="no-live-file"),
    pytest.param(MONDAY, UNDRAFTED, None, None, False, id="no-draft-marker"),
    pytest.param(MONDAY, STRUCK, None, None, False, id="struck-cell"),
    pytest.param(MONDAY, CLEAN, "20261104", "1_two_sum.py", False, id="saved-attempt-wednesday"),
    pytest.param(MONDAY, CLEAN, "20261104", None, True, id="empty-attempt-dir"),
    pytest.param(MONDAY, CLEAN, None, None, True, id="clean-draft"),
]


@pytest.mark.parametrize(("arg", "text", "day", "attempt", "is_discarded"), CASES)
def test_rebuild_week(tmp_path, capsys, arg, text, day, attempt, is_discarded):
    if text is not None:
        (tmp_path / bw.LIVE_DIR).mkdir(parents=True)
        (tmp_path / LIVE).write_text(text, encoding="utf-8")
    if day:
        _attempt(tmp_path, day, attempt)
    code = rw.main([arg], repo=tmp_path)
    out = capsys.readouterr().out
    if is_discarded:
        assert code == 0
        assert f"discarded: {LIVE.as_posix()}" in out
        assert not (tmp_path / LIVE).exists()
        return
    assert code == 2
    assert out.startswith("refused:")
    assert (text is None) or (tmp_path / LIVE).read_text(encoding="utf-8") == text
