"""Generate /learn's technique cheat sheet from the technique docs. The full contract
this module implements is documented below.

    docs/foundations/dsa/patterns/techniques/*.md
      + intuition_cheatsheet.md's Signal -> technique table
      + intuition_cheatsheet.md's Decision tree bullet list
      + techniques.yml (family/tier, joined by a `doc:` key)
    ->  dashboard/cheat-sheets.json  +  dashboard/cheat-sheets.schema.json

Usage:
    python scripts/build_cheatsheets.py             # write both files
    python scripts/build_cheatsheets.py --validate   # compute + report; write nothing
    python scripts/build_cheatsheets.py --stdout     # print the JSON, do not write

Design constraints this file honours (see CLAUDE.md and docs/foundations/dsa/patterns/README.md's
"The machine-readable contract" section):

  * THE DOCS STAY PROSE. The generator reads only five exact headings per doc (see the
    HEADING_* constants) and ignores everything else — the "Understanding …" / "Key
    Insights" deep-dives stay untouched. `scripts/check_cheatsheets.py --check` is what
    enforces the contract; this file degrades gracefully instead (a missing/short section
    yields 'TODO' or an empty list, never a crash — see the schema's own field docs).

  * SINGLE SOURCE OF TRUTH. No tuned number lives here — family/tier come from
    techniques.yml, content comes from the docs. The one HARD failure this file raises is
    the techniques.yml join (0 or >1 entries carrying a given `doc:` key): that is not a
    content gap, it is a vocabulary bug that would silently mis-tag a technique.

  * IDEMPOTENT. Two runs back to back differ only in `generatedAt` — nothing else in the
    payload depends on wall-clock time or file-system iteration order beyond the sorted
    glob below.

  * THE SEED IS THE TARGET, NOT THE INPUT. scripts/fixtures/cheat-sheets.seed.json is a
    byte copy of the site's Phase-B seed (tech-lead-authored content the docs did not yet
    carry). This generator's job is to REPRODUCE it once the docs conform — see
    scripts/test_build_cheatsheets.py's golden test — never to read from it. When a change
    to the doc set (a page added, removed or renamed) legitimately changes the output,
    refresh the seed from a reviewed run of this generator.

Markdown stripping ("the markdown contract"): the markdown noise carried into emitted text is
`**bold**`, single-`*` `*italic*` and `[text](url)` links — all three are unwrapped down to
their plain text; backticks pass through untouched — see clean()'s docstring for the empirical
check against the seed that pins this.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import _console

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
TECHNIQUES_DIR = REPO / "docs/foundations/dsa/patterns/techniques"
INTUITION_DOC = REPO / "docs/foundations/dsa/patterns/intuition_cheatsheet.md"
TECHNIQUES_YAML = REPO / "docs/foundations/dsa/mastery/techniques.yml"
CATALOGUE_YAML = REPO / "curriculum/dsa/techniques.yml"
FIXTURES = REPO / "scripts/fixtures"
SCHEMA_FIXTURE = FIXTURES / "cheat-sheets.schema.json"
DASHBOARD = REPO / "dashboard"
OUT = DASHBOARD / "cheat-sheets.json"
OUT_SCHEMA = DASHBOARD / "cheat-sheets.schema.json"

SCHEMA_VERSION = 1
DEFAULT_TIER = "core"
TODO = "TODO"

# The five headings the contract reads — exact text, except HEADING_TEMPLATE_PREFIX, which
# is a prefix ("## Template: <title>", one heading per variant). Named as constants per the
# plan so a heading-text change is a one-line edit here and nowhere else.
HEADING_WHEN = "When to reach for it"
HEADING_PICKING = "Picking feature"
HEADING_TEMPLATE_PREFIX = "Template: "
HEADING_PITFALLS = "Common pitfalls"
HEADING_PRACTICE = "Practice"

WHEN_PREFIX = "*When:* "
COMPLEXITY_PREFIX = "Complexity: "
COMPLEXITY_TIME_SEP = " time · "
COMPLEXITY_SPACE_SEP = " space — "

LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# A single-`*` italic span: the opening `*` must not be followed by whitespace and the
# closing `*` must not be preceded by whitespace (markdown's own flanking rule) — this is
# what keeps a spaced multiplication like `` `r * cols + c` `` from being mistaken for a
# pair of italic delimiters.
ITALIC_RE = re.compile(r"\*(?!\s)([^*\n]+?)(?<!\s)\*")

NOT_WHEN_RE = re.compile(r"^\*\*not\s+(.+?)\*\*\s*—\s*(.*)$")
PRACTICE_LC_RE = re.compile(r"^LC\s+(\d+)\s+—\s+(.*)$")
PRACTICE_LINK_RE = re.compile(r"^\[(\d+)\.\s+([^\]]+)\]\(")

SIGNAL_TABLE_HEADING = "Signal → technique"
SIGNAL_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
SIGNAL_DOC_LINK_RE = re.compile(r"\[[^\]]+\]\(techniques/([^)]+)\.md\)")
PAREN_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")

# ── decision tree (intuition_cheatsheet.md) ──────────────────────────────────────────

DECISION_TREE_HEADING = "Decision tree"
LEAF_ARROW = " → "
TAB_WIDTH = 4
BULLET_LINE_RE = re.compile(r"^(?P<indent>\s*)- (?P<text>.*)$")
# A leaf bullet's tail is either a `[text](techniques/<stem>.md)` link or a `**bold**`
# no-page label, optionally followed by a `(<note>)` parenthetical. The label is matched
# lazily so a ` → ` that appears INSIDE the label (there is none today, but the grammar
# must not assume it) only ever splits at the tail the anchored end forces it to.
DECISION_LEAF_RE = re.compile(
    r"^(?P<label>.+?)" + re.escape(LEAF_ARROW) +
    r"(?:\[(?P<text>[^\]]+)\]\(techniques/(?P<stem>[^)]+)\.md\)|\*\*(?P<bold>[^*]+)\*\*)"
    r"(?:\s+\((?P<note>.*)\))?\s*$"
)

# A leading emoji run (e.g. recursion.md's "# 🧠 Recursion & …") plus the whitespace after
# it. Ranges cover the common emoji blocks (misc symbols/dingbats, supplemental
# symbols-and-pictographs) plus the variation-selector codepoint some emoji carry.
LEADING_EMOJI_RE = re.compile(r"^[\U0001F000-\U0001FFFF☀-➿️]+\s*")
NAME_SUFFIX = " Patterns"

DOC_PATH_TMPL = "docs/foundations/dsa/patterns/techniques/{stem}.md"
GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?$"
)


def _doc_url_base() -> str | None:
    """The 'https://github.com/<owner>/<name>/blob/main' docUrl prefix, read from this
    repo's `origin` remote. This is a template package cloned into a learner's own repo,
    so the owner/name isn't known at authoring time the way cse-progress's own hardcoded
    URL was — None (falls back to a repo-relative path) when there's no readable GitHub
    remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=REPO, capture_output=True, text=True, timeout=5, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    match = GITHUB_REMOTE_RE.match(result.stdout.strip())
    return f"https://github.com/{match['owner']}/{match['name']}/blob/main" if match else None


