"""Emit the practice-runner data contract (practice.json) for the practice log.

progressiveoverflow.com's practice page runs the learner's Python in the browser against
stored test cases. Those cases used to be a throwaway check script the coach wrote per
rep and discarded. This script keeps them: it reads every hand-authored spec in
`dsa/tests/<number>_<snake_title>.yml` (statement, entry point, signature, comparison mode,
cases as `args` + `expected`) and emits `dashboard/practice.json`, the file the site
fetches. No reference solution is published, only inputs and expected outputs.
See decisions.yml `dashboard-contract-exporters-oct6`.

Design constraints this file honours (same as export_showcase.py):

  * NOT FAIL-SOFT. A malformed spec is a hard error (exit 1) naming the spec file — a
    wrong expected value shipped to the site marks a correct solution as failing.

  * ONE signature parser. The stub is rendered with `new_problem.parse_signature`, the
    same helper `new_problem.py --signature` uses, so a scaffold and the site's blank
    editor can never disagree on the signature.

Usage:
    python scripts/export_practice.py             # write dashboard/practice.json
    python scripts/export_practice.py --stdout     # print the JSON, do not write
    python scripts/export_practice.py --check      # build in memory, validate, write nothing;
                                                     # exit 1 on any failure
    python scripts/export_practice.py --date 2026-10-01   # override generatedAt (default: today)

Beyond the single-method shape a spec may set `result` (compare an argument after the call),
`types` (node codecs per argument and result) and `entry.kind` (`ops` or `round-trip`); a case
may set `judge` (a judge API to bind) and an `expected` of `{anyOf: [...]}`.

`--check` also fails when `dashboard/practice.json` already exists on disk and differs from
what the specs would produce right now. `generatedAt` is ignored in that comparison, so a
regeneration on a later day is not drift.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import _console
import contract_schema
import dashboard_indexes
import new_problem

_console.force_utf8()

REPO = Path(__file__).resolve().parent.parent
SPEC_DIR = REPO / "dsa" / "tests"
DASHBOARD = REPO / "dashboard"
OUT = DASHBOARD / "practice.json"
SCHEMA = REPO / "dashboard" / "practice.schema.json"

SCHEMA_VERSION = 1

# What the site's worker needs above the stub so the stub runs unmodified.
STUB_PREAMBLE = "from typing import List, Optional\n\n\n"

# The site draws a statement's indented lines verbatim (alignment matters) in a pane about 68
# characters wide, so a longer one would wrap mid-row. Unindented lines are not limited: the
# site reflows them to the pane's width.
MAX_VERBATIM_LINE = 64

KIND_METHOD = "method"
KIND_OPS = "ops"
KIND_ROUND_TRIP = "round-trip"
ENTRY_KINDS = frozenset({KIND_OPS, KIND_ROUND_TRIP})

RESULT_RETURN = "return"
RESULT_ARG = "arg"
RESULT_ARG_PREFIX = "arg-prefix"
# Spec spelling of a `result` mapping's key → the emitted `result.kind`.
RESULT_SPEC_KEYS = {"arg": RESULT_ARG, "argPrefix": RESULT_ARG_PREFIX}

CODEC_TREE_NODE = "tree-node"
CODEC_TREE_VALUE = "tree-value"
CODEC_LIST_NODE = "list-node"
CODEC_LIST_NODE_CYCLE = "list-node-cycle"
CODEC_LIST_NODE_LIST = "list-node-list"
CODEC_LIST_NODE_REF = "list-node-ref"
# A list-node-ref result is an index among the nodes built for one of these arg codecs.
LIST_HEAD_CODECS = (CODEC_LIST_NODE, CODEC_LIST_NODE_CYCLE)

# LeetCode's node classes, rendered above the stub when a codec needs them.
LIST_NODE_SOURCE = ("class ListNode:\n    def __init__(self, val=0, next=None):\n"
                    "        self.val = val\n        self.next = next\n\n\n")
TREE_NODE_SOURCE = ("class TreeNode:\n    def __init__(self, val=0, left=None, right=None):\n"
                    "        self.val = val\n        self.left = left\n"
                    "        self.right = right\n\n\n")
RANDOM_NODE_SOURCE = ("class Node:\n"
                      "    def __init__(self, x: int, next: 'Node' = None, "
                      "random: 'Node' = None):\n"
                      "        self.val = int(x)\n        self.next = next\n"
                      "        self.random = random\n\n\n")
GRAPH_NODE_SOURCE = ("class Node:\n    def __init__(self, val=0, neighbors=None):\n"
                     "        self.val = val\n"
                     "        self.neighbors = neighbors if neighbors is not None else []\n"
                     "\n\n")
CODEC_PREAMBLES = {
    "list-node": LIST_NODE_SOURCE,
    CODEC_LIST_NODE_CYCLE: LIST_NODE_SOURCE,
    CODEC_LIST_NODE_LIST: LIST_NODE_SOURCE,
    CODEC_TREE_NODE: TREE_NODE_SOURCE,
    CODEC_TREE_VALUE: TREE_NODE_SOURCE,
    "random-list": RANDOM_NODE_SOURCE,
    "graph-node": GRAPH_NODE_SOURCE,
}
CODEC_NUMBER_INF = "number-inf"  # result-only; needs no node class, so no preamble
# list-node-ref is result-only too; the list arg it indexes already brings ListNode.
RESULT_ONLY_CODECS = frozenset({CODEC_NUMBER_INF, CODEC_LIST_NODE_REF})
CODECS = frozenset(CODEC_PREAMBLES) | RESULT_ONLY_CODECS
ARG_ONLY_CODECS = frozenset({CODEC_LIST_NODE_CYCLE, CODEC_LIST_NODE_LIST})

# Names a case's `judge` may bind (the API LeetCode's judge provides). The values live in the
# checker's and the site driver's `JUDGE_APIS`; only the names are checked here.
JUDGE_NAMES = frozenset({"isBadVersion"})
ANY_OF_KEY = "anyOf"

# `name(params) -> ret` as written in an ops spec's `methods` list.
_METHOD_LINE = re.compile(r"^(\w+)\((.*)\)\s*(?:->\s*(.+))?$")

COMPARE_MODES = frozenset({"exact", "unordered", "unordered-nested", "unordered-inner"})
FIGURE_KINDS = frozenset({"graph", "grid"})
EDGE_SOURCE_KEYS = ("edgesArg", "matrixArg", "adjArg")  # exactly one per graph figure
FIGURE_HIGHLIGHT = "expected"
FIGURE_EDGES_EXPECTED = "expected"
REQUIRED_SPEC_KEYS = ("number", "title", "url", "entry", "compare", "cases")

_FILENAME_NUMBER = re.compile(r"^(\d+)_")


class PracticeError(Exception):
    """A fatal spec/contract problem. Never caught silently — see the module docstring's
    NOT FAIL-SOFT constraint."""


# ── pure helpers (no filesystem access) ─────────────────────────────────────────────

def split_method_line(line: str) -> tuple[str, str] | None:
    """`get(key: int) -> int` → `("get", "key: int -> int")`, the form
    `new_problem.parse_signature` takes; None when the line is not `name(params)[ -> ret]`."""
    match = _METHOD_LINE.match(line.strip())
    if not match:
        return None
    name, params, ret = match.groups()
    return name, f"{params} -> {ret}" if ret else params


def _method_source(name: str, signature: str) -> str:
    params, ret = new_problem.parse_signature(signature)
    ret_suffix = f" {ret}" if ret else ""
    return f"    def {name}({params}){ret_suffix}:\n        pass\n"


def _node_preambles(types: dict | None) -> str:
    """The node classes the codecs in `types` need, each class once, in first-use order."""
    if not types:
        return ""
    codecs = [*types.get("args", []), types.get("result")]
    by_class_line: dict[str, str] = {}
    for codec in codecs:
        source = CODEC_PREAMBLES.get(codec)
        if source is not None:
            by_class_line.setdefault(source.split(":", 1)[0], source)
    return "".join(by_class_line.values())


def render_stub(class_name: str, method: str, signature: str | None = None, *,
                types: dict | None = None, kind: str = KIND_METHOD,
                methods: tuple[str, ...] = (), decode: str | None = None,
                decode_signature: str | None = None) -> str:
    """The blank starting code: `STUB_PREAMBLE`, any node classes `types` needs, then the
    class with one `pass` method per entry point. Signatures are parsed by
    `new_problem.parse_signature` (`self` implied). `kind` `ops` renders one method per
    `methods` line; `round-trip` renders `method` (encode) and `decode`."""
    head = f"{STUB_PREAMBLE}{_node_preambles(types)}class {class_name}:\n"
    if kind == KIND_OPS:
        parts = [split_method_line(line) for line in methods]
        return head + "".join(_method_source(name, sig) for name, sig in parts)
    body = _method_source(method, signature or "")
    if kind == KIND_ROUND_TRIP:
        body += _method_source(decode or "", decode_signature or "")
    return head + body


def _filename_number(filename: str) -> int | None:
    match = _FILENAME_NUMBER.match(filename)
    return int(match.group(1)) if match else None


def entry_kind(entry: dict) -> str:
    """The entry's kind; `method` when the spec sets none."""
    return entry.get("kind", KIND_METHOD)


