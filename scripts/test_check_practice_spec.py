"""Tests for check_practice_spec.py — runs a solution against a practice spec.

Stdlib unittest. Run it with:

    python scripts/test_check_practice_spec.py
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import check_practice_spec as cps

SPEC_NUMBER = 7
SPEC_FILENAME = f"{SPEC_NUMBER}_fixture.yml"


def _spec(signature: str, cases: list, compare: str = "exact", **extra) -> dict:
    """A method-kind spec; `extra` adds or replaces top-level keys."""
    return {
        "number": SPEC_NUMBER, "title": "Fixture", "url": "https://example.test/",
        "entry": {"class": "Solution", "method": "f"}, "signature": signature,
        "compare": compare, "cases": cases, **extra,
    }


def _case(args: list, expected, example: bool = False) -> dict:
    return {"args": args, "expected": expected, "example": example}


def _run(spec: dict, source: str, method: str | None = None) -> list[tuple[bool, str]]:
    """Write the fixture pair to a temp dir and return the checker's report lines."""
    with tempfile.TemporaryDirectory() as directory:
        spec_path, solution_path = Path(directory) / SPEC_FILENAME, Path(directory) / "s.py"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")  # JSON is valid YAML
        solution_path.write_text(source, encoding="utf-8")
        return cps.report_lines(cps.load_problem(spec_path, solution_path), method)


PLAIN = _spec("n: int -> bool", [_case([3], True, True), _case([4], False)])
PLAIN_SOURCE = "class Solution:\n    def f(self, n):\n        return n % 2 == 1\n"

LIST_NODE_SOURCE = """
class Solution:
    def f(self, head):
        previous = None
        while head:
            head.next, previous, head = previous, head, head.next
        return previous
"""

CYCLE_SOURCE = """
class Solution:
    def f(self, head):
        seen = set()
        while head:
            if id(head) in seen:
                return True
            seen.add(id(head))
            head = head.next
        return False
"""

RANDOM_SOURCE = """
class Solution:
    def f(self, head):
        copies, node = {None: None}, head
        while node:
            copies[node] = Node(node.val)
            node = node.next
        node = head
        while node:
            copies[node].next = copies[node.next]
            copies[node].random = copies[node.random]
            node = node.next
        return copies[head]
"""

INVERT_SOURCE = """
class Solution:
    def f(self, root):
        if root:
            root.left, root.right = self.f(root.right), self.f(root.left)
        return root
"""

LCA_SOURCE = """
class Solution:
    def f(self, root, p, q):
        if root is None or root is p or root is q:
            return root
        left, right = self.f(root.left, p, q), self.f(root.right, p, q)
        return root if left and right else left or right
"""

CLONE_SOURCE = """
class Solution:
    def f(self, node):
        copies = {}
        def clone(original):
            if original not in copies:
                copies[original] = Node(original.val)
                copies[original].neighbors = [clone(n) for n in original.neighbors]
            return copies[original]
        return clone(node) if node else None
"""

DEDUPE_SOURCE = """
class Solution:
    def f(self, nums):
        kept = sorted(set(nums))
        nums[:len(kept)] = kept
        return len(kept)
"""

OPS_SOURCE = """
class Counter:
    def __init__(self, start):
        self.total = start
    def add(self, amount):
        self.total += amount
    def read(self):
        return self.total
"""

ROUND_TRIP_SOURCE = """
class Codec:
    def encode(self, values):
        return ",".join(map(str, values))
    def decode(self, text):
        return [int(part) for part in text.split(",")]
"""

OPS_SPEC = {
    **_spec("", [{"ops": ["Counter", "add", "read"], "args": [[1], [4], []],
                  "expected": [None, None, 5], "example": True}],
            entry={"class": "Counter", "kind": "ops"},
            methods=["__init__(start: int)", "add(amount: int) -> None", "read() -> int"]),
}
del OPS_SPEC["signature"]