def doc_url_for(stem: str, doc_url_base: str | None) -> str:
    path = DOC_PATH_TMPL.format(stem=stem)
    return f"{doc_url_base}/{path}" if doc_url_base else path

# The intuition_cheatsheet.md "Reach for" cell usually carries its qualifier as a
# parenthetical after the base label ("two pointers (converge from ends)" -> note
# "converge from ends" — see default_note()). Five of the current 23 rows don't fit that
# shape: the whole cell IS the qualifier with no base/paren split ("monotonic
# deque", "sort by **start**, sweep", "DFS postorder", "DFS inorder"). Fitted to the
# 23-row table — a new row follows default_note() unless it needs adding here too.
REACH_NOTE_OVERRIDES = {
    "monotonic deque": "monotonic deque",
    "sort by start, sweep": "sort by start, sweep",
    "sort by end, greedy frontier": "sort by end, greedy frontier",
    "DFS postorder": "DFS postorder",
    "DFS inorder": "DFS inorder",
}


class BuildError(Exception):
    """A fatal, must-fix condition — currently only the techniques.yml join (0 or >1
    entries for a doc's `doc:` key). Ordinary missing/short doc content is never fatal
    here; it degrades to 'TODO'/an empty list instead (fail-soft, like every other
    generator in this repo) and scripts/check_cheatsheets.py is the hard gate for that."""


