"""Tests for ETL helper utilities."""

import pytest
from etl.helpers import _escape, _q, _prop_str, Registry, ProgressReporter


class TestEscape:
    def test_plain_string(self):
        assert _escape("hello") == "hello"

    def test_single_quote(self):
        assert _escape("it's") == "it\\'s"

    def test_double_quote(self):
        assert _escape('say "hi"') == 'say \\"hi\\"'

    def test_backslash(self):
        assert _escape("a\\b") == "a\\\\b"

    def test_non_string(self):
        assert _escape(42) == "42"

    def test_combined(self):
        assert _escape("it's a \"test\" with \\n") == "it\\'s a \\\"test\\\" with \\\\n"

    def test_empty(self):
        assert _escape("") == ""


class TestQ:
    def test_string(self):
        assert _q("hello") == "'hello'"

    def test_int(self):
        assert _q(42) == "42"

    def test_float(self):
        assert _q(3.14) == "3.14"

    def test_bool_true(self):
        assert _q(True) == "true"

    def test_bool_false(self):
        assert _q(False) == "false"

    def test_none(self):
        assert _q(None) == "null"

    def test_string_with_quote(self):
        assert _q("it's") == "'it\\'s'"


class TestPropStr:
    def test_empty(self):
        assert _prop_str({}) == "{}"

    def test_single(self):
        result = _prop_str({"name": "Alice"})
        assert result == "{name: 'Alice'}"

    def test_multiple(self):
        result = _prop_str({"name": "Alice", "age": 30})
        assert "name: 'Alice'" in result
        assert "age: 30" in result

    def test_skip_none(self):
        result = _prop_str({"name": "Alice", "age": None})
        assert "age" not in result
        assert "name: 'Alice'" in result

    def test_bool_prop(self):
        result = _prop_str({"active": True})
        assert result == "{active: true}"

    def test_float_prop(self):
        result = _prop_str({"score": 0.95})
        assert result == "{score: 0.95}"


class TestRegistry:
    def test_empty_registry(self):
        reg = Registry()
        assert len(reg.pathways) == 0
        assert len(reg.proteins) == 0
        assert len(reg.go_terms) == 0

    def test_add_to_sets(self):
        reg = Registry()
        reg.pathways.add("R-HSA-109581")
        reg.proteins.add("P04637")
        assert "R-HSA-109581" in reg.pathways
        assert "P04637" in reg.proteins

    def test_dedup(self):
        reg = Registry()
        reg.proteins.add("P04637")
        reg.proteins.add("P04637")
        assert len(reg.proteins) == 1

    def test_edge_dedup(self):
        reg = Registry()
        key = "P04637|R-HSA-109581"
        reg.protein_pathways.add(key)
        assert key in reg.protein_pathways

    def test_all_sets_independent(self):
        reg = Registry()
        reg.pathways.add("X")
        reg.proteins.add("X")
        assert "X" in reg.pathways
        assert "X" in reg.proteins
        assert "X" not in reg.genes


class TestProgressReporter:
    def test_basic(self):
        pr = ProgressReporter("test", 100)
        assert pr.phase == "test"
        assert pr.total == 100
        assert pr.count == 0

    def test_tick(self):
        pr = ProgressReporter("test")
        pr.tick(10)
        assert pr.count == 10

    def test_error(self):
        pr = ProgressReporter("test")
        pr.error()
        pr.error()
        assert pr.errors == 2

    def test_summary(self):
        pr = ProgressReporter("test", 100)
        pr.tick(50)
        pr.error()
        s = pr.summary()
        assert s["phase"] == "test"
        assert s["processed"] == 50
        assert s["errors"] == 1
        assert s["elapsed_s"] >= 0
        assert s["rate"] >= 0
