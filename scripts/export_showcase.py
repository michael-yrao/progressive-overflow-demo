"""Emit the grounded-solutions data contract (showcase.json) for the practice log.

progressiveoverflow.com's algorithm visualizers used to carry a hand-pasted copy of the
learner's Python and a hand-written re-simulation of it. Nothing checked that the copy
matched the real solution, and the two drifted. This script removes the copy: it reads
`dashboard/showcase.yml` (the hand-curated pick of which attempt/variant to show for each
LeetCode problem) and emits `dashboard/showcase.json`, a byte-identical, line-numbered
slice of the REAL solution file — the site fetches this contract at runtime instead of
storing code of its own. See decisions.yml `dashboard-contract-exporters-oct6`.

Design constraints this file honours (see CLAUDE.md):

  * NOT FAIL-SOFT. Unlike gamify.py, a malformed manifest or a symbol that no longer
    exists is a hard error (exit 1) — a stale/wrong showcase contract is the exact drift
    this tool exists to remove, so silently emitting a partial file would defeat the point.

  * EMPTY MANIFEST = NOTHING TO EXPORT, NOT AN EMPTY FILE. A manifest with no entries exits
    0 with a one-line notice and writes no showcase.json. The site falls back to the
    author's showcase only when this repo's showcase.json is a 404; an empty generated
    file would suppress that fallback and leave the adopter's visualizers with no code.

  * VERBATIM, EOL-AGNOSTIC. Every segment's `lines` are read straight off the solution
    file (CRLF/LF-normalized, never re-flowed or re-indented) so the site can render code
    that is provably identical to what's on disk, with real source line numbers.

  * SINGLE SOURCE OF TRUTH for the link precedence: `links.resolve_title_url()` (header
    over tracker, plus the tracker-only trailing `(variant)` strip) is reused rather than
    re-derived here.

Usage:
    python scripts/export_showcase.py             # write dashboard/showcase.json
    python scripts/export_showcase.py --stdout     # print the JSON, do not write
    python scripts/export_showcase.py --check      # build in memory, validate, write nothing;
                                                     # exit 1 on any failure (see README below)
    python scripts/export_showcase.py --date 2026-09-22   # override generatedAt (default: today)

`--check` also fails when `dashboard/showcase.json` already exists on disk and has drifted
from what the manifest + live source files would produce right now — either the entry set
changed, a recorded segment's lines no longer match its source file, or any other field
differs. Run this before committing; the pre-commit hook runs it report-only (exit 2, a
schema violation, stops the commit).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import _console
import contract_schema
import dashboard_indexes
import links

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
DASHBOARD = REPO / "dashboard"
MANIFEST = DASHBOARD / "showcase.yml"
OUT = DASHBOARD / "showcase.json"
SCHEMA = REPO / "dashboard" / "showcase.schema.json"

SCHEMA_VERSION = 1

# A manifest entry's `container` defaults to this when the key is omitted — the common
# case (a LeetCode-style file with one wrapping `class Solution:`). An entry writes
# `container: null` explicitly for a design problem, where the picked symbol IS the class.
DEFAULT_CONTAINER = "Solution"

KIND_CONTAINER = "container"
KIND_ATTEMPT = "attempt"
KIND_HELPER = "helper"

ALLOWED_ENTRY_KEYS = frozenset({"lc", "variant", "symbol", "file", "container", "helpers"})
REQUIRED_ENTRY_KEYS = ("lc", "variant", "symbol")


class ShowcaseError(Exception):
    """A fatal manifest/contract problem. Never caught silently — see the module
    docstring's NOT FAIL-SOFT constraint."""


# ── pure extraction helpers (take `lines`/`tree`; no filesystem access) ─────────────