# ── markdown primitives ──────────────────────────────────────────────────────────────

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def clean(text: str) -> str:
    """Strip the contract's markdown noise carried into emitted text: `**bold**` markers,
    single-`*` `*italic*` spans and `[text](url)` links (unwrapped to `text`). Backticks
    pass through untouched — checked empirically against
    scripts/fixtures/cheat-sheets.seed.json (no stray markup of any of those three kinds
    survives into a non-code text field there; code fences are never passed through this)."""
    text = text.replace("**", "")
    text = LINK_RE.sub(r"\1", text)
    return ITALIC_RE.sub(r"\1", text)


def split_h2_sections(text: str) -> list[tuple[str, list[str]]]:
    """Level-2 (`## `) headings -> [(heading text, body lines)], fence-aware: a line
    inside a ```-fenced block (including one that itself starts with `##`, e.g. a Python
    comment) is never mistaken for a heading, and fence delimiter lines are kept in the
    body so find_python_fence() can find them again."""
    sections: list[tuple[str, list[str]]] = []
    heading: str | None = None
    body: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            if heading is not None:
                sections.append((heading, body))
            heading, body = line[3:].strip(), []
            continue
        if heading is not None:
            body.append(line)
    if heading is not None:
        sections.append((heading, body))
    return sections


def extract_h1(text: str) -> str:
    """The doc's level-1 heading: leading emoji + whitespace stripped, a trailing
    ' Patterns' dropped. Fence-aware for the same reason split_h2_sections() is."""
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped.startswith("# ") or stripped.startswith("## "):
            continue
        title = LEADING_EMOJI_RE.sub("", stripped[2:].strip())
        return title[: -len(NAME_SUFFIX)] if title.endswith(NAME_SUFFIX) else title
    return ""


def first_nonblank_line(lines: list[str]) -> str:
    for line in lines:
        if line.strip():
            return line.strip()
    return ""


def first_paragraph(lines: list[str]) -> str:
    """Consecutive non-blank, non-bullet lines from the start of `lines`, joined with a
    single space. Leading blank lines are skipped; the paragraph ends at the first blank
    line (once started) or the first bullet."""
    para: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if para:
                break
            continue
        if stripped.startswith("- "):
            break
        para.append(stripped)
    return " ".join(para)


def first_bullet_list(lines: list[str]) -> list[str]:
    """The first `- ` bullet list anywhere in `lines` (prose may sit before it). An
    indented continuation line is joined onto the current bullet; a blank line or a
    non-indented, non-bullet line ends the list."""
    items: list[str] = []
    current: str | None = None
    started = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            started = True
            if current is not None:
                items.append(current)
            current = stripped[2:].strip()
            continue
        if not started:
            continue
        if not stripped:
            break
        if line.startswith((" ", "\t")):
            if current is not None:
                current = f"{current} {stripped}"
            continue
        break
    if current is not None:
        items.append(current)
    return items


def find_section(sections: list[tuple[str, list[str]]], heading_text: str) -> list[str] | None:
    for heading, body in sections:
        if heading == heading_text:
            return body
    return None


def find_template_sections(sections: list[tuple[str, list[str]]]) -> list[tuple[str, list[str]]]:
    return [(h, b) for h, b in sections if h.startswith(HEADING_TEMPLATE_PREFIX)]


def find_h2_section_raw(text: str, heading_text: str) -> list[str] | None:
    return find_section(split_h2_sections(text), heading_text)


# ── technique reference resolution (id vs. label) ────────────────────────────────────

def is_technique_doc(slug: str) -> bool:
    return (TECHNIQUES_DIR / f"{slug}.md").is_file()


def technique_ref(x: str) -> dict:
    """{'technique': id} when a doc x-with-hyphens-as-underscores.md exists, else
    {'technique': x, 'page': False} — the resolution rule this file uses throughout, for
    both notWhen entries and (indirectly, via the Doc-column check) the top-level
    signals."""
    slug = x.replace("-", "_")
    if is_technique_doc(slug):
        return {"technique": x}
    return {"technique": x, "page": False}


