"""Re-run the pre-commit hook over a pushed range, so a push that bypassed it still gets its outputs.

A push made through the GitHub API (the site's Worker) never runs `.githooks/pre-commit`. The hook's
scripts read the INDEX themselves, so the replay builds the index the hook expects: soft-reset HEAD
to the base (the index keeps the after-tree, so `git diff --cached` is the pushed range), run the
hook, then soft-reset HEAD back to the pushed commit. What the hook regenerated stays staged, ready
for `.github/actions/commit-push`.

    python scripts/replay_hook.py --before <sha> --after <sha> [--marker refs/regenerate/last]

Prints `regenerated: <paths>`; exits 1 (HEAD restored) when the hook fails. See decisions.yml `site-hold`.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

import _console

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
ZERO_SHA = "0" * 40
DEFAULT_MARKER = "refs/regenerate/last"
HOOK_CMD = ("sh", ".githooks/pre-commit")


class ReplayError(RuntimeError):
    """The hook exited non-zero; HEAD has already been restored to the pushed commit."""

    def __init__(self, returncode: int):
        super().__init__(f"pre-commit hook exited {returncode}")
        self.returncode = returncode


def is_zero_sha(sha: str | None) -> bool:
    return not sha or set(sha) == {"0"}


def resolve_base(before: str | None, after: str, marker: str | None,
                 is_ancestor: Callable[[str], bool],
                 parent_of: Callable[[str], str | None]) -> str | None:
    """The commit to replay from: the last-processed marker, else the push's `before`, else the
    parent of `after` (None for a root commit: nothing to replay)."""
    if marker is not None and is_ancestor(marker):
        return marker
    if not is_zero_sha(before) and is_ancestor(before):
        return before
    return parent_of(after)


def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8")


def replay(base: str, after: str, hook_cmd: Sequence[str], cwd: Path) -> list[str]:
    """Run `hook_cmd` with the index holding base..after; return the paths it left staged."""
    _git(["reset", "--soft", base], cwd)
    try:
        hook = subprocess.run(list(hook_cmd), cwd=cwd, check=False)
    finally:
        _git(["reset", "--soft", after], cwd)
    if hook.returncode != 0:
        raise ReplayError(hook.returncode)
    return _git(["diff", "--cached", "--name-only"], cwd).stdout.split()


def _git_ok(args: Sequence[str], cwd: Path) -> bool:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True).returncode == 0


def _rev_parse(rev: str, cwd: Path) -> str | None:
    result = subprocess.run(["git", "rev-parse", "--verify", "-q", rev], cwd=cwd,
                            capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip() if result.returncode == 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--marker", default=DEFAULT_MARKER)
    args = parser.parse_args(argv)

    marker = _rev_parse(f"{args.marker}^{{commit}}", REPO)
    base = resolve_base(
        args.before, args.after, marker,
        is_ancestor=lambda sha: _git_ok(["merge-base", "--is-ancestor", sha, args.after], REPO),
        parent_of=lambda sha: _rev_parse(f"{sha}^", REPO),
    )
    if base is None:
        print("regenerated: (none: root commit)")
        return 0
    try:
        paths = replay(base, args.after, HOOK_CMD, REPO)
    except ReplayError as exc:
        print(f"ERROR: pre-commit hook exited {exc.returncode}", file=sys.stderr)
        return 1
    print("regenerated: " + (" ".join(paths) if paths else "(none)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