class IndexBlobReader:
    """Reads files' STAGED content (the git index) through ONE long-lived
    `git cat-file --batch` process, whatever the number of files. Used by the pre-commit
    hook so an unstaged edit to an unrelated problem cannot change or abort a
    regeneration the commit needs."""

    def __init__(self, repo: Path) -> None:
        self._repo = repo.resolve()
        self._proc = subprocess.Popen(
            ["git", "-C", str(self._repo), "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, path: Path) -> bytes | None:
        """The staged bytes of `path`, or None when it is outside the repo or not in the
        index (the caller then falls back to the working tree)."""
        try:
            rel = path.resolve().relative_to(self._repo).as_posix()
        except ValueError:
            return None
        self._proc.stdin.write(f":{rel}\n".encode("utf-8"))
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().decode("utf-8").split()
        if len(header) != 3 or header[1] != "blob":
            return None
        data = self._proc.stdout.read(int(header[2]))
        self._proc.stdout.read(1)  # the LF git prints after each object
        return data

    def close(self) -> None:
        self._proc.stdin.close()
        self._proc.wait()


# The active index reader, or None for the default working-tree reads. Set only through
# `index_reads()`, which restores it on exit.
_index_reader: IndexBlobReader | None = None


@contextlib.contextmanager
def index_reads(repo: Path = REPO):
    """Within the block, `read_lines` returns each file's staged content (the pre-commit
    hook's `--from-index`). Outside it, reads stay on the working tree."""
    global _index_reader
    previous = _index_reader
    reader = IndexBlobReader(repo)
    _index_reader = reader
    try:
        yield
    finally:
        _index_reader = previous
        reader.close()


def read_lines(path: Path) -> list[str]:
    """bytes -> utf-8 -> LF-normalized lines. The working tree mixes CRLF/LF; GitHub
    always serves LF, so every segment's `lines` must be EOL-agnostic to stay
    byte-identical to what the site fetches from GitHub. Under `index_reads()` the bytes
    are the staged blob's (falling back to the working tree for an unstaged path)."""
    staged = _index_reader.read(path) if _index_reader else None
    raw = staged if staged is not None else path.read_bytes()
    text = raw.decode("utf-8")
    return text.replace("\r\n", "\n").split("\n")


def def_start_line(node: ast.AST) -> int:
    """The def/class's OWN first line, decorators included — ast's `lineno` points at the
    `def`/`class` keyword, one line below its own decorator(s)."""
    decorators = getattr(node, "decorator_list", None) or []
    return decorators[0].lineno if decorators else node.lineno


def symbol_table(tree: ast.Module) -> dict[str, ast.AST]:
    """Flat symbol -> ast node: every top-level `ClassDef`/`FunctionDef` keyed by its own
    name, plus every method of a top-level class keyed `"Class.method"`."""
    table: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            table[node.name] = node
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    table[f"{node.name}.{child.name}"] = child
    return table


def leading_comment_block(lines: list[str], lineno: int) -> tuple[int, int] | None:
    """(startLine, endLine), 1-based inclusive, of the contiguous `#`-comment block
    directly above `lineno` (a def/class's own first line — see `def_start_line`), or
    None. Stops at a blank line or ANY non-comment line, so a `\"\"\"docstring\"\"\"`
    sitting above a def is never swept in (it is a normal Python statement, not a
    comment) — this is deliberate: see 1216's `kPalindromeDP`, which has exactly that
    shape above it.
    """
    def_idx = lineno - 1
    idx = def_idx - 1
    bottom_idx: int | None = None
    top_idx: int | None = None
    while idx >= 0 and lines[idx].strip().startswith("#"):
        if bottom_idx is None:
            bottom_idx = idx
        top_idx = idx
        idx -= 1
    if bottom_idx is None:
        return None
    return top_idx + 1, bottom_idx + 1


_SYMBOL_DATE = re.compile(r"_(\d{8})$")
_BANNER_DATE = re.compile(r"Attempt[^·]*·\s*(\d{4}-\d{2}-\d{2})")


def attempt_date(symbol: str, banner_lines: list[str]) -> str | None:
    """ISO date this attempt was written, or None (an undated legacy def). The symbol's
    own `_YYYYMMDD` suffix wins over the banner comment's `Attempt · YYYY-MM-DD` text —
    the suffix is the more durable fact (a banner can be edited or missing while the
    suffix stays the def's identity)."""
    m = _SYMBOL_DATE.search(symbol)
    if m:
        raw = m.group(1)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    for line in banner_lines:
        bm = _BANNER_DATE.search(line)
        if bm:
            return bm.group(1)
    return None


def _segment(kind: str, symbol: str, start: int, end: int, lines: list[str]) -> dict:
    return {"kind": kind, "symbol": symbol, "startLine": start, "endLine": end,
            "lines": lines[start - 1:end]}


def _node_segment(kind: str, symbol: str, node: ast.AST, lines: list[str]) -> tuple[dict, list[str]]:
    """A segment for `node` (a def or class), its leading comment block folded into the
    segment's own start — returns (segment, banner_lines) so callers can feed the banner
    into `attempt_date`."""
    def_start = def_start_line(node)
    banner = leading_comment_block(lines, def_start)
    start = banner[0] if banner else def_start
    banner_lines = lines[banner[0] - 1:banner[1]] if banner else []
    return _segment(kind, symbol, start, node.end_lineno, lines), banner_lines


def _resolve_symbol(table: dict[str, ast.AST], container: str | None, symbol: str,
                     key: str) -> ast.AST:
    """The def/class node for one manifest entry's (container, symbol), or a
    ShowcaseError naming the exact mistake. Checked in this order:

    1. `container` is given but `symbol` is actually a TOP-LEVEL class — the realistic
       mistake (a design problem's manifest entry forgot `container: null`). Checked
       first because the default container ("Solution") often doesn't exist at all in a
       design-problem file, which would otherwise surface the less specific "container
       not found" instead.
    2. `container` is given but doesn't name a real top-level class in this file.
    3. The resolved (container, symbol) pair isn't in the table at all.
    """
    if container is not None and isinstance(table.get(symbol), ast.ClassDef):
        raise ShowcaseError(
            f"{key}: '{symbol}' is a top-level class — use `container: null`, "
            f"not `container: {container}`")
    if container is not None and not isinstance(table.get(container), ast.ClassDef):
        raise ShowcaseError(f"{key}: container '{container}' not found")
    full_symbol = f"{container}.{symbol}" if container else symbol
    node = table.get(full_symbol)
    if node is None:
        where = f" under container '{container}'" if container else ""
        raise ShowcaseError(f"{key}: symbol '{symbol}' not found{where}")
    return node


def build_entry(entry: dict, lines: list[str], tree: ast.Module, title: str | None,
                 url: str | None) -> dict:
    """One `showcase.json` entry for a normalized manifest entry (already carrying
    `container`/`file`/`helpers` defaults — see `normalize_entry`). Pure: takes the
    already-read `lines`/`tree`, never touches the filesystem itself."""
    lc, variant, symbol = entry["lc"], entry["variant"], entry["symbol"]
    container = entry["container"]
    key = f"{lc}:{variant}"

    table = symbol_table(tree)
    node = _resolve_symbol(table, container, symbol, key)

    segments: list[dict] = []
    if container is not None:
        container_node = table[container]
        header_line = def_start_line(container_node)
        segments.append(_segment(KIND_CONTAINER, container, header_line, header_line, lines))

    attempt_segment, banner_lines = _node_segment(KIND_ATTEMPT, symbol, node, lines)
    segments.append(attempt_segment)

    for helper_name in entry["helpers"]:
        helper_node = table.get(helper_name)
        if helper_node is None or "." in helper_name:
            raise ShowcaseError(f"{key}: helper '{helper_name}' not found")
        helper_segment, _ = _node_segment(KIND_HELPER, helper_name, helper_node, lines)
        segments.append(helper_segment)

    segments.sort(key=lambda s: s["startLine"])

    return {
        "key": key,
        "lcNumber": lc,
        "variant": variant,
        "title": title,
        "url": url,
        "file": entry["file"],
        "symbol": symbol,
        "attemptDate": attempt_date(symbol, banner_lines),
        "segments": segments,
    }


# ── manifest loading + validation (boundary: everything that can be malformed input) ──

def load_manifest(path: Path) -> dict:
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        print("ERROR: PyYAML is required to read dashboard/showcase.yml "
              "(pip install pyyaml). Not falling back to a default — a stale showcase "
              "contract is exactly the drift this tool exists to remove.", file=sys.stderr)
        sys.exit(1)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ShowcaseError(f"cannot read manifest '{path}': {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ShowcaseError(f"manifest '{path}' is not valid YAML: {exc}") from exc

    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise ShowcaseError(
            f"manifest schemaVersion must be {SCHEMA_VERSION} (got {data.get('schemaVersion')!r})")
    if not isinstance(data.get("entries"), list):
        raise ShowcaseError("manifest must have a top-level 'entries' list")
    return data


def is_empty_manifest(manifest: dict) -> bool:
    """True when a loaded manifest (see `load_manifest`) picks nothing."""
    return not manifest["entries"]


def empty_manifest_notice(manifest_name: str, out_name: str) -> str:
    """The one line an exporter prints, then exits 0, for an empty manifest. The output
    file is deliberately not written — see the module docstring's EMPTY MANIFEST rule."""
    return (f"{manifest_name} has no entries - nothing to export, {out_name} not written "
            f"(the site keeps its fallback)")


def _validate_entry_shape(raw: dict) -> None:
    """Type/shape checks a hand-curated YAML file is exactly prone to getting wrong —
    fail with a message that names the bad field, never a bare KeyError/TypeError later."""
    unknown = set(raw) - ALLOWED_ENTRY_KEYS
    if unknown:
        raise ShowcaseError(f"manifest entry has unknown key(s) {sorted(unknown)}: {raw!r}")
    missing = [k for k in REQUIRED_ENTRY_KEYS if k not in raw]
    if missing:
        raise ShowcaseError(f"manifest entry missing required key(s) {missing}: {raw!r}")

    lc = raw["lc"]
    if not isinstance(lc, int) or isinstance(lc, bool):
        raise ShowcaseError(f"manifest entry 'lc' must be an integer (got {lc!r})")
    for field in ("variant", "symbol"):
        value = raw[field]
        if not isinstance(value, str) or not value.strip():
            raise ShowcaseError(f"lc {lc}: '{field}' must be a non-empty string (got {value!r})")
    if "file" in raw and raw["file"] is not None and not isinstance(raw["file"], str):
        raise ShowcaseError(f"lc {lc}: 'file' must be a string or omitted")
    if "container" in raw and raw["container"] is not None and not isinstance(raw["container"], str):
        raise ShowcaseError(f"lc {lc}: 'container' must be a string or null")
    if "helpers" in raw:
        helpers = raw["helpers"]
        if not isinstance(helpers, list) or not all(isinstance(h, str) for h in helpers):
            raise ShowcaseError(f"lc {lc}: 'helpers' must be a list of strings")


def normalize_entry(raw: dict, file_rel: str) -> dict:
    """A new dict (never mutates `raw`) with every default applied: `container` defaults
    to DEFAULT_CONTAINER only when the key is genuinely absent (an explicit `container:
    null` must stay None — that's the design-problem case), `helpers` defaults to []."""
    return {
        **raw,
        "file": file_rel,
        "container": raw["container"] if "container" in raw else DEFAULT_CONTAINER,
        "helpers": list(raw.get("helpers") or []),
    }


_FILE_LEADING_NUM = re.compile(r"^(\d+)_")


def check_leading_number(path: Path, lc: int, key: str) -> None:
    """The resolved file's leading `<n>_` number must equal the manifest entry's own
    `lc` — catches a manifest entry pointing at the wrong file (or a stale `file:`
    override) even though the path happens to still resolve to a real file."""
    leading = _FILE_LEADING_NUM.match(path.name)
    if not leading or int(leading.group(1)) != lc:
        raise ShowcaseError(
            f"{key}: lc {lc} does not match the leading number of file '{path.name}'")


def resolve_source_file(raw: dict) -> Path:
    """The solution file for one manifest entry: the explicit `file:` when given
    (validated to exist and sit under a configured source root), else the unique file
    discovered for `lc` (a "twin" — more than one file matching `lc` — is a hard error
    telling the author to add `file:`)."""
    lc = raw["lc"]
    if raw.get("file"):
        path = (REPO / raw["file"]).resolve()
        if not path.is_file():
            raise ShowcaseError(f"lc {lc}: file '{raw['file']}' does not exist")
        if not any(path.is_relative_to(root.resolve()) for root in links.source_roots()):
            raise ShowcaseError(
                f"lc {lc}: file '{raw['file']}' is outside the configured source roots")
        return path

    hits = [p for root in links.source_roots() for p in sorted(root.glob(f"*/{lc}_*.py"))]
    if not hits:
        raise ShowcaseError(f"lc {lc}: no solution file found under the configured roots")
    if len(hits) > 1:
        joined = ", ".join(p.relative_to(REPO).as_posix() for p in hits)
        raise ShowcaseError(
            f"lc {lc}: {len(hits)} files match ({joined}) — add `file:` to disambiguate (a twin)")
    return links.find_file(str(lc)) or hits[0]


def build_payload(manifest: dict, today: dt.date) -> tuple[dict, list[str]]:
    """Return (payload, warnings). Raises ShowcaseError on any fatal manifest/contract
    problem — see the module docstring's NOT FAIL-SOFT constraint. `warnings` carries
    only the one non-fatal case: a problem with no LeetCode/NeetCode URL anywhere."""
    warnings: list[str] = []
    seen_keys: set[str] = set()
    file_cache: dict[Path, tuple[list[str], ast.Module]] = {}
    entries: list[dict] = []

    for raw in manifest["entries"]:
        _validate_entry_shape(raw)
        lc, variant = raw["lc"], raw["variant"]
        key = f"{lc}:{variant}"
        if key in seen_keys:
            raise ShowcaseError(f"duplicate manifest key '{key}'")
        seen_keys.add(key)

        path = resolve_source_file(raw)
        check_leading_number(path, lc, key)

        if path not in file_cache:
            lines = read_lines(path)
            file_cache[path] = (lines, ast.parse("\n".join(lines)))
        lines, tree = file_cache[path]

        entry = normalize_entry(raw, path.relative_to(REPO).as_posix())
        title, url = links.resolve_title_url(str(lc), path)
        if url is None:
            warnings.append(f"{key}: no LeetCode/NeetCode URL found (header or tracker)")

        entries.append(build_entry(entry, lines, tree, title, url))

    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": today.isoformat(),
        "entries": entries,
    }
    return payload, warnings


# ── --check: has the committed showcase.json drifted? ───────────────────────────────

# An existing entry needs all three before `_stale_reasons` can compare it against a
# fresh rebuild or re-read its source file for a segment check.
_REQUIRED_EXISTING_ENTRY_KEYS = ("key", "file", "segments")


def _existing_shape_error(existing: object, label: str = "showcase.json") -> str | None:
    """The first way `existing` (already `json.loads`-parsed) fails to be a well-formed
    showcase.json, as one human-readable reason — or None when its shape is sound enough
    for `_stale_reasons` to compare field by field. A hand-corrupted file must produce
    this one clean reason, never a bare traceback: `--check` fails loudly, not crashes.

    `label` names the file in every reason (a caller emitting a different contract, e.g.
    big-o.json, passes its own).

    Not validated: a non-string `key` or `file` value on an otherwise well-shaped entry —
    either still crashes downstream (`e["key"]` inside a dict comprehension; `REPO /
    file_rel`)."""
    if not isinstance(existing, dict):
        return f"{label}: top level must be an object (got {type(existing).__name__})"

    entries = existing.get("entries")
    if not isinstance(entries, list):
        return f"{label}: 'entries' must be a list (got {type(entries).__name__})"

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return f"{label}: entry {index} must be an object (got {type(entry).__name__})"
        missing = [k for k in _REQUIRED_EXISTING_ENTRY_KEYS if k not in entry]
        if missing:
            missing_desc = ", ".join(f"'{k}'" for k in missing)
            return f"{label}: entry {index} missing {missing_desc}"
        if not isinstance(entry["segments"], list):
            return (f"{label}: entry {index} ('{entry['key']}') 'segments' must be "
                     f"a list (got {type(entry['segments']).__name__})")
        for seg_index, seg in enumerate(entry["segments"]):
            if not isinstance(seg, dict) or not isinstance(seg.get("startLine"), int):
                return (f"{label}: entry {index} ('{entry['key']}') segment "
                        f"{seg_index} has a missing/null/non-integer 'startLine'")
    return None


def _load_existing(existing_path: Path, label: str = "showcase.json") -> tuple[dict | None, list[str]]:
    """(existing, reasons): parses and shape-validates `existing_path`. `existing` is
    None whenever `reasons` is non-empty — the caller checks `reasons` first, so it can
    never read a partially-validated `existing`. `label` is forwarded to
    `_existing_shape_error` (see there)."""
    try:
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"cannot read existing {existing_path}: {exc}"]

    shape_error = _existing_shape_error(existing, label)
    if shape_error:
        return None, [shape_error]
    return existing, []


def _stale_reasons(payload: dict, existing_path: Path, label: str = "showcase.json") -> list[str]:
    """Every way the file at `existing_path` (the committed showcase.json) could have
    drifted from reality: the manifest's entry set changed, a recorded segment no longer
    matches its live source file, or any other field differs from a fresh rebuild. A
    malformed `existing_path` (see `_existing_shape_error`) is reported the same way —
    one clean reason — rather than raised. `label` names the file in every reason."""
    existing, load_reasons = _load_existing(existing_path, label)
    if load_reasons:
        return load_reasons

    reasons: list[str] = []
    new_by_key = {e["key"]: e for e in payload["entries"]}
    old_entries = existing.get("entries") or []
    old_by_key = {e["key"]: e for e in old_entries}

    if new_by_key.keys() != old_by_key.keys():
        added = sorted(new_by_key.keys() - old_by_key.keys())
        removed = sorted(old_by_key.keys() - new_by_key.keys())
        reasons.append(f"entry set changed — added {added}, removed {removed}")

    lines_by_file: dict[str, list[str]] = {}
    for old_entry in old_entries:
        entry_key, file_rel = old_entry.get("key"), old_entry.get("file")
        if not file_rel:
            continue
        if file_rel not in lines_by_file:
            try:
                lines_by_file[file_rel] = read_lines(REPO / file_rel)
            except OSError as exc:
                reasons.append(f"{entry_key}: cannot re-read '{file_rel}': {exc}")
                continue
        live = lines_by_file[file_rel]
        for seg in old_entry.get("segments") or []:
            start, end = seg.get("startLine"), seg.get("endLine")
            if live[start - 1:end] != seg.get("lines"):
                reasons.append(
                    f"{entry_key}: segment '{seg.get('symbol')}' ({seg.get('kind')}) "
                    f"lines {start}-{end} no longer match '{file_rel}' — regenerate")

    for key in new_by_key.keys() & old_by_key.keys():
        if new_by_key[key] != old_by_key[key]:
            reasons.append(f"{key}: entry differs from the committed {label} — regenerate")

    return reasons


# ── CLI ───────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stdout", action="store_true", help="print the JSON, do not write")
    ap.add_argument("--check", action="store_true",
                     help="build in memory, validate, never write; exit 1 on any failure")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                     help="override generatedAt (default: today)")
    ap.add_argument("--from-index", action="store_true",
                     help="read each solution file's staged (index) content, not the "
                          "working tree — the pre-commit hook's mode")
    args = ap.parse_args()

    reads = index_reads() if args.from_index else contextlib.nullcontext()
    with reads:
        _run(args)