def _require_text(mapping: dict, key: str, label: str, filename: str) -> None:
    if not isinstance(mapping.get(key), str) or not mapping[key].strip():
        raise PracticeError(f"{filename}: {label} must be a non-empty string")


def _validate_entry(entry: object, filename: str) -> None:
    if not isinstance(entry, dict):
        raise PracticeError(f"{filename}: 'entry' must be a mapping")
    if "kind" in entry and entry["kind"] not in ENTRY_KINDS:
        raise PracticeError(
            f"{filename}: entry.kind {entry['kind']!r} is not one of {sorted(ENTRY_KINDS)}")
    if "class" not in entry:
        raise PracticeError(f"{filename}: entry is missing 'class'")
    _require_text(entry, "class", "entry.class", filename)
    kind = entry_kind(entry)
    if kind == KIND_METHOD or "method" in entry:
        if "method" not in entry:
            raise PracticeError(f"{filename}: entry is missing 'method'")
        _require_text(entry, "method", "entry.method", filename)
    if kind == KIND_ROUND_TRIP:
        for key in ("encode", "decode"):
            if key not in entry:
                raise PracticeError(f"{filename}: round-trip entry is missing '{key}'")
            _require_text(entry, key, f"entry.{key}", filename)


def _validate_signatures(spec: dict, filename: str) -> None:
    """`signature` is required for method and round-trip, `decodeSignature` for round-trip,
    and `methods` (parsable `name(params) -> ret` lines) for ops."""
    kind = entry_kind(spec["entry"])
    if kind == KIND_OPS:
        methods = spec.get("methods")
        if not isinstance(methods, list) or not methods:
            raise PracticeError(f"{filename}: an ops spec needs a non-empty 'methods' list")
        for line in methods:
            if not isinstance(line, str) or split_method_line(line) is None:
                raise PracticeError(
                    f"{filename}: methods entry {line!r} is not 'name(params) -> ret'")
        return
    if not isinstance(spec.get("signature"), str):
        raise PracticeError(f"{filename}: missing required key 'signature'")
    if kind == KIND_ROUND_TRIP and not isinstance(spec.get("decodeSignature"), str):
        raise PracticeError(f"{filename}: a round-trip spec needs 'decodeSignature'")


