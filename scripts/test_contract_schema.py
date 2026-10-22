"""Tests for contract_schema.py — schema validation with a local `$ref` registry.

Stdlib unittest, same style as test_showcase.py. Run it with:

    python scripts/test_contract_schema.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import contract_schema as cs

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
PROBLEM_SCHEMA = DASHBOARD / "showcase-problem.schema.json"
SAMPLE = {
    "schemaVersion": 1, "generatedAt": "2026-10-06",
    "entries": [{"key": "1:v", "lcNumber": 1, "variant": "v", "title": "T", "url": "u",
                 "file": "dsa/leetcode/cat/1_target.py", "symbol": "target_20260101",
                 "attemptDate": "2026-01-01",
                 "segments": [{"kind": "attempt", "symbol": "target_20260101",
                               "startLine": 1, "endLine": 1, "lines": ["x"]}]}],
}
DANGLING_SCHEMA = {"$schema": "http://json-schema.org/draft-07/schema#",
                   "$ref": "https://unknown.invalid/missing.v1.json"}


def _without_entry_key(payload: dict) -> dict:
    entries = [{k: v for k, v in entry.items() if k != "key"} for entry in payload["entries"]]
    return {**payload, "entries": entries}


class ValidateTest(unittest.TestCase):
    def test_cross_file_ref_resolves_locally_and_dangling_ref_raises(self) -> None:
        self.assertEqual(cs.validate(SAMPLE, PROBLEM_SCHEMA), [])
        self.assertTrue(cs.validate(_without_entry_key(SAMPLE), PROBLEM_SCHEMA))

        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "dangling.schema.json"
            schema_path.write_text(json.dumps(DANGLING_SCHEMA), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unresolvable"):
                cs.validate({}, schema_path)

    def test_missing_jsonschema_blocks_with_the_install_hint(self) -> None:
        unimportable = {"jsonschema": None, "jsonschema.validators": None}
        with mock.patch.dict(sys.modules, unimportable):
            with self.assertRaises(SystemExit) as raised:
                cs.validate({}, PROBLEM_SCHEMA)
        self.assertEqual(raised.exception.code, cs.INSTALL_HINT)


if __name__ == "__main__":
    unittest.main()