# ── "## When to reach for it" ────────────────────────────────────────────────────────

def parse_when_section(lines: list[str]) -> tuple[str, list[str]]:
    when_to_use = clean(first_paragraph(lines)) or TODO
    signals = [clean(b) for b in first_bullet_list(lines)]
    return when_to_use, signals


# ── "## Picking feature" ─────────────────────────────────────────────────────────────

def parse_not_when_bullet(bullet_text: str) -> dict | None:
    match = NOT_WHEN_RE.match(bullet_text)
    if not match:
        return None
    x = clean(match.group(1).strip())
    because = clean(match.group(2).strip())
    return {**technique_ref(x), "because": because}


def parse_picking_section(lines: list[str]) -> tuple[str, list[dict]]:
    feature = clean(first_nonblank_line(lines)) or TODO
    not_when = [nw for nw in (parse_not_when_bullet(b) for b in first_bullet_list(lines))
                if nw is not None]
    return feature, not_when


# ── "## Template: <title>" ───────────────────────────────────────────────────────────

def find_python_fence(lines: list[str]) -> tuple[list[str], int] | None:
    """(code lines, index just after the closing fence) for the FIRST ```python fence in
    `lines`, or None if there isn't a complete one."""
    i, n = 0, len(lines)
    while i < n and lines[i].strip() != "```python":
        i += 1
    if i >= n:
        return None
    start = i + 1
    end = start
    while end < n and lines[end].strip() != "```":
        end += 1
    if end >= n:
        return None  # unterminated fence
    return lines[start:end], end + 1


def parse_complexity_line(line: str) -> dict:
    rest = line[len(COMPLEXITY_PREFIX):]
    if COMPLEXITY_TIME_SEP not in rest:
        return {"time": TODO, "space": TODO, "why": TODO}
    time_part, _, remainder = rest.partition(COMPLEXITY_TIME_SEP)
    if COMPLEXITY_SPACE_SEP not in remainder:
        return {"time": TODO, "space": TODO, "why": TODO}
    space_part, _, why_part = remainder.partition(COMPLEXITY_SPACE_SEP)
    return {"time": clean(time_part.strip()), "space": clean(space_part.strip()),
            "why": clean(why_part.strip())}


def parse_complexity_after(lines: list[str], index: int) -> dict:
    """The first non-blank line at/after `index` — required to be the doc's `Complexity:
    …` line directly after the closing fence. TODO-triple when that line is missing,
    blank-only, or doesn't start with the expected prefix."""
    n = len(lines)
    i = index
    while i < n and not lines[i].strip():
        i += 1
    if i >= n or not lines[i].strip().startswith(COMPLEXITY_PREFIX):
        return {"time": TODO, "space": TODO, "why": TODO}
    return parse_complexity_line(lines[i].strip())


def parse_template_section(heading: str, lines: list[str]) -> dict:
    title = heading[len(HEADING_TEMPLATE_PREFIX):].strip()
    first_line = first_nonblank_line(lines)
    variant = {"title": title}
    if first_line.startswith(WHEN_PREFIX):
        variant["when"] = clean(first_line[len(WHEN_PREFIX):].strip())

    fence = find_python_fence(lines)
    if fence is None:
        variant["code"] = TODO
        variant["complexity"] = {"time": TODO, "space": TODO, "why": TODO}
    else:
        code_lines, after = fence
        variant["code"] = "\n".join(code_lines)
        variant["complexity"] = parse_complexity_after(lines, after)
    return variant


# ── "## Common pitfalls" / "## Practice" ─────────────────────────────────────────────

def parse_pitfalls_section(lines: list[str]) -> list[str]:
    return [clean(b) for b in first_bullet_list(lines)]


def parse_practice_bullet(content: str) -> dict | None:
    match = PRACTICE_LC_RE.match(content)
    if match:
        return {"lcNumber": int(match.group(1)), "title": clean(match.group(2).strip())}
    match = PRACTICE_LINK_RE.match(content)
    if match:
        return {"lcNumber": int(match.group(1)), "title": clean(match.group(2).strip())}
    return None