def _validate_op_case(case: dict, index: int, class_name: str, filename: str) -> None:
    ops = case.get("ops")
    if not isinstance(ops, list) or not ops or not all(isinstance(op, str) for op in ops):
        raise PracticeError(f"{filename}: case {index} 'ops' must be a list of names")
    if ops[0] != class_name:
        raise PracticeError(
            f"{filename}: case {index} ops[0] {ops[0]!r} must be the class {class_name!r}")
    if len(case["args"]) != len(ops):
        raise PracticeError(f"{filename}: case {index} 'ops' and 'args' differ in length")
    if not isinstance(case["expected"], list) or len(case["expected"]) != len(ops):
        raise PracticeError(
            f"{filename}: case {index} 'expected' must be a list as long as 'ops'")


def _validate_expected(expected: object, label: str, filename: str) -> None:
    """A mapping with an `anyOf` key must have that as its only key, holding a non-empty
    list. Any other value is plain JSON and is left alone."""
    if not isinstance(expected, dict) or ANY_OF_KEY not in expected:
        return
    alternatives = expected[ANY_OF_KEY]
    if len(expected) != 1 or not isinstance(alternatives, list) or not alternatives:
        raise PracticeError(
            f"{filename}: {label} 'expected' with {ANY_OF_KEY} must be a mapping whose only "
            f"key is {ANY_OF_KEY}, holding a non-empty list")


