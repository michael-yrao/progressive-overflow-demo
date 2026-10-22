"""Tests for replay_hook.py and for the regenerate workflow's `paths:` against the pre-commit hook.

Stdlib unittest; the replay runs in a temp git repo, never the real one:

    python scripts/test_replay_hook.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

import replay_hook

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / ".githooks" / "pre-commit"
WORKFLOW = REPO / ".github" / "workflows" / "regenerate.yml"

STUB_HOOK = """\
import subprocess, sys
names = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True,
                       text=True, check=True).stdout
open("out.json", "w", encoding="utf-8").write(names)
subprocess.run(["git", "add", "out.json"], check=True)
sys.exit({rc})
"""

# Hook alternatives that regenerate nothing the workflow should replay for.
EXEMPT = {
    r"technique_coverage\.md$": "written by the hook's coverage block (an output)",
    r"CLAUDE\.md$": "report-only single-source check; regenerates nothing",
    r"cse\.config(\.example)?\.yml$": "the template's single-source trigger also watches the example config; "
                                      "report-only, regenerates nothing",
    r"^docs/foundations/.*\.md$": "report-only single-source check; regenerates nothing",
}

SAMPLES = {
    r"dsa_progress\.md$": "docs/foundations/dsa/mastery/dsa_progress.md",
    r"holds\.yml$": "docs/foundations/dsa/mastery/holds.yml",
    r"^dsa/leetcode/.*\.(py|java|ts|js|cpp)$": "dsa/leetcode/graphs/743_network_delay_time.cpp",
    r"design_progress\.md$": "docs/foundations/system_design/mastery/design_progress.md",
    r"techniques\.yml$": "docs/foundations/dsa/mastery/techniques.yml",
    r"^docs/foundations/schedules/[0-9]{8}_schedule\.md$":
        "docs/foundations/schedules/20261019_schedule.md",
    r"^docs/foundations/schedules/.*\.md$": "docs/foundations/schedules/archive/old.md",
    r"cse\.config\.yml$": "cse.config.yml",
    r"^scripts/gamify\.py$": "scripts/gamify.py",
    r"^scripts/effort_budget\.py$": "scripts/effort_budget.py",
    r"^dsa/leetcode/.*\.py$": "dsa/leetcode/graphs/743_network_delay_time.py",
    r"dashboard/showcase\.yml$": "dashboard/showcase.yml",
    r"scripts/export_showcase\.py$": "scripts/export_showcase.py",
    r"complexity_gotchas\.md$": "docs/foundations/dsa/mastery/complexity_gotchas.md",
    r"dashboard/bigo\.yml$": "dashboard/bigo.yml",
    r"scripts/export_bigo\.py$": "scripts/export_bigo.py",
    r"dashboard/pattern_sense\.yml$": "dashboard/pattern_sense.yml",
    r"scripts/pattern_sense\.py$": "scripts/pattern_sense.py",
    r"^dsa/tests/.*\.yml$": "dsa/tests/743_network_delay_time.yml",
    r"scripts/export_practice\.py$": "scripts/export_practice.py",
    r"scripts/new_problem\.py$": "scripts/new_problem.py",
    r"^scripts/.*\.py$": "scripts/anything.py",
    r"^docs/foundations/dsa/patterns/techniques/.*\.md$":
        "docs/foundations/dsa/patterns/techniques/dijkstra.md",
    r"intuition_cheatsheet\.md$": "docs/foundations/dsa/patterns/intuition_cheatsheet.md",
    r"^scripts/(build|check)_cheatsheets\.py$": "scripts/check_cheatsheets.py",
    r"^dsa/probes/.*\.py$": "dsa/probes/p1.py",
    r"^decisions\.yml$": "decisions.yml",
}

STAGED_FILTER = re.compile(r'echo "\$STAGED" \| grep -q?E "([^"]*)"')


def split_top_level(pattern: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for ch in pattern:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    return parts + [current]


def hook_alternatives() -> set[str]:
    found: set[str] = set()
    for pattern in STAGED_FILTER.findall(HOOK.read_text(encoding="utf-8")):
        found.update(split_top_level(pattern))
    return found


def glob_to_regex(glob: str) -> re.Pattern:
    body = ""
    for token in re.split(r"(\*\*|\*)", glob):
        body += {"**": ".*", "*": "[^/]*"}.get(token, re.escape(token))
    return re.compile(body + r"\Z")


class ReplayHookTests(unittest.TestCase):
    def test_resolve_base(self):
        ancestors = {"marker", "before"}
        cases = [
            ("zero before, no marker", replay_hook.ZERO_SHA, None, {"before"}, "parent"),
            ("before unreachable, no marker", "gone", None, set(), "parent"),
            ("marker ancestor wins over a valid before", "before", "marker", ancestors, "marker"),
            ("marker not ancestor, before valid", "before", "marker", {"before"}, "before"),
            ("root commit", replay_hook.ZERO_SHA, None, set(), None),
        ]
        for label, before, marker, anc, expected in cases:
            with self.subTest(label):
                parent = None if label == "root commit" else "parent"
                got = replay_hook.resolve_base(before, "after", marker,
                                               is_ancestor=lambda sha, a=anc: sha in a,
                                               parent_of=lambda sha, p=parent: p)
                self.assertEqual(got, expected)

    def test_replay_stages_outputs(self):
        for label, rc in (("hook succeeds", 0), ("hook fails", 1)):
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp) / "repo"
                repo.mkdir()
                git = lambda *a: subprocess.run(  # noqa: E731
                    ["git", "-c", "commit.gpgsign=false", *a], cwd=repo, check=True,
                    capture_output=True, text=True, encoding="utf-8").stdout.strip()
                git("init", "-q")
                git("config", "user.name", "t")
                git("config", "user.email", "t@example.com")
                (repo / "in.txt").write_text("a\n", encoding="utf-8")
                git("add", "in.txt")
                git("commit", "-q", "-m", "A")
                first = git("rev-parse", "HEAD")
                (repo / "in.txt").write_text("b\n", encoding="utf-8")
                git("add", "in.txt")
                git("commit", "-q", "-m", "B")
                second = git("rev-parse", "HEAD")
                stub = Path(tmp) / "stub.py"
                stub.write_text(STUB_HOOK.format(rc=rc), encoding="utf-8")
                hook_cmd = [sys.executable, str(stub)]
                if rc:
                    with self.assertRaises(replay_hook.ReplayError):
                        replay_hook.replay(first, second, hook_cmd, repo)
                else:
                    paths = replay_hook.replay(first, second, hook_cmd, repo)
                    self.assertEqual(paths, ["out.json"])
                    self.assertIn("in.txt", (repo / "out.json").read_text(encoding="utf-8"))
                self.assertEqual(git("rev-parse", "HEAD"), second)

    def test_regenerate_paths_cover_hook(self):
        extracted = hook_alternatives()
        self.assertEqual(set(SAMPLES) | set(EXEMPT), extracted,
                         "classify new/removed hook alternatives in SAMPLES or EXEMPT")
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        trigger = doc.get("on", doc.get(True))
        globs = trigger["push"]["paths"]
        self.assertFalse([g for g in globs if "{" in g], "path filters do not support braces")
        regexes = [glob_to_regex(g) for g in globs]
        for alternative, sample in SAMPLES.items():
            with self.subTest(alternative):
                self.assertTrue(re.search(alternative, sample))
                self.assertTrue(any(r.match(sample) for r in regexes), f"{sample} not in paths")
        for output in ("dashboard/progress.json", "dashboard/manifest.json"):
            self.assertFalse(any(r.match(output) for r in regexes), output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