ROUND_TRIP_SPEC = _spec(
    "values: List[int] -> str", [_case([[1, 2, 3]], [1, 2, 3], True)],
    entry={"class": "Codec", "kind": "round-trip", "encode": "encode", "decode": "decode"},
    decodeSignature="text: str -> List[int]")

TREE_LCA_SPEC = _spec(
    "root: TreeNode, p: int, q: int -> int",
    [_case([[3, 5, 1, 6, 2, 0, 8, None, None, 7, 4], 5, 1], 3, True)],
    types={"args": ["tree-node", "tree-value", "tree-value"], "result": "tree-value"})

MERGE_K_SOURCE = """
class Solution:
    def f(self, lists):
        values = sorted(node.val for head in lists for node in _chain(head))
        dummy = tail = ListNode()
        for value in values:
            tail.next = ListNode(value)
            tail = tail.next
        return dummy.next

def _chain(head):
    while head:
        yield head
        head = head.next
"""

DETECT_CYCLE_SOURCE = """
class Solution:
    def f(self, head):
        seen = set()
        while head:
            if id(head) in seen:
                return head
            seen.add(id(head))
            head = head.next
        return None
"""

FIRST_BAD_SOURCE = """
class Solution:
    def f(self, n):
        low, high = 1, n
        while low < high:
            middle = (low + high) // 2
            if isBadVersion(middle):
                high = middle
            else:
                low = middle + 1
        return low
"""

CRACK_SAFE_SOURCE = "class Solution:\n    def f(self, n, k):\n        return {answer!r}\n"

RANDOM_PICK_SOURCE = """
class Solution:
    def __init__(self, head):
        self.head = head
    def getRandom(self):
        return self.head.val
"""

RANDOM_PICK_SPEC = {
    **_spec("", [{"ops": ["Solution", "getRandom"], "args": [[[1, 2, 3]], []],
                  "expected": [None, {"anyOf": [1, 2, 3]}], "example": True}],
            entry={"class": "Solution", "kind": "ops"},
            methods=["__init__(head: Optional[ListNode])", "getRandom() -> int"],
            types={"args": ["list-node"], "result": None}),
}
del RANDOM_PICK_SPEC["signature"]

TREE_CODEC_SOURCE = """
class Codec:
    def serialize(self, root):
        if root is None:
            return "#"
        return ",".join([str(root.val), self.serialize(root.left), self.serialize(root.right)])

    def deserialize(self, data):
        tokens = iter(data.split(","))
        def build():
            token = next(tokens)
            if token == "#":
                return None
            node = TreeNode(int(token))
            node.left = build()
            {right_line}
            return node
        return build()
"""

TREE_CODEC_SPEC = _spec(
    "root: TreeNode -> str", [_case([[1, 2, 3, None, None, 4, 5]], [1, 2, 3, None, None, 4, 5], True)],
    entry={"class": "Codec", "kind": "round-trip", "encode": "serialize", "decode": "deserialize"},
    decodeSignature="data: str -> TreeNode", types={"args": ["tree-node"], "result": "tree-node"})

GRAPH = [[2, 4], [1, 3], [2, 4], [1, 3]]

