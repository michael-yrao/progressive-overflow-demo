"""Fold a practice attempt the site saved into the repo's solution file.

The site's practice page saves attempts to `dsa/attempts/<YYYYMMDD>/<n>_<name>.py`. A rep marked
complete there arrives with the learner's own rating; this folds its method into
`dsa/leetcode/<category>/<n>_<snake>.py` the way a completed in-chat rep would end up, then
prints what the coach still applies by hand. See decisions.yml `practice-site-reps-oct18`.

    python scripts/fold_attempt.py --pending                          # list the inbox; writes nothing
    python scripts/fold_attempt.py dsa/attempts/20261018/261_graph_valid_tree.py
    python scripts/fold_attempt.py --apply dsa/attempts/20261018/261_graph_valid_tree.py
    python scripts/fold_attempt.py --apply --all                      # every complete inbox entry

`--apply` also writes what the coach otherwise applies by hand (tracker row, schedule row, the
gotchas ledgers; see fold_record.py) and prints each change prefixed `applied: `.

File contract: line 1 is `# po-attempt: {"complete": bool, "rating": null|"clean"|"shaky"|"blank",
"tests": "<p>/<t>"|null, "complexity": null|{"time", "space", "whyTime", "whySpace"}, "savedAt": ISO};
a complete header carries all four complexity strings (time/space from export_bigo's COMPLEXITY_POOL).
The rest is a `class Solution:` holding one method. The fold judges the stated bounds against
`dashboard/bigo.yml` and prints the verdict (see decisions.yml `practice-site-complexity-oct19`).

The fold puts the method in as `<method>_<YYYYMMDD>` (the inbox folder's date) under the attempt
banner, newest on top. When the problem has a `.history` stash the result is exactly what
`restore_history.py` produces, because that script's own `restore_stash` does the merge.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import functools
import io
import json
import os
import re
import sys
import tokenize
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

import _console
import curriculum
import export_bigo
import links
import new_problem
import recognition_grade
import restore_history

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
INBOX = Path("dsa/attempts")
ATTEMPT_PREFIX = "# po-attempt: "
INBOX_FILE = re.compile(r"^(\d{8})/(\d+)_([a-z0-9_]+)\.py$")
TESTS_FIELD = re.compile(r"^(\d+)/(\d+)$")
RATING_EMOJI = {"clean": "🟢", "shaky": "🟡", "blank": "🔴"}
BANNER_LINE = "    # ── Attempt · {iso} ──────────────"
SCAFFOLD_FALLBACK_FOLDER = "other"
SCAFFOLD_FALLBACK_DIFFICULTY = "Medium"
SCAFFOLD_HEADER = ('"""\n{number}. {title}   ·   {url}\nPattern: {folder}\nDifficulty: {difficulty}\n"""\n'
                   "\nclass Solution:\n")
SCAFFOLD_MISS_NOTE = "scaffold: {number} not in curriculum; difficulty assumed {difficulty}"
TITLE_LINE = re.compile(r"^(\d+)\.\s*(.+?)\s{2,}·")
CLASS_INDENT = "    "
STATUS_COMPLETE = "complete"
STATUS_IN_PROGRESS = "in-progress"
STATUS_MALFORMED = "malformed"
BIGO_MANIFEST = Path("dashboard/bigo.yml")
CONFIG_NAME = "cse.config.yml"
REFERENCE_URL_KEY = "bigo_reference_url"
REFERENCE_SCHEMA_VERSION = 1
Opener = Callable[[str, float], bytes]
MASTERY_DIR = Path("docs/foundations/dsa/mastery")
TRACKER_FILE = MASTERY_DIR / "dsa_progress.md"
COMPLEXITY_FILE = MASTERY_DIR / "complexity_gotchas.md"
RECOGNITION_FILE = MASTERY_DIR / "recognition_gotchas.md"
APPLIED_PREFIX = "applied: "
COMPLEXITY_KEYS = ("time", "space", "whyTime", "whySpace")
LABEL_MAX_CHARS = 200
WHY_MAX_CHARS = 500
COMPLEXITY_MAX_CHARS = {"time": LABEL_MAX_CHARS, "space": LABEL_MAX_CHARS,
                        "whyTime": WHY_MAX_CHARS, "whySpace": WHY_MAX_CHARS}
RECOGNITION_KEYS = ("picked", "at")
PICKED_MAX_CHARS = LABEL_MAX_CHARS
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$")


class AttemptError(Exception):
    """A refusal: the message is what the learner or coach reads."""


@dataclass(frozen=True)
class AttemptHeader:
    complete: bool
    rating: str | None
    tests: str | None
    saved_at: str
    complexity: dict[str, str] | None = None
    recognition: dict[str, str] | None = None


@dataclass(frozen=True)
class Method:
    name: str
    head_lines: tuple[str, ...]
    body_lines: tuple[str, ...]


@dataclass(frozen=True)
class InboxFile:
    path: Path
    date: str
    number: str
    name: str


def parse_header(text: str, *, is_coached: bool = False) -> AttemptHeader:
    """The validated header of an attempt file. Raises AttemptError on anything the
    contract forbids. An in-progress header is returned as it is; a complete one must carry
    a rating and every test passing (a coached one, only a tests count)."""
    first = text.split("\n", 1)[0]
    if not first.startswith(ATTEMPT_PREFIX):
        raise AttemptError(f"first line is not a `{ATTEMPT_PREFIX.strip()}` header")
    try:
        raw = json.loads(first[len(ATTEMPT_PREFIX):])
    except json.JSONDecodeError as exc:
        raise AttemptError(f"header is not valid JSON ({exc.msg})") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("complete"), bool):
        raise AttemptError("header needs a boolean `complete`")
    rating, tests = raw.get("rating"), raw.get("tests")
    if rating is not None and rating not in RATING_EMOJI:
        raise AttemptError(f"unknown rating {rating!r}")
    if tests is not None and not (isinstance(tests, str) and TESTS_FIELD.match(tests)):
        raise AttemptError(f"tests {tests!r} is not '<passed>/<total>'")
    complexity = parse_complexity(raw.get("complexity"), raw["complete"])
    recognition = parse_recognition(raw.get("recognition"))
    header = AttemptHeader(raw["complete"], rating, tests, str(raw.get("savedAt") or ""), complexity,
                           recognition=recognition)
    if header.complete:
        require_complete_fields(header, is_coached=is_coached)
    return header


def parse_complexity(raw: object, is_complete: bool) -> dict[str, str] | None:
    """The validated `complexity` object of a complete header; None for an in-progress one
    (whatever it carries). Raises AttemptError naming the offending field."""
    if not is_complete:
        return None
    if not isinstance(raw, dict) or set(raw) != set(COMPLEXITY_KEYS):
        raise AttemptError(f"marked complete but `complexity` needs exactly {list(COMPLEXITY_KEYS)}")
    for key in COMPLEXITY_KEYS:
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            raise AttemptError(f"complexity.{key} must be a non-empty string")
        if len(value) > COMPLEXITY_MAX_CHARS[key]:
            raise AttemptError(f"complexity.{key} is over {COMPLEXITY_MAX_CHARS[key]} characters")
    for key in ("time", "space"):
        if raw[key] not in export_bigo.COMPLEXITY_POOL:
            raise AttemptError(f"complexity.{key} {raw[key]!r} is not a known complexity label")
    return {key: raw[key] for key in COMPLEXITY_KEYS}


def parse_recognition(raw: object) -> dict[str, str] | None:
    """The validated `recognition` pick of any header; None when the key is absent.
    Raises AttemptError naming the offending field."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != set(RECOGNITION_KEYS):
        raise AttemptError(f"`recognition` needs exactly {list(RECOGNITION_KEYS)}")
    picked, at = raw["picked"], raw["at"]
    if not isinstance(picked, str) or not picked.strip():
        raise AttemptError("recognition.picked must be a non-empty string")
    if len(picked) > PICKED_MAX_CHARS:
        raise AttemptError(f"recognition.picked is over {PICKED_MAX_CHARS} characters")
    if not isinstance(at, str) or not ISO_UTC.match(at):
        raise AttemptError("recognition.at must be an ISO UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AttemptError(f"recognition.at {at!r} is not a real timestamp") from exc
    return {"picked": picked, "at": at}


def require_complete_fields(header: AttemptHeader, *, is_coached: bool = False) -> None:
    """A coached rep already passed the in-chat gates, so only its `passed == total` check is skipped."""
    if header.rating is None:
        raise AttemptError("marked complete but carries no rating")
    match = TESTS_FIELD.match(header.tests or "")
    if not match or int(match.group(2)) == 0:
        raise AttemptError(f"marked complete but tests are {header.tests!r}, not all passing")
    if not is_coached and match.group(1) != match.group(2):
        raise AttemptError(f"marked complete but tests are {header.tests!r}, not all passing")


def parse_inbox_name(rel: str) -> tuple[str, str, str] | None:
    """(date, number, name) of a path relative to the inbox, or None if it is off-contract."""
    match = INBOX_FILE.match(rel)
    return (match.group(1), match.group(2), match.group(3)) if match else None


def list_inbox(inbox: Path) -> list[InboxFile]:
    """Every contract-shaped file under `inbox`, oldest date first."""
    found = []
    for path in sorted(inbox.glob("*/*.py")) if inbox.is_dir() else []:
        parts = parse_inbox_name(path.relative_to(inbox).as_posix())
        if parts:
            found.append(InboxFile(path, *parts))
    return found


def newest_per_problem(files: list[InboxFile]) -> list[InboxFile]:
    """The newest file (by date folder) of each problem number, ordered by number."""
    newest: dict[str, InboxFile] = {}
    for item in sorted(files, key=lambda f: f.date):
        newest[item.number] = item
    return sorted(newest.values(), key=lambda f: int(f.number))


def attempt_status(text: str) -> str:
    try:
        return STATUS_COMPLETE if parse_header(text).complete else STATUS_IN_PROGRESS
    except AttemptError:
        return STATUS_MALFORMED


def find_solution(number: str) -> Path | None:
    """Solution file by number, cwd-relative like restore_history (glob `<root>/*/<n>_*.py`)."""
    return restore_history.find_source(number)


def pending_lines(inbox: Path) -> list[str]:
    """One report line per problem: newest attempt, its status, whether a solution file exists."""
    lines = []
    for item in newest_per_problem(list_inbox(inbox)):
        status = attempt_status(item.path.read_text(encoding="utf-8"))
        has_solution = "yes" if find_solution(item.number) else "no"
        lines.append(f"{item.number:>5}  {item.name}  {item.date}  {status:<11}  "
                     f"solution file: {has_solution}")
    return lines


def signature_end_row(code: str, def_row: int) -> int:
    """1-based row of the colon that ends the `def` starting at `def_row` (depth-0 ':')."""
    depth, seen_def = 0, False
    for tok in tokenize.generate_tokens(io.StringIO(code).readline):
        if tok.start[0] < def_row:
            continue
        if tok.type == tokenize.NAME and tok.string == "def":
            seen_def = True
        elif seen_def and tok.type == tokenize.OP:
            depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(tok.string, 0)
            if tok.string == ":" and depth == 0:
                return tok.start[0]
    raise AttemptError("could not find the end of the method signature")


def extract_method(code: str) -> Method:
    """The one method of the attempt's `class Solution`, as verbatim lines."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise AttemptError(f"attempt does not parse ({exc.msg}, line {exc.lineno})") from exc
    others = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom, ast.ClassDef))]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if others or len(classes) != 1 or classes[0].name != "Solution":
        raise AttemptError("only a lone `class Solution:` is folded; fold other layouts by hand")
    methods = [n for n in classes[0].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(methods) != 1 or len(classes[0].body) != 1:
        raise AttemptError("attempt's Solution must hold exactly one method; fold by hand")
    node = methods[0]
    lines = code.split("\n")
    colon_row = signature_end_row(code, node.lineno)
    body = lines[colon_row:node.end_lineno]
    while body and not body[-1].strip():
        body.pop()
    return Method(node.name, tuple(lines[node.lineno - 1:colon_row]), tuple(body))


def has_top_comment(body_lines: tuple[str, ...]) -> bool:
    """True when the first non-blank line of the method body is a comment (the recognition call)."""
    first = next((ln for ln in body_lines if ln.strip()), "")
    return first.lstrip().startswith("#")


def has_recognition(header: AttemptHeader, body_lines: tuple[str, ...]) -> bool:
    """True when the attempt carries a recognition call: a header pick or a top-of-body comment."""
    return header.recognition is not None or has_top_comment(body_lines)


def dated_head(head_lines: tuple[str, ...], name: str, stamp: str) -> list[str]:
    first = re.sub(rf"\bdef\s+{re.escape(name)}\b", f"def {name}_{stamp}", head_lines[0], count=1)
    return [first, *head_lines[1:]]


def find_dated_def(lines: list[str], stamp: str) -> int | None:
    head = re.compile(restore_history.DATED_ATTEMPT.format(stamp=re.escape(stamp)))
    return next((i for i, ln in enumerate(lines) if head.match(ln)), None)


def block_end(lines: list[str], start: int) -> int:
    """Index just past the last non-blank line of the block that starts at `start`."""
    base, end = restore_history.indent_of(lines[start]), start + 1
    for i in range(start + 1, len(lines)):
        if not lines[i].strip():
            continue
        if restore_history.indent_of(lines[i]) <= base:
            break
        end = i + 1
    return end


def stub_head_end(lines: list[str], start: int) -> int:
    """Index just past the stub's signature (a signature may span lines)."""
    end = start
    while end < len(lines) and not lines[end].split("#")[0].rstrip().endswith(":"):
        end += 1
    return end + 1


def insert_method(lines: list[str], method: Method, stamp: str, iso: str) -> list[str]:
    """`lines` with today's method on top of `class Solution`, under its banner."""
    cls = new_problem.solution_class_start(lines)
    if cls is None:
        raise AttemptError("solution file has no `class Solution:`; fold by hand")
    block = ["", BANNER_LINE.format(iso=iso), *dated_head(method.head_lines, method.name, stamp),
             *method.body_lines]
    after = lines[cls + 1:]
    separator = [] if after and not after[0].strip() else [""]
    return lines[:cls + 1] + block + separator + after


def fill_stub(lines: list[str], at: int, method: Method) -> list[str]:
    """`lines` with the empty dated stub at `at` given the attempt's body; its signature stays."""
    end = block_end(lines, at)
    return lines[:stub_head_end(lines, at)] + list(method.body_lines) + lines[end:]


def fold_into_source(source: str, attempt: Method, stamp: str, iso: str) -> str:
    """The solution file text with today's attempt in: a filled empty stub, else a new method."""
    lines = source.split("\n")
    at = find_dated_def(lines, stamp)
    if at is None:
        merged = insert_method(lines, attempt, stamp, iso)
    elif restore_history.attempt_has_body(lines, stamp):
        raise AttemptError(f"solution file already holds an attempt dated {iso}")
    else:
        merged = fill_stub(lines, at, attempt)
    return "\n".join(merged)


def tracker_line(number: str, rating: str, iso: str) -> str:
    return (f"tracker row {number}: Comfort -> {RATING_EMOJI[rating]}; Latest Rep Date -> {iso}; "
            f"add {iso} to Rep Dates (Streak and Next Review per spaced-repetition.md)")


def solution_title(source: str, number: str, fallback: str) -> str:
    """`<n> <Title>` from the file's docstring line, else the file name."""
    for line in source.split("\n", 3)[:3]:
        match = TITLE_LINE.match(line)
        if match:
            return f"{match.group(1)} {match.group(2)}"
    return f"{number} {fallback}"


def read_reference_url(repo: Path) -> str:
    """`automation.bigo_reference_url` from the repo's config; empty (no fetch) when absent."""
    path = repo / CONFIG_NAME
    if not path.is_file():
        return ""
    block = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("automation")
    return str(block.get(REFERENCE_URL_KEY) or "") if isinstance(block, dict) else ""


@functools.cache
def remote_reference_index(url: str, opener: Opener | None) -> dict[int, tuple[str, str]] | None:
    """lcNumber -> (time, space) of the first non-TODO entry in the published Big-O reference, or
    None on any network, JSON or schema failure. Fetched at most once per process and url."""
    import build_week  # noqa: PLC0415 -- lazy like effort_budget: it imports that module
    fetch = opener or build_week.urlopen_bytes
    try:
        data = json.loads(fetch(url, build_week.SITE_INDEX_TIMEOUT_S))
        if data["schemaVersion"] != REFERENCE_SCHEMA_VERSION:
            return None
        index: dict[int, tuple[str, str]] = {}
        for entry in data["entries"]:
            bounds = (str(entry["time"]), str(entry["space"]))
            if not any(export_bigo.is_todo(bound) for bound in bounds):
                index.setdefault(int(entry["lcNumber"]), bounds)
        return index
    except (OSError, ValueError, KeyError, TypeError):
        return None


def reference_bounds(number: str, manifest: Path, url: str = "",
                     opener: Opener | None = None) -> tuple[str, str] | None:
    """(time, space) of the first bigo.yml entry for `number` with neither bound a TODO; else the
    published reference's, when `url` is set; else None."""
    try:
        entries = export_bigo.load_manifest(manifest)["entries"]
    except export_bigo.es.ShowcaseError as exc:
        raise AttemptError(f"cannot read {manifest}: {exc}") from exc
    for entry in entries:
        bounds = (str(entry.get("time")), str(entry.get("space")))
        if str(entry.get("lc")) == number and not any(export_bigo.is_todo(b) for b in bounds):
            return bounds
    if not url:
        return None
    index = remote_reference_index(url, opener)
    return index.get(int(number)) if index else None


QUEUE_PREFIX = "complexity queue row (add to complexity_gotchas.md cleanup queue): "


def queue_row(title: str, cell: str, iso: str) -> str:
    return f"{QUEUE_PREFIX}| {title} | {cell} | {iso} | |"


def mismatch_cell(stated: dict[str, str], reference: tuple[str, str]) -> str:
    wrong = [(dim, stated[dim], ref, stated[f"why{dim.capitalize()}"])
             for dim, ref in zip(("time", "space"), reference) if stated[dim] != ref]
    verify = "Verify against the learner's code cold"
    if len(wrong) == 1:
        dim, said, ref, why = wrong[0]
        return f'**{dim}**: said {said}, reference {ref} (bigo.yml); why: "{why}". {verify}'
    (_, t_said, t_ref, t_why), (_, s_said, s_ref, s_why) = wrong
    return (f"**time + space**: time said {t_said}, reference {t_ref}; space said {s_said}, "
            f'reference {s_ref} (bigo.yml); why: "{t_why}" / "{s_why}". {verify}')


def complexity_lines(title: str, number: str, stated: dict[str, str], iso: str,
                     manifest: Path = BIGO_MANIFEST, *, url: str = "",
                     opener: Opener | None = None) -> list[str]:
    """The fold's complexity verdict: a satisfied-gate line on a match, else one queue row."""
    reference = reference_bounds(number, manifest, url, opener)
    pair = (stated["time"], stated["space"])
    if reference is None:
        cell = (f"**time + space**: stated {pair[0]}/{pair[1]} with why; "
                f"no reference bound in bigo.yml. Verify cold")
        return [queue_row(title, cell, iso)]
    if pair == reference:
        return [f"complexity: stated {pair[0]}/{pair[1]}, matches bigo.yml; gate satisfied"]
    return [queue_row(title, mismatch_cell(stated, reference), iso)]


@dataclass(frozen=True)
class FoldReport:
    solution: Path
    removed: tuple[Path, ...]
    lines: tuple[str, ...]
    notes: tuple[str, ...]
    number: str = ""
    title: str = ""
    rating: str = ""
    iso: str = ""
    has_recognition: bool = True
    queue_rows: tuple[str, ...] = ()
    scaffold_note: str = ""
    picked: str = ""
    pick_grade: recognition_grade.PickGrade | None = None


def humanized(name: str) -> str:
    import update_review_dates  # noqa: PLC0415 -- reads cse.config.yml from the cwd on first import
    return update_review_dates.humanize_raw_name(name)


def scaffold_path(number: str, name: str, entry: dict | None, root: Path) -> Path:
    """Where a missing solution file is created: `<root>/<folder>/<n>_<name>.py`."""
    folder = entry["folder"] if entry else SCAFFOLD_FALLBACK_FOLDER
    return root / folder / f"{number}_{name}.py"


def scaffold_text(number: str, name: str, entry: dict | None, root: Path) -> tuple[Path, str, str]:
    """(path, file text, note) of a solution file the catalog entry describes. `entry` None (the
    catalog lacks the number): folder `other`, a humanized title, an assumed difficulty, a note."""
    title = entry["title"] if entry else humanized(name)
    difficulty = (entry["difficulty"] if entry else "") or SCAFFOLD_FALLBACK_DIFFICULTY
    folder = entry["folder"] if entry else SCAFFOLD_FALLBACK_FOLDER
    text = SCAFFOLD_HEADER.format(
        number=number, title=title, url=links.SITE_PRACTICE_URL_TEMPLATE.format(number=number),
        folder=folder, difficulty=difficulty)
    note = "" if entry else SCAFFOLD_MISS_NOTE.format(number=number, difficulty=difficulty)
    return scaffold_path(number, name, entry, root), text, note


def create_scaffold(number: str, name: str) -> tuple[Path, str]:
    """Create the missing solution file from the curriculum (cwd = the repo); (path, note)."""
    path, text, note = scaffold_text(number, name, curriculum.catalog_entry(int(number)),
                                     new_problem.source_root())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path, note


def solution_target(number: str, name: str) -> Path:
    """The solution file for `number`: the existing one, else the scaffold path (cwd = the repo)."""
    return find_solution(number) or scaffold_path(
        number, name, curriculum.catalog_entry(int(number)), new_problem.source_root())


def write_merged(src: Path, text: str, stamp: str) -> tuple[list[str], list[str]]:
    """Write the folded text; with a `.history` stash, let restore_history merge it in."""
    src.write_text(text, encoding="utf-8", newline="\n")
    stash = new_problem.history_dir() / f"{src.stem}.txt"
    if not stash.exists():
        return [], []
    warnings, renames = [], []
    reason = restore_history.restore_stash(stash, stamp, False, warnings, renames)
    if reason:
        raise AttemptError(f"restore_history kept the stash out: {reason}")
    return warnings, renames


def remove_problem_files(inbox: Path, number: str, date: str) -> tuple[Path, ...]:
    """Delete the inbox files of problem `number` dated `date` or earlier (a newer save
    stays), then the date folders left empty."""
    removed = []
    for item in list_inbox(inbox):
        if item.number == number and item.date <= date:
            item.path.unlink()
            removed.append(item.path)
    for folder in {p.parent for p in removed}:
        if not any(folder.iterdir()):
            folder.rmdir()
    return tuple(removed)


def fold_file(repo: Path, attempt_path: Path, reference_url: str = "", *, is_coached: bool = False) -> FoldReport:
    """Fold one complete attempt into its solution file. Cwd-relative lookups run inside `repo`.
    `reference_url` (see read_reference_url) is the Big-O reference fallback; empty = none.
    `is_coached` waives only the passed == total check (see require_complete_fields)."""
    inbox = repo / INBOX
    resolved, root = attempt_path.resolve(), inbox.resolve()
    parts = parse_inbox_name(resolved.relative_to(root).as_posix()) \
        if resolved.is_relative_to(root) else None
    if parts is None:
        raise AttemptError(f"{attempt_path} is not under {INBOX}/<YYYYMMDD>/<n>_<name>.py")
    date, number, name = parts
    iso = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")
    text = attempt_path.read_text(encoding="utf-8")
    header = parse_header(text, is_coached=is_coached)
    if not header.complete:
        raise AttemptError("attempt is in progress; it stays in the inbox")
    method = extract_method(text)
    with working_dir(repo):
        src, scaffold_note = find_solution(number), ""
        if src is None:
            src, scaffold_note = create_scaffold(number, name)
        source = src.read_text(encoding="utf-8")
        title = solution_title(source, number, src.resolve().stem)
        verdict = complexity_lines(title, number, header.complexity, iso, repo / BIGO_MANIFEST,
                                   url=reference_url)
        folded = fold_into_source(source, method, date, iso)
        warnings, renames = write_merged(src, folded, date)
        removed = remove_problem_files(inbox, number, date)
        solution = src.resolve()
    lines = [tracker_line(number, header.rating or "", iso), *verdict]
    recognized = has_recognition(header, method.body_lines)
    picked, pick_grade = "", None
    if header.recognition is not None:
        picked = header.recognition["picked"]
        pick_grade = recognition_grade.grade_pick(
            picked, number, solution.parent.name,
            *recognition_grade.load_declarations(repo / MASTERY_DIR / "techniques.yml"))
        lines.append(f"recognition: pick {pick_grade.result} ({pick_grade.basis})")
    if not recognized:
        lines.append("recognition: missing")
    queue_rows = tuple(ln[len(QUEUE_PREFIX):] for ln in verdict if ln.startswith(QUEUE_PREFIX))
    return FoldReport(solution, removed, tuple(lines), tuple(warnings + renames), number, title,
                      header.rating or "", iso, recognized, queue_rows, scaffold_note,
                      picked=picked, pick_grade=pick_grade)


@contextlib.contextmanager
def working_dir(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@dataclass(frozen=True)
class Doc:
    """A text file as read: LF text plus the line ending to write it back with."""
    path: Path
    text: str
    eol: str


def read_doc(path: Path) -> Doc:
    raw = path.read_bytes().decode("utf-8")
    return Doc(path, raw.replace("\r\n", "\n"), "\r\n" if "\r\n" in raw else "\n")


def write_doc(doc: Doc, new_text: str) -> None:
    if new_text != doc.text:
        doc.path.write_bytes(new_text.replace("\n", doc.eol).encode("utf-8"))


def forward_schedule(out, number: str, schedule_path: Path | None,
                     pricing_config: dict) -> tuple[Doc, str] | None:
    """(doc, text) of another live week file that holds the next review's day, with the review
    seated there; None when no such file exists or there is nothing to seat."""
    import effort_budget  # noqa: PLC0415 -- see apply_record
    import fold_record  # noqa: PLC0415
    if not out.next_iso:
        return None
    next_path = effort_budget.find_schedule(datetime.strptime(out.next_iso, "%Y-%m-%d").date())
    if next_path is None or next_path == schedule_path or next_path.parent != effort_budget.SCHEDULES:
        return None
    doc = read_doc(next_path)
    week_start = datetime.strptime(next_path.name[:8], "%Y%m%d").date()
    text = fold_record.seat_forward(doc.text, week_start, out, number, pricing_config)
    return (doc, text) if text != doc.text else None


def apply_record(repo: Path, report: FoldReport) -> list[str]:
    """Write the tracker, schedule and gotchas changes a folded rep calls for; the `applied:` lines."""
    with working_dir(repo):
        # Imported here: update_review_dates reads cse.config.yml from the cwd when first imported.
        import effort_budget
        import fold_record
        import update_review_dates
        day = datetime.strptime(report.iso, "%Y-%m-%d").date()
        tracker, complexity, recognition = (read_doc(repo / rel) for rel in
                                            (TRACKER_FILE, COMPLEXITY_FILE, RECOGNITION_FILE))
        schedule_path = effort_budget.find_schedule(day)
        schedule = read_doc(schedule_path) if schedule_path else None
        week_start = datetime.strptime(schedule_path.name[:8], "%Y%m%d").date() if schedule else None
        link_line = links.schedule_link_line(report.number, site_numbers=frozenset({int(report.number)}))
        pricing_config = effort_budget.load_config()
        inputs = fold_record.RecordInputs(
            tracker.text, schedule.text if schedule else None, week_start, complexity.text,
            recognition.text, fold_record.schedule_cell(link_line, report.title),
            update_review_dates.load_holds(), update_review_dates.CONFIG, pricing_config)
        out = fold_record.record_rep(inputs, rep_input(report))
        forward = forward_schedule(out, report.number, schedule_path, pricing_config)
    write_doc(tracker, out.tracker)
    write_doc(complexity, out.complexity)
    write_doc(recognition, out.recognition)
    if schedule is not None:
        write_doc(schedule, out.schedule)
    if forward is not None:
        write_doc(*forward)
    notes = [report.scaffold_note] if report.scaffold_note else []
    return [f"{APPLIED_PREFIX}{line}" for line in (*notes, *out.lines)]


def rep_input(report: FoldReport):
    """The `RepInput` for a folded rep; difficulty and url come from the solution file's header."""
    import fold_record  # noqa: PLC0415 -- see apply_record
    import update_review_dates  # noqa: PLC0415
    difficulty = (update_review_dates.extract_difficulty_from_source(report.solution)
                  or fold_record.DEFAULT_DIFFICULTY)
    url = (update_review_dates.extract_url_from_source(report.solution)
           or links.SITE_PRACTICE_URL_TEMPLATE.format(number=report.number))
    return fold_record.RepInput(report.number, report.title[len(report.number) + 1:], report.iso,
                                report.rating, RATING_EMOJI[report.rating], report.has_recognition,
                                report.queue_rows, difficulty, url,
                                picked=report.picked, pick=report.pick_grade)


def fold_item_errors() -> tuple[type[Exception], ...]:
    """What one attempt's fold may raise without failing the job: a refusal, a malformed or
    missing file, a bad config or hold. Imported lazily like apply_record (cwd-read config)."""
    with working_dir(REPO):
        import fold_record
        import update_review_dates
    return (AttemptError, fold_record.RecordError, update_review_dates.HoldsError, OSError,
            ValueError, yaml.YAMLError)


Snapshot = tuple[tuple[Path, bytes | None], ...]


def item_paths(repo: Path, item: InboxFile, listing: tuple[InboxFile, ...]) -> tuple[Path, ...]:
    """Every file folding `item` may write or delete: its inbox files, its solution file (or the
    scaffold it would create) and `.history` stash, the tracker and gotchas ledgers, and the
    schedule files (the rep's week and every live week a next review may be seated in)."""
    with working_dir(repo):
        import effort_budget
        day = datetime.strptime(item.date, "%Y%m%d").date()
        solution = repo / solution_target(item.number, item.name)
        stash = repo / new_problem.history_dir() / f"{solution.stem}.txt"
        inbox = [f.path for f in listing if f.number == item.number and f.date <= item.date]
        schedules = {effort_budget.find_schedule(day), *effort_budget.SCHEDULES.glob("*_schedule.md")}
        ledgers = [repo / rel for rel in (TRACKER_FILE, COMPLEXITY_FILE, RECOGNITION_FILE)]
        week_files = sorted((p for p in schedules if p is not None), key=str)
        return tuple(dict.fromkeys((*inbox, solution, stash, *ledgers, *week_files)))


def snapshot(paths: tuple[Path, ...]) -> Snapshot:
    """(path, bytes) of each path, bytes None when the file does not exist yet."""
    return tuple((path, path.read_bytes() if path.is_file() else None) for path in paths)


def restore(saved: Snapshot) -> None:
    """Put every snapshotted file back: bytes written, files that did not exist removed."""
    for path, data in saved:
        if data is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def fold_one(repo: Path, item: InboxFile, reference_url: str = "") -> tuple[FoldReport, list[str]]:
    report = fold_file(repo, item.path, reference_url)
    return report, apply_record(repo, report)


def fold_all() -> int:
    """Fold every newest-per-problem inbox entry that is not in progress; one `folded:` line each.
    One attempt is one transaction: on a refusal its files are put back and the next one folds."""
    listing = tuple(list_inbox(REPO / INBOX))
    candidates = [item for item in newest_per_problem(list(listing))
                  if attempt_status(item.path.read_text(encoding="utf-8")) != STATUS_IN_PROGRESS]
    if not candidates:
        print("nothing to fold")
        return 0
    item_errors = fold_item_errors()
    reference_url = read_reference_url(REPO)
    for item in candidates:
        saved = snapshot(item_paths(REPO, item, listing))
        try:
            report, applied = fold_one(REPO, item, reference_url)
        except item_errors as exc:
            restore(saved)
            print(f"refused: {item.path}: {exc}", file=sys.stderr)
            continue
        print(f"folded: {report.number} {RATING_EMOJI[report.rating]} {report.iso}")
        for line in applied:
            print(line, file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("attempt", nargs="?", help="inbox path of a complete attempt")
    ap.add_argument("--pending", action="store_true", help="list the inbox; write nothing")
    ap.add_argument("--apply", action="store_true",
                    help="after the fold, write the tracker, schedule and gotchas changes")
    ap.add_argument("--all", action="store_true", help="with --apply: fold every complete inbox entry")
    ap.add_argument("--coached", action="store_true",
                    help="a coach-confirmed rep: failing cases do not block the fold")
    args = ap.parse_args(argv)
    if args.all and not args.apply:
        ap.error("--all needs --apply")
    if args.all and args.coached:
        ap.error("--coached folds one attempt; --all never waives tests")
    if args.apply and args.all:
        return fold_all()
    if args.pending:
        with working_dir(REPO):
            report = pending_lines(INBOX)
        print("\n".join(report) if report else "Inbox empty.")
        return 0
    if not args.attempt:
        ap.error("give an inbox path, or --pending")
    try:
        report = fold_file(REPO, Path(args.attempt).absolute(), read_reference_url(REPO), is_coached=args.coached)
    except AttemptError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"Folded into {report.solution}")
    for removed in report.removed:
        print(f"Removed {removed}")
    for note in report.notes:
        print(note)
    print("\n".join(report.lines))
    if args.apply:
        print("\n".join(apply_record(REPO, report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