def _validate_judge(judge: object, index: int, filename: str) -> None:
    if not isinstance(judge, dict):
        raise PracticeError(f"{filename}: case {index} 'judge' must be a mapping")
    for name, value in judge.items():
        if name not in JUDGE_NAMES:
            raise PracticeError(
                f"{filename}: case {index} judge {name!r} is not one of {sorted(JUDGE_NAMES)}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise PracticeError(f"{filename}: case {index} judge.{name} must be an integer")


def _validate_cases(cases: object, filename: str, entry: dict) -> None:
    if not isinstance(cases, list) or not cases:
        raise PracticeError(f"{filename}: 'cases' must be a non-empty list")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise PracticeError(f"{filename}: case {index} must be a mapping")
        if not isinstance(case.get("args"), list):
            raise PracticeError(f"{filename}: case {index} 'args' must be a list")
        if "expected" not in case:
            raise PracticeError(f"{filename}: case {index} has no 'expected'")
        if "judge" in case:
            _validate_judge(case["judge"], index, filename)
        if entry_kind(entry) == KIND_OPS:
            _validate_op_case(case, index, entry["class"], filename)
            for position, expected in enumerate(case["expected"]):
                _validate_expected(expected, f"case {index} op {position}", filename)
        else:
            _validate_expected(case["expected"], f"case {index}", filename)
    if not any(case.get("example") is True for case in cases):
        raise PracticeError(f"{filename}: no case has 'example: true'")


def _result_index(result: object, filename: str) -> tuple[str, int] | None:
    """`(kind, index)` for a `{arg: i}` / `{argPrefix: i}` result, None for `return`/absent."""
    if result is None or result == RESULT_RETURN:
        return None
    if not isinstance(result, dict) or len(result) != 1 \
            or next(iter(result)) not in RESULT_SPEC_KEYS:
        raise PracticeError(
            f"{filename}: result must be 'return', {{arg: i}} or {{argPrefix: i}}")
    spec_key, index = next(iter(result.items()))
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise PracticeError(f"{filename}: result.{spec_key} must be an integer >= 0")
    return RESULT_SPEC_KEYS[spec_key], index


def _validate_result(spec: dict, filename: str) -> None:
    picked = _result_index(spec.get("result"), filename)
    if picked is None:
        return
    _, index = picked
    for case_number, case in enumerate(spec["cases"]):
        if index >= len(case["args"]):
            raise PracticeError(
                f"{filename}: result index {index} is beyond case {case_number}'s args")


def _parameter_count(signature: str) -> int:
    """Parameters in `signature`, split at top-level commas (`self` not counted). The text
    itself is still parsed only by `new_problem.parse_signature`."""
    params, _ = new_problem.parse_signature(signature)
    depth, count, has_text = 0, 0, False
    for char in params:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        if char == "," and depth == 0:
            count += has_text
            has_text = False
        elif not char.isspace():
            has_text = True
    return count + has_text - 1  # minus the implied `self`


CONSTRUCTOR_NAME = "__init__"


def _typed_parameter_count(spec: dict) -> int:
    """How many codecs `types.args` must have: the signature's parameters, or for an ops
    spec the constructor's (0 when `methods` lists no `__init__`)."""
    if entry_kind(spec["entry"]) != KIND_OPS:
        return _parameter_count(spec["signature"])
    for line in spec["methods"]:
        name, signature = split_method_line(line)
        if name == CONSTRUCTOR_NAME:
            return _parameter_count(signature)
    return 0


def _validate_types(spec: dict, filename: str) -> None:
    """Validate the optional `types`; absent is valid. Needs the signatures validated."""
    if "types" not in spec:
        return
    types = spec["types"]
    if not isinstance(types, dict) or not isinstance(types.get("args"), list):
        raise PracticeError(f"{filename}: 'types' must be a mapping with an 'args' list")
    result_codec = types.get("result")
    for codec in [*types["args"], result_codec]:
        if codec is not None and codec not in CODECS:
            raise PracticeError(f"{filename}: codec {codec!r} is not one of {sorted(CODECS)}")
    if result_codec in ARG_ONLY_CODECS:
        raise PracticeError(f"{filename}: {result_codec} cannot be a result codec")
    for codec in RESULT_ONLY_CODECS & set(types["args"]):
        raise PracticeError(f"{filename}: {codec} can only be a result codec")
    if result_codec == CODEC_LIST_NODE_REF \
            and not any(codec in LIST_HEAD_CODECS for codec in types["args"]):
        raise PracticeError(
            f"{filename}: a {CODEC_LIST_NODE_REF} result needs a {CODEC_LIST_NODE} or "
            f"{CODEC_LIST_NODE_CYCLE} arg")
    if CODEC_TREE_VALUE in types["args"] and CODEC_TREE_NODE not in types["args"]:
        raise PracticeError(
            f"{filename}: a {CODEC_TREE_VALUE} arg needs a {CODEC_TREE_NODE} arg")
    expected_count = _typed_parameter_count(spec)
    if len(types["args"]) != expected_count:
        raise PracticeError(
            f"{filename}: types.args has {len(types['args'])} codecs but the "
            f"{'constructor' if entry_kind(spec['entry']) == KIND_OPS else 'signature'} "
            f"has {expected_count} parameters")


def _validate_figure_index(figure: dict, key: str, spec: dict, filename: str) -> None:
    """`figure[key]` must be an int (never a bool) that indexes every example case's args."""
    index = figure[key]
    if isinstance(index, bool) or not isinstance(index, int):
        raise PracticeError(f"{filename}: figure.{key} must be an integer")
    if index < 0:
        raise PracticeError(f"{filename}: figure.{key} must not be negative")
    for case_number, case in enumerate(spec["cases"]):
        if case.get("example") is True and index >= len(case["args"]):
            raise PracticeError(
                f"{filename}: figure.{key} {index} is beyond case {case_number}'s args")


def _validate_figure(spec: dict, filename: str) -> None:
    """Validate the optional `figure`; absent is valid. Needs `cases` already validated."""
    if "figure" not in spec:
        return
    if not spec.get("statement"):
        raise PracticeError(
            f"{filename}: a figure needs a statement — the practice page draws a figure "
            f"only on its statement branch")
    figure = spec["figure"]
    if not isinstance(figure, dict):
        raise PracticeError(f"{filename}: 'figure' must be a mapping")
    kind = figure.get("kind")
    if kind not in FIGURE_KINDS:
        raise PracticeError(
            f"{filename}: figure.kind {kind!r} is not one of {sorted(FIGURE_KINDS)}")
    if kind == "grid":
        if "gridArg" not in figure:
            raise PracticeError(f"{filename}: figure is missing 'gridArg'")
        _validate_figure_index(figure, "gridArg", spec, filename)
        return
    _validate_graph_figure(figure, spec, filename)


def _validate_graph_figure(figure: dict, spec: dict, filename: str) -> None:
    """Rules for a graph figure: one edge source, and the keys that go with it."""
    sources = [key for key in EDGE_SOURCE_KEYS if key in figure]
    if len(sources) != 1:
        raise PracticeError(
            f"{filename}: figure needs exactly one of {list(EDGE_SOURCE_KEYS)}, "
            f"got {sources}")
    source = sources[0]
    for key in ("directed", "oneBased"):
        if key in figure and not isinstance(figure[key], bool):
            raise PracticeError(f"{filename}: figure.{key} must be a boolean")
    if "oneBased" in figure and source != "adjArg":
        raise PracticeError(f"{filename}: figure.oneBased needs adjArg")
    if source == "matrixArg" and figure.get("directed") is True:
        raise PracticeError(f"{filename}: figure.matrixArg cannot be directed")
    for key in ("nodesArg", "nodeCountArg"):
        if key in figure and source != "edgesArg":
            raise PracticeError(f"{filename}: figure.{key} needs edgesArg")
    if "nodesArg" in figure and "nodeCountArg" in figure:
        raise PracticeError(
            f"{filename}: figure.nodesArg and figure.nodeCountArg are exclusive")
    if "highlight" in figure and figure["highlight"] != FIGURE_HIGHLIGHT:
        raise PracticeError(
            f"{filename}: figure.highlight must be {FIGURE_HIGHLIGHT!r}")
    _validate_figure_edges(figure, source, filename)
    for key in (source, "nodesArg", "nodeCountArg"):
        if key in figure:
            _validate_figure_index(figure, key, spec, filename)


def _validate_figure_edges(figure: dict, source: str, filename: str) -> None:
    """Rules for `figure.edges`: only 'expected', only on a matrix figure, never with highlight."""
    if "edges" not in figure:
        return
    if figure["edges"] != FIGURE_EDGES_EXPECTED:
        raise PracticeError(
            f"{filename}: figure.edges must be {FIGURE_EDGES_EXPECTED!r}")
    if source != "matrixArg":
        raise PracticeError(f"{filename}: figure.edges needs matrixArg")
    if "highlight" in figure:
        raise PracticeError(
            f"{filename}: figure.edges and figure.highlight are exclusive")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_figure_cell_pair(pair: object, grid: object, label: str, filename: str) -> None:
    """One `[row, column]` pair: two ints, inside `grid`."""
    if not isinstance(pair, list) or len(pair) != 2 or not all(_is_int(n) for n in pair):
        raise PracticeError(f"{filename}: {label} must be a [row, column] pair of integers")
    row, column = pair
    if not (isinstance(grid, list) and 0 <= row < len(grid)
            and isinstance(grid[row], list) and 0 <= column < len(grid[row])):
        raise PracticeError(f"{filename}: {label} {pair} is outside the grid")


def _validate_figure_cells(spec: dict, filename: str) -> None:
    """A case's optional `figureCells`: example cases of a grid figure only, a non-empty list
    of distinct in-bounds `[row, column]` pairs. Needs `figure` already validated."""
    figure = spec.get("figure")
    for index, case in enumerate(spec["cases"]):
        if "figureCells" not in case:
            continue
        label = f"case {index} figureCells"
        if case.get("example") is not True:
            raise PracticeError(f"{filename}: {label} needs 'example: true'")
        if not isinstance(figure, dict) or figure.get("kind") != "grid":
            raise PracticeError(f"{filename}: {label} needs a grid figure")
        cells = case["figureCells"]
        if not isinstance(cells, list) or not cells:
            raise PracticeError(f"{filename}: {label} must be a non-empty list")
        grid = case["args"][figure["gridArg"]]
        for position, pair in enumerate(cells):
            _validate_figure_cell_pair(pair, grid, f"{label}[{position}]", filename)
        if len({tuple(pair) for pair in cells}) != len(cells):
            raise PracticeError(f"{filename}: {label} repeats a cell")


def _validate_statement_lines(statement: object, filename: str) -> None:
    """No indented statement line may exceed `MAX_VERBATIM_LINE` characters."""
    for line_number, line in enumerate(str(statement).splitlines(), start=1):
        if line[:1].isspace() and len(line) > MAX_VERBATIM_LINE:
            raise PracticeError(
                f"{filename}: statement line {line_number} is indented and {len(line)} "
                f"characters long (max {MAX_VERBATIM_LINE})")


def validate_spec(spec: object, filename: str) -> None:
    """Raise `PracticeError` naming `filename` on the first way `spec` is unusable."""
    if not isinstance(spec, dict):
        raise PracticeError(f"{filename}: spec must be a mapping")
    for key in REQUIRED_SPEC_KEYS:
        if key not in spec:
            raise PracticeError(f"{filename}: missing required key '{key}'")
    if spec["number"] != _filename_number(filename):
        raise PracticeError(
            f"{filename}: number {spec['number']!r} does not match the filename's "
            f"leading number")
    if spec.get("statement") is not None:
        _validate_statement_lines(spec["statement"], filename)
    _validate_entry(spec["entry"], filename)
    _validate_signatures(spec, filename)
    if spec["compare"] not in COMPARE_MODES:
        raise PracticeError(
            f"{filename}: compare {spec['compare']!r} is not one of "
            f"{sorted(COMPARE_MODES)}")
    _validate_cases(spec["cases"], filename, spec["entry"])
    _validate_figure(spec, filename)
    _validate_figure_cells(spec, filename)
    _validate_result(spec, filename)
    _validate_types(spec, filename)


def build_figure(figure: dict | None) -> dict | None:
    """The emitted `figure` from a validated spec's figure, or None when it has none."""
    if figure is None:
        return None
    if figure["kind"] == "grid":
        return {"kind": "grid", "gridArg": figure["gridArg"]}
    return _with_highlight(_build_graph_figure(figure), figure)


def _build_graph_figure(figure: dict) -> dict:
    """The graph figure's shape-specific keys, in the order existing figures use."""
    if "matrixArg" in figure:
        emitted = {"kind": "graph", "directed": False, "matrixArg": figure["matrixArg"]}
        if "edges" in figure:
            return {**emitted, "edges": figure["edges"]}
        return emitted
    directed = figure.get("directed", False)
    if "adjArg" in figure:
        return {"kind": "graph", "directed": directed, "adjArg": figure["adjArg"],
                "oneBased": figure.get("oneBased", False)}
    emitted = {"kind": "graph", "directed": directed, "edgesArg": figure["edgesArg"],
               "nodeCountArg": figure.get("nodeCountArg")}
    if "nodesArg" in figure:
        return {**emitted, "nodesArg": figure["nodesArg"]}
    return emitted


def _with_highlight(emitted: dict, figure: dict) -> dict:
    """`emitted` plus the spec's `highlight`, when it has one."""
    if "highlight" in figure:
        return {**emitted, "highlight": figure["highlight"]}
    return emitted


def build_result(result: object) -> dict | None:
    """The emitted `result` from a validated spec's result, or None when it sets none."""
    if result is None:
        return None
    if result == RESULT_RETURN:
        return {"kind": RESULT_RETURN}
    spec_key, index = next(iter(result.items()))
    return {"kind": RESULT_SPEC_KEYS[spec_key], "index": index}


def build_types(types: dict | None) -> dict | None:
    """The emitted `types` from a validated spec's types, or None when it sets none."""
    if types is None:
        return None
    return {"args": list(types["args"]), "result": types.get("result")}


def build_entry(entry: dict) -> dict:
    """The emitted `entry`; `kind`, `encode` and `decode` only when the spec sets them."""
    built = {"className": entry["class"], "method": entry.get("method", "")}
    for spec_key in ("kind", "encode", "decode"):
        if spec_key in entry:
            built[spec_key] = entry[spec_key]
    return built


def build_case(case: dict) -> dict:
    built = {"args": case["args"], "expected": case["expected"],
             "example": case.get("example") is True}
    if "ops" in case:
        built = {"ops": case["ops"], **built}
    if "judge" in case:
        built = {**built, "judge": case["judge"]}
    if "figureCells" in case:
        built = {**built, "figureCells": case["figureCells"]}
    return built


def build_problem(spec: dict) -> dict:
    """One `problems` entry from a validated spec. Optional fields are left out, never
    emitted as null, when the spec does not set them."""
    entry = spec["entry"]
    kind = entry_kind(entry)
    statement = spec.get("statement")
    types = build_types(spec.get("types"))
    problem = {
        "number": spec["number"],
        "title": spec["title"],
        "url": spec["url"],
        "statement": None if statement is None else str(statement).rstrip("\n"),
        "stub": render_stub(
            entry["class"], entry.get("encode", entry.get("method", "")),
            spec.get("signature"), types=types, kind=kind,
            methods=tuple(spec.get("methods", ())), decode=entry.get("decode"),
            decode_signature=spec.get("decodeSignature")),
        "entry": build_entry(entry),
        "compare": spec["compare"],
        "figure": build_figure(spec.get("figure")),
        "cases": [build_case(case) for case in spec["cases"]],
    }
    if kind == KIND_ROUND_TRIP:
        problem["signature"] = spec["signature"]
        problem["decodeSignature"] = spec["decodeSignature"]
    for key, value in (("result", build_result(spec.get("result"))), ("types", types)):
        if value is not None:
            problem[key] = value
    return problem


def build_payload(named_specs: list[tuple[str, object]], today: dt.date) -> dict:
    """The practice.json payload from `(filename, spec)` pairs. Validates every spec and
    refuses a number two specs share."""
    seen: dict[int, str] = {}
    problems = []
    for filename, spec in named_specs:
        validate_spec(spec, filename)
        number = spec["number"]
        if number in seen:
            raise PracticeError(
                f"{filename}: number {number} is already used by {seen[number]}")
        seen[number] = filename
        problems.append(build_problem(spec))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": today.isoformat(),
        "problems": sorted(problems, key=lambda p: p["number"]),
    }