ROWS = [
    ("plain pass", PLAIN, PLAIN_SOURCE, None, [(True, "PASS f (2/2)")]),
    ("plain fail reports the case",
     _spec("n: int -> bool", [_case([3], True, True), _case([4], False)]),
     "class Solution:\n    def f(self, n):\n        return True\n", None,
     [(False, "FAIL f (1/2): case 1 expected false got true")]),
    ("unordered", _spec("n: int -> List[int]", [_case([0], [1, 2], True)], "unordered"),
     "class Solution:\n    def f(self, n):\n        return [2, 1]\n", None,
     [(True, "PASS f (1/1)")]),
    ("unordered-nested",
     _spec("n: int -> List[List[int]]", [_case([0], [[1, 2], [3]], True)],
           "unordered-nested"),
     "class Solution:\n    def f(self, n):\n        return [[3], [2, 1]]\n", None,
     [(True, "PASS f (1/1)")]),
    ("unordered-inner passes reordered inner lists",
     _spec("n: int -> List[List[int]]", [_case([0], [[1, 2], [3]], True)], "unordered-inner"),
     "class Solution:\n    def f(self, n):\n        return [[2, 1], [3]]\n", None,
     [(True, "PASS f (1/1)")]),
    ("unordered-inner fails a swapped outer pair",
     _spec("n: int -> List[List[int]]", [_case([0], [[1, 2], [3]], True)], "unordered-inner"),
     "class Solution:\n    def f(self, n):\n        return [[3], [1, 2]]\n", None,
     [(False, "FAIL f (0/1): case 0 expected [[1, 2], [3]] got [[3], [1, 2]]")]),
    ("list-node",
     _spec("head: ListNode -> ListNode", [_case([[1, 2, 3]], [3, 2, 1], True),
                                          _case([[]], [])],
           types={"args": ["list-node"], "result": "list-node"}),
     LIST_NODE_SOURCE, None, [(True, "PASS f (2/2)")]),
    ("list-node-cycle",
     _spec("head: ListNode -> bool",
           [_case([[[3, 2, 0, -4], 1]], True, True), _case([[[1], -1]], False)],
           types={"args": ["list-node-cycle"], "result": None}),
     CYCLE_SOURCE, None, [(True, "PASS f (2/2)")]),
    ("random-list",
     _spec("head: Node -> Node",
           [_case([[[7, None], [13, 0], [11, 1]]], [[7, None], [13, 0], [11, 1]], True)],
           types={"args": ["random-list"], "result": "random-list"}),
     RANDOM_SOURCE, None, [(True, "PASS f (1/1)")]),
    ("tree-node",
     _spec("root: TreeNode -> TreeNode",
           [_case([[4, 2, 7, 1, 3, 6, 9]], [4, 7, 2, 9, 6, 3, 1], True)],
           types={"args": ["tree-node"], "result": "tree-node"}),
     INVERT_SOURCE, None, [(True, "PASS f (1/1)")]),
    ("tree-value", TREE_LCA_SPEC, LCA_SOURCE, None, [(True, "PASS f (1/1)")]),
    ("graph-node",
     _spec("node: Node -> Node", [_case([GRAPH], GRAPH, True), _case([[]], [])],
           types={"args": ["graph-node"], "result": "graph-node"}),
     CLONE_SOURCE, None, [(True, "PASS f (2/2)")]),
    ("result arg",
     _spec("nums: List[int] -> None", [_case([[3, 1, 2]], [1, 2, 3], True)],
           result={"arg": 0}),
     "class Solution:\n    def f(self, nums):\n        nums.sort()\n", None,
     [(True, "PASS f (1/1)")]),
    ("result arg-prefix",
     _spec("nums: List[int] -> int", [_case([[1, 1, 2]], [1, 2], True)],
           result={"argPrefix": 0}),
     DEDUPE_SOURCE, None, [(True, "PASS f (1/1)")]),
    ("ops", OPS_SPEC, OPS_SOURCE, None, [(True, "PASS Counter (1/1)")]),
    ("round-trip", ROUND_TRIP_SPEC, ROUND_TRIP_SOURCE, None,
     [(True, "PASS Codec (1/1)")]),
    ("list-node-list",
     _spec("lists: List[Optional[ListNode]] -> ListNode",
           [_case([[[1, 4, 5], [1, 3, 4], [2, 6]]], [1, 1, 2, 3, 4, 4, 5, 6], True)],
           types={"args": ["list-node-list"], "result": "list-node"}),
     MERGE_K_SOURCE, None, [(True, "PASS f (1/1)")]),
    ("list-node-ref: the cycle's entry node and no cycle",
     _spec("head: ListNode -> ListNode",
           [_case([[[3, 2, 0, -4], 1]], 1, True), _case([[[1, 2], -1]], None)],
           types={"args": ["list-node-cycle"], "result": "list-node-ref"}),
     DETECT_CYCLE_SOURCE, None, [(True, "PASS f (2/2)")]),
    ("judge binds isBadVersion for the case",
     _spec("n: int -> int", [{**_case([5], 4, True), "judge": {"isBadVersion": 4}}]),
     FIRST_BAD_SOURCE, None, [(True, "PASS f (1/1)")]),
    ("anyOf passes on one alternative",
     _spec("n: int, k: int -> str", [_case([1, 2], {"anyOf": ["01", "10"]}, True)]),
     CRACK_SAFE_SOURCE.format(answer="10"), None, [(True, "PASS f (1/1)")]),
    ("anyOf fails on none of them",
     _spec("n: int, k: int -> str", [_case([1, 2], {"anyOf": ["01", "10"]}, True)]),
     CRACK_SAFE_SOURCE.format(answer="00"), None,
     [(False, 'FAIL f (0/1): case 0 expected {"anyOf": ["01", "10"]} got "00"')]),
    ("ops constructor types and a per-op anyOf", RANDOM_PICK_SPEC, RANDOM_PICK_SOURCE, None,
     [(True, "PASS Solution (1/1)")]),
    ("round-trip with tree codecs passes", TREE_CODEC_SPEC,
     TREE_CODEC_SOURCE.format(right_line="node.right = build()"), None,
     [(True, "PASS Codec (1/1)")]),
    ("round-trip with tree codecs fails when a child is dropped", TREE_CODEC_SPEC,
     TREE_CODEC_SOURCE.format(right_line="build()"), None,
     [(False, "FAIL Codec (0/1): case 0 expected [1, 2, 3, null, null, 4, 5] got [1, 2]")]),
    ("dated method names are all picked up", PLAIN,
     "class Solution:\n"
     "    def f_20261001(self, n):\n        return n % 2 == 1\n"
     "    def f_20261002(self, n):\n        return True\n", None,
     [(True, "PASS f_20261001 (2/2)"),
      (False, "FAIL f_20261002 (1/2): case 1 expected false got true")]),
    ("a tuple result compares as the JSON array the site sees",
     _spec("n: int -> List[List[int]]", [_case([0], [[1, 2]], True)]),
     "class Solution:\n    def f(self, n):\n        return [(1, 2)]\n", None,
     [(True, "PASS f (1/1)")]),
    ("a module-level unittest.main() does not stop the load", PLAIN,
     "import unittest\n"
     "class Solution:\n    def f(self, n):\n        return n % 2 == 1\n"
     "unittest.main()\n", None,
     [(True, "PASS f (2/2)")]),
    ("--method picks one", PLAIN,
     "class Solution:\n"
     "    def f_a(self, n):\n        return n % 2 == 1\n"
     "    def f_b(self, n):\n        return True\n", "f_a",
     [(True, "PASS f_a (2/2)")]),
]


