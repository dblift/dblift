"""Older sqlglot releases store ``False`` for an absent ``WHERE``; it means "no predicate"."""

import pytest
from sqlglot import exp, parse_one

import dblift.core.sql_parser.sqlglot_statement_facts as facts_module
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.db import dml_analysis


def _with_false_where(sql, read=None, **kwargs):
    ast = parse_one(sql, read=read, **kwargs)
    for node in ast.find_all(exp.Insert, exp.Update, exp.Delete):
        if node.args.get("where") is None:
            node.args["where"] = False
    return ast


@pytest.mark.parametrize("dialect", ["duckdb", "sqlite", "mysql", "oracle"])
def test_insert_with_false_where_has_no_predicate(monkeypatch, dialect):
    monkeypatch.setattr(facts_module, "parse_one", _with_false_where)
    facts = read_statement_facts("INSERT INTO t (x) VALUES (1)", dialect=dialect)
    assert facts.operation == "INSERT"
    assert facts.kind == "DML"
    assert facts.diagnostic is None
    assert facts.predicate is None


@pytest.mark.parametrize("sql", ["UPDATE t SET a = 1", "DELETE FROM t"])
def test_dml_where_reader_treats_false_where_as_absent(monkeypatch, sql):
    import sqlglot

    monkeypatch.setattr(sqlglot, "parse_one", _with_false_where)
    assert dml_analysis.dml_where_predicate(sql, sqlglot_dialect="postgres") is None