def parse_practice_section(lines: list[str]) -> list[dict]:
    """Only bullet lines are read — a Practice section's markdown table (the pre-contract
    doc style) or a continuation line is silently ignored."""
    problems: list[dict] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        entry = parse_practice_bullet(stripped[2:].strip())
        if entry is not None:
            problems.append(entry)
    return problems


# ── one technique doc -> its payload entry ───────────────────────────────────────────

def parse_technique_fields(sections: list[tuple[str, list[str]]]) -> dict:
    when_to_use, signals = parse_when_section(find_section(sections, HEADING_WHEN) or [])
    feature, not_when = parse_picking_section(find_section(sections, HEADING_PICKING) or [])
    pitfalls = parse_pitfalls_section(find_section(sections, HEADING_PITFALLS) or [])
    key_problems = parse_practice_section(find_section(sections, HEADING_PRACTICE) or [])
    variants = [parse_template_section(h, b) for h, b in find_template_sections(sections)]
    return {
        "whenToUse": when_to_use,
        "signals": signals,
        "picking": {"feature": feature, "notWhen": not_when},
        "variants": variants,
        "pitfalls": pitfalls,
        "keyProblems": key_problems,
    }


def load_techniques_yaml() -> list[dict]:
    import curriculum  # noqa: PLC0415

    return curriculum.load_techniques(CATALOGUE_YAML, TECHNIQUES_YAML)["techniques"]


def family_tier_for(doc_stem: str, entries: list[dict]) -> tuple[str, str]:
    matches = [e for e in entries if e.get("doc") == doc_stem]
    if not matches:
        raise BuildError(f"techniques.yml: no entry carries `doc: {doc_stem}`")
    if len(matches) > 1:
        raise BuildError(
            f"techniques.yml: {len(matches)} entries carry `doc: {doc_stem}` (expected 1)")
    family = matches[0].get("family")
    if not family:
        raise BuildError(f"techniques.yml: the `doc: {doc_stem}` entry has no `family`")
    return family, matches[0].get("tier") or DEFAULT_TIER


def discover_technique_docs() -> list[Path]:
    return sorted(TECHNIQUES_DIR.glob("*.md"))


def build_technique(path: Path, entries: list[dict], doc_url_base: str | None) -> dict:
    text = read_text(path)
    fields = parse_technique_fields(split_h2_sections(text))
    family, tier = family_tier_for(path.stem, entries)
    return {
        "id": path.stem.replace("_", "-"),
        "name": extract_h1(text) or path.stem,
        "family": family,
        "tier": tier,
        **fields,
        "docUrl": doc_url_for(path.stem, doc_url_base),
    }


def technique_warnings(entry: dict) -> list[str]:
    """Non-fatal report lines for a technique whose doc left something at its fail-soft
    default — useful triage output, never a reason to stop the build."""
    msgs = []
    if entry["whenToUse"] == TODO:
        msgs.append("whenToUse is TODO (missing/empty '## When to reach for it')")
    if entry["picking"]["feature"] == TODO:
        msgs.append("picking.feature is TODO (missing/empty '## Picking feature')")
    if not entry["variants"]:
        msgs.append("no '## Template: …' sections found")
    for variant in entry["variants"]:
        if variant["complexity"]["time"] == TODO:
            msgs.append(f"variant '{variant['title']}': no Complexity line after its fence")
    if not entry["pitfalls"]:
        msgs.append("pitfalls is empty ('## Common pitfalls' missing/empty)")
    if not entry["keyProblems"]:
        msgs.append("keyProblems is empty ('## Practice' missing/unresolvable)")
    return [f"{entry['id']}: {m}" for m in msgs]


# ── top-level signals table (intuition_cheatsheet.md) ────────────────────────────────