class CheckPracticeSpecTests(unittest.TestCase):
    def test_each_shape_passes_and_a_wrong_answer_names_its_case(self):
        for label, spec, source, method, expected in ROWS:
            with self.subTest(label):
                self.assertEqual(_run(spec, source, method), expected)


class DecodeNumberInfTests(unittest.TestCase):
    def test_infinities_become_the_sites_strings_and_everything_else_passes_through(self):
        original = [math.inf, [-math.inf, 3]]
        rows = [
            ("+inf", [math.inf], ["Infinity"]),
            ("-inf", [-math.inf], ["-Infinity"]),
            ("an int", [5, True], [5, True]),
            ("a nested list mixing them", [[math.inf, 2], -math.inf, [[-4]]],
             [["Infinity", 2], "-Infinity", [[-4]]]),
        ]
        for label, value, expected in rows:
            with self.subTest(label):
                self.assertEqual(cps.decode_value(value, "number-inf"), expected)
        with self.subTest("the input list is not mutated"):
            cps.decode_value(original, "number-inf")
            self.assertEqual(original, [math.inf, [-math.inf, 3]])
        with self.subTest("NaN passes through and never matches"):
            decoded = cps.decode_value([math.nan], "number-inf")
            self.assertFalse(cps.values_match(decoded, ["Infinity"], "exact"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
