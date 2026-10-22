"""Tests for dashboard_indexes.py — the practice index and the per-problem showcase split.

Stdlib unittest, same style as test_showcase.py. Run it with:

    python scripts/test_dashboard_indexes.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import dashboard_indexes as di

ENVELOPE = {"schemaVersion": 1, "generatedAt": "2026-10-05"}


def _entry(number: int, variant: str) -> dict:
    return {"key": f"{number}:{variant}", "lcNumber": number, "variant": variant,
            "segments": []}


class PracticeIndexTest(unittest.TestCase):
    def test_numbers_sorted_ascending_and_deduped(self) -> None:
        practice = {**ENVELOPE, "problems": [{"number": 90}, {"number": 3}, {"number": 90},
                                             {"number": 17}]}
        self.assertEqual(di.build_practice_index(practice),
                         {**ENVELOPE, "numbers": [3, 17, 90]})


class ShowcaseSplitTest(unittest.TestCase):
    SHOWCASE = {**ENVELOPE, "entries": [_entry(733, "bfs"), _entry(200, "dfs"),
                                        _entry(733, "dfs"), _entry(200, "bfs")]}

    def test_index_lists_both_problems_with_variants_and_file(self) -> None:
        index = di.build_showcase_split(self.SHOWCASE)[di.SHOWCASE_INDEX_NAME]
        self.assertEqual(index["problems"], [
            {"lcNumber": 200, "variants": ["dfs", "bfs"], "file": "showcase/200.json"},
            {"lcNumber": 733, "variants": ["bfs", "dfs"], "file": "showcase/733.json"},
        ])

    def test_problem_file_holds_only_its_own_entries(self) -> None:
        files = di.build_showcase_split(self.SHOWCASE)
        self.assertEqual(files["showcase/733.json"],
                         {**ENVELOPE, "entries": [_entry(733, "bfs"), _entry(733, "dfs")]})
        self.assertEqual([e["lcNumber"] for e in files["showcase/200.json"]["entries"]],
                         [200, 200])

    def test_write_removes_stale_problem_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = Path(tmp)
            (dashboard / "showcase").mkdir()
            stale = dashboard / "showcase" / "999.json"
            stale.write_text(json.dumps({"entries": []}), encoding="utf-8")
            files = di.build_showcase_split(self.SHOWCASE)

            self.assertIn("showcase/999.json: extra file — regenerate",
                          di.stale_reasons(dashboard, files, check_extra_showcase=True))
            di.write_files(dashboard, files, prune_showcase=True)

            self.assertFalse(stale.exists())
            self.assertTrue((dashboard / "showcase" / "733.json").exists())
            self.assertEqual(di.stale_reasons(dashboard, files, check_extra_showcase=True), [])


if __name__ == "__main__":
    unittest.main()