def parse_signal_rows(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        match = SIGNAL_ROW_RE.match(line.strip())
        if not match:
            continue
        cells = [c.strip() for c in match.group(1).split("|")]
        if len(cells) != 3:
            continue
        if cells[0] in ("What you see in the prompt", "") or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(cells)
    return rows


def signal_doc_target(doc_cell: str) -> str | None:
    """The 'techniques/<x>.md' filename the Doc column's link points at, or None when the
    cell isn't that shape (an external link, or the '*below*' placeholder) — existence is
    NOT checked here; that's scripts/check_cheatsheets.py's job (see its docstring)."""
    match = SIGNAL_DOC_LINK_RE.search(doc_cell)
    return f"{match.group(1)}.md" if match else None


def default_note(text: str) -> str:
    match = PAREN_RE.match(text)
    return match.group(2).strip() if match else ""


def build_signal_entry(cells: list[str]) -> dict:
    see = clean(cells[0])
    reach_for = clean(cells[1])
    note = REACH_NOTE_OVERRIDES.get(reach_for, default_note(reach_for))
    target = signal_doc_target(cells[2])
    if target is not None:
        return {"see": see, "reach": target[:-3].replace("_", "-"), "note": note}
    return {"see": see, "reach": reach_for, "note": note, "page": False}


def parse_signal_table() -> list[dict]:
    lines = find_h2_section_raw(read_text(INTUITION_DOC), SIGNAL_TABLE_HEADING) or []
    return [build_signal_entry(cells) for cells in parse_signal_rows(lines)]


# ── decision tree (intuition_cheatsheet.md) ────────────────────────────────────────────

def collect_nested_bullets(lines: list[str]) -> list[tuple[int, str]]:
    """The first (nested) `- ` bullet list anywhere in `lines` (prose before it is
    skipped) as `(indent, text)` per bullet, tabs expanded to 4 columns. A blank line is
    skipped, never ends the list; a line indented deeper than its bullet's own indent is a
    continuation, joined onto it with one space. Ends at the first indent-0 non-bullet
    line seen after the list starts, or a ``` fence."""
    items: list[tuple[int, str]] = []
    current_indent: int | None = None
    current_text: str | None = None
    started = False
    for raw_line in lines:
        line = raw_line.expandtabs(TAB_WIDTH)
        stripped = line.strip()
        if stripped.startswith("```"):
            break
        if not stripped:
            continue
        bullet = BULLET_LINE_RE.match(line)
        if bullet:
            started = True
            if current_text is not None:
                items.append((current_indent, current_text))
            current_indent = len(bullet.group("indent"))
            current_text = bullet.group("text").strip()
            continue
        if not started:
            continue
        line_indent = len(line) - len(line.lstrip(" "))
        if current_text is not None and line_indent > current_indent:
            current_text = f"{current_text} {stripped}"
            continue
        break
    if current_text is not None:
        items.append((current_indent, current_text))
    return items


def parse_decision_bullet(raw: str, problems: list[str]) -> dict:
    """One bullet's text -> a tree node (`clean()` runs on label/note AFTER the arrow
    split, never on a link's stem): no arrow -> an inner node with no children yet; a
    resolvable `[text](techniques/<stem>.md)` tail -> a linked leaf, `reachLabel` = the
    link's own text (`reach` stays the id/route key); a `**bold**` tail -> a no-page leaf
    with `reachLabel == reach`. An arrow present but not matching either tail shape is
    fail-soft: it becomes a no-page leaf (split naively on the arrow, `reachLabel ==
    reach`) and is reported in `problems`."""
    if LEAF_ARROW not in raw:
        return {"label": clean(raw), "children": []}
    match = DECISION_LEAF_RE.match(raw)
    if not match:
        problems.append(f"decision tree: malformed leaf '{raw}'")
        label_part, _, reach_part = raw.partition(LEAF_ARROW)
        reach = clean(reach_part)
        return {"label": clean(label_part), "reach": reach, "reachLabel": reach,
                "note": "", "page": False}
    label = clean(match.group("label"))
    note = clean(match.group("note") or "")
    stem = match.group("stem")
    if stem is not None:
        return {"label": label, "reach": stem.replace("_", "-"),
                "reachLabel": clean(match.group("text")), "note": note}
    bold = clean(match.group("bold"))
    return {"label": label, "reach": bold, "reachLabel": bold, "note": note,
            "page": False}


def nest_decision_bullets(items: list[tuple[int, str]], problems: list[str]) -> list[dict]:
    """Indentation-stack walk from flat `(indent, raw)` bullets to root node(s): a bullet
    nests under the nearest still-open ancestor with a strictly smaller indent (tolerant
    of 2- or 4-space steps and odd sibling indents). A bullet nested under an already-built
    leaf is dropped, with a `problems` line, instead of silently becoming its child."""
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for indent, raw in items:
        node = parse_decision_bullet(raw, problems)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            parent = stack[-1][1]
            if "children" in parent:
                parent["children"].append(node)
            else:
                problems.append(f"decision tree: bullet nested under a leaf, dropped: '{raw}'")
        stack.append((indent, node))
    return roots


def parse_decision_tree(lines: list[str], problems: list[str] | None = None) -> dict | None:
    """The section body -> its single root node, or `None` (with a `problems` line) when
    the bullet list has zero or more than one root."""
    findings = problems if problems is not None else []
    roots = nest_decision_bullets(collect_nested_bullets(lines), findings)
    if len(roots) != 1:
        findings.append(f"decision tree: expected exactly one root bullet, found {len(roots)}")
        return None
    return roots[0]


def decision_tree_leaves(node: dict) -> list[dict]:
    """DFS flatten of every leaf under `node` (inclusive) — used by the coverage check and
    by the tests; an inner node's own `label` never appears in the result."""
    if "children" not in node:
        return [node]
    leaves: list[dict] = []
    for child in node["children"]:
        leaves.extend(decision_tree_leaves(child))
    return leaves


def build_decision_tree(warnings: list[str]) -> dict | None:
    lines = find_h2_section_raw(read_text(INTUITION_DOC), DECISION_TREE_HEADING)
    if lines is None:
        warnings.append(f"'## {DECISION_TREE_HEADING}' section missing from "
                        f"{INTUITION_DOC.name}")
        return None
    problems: list[str] = []
    tree = parse_decision_tree(lines, problems)
    warnings.extend(problems)
    return tree


# ── the build ─────────────────────────────────────────────────────────────────────────

def build_payload(now: dt.datetime, warnings: list[str]) -> dict:
    entries = load_techniques_yaml()
    doc_url_base = _doc_url_base()  # computed once per build, not per doc
    techniques = [build_technique(p, entries, doc_url_base) for p in discover_technique_docs()]
    for entry in techniques:
        warnings.extend(technique_warnings(entry))
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signals": parse_signal_table(),
        "techniques": techniques,
    }
    decision_tree = build_decision_tree(warnings)
    if decision_tree is not None:
        payload["decisionTree"] = decision_tree
    return payload