def _without_date(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "generatedAt"}


def stale_reasons(payload: dict, existing: object) -> list[str]:
    """Every way the parsed on-disk practice.json differs from `payload`, ignoring
    `generatedAt`. Empty when it is current."""
    if not isinstance(existing, dict) or not isinstance(existing.get("problems"), list):
        return ["practice.json: top level must be an object with a 'problems' list"]
    if _without_date(existing) == _without_date(payload):
        return []
    new_by_number = {p["number"]: p for p in payload["problems"]}
    old_by_number = {p.get("number"): p for p in existing["problems"]
                     if isinstance(p, dict)}
    reasons = []
    added = sorted(new_by_number.keys() - old_by_number.keys())
    removed = sorted(old_by_number.keys() - new_by_number.keys(), key=str)
    if added or removed:
        reasons.append(f"problem set changed — added {added}, removed {removed}")
    for number in sorted(new_by_number.keys() & old_by_number.keys()):
        if new_by_number[number] != old_by_number[number]:
            reasons.append(f"{number}: differs from the committed practice.json — "
                           f"regenerate")
    return reasons or ["practice.json: differs from the specs — regenerate"]


# ── filesystem access ────────────────────────────────────────────────────────────────

def load_specs(spec_dir: Path) -> list[tuple[str, object]]:
    """`(filename, parsed YAML)` for every `*.yml` in `spec_dir`, sorted by filename."""
    import yaml  # noqa: PLC0415 — only this loader needs PyYAML

    named_specs = []
    for path in sorted(spec_dir.glob("*.yml")):
        try:
            named_specs.append((path.name, yaml.safe_load(path.read_text(encoding="utf-8"))))
        except (OSError, yaml.YAMLError) as exc:
            raise PracticeError(f"{path.name}: cannot read spec: {exc}") from exc
    return named_specs


