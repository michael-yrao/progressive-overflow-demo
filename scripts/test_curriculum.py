"""Tests for curriculum.py. Run with: py -m pytest scripts/test_curriculum.py -q"""
from __future__ import annotations

import curriculum

MILESTONE = """\
phases:
  - name: Arrays & Hashing
    problems:
      - { number: 217, title: "Contains Duplicate", difficulty: Easy }
      - { number: 1, title: "Two Sum", difficulty: Easy }
  - name: Two Pointers
    folder: two_pointers_custom
    problems:
      - { number: 125, title: "Valid Palindrome", difficulty: Easy }
"""


def test_intake_order_flattens_phases_in_order(tmp_path):
    path = tmp_path / "milestone.yml"
    path.write_text(MILESTONE, encoding="utf-8")
    order = curriculum.intake_order(path)
    assert [entry["number"] for entry in order] == [217, 1, 125]
    assert [entry["folder"] for entry in order] == [
        "arrays_hashing", "arrays_hashing", "two_pointers_custom"]


def test_catalog_entry_hit_and_miss(tmp_path):
    path = tmp_path / "milestone.yml"
    path.write_text(MILESTONE, encoding="utf-8")
    assert curriculum.catalog_entry(125, path) == {
        "title": "Valid Palindrome", "difficulty": "Easy", "folder": "two_pointers_custom"}
    assert curriculum.catalog_entry(999, path) is None


def test_file_absent_degrades(tmp_path):
    absent = tmp_path / "none.yml"
    assert curriculum.intake_order(absent) == ()
    assert curriculum.catalog_entry(1, absent) is None
