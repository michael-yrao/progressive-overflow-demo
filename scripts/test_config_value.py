"""Tests for config_value.py. Run with: py -m pytest scripts/test_config_value.py -q"""
from __future__ import annotations

import pytest

import config_value

CONFIG_TEXT = """\
timezone: Nope/Zone
automation:
  weekly_build: true
  build_lead_hours: 3
solutions:
  roots: [dsa/leetcode, extra]
effort_budget:
  ceiling: 8.0
"""

# (argv after the key, expected exit code, expected stdout line or None)
CASES = [
    pytest.param(["effort_budget.ceiling"], 0, "8.0", id="nested"),
    pytest.param(["solutions.roots.1"], 0, "extra", id="list-index"),
    pytest.param(["automation.missing", "--default", "7"], 0, "7", id="missing-with-default"),
    pytest.param(["automation.missing"], 2, None, id="missing-no-default"),
    pytest.param(["automation"], 2, None, id="mapping"),
    pytest.param(["solutions.roots"], 2, None, id="list"),
    pytest.param(["automation.weekly_build"], 0, "true", id="bool-render"),
    pytest.param(["timezone", "--zone"], 2, None, id="bad-zone"),
]


@pytest.mark.parametrize(("argv", "code", "expected"), CASES)
def test_read_value(tmp_path, capsys, argv, code, expected):
    config = tmp_path / "cse.config.yml"
    config.write_text(CONFIG_TEXT, encoding="utf-8")
    assert config_value.main([argv[0], *argv[1:], "--config", str(config)]) == code
    if expected is not None:
        assert capsys.readouterr().out.strip() == expected


@pytest.mark.parametrize(("argv", "code", "expected"), [
    pytest.param(["timezone", "--default", "UTC"], 0, "UTC", id="absent-config-default"),
    pytest.param(["timezone"], 2, None, id="absent-config-no-default"),
])
def test_read_value_absent_config(tmp_path, capsys, argv, code, expected):
    absent = tmp_path / "none.yml"
    assert config_value.main([*argv, "--config", str(absent)]) == code
    if expected is not None:
        assert capsys.readouterr().out.strip() == expected
