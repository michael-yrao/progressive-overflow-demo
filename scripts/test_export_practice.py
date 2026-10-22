"""Tests for export_practice.py — the practice-runner contract generator.

Stdlib unittest, same style as test_showcase.py. Run it with:

    python scripts/test_export_practice.py
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import contract_schema
import export_practice as ep

TODAY = dt.date(2026, 10, 1)
FILENAME = "90_subsets_ii.yml"

VALID_SPEC = {
    "number": 90,
    "title": "Subsets II",
    "url": "https://leetcode.com/problems/subsets-ii/",
    "statement": "Return the power set.\n",
    "entry": {"class": "Solution", "method": "subsetsWithDup"},
    "signature": "nums: List[int] -> List[List[int]]",
    "compare": "unordered-nested",
    "cases": [
        {"args": [[1, 2, 2]], "expected": [[], [1]], "example": True},
        {"args": [[0]], "expected": [[], [0]]},
    ],
}


def _variant(base: dict, **overrides) -> dict:
    """`base` with `overrides` applied; a value of `...` deletes the key."""
    spec = copy.deepcopy(base)
    for key, value in overrides.items():
        if value is ...:
            del spec[key]
        else:
            spec[key] = value
    return spec


def _spec(**overrides) -> dict:
    return _variant(VALID_SPEC, **overrides)


OPS_SPEC = {
    "number": 146,
    "title": "LRU Cache",
    "url": "https://leetcode.com/problems/lru-cache/",
    "entry": {"class": "LRUCache", "kind": "ops"},
    "methods": ["__init__(capacity: int)", "get(key: int) -> int",
                "put(key: int, value: int) -> None"],
    "compare": "exact",
    "cases": [{"ops": ["LRUCache", "put", "get"], "args": [[1], [1, 1], [1]],
               "expected": [None, None, 1], "example": True}],
}
OPS_FILENAME = "146_lru_cache.yml"

ROUND_TRIP_SPEC = {
    "number": 297,
    "title": "Serialize and Deserialize Binary Tree",
    "url": "https://leetcode.com/problems/serialize-and-deserialize-binary-tree/",
    "entry": {"class": "Codec", "kind": "round-trip", "encode": "serialize",
              "decode": "deserialize"},
    "signature": "root: TreeNode -> str",
    "decodeSignature": "data: str -> TreeNode",
    "types": {"args": ["tree-node"], "result": "tree-node"},
    "compare": "exact",
    "cases": [{"args": [[1, 2, 3]], "expected": [1, 2, 3], "example": True}],
}
ROUND_TRIP_FILENAME = "297_serialize_and_deserialize_binary_tree.yml"


def _ops_entry(**entry) -> dict:
    return {"class": "LRUCache", "kind": "ops", **entry}


def _ops_case(**overrides) -> list:
    case = {"ops": ["LRUCache", "get"], "args": [[1], [1]], "expected": [None, 1],
            "example": True}
    return [{**case, **overrides}]


class ContractShapeValidationTests(unittest.TestCase):
    def test_every_new_rejection_raises_and_each_new_shape_is_accepted(self):
        reject = [
            ("unknown codec", FILENAME, _spec(types={"args": ["linked-list"]})),
            ("codec count differs from the signature", FILENAME,
             _spec(types={"args": [None, None]})),
            ("tree-value without a tree-node arg", FILENAME,
             _spec(types={"args": ["tree-value"]})),
            ("list-node-cycle as the result codec", FILENAME,
             _spec(types={"args": [None], "result": "list-node-cycle"})),
            ("result.arg beyond a case's args", FILENAME, _spec(result={"arg": 1})),
            ("result neither return nor arg", FILENAME, _spec(result="sideways")),
            ("ops without methods", OPS_FILENAME, _variant(OPS_SPEC, methods=...)),
            ("ops case whose ops[0] is not the class", OPS_FILENAME,
             _variant(OPS_SPEC, cases=_ops_case(ops=["Cache", "get"]))),
            ("ops case with ops/args length mismatch", OPS_FILENAME,
             _variant(OPS_SPEC, cases=_ops_case(args=[[1]]))),
            ("round-trip without decodeSignature", ROUND_TRIP_FILENAME,
             _variant(ROUND_TRIP_SPEC, decodeSignature=...)),
            ("entry.kind unknown", OPS_FILENAME,
             _variant(OPS_SPEC, entry=_ops_entry(kind="stream"))),
        ]
        for label, filename, spec in reject:
            with self.subTest(label):
                with self.assertRaises(ep.PracticeError) as ctx:
                    ep.build_payload([(filename, spec)], TODAY)
                self.assertIn(filename, str(ctx.exception))

        accept = [
            ("result.arg", FILENAME, _spec(result={"arg": 0})),
            ("result.argPrefix", FILENAME, _spec(result={"argPrefix": 0})),
            ("result return", FILENAME, _spec(result="return")),
            ("types with every node codec", FILENAME,
             _spec(types={"args": ["list-node-cycle"], "result": "random-list"})),
            ("ops", OPS_FILENAME, OPS_SPEC),
            ("round-trip", ROUND_TRIP_FILENAME, ROUND_TRIP_SPEC),
        ]
        for label, filename, spec in accept:
            with self.subTest(label):
                ep.build_payload([(filename, spec)], TODAY)


class NumberInfCodecTests(unittest.TestCase):
    def test_number_inf_is_a_result_codec_only(self):
        rows = [
            ("as the result codec", _spec(types={"args": [None], "result": "number-inf"}), True),
            ("as an arg codec", _spec(types={"args": ["number-inf"]}), False),
        ]
        for label, spec, is_accepted in rows:
            with self.subTest(label):
                if is_accepted:
                    ep.build_payload([(FILENAME, spec)], TODAY)
                else:
                    with self.assertRaises(ep.PracticeError):
                        ep.build_payload([(FILENAME, spec)], TODAY)


def _anyof_cases(expected) -> list:
    return [{"args": [[1, 2, 2]], "expected": expected, "example": True}]


class ContractExtensionTests(unittest.TestCase):
    def test_each_extension_accepts_its_shape_and_rejects_its_misuse(self):
        rows = [
            ("list-node-list as an arg codec",
             _spec(types={"args": ["list-node-list"], "result": "list-node"}), True),
            ("list-node-list as the result codec",
             _spec(types={"args": [None], "result": "list-node-list"}), False),
            ("list-node-ref as the result codec",
             _spec(types={"args": ["list-node-cycle"], "result": "list-node-ref"}), True),
            ("list-node-ref as an arg codec",
             _spec(types={"args": ["list-node-ref"]}), False),
            ("list-node-ref result with no list-node arg",
             _spec(types={"args": [None], "result": "list-node-ref"}), False),
            ("anyOf with one key and a non-empty list",
             _spec(cases=_anyof_cases({"anyOf": [[1], [2]]})), True),
            ("anyOf with another key beside it",
             _spec(cases=_anyof_cases({"anyOf": [[1]], "extra": 1})), False),
            ("anyOf with an empty list", _spec(cases=_anyof_cases({"anyOf": []})), False),
            ("anyOf inside an ops expected list",
             _variant(OPS_SPEC, cases=_ops_case(expected=[None, {"anyOf": [1, 2]}])), True),
            ("ops types.args matching the constructor's one parameter",
             _variant(OPS_SPEC, types={"args": ["list-node"]}), True),
            ("ops types.args longer than the constructor's parameters",
             _variant(OPS_SPEC, types={"args": ["list-node", None]}), False),
            ("judge with a known name",
             _spec(cases=[{"args": [[1]], "expected": [], "example": True,
                           "judge": {"isBadVersion": 4}}]), True),
            ("judge with an unknown name",
             _spec(cases=[{"args": [[1]], "expected": [], "example": True,
                           "judge": {"isGoodVersion": 4}}]), False),
        ]
        for label, spec, is_accepted in rows:
            with self.subTest(label):
                filename = OPS_FILENAME if spec["entry"].get("kind") == "ops" else FILENAME
                if is_accepted:
                    ep.build_payload([(filename, spec)], TODAY)
                else:
                    with self.assertRaises(ep.PracticeError):
                        ep.build_payload([(filename, spec)], TODAY)


GRID = [["A", "B"], ["C", "D"]]
GRID_FIGURE = {"kind": "grid", "gridArg": 0}
GRAPH_FIGURE = {"kind": "graph", "adjArg": 0}


def _figure_cells_spec(cells, *, is_example=True, figure=GRID_FIGURE) -> dict:
    case = {"args": [GRID], "expected": True, "figureCells": cells}
    if is_example:
        case["example"] = True
    return _spec(figure=figure, cases=[case, {"args": [GRID], "expected": True,
                                              "example": True}])


class FigureCellsTests(unittest.TestCase):
    def test_figure_cells_are_emitted_when_valid_and_rejected_otherwise(self):
        rows = [
            ("valid cells", _figure_cells_spec([[0, 0], [1, 1]]), True),
            ("on a non-example case", _figure_cells_spec([[0, 0]], is_example=False), False),
            ("on a graph figure", _figure_cells_spec([[0, 0]], figure=GRAPH_FIGURE), False),
            ("row out of bounds", _figure_cells_spec([[2, 0]]), False),
            ("column out of bounds", _figure_cells_spec([[0, 2]]), False),
            ("a repeated cell", _figure_cells_spec([[0, 0], [0, 0]]), False),
            ("a pair of length 3", _figure_cells_spec([[0, 0, 0]]), False),
            ("a non-int pair", _figure_cells_spec([[0, "1"]]), False),
        ]
        for label, spec, is_accepted in rows:
            with self.subTest(label):
                if not is_accepted:
                    with self.assertRaises(ep.PracticeError):
                        ep.build_payload([(FILENAME, spec)], TODAY)
                    continue
                payload = ep.build_payload([(FILENAME, spec)], TODAY)
                cases = payload["problems"][0]["cases"]
                self.assertEqual(cases[0]["figureCells"], [[0, 0], [1, 1]])
                self.assertNotIn("figureCells", cases[1])


class ValidationTests(unittest.TestCase):
    def test_every_validation_error_raises_and_a_valid_spec_passes(self):
        rows = [
            ("missing required key", FILENAME, _spec(url=...)),
            ("number differs from filename", "91_subsets_ii.yml", _spec()),
            ("entry.method missing", FILENAME, _spec(entry={"class": "Solution"})),
            ("entry.method empty", FILENAME,
             _spec(entry={"class": "Solution", "method": "  "})),
            ("compare not a known mode", FILENAME, _spec(compare="sorted")),
            ("cases empty", FILENAME, _spec(cases=[])),
            ("case args not a list", FILENAME,
             _spec(cases=[{"args": "x", "expected": 1, "example": True}])),
            ("case with no expected", FILENAME,
             _spec(cases=[{"args": [1], "example": True}])),
            ("no example case", FILENAME,
             _spec(cases=[{"args": [1], "expected": 1}])),
            ("figure.kind unknown", FILENAME,
             _spec(figure={"kind": "tree", "edgesArg": 0})),
            ("figure arg index not an integer", FILENAME,
             _spec(figure={"kind": "graph", "edgesArg": "0"})),
            ("figure arg index beyond an example case's args", FILENAME,
             _spec(figure={"kind": "grid", "gridArg": 1})),
            ("figure with no edge source", FILENAME,
             _spec(figure={"kind": "graph"})),
            ("figure with two edge sources", FILENAME,
             _spec(figure={"kind": "graph", "edgesArg": 0, "matrixArg": 0})),
            ("figure matrixArg with directed true", FILENAME,
             _spec(figure={"kind": "graph", "matrixArg": 0, "directed": True})),
            ("figure oneBased not a boolean", FILENAME,
             _spec(figure={"kind": "graph", "adjArg": 0, "oneBased": "yes"})),
            ("figure oneBased without adjArg", FILENAME,
             _spec(figure={"kind": "graph", "edgesArg": 0, "oneBased": True})),
            ("figure nodesArg without edgesArg", FILENAME,
             _spec(figure={"kind": "graph", "matrixArg": 0, "nodesArg": 0})),
            ("figure nodeCountArg without edgesArg", FILENAME,
             _spec(figure={"kind": "graph", "adjArg": 0, "nodeCountArg": 0})),
            ("figure nodesArg with nodeCountArg", FILENAME,
             _spec(figure={"kind": "graph", "edgesArg": 0, "nodesArg": 0, "nodeCountArg": 0})),
            ("figure highlight not 'expected'", FILENAME,
             _spec(figure={"kind": "graph", "edgesArg": 0, "highlight": "input"})),
            ("figure edges not 'expected'", FILENAME,
             _spec(figure={"kind": "graph", "matrixArg": 0, "edges": "input"})),
            ("figure edges on an edgesArg figure", FILENAME,
             _spec(figure={"kind": "graph", "edgesArg": 0, "edges": "expected"})),
            ("figure edges together with highlight", FILENAME,
             _spec(figure={"kind": "graph", "matrixArg": 0, "edges": "expected",
                           "highlight": "expected"})),
            ("figure matrixArg beyond an example case's args", FILENAME,
             _spec(figure={"kind": "graph", "matrixArg": 1})),
            ("figure with no statement", FILENAME,
             _spec(statement=..., figure={"kind": "grid", "gridArg": 0})),
            ("indented statement line of 65 characters", FILENAME,
             _spec(statement="Return it.\n" + " " * 4 + "x" * 61 + "\n")),
        ]
        for label, filename, spec in rows:
            with self.subTest(label):
                with self.assertRaises(ep.PracticeError) as ctx:
                    ep.build_payload([(filename, spec)], TODAY)
                self.assertIn(filename, str(ctx.exception))

        with self.subTest("duplicate number across specs"):
            with self.assertRaises(ep.PracticeError):
                ep.build_payload(
                    [(FILENAME, _spec()), ("90_other_title.yml", _spec())], TODAY)

        with self.subTest("valid spec passes"):
            payload = ep.build_payload([(FILENAME, _spec())], TODAY)
            self.assertEqual([p["number"] for p in payload["problems"]], [90])
            self.assertEqual([c["example"] for c in payload["problems"][0]["cases"]],
                             [True, False])
            self.assertIsNone(payload["problems"][0]["figure"])

        with self.subTest("unindented 120-character line is accepted"):
            long_prose = "Return it. " + "word " * 22
            ep.build_payload([(FILENAME, _spec(statement=long_prose.strip()[:120] + "\n"))],
                             TODAY)


class BuildFigureTests(unittest.TestCase):
    def test_emitted_figure_per_shape(self):
        rows = [
            ("edges only", {"kind": "graph", "edgesArg": 0},
             {"kind": "graph", "directed": False, "edgesArg": 0, "nodeCountArg": None}),
            ("edges with nodesArg", {"kind": "graph", "directed": True, "edgesArg": 1,
                                     "nodesArg": 0},
             {"kind": "graph", "directed": True, "edgesArg": 1, "nodeCountArg": None,
              "nodesArg": 0}),
            ("matrix with highlight",
             {"kind": "graph", "matrixArg": 0, "highlight": "expected"},
             {"kind": "graph", "directed": False, "matrixArg": 0,
              "highlight": "expected"}),
            ("matrix with edges",
             {"kind": "graph", "matrixArg": 0, "edges": "expected"},
             {"kind": "graph", "directed": False, "matrixArg": 0, "edges": "expected"}),
            ("adjacency one-based", {"kind": "graph", "adjArg": 0, "oneBased": True},
             {"kind": "graph", "directed": False, "adjArg": 0, "oneBased": True}),
        ]
        for label, figure, expected in rows:
            with self.subTest(label):
                self.assertEqual(ep.build_figure(figure), expected)

        with self.subTest("edges-only key order is unchanged"):
            result = ep.build_figure({"kind": "graph", "edgesArg": 0})
            self.assertEqual(list(result),
                             ["kind", "directed", "edgesArg", "nodeCountArg"])


class RenderStubTests(unittest.TestCase):
    def test_single_and_multi_argument_signatures(self):
        preamble = "from typing import List, Optional\n\n\n"
        rows = [
            ("single arg, no return", "n: int",
             preamble + "class Solution:\n    def isHappy(self, n: int):\n        pass\n"),
            ("multi arg with return", "n: int, edges: List[List[int]] -> List[str]",
             preamble + "class Solution:\n"
             "    def isHappy(self, n: int, edges: List[List[int]]) -> List[str]:\n"
             "        pass\n"),
        ]
        for label, signature, expected in rows:
            with self.subTest(label):
                self.assertEqual(ep.render_stub("Solution", "isHappy", signature), expected)


class RenderStubShapeTests(unittest.TestCase):
    def test_node_preambles_ops_and_round_trip_stubs(self):
        preamble = "from typing import List, Optional\n\n\n"
        list_node = ("class ListNode:\n    def __init__(self, val=0, next=None):\n"
                     "        self.val = val\n        self.next = next\n\n\n")
        tree_node = ("class TreeNode:\n"
                     "    def __init__(self, val=0, left=None, right=None):\n"
                     "        self.val = val\n        self.left = left\n"
                     "        self.right = right\n\n\n")
        random_node = ("class Node:\n    def __init__(self, x: int, next: 'Node' = None, "
                       "random: 'Node' = None):\n        self.val = int(x)\n"
                       "        self.next = next\n        self.random = random\n\n\n")
        graph_node = ("class Node:\n    def __init__(self, val=0, neighbors=None):\n"
                      "        self.val = val\n"
                      "        self.neighbors = neighbors if neighbors is not None else []\n"
                      "\n\n")
        solution = "class Solution:\n    def f(self, a):\n        pass\n"
        node_rows = [
            ("list-node", "list-node", list_node),
            ("list-node-cycle", "list-node-cycle", list_node),
            ("list-node-list", "list-node-list", list_node),
            ("tree-node", "tree-node", tree_node),
            ("random-list", "random-list", random_node),
            ("graph-node", "graph-node", graph_node),
        ]
        for label, codec, node_source in node_rows:
            with self.subTest(label):
                stub = ep.render_stub("Solution", "f", "a", types={"args": [codec]})
                self.assertEqual(stub, preamble + node_source + solution)

        with self.subTest("tree-node and tree-value share one TreeNode class"):
            stub = ep.render_stub("Solution", "f", "a, b",
                                  types={"args": ["tree-node", "tree-value"]})
            self.assertEqual(stub.count("class TreeNode"), 1)

        with self.subTest("ops"):
            stub = ep.render_stub(
                "LRUCache", "", None, kind="ops",
                methods=("__init__(capacity: int)", "get(key: int) -> int"))
            self.assertEqual(
                stub,
                preamble + "class LRUCache:\n"
                "    def __init__(self, capacity: int):\n        pass\n"
                "    def get(self, key: int) -> int:\n        pass\n")

        with self.subTest("round-trip"):
            stub = ep.render_stub("Codec", "encode", "x: int -> str", kind="round-trip",
                                  decode="decode", decode_signature="s: str -> int")
            self.assertEqual(
                stub,
                preamble + "class Codec:\n"
                "    def encode(self, x: int) -> str:\n        pass\n"
                "    def decode(self, s: str) -> int:\n        pass\n")


class OptionalFieldTests(unittest.TestCase):
    def test_a_spec_without_statement_emits_null_and_no_optional_keys(self):
        problem = ep.build_payload([(FILENAME, _spec(statement=...))], TODAY)["problems"][0]
        self.assertIsNone(problem["statement"])
        for key in ("result", "types", "signature", "decodeSignature"):
            self.assertNotIn(key, problem)
        self.assertEqual(problem["entry"], {"className": "Solution",
                                            "method": "subsetsWithDup"})
        self.assertNotIn("ops", problem["cases"][0])


class StaleReasonsTests(unittest.TestCase):
    def setUp(self):
        self.payload = ep.build_payload([(FILENAME, _spec())], TODAY)

    def test_expected_drift_is_stale_and_generated_at_alone_is_not(self):
        changed_expected = copy.deepcopy(self.payload)
        changed_expected["problems"][0]["cases"][0]["expected"] = [[], [9]]
        changed_date = {**copy.deepcopy(self.payload), "generatedAt": "2026-01-01"}

        self.assertTrue(ep.stale_reasons(self.payload, changed_expected))
        self.assertEqual(ep.stale_reasons(self.payload, changed_date), [])


class ZeroSpecsWriteTests(unittest.TestCase):
    def test_no_specs_writes_nothing_and_exits_clean(self):
        # No existing table covers main(); this is one minimal case beside them.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specs").mkdir()
            dashboard = root / "dashboard"
            with mock.patch.object(ep, "SPEC_DIR", root / "specs"), \
                    mock.patch.object(ep, "DASHBOARD", dashboard), \
                    mock.patch.object(ep, "OUT", dashboard / "practice.json"), \
                    mock.patch.object(sys, "argv", ["export_practice.py"]):
                ep.main()  # returns normally: exit 0

            self.assertFalse(dashboard.exists())


class SchemaValidationTests(unittest.TestCase):
    def test_payload_against_schema(self):
        valid = ep.build_payload([(FILENAME, _spec())], TODAY)
        missing_field = {k: v for k, v in copy.deepcopy(valid).items() if k != "problems"}
        wrong_type = {**copy.deepcopy(valid), "schemaVersion": "1"}
        rows = [("required field removed", missing_field, True),
                ("field of the wrong type", wrong_type, True),
                ("unchanged", valid, False)]
        for name, payload, should_fail in rows:
            with self.subTest(name):
                errors = contract_schema.validate(payload, ep.SCHEMA)
                self.assertEqual(bool(errors), should_fail, errors[:3])


class FigureSchemaTests(unittest.TestCase):
    """The figure oneOf mirrors the site guard: one edge source, `directed` required."""

    def _validate_figure(self, figure: dict) -> list[str]:
        problem = {"number": 1, "title": "T", "url": "u", "statement": None, "stub": "s",
                   "entry": {"className": "Solution", "method": "m"}, "compare": "exact",
                   "figure": figure,
                   "cases": [{"args": [], "expected": 0, "example": True}]}
        payload = {"schemaVersion": 1, "generatedAt": "2026-10-06", "problems": [problem]}
        return contract_schema.validate(payload, ep.SCHEMA)

    def test_graph_figure_shapes(self):
        graph = {"kind": "graph", "directed": True}
        rows = [
            ("edgesArg + nodeCountArg null + nodesArg",
             {**graph, "edgesArg": 1, "nodeCountArg": None, "nodesArg": 0}, True),
            ("adjArg + oneBased", {**graph, "adjArg": 0, "oneBased": True}, True),
            ("matrixArg undirected", {"kind": "graph", "directed": False, "matrixArg": 0}, True),
            ("matrixArg directed", {**graph, "matrixArg": 0}, False),
            ("matrixArg with edges",
             {"kind": "graph", "directed": False, "matrixArg": 0, "edges": "expected"}, True),
            ("matrixArg with edges and highlight",
             {"kind": "graph", "directed": False, "matrixArg": 0, "edges": "expected",
              "highlight": "expected"}, False),
            ("edgesArg and matrixArg", {"kind": "graph", "directed": False,
                                        "edgesArg": 0, "matrixArg": 1}, False),
            ("nodeCountArg with adjArg", {**graph, "adjArg": 0, "nodeCountArg": 1}, False),
            ("no directed", {"kind": "graph", "edgesArg": 0}, False),
        ]
        for name, figure, is_valid in rows:
            with self.subTest(name):
                self.assertEqual(self._validate_figure(figure) == [], is_valid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
