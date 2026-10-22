"""Tests for session_date.resolve_datetime's --date override announcement.

Named `_override` so it does not share a basename with tests/test_session_date.py (pytest
rootdir collection refuses two test modules with the same basename).

Run with: python scripts/test_session_date_override.py
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import session_date  # noqa: E402  (import after sys.path setup)

SMALL_HOURS = datetime(2026, 10, 10, 0, 40)
DAYTIME = datetime(2026, 10, 10, 14, 0)
OVERRIDE_LINE = (
    "--date 2026-10-10 overrides the detected session date 2026-10-09 "
    "(working tree is dirty — a session is in progress, so it started yesterday); "
    "the override is for a wrong detection, not for re-deciding which day has started."
)


class ResolveDatetimeOverrideTests(unittest.TestCase):
    def setUp(self):
        # The runner sets GITHUB_ACTIONS, which makes detect_session_date trust the wall clock;
        # these cases exercise the reasoned detection, so the variable is removed for them.
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(session_date.CI_ENV_VAR, None)

    def test_override_line_only_when_explicit_contradicts_a_reasoned_detection(self):
        cases = [
            ("explicit equals detected, small hours, dirty", "2026-10-09", SMALL_HOURS, ""),
            ("explicit differs, small hours, dirty", "2026-10-10", SMALL_HOURS, OVERRIDE_LINE),
            ("explicit differs from now, daytime", "2026-10-09", DAYTIME, ""),
        ]
        for name, explicit, now, expected in cases:
            with self.subTest(name):
                out = io.StringIO()
                with mock.patch.object(session_date, "has_uncommitted_changes", return_value=True), \
                        contextlib.redirect_stdout(out):
                    session_date.resolve_datetime(explicit, now=now)
                self.assertEqual(out.getvalue().strip(), expected)


class DetectSessionDateCiTests(unittest.TestCase):
    def test_github_actions_keeps_the_wall_date_in_the_small_hours(self):
        cases = [
            ("GITHUB_ACTIONS=true, 02:00, dirty tree", {"GITHUB_ACTIONS": "true"}, SMALL_HOURS.date(), None),
            ("not CI, 02:00, dirty tree", {"GITHUB_ACTIONS": ""}, datetime(2026, 10, 9).date(),
             "working tree is dirty"),
        ]
        for name, env, expected_date, reason_part in cases:
            with self.subTest(name), mock.patch.dict(os.environ, env), \
                    mock.patch.object(session_date, "has_uncommitted_changes", return_value=True):
                session, reason = session_date.detect_session_date(SMALL_HOURS)
                self.assertEqual(session.date(), expected_date)
                self.assertEqual(reason is None, reason_part is None)


if __name__ == "__main__":
    unittest.main()
