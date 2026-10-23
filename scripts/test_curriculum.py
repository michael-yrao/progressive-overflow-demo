"""Tests for curriculum.py. Run with: py -m pytest scripts/test_curriculum.py -q"""
from __future__ import annotations

import pytest

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


CATALOGUE = """techniques:
  - name: A
    family: fam_a
    builds_on: ["B"]
    problems:
      - {number: 1, title: One}
      - {number: 2, method: M, title: Two}
    variants:
      - {name: V1}
  - name: B
    family: fam_b
"""

OVERLAY = """techniques:
  - name: A
    family: ignored
    builds_on: ["ignored"]
    problems:
      - {number: 1, queued: "surplus>=1"}
      - {number: 2, method: M, planned: false}
      - {number: 2, method: Other, queued: "x"}
      - {number: 9001}
    variants:
      - {name: V1, queued: "rated:1"}
  - name: Local
    family: mine
"""

A_PLAIN = {
    "name": "A", "family": "fam_a", "builds_on": ["B"],
    "problems": [{"number": 1, "title": "One"}, {"number": 2, "method": "M", "title": "Two"}],
    "variants": [{"name": "V1"}],
}
A_MERGED = {
    "name": "A", "family": "fam_a", "builds_on": ["B"],
    "problems": [
        {"number": 1, "title": "One", "queued": "surplus>=1"},
        {"number": 2, "method": "M", "title": "Two", "planned": False},
        {"number": 2, "method": "Other", "queued": "x"},
        {"number": 9001},
    ],
    "variants": [{"name": "V1", "queued": "rated:1"}],
}
A_OVERLAY_ONLY = {
    "name": "A", "family": "ignored", "builds_on": ["ignored"],
    "problems": [{"number": 1, "queued": "surplus>=1"},
                 {"number": 2, "method": "M", "planned": False},
                 {"number": 2, "method": "Other", "queued": "x"}, {"number": 9001}],
    "variants": [{"name": "V1", "queued": "rated:1"}],
}
B_PLAIN = {"name": "B", "family": "fam_b"}
LOCAL = {"name": "Local", "family": "mine"}

MERGE_CASES = [
    ("overlay absent: catalogue as written", True, False, [A_PLAIN, B_PLAIN]),
    ("catalogue absent: overlay as written", False, True, [A_OVERLAY_ONLY, LOCAL]),
    ("both: queued/planned merged in place, unmatched spec appended after the catalogue's, "
     "variant merged by name, new name appended last, family/builds_on ignored",
     True, True, [A_MERGED, B_PLAIN, LOCAL]),
]


@pytest.mark.parametrize("label,has_catalogue,has_overlay,expected", MERGE_CASES,
                         ids=[case[0] for case in MERGE_CASES])
def test_load_techniques_merge(tmp_path, label, has_catalogue, has_overlay, expected):
    catalogue, overlay = tmp_path / "catalogue.yml", tmp_path / "overlay.yml"
    if has_catalogue:
        catalogue.write_text(CATALOGUE, encoding="utf-8")
    if has_overlay:
        overlay.write_text(OVERLAY, encoding="utf-8")
    assert curriculum.load_techniques(catalogue, overlay) == {"techniques": expected}


def test_load_techniques_non_list_raises_naming_the_file(tmp_path):
    catalogue, overlay = tmp_path / "catalogue.yml", tmp_path / "overlay.yml"
    catalogue.write_text(CATALOGUE, encoding="utf-8")
    overlay.write_text("techniques: {name: A}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="overlay.yml"):
        curriculum.load_techniques(catalogue, overlay)
