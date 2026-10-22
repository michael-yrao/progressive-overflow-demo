"""Force UTF-8 on this process's stdout/stderr.

⚠️ **Why this exists: without it, every script in here is silently dead inside the git
hook on Windows.** Git runs `.githooks/pre-commit` with a console whose encoding is the
system ANSI codepage (cp1252 here). Python inherits it, and the FIRST emoji printed —
`✅`, `⚠️`, a comfort glyph in a problem title — raises `UnicodeEncodeError` and kills the
script mid-report.

**The failure is worse than a crash, because these hooks are report-only and end in
`|| true`.** The traceback scrolls past, the commit succeeds, and the check appears to
have run. Found Aug 21, 2026: `reconcile.py` fired from the pre-commit hook exactly as
designed — the one moment a decision is recorded and the backlog is worth seeing — and
printed a traceback instead of the report. Same crash hit `effort_budget.py` whenever it
was run from Git Bash rather than PowerShell.

**Two layers, on purpose.** `.githooks/pre-commit` exports `PYTHONIOENCODING=utf-8`, which
covers every script it invokes including ones added later; this module covers every OTHER
context (Git Bash, a piped run, CI, an editor's task runner), where nothing sets that
variable. Neither layer alone is sufficient and the overlap costs nothing.

Call `force_utf8()` at import time in any script that prints. It is a no-op on a stream
that is already UTF-8, and it never raises: a stream that cannot be reconfigured (already
detached, replaced by a test harness, or a Python too old for `reconfigure`) leaves the
process exactly as it was.
"""

from __future__ import annotations

import sys


def force_utf8() -> None:
    """Re-encode stdout/stderr as UTF-8, replacing anything unmappable.

    `errors="replace"` rather than `"strict"`: the point is that **output survives**. A
    report that renders one glyph as `?` is still a report; a report that raises is not.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # not a TextIOWrapper (pytest capture, a StringIO, an old Python)
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Already detached, or the stream refuses re-encoding. Printing is still
            # possible in the host encoding; crashing here would defeat the purpose.
            pass
