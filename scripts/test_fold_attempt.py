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
import recognition_grade
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
PICK = {"picked": "Two Pointers", "at": "2026-10-18T08:59:00Z"}
BIGO_YML = "schemaVersion: 1\nentries:\n  - lc: 7\n    time: O(n)\n    space: O(1)\n"


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
            ("coached, failing tests", attempt_text(tests="4/5"), True, None),
            ("coached, no complexity", attempt_text(tests="4/5", complexity=None), True, "needs exactly"),
            ("valid recognition", attempt_text(recognition=PICK), False, None),
            ("recognition wrong type", attempt_text(recognition="Two Pointers"), False, "needs exactly"),
            ("recognition picked too long",
             attempt_text(recognition={**PICK, "picked": "x" * 201}), False, r"recognition\.picked is over"),
        ]
        for label, text, is_coached, refusal in cases:
            with self.subTest(label):
                if refusal is None:
                    parsed = fold_attempt.parse_header(text, is_coached=is_coached)
                    if label == "valid recognition":
                        self.assertEqual(parsed.recognition, PICK)
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

    def test_has_recognition(self):
        with_pick = fold_attempt.parse_header(attempt_text(recognition=PICK), is_coached=False)
        no_pick = fold_attempt.parse_header(attempt_text(), is_coached=False)
        code, comment = ("        return n",), ("        # shape first", "        return n")
        cases = [
            ("header pick, body opens with code", with_pick, code, True),
            ("no pick, body opens with a comment", no_pick, comment, True),
            ("neither", no_pick, code, False),
        ]
        for label, parsed, body, expected in cases:
            with self.subTest(label):
                self.assertEqual(fold_attempt.has_recognition(parsed, body), expected)

    def test_fold_grades_pick(self):
        declared = "techniques:\n  - name: Demo Technique\n    problems:\n      - number: 7\n"
        self.repo.write(self.repo.root / fold_attempt.MASTERY_DIR / "techniques.yml", declared)
        self.repo.write(self.repo.solution, f"{HEAD}\n\nclass Solution:\n\n{OLD_METHOD}")
        path = self.repo.inbox(DATE, attempt_text(
            recognition={"picked": "Demo Technique", "at": "2026-10-18T08:59:00Z"}))
        report = fold_attempt.fold_file(self.repo.root, path)
        self.assertEqual(report.pick_grade, recognition_grade.PickGrade("hit", "technique", "Demo Technique"))
        self.assertEqual(report.picked, "Demo Technique")
        self.assertIn("recognition: pick hit (technique)", report.lines)

    def test_apply_writes_tracker_and_schedule(self):
        root = self.repo.root
        row_in = "| Easy | [7. Demo Problem](https://leetcode.com/problems/demo/) | 🟡 | 0 | 2026-10-18 | 2026-10-10 | 2026-10-10 |"
        row_out = "| Easy | [7. Demo Problem](https://leetcode.com/problems/demo/) | 🟢 | 1 | 2026-11-17 | 2026-10-18 | 2026-10-10, 2026-10-18 |"
        link = "[7 Demo Problem](../../../dsa/leetcode/demo/7_demo_problem.py)"
        mastery = root / fold_attempt.MASTERY_DIR
        schedules = root / "docs/foundations/schedules"
        tracker = self.repo.write(root / fold_attempt.TRACKER_FILE, "")
        tracker.write_bytes(f"| Difficulty |\r\n{row_in}\r\n".encode("utf-8"))
        schedule = self.repo.write(
            schedules / "20261012_schedule.md",
            f"| ▸ **Sun Oct 18** · ~1.0 units — x |  |  |  |  |\n| {link} | 🟡 |  |  | Demo |\n")
        self.repo.write(mastery / "complexity_gotchas.md", "")
        self.repo.write(mastery / "recognition_gotchas.md", "")
        self.repo.write(root / "cse.config.yml", "effort_budget: {}\n")
        self.repo.write(self.repo.solution, f"{HEAD}\n\nclass Solution:\n\n{OLD_METHOD}")
        path = self.repo.inbox(DATE, attempt_text())
        config = {"clean_streak1": 30, "graduate_at_streak": 3}
        with (mock.patch.object(fold_attempt, "REPO", root),
              mock.patch.object(effort_budget, "SCHEDULES", schedules),
              mock.patch.object(effort_budget, "CONFIG", root / "cse.config.yml"),
              mock.patch.object(links, "schedule_link_line", return_value=None),
              mock.patch.dict(update_review_dates.CONFIG, config),
              contextlib.redirect_stdout(io.StringIO()) as out):
            self.assertEqual(fold_attempt.main(["--apply", str(path)]), 0)
        self.assertIn(f"applied: schedule: struck 7 on {ISO}", out.getvalue())
        tracker_lines = tracker.read_bytes().decode("utf-8").split("\r\n")
        self.assertEqual(tracker_lines, ["| Difficulty |", row_out, ""])
        struck = f"| ~~{link}~~ | 🟡 | 🟢 | 2026-11-17 | Demo |"
        self.assertEqual(schedule.read_text(encoding="utf-8").split("\n")[1], struck)

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