def read_existing(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"cannot read existing {path}: {exc}"


# ── CLI ───────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stdout", action="store_true", help="print the JSON, do not write")
    ap.add_argument("--check", action="store_true",
                     help="build in memory, validate, never write; exit 1 on any failure")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                     help="override generatedAt (default: today)")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    try:
        payload = build_payload(load_specs(SPEC_DIR), today)
    except PracticeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    count = len(payload["problems"])
    if args.check:
        contract_schema.check(payload, SCHEMA)
        if OUT.exists():
            existing = read_existing(OUT)
            reasons = ([existing] if isinstance(existing, str)
                       else stale_reasons(payload, existing))
            if reasons:
                print("ERROR: dashboard/practice.json is stale:", file=sys.stderr)
                for reason in reasons:
                    print(f"  - {reason}", file=sys.stderr)
                sys.exit(1)
        # Like practice.json itself: nothing on disk to drift from when there is no source.
        derived = dashboard_indexes.build_practice_files(payload)
        dashboard_indexes.exit_on_schema_errors(derived)
        index_reasons = [] if not OUT.exists() else dashboard_indexes.stale_reasons(
            DASHBOARD, derived)
        if index_reasons:
            print("ERROR: dashboard/practice-index.json is stale:", file=sys.stderr)
            for reason in index_reasons:
                print(f"  - {reason}", file=sys.stderr)
            sys.exit(1)
        print(f"ok: {count} practice problems verified", file=sys.stderr)
        return

    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.stdout:
        print(rendered)
        return

    if not count:
        print("no practice specs in dsa/tests: nothing written")
        return
    contract_schema.check(payload, SCHEMA)
    derived = dashboard_indexes.build_practice_files(payload)
    dashboard_indexes.exit_on_schema_errors(derived)
    DASHBOARD.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered + "\n", encoding="utf-8")
    dashboard_indexes.write_files(DASHBOARD, derived)
    print(f"wrote {OUT.relative_to(REPO)} ({count} problems)")


if __name__ == "__main__":
    main()