def _run(args: argparse.Namespace) -> None:
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    try:
        manifest = load_manifest(MANIFEST)
        if is_empty_manifest(manifest):
            print(empty_manifest_notice(MANIFEST.name, OUT.name), file=sys.stderr)
            return
        payload, warnings = build_payload(manifest, today)
    except ShowcaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    for w in warnings:
        print(f"  !! {w}", file=sys.stderr)

    if args.check:
        contract_schema.check(payload, SCHEMA)
        if OUT.exists():
            reasons = _stale_reasons(payload, OUT)
            if reasons:
                print("ERROR: dashboard/showcase.json is stale:", file=sys.stderr)
                for reason in reasons:
                    print(f"  - {reason}", file=sys.stderr)
                sys.exit(1)
        # Like showcase.json itself: nothing on disk to drift from when there is no source.
        split = dashboard_indexes.build_showcase_split(payload)
        dashboard_indexes.exit_on_schema_errors(split)
        split_reasons = [] if not OUT.exists() else dashboard_indexes.stale_reasons(
            DASHBOARD, split, check_extra_showcase=True)
        if split_reasons:
            print("ERROR: dashboard/showcase-index.json or dashboard/showcase/ is stale:",
                  file=sys.stderr)
            for reason in split_reasons:
                print(f"  - {reason}", file=sys.stderr)
            sys.exit(1)
        print(f"ok: {len(payload['entries'])} showcase entries verified", file=sys.stderr)
        return

    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.stdout:
        print(rendered)
        return

    contract_schema.check(payload, SCHEMA)
    split = dashboard_indexes.build_showcase_split(payload)
    dashboard_indexes.exit_on_schema_errors(split)
    DASHBOARD.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered + "\n", encoding="utf-8")
    dashboard_indexes.write_files(DASHBOARD, split, prune_showcase=True)
    print(f"wrote {OUT.relative_to(REPO)} ({len(payload['entries'])} entries)")


if __name__ == "__main__":
    main()
