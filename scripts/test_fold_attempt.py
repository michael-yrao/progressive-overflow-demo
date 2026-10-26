"""Tests for fold_attempt.py: header validation, the fold into a solution file, and --pending.

Stdlib unittest, temp repos only (never the real tree):

    python -m unittest scripts/test_fold_attempt.py
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import effort_budget
import fold_attempt
import fold_record
import links
import restore_history
import update_review_dates

DATE = "20261018"
ISO = "2026-10-18"
HEAD = '"""\n7. Demo Problem   ·   https://leetcode.com/problems/demo/\n"""\nfrom typing import List\n'
BANNER = fold_attempt.BANNER_LINE.format(iso=ISO)
OLD_BANNER = fold_attempt.BANNER_LINE.format(iso="2026-10-06")
OLD_METHOD = f"{OLD_BANNER}\n    def demo_20261006(self, n: int) -> int:\n        return n\n"
STUB = f"{BANNER}\n    def demo_{DATE}(self, n: int) -> int:\n        pass\n"
POINTER = f"{fold_attempt.new_problem.POINTER_PREFIX} in x — restored at session end"
ATTEMPT_BODY = "        # one number in, one out\n        return n + 1\n"
COMPLEXITY = {"time": "O(n)", "space": "O(1)", "whyTime": "one pass", "whySpace": "no extra storage"}
BIGO_YML = "schemaVersion: 1\nentries:\n  - lc: 7\n    time: O(n)\n    space: O(1)\n"
SCHEDULE_LINK = "[7 Demo Problem](../../../dsa/leetcode/demo/7_demo_problem.py)"


def header(**fields) -> str:
    base = {"complete": True, "rating": "clean", "tests": "5/5", "complexity": COMPLEXITY,
            "savedAt": "2026-10-18T09:00:00Z"}
    return fold_attempt.ATTEMPT_PREFIX + json.dumps({**base, **fields})


def attempt_text(**fields) -> str:
    return f"{header(**fields)}\nclass Solution:\n    def demo(self, n):\n{ATTEMPT_BODY}"


class Repo:
    """A temp repo: solution file, optional stash, inbox files."""

    def __init__(self, tmp: Path):
        self.root = tmp
        self.solution = tmp / "dsa/leetcode/demo/7_demo_problem.py"
        self.stash = tmp / "dsa/leetcode/.history/7_demo_problem.txt"
        self.write(tmp / fold_attempt.BIGO_MANIFEST, BIGO_YML)

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def inbox(self, date: str, text: str, number: str = "7") -> Path:
        return self.write(self.root / fold_attempt.INBOX / date / f"{number}_demo_problem.py", text)


class FoldAttemptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Repo(Path(self._tmp.name))

    def test_parse_header(self):
        cases = [
            ("valid complete", attempt_text(), False, None),
            ("valid in-progress", attempt_text(complete=False, rating=None, tests="2/5"), False, None),
            ("malformed JSON", f"{fold_attempt.ATTEMPT_PREFIX}{{nope\nclass Solution: pass", False,
             "not valid JSON"),
            ("complete, failing tests", attempt_text(tests="4/5"), False, "not all passing"),
            ("complete, no rating", attempt_text(rating=None), False, "no rating"),
            ("complete, no complexity", attempt_text(complexity=None), False, "needs exactly"),
            ("complete, unknown label", attempt_text(complexity={**COMPLEXITY, "time": "O(banana)"}), False,
             r"complexity\.time .* not a known"),
            ("provisional", attempt_text(rating=None, complexity=None), False, None),
            ("provisional, failing tests", attempt_text(rating=None, complexity=None, tests="4/5"), False,
             "not all passing"),
            ("coached, failing tests", attempt_text(tests="4/5"), True, None),
            ("coached, no complexity", attempt_text(tests="4/5", complexity=None), True, "needs exactly"),
            ("legacy recognition key is ignored",
             attempt_text(recognition={"picked": "X", "at": "2026-10-20T00:00:00Z"}), False, None),
            ("why at the cap", attempt_text(complexity={**COMPLEXITY, "whyTime": "x" * 2000}), False, None),
            ("why one char over the cap", attempt_text(complexity={**COMPLEXITY, "whyTime": "x" * 2001}),
             False, "whyTime"),
        ]
        for label, text, is_coached, refusal in cases:
            with self.subTest(label):
                if refusal is None:
                    fold_attempt.parse_header(text, is_coached=is_coached)
                    continue
                with self.assertRaisesRegex(fold_attempt.AttemptError, refusal):
                    fold_attempt.parse_header(text, is_coached=is_coached)

    def test_complexity_lines(self):
        manifest = self.repo.root / fold_attempt.BIGO_MANIFEST
        self.repo.write(manifest, BIGO_YML + "  - lc: 9\n    time: TODO\n    space: TODO\n")
        wrong_time = {**COMPLEXITY, "time": "O(n²)"}
        wrong_both = {**wrong_time, "space": "O(n)"}
        cases = [
            ("match", "7", COMPLEXITY,
             ["complexity: stated O(n)/O(1), matches bigo.yml; gate satisfied"]),
            ("one dimension wrong", "7", wrong_time,
             ["complexity queue row (add to complexity_gotchas.md cleanup queue): | T | "
              '**time**: said O(n²), reference O(n) (bigo.yml); why: "one pass". '
              "Verify against the learner's code cold | 2026-10-18 | |"]),
            ("both wrong", "7", wrong_both,
             ["complexity queue row (add to complexity_gotchas.md cleanup queue): | T | "
              "**time + space**: time said O(n²), reference O(n); space said O(n), reference O(1) "
              '(bigo.yml); why: "one pass" / "no extra storage". '
              "Verify against the learner's code cold | 2026-10-18 | |"]),
            ("no entry", "8", COMPLEXITY,
             ["complexity queue row (add to complexity_gotchas.md cleanup queue): | T | "
              "**time + space**: stated O(n)/O(1) with why; no reference bound in bigo.yml. "
              "Verify cold | 2026-10-18 | |"]),
            ("TODO entry is no reference", "9", COMPLEXITY,
             ["complexity queue row (add to complexity_gotchas.md cleanup queue): | T | "
              "**time + space**: stated O(n)/O(1) with why; no reference bound in bigo.yml. "
              "Verify cold | 2026-10-18 | |"]),
        ]
        for label, number, stated, expected in cases:
            with self.subTest(label):
                self.assertEqual(
                    fold_attempt.complexity_lines("T", number, stated, ISO, manifest), expected)

    def test_reference_bounds_remote(self):
        manifest = self.repo.root / fold_attempt.BIGO_MANIFEST
        url = "https://example.test/big-o.json"
        payload = json.dumps({"schemaVersion": 1, "entries": [
            {"lcNumber": 8, "variant": None, "time": "O(n log n)", "space": "O(n)"}]}).encode()

        def serving(body):
            return mock.Mock(side_effect=lambda _url, _timeout: body)

        def failing(error):
            return mock.Mock(side_effect=error)

        cases = [
            ("local hit wins", "7", url, serving(payload), ("O(n)", "O(1)"), 0),
            ("local miss, remote hit", "8", url, serving(payload), ("O(n log n)", "O(n)"), 1),
            ("remote 404", "8", url, failing(OSError("404")), None, 1),
            ("remote timeout", "8", url, failing(TimeoutError("slow")), None, 1),
            ("remote bad json", "8", url, serving(b"not json"), None, 1),
            ("remote wrong schema", "8", url, serving(b'{"schemaVersion": 2, "entries": []}'),
             None, 1),
            ("key absent", "8", "", serving(payload), None, 0),
        ]
        for label, number, key_url, opener, expected, calls in cases:
            with self.subTest(label):
                fold_attempt.remote_reference_index.cache_clear()
                self.assertEqual(
                    fold_attempt.reference_bounds(number, manifest, key_url, opener), expected)
                self.assertEqual(opener.call_count, calls)

    def test_fold(self):
        old_in_file = f"{HEAD}\n\nclass Solution:\n\n{OLD_METHOD}"
        stash_prior = OLD_METHOD
        stub_source = f"{HEAD}\n\nclass Solution:\n\n{STUB}\n{POINTER}\n"
        filled_stub_source = stub_source.replace("        pass\n", ATTEMPT_BODY)

        with self.subTest("history in the file: today on top, history intact"):
            self.repo.write(self.repo.solution, old_in_file)
            path = self.repo.inbox(DATE, attempt_text())
            fold_attempt.fold_file(self.repo.root, path)
            folded = self.repo.solution.read_text(encoding="utf-8")
            self.assertLess(folded.index(f"demo_{DATE}"), folded.index("demo_20261006"))
            self.assertIn(OLD_METHOD, folded)
            self.assertIn(f"{BANNER}\n    def demo_{DATE}(self, n):\n{ATTEMPT_BODY}", folded)
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

        with self.subTest("stash and empty stub: equals the restore_history result"):
            self.setUp()
            self.repo.write(self.repo.solution, stub_source)
            self.repo.write(self.repo.stash, stash_prior)
            fold_attempt.fold_file(self.repo.root, self.repo.inbox(DATE, attempt_text()))
            folded = self.repo.solution.read_text(encoding="utf-8")

            expected_repo = Repo(Path(self._tmp.name) / "expected")
            expected_repo.write(expected_repo.solution, filled_stub_source)
            expected_repo.write(expected_repo.stash, stash_prior)
            with fold_attempt.working_dir(expected_repo.root):
                restore_history.restore_stash(expected_repo.stash, DATE, False, [], [])
            self.assertEqual(folded, expected_repo.solution.read_text(encoding="utf-8"))
            self.assertFalse(self.repo.stash.exists())

        with self.subTest("a newer in-progress save survives the fold"):
            self.setUp()
            self.repo.write(self.repo.solution, old_in_file)
            older = self.repo.inbox("20261017", attempt_text())
            newer = self.repo.inbox("20261019", attempt_text(complete=False, rating=None, tests=None))
            fold_attempt.fold_file(self.repo.root, self.repo.inbox(DATE, attempt_text()))
            self.assertFalse(older.exists())
            self.assertTrue(newer.exists())
            with fold_attempt.working_dir(self.repo.root):
                self.assertRegex(fold_attempt.pending_lines(fold_attempt.INBOX)[0],
                                 r"20261019 +in-progress")

        with self.subTest("in-progress attempt: refused, stays in the inbox"):
            self.setUp()
            self.repo.write(self.repo.solution, old_in_file)
            path = self.repo.inbox(DATE, attempt_text(complete=False, rating=None, tests=None))
            with self.assertRaisesRegex(fold_attempt.AttemptError, "in progress"):
                fold_attempt.fold_file(self.repo.root, path)
            self.assertTrue(path.exists())
            self.assertEqual(self.repo.solution.read_text(encoding="utf-8"), old_in_file)

    def seed_world(self, *, reps: str = "2026-10-10", on_schedule: bool = True,
                   solution: str | None = None) -> None:
        """Tracker (CRLF) with row 7 due today, a week file, ledgers, config and a solution file."""
        root = self.repo.root
        row = (f"| Easy | [7. Demo Problem](https://leetcode.com/problems/demo/) | 🟡 | 0 | {ISO} | "
               f"2026-10-10 | {reps} |")
        self.tracker = self.repo.write(root / fold_attempt.TRACKER_FILE, "")
        self.tracker.write_bytes(f"| Difficulty |\r\n{row}\r\n".encode("utf-8"))
        self.schedules = root / "docs/foundations/schedules"
        row_7 = f"| {SCHEDULE_LINK} | 🟡 |  |  | Demo |\n" if on_schedule else ""
        self.schedule = self.repo.write(
            self.schedules / "20261012_schedule.md",
            f"| ▸ **Sun Oct 18** · ~1.0 units — x |  |  |  |  |\n{row_7}")
        self.repo.write(root / fold_attempt.MASTERY_DIR / "complexity_gotchas.md", "")
        self.repo.write(root / "cse.config.yml", "effort_budget: {}\n")
        self.repo.write(self.repo.solution, solution or f"{HEAD}\n\nclass Solution:\n\n{OLD_METHOD}")

    def run_in_world(self, *argv: str) -> tuple[int, str, str]:
        """`fold_attempt.main(argv)` (or `fold_all` when no argv) against the seeded world."""
        root = self.repo.root
        out, err = io.StringIO(), io.StringIO()
        with (mock.patch.object(fold_attempt, "REPO", root),
              mock.patch.object(effort_budget, "SCHEDULES", self.schedules),
              mock.patch.object(effort_budget, "CONFIG", root / "cse.config.yml"),
              mock.patch.object(links, "schedule_link_line", return_value=None),
              mock.patch.dict(update_review_dates.CONFIG, {"clean_streak1": 30, "graduate_at_streak": 3}),
              contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
            code = fold_attempt.main(list(argv)) if argv else fold_attempt.fold_all()
        return code, out.getvalue(), err.getvalue()

    def world_lines(self) -> tuple[str, str, str]:
        """(tracker row 7, schedule row 7, solution text) as they stand."""
        tracker = self.tracker.read_bytes().decode("utf-8").split("\r\n")[1]
        rows = [ln for ln in self.schedule.read_text(encoding="utf-8").split("\n") if "7 Demo Problem" in ln]
        return tracker, rows[0] if rows else "", self.repo.solution.read_text(encoding="utf-8")

    def test_site_rep_scenarios(self):
        provisional = attempt_text(rating=None, complexity=None).replace("return n + 1", "return n + 2")
        malformed = attempt_text().replace("class Solution:", "def helper():\n    pass\n\nclass Solution:")
        settle_args = ("--settle", "7", ISO, "--rating", "clean", "--complexity", json.dumps(COMPLEXITY))
        struck = f"| ~~{SCHEDULE_LINK}~~ | 🟡 | {{end}} | {{next}} | Demo |"
        logged = f" 🟡 | 0 | {ISO} | {ISO} | 2026-10-10, {ISO} |"
        rated = f" 🟢 | 1 | 2026-11-17 | {ISO} | 2026-10-10, {ISO} |"
        coached_source = f"{HEAD}\n\nclass Solution:\n\n{BANNER}\n    def demo_{DATE}(self, n):\n{ATTEMPT_BODY}\n{OLD_METHOD}"

        def refused_path() -> Path:
            return self.repo.root / fold_attempt.INBOX / DATE / fold_attempt.REFUSED_FILE

        def s1():
            self.repo.inbox(DATE, attempt_text())
            _, out, _ = self.run_in_world()
            row, sched, _ = self.world_lines()
            self.assertIn(f"folded: 7 🟢 {ISO}", out)
            self.assertTrue(row.endswith(rated))
            self.assertEqual(sched, struck.format(end="🟢", next="2026-11-17"))
            self.assertIn(b"\r\n", self.tracker.read_bytes())

        def s2():
            self.repo.inbox(DATE, provisional)
            _, out, _ = self.run_in_world()
            row, sched, _ = self.world_lines()
            self.assertIn(f"folded: 7 ❔ {ISO}", out)
            self.assertTrue(row.endswith(logged))
            self.assertEqual(sched, struck.format(end="❔", next=""))

        def provisional_then_rated():
            self.repo.inbox(DATE, provisional)
            self.run_in_world()
            self.repo.inbox(DATE, attempt_text())
            _, out, _ = self.run_in_world()
            row, sched, solution = self.world_lines()
            self.assertIn(f"folded: 7 🟢 {ISO}", out)
            self.assertTrue(row.endswith(rated))
            self.assertEqual(sched, struck.format(end="🟢", next="2026-11-17"))
            self.assertEqual(solution.count(f"def demo_{DATE}("), 1)
            self.assertIn("return n + 1", solution)
            self.assertNotIn("return n + 2", solution)

        def settle_cli():
            self.repo.inbox(DATE, provisional)
            self.run_in_world()
            code, _, _ = self.run_in_world(*settle_args)
            row, sched, solution = self.world_lines()
            self.assertEqual(code, 0)
            self.assertTrue(row.endswith(rated))
            self.assertEqual(sched, struck.format(end="🟢", next="2026-11-17"))
            self.assertIn("return n + 2", solution)

        def settle_without_provisional():
            code, _, err = self.run_in_world(*settle_args)
            self.assertEqual(code, 1)
            self.assertIn(f"no ❔ rep for 7 on {ISO}", err)

        def newer_in_progress_does_not_shadow():
            self.repo.inbox(DATE, attempt_text())
            newer = self.repo.inbox("20261019", attempt_text(complete=False, rating=None, tests=None))
            _, out, _ = self.run_in_world()
            self.assertIn(f"folded: 7 🟢 {ISO}", out)
            self.assertTrue(newer.exists())

        def duplicate_of_coach_logged_rep():
            self.seed_world(reps=f"2026-10-10, {ISO}", solution=coached_source)
            inbox = self.repo.inbox(DATE, attempt_text())
            before = self.world_lines()
            _, out, err = self.run_in_world()
            self.assertIn(f"duplicate: 7 {ISO}", out)
            self.assertNotIn("refused", err)
            self.assertFalse(inbox.exists())
            self.assertFalse(refused_path().exists())
            self.assertEqual(self.world_lines(), before)

        def duplicate_of_provisional_rep():
            self.repo.inbox(DATE, provisional)
            self.run_in_world()
            inbox = self.repo.inbox(DATE, provisional)
            before = self.world_lines()
            _, out, err = self.run_in_world()
            self.assertIn(f"duplicate: 7 {ISO}", out)
            self.assertNotIn("refused", err)
            self.assertFalse(inbox.exists())
            self.assertEqual(self.world_lines(), before)

        def refusal_reaches_refused_json():
            bad = self.repo.inbox(DATE, malformed)
            _, _, err = self.run_in_world()
            entries = json.loads(refused_path().read_text(encoding="utf-8"))
            self.assertEqual([e["number"] for e in entries], [7])
            self.assertIn(entries[0]["reason"], err)
            self.repo.inbox(DATE, attempt_text())
            self.run_in_world()
            self.assertFalse(bad.exists())
            self.assertFalse(refused_path().exists())

        def not_on_schedule_is_appended():
            self.seed_world(on_schedule=False)
            self.repo.inbox(DATE, attempt_text())
            _, _, err = self.run_in_world()
            row, sched, _ = self.world_lines()
            self.assertIn(f"schedule: appended 7 to {ISO}", err)
            self.assertTrue(row.endswith(rated))
            self.assertIn("🟢", sched)

        cases = [("S1 complete", s1), ("S2 provisional", s2),
                 ("provisional then rated settles", provisional_then_rated),
                 ("--settle CLI settles a provisional rep", settle_cli),
                 ("--settle CLI refuses without one", settle_without_provisional),
                 ("S3/S4 newer in-progress does not shadow", newer_in_progress_does_not_shadow),
                 ("S5 duplicate of a coach-logged rep", duplicate_of_coach_logged_rep),
                 ("S6 duplicate of a provisional rep", duplicate_of_provisional_rep),
                 ("S7 refusal reaches refused.json, success clears it", refusal_reaches_refused_json),
                 ("S12 not on the schedule is appended", not_on_schedule_is_appended)]
        for label, scenario in cases:
            with self.subTest(label):
                self.setUp()
                self.seed_world()
                scenario()

    def test_scaffold_text(self):
        root = Path("solutions")
        header = '"""\n7. {title}   ·   https://progressiveoverflow.com/practice/7\nPattern: {folder}\nDifficulty: {diff}\n"""\n\nclass Solution:\n'
        cases = [
            ("catalog hit", {"title": "Demo Problem", "difficulty": "Hard", "folder": "graphs"},
             Path("solutions/graphs/7_demo_problem.py"), header.format(title="Demo Problem", folder="graphs", diff="Hard"), ""),
            ("catalog miss", None, Path("solutions/other/7_demo_problem.py"),
             header.format(title="Demo Problem", folder="other", diff="Medium"),
             "scaffold: 7 not in curriculum; difficulty assumed Medium"),
        ]
        for label, entry, expected_path, expected_text, expected_note in cases:
            with self.subTest(label):
                self.assertEqual(fold_attempt.scaffold_text("7", "demo_problem", entry, root),
                                 (expected_path, expected_text, expected_note))

    def test_fold_all_isolates_failures(self):
        real_apply = fold_attempt.apply_record

        def record_error(repo, report):
            if report.number == "7":
                raise fold_record.RecordError("boom")
            return ["applied: ok"]

        def missing_ledger(repo, report):
            return real_apply(repo, report) if report.number == "7" else ["applied: ok"]

        cases = [("RecordError from apply_record", record_error, "boom"),
                 ("OSError from a missing ledger", missing_ledger, "No such file")]
        for label, apply_stub, reason in cases:
            with self.subTest(label):
                self.setUp()
                root = self.repo.root
                old = f"{HEAD}\n\nclass Solution:\n\n{OLD_METHOD}"
                good_solution = root / "dsa/leetcode/demo/9_demo_problem.py"
                self.repo.write(self.repo.solution, old)
                self.repo.write(good_solution, old.replace("7.", "9.", 1))
                bad = self.repo.inbox(DATE, attempt_text(), number="7")
                good = self.repo.inbox(DATE, attempt_text(), number="9")
                out, err = io.StringIO(), io.StringIO()
                with (mock.patch.object(fold_attempt, "REPO", root),
                      mock.patch.object(effort_budget, "SCHEDULES", root / "schedules"),
                      mock.patch.object(fold_attempt, "apply_record", apply_stub),
                      contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
                    self.assertEqual(fold_attempt.fold_all(), 0)
                self.assertEqual(self.repo.solution.read_text(encoding="utf-8"), old)
                self.assertTrue(bad.exists())
                self.assertIn(f"refused: {bad}", err.getvalue())
                self.assertIn(reason, err.getvalue())
                self.assertIn(BANNER, good_solution.read_text(encoding="utf-8"))
                self.assertFalse(good.exists())
                self.assertIn("folded: 9", out.getvalue())

    def test_pending_picks_newest_date_per_problem(self):
        self.repo.write(self.repo.solution, f"{HEAD}\n\nclass Solution:\n\n{OLD_METHOD}")
        self.repo.inbox("20261016", attempt_text())
        self.repo.inbox("20261018", attempt_text(complete=False, rating=None, tests=None))
        self.repo.inbox("20261017", attempt_text(), number="9")
        with fold_attempt.working_dir(self.repo.root):
            report = fold_attempt.pending_lines(fold_attempt.INBOX)
        self.assertEqual(len(report), 2)
        self.assertRegex(report[0], r"^\s*7 .*20261018 +in-progress +solution file: yes$")
        self.assertRegex(report[1], r"^\s*9 .*20261017 +complete +solution file: no$")


if __name__ == "__main__":
    unittest.main()