def write_schema_copy() -> None:
    # A byte copy, not a text round-trip: `write_text` on Windows re-expands `\n` to
    # `\r\n`, which would make this copy differ from SCHEMA_FIXTURE byte-for-byte even
    # though nothing about its content changed (the two files are meant to be identical —
    # `cmp scripts/fixtures/cheat-sheets.schema.json dashboard/cheat-sheets.schema.json`).
    OUT_SCHEMA.write_bytes(SCHEMA_FIXTURE.read_bytes())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate", action="store_true",
                    help="compute + report; write nothing (for tests / CI)")
    ap.add_argument("--stdout", action="store_true", help="print the JSON, do not write")
    args = ap.parse_args()

    warnings: list[str] = []
    try:
        payload = build_payload(dt.datetime.now(dt.timezone.utc), warnings)
    except BuildError as exc:
        sys.exit(f"build_cheatsheets: {exc}")

    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    n_tech, n_sig = len(payload["techniques"]), len(payload["signals"])
    tree_note = " · decision tree" if "decisionTree" in payload else ""

    if args.stdout:
        print(text)
    elif args.validate:
        print(f"valid: {n_tech} techniques · {n_sig} signals{tree_note}", file=sys.stderr)
    else:
        DASHBOARD.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        write_schema_copy()
        print(f"wrote {OUT.relative_to(REPO)} + {OUT_SCHEMA.relative_to(REPO)} "
              f"({n_tech} techniques, {n_sig} signals{tree_note})")

    for w in warnings:
        print(f"  !! {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
