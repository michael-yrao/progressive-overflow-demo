"""Run a Python solution file against a practice spec, with the site's semantics.

A spec's expected values are hand-written or computed offline; a wrong one marks a correct
solution as failing on the site. This runs every case the way the site's driver does (encode
the arguments by codec, call, pick the result by `result` kind, decode, compare under
`compare`) so a spec can be verified against a known-good solution before it ships.

The spec is loaded through `export_practice.validate_spec` / `build_problem`, so a spec's
meaning comes from one place.

Usage:
    python scripts/check_practice_spec.py dsa/tests/202_happy_number.yml \\
        dsa/leetcode/arrays_hash/202_happy_number.py [--method NAME]

Without `--method`, every method on the entry class whose name starts with the entry's
method name runs (the learner's files date attempts: `isHappy_20261001`). One line per
method; exit 1 if any fails.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import unittest
from collections import deque
from contextlib import contextmanager
from pathlib import Path

import _console
import export_practice as ep

_console.force_utf8()

MAX_SHOWN_CHARS = 80

# What a solution file may use without importing it: LeetCode's judge preloads these.
SEED_SOURCE = (
    "from typing import *\n\n\n"
    + ep.LIST_NODE_SOURCE
    + ep.TREE_NODE_SOURCE
    + "class Node:\n"
      "    def __init__(self, val=0, neighbors=None, next=None, random=None):\n"
      "        self.val = val\n"
      "        self.neighbors = neighbors if neighbors is not None else []\n"
      "        self.next = next\n"
      "        self.random = random\n"
)


# Judge APIs a case's `judge` may bind, by name. Kept verbatim in the site's python-driver.ts;
# the exporter keeps the names (`export_practice.JUDGE_NAMES`).
JUDGE_APIS = {"isBadVersion": lambda bad: (lambda version: version >= bad)}


class CheckError(Exception):
    """The spec or the solution file cannot be run at all (not a failing case)."""


# ── codecs ───────────────────────────────────────────────────────────────────────────

def _linked_nodes(values: list, node_class: type) -> list:
    nodes = [node_class(value) for value in values]
    for node, following in zip(nodes, nodes[1:]):
        node.next = following
    return nodes


def encode_list_node(values: list, ns: dict):
    nodes = _linked_nodes(values, ns["ListNode"])
    return nodes[0] if nodes else None


def encode_list_node_cycle(arg: list, ns: dict):
    values, position = arg
    nodes = _linked_nodes(values, ns["ListNode"])
    if nodes and position >= 0:
        nodes[-1].next = nodes[position]
    return nodes[0] if nodes else None


def encode_list_node_list(lists: list, ns: dict) -> list:
    return [encode_list_node(values, ns) for values in lists]


def encode_random_list(pairs: list, ns: dict):
    nodes = _linked_nodes([value for value, _ in pairs], ns["Node"])
    for node, (_, random_index) in zip(nodes, pairs):
        node.random = None if random_index is None else nodes[random_index]
    return nodes[0] if nodes else None


def encode_tree_node(values: list, ns: dict):
    if not values or values[0] is None:
        return None
    tree_class = ns["TreeNode"]
    root = tree_class(values[0])
    queue, cursor = deque([root]), 1
    while queue and cursor < len(values):
        node = queue.popleft()
        for side in ("left", "right"):
            if cursor < len(values) and values[cursor] is not None:
                child = tree_class(values[cursor])
                setattr(node, side, child)
                queue.append(child)
            cursor += 1
    return root


def encode_graph_node(adjacency: list, ns: dict):
    if not adjacency:
        return None
    nodes = [ns["Node"](number) for number in range(1, len(adjacency) + 1)]
    for node, neighbor_numbers in zip(nodes, adjacency):
        node.neighbors = [nodes[number - 1] for number in neighbor_numbers]
    return nodes[0]


def find_tree_value(root, value: int):
    """The node holding `value` in the tree under `root`, or None."""
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if node is None:
            continue
        if node.val == value:
            return node
        queue.extend((node.left, node.right))
    return None


ENCODERS = {
    "list-node": encode_list_node,
    "list-node-cycle": encode_list_node_cycle,
    "list-node-list": encode_list_node_list,
    "random-list": encode_random_list,
    "tree-node": encode_tree_node,
    "graph-node": encode_graph_node,
}


def encode_args(args: list, codecs: list, ns: dict) -> list:
    """The arguments the learner's method receives. `tree-value` args resolve against the
    first `tree-node` arg, so they are encoded last."""
    encoded = [None] * len(args)
    for index, arg in enumerate(args):
        codec = codecs[index] if index < len(codecs) else None
        if codec is None:
            encoded[index] = arg
        elif codec != ep.CODEC_TREE_VALUE:
            encoded[index] = ENCODERS[codec](arg, ns)
    for index, arg in enumerate(args):
        if index < len(codecs) and codecs[index] == ep.CODEC_TREE_VALUE:
            root = encoded[codecs.index(ep.CODEC_TREE_NODE)]
            encoded[index] = find_tree_value(root, arg)
    return encoded


def _walk_list(head) -> list:
    nodes, seen = [], set()
    while head is not None:
        if id(head) in seen:
            raise CheckError("the returned list has a cycle")
        seen.add(id(head))
        nodes.append(head)
        head = head.next
    return nodes


def decode_list_node(head) -> list:
    return [node.val for node in _walk_list(head)]


def decode_random_list(head) -> list:
    nodes = _walk_list(head)
    index_of = {id(node): index for index, node in enumerate(nodes)}
    return [[node.val, None if node.random is None else index_of.get(id(node.random))]
            for node in nodes]


def decode_tree_node(root) -> list:
    values, queue = [], deque([root])
    while queue:
        node = queue.popleft()
        values.append(None if node is None else node.val)
        if node is not None:
            queue.extend((node.left, node.right))
    while values and values[-1] is None:
        values.pop()
    return values


def decode_graph_node(start) -> list:
    """Adjacency list of every node reachable from `start`, in node-value order."""
    if start is None:
        return []
    reached, queue = {id(start): start}, deque([start])
    while queue:
        for neighbor in queue.popleft().neighbors:
            if id(neighbor) not in reached:
                reached[id(neighbor)] = neighbor
                queue.append(neighbor)
    ordered = sorted(reached.values(), key=lambda node: node.val)
    return [[neighbor.val for neighbor in node.neighbors] for node in ordered]


def decode_tree_value(node):
    return None if node is None else node.val


def decode_list_node_ref(returned, call_args: list, codecs: list):
    """The 0-based index of the returned node among the nodes reachable from the first
    `list-node` / `list-node-cycle` arg (identity; a seen set keeps a cycle finite). None
    stays None; a node outside that walk is a codec error, not a wrong answer."""
    if returned is None:
        return None
    head_index = next(index for index, codec in enumerate(codecs)
                      if codec in ep.LIST_HEAD_CODECS)
    nodes, seen, node = [], set(), call_args[head_index]
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        nodes.append(node)
        node = node.next
    for index, candidate in enumerate(nodes):
        if candidate is returned:
            return index
    raise CheckError("the returned node is not in the argument list")


def decode_number_inf(value):
    """The site's JSON form of a number result: +/-inf become "Infinity" / "-Infinity".
    Lists are rebuilt, never mutated; ints, bools and NaN pass through unchanged."""
    if isinstance(value, list):
        return [decode_number_inf(item) for item in value]
    if isinstance(value, float) and value in (math.inf, -math.inf):
        return "Infinity" if value > 0 else "-Infinity"
    return value


DECODERS = {
    "number-inf": decode_number_inf,
    "list-node": decode_list_node,
    "random-list": decode_random_list,
    "tree-node": decode_tree_node,
    "tree-value": decode_tree_value,
    "graph-node": decode_graph_node,
}


def decode_value(value, codec: str | None):
    return value if codec is None else DECODERS[codec](value)


# ── comparison ────────────────────────────────────────────────────────────────────────

def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _sorted_items(items) -> list:
    return sorted(items, key=_canonical)


def _as_json_value(value):
    """What the site sees: the result after a JSON round trip (a tuple becomes a list)."""
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError):
        return value


def _is_any_of(expected) -> bool:
    return isinstance(expected, dict) and set(expected) == {ep.ANY_OF_KEY}


def values_match(actual, expected, mode: str) -> bool:
    """`exact` is equality; `unordered` ignores the order of the top-level items;
    `unordered-nested` also ignores the order inside each inner list; `unordered-inner` ignores
    only the order inside each inner list and keeps the outer order fixed. The result is compared
    in its JSON form, as the site compares it. An `{anyOf: [...]}` expected matches when any
    alternative does; an expected list holding one (an ops case) compares element by element."""
    if _is_any_of(expected):
        return any(values_match(actual, alternative, mode)
                   for alternative in expected[ep.ANY_OF_KEY])
    actual = _as_json_value(actual)
    if isinstance(expected, list) and any(_is_any_of(item) for item in expected):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(values_match(got, want, mode) for got, want in zip(actual, expected)))
    if mode == "exact" or not isinstance(actual, list) or not isinstance(expected, list):
        return actual == expected
    if mode == "unordered":
        return _sorted_items(actual) == _sorted_items(expected)
    if mode == "unordered-inner":
        return _sort_inner(actual) == _sort_inner(expected)
    return _sorted_items(_sort_inner(actual)) == _sorted_items(_sort_inner(expected))


def _sort_inner(items: list) -> list:
    return [_sorted_items(item) if isinstance(item, list) else item for item in items]


# ── running ───────────────────────────────────────────────────────────────────────────

def load_solution(path: Path) -> dict:
    """Execute the solution file in a fresh namespace with the node classes seeded. A
    module-level `unittest.main()` (some learner files end in one) must not run the file's
    own tests, so it is a no-op while the file loads."""
    namespace: dict = {"__name__": "solution"}
    real_main = unittest.main
    unittest.main = lambda *args, **kwargs: None
    try:
        exec(compile(SEED_SOURCE, "<seed>", "exec"), namespace)
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    except Exception as exc:  # noqa: BLE001 — any failure in the learner's file is reported
        raise CheckError(f"{path.name}: cannot load: {type(exc).__name__}: {exc}") from exc
    finally:
        unittest.main = real_main
    return namespace


def pick_result(returned, call_args: list, result: dict | None, types: dict | None):
    """The value compared against `expected`, decoded by its codec."""
    arg_codecs = (types or {}).get("args", [])
    kind = (result or {"kind": ep.RESULT_RETURN})["kind"]
    if kind == ep.RESULT_RETURN:
        result_codec = (types or {}).get("result")
        if result_codec == ep.CODEC_LIST_NODE_REF:
            return decode_list_node_ref(returned, call_args, arg_codecs)
        return decode_value(returned, result_codec)
    index = result["index"]
    codec = arg_codecs[index] if index < len(arg_codecs) else None
    picked = decode_value(call_args[index], codec)
    return picked[:returned] if kind == ep.RESULT_ARG_PREFIX else picked


def run_method_case(instance, method: str, case: dict, problem: dict):
    codecs = (problem.get("types") or {}).get("args", [])
    call_args = encode_args(copy.deepcopy(case["args"]), codecs, problem["namespace"])
    returned = getattr(instance, method)(*call_args)
    return pick_result(returned, call_args, problem.get("result"), problem.get("types"))


def run_ops_case(case: dict, problem: dict) -> list:
    class_ = problem["namespace"][problem["entry"]["className"]]
    args = copy.deepcopy(case["args"])
    codecs = (problem.get("types") or {}).get("args", [])
    instance = class_(*encode_args(args[0], codecs, problem["namespace"]))
    outputs = [None]
    for op, op_args in zip(case["ops"][1:], args[1:]):
        outputs.append(getattr(instance, op)(*op_args))
    return outputs


def run_round_trip_case(case: dict, problem: dict):
    """Encode the args by `types.args`, call encode then decode, and pick the result the
    way a method case does (the site's `_invoke` + `_select_result`)."""
    entry = problem["entry"]
    types = problem.get("types")
    codecs = (types or {}).get("args", [])
    call_args = encode_args(copy.deepcopy(case["args"]), codecs, problem["namespace"])
    instance = problem["namespace"][entry["className"]]()
    returned = getattr(instance, entry["decode"])(
        getattr(instance, entry["encode"])(*call_args))
    return pick_result(returned, call_args, problem.get("result"), types)


@contextmanager
def bound_judge(namespace: dict, judge: dict | None):
    """Bind each `judge` API as a global in the namespace the solution runs in, for one
    case; afterwards the namespace is as it was, so no binding leaks into the next case."""
    missing = object()
    previous = {name: namespace.get(name, missing) for name in (judge or {})}
    for name, value in (judge or {}).items():
        namespace[name] = JUDGE_APIS[name](value)
    try:
        yield
    finally:
        for name, old in previous.items():
            if old is missing:
                namespace.pop(name, None)
            else:
                namespace[name] = old


def _shown(value) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= MAX_SHOWN_CHARS else text[:MAX_SHOWN_CHARS] + "..."


def check_cases(problem: dict, method: str | None) -> tuple[int, str | None]:
    """`(passed, first_failure)` over every case; `first_failure` is None when all pass."""
    kind = ep.entry_kind(problem["entry"])
    class_ = problem["namespace"].get(problem["entry"]["className"])
    if class_ is None:
        raise CheckError(f"the solution defines no class {problem['entry']['className']!r}")
    passed, first_failure = 0, None
    for index, case in enumerate(problem["cases"]):
        try:
            with bound_judge(problem["namespace"], case.get("judge")):
                if kind == ep.KIND_OPS:
                    actual = run_ops_case(case, problem)
                elif kind == ep.KIND_ROUND_TRIP:
                    actual = run_round_trip_case(case, problem)
                else:
                    actual = run_method_case(class_(), method, case, problem)
        except CheckError as exc:
            actual, error = None, str(exc)
        except Exception as exc:  # noqa: BLE001 — a learner exception is a failing case
            actual, error = None, f"raised {type(exc).__name__}: {exc}"
        else:
            error = None
        if error is None and values_match(actual, case["expected"], problem["compare"]):
            passed += 1
        elif first_failure is None:
            got = error if error else f"got {_shown(actual)}"
            first_failure = f"case {index} expected {_shown(case['expected'])} {got}"
    return passed, first_failure


def selected_methods(problem: dict, explicit: str | None) -> list[str]:
    """The method names to run: `explicit`, else every function on the entry class whose
    name starts with the entry's method name, in definition order."""
    kind = ep.entry_kind(problem["entry"])
    if kind != ep.KIND_METHOD:
        return [problem["entry"]["className"]]
    if explicit:
        return [explicit]
    class_ = problem["namespace"].get(problem["entry"]["className"])
    prefix = problem["entry"]["method"]
    names = [name for name, member in vars(class_ or object).items()
             if name.startswith(prefix) and callable(member)]
    if not names:
        raise CheckError(f"the class has no method starting with {prefix!r}")
    return names


def load_problem(spec_path: Path, solution_path: Path) -> dict:
    import yaml  # noqa: PLC0415 — only the loader needs PyYAML

    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        ep.validate_spec(spec, spec_path.name)
    except (OSError, yaml.YAMLError, ep.PracticeError) as exc:
        raise CheckError(str(exc)) from exc
    return {**ep.build_problem(spec), "namespace": load_solution(solution_path)}


def report_lines(problem: dict, explicit: str | None) -> list[tuple[bool, str]]:
    """`(is_passing, line)` per method."""
    total = len(problem["cases"])
    lines = []
    for method in selected_methods(problem, explicit):
        passed, failure = check_cases(problem, method)
        verdict = "PASS" if failure is None else "FAIL"
        suffix = "" if failure is None else f": {failure}"
        lines.append((failure is None, f"{verdict} {method} ({passed}/{total}){suffix}"))
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path)
    ap.add_argument("solution", type=Path)
    ap.add_argument("--method", metavar="NAME", help="run only this method")
    args = ap.parse_args()
    try:
        lines = report_lines(load_problem(args.spec, args.solution), args.method)
    except CheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    for _, line in lines:
        print(line)
    if not all(is_passing for is_passing, _ in lines):
        sys.exit(1)


if __name__ == "__main__":
    main()
