"""Tests for check_line_endings.flipped_endings (the pure compare; no git needed)."""
from __future__ import annotations

import pytest

from check_line_endings import flipped_endings

CASES = [
    ("crlf to lf is reported", b"a\r\nb\r\n", b"a\nb\n", ("crlf", "lf")),
    ("unchanged endings are not reported", b"a\r\nb\r\n", b"a\r\nc\r\n", None),
    ("new file (no HEAD blob) is not reported", None, b"a\nb\n", None),
]


@pytest.mark.parametrize("label, head, staged, expected", CASES, ids=[c[0] for c in CASES])
def test_flipped_endings(label, head, staged, expected):
    assert flipped_endings(head, staged) == expected
