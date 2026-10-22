"""Tests for export_manifest.py — the dashboard file-hash manifest.

Stdlib unittest, same style as test_showcase.py. Run it with:

    python scripts/test_export_manifest.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import export_manifest as em

PRACTICE_BYTES = b'{"a":1}\n'
SHOWCASE_BYTES = b'{"entries":[]}\n'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BuildFilesMapTest(unittest.TestCase):
    def test_covers_data_files_only_with_sorted_keys(self) -> None:
        cases = [
            ("two data files give two sorted keys", {}, 2),
            ("a *.schema.json is excluded", {"practice.schema.json": b"{}"}, 2),
            ("manifest.json is excluded", {"manifest.json": b"{}"}, 2),
            ("a CRLF file hashes as its LF form", {"practice.json": b'{"a":1}\r\n'}, 2),
        ]
        for label, extra, expected_count in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                dashboard = Path(tmp)
                (dashboard / "showcase").mkdir()
                (dashboard / "showcase" / "733.json").write_bytes(SHOWCASE_BYTES)
                (dashboard / "practice.json").write_bytes(PRACTICE_BYTES)
                for name, data in extra.items():
                    (dashboard / name).write_bytes(data)

                files = em.build_files_map(dashboard)

                self.assertEqual(list(files), ["practice.json", "showcase/733.json"])
                self.assertEqual(len(files), expected_count)
                self.assertEqual(files["practice.json"],
                                 {"sha256": _sha(PRACTICE_BYTES), "bytes": len(PRACTICE_BYTES)})
                self.assertEqual(files["showcase/733.json"],
                                 {"sha256": _sha(SHOWCASE_BYTES), "bytes": len(SHOWCASE_BYTES)})


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class StagedByteSourceTest(unittest.TestCase):
    def test_index_bytes_win_where_staged_working_tree_elsewhere(self) -> None:
        staged_old, staged_new = b'{"v":1}\n', b'{"v":2}\n'
        untracked = b'{"u":1}\n'
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            dashboard = repo / "dashboard"
            dashboard.mkdir()
            _git(repo, "init", "-q")
            (dashboard / "staged.json").write_bytes(staged_old)
            _git(repo, "add", "dashboard/staged.json")
            (dashboard / "staged.json").write_bytes(staged_new)
            (dashboard / "untracked.json").write_bytes(untracked)

            files = em.build_files_map(dashboard, em.staged_byte_source(repo, dashboard))

            self.assertEqual(files["staged.json"]["sha256"], _sha(staged_old))
            self.assertEqual(files["untracked.json"]["sha256"], _sha(untracked))


class CheckWithNothingToCoverTest(unittest.TestCase):
    def test_absent_manifest_and_no_json_exits_clean_and_writes_nothing(self) -> None:
        # No existing test covers main(); this is one minimal case beside them.
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = Path(tmp)
            schema = em.DASHBOARD / em.SCHEMA_NAME
            (dashboard / em.SCHEMA_NAME).write_bytes(schema.read_bytes())
            with mock.patch.object(em, "DASHBOARD", dashboard), \
                    mock.patch.object(sys, "argv", ["export_manifest.py", "--check"]):
                em.main()  # returns normally: exit 0

            self.assertFalse((dashboard / em.MANIFEST_NAME).exists())


class ManifestSchemaTest(unittest.TestCase):
    def test_valid_manifest_passes_and_bad_sha_is_an_error(self) -> None:
        good = {"schemaVersion": 1, "generatedAt": "2026-10-06",
                "files": {"a.json": {"sha256": _sha(b"x"), "bytes": 1}}}
        bad = {**good, "files": {"a.json": {"sha256": "abc", "bytes": 1}}}
        self.assertEqual(em.schema_errors(good), [])
        self.assertTrue(em.schema_errors(bad))


if __name__ == "__main__":
    unittest.main()
